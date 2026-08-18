"""M5：战术执行层（内政）的单元测试。

用真实的 enumerate_legal_actions() 产出合法动作列表（不是手工拼 Action 对象），
这样"select_domestic_actions() 返回的动作确实来自 legal_actions"这条核心约束
测的是端到端行为，不是"两边巧合用了同样的构造逻辑"。规则表复用
tests/fixtures/domestic_rules_test.json（跟 test_legal_actions.py 系列共享，
子类型 id 跟生产 rules/domestic_actions_pk_1.1_cn.json 一致：facility
farm/market，diplomacy alliance/ceasefire，stratagem sabotage）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from san11agent.domestic_rules import ActionRuleSpec, DomesticRulesConfig, RuleValue, SubTypeSpec, load_domestic_rules
from san11agent.domestic_tactics import TacticalError, select_domestic_actions
from san11agent.intent import CityDirective, DomesticFocus, StrategicIntent
from san11agent.legal_actions import (
    BuildFacilityAction,
    DiplomacyAction,
    LevyFoodAction,
    LevyGoldAction,
    RecruitTroopsAction,
    SecurityPatrolAction,
    StratagemAction,
    TrainTroopsAction,
    enumerate_legal_actions,
)
from san11agent.visible_state import (
    VisibleCityDetail,
    VisibleCitySummary,
    VisibleFactionPublic,
    VisibleGameState,
    VisibleGeneralFull,
    VisibleGlobalState,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_RULES = REPO_ROOT / "tests" / "fixtures" / "domestic_rules_test.json"

PLAYER_FACTION_ID = 0
ENEMY_FACTION_ID = 1
OWN_CITY = 0
ENEMY_CITY = 1
GENERAL_A = 0


@pytest.fixture
def rules() -> DomesticRulesConfig:
    return load_domestic_rules(TEST_RULES)


def _global_state() -> VisibleGlobalState:
    return VisibleGlobalState(
        scenario_id=1, start_year=190, start_month=1, start_day=1,
        emperor_general_id=0, difficulty=1, death_setting=0, current_xun=1,
        current_year=190, current_month=1, current_day=1, phase=1,
    )


def _own_city(index: int) -> VisibleCityDetail:
    return VisibleCityDetail(
        index=index, name=f"city{index}", province=0, adjacent_cities=[],
        faction_id=PLAYER_FACTION_ID, map_x=0, map_y=0,
        governor_general_id=0, force_id=0, troop_capacity=100, troops=50,
        gold=500, food=8000, trade_price=10, has_merchant=1, morale=80,
        security=80, policy=0, target=0,
        development_land_count=5, developed_land_count=3,
        domestic_land_x=10, domestic_land_y=20,
    )


def _general(index: int, *, location: int) -> VisibleGeneralFull:
    return VisibleGeneralFull(
        index=index, name=f"g{index}", portrait_id=0, gender=0, debut_year=0,
        birth_year=0, death_year=-1, faction_id=PLAYER_FACTION_ID, identity=0, office=0,
        location=location, special_skill_id=-1,
        display_stats_wound=b"\x00" * 5, display_stats_normal=b"\x00" * 5,
        loyalty=80, merit=0, stamina=50, garrison_count=0, health=1, force_id=PLAYER_FACTION_ID,
    )


def _build_legal_actions(rules: DomesticRulesConfig) -> list:
    state = VisibleGameState(
        global_state=_global_state(),
        generals=[_general(GENERAL_A, location=OWN_CITY)],
        cities=[
            _own_city(OWN_CITY),
            VisibleCitySummary(
                index=ENEMY_CITY, name="敌城", province=1, adjacent_cities=[],
                faction_id=ENEMY_FACTION_ID, map_x=1, map_y=1,
            ),
        ],
        troops=[],
        factions=[
            VisibleFactionPublic(index=PLAYER_FACTION_ID, ruler_general_id=0, advisor_general_id=-1, player_marker=1),
            VisibleFactionPublic(index=ENEMY_FACTION_ID, ruler_general_id=1, advisor_general_id=-1, player_marker=0),
        ],
    )
    return enumerate_legal_actions(
        state, player_faction_id=PLAYER_FACTION_ID, assigned_general_indices=frozenset(), rules=rules
    )


def _intent(focus: DomesticFocus, *, directives: tuple[CityDirective, ...] = ()) -> StrategicIntent:
    return StrategicIntent(turn=1, default_focus=focus, city_directives=directives)


# ---------------------------------------------------------------------------
# 核心约束：只能挑选，不能编造
# ---------------------------------------------------------------------------


def test_every_decision_action_is_one_of_the_legal_actions_by_identity(rules):
    legal = _build_legal_actions(rules)
    decisions = select_domestic_actions(_intent(DomesticFocus.BALANCED), legal, rules)

    assert decisions  # 这位武将确实有合法动作，不能测个空的
    for decision in decisions:
        assert any(decision.action is a for a in legal), "TacticalDecision.action 必须是 legal_actions 里的同一个对象"


def test_exactly_one_decision_per_general_present_in_legal_actions(rules):
    legal = _build_legal_actions(rules)
    decisions = select_domestic_actions(_intent(DomesticFocus.BALANCED), legal, rules)
    assert {d.general_index for d in decisions} == {GENERAL_A}
    assert len(decisions) == 1  # 只有一位武将，一将一令


# ---------------------------------------------------------------------------
# 重心 -> 动作类型的优先级映射
# ---------------------------------------------------------------------------


def test_economy_focus_prefers_levy_gold(rules):
    legal = _build_legal_actions(rules)
    decisions = select_domestic_actions(_intent(DomesticFocus.ECONOMY), legal, rules)
    assert isinstance(decisions[0].action, LevyGoldAction)


def test_agriculture_focus_prefers_levy_food(rules):
    legal = _build_legal_actions(rules)
    decisions = select_domestic_actions(_intent(DomesticFocus.AGRICULTURE), legal, rules)
    assert isinstance(decisions[0].action, LevyFoodAction)


def test_military_focus_prefers_recruit_troops(rules):
    legal = _build_legal_actions(rules)
    decisions = select_domestic_actions(_intent(DomesticFocus.MILITARY), legal, rules)
    assert isinstance(decisions[0].action, RecruitTroopsAction)


def test_security_focus_prefers_security_patrol(rules):
    legal = _build_legal_actions(rules)
    decisions = select_domestic_actions(_intent(DomesticFocus.SECURITY), legal, rules)
    assert isinstance(decisions[0].action, SecurityPatrolAction)


def test_decision_reason_is_human_readable_and_non_empty(rules):
    legal = _build_legal_actions(rules)
    decisions = select_domestic_actions(_intent(DomesticFocus.SECURITY), legal, rules)
    assert decisions[0].reason
    assert "security" in decisions[0].reason or "治安" in decisions[0].reason


# ---------------------------------------------------------------------------
# city_directives 覆盖 default_focus
# ---------------------------------------------------------------------------


def test_city_directive_overrides_default_focus_for_that_city(rules):
    legal = _build_legal_actions(rules)
    intent = _intent(
        DomesticFocus.ECONOMY, directives=(CityDirective(city_index=OWN_CITY, focus=DomesticFocus.MILITARY),)
    )
    decisions = select_domestic_actions(intent, legal, rules)
    assert isinstance(decisions[0].action, RecruitTroopsAction)
    assert decisions[0].focus == DomesticFocus.MILITARY


def test_city_directive_for_a_different_city_does_not_apply(rules):
    legal = _build_legal_actions(rules)
    intent = _intent(
        DomesticFocus.ECONOMY, directives=(CityDirective(city_index=999, focus=DomesticFocus.MILITARY),)
    )
    decisions = select_domestic_actions(intent, legal, rules)
    assert isinstance(decisions[0].action, LevyGoldAction)  # 没被覆盖，仍然是 default_focus=ECONOMY 的结果


# ---------------------------------------------------------------------------
# build_facility 子类型的重心偏好
# ---------------------------------------------------------------------------


def _facility_only_rules() -> DomesticRulesConfig:
    spec = ActionRuleSpec(
        kind="build_facility", display_name_cn="设施建设",
        requires_own_city=True, requires_facility_slot=True,
        min_general_stamina=RuleValue(value=None, unknown=True),
        gold_cost=RuleValue(value=None, unknown=True),
        food_cost=RuleValue(value=None, unknown=True),
        sub_types={
            "farm": SubTypeSpec(id="farm", display_name_cn="农田"),
            "market": SubTypeSpec(id="market", display_name_cn="市场"),
        },
    )
    return DomesticRulesConfig(label="facility_only_test", verified=True, actions={"build_facility": spec}, raw={})


def test_economy_focus_prefers_market_facility():
    rules = _facility_only_rules()
    legal = _build_legal_actions(rules)
    decisions = select_domestic_actions(_intent(DomesticFocus.ECONOMY), legal, rules)
    action = decisions[0].action
    assert isinstance(action, BuildFacilityAction)
    assert action.facility_type == "market"


def test_agriculture_focus_prefers_farm_facility():
    rules = _facility_only_rules()
    legal = _build_legal_actions(rules)
    decisions = select_domestic_actions(_intent(DomesticFocus.AGRICULTURE), legal, rules)
    action = decisions[0].action
    assert isinstance(action, BuildFacilityAction)
    assert action.facility_type == "farm"


def test_balanced_focus_with_only_facility_actions_picks_one_deterministically():
    rules = _facility_only_rules()
    legal = _build_legal_actions(rules)
    decisions = select_domestic_actions(_intent(DomesticFocus.BALANCED), legal, rules)
    assert isinstance(decisions[0].action, BuildFacilityAction)
    assert decisions[0].action in legal


# ---------------------------------------------------------------------------
# 防御性检查：一位武将不该出现在多座城池的合法动作里
# ---------------------------------------------------------------------------


def test_general_spanning_multiple_cities_raises_tactical_error(rules):
    legal = _build_legal_actions(rules)
    fabricated = legal[0]
    # 手工构造一个"同一武将出现在另一座城"的动作，制造违反假设的输入——
    # 正常的 enumerate_legal_actions() 不会产出这种数据，这里是纯防御性测试。
    from dataclasses import replace

    conflicting = replace(fabricated, city_index=fabricated.city_index + 100)
    with pytest.raises(TacticalError):
        select_domestic_actions(_intent(DomesticFocus.BALANCED), legal + [conflicting], rules)


# ---------------------------------------------------------------------------
# 保底分支：优先级表里一个都没命中时不漏派
# ---------------------------------------------------------------------------


def test_fallback_picks_something_when_priority_table_misses_everything(rules, monkeypatch):
    import san11agent.domestic_tactics as tactics

    legal = _build_legal_actions(rules)  # 这位武将实际拥有多种动作
    # 把 BALANCED 的优先级表临时改成只认一个不存在于 legal 里的动作类型，
    # 逼出保底分支——正常代码路径下这条分支不可达（8种 ActionKind 全覆盖），
    # 这里用 monkeypatch 显式制造那个不可达条件，验证保底逻辑本身是对的。
    from san11agent.legal_actions import ActionKind

    monkeypatch.setitem(tactics._FOCUS_ACTION_PRIORITY, DomesticFocus.BALANCED, ())
    decisions = select_domestic_actions(_intent(DomesticFocus.BALANCED), legal, rules)
    assert len(decisions) == 1
    assert "保底" in decisions[0].reason
    assert any(decisions[0].action is a for a in legal)
