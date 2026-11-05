"""Test suite for township statistics join (W19 slice & UT11/UT12)."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
SCRIPTS_DIR = REPO_ROOT / "qgis" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from join_statistics import (
    EXPECTED_CSV_COLUMNS,
    join_statistics_data,
    load_and_verify_csv,
)


def create_sample_csv(csv_path: Path, rows: list[list[str]]):
    with open(csv_path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(EXPECTED_CSV_COLUMNS)
        for r in rows:
            writer.writerow(r)


def test_join_preserves_leading_zeros(tmp_path: Path):
    """Verifies that '001' and '1' are treated as two distinct string IDs."""
    csv_file = tmp_path / "stats.csv"
    # Row for '001' and '1'
    rows = [
        ["001", "大丰街道", "street", "2021", "20.0", "18.0", "0.9", "5.0", "12.0", "4.0", "8.0", "1.0", "7.0", "0.24", "1.2"],
        ["1", "新都街道", "street", "2021", "30.0", "28.0", "0.93", "8.0", "18.0", "7.0", "11.0", "1.0", "10.0", "0.34", "1.15"],
    ]
    create_sample_csv(csv_file, rows)

    township_feats = [
        {"unit_id": "001", "name": "大丰街道"},
        {"unit_id": "1", "name": "新都街道"},
    ]

    joined, report = join_statistics_data(township_feats, csv_file)
    assert report.success is True
    assert report.status == "PASSED"
    assert report.matched_count == 2
    assert len(joined) == 2

    feat_001 = next(f for f in joined if f["unit_id"] == "001")
    feat_1 = next(f for f in joined if f["unit_id"] == "1")

    assert feat_001["stat_name"] == "大丰街道"
    assert feat_001["stat_annual_intensity_pct"] == "1.2"
    assert feat_1["stat_name"] == "新都街道"
    assert feat_1["stat_annual_intensity_pct"] == "1.15"


def test_join_rejects_duplicate_csv_ids(tmp_path: Path):
    """Verifies that duplicate unit_id in CSV causes join failure."""
    csv_file = tmp_path / "stats_dup.csv"
    rows = [
        ["001", "大丰街道", "street", "2021", "20.0", "18.0", "0.9", "5.0", "12.0", "4.0", "8.0", "1.0", "7.0", "0.24", "1.2"],
        ["001", "大丰街道(重复)", "street", "2021", "20.0", "18.0", "0.9", "5.0", "12.0", "4.0", "8.0", "1.0", "7.0", "0.24", "1.2"],
    ]
    create_sample_csv(csv_file, rows)

    township_feats = [{"unit_id": "001", "name": "大丰街道"}]
    _, report = join_statistics_data(township_feats, csv_file)

    assert report.success is False
    assert report.status == "FAILED"
    assert "001" in report.duplicate_csv_ids
    assert any("duplicate" in err.lower() for err in report.errors)


def test_join_rejects_unmatched_ids(tmp_path: Path):
    """Verifies that missing or extra IDs trigger coverage failure."""
    csv_file = tmp_path / "stats_mismatch.csv"
    rows = [
        ["001", "大丰街道", "street", "2021", "20.0", "18.0", "0.9", "5.0", "12.0", "4.0", "8.0", "1.0", "7.0", "0.24", "1.2"],
        ["002", "三河街道", "street", "2021", "25.0", "22.0", "0.88", "6.0", "14.0", "5.0", "9.0", "1.0", "8.0", "0.27", "1.1"],
    ]
    create_sample_csv(csv_file, rows)

    # Township layer only has 001 and 003
    township_feats = [
        {"unit_id": "001", "name": "大丰街道"},
        {"unit_id": "003", "name": "斑竹园街道"},
    ]

    _, report = join_statistics_data(township_feats, csv_file)
    assert report.success is False
    assert report.status == "FAILED"
    assert "003" in report.unmatched_township_ids
    assert "002" in report.unmatched_csv_ids


def test_join_preserves_null_metrics_when_comparable_area_zero(tmp_path: Path):
    """Verifies UT12: when comparable area is zero, metrics remain NULL (None) instead of 0."""
    csv_file = tmp_path / "stats_zero_obs.csv"
    # Row with comparable_area_km2 = 0, so change metrics are left empty
    rows = [
        ["001", "特殊街镇", "town", "2021", "15.0", "0.0", "0.0", "", "", "", "", "", "", "", ""],
    ]
    create_sample_csv(csv_file, rows)

    township_feats = [{"unit_id": "001", "name": "特殊街镇"}]
    joined, report = join_statistics_data(township_feats, csv_file)

    assert report.success is True
    feat = joined[0]
    assert feat["stat_total_area_km2"] == "15.0"
    assert feat["stat_comparable_area_km2"] == "0.0"
    assert feat["stat_net_km2"] is None
    assert feat["stat_annual_intensity_pct"] is None
