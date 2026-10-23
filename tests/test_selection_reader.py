"""Tests for the version-specific city-menu selection reader."""
from __future__ import annotations

from pathlib import Path

from san11agent.memory import MutableMemoryReader
from san11agent.offsets import load_offsets
from san11agent.selection_reader import (
    DEFAULT_SELECTION_LAYOUT,
    read_city_map_coordinate,
    read_selected_city,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
OFFSETS = load_offsets(REPO_ROOT / "offsets/pk_1.1_cn.json")

MODULE_BASE = 0x00400000
GAME_DATA_BASE = 0x07201958
MANAGER_GLOBAL = 0x096A58F0
MANAGER_ADDRESS = 0x00500000
OBJECT_BASE = GAME_DATA_BASE + DEFAULT_SELECTION_LAYOUT.map_object_base_offset
CITY_BASE = GAME_DATA_BASE + DEFAULT_SELECTION_LAYOUT.city_base_offset


def _reader() -> MutableMemoryReader:
    return MutableMemoryReader(
        {
            MANAGER_GLOBAL: bytearray(4),
            MANAGER_ADDRESS: bytearray(0x100),
            OBJECT_BASE: bytearray(42 * DEFAULT_SELECTION_LAYOUT.map_object_stride),
            CITY_BASE: bytearray(42 * DEFAULT_SELECTION_LAYOUT.city_stride),
        },
        module_base=MODULE_BASE,
    )


def _set_city(
    reader: MutableMemoryReader,
    *,
    index: int,
    name: str,
    map_x: int,
    map_y: int,
) -> int:
    object_address = OBJECT_BASE + index * DEFAULT_SELECTION_LAYOUT.map_object_stride
    reader.write_i32(MANAGER_GLOBAL, MANAGER_ADDRESS)
    reader.write_i32(MANAGER_ADDRESS + DEFAULT_SELECTION_LAYOUT.selected_object_offset, object_address)
    reader.write_bytes(object_address + 0x1C, (map_x << 16).to_bytes(4, "little"))
    reader.write_bytes(object_address + 0x20, (map_y & 0xFFFF).to_bytes(4, "little"))
    city_address = CITY_BASE + index * DEFAULT_SELECTION_LAYOUT.city_stride
    encoded = name.encode(OFFSETS.text_encoding)
    reader.write_bytes(city_address + 4, encoded + b"\x00" * (8 - len(encoded)))
    return object_address


def test_reads_selected_city_and_candidate_coordinate():
    reader = _reader()
    object_address = _set_city(reader, index=11, name="濮陽", map_x=120, map_y=71)

    result = read_selected_city(reader, OFFSETS, GAME_DATA_BASE)

    assert result is not None
    assert result.city_index == 11
    assert result.city_name == "濮陽"
    assert (result.map_x, result.map_y) == (120, 71)
    assert result.manager_address == MANAGER_ADDRESS
    assert result.object_address == object_address
    assert result.is_city


def test_reads_second_city():
    reader = _reader()
    _set_city(reader, index=3, name="南皮", map_x=138, map_y=37)

    result = read_selected_city(reader, OFFSETS, GAME_DATA_BASE)

    assert result is not None
    assert result.city_index == 3
    assert result.city_name == "南皮"
    assert (result.map_x, result.map_y) == (138, 37)


def test_returns_none_when_idle():
    reader = _reader()
    reader.write_i32(MANAGER_GLOBAL, 0)

    assert read_selected_city(reader, OFFSETS, GAME_DATA_BASE) is None


def test_returns_none_for_invalid_selected_pointer():
    reader = _reader()
    reader.write_i32(MANAGER_GLOBAL, MANAGER_ADDRESS)
    reader.write_i32(MANAGER_ADDRESS + DEFAULT_SELECTION_LAYOUT.selected_object_offset, 0x12345678)

    assert read_selected_city(reader, OFFSETS, GAME_DATA_BASE) is None


def test_independent_map_coordinate_reader():
    reader = _reader()
    _set_city(reader, index=11, name="濮陽", map_x=120, map_y=71)

    assert read_city_map_coordinate(reader, GAME_DATA_BASE, 11) == (120, 71)
    assert read_city_map_coordinate(reader, GAME_DATA_BASE, 42) is None
