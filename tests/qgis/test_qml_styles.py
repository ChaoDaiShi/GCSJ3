"""Test suite for QML styles contract and palette consistency."""

from __future__ import annotations

import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
STYLES_DIR = REPO_ROOT / "qgis" / "styles"
CONFIG_FILE = REPO_ROOT / "configs" / "project.toml"


def test_qml_files_exist_and_parse():
    """Verifies all expected QML files exist and parse as valid XML."""
    expected_qmls = [
        "lulc_5class.qml",
        "change_4class.qml",
        "townships.qml",
        "township_intensity.qml",
        "study_area.qml",
    ]
    for qml_name in expected_qmls:
        qml_path = STYLES_DIR / qml_name
        assert qml_path.is_file(), f"QML style missing: {qml_path}"
        tree = ET.parse(qml_path)
        root = tree.getroot()
        assert root.tag == "qgis", f"Invalid QGIS root tag in {qml_name}"


def test_lulc_5class_palette_matches_config():
    """Verifies 5-class LULC palette strictly matches configs/project.toml."""
    with open(CONFIG_FILE, "rb") as f:
        cfg = tomllib.load(f)

    expected_classes = {c["code"]: c for c in cfg["classes"]}
    assert len(expected_classes) == 5

    qml_path = STYLES_DIR / "lulc_5class.qml"
    tree = ET.parse(qml_path)
    root = tree.getroot()

    palette_entries = root.findall(".//colorPalette/paletteEntry")
    found_palette = {}
    for entry in palette_entries:
        val = int(entry.get("value"))
        color = entry.get("color").lower()
        alpha = int(entry.get("alpha"))
        label = entry.get("label")
        found_palette[val] = {"color": color, "alpha": alpha, "label": label}

    # Verify NoData (0) is fully transparent
    assert 0 in found_palette
    assert found_palette[0]["alpha"] == 0 or found_palette[0]["label"] == "NoData"

    # Verify classes 1 to 5
    for code, expected in expected_classes.items():
        assert code in found_palette, f"Class {code} missing from QML palette"
        assert found_palette[code]["label"] == expected["name"]
        assert found_palette[code]["color"] == expected["color"].lower()
        assert found_palette[code]["alpha"] == 255


def test_change_4class_palette():
    """Verifies 4-class change palette matches baseline colors."""
    qml_path = STYLES_DIR / "change_4class.qml"
    tree = ET.parse(qml_path)
    root = tree.getroot()

    palette_entries = root.findall(".//colorPalette/paletteEntry")
    found_palette = {int(e.get("value")): e for e in palette_entries}

    assert 0 in found_palette
    assert 1 in found_palette  # 持续建设
    assert 2 in found_palette  # 新增建设
    assert 3 in found_palette  # 减少建设
    assert 4 in found_palette  # 持续非建设

    assert found_palette[1].get("color").lower() == "#d95f02"
    assert found_palette[2].get("color").lower() == "#e41a1c"
    assert found_palette[3].get("color").lower() == "#377eb8"
