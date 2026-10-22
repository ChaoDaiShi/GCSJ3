"""Micro-data fixture generators for unit and integration testing.

These fixtures implement the micro-data contracts specified in Section 4 of
docs/superpowers/plans/2026-10-14-first-release-parallel-plan.md.
All generated outputs are strictly confined to pytest temporary directories;
never write test fixture outputs to real outputs/ or data/ directories.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any


def create_scaling_fixture(out_dir: Path) -> dict[str, Any]:
    """Create scaling_fixture for preprocessing validation.

    - DN=10000 -> scaled reflectance = 10000 * 0.0000275 - 0.2 = 0.075
    - Fill DN=0 with QA_PIXEL bit 0 set (1)
    - Cloud pixel: DN=10000 with QA_PIXEL bit 3 set (8) -> excluded
    - Water pixel: DN=10000 with QA_PIXEL bit 7 set (128) -> retained
    - Clear valid pixel: DN=10000 with QA_PIXEL=0 -> valid, reflectance=0.075
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    pixels = [
        {"name": "clear_valid", "row": 0, "col": 0, "dn": 10000, "qa_pixel": 0, "expected_valid": True, "expected_sr": 0.075},
        {"name": "fill", "row": 0, "col": 1, "dn": 0, "qa_pixel": 1, "expected_valid": False, "expected_sr": None},
        {"name": "cloud", "row": 1, "col": 0, "dn": 10000, "qa_pixel": 8, "expected_valid": False, "expected_sr": None},
        {"name": "water", "row": 1, "col": 1, "dn": 10000, "qa_pixel": 128, "expected_valid": True, "expected_sr": 0.075},
    ]

    manifest = {
        "fixture_name": "scaling_fixture",
        "scale_factor": 0.0000275,
        "offset": -0.2,
        "expected_valid_sr": 0.075,
        "pixels": pixels,
    }

    manifest_path = out_dir / "scaling_fixture.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return {"manifest_path": manifest_path, "data": manifest}


