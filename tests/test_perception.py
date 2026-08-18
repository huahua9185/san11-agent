from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from san11agent.memory import DumpMemoryReader
from san11agent.offsets import load_offsets
from san11agent.perception import (
    parse_generals,
    AnchorResolutionError,
    ValidationError,
    parse_game_state,
    resolve_anchor,
    validate_constants,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
OFFSETS_TEST = FIXTURES / "offsets_test.json"
DUMP_TEST = FIXTURES / "synthetic_dump.json"


@pytest.fixture()
def offsets():
    return load_offsets(OFFSETS_TEST)


@pytest.fixture()
def reader():
    return DumpMemoryReader.from_json_file(DUMP_TEST)


def test_resolve_anchor_fixed_for_fixture(reader, offsets):
    assert resolve_anchor(reader, offsets) == 0x1000


def test_parse_global_state(reader, offsets):
    state = parse_game_state(reader, offsets)
    g = state.global_state
    assert g.scenario_id == 3
    assert g.start_year == 190
    assert g.current_xun == 7
    # 故意标记 unknown 的字段必须解析成 None，而不是抛异常或读出垃圾值
    assert g.current_year is None
    assert g.current_month is None
    assert g.phase is None


def test_parse_generals(reader, offsets):
    state = parse_game_state(reader, offsets)
    assert len(state.generals) == 2
    caocao = state.generals[0]
    assert caocao.name == "曹操"
    assert caocao.faction_id == 0
    assert caocao.loyalty == 100
    assert caocao.base_stats == bytes([96, 72, 90, 94, 96])

    liubei = state.generals[1]
    assert liubei.name == "刘备"
    assert liubei.faction_id == 1


def test_parse_generals_composes_full_name_from_three_segments():
    """姓/名/字三段拼接。用 MutableMemoryReader 手工摆一条武将记录，布局照搬
    实机确认的 姓(+0x00,5) + 名(+0x05,5) + 字(+0x0A,46)。

    这里刻意用真实存在的例子（韋昭，字弘嗣）：修复前 name 只会读出"韋"。
    """
    from san11agent.memory import MutableMemoryReader
    from san11agent.offsets import load_offsets as _load

    raw = json.loads(OFFSETS_TEST.read_text(encoding="utf-8"))
    g = raw["structs"]["general"]
    g["count"] = 1
    g["fields"].pop("name")
    g["fields"]["surname"] = {"offset": "0x00", "size": 5, "type": "fixed_str", "unknown": False}
    g["fields"]["given_name"] = {"offset": "0x05", "size": 5, "type": "fixed_str", "unknown": False}
    # 字段挪到结构体后段的空闲区，避开 fixture 里 0x08 起的其它字段
    g["fields"]["courtesy_name"] = {"offset": "0x54", "size": 8, "type": "fixed_str", "unknown": False}
    raw["validation"]["expected_general_count"] = 1

    path = FIXTURES / "_tmp_offsets_name_split.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    try:
        offsets = _load(path)
        base = 0x1000
        reader = MutableMemoryReader({base: bytes(0x400)}, module_base=0x400000)
        rec = base + 0x100  # general.base_offset
        reader.write_bytes(rec + 0x00, "韋".encode("gbk") + b"\x00" * 3)
        reader.write_bytes(rec + 0x05, "昭".encode("gbk") + b"\x00" * 3)
        reader.write_bytes(rec + 0x54, "弘嗣".encode("gbk") + b"\x00" * 4)

        generals = parse_generals(reader, offsets, base)
        assert generals[0].surname == "韋"
        assert generals[0].given_name == "昭"
        assert generals[0].courtesy_name == "弘嗣"
        assert generals[0].name == "韋昭", "name 必须是姓+名，不能只有姓"
    finally:
        path.unlink(missing_ok=True)


def test_parse_generals_falls_back_to_legacy_single_name_field(reader, offsets):
    """兼容退路：offsets 只声明旧的整段 name 字段时，不应该解析出空姓名。
    退化行为是"信息不全"（名和字为空），不是"编造"或"报错"。"""
    generals = parse_generals(reader, offsets, 0x1000)
    assert generals[0].name == "曹操"
    assert generals[0].surname == "曹操"
    assert generals[0].given_name == ""
    assert generals[0].courtesy_name == ""


def test_parse_cities(reader, offsets):
    state = parse_game_state(reader, offsets)
    assert len(state.cities) == 2
    xuchang = state.cities[0]
    assert xuchang.name == "许昌"
    assert xuchang.gold == 5000
    assert xuchang.food == 8000
    assert xuchang.troops == 3000
    # 未解析出来的字段必须是 None
    assert xuchang.faction_id is None
    assert xuchang.map_x is None
    assert xuchang.map_y is None


def test_parse_troops(reader, offsets):
    state = parse_game_state(reader, offsets)
    assert len(state.troops) == 2
    t0 = state.troops[0]
    assert t0.commander_general_id == 0
    assert t0.faction_id == 0
    assert (t0.x, t0.y) == (50, 60)
    assert t0.troop_count == 3000


def test_parse_factions(reader, offsets):
    state = parse_game_state(reader, offsets)
    assert len(state.factions) == 1
    assert state.factions[0].ruler_general_id == 0
    assert state.factions[0].player_marker == 1


def test_parse_forces(reader, offsets):
    """Force(军团)是 2026-08-18 才追加的结构体，见 docs/offset_research.md
    第7.10节——它是目前唯一能从 General/City.force_id 正确推导出真正政治
    势力归属的路径（General.faction_id/Troop.faction_id 本身不可信，见
    同一节"新发现的异常"）。"""
    state = parse_game_state(reader, offsets)
    assert len(state.forces) == 2
    assert state.forces[0].faction_id == 0
    assert state.forces[0].force_number == 1
    assert state.forces[0].commander_general_id == 0
    assert state.forces[1].force_number == 2


def test_parse_forces_empty_when_offsets_lacks_force_struct(tmp_path):
    """向后兼容：没有定义 force struct 的 offsets 文件（比如其它测试 fixture）
    不应该报错，forces 应该安静地是空列表，而不是强制要求所有 offsets 文件
    都提供这个后来才追加的结构体。"""
    import json

    from san11agent.memory import DumpMemoryReader

    raw = json.loads(OFFSETS_TEST.read_text(encoding="utf-8"))
    del raw["structs"]["force"]
    path = tmp_path / "offsets_no_force.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    offsets_without_force = load_offsets(path)
    reader = DumpMemoryReader.from_json_file(DUMP_TEST)
    state = parse_game_state(reader, offsets_without_force)
    assert state.forces == []


def test_validate_constants_passes_on_matching_data(reader, offsets):
    state = parse_game_state(reader, offsets, validate=False)
    validate_constants(offsets, state)  # 不应该抛异常


def test_validate_constants_fails_on_mismatch(reader, offsets):
    state = parse_game_state(reader, offsets, validate=False)
    bad_offsets = dataclasses.replace(offsets, validation={"expected_general_count": 999})
    with pytest.raises(ValidationError):
        validate_constants(bad_offsets, state)


def test_anchor_unknown_raises(reader, offsets):
    bad_anchor = dataclasses.replace(offsets.anchor, resolution_method="unknown")
    bad_offsets = dataclasses.replace(offsets, anchor=bad_anchor)
    with pytest.raises(AnchorResolutionError):
        resolve_anchor(reader, bad_offsets)


def test_dump_reader_rejects_uncovered_address(reader):
    from san11agent.memory import MemoryReadError

    with pytest.raises(MemoryReadError):
        reader.read_bytes(0x99999999, 4)
