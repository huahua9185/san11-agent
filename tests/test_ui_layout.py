from __future__ import annotations

from pathlib import Path

import pytest

from san11agent.ui_layout import UILayoutError, load_ui_layout

FIXTURES = Path(__file__).resolve().parent / "fixtures"
UI_LAYOUT_TEST = FIXTURES / "ui_layout_test.json"
UI_LAYOUT_PROD = Path(__file__).resolve().parents[1] / "ui_layout" / "pk_1.1_cn.json"


def test_load_ui_layout_parses_known_elements():
    config = load_ui_layout(UI_LAYOUT_TEST)
    assert config.label == "test_fixture"
    assert config.verified is True
    assert config.assumed_client_resolution == (800, 600)

    viewport = config.element("map_viewport")
    assert (viewport.x, viewport.y, viewport.width, viewport.height) == (100, 50, 400, 300)
    assert (viewport.tile_width, viewport.tile_height) == (20, 20)
    assert viewport.unknown is False

    button = config.element("end_turn_button")
    assert (button.x, button.y) == (750, 20)


def test_load_ui_layout_parses_menu_element_fields():
    config = load_ui_layout(UI_LAYOUT_TEST)
    top_menu = config.element("city_top_menu")
    assert (top_menu.x, top_menu.y) == (10, -30)
    assert top_menu.item_height == 20
    assert top_menu.item_count == 6
    assert top_menu.unknown is False
    # 普通元素不声明 item_height/item_count 时应该保持 None，不是 0 或别的默认值。
    viewport = config.element("map_viewport")
    assert viewport.item_height is None
    assert viewport.item_count is None


def test_element_require_known_returns_self_when_known():
    config = load_ui_layout(UI_LAYOUT_TEST)
    button = config.element("end_turn_button")
    assert button.require_known() is button


def test_element_require_known_raises_when_unknown():
    config = load_ui_layout(UI_LAYOUT_TEST)
    button = config.element("unmeasured_button")
    with pytest.raises(UILayoutError):
        button.require_known()


def test_element_lookup_raises_for_missing_name():
    config = load_ui_layout(UI_LAYOUT_TEST)
    with pytest.raises(UILayoutError):
        config.element("does_not_exist")


def test_production_ui_layout_loads_with_measured_elements():
    # 2026-08-19 用 GetCursorPos+ScreenToClient 现场测量完成，三个元素均已知，
    # 见 ui_layout/pk_1.1_cn.json 各元素 note 和 docs/execution_research.md 7.10节。
    config = load_ui_layout(UI_LAYOUT_PROD)
    assert config.verified is True
    assert config.assumed_client_resolution == (2560, 1600)

    viewport = config.element("map_viewport")
    assert viewport.unknown is False
    assert (viewport.x, viewport.y, viewport.width, viewport.height) == (471, 12, 1772, 1542)
    assert (viewport.tile_width, viewport.tile_height) == (184, 135)
    assert viewport.require_known() is viewport

    top_menu = config.element("city_top_menu")
    assert top_menu.unknown is False
    assert (top_menu.x, top_menu.y, top_menu.item_height, top_menu.item_count) == (-143, 98, 34, 6)

    submenu = config.element("city_submenu")
    assert submenu.unknown is False
    assert (submenu.x, submenu.y, submenu.item_height) == (80, 12, 30)
