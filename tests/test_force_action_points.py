"""Resource interpretation, byte width, visibility, and summary integration."""
from __future__ import annotations

from dataclasses import replace

import pytest

from san11agent.boundary import filter_game_state
from san11agent.game_state import Force, GameState, GlobalState
from san11agent.memory import DumpMemoryReader
from san11agent.offsets import load_offsets
from san11agent.perception import parse_forces
from san11agent.situation_summary import render_situation_text, summarize_situation
from san11agent.visibility import StaticVisibilitySource
from san11agent.visible_state import VisibleForce


@pytest.mark.parametrize("points", [0, 35, 90, 255])
def test_force_action_points_are_unsigned_byte(points):
    cfg = load_offsets("offsets/pk_1.1_cn.json")
    force = cfg.struct("force")
    cfg = replace(cfg, structs={**cfg.structs, "force": replace(force, count=1)})
    record = bytearray(force.struct_size)
    record[0x2C] = points
    record[0x2D] = 0xA5  # A neighbouring byte must not become part of this value.
    reader = DumpMemoryReader({0x1000 + force.base_offset: bytes(record)}, module_base=0)
    assert parse_forces(reader, cfg, 0x1000)[0].action_points == points


def test_legacy_force_config_does_not_invent_resource_balance():
    cfg = load_offsets("offsets/pk_1.1_cn.json")
    force = cfg.struct("force")
    fields = {k: v for k, v in force.fields.items() if k != "action_points"}
    cfg = replace(cfg, structs={**cfg.structs, "force": replace(force, count=1, fields=fields)})
    reader = DumpMemoryReader({0x1000 + force.base_offset: bytes(force.struct_size)}, module_base=0)
    assert parse_forces(reader, cfg, 0x1000)[0].action_points is None


def test_full_force_capacity_includes_slot_46_without_overlapping_generals():
    cfg = load_offsets("offsets/pk_1.1_cn.json")
    force = cfg.struct("force")
    assert force.count == 47
    assert force.base_offset + force.count * force.struct_size == cfg.struct("general").base_offset
    table = bytearray(force.count * force.struct_size)
    table[46 * force.struct_size + 0x2C] = 255
    reader = DumpMemoryReader({0x1000 + force.base_offset: bytes(table)}, module_base=0)
    assert parse_forces(reader, cfg, 0x1000)[46].action_points == 255


def test_only_own_force_budgets_reach_summary_once_per_force():
    state = GameState(
        global_state=GlobalState(1, 190, 1, 1, 0, 1, 0, 1),
        forces=[Force(0, 0, 1, 343, 90), Force(1, 1, 1, 635, 247), Force(2, -1, 0, -1, 251)],
    )
    visible = filter_game_state(state, StaticVisibilitySource(_player_faction_id=0))
    assert visible.forces == [VisibleForce(0, 0, 90)]
    summary = summarize_situation(visible, 0)
    assert summary.own_force_action_points == ((0, 90),)
    text = render_situation_text(summary)
    assert text.count("军团[0]") == 1
    assert "行動力=90" in text
    assert "247" not in text and "251" not in text


def test_missing_own_force_balance_remains_unknown_in_summary():
    state = GameState(global_state=GlobalState(1, 190, 1, 1, 0, 1, 0, 1), forces=[Force(0, 0, 1, 343)])
    visible = filter_game_state(state, StaticVisibilitySource(_player_faction_id=0))
    assert "行動力=未知" in render_situation_text(summarize_situation(visible, 0))
