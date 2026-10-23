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
    "produce_equipment",
    "research_tech",
    "merchant",
    "seek_talent",
    "reward",
    "recruit_general",
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


def test_effective_action_points_cost_is_explicit_and_patrol_only_in_production():
    rules = load_domestic_rules(REPO_ROOT / "rules" / "domestic_actions_pk_1.1_cn.json")
    known = {key: rule.effective_action_points_cost.value for key, rule in rules.actions.items()
             if rule.effective_action_points_cost.is_known}
    assert known == {"security_patrol": 20}
    legacy = load_domestic_rules(TEST_FIXTURE)
    assert all(not rule.effective_action_points_cost.is_known for rule in legacy.actions.values())


@pytest.mark.parametrize("value", [-1, True, 1.5, "20"])
def test_effective_action_points_cost_rejects_invalid_values(tmp_path, value):
    import json
    raw = json.loads(TEST_FIXTURE.read_text(encoding="utf-8"))
    raw["actions"]["security_patrol"]["effective_action_points_cost"] = {"value": value, "unknown": False}
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(DomesticRulesError, match="有效行動力费用"):
        load_domestic_rules(path)


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
    """核心断言：还没有可靠依据的资源消耗数值必须标 unknown，不能猜测填值。

    2026-08-19 之前这条断言要求全部8种动作的三项资源都 unknown。当天有
    两类事件改变了这个状态：① security_patrol 实机执行两次独立核对
    （stamina/资金/兵糧）；② 在游戏安装目录找到官方内建手册（San11WPK.pdf，
    用 pdftotext 提取文字层），里面的'指令一覽'章节给出了每种内政指令精确
    的资金/行動力（不是体力）消耗——这是官方权威数据源，不是猜测，跟本
    项目'没依据就标 unknown'的原则不冲突。

    min_general_stamina 现在全部指令都标 0/已知——不是巧合，是手册对这些
    内政指令统一没有提到'体力'这个概念，真正的门槛资源是'行動力'
    （action_points_cost，另有断言锁定）。food_cost 同理，手册没有为任何
    一种内政指令列出兵糧消耗项，全部标 0/已知。

    gold_cost 只在数值单一确定时才标已知；'因设施/研究而异'
    （build_facility/研究技巧顶层）、'多的話成功率上昇'这类可变出价
    （diplomacy 顶层及部分子类型）保持 unknown，不编一个具体数字。
    """
    rules = load_domestic_rules(PK_RULES)

    for kind in _ALL_KINDS:
        rule = rules.action(kind)
        assert (rule.min_general_stamina.value, rule.min_general_stamina.is_known) == (0, True), kind
        assert (rule.food_cost.value, rule.food_cost.is_known) == (0, True), kind

    expected_action_points = {
        "build_facility": 20,
        "recruit_troops": 20,
        "train_troops": 20,
        "security_patrol": 20,
        "diplomacy": 30,
        "stratagem": 30,
    }
    for kind, expected in expected_action_points.items():
        rule = rules.action(kind)
        assert (rule.action_points_cost.value, rule.action_points_cost.is_known) == (expected, True), kind

    expected_gold = {
        "recruit_troops": 300,
        "train_troops": 0,
        "security_patrol": 100,
        "stratagem": 200,
    }
    for kind, expected in expected_gold.items():
        rule = rules.action(kind)
        assert (rule.gold_cost.value, rule.gold_cost.is_known) == (expected, True), kind

    # build_facility/diplomacy 顶层的 gold_cost 因子类型/出价而异，故意保持 unknown。
    assert rules.action("build_facility").gold_cost.is_known is False
    assert rules.action("diplomacy").gold_cost.is_known is False


