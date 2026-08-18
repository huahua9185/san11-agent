from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from san11agent.memory import DumpMemoryReader
from san11agent.offsets import load_offsets
from san11agent.perception import (
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
