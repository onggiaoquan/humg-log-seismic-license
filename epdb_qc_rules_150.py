from __future__ import annotations

"""EPDB QC engine.

Groups 8 (Stratigraphy) and 9 (Biostratigraphy) are retained in the historical
catalogue but excluded from runtime. Cross-Domain criteria are not present in this
runtime catalogue. WH-15 (TD on Well Header) has been removed because TD belongs
to epdb_borehole. The legacy RULES_150 export name is retained for app compatibility;
this file contains 134 catalogue entries and 120 active runtime criteria.
Missing tables/columns are reported as NOT CHECKED, never as PASS.
"""

import os
from pathlib import Path

QC_RULES_VERSION = "epdb_qc_150_cuulong_v1"

import json
import re
from typing import Any, Callable

_RULES_JSON = r'''[{"number":1,"domain":"Well Header QC","criterion":"Well Name tồn tại"},{"number":2,"domain":"Well Header QC","criterion":"Well Name duy nhất"},{"number":3,"domain":"Well Header QC","criterion":"UWI tồn tại"},{"number":4,"domain":"Well Header QC","criterion":"UWI duy nhất"},{"number":5,"domain":"Well Header QC","criterion":"API Number tồn tại"},{"number":6,"domain":"Well Header QC","criterion":"Well Type hợp lệ"},{"number":7,"domain":"Well Header QC","criterion":"Well Status hợp lệ"},{"number":8,"domain":"Well Header QC","criterion":"Operator tồn tại"},{"number":9,"domain":"Well Header QC","criterion":"Field tồn tại"},{"number":10,"domain":"Well Header QC","criterion":"Block tồn tại"},{"number":11,"domain":"Well Header QC","criterion":"Basin tồn tại"},{"number":12,"domain":"Well Header QC","criterion":"Country tồn tại"},{"number":13,"domain":"Well Header QC","criterion":"Spud Date tồn tại"},{"number":14,"domain":"Well Header QC","criterion":"Completion Date hợp lệ"},{"number":15,"domain":"Coordinate QC","criterion":"X Coordinate không rỗng"},{"number":16,"domain":"Coordinate QC","criterion":"Y Coordinate không rỗng"},{"number":17,"domain":"Coordinate QC","criterion":"CRS được khai báo"},{"number":18,"domain":"Coordinate QC","criterion":"UTM Zone hợp lệ"},{"number":19,"domain":"Coordinate QC","criterion":"Coordinate Unit hợp lệ"},{"number":20,"domain":"Coordinate QC","criterion":"Well nằm trong Block"},{"number":21,"domain":"Coordinate QC","criterion":"Well nằm trong License"},{"number":22,"domain":"Coordinate QC","criterion":"Well không nằm trên đất liền"},{"number":23,"domain":"Coordinate QC","criterion":"Surface Location không trùng"},{"number":24,"domain":"Coordinate QC","criterion":"Coordinate không vượt phạm vi Basin"},{"number":25,"domain":"Coordinate QC","criterion":"KB Elevation hợp lệ"},{"number":26,"domain":"Coordinate QC","criterion":"Water Depth hợp lệ"},{"number":27,"domain":"Wellbore QC","criterion":"Wellbore Name tồn tại"},{"number":28,"domain":"Wellbore QC","criterion":"Parent Well tồn tại"},{"number":29,"domain":"Wellbore QC","criterion":"Sidetrack liên kết đúng"},{"number":30,"domain":"Wellbore QC","criterion":"Wellbore Type hợp lệ"},{"number":31,"domain":"Wellbore QC","criterion":"TD > 0"},{"number":32,"domain":"Wellbore QC","criterion":"TD hợp lý theo thiết kế"},{"number":33,"domain":"Wellbore QC","criterion":"Well Path tồn tại"},{"number":34,"domain":"Wellbore QC","criterion":"Wellbore không mồ côi"},{"number":35,"domain":"Directional Survey QC","criterion":"Survey tồn tại"},{"number":36,"domain":"Directional Survey QC","criterion":"MD tăng dần"},{"number":37,"domain":"Directional Survey QC","criterion":"Không trùng MD"},{"number":38,"domain":"Directional Survey QC","criterion":"TVD ≤ MD"},{"number":39,"domain":"Directional Survey QC","criterion":"TVDSS hợp lệ"},{"number":40,"domain":"Directional Survey QC","criterion":"Inc từ 0-180°"},{"number":41,"domain":"Directional Survey QC","criterion":"Azi từ 0-360°"},{"number":42,"domain":"Directional Survey QC","criterion":"Dogleg không bất thường"},{"number":43,"domain":"Directional Survey QC","criterion":"Northing hợp lệ"},{"number":44,"domain":"Directional Survey QC","criterion":"Easting hợp lệ"},{"number":45,"domain":"Directional Survey QC","criterion":"Survey Station đầy đủ"},{"number":46,"domain":"Directional Survey QC","criterion":"Survey kết thúc tại TD"},{"number":47,"domain":"Directional Survey QC","criterion":"Survey không bị đứt đoạn"},{"number":48,"domain":"Directional Survey QC","criterion":"Survey Datum đúng"},{"number":49,"domain":"Directional Survey QC","criterion":"Survey QA Status được khai báo"},{"number":50,"domain":"Well Log QC","criterion":"Log dataset tồn tại"},{"number":51,"domain":"Well Log QC","criterion":"LAS đọc được"},{"number":52,"domain":"Well Log QC","criterion":"Curve có mnemonic"},{"number":53,"domain":"Well Log QC","criterion":"Curve có unit"},{"number":54,"domain":"Well Log QC","criterion":"Depth tăng liên tục"},{"number":55,"domain":"Well Log QC","criterion":"Depth không âm"},{"number":56,"domain":"Well Log QC","criterion":"Null Value chuẩn hóa"},{"number":57,"domain":"Well Log QC","criterion":"GR trong giới hạn"},{"number":58,"domain":"Well Log QC","criterion":"RHOB trong giới hạn"},{"number":59,"domain":"Well Log QC","criterion":"NPHI trong giới hạn"},{"number":60,"domain":"Well Log QC","criterion":"DT trong giới hạn"},{"number":61,"domain":"Well Log QC","criterion":"Resistivity > 0"},{"number":62,"domain":"Well Log QC","criterion":"Curve Mapping hoàn chỉnh"},{"number":63,"domain":"Well Log QC","criterion":"Metadata log đầy đủ"},{"number":64,"domain":"Core Data QC","criterion":"Core Depth hợp lệ"},{"number":65,"domain":"Core Data QC","criterion":"Porosity 0-40%"},{"number":66,"domain":"Core Data QC","criterion":"Sw 0-100%"},{"number":67,"domain":"Core Data QC","criterion":"Permeability > 0"},{"number":68,"domain":"Core Data QC","criterion":"Grain Density hợp lệ"},{"number":69,"domain":"Core Data QC","criterion":"Sample ID duy nhất"},{"number":70,"domain":"Core Data QC","criterion":"Core Plug đầy đủ"},{"number":71,"domain":"Core Data QC","criterion":"Core Analysis Report tồn tại"},{"number":72,"domain":"Mud Log QC","criterion":"Mud Log tồn tại"},{"number":73,"domain":"Mud Log QC","criterion":"Gas Reading hợp lệ"},{"number":74,"domain":"Mud Log QC","criterion":"Lithology Coding hợp lệ"},{"number":75,"domain":"Mud Log QC","criterion":"Mud Log Depth khớp Survey"},{"number":76,"domain":"Mud Log QC","criterion":"Metadata đầy đủ"},{"number":77,"domain":"Stratigraphy QC","criterion":"Formation Name hợp lệ"},{"number":78,"domain":"Stratigraphy QC","criterion":"Top Depth tồn tại"},{"number":79,"domain":"Stratigraphy QC","criterion":"Base Depth tồn tại"},{"number":80,"domain":"Stratigraphy QC","criterion":"Top < Base"},{"number":81,"domain":"Stratigraphy QC","criterion":"Không trùng Formation"},{"number":82,"domain":"Stratigraphy QC","criterion":"Formation Sequence hợp lệ"},{"number":83,"domain":"Stratigraphy QC","criterion":"Marker Horizon hợp lệ"},{"number":84,"domain":"Stratigraphy QC","criterion":"Missing Formation được cảnh báo"},{"number":85,"domain":"Stratigraphy QC","criterion":"Stratigraphy Datum thống nhất"},{"number":86,"domain":"Stratigraphy QC","criterion":"QC Status được khai báo"},{"number":87,"domain":"Biostratigraphy QC","criterion":"Sample Depth hợp lệ"},{"number":88,"domain":"Biostratigraphy QC","criterion":"Fossil Code hợp lệ"},{"number":89,"domain":"Biostratigraphy QC","criterion":"Age Assignment tồn tại"},{"number":90,"domain":"Biostratigraphy QC","criterion":"Stratigraphic Age nhất quán"},{"number":91,"domain":"Geochemistry QC","criterion":"TOC hợp lệ"},{"number":92,"domain":"Geochemistry QC","criterion":"Ro hợp lệ"},{"number":93,"domain":"Geochemistry QC","criterion":"Tmax hợp lệ"},{"number":94,"domain":"Geochemistry QC","criterion":"S1 hợp lệ"},{"number":95,"domain":"Geochemistry QC","criterion":"S2 hợp lệ"},{"number":96,"domain":"Geochemistry QC","criterion":"OI hợp lệ"},{"number":97,"domain":"Geochemistry QC","criterion":"HI tính đúng"},{"number":98,"domain":"Geochemistry QC","criterion":"Sample ID duy nhất"},{"number":99,"domain":"Geochemistry QC","criterion":"Laboratory tồn tại"},{"number":100,"domain":"Geochemistry QC","criterion":"Lab Report đính kèm"},{"number":101,"domain":"Seismic Survey QC","criterion":"Survey Name duy nhất"},{"number":102,"domain":"Seismic Survey QC","criterion":"2D/3D Type hợp lệ"},{"number":103,"domain":"Seismic Survey QC","criterion":"Acquisition Date tồn tại"},{"number":104,"domain":"Seismic Survey QC","criterion":"Inline hợp lệ"},{"number":105,"domain":"Seismic Survey QC","criterion":"Crossline hợp lệ"},{"number":106,"domain":"Seismic Survey QC","criterion":"CDP hợp lệ"},{"number":107,"domain":"Seismic Survey QC","criterion":"Geometry QC đạt"},{"number":108,"domain":"Seismic Survey QC","criterion":"Coordinate Scaling đúng"},{"number":109,"domain":"Seismic Survey QC","criterion":"SEG-Y Header hợp lệ"},{"number":110,"domain":"Seismic Survey QC","criterion":"Navigation QC đạt"},{"number":111,"domain":"Reservoir QC","criterion":"Net Pay ≥ 0"},{"number":112,"domain":"Reservoir QC","criterion":"Gross Thickness ≥ Net Pay"},{"number":113,"domain":"Reservoir QC","criterion":"Porosity Model hợp lệ"},{"number":114,"domain":"Reservoir QC","criterion":"Water Saturation hợp lệ"},{"number":115,"domain":"Reservoir QC","criterion":"NTG hợp lệ"},{"number":116,"domain":"Reservoir QC","criterion":"Reservoir Unit Mapping đúng"},{"number":117,"domain":"Production QC","criterion":"Production Date tồn tại"},{"number":118,"domain":"Production QC","criterion":"Oil không âm"},{"number":119,"domain":"Production QC","criterion":"Gas không âm"},{"number":120,"domain":"Production QC","criterion":"Water không âm"},{"number":121,"domain":"Production QC","criterion":"Injection không âm"},{"number":122,"domain":"Production QC","criterion":"Cumulative Production đúng"},{"number":123,"domain":"Production QC","criterion":"Missing Month được phát hiện"},{"number":124,"domain":"Production QC","criterion":"Material Balance hợp lý"},{"number":125,"domain":"Metadata QC","criterion":"Data Owner tồn tại"},{"number":126,"domain":"Metadata QC","criterion":"Source tồn tại"},{"number":127,"domain":"Metadata QC","criterion":"Document Reference tồn tại"},{"number":128,"domain":"Metadata QC","criterion":"Version tồn tại"},{"number":129,"domain":"Metadata QC","criterion":"Load Date tồn tại"},{"number":130,"domain":"Metadata QC","criterion":"QC By tồn tại"},{"number":131,"domain":"Metadata QC","criterion":"QC Date tồn tại"},{"number":132,"domain":"Metadata QC","criterion":"Approval By tồn tại"},{"number":133,"domain":"Metadata QC","criterion":"Approval Date tồn tại"},{"number":134,"domain":"Metadata QC","criterion":"Data Lineage đầy đủ"}]'''
RAW_RULES = json.loads(_RULES_JSON)

# The active operational labels below follow the user's supplied QC_Data_EPDB.docx table.
# ST (group 8), BS (group 9), and XD (group 15) remain in the historical source catalog only.
ACTIVE_DOCX_CRITERIA = {
    "Well Header QC": [
        "Well Name tồn tại", "Well Name duy nhất", "UWI tồn tại", "UWI duy nhất", "API Number tồn tại",
        "Well Type hợp lệ", "Well Status hợp lệ", "Operator tồn tại", "Field tồn tại", "Block tồn tại",
        "Basin tồn tại", "Country tồn tại", "Spud Date tồn tại", "Completion Date hợp lệ",
    ],
    "Coordinate QC": [
        "X Coordinate", "Y Coordinate", "CRS khai báo", "CRS hợp lệ", "UTM Zone đúng",
        "X Range hợp lệ", "Y Range hợp lệ", "Well nằm trong Block", "Well nằm trong License",
        "Surface không trùng", "KB Elevation hợp lệ", "Water Depth hợp lệ",
    ],
    "Wellbore QC": [
        "Wellbore Name", "Parent Well", "Sidetrack Link", "Wellbore Type", "TD > 0",
        "Tồn tại Survey", "Wellbore Status", "Orphan Wellbore",
    ],
    "Directional Survey QC": [
        "Survey tồn tại", "MD tăng dần", "Không trùng MD", "TVD ≤ MD", "Inc hợp lệ",
        "Azi hợp lệ", "Station đầy đủ", "Northing hợp lệ", "Easting hợp lệ", "Dogleg hợp lệ",
        "Survey Datum", "TVDSS tính được", "Survey tới TD", "Survey không đứt đoạn", "Survey QA Status",
    ],
    "Well Log QC": [
        "LAS đọc được", "Dataset tồn tại", "Curve Name", "Curve Unit", "Depth tăng dần",
        "Depth không âm", "Null chuẩn hóa", "GR", "RHOB", "NPHI", "DT", "Rt",
        "Curve Mapping", "Metadata",
    ],
    "Core Data QC": [
        "Core Depth", "Sample ID", "Porosity", "Sw", "Permeability", "Grain Density", "Plug Data", "Report",
    ],
    "Mud Log QC": [
        "Mud Log tồn tại", "Depth khớp Survey", "Gas Reading ≥ 0", "Lithology Code hợp lệ", "Metadata đầy đủ",
    ],
    "Geochemistry QC": [
        "TOC", "Ro", "Tmax", "S1", "S2", "HI", "OI", "Sample ID Unique", "Laboratory", "Report",
    ],
    "Seismic Survey QC": [
        "Survey Name Unique", "Acquisition Date tồn tại", "Inline hợp lệ", "Crossline hợp lệ", "CDP hợp lệ",
        "Geometry QC Pass", "Navigation QC Pass", "Trace Count đúng", "SEG-Y Header hợp lệ", "Coordinate Scaling đúng",
    ],
    "Reservoir QC": [
        "Gross Thickness >0", "Net Pay ≥0", "Gross ≥ Net", "Porosity 0-40%", "Sw 0-100%", "NTG 0-1",
    ],
    "Production QC": [
        "Production Date tồn tại", "Oil ≥ 0", "Gas ≥ 0", "Water ≥ 0", "Injection ≥ 0",
        "No Missing Month", "Cumulative Production tăng liên tục", "UBHI + Production Date không trùng",
    ],
    "Metadata QC": [
        "Data Owner", "Source", "Document Reference", "Version", "Load Date", "QC By",
        "QC Date", "Approval By", "Approval Date", "Data Lineage",
    ],
}
for domain, labels in ACTIVE_DOCX_CRITERIA.items():
    domain_rows = [r for r in RAW_RULES if r["domain"] == domain]
    if len(domain_rows) != len(labels):
        raise RuntimeError(f"DOCX criterion count mismatch for {domain}: {len(domain_rows)} vs {len(labels)}")
    for raw_row, label in zip(domain_rows, labels):
        raw_row["criterion"] = label


PREFIXES = {
    "Well Header QC": "WH", "Coordinate QC": "CO", "Wellbore QC": "WB",
    "Directional Survey QC": "SV", "Well Log QC": "LG", "Core Data QC": "CR",
    "Mud Log QC": "ML", "Stratigraphy QC": "ST", "Biostratigraphy QC": "BS",
    "Geochemistry QC": "GC", "Seismic Survey QC": "SE", "Reservoir QC": "RS",
    "Production QC": "PD", "Metadata QC": "MD"
}
GROUP_NUMBERS: dict[str, int] = {}
RULES_150: list[dict[str, Any]] = []
for row in RAW_RULES:
    group = row["domain"]
    GROUP_NUMBERS[group] = GROUP_NUMBERS.get(group, 0) + 1
    code = f"{PREFIXES[group]}-{GROUP_NUMBERS[group]:02d}"
    RULES_150.append({
        "number": row["number"], "rule_id": code, "domain": group,
        "name": row["criterion"], "criterion": row["criterion"],
    })

