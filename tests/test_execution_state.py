from __future__ import annotations

from pathlib import Path

import pytest

from san11agent.execution_state import parse_camera_state, parse_selection_state
from san11agent.memory import MutableMemoryReader
from san11agent.offsets import load_offsets
from san11agent.perception import resolve_anchor

FIXTURES = Path(__file__).resolve().parent / "fixtures"
OFFSETS_EXECUTION_TEST = FIXTURES / "offsets_execution_test.json"

GAME_DATA_BASE = 0x1000


@pytest.fixture()
def offsets():
    return load_offsets(OFFSETS_EXECUTION_TEST)


@pytest.fixture()
def reader():
    return MutableMemoryReader({GAME_DATA_BASE: bytes(0x30)}, module_base=0x400000)


def test_resolve_anchor_matches_fixture_address(reader, offsets):
    assert resolve_anchor(reader, offsets) == GAME_DATA_BASE


def test_parse_camera_state_reads_known_fields(reader, offsets):
    reader.write_i32(GAME_DATA_BASE + 0x00, 12)
    reader.write_i32(GAME_DATA_BASE + 0x04, -7)
    reader.write_i32(GAME_DATA_BASE + 0x08, 150)

    camera = parse_camera_state(reader, offsets, GAME_DATA_BASE)
    assert camera.offset_x == 12
    assert camera.offset_y == -7
    assert camera.zoom_level == 150


def test_parse_selection_state_reads_known_field(reader, offsets):
    reader.write_i32(GAME_DATA_BASE + 0x20, 5)
    selection = parse_selection_state(reader, offsets, GAME_DATA_BASE)
    assert selection.selected_city_index == 5


def test_camera_state_equality_reflects_field_values(reader, offsets):
    reader.write_i32(GAME_DATA_BASE + 0x00, 1)
    reader.write_i32(GAME_DATA_BASE + 0x04, 2)
    reader.write_i32(GAME_DATA_BASE + 0x08, 100)
    a = parse_camera_state(reader, offsets, GAME_DATA_BASE)
    b = parse_camera_state(reader, offsets, GAME_DATA_BASE)
    assert a == b

    reader.write_i32(GAME_DATA_BASE + 0x00, 3)
    c = parse_camera_state(reader, offsets, GAME_DATA_BASE)
    assert a != c


def test_parse_camera_state_returns_none_for_unknown_fields():
    # 用生产 offsets 文件验证：camera 字段目前确实全部是 unknown，
    # 解析结果应该是全 None，而不是报错或读出垃圾值——跟 M1/M2 的既有行为一致。
    from san11agent.offsets import load_offsets as load_prod_offsets

    prod_offsets = load_prod_offsets(Path(__file__).resolve().parents[1] / "offsets" / "pk_1.1_cn.json")
    reader = MutableMemoryReader({0x0: bytes(4)}, module_base=0x400000)
    camera = parse_camera_state(reader, prod_offsets, game_data_base=0x0)
    assert camera.offset_x is None
    assert camera.offset_y is None
    assert camera.zoom_level is None

    selection = parse_selection_state(reader, prod_offsets, game_data_base=0x0)
    assert selection.selected_city_index is None
