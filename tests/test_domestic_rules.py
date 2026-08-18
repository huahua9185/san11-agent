from __future__ import annotations

import json
from pathlib import Path

import pytest

from san11agent.domestic_rules import DomesticRulesError, RuleValue, load_domestic_rules

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "domestic_rules_test.json"
PK_RULES = REPO_ROOT / "rules" / "domestic_actions_pk_1.1_cn.json"

_ALL_KINDS = {
    "build_facility",
    "recruit_troops",
    "train_troops",
    "security_patrol",
    "levy_gold",
    "levy_food",
    "diplomacy",
    "stratagem",
}


def test_fixture_loads():
    rules = load_domestic_rules(TEST_FIXTURE)
    assert rules.label == "domestic_rules_test_fixture"
    assert rules.verified is True
    assert set(rules.actions.keys()) == _ALL_KINDS


def test_fixture_all_costs_unknown():
    rules = load_domestic_rules(TEST_FIXTURE)
    for kind in _ALL_KINDS:
        rule = rules.action(kind)
        assert rule.min_general_stamina.is_known is False
        assert rule.gold_cost.is_known is False
        assert rule.food_cost.is_known is False


def test_build_facility_sub_types():
    rules = load_domestic_rules(TEST_FIXTURE)
    rule = rules.action("build_facility")
    assert rule.requires_facility_slot is True
    assert set(rule.sub_types.keys()) == {"farm", "market"}
    assert rule.sub_types["farm"].display_name_cn == "农田"


def test_diplomacy_and_stratagem_sub_types():
    rules = load_domestic_rules(TEST_FIXTURE)
    assert set(rules.action("diplomacy").sub_types.keys()) == {"alliance", "ceasefire"}
    assert set(rules.action("stratagem").sub_types.keys()) == {"sabotage"}


def test_has_action():
    rules = load_domestic_rules(TEST_FIXTURE)
    assert rules.has_action("recruit_troops") is True
    assert rules.has_action("nonexistent") is False


def test_action_lookup_raises_for_unknown_kind():
    rules = load_domestic_rules(TEST_FIXTURE)
    with pytest.raises(DomesticRulesError):
        rules.action("nonexistent")


def test_rule_value_is_known():
    known = RuleValue(value=10, unknown=False)
    unknown = RuleValue(value=None, unknown=True)
    assert known.is_known is True
    assert unknown.is_known is False


# ---------------------------------------------------------------------------
# 生产规则表本身也要能加载，且结构性字段（哪些数值 unknown）符合预期——这份表
# 里绝大多数资源消耗数值应该诚实地标 unknown，不能编数字进去。
# ---------------------------------------------------------------------------


def test_pk_rules_file_loads():
    rules = load_domestic_rules(PK_RULES)
    assert rules.label == "domestic_actions_pk_1.1_cn"
    assert rules.verified is False
    assert set(rules.actions.keys()) == _ALL_KINDS


def test_pk_rules_costs_are_honestly_unknown():
    """核心断言：还没有实机验证途径的资源消耗数值必须标 unknown，不能猜测填值。"""
    rules = load_domestic_rules(PK_RULES)
    for kind in _ALL_KINDS:
        rule = rules.action(kind)
        assert rule.min_general_stamina.is_known is False, kind
        assert rule.gold_cost.is_known is False, kind
        assert rule.food_cost.is_known is False, kind


def test_pk_rules_build_facility_types_match_user_request():
    rules = load_domestic_rules(PK_RULES)
    assert set(rules.action("build_facility").sub_types.keys()) == {
        "farm", "market", "barracks", "stable", "crossbow_tower",
    }


# ---------------------------------------------------------------------------
# 格式错误
# ---------------------------------------------------------------------------


def test_missing_top_level_key_raises(tmp_path):
    bad = {"meta": {"label": "x", "verified": False}}
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(DomesticRulesError):
        load_domestic_rules(path)


def test_missing_meta_field_raises(tmp_path):
    bad = {"meta": {"label": "x"}, "actions": {}}
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(DomesticRulesError):
        load_domestic_rules(path)


def test_action_missing_display_name_raises(tmp_path):
    bad = {
        "meta": {"label": "x", "verified": False},
        "actions": {"recruit_troops": {"requires_own_city": True}},
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(DomesticRulesError):
        load_domestic_rules(path)


def test_rule_value_missing_unknown_key_raises(tmp_path):
    bad = {
        "meta": {"label": "x", "verified": False},
        "actions": {
            "recruit_troops": {
                "display_name_cn": "征兵",
                "requires_own_city": True,
                "gold_cost": {"value": 10},
            }
        },
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(DomesticRulesError):
        load_domestic_rules(path)


def test_known_rule_value_without_value_raises(tmp_path):
    bad = {
        "meta": {"label": "x", "verified": False},
        "actions": {
            "recruit_troops": {
                "display_name_cn": "征兵",
                "requires_own_city": True,
                "gold_cost": {"value": None, "unknown": False},
            }
        },
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(DomesticRulesError):
        load_domestic_rules(path)


def test_sub_type_missing_display_name_raises(tmp_path):
    bad = {
        "meta": {"label": "x", "verified": False},
        "actions": {
            "build_facility": {
                "display_name_cn": "设施建设",
                "requires_own_city": True,
                "facility_types": {"farm": {}},
            }
        },
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(DomesticRulesError):
        load_domestic_rules(path)


def test_duplicate_sub_type_id_across_groups_raises(tmp_path):
    bad = {
        "meta": {"label": "x", "verified": False},
        "actions": {
            "diplomacy": {
                "display_name_cn": "外交",
                "requires_own_city": True,
                "diplomacy_types": {"same_id": {"display_name_cn": "A"}},
                "stratagem_types": {"same_id": {"display_name_cn": "B"}},
            }
        },
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(DomesticRulesError):
        load_domestic_rules(path)
