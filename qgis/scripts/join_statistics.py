"""Township statistics join module (W19 slice).

Strictly joins township polygon geometries with township_change_1992_2021.csv
using string unit_id key, preserving leading zeros (e.g. distinguishing '001' from '1').
Rejects duplicates, missing matches, and many-to-many relationships.
Preserves NULL values for metrics when comparable observation is zero.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class JoinCheckItem:
    check_id: str
    status: str  # PASS / FAIL / WARNING
    description: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class JoinReport:
    success: bool
    status: str  # PASSED / FAILED / BLOCKED
    layer_name: str
    csv_path: str
    matched_count: int
    unmatched_township_ids: List[str] = field(default_factory=list)
    unmatched_csv_ids: List[str] = field(default_factory=list)
    duplicate_township_ids: List[str] = field(default_factory=list)
    duplicate_csv_ids: List[str] = field(default_factory=list)
    checks: List[JoinCheckItem] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


EXPECTED_CSV_COLUMNS = [
    "unit_id",
    "name",
    "unit_type",
    "boundary_year",
    "total_area_km2",
    "comparable_area_km2",
    "valid_ratio",
    "built_1992_km2",
    "built_2021_km2",
    "persistent_km2",
    "added_km2",
    "lost_km2",
    "net_km2",
    "annual_net_km2",
    "annual_intensity_pct",
]


def load_and_verify_csv(csv_path: Path | str) -> Tuple[List[str], Dict[str, Dict[str, Optional[str]]], List[str]]:
    """Loads CSV strictly as string unit_id and verifies header and uniqueness."""
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Statistics CSV not found: {csv_path}")

    duplicate_ids: List[str] = []
    seen_ids: Set[str] = set()
    records: Dict[str, Dict[str, Optional[str]]] = {}

    with open(csv_path, mode="r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            raise ValueError(f"Empty CSV file: {csv_path}")

        # Check required columns
        for col in EXPECTED_CSV_COLUMNS:
            if col not in header:
                raise ValueError(f"Missing required column '{col}' in {csv_path}")

        unit_id_idx = header.index("unit_id")

        for row_idx, row in enumerate(reader, start=2):
            if not row or all(c.strip() == "" for c in row):
                continue
            if len(row) != len(header):
                raise ValueError(
                    f"Row {row_idx} column count mismatch: expected {len(header)}, got {len(row)}"
                )

            unit_id = str(row[unit_id_idx]).strip()
            if not unit_id:
                raise ValueError(f"Empty unit_id in {csv_path} at row {row_idx}")

            if unit_id in seen_ids:
                duplicate_ids.append(unit_id)
            seen_ids.add(unit_id)

            row_data: Dict[str, Optional[str]] = {}
            for col_name, val in zip(header, row):
                val_str = val.strip()
                # Empty string represents NULL per contract
                row_data[col_name] = val_str if val_str != "" else None

            records[unit_id] = row_data

    return header, records, duplicate_ids


def verify_township_ids(township_ids: List[str]) -> Tuple[Set[str], List[str]]:
    """Verifies township unit_id uniqueness."""
    seen: Set[str] = set()
    duplicates: List[str] = []
    for tid in township_ids:
        tid_str = str(tid).strip()
        if not tid_str:
            raise ValueError("Found empty or null unit_id in township layer")
        if tid_str in seen:
            duplicates.append(tid_str)
        seen.add(tid_str)
    return seen, duplicates


def join_statistics_data(
    township_records: List[Dict[str, Any]],
    csv_path: Path | str,
    id_field: str = "unit_id",
) -> Tuple[List[Dict[str, Any]], JoinReport]:
    """Pure-Python / dataframe level join with strict validation.

    Preserves exact string matching (e.g. '001' != '1').
    """
    csv_path = Path(csv_path)
    header, csv_records, csv_dups = load_and_verify_csv(csv_path)

    township_ids = [str(r.get(id_field, "")).strip() for r in township_records]
    township_id_set, township_dups = verify_township_ids(township_ids)

    checks: List[JoinCheckItem] = []
    errors: List[str] = []

    # 1. Uniqueness check in CSV
    if csv_dups:
        errors.append(f"Duplicate unit_id in CSV: {csv_dups}")
        checks.append(JoinCheckItem(
            check_id="CHK_JOIN_CSV_UNIQUE",
            status="FAIL",
            description="CSV unit_id must be unique",
            details={"duplicates": csv_dups},
        ))
    else:
        checks.append(JoinCheckItem(
            check_id="CHK_JOIN_CSV_UNIQUE",
            status="PASS",
            description="CSV unit_id uniqueness verified",
        ))

    # 2. Uniqueness check in Layer
    if township_dups:
        errors.append(f"Duplicate unit_id in township layer: {township_dups}")
        checks.append(JoinCheckItem(
            check_id="CHK_JOIN_LAYER_UNIQUE",
            status="FAIL",
            description="Township layer unit_id must be unique",
            details={"duplicates": township_dups},
        ))
    else:
        checks.append(JoinCheckItem(
            check_id="CHK_JOIN_LAYER_UNIQUE",
            status="PASS",
            description="Township layer unit_id uniqueness verified",
        ))

    # 3. Match coverage check (1-to-1 match requirement)
    csv_id_set = set(csv_records.keys())
    unmatched_townships = sorted(list(township_id_set - csv_id_set))
    unmatched_csv = sorted(list(csv_id_set - township_id_set))

    if unmatched_townships or unmatched_csv:
        if unmatched_townships:
            errors.append(f"Townships missing in CSV: {unmatched_townships}")
        if unmatched_csv:
            errors.append(f"CSV records missing in Townships layer: {unmatched_csv}")
        checks.append(JoinCheckItem(
            check_id="CHK_JOIN_COVERAGE",
            status="FAIL",
            description="Strict 1-to-1 coverage between layer and statistics CSV required",
            details={
                "unmatched_townships": unmatched_townships,
                "unmatched_csv": unmatched_csv,
            },
        ))
    else:
        checks.append(JoinCheckItem(
            check_id="CHK_JOIN_COVERAGE",
            status="PASS",
            description="Complete 1-to-1 coverage verified",
            details={"matched_units": len(township_id_set)},
        ))

    # Perform join
    joined_features: List[Dict[str, Any]] = []
    for feat in township_records:
        feat_id = str(feat.get(id_field, "")).strip()
        joined = dict(feat)
        csv_data = csv_records.get(feat_id, {})
        for col in header:
            if col == id_field:
                continue
            joined[f"stat_{col}"] = csv_data.get(col, None)
        joined_features.append(joined)

    success = len(errors) == 0
    report = JoinReport(
        success=success,
        status="PASSED" if success else "FAILED",
        layer_name="townships",
        csv_path=str(csv_path),
        matched_count=len(township_id_set & csv_id_set),
        unmatched_township_ids=unmatched_townships,
        unmatched_csv_ids=unmatched_csv,
        duplicate_township_ids=township_dups,
        duplicate_csv_ids=csv_dups,
        checks=checks,
        errors=errors,
    )

    return joined_features, report


def apply_qgis_vector_join(township_layer: Any, csv_layer: Any, join_field: str = "unit_id") -> bool:
    """Applies QgsVectorLayerJoinInfo in PyQGIS environment if running inside QGIS.

    Ensures no duplicate join is created upon repeated execution.
    """
    try:
        from qgis.core import QgsVectorLayerJoinInfo  # type: ignore
    except ImportError:
        # Not in PyQGIS environment
        return False

    # Check if join already exists
    for existing_join in township_layer.vectorJoins():
        if existing_join.joinLayerId == csv_layer.id():
            # Remove old join to prevent duplicates
            township_layer.removeJoin(csv_layer.id())

    join_info = QgsVectorLayerJoinInfo()
    join_info.setJoinLayer(csv_layer)
    join_info.setJoinFieldName(join_field)
    join_info.setTargetFieldName(join_field)
    join_info.setPrefix("stat_")
    join_info.setUsingMemoryCache(True)
    join_info.setDynamicForm(True)

    township_layer.addJoin(join_info)
    return True
