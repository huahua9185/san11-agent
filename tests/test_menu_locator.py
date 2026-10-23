"""截图检测结果的纯几何契约测试。"""
from __future__ import annotations

import pytest

from san11agent.menu_locator import MenuGeometry
from san11agent.map_projection import ScreenPoint


def test_item_center_for_top_menu():
    geometry = MenuGeometry(left=1165, top=407, right=1235, bottom=632, item_height=34)
    assert geometry.item_count == 6
    assert geometry.item_center(0) == ScreenPoint(1200, 424)
    assert geometry.item_center(1) == ScreenPoint(1200, 458)


def test_item_center_for_seven_item_submenu():
    geometry = MenuGeometry(left=1250, top=407, right=1365, bottom=644, item_height=34, count=7)
    assert geometry.item_count == 7
    assert geometry.item_center(5) == ScreenPoint(1307, 594)


def test_out_of_range_raises():
    geometry = MenuGeometry(left=0, top=0, right=100, bottom=100, item_height=20)
    with pytest.raises(IndexError):
        geometry.item_center(5)


def test_invalid_geometry_raises():
    with pytest.raises(ValueError, match="positive"):
        MenuGeometry(left=10, top=10, right=10, bottom=100, item_height=20)
    with pytest.raises(ValueError, match="item_height"):
        MenuGeometry(left=0, top=0, right=100, bottom=100, item_height=0)
