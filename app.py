from __future__ import annotations

import os
import sys
import json
import re
import html
import uuid
import hashlib
import warnings
import base64
import mimetypes
import textwrap
import unicodedata

from io import BytesIO
from pathlib import Path
from urllib.parse import quote, unquote
from datetime import datetime, timedelta
from typing import Any

# Prefer the modules shipped beside this app.py. This prevents an older
# epdb_qc_rules_150.py or epdb_qc_scheduler.py in the working directory from
# being imported accidentally when Streamlit is launched from another folder.
APP_DIR = Path(__file__).resolve().parent
APP_DIR_TEXT = str(APP_DIR)
if APP_DIR_TEXT in sys.path:
    sys.path.remove(APP_DIR_TEXT)
sys.path.insert(0, APP_DIR_TEXT)

if "warnings" not in sys.modules:
    sys.modules["warnings"] = warnings

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import streamlit_antd_components as sac
from sqlalchemy import create_engine, inspect as sqlalchemy_inspect, text
import epdb_qc_rules_150 as _epdb_qc_rules_module
import epdb_qc_scheduler as _epdb_qc_scheduler_module

_expected_rules_file = (APP_DIR / "epdb_qc_rules_150.py").resolve()
_expected_scheduler_file = (APP_DIR / "epdb_qc_scheduler.py").resolve()
if Path(_epdb_qc_rules_module.__file__).resolve() != _expected_rules_file:
    raise ImportError(
        "EPDB đang nạp nhầm epdb_qc_rules_150.py. Hãy đặt đúng bộ 3 file cùng thư mục "
        "và xóa/đổi tên bản cũ trùng tên ở thư mục chạy."
    )
if Path(_epdb_qc_scheduler_module.__file__).resolve() != _expected_scheduler_file:
    raise ImportError(
        "EPDB đang nạp nhầm epdb_qc_scheduler.py. Hãy đặt đúng bộ 3 file cùng thư mục "
        "và xóa/đổi tên bản cũ trùng tên ở thư mục chạy."
    )
if (
    getattr(_epdb_qc_rules_module, "QC_RULES_VERSION", None) != "epdb_qc_150_cuulong_v1"
    or getattr(_epdb_qc_rules_module, "ACTIVE_RULE_COUNT", None) != 120
    or len(getattr(_epdb_qc_rules_module, "RULES_150", [])) != 134
):
    raise RuntimeError(
        "Sai phiên bản Rule Engine: bộ dashboard này yêu cầu QC_RULES_VERSION="
        "epdb_qc_150_instructor_v1, 134 luật trong catalogue và 120 luật runtime. "
        "Không tiếp tục chạy với file luật cũ/không đồng bộ."
    )

from epdb_qc_rules_150 import RULES_150, build_checks as build_checks_150
from epdb_qc_scheduler import (
    ensure_qc_storage_tables, load_latest_qc_summary, load_qc_rule_detail,
    load_qc_well_summary, QCBackgroundWorker,
)

# =========================================================
# 0. APPLICATION SETTINGS
# =========================================================
st.set_page_config(
    page_title="EPDB Control Center",
    layout="wide",
    page_icon="🛢️",
    initial_sidebar_state="collapsed",
)

BASE_DIR = APP_DIR
# Thư mục gốc chứa tài liệu EPDB.
# Có thể ghi đè bằng biến môi trường EPDB_DOCUMENT_ROOT.
DOCUMENT_ROOT = Path(
    os.getenv("EPDB_DOCUMENT_ROOT", r"C:\EPDB_DOCUMENTS")
).expanduser()
GEOJSON_FILE_PATH = BASE_DIR / "VN_Offshore_Blocks.geojson"
# Khóa trong properties dùng để nối polygon GeoJSON với tên lô trong EPDB.
# Có thể ghi đè qua biến môi trường nếu GeoJSON có cấu trúc khác.
GEOJSON_FEATURE_MATCH_KEY = os.getenv(
    "EPDB_GEOJSON_FEATURE_MATCH_KEY", "properties.block_name"
)

TIMELINESS_MAX_AGE_DAYS = max(1, int(os.getenv("EPDB_TIMELINESS_MAX_AGE_DAYS", "365")))
QC_CYCLE_INTERVAL_HOURS = max(1, int(os.getenv("EPDB_QC_INTERVAL_HOURS", "6")))

# IMPORTANT: these weights are provisional until checked against the approved proposal.
# Keep the six dimensions visible; change this single configuration after supervisor approval.
DQS_WEIGHTS = {
    "Completeness": 0.25,
    "Accuracy": 0.25,
    "Consistency": 0.20,
    "Validity": 0.10,
    "Uniqueness": 0.10,
    "Timeliness": 0.10,
}

# Central QC source. Thresholds are engineering screening rules, not universal petrophysical truths.
QC_RULES_VERSION = "epdb_qc_150_cuulong_v1"
LOG_FEATURE_ALIASES = {
    "MD_m": ["md", "md_m", "measured_depth", "depth"],
    "GR_gAPI": ["gr", "gr_gapi", "gamma_ray"],
    "CALI_in": ["cali", "cali_in", "caliper"],
    "NPHI_vv": ["nphi", "nphi_vv", "neutron_porosity"],
    "RHOB_gcm3": ["rhob", "rhob_gcm3", "density"],
    "DT_usft": ["dt", "dt_usft", "sonic", "deltat"],
    "SP_mV": ["sp", "sp_mv", "spontaneous_potential"],
}
DQS_DIMENSION_LABELS = {
    "Completeness": "Completeness — Đầy đủ",
    "Accuracy": "Accuracy — Chính xác",
    "Consistency": "Consistency — Nhất quán",
    "Validity": "Validity — Hợp lệ",
    "Uniqueness": "Uniqueness — Duy nhất",
    "Timeliness": "Timeliness — Kịp thời",
}

if "active_file" not in st.session_state:
    st.session_state.active_file = None

# =========================================================
# 1. UI STYLE
# =========================================================
st.markdown(
    """
    <style>
        :root {
            --epdb-navy: #17365D;
            --epdb-blue: #245A8D;
            --epdb-teal: #0F766E;
            --epdb-ink: #1F2937;
            --epdb-muted: #526174;
            --epdb-border: #CBD5E1;
            --epdb-page: #F3F6FA;
            --epdb-card: #FFFFFF;
            --epdb-red: #B42318;
            --epdb-amber: #92400E;
            --epdb-green: #166534;
        }
        *, *::before, *::after { box-sizing: border-box; }
        html, body { width: 100%; max-width: 100%; overflow-x: hidden; }
        [data-testid="stAppViewContainer"] { background: var(--epdb-page); color: var(--epdb-ink); }
        [data-testid="stMainBlockContainer"], .block-container {
            width: 100% !important;
            max-width: 100% !important;
            margin-inline: auto !important;
            padding: 0 clamp(.65rem, 1.35vw, 1.4rem) .75rem !important;
        }
        header[data-testid="stHeader"] { visibility: hidden; height: 0; }
        [data-testid="collapsedControl"] {
            background: var(--epdb-navy) !important; border-radius: 9px !important;
            color: white !important; box-shadow: 0 2px 6px rgba(23,54,93,.22) !important;
            top: 10px !important; right: 14px !important; left: auto !important;
            width: 38px !important; height: 38px !important; display: flex;
            align-items: center; justify-content: center; z-index: 999999;
        }
        [data-testid="collapsedControl"]:hover { background: var(--epdb-blue) !important; }
        [data-testid="collapsedControl"] svg { fill: white !important; width: 21px !important; height: 21px !important; }
        [data-testid="stSidebar"][aria-expanded="true"] {
            width: 100vw !important; min-width: 0 !important; max-width: 100vw !important;
            background: #F7F9FC;
        }
        [data-testid="stSidebar"] > div:first-child {
            padding: clamp(.5rem, 1vw, .9rem) clamp(.65rem, 1.25vw, 1.25rem) !important;
        }
        .main-title {
            color: var(--epdb-navy); margin: 0; font-weight: 800;
            font-size: clamp(1.02rem, 1.45vw, 1.48rem); letter-spacing: .12px; line-height: 1.35;
        }
        .overview-panel-title, .section-heading {
            font-size: clamp(.92rem, 1vw, 1.05rem); font-weight: 800; color: var(--epdb-navy);
            padding: .28rem 0 .72rem 0; margin: .04rem 0 .72rem 0;
            border-bottom: 1px solid #B9C8D8;
        }
        /* Plotly: nhấn đậm tiêu đề trục và giữ nhãn tick dễ đọc. */
        .js-plotly-plot .xtitle, .js-plotly-plot .ytitle {
            font-weight: 800 !important; fill: #26384A !important;
        }
        .js-plotly-plot .xtick text, .js-plotly-plot .ytick text {
            font-weight: 650 !important; fill: #40546A !important;
        }
        .js-plotly-plot .legend text { font-weight: 650 !important; }
        /* Bảng Streamlit: viền ngoài rõ, đường phân cách hàng/cột và nền sáng. */
        [data-testid="stDataFrame"], [data-testid="stTable"] {
            width: 100%; border: 1px solid #AAB9C9 !important; border-radius: 9px;
            overflow: hidden; background: #FFFFFF; box-shadow: 0 1px 3px rgba(15,23,42,.045);
        }
        [data-testid="stDataFrame"] [role="columnheader"] {
            font-weight: 900 !important; color: #102F53 !important;
            background: #DCE8F5 !important; border-bottom: 2px solid #7893B1 !important;
        }
        [data-testid="stDataFrame"] [role="gridcell"] {
            border-bottom: 1px solid #E0E7EF !important;
        }
        .epdb-overview-dqs-marker { display: none !important; }
        @media (min-width: 1101px) {
            [data-testid="stVerticalBlockBorderWrapper"]:has(.epdb-overview-dqs-marker) {
                min-height: 585px !important;
            }
        }
        .section-subtitle { color: var(--epdb-muted); font-size: .84rem; margin: -.2rem 0 .7rem 0; }
        .epdb-nav-marker, .epdb-cat-nav-marker { display: none; }
        .view-caption {
            color: var(--epdb-muted); font-size: .86rem; text-align: center;
            margin: .2rem 0 .85rem 0; line-height: 1.4;
        }
        .map-legend { color: var(--epdb-muted); font-size: .78rem; margin: 0 0 .4rem 0; }
        [data-testid="stTabs"] [role="tablist"] {
            gap: .35rem; border-bottom: 1px solid var(--epdb-border);
            padding-bottom: .1rem; margin-bottom: .55rem; flex-wrap: wrap;
        }
        [data-testid="stTabs"] button[role="tab"] {
            color: #46566B; font-size: .88rem; font-weight: 700;
            padding: .52rem .8rem; border-radius: 7px 7px 0 0;
        }
        [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
            color: var(--epdb-navy) !important; border-bottom: 3px solid var(--epdb-teal) !important;
            background: #FFFFFF;
        }
        [data-testid="stRadio"] > div[role="radiogroup"] { gap: .4rem; flex-wrap: wrap; }
        [data-testid="stRadio"] label {
            background: #FFFFFF; border: 1px solid #B8C6D7; border-radius: 8px;
            padding: .45rem .7rem; margin: 0;
        }
        [data-testid="stRadio"] label:has(input:checked) {
            background: #E7F1FA; border-color: var(--epdb-teal);
            color: var(--epdb-navy); font-weight: 800;
        }
        [data-testid="stRadio"] label > div:first-child { display: none; }
        [data-testid="stVerticalBlock"] > div:has(.epdb-nav-marker) + div [data-testid="stRadio"] > div[role="radiogroup"] {
            display: flex; width: 100%; gap: 0; flex-wrap: nowrap;
            background: #FFFFFF; border: 1px solid var(--epdb-border);
            border-radius: 10px; overflow: hidden; margin: 0;
        }
        [data-testid="stVerticalBlock"] > div:has(.epdb-nav-marker) + div [data-testid="stRadio"] label {
            flex: 1 1 0; text-align: center; justify-content: center;
            background: transparent; border: none !important; border-radius: 0 !important;
            border-right: 1px solid var(--epdb-border) !important;
            padding: .68rem .4rem !important; margin: 0; color: #46566B;
            font-weight: 700; font-size: clamp(.78rem, .92vw, .9rem);
        }
        [data-testid="stVerticalBlock"] > div:has(.epdb-nav-marker) + div [data-testid="stRadio"] label:last-child {
            border-right: none !important;
        }
        [data-testid="stVerticalBlock"] > div:has(.epdb-nav-marker) + div [data-testid="stRadio"] label:has(input:checked) {
            background: var(--epdb-navy) !important; 
            color: #FFFFFF !important; 
            border-color: var(--epdb-navy) !important; 
            font-weight: 850 !important;
        }
        [data-testid="stVerticalBlock"] > div:has(.epdb-nav-marker) + div [data-testid="stRadio"] label:has(input:checked) div {
            color: #FFFFFF !important;
        }
        [data-testid="stColumn"] [data-testid="stSelectbox"] {
            width: 100%; max-width: 100%; margin-inline: 0;
        }
        .epdb-kpi-card-raised { transform: translateY(-4px); }
        div[data-testid="stMetric"] {
            background: var(--epdb-card); border: 1px solid var(--epdb-border);
            border-radius: 10px; padding: clamp(.5rem, .7vw, .8rem);
            min-height: clamp(72px, 5.8vw, 88px); height: 100%;
            box-shadow: 0 1px 3px rgba(15,23,42,.035);
        }
        div[data-testid="stMetricLabel"] {
            color: #526174 !important; font-size: clamp(.68rem, .73vw, .78rem) !important;
            font-weight: 750 !important; white-space: normal; line-height: 1.25 !important;
        }
        div[data-testid="stMetricValue"] {
            color: var(--epdb-navy) !important; font-size: clamp(1.12rem, 1.45vw, 1.62rem) !important;
            font-weight: 800 !important; line-height: 1.15 !important; overflow-wrap: anywhere;
        }
        .epdb-alert-metric {
            display: flex; flex-direction: column; justify-content: center; gap: .32rem;
            min-height: clamp(76px, 6.3vw, 94px); height: 100%; padding: clamp(.55rem, .75vw, .85rem);
            border: 1px solid #F1A5A5; border-left: 4px solid #C62828; border-radius: 10px;
            background: #FFF0F0; box-shadow: 0 1px 3px rgba(127,29,29,.06);
        }
        .epdb-alert-metric-label { color: #8F1D1D; font-size: clamp(.68rem, .73vw, .78rem); font-weight: 800; line-height: 1.25; }
        .epdb-alert-metric-value { color: #991B1B; font-size: clamp(1.12rem, 1.45vw, 1.62rem); font-weight: 850; line-height: 1.15; overflow-wrap: anywhere; }
        [data-testid="stSelectbox"] {
            width: 100%; max-width: min(72vw, 38rem); margin-inline: auto;
        }
        [data-testid="stSelectbox"] label, [data-testid="stTextInput"] label,
        [data-testid="stMultiSelect"] label, [data-testid="stDateInput"] label {
            color: #344256 !important; font-size: .82rem !important; font-weight: 750 !important;
        }
        [data-testid="stSelectbox"] div[data-baseweb="select"] > div {
            background: #FFFFFF !important; border-color: #A9B8CA !important;
            border-radius: 8px !important; min-height: 2.45rem;
        }
        [data-testid="stSelectbox"] div[data-baseweb="select"] > div:focus-within {
            border-color: var(--epdb-teal) !important; box-shadow: 0 0 0 2px rgba(15,118,110,.15) !important;
        }
        [data-testid="stDataFrame"] {
            width: 100%; border: 1px solid var(--epdb-border); border-radius: 9px;
            overflow: hidden; background: #FFFFFF;
        }
        [data-testid="stExpander"] { border: 1px solid var(--epdb-border); border-radius: 9px; background: rgba(255,255,255,.92); }
        [data-testid="stAlert"] { border-radius: 9px; border: 1px solid var(--epdb-border); }
        div.stButton > button[kind="primary"] {
            background: var(--epdb-navy); color: #FFFFFF; border: 1px solid var(--epdb-navy);
            border-radius: 8px; font-weight: 750;
        }
        div.stButton > button[kind="primary"]:hover { background: var(--epdb-blue); border-color: var(--epdb-blue); }
        .error-metric { color: var(--epdb-red) !important; font-weight: 800 !important; }
        .alert-panel { border-left: 4px solid var(--epdb-red); background: #FFF0F0; padding: 10px 14px; border-radius: 8px; margin-bottom: 10px; color: #7F1D1D; }
        [data-testid="stCaptionContainer"] { color: #526174; }
        @media (max-width: 1100px) {
            [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; align-items: stretch; }
            [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
                flex: 1 1 235px !important; min-width: min(100%, 235px) !important;
            }
            [data-testid="stMainBlockContainer"], .block-container {
                padding: .16rem .75rem .85rem !important;
            }
            [data-testid="stVerticalBlock"] > div:has(.epdb-nav-marker) + div [data-testid="stRadio"] > div[role="radiogroup"] {
                flex-wrap: wrap;
            }
            [data-testid="stVerticalBlock"] > div:has(.epdb-nav-marker) + div [data-testid="stRadio"] label {
                flex: 1 1 40%;
            }
        }
                /* =====================================================
        MOBILE NAVIGATION
        ===================================================== */
        @media (max-width: 600px) {
            [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
                flex: 1 1 100% !important;
                min-width: 100% !important;
                width: 100% !important;
            }

            .main-title {
                font-size: 1rem;
            }

            div[data-testid="stMetric"],
            .epdb-alert-metric {
                min-height: 72px;
            }

            div[data-testid="stMetricValue"],
            .epdb-alert-metric-value {
                font-size: 1.18rem !important;
            }

            [data-testid="stSelectbox"] {
                max-width: 100%;
            }

            [data-testid="stVerticalBlock"] > div:has(.epdb-nav-marker)
            + div [data-testid="stRadio"] label {
                flex: 1 1 100%;
            }
        }

        /* =====================================================
        SIDEBAR — REDUCE EMPTY SPACE ABOVE EXPLORER
        ===================================================== */
        [data-testid="stSidebarContent"] {
            padding-top: 0 !important;
            margin-top: -24px !important;
        }
        [data-testid="stSidebarUserContent"] {
            padding-top: 0 !important;
            margin-top: 0 !important;
        }

        [data-testid="stSidebar"] > div:first-child {
            padding: 0 .5rem .45rem !important;
        }

        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
            gap: .3rem !important;
        }

        [data-testid="stSidebar"] [data-testid="stElementContainer"] {
            margin-top: 0 !important;
            margin-bottom: 0 !important;
        }

        .epdb-explorer-marker {
            height: 0 !important;
            min-height: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        .epdb-explorer-header {
            display:flex; align-items:center; justify-content:space-between; gap:10px;
            background:linear-gradient(110deg,#F8FBFF 0%,#EAF1F8 100%);
            border:1px solid #AFC0D2; border-left:4px solid #17365D;
            border-radius:9px; padding:7px 10px; margin-top:0; margin-bottom:6px;
            box-shadow:0 2px 5px rgba(15,23,42,.055);
        }
        .epdb-explorer-header-title {
            color:#17365D; font-size:.82rem; font-weight:900;
            letter-spacing:.28px; line-height:1.25;
        }
        .epdb-explorer-header-subtitle {
            color:#60748A; font-size:.68rem; font-weight:650; margin-top:2px;
        }
        .epdb-explorer-count {
            flex:0 0 auto; background:#17365D; color:#FFFFFF;
            border:1px solid #17365D; border-radius:6px;
            padding:4px 8px; font-size:.68rem; font-weight:850;
            white-space:nowrap;
        }
        .epdb-tree-panel-heading, .epdb-viewer-panel-heading {
            display:flex; align-items:center; gap:7px;
            padding:5px 7px; margin:0 0 6px 0;
            border-radius:6px; font-size:.70rem; font-weight:900;
            letter-spacing:.35px; line-height:1.2;
        }
        .epdb-tree-panel-heading {
            color:#17365D; background:#EAF1F8; border-left:3px solid #245A8D;
        }
        .epdb-viewer-panel-heading {
            color:#0F5E58; background:#E7F3F1; border-left:3px solid #0F766E;
        }
        .epdb-viewer-summary-line {
            display:flex; align-items:center; gap:9px; flex-wrap:nowrap;
            width:100%; min-width:0; overflow-x:auto; white-space:nowrap;
            padding:5px 8px; margin:0 0 7px 0; border:1px solid #AFCBC7;
            border-left:3px solid #0F766E; border-radius:7px;
            background:#E7F3F1; color:#174B48; font-size:.74rem; line-height:1.25;
        }
        .epdb-viewer-summary-line .summary-title { color:#17365D; font-weight:900; }
        .epdb-viewer-summary-line .summary-kind { color:#0F5E58; font-weight:850; }
        .epdb-viewer-summary-line .summary-meta { color:#334E68; font-weight:650; }
        .epdb-viewer-summary-line .summary-count { color:#102F53; font-weight:900; background:#C4DBEA; border:1px solid #8EABC3; border-radius:5px; padding:2px 6px; }
        /* streamlit-antd-components tree: consistent node rhythm and selection colors */
        [data-testid="stSidebar"] .ant-tree {
            color:#26384A !important; font-size:12px !important;
            background:transparent !important; padding:2px 0 !important;
        }
        [data-testid="stSidebar"] .ant-tree-treenode {
            min-height:27px; padding:1px 0 !important;
        }
        [data-testid="stSidebar"] .ant-tree-node-content-wrapper {
            min-height:25px; line-height:25px !important; border-radius:6px !important;
            padding:0 6px !important; transition:background .12s ease,color .12s ease;
        }
        [data-testid="stSidebar"] .ant-tree-node-content-wrapper:hover {
            background:#E6EEF7 !important; color:#17365D !important;
        }
        [data-testid="stSidebar"] .ant-tree-node-content-wrapper.ant-tree-node-selected {
            background:#D4E3F2 !important; color:#123B63 !important;
            font-weight:850 !important; box-shadow:inset 3px 0 0 #245A8D;
        }
        [data-testid="stSidebar"] .ant-tree-switcher {
            color:#5D7690 !important; width:20px !important;
        }

        /* =====================================================
        LAS VIEWER — NATIVE STREAMLIT CODE BLOCK
        ===================================================== */

        [data-testid="stSidebar"] [data-testid="stCode"] {
            width: 100% !important;
            border: 1px solid #AAB8C8 !important;
            border-radius: 8px !important;
            background: #FFFFFF !important;
            overflow: hidden !important;
        }

        [data-testid="stSidebar"] [data-testid="stCode"] pre {
            white-space: pre !important;
            overflow-wrap: normal !important;
            word-break: normal !important;
            font-family: Consolas, "Courier New", monospace !important;
            font-size: 12px !important;
            line-height: 1.45 !important;
        }

        /* =====================================================
        FILE EXPLORER — TREE AND VIEWER PANELS
        ===================================================== */

        /* Hai cột Tree và Viewer */
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"]
        > div:has(.epdb-explorer-marker)
        + div [data-testid="stHorizontalBlock"]
        > [data-testid="stColumn"] {

            background: #FFFFFF !important;
            border: 1px solid #9FB2C6 !important;
            border-radius: 10px !important;
            background: linear-gradient(180deg,#FFFFFF 0%,#F9FBFD 100%) !important;

            padding: 8px !important;
            min-width: 0 !important;

            box-sizing: border-box !important;
            box-shadow: 0 2px 5px rgba(15, 23, 42, .055);
        }

        /* Nhấn màu cho khung Tree */
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"]
        > div:has(.epdb-explorer-marker)
        + div [data-testid="stHorizontalBlock"]
        > [data-testid="stColumn"]:first-child {
            border-top: 3px solid #17365D !important;
            box-shadow: 0 2px 7px rgba(23,54,93,.085) !important;
        }

        /* Nhấn màu cho khung Viewer */
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"]
        > div:has(.epdb-explorer-marker)
        + div [data-testid="stHorizontalBlock"]
        > [data-testid="stColumn"]:last-child {
            border-top: 3px solid #0F766E !important;
            box-shadow: 0 2px 7px rgba(15,118,110,.075) !important;
        }

        /* Thu gọn khoảng cách bên trong */
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"]
        > div:has(.epdb-explorer-marker)
        + div [data-testid="stHorizontalBlock"]
        > [data-testid="stColumn"] [data-testid="stVerticalBlock"] {
            gap: .35rem !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================================================
# 2. DATABASE CONNECTION AND COMMON HELPERS
# =========================================================
def resolve_db_url() -> str | None:
    """Get credentials from environment or Streamlit secrets; never embed passwords in source."""
    env_url = os.getenv("EPDB_DB_URL")
    if env_url:
        return env_url
    try:
        if st.secrets.get("DB_URL"):
            return str(st.secrets["DB_URL"])
        database_section = st.secrets.get("database", {})
        if database_section and database_section.get("url"):
            return str(database_section["url"])
    except Exception:
        pass
    return None


DB_URL = resolve_db_url()
if not DB_URL:
    st.error(
        "Chưa cấu hình kết nối PostgreSQL. Hãy đặt biến môi trường EPDB_DB_URL "
        "hoặc khai báo DB_URL trong .streamlit/secrets.toml. Không đặt mật khẩu trực tiếp trong app.py."
    )
    st.stop()

engine = create_engine(DB_URL, pool_pre_ping=True, pool_recycle=1800)

def verify_target_database(db_engine):
    expected_database = "QA QC EPDB CUULONG"

    required_tables = {
        "epdb_formation_dictionary",
        "epdb_npt_code_dictionary",
        "epdb_document_type_dictionary",
        "epdb_basin",
        "epdb_block",
        "epdb_field",
        "epdb_well",
        "epdb_borehole",
        "epdb_marker",
        "epdb_deviation",
        "epdb_checkshot",
        "epdb_log_run",
        "epdb_log_data",
        "epdb_core_cuttings_sample",
        "epdb_pvt_sample",
        "epdb_well_test",
        "epdb_casing",
        "epdb_cementing",
        "epdb_lot_fit",
        "epdb_bha",
        "epdb_npt_event",
        "epdb_completion",
        "epdb_production",
        "epdb_document",
    }

    with db_engine.connect() as conn:
        current_database = conn.execute(
            text("SELECT current_database()")
        ).scalar()

        if current_database != expected_database:
            raise RuntimeError(
                f"Đang kết nối nhầm CSDL: {current_database}. "
                f"Yêu cầu: {expected_database}"
            )

        existing_tables = set(
            conn.execute(
                text("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_type = 'BASE TABLE'
                """)
            ).scalars().all()
        )

    missing_tables = sorted(required_tables - existing_tables)

    if missing_tables:
        raise RuntimeError(
            "CSDL Cửu Long thiếu bảng: " + ", ".join(missing_tables)
        )

    return True


verify_target_database(engine)

# Chỉ tạo bảng lưu snapshot QC; không thực thi bộ luật tại thời điểm khởi động app.
@st.cache_resource
def initialize_qc_cycle_store() -> bool:
    ensure_qc_storage_tables(engine)
    return True


initialize_qc_cycle_store()


@st.cache_resource
def get_qc_background_worker(_db_engine, document_root: str, interval_hours: int):
    worker = QCBackgroundWorker(
        _db_engine,
        document_root=document_root,
        interval_hours=interval_hours,
        keep_runs=int(os.getenv("EPDB_QC_KEEP_RUNS", "20")),
    )
    worker.start()
    return worker


def read_df(sql: str, params: dict[str, Any] | None = None, con=None) -> pd.DataFrame:
    target = con if con is not None else engine
    return pd.read_sql_query(text(sql), con=target, params=params or {})


def read_scalar(sql: str, params: dict[str, Any] | None = None, default=None):
    try:
        df = read_df(sql, params=params)
        if df.empty:
            return default
        return df.iloc[0, 0]
    except Exception:
        return default