# Canonical expected names plus compatibility aliases for the current EPDB schema.
COLUMN_ALIASES: dict[str, dict[str, list[str]]] = {
    "epdb_basin": {"basin_id": ["basin_id"], "basin_name": ["basin_name", "name"]},
    "epdb_block": {
        "block_id": ["block_id"], "block_name": ["block_name", "name"], "basin_id": ["basin_id"],
        "x_min": ["x_min"], "x_max": ["x_max"], "y_min": ["y_min"], "y_max": ["y_max"],
        "bounds_crs": ["bounds_crs"], "coordinate_unit": ["coordinate_unit", "coord_unit"],
    },
    "epdb_field": {"field_id": ["field_id"], "field_name": ["field_name", "name"], "block_id": ["block_id"]},
    "epdb_well": {
        "well_name": ["well_name", "wellname", "name"], "uwi": ["uwi"],
        "api_number": ["api_number", "api", "api_no", "api_num"],
        "well_type": ["well_type", "welltype"],
        "well_status": ["well_status", "current_status", "status"],
        "operator": ["operator", "operator_name"], "field_id": ["field_id"],
        "block_id": ["block_id"], "basin_id": ["basin_id"], "country": ["country", "country_name"],
        "spud_date": ["spud_date"], "completion_date": ["completion_date", "completed_date"],
        "rig_name": ["rig_name", "rig"], "td": ["td", "total_depth", "totaldepth"],
        "x_coordinate": ["x_coordinate", "easting", "x", "surface_x"],
        "y_coordinate": ["y_coordinate", "northing", "y", "surface_y"],
        "crs": ["crs", "coordinate_reference_system", "coordinate_system"],
        "utm_zone": ["utm_zone", "zone"], "coordinate_unit": ["coordinate_unit", "coord_unit"],
        "surface_location": ["surface_location", "surface_location_id"],
        "kb_elevation": ["kb_elevation", "kb", "kelly_bushing_elevation"],
        "water_depth": ["water_depth", "waterdepth"], "license_id": ["license_id", "licence_id"],
        "is_within_block": ["is_within_block", "within_block", "block_spatial_qc"],
        "is_within_license": ["is_within_license", "within_license", "license_spatial_qc", "licence_spatial_qc"],
        "well_not_on_land": ["well_not_on_land", "is_offshore", "offshore_location_valid", "not_on_land"],
        "coordinate_within_basin": ["coordinate_within_basin", "within_basin", "basin_coordinate_valid"],
        "x_within_asset": ["x_within_asset", "x_range_valid"], "y_within_asset": ["y_within_asset", "y_range_valid"],
        "planned_td": ["planned_td", "design_td", "planned_total_depth"],
        "data_owner": ["data_owner"], "source": ["source", "source_name", "data_source"],
        "document_reference": ["document_reference", "doc_reference", "document_ref"],
        "version": ["version", "data_version"], "load_date": ["load_date"],
        "qc_by": ["qc_by"], "qc_date": ["qc_date"], "approval_by": ["approval_by"],
        "approval_date": ["approval_date"], "data_lineage": ["data_lineage", "lineage"],
    },
    "epdb_borehole": {
        "borehole_name": ["borehole_name", "wellbore_name", "name"], "ubhi": ["ubhi"], "uwi": ["uwi"],
        "borehole_type": ["borehole_type", "wellbore_type", "type"], "td": ["td", "total_depth", "totaldepth"],
        "planned_td": ["planned_td", "design_td", "planned_total_depth"],
        "well_path_id": ["well_path_id", "well_path", "path_id"],
        "sidetrack_parent_ubhi": ["sidetrack_parent_ubhi", "parent_ubhi", "parent_wellbore_ubhi"],
        "is_sidetrack": ["is_sidetrack", "sidetrack_flag", "sidetrack"],
        "wellbore_status": ["wellbore_status", "borehole_status", "current_status", "status"],
    },
    "epdb_deviation": {
        "ubhi": ["ubhi"], "md": ["md", "measured_depth", "depth"], "tvd": ["tvd", "true_vertical_depth"],
        "tvdss": ["tvdss", "tvd_ss", "tvdss_m"], "inc": ["inc", "inclination", "incl"],
        "azi": ["azi", "azimuth", "azim"], "dogleg": ["dogleg", "dogleg_severity", "dls"],
        "northing": ["northing", "y_coordinate", "y"], "easting": ["easting", "x_coordinate", "x"], "block_id": ["block_id"],
        "survey_station": ["survey_station", "station_id", "station_number"],
        "sample_order": ["station_order", "sample_order", "row_order", "record_order", "station_number", "id"],
        "crs": ["crs", "coordinate_reference_system", "coordinate_system"],
        "survey_datum": ["survey_datum", "datum", "vertical_datum"],
        "survey_qa_status": ["survey_qa_status", "qa_status", "qc_status", "status"],
        "coordinate_unit": ["coordinate_unit"],
    },
    "epdb_log_data": {
        "ubhi": ["ubhi"], "uwi": ["uwi"], "md": ["md", "measured_depth", "depth"],
        "gr": ["gr", "gamma_ray"], "rhob": ["rhob", "density"], "nphi": ["nphi", "neutron_porosity"],
        "dt": ["dt", "sonic", "deltat"], "rt": ["rt", "resistivity", "lld"],
        "cali": ["cali", "caliper"], "sp": ["sp", "spontaneous_potential"],
        "sample_order": ["sample_order", "row_order", "record_order", "sample_index", "id"],
    },
    "epdb_log_metadata": {
        # ubhi is stored directly on this existing table because epdb_log_dataset was removed.
        "dataset_id": ["dataset_id"], "ubhi": ["ubhi"], "curve_name": ["curve_name", "mnemonic", "curve_mnemonic"],
        "curve_unit": ["curve_unit", "unit", "units"], "curve_value": ["curve_value", "value", "data_value"],
        "mapping_status": ["mapping_status", "curve_mapping_status", "mapped_status"],
        "las_read_status": ["las_read_status", "read_status", "parse_status"],
        "source_file": ["source_file", "file_name", "las_file_name"],
        "las_version": ["las_version", "version"], "null_value": ["null_value", "null_sentinel"],
    },
    "epdb_core_cuttings_sample": {
        "ubhi": ["ubhi"], "plug_depth": ["plug_depth", "core_depth", "depth"],
        "sample_id": ["sample_id", "plug_number", "sample_number", "plug_id"],
        "porosity": ["porosity", "porosity_pct", "phi"], "sw": ["sw", "water_saturation", "sw_pct"],
        "permeability": ["permeability", "perm", "permeability_md"],
        "grain_density": ["grain_density", "grain_density_gcc", "matrix_density"],
        "plug_data_status": ["plug_data_status", "data_completeness_status", "qc_status"],
        "report_reference": ["report_reference", "report_uri", "report_path", "report_file"],
    },
    "epdb_mud_log": {
        "ubhi": ["ubhi"], "md": ["md", "depth", "measured_depth"], "gas_reading": ["gas_reading", "total_gas", "gas", "gas_units"],
        "lithology_code": ["lithology_code", "lith_code", "lithology"], "recorded_at": ["recorded_at", "log_date", "date"],
        "source": ["source", "data_source"], "mud_log_id": ["mud_log_id", "record_id", "id"],
    },
    "epdb_stratigraphy": {
        "ubhi": ["ubhi"], "formation_name": ["formation_name", "formation", "formation_name_en"],
        "top_depth": ["top_depth", "formation_top", "top_md", "top"],
        "base_depth": ["base_depth", "formation_base", "base_md", "base"],
        "formation_sequence": ["formation_sequence", "sequence_no", "sequence"],
        "marker_horizon": ["marker_horizon", "marker_name", "marker"], "datum": ["datum", "stratigraphy_datum"],
        "qc_status": ["qc_status", "quality_status", "approval_status"],
    },
    "epdb_biostratigraphy": {
        "ubhi": ["ubhi"], "sample_depth": ["sample_depth", "depth", "md"],
        "fossil_code": ["fossil_code", "fossil", "bio_code"], "age_assignment": ["age_assignment", "age", "age_name"],
        "stratigraphic_age_ma": ["stratigraphic_age_ma", "age_ma", "age_myr", "age_numeric"],
    },
    "epdb_geochemistry": {
        "sample_id": ["sample_id", "sample_number", "sample_no"], "ubhi": ["ubhi"],
        "toc": ["toc", "toc_pct"], "ro": ["ro", "vitrinite_reflectance"], "tmax": ["tmax", "t_max"],
        "s1": ["s1"], "s2": ["s2"], "oi": ["oi", "oxygen_index"], "hi": ["hi", "hydrogen_index"],
        "laboratory": ["laboratory", "lab_name", "lab"],
    },
    "epdb_seismic": {
        "survey_name": ["survey_name", "name"], "survey_type": ["survey_type", "type", "dimension"],
        "acquisition_date": ["acquisition_date", "acq_date", "survey_date"], "inline": ["inline", "inline_number"],
        "crossline": ["crossline", "cross_line", "crossline_number"], "cdp": ["cdp", "cdp_number"],
        "geometry_qc_status": ["geometry_qc_status", "geometry_status"],
        "coordinate_scaling_status": ["coordinate_scaling_status", "coord_scaling_status"],
        "segy_header_status": ["segy_header_status", "segy_qc_status", "header_status"],
        "navigation_qc_status": ["navigation_qc_status", "navigation_status"],
        "block_id": ["block_id"], "field_id": ["field_id"], "trace_count": ["trace_count", "n_traces"],
        "trace_count_qc_status": ["trace_count_qc_status", "trace_count_status"],
    },
    "epdb_reservoir": {
        "uwi": ["uwi"], "ubhi": ["ubhi"], "field_id": ["field_id"], "block_id": ["block_id"],
        "gross_thickness": ["gross_thickness", "gross"], "net_pay": ["net_pay", "netpay"],
        "porosity": ["porosity", "porosity_pct", "phi"], "sw": ["sw", "water_saturation", "sw_pct"],
        "ntg": ["ntg", "net_to_gross"], "reservoir_unit_mapping_status": ["reservoir_unit_mapping_status", "unit_mapping_status", "mapping_status"],
    },
    
    "epdb_production": {
        "ubhi": ["ubhi"],
        "prod_date": ["prod_date", "production_date", "date"],
        "oil_rate": ["oil_rate", "oilrate", "oil"],
        "gas_rate": ["gas_rate", "gasrate", "gas"],
        "water_rate": ["water_rate", "waterrate", "water"],
        "injection_rate": ["injection_rate", "injection", "inj_rate"],
        "cumulative_production": [
            "cumulative_production",
            "cum_production",
            "cum_oil",
            "cumulative_oil"
        ],
        "material_balance_error": [
            "material_balance_error",
            "material_balance_pct",
            "balance_error_pct"
        ],
    },

    "epdb_qc_cross_domain": {
        "uwi": ["uwi"], "ubhi": ["ubhi"], "field_id": ["field_id"], "block_id": ["block_id"],
        "tops_log_match": ["tops_log_match"], "tops_core_match": ["tops_core_match"],
        "core_survey_match": ["core_survey_match"], "log_survey_match": ["log_survey_match"],
        "well_block_match": ["well_block_match"], "well_seismic_match": ["well_seismic_match"],
        "formation_biostrat_match": ["formation_biostrat_match"], "formation_basin_model_match": ["formation_basin_model_match", "formation_basin_match"], "reservoir_static_match": ["reservoir_static_match"],
        "static_dynamic_match": ["static_dynamic_match"], "production_completion_match": ["production_completion_match"],
    },
    "epdb_export_audit": {
        "system_name": ["system_name", "target_system"], "export_status": ["export_status", "status", "result"],
    },
    "epdb_ai_dataset_audit": {"readiness_status": ["readiness_status", "status", "qc_status"]},
    "epdb_well_type_dictionary": {"well_type": ["well_type", "type_name", "value", "code", "type_code"]},
    "epdb_well_status_dictionary": {"well_status": ["well_status", "status_name", "value", "code", "status_code"]},
    "epdb_borehole_type_dictionary": {"borehole_type": ["borehole_type", "type_name", "value", "code", "type_code"]},
    "epdb_lithology_dictionary": {"lithology_code": ["lithology_code", "lith_code", "code", "value"]},
    "epdb_fossil_dictionary": {"fossil_code": ["fossil_code", "code", "value"]},
    "epdb_marker": {"marker_horizon": ["marker_horizon", "marker_name", "marker", "name"]},
    "epdb_expected_formation": {"ubhi": ["ubhi"], "formation_name": ["formation_name", "formation", "expected_formation"], "is_required": ["is_required", "required"]},
    "epdb_core_report": {"sample_id": ["sample_id", "plug_number", "sample_number"]},
    "epdb_geochem_report": {"sample_id": ["sample_id", "sample_number", "sample_no"]},
}
# ============================================================
# CUU LONG FIXED SCHEMA - COLUMN MAPPINGS
# ============================================================

COLUMN_ALIASES["epdb_well"].update({
    "uwi": ["well_code"],
    "well_status": ["status"],
    "x_coordinate": ["surface_longitude"],
    "y_coordinate": ["surface_latitude"],
    "water_depth": ["water_depth_m"],
})

COLUMN_ALIASES["epdb_borehole"].update({
    "borehole_name": ["wellbore_code"],
    "ubhi": ["wellbore_id"],
    "borehole_type": ["wellbore_type"],
    "td": ["td_md_m"],
    "wellbore_status": ["status"],
})

COLUMN_ALIASES["epdb_deviation"].update({
    "ubhi": ["wellbore_id"],
    "md": ["md_m"],
    "tvd": ["tvd_m"],
    "inclination": ["inclination_deg"],
    "azimuth": ["azimuth_deg"],
    "dog_leg_severity": ["dogleg_severity"],
})

COLUMN_ALIASES["epdb_log_data"].update({
    "ubhi": ["wellbore_id"],
    "md": ["depth_md_m"],
    "gr": ["gr_api"],
    "rhob": ["rhob_gcc"],
    "nphi": ["nphi_v_v"],
    "rt": ["rt_ohmm"],
    "cali": ["cali_in"],
    "sp": ["sp_mv"],
})

COLUMN_ALIASES["epdb_production"].update({
    "ubhi": ["wellbore_id"],
    "prod_date": ["production_month"],
    "oil_rate": ["oil_bbl"],
    "gas_rate": ["gas_mscf"],
    "water_rate": ["water_bbl"],
})

COLUMN_ALIASES["epdb_core_cuttings_sample"] = {
    "ubhi": ["wellbore_id"],
    "plug_depth": ["bottom_md_m"],
    "plug_number": ["sample_id"],
    "porosity": ["porosity_pct"],
    "permeability": ["permeability_md"],
}

# Every rule is explicitly mapped to an evaluator. Where geometric, export or inter-domain
# evidence cannot be inferred from core tables alone, a dedicated evidence/status column/table
# is required; missing evidence is classified as NOT CHECKED.
SPECS: dict[str, dict[str, Any]] = {}
def _s(code: str, table: str, kind: str, **kw: Any) -> None:
    SPECS[code] = {"table": table, "kind": kind, **kw}

# ============================================================
# 1. WELL HEADER QC — WH-01..WH-14
# Điều kiện theo QC_Data_EPDB.docx
# ============================================================

# 1. Well Name: không Null
_s("WH-01", "epdb_well", "required",
   column="well_name",
   dimensions=["Completeness"])

# 2. Well Name: duy nhất
_s("WH-02", "epdb_well", "unique",
   columns=["well_name"],
   dimensions=["Uniqueness"])

# 3. UWI: không Null
_s("WH-03", "epdb_well", "required",
   column="uwi",
   dimensions=["Completeness"])

# 4. UWI: duy nhất
_s("WH-04", "epdb_well", "unique",
   columns=["uwi"],
   dimensions=["Uniqueness"])

# 5. API Number: có dữ liệu
_s("WH-05", "epdb_well", "required",
   column="api_number",
   dimensions=["Completeness"])

# 6. Well Type: phải thuộc Master List.
# Dùng danh sách cấu hình trong Python để tránh tạo bảng Dictionary riêng.
# Phải xác nhận các giá trị này đúng với Master List chính thức của dự án.
_s("WH-06", "epdb_well", "enum_values",
   column="well_type",
   allowed=[
        "Exploration",
        "Appraisal",
        "Development",
        "Injection",
    ],
   dimensions=["Completeness", "Validity"])

# 7. Well Status: phải thuộc danh mục trạng thái được duyệt.
# Danh sách này là allow-list cấu hình, không phải Dictionary trong CSDL.
# Cần xác nhận danh sách có đúng với danh mục nghiệp vụ đang sử dụng.
_s("WH-07", "epdb_well", "enum_values",
   column="well_status",
    allowed=[
        "Drilling",
        "Suspended",
        "Producing",
        "P&A",
        "Injecting",
    ],
   dimensions=["Completeness", "Validity"])

# 8. Operator: không Null
_s("WH-08", "epdb_well", "required",
   column="operator",
   dimensions=["Completeness"])

