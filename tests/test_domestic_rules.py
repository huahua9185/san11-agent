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


def test_pk_rules_build_facility_types_match_ingame_menu():
    """2026-08-18：原测试名叫 ..._match_user_request，断言的是需求里列的5种设施
    （farm/market/barracks/stable/crossbow_tower）。用户点开游戏「都市」→「開發」
    截图后确认实际有19种，且其中 crossbow_tower(弩楼) 根本不是城池开发设施
    （它是部队在战场上造的军事建筑），属于分类错误。现改为断言实机确认的19种。
    """
    rules = load_domestic_rules(PK_RULES)
    sub_types = rules.action("build_facility").sub_types
    assert set(sub_types.keys()) == {
        # 商业/金钱系
        "market", "mint", "black_market", "great_market", "fish_market",
        "drill_ground", "envoy_platform",
        # 农业 + 府系
        "farm", "granary", "military_farm",
        "military_office", "personnel_office", "diplomacy_office", "stratagem_office",
        # 军事/生产系
        "barracks", "smithy", "stable", "workshop", "shipyard",
    }
    # 原表5种里真实存在的4种，繁体名称对得上
    assert sub_types["farm"].display_name_cn == "農場"
    assert sub_types["market"].display_name_cn == "市場"
    assert sub_types["barracks"].display_name_cn == "兵舍"
    assert sub_types["stable"].display_name_cn == "廐舍"
    # 弩楼不是开发设施，必须不在列表里
    assert "crossbow_tower" not in sub_types


def test_pk_rules_facility_gold_costs_are_known_per_subtype():
    """2026-08-18：设施造价是本规则表里第一批有实机依据的数值（来自「開發」界面
    截图，50~400 不等）。因为造价按子类型区分、没有统一值，所以动作层级的
    gold_cost 仍然必须是 unknown——下游要判断钱够不够，得看具体子类型。"""
    rules = load_domestic_rules(PK_RULES)
    rule = rules.action("build_facility")
    assert rule.gold_cost.is_known is False, "动作层级不应该有统一造价"

    sub_types = rule.sub_types
    assert all(st.gold_cost.is_known for st in sub_types.values()), "19种设施都应有已知造价"
    assert sub_types["black_market"].gold_cost.value == 50   # 最便宜
    assert sub_types["market"].gold_cost.value == 200
    assert sub_types["barracks"].gold_cost.value == 300
    assert sub_types["mint"].gold_cost.value == 400          # 最贵档
    assert {st.gold_cost.value for st in sub_types.values()} == {50, 200, 300, 400}


def test_sub_type_gold_cost_defaults_to_unknown_when_absent():
    """外交/计略的子类型目前没有造价数据，必须安静地默认 unknown，
    而不是报错或被当成 0。"""
    rules = load_domestic_rules(PK_RULES)
    for kind in ("diplomacy", "stratagem"):
        for st in rules.action(kind).sub_types.values():
            assert st.gold_cost.is_known is False, f"{kind}.{st.id}"


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
