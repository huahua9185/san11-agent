"""Decode the action bit independently of stamina, experience and other flags."""
from dataclasses import replace
import struct

import pytest

from san11agent.memory import DumpMemoryReader
from san11agent.offsets import load_offsets
from san11agent.perception import parse_generals


@pytest.mark.parametrize("flags, expected", [
    (0x2C8, False), (0x2C9, True), (0x2F8, False), (0x2F9, True),
    (2, False), (0xFFFFFFFF, True),
])
def test_general_action_bit_is_not_whole_flags_or_experience(flags, expected):
    cfg = load_offsets("offsets/pk_1.1_cn.json")
    spec = cfg.struct("general")
    cfg = replace(cfg, structs={**cfg.structs, "general": replace(spec, count=1)})
    record = bytearray(spec.struct_size)
    struct.pack_into("<I", record, 0x124, flags)
    record[0x128] = 100
    struct.pack_into("<H", record, 0x12A, 2)  # Persists after turn; not action state.
    reader = DumpMemoryReader({0x1000 + spec.base_offset: bytes(record)}, module_base=0)
    general = parse_generals(reader, cfg, 0x1000)[0]
    assert general.has_acted is expected
    assert general.stamina == 100


def test_legacy_general_config_keeps_action_state_unknown():
    cfg = load_offsets("offsets/pk_1.1_cn.json")
    spec = cfg.struct("general")
    fields = {k: v for k, v in spec.fields.items() if k != "action_flags"}
    cfg = replace(cfg, structs={**cfg.structs, "general": replace(spec, count=1, fields=fields)})
    reader = DumpMemoryReader({0x1000 + spec.base_offset: bytes(spec.struct_size)}, module_base=0)
    assert parse_generals(reader, cfg, 0x1000)[0].has_acted is None
