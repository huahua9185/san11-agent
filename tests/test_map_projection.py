from __future__ import annotations

import pytest

from san11agent.execution_state import CameraState
from san11agent.map_projection import MapProjectionError, TileCoord, project_tile_to_client
from san11agent.ui_layout import UIElement, UILayoutError

VIEWPORT = UIElement(
    name="map_viewport",
    x=100, y=50, width=400, height=300,
    tile_width=20, tile_height=20,
    unknown=False,
)

UNKNOWN_VIEWPORT = UIElement(
    name="map_viewport", x=None, y=None, width=None, height=None,
    tile_width=None, tile_height=None, unknown=True, note="未测量",
)


def test_project_tile_to_client_origin_maps_to_viewport_corner():
    camera = CameraState(offset_x=0, offset_y=0, zoom_level=100)
    point = project_tile_to_client(TileCoord(0, 0), camera, VIEWPORT)
    assert (point.x, point.y) == (100, 50)


def test_project_tile_to_client_applies_camera_offset_and_tile_size():
    camera = CameraState(offset_x=0, offset_y=0, zoom_level=100)
    point = project_tile_to_client(TileCoord(2, 3), camera, VIEWPORT)
    assert (point.x, point.y) == (100 + 2 * 20, 50 + 3 * 20)


def test_project_tile_to_client_applies_zoom_scale():
    camera = CameraState(offset_x=0, offset_y=0, zoom_level=200)  # 2倍缩放
    point = project_tile_to_client(TileCoord(1, 0), camera, VIEWPORT)
    assert (point.x, point.y) == (100 + 1 * 20 * 2, 50)


def test_project_tile_to_client_returns_none_when_outside_viewport():
    camera = CameraState(offset_x=0, offset_y=0, zoom_level=100)
    # 视口只有 400x300，tile_width/height=20 -> 大约 20x15 格可见范围，
    # 格子 (100, 0) 离得远远超出这个范围。
    point = project_tile_to_client(TileCoord(100, 0), camera, VIEWPORT)
    assert point is None


def test_project_tile_to_client_raises_when_camera_unknown():
    camera = CameraState(offset_x=None, offset_y=0, zoom_level=100)
    with pytest.raises(MapProjectionError):
        project_tile_to_client(TileCoord(0, 0), camera, VIEWPORT)


def test_project_tile_to_client_raises_when_viewport_unknown():
    camera = CameraState(offset_x=0, offset_y=0, zoom_level=100)
    with pytest.raises(UILayoutError):
        project_tile_to_client(TileCoord(0, 0), camera, UNKNOWN_VIEWPORT)


def test_project_tile_to_client_raises_when_tile_size_missing():
    camera = CameraState(offset_x=0, offset_y=0, zoom_level=100)
    viewport_no_tile_size = UIElement(
        name="map_viewport", x=100, y=50, width=400, height=300,
        tile_width=None, tile_height=None, unknown=False,
    )
    with pytest.raises(MapProjectionError):
        project_tile_to_client(TileCoord(0, 0), camera, viewport_no_tile_size)