# 9. Field: phải có giá trị và Field tham chiếu phải tồn tại.
# Foreign key sẽ báo lỗi cả khi Field rỗng lẫn khi field_id không tồn tại.
_s("WH-09", "epdb_well", "foreign_key",
   column="field_id",
   ref_table="epdb_field",
   ref_column="field_id",
   dimensions=["Completeness", "Validity", "Consistency"])

# 10. Block: kiểm tra chuỗi Well -> Field -> Block.
# Phù hợp với mô hình dữ liệu chuẩn hóa, trong đó Block được xác định qua Field.
_s("WH-10", "epdb_well", "well_block_chain",
   column="field_id",
   dimensions=["Completeness", "Validity", "Consistency"])

# 11. Basin: kiểm tra chuỗi Well -> Field -> Block -> Basin.
_s("WH-11", "epdb_well", "well_basin_chain",
   column="field_id",
   dimensions=["Completeness", "Validity", "Consistency"])

# 12. Country: không Null
_s("WH-12", "epdb_well", "required",
   column="country",
   dimensions=["Completeness"])

# 13. Spud Date: phải là ngày hợp lệ, không chỉ là chuỗi có dữ liệu.
_s("WH-13", "epdb_well", "date_required",
   column="spud_date",
   dimensions=["Completeness", "Validity"])

# 14. Completion Date >= Spud Date.
# Evaluator date_order phải phân tích thành ngày trước khi so sánh.
_s("WH-14", "epdb_well", "date_order",
   column="completion_date",
   other_column="spud_date",
   dimensions=["Completeness", "Validity", "Consistency"])



# ============================================================
# 2. COORDINATE QC — CO-01..CO-12
# ============================================================

# 1. X Coordinate: không Null
_s("CO-01", "epdb_well", "required",
   column="x_coordinate",
   dimensions=["Completeness", "Validity"])

# 2. Y Coordinate: không Null
_s("CO-02", "epdb_well", "required",
   column="y_coordinate",
   dimensions=["Completeness", "Validity"])

# 3. CRS: phải được khai báo
_s("CO-03", "epdb_well", "required",
   column="crs",
   dimensions=["Completeness"])

# 4. CRS: chỉ chấp nhận loại CRS hợp lệ.
# Cần dùng regex chặt hơn trong evaluator crs_valid; xem mục 2 bên dưới.
_s("CO-04", "epdb_well", "crs_valid",
   column="crs",
   dimensions=["Completeness", "Validity"])

# 5. UTM Zone: chỉ áp dụng khi CRS được khai báo là UTM.
# VN2000/WGS84 không bắt buộc có UTM Zone; khi CRS=UTM chỉ nhận 48N/49N.
_s("CO-05", "epdb_well", "utm_zone_valid",
   columns=["utm_zone"],
   allowed=["48N", "49N"],
   dimensions=["Validity", "Consistency"])

# 6. X nằm trong giới hạn của Block/Asset.
# Chỉ đánh giá khi giới hạn, CRS và đơn vị tham chiếu hợp lệ.
_s("CO-06", "epdb_well", "range_reference",
   column="x_coordinate",
   axis="x",
   path="well",
   dimensions=["Accuracy", "Validity"])

# 7. Y nằm trong giới hạn của Block/Asset.
_s("CO-07", "epdb_well", "range_reference",
   column="y_coordinate",
   axis="y",
   path="well",
   dimensions=["Accuracy", "Validity"])

# 8. Well nằm trong phạm vi Block đã khai báo.
# Liên kết Well -> Field -> Block và kiểm tra điểm X/Y trong hình chữ nhật
# x_min/x_max/y_min/y_max; phạm vi 30 x 30 km giả chỉ phục vụ thử nghiệm.
_s("CO-08", "epdb_well", "within_block",
   columns=["x_coordinate", "y_coordinate", "crs", "coordinate_unit", "field_id"],
   dimensions=["Accuracy", "Consistency", "Validity"])

# 9. Well nằm trong polygon License.
# Chỉ PASS khi cờ được tính từ ranh giới License thực tế.
# Nếu không có dữ liệu polygon License, phải trả về Chưa kiểm tra được.
_s("CO-09", "epdb_well", "boolean_true",
   column="is_within_license",
   dimensions=["Accuracy", "Consistency"])

# 10. Surface Location không trùng.
# Hiện dùng cặp tọa độ X/Y làm khóa kiểm tra trùng vị trí.
_s("CO-10", "epdb_well", "unique",
   columns=["x_coordinate", "y_coordinate"],
   dimensions=["Uniqueness"])

# 11. KB Elevation: từ -100 đến 500 m.
_s("CO-11", "epdb_well", "range",
   column="kb_elevation",
   minimum=-100,
   maximum=500,
   dimensions=["Accuracy", "Validity"])

# 12. Water Depth: >= 0
_s("CO-12", "epdb_well", "nonnegative",
   column="water_depth",
   dimensions=["Accuracy", "Validity"])


# ============================================================
# 3. WELLBORE QC — WB-01..WB-08
# ============================================================

# 1. Wellbore Name: không Null
_s("WB-01", "epdb_borehole", "required",
   column="borehole_name",
   dimensions=["Completeness"])

# 2. Parent Well: UWI phải trỏ đến Well thực sự tồn tại.
_s("WB-02", "epdb_borehole", "required",
   column="well_id",
   dimensions=["Completeness"])

# 3. Sidetrack Link:
# - Nếu là sidetrack: bắt buộc có Parent UBHI tồn tại.
# - Parent phải thuộc cùng UWI.
# - Nếu không phải sidetrack: không được khai báo Parent UBHI.
# Cần cập nhật evaluator conditional_sidetrack như mục 2 bên dưới.
_s("WB-03", "epdb_borehole", "conditional_sidetrack",
   columns=["is_sidetrack", "sidetrack_parent_ubhi", "uwi", "ubhi"],
   ref_table="epdb_borehole",
   ref_column="ubhi",
   dimensions=["Completeness", "Validity", "Consistency"])

# 4. Wellbore Type: allow-list kỹ thuật WITSML WellboreType tạm thời.
# Nếu PVEP có master list riêng đã phê duyệt, thay danh sách này bằng danh mục đó.
_s("WB-04", "epdb_borehole", "enum_values",
   column="borehole_type",
    allowed=[
        "Original",
        "Sidetrack",
        "Re-entry",
    ],
   dimensions=["Completeness", "Validity"])

# 5. TD > 0
_s("WB-05", "epdb_borehole", "positive",
   column="td",
   dimensions=["Completeness", "Accuracy", "Validity"])

# 6. Phải tồn tại Survey trong epdb_deviation.
_s("WB-06", "epdb_borehole", "has_child",
   column="ubhi",
   child_table="epdb_deviation",
   child_column="ubhi",
   dimensions=["Completeness"])

# 7. Wellbore Status: phải thuộc danh mục Well/Borehole Status đã cung cấp.
_s("WB-07", "epdb_borehole", "enum_values",
   column="wellbore_status",
    allowed=[
        "Producing",
        "Suspended",
        "P&A",
        "Injecting",
        "Drilling",
    ],
   dimensions=["Completeness", "Validity"])

# 8. Không có Orphan Wellbore.
# Theo định nghĩa hiện tại, tiêu chí này trùng quan hệ Parent Well của WB-02:
# giữ mã để theo dõi đúng danh mục Word, nhưng cần tránh tính hai lần khi tổng hợp DQS.
_s("WB-08", "epdb_borehole", "foreign_key",
   column="well_id",
   ref_table="epdb_well",
   ref_column="well_id",
   dimensions=["Validity", "Consistency"])


# DIRECTIONAL SURVEY QC
# Survey stations are stored in epdb_deviation.
# Assumption: one row represents one survey station; MD is measured depth.

_s("SV-01", "epdb_borehole", "has_child",
   column="ubhi", child_table="epdb_deviation", child_column="ubhi",
   dimensions=["Completeness"])

_s("SV-02", "epdb_deviation", "sequence_increasing",
   columns=["ubhi", "md"],
   dimensions=["Consistency", "Validity"])

_s("SV-03", "epdb_deviation", "unique",
   columns=["ubhi", "md"],
   dimensions=["Uniqueness"])

_s("SV-04", "epdb_deviation", "compare_le",
   columns=["tvd", "md"],
   dimensions=["Consistency", "Validity"])

_s(
    "SV-05", "epdb_deviation", "range",
    column="inclination", minimum=0, maximum=180,
    dimensions=["Accuracy", "Validity"],
)

_s(
    "SV-06", "epdb_deviation", "range",
    column="azimuth", minimum=0, maximum=360,
    dimensions=["Accuracy", "Validity"],
)

_s(
    "SV-07", "epdb_deviation", "multi_required",
    columns=["md", "tvd", "inclination", "azimuth"],
    dimensions=["Completeness"],
)

_s("SV-08", "epdb_deviation", "range_reference",
   column="northing", axis="y", path="deviation",
   dimensions=["Accuracy", "Validity"])

_s("SV-09", "epdb_deviation", "range_reference",
   column="easting", axis="x", path="deviation",
   dimensions=["Accuracy", "Validity"])

# Valid only if dogleg is already expressed in degrees per 30 metres.
_s(
    "SV-10", "epdb_deviation", "max",
    column="dog_leg_severity", maximum=15, strict_max=True,
    dimensions=["Accuracy", "Validity"],
)

_s("SV-11", "epdb_deviation", "required",
   column="survey_datum",
   dimensions=["Completeness", "Consistency"])

_s("SV-12", "epdb_deviation", "required",
   column="tvdss",
   dimensions=["Completeness", "Validity"])

_s("SV-13", "epdb_borehole", "survey_reaches_td",
   columns=["ubhi", "td"],
   child_table="epdb_deviation", child_columns=["ubhi", "md"],
   dimensions=["Consistency", "Accuracy"],
   tolerance_abs=10.0, tolerance_pct=0.01)

_s("SV-14", "epdb_deviation", "max_gap",
   columns=["ubhi", "md"], maximum_gap=30.0,
   dimensions=["Consistency", "Validity"])

_s(
    "SV-15", "epdb_deviation", "status_pass",
    column="survey_qa_status",
    allowed=["Approved"],
    dimensions=["Validity", "Consistency"],
)


# WELL LOG QC
# Curve metadata: epdb_log_metadata.
# Sample values: epdb_log_data.

_s(
    "LG-01",
    "epdb_borehole",
    "document_file",
    population_table="epdb_borehole",
    population_key="ubhi",
    document_type="LAS",
    file_validation="las_readable",
    dimensions=["Validity"],
)

# Dataset/curve metadata must be linked to the borehole.
_s(
    "LG-02", "epdb_borehole", "has_child",
    column="ubhi",
    child_table="epdb_log_data",
    child_column="ubhi",
    dimensions=["Completeness"],
)

_s("LG-03", "epdb_log_metadata", "required",
   column="curve_name",
   dimensions=["Completeness"])

_s("LG-04", "epdb_log_metadata", "required",
   column="curve_unit",
   dimensions=["Completeness", "Validity"])

_s("LG-05", "epdb_log_data", "sequence_increasing",
   columns=["ubhi", "md"],
   dimensions=["Consistency", "Validity"])

_s("LG-06", "epdb_log_data", "nonnegative",
   column="md",
   dimensions=["Accuracy", "Validity"])

_s("LG-07", "epdb_log_data", "sentinel_any",
   columns=["gr", "rhob", "nphi", "rt"],
   sentinel="-999",
   dimensions=["Validity", "Accuracy"])

_s("LG-08", "epdb_log_data", "range",
   column="gr", minimum=0, maximum=300,
   dimensions=["Accuracy", "Validity"])

_s("LG-09", "epdb_log_data", "range",
   column="rhob", minimum=1, maximum=3.5,
   dimensions=["Accuracy", "Validity"])

_s("LG-10", "epdb_log_data", "range",
   column="nphi", minimum=-0.15, maximum=0.80,
   dimensions=["Accuracy", "Validity"])

_s("LG-11", "epdb_log_data", "range",
   column="dt", minimum=40, maximum=250,
   dimensions=["Accuracy", "Validity"])

_s("LG-12", "epdb_log_data", "positive",
   column="rt",
   dimensions=["Accuracy", "Validity"])

_s("LG-13", "epdb_log_metadata", "status_pass",
   column="mapping_status",
   allowed=["Hoàn tất"],
   dimensions=["Completeness", "Consistency"])

_s("LG-14", "epdb_log_metadata", "multi_required",
   columns=["dataset_id", "ubhi", "source_file", "las_version"],
   dimensions=["Completeness"])


# CORE QC
# Core plug/sample records are stored in epdb_core_cuttings_sample.
# No separate core-report table is assumed.

_s("CR-01", "epdb_core_cuttings_sample", "within_parent_td",
   columns=["ubhi", "plug_depth"],
   parent_table="epdb_borehole", parent_key="ubhi", parent_value="td",
   dimensions=["Accuracy", "Consistency"])

_s(
    "CR-02", "epdb_core_cuttings_sample", "unique",
    columns=["ubhi", "plug_number"],
    dimensions=["Uniqueness"],
)

_s("CR-03", "epdb_core_cuttings_sample", "range",
   column="porosity", minimum=0, maximum=40,
   dimensions=["Accuracy", "Validity"])

_s("CR-04", "epdb_core_cuttings_sample", "range",
   column="sw", minimum=0, maximum=100,
   dimensions=["Accuracy", "Validity"])

_s("CR-05", "epdb_core_cuttings_sample", "positive",
   column="permeability",
   dimensions=["Accuracy", "Validity"])

_s("CR-06", "epdb_core_cuttings_sample", "range",
   column="grain_density", minimum=1.5, maximum=4.0,
   dimensions=["Accuracy", "Validity"])

_s("CR-07", "epdb_core_cuttings_sample", "multi_required",
    columns=[
        "plug_number",
        "sample_type",
        "top_md_m",
        "bottom_md_m",
    ],
    dimensions=["Completeness"],
)

# This verifies that a report reference is populated, not that a physical file exists.
_s(
    "CR-08",
    "epdb_core_cuttings_sample",
    "document_file",
    population_table="epdb_core_cuttings_sample",
    population_key="ubhi",
    document_type="CORE_REPORT",
    file_validation="exists",
    dimensions=["Completeness"],
)

# MUD LOG QC — epdb_mud_log was removed; these rules stay NOT CHECKED until a retained source is identified.
_s("ML-01", "epdb_borehole", "has_child", column="ubhi", child_table="epdb_mud_log", child_column="ubhi", dimensions=["Completeness"])
_s("ML-02", "epdb_mud_log", "depth_within_survey", columns=["ubhi", "md"], ref_table="epdb_deviation", ref_columns=["ubhi", "md"], dimensions=["Consistency", "Accuracy"])
_s("ML-03", "epdb_mud_log", "nonnegative", column="gas_reading", dimensions=["Accuracy", "Validity"])
# Without a separate dictionary or approved value list, this verifies presence only.
_s("ML-04", "epdb_mud_log", "dictionary", column="lithology_code", ref_table="epdb_lithology_dictionary", ref_column="lithology_code", ref_alternative_columns=["description"], dimensions=["Completeness", "Validity"])
_s("ML-05", "epdb_mud_log", "multi_required", columns=["ubhi", "md", "recorded_at", "source"], dimensions=["Completeness"])

# STRATIGRAPHY: ST-01..ST-10
_s("ST-01", "epdb_stratigraphy", "required", column="formation_name", dimensions=["Completeness", "Validity"])
_s("ST-02", "epdb_stratigraphy", "required", column="top_depth", dimensions=["Completeness"])
_s("ST-03", "epdb_stratigraphy", "required", column="base_depth", dimensions=["Completeness"])
_s("ST-04", "epdb_stratigraphy", "compare_lt", columns=["top_depth", "base_depth"], dimensions=["Consistency", "Validity"])
_s("ST-05", "epdb_stratigraphy", "unique", columns=["ubhi", "formation_name"], dimensions=["Uniqueness"])
_s("ST-06", "epdb_stratigraphy", "interval_order", columns=["ubhi", "top_depth", "base_depth"], dimensions=["Consistency", "Validity"])
_s("ST-07", "epdb_stratigraphy", "dictionary", column="marker_horizon", ref_table="epdb_marker", ref_column="marker_horizon", dimensions=["Validity", "Consistency"])
_s("ST-08", "epdb_expected_formation", "missing_formation", child_table="epdb_stratigraphy", dimensions=["Completeness", "Consistency"])
_s("ST-09", "epdb_stratigraphy", "consistent_group", columns=["ubhi", "datum"], dimensions=["Consistency"])
_s("ST-10", "epdb_stratigraphy", "status_pass", column="qc_status", allowed=["approved", "pass", "passed"], dimensions=["Validity", "Consistency"])

# BIOSTRATIGRAPHY: BS-01..BS-04
_s("BS-01", "epdb_biostratigraphy", "within_parent_td", columns=["ubhi", "sample_depth"], parent_table="epdb_borehole", parent_key="ubhi", parent_value="td", dimensions=["Accuracy", "Consistency"])
_s("BS-02", "epdb_biostratigraphy", "dictionary", column="fossil_code", ref_table="epdb_fossil_dictionary", ref_column="fossil_code", dimensions=["Validity"])
_s("BS-03", "epdb_biostratigraphy", "required", column="age_assignment", dimensions=["Completeness"])
_s("BS-04", "epdb_biostratigraphy", "age_consistency", columns=["ubhi", "sample_depth", "stratigraphic_age_ma"], dimensions=["Consistency", "Validity"])

