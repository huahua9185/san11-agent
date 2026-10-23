"""map_camera 的回归测试：4K 四城验证数据 + D3D9 投影约定。"""
from __future__ import annotations

import pytest

from san11agent.map_camera import (
    CameraMatrices,
    DEFAULT_MAP_CALIBRATION,
    MapCalibration,
    project_map_point,
    project_world,
)

VIEW_4K = [
    [0.7071069, -0.4999996, -0.4999999, 0.0],
    [0.0, 0.7071068, -0.7071066, 0.0],
    [-0.7071064, -0.5, -0.5000003, 0.0],
    [-719.1173, 2573.048, 3195.677, 1.0],
]
PROJECTION_4K = [
    [0.0020993, 0.0, 0.0, 0.0],
    [0.0, 0.0037321, 0.0, 0.0],
    [0.0, 0.0, 0.0010163, 0.001],
    [0.0, 0.0, -0.0162602, 0.0],
]
CAMERA_4K = CameraMatrices(
    view=VIEW_4K,
    projection=PROJECTION_4K,
    screen_width=3840,
    screen_height=2160,
)

# map 坐标与 4K 实测屏幕坐标（probe9，静止相机）。
CITY_SCREEN_POINTS = [
    ("平原", 129, 54, 3623, 179),
    ("小沛", 136, 77, 2825, 2110),
    ("濮陽", 120, 71, 1785, 563),
    ("陳留", 108, 79, 296, 357),
]


def test_map_to_world_known_values():
    world = DEFAULT_MAP_CALIBRATION.map_to_world(120, 71)
    assert world[0] == pytest.approx(
        19.886052141042683 * 120 + 0.2369451393790314 * 71 + 565.1875792680657
    )
    assert world[1] == 0.0
    assert world[2] == pytest.approx(
        0.27223148156167554 * 120 + 20.20238763173404 * 71 + 520.4224581284507
    )


def test_four_city_projection_error_below_20_pixels():
    for name, map_x, map_y, actual_x, actual_y in CITY_SCREEN_POINTS:
        predicted_x, predicted_y = project_map_point(map_x, map_y, CAMERA_4K)
        assert abs(predicted_x - actual_x) < 20, name
        assert abs(predicted_y - actual_y) < 20, name


def test_project_map_point_matches_project_world():
    world = DEFAULT_MAP_CALIBRATION.map_to_world(129, 54)
    assert project_map_point(129, 54, CAMERA_4K) == pytest.approx(
        project_world(world, CAMERA_4K)
    )


def test_project_world_accepts_custom_calibration():
    calibration = MapCalibration(1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    # identity-like view/projection: screen center for world origin
    camera = CameraMatrices(
        view=[[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]],
        projection=[[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]],
        screen_width=100,
        screen_height=50,
    )
    assert project_world(calibration.map_to_world(0, 0), camera) == pytest.approx((50.0, 25.0))


def test_invalid_matrix_shape_raises():
    with pytest.raises(ValueError, match="4x4"):
        project_world((0.0, 0.0, 0.0), CameraMatrices(
            view=[[1.0, 0.0, 0.0, 0.0]],
            projection=PROJECTION_4K,
            screen_width=3840,
            screen_height=2160,
        ))


def test_degenerate_projection_raises():
    zero_projection = [[0.0] * 4 for _ in range(4)]
    with pytest.raises(ValueError, match="w is zero"):
        project_world((0.0, 0.0, 0.0), CameraMatrices(
            view=VIEW_4K,
            projection=zero_projection,
            screen_width=3840,
            screen_height=2160,
        ))
