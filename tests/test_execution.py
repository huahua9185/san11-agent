"""CitySelector（M3 执行链路）的离线测试：假后端 + 假内存 + 可注入时钟，
完全不接触真实游戏、不真的等待。

覆盖的场景对应验收标准的几个关键分支：
- 目标格子已在视野内，点击一次就确认选中成功。
- 目标格子在视野外，滚动地图直到进入视野后再点击成功。
- 点击没有在轮询窗口内生效：归位重试，重试后成功 / 重试耗尽后失败。
- 配置缺口（camera 字段 unknown / ui_layout 元素 unknown）时的报错行为，
  以及这两类错误在"是否会被重试"上的区别（见 execution.py 模块顶部说明）。
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from san11agent.action_log import ActionLog
from san11agent.clock import FakeClock
from san11agent.execution import CitySelector, ExecutionConfig, ExecutionFailedError
from san11agent.input_backend import VK_ESCAPE, FakeInputBackend
from san11agent.map_projection import MapProjectionError, TileCoord
from san11agent.memory import MutableMemoryReader
from san11agent.offsets import load_offsets
from san11agent.ui_layout import UILayoutError, load_ui_layout
from san11agent.window import FakeGameWindow

FIXTURES = Path(__file__).resolve().parent / "fixtures"
OFFSETS_EXECUTION_TEST = FIXTURES / "offsets_execution_test.json"
UI_LAYOUT_TEST = FIXTURES / "ui_layout_test.json"

GAME_DATA_BASE = 0x1000
CAMERA_OFFSET_X_ADDR = GAME_DATA_BASE + 0x00
CAMERA_OFFSET_Y_ADDR = GAME_DATA_BASE + 0x04
CAMERA_ZOOM_ADDR = GAME_DATA_BASE + 0x08
SELECTION_ADDR = GAME_DATA_BASE + 0x20

CITY_INDEX = 7
FAST_CONFIG = ExecutionConfig(
    poll_timeout=0.5,
    poll_interval=0.1,
    max_retries=2,
    home_esc_presses=1,
    max_scroll_nudges=5,
    scroll_poll_timeout=0.5,
    scroll_poll_interval=0.1,
)


def _build_reader(*, offset_x=0, offset_y=0, zoom=100, selected=-1):
    reader = MutableMemoryReader({GAME_DATA_BASE: bytes(0x30)}, module_base=0x400000)
    reader.write_i32(CAMERA_OFFSET_X_ADDR, offset_x)
    reader.write_i32(CAMERA_OFFSET_Y_ADDR, offset_y)
    reader.write_i32(CAMERA_ZOOM_ADDR, zoom)
    reader.write_i32(SELECTION_ADDR, selected)
    return reader


def _esc_press_count(input_backend: FakeInputBackend) -> int:
    return sum(1 for c in input_backend.calls if c.method == "key_press" and c.args == (VK_ESCAPE,))


@pytest.fixture()
def offsets():
    return load_offsets(OFFSETS_EXECUTION_TEST)


@pytest.fixture()
def ui_layout():
    return load_ui_layout(UI_LAYOUT_TEST)


def test_select_city_succeeds_when_target_already_in_view(offsets, ui_layout):
    reader = _build_reader()

    def on_click(x, y, button):
        reader.write_i32(SELECTION_ADDR, CITY_INDEX)

    input_backend = FakeInputBackend(on_click=on_click)
    clock = FakeClock()
    action_log = ActionLog(clock)
    selector = CitySelector(
        reader=reader, offsets=offsets, ui_layout=ui_layout,
        input_backend=input_backend, window=FakeGameWindow(), clock=clock,
        action_log=action_log, config=FAST_CONFIG,
    )

    selector.select_city(CITY_INDEX, TileCoord(5, 5))

    click_calls = [c for c in input_backend.calls if c.method == "click"]
    assert len(click_calls) == 1
    assert _esc_press_count(input_backend) == FAST_CONFIG.home_esc_presses  # 只归位了一次

    results = [e.result for e in action_log.entries]
    assert "success" in results
    success_entry = next(e for e in action_log.entries if e.intent == "select_city.click")
    assert success_entry.result == "success"
    assert success_entry.state_diff == {"selected_city_index": (-1, CITY_INDEX)}


def test_select_city_pans_map_when_target_outside_viewport(offsets, ui_layout):
    # viewport: x=100,y=50,width=400,height=300 → 右边缘悬停点 = (100+400-1-2, 50+150) = (497, 200)
    RIGHT_EDGE = (497, 200)
    reader = _build_reader(offset_x=0)  # 目标格子 (30,5) 一开始在视野外

    def on_move_mouse(x, y):
        if (x, y) == RIGHT_EDGE:
            reader.write_i32(CAMERA_OFFSET_X_ADDR, 15)  # 模拟鼠标停在右边缘触发地图向右平移

    def on_click(x, y, button):
        reader.write_i32(SELECTION_ADDR, CITY_INDEX)

    input_backend = FakeInputBackend(on_click=on_click, on_move_mouse=on_move_mouse)
    clock = FakeClock()
    action_log = ActionLog(clock)
    selector = CitySelector(
        reader=reader, offsets=offsets, ui_layout=ui_layout,
        input_backend=input_backend, window=FakeGameWindow(), clock=clock,
        action_log=action_log, config=FAST_CONFIG,
    )

    selector.select_city(CITY_INDEX, TileCoord(30, 5))

    pan_entries = [e for e in action_log.entries if e.intent == "pan_map"]
    assert len(pan_entries) == 1
    assert pan_entries[0].result == "success"
    assert pan_entries[0].params["direction"] == "right"
    assert pan_entries[0].params["edge_screen"] == RIGHT_EDGE

    click_entries = [e for e in action_log.entries if e.intent == "select_city.click"]
    assert click_entries[-1].result == "success"


def test_select_city_retries_after_homing_when_click_does_not_register(offsets, ui_layout):
    reader = _build_reader()
    counter = {"n": 0}

    def on_click(x, y, button):
        counter["n"] += 1
        if counter["n"] >= 2:  # 第一次点击"没生效"，第二次（归位重试后）才生效
            reader.write_i32(SELECTION_ADDR, CITY_INDEX)

    input_backend = FakeInputBackend(on_click=on_click)
    clock = FakeClock()
    action_log = ActionLog(clock)
    selector = CitySelector(
        reader=reader, offsets=offsets, ui_layout=ui_layout,
        input_backend=input_backend, window=FakeGameWindow(), clock=clock,
        action_log=action_log, config=FAST_CONFIG,
    )

    selector.select_city(CITY_INDEX, TileCoord(5, 5))

    assert counter["n"] == 2
    assert _esc_press_count(input_backend) == FAST_CONFIG.home_esc_presses * 2  # 归位了两次
    failed_entries = [e for e in action_log.entries if e.intent == "select_city.attempt_failed"]
    assert len(failed_entries) == 1
    success_entries = [e for e in action_log.entries if e.result == "success"]
    assert len(success_entries) >= 1


def test_select_city_raises_after_retries_exhausted(offsets, ui_layout):
    reader = _build_reader()  # on_click 永远不设置 selection，模拟点击完全没反应

    input_backend = FakeInputBackend()
    clock = FakeClock()
    action_log = ActionLog(clock)
    selector = CitySelector(
        reader=reader, offsets=offsets, ui_layout=ui_layout,
        input_backend=input_backend, window=FakeGameWindow(), clock=clock,
        action_log=action_log, config=FAST_CONFIG,
    )

    with pytest.raises(ExecutionFailedError):
        selector.select_city(CITY_INDEX, TileCoord(5, 5))

    # 首次尝试 + max_retries 次重试，每次都先归位
    expected_attempts = FAST_CONFIG.max_retries + 1
    assert _esc_press_count(input_backend) == FAST_CONFIG.home_esc_presses * expected_attempts
    failed_entries = [e for e in action_log.entries if e.intent == "select_city.attempt_failed"]
    assert len(failed_entries) == expected_attempts


def test_select_city_retries_but_ultimately_fails_when_camera_fields_unknown(offsets, ui_layout):
    # camera 字段是配置缺失（内存字段没定位到），不是"这次点击碰巧没生效"，
    # 但目前的实现把它和滚动超时归入同一个可重试分支——这是当前设计的已知
    # 取舍（见 execution.py 模块顶部说明和提交报告），这里测的是"现状行为"，
    # 不代表这是理想设计。
    unknown_camera_struct = dataclasses.replace(
        offsets.struct("camera"),
        fields={
            name: dataclasses.replace(spec, unknown=True, offset=None)
            for name, spec in offsets.struct("camera").fields.items()
        },
    )
    offsets_with_unknown_camera = dataclasses.replace(
        offsets, structs={**offsets.structs, "camera": unknown_camera_struct}
    )
    reader = _build_reader()
    input_backend = FakeInputBackend()
    clock = FakeClock()
    action_log = ActionLog(clock)
    selector = CitySelector(
        reader=reader, offsets=offsets_with_unknown_camera, ui_layout=ui_layout,
        input_backend=input_backend, window=FakeGameWindow(), clock=clock,
        action_log=action_log, config=FAST_CONFIG,
    )

    with pytest.raises(ExecutionFailedError):
        selector.select_city(CITY_INDEX, TileCoord(5, 5))

    failed_entries = [e for e in action_log.entries if e.intent == "select_city.attempt_failed"]
    assert all(isinstance(e.detail, str) and "camera" in e.detail for e in failed_entries)


def test_select_city_raises_uilayout_error_immediately_without_retry_when_viewport_unknown(offsets):
    unknown_ui_layout = load_ui_layout(FIXTURES / "ui_layout_test.json")
    unknown_viewport = dataclasses.replace(unknown_ui_layout.element("map_viewport"), unknown=True)
    unknown_ui_layout = dataclasses.replace(
        unknown_ui_layout, elements={**unknown_ui_layout.elements, "map_viewport": unknown_viewport}
    )
    reader = _build_reader()
    input_backend = FakeInputBackend()
    clock = FakeClock()
    action_log = ActionLog(clock)
    selector = CitySelector(
        reader=reader, offsets=offsets, ui_layout=unknown_ui_layout,
        input_backend=input_backend, window=FakeGameWindow(), clock=clock,
        action_log=action_log, config=FAST_CONFIG,
    )

    with pytest.raises(UILayoutError):
        selector.select_city(CITY_INDEX, TileCoord(5, 5))

    # 配置缺失不是偶发失败，不应该被重试——只归位了一次（第一次尝试之前）。
    assert _esc_press_count(input_backend) == FAST_CONFIG.home_esc_presses
    assert not any(e.intent == "select_city.attempt_failed" for e in action_log.entries)


def test_select_city_gives_up_panning_when_camera_never_changes(offsets, ui_layout):
    reader = _build_reader()  # on_move_mouse 什么都不做，摄像机永远不变

    input_backend = FakeInputBackend()
    clock = FakeClock()
    action_log = ActionLog(clock)
    selector = CitySelector(
        reader=reader, offsets=offsets, ui_layout=ui_layout,
        input_backend=input_backend, window=FakeGameWindow(), clock=clock,
        action_log=action_log, config=FAST_CONFIG,
    )

    with pytest.raises(ExecutionFailedError):
        selector.select_city(CITY_INDEX, TileCoord(30, 5))  # 一开始就在视野外

    pan_timeouts = [e for e in action_log.entries if e.intent == "pan_map" and e.result == "timeout"]
    assert len(pan_timeouts) > 0