# GEOCHEMISTRY QC — epdb_geochemistry was removed; do not treat core-plug data as geochemistry.
_s("GC-01", "epdb_geochemistry", "range", column="toc", minimum=0, maximum=20, dimensions=["Accuracy", "Validity"])
_s("GC-02", "epdb_geochemistry", "range", column="ro", minimum=0.2, maximum=5, dimensions=["Accuracy", "Validity"])
_s("GC-03", "epdb_geochemistry", "range", column="tmax", minimum=350, maximum=600, dimensions=["Accuracy", "Validity"])
_s("GC-04", "epdb_geochemistry", "nonnegative", column="s1", dimensions=["Accuracy", "Validity"])
_s("GC-05", "epdb_geochemistry", "nonnegative", column="s2", dimensions=["Accuracy", "Validity"])
_s("GC-06", "epdb_geochemistry", "range", column="hi", minimum=0, maximum=1000, dimensions=["Accuracy", "Validity"])
_s("GC-07", "epdb_geochemistry", "range", column="oi", minimum=0, maximum=1000, dimensions=["Accuracy", "Validity"])
_s("GC-08", "epdb_geochemistry", "unique", columns=["sample_id"], dimensions=["Uniqueness"])
_s("GC-09", "epdb_geochemistry", "child_required", column="geochem_id", child_table="epdb_geochem_report", child_column="geochem_id", child_value_column="lab_name", dimensions=["Completeness"])
_s("GC-10", "epdb_geochemistry", "child_required", column="geochem_id", child_table="epdb_geochem_report", child_column="geochem_id", child_value_column="report_id", dimensions=["Completeness"])

# SEISMIC QC — header status fields are evidence from a real SEG-Y/navigation parser, not manual defaults.
_s("SE-01", "epdb_seismic", "unique", columns=["survey_name"], dimensions=["Uniqueness"])
_s("SE-02", "epdb_seismic", "required", column="acquisition_date", dimensions=["Completeness", "Timeliness"])
_s("SE-03", "epdb_seismic", "nonnegative", column="inline", dimensions=["Accuracy", "Validity"])
_s("SE-04", "epdb_seismic", "nonnegative", column="crossline", dimensions=["Accuracy", "Validity"])
_s("SE-05", "epdb_seismic", "nonnegative", column="cdp", dimensions=["Accuracy", "Validity"])
_s("SE-06", "epdb_seismic", "status_pass", column="geometry_qc_status", allowed=["pass", "passed", "approved", "valid"], dimensions=["Validity", "Consistency"])
_s("SE-07", "epdb_seismic", "status_pass", column="navigation_qc_status", allowed=["pass", "passed", "approved", "valid"], dimensions=["Validity", "Consistency"])
_s("SE-08", "epdb_seismic", "status_pass", column="trace_count_qc_status", allowed=["pass", "passed", "approved", "valid"], dimensions=["Validity", "Consistency"])
_s("SE-09", "epdb_seismic", "status_pass", column="segy_header_status", allowed=["pass", "passed", "valid", "approved"], dimensions=["Validity"])
_s("SE-10", "epdb_seismic", "status_pass", column="coordinate_scaling_status", allowed=["pass", "passed", "correct", "valid", "approved"], dimensions=["Validity", "Consistency"])

# RESERVOIR QC — criteria and IDs follow the provided DOCX.
_s("RS-01", "epdb_reservoir", "positive", column="gross_thickness", dimensions=["Accuracy", "Validity"])
_s("RS-02", "epdb_reservoir", "nonnegative", column="net_pay", dimensions=["Accuracy", "Validity"])
_s("RS-03", "epdb_reservoir", "gross_ge_net", columns=["gross_thickness", "net_pay"], dimensions=["Consistency", "Accuracy"])
_s("RS-04", "epdb_reservoir", "range", column="porosity", minimum=0, maximum=40, dimensions=["Accuracy", "Validity"])
_s(
    "RS-05", "epdb_reservoir", "range",
    column="water_saturation", minimum=0, maximum=100,
    dimensions=["Accuracy", "Validity"],
)
_s("RS-06", "epdb_reservoir", "range", column="ntg", minimum=0, maximum=1, dimensions=["Accuracy", "Validity"])

# PRODUCTION QC — No Missing Month precedes cumulative production per the provided DOCX.
_s("PD-01", "epdb_production", "date_required", column="prod_date", dimensions=["Completeness", "Validity", "Timeliness"])
_s("PD-02", "epdb_production", "nonnegative",
   column="oil_rate",
   null_is_not_error=True,
   dimensions=["Accuracy", "Validity"])

_s("PD-03", "epdb_production", "nonnegative",
   column="gas_rate",
   null_is_not_error=True,
   dimensions=["Accuracy", "Validity"])

_s("PD-04", "epdb_production", "nonnegative",
   column="water_rate",
   null_is_not_error=True,
   dimensions=["Accuracy", "Validity"])

_s("PD-05", "epdb_production", "nonnegative",
   column="injection_rate",
   null_is_not_error=True,
   dimensions=["Accuracy", "Validity"])

# PD-06: Kiểm tra tháng khai thác bị thiếu theo từng thân giếng.
_s(
    "PD-06",
    "epdb_production",
    "missing_month",
    columns=["ubhi", "prod_date"],
    dimensions=["Completeness", "Timeliness"]
)

# PD-07: Sản lượng tích lũy phải tăng liên tục theo từng thân giếng.
_s(
    "PD-07",
    "epdb_production",
    "cumulative_increasing",
    columns=["ubhi", "prod_date", "cumulative_production"],
    dimensions=["Consistency", "Accuracy"]
)

_s(
    "PD-08",
    "epdb_production",
    "unique",
    columns=["ubhi", "prod_date"],
    dimensions=["Uniqueness"]
)

# METADATA: MD-01..MD-10. These fields live on existing epdb_well rows.
_METADATA_COLS = [
    "data_owner",
    "source",
    "document_reference",
    "version",
    "load_date",
    "qc_by",
    "qc_date",
    "approval_by",
    "approval_date",
    "data_lineage",
]

for i, col in enumerate(_METADATA_COLS, 1):

    if col == "document_reference":
        _s(
            "MD-03",
            "epdb_borehole",
            "document_reference",
            dimensions=["Completeness"],
        )

    else:
        _s(
            f"MD-{i:02d}",
            "epdb_well",
            "required",
            column=col,
            dimensions=(
                ["Completeness", "Timeliness"]
                if col in {"load_date", "qc_date", "approval_date"}
                else ["Completeness"]
            ),
        )

# Every catalog row must have one and only one explicit evaluator definition.
spec_count = len(SPECS)
if len(RULES_150) != spec_count or len({r["rule_id"] for r in RULES_150}) != spec_count or set(SPECS) != {r["rule_id"] for r in RULES_150}:
    raise RuntimeError(f"Rule catalog mismatch: catalog={len(RULES_150)}, specs={spec_count}")
    
EXCLUDED_RUNTIME_DOMAINS = {"Stratigraphy QC", "Biostratigraphy QC", "Cross-Domain QC"}
ACTIVE_RULES = [r for r in RULES_150 if r["domain"] not in EXCLUDED_RUNTIME_DOMAINS]
ACTIVE_RULE_COUNT = len(ACTIVE_RULES)
if ACTIVE_RULE_COUNT != 120:
    raise RuntimeError(f"Expected 120 active rules after removing WH-15 and excluding groups 8/9/15, got {ACTIVE_RULE_COUNT}")


def _get_actual(table: str, semantic: str, table_columns_fn: Callable[[str], dict[str, str]], normalize_fn: Callable[[Any], str]) -> str | None:
    columns = table_columns_fn(table)
    aliases = COLUMN_ALIASES.get(table, {}).get(semantic, [semantic])
    for alias in aliases:
        hit = columns.get(normalize_fn(alias))
        if hit:
            return hit
    # If the requested semantic itself is a physical field not in alias catalog, try it literally.
    return columns.get(normalize_fn(semantic))


def _ident(name: str, quote_ident_fn: Callable[[str], str], alias: str = "t") -> str:
    return f"{alias}.{quote_ident_fn(name)}"


def _blank(ref: str) -> str:
    return f"({ref} IS NULL OR BTRIM(COALESCE(({ref})::text, '')) = '')"


def _num(ref: str) -> str:
    # Safe numeric conversion: invalid text becomes NULL instead of aborting the entire QC run.
    return (f"CASE WHEN BTRIM(COALESCE(({ref})::text,'')) ~ '^[+-]?([0-9]+(\\.[0-9]*)?|\\.[0-9]+)([eE][+-]?[0-9]+)?$' "
            f"THEN BTRIM(({ref})::text)::NUMERIC ELSE NULL END")


def _date_value(ref: str) -> str:
    """Parse ISO, slash-ISO, or Vietnamese DD/MM/YYYY dates stored as text safely."""
    v = f"LEFT(BTRIM(COALESCE(({ref})::text, '')), 10)"

    def branch(pattern: str, year_expr: str, month_expr: str, day_expr: str) -> str:
        year = f"({year_expr})::INTEGER"
        month = f"({month_expr})::INTEGER"
        day = f"({day_expr})::INTEGER"
        last_day = f"EXTRACT(DAY FROM (MAKE_DATE({year}, {month}, 1) + INTERVAL '1 month - 1 day'))::INTEGER"
        # Nested CASE gates each cast and MAKE_DATE call so malformed dates do not abort QC.
        return (
            f"CASE WHEN {v} ~ '{pattern}' THEN CASE WHEN {year} BETWEEN 1 AND 9999 THEN "
            f"CASE WHEN {month} BETWEEN 1 AND 12 THEN CASE WHEN {day} BETWEEN 1 AND {last_day} "
            f"THEN MAKE_DATE({year}, {month}, {day}) ELSE NULL END ELSE NULL END ELSE NULL END ELSE NULL END"
        )

    iso = branch(
        r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
        f"SUBSTRING({v} FROM 1 FOR 4)",
        f"SUBSTRING({v} FROM 6 FOR 2)",
        f"SUBSTRING({v} FROM 9 FOR 2)",
    )
    return f"({iso})"


def _python_scalar(value: Any) -> Any:
    """Convert NumPy scalar parameters (e.g. numpy.int64 IDs) to DB-driver-safe Python values."""
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:
            pass
    return value


def _find_top_level_keyword(sql: str, keyword: str) -> int:
    """Find a SQL keyword outside parentheses and quoted strings/identifiers."""
    target = keyword.upper()
    depth = 0
    in_single = False
    in_double = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_double:
            if in_single and i + 1 < len(sql) and sql[i + 1] == "'":
                i += 2
                continue
            in_single = not in_single
            i += 1
            continue
        if ch == '"' and not in_single:
            if in_double and i + 1 < len(sql) and sql[i + 1] == '"':
                i += 2
                continue
            in_double = not in_double
            i += 1
            continue
        if not in_single and not in_double:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            if depth == 0 and sql[i:i + len(target)].upper() == target:
                before_ok = i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")
                end = i + len(target)
                after_ok = end >= len(sql) or not (sql[end].isalnum() or sql[end] == "_")
                if before_ok and after_ok:
                    return i
        i += 1
    return -1


def _table_columns_resolved(table: str, semantics: list[str], table_columns_fn, normalize_fn):
    return {key: _get_actual(table, key, table_columns_fn, normalize_fn) for key in semantics}


