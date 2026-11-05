"""Test suite for QGIS layout QPT templates (W20)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
LAYOUTS_DIR = REPO_ROOT / "qgis" / "layouts"

REQUIRED_LAYOUT_NAMES = ["lulc_1992", "lulc_2021", "urban_change", "township_change"]
REQUIRED_ITEM_IDS = [
    "map_main",
    "legend_main",
    "scale_main",
    "north_main",
    "title_text",
    "source_text",
]


@pytest.mark.parametrize("layout_name", REQUIRED_LAYOUT_NAMES)
def test_layout_qpt_file_exists_and_parses(layout_name: str):
    """Verifies that all 4 required layout templates exist and parse as XML."""
    qpt_path = LAYOUTS_DIR / f"{layout_name}.qpt"
    assert qpt_path.is_file(), f"Missing QPT template: {qpt_path}"

    tree = ET.parse(qpt_path)
    root = tree.getroot()
    assert root.tag == "Layout", f"Root tag must be <Layout>, got <{root.tag}>"
    assert root.get("name") == layout_name
    assert root.get("printResolution") == "300"


@pytest.mark.parametrize("layout_name", REQUIRED_LAYOUT_NAMES)
def test_layout_contains_required_items(layout_name: str):
    """Verifies that each layout strictly contains the 6 required stable item IDs."""
    qpt_path = LAYOUTS_DIR / f"{layout_name}.qpt"
    tree = ET.parse(qpt_path)
    root = tree.getroot()

    found_ids = set()
    for item in root.findall(".//LayoutItem"):
        item_id = item.get("id")
        if item_id:
            found_ids.add(item_id)

    for req_id in REQUIRED_ITEM_IDS:
        assert req_id in found_ids, f"Layout '{layout_name}' missing required item ID '{req_id}'"


@pytest.mark.parametrize("layout_name", REQUIRED_LAYOUT_NAMES)
def test_layout_page_size_a4_landscape(layout_name: str):
    """Verifies that layout page size is A4 landscape (297x210 mm)."""
    qpt_path = LAYOUTS_DIR / f"{layout_name}.qpt"
    tree = ET.parse(qpt_path)
    root = tree.getroot()

    page = root.find(".//PageCollection/LayoutItem/page")
    assert page is not None, "Page definition missing in Layout"
    assert page.get("pageSize") == "A4"
    assert page.get("orientation") == "landscape"
    assert page.get("width") == "297"
    assert page.get("height") == "210"
