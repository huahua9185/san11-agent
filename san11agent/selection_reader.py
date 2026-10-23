"""Read the current city-menu target from the running game process.

This is the first reader built on the 2026-10-23 A/B finding:

    DAT_096a58f0 + 0x64              -> selected map object pointer
    GAME_DATA_BASE + 0x89730 + i*0x38 -> city map-object (first 42 = cities)
    object + 0x1C high word / +0x20 low word -> map coordinate candidate

The layout below is **version-specific** and was verified by clicking the 濮陽
and 南皮 city menus on 2026-10-23 (index 11 and 3, with matching city names and
coordinates). It must be revalidated if the EXE SHA-256 changes. The layout is
kept as a dataclass rather than scattered constants so it can later move into
the offsets schema without changing callers.

Boundary: this reader is read-only and does not send input or write game memory.
The command-manager global is non-zero only while a city menu/command context
exists; at idle it returns `None`. It therefore confirms a **menu target**, not
a hover-only highlight.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from .memory import MemoryReadError, MemoryReader
from .offsets import OffsetsConfig


@dataclass(frozen=True)
class SelectionLayout:
    """Version-specific layout for the city-menu target chain."""

    image_base: int = 0x00400000
    command_manager_va: int = 0x096A58F0
    selected_object_offset: int = 0x64
    map_object_base_offset: int = 0x89730
    map_object_stride: int = 0x38
    map_object_capacity: int = 0x4000
    city_base_offset: int = 0x1D8
    city_stride: int = 0x248
    city_count: int = 42


DEFAULT_SELECTION_LAYOUT = SelectionLayout()


@dataclass(frozen=True)
class SelectedCity:
    """The city-menu target and the candidate map coordinate."""

    city_index: int
    city_name: str | None
    map_x: int | None
    map_y: int | None
    manager_address: int
    object_address: int

    @property
    def is_city(self) -> bool:
        return self.city_name is not None


def _u32(reader: MemoryReader, address: int) -> int:
    return struct.unpack("<I", reader.read_bytes(address, 4))[0]


def read_selected_city(
    reader: MemoryReader,
    offsets: OffsetsConfig,
    game_data_base: int,
    *,
    layout: SelectionLayout = DEFAULT_SELECTION_LAYOUT,
) -> SelectedCity | None:
    """Return the current city-menu target, or None when no target exists."""
    manager_va = reader.module_base + (layout.command_manager_va - layout.image_base)
    try:
        manager = _u32(reader, manager_va)
        if not manager:
            return None
        selected = _u32(reader, manager + layout.selected_object_offset)
        if not selected:
            return None

        object_base = game_data_base + layout.map_object_base_offset
        object_end = object_base + layout.map_object_capacity * layout.map_object_stride
        if not (object_base <= selected < object_end):
            return None

        city_index = (selected - object_base) // layout.map_object_stride
        city_name = None
        if 0 <= city_index < layout.city_count:
            city_address = game_data_base + layout.city_base_offset + city_index * layout.city_stride
            city_name = reader.read_fixed_str(
                city_address + 4, 8, encoding=offsets.text_encoding
            )

        map_x = _u32(reader, selected + 0x1C) >> 16
        map_y = _u32(reader, selected + 0x20) & 0xFFFF
    except (MemoryReadError, OSError, ValueError):
        return None

    return SelectedCity(
        city_index=city_index,
        city_name=city_name,
        map_x=map_x,
        map_y=map_y,
        manager_address=manager,
        object_address=selected,
    )


def read_city_map_coordinate(
    reader: MemoryReader,
    game_data_base: int,
    city_index: int,
    *,
    layout: SelectionLayout = DEFAULT_SELECTION_LAYOUT,
) -> tuple[int, int] | None:
    """Read the candidate map coordinate for a city index.

    This is the object-array path, independent of any open menu. The coordinate
    semantics are still a candidate (`+0x1C>>16`, `+0x20&0xFFFF`) and have only
    been checked against the 42-city domestic-land correlation plus the two A/B
    points; callers must not treat it as a verified `city.map_x/map_y` field yet.
    """
    if not 0 <= city_index < layout.city_count:
        return None
    object_address = (
        game_data_base
        + layout.map_object_base_offset
        + city_index * layout.map_object_stride
    )
    try:
        return _u32(reader, object_address + 0x1C) >> 16, _u32(reader, object_address + 0x20) & 0xFFFF
    except (MemoryReadError, OSError, ValueError):
        return None
