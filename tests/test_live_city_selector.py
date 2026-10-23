"""CitySelector 的 live camera 分支：使用 4K 实时矩阵链路，不读旧 CameraState。"""
from __future__ import annotations

from pathlib import Path

import pytest

from san11agent.action_log import ActionLog
from san11agent.clock import FakeClock
from san11agent.execution import CitySelector, ExecutionConfig, ExecutionFailedError
from san11agent.input_backend import FakeInputBackend
from san11agent.map_camera import CameraMatrices
from san11agent.map_projection import TileCoord
from san11agent.memory import MutableMemoryReader
from san11agent.offsets import load_offsets
from san11agent.ui_layout import load_ui_layout
from san11agent.window import FakeGameWindow

FIXTURES = Path(__file__).resolve().parent / "fixtures"
OFFSETS_EXECUTION_TEST = FIXTURES / "offsets_execution_test.json"
UI_LAYOUT_TEST = FIXTURES / "ui_layout_test.json"
GAME_DATA_BASE = 0x1000
SELECTION_ADDR = GAME_DATA_BASE + 0x20
CITY_INDEX = 4

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
LIVE_CAMERA = CameraMatrices(
    view=VIEW_4K,
    projection=PROJECTION_4K,
    screen_width=3840,
    screen_height=2160,
)
FAST_CONFIG = ExecutionConfig(
    poll_timeout=0.5,
    poll_interval=0.1,
    max_retries=1,
    home_esc_presses=1,
    max_scroll_nudges=5,
    scroll_poll_timeout=0.5,
    scroll_poll_interval=0.1,
)


def _reader():
    reader = MutableMemoryReader({GAME_DATA_BASE: bytes(0x30)}, module_base=0x400000)
    reader.write_i32(SELECTION_ADDR, -1)
    return reader


def test_live_camera_selects_projected_city():
    reader = _reader()
    moved = []

    def on_move_mouse(x, y):
        moved.append((x, y))
        reader.write_i32(SELECTION_ADDR, CITY_INDEX)

    selector = CitySelector(
        reader=reader,
        offsets=load_offsets(OFFSETS_EXECUTION_TEST),
        ui_layout=load_ui_layout(UI_LAYOUT_TEST),
        input_backend=FakeInputBackend(on_move_mouse=on_move_mouse),
        window=FakeGameWindow(),
        clock=FakeClock(),
        action_log=ActionLog(FakeClock()),
        config=FAST_CONFIG,
        live_camera=lambda: LIVE_CAMERA,
    )

    selector.select_city(CITY_INDEX, TileCoord(129, 54))  # 平原

    assert moved[-1] == (3628, 183)  # project_map_point 的取整结果
    success = [e for e in selector._log.entries if e.intent == "select_city.hover" and e.result == "success"]
    assert success and success[-1].params["screen"] == (3628, 183)


def test_live_camera_rejects_off_screen_target():
    reader = _reader()
    selector = CitySelector(
        reader=reader,
        offsets=load_offsets(OFFSETS_EXECUTION_TEST),
        ui_layout=load_ui_layout(UI_LAYOUT_TEST),
        input_backend=FakeInputBackend(),
        window=FakeGameWindow(),
        clock=FakeClock(),
        action_log=ActionLog(FakeClock()),
        config=FAST_CONFIG,
        live_camera=lambda: LIVE_CAMERA,
    )

    with pytest.raises(ExecutionFailedError):
        selector.select_city(CITY_INDEX, TileCoord(0, 0))


def test_live_camera_reader_error_is_not_silent():
    reader = _reader()
    selector = CitySelector(
        reader=reader,
        offsets=load_offsets(OFFSETS_EXECUTION_TEST),
        ui_layout=load_ui_layout(UI_LAYOUT_TEST),
        input_backend=FakeInputBackend(),
        window=FakeGameWindow(),
        clock=FakeClock(),
        action_log=ActionLog(FakeClock()),
        config=FAST_CONFIG,
        live_camera=lambda: (_ for _ in ()).throw(RuntimeError("mapping missing")),
    )

    with pytest.raises(ExecutionFailedError):
        selector.select_city(CITY_INDEX, TileCoord(129, 54))
