from __future__ import annotations

"""EPDB Rule-QC execution, background cycle worker and PostgreSQL snapshots.

The Streamlit dashboard never executes the full Rule Engine in its request thread.
A single in-process daemon worker runs QC when the configured interval is due or
when a user requests a run. PostgreSQL advisory locking prevents overlapping runs.
"""

import argparse
import json
import logging
import os
import re
import sys
import uuid
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, inspect as sqlalchemy_inspect, text

from epdb_qc_rules_150 import (
    RULES_150,
    QC_RULES_VERSION,
    build_checks as build_checks_150,
    execute_checks as execute_checks_150,
)

LOGGER = logging.getLogger("epdb_qc_scheduler")
RULES_VERSION = QC_RULES_VERSION
DEFAULT_DOCUMENT_ROOT = Path(os.getenv("EPDB_DOCUMENT_ROOT", r"C:\EPDB_DOCUMENTS")).expanduser()
QC_LOCK_KEY = 764_920_261_105

SUMMARY_COLUMNS = [
    "Mã luật", "Lĩnh vực", "Nhóm kiểm tra", "Mức độ", "Yêu cầu kiểm tra",
    "Nguồn đánh giá", "Chiều DQS", "Mẫu đánh giá", "Bản ghi / lượt vi phạm",
    "Đối tượng liên quan", "Kết quả", "Lỗi kỹ thuật",
]

WELL_SUMMARY_COLUMNS = [
    "Mã luật", "Lĩnh vực", "Nhóm kiểm tra", "Mức độ", "Yêu cầu kiểm tra",
    "Chiều DQS", "Mẫu đánh giá", "Bản ghi / lượt vi phạm", "Kết quả", "Lỗi kỹ thuật",
]


