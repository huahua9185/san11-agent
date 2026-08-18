from __future__ import annotations

import json
from pathlib import Path

import pytest

from san11agent.offsets import OffsetsError, load_offsets

REPO_ROOT = Path(__file__).resolve().parent.parent
PK_OFFSETS = REPO_ROOT / "offsets" / "pk_1.1_cn.json"


def test_pk_offsets_file_loads():
    offsets = load_offsets(PK_OFFSETS)
    assert offsets.label == "pk_1.1_cn"
    assert offsets.process_name == "san11pk.exe"
    assert offsets.verified is False


def test_pk_offsets_anchor_is_honestly_unknown():
    """核心断言：锚点解析方式必须诚实标记为 unknown，不能悄悄塞一个绝对地址当真值用。"""
    offsets = load_offsets(PK_OFFSETS)
    assert offsets.anchor.resolution_method == "unknown"
    assert offsets.anchor.observed_absolute_address == 0x07201958


def test_pk_offsets_struct_counts():
    offsets = load_offsets(PK_OFFSETS)
    assert offsets.struct("general").count == 1100
    assert offsets.struct("city").count == 42
    assert offsets.struct("faction").count == 42


def test_pk_offsets_known_field_has_offset():
    offsets = load_offsets(PK_OFFSETS)
    field = offsets.struct("general").field("name")
    assert field.unknown is False
    assert field.offset == 0x04


def test_pk_offsets_unresolved_fields_are_flagged_unknown():
    """城池所属势力、地图坐标、当前年月日、游戏阶段——这些字段必须显式标 unknown，
    不能因为"看起来该有个值"就编一个偏移进去。"""
    offsets = load_offsets(PK_OFFSETS)
    assert offsets.struct("city").field("faction_id").unknown is True
    assert offsets.struct("city").field("map_x").unknown is True
    assert offsets.struct("city").field("map_y").unknown is True
    assert offsets.struct("global").field("current_year").unknown is True
    assert offsets.struct("global").field("phase").unknown is True


def test_troop_base_offset_has_two_unresolved_candidates():
    offsets = load_offsets(PK_OFFSETS)
    troop = offsets.struct("troop")
    assert len(troop.base_offset_candidates) == 2


def test_unknown_field_require_known_raises():
    offsets = load_offsets(PK_OFFSETS)
    field = offsets.struct("global").field("phase")
    with pytest.raises(OffsetsError):
        field.require_known()


def test_known_field_require_known_ok():
    offsets = load_offsets(PK_OFFSETS)
    field = offsets.struct("global").field("scenario_id")
    assert field.require_known() is field


def test_missing_top_level_key_raises(tmp_path):
    bad = {"meta": {"label": "x", "process_name": "x.exe", "verified": False}, "anchor": {"resolution_method": "unknown"}}
    path = tmp_path / "bad_offsets.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(OffsetsError):
        load_offsets(path)


def test_field_missing_unknown_key_raises(tmp_path):
    bad = {
        "meta": {"label": "x", "process_name": "x.exe", "verified": False},
        "anchor": {"resolution_method": "unknown"},
        "structs": {
            "global": {
                "base_offset": "0x0",
                "fields": {
                    "scenario_id": {"offset": "0x04", "size": 4, "type": "i32"}
                },
            }
        },
    }
    path = tmp_path / "bad_field.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(OffsetsError):
        load_offsets(path)


def test_known_field_without_offset_raises(tmp_path):
    bad = {
        "meta": {"label": "x", "process_name": "x.exe", "verified": False},
        "anchor": {"resolution_method": "unknown"},
        "structs": {
            "global": {
                "base_offset": "0x0",
                "fields": {
                    "scenario_id": {"offset": None, "size": 4, "type": "i32", "unknown": False}
                },
            }
        },
    }
    path = tmp_path / "bad_field2.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(OffsetsError):
        load_offsets(path)


def test_invalid_resolution_method_raises(tmp_path):
    bad = {
        "meta": {"label": "x", "process_name": "x.exe", "verified": False},
        "anchor": {"resolution_method": "guessing"},
        "structs": {},
    }
    path = tmp_path / "bad_anchor.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(OffsetsError):
        load_offsets(path)