def build_checks(table_exists_fn, table_columns_fn, normalize_fn, quote_ident_fn, scope: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def make(rule: dict[str, Any]) -> dict[str, Any]:
        code = rule["rule_id"]
        spec = SPECS[code].copy()
        table = spec["table"]
        kind = spec["kind"]
        needed_tables = {table}
        if spec.get("ref_table"):
            needed_tables.add(spec["ref_table"])
        if spec.get("child_table"):
            needed_tables.add(spec["child_table"])
        if spec.get("parent_table"):
            needed_tables.add(spec["parent_table"])
        if kind == "missing_formation":
            needed_tables.add("epdb_stratigraphy")
        if kind in {"well_block_chain", "well_basin_chain"}:
            needed_tables.update({"epdb_field", "epdb_block"})
            if kind == "well_basin_chain":
                needed_tables.add("epdb_basin")
        if kind == "export_status":
            needed_tables.add("epdb_export_audit")
        missing_tables = [t for t in sorted(needed_tables) if not table_exists_fn(t)]
        # Determine fields to resolve per table; the rule dictionary intentionally identifies future fields.
        requirements: dict[str, list[str]] = {table: []}
        for k in ("column", "columns", "other_column"):
            value = spec.get(k)
            if isinstance(value, str): requirements[table].append(value)
            elif isinstance(value, list): requirements[table].extend(value)
        if spec.get("ref_table"):
            ref_t = spec["ref_table"]
            requirements.setdefault(ref_t, []).extend([spec.get("ref_column", "")])
        if spec.get("child_table"):
            ct = spec["child_table"]
            requirements.setdefault(ct, []).append(spec.get("child_column", ""))
            if spec.get("child_columns"):
                requirements[ct].extend(spec["child_columns"])
        if spec.get("parent_table"):
            pt = spec["parent_table"]
            requirements.setdefault(pt, []).extend([spec.get("parent_key", ""), spec.get("parent_value", "")])
        if kind == "has_child_by_key":
            requirements.setdefault(spec["child_table"], []).append(spec["child_column"])
        if kind == "child_required":
            requirements.setdefault(spec["child_table"], []).extend([spec["child_column"], spec["child_value_column"]])
        if kind == "depth_within_survey":
            requirements.setdefault(spec["ref_table"], []).extend(spec["ref_columns"])
        if kind == "within_block":
            needed_tables.update({"epdb_field", "epdb_block"})
            requirements.setdefault(table, []).extend(["x_coordinate", "y_coordinate", "crs", "coordinate_unit", "field_id"])
            requirements.setdefault("epdb_field", []).extend(["field_id", "block_id"])
            requirements.setdefault("epdb_block", []).extend([
                "block_id",
                "x_min",
                "x_max",
                "y_min",
                "y_max",
                "bounds_crs",
                "coordinate_unit",
                "bounds_is_synthetic",
            ])
        if kind == "range_reference":
            requirements.setdefault("epdb_block", []).extend(["block_id", "x_min", "x_max", "y_min", "y_max", "bounds_crs", "coordinate_unit", "bounds_is_synthetic"])
            requirements.setdefault(table, []).append("crs")
            if spec.get("path") == "well":
                requirements.setdefault(table, []).append("coordinate_unit")
            needed_tables.add("epdb_block")
            if spec.get("path") == "well":
                requirements.setdefault("epdb_field", []).extend(["field_id", "block_id"])
                requirements.setdefault(table, []).append("field_id")
                needed_tables.add("epdb_field")
            elif spec.get("path") == "deviation":
                requirements.setdefault(table, []).extend([
                    "ubhi",
                    "coordinate_unit",
                ])

                requirements.setdefault("epdb_borehole", []).extend([
                    "ubhi",
                    "uwi",
                ])

                requirements.setdefault("epdb_well", []).extend([
                    "uwi",
                    "field_id",
                ])

                requirements.setdefault("epdb_field", []).extend([
                    "field_id",
                    "block_id",
                ])

                needed_tables.update({
                    "epdb_borehole",
                    "epdb_well",
                    "epdb_field",
                })
        if kind == "missing_formation":
            requirements.setdefault(table, []).extend([
                "ubhi",
                "formation_name",
                "is_required",
            ])

            requirements.setdefault("epdb_stratigraphy", []).extend([
                "ubhi",
                "formation_name",
            ])
        if kind == "dictionary":
            # Chỉ cột khóa tham chiếu là bắt buộc.
            requirements.setdefault(spec["ref_table"], []).append(
                spec["ref_column"]
            )
        if kind == "conditional_sidetrack":
            # Cần UBHI và UWI của Parent để kiểm tra liên kết.
            requirements.setdefault(spec["ref_table"], []).extend([
                spec["ref_column"],
                "uwi",
            ])
            requirements.setdefault(table, []).append("uwi")
        if kind in {"well_block_chain", "well_basin_chain"}:
            requirements.setdefault("epdb_field", []).extend(["field_id", "block_id"])
            requirements.setdefault("epdb_block", []).extend(["block_id", "basin_id"] if kind == "well_basin_chain" else ["block_id"])
            if kind == "well_basin_chain":
                requirements.setdefault("epdb_basin", []).append("basin_id")
        if kind == "enum_values":
            pass
                # DOCUMENT QC: kiểm tra reference trong epdb_document.
                # DOCUMENT REFERENCE QC — MD-03
        # Đánh giá từng UBHI, không đánh giá gộp theo UWI.
        if kind == "document_reference":
            needed_tables.add("epdb_document")

            requirements.setdefault(table, []).append("ubhi")

            requirements.setdefault("epdb_document", []).extend([
                "ubhi",
                "storage_path",
            ])

        # DOCUMENT FILE QC — LG-01 / CR-08
        elif kind == "document_file":
            population_table = spec["population_table"]

            needed_tables.update({
                population_table,
                "epdb_borehole",
                "epdb_document",
            })

            requirements.setdefault(population_table, []).append(
                spec["population_key"]
            )

            requirements.setdefault("epdb_borehole", []).extend([
                "ubhi",
                "uwi",
            ])

            requirements.setdefault("epdb_document", []).extend([
                "ubhi",
                "doc_type",
                "storage_path",
            ])

        # DOCUMENT FILE QC: kiểm tra file LAS/Core Report thực tế.
        elif kind == "document_file":
            population_table = spec["population_table"]

            needed_tables.update({
                population_table,
                "epdb_borehole",
                "epdb_document",
            })

            requirements.setdefault(population_table, []).append(
                spec["population_key"]
            )

            requirements.setdefault("epdb_borehole", []).extend([
                "ubhi",
                "uwi",
            ])

            requirements.setdefault("epdb_document", []).extend([
                "ubhi",
                "doc_type",
                "storage_path",
            ])
        # Recompute table availability after evaluator-specific join paths were added.
        missing_tables = [t for t in sorted(needed_tables) if not table_exists_fn(t)]

        actuals: dict[str, dict[str, str | None]] = {}
        missing_columns: list[str] = []
        for req_table, fields in requirements.items():
            if req_table not in needed_tables and not table_exists_fn(req_table):
                missing_tables.append(req_table)
                continue
            if not table_exists_fn(req_table):
                continue
            actuals[req_table] = _table_columns_resolved(req_table, sorted(set(f for f in fields if f)), table_columns_fn, normalize_fn)
            for field, actual in actuals[req_table].items():
                if actual is None:
                    missing_columns.append(f"{req_table}.{field}")
        missing = sorted(set(missing_tables + missing_columns))
        base = {
            "rule_id": code, "domain": rule["domain"], "name": rule["name"],
            "requirement": rule["name"], "severity": severity_for(rule),
            "dimensions": spec.get("dimensions", ["Validity"]), "source_table": ", ".join(sorted(needed_tables)),
        }
        if missing:
            base["schema_missing"] = missing
            return base

        # Translate conceptual field names into quoted physical columns.
        def q(table_name: str, semantic: str, alias: str = "t") -> str:
            actual = actuals.get(table_name, {}).get(semantic)
            if not actual:
                actual = _get_actual(table_name, semantic, table_columns_fn, normalize_fn)
            if not actual:
                raise KeyError(f"Missing resolved column {table_name}.{semantic}")
            return _ident(actual, quote_ident_fn, alias)

        from_sql = f'FROM {quote_ident_fn(table)} t'
        scope_condition = "TRUE"
        condition = None
        custom_from = None
        custom_condition = None
        unique_cols: list[str] = []
        population_from = from_sql
        population_condition = scope_condition


        # ====================================================
        # DOCUMENT REFERENCE QC — MD-03
        # Đánh giá riêng từng UBHI.
        # ====================================================
        if kind == "document_reference":

            # UBHI của bản ghi đang được kiểm tra trong epdb_borehole.
            ubhi_ref = q(
                table,
                "ubhi",
                alias="t",
            )

            # UBHI và storage_path trong epdb_document.
            doc_ubhi = q(
                "epdb_document",
                "ubhi",
                alias="d",
            )

            doc_path = q(
                "epdb_document",
                "storage_path",
                alias="d",
            )

            # Một UBHI FAIL nếu không có bất kỳ document
            # reference nào có storage_path hợp lệ.
            condition = (
                f"NOT EXISTS ("
                f"SELECT 1 "
                f"FROM {quote_ident_fn('epdb_document')} d "
                f"WHERE {doc_ubhi} = {ubhi_ref} "
                f"AND NOT {_blank(doc_path)}"
                f")"
            )

            from_sql = (
                f"FROM {quote_ident_fn(table)} t"
            )

            population_from = from_sql
            population_condition = "TRUE"

        # ====================================================
        # DOCUMENT FILE QC — LG-01 / CR-08
        # ====================================================
        elif kind == "document_file":

            population_table = spec["population_table"]
            population_key = actuals[population_table][
                spec["population_key"]
            ]

            bh_cols = actuals["epdb_borehole"]
            bh_ubhi_col = quote_ident_fn(bh_cols["ubhi"])
            bh_uwi_col = quote_ident_fn(bh_cols["uwi"])

            population_key_col = quote_ident_fn(population_key)

            population_sql_source = quote_ident_fn(population_table)
            borehole_sql_source = quote_ident_fn("epdb_borehole")
            document_sql_source = quote_ident_fn("epdb_document")

            document_cols = actuals["epdb_document"]

            doc_ubhi_col = quote_ident_fn(document_cols["ubhi"])
            doc_type_col = quote_ident_fn(document_cols["doc_type"])
            doc_path_col = quote_ident_fn(document_cols["storage_path"])

            # Mỗi UBHI chỉ xuất hiện một lần trong quần thể.
            # LG-01: UBHI có dữ liệu Log.
            # CR-08: UBHI có dữ liệu Core Plug.
            base_select = (
                f"SELECT DISTINCT "
                f"p.{population_key_col} AS ubhi, "
                f"bh.{bh_uwi_col} AS uwi "
                f"FROM {population_sql_source} p "
                f"JOIN {borehole_sql_source} bh "
                f"ON bh.{bh_ubhi_col} = p.{population_key_col} "
                f"WHERE p.{population_key_col} IS NOT NULL"
            )

            expected_type = str(
                spec["document_type"]
            ).upper().replace("'", "''")

            # Lấy một reference tương ứng với đúng loại tài liệu.
            # Nếu không có, LEFT JOIN vẫn giữ UBHI trong quần thể
            # để Python đánh giá là thiếu tài liệu.
            document_join = (
                f"LEFT JOIN {document_sql_source} d "
                f"ON d.{doc_ubhi_col} = t.ubhi "
                f"AND UPPER(BTRIM(COALESCE("
                f"d.{doc_type_col}::text, ''))) = '{expected_type}'"
            )

            from_sql = (
                f"FROM ({base_select}) t "
                f"{document_join}"
            )

            population_from = f"FROM ({base_select}) t"
            population_condition = "TRUE"
            condition = "TRUE"

            base["empty_population_status"] = "Chưa có dữ liệu"

        if kind in {"required", "date_required", "required_pattern", "range", "min", "max", "positive", "nonnegative", "not_sentinel", "sentinel_any", "boolean_true", "enum_values", "crs_valid", "utm_zone_valid", "within_block", "status_pass", "multi_required", "date_order", "compare_le", "compare_lt", "planned_td", "gross_ge_net", "hi_formula", "abs_less_than", "consistent_group", "age_consistency", "interval_order", "interval_gap", "max_gap", "sequence_increasing", "cumulative_increasing", "missing_month", "export_status", "conditional_sidetrack", "foreign_key", "dictionary", "range_reference", "within_parent_td", "depth_within_survey", "survey_reaches_td", "has_child", "has_child_by_key", "child_required", "unique", "well_block_chain", "well_basin_chain", "missing_formation", "document_reference", "document_file"}:
            pass
        else:
            return {**base, "schema_missing": [f"No evaluator for kind={kind}"]}

        # Simple row predicates.
        if kind == "required":
            condition = _blank(q(table, spec["column"]))
        elif kind == "date_required":
            date_expr = _date_value(q(table, spec["column"]))
            condition = f"({date_expr}) IS NULL"
        elif kind == "required_pattern":
            ref = q(table, spec["column"])
            condition = f"({_blank(ref)} OR BTRIM(({ref})::text) !~ '{spec['pattern']}')"
        elif kind == "range":
            ref = q(table, spec["column"]); val = _num(ref)
            condition = f"({_blank(ref)} OR ({val}) IS NULL OR ({val}) < {spec['minimum']} OR ({val}) > {spec['maximum']})"
        elif kind == "min":
            ref = q(table, spec["column"]); val = _num(ref)
            condition = f"({_blank(ref)} OR ({val}) IS NULL OR ({val}) < {spec['minimum']})"
        elif kind == "max":
            ref = q(table, spec["column"]); val = _num(ref)
            comp = ">=" if spec.get("strict_max") else ">"
            condition = f"({_blank(ref)} OR ({val}) IS NULL OR ({val}) {comp} {spec['maximum']})"
        elif kind == "abs_less_than":
            ref = q(table, spec["column"]); val = _num(ref)
            # Strict absolute threshold: e.g. Material Balance error must satisfy |error| < 5%.
            condition = f"({_blank(ref)} OR ({val}) IS NULL OR ABS(({val})) >= {spec['maximum']})"
        elif kind == "positive":
            ref = q(table, spec["column"]); val = _num(ref)
            condition = f"({_blank(ref)} OR ({val}) IS NULL OR ({val}) <= 0)"
        elif kind == "nonnegative":
            ref = q(table, spec["column"])
            val = _num(ref)

            if spec.get("null_is_not_error", False):
                # NULL không phải giá trị âm.
                # Chỉ đánh giá các bản ghi có giá trị được cung cấp.
                population_condition = f"NOT {_blank(ref)}"

                # Giá trị không rỗng nhưng không chuyển được sang số
                # vẫn bị coi là không hợp lệ.
                condition = (
                    f"(NOT {_blank(ref)} "
                    f"AND (({val}) IS NULL OR ({val}) < 0))"
                )

                base["empty_population_status"] = "Chưa có dữ liệu"

            else:
                # Giữ nguyên hành vi cũ cho các luật nonnegative khác.
                condition = (
                    f"({_blank(ref)} OR ({val}) IS NULL OR ({val}) < 0)"
                )
        elif kind == "not_sentinel":
            ref = q(table, spec["column"])
            condition = f"(BTRIM(COALESCE(({ref})::text,'')) = '{spec.get('sentinel', '-999')}')"
        elif kind == "sentinel_any":
            sentinel = float(spec.get("sentinel", -999))
            refs = [q(table, col) for col in spec["columns"]]
            condition = "(" + " OR ".join(f"(({_num(ref)}) = {sentinel:g})" for ref in refs) + ")"
        elif kind == "boolean_true":
            ref = q(table, spec["column"])

            normalized = (
                f"LOWER(BTRIM(COALESCE(({ref})::text, '')))"
            )

            allowed = (
                "'true','t','1','yes','y','pass','passed',"
                "'approved','valid','success','inside'"
            )

            # Chỉ đánh giá khi cờ có giá trị rõ ràng.
            condition = (
                f"(NOT {_blank(ref)} "
                f"AND {normalized} NOT IN ({allowed}))"
            )

            # Cờ NULL/rỗng không được xem là một phép kiểm tra đã thực hiện.
            population_condition = f"NOT {_blank(ref)}"
            base["empty_population_status"] = "Chưa kiểm tra được"
        elif kind == "enum_values":
            ref = q(table, spec["column"])

            # So sánh chính xác với danh sách cho phép.
            # Không đổi chữ hoa/thường, không thay dấu cách,
            # dấu gạch ngang hoặc dấu gạch dưới.
            allowed_values = [
                "'" + str(value).replace("'", "''") + "'"
                for value in spec["allowed"]
            ]
            allowed = ",".join(allowed_values)

            condition = (
                f"({_blank(ref)} "
                f"OR ({ref})::text NOT IN ({allowed}))"
            )
        elif kind == "crs_valid":
            ref = q(table, spec["column"])

            # Danh sách CRS chính xác theo định nghĩa hiện tại.
            condition = (
                f"({_blank(ref)} "
                f"OR ({ref})::text NOT IN "
                f"('VN2000', 'WGS84', 'UTM'))"
            )
        
        elif kind == "utm_zone_valid":
            zone_ref = q(table, "utm_zone")

            # CO-05:
            # PASS khi UTM Zone chính xác là 48N hoặc 49N.
            # FAIL khi NULL, rỗng hoặc không thuộc allow-list.
            # Không phụ thuộc giá trị CRS; CRS được kiểm tra riêng
            # bởi CO-03 và CO-04.
            allowed_values = [
                "'" + str(value).replace("'", "''") + "'"
                for value in spec["allowed"]
            ]
            allowed = ",".join(allowed_values)

            condition = (
                f"({_blank(zone_ref)} "
                f"OR ({zone_ref})::text NOT IN ({allowed}))"
            )

            # Mọi bản ghi Well đều thuộc quần thể CO-05.
            population_condition = "TRUE"

        elif kind == "status_pass":
            ref = q(table, spec["column"])

            # Chỉ chấp nhận đúng chuỗi được khai báo trong allowed.
            # Ví dụ: 'pass' không đồng nghĩa với 'PASS'.
            allowed_values = [
                "'" + str(value).replace("'", "''") + "'"
                for value in spec["allowed"]
            ]
            allowed = ",".join(allowed_values)

            condition = (
                f"({_blank(ref)} "
                f"OR ({ref})::text NOT IN ({allowed}))"
            )
        elif kind == "multi_required":
            condition = " OR ".join(_blank(q(table, col)) for col in spec["columns"])
        elif kind == "date_order":
            completion = q(table, spec["column"])
            spud = q(table, spec["other_column"])

            # Phân tích thành kiểu DATE trước khi so sánh.
            completion_date = _date_value(completion)
            spud_date = _date_value(spud)

            # Fail nếu một trong hai ngày thiếu/sai định dạng,
            # hoặc Completion Date < Spud Date.
            condition = (
                f"(({completion_date}) IS NULL "
                f"OR ({spud_date}) IS NULL "
                f"OR ({completion_date}) < ({spud_date}))"
            )
        elif kind == "compare_le":
            a, b = q(table, spec["columns"][0]), q(table, spec["columns"][1]); an, bn = _num(a), _num(b)
            condition = f"({_blank(a)} OR {_blank(b)} OR ({an}) IS NULL OR ({bn}) IS NULL OR ({an}) > ({bn}))"
        elif kind == "compare_lt":
            a, b = q(table, spec["columns"][0]), q(table, spec["columns"][1]); an, bn = _num(a), _num(b)
            condition = f"({_blank(a)} OR {_blank(b)} OR ({an}) IS NULL OR ({bn}) IS NULL OR ({an}) >= ({bn}))"
        elif kind == "planned_td":
            a, b = q(table, "td"), q(table, "planned_td"); an, bn = _num(a), _num(b)
            condition = f"({_blank(a)} OR {_blank(b)} OR ({an}) IS NULL OR ({bn}) IS NULL OR ({an}) > ({bn}))"
        elif kind == "gross_ge_net":
            a, b = q(table, "gross_thickness"), q(table, "net_pay"); an, bn = _num(a), _num(b)
            condition = (
                f"({_blank(a)} OR {_blank(b)} "
                f"OR ({an}) IS NULL OR ({bn}) IS NULL "
                f"OR ({an}) < ({bn}))"
            )
        elif kind == "hi_formula":
            hi, s2, toc = [q(table, c) for c in spec["columns"]]
            hn, s2n, tocn = _num(hi), _num(s2), _num(toc)
            # Source criterion states HI calculated correctly. Formula is HI = (S2 / TOC) * 100; allow 0.01 absolute rounding.
            condition = f"({_blank(hi)} OR {_blank(s2)} OR {_blank(toc)} OR ({tocn}) IS NULL OR ({tocn}) <= 0 OR ({hn}) IS NULL OR ({s2n}) IS NULL OR ({hn}) < 0 OR ({hn}) > 1000 OR ABS(({hn}) - (({s2n}) / NULLIF(({tocn}),0) * 100)) > 0.01)"
        elif kind == "unique":
            unique_cols = list(spec["columns"])
            # Numeric keys (especially X/Y coordinates and measured depth) must be compared
            # numerically, not through text representations such as 1.0 versus 1.00.
            numeric_key_semantics = {"x_coordinate", "y_coordinate", "md", "plug_depth", "sample_depth", "top_depth", "base_depth"}
            normalized_keys = []
            join_terms = []
            base_terms = []
            population_terms = []
            aliases = [f"_key_{i}" for i in range(len(unique_cols))]
            for col, alias in zip(unique_cols, aliases):
                src_ref = q(table, col, alias="src")
                t_ref = q(table, col, alias="t")
                if col in numeric_key_semantics:
                    key_expr = _num(src_ref)
                    normalized_keys.append(key_expr)
                    join_terms.append(f"({_num(t_ref)}) IS NOT DISTINCT FROM d.{quote_ident_fn(alias)}")
                    actual = quote_ident_fn(actuals[table][col])
                    base_terms.append(f"({_num(actual)}) IS NOT NULL")
                    population_terms.append(f"({_num(t_ref)}) IS NOT NULL")
                else:
                    key_expr = f"LOWER(BTRIM(COALESCE({src_ref}::text,'')))"
                    normalized_keys.append(key_expr)
                    join_terms.append(
                        f"LOWER(BTRIM(COALESCE({t_ref}::text,''))) IS NOT DISTINCT FROM d.{quote_ident_fn(alias)}"
                    )
                    actual = quote_ident_fn(actuals[table][col])
                    base_terms.append(f"{actual} IS NOT NULL AND BTRIM(COALESCE({actual}::text,''))<>''")
                    population_terms.append(f"NOT {_blank(t_ref)}")
            grouped_select = ", ".join(f"{expr} AS {quote_ident_fn(alias)}" for expr, alias in zip(normalized_keys, aliases))
            grouped_by = ", ".join(normalized_keys)
            join_condition = " AND ".join(join_terms)
            base_key_cond = " AND ".join(base_terms)
            dup = f'(SELECT {grouped_select} FROM {quote_ident_fn(table)} src WHERE {base_key_cond} GROUP BY {grouped_by} HAVING COUNT(*) > 1) d'
            from_sql = f'FROM {quote_ident_fn(table)} t JOIN {dup} ON {join_condition}'
            condition = "TRUE"
            population_condition = " AND ".join(population_terms)
        elif kind == "dictionary":
            ref = q(table, spec["column"])
            dict_columns = [spec["ref_column"]]

            # Chỉ sử dụng cột thay thế nếu thực sự tồn tại.
            for semantic in spec.get("ref_alternative_columns", []):
                if _get_actual(
                    spec["ref_table"],
                    semantic,
                    table_columns_fn,
                    normalize_fn,
                ):
                    dict_columns.append(semantic)
            matches = []
            for semantic in dict_columns:
                dict_col = q(spec["ref_table"], semantic, alias="dref")
                matches.append(
                    f"LOWER(BTRIM(COALESCE(({dict_col})::text,''))) = "
                    f"LOWER(BTRIM(COALESCE(({ref})::text,'')))"
                )
            condition = (
                f"({_blank(ref)} OR NOT EXISTS (SELECT 1 FROM {quote_ident_fn(spec['ref_table'])} dref "
                f"WHERE (" + " OR ".join(matches) + ")))"
            )
        elif kind == "foreign_key":
            fk = q(table, spec["column"]); parent_col = q(spec["ref_table"], spec["ref_column"], alias="p")
            condition = f"({_blank(fk)} OR NOT EXISTS (SELECT 1 FROM {quote_ident_fn(spec['ref_table'])} p WHERE p.{quote_ident_fn(actuals[spec['ref_table']][spec['ref_column']])} = {fk}))"
        elif kind == "conditional_sidetrack":
            sidetrack = q(table, "is_sidetrack")
            parent = q(table, "sidetrack_parent_ubhi")
            current_uwi = q(table, "uwi")
            current_ubhi = q(table, "ubhi")

            parent_ubhi = q(
                spec["ref_table"], spec["ref_column"], alias="p"
            )
            parent_uwi = q(
                spec["ref_table"], "uwi", alias="p"
            )

            is_true = (
                f"LOWER(BTRIM(COALESCE(({sidetrack})::text,''))) "
                f"IN ('true','t','1','yes','y','sidetrack')"
            )
            is_false = (
                f"LOWER(BTRIM(COALESCE(({sidetrack})::text,''))) "
                f"IN ('false','f','0','no','n','non-sidetrack')"
            )

            flag_missing = _blank(sidetrack)
            parent_missing = _blank(parent)

            parent_exists = (
                f"EXISTS (SELECT 1 FROM "
                f"{quote_ident_fn(spec['ref_table'])} p "
                f"WHERE {parent_ubhi} = {parent} "
                f"AND {parent_uwi} = {current_uwi} "
                f"AND {parent_ubhi} <> {current_ubhi})"
            )

            # Fail khi:
            # 1. Không khai báo rõ có phải Sidetrack hay không.
            # 2. Là Sidetrack nhưng thiếu Parent UBHI hoặc Parent không hợp lệ.
            # 3. Không phải Sidetrack nhưng lại khai báo Parent UBHI.
            condition = (
                f"({flag_missing} "
                f"OR ({is_true} AND "
                f"({parent_missing} OR NOT {parent_exists})) "
                f"OR ({is_false} AND NOT {parent_missing}) "
                f"OR (NOT ({is_true}) AND NOT ({is_false})))"
            )
        elif kind == "has_child":
            parent_key = q(table, spec["column"]); child_key = q(spec["child_table"], spec["child_column"], alias="c")
            condition = f"({_blank(parent_key)} OR NOT EXISTS (SELECT 1 FROM {quote_ident_fn(spec['child_table'])} c WHERE c.{quote_ident_fn(actuals[spec['child_table']][spec['child_column']])} = {parent_key}))"
        elif kind == "has_child_by_key":
            # Parent/source records such as core samples and geochemistry samples.
            parent_key = q(table, spec["column"]); child_key = q(spec["child_table"], spec["child_column"], alias="c")
            condition = f"({_blank(parent_key)} OR NOT EXISTS (SELECT 1 FROM {quote_ident_fn(spec['child_table'])} c WHERE c.{quote_ident_fn(actuals[spec['child_table']][spec['child_column']])} = {parent_key}))"
        elif kind == "child_required":
            # At least one linked child row must contain the requested metadata value.
            parent_key = q(table, spec["column"])
            child_key = q(spec["child_table"], spec["child_column"], alias="c")
            child_value = q(spec["child_table"], spec["child_value_column"], alias="c")
            condition = (
                f"({_blank(parent_key)} OR NOT EXISTS (SELECT 1 FROM {quote_ident_fn(spec['child_table'])} c "
                f"WHERE {child_key} = {parent_key} AND NOT {_blank(child_value)}))"
            )
        elif kind == "missing_formation":
            # Compare an explicit wellbore-specific expected-formation list against observed
            # stratigraphy. This avoids incorrectly treating an arbitrary depth gap as a
            # missing formation. The expected list is a future/reference table in the schema.
            expected_cols = actuals[table]
            strat_cols = actuals["epdb_stratigraphy"]
            expected_table = quote_ident_fn(table)
            strat_table = quote_ident_fn("epdb_stratigraphy")
            expected_ubhi = expected_cols["ubhi"]
            expected_name = expected_cols["formation_name"]
            required_flag = expected_cols["is_required"]
            strat_ubhi = strat_cols["ubhi"]
            strat_name = strat_cols["formation_name"]
            subquery = (
                f"SELECT e.{quote_ident_fn(expected_ubhi)} AS ubhi_check, "
                f"e.{quote_ident_fn(expected_name)} AS expected_formation, "
                f"s.{quote_ident_fn(strat_name)} AS observed_formation, "
                f"(s.{quote_ident_fn(strat_name)} IS NULL) AS is_missing "
                f"FROM {expected_table} e LEFT JOIN {strat_table} s "
                f"ON s.{quote_ident_fn(strat_ubhi)}=e.{quote_ident_fn(expected_ubhi)} "
                f"AND LOWER(BTRIM(COALESCE(s.{quote_ident_fn(strat_name)}::text,'')))="
                f"LOWER(BTRIM(COALESCE(e.{quote_ident_fn(expected_name)}::text,''))) "
                f"WHERE LOWER(BTRIM(COALESCE(e.{quote_ident_fn(required_flag)}::text,''))) "
                f"IN ('true','t','1','yes','y','required')"
            )
            from_sql = f"FROM ({subquery}) t"
            custom_from = from_sql
            population_from = from_sql
            condition = "t.is_missing IS TRUE"
            population_condition = "TRUE"
        elif kind == "range_reference":
            # Compare coordinates with extents stored directly on epdb_block.
            # If boundaries/CRS are missing, population_count is zero and the result is NOT CHECKED.
            value_col = q(table, spec["column"])
            axis = spec.get("axis", "x")
            min_sem, max_sem = ("x_min", "x_max") if axis == "x" else ("y_min", "y_max")
            block_cols = actuals["epdb_block"]
            block_table = quote_ident_fn("epdb_block")
            field_table = quote_ident_fn("epdb_field")
            min_col = f"b.{quote_ident_fn(block_cols[min_sem])}"
            max_col = f"b.{quote_ident_fn(block_cols[max_sem])}"
            bounds_crs = f"b.{quote_ident_fn(block_cols['bounds_crs'])}"
            bounds_unit = f"b.{quote_ident_fn(block_cols['coordinate_unit'])}"
            val_num = _num(value_col)
            block_id_col = quote_ident_fn(block_cols["block_id"])
            bounds_synthetic = (
                f"b.{quote_ident_fn(block_cols['bounds_is_synthetic'])}"
            )
            if spec.get("path") == "well":
                fcols = actuals["epdb_field"]
                from_sql = (f"FROM {quote_ident_fn(table)} t LEFT JOIN {field_table} f "
                            f"ON f.{quote_ident_fn(fcols['field_id'])}=t.{quote_ident_fn(actuals[table]['field_id'])} "
                            f"LEFT JOIN {block_table} b ON b.{block_id_col}=f.{quote_ident_fn(fcols['block_id'])}")
                source_crs = q(table, "crs")
                source_unit = q(table, "coordinate_unit")
                unit_match = (
                    f"(NOT {_blank(bounds_unit)} "
                    f"AND NOT {_blank(source_unit)} "
                    f"AND ({bounds_unit})::text = ({source_unit})::text)"
                )
            else:
                bh_cols = actuals["epdb_borehole"]
                well_cols = actuals["epdb_well"]
                fcols = actuals["epdb_field"]

                from_sql = (
                    f"FROM {quote_ident_fn(table)} t "
                    f"LEFT JOIN {quote_ident_fn('epdb_borehole')} bh "
                    f"ON bh.{quote_ident_fn(bh_cols['ubhi'])}"
                    f"=t.{quote_ident_fn(actuals[table]['ubhi'])} "
                    f"LEFT JOIN {quote_ident_fn('epdb_well')} w "
                    f"ON w.{quote_ident_fn(well_cols['uwi'])}"
                    f"=bh.{quote_ident_fn(bh_cols['uwi'])} "
                    f"LEFT JOIN {field_table} f "
                    f"ON f.{quote_ident_fn(fcols['field_id'])}"
                    f"=w.{quote_ident_fn(well_cols['field_id'])} "
                    f"LEFT JOIN {block_table} b "
                    f"ON b.{block_id_col}"
                    f"=f.{quote_ident_fn(fcols['block_id'])}"
                )

                source_crs = q(table, "crs")
                source_unit = q(table, "coordinate_unit")

                # CRS và đơn vị đều phải có giá trị.
                # Không chuẩn hóa, không tự đổi đơn vị.
                unit_match = (
                    f"NOT {_blank(bounds_unit)} "
                    f"AND NOT {_blank(source_unit)} "
                    f"AND ({bounds_unit})::text "
                    f"= ({source_unit})::text"
                )
            # Missing/mismatched boundaries are excluded from the evaluated population, not counted as spatial failures.
            
            # Chỉ đánh giá trên các bản ghi có đủ điều kiện tham chiếu.
            # Bản ghi có bounds giả lập, CRS/đơn vị không khớp hoặc tọa độ thiếu
            # sẽ không nằm trong quần thể đánh giá.

            population_from = from_sql

            population_condition = (
                f"({min_col} IS NOT NULL "
                f"AND {max_col} IS NOT NULL "
                f"AND {min_col} <= {max_col} "
                f"AND NOT {_blank(bounds_crs)} "
                f"AND NOT {_blank(source_crs)} "
                f"AND ({bounds_crs})::text = ({source_crs})::text "
                f"AND {unit_match} "
                f"AND NOT {_blank(value_col)} "
                f"AND ({val_num}) IS NOT NULL)"
            )
            # Điều kiện phát hiện vi phạm phải dùng cùng quần thể với population_condition.
            out_of_range_condition = (
                f"(({val_num}) < {min_col} "
                f"OR ({val_num}) > {max_col})"
            )

            condition = (
                f"({population_condition}) "
                f"AND ({out_of_range_condition})"
            )

            if spec.get("path") == "deviation":
                coordinate_missing_or_invalid = (
                    f"({_blank(value_col)} "
                    f"OR ({val_num}) IS NULL)"
                )

                reference_valid = (
                    f"({min_col} IS NOT NULL "
                    f"AND {max_col} IS NOT NULL "
                    f"AND {min_col} <= {max_col} "
                    f"AND NOT {_blank(bounds_crs)} "
                    f"AND NOT {_blank(source_crs)} "
                    f"AND ({bounds_crs})::text = ({source_crs})::text "
                    f"AND {unit_match})"
                )

                coordinate_out_of_range = (
                    f"({reference_valid} "
                    f"AND ({out_of_range_condition}))"
                )

                coordinate_present_but_unverifiable = (
                    f"(NOT ({coordinate_missing_or_invalid}) "
                    f"AND NOT ({reference_valid}))"
                )

                condition = (
                    f"(({coordinate_missing_or_invalid}) "
                    f"OR ({coordinate_out_of_range}) "
                    f"OR ({coordinate_present_but_unverifiable}))"
                )

                population_condition = "TRUE"

            else:
                population_condition = (
                    f"({min_col} IS NOT NULL "
                    f"AND {max_col} IS NOT NULL "
                    f"AND {min_col} <= {max_col} "
                    f"AND NOT {_blank(bounds_crs)} "
                    f"AND NOT {_blank(source_crs)} "
                    f"AND ({bounds_crs})::text = ({source_crs})::text "
                    f"AND {unit_match} "
                    f"AND NOT {_blank(value_col)} "
                    f"AND ({val_num}) IS NOT NULL)"
                )

                condition = (
                    f"({population_condition}) "
                    f"AND ({out_of_range_condition})"
                )
            base["empty_population_status"] = "Chưa kiểm tra được"

        elif kind == "within_block":
            # Check Well surface coordinates against the declared rectangular Block bounds.
            well_x = q(table, "x_coordinate")
            well_y = q(table, "y_coordinate")
            well_crs = q(table, "crs")
            well_unit = q(table, "coordinate_unit")
            well_field = q(table, "field_id")
            field_cols = actuals["epdb_field"]
            block_cols = actuals["epdb_block"]
            field_table = quote_ident_fn("epdb_field")
            block_table = quote_ident_fn("epdb_block")
            field_key = f'f.{quote_ident_fn(field_cols["field_id"])}'
            field_block = f'f.{quote_ident_fn(field_cols["block_id"])}'
            block_key = f'b.{quote_ident_fn(block_cols["block_id"])}'
            xmin_ref = f'b.{quote_ident_fn(block_cols["x_min"])}'
            xmax_ref = f'b.{quote_ident_fn(block_cols["x_max"])}'
            ymin_ref = f'b.{quote_ident_fn(block_cols["y_min"])}'
            ymax_ref = f'b.{quote_ident_fn(block_cols["y_max"])}'
            bounds_crs = f'b.{quote_ident_fn(block_cols["bounds_crs"])}'
            bounds_unit = f'b.{quote_ident_fn(block_cols["coordinate_unit"])}'
            bounds_synthetic = (
                f'b.{quote_ident_fn(block_cols["bounds_is_synthetic"])}'
            )
            x_num, y_num = _num(well_x), _num(well_y)
            xmin_num, xmax_num = _num(xmin_ref), _num(xmax_ref)
            ymin_num, ymax_num = _num(ymin_ref), _num(ymax_ref)
            well_crs_norm = f"UPPER(REGEXP_REPLACE(BTRIM(COALESCE(({well_crs})::text,'')), '[[:space:]_-]+', '', 'g'))"
            block_crs_norm = f"UPPER(REGEXP_REPLACE(BTRIM(COALESCE(({bounds_crs})::text,'')), '[[:space:]_-]+', '', 'g'))"
            well_unit_norm = f"LOWER(REGEXP_REPLACE(BTRIM(COALESCE(({well_unit})::text,'')), '[[:space:]_-]+', '', 'g'))"
            block_unit_norm = f"LOWER(REGEXP_REPLACE(BTRIM(COALESCE(({bounds_unit})::text,'')), '[[:space:]_-]+', '', 'g'))"
            from_sql = (
                f"FROM {quote_ident_fn(table)} t "
                f"LEFT JOIN {field_table} f ON {field_key} = {well_field} "
                f"LEFT JOIN {block_table} b ON {block_key} = {field_block}"
            )
            crs_unit_match = (
                f"NOT {_blank(well_crs)} "
                f"AND NOT {_blank(bounds_crs)} "
                f"AND ({well_crs})::text = ({bounds_crs})::text "
                f"AND NOT {_blank(well_unit)} "
                f"AND NOT {_blank(bounds_unit)} "
                f"AND ({well_unit})::text = ({bounds_unit})::text"
            )
            valid_population = (
                f"({x_num}) IS NOT NULL "
                f"AND ({y_num}) IS NOT NULL "
                f"AND ({xmin_num}) IS NOT NULL "
                f"AND ({xmax_num}) IS NOT NULL "
                f"AND ({ymin_num}) IS NOT NULL "
                f"AND ({ymax_num}) IS NOT NULL "
                f"AND ({xmin_num}) <= ({xmax_num}) "
                f"AND ({ymin_num}) <= ({ymax_num}) "
                f"AND {crs_unit_match} "
                f"AND {well_field} IS NOT NULL "
                f"AND {field_block} IS NOT NULL "
                f"AND {block_key} IS NOT NULL "
            )
            population_from = from_sql
            population_condition = f"({valid_population})"
            condition = (
                f"({valid_population} AND "
                f"(({x_num}) < ({xmin_num}) OR ({x_num}) > ({xmax_num}) "
                f"OR ({y_num}) < ({ymin_num}) OR ({y_num}) > ({ymax_num}))"
                f")"
            )
            base["empty_population_status"] = "Chưa kiểm tra được"
        elif kind == "within_parent_td":
            depth_col = q(table, spec["columns"][1])
            ubhi_col = q(table, spec["columns"][0])

            td_col = q(
                spec["parent_table"],
                spec["parent_value"],
                alias="pb",
            )
            pkey = q(
                spec["parent_table"],
                spec["parent_key"],
                alias="pb",
            )

            dnum = _num(depth_col)
            tdnum = _num(td_col)

            from_sql += (
                f' LEFT JOIN {quote_ident_fn(spec["parent_table"])} pb'
                f' ON {pkey} = {ubhi_col}'
            )
            population_from = from_sql

            # Chỉ đánh giá quan hệ độ sâu khi parent có TD hợp lệ.
            td_valid = (
                f"({td_col} IS NOT NULL "
                f"AND ({tdnum}) IS NOT NULL "
                f"AND ({tdnum}) > 0)"
            )

            depth_invalid = (
                f"({_blank(depth_col)} "
                f"OR ({dnum}) IS NULL "
                f"OR ({dnum}) < 0 "
                f"OR ({dnum}) > ({tdnum}))"
            )

            condition = f"({td_valid} AND {depth_invalid})"
            population_condition = td_valid
        elif kind == "depth_within_survey":
            depth_col = q(table, "md"); ubhi_col = q(table, "ubhi")
            r_ubhi = q(spec["ref_table"], spec["ref_columns"][0], alias="sd"); r_md = q(spec["ref_table"], spec["ref_columns"][1], alias="sd")
            dnum, snum = _num(depth_col), _num(r_md)
            condition = f"({_blank(depth_col)} OR NOT EXISTS (SELECT 1 FROM {quote_ident_fn(spec['ref_table'])} sd WHERE {r_ubhi}={ubhi_col} AND ({snum}) IS NOT NULL AND ABS(({snum})-({dnum})) <= 30))"
        elif kind == "survey_reaches_td":
            # Aggregate one row per wellbore: latest MD must be close to declared TD.
            bh = quote_ident_fn(table); dev = quote_ident_fn(spec["child_table"])
            bh_cols = actuals[table]; dev_cols = actuals[spec["child_table"]]
            ubhi_b, td_b = bh_cols["ubhi"], bh_cols["td"]
            ubhi_d, md_d = dev_cols["ubhi"], dev_cols["md"]
            custom_from = (f"FROM (SELECT b.{quote_ident_fn(ubhi_b)} AS ubhi_check, b.{quote_ident_fn(td_b)} AS td_check, "
                           f"MAX(d.{quote_ident_fn(md_d)}) AS end_md FROM {bh} b LEFT JOIN {dev} d "
                           f"ON d.{quote_ident_fn(ubhi_d)}=b.{quote_ident_fn(ubhi_b)} GROUP BY b.{quote_ident_fn(ubhi_b)}, b.{quote_ident_fn(td_b)}) t")
            condition = (
                f"(t.td_check IS NOT NULL "
                f"AND t.td_check::NUMERIC > 0 "
                f"AND ("
                f"t.end_md IS NULL "
                f"OR ABS(t.end_md::NUMERIC - t.td_check::NUMERIC) "
                f"> GREATEST("
                f"{spec['tolerance_abs']}, "
                f"ABS(t.td_check::NUMERIC) * {spec['tolerance_pct']}"
                f")"
                f"))"
            )

            from_sql = custom_from
            population_from = custom_from
            population_condition = (
                "t.td_check IS NOT NULL "
                "AND t.td_check::NUMERIC > 0"
            )
        elif kind == "sequence_increasing":
            md = actuals[table]["md"]; ubhi = actuals[table]["ubhi"]
            mdq, ubhiq = quote_ident_fn(md), quote_ident_fn(ubhi)
            # Prefer an explicit sample-order column when the schema has one. ctid is
            # only a last-resort approximation of imported row order, not a business key.
            order_actual = _get_actual(
                table, "sample_order", table_columns_fn, normalize_fn
            )
            id_actual = _get_actual(
                table, "id", table_columns_fn, normalize_fn
            )

            if order_actual:
                order_expr = f"src.{quote_ident_fn(order_actual)}"
            elif id_actual:
                order_expr = f"src.{quote_ident_fn(id_actual)}"
            else:
                order_expr = "src.ctid"
            from_sql = f'FROM (SELECT src.*, LAG(src.{mdq}) OVER (PARTITION BY src.{ubhiq} ORDER BY {order_expr}) AS __previous_md FROM {quote_ident_fn(table)} src) t'
            condition = f'(t.{mdq} IS NULL OR (t.__previous_md IS NOT NULL AND t.{mdq}::NUMERIC <= t.__previous_md::NUMERIC))'
            population_from = from_sql
        elif kind == "max_gap":
            md = actuals[table]["md"]; ubhi = actuals[table]["ubhi"]
            mdq, ubhiq = quote_ident_fn(md), quote_ident_fn(ubhi)
            from_sql = f'FROM (SELECT src.*, LAG(src.{mdq}) OVER (PARTITION BY src.{ubhiq} ORDER BY src.{mdq}) AS __previous_md FROM {quote_ident_fn(table)} src) t'
            condition = f'(t.__previous_md IS NOT NULL AND t.{mdq}::NUMERIC-t.__previous_md::NUMERIC > {spec["maximum_gap"]})'
            population_from = from_sql
        elif kind == "interval_order":
            ubhi, top, base_depth = [actuals[table][c] for c in ["ubhi", "top_depth", "base_depth"]]
            qubhi, qtop, qbase = [quote_ident_fn(x) for x in (ubhi, top, base_depth)]
            from_sql = f'FROM (SELECT src.*, LAG(src.{qtop}) OVER (PARTITION BY src.{qubhi} ORDER BY src.{qtop}) AS __prev_top, LAG(src.{qbase}) OVER (PARTITION BY src.{qubhi} ORDER BY src.{qtop}) AS __prev_base FROM {quote_ident_fn(table)} src) t'
            condition = f'({qbase} IS NULL OR {qtop} IS NULL OR t.{qtop}::NUMERIC >= t.{qbase}::NUMERIC OR (t.__prev_top IS NOT NULL AND t.{qtop}::NUMERIC < t.__prev_top::NUMERIC) OR (t.__prev_base IS NOT NULL AND t.{qbase}::NUMERIC < t.__prev_base::NUMERIC))'
            population_from = from_sql
        elif kind == "interval_gap":
            ubhi, top, base_depth = [actuals[table][c] for c in ["ubhi", "top_depth", "base_depth"]]
            qubhi, qtop, qbase = [quote_ident_fn(x) for x in (ubhi, top, base_depth)]
            from_sql = f'FROM (SELECT src.*, LAG(src.{qbase}) OVER (PARTITION BY src.{qubhi} ORDER BY src.{qtop}) AS __prev_base FROM {quote_ident_fn(table)} src) t'
            condition = f'(t.__prev_base IS NOT NULL AND t.{qtop}::NUMERIC-t.__prev_base::NUMERIC > {spec["maximum_gap"]})'
            population_from = from_sql
        elif kind == "consistent_group":
            key, val = [actuals[table][c] for c in spec["columns"]]
            qkey, qval = quote_ident_fn(key), quote_ident_fn(val)
            condition = (f'(t.{qval} IS NULL OR (SELECT COUNT(DISTINCT d.{qval}) FROM {quote_ident_fn(table)} d '
                         f'WHERE d.{qkey}=t.{qkey}) > 1)')
        elif kind == "age_consistency":
            ubhi, depth, age = [actuals[table][c] for c in spec["columns"]]
            qu, qd, qa = map(quote_ident_fn, [ubhi, depth, age])
            from_sql = f'FROM (SELECT src.*, LAG(src.{qa}) OVER (PARTITION BY src.{qu} ORDER BY src.{qd}) AS __prev_age FROM {quote_ident_fn(table)} src) t'
            condition = f'(t.{qa} IS NULL OR (t.__prev_age IS NOT NULL AND t.{qa}::NUMERIC < t.__prev_age::NUMERIC) OR t.{qd}::NUMERIC < 0)'
            population_from = from_sql
        
        elif kind == "cumulative_increasing":
            entity_key, dt, cum = [
                actuals[table][c]
                for c in spec["columns"]
            ]

            qkey, qd, qc = map(
                quote_ident_fn,
                [entity_key, dt, cum]
            )

            if table == "epdb_production":
                parsed_date = _date_value(f"src.{qd}")
                cum_ref = f"src.{qc}"
                cum_num = _num(cum_ref)

                # Chỉ đưa bản ghi có ngày hợp lệ và có cumulative
                # chuyển đổi được sang số vào population.
                valid_source = (
                    f"({parsed_date}) IS NOT NULL "
                    f"AND NOT {_blank(cum_ref)} "
                    f"AND ({cum_num}) IS NOT NULL"
                )

                # Nếu bảng có ID thì sử dụng làm khóa phụ
                # để thứ tự đánh giá được xác định ổn định.
                id_actual = _get_actual(
                    table, "id", table_columns_fn, normalize_fn
                )

                order_expr = parsed_date

                if id_actual:
                    order_expr += f", src.{quote_ident_fn(id_actual)}"

                from_sql = (
                    f"FROM ("
                    f"SELECT src.*, "
                    f"{parsed_date} AS __parsed_prod_date, "
                    f"{cum_num} AS __cum_numeric, "
                    f"LAG({cum_num}) OVER ("
                    f"PARTITION BY src.{qkey} "
                    f"ORDER BY {order_expr}"
                    f") AS __prev_cum "
                    f"FROM {quote_ident_fn(table)} src "
                    f"WHERE {valid_source}"
                    f") t"
                )

                # Cumulative âm hoặc giảm so với kỳ trước là lỗi.
                condition = (
                    f"(t.__cum_numeric < 0 "
                    f"OR (t.__prev_cum IS NOT NULL "
                    f"AND t.__cum_numeric < t.__prev_cum))"
                )

                # Population đã được lọc ở truy vấn con.
                population_condition = "TRUE"

                base["empty_population_status"] = "Chưa có dữ liệu"

            else:
                # Giữ logic cũ cho các bảng khác nếu sau này dùng evaluator này.
                from_sql = (
                    f"FROM ("
                    f"SELECT src.*, "
                    f"LAG(src.{qc}) OVER ("
                    f"PARTITION BY src.{qkey} "
                    f"ORDER BY src.{qd}"
                    f") AS __prev_cum "
                    f"FROM {quote_ident_fn(table)} src"
                    f") t"
                )

                condition = (
                    f"({qc} IS NULL "
                    f"OR (t.__prev_cum IS NOT NULL "
                    f"AND t.{qc}::NUMERIC < t.__prev_cum::NUMERIC))"
                )

            population_from = from_sql

        elif kind == "missing_month":
            entity_key, dt = [
                actuals[table][c]
                for c in spec["columns"]
            ]

            qkey, qd = map(
                quote_ident_fn,
                [entity_key, dt]
            )

            parsed_src_date = _date_value(f"src.{qd}")

            from_sql = (
                f"FROM ("
                f"SELECT src.*, "
                f"{parsed_src_date} AS __parsed_prod_date, "
                f"LAG({parsed_src_date}) OVER ("
                f"PARTITION BY src.{qkey} "
                f"ORDER BY {parsed_src_date}"
                f") AS __prev_month "
                f"FROM {quote_ident_fn(table)} src"
                f") t"
            )

            condition = (
                f"(t.__parsed_prod_date IS NOT NULL "
                f"AND t.__prev_month IS NOT NULL "
                f"AND date_trunc('month', t.__parsed_prod_date) "
                f"> date_trunc('month', t.__prev_month) "
                f"+ INTERVAL '1 month')"
            )

            population_from = from_sql
            population_condition = "t.__parsed_prod_date IS NOT NULL"

        
        elif kind == "well_block_chain":
            field_cols = actuals["epdb_field"]; block_cols = actuals["epdb_block"]
            well_field = q(table, "field_id")
            f_id = quote_ident_fn(field_cols["field_id"]); f_block = quote_ident_fn(field_cols["block_id"]); b_id = quote_ident_fn(block_cols["block_id"])
            from_sql = (f'FROM {quote_ident_fn(table)} t LEFT JOIN {quote_ident_fn("epdb_field")} f '
                        f'ON f.{f_id}=t.{quote_ident_fn(actuals[table]["field_id"])} LEFT JOIN {quote_ident_fn("epdb_block")} b ON b.{b_id}=f.{f_block}')
            condition = f'({well_field} IS NULL OR f.{f_id} IS NULL OR b.{b_id} IS NULL)'
            population_from = f'FROM {quote_ident_fn(table)} t'
        elif kind == "well_basin_chain":
            field_cols = actuals["epdb_field"]; block_cols = actuals["epdb_block"]; basin_cols = actuals["epdb_basin"]
            well_field = q(table, "field_id")
            f_id = quote_ident_fn(field_cols["field_id"]); f_block = quote_ident_fn(field_cols["block_id"]); b_id = quote_ident_fn(block_cols["block_id"]); b_basin = quote_ident_fn(block_cols["basin_id"]); ba_id = quote_ident_fn(basin_cols["basin_id"])
            from_sql = (f'FROM {quote_ident_fn(table)} t LEFT JOIN {quote_ident_fn("epdb_field")} f '
                        f'ON f.{f_id}=t.{quote_ident_fn(actuals[table]["field_id"])} LEFT JOIN {quote_ident_fn("epdb_block")} b ON b.{b_id}=f.{f_block} '
                        f'LEFT JOIN {quote_ident_fn("epdb_basin")} ba ON ba.{ba_id}=b.{b_basin}')
            condition = f'({well_field} IS NULL OR f.{f_id} IS NULL OR b.{b_id} IS NULL OR ba.{ba_id} IS NULL)'
            population_from = f'FROM {quote_ident_fn(table)} t'
        elif kind == "export_status":
            system = spec["system"]
            system_col, status_col = actuals[table]["system_name"], actuals[table]["export_status"]
            from_sql = f'FROM {quote_ident_fn(table)} t'
            scope_condition = f"LOWER(BTRIM(t.{quote_ident_fn(system_col)}::text)) = '{system.lower()}'"
            condition = f"({scope_condition} AND LOWER(BTRIM(COALESCE(t.{quote_ident_fn(status_col)}::text,''))) NOT IN ('pass','passed','success','successful','approved','true'))"
            population_condition = scope_condition
        else:
            pass

        if condition is None:
            return {**base, "schema_missing": [f"No condition generated for kind={kind}"]}
        if kind != "unique" and kind != "export_status":
            # Keep evaluator-specific population predicates (e.g. rows with valid parsed dates,
            # or coordinates whose reference bounds are available). Scope is appended separately.
            scope_condition = "TRUE"
        count_sql = f"SELECT COUNT(*) AS issue_count {from_sql} WHERE {condition}"
        entities_sql = f"SELECT DISTINCT 'Đối tượng' AS entity_name {from_sql} WHERE {condition}"
        detail_sql = f"SELECT t.*, '{code} — {rule['name'].replace(chr(39), chr(39)+chr(39))}' AS \"Vấn đề QC\" {from_sql} WHERE {condition} LIMIT 200"
        document_validation = None

        if kind == "document_file":

            detail_sql = (
                "SELECT "
                "t.ubhi AS ubhi, "
                "t.uwi AS uwi, "
                "d.doc_type AS doc_type, "
                "d.storage_path AS storage_path "
                f"{from_sql} "
                "WHERE TRUE"
            )

            document_validation = {
                "mode": spec["file_validation"],
                "document_type": spec["document_type"],
            }
        # Replace generic ctid-only labels with business identifiers when available.
        entity_cols = []
        for semantic in ("well_name", "borehole_name", "uwi", "ubhi", "sample_id", "survey_name", "formation_name", "data_owner"):
            actual = _get_actual(table, semantic, table_columns_fn, normalize_fn)
            if actual:
                entity_cols.append(f"NULLIF(BTRIM(COALESCE(t.{quote_ident_fn(actual)}::text,'')),'')")
        if kind == "document_reference":
            ubhi_actual = actuals[table]["ubhi"]

            entity_expr = (
                f"COALESCE("
                f"NULLIF(BTRIM(t.{quote_ident_fn(ubhi_actual)}::text), ''), "
                f"'Đối tượng'"
                f")"
            )

        elif kind in {"survey_reaches_td", "missing_formation"}:
            entity_expr = "COALESCE(t.ubhi_check::text, 'Đối tượng')"

        elif kind == "export_status":
            sys_actual = actuals[table].get("system_name")
            entity_expr = (
                f"COALESCE(t.{quote_ident_fn(sys_actual)}::text, 'Đối tượng')"
                if sys_actual else "'Đối tượng'"
            )

        elif entity_cols:
            entity_expr = (
                "COALESCE("
                + ", ".join(entity_cols + ["'Đối tượng'"])
                + ")"
            )

        else:
            entity_expr = "'Đối tượng'"
        entities_sql = f"SELECT DISTINCT {entity_expr} AS entity_name {from_sql} WHERE {condition}"
        population_sql = f"SELECT COUNT(*) AS population_count {population_from} WHERE {population_condition}"
        result = {
            **base,
            "count_sql": count_sql,
            "entities_sql": entities_sql,
            "detail_sql": detail_sql,
            "population_sql": population_sql,
        }

        if document_validation is not None:
            result["document_validation"] = document_validation

        return result
    def severity_for(rule: dict[str, Any]) -> str:
        code = rule["rule_id"]
        if code in {"WH-01", "WH-03", "WH-04", "WB-02", "WB-08", "CO-01", "CO-02", "LG-02", "SV-01", "CR-01", "MD-01", "MD-02", "MD-03"}:
            return "Nghiêm trọng"
        if code.startswith(("WH-", "CO-", "WB-", "SV-", "LG-", "CR-", "ML-", "ST-", "BS-", "GC-", "SE-", "RS-", "PD-", "MD-", "XD-")):
            return "Cao"
        return "Trung bình"

    for rule in ACTIVE_RULES:
        check = make(rule)
        if scope is not None:
            spec = SPECS[rule["rule_id"]]
            source_table = spec["table"]
            uwi = scope.get("uwi")
            ubhi = scope.get("ubhi")
            field_id = scope.get("field_id")
            block_id = scope.get("block_id")
            params: dict[str, Any] = {}
            scope_terms: list[str] = []

            # Some checks aggregate a borehole into a derived row with its own UBHI alias.
            if spec["kind"] in {"survey_reaches_td", "missing_formation"}:
                if ubhi:
                    scope_terms.append("t.ubhi_check = :qc_scope_ubhi")
                    params["qc_scope_ubhi"] = ubhi
                elif uwi:
                    scope_terms.append('t.ubhi_check IN (SELECT b."ubhi" FROM "epdb_borehole" b WHERE b."uwi" = :qc_scope_uwi)')
                    params["qc_scope_uwi"] = uwi
            else:
                actual_ubhi = _get_actual(source_table, "ubhi", table_columns_fn, normalize_fn)
                actual_uwi = _get_actual(source_table, "uwi", table_columns_fn, normalize_fn)
                actual_field = _get_actual(source_table, "field_id", table_columns_fn, normalize_fn)
                actual_block = _get_actual(source_table, "block_id", table_columns_fn, normalize_fn)
                if ubhi and actual_ubhi:
                    scope_terms.append(f't.{quote_ident_fn(actual_ubhi)} = :qc_scope_ubhi')
                    params["qc_scope_ubhi"] = str(_python_scalar(ubhi))
                elif uwi and actual_uwi:
                    scope_terms.append(f't.{quote_ident_fn(actual_uwi)} = :qc_scope_uwi')
                    params["qc_scope_uwi"] = str(_python_scalar(uwi))
                elif uwi and actual_ubhi:
                    scope_terms.append(f't.{quote_ident_fn(actual_ubhi)} IN (SELECT b."ubhi" FROM "epdb_borehole" b WHERE b."uwi" = :qc_scope_uwi)')
                    params["qc_scope_uwi"] = str(_python_scalar(uwi))
                else:
                    # Survey records use string identifiers in this schema; casting also works for integer IDs.
                    if field_id is not None and actual_field:
                        scope_terms.append(f'CAST(t.{quote_ident_fn(actual_field)} AS TEXT) = :qc_scope_field_id')
                        params["qc_scope_field_id"] = str(_python_scalar(field_id))
                    if block_id is not None and actual_block:
                        scope_terms.append(f'CAST(t.{quote_ident_fn(actual_block)} AS TEXT) = :qc_scope_block_id')
                        params["qc_scope_block_id"] = str(_python_scalar(block_id))

            if scope_terms and not check.get("schema_missing"):
                scope_condition = "(" + " OR ".join(scope_terms) + ")"
                def add_scope(sql: str | None) -> str | None:
                    if not sql:
                        return sql
                    # Split at top-level LIMIT first. This prevents the old bug where LIMIT 200
                    # became part of the WHERE predicate when a well-scope filter was appended.
                    limit_at = _find_top_level_keyword(sql, "LIMIT")
                    main = sql[:limit_at].rstrip() if limit_at >= 0 else sql.rstrip()
                    tail = " " + sql[limit_at:].lstrip() if limit_at >= 0 else ""
                    where_at = _find_top_level_keyword(main, "WHERE")
                    if where_at < 0:
                        return sql
                    where_end = where_at + len("WHERE")
                    predicate = main[where_end:].strip()
                    if not predicate:
                        return sql
                    return main[:where_end] + " (" + predicate + ") AND " + scope_condition + tail
                for key in ("count_sql", "entities_sql", "detail_sql", "population_sql"):
                    if key in check:
                        check[key] = add_scope(check[key])
                check["params"] = {key: _python_scalar(value) for key, value in params.items()}
                check["scope_applicable"] = True
            else:
                # Keep missing-schema checks visible if the underlying source concept is
                # normally linkable to a well; unrelated global/reference checks are omitted.
                has_link_concept = any(
                    _get_actual(source_table, semantic, table_columns_fn, normalize_fn)
                    for semantic in ("uwi", "ubhi", "field_id", "block_id")
                )
                if check.get("schema_missing") and has_link_concept:
                    check["scope_applicable"] = True
                else:
                    check["scope_applicable"] = False
        checks.append(check)
    return checks

def _is_blank_value(value: Any) -> bool:
    """Kiểm tra giá trị rỗng an toàn với cả pandas/NumPy scalar."""
    if value is None:
        return True

    try:
        import pandas as pd
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass

    return str(value).strip() == ""


def _validate_document_file(
    storage_path: Any,
    document_root: str | Path | None,
    mode: str,
) -> tuple[str, str, str]:
    """
    Kiểm tra file vật lý dựa trên storage_path trong epdb_document.

    Trả về:
        (status, message, resolved_path)

    status:
        Đạt
        Có lỗi
        Chưa kiểm tra được
    """

    if _is_blank_value(storage_path):
        return (
            "Có lỗi",
            "Không có storage_path trong Document Reference.",
            "",
        )

    if document_root is None or str(document_root).strip() == "":
        return (
            "Chưa kiểm tra được",
            "Chưa cấu hình EPDB_DOCUMENT_ROOT.",
            "",
        )

    try:
        root = Path(document_root).expanduser().resolve()

        if not root.exists() or not root.is_dir():
            return (
                "Chưa kiểm tra được",
                f"Thư mục Document Root không tồn tại hoặc không truy cập được: {root}",
                "",
            )

        raw_path = Path(str(storage_path).strip())

        if raw_path.is_absolute():
            file_path = raw_path.resolve()
        else:
            file_path = (root / raw_path).resolve()

        # Không cho phép storage_path thoát ra ngoài Document Root.
        try:
            file_path.relative_to(root)
        except ValueError:
            return (
                "Có lỗi",
                "Storage Path nằm ngoài EPDB_DOCUMENT_ROOT.",
                str(file_path),
            )

        if not file_path.exists():
            return (
                "Có lỗi",
                "File không tồn tại trên hệ thống lưu trữ.",
                str(file_path),
            )

        if not file_path.is_file():
            return (
                "Có lỗi",
                "Đường dẫn không trỏ đến một file.",
                str(file_path),
            )

        if file_path.stat().st_size <= 0:
            return (
                "Có lỗi",
                "File tồn tại nhưng dung lượng bằng 0.",
                str(file_path),
            )

        # LG-01: thử đọc thực tế file LAS.
        if mode == "las_readable":

            try:
                import lasio
            except ImportError:
                return (
                    "Chưa kiểm tra được",
                    "Chưa cài thư viện lasio để đọc file LAS.",
                    str(file_path),
                )

            try:
                las = lasio.read(str(file_path))

                if len(las.curves) == 0:
                    return (
                        "Có lỗi",
                        "LAS đọc được nhưng không có Curve.",
                        str(file_path),
                    )

            except Exception as exc:
                return (
                    "Có lỗi",
                    f"Không đọc được LAS: {type(exc).__name__}: {exc}",
                    str(file_path),
                )

        # CR-08: tiêu chí yêu cầu có Core Report file.
        # Kiểm tra file tồn tại và có dung lượng > 0.
        elif mode == "exists":
            pass

        else:
            return (
                "Chưa kiểm tra được",
                f"Chưa có cơ chế kiểm tra cho mode={mode}.",
                str(file_path),
            )

        return (
            "Đạt",
            "File tồn tại và đáp ứng điều kiện kiểm tra.",
            str(file_path),
        )

    except Exception as exc:
        return (
            "Chưa kiểm tra được",
            f"{type(exc).__name__}: {exc}",
            "",
        )

def execute_checks(
    checks: list[dict[str, Any]],
    read_df_fn,
    ensure_unique_df_fn,
    document_root: str | Path | None = None,
) -> tuple[Any, dict[str, Any], list[str], set[str]]:
    import pandas as pd
    if document_root is None:
        document_root = os.getenv("EPDB_DOCUMENT_ROOT")
    summary_rows: list[dict[str, Any]] = []
    details: dict[str, Any] = {}
    failures: list[str] = []
    entities: set[str] = set()
    for check in checks:
        name = check["name"]
        code = check["rule_id"]
        if check.get("schema_missing"):
            missing = ", ".join(check["schema_missing"])
            details[code] = pd.DataFrame()
            summary_rows.append({
                "Mã luật": code, "Lĩnh vực": check["domain"], "Nhóm kiểm tra": name,
                "Mức độ": check["severity"], "Yêu cầu kiểm tra": check["requirement"],
                "Nguồn đánh giá": check["source_table"], "Chiều DQS": ", ".join(check["dimensions"]),
                "Mẫu đánh giá": None, "Bản ghi / lượt vi phạm": None, "Đối tượng liên quan": None,
                "Kết quả": "Chưa kiểm tra được", "Lỗi kỹ thuật": "Thiếu schema: " + missing,
            })
            failures.append(f"{code} {name}: thiếu schema")
            continue
                # ====================================================
        # DOCUMENT FILE EVALUATION — LG-01 / CR-08
        # ====================================================
        if check.get("document_validation"):

            try:
                params = check.get("params") or {}

                population_df = read_df_fn(
                    check["population_sql"],
                    params=params,
                )

                population = (
                    int(population_df.iloc[0]["population_count"] or 0)
                    if not population_df.empty
                    else 0
                )

                if population == 0:
                    details[code] = pd.DataFrame()

                    summary_rows.append({
                        "Mã luật": code,
                        "Lĩnh vực": check["domain"],
                        "Nhóm kiểm tra": name,
                        "Mức độ": check["severity"],
                        "Yêu cầu kiểm tra": check["requirement"],
                        "Nguồn đánh giá": check["source_table"],
                        "Chiều DQS": ", ".join(check["dimensions"]),
                        "Mẫu đánh giá": 0,
                        "Bản ghi / lượt vi phạm": 0,
                        "Đối tượng liên quan": 0,
                        "Kết quả": "Chưa có dữ liệu",
                        "Lỗi kỹ thuật": "",
                    })
                    continue

                document_df = ensure_unique_df_fn(
                    read_df_fn(
                        check["detail_sql"],
                        params=params,
                    )
                )

                mode = check["document_validation"]["mode"]

                outcomes = []
                failed_ubhi = set()
                unchecked_ubhi = set()

                # Mỗi UBHI được tính là một mẫu QC.
                for ubhi, group in document_df.groupby(
                    "ubhi",
                    dropna=False,
                ):

                    ubhi_text = (
                        ""
                        if _is_blank_value(ubhi)
                        else str(ubhi).strip()
                    )

                    ref_rows = group[
                        group["doc_type"].apply(
                            lambda x: not _is_blank_value(x)
                        )
                    ]

                    # Không có document reference đúng loại.
                    if ref_rows.empty:

                        ubhi_status = "Có lỗi"
                        ubhi_message = (
                            "Không có Document Reference loại "
                            f"{check['document_validation']['document_type']}."
                        )

                        failed_ubhi.add(ubhi_text)

                        outcomes.append({
                            "UBHI": ubhi_text,
                            "Document Type": None,
                            "Storage Path": None,
                            "Physical Path": None,
                            "Kết quả": ubhi_status,
                            "Chi tiết": ubhi_message,
                        })

                        continue

                    file_results = []

                    for _, row in ref_rows.iterrows():

                        status, message, resolved_path = (
                            _validate_document_file(
                                storage_path=row.get("storage_path"),
                                document_root=document_root,
                                mode=mode,
                            )
                        )

                        file_results.append(status)

                        outcomes.append({
                            "UBHI": ubhi_text,
                            "Document Type": row.get("doc_type"),
                            "Storage Path": row.get("storage_path"),
                            "Physical Path": resolved_path,
                            "Kết quả": status,
                            "Chi tiết": message,
                        })

                    # LG-01: mọi LAS reference của UBHI phải đọc được.
                    if mode == "las_readable":

                        if "Có lỗi" in file_results:
                            ubhi_status = "Có lỗi"
                            failed_ubhi.add(ubhi_text)

                        elif "Chưa kiểm tra được" in file_results:
                            ubhi_status = "Chưa kiểm tra được"
                            unchecked_ubhi.add(ubhi_text)

                        else:
                            ubhi_status = "Đạt"

                    # CR-08: chỉ cần có ít nhất một Core Report
                    # tồn tại và có dung lượng hợp lệ.
                    elif mode == "exists":

                        if "Đạt" in file_results:
                            ubhi_status = "Đạt"

                        elif "Chưa kiểm tra được" in file_results:
                            ubhi_status = "Chưa kiểm tra được"
                            unchecked_ubhi.add(ubhi_text)

                        else:
                            ubhi_status = "Có lỗi"
                            failed_ubhi.add(ubhi_text)

                    else:
                        ubhi_status = "Chưa kiểm tra được"
                        unchecked_ubhi.add(ubhi_text)

                    # Gắn kết quả tổng hợp vào từng dòng chi tiết.
                    for item in reversed(outcomes):
                        if item["UBHI"] != ubhi_text:
                            break
                        item["Kết quả UBHI"] = ubhi_status

                details[code] = pd.DataFrame(outcomes)

                entities.update(failed_ubhi)

                issue_count = len(failed_ubhi)
                unchecked_count = len(unchecked_ubhi)

                if issue_count > 0:
                    result = "Có lỗi"

                elif unchecked_count > 0:
                    result = "Chưa kiểm tra được"

                else:
                    result = "Đạt"

                summary_rows.append({
                    "Mã luật": code,
                    "Lĩnh vực": check["domain"],
                    "Nhóm kiểm tra": name,
                    "Mức độ": check["severity"],
                    "Yêu cầu kiểm tra": check["requirement"],
                    "Nguồn đánh giá": check["source_table"],
                    "Chiều DQS": ", ".join(check["dimensions"]),
                    "Mẫu đánh giá": population,
                    "Bản ghi / lượt vi phạm": issue_count,
                    "Đối tượng liên quan": len(failed_ubhi),
                    "Kết quả": result,
                    "Lỗi kỹ thuật": (
                        f"{unchecked_count} UBHI chưa kiểm tra được."
                        if unchecked_count
                        else ""
                    ),
                })

            except Exception as exc:

                details[code] = pd.DataFrame()

                failures.append(
                    f"{code} {name}: "
                    f"{type(exc).__name__}: {exc}"
                )

                summary_rows.append({
                    "Mã luật": code,
                    "Lĩnh vực": check["domain"],
                    "Nhóm kiểm tra": name,
                    "Mức độ": check["severity"],
                    "Yêu cầu kiểm tra": check["requirement"],
                    "Nguồn đánh giá": check["source_table"],
                    "Chiều DQS": ", ".join(check["dimensions"]),
                    "Mẫu đánh giá": None,
                    "Bản ghi / lượt vi phạm": None,
                    "Đối tượng liên quan": None,
                    "Kết quả": "Chưa kiểm tra được",
                    "Lỗi kỹ thuật": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                })

            continue

        try:
            count_df = read_df_fn(check["count_sql"], params=check.get("params") or {})
            issue_count = int(count_df.iloc[0]["issue_count"] or 0) if not count_df.empty else 0
            population_df = read_df_fn(check["population_sql"], params=check.get("params") or {})
            population = int(population_df.iloc[0]["population_count"] or 0) if not population_df.empty else 0
            if population == 0 and issue_count > 0:
                raise RuntimeError(
                    "Inconsistent QC evaluator: "
                    f"{issue_count} violations but population is zero. "
                    "Check condition and population_condition."
                )
            detail_df = pd.DataFrame()
            entity_count = 0
            if issue_count > 0:
                entity_df = read_df_fn(check["entities_sql"], params=check.get("params") or {})
                if "entity_name" in entity_df.columns:
                    found = {str(v).strip() for v in entity_df["entity_name"].dropna() if str(v).strip()}
                    entities.update(found)
                    entity_count = len(found)
                detail_df = ensure_unique_df_fn(read_df_fn(check["detail_sql"], params=check.get("params") or {}))
            details[code] = detail_df
            if population == 0:
                result = check.get("empty_population_status", "Chưa có dữ liệu")
                shown_issues = 0
            else:
                result = "Có lỗi" if issue_count else "Đạt"
                shown_issues = issue_count
            summary_rows.append({
                "Mã luật": code, "Lĩnh vực": check["domain"], "Nhóm kiểm tra": name,
                "Mức độ": check["severity"], "Yêu cầu kiểm tra": check["requirement"],
                "Nguồn đánh giá": check["source_table"], "Chiều DQS": ", ".join(check["dimensions"]),
                "Mẫu đánh giá": population, "Bản ghi / lượt vi phạm": shown_issues,
                "Đối tượng liên quan": entity_count, "Kết quả": result, "Lỗi kỹ thuật": "",
            })
        except Exception as exc:
            details[code] = pd.DataFrame()
            failures.append(f"{code} {name}: {type(exc).__name__}: {exc}")
            summary_rows.append({
                "Mã luật": code, "Lĩnh vực": check["domain"], "Nhóm kiểm tra": name,
                "Mức độ": check["severity"], "Yêu cầu kiểm tra": check["requirement"],
                "Nguồn đánh giá": check["source_table"], "Chiều DQS": ", ".join(check["dimensions"]),
                "Mẫu đánh giá": None, "Bản ghi / lượt vi phạm": None, "Đối tượng liên quan": None,
                "Kết quả": "Chưa kiểm tra được", "Lỗi kỹ thuật": f"{type(exc).__name__}: {exc}",
            })
    return pd.DataFrame(summary_rows), details, failures, entities


# Backward-compatible public names used by the EPDB Streamlit app.
# They delegate to the full implementations above; no evaluator logic is duplicated.
build_checks_150 = build_checks
execute_checks_150 = execute_checks