def normalize_column_name(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def ensure_unique_dataframe_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty and df.columns.is_unique:
        return df
    result = df.copy()
    used: set[str] = set()
    counts: dict[str, int] = {}
    unique_names: list[str] = []
    for raw_name in result.columns:
        name = str(raw_name)
        key = name.casefold()
        counts[key] = counts.get(key, 0) + 1
        candidate = name if counts[key] == 1 else f"{name} ({counts[key]})"
        while candidate.casefold() in used:
            counts[key] += 1
            candidate = f"{name} ({counts[key]})"
        used.add(candidate.casefold())
        unique_names.append(candidate)
    result.columns = unique_names
    return result


def ensure_qc_storage_tables(db_engine) -> None:
    """Create the append-only run history/snapshot table if it does not exist."""
    ddl = [
        """CREATE TABLE IF NOT EXISTS epdb_qc_cycle_runs (
            run_id TEXT PRIMARY KEY,
            started_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            completed_at TIMESTAMP WITHOUT TIME ZONE,
            status TEXT NOT NULL,
            rule_count INTEGER NOT NULL DEFAULT 0,
            issue_count BIGINT NOT NULL DEFAULT 0,
            failed_rule_count INTEGER NOT NULL DEFAULT 0,
            affected_entities_count BIGINT NOT NULL DEFAULT 0,
            rule_version TEXT NOT NULL,
            summary_json TEXT,
            details_json TEXT,
            failures_json TEXT,
            affected_entities_json TEXT,
            error_message TEXT
        )""",
        "ALTER TABLE epdb_qc_cycle_runs ADD COLUMN IF NOT EXISTS well_summary_ready BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE epdb_qc_cycle_runs ADD COLUMN IF NOT EXISTS well_summary_error_count INTEGER NOT NULL DEFAULT 0",
        "CREATE INDEX IF NOT EXISTS ix_epdb_qc_cycle_runs_completed ON epdb_qc_cycle_runs(status, completed_at DESC)",
        """CREATE TABLE IF NOT EXISTS epdb_qc_cycle_details (
            run_id TEXT NOT NULL REFERENCES epdb_qc_cycle_runs(run_id) ON DELETE CASCADE,
            rule_id TEXT NOT NULL,
            details_json TEXT NOT NULL,
            detail_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (run_id, rule_id)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_epdb_qc_cycle_details_run_rule ON epdb_qc_cycle_details(run_id, rule_id)",
        """CREATE TABLE IF NOT EXISTS epdb_qc_cycle_well_summary (
            run_id TEXT NOT NULL REFERENCES epdb_qc_cycle_runs(run_id) ON DELETE CASCADE,
            rule_id TEXT NOT NULL,
            uwi TEXT NOT NULL,
            ubhi TEXT NOT NULL DEFAULT '',
            domain TEXT,
            rule_name TEXT,
            severity TEXT,
            requirement TEXT,
            dimensions TEXT,
            population_count BIGINT NOT NULL DEFAULT 0,
            issue_count BIGINT NOT NULL DEFAULT 0,
            result TEXT NOT NULL,
            error_message TEXT,
            PRIMARY KEY (run_id, rule_id, uwi, ubhi)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_epdb_qc_well_summary_scope ON epdb_qc_cycle_well_summary(run_id, uwi, ubhi)",
        "CREATE INDEX IF NOT EXISTS ix_epdb_qc_well_summary_rule ON epdb_qc_cycle_well_summary(run_id, rule_id)",
    ]
    with db_engine.begin() as conn:
        for statement in ddl:
            conn.execute(text(statement))


def load_latest_qc_summary(db_engine):
    """Read only the latest summary payload; do not fetch violation details here."""
    row_df = pd.read_sql_query(
        text("""SELECT run_id, started_at, completed_at, status, rule_count,
                     issue_count, failed_rule_count, affected_entities_count,
                     rule_version, summary_json, failures_json,
                     affected_entities_json, error_message, well_summary_ready,
                     well_summary_error_count
              FROM epdb_qc_cycle_runs
              WHERE status='completed'
              ORDER BY completed_at DESC
              LIMIT 1"""),
        con=db_engine,
    )
    if row_df.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS), [], set(), None

    row = row_df.iloc[0].to_dict()
    try:
        summary = pd.DataFrame(json.loads(row.get("summary_json") or "[]"))
    except Exception as exc:
        LOGGER.exception("Cannot decode QC summary snapshot")
        summary = pd.DataFrame(columns=SUMMARY_COLUMNS)
        row["snapshot_decode_error"] = f"summary_json: {type(exc).__name__}: {exc}"

    for column in SUMMARY_COLUMNS:
        if column not in summary.columns:
            summary[column] = pd.Series(dtype="object")
    summary = summary.reindex(columns=SUMMARY_COLUMNS)

    try:
        failures = json.loads(row.get("failures_json") or "[]")
    except Exception:
        failures = ["Không đọc được danh sách lỗi kỹ thuật từ snapshot QC."]

    try:
        entities = set(json.loads(row.get("affected_entities_json") or "[]"))
    except Exception:
        entities = set()

    meta = {key: row.get(key) for key in (
        "run_id", "started_at", "completed_at", "status", "rule_count",
        "issue_count", "failed_rule_count", "affected_entities_count",
        "rule_version", "error_message", "snapshot_decode_error",
        "well_summary_ready", "well_summary_error_count",
    )}
    return summary, failures, entities, meta


def load_qc_well_summary(
    db_engine,
    run_id: str,
    uwi: str,
    ubhi: str | None = None,
) -> pd.DataFrame:
    """Read precomputed per-rule results for one well; never execute QC here."""
    if not run_id or not uwi:
        return pd.DataFrame(columns=WELL_SUMMARY_COLUMNS)

    params: dict[str, Any] = {"run_id": str(run_id), "uwi": str(uwi)}
    where = "run_id=:run_id AND uwi=:uwi"
    if ubhi:
        where += " AND (ubhi=:ubhi OR ubhi='')"
        params["ubhi"] = str(ubhi)

    rows = pd.read_sql_query(
        text(f"""SELECT rule_id, domain, rule_name, severity, requirement,
                         dimensions, population_count, issue_count, result, error_message
                  FROM epdb_qc_cycle_well_summary
                  WHERE {where}
                  ORDER BY domain, rule_id"""),
        con=db_engine,
        params=params,
    )
    if rows.empty:
        return pd.DataFrame(columns=WELL_SUMMARY_COLUMNS)

    # An unselected borehole means the whole well: aggregate borehole-level rows
    # and well-level rows by rule. A selected borehole includes only its rows plus
    # well-level checks (ubhi='').
    grouped_rows = []
    for rule_id, group in rows.groupby("rule_id", sort=False, dropna=False):
        first = group.iloc[0]
        population = int(pd.to_numeric(group["population_count"], errors="coerce").fillna(0).sum())
        issues = int(pd.to_numeric(group["issue_count"], errors="coerce").fillna(0).sum())
        statuses = set(group["result"].fillna("").astype(str))
        if issues > 0:
            result = "Có lỗi"
        elif "Chưa kiểm tra được" in statuses:
            result = "Chưa kiểm tra được"
        elif population > 0:
            result = "Đạt"
        else:
            result = "Chưa có dữ liệu"
        errors = [str(v).strip() for v in group["error_message"].dropna() if str(v).strip()]
        grouped_rows.append({
            "Mã luật": str(rule_id),
            "Lĩnh vực": first.get("domain"),
            "Nhóm kiểm tra": first.get("rule_name"),
            "Mức độ": first.get("severity"),
            "Yêu cầu kiểm tra": first.get("requirement"),
            "Chiều DQS": first.get("dimensions"),
            "Mẫu đánh giá": population,
            "Bản ghi / lượt vi phạm": issues,
            "Kết quả": result,
            "Lỗi kỹ thuật": "; ".join(dict.fromkeys(errors)),
        })
    result_df = pd.DataFrame(grouped_rows, columns=WELL_SUMMARY_COLUMNS)
    return result_df.sort_values(["Lĩnh vực", "Mã luật"], na_position="last").reset_index(drop=True)


def load_qc_rule_detail(db_engine, run_id: str, rule_id: str) -> pd.DataFrame:
    """Load one selected rule's details only; legacy snapshots are supported."""
    if not run_id or not rule_id:
        return pd.DataFrame()

    try:
        detail_df = pd.read_sql_query(
            text("""SELECT details_json FROM epdb_qc_cycle_details
                    WHERE run_id=:run_id AND rule_id=:rule_id LIMIT 1"""),
            con=db_engine,
            params={"run_id": str(run_id), "rule_id": str(rule_id)},
        )
        if not detail_df.empty:
            records = json.loads(detail_df.iloc[0]["details_json"] or "[]")
            return pd.DataFrame(records or [])
    except Exception:
        # Older installations may not yet have the normalized details table.
        LOGGER.exception("Cannot read normalized detail row for %s", rule_id)

    # Backward compatibility for snapshots created before epdb_qc_cycle_details existed.
    legacy = pd.read_sql_query(
        text("SELECT details_json FROM epdb_qc_cycle_runs WHERE run_id=:run_id LIMIT 1"),
        con=db_engine,
        params={"run_id": str(run_id)},
    )
    if legacy.empty:
        return pd.DataFrame()
    try:
        raw = json.loads(legacy.iloc[0]["details_json"] or "{}")
        return pd.DataFrame(raw.get(str(rule_id)) or [])
    except Exception:
        LOGGER.exception("Cannot decode legacy detail snapshot for %s", rule_id)
        return pd.DataFrame()


def load_latest_qc_snapshot(db_engine):
    """Compatibility loader returning all details; new dashboard code should use lazy loaders."""
    summary, failures, entities, meta = load_latest_qc_summary(db_engine)
    if not meta:
        return summary, {}, failures, entities, meta

    details: dict[str, pd.DataFrame] = {}
    try:
        normalized = pd.read_sql_query(
            text("""SELECT rule_id, details_json FROM epdb_qc_cycle_details
                    WHERE run_id=:run_id"""),
            con=db_engine,
            params={"run_id": meta["run_id"]},
        )
        for _, item in normalized.iterrows():
            details[str(item["rule_id"])] = pd.DataFrame(json.loads(item["details_json"] or "[]"))
    except Exception:
        LOGGER.exception("Cannot read normalized QC detail rows")

    # Fall back to the original JSON column for snapshots created by older versions.
    if not details:
        row_df = pd.read_sql_query(
            text("SELECT details_json FROM epdb_qc_cycle_runs WHERE run_id=:run_id LIMIT 1"),
            con=db_engine,
            params={"run_id": meta["run_id"]},
        )
        if not row_df.empty:
            try:
                raw = json.loads(row_df.iloc[0]["details_json"] or "{}")
                details = {str(code): pd.DataFrame(records or []) for code, records in raw.items()}
            except Exception:
                pass
    return summary, details, failures, entities, meta


def _json_from_dataframe(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "[]"
    # pandas converts NaN/NaT to JSON null and timestamps to ISO strings.
    return df.to_json(orient="records", date_format="iso", force_ascii=False)


def _make_schema_helpers(db_engine):
    inspector = sqlalchemy_inspect(db_engine)

    def table_exists(table_name: str) -> bool:
        try:
            return bool(inspector.has_table(table_name))
        except Exception:
            LOGGER.exception("Schema inspection failed for table %s", table_name)
            return False

    def table_columns(table_name: str) -> dict[str, str]:
        try:
            result: dict[str, str] = {}
            for item in inspector.get_columns(table_name):
                actual = str(item["name"])
                key = normalize_column_name(actual)
                previous = result.get(key)
                if previous is None or ("_" in actual and "_" not in previous):
                    result[key] = actual
            return result
        except Exception:
            LOGGER.exception("Cannot inspect columns for %s", table_name)
            return {}

    return table_exists, table_columns


def _find_top_level_keyword(sql: str, keyword: str) -> int:
    """Find a SQL keyword outside parentheses, string literals and quoted identifiers."""
    target = keyword.upper()
    depth = 0
    single = False
    double = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if single:
            if ch == "\\":
                i += 2
                continue
            if ch == "'":
                if nxt == "'":
                    i += 2
                    continue
                single = False
            i += 1
            continue
        if double:
            if ch == '"':
                if nxt == '"':
                    i += 2
                    continue
                double = False
            i += 1
            continue
        if ch == "'":
            single = True
            i += 1
            continue
        if ch == '"':
            double = True
            i += 1
            continue
        if ch == "-" and nxt == "-":
            end = sql.find("\n", i + 2)
            i = n if end < 0 else end + 1
            continue
        if ch == "/" and nxt == "*":
            end = sql.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth == 0 and sql[i:i + len(target)].upper() == target:
            before = sql[i - 1] if i > 0 else " "
            after = sql[i + len(target)] if i + len(target) < n else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                return i
        i += 1
    return -1


def _split_count_query(sql: str) -> tuple[str, str] | None:
    """Return the top-level FROM and WHERE fragments from a generated count query."""
    from_at = _find_top_level_keyword(sql, "FROM")
    if from_at < 0:
        return None
    where_at = _find_top_level_keyword(sql, "WHERE")
    if where_at < 0 or where_at < from_at:
        return None
    from_clause = "FROM " + sql[from_at + 4:where_at].strip()
    where_clause = sql[where_at + 5:].strip().rstrip(";")
    # Count/population SQL generated by the rule engine has no top-level LIMIT,
    # but remove it defensively if a future rule template adds one.
    for keyword in ("LIMIT", "ORDER BY", "GROUP BY", "HAVING"):
        pos = _find_top_level_keyword(where_clause, keyword)
        if pos >= 0:
            where_clause = where_clause[:pos].strip()
    return (from_clause, where_clause) if from_clause and where_clause else None


def _well_scope_grouping(
    db_engine,
    from_clause: str,
    table_columns_fn,
) -> tuple[str, str, str] | None:
    """
    Resolve a rule query to application-level well codes.

    Legacy snapshot aliases:
        uwi  = well_code
        ubhi = wellbore_code

    Source data is joined using well_id/wellbore_id.
    """

    probe = pd.read_sql_query(
        text(f"SELECT t.* {from_clause} WHERE FALSE LIMIT 0"),
        con=db_engine,
    )

    columns = {
        normalize_column_name(c): str(c)
        for c in probe.columns
    }

    def pick(name: str) -> str | None:
        return columns.get(normalize_column_name(name))

    well_code_col = pick("well_code")
    well_id_col = pick("well_id")
    wellbore_id_col = pick("wellbore_id")
    field_id_col = pick("field_id")
    block_id_col = pick("block_id")

    # Well-level rule: epdb_well already contains well_code.
    if well_code_col:
        return (
            from_clause,
            f"NULLIF(BTRIM(t.{quote_ident(well_code_col)}::text), '')",
            "''::text",
        )

    # Borehole-level or child-table rule:
    # child.wellbore_id -> borehole -> well.
    if wellbore_id_col:
        grouped_from = (
            f"{from_clause} "
            f"LEFT JOIN public.epdb_borehole qc_scope_bh "
            f"ON qc_scope_bh.wellbore_id = "
            f"t.{quote_ident(wellbore_id_col)} "
            f"LEFT JOIN public.epdb_well qc_scope_w "
            f"ON qc_scope_w.well_id = qc_scope_bh.well_id"
        )

        return (
            grouped_from,
            "NULLIF(BTRIM(qc_scope_w.well_code::text), '')",
            "NULLIF(BTRIM(qc_scope_bh.wellbore_code::text), '')",
        )

    # Table containing well_id but not wellbore_id.
    if well_id_col:
        grouped_from = (
            f"{from_clause} "
            f"LEFT JOIN public.epdb_well qc_scope_w "
            f"ON qc_scope_w.well_id = t.{quote_ident(well_id_col)}"
        )

        return (
            grouped_from,
            "NULLIF(BTRIM(qc_scope_w.well_code::text), '')",
            "''::text",
        )

    # Field-level rule.
    if field_id_col:
        grouped_from = (
            f"{from_clause} "
            f"LEFT JOIN public.epdb_well qc_scope_w "
            f"ON qc_scope_w.field_id = t.{quote_ident(field_id_col)}"
        )

        return (
            grouped_from,
            "NULLIF(BTRIM(qc_scope_w.well_code::text), '')",
            "''::text",
        )

    # Block-level rule.
    if block_id_col:
        grouped_from = (
            f"{from_clause} "
            f"LEFT JOIN public.epdb_field qc_scope_f "
            f"ON qc_scope_f.block_id = t.{quote_ident(block_id_col)} "
            f"LEFT JOIN public.epdb_well qc_scope_w "
            f"ON qc_scope_w.field_id = qc_scope_f.field_id"
        )

        return (
            grouped_from,
            "NULLIF(BTRIM(qc_scope_w.well_code::text), '')",
            "''::text",
        )

    return None


def _grouped_rule_counts(
    db_engine,
    checks: list[dict[str, Any]],
    summary: pd.DataFrame,
    details: dict[str, pd.DataFrame],
    table_columns_fn,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build a materialized per-well/per-borehole snapshot during the global QC run.

    The dashboard never executes QC for a selected well. It reads these rows by
    run_id/UWI/UBHI and filters the already completed global cycle.
    """
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    meta_by_rule = {
        str(row.get("Mã luật")): row.to_dict()
        for _, row in summary.iterrows()
        if str(row.get("Mã luật", "")).strip()
    }

    
    # Load the well/borehole universe using the fixed Cuu Long schema.
    # well_code is the application-level UWI.
    # wellbore_code is the application-level UBHI.
    # Relationships are resolved through well_id, not by joining codes.

    known_scope_keys: list[tuple[str, str]] = []
    all_uwis: list[str] = []

    try:
        known = pd.read_sql_query(
            text("""
                SELECT
                    w.well_code::text AS uwi,
                    b.wellbore_code::text AS ubhi
                FROM public.epdb_well w
                LEFT JOIN public.epdb_borehole b
                    ON b.well_id = w.well_id
                WHERE w.well_code IS NOT NULL
            """),
            con=db_engine,
        )

        for item in known.to_dict(orient="records"):
            raw_uwi = item.get("uwi")
            raw_ubhi = item.get("ubhi")

            if raw_uwi is None or pd.isna(raw_uwi):
                continue

            uwi_text = str(raw_uwi).strip()
            ubhi_text = (
                ""
                if raw_ubhi is None or pd.isna(raw_ubhi)
                else str(raw_ubhi).strip()
            )

            if uwi_text:
                known_scope_keys.append((uwi_text, ubhi_text))

    except Exception as exc:
        message = (
            "Không tải được danh mục Well Code/Wellbore Code "
            f"để tổng hợp QC: {type(exc).__name__}: {exc}"
        )
        errors.append(message)
        LOGGER.exception(
            "Cannot load well/borehole codes for per-well QC snapshot"
        )

    # Remove duplicate well/borehole pairs.
    known_scope_keys = list(dict.fromkeys(known_scope_keys))

    # Every well must also have a well-level key.
    all_uwis = sorted({
        uwi for uwi, _ in known_scope_keys
    })


    def default_keys(group_by_borehole: bool) -> list[tuple[str, str]]:
        if not group_by_borehole:
            return [(uwi, "") for uwi in all_uwis]
        keys = list(known_scope_keys)
        # Empty UBHI key preserves well-level checks and records whose source
        # table has UWI but does not identify a specific borehole.
        keys.extend((uwi, "") for uwi in all_uwis)
        return list(dict.fromkeys(keys))

    def append_record(
        check: dict[str, Any],
        uwi: Any,
        ubhi: Any,
        population: Any,
        issue_count: Any,
        result_override: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if uwi is None or pd.isna(uwi):
            return
        uwi_text = str(uwi).strip()
        ubhi_text = "" if ubhi is None or pd.isna(ubhi) else str(ubhi).strip()
        if not uwi_text:
            return
        try:
            population_int = max(0, int(population or 0))
        except (TypeError, ValueError):
            population_int = 0
        try:
            issues_int = max(0, int(issue_count or 0))
        except (TypeError, ValueError):
            issues_int = 0
        meta = meta_by_rule.get(str(check.get("rule_id")), {})
        result = result_override or (
            "Có lỗi" if issues_int > 0 else "Đạt" if population_int > 0 else "Chưa có dữ liệu"
        )
        rows.append({
            "rule_id": str(check.get("rule_id", "")),
            "uwi": uwi_text,
            "ubhi": ubhi_text,
            "domain": str(meta.get("Lĩnh vực") or check.get("domain") or ""),
            "rule_name": str(meta.get("Nhóm kiểm tra") or check.get("name") or ""),
            "severity": str(meta.get("Mức độ") or check.get("severity") or ""),
            "requirement": str(meta.get("Yêu cầu kiểm tra") or check.get("requirement") or ""),
            "dimensions": str(meta.get("Chiều DQS") or ", ".join(check.get("dimensions") or [])),
            "population_count": population_int,
            "issue_count": issues_int,
            "result": result,
            "error_message": (error_message or "")[:2000],
        })

    for check in checks:
        rule_id = str(check.get("rule_id", ""))
        if not rule_id:
            continue
        if check.get("schema_missing"):
            # Missing schema is already represented in the global summary. These
            # rules cannot be reliably scoped because their SQL was not generated.
            continue

        default_scope: list[tuple[str, str]] = []
        try:
            # File validation evaluated all boreholes in the global pass. Reuse
            # those outcomes; never reopen physical LAS/Core files in this step.
            if check.get("document_validation"):
                detail = details.get(rule_id, pd.DataFrame())
                default_scope = default_keys(group_by_borehole=True)
                if detail is None or detail.empty:
                    for uwi, ubhi in default_scope:
                        append_record(check, uwi, ubhi, 0, 0, result_override="Chưa có dữ liệu")
                    continue

                ubhi_col = next((c for c in detail.columns if normalize_column_name(c) == "ubhi"), None)
                status_col = next((
                    c for c in detail.columns
                    if normalize_column_name(c) in {"ketquaubhi", "ktquubhi"}
                    or str(c).strip().casefold() == "kết quả ubhi"
                ), None)
                if not ubhi_col or not status_col:
                    raise RuntimeError("Thiếu UBHI/Kết quả UBHI trong kết quả kiểm tra file.")

                outcome_by_ubhi: dict[str, str] = {}
                for ubhi_value, group in detail.groupby(ubhi_col, dropna=False):
                    ubhi_text = "" if pd.isna(ubhi_value) else str(ubhi_value).strip()
                    if not ubhi_text:
                        continue
                    statuses = set(group[status_col].fillna("").astype(str))
                    outcome_by_ubhi[ubhi_text] = (
                        "Có lỗi" if "Có lỗi" in statuses
                        else "Chưa kiểm tra được" if "Chưa kiểm tra được" in statuses
                        else "Đạt"
                    )

                for uwi, ubhi in default_scope:
                    result = outcome_by_ubhi.get(ubhi, "Chưa có dữ liệu") if ubhi else "Chưa có dữ liệu"
                    append_record(
                        check, uwi, ubhi, 1 if result != "Chưa có dữ liệu" else 0,
                        1 if result == "Có lỗi" else 0, result_override=result,
                        error_message=("File chưa được kiểm tra đầy đủ." if result == "Chưa kiểm tra được" else ""),
                    )
                continue

            issue_parts = _split_count_query(str(check.get("count_sql") or ""))
            population_parts = _split_count_query(str(check.get("population_sql") or ""))
            if not issue_parts or not population_parts:
                continue
            issue_from, issue_where = issue_parts
            population_from, population_where = population_parts
            scope = _well_scope_grouping(db_engine, issue_from, table_columns_fn)
            if scope is None:
                # Rule is a global/reference check with no reliable UWI/UBHI,
                # field_id or block_id path. It remains in the global QC view.
                continue
            grouped_from, uwi_expr, ubhi_expr = scope
            is_borehole_level = str(ubhi_expr).strip() != "''::text"
            default_scope = default_keys(group_by_borehole=is_borehole_level)
            params = check.get("params") or {}

            if issue_from == population_from:
                grouped_sql = f"""SELECT {uwi_expr} AS uwi, {ubhi_expr} AS ubhi,
                    COUNT(*) FILTER (WHERE ({issue_where})) AS issue_count,
                    COUNT(*) FILTER (WHERE ({population_where})) AS population_count
                    {grouped_from}
                    WHERE ({issue_where}) OR ({population_where})
                    GROUP BY {uwi_expr}, {ubhi_expr}"""
                grouped = pd.read_sql_query(text(grouped_sql), con=db_engine, params=params)
            else:
                population_scope = _well_scope_grouping(db_engine, population_from, table_columns_fn)
                if population_scope is None:
                    raise RuntimeError("Không xác định được khóa UWI/UBHI cho population SQL.")
                pop_from, pop_uwi, pop_ubhi = population_scope
                is_borehole_level = is_borehole_level or str(pop_ubhi).strip() != "''::text"
                default_scope = default_keys(group_by_borehole=is_borehole_level)
                issue_sql = f"""SELECT {uwi_expr} AS uwi, {ubhi_expr} AS ubhi,
                    COUNT(*) AS issue_count {grouped_from}
                    WHERE ({issue_where}) GROUP BY {uwi_expr}, {ubhi_expr}"""
                population_sql = f"""SELECT {pop_uwi} AS uwi, {pop_ubhi} AS ubhi,
                    COUNT(*) AS population_count {pop_from}
                    WHERE ({population_where}) GROUP BY {pop_uwi}, {pop_ubhi}"""
                issue_df = pd.read_sql_query(text(issue_sql), con=db_engine, params=params)
                population_df = pd.read_sql_query(text(population_sql), con=db_engine, params=params)
                grouped = population_df.merge(issue_df, on=["uwi", "ubhi"], how="outer")
                grouped["population_count"] = pd.to_numeric(grouped.get("population_count"), errors="coerce").fillna(0)
                grouped["issue_count"] = pd.to_numeric(grouped.get("issue_count"), errors="coerce").fillna(0)

            # Start from all relevant well/borehole keys (explicit no-data), then
            # replace with actual aggregate counts returned by PostgreSQL.
            by_key: dict[tuple[str, str], tuple[int, int]] = {key: (0, 0) for key in default_scope}
            for item in grouped.to_dict(orient="records"):
                raw_uwi = item.get("uwi")
                raw_ubhi = item.get("ubhi")
                if raw_uwi is None or pd.isna(raw_uwi):
                    continue
                key = (str(raw_uwi).strip(), "" if raw_ubhi is None or pd.isna(raw_ubhi) else str(raw_ubhi).strip())
                try:
                    pop_count = max(0, int(item.get("population_count") or 0))
                except (TypeError, ValueError):
                    pop_count = 0
                try:
                    issue_count = max(0, int(item.get("issue_count") or 0))
                except (TypeError, ValueError):
                    issue_count = 0
                previous = by_key.get(key, (0, 0))
                by_key[key] = (previous[0] + pop_count, previous[1] + issue_count)

            for (uwi, ubhi), (population_count, issue_count) in by_key.items():
                append_record(check, uwi, ubhi, population_count, issue_count)

        except Exception as exc:
            message = f"{rule_id}: {type(exc).__name__}: {exc}"
            errors.append(message)
            LOGGER.exception("Could not build per-well snapshot for rule %s", rule_id)
            # Do not present an aggregation failure as "no data". Store an
            # explicit unchecked row for all resolvable well/borehole scopes.
            if not default_scope:
                try:
                    probe_parts = _split_count_query(str(check.get("count_sql") or ""))
                    probe_scope = _well_scope_grouping(db_engine, probe_parts[0], table_columns_fn) if probe_parts else None
                    if probe_scope:
                        default_scope = default_keys(str(probe_scope[2]).strip() != "''::text")
                except Exception:
                    default_scope = []
            for uwi, ubhi in default_scope:
                append_record(
                    check, uwi, ubhi, 0, 0,
                    result_override="Chưa kiểm tra được", error_message=message,
                )

    # Collapse duplicate groups caused by legitimate joins, then compute statuses.
    if rows:
        frame = pd.DataFrame(rows)
        identity = ["rule_id", "uwi", "ubhi"]
        numeric = frame.groupby(identity, dropna=False)[["population_count", "issue_count"]].sum().reset_index()
        metadata = frame.drop_duplicates(identity).drop(columns=["population_count", "issue_count", "result", "error_message"])
        status_meta = frame.groupby(identity, dropna=False).agg(
            unchecked=("result", lambda values: bool((values == "Chưa kiểm tra được").any())),
            errors=("error_message", lambda values: "; ".join(dict.fromkeys(str(v) for v in values if str(v).strip()))),
        ).reset_index()
        frame = metadata.merge(numeric, on=identity, how="left").merge(status_meta, on=identity, how="left")
        frame["result"] = frame.apply(
            lambda r: "Có lỗi" if int(r["issue_count"] or 0) > 0
            else "Chưa kiểm tra được" if bool(r["unchecked"])
            else "Đạt" if int(r["population_count"] or 0) > 0
            else "Chưa có dữ liệu",
            axis=1,
        )
        frame["error_message"] = frame["errors"].fillna("")
        rows = frame.drop(columns=["unchecked", "errors"]).to_dict(orient="records")

    return rows, errors

def run_qc_cycle(db_engine, document_root: str | Path | None = None, keep_runs: int = 20) -> str | None:
    """Execute one full QC cycle and persist its summary/detail snapshot atomically.

    A PostgreSQL session advisory lock prevents overlapping runs from the dashboard
    and the in-process background worker. Returns None when another run currently owns the lock.
    """
    ensure_qc_storage_tables(db_engine)
    lock_conn = db_engine.connect()
    acquired = False
    try:
        acquired = bool(lock_conn.execute(
            text("SELECT pg_try_advisory_lock(:lock_key)"), {"lock_key": QC_LOCK_KEY}
        ).scalar())
        lock_conn.commit()
        if not acquired:
            LOGGER.warning("Another EPDB QC cycle is already running; skip this trigger.")
            return None

        run_id = str(uuid.uuid4())
        started_at = datetime.now()
        with db_engine.begin() as conn:
            conn.execute(text("""INSERT INTO epdb_qc_cycle_runs
                (run_id, started_at, status, rule_count, rule_version)
                VALUES (:run_id, :started_at, 'running', 0, :rule_version)"""), {
                    "run_id": run_id,
                    "started_at": started_at,
                    "rule_version": RULES_VERSION,
                })

        try:
            table_exists, table_columns = _make_schema_helpers(db_engine)
            checks = build_checks_150(
                table_exists,
                table_columns,
                normalize_column_name,
                quote_ident,
            )

            def read_df(sql: str, params: dict[str, Any] | None = None):
                return pd.read_sql_query(text(sql), con=db_engine, params=params or {})

            doc_root = document_root if document_root is not None else DEFAULT_DOCUMENT_ROOT
            summary, details, failures, entities = execute_checks_150(
                checks,
                read_df,
                ensure_unique_dataframe_columns,
                document_root=doc_root,
            )
            summary = ensure_unique_dataframe_columns(summary)
            well_summary_rows, well_summary_errors = _grouped_rule_counts(
                db_engine, checks, summary, details or {}, table_columns
            )

            if "Bản ghi / lượt vi phạm" in summary.columns:
                issue_count = int(pd.to_numeric(summary["Bản ghi / lượt vi phạm"], errors="coerce").fillna(0).sum())
            else:
                issue_count = 0
            failed_rule_count = int((summary.get("Kết quả", pd.Series(dtype=str)) == "Chưa kiểm tra được").sum())

            detail_rows = []
            for code, detail in (details or {}).items():
                detail_json = _json_from_dataframe(detail)
                detail_rows.append({
                    "run_id": run_id,
                    "rule_id": str(code),
                    "details_json": detail_json,
                    "detail_count": int(len(detail)) if detail is not None else 0,
                })
            summary_json = _json_from_dataframe(summary)
            failures_json = json.dumps(list(failures or []), ensure_ascii=False)
            entities_json = json.dumps(sorted(str(item) for item in (entities or set())), ensure_ascii=False)
            completed_at = datetime.now()

            with db_engine.begin() as conn:
                conn.execute(text("""UPDATE epdb_qc_cycle_runs
                    SET completed_at=:completed_at,
                        status='completed',
                        rule_count=:rule_count,
                        issue_count=:issue_count,
                        failed_rule_count=:failed_rule_count,
                        affected_entities_count=:affected_entities_count,
                        summary_json=:summary_json,
                        failures_json=:failures_json,
                        affected_entities_json=:entities_json,
                        details_json=NULL,
                        error_message=NULL,
                        well_summary_ready=TRUE,
                        well_summary_error_count=:well_summary_error_count
                    WHERE run_id=:run_id"""), {
                        "completed_at": completed_at,
                        "rule_count": int(len(summary)),
                        "issue_count": issue_count,
                        "failed_rule_count": failed_rule_count,
                        "affected_entities_count": len(entities or set()),
                        "summary_json": summary_json,
                        "failures_json": failures_json,
                        "entities_json": entities_json,
                        "well_summary_error_count": int(len(well_summary_errors)),
                        "run_id": run_id,
                    })
                if detail_rows:
                    conn.execute(text("""INSERT INTO epdb_qc_cycle_details
                        (run_id, rule_id, details_json, detail_count)
                        VALUES (:run_id, :rule_id, :details_json, :detail_count)
                        ON CONFLICT (run_id, rule_id) DO UPDATE SET
                            details_json=EXCLUDED.details_json,
                            detail_count=EXCLUDED.detail_count"""), detail_rows)
                if well_summary_rows:
                    well_payload = [dict(item, run_id=run_id) for item in well_summary_rows]
                    conn.execute(text("""INSERT INTO epdb_qc_cycle_well_summary
                        (run_id, rule_id, uwi, ubhi, domain, rule_name, severity,
                         requirement, dimensions, population_count, issue_count,
                         result, error_message)
                        VALUES (:run_id, :rule_id, :uwi, :ubhi, :domain, :rule_name,
                                :severity, :requirement, :dimensions, :population_count,
                                :issue_count, :result, :error_message)
                        ON CONFLICT (run_id, rule_id, uwi, ubhi) DO UPDATE SET
                            population_count=EXCLUDED.population_count,
                            issue_count=EXCLUDED.issue_count,
                            result=EXCLUDED.result,
                            error_message=EXCLUDED.error_message"""), well_payload)
                # Retain a finite history of completed/failed cycles. FK cascade removes details.
                conn.execute(text("""DELETE FROM epdb_qc_cycle_runs
                    WHERE run_id IN (
                        SELECT run_id FROM epdb_qc_cycle_runs
                        WHERE status IN ('completed', 'failed')
                        ORDER BY started_at DESC
                        OFFSET :keep_count
                    )"""), {"keep_count": max(1, int(keep_runs))})

            LOGGER.info(
                "QC cycle %s completed: %s rules, %s record issues, %s well-rule rows, %s per-well aggregation errors, %.1fs",
                run_id, len(summary), issue_count, len(well_summary_rows), len(well_summary_errors),
                (completed_at - started_at).total_seconds(),
            )
            if failures:
                LOGGER.warning("QC cycle completed with %s evaluator/runtime warnings.", len(failures))
            if well_summary_errors:
                LOGGER.warning("Per-well snapshot has %s rule aggregation errors.", len(well_summary_errors))
            return run_id

        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            LOGGER.exception("QC cycle %s failed", run_id)
            with db_engine.begin() as conn:
                conn.execute(text("""UPDATE epdb_qc_cycle_runs
                    SET completed_at=:completed_at, status='failed', error_message=:error
                    WHERE run_id=:run_id"""), {
                        "completed_at": datetime.now(),
                        "error": error_text[:8000],
                        "run_id": run_id,
                    })
            raise
    finally:
        if acquired:
            try:
                lock_conn.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": QC_LOCK_KEY}
                )
                lock_conn.commit()
            except Exception:
                LOGGER.exception("Could not release QC advisory lock cleanly")
        lock_conn.close()



class QCBackgroundWorker:
    """One daemon worker per Streamlit server process; no OS scheduler required."""

    def __init__(
        self,
        db_engine,
        document_root: str | Path | None = None,
        interval_hours: int = 6,
        keep_runs: int = 20,
        poll_seconds: int = 15,
    ) -> None:
        self.db_engine = db_engine
        self.document_root = document_root if document_root is not None else DEFAULT_DOCUMENT_ROOT
        self.interval_seconds = max(1, int(interval_hours)) * 3600
        self.keep_runs = max(1, int(keep_runs))
        self.poll_seconds = max(5, int(poll_seconds))
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._retry_after: datetime | None = None
        self._state: dict[str, Any] = {
            "running": False,
            "queued": False,
            "last_run_id": None,
            "last_trigger": None,
            "last_error": None,
            "last_started_at": None,
            "last_finished_at": None,
        }

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="EPDB-QC-Background-Worker",
            daemon=True,
        )
        self._thread.start()

    def request_run(self) -> bool:
        """Queue a manual cycle and return immediately to the Streamlit request."""
        with self._state_lock:
            if self._state["running"] or self._state["queued"]:
                return False
            self._state["queued"] = True
            self._state["last_error"] = None
        self._wake.set()
        return True

    def get_state(self) -> dict[str, Any]:
        with self._state_lock:
            return dict(self._state)

    def _is_due(self) -> bool:
        if self._retry_after is not None and datetime.now() < self._retry_after:
            return False
        with self.db_engine.connect() as conn:
            latest = conn.execute(text("""SELECT completed_at, well_summary_ready, rule_version
                FROM epdb_qc_cycle_runs
                WHERE status='completed'
                ORDER BY completed_at DESC
                LIMIT 1""")).mappings().first()
        if latest is None:
            return True
        # A changed rule catalogue must trigger a fresh snapshot immediately;
        # do not wait for the ordinary periodic interval.
        if str(latest.get("rule_version") or "") != RULES_VERSION:
            return True
        if not bool(latest.get("well_summary_ready")):
            return True
        completed_at = latest.get("completed_at")
        if hasattr(completed_at, "to_pydatetime"):
            completed_at = completed_at.to_pydatetime()
        return completed_at is None or (datetime.now() - completed_at).total_seconds() >= self.interval_seconds

    def _execute(self, trigger: str) -> None:
        with self._state_lock:
            self._state.update({
                "running": True,
                "queued": False,
                "last_trigger": trigger,
                "last_started_at": datetime.now(),
                "last_error": None,
            })
        try:
            run_id = run_qc_cycle(
                self.db_engine,
                document_root=self.document_root,
                keep_runs=self.keep_runs,
            )
            with self._state_lock:
                self._state["last_run_id"] = run_id
                if run_id is None:
                    self._state["last_error"] = "Một tiến trình QC khác đang giữ khóa thực thi."
                    self._retry_after = datetime.now() + timedelta(seconds=30)
                else:
                    self._retry_after = None
        except Exception as exc:
            LOGGER.exception("Background QC cycle failed")
            with self._state_lock:
                self._state["last_error"] = f"{type(exc).__name__}: {exc}"
                self._retry_after = datetime.now() + timedelta(minutes=5)
        finally:
            with self._state_lock:
                self._state["running"] = False
                self._state["queued"] = False
                self._state["last_finished_at"] = datetime.now()

    def _run_loop(self) -> None:
        try:
            ensure_qc_storage_tables(self.db_engine)
        except Exception:
            LOGGER.exception("Cannot initialize QC snapshot storage in background worker")

        first_check = True
        while not self._stop.is_set():
            requested = self._wake.is_set()
            if requested:
                self._wake.clear()
                self._execute("manual")
            else:
                try:
                    if first_check or self._is_due():
                        self._execute("periodic")
                except Exception as exc:
                    LOGGER.exception("QC background due-check failed")
                    with self._state_lock:
                        self._state["last_error"] = f"{type(exc).__name__}: {exc}"
                first_check = False

            self._wake.wait(timeout=self.poll_seconds)
            if self._stop.is_set():
                break

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

def _resolve_db_url() -> str | None:
    value = os.getenv("EPDB_DB_URL")
    if value:
        return value

    # The scheduled process can reuse the app's Streamlit secrets file.
    secrets_path = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
    if secrets_path.is_file():
        try:
            import tomllib
            data = tomllib.loads(secrets_path.read_text(encoding="utf-8"))
            value = data.get("DB_URL")
            if not value:
                value = (data.get("database") or {}).get("url")
            if value:
                return str(value)
        except Exception:
            LOGGER.exception("Cannot read %s", secrets_path)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one EPDB periodic Rule-QC cycle.")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit (default behavior).")
    parser.add_argument("--document-root", default=str(DEFAULT_DOCUMENT_ROOT))
    parser.add_argument("--keep-runs", type=int, default=int(os.getenv("EPDB_QC_KEEP_RUNS", "20")))
    args = parser.parse_args()

    logging.basicConfig(
        level=os.getenv("EPDB_QC_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    db_url = _resolve_db_url()
    if not db_url:
        LOGGER.error("Set EPDB_DB_URL or configure DB_URL in .streamlit/secrets.toml before scheduling QC.")
        return 2

    db_engine = create_engine(db_url, pool_pre_ping=True, pool_recycle=1800)
    try:
        run_id = run_qc_cycle(db_engine, document_root=args.document_root, keep_runs=args.keep_runs)
        if run_id is None:
            LOGGER.info("No new run was started because another QC cycle is active.")
        else:
            LOGGER.info("QC cycle finished successfully: %s", run_id)
        return 0
    finally:
        db_engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