def test_pk_rules_build_facility_types_match_ingame_menu():
    """2026-08-18：原测试名叫 ..._match_user_request，断言的是需求里列的5种设施
    （farm/market/barracks/stable/crossbow_tower）。用户点开游戏「都市」→「開發」
    截图后确认实际有19种，且其中 crossbow_tower(弩楼) 根本不是城池开发设施
    （它是部队在战场上造的军事建筑），属于分类错误。现改为断言实机确认的19种。
    2026-08-20：官方手册确认还有第20种「銅雀台」（需要「銅雀」道具才会出现在
    開發界面里，之前的截图里没拍到，不是遗漏）。
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
        # 道具解锁系
        "bronze_sparrow_tower",
    }
    # 原表5种里真实存在的4种，繁体名称对得上
    assert sub_types["farm"].display_name_cn == "農場"
    assert sub_types["market"].display_name_cn == "市場"
    assert sub_types["barracks"].display_name_cn == "兵舍"
    assert sub_types["stable"].display_name_cn == "廐舍"
    # 弩楼不是开发设施，必须不在列表里
    assert "crossbow_tower" not in sub_types


def test_pk_rules_facility_durability_and_effect_are_known_per_subtype():
    """2026-08-20：用官方手册《遊戲說明書》P.14-15/《威力加強手冊》P.28-29
    给全部20种设施补上耐久（durability）和效果说明（effect_note），来源与
    gold_cost 不同（手册原文，不是实机截图），但同样是权威依据，不是猜测。
    """
    rules = load_domestic_rules(PK_RULES)
    sub_types = rules.action("build_facility").sub_types

    assert all(st.durability.is_known for st in sub_types.values()), "20种设施都应有已知耐久"
    assert all(st.effect_note for st in sub_types.values()), "20种设施都应有效果说明原文"

    # 相邻加成的两个典型例子：造幣廠/穀倉把相邻市場/農場的效果变成1.5倍
    assert sub_types["mint"].durability.value == 1000
    assert "1.5倍" in sub_types["mint"].effect_note
    assert sub_types["granary"].durability.value == 1000
    assert "1.5倍" in sub_types["granary"].effect_note

    # 道具解锁设施，耐久档位比其余19种都高
    assert sub_types["bronze_sparrow_tower"].durability.value == 1300
    assert "銅雀" in sub_types["bronze_sparrow_tower"].effect_note


def test_pk_rules_research_tech_has_32_techs_with_tiered_gold_cost():
    """2026-08-20：技巧树8个分类（槍兵/戟兵/弩兵/騎兵/鍊兵/發明/防衛/火攻）
    各4级共32个技巧，来自官方手册《遊戲說明書》P.18-19。资金门槛按等级分
    4档（①1000/②2000/③5000/④10000），同一档位在8个分类间通用。
    """
    rules = load_domestic_rules(PK_RULES)
    sub_types = rules.action("research_tech").sub_types

    assert len(sub_types) == 32
    assert all(st.gold_cost.is_known for st in sub_types.values()), "32个技巧都应有已知资金门槛"
    assert all(st.effect_note for st in sub_types.values()), "32个技巧都应有效果说明原文"
    assert {st.gold_cost.value for st in sub_types.values()} == {1000, 2000, 5000, 10000}

    # 每个分类第1级和第4级各抽一个核对
    assert sub_types["spear_training"].display_name_cn == "鍛鍊槍兵"
    assert sub_types["spear_training"].gold_cost.value == 1000
    assert sub_types["elite_cavalry"].display_name_cn == "精銳騎兵"
    assert sub_types["explosive_refinement"].display_name_cn == "鍊成炸藥"
    assert sub_types["explosive_refinement"].gold_cost.value == 10000


def test_pk_rules_facility_gold_costs_are_known_per_subtype():
    """2026-08-18：设施造价是本规则表里第一批有实机依据的数值（来自「開發」界面
    截图，50~400 不等）。因为造价按子类型区分、没有统一值，所以动作层级的
    gold_cost 仍然必须是 unknown——下游要判断钱够不够，得看具体子类型。
    2026-08-20：加入官方手册确认的第20种「銅雀台」，造价1500（道具解锁设施，
    价格档位比其余19种都高，单独校验）。"""
    rules = load_domestic_rules(PK_RULES)
    rule = rules.action("build_facility")
    assert rule.gold_cost.is_known is False, "动作层级不应该有统一造价"

    sub_types = rule.sub_types
    assert all(st.gold_cost.is_known for st in sub_types.values()), "20种设施都应有已知造价"
    assert sub_types["black_market"].gold_cost.value == 50   # 最便宜
    assert sub_types["market"].gold_cost.value == 200
    assert sub_types["barracks"].gold_cost.value == 300
    assert sub_types["mint"].gold_cost.value == 400          # 原19种里最贵档
    assert sub_types["bronze_sparrow_tower"].gold_cost.value == 1500  # 道具解锁，全场最贵
    assert {st.gold_cost.value for st in sub_types.values()} == {50, 200, 300, 400, 1500}


def test_sub_type_gold_cost_known_or_unknown_matches_manual():
    """2026-08-19 之前外交/计略全部子类型都是 unknown（安静默认，不报错、
    不当成0）。找到官方手册后，数值固定的子类型已经标为已知；'多的話成功
    率上昇'这类可变出价的子类型（不是固定数值）保持 unknown，不编一个数字。
    """
    rules = load_domestic_rules(PK_RULES)

    known = {
        ("diplomacy", "goodwill"): 1000,
        ("diplomacy", "alliance"): 1000,
        ("diplomacy", "break_alliance"): 0,
        ("diplomacy", "demand_surrender"): 0,
        ("stratagem", "two_tigers"): 200,
        ("stratagem", "drive_tiger_devour_wolf"): 200,
        ("stratagem", "spread_rumor"): 200,
    }
    still_unknown = {
        ("diplomacy", "ceasefire"),
        ("diplomacy", "exchange_prisoners"),
        ("diplomacy", "request_reinforcements"),
    }

    for kind in ("diplomacy", "stratagem"):
        for st in rules.action(kind).sub_types.values():
            key = (kind, st.id)
            if key in known:
                assert (st.gold_cost.value, st.gold_cost.is_known) == (known[key], True), key
            else:
                assert key in still_unknown, f"未分类的子类型: {key}"
                assert st.gold_cost.is_known is False, key


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
