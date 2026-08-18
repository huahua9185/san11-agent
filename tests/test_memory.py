from __future__ import annotations

import struct

import pytest

from san11agent.memory import MemoryReadError, MutableMemoryReader


def test_mutable_memory_reader_round_trips_write_and_read():
    reader = MutableMemoryReader({0x1000: bytes(16)}, module_base=0x400000)
    reader.write_i32(0x1000, 42)
    assert reader.read_i32(0x1000) == 42


def test_mutable_memory_reader_write_does_not_disturb_neighboring_bytes():
    reader = MutableMemoryReader({0x1000: bytes(16)}, module_base=0x400000)
    reader.write_bytes(0x1000, struct.pack("<i", -1))
    reader.write_bytes(0x1004, struct.pack("<i", 7))
    assert reader.read_i32(0x1000) == -1
    assert reader.read_i32(0x1004) == 7


def test_mutable_memory_reader_rejects_write_outside_regions():
    reader = MutableMemoryReader({0x1000: bytes(4)}, module_base=0x400000)
    with pytest.raises(MemoryReadError):
        reader.write_bytes(0x2000, b"\x01\x02\x03\x04")


def test_mutable_memory_reader_rejects_read_outside_regions():
    reader = MutableMemoryReader({0x1000: bytes(4)}, module_base=0x400000)
    with pytest.raises(MemoryReadError):
        reader.read_bytes(0x9999, 4)


def test_mutable_memory_reader_initial_regions_are_copied_not_aliased():
    original = bytearray(4)
    reader = MutableMemoryReader({0x1000: bytes(original)}, module_base=0x400000)
    reader.write_i32(0x1000, 99)
    assert original == bytearray(4)  # 传入的原始数据没有被修改
