"""ActionMenuExecutor（M3/M4 Execute 扩展）的离线测试：假后端 + 假内存 +
可注入时钟，完全不接触真实游戏。跟 tests/test_execution.py 共享同一套
fixture（offsets_execution_test.json / ui_layout_test.json），因为
menu_execution.py 复用了 execution.py 的 reveal_tile()。

这条链路本身无法自我验证（见 menu_execution.py 模块文档），所以这里的
断言重点不是"轮询确认生效"（没有这回事），而是：
- resolve_menu_path() 算出的 (top_index, sub_index) 是否正确；
- 点击坐标是否按 anchor + element.(x,y) + index*item_height 正确计算；
- 点击序列的先后顺序（归位 -> 平移进视野 -> 单击弹出菜单 -> 点顶层项 -> 点二级项）；
- 未知 ui_layout 元素 / 下标越界 / 未实现的更深步骤，分别抛出预期的错误。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from san11agent.action_log import ActionLog
from san11agent.clock import FakeClock
from san11agent.domestic_rules import load_domestic_rules
from san11agent.execution import ExecutionConfig
from san11agent.input_backend import VK_ESCAPE, FakeInputBackend
from san11agent.map_camera import CameraMatrices
from san11agent.legal_actions import (
    DiplomacyAction,
    RecruitTroopsAction,
    SecurityPatrolAction,
    StratagemAction,
    TrainTroopsAction,
)
from san11agent.map_projection import TileCoord
from san11agent.memory import MutableMemoryReader
from san11agent.menu_execution import (
    ActionMenuExecutor,
    FurtherStepsNotImplementedError,
    MenuExecutionError,
    resolve_menu_path,
)
from san11agent.offsets import load_offsets
from san11agent.ui_layout import UILayoutError, load_ui_layout
from san11agent.window import FakeGameWindow

FIXTURES = Path(__file__).resolve().parent / "fixtures"
OFFSETS_EXECUTION_TEST = FIXTURES / "offsets_execution_test.json"
UI_LAYOUT_TEST = FIXTURES / "ui_layout_test.json"
DOMESTIC_RULES_TEST = FIXTURES / "domestic_rules_test.json"

GAME_DATA_BASE = 0x1000
CAMERA_OFFSET_X_ADDR = GAME_DATA_BASE + 0x00
CAMERA_OFFSET_Y_ADDR = GAME_DATA_BASE + 0x04
CAMERA_ZOOM_ADDR = GAME_DATA_BASE + 0x08

CITY_INDEX = 7
GENERAL_INDEX = 42
FAST_CONFIG = ExecutionConfig(
    home_esc_presses=1,
    max_scroll_nudges=5,
    scroll_poll_timeout=0.5,
    scroll_poll_interval=0.1,
)

LIVE_CAMERA = CameraMatrices(
    view=[
        [0.7071069, -0.4999996, -0.4999999, 0.0],
        [0.0, 0.7071068, -0.7071066, 0.0],
        [-0.7071064, -0.5, -0.5000003, 0.0],
        [-719.1173, 2573.048, 3195.677, 1.0],
    ],
    projection=[
        [0.0020993, 0.0, 0.0, 0.0],
        [0.0, 0.0037321, 0.0, 0.0],
        [0.0, 0.0, 0.0010163, 0.001],
        [0.0, 0.0, -0.0162602, 0.0],
    ],
    screen_width=3840,
    screen_height=2160,
)


def _build_reader(*, offset_x=0, offset_y=0, zoom=100):
    reader = MutableMemoryReader({GAME_DATA_BASE: bytes(0x30)}, module_base=0x400000)
    reader.write_i32(CAMERA_OFFSET_X_ADDR, offset_x)
    reader.write_i32(CAMERA_OFFSET_Y_ADDR, offset_y)
    reader.write_i32(CAMERA_ZOOM_ADDR, zoom)
    return reader


@pytest.fixture()
def offsets():
    return load_offsets(OFFSETS_EXECUTION_TEST)


@pytest.fixture()
def ui_layout():
    return load_ui_layout(UI_LAYOUT_TEST)


@pytest.fixture()
def rules():
    return load_domestic_rules(DOMESTIC_RULES_TEST)


def _make_executor(reader, offsets, ui_layout, input_backend, action_log, *, live_camera=None):
    return ActionMenuExecutor(
        reader=reader,
        offsets=offsets,
        ui_layout=ui_layout,
        input_backend=input_backend,
        window=FakeGameWindow(),
        clock=FakeClock(),
        action_log=action_log,
        config=FAST_CONFIG,
        live_camera=live_camera,
    )


# -- resolve_menu_path() ---------------------------------------------------


def test_resolve_menu_path_for_recruit_troops(rules):
    action = RecruitTroopsAction(general_index=GENERAL_INDEX, city_index=CITY_INDEX)
    assert resolve_menu_path(action, rules) == (0, 2)  # 都市 > 徵兵


def test_resolve_menu_path_for_train_troops(rules):
    action = TrainTroopsAction(general_index=GENERAL_INDEX, city_index=CITY_INDEX)
    assert resolve_menu_path(action, rules) == (1, 0)  # 軍事 > 訓練


def test_resolve_menu_path_for_security_patrol(rules):
    action = SecurityPatrolAction(general_index=GENERAL_INDEX, city_index=CITY_INDEX)
    assert resolve_menu_path(action, rules) == (0, 4)  # 都市 > 巡察


def test_resolve_menu_path_for_diplomacy_uses_rules_sub_type_order(rules):
    # fixture 里 diplomacy_types 顺序是 alliance(0) -> ceasefire(1)
    action = DiplomacyAction(
        general_index=GENERAL_INDEX, city_index=CITY_INDEX,
        target_faction_index=3, diplomacy_type="ceasefire",
    )
    assert resolve_menu_path(action, rules) == (3, 1)  # 外交 > 第2项


def test_resolve_menu_path_for_stratagem(rules):
    action = StratagemAction(
        general_index=GENERAL_INDEX, city_index=CITY_INDEX,
        target_city_index=9, stratagem_type="sabotage",
    )
    assert resolve_menu_path(action, rules) == (4, 0)  # 計略 > 第1项


def test_resolve_menu_path_raises_for_unknown_sub_type(rules):
    action = DiplomacyAction(
        general_index=GENERAL_INDEX, city_index=CITY_INDEX,
        target_faction_index=3, diplomacy_type="not_a_real_sub_type",
    )
    with pytest.raises(MenuExecutionError):
        resolve_menu_path(action, rules)


# -- ActionMenuExecutor.open_city_menu() -----------------------------------


def test_open_city_menu_homes_reveals_and_clicks_once(offsets, ui_layout):
    reader = _build_reader()
    input_backend = FakeInputBackend()
    action_log = ActionLog(FakeClock())
    executor = _make_executor(reader, offsets, ui_layout, input_backend, action_log)

    point = executor.open_city_menu(CITY_INDEX, TileCoord(5, 5))

    esc_calls = [c for c in input_backend.calls if c.method == "key_press" and c.args == (VK_ESCAPE,)]
    assert len(esc_calls) == FAST_CONFIG.home_esc_presses

    click_calls = [c for c in input_backend.calls if c.method == "click"]
    assert len(click_calls) == 1  # 单击弹出菜单，不是双击

    assert [e.intent for e in action_log.entries] == ["menu.home", "menu.open_city"]
    # 等距菱形变换：视口中心(300,200)+(dx-dy,dx+dy)*half_tile(10,10)，
    # 地图坐标(5,5)、offset(0,0) 时 dx=dy=5 -> (300,300)，已经在视野内不需要滚动。
    assert point.x == 300
    assert point.y == 300


def test_open_city_menu_uses_live_camera(offsets, ui_layout):
    reader = _build_reader()
    input_backend = FakeInputBackend()
    action_log = ActionLog(FakeClock())
    executor = _make_executor(
        reader, offsets, ui_layout, input_backend, action_log,
        live_camera=lambda: LIVE_CAMERA,
    )

    point = executor.open_city_menu(4, TileCoord(129, 54))  # 平原

    assert point.x == 3628
    assert point.y == 183
    click_calls = [c for c in input_backend.calls if c.method == "click"]
    assert click_calls[-1].args == (3628, 183, "left")
    assert not [e for e in action_log.entries if e.intent == "pan_map"]


def test_open_city_menu_pans_map_when_target_outside_viewport(offsets, ui_layout):
    # viewport: x=100,y=50,width=400,height=300 → 右边缘悬停点 = (497, 200)
    # 等距变换下 target.y==offset_y（dy=0）时屏幕x/y一起随 offset_x 变化，
    # 见 test_execution.py 里同款场景的注释。
    RIGHT_EDGE = (497, 200)
    reader = _build_reader(offset_x=0)

    def on_move_mouse(x, y):
        if (x, y) == RIGHT_EDGE:
            reader.write_i32(CAMERA_OFFSET_X_ADDR, 25)

    input_backend = FakeInputBackend(on_move_mouse=on_move_mouse)
    action_log = ActionLog(FakeClock())
    executor = _make_executor(reader, offsets, ui_layout, input_backend, action_log)

    executor.open_city_menu(CITY_INDEX, TileCoord(30, 0))

    pan_entries = [e for e in action_log.entries if e.intent == "pan_map"]
    assert len(pan_entries) == 1
    assert pan_entries[0].result == "success"


def test_open_city_menu_raises_uilayout_error_when_viewport_unknown(offsets, ui_layout):
    import dataclasses

    unknown_viewport = dataclasses.replace(ui_layout.element("map_viewport"), unknown=True)
    broken_ui_layout = dataclasses.replace(
        ui_layout, elements={**ui_layout.elements, "map_viewport": unknown_viewport}
    )
    reader = _build_reader()
    input_backend = FakeInputBackend()
    action_log = ActionLog(FakeClock())
    executor = _make_executor(reader, offsets, broken_ui_layout, input_backend, action_log)

    with pytest.raises(UILayoutError):
        executor.open_city_menu(CITY_INDEX, TileCoord(5, 5))


# -- ActionMenuExecutor.execute_action() -----------------------------------


def test_execute_action_clicks_top_and_submenu_at_expected_coordinates(offsets, ui_layout, rules):
    reader = _build_reader()
    input_backend = FakeInputBackend()
    action_log = ActionLog(FakeClock())
    executor = _make_executor(reader, offsets, ui_layout, input_backend, action_log)
    action = TrainTroopsAction(general_index=GENERAL_INDEX, city_index=CITY_INDEX)

    executor.execute_action(action, TileCoord(5, 5), rules)

    click_calls = [c for c in input_backend.calls if c.method == "click"]
    # 1次单击弹出菜单 + 1次顶层菜单项 + 1次二级菜单项 = 3次
    assert len(click_calls) == 3

    # 等距菱形变换：TileCoord(5,5)、offset(0,0) -> (300, 300)，见上面
    # test_open_city_menu_homes_reveals_and_clicks_once 的注释。
    anchor_x, anchor_y = 300, 300
    # city_top_menu: x=10,y=-30,item_height=20；train_troops 是 (top=1, sub=0)
    top_x, top_y = anchor_x + 10, anchor_y - 30 + 1 * 20
    assert click_calls[1].args == (top_x, top_y, "left")
    # city_submenu: x=80,y=0,item_height=20，相对刚点的顶层项，sub_index=0
    sub_x, sub_y = top_x + 80, top_y + 0
    assert click_calls[2].args == (sub_x, sub_y, "left")

    intents = [e.intent for e in action_log.entries]
    assert intents == ["menu.home", "menu.open_city", "menu.click_item", "menu.click_item", "menu.execute_action"]


def test_execute_action_returns_normally_for_terminal_action_kinds(offsets, ui_layout, rules):
    reader = _build_reader()
    input_backend = FakeInputBackend()
    action_log = ActionLog(FakeClock())
    executor = _make_executor(reader, offsets, ui_layout, input_backend, action_log)

    for action in (
        RecruitTroopsAction(general_index=GENERAL_INDEX, city_index=CITY_INDEX),
        TrainTroopsAction(general_index=GENERAL_INDEX, city_index=CITY_INDEX),
        SecurityPatrolAction(general_index=GENERAL_INDEX, city_index=CITY_INDEX),
    ):
        executor.execute_action(action, TileCoord(5, 5), rules)  # 不应该抛异常


def test_execute_action_raises_further_steps_not_implemented_for_diplomacy(offsets, ui_layout, rules):
    reader = _build_reader()
    input_backend = FakeInputBackend()
    action_log = ActionLog(FakeClock())
    executor = _make_executor(reader, offsets, ui_layout, input_backend, action_log)
    action = DiplomacyAction(
        general_index=GENERAL_INDEX, city_index=CITY_INDEX,
        target_faction_index=3, diplomacy_type="alliance",
    )

    with pytest.raises(FurtherStepsNotImplementedError):
        executor.execute_action(action, TileCoord(5, 5), rules)

    # 两级菜单点击应该已经真实发生过，只是没能力继续往下走。
    click_calls = [c for c in input_backend.calls if c.method == "click"]
    assert len(click_calls) == 3
    assert any(e.intent == "menu.execute_action" for e in action_log.entries)


def test_click_menu_item_raises_when_index_out_of_expected_count(offsets, ui_layout):
    reader = _build_reader()
    input_backend = FakeInputBackend()
    action_log = ActionLog(FakeClock())
    executor = _make_executor(reader, offsets, ui_layout, input_backend, action_log)
    anchor = executor.open_city_menu(CITY_INDEX, TileCoord(5, 5))
    top_menu = ui_layout.element("city_top_menu")

    with pytest.raises(MenuExecutionError):
        # city_top_menu.item_count=6，下标99必然越界。
        executor._click_menu_item(anchor, top_menu, 99)


def test_click_menu_item_raises_when_item_height_missing(offsets, ui_layout):
    import dataclasses

    no_item_height = dataclasses.replace(ui_layout.element("city_top_menu"), item_height=None)
    broken_ui_layout = dataclasses.replace(
        ui_layout, elements={**ui_layout.elements, "city_top_menu": no_item_height}
    )
    reader = _build_reader()
    input_backend = FakeInputBackend()
    action_log = ActionLog(FakeClock())
    executor = _make_executor(reader, offsets, broken_ui_layout, input_backend, action_log)
    anchor = executor.open_city_menu(CITY_INDEX, TileCoord(5, 5))

    with pytest.raises(MenuExecutionError):
        executor._click_menu_item(anchor, broken_ui_layout.element("city_top_menu"), 0)