def create_feature_fixture(out_dir: Path) -> dict[str, Any]:
    """Create feature_fixture for index calculations and invalid pixel rules.

    - Six-band base: [blue=0.1, green=0.2, red=0.3, nir=0.6, swir1=0.4, swir2=0.5]
    - Expected indices:
        NDVI  = (0.6 - 0.3) / (0.6 + 0.3) = 0.3 / 0.9 = 1/3
        NDBI  = (0.4 - 0.6) / (0.4 + 0.6) = -0.2 / 1.0 = -0.2
        MNDWI = (0.2 - 0.4) / (0.2 + 0.4) = -0.2 / 0.6 = -1/3
        BSI   = ((0.4 + 0.3) - (0.6 + 0.1)) / ((0.4 + 0.3) + (0.6 + 0.1)) = 0 / 1.4 = 0.0
    - Denominator zero pixels: when denominator is 0, entire feature vector is masked as NoData.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    valid_pixel = {
        "blue": 0.1,
        "green": 0.2,
        "red": 0.3,
        "nir": 0.6,
        "swir1": 0.4,
        "swir2": 0.5,
        "expected_ndvi": 1.0 / 3.0,
        "expected_ndbi": -0.2,
        "expected_mndwi": -1.0 / 3.0,
        "expected_bsi": 0.0,
        "is_valid": True,
    }

    zero_denom_ndvi = {
        "blue": 0.1,
        "green": 0.2,
        "red": 0.0,
        "nir": 0.0,
        "swir1": 0.4,
        "swir2": 0.5,
        "zero_denom_index": "ndvi",
        "is_valid": False,
    }

    zero_denom_ndbi = {
        "blue": 0.1,
        "green": 0.2,
        "red": 0.3,
        "nir": 0.0,
        "swir1": 0.0,
        "swir2": 0.5,
        "zero_denom_index": "ndbi",
        "is_valid": False,
    }

    manifest = {
        "fixture_name": "feature_fixture",
        "feature_order": ["blue", "green", "red", "nir", "swir1", "swir2", "ndvi", "ndbi", "mndwi", "bsi"],
        "valid_pixel": valid_pixel,
        "zero_denom_pixels": [zero_denom_ndvi, zero_denom_ndbi],
    }

    manifest_path = out_dir / "feature_fixture.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return {"manifest_path": manifest_path, "data": manifest}


def create_grouped_samples_fixture(out_dir: Path) -> dict[str, Any]:
    """Create grouped_samples_fixture with 5 classes, 8 groups per class, and unique group_ids."""
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "samples.csv"

    fieldnames = [
        "sample_id", "group_id", "year", "class_id",
        "row", "col", "x", "y",
        "blue", "green", "red", "nir", "swir1", "swir2",
        "ndvi", "ndbi", "mndwi", "bsi",
    ]

    rows: list[dict[str, Any]] = []
    groups_summary: dict[int, list[str]] = {}

    sample_counter = 0
    for class_id in range(1, 6):
        groups_summary[class_id] = []
        for g_idx in range(1, 9):
            group_id = f"cls_{class_id}_grp_{g_idx:02d}"
            groups_summary[class_id].append(group_id)

            # Generate 3 sample pixels per group
            for p_idx in range(3):
                sample_counter += 1
                sample_id = f"s_{sample_counter:04d}"
                row = (class_id - 1) * 8 + (g_idx - 1)
                col = p_idx
                x = 500000.0 + col * 30.0
                y = 3380000.0 - row * 30.0

                # Distinct feature signatures per class
                base_val = 0.1 * class_id
                blue = round(base_val, 4)
                green = round(base_val + 0.05, 4)
                red = round(base_val + 0.1, 4)
                nir = round(base_val + 0.3, 4)
                swir1 = round(base_val + 0.15, 4)
                swir2 = round(base_val + 0.08, 4)

                ndvi = round((nir - red) / (nir + red), 6)
                ndbi = round((swir1 - nir) / (swir1 + nir), 6)
                mndwi = round((green - swir1) / (green + swir1), 6)
                bsi = round(((swir1 + red) - (nir + blue)) / ((swir1 + red) + (nir + blue)), 6)

                row_dict = {
                    "sample_id": sample_id,
                    "group_id": group_id,
                    "year": 2021,
                    "class_id": class_id,
                    "row": row,
                    "col": col,
                    "x": x,
                    "y": y,
                    "blue": blue,
                    "green": green,
                    "red": red,
                    "nir": nir,
                    "swir1": swir1,
                    "swir2": swir2,
                    "ndvi": ndvi,
                    "ndbi": ndbi,
                    "mndwi": mndwi,
                    "bsi": bsi,
                }
                rows.append(row_dict)

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "fixture_name": "grouped_samples_fixture",
        "csv_path": str(csv_path),
        "total_samples": len(rows),
        "num_classes": 5,
        "groups_per_class": 8,
        "groups_summary": groups_summary,
    }

    manifest_path = out_dir / "grouped_samples_summary.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return {"csv_path": csv_path, "manifest_path": manifest_path, "data": manifest}


def create_metric_fixture(out_dir: Path) -> dict[str, Any]:
    """Create metric_fixture for evaluation and confusion matrix validation.

    Truth: [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    Pred:  [1, 2, 2, 2, 3, 3, 4, 4, 5, 1]
    Expected:
      - Total samples: 10
      - Correct predictions: 8 -> Overall Accuracy (OA) = 0.8
      - Full 5x5 confusion matrix (row=true, col=pred):
          [[1, 1, 0, 0, 0],
           [0, 2, 0, 0, 0],
           [0, 0, 2, 0, 0],
           [0, 0, 0, 2, 0],
           [1, 0, 0, 0, 1]]
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    y_true = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    y_pred = [1, 2, 2, 2, 3, 3, 4, 4, 5, 1]

    classes = [1, 2, 3, 4, 5]
    matrix = [[0] * 5 for _ in range(5)]
    for t, p in zip(y_true, y_pred):
        matrix[t - 1][p - 1] += 1

    correct = sum(matrix[i][i] for i in range(5))
    total = len(y_true)
    oa = correct / total

    # Per-class metrics
    class_metrics = []
    for i, c in enumerate(classes):
        support = sum(matrix[i])
        pred_count = sum(matrix[r][i] for r in range(5))
        tp = matrix[i][i]
        precision = tp / pred_count if pred_count > 0 else 0.0
        recall = tp / support if support > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        class_metrics.append({
            "class_id": c,
            "support": support,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        })

    confusion_csv = out_dir / "confusion_matrix.csv"
    with open(confusion_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["true_class", "pred_1", "pred_2", "pred_3", "pred_4", "pred_5"])
        for i, row in enumerate(matrix):
            writer.writerow([classes[i], *row])

    manifest = {
        "fixture_name": "metric_fixture",
        "y_true": y_true,
        "y_pred": y_pred,
        "overall_accuracy": oa,
        "confusion_matrix": matrix,
        "class_metrics": class_metrics,
        "confusion_csv": str(confusion_csv),
    }

    manifest_path = out_dir / "metric_fixture.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return {"manifest_path": manifest_path, "confusion_csv": confusion_csv, "data": manifest}


def create_change_fixture(out_dir: Path) -> dict[str, Any]:
    """Create change_fixture for 3x3 change matrix, township geometry, and area verification.

    Grid: 3x3, 30m cell size, EPSG:32648
    Bounds: [xmin=500010, ymin=3380010, xmax=500100, ymax=3380100]
    Transform: [500010, 30, 0, 3380100, 0, -30]

    1992:
      1 2 0
      1 2 2
      4 4 1
    2021:
      1 1 1
      2 2 1
      4 1 1
    Expected change:
      1 2 0
      3 4 2
      4 2 1

    Change codes:
      0 = NoData (at least one year is NoData 0)
      1 = Persistent built (1 -> 1)
      2 = Added built (non-built -> 1)
      3 = Lost built (1 -> non-built)
      4 = Persistent non-built (non-built -> non-built)

    Expected areas:
      - Valid cells: 8 cells * 0.0009 km2 = 0.0072 km2
      - Persistent built: 2 cells * 0.0009 = 0.0018 km2
      - Added built: 3 cells * 0.0009 = 0.0027 km2
      - Lost built: 1 cell * 0.0009 = 0.0009 km2
      - Persistent non-built: 2 cells * 0.0009 = 0.0018 km2
      - Net built: 0.0027 - 0.0009 = 0.0018 km2

    Two test townships (divided at x=500055):
      - Township 1 (West): [500010, 3380010, 500055, 3380100] (area 4050 m2 = 0.00405 km2)
      - Township 2 (East): [500055, 3380010, 500100, 3380100] (area 4050 m2 = 0.00405 km2)
      - Mid column (col 1, x: 500040..500070) is split evenly (0.5 pixel to T1, 0.5 to T2).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    grid_1992 = [
        [1, 2, 0],
        [1, 2, 2],
        [4, 4, 1],
    ]
    grid_2021 = [
        [1, 1, 1],
        [2, 2, 1],
        [4, 1, 1],
    ]
    expected_change = [
        [1, 2, 0],
        [3, 4, 2],
        [4, 2, 1],
    ]

    cell_area_km2 = 0.0009  # 30m * 30m = 900 m2 = 0.0009 km2

    # District totals
    valid_cells = 8
    total_valid_km2 = round(valid_cells * cell_area_km2, 6)  # 0.0072
    persistent_km2 = round(2 * cell_area_km2, 6)             # 0.0018
    added_km2 = round(3 * cell_area_km2, 6)                  # 0.0027
    lost_km2 = round(1 * cell_area_km2, 6)                   # 0.0009
    net_km2 = round(added_km2 - lost_km2, 6)                 # 0.0018
    persistent_nonbuilt_km2 = round(2 * cell_area_km2, 6)    # 0.0018

    # Township calculations:
    # Col 0 (x: 500010..500040) -> 100% in Township 1
    # Col 1 (x: 500040..500070) -> 50% in T1, 50% in T2
    # Col 2 (x: 500070..500100) -> 100% in Township 2
    #
    # Change grid cells:
    # row 0: col0: 1 (T1), col1: 2 (0.5 T1, 0.5 T2), col2: 0 (NoData)
    # row 1: col0: 3 (T1), col1: 4 (0.5 T1, 0.5 T2), col2: 2 (T2)
    # row 2: col0: 4 (T1), col1: 2 (0.5 T1, 0.5 T2), col2: 1 (T2)
    #
    # T1 effective weights:
    # persistent (1): (0,0)->1.0, (2,2)->0 => 1.0 cell = 0.0009 km2
    # added (2): (0,1)->0.5, (1,2)->0, (2,1)->0.5 => 1.0 cell = 0.0009 km2
    # lost (3): (1,0)->1.0 => 1.0 cell = 0.0009 km2
    # net T1: 0.0009 - 0.0009 = 0.0 km2
    #
    # T2 effective weights:
    # persistent (1): (2,2)->1.0 => 1.0 cell = 0.0009 km2
    # added (2): (0,1)->0.5, (1,2)->1.0, (2,1)->0.5 => 2.0 cells = 0.0018 km2
    # lost (3): 0 => 0.0 km2
    # net T2: 0.0018 - 0.0 = 0.0018 km2
    #
    # T1 + T2 persistent: 0.0009 + 0.0009 = 0.0018 (matches District!)
    # T1 + T2 added: 0.0009 + 0.0018 = 0.0027 (matches District!)
    # T1 + T2 lost: 0.0009 + 0.0 = 0.0009 (matches District!)
    # T1 + T2 net: 0.0 + 0.0018 = 0.0018 (matches District!)

    manifest = {
        "fixture_name": "change_fixture",
        "crs": "EPSG:32648",
        "bounds": [500010, 3380010, 500100, 3380100],
        "resolution": [30, 30],
        "width": 3,
        "height": 3,
        "transform": [500010, 30, 0, 3380100, 0, -30],
        "grid_1992": grid_1992,
        "grid_2021": grid_2021,
        "expected_change": expected_change,
        "district_expected": {
            "comparable_area_km2": total_valid_km2,
            "persistent_km2": persistent_km2,
            "added_km2": added_km2,
            "lost_km2": lost_km2,
            "net_km2": net_km2,
            "persistent_nonbuilt_km2": persistent_nonbuilt_km2,
        },
        "townships": [
            {
                "unit_id": "T01",
                "name": "西街镇",
                "unit_type": "town",
                "total_area_km2": 0.00405,
                "comparable_area_km2": 4.5 * cell_area_km2,
                "persistent_km2": 1.0 * cell_area_km2,
                "added_km2": 1.0 * cell_area_km2,
                "lost_km2": 1.0 * cell_area_km2,
                "net_km2": 0.0,
            },
            {
                "unit_id": "T02",
                "name": "东街道",
                "unit_type": "street",
                "total_area_km2": 0.00405,
                "comparable_area_km2": 3.5 * cell_area_km2,
                "persistent_km2": 1.0 * cell_area_km2,
                "added_km2": 2.0 * cell_area_km2,
                "lost_km2": 0.0,
                "net_km2": 2.0 * cell_area_km2,
            },
        ],
    }

    manifest_path = out_dir / "change_fixture.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return {"manifest_path": manifest_path, "data": manifest}