def normalize_column_name(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def ensure_unique_dataframe_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Avoid Arrow/UI failures when SQL expressions produce duplicate result labels."""
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


def _normalize_ui_label(value: Any) -> str:
    """Normalize English/Vietnamese labels for deterministic UI rules."""
    raw = str(value).strip().casefold().replace("đ", "d")
    decomposed = unicodedata.normalize("NFKD", raw)
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", ascii_text)


def _qc_status_kind(value: Any) -> str | None:
    """Classify recognised QC/AI result labels consistently across all tables.

    Matching is restricted to status/result columns and uses phrase boundaries.
    This accepts labels such as "Có lỗi - 3 bản ghi" while avoiding accidental
    matches inside unrelated words or long descriptions.
    """
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    raw = str(value).strip().casefold().replace("đ", "d")
    decomposed = unicodedata.normalize("NFKD", raw)
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    phrase = re.sub(r"[^a-z0-9]+", " ", ascii_text).strip()
    if not phrase:
        return None

    def starts_with_status(status_phrases: tuple[str, ...]) -> bool:
        for status in status_phrases:
            status_raw = status.casefold().replace("đ", "d")
            status_decomposed = unicodedata.normalize("NFKD", status_raw)
            status_ascii = "".join(ch for ch in status_decomposed if not unicodedata.combining(ch))
            status_norm = re.sub(r"[^a-z0-9]+", " ", status_ascii).strip()
            if phrase == status_norm or re.match(rf"^{re.escape(status_norm)}(?=$|[\s:;,.(/\-\d])", phrase):
                return True
        return False

    # Confirmed failures take precedence over pending/success labels.
    danger = (
        "cần xử lý", "có lỗi", "lỗi kỹ thuật", "lỗi", "không đạt",
        "chưa đạt", "không đạt yêu cầu", "không hợp lệ", "thất bại",
        "failed", "fail", "not pass", "not passed", "invalid", "abnormal",
        "bất thường", "error", "out of range", "vi phạm", "anomaly",
        "anomalous", "critical error",
    )
    if starts_with_status(danger):
        return "danger"

    warning = (
        "chưa kiểm tra", "chưa kiểm tra được", "chưa có dữ liệu", "chưa có mẫu",
        "cần kiểm tra", "cần bổ sung", "cần xác minh", "đang kiểm tra",
        "chờ xử lý", "chờ cập nhật", "chưa chạy", "pending", "not checked",
        "not assessed", "warning", "warn", "awaiting", "missing", "no data",
        "not run", "not available",
    )
    if starts_with_status(warning):
        return "warning"

    success = (
        "đã đạt", "đạt", "đạt chuẩn", "đạt yêu cầu", "pass", "passed",
        "bình thường", "normal", "hoàn thành", "không có lỗi", "không lỗi",
        "không có vi phạm", "không vi phạm", "success", "completed", "valid", "ok",
    )
    if starts_with_status(success):
        return "success"

    return None


def _qc_cell_style(value: Any) -> str:
    """Apply fill, text and left edge together as one indivisible QC-cell style."""
    kind = _qc_status_kind(value)
    if kind == "danger":
        return (
            "background-color: #FCA5A5 !important; color: #7F1D1D !important; "
            "font-weight: 900 !important; border-left: 4px solid #B91C1C !important;"
        )
    if kind == "warning":
        return (
            "background-color: #FDE68A !important; color: #78350F !important; "
            "font-weight: 900 !important; border-left: 4px solid #B45309 !important;"
        )
    if kind == "success":
        return (
            "background-color: #BBF7D0 !important; color: #14532D !important; "
            "font-weight: 850 !important; border-left: 4px solid #15803D !important;"
        )
    return ""


def _qc_row_style(row: pd.Series) -> list[str]:
    """Keep data rows neutral; status/count cells carry the only QC emphasis."""
    return [""] * len(row)


def _is_qc_status_column(column: Any) -> bool:
    """Recognise status/result columns, excluding the removed rule-severity field."""
    normalized = _normalize_ui_label(column)
    exact = {
        "ketqua", "ketquaqc", "ketquakiemtra", "ketquathuchien",
        "trangthai", "trangthaiqc", "trangthaikiemtra", "tinhtrang",
        "qcstatus", "qcresult", "checkstatus", "checkresult",
        "resultstatus", "status", "result", "predictionlabel",
        "phanloai", "phanloaiAI",
    }
    if normalized in exact:
        return True
    return normalized.startswith((
        "ketqua", "trangthai", "tinhtrang", "qcstatus", "qcresult",
        "checkstatus", "checkresult", "resultstatus", "phanloai",
    ))


def _is_internal_id_column(column: Any) -> bool:
    """Return True for database-only identifiers that should not be exposed in UI tables.

    This is strictly a presentation filter. The source DataFrame, SQL queries,
    joins, QC matching and session-state identifiers remain unchanged.
    """
    raw = str(column).strip()
    if not raw:
        return False
    # Split snake_case, kebab-case, spaced and CamelCase names into tokens.
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", raw)
    tokens = [t for t in re.split(r"[^a-zA-Z0-9]+", camel_split.casefold()) if t]
    normalized = _normalize_ui_label(raw)
    technical_tokens = {"id", "uid", "uuid", "guid", "uwi", "ubhi", "identifier", "identifiers"}
    if technical_tokens.intersection(tokens):
        return True
    # EPDB well/borehole identity keys are also database join identifiers.
    if normalized in {"uwi", "ubhi", "unique well identifier", "uniquewellidentifier", "uniqueboreholeidentifier"}:
        return True
    # Common compact DB key names without separators (wellID, boreholeId, etc.).
    compact_key_prefixes = (
        "basinid", "blockid", "fieldid", "wellid", "boreholeid", "documentid",
        "logid", "curveid", "sampleid", "seismicid", "productionid", "runid",
        "ruleid", "alertid", "resultid", "datasetid", "metadataid", "fileid",
        "recordid", "userid", "createdbyid", "updatedbyid",
    )
    return normalized in compact_key_prefixes


def hide_internal_id_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Create a display-only copy without database surrogate/relationship IDs."""
    if df is None or df.empty or len(df.columns) == 0:
        return df
    visible_columns = [column for column in df.columns if not _is_internal_id_column(column)]
    if len(visible_columns) == len(df.columns):
        return df
    return df.loc[:, visible_columns].copy()


def _is_violation_count_column(column: Any) -> bool:
    """Recognise actual QC issue counters without matching unrelated numeric fields.

    Vietnamese labels are token-checked so "Lỗi kỹ thuật" is not mistaken for
    a count, while "Số luật có lỗi" and "Bản ghi / lượt vi phạm" are recognised.
    """
    raw = str(column).strip().casefold().replace("đ", "d")
    decomposed = unicodedata.normalize("NFKD", raw)
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    tokens = set(re.findall(r"[a-z0-9]+", ascii_text))
    compact = re.sub(r"[^a-z0-9]", "", ascii_text)

    exact_names = {
        "luotvipham", "luotviphamphambanghi", "banghiluotvipham",
        "sobanghiluotvipham", "sobanghivipham", "banghivipham",
        "sobanghiloi", "banghiloi", "soloi", "soluongloi",
        "soluongbanghiloi", "sovipham", "soluongvipham",
        "luatcoloi", "soluatcoloi", "soluatvipham",
        "soviolation", "violationcount", "totalviolations",
        "numberofviolations", "qcviolations", "ruleviolationcount",
        "issuecount", "errorcount", "failedcount", "anomalycount",
        "recordviolations", "recordviolationcount", "errorrecords",
        "failedrecords", "failedrows", "violatingrecords",
        "tongsoloi", "tongvipham", "tongluotvipham",
    }
    if compact in exact_names:
        return True

    # Count context is mandatory: the presence of "lỗi" alone is insufficient.
    count_tokens = {
        "so", "luot", "banghi", "luat", "soluong", "tong", "total",
        "count", "number", "records", "record", "rows", "failed", "issue",
    }
    has_count_context = bool(tokens.intersection(count_tokens)) or {"ban", "ghi"}.issubset(tokens)
    has_vietnamese_issue = "vipham" in compact or "loi" in compact
    has_english_issue = any(token in tokens for token in ("violation", "violations", "error", "errors", "anomaly", "anomalies"))
    return has_count_context and (has_vietnamese_issue or has_english_issue)


def _qc_violation_count_style(value: Any) -> str:
    """Use the same whole-cell failure treatment for every positive/invalid count.

    A zero is neutral grey; blanks and non-numeric values remain unstyled. A
    negative count is also red because it is an invalid counter value.
    """
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return ""
    if float(numeric) != 0:
        return (
            _qc_cell_style("Có lỗi")
            + " text-align: center !important; font-variant-numeric: tabular-nums;"
        )
    return (
        "background-color: #E2E8F0 !important; color: #475569 !important; "
        "font-weight: 750 !important; border-left: 4px solid #94A3B8 !important; "
        "text-align: center !important; font-variant-numeric: tabular-nums;"
    )


def style_qc_table(df: pd.DataFrame, highlight_first_column: bool = False):
    """Build a Styler with one consistent whole-cell signal for QC status/count.

    The first data row is not specially highlighted. Status/count styling takes
    precedence over optional first-column emphasis, avoiding stacked cell styles.
    Header styling is applied by render_interactive_table().
    """
    if df is None or df.empty:
        return df

    table_cells = int(len(df.index) * len(df.columns))
    current_limit = int(pd.get_option("styler.render.max_elements"))
    if table_cells >= current_limit:
        pd.set_option("styler.render.max_elements", table_cells + 1)

    styled_frame = df.copy(deep=False)
    styled_frame.index = pd.RangeIndex(len(styled_frame))

    first_column_css = (
        "font-weight: 850; background-color: #C7D9EC; color: #17365D;"
    )
    status_positions = [
        pos for pos, column in enumerate(styled_frame.columns)
        if _is_qc_status_column(column)
    ]
    violation_count_positions = [
        pos for pos, column in enumerate(styled_frame.columns)
        if _is_violation_count_column(column)
    ]

    def _build_cell_style_matrix(data: pd.DataFrame) -> pd.DataFrame:
        styles = pd.DataFrame("", index=data.index, columns=data.columns, dtype=object)
        for row_position in range(len(data.index)):
            for column_position, value in enumerate(data.iloc[row_position].tolist()):
                # One cell receives one coherent treatment. QC state/count always
                # overrides optional first-column emphasis; do not stack competing
                # background/border rules on the same cell.
                cell_css = ""
                if column_position in status_positions:
                    cell_css = _qc_cell_style(value)
                elif column_position in violation_count_positions:
                    cell_css = _qc_violation_count_style(value)
                elif highlight_first_column and column_position == 0:
                    cell_css = first_column_css
                styles.iat[row_position, column_position] = cell_css
        return styles

    return styled_frame.style.apply(_build_cell_style_matrix, axis=None)


def render_interactive_table(
    df: pd.DataFrame,
    *,
    height: int = 320,
    highlight_first_column: bool = False,
) -> None:
    """Render a styled table with clickable sorting and drag-to-reorder columns.

    A native Streamlit dataframe is virtualized on a canvas and does not expose a
    supported way to style its header cells. This renderer styles real HTML header
    cells and restores the two interactions requested here: sort by clicking a
    header and reorder columns by dragging a header. Data values are HTML-escaped
    by Pandas Styler before being embedded in the isolated component iframe.
    """
    if df is None or df.empty:
        st.info("Không có dữ liệu để hiển thị.")
        return

    display_df = hide_internal_id_columns(df)
    if display_df is None or len(display_df.columns) == 0:
        st.info("Không có trường dữ liệu hiển thị cho bảng này.")
        return

    table_height = max(110, min(int(height), 1200))
    styled = style_qc_table(display_df, highlight_first_column=highlight_first_column)
    if not hasattr(styled, "to_html"):
        st.info("Không thể tạo bảng tương tác cho dữ liệu này.")
        return

    styled = styled.hide(axis="index")
    # Render selected depth/elevation/coordinate columns with at most 2 decimals.
    # Underlying DataFrame values remain numeric, so browser-side sorting stays numeric.
    precision_two_columns = {
        "md", "mdm", "measureddepth", "measureddepthm",
        "tvd", "tvdm", "trueverticaldepth", "trueverticaldepthm",
        "kb", "kbm", "kbelevation", "kbelevationm", "kellybushingelevation", "elevation",
        "x", "xm", "xcoordinate", "xcoordinatem", "easting",
        "y", "ym", "ycoordinate", "ycoordinatem", "northing",
    }

    def _format_max_two_decimals(value):
        if value is None:
            return ""
        try:
            if pd.isna(value):
                return ""
        except (TypeError, ValueError):
            pass
        numeric_value = pd.to_numeric(value, errors="coerce")
        if pd.isna(numeric_value):
            return value
        rendered = f"{float(numeric_value):,.2f}".rstrip("0").rstrip(".")
        return rendered

    numeric_formatters = {
        column: _format_max_two_decimals
        for column in display_df.columns
        if normalize_column_name(column) in precision_two_columns
    }

    # Escape cell values and column labels from uploaded/database content before
    # placing the rendered table inside the component iframe.
    styled = styled.format(formatter=numeric_formatters, escape="html").format_index(escape="html", axis="columns")
    styled = styled.set_table_attributes('class="epdb-qc-html-table"')
    styled = styled.set_table_styles(
        [
            {
                "selector": "table",
                "props": [
                    ("width", "100%"),
                    ("min-width", "100%"),
                    ("border-collapse", "separate"),
                    ("border-spacing", "0"),
                    ("table-layout", "auto"),
                    ("font-family", "Arial, sans-serif"),
                    ("font-size", "12px"),
                    ("color", "#243B53"),
                ],
            },
            {
                "selector": "thead th, thead th.col_heading",
                "props": [
                    ("background-color", "#B8CDE3"),
                    ("color", "#102F53"),
                    ("font-weight", "900"),
                    ("font-size", "12px"),
                    ("border-bottom", "2px solid #315F8C"),
                    ("border-right", "1px solid #9FB5CC"),
                    ("padding", "10px 11px"),
                    ("text-align", "left"),
                    ("white-space", "nowrap"),
                    ("position", "sticky"),
                    ("top", "0"),
                    ("z-index", "3"),
                    ("cursor", "pointer"),
                    ("user-select", "none"),
                ],
            },
            {
                "selector": "thead th:hover",
                "props": [
                    ("background-color", "#9FBAD6"),
                ],
            },
            {
                "selector": "tbody td",
                "props": [
                    ("padding", "8px 10px"),
                    ("border-bottom", "1px solid #D7E0EA"),
                    ("border-right", "1px solid #E1E8F0"),
                    ("background-color", "#FFFFFF"),
                    ("color", "#243B53"),
                    ("vertical-align", "top"),
                    ("white-space", "normal"),
                    ("overflow-wrap", "anywhere"),
                ],
            },
        ],
        overwrite=False,
    )

    html_table = styled.to_html(escape="html")
    # Give every column an initial practical width, then expose a draggable
    # resize handle on each real HTML header cell. Widths remain within this
    # rendered table and do not alter the underlying DataFrame/database.
    column_widths = []
    for column in display_df.columns:
        samples = display_df[column].dropna().astype(str).head(80).tolist()
        max_chars = max([len(str(column)), *(len(value) for value in samples)], default=12)
        column_widths.append(max(112, min(340, max_chars * 7 + 34)))
    colgroup_html = "<colgroup>" + "".join(
        f'<col style="width:{width}px;min-width:72px">' for width in column_widths
    ) + "</colgroup>"
    html_table = re.sub(
        r"(<table\b[^>]*>)",
        lambda match: match.group(1) + colgroup_html,
        html_table,
        count=1,
    )
    total_table_width = max(100, sum(column_widths))
    html_table = re.sub(
        r"(<table\b[^>]*)(>)",
        lambda match: match.group(1) + f' style="width:{total_table_width}px;min-width:{total_table_width}px;table-layout:fixed;"' + match.group(2),
        html_table,
        count=1,
    )
    html_document = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
html, body {{ margin:0; padding:0; width:100%; height:100%; background:transparent; overflow:hidden; }}
.epdb-table-scroll {{ width:100%; height:{max(90, table_height - 4)}px; overflow:auto; border:1px solid #AEBFD1; border-radius:8px; background:#FFFFFF; box-shadow:0 1px 3px rgba(15,23,42,.06); }}
.epdb-qc-html-table {{ width:max(100%, {total_table_width}px); min-width:{total_table_width}px; table-layout:fixed; }}
.epdb-qc-html-table thead th {{ box-shadow: inset 0 -1px 0 #315F8C; position:sticky; }}
.epdb-qc-html-table thead th .epdb-col-resize-handle {{ position:absolute; top:0; right:-2px; width:8px; height:100%; z-index:7; cursor:col-resize; touch-action:none; user-select:none; }}
.epdb-qc-html-table thead th .epdb-col-resize-handle:hover {{ background:rgba(23,54,93,.22); }}
body.epdb-resizing, body.epdb-resizing * {{ cursor:col-resize !important; user-select:none !important; }}
.epdb-qc-html-table thead th[data-sort="asc"]::after {{ content:"  ▲"; color:#17365D; font-size:10px; }}
.epdb-qc-html-table thead th[data-sort="desc"]::after {{ content:"  ▼"; color:#17365D; font-size:10px; }}
.epdb-qc-html-table thead th.dragging {{ opacity:.55; }}
.epdb-qc-html-table thead th.drop-target {{ outline:2px dashed #245A8D; outline-offset:-3px; }}
</style>
</head>
<body>
<div class="epdb-table-scroll">{html_table}</div>
<script>
(function() {{
  const table = document.querySelector('.epdb-qc-html-table');
  if (!table || !table.tHead || !table.tBodies.length) return;
  const headerRow = table.tHead.rows[0];
  const body = table.tBodies[0];
  const colGroup = table.querySelector('colgroup');
  const colElements = colGroup ? Array.from(colGroup.children) : [];
  const collator = new Intl.Collator('vi', {{numeric:true, sensitivity:'base'}});
  let dragged = false;
  let dragFrom = -1;

  function columnWidthTotal() {{
    return colElements.reduce((sum, col) => sum + Math.max(72, parseFloat(col.style.width) || 112), 0);
  }}

  function updateTableWidth() {{
    if (!colElements.length) return;
    const total = columnWidthTotal();
    table.style.width = Math.max(total, scrollContainer.clientWidth) + 'px';
    table.style.minWidth = total + 'px';
  }}

  function fitTableToAvailableWidth() {{
    if (!colElements.length) return;
    const currentTotal = columnWidthTotal();
    const available = scrollContainer.clientWidth;
    if (available > currentTotal) {{
      const extraPerColumn = (available - currentTotal) / colElements.length;
      colElements.forEach((col) => {{
        const current = Math.max(72, parseFloat(col.style.width) || 112);
        col.style.width = (current + extraPerColumn) + 'px';
      }});
    }}
    updateTableWidth();
  }}

  function attachResizeHandle(header) {{
    const handle = document.createElement('span');
    handle.className = 'epdb-col-resize-handle';
    handle.setAttribute('aria-label', 'Kéo để chỉnh độ rộng cột');
    handle.title = 'Kéo để chỉnh độ rộng cột';
    handle.draggable = false;
    handle.addEventListener('click', (event) => {{
      event.preventDefault();
      event.stopPropagation();
    }});
    handle.addEventListener('pointerdown', (event) => {{
      event.preventDefault();
      event.stopPropagation();
      const columnIndex = header.cellIndex;
      const col = colElements[columnIndex];
      if (!col) return;
      const startX = event.clientX;
      const startWidth = Math.max(72, col.getBoundingClientRect().width || header.getBoundingClientRect().width);
      document.body.classList.add('epdb-resizing');
      const onMove = (moveEvent) => {{
        const nextWidth = Math.max(72, Math.min(900, startWidth + moveEvent.clientX - startX));
        col.style.width = nextWidth + 'px';
        col.style.minWidth = '72px';
        updateTableWidth();
      }};
      const onUp = () => {{
        document.removeEventListener('pointermove', onMove);
        document.removeEventListener('pointerup', onUp);
        document.body.classList.remove('epdb-resizing');
        fitTableToAvailableWidth();
      }};
      document.addEventListener('pointermove', onMove);
      document.addEventListener('pointerup', onUp, {{once:true}});
    }});
    header.appendChild(handle);
  }}

  function normalizedValue(raw) {{
    const value = (raw || '').replace(/\\u00a0/g, ' ').trim();
    if (!value || value === '—' || value === '-' || value.toLowerCase() === 'nan' || value.toLowerCase() === 'none')
      return {{kind:'empty', value:''}};
    const dateLike = /^\\d{{4}}[-/]\\d{{1,2}}[-/]\\d{{1,2}}(?:[ T].*)?$/.test(value);
    if (dateLike) {{
      const timestamp = Date.parse(value);
      if (!Number.isNaN(timestamp)) return {{kind:'date', value:timestamp}};
    }}
    const dmy = value.match(/^(\\d{{1,2}})\\/(\\d{{1,2}})\\/(\\d{{4}})(?:\\s+(.*))?$/);
    if (dmy) {{
      const timestamp = new Date(Number(dmy[3]), Number(dmy[2]) - 1, Number(dmy[1])).getTime();
      if (!Number.isNaN(timestamp)) return {{kind:'date', value:timestamp}};
    }}
    let numeric = value.replace(/\\s/g, '');
    const numericPattern = /^[+-]?(?:\\d+|\\d{{1,3}}(?:[.,]\\d{{3}})+)(?:[.,]\\d+)?$/;
    if (numericPattern.test(numeric)) {{
      if (numeric.includes(',') && numeric.includes('.')) {{
        if (numeric.lastIndexOf(',') > numeric.lastIndexOf('.'))
          numeric = numeric.replace(/\\./g, '').replace(',', '.');
        else
          numeric = numeric.replace(/,/g, '');
      }} else if (numeric.includes(',')) {{
        numeric = numeric.replace(',', '.');
      }} else if ((numeric.match(/\\./g) || []).length > 1) {{
        numeric = numeric.replace(/\\./g, '');
      }}
      const number = Number(numeric);
      if (Number.isFinite(number)) return {{kind:'number', value:number}};
    }}
    return {{kind:'text', value:value}};
  }}

  Array.from(body.rows).forEach((row, index) => {{
    row.dataset.epdbOriginalIndex = String(index);
  }});

  headerRow.querySelectorAll('th').forEach((header) => {{
    header.draggable = true;
    header.removeAttribute('title');
    attachResizeHandle(header);
    header.addEventListener('dblclick', (event) => {{
      event.preventDefault();
      event.stopPropagation();
      const originalRows = Array.from(body.rows).sort((a, b) =>
        Number(a.dataset.epdbOriginalIndex || 0) - Number(b.dataset.epdbOriginalIndex || 0)
      );
      originalRows.forEach((row) => body.appendChild(row));
      headerRow.querySelectorAll('th').forEach((item) => delete item.dataset.sort);
    }});
    header.addEventListener('click', (event) => {{
      if (dragged || event.target.closest('.epdb-col-resize-handle')) return;
      const columnIndex = header.cellIndex;
      const direction = header.dataset.sort === 'asc' ? 'desc' : 'asc';
      headerRow.querySelectorAll('th').forEach((other) => {{
        if (other !== header) delete other.dataset.sort;
      }});
      header.dataset.sort = direction;
      const rows = Array.from(body.rows).map((row, index) => ({{row, index}}));
      rows.sort((left, right) => {{
        const a = normalizedValue(left.row.cells[columnIndex]?.innerText || '');
        const b = normalizedValue(right.row.cells[columnIndex]?.innerText || '');
        if (a.kind === 'empty' && b.kind !== 'empty') return 1;
        if (b.kind === 'empty' && a.kind !== 'empty') return -1;
        let result = 0;
        if (a.kind === b.kind && (a.kind === 'number' || a.kind === 'date'))
          result = a.value < b.value ? -1 : (a.value > b.value ? 1 : 0);
        else
          result = collator.compare(String(a.value), String(b.value));
        if (result === 0) return left.index - right.index;
        return direction === 'asc' ? result : -result;
      }});
      rows.forEach((item) => body.appendChild(item.row));
    }});
    header.addEventListener('dragstart', (event) => {{
      dragged = false;
      dragFrom = header.cellIndex;
      header.classList.add('dragging');
      if (event.dataTransfer) {{
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', String(dragFrom));
      }}
    }});
    header.addEventListener('dragover', (event) => {{
      event.preventDefault();
      header.classList.add('drop-target');
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    }});
    header.addEventListener('dragleave', () => header.classList.remove('drop-target'));
    header.addEventListener('drop', (event) => {{
      event.preventDefault();
      headerRow.querySelectorAll('th').forEach((item) => item.classList.remove('drop-target'));
      const from = dragFrom;
      const to = header.cellIndex;
      if (from < 0 || to < 0 || from === to) return;
      const allRows = [headerRow, ...Array.from(body.rows)];
      allRows.forEach((row) => {{
        const movingCell = row.children[from];
        const targetCell = row.children[to];
        if (!movingCell || !targetCell) return;
        if (from < to) row.insertBefore(movingCell, targetCell.nextSibling);
        else row.insertBefore(movingCell, targetCell);
      }});
      // Keep the width definitions aligned with the reordered header/body cells.
      if (colGroup && colElements[from] && colElements[to]) {{
        const movingCol = colElements[from];
        const targetCol = colElements[to];
        if (from < to) colGroup.insertBefore(movingCol, targetCol.nextSibling);
        else colGroup.insertBefore(movingCol, targetCol);
        colElements.splice(from, 1);
        colElements.splice(to, 0, movingCol);
      }}
      updateTableWidth();
      dragged = true;
      headerRow.querySelectorAll('th').forEach((item) => delete item.dataset.sort);
    }});
    header.addEventListener('dragend', () => {{
      headerRow.querySelectorAll('th').forEach((item) => item.classList.remove('dragging', 'drop-target'));
      window.setTimeout(() => {{ dragged = false; dragFrom = -1; }}, 0);
    }});
  }});
  requestAnimationFrame(() => requestAnimationFrame(fitTableToAvailableWidth));
}})();
</script>
</body>
</html>"""
    st.components.v1.html(html_document, height=table_height, scrolling=False)


def render_styled_html_table(
    df: pd.DataFrame,
    *,
    height: int = 260,
    highlight_first_column: bool = False,
) -> None:
    """Backward-compatible wrapper for the interactive table renderer."""
    render_interactive_table(
        df,
        height=height,
        highlight_first_column=highlight_first_column,
    )

def format_integer_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Ép các cột số lượng/vi phạm về kiểu Int64 chuẩn để tránh hiển thị .000 hoặc .0"""
        if df is None or df.empty:
            return df
        res = df.copy()
        int_cols = [
            "Mẫu đánh giá", "Bản ghi / lượt vi phạm", "Lượt vi phạm", 
            "Đối tượng liên quan", "Đối tượng ảnh hưởng", "Số luật", "Luật có lỗi", "Chưa kiểm tra được", "Chưa có mẫu"
        ]
        for col in int_cols:
            if col in res.columns:
                res[col] = pd.to_numeric(res[col], errors="coerce").fillna(0).astype("Int64")
        return res


def render_alert_metric_card(label: str, value: Any) -> None:
    """Render a responsive red metric for a QC issue count."""
    safe_label = html.escape(str(label))
    safe_value = html.escape(str(value))
    st.markdown(
        '<div class="epdb-alert-metric">'
        f'<div class="epdb-alert-metric-label">{safe_label}</div>'
        f'<div class="epdb-alert-metric-value">{safe_value}</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def find_dataframe_column(df: pd.DataFrame, aliases: list[str]) -> str | None:
    lookup = {normalize_column_name(col): col for col in df.columns}
    for alias in aliases:
        key = normalize_column_name(alias)
        if key in lookup:
            return lookup[key]
    return None


@st.cache_data(ttl=60)
def get_master_data() -> pd.DataFrame:
    """
    Load hierarchy from the fixed Cuu Long EPDB schema.

    Compatibility aliases:
        uwi  = well_code
        ubhi = wellbore_code

    The aliases exist only in the application DataFrame.
    They are not physical PostgreSQL columns.
    """

    sql = """
        SELECT
            ba.basin_id,
            ba.basin_name,
            ba.country,

            bl.block_id,
            bl.block_code,
            COALESCE(
                NULLIF(BTRIM(bl.block_name), ''),
                bl.block_code
            ) AS block_name,
            bl.operator,

            f.field_id,
            f.field_code,
            f.field_name,

            w.well_id,
            w.well_code::text AS well_code,
            w.well_code::text AS uwi,
            COALESCE(
                NULLIF(BTRIM(w.well_name), ''),
                w.well_code
            ) AS well_name,
            w.well_type,
            w.status AS well_status,
            w.surface_latitude,
            w.surface_longitude,
            w.water_depth_m,
            w.ground_elevation_m,
            w.spud_date,
            w.rig_name,

            b.wellbore_id,
            b.wellbore_id AS borehole_id,
            b.well_id AS borehole_well_id,
            b.wellbore_code::text AS wellbore_code,
            b.wellbore_code::text AS ubhi,
            b.wellbore_code::text AS borehole_name,
            b.wellbore_type AS borehole_type,
            b.td_md_m AS td,
            b.td_tvd_m,
            b.kickoff_depth_md,
            b.completion_date,
            b.status AS wellbore_status

        FROM public.epdb_basin ba

        LEFT JOIN public.epdb_block bl
            ON bl.basin_id = ba.basin_id

        LEFT JOIN public.epdb_field f
            ON f.block_id = bl.block_id

        LEFT JOIN public.epdb_well w
            ON w.field_id = f.field_id

        LEFT JOIN public.epdb_borehole b
            ON b.well_id = w.well_id

        ORDER BY
            ba.basin_id,
            bl.block_id,
            f.field_id,
            w.well_id,
            b.wellbore_id
    """

    return read_df(sql)


@st.cache_data(ttl=300, show_spinner=False)
def get_well_map_coordinates() -> pd.DataFrame:
    return read_df("""
        SELECT
            COALESCE(
                NULLIF(BTRIM(well_name), ''),
                well_code
            ) AS well_name,
            surface_latitude::double precision AS lat,
            surface_longitude::double precision AS lon
        FROM public.epdb_well
        WHERE surface_latitude IS NOT NULL
          AND surface_longitude IS NOT NULL
    """)


@st.cache_data(ttl=60, show_spinner=False)
def get_asset_display_name_lookups() -> tuple[pd.DataFrame, pd.DataFrame]:

    well_lookup = read_df("""
        SELECT
            well_code::text AS uwi,
            COALESCE(
                NULLIF(BTRIM(well_name), ''),
                well_code
            ) AS well_name
        FROM public.epdb_well
        WHERE well_code IS NOT NULL
    """)

    bh_lookup = read_df("""
        SELECT
            wellbore_code::text AS ubhi,
            wellbore_code::text AS borehole_name
        FROM public.epdb_borehole
        WHERE wellbore_code IS NOT NULL
    """)

    well_lookup = well_lookup.drop_duplicates("uwi")
    bh_lookup = bh_lookup.drop_duplicates("ubhi")

    return well_lookup, bh_lookup


def _apply_asset_display_name_lookups(master: pd.DataFrame) -> pd.DataFrame:
    """Fill missing hierarchy names from direct master-table lookups."""
    if master is None or master.empty:
        return master
    result = master.copy()
    try:
        well_lookup, bh_lookup = get_asset_display_name_lookups()

        def _first_valid_map(lookup: pd.DataFrame, key_col: str, name_col: str) -> dict[str, str]:
            mapping: dict[str, str] = {}
            if lookup is None or lookup.empty or not {key_col, name_col}.issubset(lookup.columns):
                return mapping
            for _, row in lookup.iterrows():
                key = str(row.get(key_col, "") or "").strip().casefold()
                name = str(row.get(name_col, "") or "").strip()
                if key and key not in {"nan", "none", "null", "<na>"} and name and name.casefold() not in {"nan", "none", "null", "<na>"}:
                    mapping.setdefault(key, name)
            return mapping

        well_map = _first_valid_map(well_lookup, "uwi", "well_name")
        bh_map = _first_valid_map(bh_lookup, "ubhi", "borehole_name")

        if "uwi" in result.columns:
            mapped = result["uwi"].map(lambda value: well_map.get(str(value).strip().casefold()) if pd.notna(value) else None)
            if "well_name" not in result.columns:
                result["well_name"] = mapped
            else:
                current = result["well_name"].map(lambda value: str(value).strip() if pd.notna(value) else "")
                invalid = current.str.casefold().isin(["", "nan", "none", "null", "<na>"])
                result.loc[invalid, "well_name"] = mapped.loc[invalid]

        if "ubhi" in result.columns:
            mapped = result["ubhi"].map(lambda value: bh_map.get(str(value).strip().casefold()) if pd.notna(value) else None)
            if "borehole_name" not in result.columns:
                result["borehole_name"] = mapped
            else:
                current = result["borehole_name"].map(lambda value: str(value).strip() if pd.notna(value) else "")
                invalid = current.str.casefold().isin(["", "nan", "none", "null", "<na>"])
                result.loc[invalid, "borehole_name"] = mapped.loc[invalid]
    except Exception as exc:
        # Do not break application startup if optional presentation lookup fails;
        # the original hierarchy frame remains usable and error is logged once.
        st.warning(f"Không tải được ánh xạ tên Giếng/Thân giếng trực tiếp: {type(exc).__name__}: {exc}")
    return result


try:
    df_master = get_master_data()
    df_master = _apply_asset_display_name_lookups(df_master)
except Exception as exc:
    st.error(f"Không thể tải danh mục EPDB: {type(exc).__name__}: {exc}")
    st.stop()

wells_with_logs_count = 0  # populated after database schema introspection below


@st.cache_data(show_spinner=False)
def load_geojson_data(filepath: str) -> dict:
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"type": "FeatureCollection", "features": []}
    return {"type": "FeatureCollection", "features": []}


VN_BLOCKS_GEOJSON = load_geojson_data(str(GEOJSON_FILE_PATH))

# =========================================================
# 3. SCHEMA HELPERS / CENTRAL QC ENGINE
# =========================================================
@st.cache_resource
def get_schema_inspector():
    return sqlalchemy_inspect(engine)


inspector = get_schema_inspector()


@st.cache_data(ttl=300, show_spinner=False)
def table_exists(table_name: str) -> bool:
    try:
        return bool(inspector.has_table(table_name))
    except Exception:
        return False


@st.cache_data(ttl=300, show_spinner=False)
def table_columns(table_name: str) -> dict[str, str]:
    """Ưu tiên tên cột chuẩn snake_case khi có tên legacy tương tự."""
    try:
        result: dict[str, str] = {}

        for item in inspector.get_columns(table_name):
            actual = str(item["name"])
            key = normalize_column_name(actual)
            previous = result.get(key)

            # Ví dụ: ưu tiên survey_name thay vì surveyname.
            if previous is None or ("_" in actual and "_" not in previous):
                result[key] = actual

        return result
    except Exception:
        return {}


@st.cache_data(ttl=300, show_spinner=False)
def get_all_table_names_cached() -> tuple[str, ...]:
    try:
        return tuple(inspector.get_table_names())
    except Exception:
        return tuple()


@st.cache_data(ttl=15, show_spinner=False)
def get_latest_ai_run_id_cached() -> str | None:
    if not table_exists("epdb_ai_las_v4_runs"):
        return None
    return read_scalar(
        "SELECT run_id FROM epdb_ai_las_v4_runs WHERE status='completed' ORDER BY completed_at DESC LIMIT 1",
        default=None,
    )

@st.cache_data(ttl=300, show_spinner=False)
def count_wells_with_logs() -> int:
    sql = """
        SELECT COUNT(DISTINCT b.well_id)
        FROM public.epdb_log_data l
        JOIN public.epdb_borehole b
            ON b.wellbore_id = l.wellbore_id
        WHERE l.wellbore_id IS NOT NULL
    """

    return int(read_scalar(sql, default=0) or 0)


wells_with_logs_count = count_wells_with_logs()


def col_ref(alias: str, actual_name: str) -> str:
    return f"{alias}.{quote_ident(actual_name)}"


def build_qc_checks() -> list[dict[str, Any]]:
    try:
        inspector.clear_cache()
    except Exception:
        pass
    return build_checks_150(table_exists, table_columns, normalize_column_name, quote_ident)


@st.cache_data(ttl=3, show_spinner=False)
def load_qc_summary_cached(cache_key: str):
    """Chỉ đọc snapshot tổng hợp; chi tiết vi phạm được tải theo rule khi cần."""
    return load_latest_qc_summary(engine)


def get_qc_snapshot():
    cache_key = str(st.session_state.get("qc_snapshot_cache_key", "initial"))
    summary, failures, entities, meta = load_qc_summary_cached(cache_key)
    return summary, {}, failures, entities, meta


def execute_qc_checks(
    cache_key: str = "epdb_qc_cycle_snapshot_v1"
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], list[str], set[str]]:
    """Giữ tương thích tên hàm cũ; chỉ đọc summary, không tải toàn bộ detail JSON."""
    summary, _, failures, entities, _ = get_qc_snapshot()
    return summary, {}, failures, entities


@st.cache_data(ttl=300, show_spinner=False)
def load_qc_rule_detail_cached(run_id: str, rule_id: str) -> pd.DataFrame:
    """Chỉ tải các bản ghi vi phạm của đúng luật đang được người dùng chọn."""
    return load_qc_rule_detail(engine, run_id, rule_id)


@st.cache_data(ttl=30, show_spinner=False)
def load_qc_well_summary_cached(run_id: str, uwi: str, ubhi: str | None) -> pd.DataFrame:
    """Read precomputed well QC from one completed full-system QC cycle."""
    return load_qc_well_summary(engine, run_id, uwi, ubhi)


def filter_qc_detail_for_well(
        detail: pd.DataFrame,
        selected_uwi: str,
        selected_ubhi: str | None,
        well_ubhis: list[str],
        selected_well_name: str | None = None,
        selected_well_id: Any = None,
        selected_borehole_id: Any = None,
    ) -> pd.DataFrame:

    if detail is None or detail.empty:
        return pd.DataFrame()

    result = ensure_unique_dataframe_columns(detail.copy())

    col_lookup = {
        normalize_column_name(c): c
        for c in result.columns
    }

    wellbore_id_col = col_lookup.get("wellboreid")
    well_id_col = col_lookup.get("wellid")

    # Borehole-level violation.
    if selected_borehole_id is not None and wellbore_id_col:
        mask = (
            result[wellbore_id_col]
            .astype(str)
            .str.strip()
            .eq(str(selected_borehole_id).strip())
        )
        return result.loc[mask].copy()

    # Well-level violation.
    if selected_well_id is not None and well_id_col:
        mask = (
            result[well_id_col]
            .astype(str)
            .str.strip()
            .eq(str(selected_well_id).strip())
        )
        return result.loc[mask].copy()

    # Legacy compatibility fallback.
    uwi_col = col_lookup.get("uwi")
    ubhi_col = col_lookup.get("ubhi")

    if selected_ubhi and ubhi_col:
        return result.loc[
            result[ubhi_col].astype(str).str.strip()
            == str(selected_ubhi).strip()
        ].copy()

    if uwi_col:
        return result.loc[
            result[uwi_col].astype(str).str.strip()
            == str(selected_uwi).strip()
        ].copy()

    return pd.DataFrame()



# =========================================================
# 4. DQS CALCULATOR — SIX DIMENSIONS, AUDITABLE DENOMINATORS
# =========================================================
def calculate_dqs(summary: pd.DataFrame | None = None) -> dict[str, Any]:
    """Calculate DQS from the completed QC snapshot already loaded by the dashboard."""
    dims: dict[str, float | None] = {k: None for k in DQS_WEIGHTS}
    diagnostics: list[str] = []
    if summary is None:
        try:
            summary, _, _, _ = execute_qc_checks()
        except Exception as exc:
            return {
                "scores": dims, "final_score": None,
                "diagnostics": [f"Không đọc được snapshot QC: {type(exc).__name__}: {exc}"],
                "available_dimensions": 0,
            }
    if summary is None:
        summary = pd.DataFrame()
    if summary.empty:
        return {"scores": dims, "final_score": None, "diagnostics": ["Danh mục QC chưa có kết quả."], "available_dimensions": 0}

    checked_statuses = {"Đạt", "Có lỗi"}
    rule_scores: dict[str, list[float]] = {k: [] for k in DQS_WEIGHTS}
    for _, row in summary.iterrows():
        if str(row.get("Kết quả", "")) not in checked_statuses:
            continue
        try:
            population = int(row.get("Mẫu đánh giá") or 0)
            issue_count = int(row.get("Bản ghi / lượt vi phạm") or 0)
        except (TypeError, ValueError):
            continue
        if population <= 0:
            continue
        score = round(100.0 * (1.0 - min(max(issue_count, 0), population) / population), 2)
        dimensions = [d.strip() for d in str(row.get("Chiều DQS", "") or "").split(",")]
        for dimension in dimensions:
            if dimension in rule_scores:
                rule_scores[dimension].append(score)

    for dim, scores in rule_scores.items():
        if scores:
            dims[dim] = round(float(np.mean(scores)), 2)
    available = [d for d, value in dims.items() if value is not None and DQS_WEIGHTS.get(d, 0) > 0]
    if available:
        weights_total = sum(DQS_WEIGHTS[d] for d in available)
        final_score = round(sum(float(dims[d]) * DQS_WEIGHTS[d] for d in available) / weights_total, 2)
    else:
        final_score = None

    checked_rules = int(summary["Kết quả"].isin(checked_statuses).sum())
    not_checked = int((summary["Kết quả"] == "Chưa kiểm tra được").sum())
    no_data = int((summary["Kết quả"] == "Chưa có dữ liệu").sum())
    issue_count = int(pd.to_numeric(summary["Bản ghi / lượt vi phạm"], errors="coerce").fillna(0).sum())

    return {"scores": dims, "final_score": final_score, "diagnostics": diagnostics, "available_dimensions": len(available)}

# =========================================================
# 5. LAS AI v4 — INDEPENDENT FROM RULE QC CYCLES
# =========================================================
@st.cache_data(ttl=60, show_spinner=False)
def load_ai_las_curve_audit_cached(run_id: str) -> pd.DataFrame:
    return load_ai_las_curve_audit(engine, str(run_id))


def load_ai_las_dashboard_snapshot(
    db_engine,
) -> tuple[pd.DataFrame, dict[str, Any] | None, str | None]:
    """Read-only dashboard loader. Never creates tables, trains or runs inference."""
    required = ("epdb_ai_las_v4_runs", "epdb_ai_las_v4_intervals", "epdb_ai_las_v4_curve_audit")
    missing = [name for name in required if not table_exists(name)]
    if missing:
        return pd.DataFrame(), None, (
            "Chưa có bảng kết quả AI: " + ", ".join(missing)
            + ". Hãy khởi tạo bảng và chạy chương trình dự đoán AI độc lập trước."
        )
    try:
        latest = load_latest_ai_las_run(db_engine)
        if latest is None:
            return pd.DataFrame(), None, "Chưa có snapshot AI LAS. Dashboard chỉ hiển thị kết quả đã được chương trình AI tạo trước đó."
        intervals = load_ai_las_intervals(db_engine, str(latest["run_id"]))
        return intervals_for_dashboard(intervals), latest, None
    except Exception as exc:
        return pd.DataFrame(), None, f"Không đọc được snapshot AI LAS: {type(exc).__name__}: {exc}"


# =========================================================
# 6. FILE EXPLORER — COMPACT TREE + DOCUMENT VIEWER
# =========================================================

def _format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

@st.cache_data(ttl=60, show_spinner=False)
def get_explorer_documents() -> pd.DataFrame:
    if not table_exists("epdb_document"):
        return pd.DataFrame()
    df = read_df("SELECT * FROM public.epdb_document")
    if df.empty:
        return df.reset_index(drop=True)
    sort_cols = [c for c in ("doc_type", "storage_path", "file_name") if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols, na_position="last")
    return df.reset_index(drop=True)

def _explorer_find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    if df is None or df.empty:
        return None
    lookup = {normalize_column_name(str(col)): col for col in df.columns}
    for candidate in candidates:
        actual = lookup.get(normalize_column_name(candidate))
        if actual is not None:
            return actual
    return None

def _explorer_value(row: pd.Series, columns: pd.DataFrame, candidates: list[str], default: Any = None):
    col = _explorer_find_col(columns, candidates)
    if col is None:
        return default
    value = row.get(col, default)
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    return value

def _explorer_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    res = str(value).strip()
    return res if res and res.casefold() not in {"nan", "none", "null", "<na>"} else default


def _is_valid_asset_display_name(value: Any) -> bool:
    """Return False for empty values and generated placeholder labels."""
    candidate = _explorer_text(value)
    if not candidate:
        return False
    folded = candidate.casefold()
    invalid_phrases = (
        "chưa đặt tên", "chua dat ten", "unnamed well", "unnamed borehole",
        "giếng chưa có tên", "gieng chua co ten", "thân giếng chưa có tên",
        "than gieng chua co ten",
    )
    return not any(phrase in folded for phrase in invalid_phrases)


def _explorer_name_for_key(
    frame: pd.DataFrame,
    id_column: str,
    id_value: Any,
    name_column: str,
    fallback: str,
) -> str:
    """Resolve a display name from every row for an ID, never just the first row."""
    key = _explorer_text(id_value)
    if not key or frame is None or frame.empty or id_column not in frame.columns or name_column not in frame.columns:
        return fallback
    keys = frame[id_column].fillna("").astype(str).str.strip()
    rows = frame.loc[keys.eq(key), name_column]
    for value in rows.tolist():
        candidate = _explorer_text(value)
        # The stored display name may intentionally equal UWI/UBHI. That is a
        # valid database name; only blank/generated placeholder values are rejected.
        if _is_valid_asset_display_name(candidate):
            return candidate
    return fallback if _is_valid_asset_display_name(fallback) else ""


def _render_explorer_summary_line(kind: str, well_name: str, detail: str, borehole_name: str = "") -> None:
    """Render the Viewer title, asset label and record count as one compact line."""
    safe_kind = html.escape(str(kind))
    safe_well = html.escape(str(well_name))
    safe_detail = html.escape(str(detail))
    safe_borehole = html.escape(str(borehole_name))
    borehole_html = (
        f'<span class="summary-meta">Thân giếng: {safe_borehole}</span>'
        if safe_borehole else ""
    )
    st.markdown(
        '<div class="epdb-viewer-summary-line">'
        '<span class="summary-title">▤ NỘI DUNG ĐỐI TƯỢNG</span>'
        '<span aria-hidden="true">│</span>'
        f'<span class="summary-kind">{safe_kind}</span>'
        f'<span class="summary-meta">Giếng: {safe_well}</span>'
        f'{borehole_html}'
        f'<span class="summary-count">{safe_detail}</span>'
        '</div>',
        unsafe_allow_html=True,
    )


def _explorer_unique_values(series: pd.Series) -> list[str]:
    values = []
    for value in series.dropna():
        item = str(value).strip()
        if item and item not in values:
            values.append(item)
    return sorted(values, key=str.casefold)

def _explorer_filter_text(df: pd.DataFrame, column: str, value: str) -> pd.DataFrame:
    if df.empty or column not in df.columns:
        return df.iloc[0:0].copy()
    mask = df[column].fillna("").astype(str).str.strip().eq(str(value).strip())
    return df.loc[mask].copy()

def _explorer_doc_title(row: pd.Series, documents: pd.DataFrame) -> str:
    title = _explorer_value(row, documents, ["doc_title", "document_title", "title"])
    if title:
        return str(title).strip()
    filename = _explorer_value(row, documents, ["file_name", "filename"])
    if filename:
        return str(filename).strip()
    storage_path = _explorer_value(row, documents, ["storage_path", "file_path"])
    if storage_path:
        return Path(str(storage_path)).name
    return "Tài liệu chưa có tên"


def _explorer_docs_for_ubhi(
    documents: pd.DataFrame,
    ubhi: str
) -> pd.DataFrame:

    if documents.empty or not ubhi:
        return documents.iloc[0:0].copy()

    ubhi_col = _explorer_find_col(documents, ["ubhi"])

    if ubhi_col is None:
        return documents.iloc[0:0].copy()

    wanted = str(ubhi).strip().casefold()

    actual = (
        documents[ubhi_col]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.casefold()
    )

    return documents.loc[actual == wanted].copy()


def _explorer_tree_item(display_name: str, internal_value: str, children: list | None = None):
    """Create clean tree labels and move child/file counts into compact Ant Design tags."""
    clean_label = str(display_name).strip()
    count_match = re.search(r"\s+\((\d+)\)$", clean_label)
    tags = []
    if count_match:
        clean_label = clean_label[:count_match.start()].rstrip()
        tags = [sac.Tag(count_match.group(1), color="blue", bordered=False)]
    value = f"{clean_label} | {internal_value}"
    tree_kwargs = {"tag": tags} if tags else {}
    return sac.TreeItem(value, children=children, **tree_kwargs) if children else sac.TreeItem(value, **tree_kwargs)


def _explorer_tree_allowed_values(items: list) -> set[str]:
    """Collect raw TreeItem labels for validating the Viewer selection only."""
    allowed: set[str] = set()
    stack = list(items or [])
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            label = item
            children = None
        elif isinstance(item, dict):
            label = item.get("label")
            children = item.get("children")
        else:
            label = getattr(item, "label", None)
            children = getattr(item, "children", None)

        if label is not None:
            allowed.add(str(label))
        if children:
            stack.extend(list(children))
    return allowed


def build_tree_data(df: pd.DataFrame, documents: pd.DataFrame):
    """Build the original EPDB hierarchy: Basin > Block > Field > Well > Borehole > Data."""
    tree_items = []
    if df is None or df.empty:
        return tree_items

    required_columns = {"basin_name", "block_name", "field_name", "uwi", "well_name", "ubhi", "borehole_name"}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        return tree_items

    has_document_table = table_exists("epdb_document")

    for basin in _explorer_unique_values(df["basin_name"]):
        df_basin = _explorer_filter_text(df, "basin_name", basin)
        block_items = []

        for block in _explorer_unique_values(df_basin["block_name"]):
            df_block = _explorer_filter_text(df_basin, "block_name", block)
            field_items = []

            for field in _explorer_unique_values(df_block["field_name"]):
                df_field = _explorer_filter_text(df_block, "field_name", field)
                well_items = []
                unique_wells = (
                    df_field.dropna(subset=["uwi"])
                    .drop_duplicates(subset=["uwi"])
                )

                for _, well_row in unique_wells.iterrows():
                    uwi = str(well_row["uwi"]).strip()
                    name = _explorer_name_for_key(df_field, "uwi", uwi, "well_name", "")
                    # Do not create a fake asset node when the master record has no
                    # valid display name. Its technical UWI remains internal only.
                    if not _is_valid_asset_display_name(name):
                        continue
                    well_rows = _explorer_filter_text(df_field, "uwi", uwi)
                    borehole_rows = (
                        well_rows.dropna(subset=["ubhi"])
                        .drop_duplicates(subset=["ubhi"])
                    )
                    borehole_items = []
                    borehole_records = (
                        [(None, None)] if borehole_rows.empty
                        else list(borehole_rows.iterrows())
                    )

                    for _, borehole_row in borehole_records:
                        if borehole_row is None:
                            ubhi = ""
                            borehole_name = "Dữ liệu chung"
                        else:
                            ubhi = _explorer_text(borehole_row.get("ubhi"))
                            borehole_name = _explorer_name_for_key(
                                well_rows,
                                "ubhi",
                                ubhi,
                                "borehole_name",
                                "",
                            )
                            # A borehole with UBHI but no database name is omitted;
                            # omit generated placeholder nodes.
                            if not _is_valid_asset_display_name(borehole_name):
                                continue

                        data_items = []
                        if has_document_table:
                            doc_rows = _explorer_docs_for_ubhi(documents, ubhi)
                            document_items = []

                            for doc_idx, doc_row in doc_rows.iterrows():
                                title = _explorer_doc_title(doc_row, documents)
                                doc_type = _explorer_text(
                                    _explorer_value(
                                        doc_row,
                                        documents,
                                        ["doc_type"],
                                        "DOCUMENT",
                                    ),
                                    "DOCUMENT",
                                )
                                document_items.append(
                                    _explorer_tree_item(
                                        f"📄 [{doc_type}] {title}",
                                        f"DocumentFile#{int(doc_idx)}",
                                    )
                                )

                            data_items.append(
                                _explorer_tree_item(
                                    f"📁 Tài liệu ({len(doc_rows)})",
                                    f"Document#{quote(uwi, safe='')}#{quote(name, safe='')}#{quote(ubhi, safe='')}",
                                    document_items,
                                )
                            )

                        data_items.extend([
                            _explorer_tree_item(
                                "📈 Production",
                                f"Production#{quote(uwi, safe='')}#{quote(name, safe='')}#{quote(ubhi, safe='')}",
                            ),
                            _explorer_tree_item(
                                "📊 Log (LAS)",
                                f"Log#{quote(uwi, safe='')}#{quote(name, safe='')}#{quote(ubhi, safe='')}",
                            ),
                            _explorer_tree_item(
                                "↗ Deviation",
                                f"Deviation#{quote(uwi, safe='')}#{quote(name, safe='')}#{quote(ubhi, safe='')}",
                            ),
                            _explorer_tree_item(
                                "▦ Core",
                                f"Core#{quote(uwi, safe='')}#{quote(name, safe='')}#{quote(ubhi, safe='')}",
                            ),
                        ])

                        borehole_items.append(
                            _explorer_tree_item(
                                f"🕳️ {borehole_name} ({len(data_items)})",
                                f"Borehole#{quote(uwi, safe='')}#{quote(name, safe='')}#{quote(ubhi, safe='')}",
                                data_items,
                            )
                        )

                    if not borehole_items:
                        continue
                    well_items.append(
                        _explorer_tree_item(
                            f"📍 {name} ({len(borehole_items)})",
                            f"Well#{quote(uwi, safe='')}#{quote(name, safe='')}",
                            borehole_items,
                        )
                    )

                field_items.append(
                    _explorer_tree_item(
                        f"🛢️ {field} ({len(well_items)})",
                        f"Field#{quote(basin, safe='')}#{quote(block, safe='')}#{quote(field, safe='')}",
                        well_items,
                    )
                )

            block_items.append(
                _explorer_tree_item(
                    f"📂 {block} ({len(field_items)})",
                    f"Block#{quote(basin, safe='')}#{quote(block, safe='')}",
                    field_items,
                )
            )

        tree_items.append(
            _explorer_tree_item(
                f"🗂️ {basin} ({len(block_items)})",
                f"Basin#{quote(basin, safe='')}",
                block_items,
            )
        )

    return tree_items


def _explorer_documents_for_payload(payload_parts: list[str], documents: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    if documents.empty or not payload_parts:
        return documents.iloc[0:0].copy()
    node_type = payload_parts[0]
    ubhi_col = _explorer_find_col(documents, ["ubhi"])
    if ubhi_col is None:
        return documents.iloc[0:0].copy()
    if node_type == "Document":
        uwi = payload_parts[1] if len(payload_parts) > 1 else ""
        ubhi = payload_parts[3] if len(payload_parts) > 3 else ""
        if ubhi:
            return _explorer_docs_for_ubhi(documents, ubhi)
        well_rows = _explorer_filter_text(master, "uwi", uwi)
        ubhis = well_rows["ubhi"].dropna().astype(str).str.strip().unique().tolist() if "ubhi" in well_rows.columns else []
        return documents[documents[ubhi_col].fillna("").astype(str).str.strip().isin(ubhis)].copy()
    if node_type == "DocumentFile":
        return documents
    scope = master.copy()
    if node_type == "Basin" and len(payload_parts) > 1:
        scope = _explorer_filter_text(scope, "basin_name", payload_parts[1])
    elif node_type == "Block" and len(payload_parts) > 2:
        scope = _explorer_filter_text(scope, "basin_name", payload_parts[1])
        scope = _explorer_filter_text(scope, "block_name", payload_parts[2])
    elif node_type == "Field" and len(payload_parts) > 3:
        scope = _explorer_filter_text(scope, "basin_name", payload_parts[1])
        scope = _explorer_filter_text(scope, "block_name", payload_parts[2])
        scope = _explorer_filter_text(scope, "field_name", payload_parts[3])
    elif node_type in {"Well", "Borehole"} and len(payload_parts) > 1:
        scope = _explorer_filter_text(scope, "uwi", payload_parts[1])
        if node_type == "Borehole" and len(payload_parts) > 3 and payload_parts[3]:
            scope = _explorer_filter_text(scope, "ubhi", payload_parts[3])
    else:
        return documents.iloc[0:0].copy()
    ubhis = scope["ubhi"].dropna().astype(str).str.strip().unique().tolist() if "ubhi" in scope.columns else []
    if not ubhis:
        return documents.iloc[0:0].copy()
    return documents[documents[ubhi_col].fillna("").astype(str).str.strip().isin(ubhis)].copy()

def _resolve_explorer_document_path(storage_path: Any) -> Path:
    raw_path = _explorer_text(storage_path)
    if not raw_path:
        raise ValueError("Bản ghi tài liệu chưa có storage_path.")
    root = DOCUMENT_ROOT.resolve()
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("Đường dẫn tài liệu nằm ngoài DOCUMENT_ROOT; từ chối truy cập.")
    if not candidate.is_file():
        raise FileNotFoundError(f"Không tìm thấy file: {candidate}")
    return candidate

def _explorer_restore_las_line_breaks(raw_text: str) -> str:
    text = raw_text.replace("\ufeff", "").replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    if text.count("\\n") >= 3:
        text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    ascii_match = re.search(r"~ASCII\s+Log\s+Data", text, flags=re.IGNORECASE)
    if not ascii_match:
        return text
    header = text[:ascii_match.start()]
    ascii_body = text[ascii_match.end():].strip()
    if header.count("\n") < 10:
        header = re.sub(r"[ \t]*(~(?:Version Information Section|Well Information Section|Curve Information Section|Parameter Information Section|Other Information Section))", r"\n\1", header, flags=re.IGNORECASE)
        header = re.sub(r"[ \t]+(?=#MNEM\b)", "\n", header, flags=re.IGNORECASE)
        header = re.sub(r"[ \t]+(?=[A-Z][A-Z0-9_]{0,20}[ \t]*\.[ \t]*\S)", "\n", header)
    curve_count = 0
    curve_match = re.search(r"~Curve Information Section(.*?)(?=~Parameter Information Section|~Other Information Section|$)", header, flags=re.IGNORECASE | re.DOTALL)
    if curve_match:
        for line in curve_match.group(1).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if re.match(r"^[A-Za-z][A-Za-z0-9_]*\s*\.\s*\S+", line):
                curve_count += 1
    if curve_count > 0 and ascii_body:
        data_lines = [line for line in ascii_body.splitlines() if line.strip()]
        rows_are_valid = len(data_lines) > 1 and all(len(line.split()) == curve_count for line in data_lines)
        if not rows_are_valid:
            tokens = ascii_body.split()
            if len(tokens) % curve_count == 0:
                rebuilt_rows = [" ".join(tokens[i:i + curve_count]) for i in range(0, len(tokens), curve_count)]
                ascii_body = "\n".join(rebuilt_rows)
    return header.rstrip() + "\n~ASCII Log Data\n" + ascii_body.rstrip() + "\n"

def _explorer_render_las(file_bytes: bytes, file_key: str) -> None:
    try:
        if file_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
            raw_text = file_bytes.decode("utf-16")
        else:
            try:
                raw_text = file_bytes.decode("utf-8-sig")
            except UnicodeDecodeError:
                raw_text = file_bytes.decode("cp1252")
        display_text = _explorer_restore_las_line_breaks(raw_text)

        curves = re.findall(r"^\s*([A-Za-z0-9_]+)\s*\.\s*(\S*)", display_text, flags=re.MULTILINE)
        curves_list = [c[0] for c in curves if not c[0].startswith("~")][:12]
        if curves_list:
            st.markdown(
                f"""<div style="display:flex;flex-wrap:wrap;gap:6px;background:#F1F5F9;border:1px solid #CBD5E1;border-radius:6px;padding:4px 8px;margin-bottom:6px;font-size:0.75rem;">
                    <span>📊 <b>Curves nhận diện:</b></span>
                    {' '.join([f'<span style="background:#E2E8F0;padding:1px 5px;border-radius:4px;font-weight:600;">{c}</span>' for c in curves_list])}
                </div>""",
                unsafe_allow_html=True,
            )
        st.code(display_text, language=None, line_numbers=True, wrap_lines=False, height=540)
    except Exception as exc:
        st.error(f"Không thể hiển thị nội dung LAS: {type(exc).__name__}: {exc}")

def render_explorer_document_preview(row: pd.Series, documents: pd.DataFrame):
    storage_path = _explorer_value(row, documents, ["storage_path", "file_path"])
    try:
        file_path = _resolve_explorer_document_path(storage_path)
    except Exception as exc:
        st.error(f"Không thể mở tài liệu: {type(exc).__name__}: {exc}")
        return

    extension = file_path.suffix.lower()
    try:
        file_bytes = file_path.read_bytes()
    except Exception as exc:
        st.error(f"Không đọc được file: {type(exc).__name__}: {exc}")
        return

    file_key = hashlib.sha256(str(file_path).encode("utf-8")).hexdigest()[:16]
    doc_title = _explorer_doc_title(row, documents)
    file_size_str = _format_file_size(len(file_bytes))

    ext_badge_colors = {
        ".pdf": ("#DC2626", "#FEE2E2"),
        ".las": ("#0F766E", "#CCFBF1"),
        ".xlsx": ("#166534", "#DCFCE7"),
        ".xls": ("#166534", "#DCFCE7"),
        ".csv": ("#2563EB", "#DBEAFE"),
        ".docx": ("#1E40AF", "#EFF6FF"),
    }
    b_color, b_bg = ext_badge_colors.get(extension, ("#475569", "#F1F5F9"))
    
    st.markdown(
        f"""<div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;background:#FFFFFF;border:1px solid #CBD5E1;border-radius:8px;padding:6px 10px;margin-bottom:8px;">
            <div style="display:flex;align-items:center;gap:8px;">
                <span style="font-size:0.7rem;font-weight:800;color:{b_color};background:{b_bg};padding:2px 7px;border-radius:4px;text-transform:uppercase;">{extension.lstrip('.')}</span>
                <span style="font-size:0.85rem;font-weight:750;color:#17365D;">{html.escape(doc_title)}</span>
                <span style="font-size:0.75rem;color:#64748B;">({file_size_str})</span>
            </div>
        </div>""",
        unsafe_allow_html=True,
    )
    st.download_button(
        label=f"📥 Tải file {file_path.name} ({file_size_str})",
        data=file_bytes,
        file_name=file_path.name,
        key=f"dl_{file_key}",
    )

    if extension == ".pdf":
        try:
            from streamlit_pdf_viewer import pdf_viewer
            pdf_viewer(input=file_bytes, width="100%", height=850, key=f"explorer_pdf_{file_key}", pages_vertical_spacing=4, show_page_separator=True)
        except ImportError:
            b64_pdf = base64.b64encode(file_bytes).decode("utf-8")
            st.markdown(f'<iframe src="data:application/pdf;base64,{b64_pdf}" width="100%" height="800" type="application/pdf"></iframe>', unsafe_allow_html=True)
        except Exception as exc:
            st.error(f"Không thể hiển thị PDF: {type(exc).__name__}: {exc}")
    elif extension == ".las":
        _explorer_render_las(file_bytes, file_key)
    elif extension in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
        st.image(BytesIO(file_bytes), use_container_width=True)
    elif extension in {".csv", ".tsv"}:
        try:
            sep = "\t" if extension == ".tsv" else ","
            frame = pd.read_csv(BytesIO(file_bytes), sep=sep, low_memory=False)
            st.caption(f"Kích thước bảng: {frame.shape[0]:,} dòng × {frame.shape[1]} cột")
            render_interactive_table(
                frame,
                height=580,
                highlight_first_column=False,
            )
        except Exception as exc:
            st.error(f"Không thể dựng bảng dữ liệu: {exc}")
    elif extension in {".xlsx", ".xls"}:
        try:
            excel_file = pd.ExcelFile(BytesIO(file_bytes))
            sheet_name = st.selectbox("Chọn trang tính (Sheet)", excel_file.sheet_names, key=f"explorer_sheet_{file_key}")
            frame = pd.read_excel(excel_file, sheet_name=sheet_name)
            st.caption(f"Trang tính: {sheet_name} | {frame.shape[0]:,} dòng × {frame.shape[1]} cột")
            render_interactive_table(
                frame,
                height=580,
                highlight_first_column=False,
            )
        except Exception as exc:
            st.error(f"Không thể đọc file Excel: {exc}")
    elif extension == ".docx":
        try:
            from docx import Document as DocxDocument
            word_doc = DocxDocument(BytesIO(file_bytes))
            for p in word_doc.paragraphs:
                txt = p.text.strip()
                if txt:
                    st.write(txt)
            for tbl in word_doc.tables:
                rows = [[c.text.strip() for c in r.cells] for r in tbl.rows]
                if rows:
                    render_interactive_table(
                        pd.DataFrame(rows[1:], columns=rows[0]),
                        highlight_first_column=False,
                    )
        except Exception as exc:
            st.error(f"Không thể xem trước DOCX: {exc}")
    elif extension == ".pptx":
        try:
            from pptx import Presentation
            prs = Presentation(BytesIO(file_bytes))
            for i, sld in enumerate(prs.slides, start=1):
                with st.expander(f"Slide {i}", expanded=(i == 1)):
                    for shp in sld.shapes:
                        if getattr(shp, "has_text_frame", False) and shp.text.strip():
                            st.write(shp.text.strip())
        except Exception as exc:
            st.error(f"Không thể xem trước PPTX: {exc}")
    elif extension in {".dev", ".txt", ".dat", ".asc", ".json", ".xml", ".log", ".yaml", ".yml", ".prn"}:
        content = file_bytes.decode("utf-8-sig", errors="replace")
        if extension == ".json":
            try:
                st.json(json.loads(content))
            except Exception:
                st.code(content, language="json", line_numbers=True)
        else:
            st.code(content, language="text", line_numbers=True)
    else:
        st.info(f"Định dạng {extension or 'không xác định'} chưa có bộ dựng nội dung trực tiếp. Bạn có thể bấm nút tải ở trên để mở trên máy tính.")

try:
    explorer_documents = get_explorer_documents()
except Exception as exc:
    explorer_documents = pd.DataFrame()
    st.warning(f"Không tải được danh sách tài liệu: {type(exc).__name__}: {exc}")

with st.sidebar:
    st.markdown(
        f"""<div class="epdb-explorer-header">
            <div class="epdb-explorer-header-title">📁 EPDB DATA EXPLORER</div>
            <div class="epdb-explorer-count">{len(explorer_documents):,} TÀI LIỆU</div>
        </div>""",
        unsafe_allow_html=True,
    )
    st.markdown('<div class="epdb-explorer-marker"></div>', unsafe_allow_html=True)
    col_nav, col_viewer = st.columns([1, 2.5], gap="small")

    with col_nav:
        tree_data = build_tree_data(df_master, explorer_documents)
        valid_tree_values = _explorer_tree_allowed_values(tree_data)

        # Bỏ cache và state của các widget Tree ở các phiên bản trước.
        # Tree bên dưới trở lại cách gọi cũ, không gắn key tùy biến.
        st.session_state.pop("_epdb_tree_cache", None)
        for old_tree_key in list(st.session_state.keys()):
            if isinstance(old_tree_key, str) and (
                old_tree_key == "epdb_data_document_tree"
                or old_tree_key.startswith("epdb_data_document_tree_")
            ):
                st.session_state.pop(old_tree_key, None)

        selected_node = sac.tree(
            items=tree_data,
            label="",
            index=None,
            format_func=lambda lbl: lbl.split(" | ", 1)[0] if " | " in lbl else lbl,
            open_index=[0],
            return_index=False,
        )

        # Tùy phiên bản streamlit-antd-components, kết quả có thể là str hoặc list[str].
        if isinstance(selected_node, (list, tuple)):
            selected_node = selected_node[-1] if selected_node else None

        if isinstance(selected_node, str) and selected_node in valid_tree_values:
            st.session_state.active_file = selected_node

        # Không giữ Viewer trỏ tới node đã bị xóa/đổi trong danh mục hiện tại.
        active_node_before_tree = st.session_state.get("active_file")
        if (
            isinstance(active_node_before_tree, str)
            and active_node_before_tree not in valid_tree_values
        ):
            st.session_state.active_file = None

    with col_viewer:
        active_node = st.session_state.get("active_file")
        if not active_node or " | " not in active_node:
            st.markdown('<div class="epdb-viewer-panel-heading">▤ NỘI DUNG ĐỐI TƯỢNG</div>', unsafe_allow_html=True)
            st.markdown(
                """<div style="background:#FFFFFF;border:1px dashed #CBD5E1;border-radius:10px;padding:30px 20px;text-align:center;margin-top:20px;">
                    <span style="font-size:2.2rem;">🗂️</span>
                    <div style="font-size:0.92rem;font-weight:750;color:#17365D;margin-top:8px;">Chưa chọn đối tượng để xem</div>
                    <div style="font-size:0.78rem;color:#64748B;margin-top:4px;max-width:380px;margin-inline:auto;">
                        Hãy bấm chọn một Bể, Lô, Mỏ, Giếng, Thân giếng hoặc File tài liệu trên cây phân cấp bên trái để xem nội dung tương ứng.
                    </div>
                </div>""",
                unsafe_allow_html=True,
            )
        else:
            try:
                payload = active_node.split(" | ", 1)[1]
                parts = [unquote(item) for item in payload.split("#")]
                dtype = parts[0]

                
                if dtype in {"Production", "Log", "Deviation", "Core", "Seismic", "Well", "Borehole", "Document"}:
                    # Only show friendly asset names; technical database keys remain in payloads.
                    well_display = parts[2] if len(parts) > 2 else ""
                    crumb_items = []
                    if well_display:
                        crumb_items.append(f"Giếng: {html.escape(well_display)}")
                    if dtype == "Borehole" and len(parts) > 3 and parts[1] and parts[3]:
                        borehole_rows = df_master[
                            df_master["uwi"].astype(str).str.strip().eq(parts[1])
                            & df_master["ubhi"].astype(str).str.strip().eq(parts[3])
                        ] if {"uwi", "ubhi"}.issubset(df_master.columns) else pd.DataFrame()
                        if not borehole_rows.empty and "borehole_name" in borehole_rows.columns:
                            borehole_display = _explorer_name_for_key(
                                borehole_rows, "ubhi", parts[3], "borehole_name", ""
                            )
                            if borehole_display:
                                crumb_items.append(f"Thân giếng: {html.escape(borehole_display)}")
                    crumb_text = " &bull; ".join(crumb_items)
                elif dtype == "DocumentFile":
                    crumb_text = "Tài liệu đã chọn"
                else:
                    # Basin/Block/Field payloads contain display names, not DB keys.
                    breadcrumb_parts = []
                    for part in parts[1:]:
                        if part and (
                            not breadcrumb_parts
                            or part.casefold() != breadcrumb_parts[-1].casefold()
                        ):
                            breadcrumb_parts.append(part)
                    crumb_text = " &bull; ".join(html.escape(part) for part in breadcrumb_parts)

                if dtype not in {"Deviation", "Core"}:
                    st.markdown(
                        f"""<div style="font-size:0.75rem;color:#17365D;background:#F8FAFC;border:1px solid #E2E8F0;border-radius:6px;padding:4px 8px;margin-bottom:8px;white-space:nowrap;overflow-x:auto;">
                            <b>▤ NỘI DUNG ĐỐI TƯỢNG</b> &nbsp;│&nbsp; <b>{html.escape(dtype)}</b> {(' &bull; ' + crumb_text) if crumb_text else ''}
                        </div>""",
                        unsafe_allow_html=True,
                    )

                if dtype == "DocumentFile":
                    try:
                        selected_doc_index = int(parts[1])
                    except (IndexError, ValueError):
                        selected_doc_index = None
                    if selected_doc_index is None or selected_doc_index not in explorer_documents.index:
                        st.error("Không xác định được tài liệu đã chọn.")
                    else:
                        selected_row = explorer_documents.loc[selected_doc_index]
                        render_explorer_document_preview(selected_row, explorer_documents)

                elif dtype in {"Basin", "Block", "Field", "Well", "Borehole", "Document"}:
                    # Restore object metadata in the Viewer; previously this branch only
                    # listed linked files, making Basin/Block/Field/Well selections look empty.
                    if dtype != "Document":
                        scoped_master = df_master.copy()
                        if dtype == "Basin" and len(parts) > 1:
                            scoped_master = _explorer_filter_text(scoped_master, "basin_name", parts[1])
                        elif dtype == "Block" and len(parts) > 2:
                            scoped_master = _explorer_filter_text(scoped_master, "basin_name", parts[1])
                            scoped_master = _explorer_filter_text(scoped_master, "block_name", parts[2])
                        elif dtype == "Field" and len(parts) > 3:
                            scoped_master = _explorer_filter_text(scoped_master, "basin_name", parts[1])
                            scoped_master = _explorer_filter_text(scoped_master, "block_name", parts[2])
                            scoped_master = _explorer_filter_text(scoped_master, "field_name", parts[3])
                        elif dtype in {"Well", "Borehole"} and len(parts) > 1:
                            scoped_master = _explorer_filter_text(scoped_master, "uwi", parts[1])
                            if dtype == "Borehole" and len(parts) > 3 and parts[3]:
                                scoped_master = _explorer_filter_text(scoped_master, "ubhi", parts[3])

                        master_columns = [
                            ("basin_name", "Bể"),
                            ("block_name", "Lô"),
                            ("field_name", "Mỏ"),
                            ("well_name", "Giếng"),
                            ("borehole_name", "Thân giếng"),
                        ]
                        visible_columns = [source for source, _ in master_columns if source in scoped_master.columns]
                        if not scoped_master.empty and visible_columns:
                            object_view = scoped_master[visible_columns].drop_duplicates().rename(
                                columns={source: label for source, label in master_columns}
                            )
                            st.markdown('<div class="overview-panel-title">Thông tin đối tượng trong EPDB</div>', unsafe_allow_html=True)
                            render_interactive_table(
                                object_view,
                                height=min(300, max(100, 34 * (min(len(object_view), 8) + 1))),
                                highlight_first_column=True,
                            )
                        else:
                            st.info("Không tìm thấy bản ghi danh mục tương ứng với node đã chọn.")

                    docs_scope = _explorer_documents_for_payload(parts, explorer_documents, df_master)
                    if docs_scope.empty:
                        st.info("Không có tài liệu được liên kết trong phạm vi đối tượng này.")
                    else:
                        display_rows = []
                        for _, doc_row in docs_scope.iterrows():
                            t = _explorer_doc_title(doc_row, docs_scope)
                            dt = _explorer_text(_explorer_value(doc_row, docs_scope, ["doc_type"]), "Document")
                            p = _explorer_text(_explorer_value(doc_row, docs_scope, ["storage_path", "file_path"]))
                            ext = Path(p).suffix.lower() if p else ""
                            display_rows.append({"Tên tài liệu": t, "Phân loại": dt, "Định dạng": ext or "—"})
                        st.markdown('<div class="overview-panel-title">Tài liệu liên kết</div>', unsafe_allow_html=True)
                        render_interactive_table(
                            pd.DataFrame(display_rows),
                            height=min(480, max(120, 34 * (min(len(display_rows), 12) + 1))),
                            highlight_first_column=False,
                        )

                
                
                
                elif dtype == "Production":
                    t_ubhi = parts[3] if len(parts) > 3 else ""

                    if not t_ubhi:
                        st.warning("Chưa xác định được mã thân giếng.")
                    else:
                        prod = read_df(
                            """
                            SELECT
                                p.production_id,
                                p.production_month,
                                p.oil_bbl,
                                p.gas_mscf,
                                p.water_bbl,
                                p.whp_psi,
                                p.choke_size_in,
                                p.onstream_hours

                            FROM public.epdb_production p

                            JOIN public.epdb_borehole b
                                ON b.wellbore_id = p.wellbore_id

                            WHERE b.wellbore_code = :wellbore_code

                            ORDER BY
                                p.production_month,
                                p.production_id
                            """,
                            {"wellbore_code": t_ubhi},
                        )

                        if prod.empty:
                            st.info("Không có dữ liệu khai thác cho thân giếng này.")
                        else:
                            chart_prod = prod.copy()

                            chart_prod["production_month"] = pd.to_datetime(
                                chart_prod["production_month"],
                                errors="coerce",
                            )

                            numeric_columns = [
                                "oil_bbl",
                                "gas_mscf",
                                "water_bbl",
                                "whp_psi",
                                "onstream_hours",
                            ]

                            for col in numeric_columns:
                                chart_prod[col] = pd.to_numeric(
                                    chart_prod[col],
                                    errors="coerce",
                                )

                            chart_prod = chart_prod.sort_values(
                                "production_month",
                                na_position="last",
                            )

                            # Sản lượng tích lũy được tính từ tổng sản lượng tháng.
                            chart_prod["oil_cumulative_bbl"] = (
                                chart_prod["oil_bbl"].fillna(0).cumsum()
                            )

                            chart_prod["gas_cumulative_mscf"] = (
                                chart_prod["gas_mscf"].fillna(0).cumsum()
                            )

                            c1, c2, c3, c4 = st.columns(4)

                            with c1:
                                render_kpi_card(
                                    "Số tháng dữ liệu",
                                    f"{len(chart_prod):,}",
                                    "Số bản ghi Production",
                                    status="navy",
                                    icon="📅",
                                )

                            with c2:
                                render_kpi_card(
                                    "Tổng dầu",
                                    f"{chart_prod['oil_bbl'].sum():,.1f} bbl",
                                    "Tổng sản lượng dầu",
                                    status="success",
                                    icon="🛢️",
                                )

                            with c3:
                                render_kpi_card(
                                    "Tổng khí",
                                    f"{chart_prod['gas_mscf'].sum():,.1f} Mscf",
                                    "Tổng sản lượng khí",
                                    status="navy",
                                    icon="💨",
                                )

                            with c4:
                                valid_whp = chart_prod["whp_psi"].dropna()
                                whp_text = (
                                    f"{valid_whp.iloc[-1]:,.1f} psi"
                                    if not valid_whp.empty else "—"
                                )

                                render_kpi_card(
                                    "WHP gần nhất",
                                    whp_text,
                                    "Áp suất đầu giếng",
                                    status="warning",
                                    icon="📈",
                                )

                            # Biểu đồ sản lượng theo tháng.
                            fig_monthly = go.Figure()

                            fig_monthly.add_trace(go.Scatter(
                                x=chart_prod["production_month"],
                                y=chart_prod["oil_bbl"],
                                name="Dầu (bbl/tháng)",
                                mode="lines+markers",
                                line=dict(color="#15803D", width=2),
                            ))

                            fig_monthly.add_trace(go.Scatter(
                                x=chart_prod["production_month"],
                                y=chart_prod["water_bbl"],
                                name="Nước (bbl/tháng)",
                                mode="lines+markers",
                                line=dict(color="#245A8D", width=2),
                            ))

                            fig_monthly.add_trace(go.Scatter(
                                x=chart_prod["production_month"],
                                y=chart_prod["gas_mscf"],
                                name="Khí (Mscf/tháng)",
                                mode="lines+markers",
                                line=dict(color="#DC2626", width=2),
                                yaxis="y2",
                            ))

                            fig_monthly.update_layout(
                                title="Sản lượng khai thác theo tháng",
                                height=330,
                                margin=dict(l=55, r=60, t=45, b=40),
                                hovermode="x unified",
                                paper_bgcolor="#FFFFFF",
                                plot_bgcolor="#FFFFFF",
                                xaxis=dict(
                                    title="Tháng khai thác",
                                    tickformat="%m/%Y",
                                ),
                                yaxis=dict(
                                    title="Dầu / Nước (bbl/tháng)",
                                    rangemode="tozero",
                                ),
                                yaxis2=dict(
                                    title="Khí (Mscf/tháng)",
                                    overlaying="y",
                                    side="right",
                                    rangemode="tozero",
                                ),
                                legend=dict(
                                    orientation="h",
                                    y=1.12,
                                    x=0,
                                ),
                            )

                            st.plotly_chart(
                                fig_monthly,
                                use_container_width=True,
                                config={"displayModeBar": False, "responsive": True},
                                key=f"production_monthly_{hashlib.md5(t_ubhi.encode()).hexdigest()[:8]}",
                            )

                            # Biểu đồ WHP, phục vụ theo dõi áp suất đầu giếng.
                            fig_pressure = go.Figure()

                            fig_pressure.add_trace(go.Scatter(
                                x=chart_prod["production_month"],
                                y=chart_prod["whp_psi"],
                                name="WHP",
                                mode="lines+markers",
                                line=dict(color="#B42318", width=2),
                                connectgaps=False,
                            ))

                            fig_pressure.update_layout(
                                title="Diễn biến áp suất đầu giếng (WHP)",
                                height=280,
                                margin=dict(l=55, r=25, t=45, b=40),
                                paper_bgcolor="#FFFFFF",
                                plot_bgcolor="#FFFFFF",
                                xaxis=dict(title="Tháng khai thác", tickformat="%m/%Y"),
                                yaxis=dict(
                                    title="Áp suất (psi)",
                                    rangemode="tozero",
                                ),
                                showlegend=False,
                            )

                            st.plotly_chart(
                                fig_pressure,
                                use_container_width=True,
                                config={"displayModeBar": False, "responsive": True},
                                key=f"production_whp_{hashlib.md5(t_ubhi.encode()).hexdigest()[:8]}",
                            )

                            st.markdown("**Sản lượng tích lũy tính từ dữ liệu tháng**")

                            display_prod = chart_prod.rename(
                                columns={
                                    "production_month": "Tháng khai thác",
                                    "oil_bbl": "Dầu (bbl/tháng)",
                                    "gas_mscf": "Khí (Mscf/tháng)",
                                    "water_bbl": "Nước (bbl/tháng)",
                                    "whp_psi": "WHP (psi)",
                                    "onstream_hours": "Thời gian hoạt động (giờ)",
                                    "oil_cumulative_bbl": "Dầu tích lũy (bbl)",
                                    "gas_cumulative_mscf": "Khí tích lũy (Mscf)",
                                }
                            )

                            render_interactive_table(
                                display_prod,
                                height=420,
                                highlight_first_column=False,
                            )




                
                elif dtype == "Seismic":
                    t_uwi = parts[1] if len(parts) > 1 else ""

                    well_rows = df_master[
                        df_master["uwi"].astype(str).str.strip() == t_uwi
                    ]

                    b_name = (
                        well_rows["block_name"].dropna().iloc[0]
                        if not well_rows.empty
                        and well_rows["block_name"].notna().any()
                        else None
                    )

                    f_name = (
                        well_rows["field_name"].dropna().iloc[0]
                        if not well_rows.empty
                        and well_rows["field_name"].notna().any()
                        else None
                    )

                    st.caption("Khảo sát địa chấn được tra cứu theo phạm vi Lô/Mỏ bao phủ giếng.")

                    if not table_exists("epdb_seismic"):
                        st.warning("Không tồn tại bảng epdb_seismic.")
                    else:
                        seismic_columns = table_columns("epdb_seismic")

                        if not seismic_columns:
                            st.warning("Không đọc được cấu trúc bảng epdb_seismic.")
                        else:
                            
                            seis = read_df(
                                """
                                SELECT
                                    s.survey_id,
                                    s.survey_name,
                                    s.survey_type,
                                    s.vintage,
                                    s.acquisition_date,
                                    s.domain,
                                    s.file_format,
                                    s.file_size_gb,
                                    s.file_path,
                                    s.remarks,
                                    s.inline,
                                    s.crossline,
                                    s.cdp,
                                    s.geometry_qc_status,
                                    s.coordinate_scaling_status,
                                    s.segy_header_status,
                                    s.navigation_qc_status,
                                    s.trace_count_qc_status
                                FROM public.epdb_seismic s
                                LEFT JOIN public.epdb_block b
                                    ON s.block_id = b.block_id
                                LEFT JOIN public.epdb_field f
                                    ON s.field_id = f.field_id
                                WHERE
                                    (:b_name IS NOT NULL AND b.block_name = :b_name)
                                    OR
                                    (:f_name IS NOT NULL AND f.field_name = :f_name)
                                ORDER BY s.survey_id
                                """,
                                {"b_name": b_name, "f_name": f_name},
                            )


                            if seis.empty:
                                st.info(
                                    "Không có khảo sát địa chấn trong phạm vi Lô/Mỏ này."
                                )
                            else:
                                path_col = _explorer_find_col(
                                    seis,
                                    [
                                        "storage_path",
                                        "file_path",
                                        "filepath",
                                        "seismic_file_path",
                                        "segy_path",
                                        "segy_file_path",
                                        "data_path",
                                        "source_path",
                                        "file_uri",
                                        "uri",
                                    ],
                                )

                                name_col = _explorer_find_col(
                                    seis,
                                    ["file_name", "filename", "seismic_file_name"],
                                )

                                total_size = (
                                    pd.to_numeric(
                                        seis["file_size_gb"], errors="coerce"
                                    ).fillna(0).sum()
                                    if "file_size_gb" in seis.columns
                                    else 0
                                )

                                # Không dùng st.columns bên trong Sidebar.
                                seismic_metric_html = f"""
                                <div style="
                                    display:flex;flex-wrap:wrap;gap:8px;
                                    margin:6px 0 12px 0;">

                                    <div style="
                                        flex:1;min-width:130px;
                                        background:#FFFFFF;border:1px solid #CBD5E1;
                                        border-radius:8px;padding:9px 12px;">
                                        <div style="font-size:.72rem;color:#64748B;">
                                            Số khảo sát
                                        </div>
                                        <div style="font-size:1.2rem;font-weight:850;color:#17365D;">
                                            {len(seis):,}
                                        </div>
                                    </div>

                                    <div style="
                                        flex:1;min-width:130px;
                                        background:#FFFFFF;border:1px solid #CBD5E1;
                                        border-radius:8px;padding:9px 12px;">
                                        <div style="font-size:.72rem;color:#64748B;">
                                            Tổng dung lượng khai báo
                                        </div>
                                        <div style="font-size:1.2rem;font-weight:850;color:#17365D;">
                                            {total_size:,.2f} GB
                                        </div>
                                    </div>
                                </div>
                                """

                                st.markdown(
                                    seismic_metric_html,
                                    unsafe_allow_html=True,
                                )

                                if path_col is None:
                                    st.warning(
                                        "Hiện chỉ đọc được metadata khảo sát từ "
                                        "epdb_seismic. Không tìm thấy cột đường dẫn "
                                        "file địa chấn trong kết quả truy vấn. "
                                        "Chưa đủ căn cứ xác nhận có file SEG-Y thực tế."
                                    )
                                else:
                                    def check_seismic_file(value):
                                        raw = _explorer_text(value)

                                        if not raw:
                                            return "Chưa khai báo đường dẫn"

                                        if raw.lower().startswith(
                                            ("s3://", "http://", "https://")
                                        ):
                                            return "URI bên ngoài — chưa xác minh truy cập"

                                        candidate = Path(raw).expanduser()

                                        if not candidate.is_absolute():
                                            candidate = DOCUMENT_ROOT / candidate

                                        return (
                                            "Tồn tại trên máy chạy ứng dụng"
                                            if candidate.is_file()
                                            else "Không tìm thấy file tại đường dẫn"
                                        )

                                    seis_display = seis.copy()

                                    seis_display["Tình trạng file"] = (
                                        seis[path_col].apply(check_seismic_file)
                                    )

                                    if seis_display["Tình trạng file"].eq(
                                        "Tồn tại trên máy chạy ứng dụng"
                                    ).any():
                                        st.success(
                                            "Đã xác định được ít nhất một file tại "
                                            "đường dẫn trên máy chạy ứng dụng. "
                                            "Đây mới là kiểm tra sự tồn tại, chưa phải "
                                            "đọc và giải mã dữ liệu địa chấn."
                                        )
                                    else:
                                        st.warning(
                                            "Chưa xác minh được file địa chấn thực tế "
                                            "tại các đường dẫn đã khai báo."
                                        )

                                    display_columns = []

                                    for candidate in (
                                        "survey_name",
                                        "survey_type",
                                        "vintage",
                                        "domain",
                                        "file_format",
                                        "file_size_gb",
                                    ):
                                        actual = _explorer_find_col(
                                            seis_display, [candidate]
                                        )
                                        if actual and actual not in display_columns:
                                            display_columns.append(actual)

                                    if name_col and name_col not in display_columns:
                                        display_columns.append(name_col)

                                    if path_col not in display_columns:
                                        display_columns.append(path_col)

                                    display_columns.append("Tình trạng file")

                                    render_interactive_table(
                                        seis_display[display_columns],
                                        highlight_first_column=False,
                                    )

                                if name_col and path_col is None:
                                    st.caption(
                                        "Có tên file nhưng chưa xác định được đường dẫn "
                                        "vật lý tới dữ liệu."
                                    )


                elif dtype == "Log":
                    t_ubhi = parts[3] if len(parts) > 3 else ""

                    if not t_ubhi:
                        st.warning("Chưa xác định được mã thân giếng.")
                    else:
                        runs = read_df(
                            """
                            SELECT
                                r.log_id,
                                r.run_number,
                                r.logging_date,
                                r.tool_company,
                                r.top_md_m,
                                r.bottom_md_m,
                                r.curves_acquired

                            FROM public.epdb_log_run r

                            JOIN public.epdb_borehole b
                                ON b.wellbore_id = r.wellbore_id

                            WHERE b.wellbore_code = :wellbore_code

                            ORDER BY r.run_number
                            """,
                            {"wellbore_code": t_ubhi},
                        )

                        if runs.empty:
                            st.info("Không có lần chạy Log cho thân giếng này.")
                        else:
                            run_lookup = {
                                int(row["log_id"]):
                                f"Run {row['run_number']} — {row['logging_date']}"
                                for _, row in runs.iterrows()
                            }

                            selected_log_id = st.selectbox(
                                "Chọn lần chạy Log",
                                options=list(run_lookup.keys()),
                                format_func=lambda value: run_lookup[value],
                                key=f"log_run_{t_ubhi}",
                            )

                            df_show = read_df(
                                """
                                SELECT
                                    log_id,
                                    depth_md_m,
                                    gr_api,
                                    rt_ohmm,
                                    rhob_gcc,
                                    nphi_v_v,
                                    cali_in,
                                    sp_mv

                                FROM public.epdb_log_data

                                WHERE log_id = :log_id

                                ORDER BY depth_md_m

                                LIMIT 5000
                                """,
                                {"log_id": int(selected_log_id)},
                            )

                            if not df_show.empty:
                                st.caption(
                                    f"Well Log — {len(df_show):,} mẫu đo"
                                )

                                render_interactive_table(
                                    df_show,
                                    height=520,
                                    highlight_first_column=True,
                                )
                            else:
                                st.info("Lần chạy Log này chưa có mẫu đường cong.")

                elif dtype == "Deviation":
                    t_uwi = parts[1] if len(parts) > 1 else ""
                    well_display = _explorer_name_for_key(df_master, "uwi", t_uwi, "well_name", parts[2] if len(parts) > 2 else "")
                    t_ubhi = parts[3] if len(parts) > 3 else ""
                    borehole_display = _explorer_name_for_key(df_master, "ubhi", t_ubhi, "borehole_name", "")
                    df_show = read_df(
                        """
                        SELECT
                            d.survey_id,
                            d.wellbore_id,
                            d.md_m,
                            d.inclination_deg,
                            d.azimuth_deg,
                            d.tvd_m,
                            d.north_offset_m,
                            d.east_offset_m,
                            d.dogleg_severity

                        FROM public.epdb_deviation d

                        JOIN public.epdb_borehole b
                            ON b.wellbore_id = d.wellbore_id

                        WHERE b.wellbore_code = :wellbore_code

                        ORDER BY d.md_m
                        """,
                        {"wellbore_code": t_ubhi},
                    )
                    _render_explorer_summary_line(
                        "↗ Deviation", well_display,
                        f"Quỹ đạo giếng ({len(df_show):,} trạm đo)", borehole_display,
                    )
                    if not df_show.empty:
                        render_interactive_table(
                            df_show,
                            height=520,
                            highlight_first_column=True,
                        )
                    else:
                        st.info("Không có dữ liệu quỹ đạo giếng.")

                elif dtype == "Core":
                    t_uwi = parts[1] if len(parts) > 1 else ""
                    well_display = _explorer_name_for_key(df_master, "uwi", t_uwi, "well_name", parts[2] if len(parts) > 2 else "")
                    t_ubhi = parts[3] if len(parts) > 3 else ""
                    borehole_display = _explorer_name_for_key(df_master, "ubhi", t_ubhi, "borehole_name", "")
                    df_show = read_df(
                        """
                        SELECT
                            sample_id,
                            wellbore_id,
                            sample_type,
                            top_md_m,
                            bottom_md_m,
                            recovery_pct,
                            lithology,
                            porosity_pct,
                            permeability_md,
                            description

                        FROM public.epdb_core_cuttings_sample

                        WHERE wellbore_id = (
                            SELECT wellbore_id
                            FROM public.epdb_borehole
                            WHERE wellbore_code = :wellbore_code
                        )

                        ORDER BY top_md_m, sample_id
                        """,
                        {"wellbore_code": t_ubhi},
                    )
                    _render_explorer_summary_line(
                        "▦ Core / Cuttings",
                        well_display,
                        f"Mẫu Core/Cuttings ({len(df_show):,} mẫu)",
                        borehole_display,
                    )
                    if not df_show.empty:
                        render_interactive_table(
                            df_show,
                            height=520,
                            highlight_first_column=True,
                        )
                    else:
                        st.info("Không có dữ liệu phân tích mẫu lõi.")
            except Exception as exc:
                st.error(f"Lỗi truy xuất dữ liệu: {type(exc).__name__}: {exc}")

# Khởi chạy worker sau khi dữ liệu nền và file explorer đã sẵn sàng.
# QC chạy trong daemon thread, không chặn luồng dựng giao diện Streamlit.
qc_background_worker = get_qc_background_worker(
    engine, str(DOCUMENT_ROOT), QC_CYCLE_INTERVAL_HOURS
)


# =========================================================
# 7. MAIN DASHBOARD AND FOUR PROPOSAL VIEWS + SEPARATE QC
# =========================================================

st.markdown(
    """
    <style>
        [data-testid="stVerticalBlock"] > div:has(.epdb-nav-marker) + div [data-testid="stRadio"] > div[role="radiogroup"] {
            display: flex; width: 100%; gap: 4px; background: #EDF2F7; padding: 4px; border-radius: 12px; border: 1px solid #CBD5E1;
        }
        [data-testid="stVerticalBlock"] > div:has(.epdb-nav-marker) + div [data-testid="stRadio"] label {
            flex: 1 1 0; text-align: center; border-radius: 8px !important; border: none !important; background: transparent;
            color: #475569; font-weight: 700; font-size: clamp(0.78rem, 0.88vw, 0.92rem); padding: 0.58rem 0.4rem !important; transition: all 0.2s ease;
        }
        [data-testid="stVerticalBlock"] > div:has(.epdb-nav-marker) + div [data-testid="stRadio"] label:hover {
            background: rgba(255, 255, 255, 0.7); color: #17365D;
        }
        [data-testid="stVerticalBlock"] > div:has(.epdb-nav-marker) + div [data-testid="stRadio"] label:has(input:checked) {
            background: #17365D !important; color: #FFFFFF !important; box-shadow: 0 2px 6px rgba(23, 54, 93, 0.28) !important; font-weight: 850 !important;
        }
        [data-testid="stVerticalBlock"] > div:has(.epdb-nav-marker) + div [data-testid="stRadio"] label:has(input:checked) div { color: #FFFFFF !important; }
        [data-testid="stVerticalBlock"] > div:has(.epdb-cat-nav-marker) + div [data-testid="stRadio"] > div[role="radiogroup"] {
            display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px;
        }
        [data-testid="stVerticalBlock"] > div:has(.epdb-cat-nav-marker) + div [data-testid="stRadio"] label {
            background: #FFFFFF; border: 1px solid #CBD5E1 !important; border-radius: 8px !important; padding: 0.42rem 0.82rem !important; font-weight: 650; font-size: 0.82rem; color: #334155;
        }
        [data-testid="stVerticalBlock"] > div:has(.epdb-cat-nav-marker) + div [data-testid="stRadio"] label:has(input:checked) {
            background: #0F766E !important; border-color: #0F766E !important; color: #FFFFFF !important;
        }
        [data-testid="stVerticalBlock"] > div:has(.epdb-cat-nav-marker) + div [data-testid="stRadio"] label:has(input:checked) div { color: #FFFFFF !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

def render_kpi_card(label: str, value: Any, subtext: str = "", status: str = "navy", icon: str = "", raise_up: bool = False) -> None:
    safe_label = html.escape(str(label))
    safe_val = html.escape(str(value))
    safe_sub = html.escape(str(subtext))
    color_map = {
        "navy":    {"border": "#17365D", "bg": "#FFFFFF", "val_color": "#17365D", "sub_bg": "#F1F5F9", "sub_color": "#334155"},
        "teal":    {"border": "#0F766E", "bg": "#FFFFFF", "val_color": "#0F766E", "sub_bg": "#F0FDFA", "sub_color": "#0F766E"},
        "success": {"border": "#166534", "bg": "#FFFFFF", "val_color": "#166534", "sub_bg": "#DCFCE7", "sub_color": "#14532D"},
        "warning": {"border": "#D97706", "bg": "#FFFFFF", "val_color": "#92400E", "sub_bg": "#FEF3C7", "sub_color": "#78350F"},
        "danger":  {"border": "#DC2626", "bg": "#FFF5F5", "val_color": "#991B1B", "sub_bg": "#FEE2E2", "sub_color": "#991B1B"},
    }
    cfg = color_map.get(status, color_map["navy"])
    icon_html = f'<span style="font-size:1.05rem;margin-right:6px;">{icon}</span>' if icon else ""
    sub_html = f'<div style="font-size:0.73rem;font-weight:650;color:{cfg["sub_color"]};background:{cfg["sub_bg"]};padding:2px 7px;border-radius:5px;display:inline-block;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;">{safe_sub}</div>' if subtext else ""
    card_class = "epdb-kpi-card epdb-kpi-card-raised" if raise_up else "epdb-kpi-card"
    st.markdown(
        f'<div class="{card_class}" style="background:{cfg["bg"]};border:1px solid #CBD5E1;border-left:4px solid {cfg["border"]};border-radius:10px;padding:8px 12px;box-shadow:0 1px 3px rgba(15,23,42,0.04);height:100%;min-height:76px;display:flex;flex-direction:column;justify-content:center;">'
        f'<div style="display:flex;align-items:center;color:#526174;font-size:0.72rem;font-weight:750;text-transform:uppercase;letter-spacing:0.04em;">{icon_html}{safe_label}</div>'
        f'<div style="font-size:1.42rem;font-weight:850;color:{cfg["val_color"]};line-height:1.18;margin-top:3px;font-variant-numeric:tabular-nums;overflow-wrap:anywhere;">{safe_val}</div>'
        f'{sub_html}</div>',
        unsafe_allow_html=True,
    )

def render_dimension_card_html(dim_name: str, dim_label_vn: str, score: float | None, weight: float) -> str:
    if score is None:
        score_text = "Chưa đủ mẫu"
        pct = 0.0
        bar_color = "#94A3B8"
        status_badge = '<span style="font-size:0.68rem;padding:2px 6px;border-radius:4px;background:#F1F5F9;color:#64748B;font-weight:700;">Chưa kiểm tra</span>'
    else:
        score_text = f"{score:.1f}%"
        pct = max(0.0, min(100.0, score))
        if pct >= 85:
            bar_color = "#10B981"
            status_badge = '<span style="font-size:0.68rem;padding:2px 6px;border-radius:4px;background:#DCFCE7;color:#166534;font-weight:700;">Đạt chuẩn</span>'
        elif pct >= 70:
            bar_color = "#0F766E"
            status_badge = '<span style="font-size:0.68rem;padding:2px 6px;border-radius:4px;background:#CCFBF1;color:#0F766E;font-weight:700;">Chấp nhận</span>'
        elif pct >= 50:
            bar_color = "#F59E0B"
            status_badge = '<span style="font-size:0.68rem;padding:2px 6px;border-radius:4px;background:#FEF3C7;color:#92400E;font-weight:700;">Cần xử lý</span>'
        else:
            bar_color = "#EF4444"
            status_badge = '<span style="font-size:0.68rem;padding:2px 6px;border-radius:4px;background:#FEE2E2;color:#991B1B;font-weight:700;">Nguy cơ</span>'

    return textwrap.dedent(f"""\
        <div style="background:#FFFFFF;border:1px solid #AAB9C9;border-left:3px solid {bar_color};border-radius:8px;padding:7px 9px;box-shadow:0 1px 3px rgba(15,23,42,.055);margin:0;min-height:78px;">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:5px;">
                <div style="font-size:0.73rem;font-weight:750;color:#1E293B;line-height:1.2;">{dim_label_vn} <span style="font-size:0.64rem;color:#64748B;font-weight:500;">({dim_name})</span></div>
                <div style="flex:0 0 auto;">{status_badge}</div>
            </div>
            <div style="display:flex;justify-content:space-between;align-items:baseline;margin:3px 0 2px 0;">
                <div style="font-size:1.00rem;font-weight:800;color:#17365D;">{score_text}</div>
                <div style="font-size:0.66rem;color:#64748B;font-weight:600;">Trọng số: {weight:.0%}</div>
            </div>
            <div style="width:100%;height:4px;background:#EDF2F7;border-radius:4px;overflow:hidden;">
                <div style="width:{pct}%;height:100%;background:{bar_color};border-radius:4px;"></div>
            </div>
        </div>
    """).strip()

try:
    _qc_header_state = qc_background_worker.get_state()
except Exception:
    _qc_header_state = {}

if _qc_header_state.get("running"):
    _qc_header_label, _qc_header_bg, _qc_header_fg, _qc_header_border = "QC ĐANG THỰC THI", "#FFF7ED", "#9A3412", "#FED7AA"
elif _qc_header_state.get("queued"):
    _qc_header_label, _qc_header_bg, _qc_header_fg, _qc_header_border = "QC ĐANG XẾP HÀNG", "#EFF6FF", "#1D4ED8", "#BFDBFE"
elif _qc_header_state.get("last_error"):
    _qc_header_label, _qc_header_bg, _qc_header_fg, _qc_header_border = "QC CẦN KIỂM TRA", "#FEF2F2", "#991B1B", "#FECACA"
else:
    _qc_header_label, _qc_header_bg, _qc_header_fg, _qc_header_border = "QC ĐỊNH KỲ SẴN SÀNG", "#ECFDF5", "#065F46", "#A7F3D0"

st.markdown(
    f"""<div style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;padding:8px 14px;background:#FFFFFF;border:1px solid #CBD5E1;border-radius:10px;margin:0 0 3px 0;box-shadow:0 1px 3px rgba(15,23,42,0.04);">
        <div style="display:flex;align-items:center;gap:10px;">
            <span style="font-size:1.45rem;">🛢️</span>
            <h3 class="main-title" style="margin:0;padding:0;">HỆ THỐNG GIÁM SÁT CHẤT LƯỢNG DỮ LIỆU EPDB</h3>
        </div>
        <span style="font-size:.70rem;background:{_qc_header_bg};color:{_qc_header_fg};border:1px solid {_qc_header_border};padding:4px 9px;border-radius:6px;font-weight:800;letter-spacing:.02em;">{_qc_header_label}</span>
    </div>""",
    unsafe_allow_html=True,
)

DASHBOARD_VIEWS = ["Tổng quan", "Theo giếng", "Theo loại dữ liệu", "Cảnh báo AI", "QC chi tiết"]
_LEGACY_DASHBOARD_VIEWS = {"4.1 Tổng quan & DQS": "Tổng quan", "4.2 Theo giếng": "Theo giếng", "4.3 Theo loại dữ liệu": "Theo loại dữ liệu", "4.4 Cảnh báo AI": "Cảnh báo AI"}
_saved_view = st.session_state.get("epdb_active_dashboard_view")
if _saved_view in _LEGACY_DASHBOARD_VIEWS:
    st.session_state.epdb_active_dashboard_view = _LEGACY_DASHBOARD_VIEWS[_saved_view]
elif _saved_view not in DASHBOARD_VIEWS and _saved_view is not None:
    st.session_state.pop("epdb_active_dashboard_view", None)

TAB_ICON_MAP = {
    "Tổng quan": "📊 Tổng quan & DQS",
    "Theo giếng": "🕳️ Theo giếng",
    "Theo loại dữ liệu": "📑 Theo loại dữ liệu",
    "Cảnh báo AI": "🤖 Cảnh báo AI",
    "QC chi tiết": "🛡️ QC chi tiết",
}

st.markdown('<div class="epdb-nav-marker"></div>', unsafe_allow_html=True)
active_dashboard_view = st.radio(
    "Điều hướng Dashboard",
    options=DASHBOARD_VIEWS,
    index=0,
    horizontal=True,
    format_func=lambda x: TAB_ICON_MAP.get(x, x),
    key="epdb_active_dashboard_view",
    label_visibility="collapsed",
)

# =========================================================
# QC SNAPSHOT — mọi view dùng chung một summary đã cache; detail tải theo nhu cầu
# =========================================================
st.session_state.setdefault("qc_snapshot_cache_key", "initial")
qc_snapshot = get_qc_snapshot()
qc_summary_snapshot, qc_details_snapshot, qc_failures_snapshot, qc_entities_snapshot, qc_run_meta = qc_snapshot

# ---------------------------------------------------------
# 4.1 OVERVIEW / DQS
# ---------------------------------------------------------
if active_dashboard_view == "Tổng quan":
    qc_summary_for_metric = qc_summary_snapshot
    numeric_issues = pd.to_numeric(
        qc_summary_for_metric.get("Bản ghi / lượt vi phạm", pd.Series(dtype=float)),
        errors="coerce",
    )
    total_errors_count = int(numeric_issues.fillna(0).sum())
    total_qc_rules = int(len(qc_summary_for_metric))

    dqs_result = calculate_dqs(qc_summary_for_metric)
    dqs_scores = dqs_result["scores"]
    final_dqs = dqs_result["final_score"]

    basin_count = int(df_master["basin_name"].nunique())
    block_count = int(df_master["block_name"].nunique())
    field_count = int(df_master["field_name"].nunique())
    well_count = int(df_master["uwi"].nunique())
    borehole_count = int(df_master["ubhi"].nunique())

    if final_dqs is None:
        dqs_text, dqs_grade, dqs_status = "—", "Chưa đủ dữ liệu", "warning"
    elif final_dqs >= 85:
        dqs_text, dqs_grade, dqs_status = f"{final_dqs:.1f}/100", "Xếp hạng A · ≥ 85 điểm", "success"
    elif final_dqs >= 70:
        dqs_text, dqs_grade, dqs_status = f"{final_dqs:.1f}/100", "Xếp hạng B · 70–84,9 điểm", "teal"
    elif final_dqs >= 50:
        dqs_text, dqs_grade, dqs_status = f"{final_dqs:.1f}/100", "Xếp hạng C · 50–69,9 điểm", "warning"
    else:
        dqs_text, dqs_grade, dqs_status = f"{final_dqs:.1f}/100", "Xếp hạng D · < 50 điểm", "danger"

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        render_kpi_card("Quy mô EPDB", f"{block_count:,} Lô", f"{basin_count} Bể · {field_count} Mỏ", status="navy", icon="🌐", raise_up=True)
    with k2:
        render_kpi_card("Tài sản giếng", f"{well_count:,} Giếng", f"{borehole_count:,} Thân giếng · {wells_with_logs_count:,} có Log", status="navy", icon="🛢️", raise_up=True)
    with k3:
        render_kpi_card("Chỉ số DQS Tổng thể", dqs_text, dqs_grade, status=dqs_status, icon="🎯", raise_up=True)
    with k4:
        render_kpi_card(
            "Lượt vi phạm QC",
            f"{total_errors_count:,}" if qc_run_meta else "—",
            f"{total_qc_rules:,} quy tắc trong danh mục QC" if qc_run_meta else "Chưa có snapshot QC",
            status=("danger" if total_errors_count > 0 else "success") if qc_run_meta else "warning",
            icon="⚠️", raise_up=True,
        )

    # Ba khu vực cân đối: bản đồ trái, thống kê thân giếng ở giữa, DQS ở phải.
    col_map, col_field_chart, col_dqs = st.columns([1.15, 1.35, 1.10], gap="small")
    overview_plot_height = 505

    with col_map:
        with st.container(border=True):
            st.markdown("<div class='overview-panel-title'>🗺️ Vị trí giếng khoan</div>", unsafe_allow_html=True)
            key_name = GEOJSON_FEATURE_MATCH_KEY.split(".")[-1]
            geo_features = VN_BLOCKS_GEOJSON.get("features", []) if isinstance(VN_BLOCKS_GEOJSON, dict) else []
            all_blocks_geo = [
                str(feature.get("id") or feature.get("properties", {}).get(key_name, ""))
                for feature in geo_features if isinstance(feature, dict)
            ]
            all_blocks_geo = [value for value in all_blocks_geo if value]
            available_blocks = set(df_master["block_name"].dropna().astype(str).str.strip().unique())
            statuses = ["Có dữ liệu" if block in available_blocks else "Lô trống" for block in all_blocks_geo]
            z_values = [0.5 if block in available_blocks else 0.0 for block in all_blocks_geo]
            map_base = pd.DataFrame({"block_name": all_blocks_geo, "Trạng thái": statuses, "z": z_values})
            fig_map = go.Figure()

            if geo_features and not map_base.empty:
                fig_map.add_trace(go.Choroplethmapbox(
                    geojson=VN_BLOCKS_GEOJSON,
                    locations=map_base["block_name"],
                    featureidkey=GEOJSON_FEATURE_MATCH_KEY,
                    z=map_base["z"],
                    colorscale=[[0.0, "rgba(226,232,240,0.78)"], [1.0, "rgba(36,90,141,0.96)"]],
                    zmin=0, zmax=1, showscale=False,
                    text=map_base["block_name"] + " — " + map_base["Trạng thái"],
                    hoverinfo="text", name="Lô dầu khí",
                ))

            well_points_count = 0
            try:
                coords = get_well_map_coordinates()

                if not coords.empty:
                    coords = coords.dropna(subset=["lat", "lon"])

                    well_points_count = len(coords)

                    fig_map.add_trace(go.Scattermapbox(
                        lat=coords["lat"],
                        lon=coords["lon"],
                        mode="markers",
                        marker=go.scattermapbox.Marker(
                            size=7,
                            color="#D9485F",
                            opacity=0.92,
                        ),
                        text=coords["well_name"],
                        hovertemplate=(
                            "<b>%{text}</b>"
                            "<br>Tọa độ: (%{lat:.3f}°N, %{lon:.3f}°E)"
                            "<extra></extra>"
                        ),
                        name="Giếng khoan",
                    ))
            except Exception:
                pass

            fig_map.update_layout(
                mapbox_style="white-bg",
                mapbox_layers=[{"below": "traces", "sourcetype": "raster", "source": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"]}],
                mapbox=dict(center=dict(lat=13.0, lon=108.8), zoom=4.4),
                margin=dict(r=0, t=2, l=0, b=0), height=overview_plot_height,
                showlegend=False, paper_bgcolor="#FFFFFF", plot_bgcolor="#F7F9FC",
                font=dict(family="Arial, sans-serif", size=10, color="#26384A"),
            )
            st.plotly_chart(fig_map, use_container_width=True, config={"staticPlot": False, "displayModeBar": False, "scrollZoom": True, "responsive": True}, key="overview_well_map")



    with col_field_chart:
        with st.container(border=True):
            st.markdown("<div class='overview-panel-title'>🕳️ Số thân giếng theo từng mỏ</div>", unsafe_allow_html=True)
            field_scope = df_master[[column for column in ("field_id", "field_name", "ubhi") if column in df_master.columns]].copy()
            if "field_name" in field_scope.columns and "ubhi" in field_scope.columns and not field_scope.empty:
                field_scope["field_name"] = field_scope["field_name"].fillna("").astype(str).str.strip()
                field_scope["ubhi"] = field_scope["ubhi"].fillna("").astype(str).str.strip()
                if "field_id" in field_scope.columns:
                    field_scope["_field_key"] = field_scope["field_id"].map(
                        lambda value: str(value).strip() if pd.notna(value) and str(value).strip() else ""
                    )
                else:
                    field_scope["_field_key"] = ""
                field_scope["_field_key"] = field_scope["_field_key"].where(field_scope["_field_key"].ne(""), field_scope["field_name"])
                field_scope = field_scope[field_scope["_field_key"].ne("") & field_scope["field_name"].ne("")]
                field_counts = (
                    field_scope.groupby("_field_key", as_index=False, sort=False)
                    .agg(**{"Mỏ": ("field_name", "first"), "Số thân giếng": ("ubhi", lambda values: values[values.ne("")].nunique())})
                )
                duplicate_names = field_counts["Mỏ"].duplicated(keep=False)
                field_counts["Nhãn"] = field_counts["Mỏ"]
                field_counts.loc[duplicate_names, "Nhãn"] = (
                    field_counts.loc[duplicate_names, "Mỏ"] + " [" + field_counts.loc[duplicate_names, "_field_key"] + "]"
                ) if "_field_key" in field_counts.columns else field_counts.loc[duplicate_names, "Mỏ"]
                field_counts = field_counts.sort_values("Số thân giếng", ascending=False, kind="stable")
            else:
                field_counts = pd.DataFrame()

            if field_counts.empty:
                st.info("Chưa có dữ liệu mỏ hoặc liên kết thân giếng để thống kê.")
            else:
                bar_colors = ["#0F766E" if index == 0 else "#3977A8" for index in range(len(field_counts))]
                show_bar_labels = len(field_counts) <= 18
                fig_field_boreholes = go.Figure(go.Bar(
                    x=field_counts["Nhãn"], y=field_counts["Số thân giếng"],
                    marker=dict(color=bar_colors, line=dict(color="#FFFFFF", width=0.8)),
                    text=field_counts["Số thân giếng"] if show_bar_labels else None,
                    textposition="outside" if show_bar_labels else "none",
                    textfont=dict(size=10, color="#26384A", family="Arial, sans-serif"),
                    cliponaxis=False,
                    hovertemplate="<b>%{x}</b><br>Số thân giếng: %{y:,}<extra></extra>",
                ))
                label_angle = -55 if len(field_counts) > 8 else -30
                fig_field_boreholes.update_layout(
                    height=overview_plot_height,
                    margin=dict(l=50, r=16, t=20, b=105 if len(field_counts) > 8 else 76),
                    showlegend=False, bargap=0.30,
                    paper_bgcolor="#FFFFFF", plot_bgcolor="#FBFCFE",
                    font=dict(family="Arial, sans-serif", size=11, color="#26384A"),
                    xaxis=dict(title=dict(text="Mỏ", font=dict(size=11, color="#344B61")), tickangle=label_angle, tickfont=dict(size=10, color="#526174"), showgrid=False, showline=True, linecolor="#C7D2DE", automargin=True, ticks="outside", tickcolor="#C7D2DE"),
                    yaxis=dict(title=dict(text="Số thân giếng", font=dict(size=11, color="#344B61")), rangemode="tozero", gridcolor="#E5EBF2", tickfont=dict(size=10, color="#526174"), dtick=1, showline=False, zeroline=False),
                    uniformtext_minsize=8, uniformtext_mode="hide",
                )
                st.plotly_chart(fig_field_boreholes, use_container_width=True, config={"staticPlot": True, "displayModeBar": False, "responsive": True}, key="overview_boreholes_by_field")


    with col_dqs:
        with st.container(border=True):
            st.markdown(
                "<div class='overview-panel-title'>🎯 Chất lượng dữ liệu (DQS)</div>",
                unsafe_allow_html=True,
            )
            st.markdown("<div class='epdb-overview-dqs-marker'></div>", unsafe_allow_html=True)
            available_dimension_keys = [key for key in DQS_WEIGHTS if dqs_scores.get(key) is not None]
            if available_dimension_keys:
                radar_keys = list(DQS_WEIGHTS.keys())
                radar_labels = [key for key in radar_keys]
                radar_values = [dqs_scores.get(key) for key in radar_keys]
                radar = go.Figure()
                radar.add_trace(go.Scatterpolar(
                    r=radar_values + [radar_values[0]],
                    theta=radar_labels + [radar_labels[0]],
                    mode="lines+markers", fill="toself", name="Điểm hiện tại",
                    line=dict(color="#0F766E", width=2.4),
                    marker=dict(size=6, color="#0F766E", line=dict(color="#FFFFFF", width=1)),
                    fillcolor="rgba(15,118,110,0.20)", connectgaps=False,
                    hovertemplate="%{theta}: %{r:.1f}<extra></extra>",
                ))
                radar.add_trace(go.Scatterpolar(
                    r=[85] * 7, theta=radar_labels + [radar_labels[0]],
                    mode="lines", name="Mục tiêu 85",
                    line=dict(color="#D97706", width=1.7, dash="dot"),
                    hovertemplate="Mục tiêu: %{r}<extra></extra>",
                ))
                radar.update_layout(
                    height=225, margin=dict(l=28, r=28, t=6, b=28),
                    paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
                    font=dict(family="Arial, sans-serif", size=9, color="#344B61"),
                    showlegend=True,
                    legend=dict(orientation="h", y=-0.08, x=0.5, xanchor="center", font=dict(size=8, color="#526174")),
                    polar=dict(
                        bgcolor="#FBFCFE",
                        radialaxis=dict(visible=True, range=[0, 100], dtick=25, tickfont=dict(family="Arial Black, Arial, sans-serif", size=8, color="#526174"), gridcolor="#DCE4ED", linecolor="#DCE4ED"),
                        angularaxis=dict(tickfont=dict(family="Arial Black, Arial, sans-serif", size=9, color="#26384A"), gridcolor="#DCE4ED", linecolor="#DCE4ED"),
                    ),
                )
                st.plotly_chart(radar, use_container_width=True, config={"staticPlot": True, "displayModeBar": False, "responsive": True}, key="overview_dqs_radar")
            else:
                st.info("Chưa đủ dữ liệu để dựng biểu đồ sáu chiều DQS.")

            st.markdown(
                "<div style='font-size:.76rem;font-weight:800;color:#17365D;margin:1px 0 5px 0;'>Chi tiết sáu chiều</div>",
                unsafe_allow_html=True,
            )
            dimension_columns = st.columns(2, gap="small")
            for dimension_index, (dimension_key, weight_value) in enumerate(DQS_WEIGHTS.items()):
                score_value = dqs_scores.get(dimension_key)
                dimension_label = DQS_DIMENSION_LABELS[dimension_key].split(" — ")[1] if " — " in DQS_DIMENSION_LABELS[dimension_key] else dimension_key
                with dimension_columns[dimension_index % 2]:
                    st.markdown(
                        render_dimension_card_html(dimension_key, dimension_label, score_value, weight_value),
                        unsafe_allow_html=True,
                    )


# ---------------------------------------------------------
# 4.2 WELL VIEW — MANAGEMENT QC SUMMARY
# ---------------------------------------------------------
if active_dashboard_view == "Theo giếng":
    # Persistent non-widget keys survive when Streamlit removes hidden-tab widgets.
    _well_filter_specs = [
        {"level": "basin", "id_col": "basin_id", "name_col": "basin_name", "widget": "well_view_basin", "persist": "well_filter_selected_basin"},
        {"level": "block", "id_col": "block_id", "name_col": "block_name", "widget": "well_view_block", "persist": "well_filter_selected_block"},
        {"level": "field", "id_col": "field_id", "name_col": "field_name", "widget": "well_view_field", "persist": "well_filter_selected_field"},
        {"level": "well", "id_col": "uwi", "name_col": "well_name", "widget": "well_view_uwi", "persist": "well_filter_selected_uwi"},
        {"level": "borehole", "id_col": "ubhi", "name_col": "borehole_name", "widget": "well_view_ubhi", "persist": "well_filter_selected_ubhi"},
    ]

    def _well_clean_id(value):
        if value is None or pd.isna(value):
            return None
        result = str(value).strip()
        return result if result and result.casefold() not in {"nan", "none", "null"} else None

    def _well_entity_maps(frame):
        maps = {}
        for spec in _well_filter_specs:
            id_col, name_col = spec["id_col"], spec["name_col"]
            label_map = {}
            if id_col in frame.columns and name_col in frame.columns:
                subset = frame[[id_col, name_col]].dropna(subset=[id_col]).copy()
                subset[id_col] = subset[id_col].map(_well_clean_id)
                subset = subset[subset[id_col].notna()]
                for entity_id, entity_rows in subset.groupby(id_col, sort=False):
                    entity_name = None
                    for raw_name in entity_rows[name_col].tolist():
                        candidate = _well_clean_id(raw_name)
                        if candidate and _is_valid_asset_display_name(candidate):
                            # A legitimate well/borehole name may equal UWI/UBHI.
                            entity_name = candidate
                            break
                    # IDs without real display names are excluded from the options.
                    if entity_name:
                        label_map[str(entity_id)] = entity_name
            maps[spec["level"]] = label_map
        return maps

    _well_entity_labels = _well_entity_maps(df_master)

    def _well_scope_from_selection(selection, exclude_level=None):
        scoped_frame = df_master
        for spec in _well_filter_specs:
            if spec["level"] == exclude_level:
                continue
            selected_id = selection.get(spec["level"])
            if selected_id:
                col = spec["id_col"]
                scoped_frame = scoped_frame[
                    scoped_frame[col].map(_well_clean_id).eq(str(selected_id))
                ]
        return scoped_frame

    def _sync_well_filter_from(changed_level):
        changed_spec = next(spec for spec in _well_filter_specs if spec["level"] == changed_level)
        current_widget_value = _well_clean_id(st.session_state.get(changed_spec["widget"]))
        selection = {
            spec["level"]: _well_clean_id(st.session_state.get(spec["persist"]))
            for spec in _well_filter_specs
        }
        selection[changed_level] = current_widget_value

        # Clearing a parent is an explicit reset of its entire descendant branch.
        # Do this before compatibility checks: a child may exist elsewhere in the
        # database and must not survive merely because it remains globally valid.
        changed_index = next(
            index for index, spec in enumerate(_well_filter_specs)
            if spec["level"] == changed_level
        )
        if current_widget_value is None:
            for descendant_spec in _well_filter_specs[changed_index + 1:]:
                selection[descendant_spec["level"]] = None

        # The actively changed dropdown has priority. Retain every other existing
        # selection only if it belongs to the currently narrowed master-data scope.
        scope = df_master
        if current_widget_value:
            changed_col = changed_spec["id_col"]
            scope = scope[scope[changed_col].map(_well_clean_id).eq(current_widget_value)]
        for spec in _well_filter_specs:
            level = spec["level"]
            if level == changed_level:
                continue
            selected_id = selection.get(level)
            if not selected_id:
                continue
            id_col = spec["id_col"]
            compatible = scope[id_col].map(_well_clean_id).eq(selected_id).any()
            if compatible:
                scope = scope[scope[id_col].map(_well_clean_id).eq(selected_id)]
            else:
                selection[level] = None

        # Infer only ancestors of the deepest selected level. Descendants remain
        # available choices and are never silently auto-selected; users must select
        # through the Borehole level before QC/AI result tables are shown.
        selected_indexes = [
            index for index, spec in enumerate(_well_filter_specs)
            if selection.get(spec["level"])
        ]
        if selected_indexes:
            deepest_index = max(selected_indexes)
            for parent_index in range(deepest_index):
                parent_spec = _well_filter_specs[parent_index]
                parent_level = parent_spec["level"]
                if selection.get(parent_level):
                    continue
                parent_values = [
                    value for value in scope[parent_spec["id_col"]].map(_well_clean_id).dropna().unique().tolist()
                ]
                if len(parent_values) == 1:
                    inferred_id = parent_values[0]
                    selection[parent_level] = inferred_id
                    scope = scope[scope[parent_spec["id_col"]].map(_well_clean_id).eq(inferred_id)]

        # Persist both selected values and the currently rendered widget values.
        for spec in _well_filter_specs:
            value = selection.get(spec["level"])
            st.session_state[spec["persist"]] = value
            st.session_state[spec["widget"]] = value

    def _migrate_legacy_well_filter_state():
        """Migrate old name-based selections into stable ID-based session values."""
        legacy = {
            "basin": st.session_state.get("well_view_basin"),
            "block": st.session_state.get("well_view_block"),
            "field": st.session_state.get("well_view_field"),
            "well": st.session_state.get("well_view_uwi"),
            "borehole": st.session_state.get("well_view_ubhi"),
        }
        scope = df_master
        migrated = {spec["level"]: None for spec in _well_filter_specs}
        name_levels = [
            ("basin", "basin_name", "basin_id"),
            ("block", "block_name", "block_id"),
            ("field", "field_name", "field_id"),
        ]
        for level, name_col, id_col in name_levels:
            old_value = legacy.get(level)
            if old_value:
                match_scope = scope[scope[name_col].astype(str).str.strip().eq(str(old_value).strip())]
                ids = [value for value in match_scope[id_col].map(_well_clean_id).dropna().unique().tolist()]
                if len(ids) == 1:
                    migrated[level] = ids[0]
                    scope = scope[scope[id_col].map(_well_clean_id).eq(ids[0])]
        for level, id_col, token in (("well", "uwi", "UWI"), ("borehole", "ubhi", "UBHI")):
            old_value = legacy.get(level)
            if old_value:
                match = re.search(rf"\|\s*{token}\s+(.+)$", str(old_value))
                raw_id = match.group(1).strip() if match else str(old_value).strip()
                match_scope = scope[scope[id_col].map(_well_clean_id).eq(raw_id)]
                if not match_scope.empty:
                    migrated[level] = raw_id
                    scope = match_scope
        for spec in _well_filter_specs:
            st.session_state[spec["persist"]] = migrated.get(spec["level"])
            st.session_state.pop(spec["widget"], None)
        st.session_state["_well_filter_ui_version"] = 4

    if st.session_state.get("_well_filter_ui_version") != 4:
        _migrate_legacy_well_filter_state()

    # Remove stale selections whose entity no longer has a valid database name.
    # Clear the whole branch so hidden invalid IDs cannot persist across tab changes.
    for _invalid_index, _invalid_spec in enumerate(_well_filter_specs):
        _persisted_id = _well_clean_id(st.session_state.get(_invalid_spec["persist"]))
        if _persisted_id and _persisted_id not in _well_entity_labels.get(_invalid_spec["level"], {}):
            for _branch_spec in _well_filter_specs[_invalid_index:]:
                st.session_state[_branch_spec["persist"]] = None
                st.session_state[_branch_spec["widget"]] = None
            break

    # Restore widget values from durable keys after switching away from this tab.
    for _spec in _well_filter_specs:
        _widget_key = _spec["widget"]
        _persist_key = _spec["persist"]
        _persist_value = st.session_state.get(_persist_key)
        if _widget_key not in st.session_state or st.session_state.get(_widget_key) != _persist_value:
            st.session_state[_widget_key] = _persist_value

    filter_cols = st.columns(5)
    _well_selected_ids = {
        spec["level"]: _well_clean_id(st.session_state.get(spec["persist"]))
        for spec in _well_filter_specs
    }

    for _index, _spec in enumerate(_well_filter_specs):
        _level = _spec["level"]
        _scope_for_options = _well_scope_from_selection(_well_selected_ids, exclude_level=_level)
        _option_ids = [
            value for value in _scope_for_options[_spec["id_col"]].map(_well_clean_id).dropna().unique().tolist()
            if value in _well_entity_labels.get(_level, {})
        ]
        _option_ids.sort(key=lambda value: _well_entity_labels[_level].get(value, value).casefold())
        _label = {"basin": "Bể", "block": "Lô", "field": "Mỏ", "well": "Giếng", "borehole": "Thân giếng"}[_level]
        _placeholder = {
            "basin": "Tất cả bể",
            "block": "Tất cả lô",
            "field": "Tất cả mỏ",
            "well": "Tất cả giếng",
            "borehole": "Chọn thân giếng",
        }[_level]
        filter_cols[_index].selectbox(
            _label,
            options=_option_ids,
            index=None,
            placeholder=_placeholder,
            format_func=lambda value, level=_level: _well_entity_labels[level].get(str(value), str(value)),
            key=_spec["widget"],
            on_change=_sync_well_filter_from,
            args=(_level,),
            disabled=not _option_ids,
        )

    # Re-read the synchronized IDs after all dropdowns have been instantiated.
    _well_selected_ids = {
        spec["level"]: _well_clean_id(st.session_state.get(spec["persist"]))
        for spec in _well_filter_specs
    }
    selected_basin_id = _well_selected_ids["basin"]
    selected_block_id = _well_selected_ids["block"]
    selected_field_id = _well_selected_ids["field"]
    selected_uwi = _well_selected_ids["well"]
    selected_ubhi = _well_selected_ids["borehole"]

    selected_basin = _well_entity_labels["basin"].get(selected_basin_id) if selected_basin_id else None
    selected_block = _well_entity_labels["block"].get(selected_block_id) if selected_block_id else None
    selected_field = _well_entity_labels["field"].get(selected_field_id) if selected_field_id else None
    selected_well_label = _well_entity_labels["well"].get(selected_uwi) if selected_uwi else None
    selected_bh_label = _well_entity_labels["borehole"].get(selected_ubhi) if selected_ubhi else None
    well_labels = {
        label: entity_id for entity_id, label in _well_entity_labels["well"].items()
    }
    bh_labels = {
        label: entity_id for entity_id, label in _well_entity_labels["borehole"].items()
        if selected_uwi and entity_id in set(
            df_master.loc[df_master["uwi"].map(_well_clean_id).eq(selected_uwi), "ubhi"].map(_well_clean_id).dropna().tolist()
        )
    }
    well_options = [value for value in _well_entity_labels["well"]]

    if selected_ubhi is None:
        # Keep the result region visually empty until the user selects a borehole.
        # Intermediate selection guidance is omitted to reduce sidebar/dashboard clutter.
        pass
    else:
        _selected_borehole_rows = df_master[df_master["ubhi"].map(_well_clean_id).eq(selected_ubhi)]
        if not selected_uwi and not _selected_borehole_rows.empty:
            selected_uwi = _well_clean_id(_selected_borehole_rows.iloc[0].get("uwi"))
        well_rows = df_master[df_master["uwi"].map(_well_clean_id).eq(selected_uwi)]
        curr_well_name = _explorer_name_for_key(
            well_rows, "uwi", selected_uwi, "well_name", ""
        )

        # Kết quả theo giếng chỉ đọc snapshot của chu kỳ QC toàn hệ thống.
        # Thay đổi bộ lọc không được gọi Rule Engine hay chạy lại bất kỳ luật nào.
        qc_run_id = str((qc_run_meta or {}).get("run_id") or "")
        well_snapshot_ready = bool((qc_run_meta or {}).get("well_summary_ready"))
        scope_signature = f"{qc_run_id}|{selected_uwi}|{selected_ubhi or '*'}"

        # AI LAS đã được ngừng sử dụng.
        # Chờ mô-đun phát hiện bất thường áp suất được tích hợp.
        ai_details = pd.DataFrame()
        ai_count = None

        if qc_run_id and well_snapshot_ready:
            scoped_qc_summary = load_qc_well_summary_cached(
                qc_run_id,
                str(selected_uwi),
                str(selected_ubhi) if selected_ubhi else None,
            )
            scoped_qc_has_run = True
        else:
            scoped_qc_summary = pd.DataFrame(columns=[
                "Mã luật", "Lĩnh vực", "Nhóm kiểm tra", "Yêu cầu kiểm tra",
                "Chiều DQS", "Mẫu đánh giá", "Bản ghi / lượt vi phạm", "Kết quả", "Lỗi kỹ thuật",
            ])
            scoped_qc_has_run = False

        qc_issue_num = pd.to_numeric(
            scoped_qc_summary.get("Bản ghi / lượt vi phạm", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0)
        qc_rule_count = len(scoped_qc_summary)
        qc_rules_with_issues = int((scoped_qc_summary.get("Kết quả", pd.Series(dtype=str)) == "Có lỗi").sum()) if qc_rule_count else 0
        qc_issue_total = int(qc_issue_num.sum())
        qc_unchecked = int((scoped_qc_summary.get("Kết quả", pd.Series(dtype=str)) == "Chưa kiểm tra được").sum()) if qc_rule_count else 0
        qc_no_data = int((scoped_qc_summary.get("Kết quả", pd.Series(dtype=str)) == "Chưa có dữ liệu").sum()) if qc_rule_count else 0

        k1, k2, k3, k4 = st.columns(4)
        with k1:
            render_kpi_card("Luật QC theo giếng", f"{qc_rule_count:,}" if scoped_qc_has_run else "—",
                            "Kết quả từ chu kỳ toàn hệ thống", status="navy", icon="📋")
        with k2:
            render_kpi_card("Luật phát hiện lỗi", f"{qc_rules_with_issues:,}" if scoped_qc_has_run else "—",
                            "Quy tắc không đạt chuẩn", status="warning" if qc_rules_with_issues > 0 else "success", icon="⚠️")
        with k3:
            render_kpi_card("Lượt vi phạm", f"{qc_issue_total:,}" if scoped_qc_has_run else "—",
                            "Bản ghi ngoài quy chuẩn", status="danger" if qc_issue_total > 0 else "success", icon="🚨")
        with k4:
            render_kpi_card(
                "Cảnh báo AI áp suất",
                "—",
                "Mô hình phát hiện bất thường áp suất đang được thay thế",
                status="neutral",
                icon="🤖",
            )

        if not scoped_qc_has_run:
            well_worker_state = qc_background_worker.get_state()
            if well_worker_state.get("running"):
                st.info("Chu kỳ QC toàn hệ thống đang chạy nền. Kết quả theo giếng sẽ xuất hiện sau khi snapshot hoàn tất.")
            elif well_worker_state.get("queued"):
                st.info("Yêu cầu QC toàn hệ thống đang chờ xử lý. Không cần chạy QC riêng cho giếng đang chọn.")
            elif well_worker_state.get("last_error"):
                st.error(f"Không tạo được snapshot QC theo giếng: {well_worker_state['last_error']}")
            else:
                st.warning("Chưa có snapshot QC theo giếng. Chu kỳ QC toàn hệ thống sẽ tự tạo dữ liệu phân rã theo giếng và thân giếng khi ứng dụng hoạt động; không cần chạy QC riêng từng giếng.")
        elif scoped_qc_summary.empty:
            st.warning("Snapshot toàn hệ thống đã có, nhưng chưa có bản ghi tổng hợp cho giếng này. Kiểm tra trạng thái tổng hợp theo giếng của chu kỳ QC.")
        else:
            st.markdown('<div class="overview-panel-title">Đánh giá chất lượng theo lĩnh vực chuyên môn</div>', unsafe_allow_html=True)
            domain_rows = []
            for domain, group in scoped_qc_summary.groupby("Lĩnh vực", dropna=False, sort=False):
                counts = pd.to_numeric(group["Bản ghi / lượt vi phạm"], errors="coerce").fillna(0)
                statuses = group["Kết quả"].astype(str)
                domain_rows.append({
                    "Lĩnh vực": domain,
                    "Số luật": len(group),
                    "Luật có lỗi": int((statuses == "Có lỗi").sum()),
                    "Lượt vi phạm": int(counts.sum()),
                    "Chưa kiểm tra được": int((statuses == "Chưa kiểm tra được").sum()),
                    "Chưa có mẫu": int((statuses == "Chưa có dữ liệu").sum()),
                })
            if domain_rows:
                render_interactive_table(
                    pd.DataFrame(domain_rows),
                    highlight_first_column=True,
                )

            with st.expander("Danh sách luật QC áp dụng cho phạm vi này", expanded=False):
                columns_show = [c for c in [
                    "Mã luật", "Lĩnh vực", "Nhóm kiểm tra", "Yêu cầu kiểm tra",
                    "Mẫu đánh giá", "Bản ghi / lượt vi phạm", "Kết quả", "Lỗi kỹ thuật",
                ] if c in scoped_qc_summary]
                render_interactive_table(
                    format_integer_columns(scoped_qc_summary[columns_show]),
                    height=min(480, max(180, 32 * (min(len(scoped_qc_summary), 14) + 1))),
                    highlight_first_column=True,
                )

            # Load only details for rules that have violations in this selected scope.
            # Each rule-detail payload comes from the same full-system QC run.
            selected_ubhis = [str(selected_ubhi)]
            violation_frames = []
            detail_unattributed = []
            if qc_run_id:
                for _, rule_row in scoped_qc_summary[scoped_qc_summary["Kết quả"] == "Có lỗi"].iterrows():
                    rule_id = str(rule_row.get("Mã luật", "")).strip()
                    if not rule_id:
                        continue
                    global_detail = load_qc_rule_detail_cached(qc_run_id, rule_id)
                    selected_scope_rows = df_master[
                        df_master["ubhi"].map(_well_clean_id).eq(selected_ubhi)
                    ]

                    selected_well_id = None
                    selected_borehole_id = None

                    if not selected_scope_rows.empty:
                        selected_well_id = selected_scope_rows.iloc[0]["well_id"]
                        selected_borehole_id = selected_scope_rows.iloc[0]["wellbore_id"]
                    filtered_detail = filter_qc_detail_for_well(
                        global_detail,
                        str(selected_uwi),
                        str(selected_ubhi) if selected_ubhi else None,
                        selected_ubhis,
                        selected_well_name,
                        selected_well_id=selected_well_id,
                        selected_borehole_id=selected_borehole_id,
                    )
                    if not filtered_detail.empty:
                        filtered_detail = ensure_unique_dataframe_columns(filtered_detail)
                        if "Mã luật" not in filtered_detail.columns:
                            filtered_detail.insert(0, "Mã luật", rule_id)
                        if "Luật QC" not in filtered_detail.columns:
                            filtered_detail.insert(1, "Luật QC", str(rule_row.get("Nhóm kiểm tra", "")))
                        violation_frames.append(filtered_detail)
                    elif global_detail is not None and not global_detail.empty:
                        detail_unattributed.append(rule_id)

            if violation_frames:
                # Bỏ các cột toàn NA ở từng frame trước concat. Những cột có dữ liệu
                # ở frame khác vẫn được pandas giữ lại trong phép hợp nhất; cách này
                # tránh FutureWarning về dtype khi nối các frame có cột rỗng hoàn toàn.
                concat_frames = []
                for detail_frame in violation_frames:
                    if detail_frame is None or detail_frame.empty:
                        continue
                    useful_columns = detail_frame.columns[~detail_frame.isna().all(axis=0)]
                    if len(useful_columns):
                        concat_frames.append(detail_frame.loc[:, useful_columns])

                if concat_frames:
                    all_violation_details = ensure_unique_dataframe_columns(
                        pd.concat(concat_frames, ignore_index=True, sort=False)
                    )
                    with st.expander(f"Bản ghi vi phạm của phạm vi đã chọn ({len(all_violation_details):,} dòng)", expanded=False):
                        render_interactive_table(
                            all_violation_details,
                            height=min(520, max(180, 34 * (min(len(all_violation_details), 14) + 1))),
                            highlight_first_column=True,
                        )
                else:
                    st.info("Các luật có ghi nhận vi phạm nhưng không có cột dữ liệu chi tiết hợp lệ để hiển thị.")

        if not ai_details.empty:
            st.markdown('<div class="overview-panel-title" style="margin-top:14px;">Cảnh báo AI trên thân giếng đang chọn</div>', unsafe_allow_html=True)
            col_lookup = {normalize_column_name(c): c for c in ai_details.columns}
            actual = lambda key: col_lookup.get(normalize_column_name(key))
            alert_view = pd.DataFrame(index=ai_details.index)
            alert_view["Giếng"] = curr_well_name if curr_well_name else "Giếng chưa có tên"
            alert_view["Thân giếng"] = selected_bh_label if selected_bh_label else "Thân giếng chưa có tên"
            md_start_col = actual("md_m")
            md_end_col = actual("md_end_m")
            if md_start_col:
                md_start = pd.to_numeric(ai_details[md_start_col], errors="coerce")
                md_end = pd.to_numeric(ai_details[md_end_col], errors="coerce") if md_end_col else md_start
                alert_view["Khoảng MD (m)"] = [
                    f"{a:,.2f} – {b:,.2f}" if pd.notna(a) and pd.notna(b) else "—"
                    for a, b in zip(md_start, md_end)
                ]
            level_source = actual("prediction_label") or actual("status")
            if level_source:
                alert_view["Mức ưu tiên"] = ai_details[level_source].map(_ai_las_level_label)
            evidence_source = actual("feature_name") or actual("evidence")
            description_source = actual("description")
            type_source = actual("anomaly_type")
            alert_view["Dấu hiệu"] = ai_details.apply(
                lambda row: _ai_las_signal_group(
                    row.get(evidence_source) if evidence_source else "",
                    row.get(description_source) if description_source else "",
                    row.get(type_source) if type_source else "",
                ), axis=1,
            )
            alert_view["Đường cong"] = ai_details.apply(
                lambda row: _ai_las_curve_names(
                    row.get(evidence_source) if evidence_source else "",
                    row.get(description_source) if description_source else "",
                ), axis=1,
            )
            render_interactive_table(
                alert_view,
                height=min(320, max(110, 34 * (len(alert_view) + 1))),
                highlight_first_column=True,
            )
        elif not scoped_qc_has_run:
            st.info("Chưa có cảnh báo AI và chưa có snapshot QC theo giếng cho phạm vi này.")

# ---------------------------------------------------------
# 4.3 DATA-TYPE VIEW — MANAGEMENT QC SUMMARY
# ---------------------------------------------------------
if active_dashboard_view == "Theo loại dữ liệu":
    categories = {
        "Master data — Danh mục & liên kết": [("epdb_basin", "Bể"), ("epdb_block", "Lô"), ("epdb_field", "Mỏ"), ("epdb_well", "Giếng"), ("epdb_borehole", "Thân giếng")],
        "Geological — Địa chất": [("epdb_document", "Tài liệu"), ("epdb_seismic", "Địa chấn"), ("epdb_marker", "Marker địa tầng"), ("epdb_checkshot", "Checkshot"), ("epdb_stratigraphy", "Stratigraphy"), ("epdb_biostratigraphy", "Biostratigraphy"), ("epdb_data_metadata", "Metadata")],
        "Petrophysical — Địa vật lý / mẫu lõi": [("epdb_log_data", "Well Log"), ("epdb_deviation", "Deviation"), ("epdb_core_plug_analysis", "Mẫu lõi"), ("epdb_core_information", "Thông tin mẫu lõi"), ("epdb_mud_log", "Mud Log"), ("epdb_log_metadata", "Log Curve"), ("epdb_log_dataset", "Log Dataset"), ("epdb_geochemistry", "Geochemistry")],
        "Production — Khai thác (QC riêng)": [("epdb_production", "Dữ liệu khai thác")],
        "Reservoir — Vỉa chứa": [("epdb_reservoir", "Reservoir")],
        "Cross-Domain — Liên miền": [("epdb_qc_cross_domain", "QC liên miền"), ("epdb_export_audit", "Lịch sử export"), ("epdb_ai_dataset_audit", "AI dataset readiness")],
    }
    all_table_names = set(get_all_table_names_cached())
    reservoir_candidates = sorted(t for t in all_table_names if ("reservoir" in t.lower() or "via" in normalize_column_name(t)) and t != "epdb_reservoir")
    categories["Reservoir — Vỉa chứa"] = [("epdb_reservoir", "Reservoir")] + [(t, t) for t in reservoir_candidates]

    category_nav = {
        "🏛️ Master": "Master data — Danh mục & liên kết",
        "🌍 Địa chất": "Geological — Địa chất",
        "🔬 Địa vật lý": "Petrophysical — Địa vật lý / mẫu lõi",
        "⚡ Khai thác": "Production — Khai thác (QC riêng)",
        "🛢️ Vỉa chứa": "Reservoir — Vỉa chứa",
        "🔗 Liên miền": "Cross-Domain — Liên miền",
    }
    st.markdown('<div class="epdb-cat-nav-marker"></div>', unsafe_allow_html=True)
    selected_category_short = st.radio("Nhóm dữ liệu", list(category_nav.keys()), horizontal=True, key="data_type_category_nav", label_visibility="collapsed")
    selected_category = category_nav[selected_category_short]

    try:
        qc_summary, _, _, _ = execute_qc_checks()
    except Exception:
        qc_summary = pd.DataFrame(columns=["Nhóm kiểm tra", "Bản ghi / lượt vi phạm", "Đối tượng liên quan", "Kết quả", "Lỗi kỹ thuật"])

    def _category_for_check(check_name: str, domain: str = "") -> str | None:
        src = str(domain or "")
        if src == "Production QC": return "Production — Khai thác (QC riêng)"
        if src == "Reservoir QC": return "Reservoir — Vỉa chứa"
        if src == "Cross-Domain QC": return "Cross-Domain — Liên miền"
        if src in {"Well Header QC", "Coordinate QC"}: return "Master data — Danh mục & liên kết"
        if src in {"Stratigraphy QC", "Biostratigraphy QC", "Seismic Survey QC"}: return "Geological — Địa chất"
        if src == "Metadata QC": return "Cross-Domain — Liên miền"
        if src in {"Wellbore QC", "Directional Survey QC", "Well Log QC", "Core Data QC", "Mud Log QC", "Geochemistry QC"}: return "Petrophysical — Địa vật lý / mẫu lõi"
        name = str(check_name).lower()
        if any(x in name for x in ("khai thác", "production")): return "Production — Khai thác (QC riêng)"
        if "reservoir" in name or "vỉa" in name: return "Reservoir — Vỉa chứa"
        if any(x in name for x in ("log", "quỹ đạo", "mẫu lõi", "core", "deviation")): return "Petrophysical — Địa vật lý / mẫu lõi"
        return None

    mapped = qc_summary.copy()
    if not mapped.empty and "Nhóm kiểm tra" in mapped.columns:
        mapped["Nhóm dữ liệu"] = mapped.apply(lambda r: _category_for_check(r.get("Nhóm kiểm tra", ""), r.get("Lĩnh vực", "")), axis=1)
        category_checks = mapped[mapped["Nhóm dữ liệu"] == selected_category].copy()
    else:
        category_checks = pd.DataFrame()

    if selected_category == "Reservoir — Vỉa chứa" and not any(t in all_table_names for t, _ in categories[selected_category]):
        st.info("Chưa có bảng Reservoir trong schema. Các luật RS-01 đến RS-06 được liệt kê ở QC chi tiết là Chưa kiểm tra được cho đến khi bổ sung bảng/cột.")

    if category_checks.empty:
        st.info("Chưa có luật QC được liên kết với nhóm dữ liệu này.")
    else:
        issue_counts = pd.to_numeric(category_checks["Bản ghi / lượt vi phạm"], errors="coerce")
        issue_total = int(issue_counts.fillna(0).sum())
        issue_groups = int((issue_counts.fillna(0) > 0).sum())
        not_checked_count = int((category_checks["Kết quả"] == "Chưa kiểm tra được").sum())
        checked_count = int((category_checks["Kết quả"] != "Chưa kiểm tra được").sum())
        checked_eval = category_checks[category_checks["Kết quả"].isin(["Đạt", "Có lỗi"])]
        passed_rules = int((category_checks["Kết quả"] == "Đạt").sum())
        compliance_rate = round(100.0 * passed_rules / len(checked_eval), 1) if not checked_eval.empty else 0.0

        k1, k2, k3, k4 = st.columns(4)
        with k1:
            render_kpi_card("Số luật QC", f"{len(category_checks):,}", f"{checked_count} luật đã đánh giá", status="navy", icon="📚")
        with k2:
            render_kpi_card("Tỷ lệ tuân thủ", f"{compliance_rate:.1f}%", f"{passed_rules}/{len(checked_eval)} quy tắc đạt", status="success" if compliance_rate >= 85 else "warning", icon="📈")
        with k3:
            render_kpi_card("Luật cần xử lý", f"{issue_groups:,}", "Phát hiện bản ghi lỗi", status="danger" if issue_groups > 0 else "success", icon="⚠️")
        with k4:
            render_kpi_card("Lượt vi phạm bản ghi", f"{issue_total:,}", f"{not_checked_count} quy tắc chưa kiểm tra", status="danger" if issue_total > 0 else "neutral", icon="🔥")

        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
        col_pie, col_tbl = st.columns([0.38, 0.62], gap="medium")
        with col_pie:
            st.markdown("<div class='overview-panel-title'>Cơ cấu trạng thái quy tắc</div>", unsafe_allow_html=True)
            status_series = category_checks["Kết quả"].replace({"Có lỗi": "Cần xử lý", "Chưa kiểm tra được": "Chưa kiểm tra"}).value_counts()
            color_pie_map = {"Đạt": "#10B981", "Cần xử lý": "#EF4444", "Chưa kiểm tra": "#F59E0B", "Chưa có dữ liệu": "#94A3B8"}
            fig_donut = go.Figure(go.Pie(
                labels=status_series.index, values=status_series.values, hole=0.55,
                marker=dict(colors=[color_pie_map.get(s, "#CBD5E1") for s in status_series.index]),
                textinfo="label+value", hovertemplate="<b>%{label}</b>: %{value} luật (%{percent})<extra></extra>",
            ))
            fig_donut.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
            st.plotly_chart(fig_donut, use_container_width=True, config={"staticPlot": True, "displayModeBar": False, "responsive": True})

        with col_tbl:
            st.markdown("<div class='overview-panel-title'>Chi tiết các quy tắc kiểm tra</div>", unsafe_allow_html=True)
            display_cols = [c for c in ["Mã luật", "Nhóm kiểm tra", "Bản ghi / lượt vi phạm", "Kết quả"] if c in category_checks.columns]
            display = category_checks[display_cols].rename(columns={"Nhóm kiểm tra": "Luật QC", "Bản ghi / lượt vi phạm": "Lượt vi phạm", "Kết quả": "Trạng thái"}).copy()
            display["Trạng thái"] = display["Trạng thái"].replace({"Có lỗi": "Cần xử lý", "Chưa kiểm tra được": "Chưa kiểm tra"})
            render_styled_html_table(
                format_integer_columns(display),
                height=260,
                highlight_first_column=True,
            )

# ---------------------------------------------------------
# 4.4 AI ALERT DASHBOARD / PERSISTED LATEST RUN
# ---------------------------------------------------------
def _ai_las_level_label(value: Any) -> str:
    token = str(value or "").strip().casefold().replace("_", " ")
    if token in {"abnormal candidate", "abnormal", "ứng viên bất thường"}:
        return "Ưu tiên kiểm tra"
    if token in {"warning", "warning candidate", "warn", "cần kiểm tra"}:
        return "Cần kiểm tra"
    return "Chưa phân loại"


def _ai_las_signal_group(evidence: Any = "", description: Any = "", anomaly_type: Any = "") -> str:
    """Return one compact category so charts do not fragment into long phrases."""
    text_blob = f"{evidence or ''} {description or ''} {anomaly_type or ''}".upper()
    if "VÙNG TÍN HIỆU KHÁC BIỆT KÉO DÀI" in text_blob:
        return "Vùng tín hiệu khác biệt kéo dài"
    if "ĐOẠN TÍN HIỆU CẦN XEM XÉT" in text_blob:
        return "Đoạn tín hiệu cần xem xét"
    if "SPIKE_OR_LOCAL_OUTLIER" in text_blob:
        return "Đột biến cục bộ"
    if "RAPID_CHANGE" in text_blob:
        return "Thay đổi nhanh"
    if "LEVEL_SHIFT_OR_DRIFT" in text_blob:
        return "Dịch chuyển tín hiệu"
    if "HIGH_FREQUENCY_NOISE" in text_blob:
        return "Nhiễu tín hiệu"
    if "FLATLINE" in text_blob:
        return "Tín hiệu đi ngang kéo dài"
    if "_TO_" in text_blob and ("_RELATION" in text_blob or "PREDICTS" in text_blob):
        return "Quan hệ giữa các đường cong"
    if "ISOLATION_FOREST" in text_blob or "_SINGLE" in text_blob or "ISOLATION FOREST" in text_blob:
        return "Khác biệt so với tham chiếu"
    return "Tín hiệu cần kiểm tra"


def _ai_las_curve_names(evidence: Any = "", description: Any = "") -> str:
    """Show at most two leading curve signals, preserving model evidence order."""
    allowed = {"GR", "CALI", "NPHI", "RHOB", "DT", "SP", "LLD", "LLS", "MSFL"}
    found = []

    def add_curve(value):
        value = str(value).strip().upper()
        if value in allowed and value not in found:
            found.append(value)

    for token in str(evidence or "").upper().split(";"):
        token = token.strip()
        if token.endswith("_SINGLE"):
            add_curve(token[:-7])
        elif token.endswith("_RELATION") and "_TO_" in token:
            for part in token.replace("_RELATION", "").split("_TO_"):
                add_curve(part)

    description_text = str(description or "")
    match = re.search(r"(?:lý do|reasons)\s*:\s*(.*?)(?:\.\s*Điểm là|$)", description_text, flags=re.IGNORECASE)
    if match:
        for token in match.group(1).split(";"):
            add_curve(token.strip().upper().split(":", 1)[0])

    if len(found) > 2:
        return f"{', '.join(found[:2])} và {len(found) - 2} đường cong khác"
    return ", ".join(found) or "Chưa xác định"


def _ai_las_merge_display_zones(events: pd.DataFrame) -> pd.DataFrame:
    """Merge overlapping detector events into physical MD zones for display only.

    Stored AI events are not changed. Events from different curves at the same
    or overlapping MD are represented by one display row, with their signal
    count and contributing curves retained separately.
    """
    if events is None or events.empty:
        return pd.DataFrame()

    curve_order = ["GR", "CALI", "NPHI", "RHOB", "DT", "SP", "LLD", "LLS", "MSFL"]
    records = []
    group_col = "_borehole_key" if "_borehole_key" in events.columns else "_borehole"

    for _, group in events.groupby(group_col, dropna=False, sort=False):
        group = group.sort_values(["_md_start", "_md_end"], kind="mergesort")
        current = None
        for row in group.to_dict(orient="records"):
            start = pd.to_numeric(row.get("_md_start"), errors="coerce")
            end = pd.to_numeric(row.get("_md_end"), errors="coerce")
            if pd.isna(start) or pd.isna(end):
                continue
            start, end = float(min(start, end)), float(max(start, end))
            if current is None or start > current["_md_end"] + 1e-6:
                if current is not None:
                    records.append(current)
                current = {
                    "_well": row.get("_well", ""),
                    "_borehole": row.get("_borehole", ""),
                    "_borehole_key": row.get("_borehole_key", ""),
                    "_md_start": start,
                    "_md_end": end,
                    "_levels": {str(row.get("_level") or "")},
                    "_issues": {str(row.get("_issue") or "")},
                    "_curves": set(),
                    "_times": [row.get("_time")],
                    "_signal_events": 0,
                    "_scored_depth_m": row.get("_scored_depth_m", np.nan),
                }
            else:
                current["_md_end"] = max(current["_md_end"], end)
                current["_levels"].add(str(row.get("_level") or ""))
                current["_issues"].add(str(row.get("_issue") or ""))
                current["_times"].append(row.get("_time"))
            # Parse only approved curve mnemonics from the display-ready text.
            curve_text = str(row.get("_curves") or "").upper()
            for curve in curve_order:
                if re.search(rf"(?<![A-Z0-9]){re.escape(curve)}(?![A-Z0-9])", curve_text):
                    current["_curves"].add(curve)
            current["_signal_events"] += 1

        if current is not None:
            records.append(current)

    output = []
    for item in records:
        curves = [curve for curve in curve_order if curve in item["_curves"]]
        if len(curves) > 2:
            curve_label = f"{', '.join(curves[:2])} và {len(curves) - 2} đường cong khác"
        else:
            curve_label = ", ".join(curves) if curves else "Chưa xác định"
        issues = sorted(issue for issue in item["_issues"] if issue and issue != "Chưa xác định")
        issue_label = issues[0] if len(issues) == 1 else ("Nhiều dấu hiệu" if issues else "Tín hiệu cần kiểm tra")
        level_label = "Ưu tiên kiểm tra" if "Ưu tiên kiểm tra" in item["_levels"] else "Cần kiểm tra"
        width = max(0.0, item["_md_end"] - item["_md_start"])
        scored_depth = pd.to_numeric(item.get("_scored_depth_m"), errors="coerce")
        share = (100.0 * width / float(scored_depth)) if pd.notna(scored_depth) and scored_depth > 0 else np.nan
        valid_times = [pd.Timestamp(t) for t in item["_times"] if t is not None and pd.notna(t)]
        output.append({
            "_well": item["_well"],
            "_borehole": item["_borehole"],
            "_borehole_key": item["_borehole_key"],
            "_md_start": item["_md_start"],
            "_md_end": item["_md_end"],
            "_md_width": width,
            "_md_share_pct": share,
            "_level": level_label,
            "_issue": issue_label,
            "_curves": curve_label,
            "_time": max(valid_times) if valid_times else pd.NaT,
            "_signal_event_count": int(item["_signal_events"]),
        })
    return pd.DataFrame(output)


def _show_more_ai_alert_rows(state_key: str, total_rows: int, page_size: int = 50) -> None:
    """Increase visible AI alert rows by one page before Streamlit reruns."""
    current = int(st.session_state.get(state_key, page_size))
    st.session_state[state_key] = min(current + page_size, int(total_rows))

def render_ai_alert_dashboard(db_engine):
    """User-facing LAS AI dashboard. Displays event counts and MD extent separately.

    Alert intervals are scored per borehole (UBHI / source dataset). This view
    also aggregates rankings per borehole, never by well name alone.
    """
    try:
        alerts, run_meta, refresh_error = load_ai_las_dashboard_snapshot(db_engine)
    except Exception:
        alerts, run_meta, refresh_error = pd.DataFrame(), None, "Không đọc được kết quả phân tích AI. Vui lòng kiểm tra kết nối CSDL và thử lại."

    if refresh_error and run_meta is None:
        st.info("Chưa có kết quả phân tích AI để hiển thị. Hãy chạy chương trình phân tích LAS độc lập trước.")
        return
    if not run_meta:
        st.info("Chưa có kết quả phân tích AI để hiển thị.")
        return

    def find_col(df, candidates):
        lookup = {normalize_column_name(c): c for c in df.columns}
        for candidate in candidates:
            key = normalize_column_name(candidate)
            if key in lookup:
                return lookup[key]
        return None

    def clean_value(value):
        if value is None or pd.isna(value):
            return ""
        value = str(value).strip()
        return "" if value.casefold() in {"", "nan", "none", "null", "<na>"} else value

    def make_lookup(frame, key_col, value_col):
        result = {}
        if frame is None or frame.empty or not {key_col, value_col}.issubset(frame.columns):
            return result
        for _, item in frame[[key_col, value_col]].dropna().iterrows():
            key = clean_value(item[key_col]).casefold()
            value = clean_value(item[value_col])
            if key and value:
                result.setdefault(key, value)
        return result

    master = df_master.copy() if isinstance(df_master, pd.DataFrame) else pd.DataFrame()
    well_by_uwi = make_lookup(master, "uwi", "well_name")
    well_by_ubhi = make_lookup(master, "ubhi", "well_name")
    borehole_by_ubhi = make_lookup(master, "ubhi", "borehole_name")

    # Resolve labels directly from epdb_well and epdb_borehole, not only from
    # the hierarchy DataFrame. IDs remain internal and are never shown as labels.
    direct_well_by_uwi, direct_uwi_by_ubhi, direct_borehole_by_ubhi = {}, {}, {}
    try:
        inspector = sqlalchemy_inspect(db_engine)
        def _direct_columns(table_name):
            if not inspector.has_table(table_name):
                return []
            return [str(item["name"]) for item in inspector.get_columns(table_name)]
        def _direct_pick(columns, *candidates):
            for candidate in candidates:
                for actual in columns:
                    if normalize_column_name(actual) == normalize_column_name(candidate):
                        return actual
            return None
        def _direct_name_expr(alias, columns, *candidates):
            matches = []
            for candidate in candidates:
                for actual in columns:
                    if normalize_column_name(actual) == normalize_column_name(candidate) and actual not in matches:
                        matches.append(actual)
            if not matches:
                return None
            parts = [f"NULLIF(BTRIM({alias}.{quote_ident(actual)}::text), '')" for actual in matches]
            return f"COALESCE({', '.join(parts)})"
        well_cols = _direct_columns("epdb_well")
        borehole_cols = _direct_columns("epdb_borehole")
        w_uwi = _direct_pick(well_cols, "uwi")
        w_name_expr = _direct_name_expr("w", well_cols, "well_name", "wellname", "name")
        b_ubhi = _direct_pick(borehole_cols, "ubhi")
        b_uwi = _direct_pick(borehole_cols, "uwi")
        b_name_expr = _direct_name_expr("b", borehole_cols, "borehole_name", "wellbore_name", "name")
        if w_uwi and w_name_expr:
            q_uwi = quote_ident(w_uwi)
            direct_wells = pd.read_sql_query(
                text(f"SELECT BTRIM(w.{q_uwi}::text) AS uwi, {w_name_expr} AS well_name FROM epdb_well w WHERE w.{q_uwi} IS NOT NULL"),
                con=db_engine,
            )
            direct_well_by_uwi = make_lookup(direct_wells, "uwi", "well_name")
        if b_ubhi:
            select_parts = [f"BTRIM(b.{quote_ident(b_ubhi)}::text) AS ubhi"]
            if b_uwi:
                select_parts.append(f"NULLIF(BTRIM(b.{quote_ident(b_uwi)}::text), '') AS uwi")
            if b_name_expr:
                select_parts.append(f"{b_name_expr} AS borehole_name")
            direct_bhs = pd.read_sql_query(
                text(f"SELECT {', '.join(select_parts)} FROM epdb_borehole b WHERE b.{quote_ident(b_ubhi)} IS NOT NULL"),
                con=db_engine,
            )
            direct_uwi_by_ubhi = make_lookup(direct_bhs, "ubhi", "uwi") if "uwi" in direct_bhs.columns else {}
            direct_borehole_by_ubhi = make_lookup(direct_bhs, "ubhi", "borehole_name") if "borehole_name" in direct_bhs.columns else {}
    except Exception:
        st.warning("Chưa thể liên kết tên giếng và thân giếng từ danh mục EPDB. Vui lòng kiểm tra quan hệ danh mục.")

    alerts = alerts.copy() if isinstance(alerts, pd.DataFrame) else pd.DataFrame()
    well_col = find_col(alerts, ["well_name"])
    borehole_col = find_col(alerts, ["borehole_name"])
    uwi_col = find_col(alerts, ["uwi"])
    ubhi_col = find_col(alerts, ["ubhi"])
    md_col = find_col(alerts, ["md_m", "md", "measured_depth"])
    md_end_col = find_col(alerts, ["md_end_m", "md_end"])
    time_col = find_col(alerts, ["alert_time", "detected_at", "created_at"])
    level_col = find_col(alerts, ["prediction_label", "alert_level", "severity", "status"])
    evidence_col = find_col(alerts, ["feature_name", "evidence"])
    type_col = find_col(alerts, ["anomaly_type", "alert_type"])
    detail_col = find_col(alerts, ["description", "details", "reason"])

    def resolve_well(row):
        raw_well = clean_value(row.get(well_col)) if well_col else ""
        uwi = clean_value(row.get(uwi_col)) if uwi_col else ""
        ubhi = clean_value(row.get(ubhi_col)) if ubhi_col else ""
        if not uwi and ubhi:
            uwi = direct_uwi_by_ubhi.get(ubhi.casefold(), "")
        mapped = (direct_well_by_uwi.get(uwi.casefold())
                  or well_by_uwi.get(uwi.casefold())
                  or well_by_ubhi.get(ubhi.casefold()))
        # Catalog labels are authoritative even when their text is identical to UWI/UBHI.
        if mapped:
            return mapped
        if raw_well:
            return raw_well
        return "Chưa khai báo tên giếng trong danh mục"

    def level_label(value):
        return _ai_las_level_label(value)

    if alerts.empty:
        alerts = pd.DataFrame(columns=["ubhi", "uwi", "well_name", "md_m", "md_end_m", "prediction_label"])
        ubhi_col, uwi_col, well_col = "ubhi", "uwi", "well_name"
        md_col, md_end_col, time_col = "md_m", "md_end_m", None
        level_col, evidence_col, type_col, detail_col = "prediction_label", None, None, None

    alerts["_well"] = alerts.apply(resolve_well, axis=1) if not alerts.empty else pd.Series(dtype=str)
    alerts["_well_key"] = (
        alerts[uwi_col].map(clean_value).str.casefold() if uwi_col else pd.Series("", index=alerts.index)
    )
    if ubhi_col:
        ubhi_values = alerts[ubhi_col].map(clean_value).str.casefold()
    else:
        ubhi_values = pd.Series("", index=alerts.index)
    alerts["_borehole_key"] = ubhi_values
    missing_key = alerts["_borehole_key"].eq("")
    alerts.loc[missing_key, "_borehole_key"] = [f"unidentified-{i}" for i in alerts.index[missing_key]]
    missing_well_key = alerts["_well_key"].eq("")
    alerts.loc[missing_well_key, "_well_key"] = alerts.loc[missing_well_key, "_borehole_key"]

    # Use the exact borehole name from epdb_borehole; do not invent ordinal labels.
    borehole_name_map = dict(direct_borehole_by_ubhi)
    if not master.empty and {"ubhi", "borehole_name"}.issubset(master.columns):
        for _, row in master[["ubhi", "borehole_name"]].dropna(subset=["ubhi"]).iterrows():
            key = clean_value(row.get("ubhi")).casefold()
            name = clean_value(row.get("borehole_name"))
            if key and name:
                borehole_name_map.setdefault(key, name)

    def borehole_label(row):
        key = clean_value(row.get("_borehole_key")).casefold()
        name = borehole_name_map.get(key)
        stored_name = clean_value(row.get(borehole_col)) if borehole_col else ""
        if name:
            return name
        if stored_name:
            return stored_name
        return "Chưa khai báo tên thân giếng trong danh mục"

    alerts["_borehole"] = alerts.apply(borehole_label, axis=1) if not alerts.empty else pd.Series(dtype=str)
    # Disambiguate identical display names belonging to different boreholes.
    if not alerts.empty:
        duplicate_names = alerts.groupby(["_well_key", "_borehole"], dropna=False)["_borehole_key"].nunique()
        duplicate_names = duplicate_names[duplicate_names > 1].index
        for well_key, name in duplicate_names:
            mask = alerts["_well_key"].eq(well_key) & alerts["_borehole"].eq(name)
            for suffix, borehole_key in enumerate(sorted(alerts.loc[mask, "_borehole_key"].unique()), start=1):
                alerts.loc[mask & alerts["_borehole_key"].eq(borehole_key), "_borehole"] = f"{name} ({suffix})"

    alerts["_level"] = alerts[level_col].map(level_label) if level_col else "Chưa phân loại"
    alerts["_md_start"] = pd.to_numeric(alerts[md_col], errors="coerce") if md_col else np.nan
    alerts["_md_end"] = pd.to_numeric(alerts[md_end_col], errors="coerce") if md_end_col else alerts["_md_start"]
    alerts["_md_width"] = (alerts["_md_end"] - alerts["_md_start"]).clip(lower=0).fillna(0)
    alerts["_issue"] = alerts.apply(
        lambda row: _ai_las_signal_group(
            row.get(evidence_col) if evidence_col else "",
            row.get(detail_col) if detail_col else "",
            row.get(type_col) if type_col else "",
        ), axis=1,
    ) if not alerts.empty else pd.Series(dtype=str)
    # Never call a very broad flagged zone a "local spike". The width label
    # describes the extent of the candidate zone, not a confirmed bad-data span.
    if not alerts.empty:
        alerts.loc[alerts["_md_width"] >= 50.0, "_issue"] = "Vùng tín hiệu cần rà soát kéo dài"
        mid_width = alerts["_md_width"].ge(10.0) & alerts["_md_width"].lt(50.0)
        alerts.loc[mid_width, "_issue"] = "Đoạn tín hiệu cần rà soát"
    alerts["_curves"] = alerts.apply(
        lambda row: _ai_las_curve_names(
            row.get(evidence_col) if evidence_col else "",
            row.get(detail_col) if detail_col else "",
        ), axis=1,
    ) if not alerts.empty else pd.Series(dtype=str)
    alerts["_time"] = pd.to_datetime(alerts[time_col], errors="coerce") if time_col else pd.NaT
    alert_rows = alerts[alerts["_level"].isin(["Cần kiểm tra", "Ưu tiên kiểm tra"])].copy()

    # Filtering is applied before KPI/chart calculation so every figure follows
    # the selected well and borehole scope.
    well_options = ["Tất cả giếng"] + sorted(alert_rows["_well"].dropna().astype(str).unique().tolist())
    filter_cols = st.columns([1.0, 1.0, 2.0])
    with filter_cols[0]:
        selected_alert_well = st.selectbox("Giếng", well_options, key="ai_alert_well_filter")
    scoped = alert_rows.copy()
    if selected_alert_well != "Tất cả giếng":
        scoped = scoped[scoped["_well"] == selected_alert_well].copy()
    borehole_options = ["Tất cả thân giếng"] + sorted(scoped["_borehole"].dropna().astype(str).unique().tolist())
    with filter_cols[1]:
        selected_alert_borehole = st.selectbox("Thân giếng", borehole_options, key="ai_alert_borehole_filter")
    if selected_alert_borehole != "Tất cả thân giếng":
        scoped = scoped[scoped["_borehole"] == selected_alert_borehole].copy()

    signal_event_count = len(scoped)
    display_zones = _ai_las_merge_display_zones(scoped)
    zone_count = len(display_zones)
    affected_wells = int(scoped["_well_key"].nunique()) if not scoped.empty else 0
    affected_boreholes = int(scoped["_borehole_key"].nunique()) if not scoped.empty else 0

    # Compare boreholes by MD-weighted flagged coverage, not by raw interval count.
    run_summary = (run_meta or {}).get("summary") or {}
    coverage_records = run_summary.get("borehole_coverage") or []
    coverage_view = pd.DataFrame(coverage_records)
    if not coverage_view.empty and "ubhi" in coverage_view.columns:
        coverage_view = coverage_view.copy()
        coverage_view["_ubhi_key"] = coverage_view["ubhi"].map(clean_value).str.casefold()
        coverage_view["_well"] = coverage_view["_ubhi_key"].map(
            lambda key: direct_well_by_uwi.get(direct_uwi_by_ubhi.get(key, "").casefold(), "")
                        or well_by_ubhi.get(key, "")
        )
        coverage_view["_borehole"] = coverage_view["_ubhi_key"].map(
            lambda key: direct_borehole_by_ubhi.get(key, "") or borehole_by_ubhi.get(key, "")
        )
        coverage_view["_well"] = coverage_view["_well"].replace("", "Chưa khai báo tên giếng trong danh mục")
        coverage_view["_borehole"] = coverage_view["_borehole"].replace("", "Chưa khai báo tên thân giếng trong danh mục")
        for col in ("scored_depth_m", "flagged_depth_m", "flagged_depth_pct", "interval_count"):
            if col in coverage_view.columns:
                coverage_view[col] = pd.to_numeric(coverage_view[col], errors="coerce").fillna(0)
        if selected_alert_well != "Tất cả giếng":
            coverage_view = coverage_view[coverage_view["_well"].eq(selected_alert_well)].copy()
        if selected_alert_borehole != "Tất cả thân giếng":
            coverage_view = coverage_view[coverage_view["_borehole"].eq(selected_alert_borehole)].copy()
        total_flagged_md = float(coverage_view.get("flagged_depth_m", pd.Series(dtype=float)).sum())
        total_scored_md = float(coverage_view.get("scored_depth_m", pd.Series(dtype=float)).sum())
        coverage_valid = total_scored_md > 0 and (signal_event_count == 0 or total_flagged_md > 0)
        affected_md_pct = (100.0 * total_flagged_md / total_scored_md) if coverage_valid else float("nan")
        if not coverage_valid:
            total_flagged_md = float("nan")
        coverage_by_ubhi = coverage_view.set_index("_ubhi_key").to_dict(orient="index") if not coverage_view.empty else {}
        alerts["_scored_depth_m"] = alerts["_borehole_key"].map(lambda key: float(coverage_by_ubhi.get(key, {}).get("scored_depth_m") or 0.0))
        alerts["_md_share_pct"] = np.where(alerts["_scored_depth_m"] > 0, alerts["_md_width"] / alerts["_scored_depth_m"] * 100.0, np.nan)
        scoped = alerts.loc[scoped.index].copy()
    else:
        total_flagged_md = float("nan")
        total_scored_md = 0.0
        affected_md_pct = float("nan")
        coverage_valid = False

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        render_kpi_card("Vùng MD cần xem xét", f"{zone_count:,}", f"Đã gộp vùng chồng lấn từ {signal_event_count:,} tín hiệu", status="warning" if zone_count else "success", icon="🔔")
    with k2:
        render_kpi_card("Chiều dài bị đánh dấu", f"{total_flagged_md:,.1f} m" if coverage_valid else "—", "Tính một lần cho mỗi thân giếng", status="navy", icon="📏")
    with k3:
        render_kpi_card("Tỷ lệ chiều sâu bị đánh dấu", f"{affected_md_pct:,.2f}%" if np.isfinite(affected_md_pct) else "—", "So với chiều sâu có thể phân tích", status="navy", icon="📊")
    with k4:
        render_kpi_card("Thân giếng ảnh hưởng", f"{affected_boreholes:,}", "Mỗi thân giếng được thống kê riêng", status="navy", icon="🛢️")
    with k5:
        render_kpi_card("Giếng ảnh hưởng", f"{affected_wells:,}", "Số giếng có ít nhất một đoạn được đánh dấu", status="navy", icon="📍")

    completed_at = pd.to_datetime(run_meta.get("completed_at"), errors="coerce")
    if pd.notna(completed_at):
        st.caption(f"Lần phân tích gần nhất: {completed_at.strftime('%d/%m/%Y %H:%M:%S')}")
    st.caption(f"Mỗi hàng trong bảng là một vùng MD đã gộp. Có {signal_event_count:,} sự kiện theo đường cong/quan hệ; các sự kiện chồng lấn được hiển thị chung để tránh đếm lặp vùng độ sâu. AI chỉ đánh dấu tín hiệu cần rà soát, chưa xác nhận lỗi dữ liệu.")
    if coverage_valid and np.isfinite(affected_md_pct) and affected_md_pct >= 95.0:
        st.warning("Tỷ lệ chiều sâu được đánh dấu đang rất cao. Điều này cho thấy mô hình đánh dấu gần như toàn bộ phạm vi có thể phân tích, không chứng minh dữ liệu LAS bị lỗi. Tạm thời không dùng tỷ lệ này để kết luận chất lượng dữ liệu; cần kiểm tra phân bố và ngưỡng của từng đường cong trước khi đánh giá.")

    # Present curve availability in plain language. Database column names,
    # internal unit-source labels and UBHI/UWI identifiers are intentionally hidden.
    try:
        audit_view = load_ai_las_curve_audit_cached(str(run_meta.get("run_id")))
    except Exception:
        audit_view = pd.DataFrame()
    if not audit_view.empty:
        curve_display = {"gr": "GR", "cali": "CALI", "nphi": "NPHI", "rhob": "RHOB", "dt": "DT", "sp": "SP", "lld": "LLD", "lls": "LLS", "msfl": "MSFL"}
        audit_view = audit_view.copy()
        audit_view["_ubhi_key"] = audit_view.get("ubhi", pd.Series("", index=audit_view.index)).map(clean_value).str.casefold()
        uwi_by_ubhi = make_lookup(master, "ubhi", "uwi")
        def resolve_audit_well(key):
            uwi = direct_uwi_by_ubhi.get(key, "") or uwi_by_ubhi.get(key, "")
            name = direct_well_by_uwi.get(uwi.casefold(), "") if uwi else ""
            if not name:
                name = well_by_ubhi.get(key, "")
            if not name and uwi:
                name = well_by_uwi.get(uwi.casefold(), "")
            return name if name else "Chưa khai báo tên giếng trong danh mục"
        audit_view["_well"] = audit_view["_ubhi_key"].map(resolve_audit_well)
        audit_view["_borehole"] = audit_view["_ubhi_key"].map(
            lambda key: borehole_name_map.get(key, "Chưa khai báo tên thân giếng trong danh mục")
        )
        audit_records = []
        for (well_name, borehole_name), group in audit_view.groupby(["_well", "_borehole"], dropna=False, sort=False):
            ready = set()
            for _, item in group.iterrows():
                curve = curve_display.get(clean_value(item.get("curve")).casefold(), clean_value(item.get("curve")).upper())
                status = clean_value(item.get("status")).upper()
                valid_samples = pd.to_numeric(item.get("valid_samples"), errors="coerce")
                is_ready = status in {"OK", "UNIT_ASSUMED_FROM_COLUMN"} and pd.notna(valid_samples) and valid_samples > 0
                if is_ready and curve:
                    ready.add(curve)
            total_curve_types = len(set(curve_display.values()))
            audit_records.append({
                "Giếng": well_name,
                "Thân giếng": borehole_name,
                "Đường cong có thể phân tích": f"{len(ready)}/{total_curve_types} loại",
                "Tình trạng": "Đầy đủ" if len(ready) == total_curve_types else ("Có thể phân tích một phần" if ready else "Chưa đủ dữ liệu"),
            })
        with st.expander("Dữ liệu đường cong", expanded=False):
            render_interactive_table(pd.DataFrame(audit_records), height=300, highlight_first_column=True)

    if scoped.empty:
        st.info("Không có khoảng dữ liệu cần kiểm tra trong phạm vi đang chọn.")
        return

    # Build concise signal categories for charts.
    ai_chart_left, ai_chart_right = st.columns(2, gap="medium")
    with ai_chart_left:
        st.markdown("<div class='overview-panel-title'>Các dấu hiệu thường gặp</div>", unsafe_allow_html=True)
        issue_lengths = display_zones.groupby("_issue")["_md_width"].sum().sort_values(ascending=True).tail(8) if not display_zones.empty else pd.Series(dtype=float)
        fig_types = go.Figure(go.Bar(
            x=issue_lengths.values, y=issue_lengths.index, orientation="h",
            marker=dict(color="#3977A8", line=dict(color="#FFFFFF", width=0.7)),
            text=np.round(issue_lengths.values, 1), textposition="outside", textfont=dict(size=10, color="#26384A"), cliponaxis=False,
            hovertemplate="<b>%{y}</b><br>Tổng chiều dài MD: %{x:,.1f} m<extra></extra>",
        ))
        fig_types.update_layout(
            height=300, margin=dict(l=12, r=18, t=12, b=42),
            paper_bgcolor="#FFFFFF", plot_bgcolor="#F8FAFC",
            font=dict(family="Arial, sans-serif", size=11, color="#26384A"),
            xaxis=dict(title="<b>Chiều dài độ sâu đo được đánh dấu (m)</b>", gridcolor="#E3EAF2", tickfont=dict(size=10, color="#40546A"), rangemode="tozero"),
            yaxis=dict(title="", tickfont=dict(size=10, color="#40546A"), showgrid=False), showlegend=False,
        )
        st.plotly_chart(fig_types, use_container_width=True, config={"staticPlot": True, "displayModeBar": False, "responsive": False}, key="ai_alert_type_distribution_chart")

    with ai_chart_right:
        st.markdown("<div class='overview-panel-title'>Chiều dài vùng theo mức độ</div>", unsafe_allow_html=True)
        severity_lengths = display_zones.groupby("_level")["_md_width"].sum().reindex(["Ưu tiên kiểm tra", "Cần kiểm tra"], fill_value=0) if not display_zones.empty else pd.Series(dtype=float)
        severity_lengths = severity_lengths[severity_lengths > 0]
        severity_colors = {"Ưu tiên kiểm tra": "#C53030", "Cần kiểm tra": "#D97706"}
        fig_severity = go.Figure(go.Pie(
            labels=severity_lengths.index, values=severity_lengths.values, hole=0.58,
            marker=dict(colors=[severity_colors.get(label, "#64748B") for label in severity_lengths.index], line=dict(color="#FFFFFF", width=2)),
            textinfo="label+value", textposition="outside", textfont=dict(size=10, color="#26384A"),
            hovertemplate="<b>%{label}</b><br>Chiều dài MD: %{value:,.1f} m<extra></extra>",
        ))
        fig_severity.update_layout(height=300, margin=dict(l=18, r=18, t=10, b=20), paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF", font=dict(family="Arial, sans-serif", size=11, color="#26384A"), showlegend=False)
        st.plotly_chart(fig_severity, use_container_width=True, config={"staticPlot": True, "displayModeBar": False, "responsive": False}, key="ai_alert_class_donut")

    # Rank separate boreholes by the percentage of scorable MD marked by AI.
    st.markdown("<div class='overview-panel-title'>Thân giếng có tỷ lệ MD cần xem xét cao</div>", unsafe_allow_html=True)
    borehole_counts = coverage_view.copy() if not coverage_view.empty and coverage_valid else pd.DataFrame()
    if not borehole_counts.empty:
        borehole_counts = borehole_counts[
            pd.to_numeric(borehole_counts.get("scored_depth_m"), errors="coerce").gt(0)
            & pd.to_numeric(borehole_counts.get("flagged_depth_pct"), errors="coerce").notna()
        ].copy()
        borehole_counts["Nhãn"] = borehole_counts["_well"].astype(str) + " — " + borehole_counts["_borehole"].astype(str)
        borehole_counts = borehole_counts.sort_values(
            ["flagged_depth_pct", "flagged_depth_m"], ascending=[False, False], kind="mergesort"
        ).head(10).sort_values("flagged_depth_pct", ascending=True)
        custom = np.column_stack([
            borehole_counts["flagged_depth_m"].to_numpy(float),
            borehole_counts["scored_depth_m"].to_numpy(float),
            borehole_counts["interval_count"].to_numpy(float),
        ])
        fig_boreholes = go.Figure(go.Bar(
            x=borehole_counts["flagged_depth_pct"], y=borehole_counts["Nhãn"], orientation="h",
            marker=dict(color="#3977A8", line=dict(color="#FFFFFF", width=0.7)),
            text=np.round(borehole_counts["flagged_depth_pct"], 1).astype(str) + "%",
            textposition="outside", textfont=dict(size=10, color="#26384A"), cliponaxis=False,
            customdata=custom,
            hovertemplate=("<b>%{y}</b><br>Tỷ lệ chiều sâu được đánh dấu: %{x:.2f}%"
                           "<br>Chiều sâu được đánh dấu: %{customdata[0]:,.1f} m"
                           "<br>Chiều sâu đủ điều kiện: %{customdata[1]:,.1f} m"
                           "<br>Số đoạn: %{customdata[2]:,.0f}<extra></extra>"),
        ))
        fig_boreholes.update_layout(
            height=max(260, min(420, 34 * len(borehole_counts) + 80)), margin=dict(l=12, r=18, t=10, b=42),
            paper_bgcolor="#FFFFFF", plot_bgcolor="#F8FAFC", font=dict(family="Arial, sans-serif", size=11, color="#26384A"),
            xaxis=dict(title="<b>Tỷ lệ chiều sâu được đánh dấu (%)</b>", gridcolor="#E3EAF2", tickfont=dict(size=10, color="#40546A"), rangemode="tozero"),
            yaxis=dict(title="", tickfont=dict(size=10, color="#40546A"), showgrid=False), showlegend=False,
        )
        st.plotly_chart(fig_boreholes, use_container_width=True, config={"staticPlot": True, "displayModeBar": False, "responsive": False}, key="ai_alert_top_boreholes_chart")
    else:
        st.info("Chưa đủ thông tin độ sâu để so sánh tỷ lệ giữa các thân giếng. Các số liệu chiều dài và tỷ lệ được để trống để tránh hiển thị sai.")

    # User-facing table only: no UWI, UBHI, database columns, raw reason codes or scores.
    zone_source = display_zones.copy()
    severity_order = zone_source["_level"].map({"Ưu tiên kiểm tra": 0, "Cần kiểm tra": 1}).fillna(2)
    zone_source = zone_source.assign(_severity_order=severity_order).sort_values(
        ["_severity_order", "_time", "_md_width"], ascending=[True, False, False], na_position="last"
    ).drop(columns="_severity_order")
    display = pd.DataFrame(index=zone_source.index)
    display["Giếng"] = zone_source["_well"]
    display["Thân giếng"] = zone_source["_borehole"]
    display["Khoảng độ sâu đo (m)"] = zone_source.apply(
        lambda row: f"{row['_md_start']:,.2f} – {row['_md_end']:,.2f}" if pd.notna(row["_md_start"]) and pd.notna(row["_md_end"]) else "—",
        axis=1,
    )
    display["Độ dài vùng (m)"] = zone_source["_md_width"].round(2).where(zone_source["_md_width"] > 0.001, np.nan)
    display["Số tín hiệu gộp"] = zone_source["_signal_event_count"].astype(int)
    if "_md_share_pct" in zone_source.columns:
        display["Tỷ lệ chiều sâu thân giếng (%)"] = zone_source["_md_share_pct"].round(2)
    display["Mức độ"] = zone_source["_level"]
    display["Dấu hiệu"] = zone_source["_issue"]
    display["Đường cong liên quan"] = zone_source["_curves"]
    if zone_source["_time"].notna().any():
        display["Thời điểm phân tích"] = zone_source["_time"].dt.strftime("%d/%m/%Y %H:%M:%S").fillna("—")

    ai_run_scope = str((run_meta or {}).get("run_id") or "latest")
    ai_filter_scope = f"{ai_run_scope}|{selected_alert_well}|{selected_alert_borehole}"
    ai_scope_state_key = "ai_alert_table_scope"
    ai_visible_state_key = "ai_alert_visible_rows"
    if st.session_state.get(ai_scope_state_key) != ai_filter_scope:
        st.session_state[ai_scope_state_key] = ai_filter_scope
        st.session_state[ai_visible_state_key] = 50
    visible_count = min(int(st.session_state.get(ai_visible_state_key, 50)), len(display))
    display_page = display.iloc[:visible_count].copy()
    st.markdown(f"<div class='overview-panel-title'>Các vùng độ sâu cần xem xét · {len(display):,} vùng</div>", unsafe_allow_html=True)
    render_interactive_table(display_page, height=480, highlight_first_column=True)
    if visible_count < len(display):
        st.caption(f"Đang hiển thị {visible_count:,}/{len(display):,} vùng độ sâu.")
        st.button(
            "Hiển thị thêm 50 khoảng", key=f"ai_alert_show_more_{hashlib.sha1(ai_filter_scope.encode('utf-8')).hexdigest()[:10]}",
            on_click=_show_more_ai_alert_rows, args=(ai_visible_state_key, len(display), 50),
        )
    else:
        st.caption(f"Đã hiển thị {len(display):,} vùng độ sâu trong phạm vi đang chọn.")

    csv_data = display.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        f"Tải danh sách vùng cần kiểm tra · {len(display):,} dòng (.csv)",
        data=csv_data, file_name=f"EPDB_LAS_AI_alerts_{ai_run_scope}.csv",
        mime="text/csv", key="download_ai_alerts_csv",
    )

# ---------------------------------------------------------
# 4.4 PRESSURE AI — WHP ANOMALY DETECTION
# ---------------------------------------------------------
_PRESSURE_AI_FEATURE_COLUMNS = [
    "delta_psi",
    "abs_delta_psi",
    "relative_delta_pct",
    "residual_prev_median_psi",
    "robust_z_prev",
    "past_mad_5_psi",
    "rolling_std_4_psi",
    "rolling_range_4_psi",
    "rolling_unique_4",
    "same_value_run",
    "delta_acceleration_psi",
    "days_since_previous",
]


@st.cache_resource(show_spinner=False)
def _load_pressure_ai_model_cached(model_path: str, model_mtime_ns: int):
    """Load the trained WHP model once per model-file version."""
    import joblib

    artifact = joblib.load(model_path)
    if not isinstance(artifact, dict) or "pipeline" not in artifact or "metadata" not in artifact:
        raise ValueError("File .joblib không đúng định dạng mô hình EPDB Pressure AI.")
    metadata = artifact["metadata"]
    if metadata.get("pressure_channel") != "WHP":
        raise ValueError("Mô hình này không được huấn luyện cho kênh WHP.")
    if list(metadata.get("features") or []) != _PRESSURE_AI_FEATURE_COLUMNS:
        raise ValueError("Danh sách đặc trưng trong model không khớp với app.py.")
    if "validation" not in metadata or "threshold" not in metadata["validation"]:
        raise ValueError("Model thiếu ngưỡng phân loại trong metadata.")
    return artifact


@st.cache_data(ttl=180, show_spinner=False)
def _load_pressure_ai_source_cached() -> pd.DataFrame:
    """Read WHP from the current Cuu Long schema; read-only, no DDL or writes."""
    sql = """
        SELECT
            p.production_id::text AS record_id,
            BTRIM(b.wellbore_code::text) AS ubhi,
            COALESCE(
                NULLIF(BTRIM(w.well_name::text), ''),
                NULLIF(BTRIM(w.well_code::text), ''),
                BTRIM(b.wellbore_code::text)
            ) AS well_name,
            BTRIM(b.wellbore_code::text) AS borehole_name,
            p.production_month::text AS pressure_date,
            p.whp_psi::double precision AS pressure_value
        FROM public.epdb_production p
        JOIN public.epdb_borehole b
            ON b.wellbore_id = p.wellbore_id
        LEFT JOIN public.epdb_well w
            ON w.well_id = b.well_id
        WHERE b.wellbore_code IS NOT NULL
          AND p.production_month IS NOT NULL
          AND p.whp_psi IS NOT NULL
          AND p.whp_psi > 0
        ORDER BY b.wellbore_code, p.production_month, p.production_id
    """
    return read_df(sql)


def _pressure_ai_same_value_run(values: np.ndarray, dates: pd.Series) -> np.ndarray:
    """Count consecutive repeated WHP values within adjacent monthly periods."""
    result = np.zeros(len(values), dtype=float)
    run = 0
    for i, value in enumerate(values):
        if i == 0 or not np.isfinite(value):
            run = 1 if np.isfinite(value) else 0
        else:
            gap = (dates.iloc[i] - dates.iloc[i - 1]).days
            previous = values[i - 1]
            if (
                np.isfinite(previous)
                and abs(float(value) - float(previous)) <= 1e-6
                and 0 < gap <= 62
            ):
                run += 1
            else:
                run = 1
        result[i] = run
    return result


def _build_pressure_ai_features(group: pd.DataFrame) -> pd.DataFrame:
    """Reproduce the exact causal features used when training the .joblib model."""
    g = group.copy()
    g["pressure_date"] = pd.to_datetime(g["pressure_date"], errors="coerce")
    g["pressure_value"] = pd.to_numeric(g["pressure_value"], errors="coerce")
    g = g.dropna(subset=["pressure_date", "pressure_value"]).sort_values(
        "pressure_date", kind="mergesort"
    )
    p = g["pressure_value"].astype(float)
    delta = p.diff()
    previous = p.shift(1)
    history = p.shift(1)

    prior_median = history.rolling(window=5, min_periods=2).median()
    prior_mad = history.rolling(window=5, min_periods=2).apply(
        lambda x: float(np.median(np.abs(x - np.median(x))), raw=True
    )
    residual = p - prior_median
    robust_scale = (1.4826 * prior_mad).clip(lower=25.0)

    rolling = p.rolling(window=4, min_periods=2)
    rolling_std = rolling.std(ddof=0)
    rolling_range = rolling.max() - rolling.min()
    rolling_unique = rolling.apply(
        lambda x: float(pd.Series(x).round(5).nunique()), raw=True
    )
    dates = g["pressure_date"].reset_index(drop=True)
    values = p.to_numpy(dtype=float)

    features = pd.DataFrame(index=g.index)
    features["delta_psi"] = delta
    features["abs_delta_psi"] = delta.abs()
    features["relative_delta_pct"] = (
        delta / previous.abs().clip(lower=25.0)
    ) * 100.0
    features["residual_prev_median_psi"] = residual
    features["robust_z_prev"] = residual / robust_scale
    features["past_mad_5_psi"] = prior_mad
    features["rolling_std_4_psi"] = rolling_std
    features["rolling_range_4_psi"] = rolling_range
    features["rolling_unique_4"] = rolling_unique
    features["same_value_run"] = _pressure_ai_same_value_run(values, dates)
    features["delta_acceleration_psi"] = delta.diff()
    features["days_since_previous"] = (
        dates.diff().dt.total_seconds() / 86400.0
    )
    return features[_PRESSURE_AI_FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan)


def _score_pressure_ai_dataframe(
    source_df: pd.DataFrame,
    model_artifact: dict[str, Any],
) -> pd.DataFrame:
    """Score each WHP series independently by borehole; do not mix wells."""
    data = source_df.copy()
    required = {"ubhi", "pressure_date", "pressure_value"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Thiếu trường dữ liệu WHP: {sorted(missing)}")

    data["ubhi"] = data["ubhi"].astype(str).str.strip()
    data["pressure_date"] = pd.to_datetime(data["pressure_date"], errors="coerce")
    data["pressure_value"] = pd.to_numeric(data["pressure_value"], errors="coerce")
    data = data.dropna(subset=["pressure_date", "pressure_value"])
    data = data[data["ubhi"].ne("") & data["pressure_value"].gt(0)].copy()
    if "record_id" not in data.columns:
        data["record_id"] = data.index.astype(str)

    metadata = model_artifact["metadata"]
    threshold = float(metadata["validation"]["threshold"])
    outputs = []

    for ubhi, group in data.groupby("ubhi", sort=False):
        group = group.sort_values(
            ["pressure_date", "record_id"], kind="mergesort"
        ).reset_index(drop=True)
        features = _build_pressure_ai_features(group)
        group = group.loc[features.index].copy().reset_index(drop=True)
        features = features.reset_index(drop=True)
        if group.empty:
            continue

        probabilities = model_artifact["pipeline"].predict_proba(
            features[_PRESSURE_AI_FEATURE_COLUMNS]
        )[:, 1]
        group["anomaly_score"] = probabilities * 100.0
        group["same_value_run"] = features["same_value_run"].to_numpy()
        group["abs_delta_psi"] = features["abs_delta_psi"].to_numpy()
        group["robust_z_prev"] = features["robust_z_prev"].to_numpy()

        flatline = group["same_value_run"].ge(4)
        model_flag = probabilities >= threshold
        group["is_anomaly"] = flatline.to_numpy() | model_flag
        group["alert_level"] = np.where(group["is_anomaly"], "WARNING", "NORMAL")

        anomaly_types, reasons = [], []
        for i, (_, row) in enumerate(group.iterrows()):
            if bool(flatline.iloc[i]):
                anomaly_types.append("PRESSURE_FLATLINE")
                reasons.append(
                    f"WHP lặp lại cùng một giá trị trong {int(row['same_value_run'])} kỳ liên tiếp; "
                    "cần kiểm tra dữ liệu đo/ghi nhận."
                )
            elif bool(model_flag[i]):
                if pd.notna(row["robust_z_prev"]) and abs(float(row["robust_z_prev"])) >= 3:
                    anomaly_types.append("LOCAL_PRESSURE_DEVIATION")
                    reasons.append(
                        "WHP lệch mạnh so với nền áp suất gần nhất của cùng thân giếng."
                    )
                elif pd.notna(row["abs_delta_psi"]) and float(row["abs_delta_psi"]) >= 300:
                    anomaly_types.append("SUDDEN_PRESSURE_CHANGE")
                    reasons.append(
                        "WHP thay đổi đột ngột so với kỳ trước; cần đối chiếu điều kiện khai thác."
                    )
                else:
                    anomaly_types.append("ML_PATTERN_ANOMALY")
                    reasons.append(
                        "Mô hình nhận diện mẫu biến động WHP khác với tập nền huấn luyện."
                    )
            else:
                anomaly_types.append("NORMAL")
                reasons.append("Chưa phát hiện mẫu bất thường theo mô hình hiện tại.")

        group["anomaly_type"] = anomaly_types
        group["reason"] = reasons
        group["model_version"] = metadata.get("model_version", "unknown")
        outputs.append(group)

    if not outputs:
        return pd.DataFrame()
    return pd.concat(outputs, ignore_index=True).sort_values(
        ["ubhi", "pressure_date", "record_id"], kind="mergesort"
    ).reset_index(drop=True)


def render_pressure_ai_dashboard() -> None:
    """Read current WHP, score it with the saved model and render review candidates."""
    st.markdown(
        '<div class="overview-panel-title">CẢNH BÁO AI PHÁT HIỆN BẤT THƯỜNG ÁP SUẤT ĐẦU GIẾNG (WHP)</div>',
        unsafe_allow_html=True,
    )
    model_path = BASE_DIR / "epdb_pressure_whp_model.joblib"
    if not model_path.is_file():
        st.error("Chưa tìm thấy file epdb_pressure_whp_model.joblib.")
        st.caption(
            "Đặt file .joblib cùng thư mục với app.py. Nếu dashboard chạy trên máy chủ, "
            "file phải có mặt trong thư mục triển khai trên máy chủ đó."
        )
        return

    try:
        artifact = _load_pressure_ai_model_cached(
            str(model_path), int(model_path.stat().st_mtime_ns)
        )
    except Exception as exc:
        st.error(
            f"Không nạp được mô hình Pressure AI: {type(exc).__name__}: {exc}"
        )
        st.caption(
            "Môi trường chạy cần có joblib và scikit-learn tương thích với model đã huấn luyện."
        )
        return

    metadata = artifact["metadata"]
    refresh_col, info_col = st.columns([0.30, 0.70])
    with refresh_col:
        if st.button(
            "Làm mới dữ liệu WHP",
            key="refresh_pressure_ai_data",
            use_container_width=True,
        ):
            _load_pressure_ai_source_cached.clear()
    with info_col:
        st.caption(
            f"Model: {metadata.get('model_version', 'unknown')} · "
            f"Ngưỡng cảnh báo: {float(metadata['validation']['threshold']):.2f} · "
            "Kênh áp suất: WHP (psi)"
        )

    try:
        with st.spinner("Đang đọc dữ liệu WHP và chạy mô hình..."):
            source = _load_pressure_ai_source_cached()
            if source.empty:
                st.info("CSDL hiện chưa có bản ghi WHP hợp lệ để phân tích.")
                return
            results = _score_pressure_ai_dataframe(source, artifact)
    except Exception as exc:
        st.error(
            f"Không thể phân tích dữ liệu WHP: {type(exc).__name__}: {exc}"
        )
        st.caption(
            "Ứng dụng đang dùng schema Cửu Long: epdb_production.production_month, "
            "epdb_production.whp_psi và epdb_borehole.wellbore_code."
        )
        return

    if results.empty:
        st.info("Không có bản ghi WHP đủ điều kiện sau bước chuẩn hóa dữ liệu.")
        return

    alerts = results[results["is_anomaly"]].copy()
    flatline_count = int((alerts["anomaly_type"] == "PRESSURE_FLATLINE").sum())
    metric_cols = st.columns(4)
    metric_cols[0].metric("Bản ghi WHP đã phân tích", f"{len(results):,}")
    metric_cols[1].metric("Thân giếng có WHP", f"{results['ubhi'].nunique():,}")
    metric_cols[2].metric("Bản ghi cần kiểm tra", f"{len(alerts):,}")
    metric_cols[3].metric("Tín hiệu WHP lặp giá trị", f"{flatline_count:,}")

    st.info(
        "Đây là các bản ghi nghi vấn do mô hình sàng lọc, không phải kết luận có sự cố khai thác. "
        "Đặc biệt, WHP lặp giá trị kéo dài có thể phản ánh dữ liệu mặc định hoặc tín hiệu đo bị đóng băng."
    )
    st.caption(
        "Model được huấn luyện từ dữ liệu thực hành Cửu Long và các bất thường mô phỏng. "
        "Điểm ML (%) là điểm đầu ra của bộ phân loại, không phải xác suất xảy ra sự cố ngoài thực địa."
    )

    well_options = sorted(results["ubhi"].dropna().astype(str).unique().tolist())
    well_labels = {}
    for _, item in results[["ubhi", "well_name", "borehole_name"]].drop_duplicates("ubhi").iterrows():
        code = str(item["ubhi"])
        name = str(item.get("well_name") or "").strip()
        well_labels[code] = f"{name} — {code}" if name and name != code else code

    selected_ubhi = st.selectbox(
        "Chọn thân giếng xem diễn biến áp suất",
        options=well_options,
        format_func=lambda value: well_labels.get(value, value),
        key="pressure_ai_selected_ubhi",
    )
    well_results = results[results["ubhi"].astype(str) == str(selected_ubhi)].copy()
    well_alerts = well_results[well_results["is_anomaly"]].copy()

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=well_results["pressure_date"],
            y=well_results["pressure_value"],
            mode="lines+markers",
            name="WHP",
            line=dict(width=2, color="#245A8D"),
            marker=dict(size=6),
            hovertemplate="Ngày: %{x|%Y-%m-%d}<br>WHP: %{y:.1f} psi<extra></extra>",
        )
    )
    if not well_alerts.empty:
        fig.add_trace(
            go.Scatter(
                x=well_alerts["pressure_date"],
                y=well_alerts["pressure_value"],
                mode="markers",
                name="Bản ghi nghi vấn",
                marker=dict(size=12, color="#B42318", symbol="x"),
                customdata=well_alerts[["anomaly_type", "anomaly_score"]],
                hovertemplate=(
                    "Ngày: %{x|%Y-%m-%d}<br>WHP: %{y:.1f} psi"
                    "<br>Loại: %{customdata[0]}<br>Điểm ML: %{customdata[1]:.1f}%<extra></extra>"
                ),
            )
        )
    fig.update_layout(
        height=360,
        margin=dict(l=12, r=12, t=18, b=12),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        xaxis_title="Thời gian",
        yaxis_title="WHP (psi)",
        legend=dict(orientation="h", y=1.12, x=0),
        hovermode="x unified",
    )
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displayModeBar": False, "responsive": True},
        key="pressure_ai_whp_timeline",
    )

    st.markdown(
        f"<div class='overview-panel-title'>BẢN GHI WHP CẦN KIỂM TRA · {len(well_alerts):,}</div>",
        unsafe_allow_html=True,
    )
    if well_alerts.empty:
        st.success("Thân giếng đang chọn không có bản ghi vượt ngưỡng sàng lọc của mô hình.")
    else:
        display = well_alerts[
            [
                "well_name", "borehole_name", "pressure_date", "pressure_value",
                "anomaly_score", "anomaly_type", "reason",
            ]
        ].copy()
        display["pressure_value"] = display["pressure_value"].round(1)
        display["anomaly_score"] = display["anomaly_score"].round(1)
        display = display.rename(columns={
            "well_name": "Giếng",
            "borehole_name": "Thân giếng",
            "pressure_date": "Ngày ghi nhận",
            "pressure_value": "WHP (psi)",
            "anomaly_score": "Điểm ML (%)",
            "anomaly_type": "Dạng nghi vấn",
            "reason": "Giải thích",
        })
        st.dataframe(
            display,
            use_container_width=True,
            hide_index=True,
            height=min(420, 90 + 38 * len(display)),
        )
        csv_data = display.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Tải danh sách bản ghi WHP cần kiểm tra (.csv)",
            data=csv_data,
            file_name=f"EPDB_Pressure_AI_{selected_ubhi}.csv",
            mime="text/csv",
            key="download_pressure_ai_alerts",
        )


if active_dashboard_view == "Cảnh báo AI":
    render_pressure_ai_dashboard()

# ---------------------------------------------------------
# QC DETAILS (SEPARATE FROM PROPOSAL'S 4.1–4.4 VIEWS)
# ---------------------------------------------------------
if active_dashboard_view == "QC chi tiết":
    worker_state = qc_background_worker.get_state()
    control_col, status_col = st.columns([0.24, 0.76])
    with control_col:
        run_global_qc = st.button(
            "Chạy QC toàn hệ thống",
            key="run_global_qc_cycle",
            type="primary",
            use_container_width=True,
        )
    if run_global_qc:
        qc_background_worker.request_run()

    worker_state = qc_background_worker.get_state()
    with status_col:
        if worker_state.get("last_error"):
            st.error(f"QC: {worker_state['last_error']}")
        elif qc_run_meta and not worker_state.get("running") and not worker_state.get("queued"):
            completed_at = pd.to_datetime((qc_run_meta or {}).get("completed_at"), errors="coerce")
            completed_label = completed_at.strftime("%d/%m/%Y %H:%M") if pd.notna(completed_at) else "—"
            st.caption(f"Snapshot hiện hành · Hoàn thành {completed_label}")

    summary_df, details_by_group, check_failures, affected_entities = execute_qc_checks()

    issue_num = pd.to_numeric(summary_df["Bản ghi / lượt vi phạm"], errors="coerce")
    total_issues = int(issue_num.fillna(0).sum())
    groups_with_issues = int((issue_num.fillna(0) > 0).sum())
    not_checked = int((summary_df["Kết quả"] == "Chưa kiểm tra được").sum())
    passed_rules = int((summary_df["Kết quả"] == "Đạt").sum())
    total_rules = len(summary_df)

    q1, q2, q3, q4, q5 = st.columns(5)
    with q1:
        render_kpi_card("Lượt vi phạm (Bản ghi)", f"{total_issues:,}", "Toàn bộ cơ sở dữ liệu", status="danger" if total_issues > 0 else "success", icon="🔥")
    with q2:
        render_kpi_card("Luật phát hiện lỗi", f"{groups_with_issues:,} / {total_rules}", "Quy tắc không đạt chuẩn", status="danger" if groups_with_issues > 0 else "success", icon="⚠️")
    with q3:
        render_kpi_card("Luật đạt chuẩn", f"{passed_rules:,} / {total_rules}", "Quy tắc đạt 100%", status="success", icon="✅")
    with q4:
        render_kpi_card("Đối tượng ảnh hưởng", f"{len(affected_entities):,}", "Giếng, thân giếng, bảng", status="navy", icon="🎯")
    with q5:
        render_kpi_card("Chưa kiểm tra được", f"{not_checked:,}", "Chờ bổ sung bảng/cột", status="warning" if not_checked > 0 else "neutral", icon="⏳")

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
        # =====================================================
    # BỘ LỌC QC CHI TIẾT
    # =====================================================
    f_col1, f_col2 = st.columns(2)

    status_filter = f_col1.selectbox(
        "Lọc Trạng thái",
        ["Tất cả", "Cần xử lý", "Đạt", "Chưa kiểm tra", "Chưa có dữ liệu"],
        key="qc_detail_status_filter",
    )

    all_domains = (
        ["Tất cả"] +
        sorted(
            summary_df["Lĩnh vực"]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )
        if "Lĩnh vực" in summary_df.columns
        else ["Tất cả"]
    )

    domain_filter = f_col2.selectbox(
        "Lọc Lĩnh vực",
        all_domains,
        key="qc_detail_domain_filter",
    )

    # =====================================================
    # CHUẨN BỊ BẢNG HIỂN THỊ
    # =====================================================
    display = summary_df.drop(
        columns=[
            "Mức độ",
            "Lỗi kỹ thuật",
            "Nguồn đánh giá",
            "Chiều DQS",
            "Yêu cầu kiểm tra",
        ],
        errors="ignore",
    ).rename(columns={
        "Nhóm kiểm tra": "Luật QC",
        "Bản ghi / lượt vi phạm": "Lượt vi phạm",
        "Đối tượng liên quan": "Đối tượng ảnh hưởng",
        "Kết quả": "Trạng thái",
    }).copy()

    display["Trạng thái"] = display["Trạng thái"].replace({
        "Có lỗi": "Cần xử lý",
        "Chưa kiểm tra được": "Chưa kiểm tra",
    })

    # =====================================================
    # ÁP DỤNG CÁC BỘ LỌC
    # =====================================================
    filtered_display = display.copy()

    if status_filter != "Tất cả":
        filtered_display = filtered_display[
            filtered_display["Trạng thái"].astype(str) == status_filter
        ]

    if domain_filter != "Tất cả" and "Lĩnh vực" in filtered_display.columns:
        filtered_display = filtered_display[
            filtered_display["Lĩnh vực"].astype(str) == domain_filter
        ]

    render_interactive_table(
        format_integer_columns(filtered_display),
        height=min(
            420,
            max(190, 32 * (min(len(filtered_display), 12) + 1))
        ),
        highlight_first_column=True,
    )

    # =====================================================
    # CHI TIẾT BẢN GHI VI PHẠM
    # =====================================================

    violated = summary_df.loc[
        issue_num.fillna(0) > 0
    ].copy()

    # Luôn hiển thị tiêu đề, không phụ thuộc số lượng vi phạm.
    st.markdown(
        """
        <div style="
            background:#FFFFFF;
            border:1px solid #CBD5E1;
            border-left:4px solid #DC2626;
            border-radius:10px;
            padding:10px 14px;
            margin-top:14px;
            margin-bottom:10px;
        ">
            <div style="
                font-size:0.85rem;
                font-weight:800;
                color:#991B1B;
                text-transform:uppercase;
                letter-spacing:0.04em;
            ">
                🛠️ Chọn quy tắc vi phạm để kiểm tra bản ghi gốc:
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if violated.empty:
        st.info(
            "Hiện chưa có quy tắc nào phát hiện bản ghi vi phạm. "
            "Khu vực tra cứu bản ghi gốc sẽ xuất hiện khi có vi phạm."
        )

    elif "Mã luật" not in violated.columns:
        st.warning("Không tìm thấy cột Mã luật trong kết quả QC.")

    else:
        # Chuẩn hóa mã luật
        violated = violated.copy()
        violated["_rule_id"] = (
            violated["Mã luật"].astype(str).str.strip()
        )

        rule_ids = violated["_rule_id"].drop_duplicates().tolist()

        # Tạo nhãn hiển thị cho dropdown
        rule_label_map = {}

        for _, row in violated.iterrows():
            rule_id_item = str(row["_rule_id"])

            count_value = pd.to_numeric(
                pd.Series([row.get("Bản ghi / lượt vi phạm", 0)]),
                errors="coerce",
            ).fillna(0).iloc[0]

            rule_label_map[rule_id_item] = (
                f"[{rule_id_item}] "
                f"{row.get('Nhóm kiểm tra', '')} "
                f"— {int(count_value):,} vi phạm"
            )

        # Xử lý trạng thái cũ của dropdown sau khi cập nhật code
        rule_widget_key = "qc_detail_rule_pick"

        if st.session_state.get(rule_widget_key) not in rule_ids:
            st.session_state[rule_widget_key] = rule_ids[0]

        selected_rule_id = st.selectbox(
            "Chọn quy tắc QC",
            options=rule_ids,
            format_func=lambda value: rule_label_map.get(
                value, value
            ),
            key=rule_widget_key,
            label_visibility="visible",
        )

        selected_rows = violated[
            violated["_rule_id"] == selected_rule_id
        ]

        if not selected_rows.empty:
            selected_row = selected_rows.iloc[0]

            rule_id = selected_rule_id

            detail = (
                load_qc_rule_detail_cached(str(qc_run_meta.get("run_id")), rule_id)
                if qc_run_meta and qc_run_meta.get("run_id")
                else pd.DataFrame()
            )

            domain_name = str(selected_row.get("Lĩnh vực", ""))
            dqs_dim = str(selected_row.get("Chiều DQS", ""))

            requirement_raw = selected_row.get(
                "Yêu cầu kiểm tra", ""
            )

            requirement = (
                ""
                if pd.isna(requirement_raw)
                else str(requirement_raw).strip()
            )

            st.markdown(
                f"""
                <div style="
                    display:flex;
                    flex-wrap:wrap;
                    gap:10px;
                    background:#FEF2F2;
                    border:1px solid #FECACA;
                    border-radius:8px;
                    padding:8px 12px;
                    margin:8px 0;
                    font-size:0.78rem;
                ">
                    <span><b>Mã luật:</b> <code>{html.escape(rule_id)}</code></span>
                    <span><b>Lĩnh vực:</b> {html.escape(domain_name)}</span>
                    <span><b>Chiều DQS:</b> {html.escape(dqs_dim)}</span>
                    <div style="
                        width:100%;
                        color:#7F1D1D;
                        margin-top:4px;
                    ">
                        <b>Tiêu chuẩn kỹ thuật:</b>
                        {html.escape(requirement)}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Hiển thị các bản ghi gốc vi phạm
            if isinstance(detail, pd.DataFrame) and not detail.empty:
                render_interactive_table(
                    detail,
                    height=min(
                        340,
                        max(120, 32 * (len(detail) + 1)),
                    ),
                    highlight_first_column=True,
                )
            else:
                st.info(
                    f"Luật {rule_id} có kết quả vi phạm, "
                    "nhưng truy vấn chi tiết chưa trả về bản ghi gốc."
                )

    catalog_columns = [c for c in ["Mã luật", "Lĩnh vực", "Nhóm kiểm tra", "Yêu cầu kiểm tra", "Nguồn đánh giá", "Chiều DQS", "Kết quả"] if c in summary_df.columns]
    catalog_df = summary_df[catalog_columns].rename(columns={"Nhóm kiểm tra": "Luật QC", "Kết quả": "Trạng thái"}).copy()
    with st.expander("Danh mục toàn bộ luật QC và tiêu chí áp dụng"):
        render_interactive_table(
            catalog_df,
            height=420,
            highlight_first_column=True,
        )

