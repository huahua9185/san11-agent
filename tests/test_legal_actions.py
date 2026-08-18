"""M4 LegalActions 的核心测试。

刻意不经过 M1(memory/perception)/M2(boundary.filter_game_state) 链路——直接
手工构造 VisibleGameState fixture，让 LegalActions 测试完全独立于"怎么从内存
读出/过滤出这份状态"，跟 M2 的 test_boundary.py 是同一种做法。

本文件里最重要的一组测试是"架构守卫"：LegalActions 必须只建立在 M2 的
VisibleGameState 之上，不能碰完整 GameState——这是项目规格明确要求的实验
前提（AI 只能用人类玩家在界面上能看到的信息来判断自己能做什么），不是普通的
代码风格偏好。
"""
from __future__ import annotations

import inspect
import typing
from pathlib import Path

import pytest

from san11agent.domestic_rules import ActionRuleSpec, DomesticRulesConfig, RuleValue, load_domestic_rules
from san11agent.legal_actions import (
    Action,
    ActionKind,
    BuildFacilityAction,
    DiplomacyAction,
    RecruitTroopsAction,
    SecurityPatrolAction,
    StratagemAction,
    TrainTroopsAction,
    default_is_general_in_city,
    describe_action,
    enumerate_legal_actions,
)
from san11agent.visible_state import (
    VisibleCityDetail,
    VisibleCitySummary,
    VisibleFactionPublic,
    VisibleGameState,
    VisibleGeneralFull,
    VisibleGeneralPublic,
    VisibleGlobalState,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_RULES = REPO_ROOT / "tests" / "fixtures" / "domestic_rules_test.json"

PLAYER_FACTION_ID = 0
ENEMY_FACTION_ID = 1
UNKNOWN_OWNERSHIP_MARKER = None

# 武将 index 语义（见下方 _build_state）：
GENERAL_AT_CITY0 = 0  # 己方、在 city0、体力充足 -> 应该产生动作
GENERAL_AT_CITY1 = 1  # 己方、在 city1（开发用地已满）、体力充足 -> 应该产生动作（无设施建设）
GENERAL_ELSEWHERE = 2  # 己方、location 不匹配任何己方城池 -> 不应该产生动作
GENERAL_NO_STAMINA = 3  # 己方、在 city0，但体力为 0 -> 不应该产生动作
GENERAL_ALREADY_ASSIGNED = 4  # 己方、在 city0、体力充足，但本回合已被指派 -> 不应该产生动作
GENERAL_ENEMY = 5  # 非己方，只有 Public 档 -> 不应该产生动作

OWN_CITY_WITH_SLOT = 0
OWN_CITY_FULL = 1
ENEMY_CITY_KNOWN = 2
CITY_UNKNOWN_OWNERSHIP = 3


def _global_state() -> VisibleGlobalState:
    return VisibleGlobalState(
        scenario_id=1, start_year=190, start_month=1, start_day=1,
        emperor_general_id=0, difficulty=1, death_setting=0, current_xun=1,
        current_year=190, current_month=1, current_day=1, phase=1,
    )


def _own_city(index: int, *, gold: int, food: int, dev_count: int, developed: int) -> VisibleCityDetail:
    return VisibleCityDetail(
        index=index, name=f"city{index}", province=0, adjacent_cities=[],
        faction_id=PLAYER_FACTION_ID, map_x=0, map_y=0,
        governor_general_id=0, force_id=0, troop_capacity=100, troops=50,
        gold=gold, food=food, trade_price=10, has_merchant=1, morale=80,
        security=80, policy=0, target=0,
        development_land_count=dev_count, developed_land_count=developed,
        domestic_land_x=10, domestic_land_y=20,
    )


def _general_full(index: int, *, faction_id: int, location: int, stamina: int) -> VisibleGeneralFull:
    return VisibleGeneralFull(
        index=index, name=f"g{index}", portrait_id=0, gender=0, debut_year=0,
        birth_year=0, death_year=-1, faction_id=faction_id, identity=0, office=0,
        location=location, special_skill_id=-1,
        display_stats_wound=b"\x00" * 5, display_stats_normal=b"\x00" * 5,
        loyalty=80, merit=0, stamina=stamina, garrison_count=0, health=1, force_id=faction_id,
    )


def _build_state() -> VisibleGameState:
    cities = [
        _own_city(OWN_CITY_WITH_SLOT, gold=500, food=8000, dev_count=5, developed=3),
        _own_city(OWN_CITY_FULL, gold=1000, food=100, dev_count=4, developed=4),
        VisibleCitySummary(
            index=ENEMY_CITY_KNOWN, name="enemy_city", province=1,
            adjacent_cities=[], faction_id=ENEMY_FACTION_ID, map_x=50, map_y=50,
        ),
        VisibleCitySummary(
            index=CITY_UNKNOWN_OWNERSHIP, name="unknown_city", province=2,
            adjacent_cities=[], faction_id=UNKNOWN_OWNERSHIP_MARKER, map_x=None, map_y=None,
        ),
    ]
    generals = [
        _general_full(GENERAL_AT_CITY0, faction_id=PLAYER_FACTION_ID, location=OWN_CITY_WITH_SLOT, stamina=50),
        _general_full(GENERAL_AT_CITY1, faction_id=PLAYER_FACTION_ID, location=OWN_CITY_FULL, stamina=50),
        _general_full(GENERAL_ELSEWHERE, faction_id=PLAYER_FACTION_ID, location=99, stamina=100),
        _general_full(GENERAL_NO_STAMINA, faction_id=PLAYER_FACTION_ID, location=OWN_CITY_WITH_SLOT, stamina=0),
        _general_full(GENERAL_ALREADY_ASSIGNED, faction_id=PLAYER_FACTION_ID, location=OWN_CITY_WITH_SLOT, stamina=50),
        VisibleGeneralPublic(
            index=GENERAL_ENEMY, name="enemy_general", portrait_id=0, gender=0, debut_year=0,
            birth_year=0, death_year=-1, faction_id=ENEMY_FACTION_ID, identity=0, office=0,
            location=0, special_skill_id=-1,
            display_stats_wound=b"\x00" * 5, display_stats_normal=b"\x00" * 5,
        ),
    ]
    factions = [
        VisibleFactionPublic(index=PLAYER_FACTION_ID, ruler_general_id=0, advisor_general_id=-1, player_marker=1),
        VisibleFactionPublic(index=ENEMY_FACTION_ID, ruler_general_id=5, advisor_general_id=-1, player_marker=0),
        VisibleFactionPublic(index=2, ruler_general_id=-1, advisor_general_id=-1, player_marker=0),
    ]
    return VisibleGameState(global_state=_global_state(), generals=generals, cities=cities, troops=[], factions=factions)


@pytest.fixture()
def rules() -> DomesticRulesConfig:
    return load_domestic_rules(TEST_RULES)


@pytest.fixture()
def actions(rules) -> list[Action]:
    return enumerate_legal_actions(
        _build_state(),
        player_faction_id=PLAYER_FACTION_ID,
        assigned_general_indices=frozenset({GENERAL_ALREADY_ASSIGNED}),
        rules=rules,
    )


# ---------------------------------------------------------------------------
# 架构守卫：LegalActions 必须只建立在 VisibleGameState 之上
# ---------------------------------------------------------------------------


def test_legal_actions_module_does_not_bind_full_game_state_types():
    import san11agent.legal_actions as la

    for name in ("GameState", "General", "City", "Troop", "Faction", "GlobalState"):
        assert not hasattr(la, name), f"legal_actions.py 不应该引用完整 GameState 的 {name}"


def test_legal_actions_module_only_imports_from_visible_state_and_domestic_rules():
    import ast

    module_path = Path(inspect.getfile(enumerate_legal_actions))
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    from_imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "game_state" not in {(m or "").rsplit(".", 1)[-1] for m in from_imports}


def test_enumerate_legal_actions_state_param_is_visible_game_state():
    hints = typing.get_type_hints(enumerate_legal_actions)
    assert hints["state"] is VisibleGameState


def test_own_general_without_full_tier_is_defensively_skipped(rules):
    """防御性测试：即便某个己方武将因为上游 bug 只带 Public 档（没有体力等字段），
    LegalActions 也必须靠 isinstance() 拒绝它，而不是尝试访问不存在的字段
    崩溃、或者悄悄当作"体力无限"处理。正常情况下 boundary.py 不会产出这种
    数据，这里是纯防御性验证。
    """
    state = _build_state()
    state.generals.append(
        VisibleGeneralPublic(
            index=6, name="leaked_public_tier_own_general", portrait_id=0, gender=0, debut_year=0,
            birth_year=0, death_year=-1, faction_id=PLAYER_FACTION_ID, identity=0, office=0,
            location=OWN_CITY_WITH_SLOT, special_skill_id=-1,
            display_stats_wound=b"\x00" * 5, display_stats_normal=b"\x00" * 5,
        )
    )
    result = enumerate_legal_actions(
        state, player_faction_id=PLAYER_FACTION_ID,
        assigned_general_indices=frozenset(), rules=rules,
    )
    assert all(a.general_index != 6 for a in result)


# ---------------------------------------------------------------------------
# 结构性约束：武将是否已指派 / 体力 / 是否在该城 / 城池是否己方
# ---------------------------------------------------------------------------


def test_only_eligible_generals_produce_actions(actions):
    general_indices = {a.general_index for a in actions}
    assert general_indices == {GENERAL_AT_CITY0, GENERAL_AT_CITY1}


def test_general_elsewhere_produces_no_actions(actions):
    assert all(a.general_index != GENERAL_ELSEWHERE for a in actions)


def test_general_with_zero_stamina_produces_no_actions(actions):
    assert all(a.general_index != GENERAL_NO_STAMINA for a in actions)


def test_already_assigned_general_produces_no_actions(actions):
    assert all(a.general_index != GENERAL_ALREADY_ASSIGNED for a in actions)


def test_enemy_general_produces_no_actions(actions):
    assert all(a.general_index != GENERAL_ENEMY for a in actions)


def test_actions_only_target_own_cities_as_acting_city(actions):
    city_indices = {a.city_index for a in actions}
    assert city_indices == {OWN_CITY_WITH_SLOT, OWN_CITY_FULL}


def test_full_city_produces_no_build_facility_action(actions):
    facility_actions = [a for a in actions if isinstance(a, BuildFacilityAction)]
    assert all(a.city_index != OWN_CITY_FULL for a in facility_actions)
    assert all(a.city_index == OWN_CITY_WITH_SLOT for a in facility_actions)


def test_city_with_slot_produces_build_facility_actions_for_each_facility_type(actions):
    facility_actions = [a for a in actions if isinstance(a, BuildFacilityAction)]
    assert {a.facility_type for a in facility_actions} == {"farm", "market"}


def test_build_facility_target_tile_is_marked_unverified(actions):
    facility_actions = [a for a in actions if isinstance(a, BuildFacilityAction)]
    assert facility_actions
    for a in facility_actions:
        assert a.target_tile == (10, 20)
        assert "target_tile_precision" in a.unverified_constraints


# ---------------------------------------------------------------------------
# 外交 / 计略 目标枚举
# ---------------------------------------------------------------------------


def test_diplomacy_never_targets_own_faction(actions):
    diplomacy_actions = [a for a in actions if isinstance(a, DiplomacyAction)]
    assert diplomacy_actions
    assert all(a.target_faction_index != PLAYER_FACTION_ID for a in diplomacy_actions)


def test_diplomacy_targets_all_other_factions_with_all_sub_types(actions):
    diplomacy_actions = [a for a in actions if isinstance(a, DiplomacyAction) and a.city_index == OWN_CITY_WITH_SLOT]
    targets = {(a.target_faction_index, a.diplomacy_type) for a in diplomacy_actions}
    assert targets == {(1, "alliance"), (1, "ceasefire"), (2, "alliance"), (2, "ceasefire")}


def test_stratagem_only_targets_cities_with_known_enemy_ownership(actions):
    stratagem_actions = [a for a in actions if isinstance(a, StratagemAction)]
    assert stratagem_actions
    assert all(a.target_city_index == ENEMY_CITY_KNOWN for a in stratagem_actions)
    assert all(a.target_city_index != CITY_UNKNOWN_OWNERSHIP for a in stratagem_actions)


def test_stratagem_never_targets_own_city(actions):
    stratagem_actions = [a for a in actions if isinstance(a, StratagemAction)]
    assert all(a.target_city_index not in (OWN_CITY_WITH_SLOT, OWN_CITY_FULL) for a in stratagem_actions)


# ---------------------------------------------------------------------------
# 简单动作种类（征兵/训练/治安/征收）+ 总数核对
# ---------------------------------------------------------------------------


def test_simple_action_kinds_present_for_eligible_generals(actions):
    kinds_at_city0 = {type(a) for a in actions if a.general_index == GENERAL_AT_CITY0}
    assert {RecruitTroopsAction, TrainTroopsAction, SecurityPatrolAction} <= kinds_at_city0


def test_total_action_count_matches_expected_combinatorics(actions):
    # 2026-08-18 levy_gold/levy_food 两个 ActionKind 已删除（游戏里没有'征收'指令），
    # 简单动作从 5 项减为 3 项（徵兵/訓練/巡察），总数相应从 22 减为 16。
    # city0（有空闲开发位，2种设施）：2(设施) + 3(简单动作) + 4(外交 2子类型x2势力) + 1(计略 1子类型x1合法目标) = 10
    # city1（开发位已满，0种设施）：0 + 3 + 4 + 1 = 8
    assert len(actions) == 18


def test_unknown_cost_rules_never_block_but_are_recorded(actions):
    recruit_actions = [a for a in actions if isinstance(a, RecruitTroopsAction)]
    assert recruit_actions
    for a in recruit_actions:
        assert set(a.unverified_constraints) == {"min_general_stamina", "gold_cost", "food_cost"}


# ---------------------------------------------------------------------------
# 资源阈值一旦在规则表里明确给出，就必须真正拦截——用独立构造的最小规则表测试，
# 不依赖上面那份"全部 unknown"的 fixture。
# ---------------------------------------------------------------------------


def _minimal_state_single_general(stamina: int, gold: int) -> VisibleGameState:
    city = _own_city(0, gold=gold, food=1000, dev_count=1, developed=0)
    general = _general_full(0, faction_id=PLAYER_FACTION_ID, location=0, stamina=stamina)
    faction = VisibleFactionPublic(index=PLAYER_FACTION_ID, ruler_general_id=0, advisor_general_id=-1, player_marker=1)
    return VisibleGameState(global_state=_global_state(), generals=[general], cities=[city], troops=[], factions=[faction])


def _rules_with(kind: str, *, min_stamina: RuleValue, gold_cost: RuleValue) -> DomesticRulesConfig:
    spec = ActionRuleSpec(
        kind=kind, display_name_cn=kind, requires_own_city=True, requires_facility_slot=False,
        min_general_stamina=min_stamina, gold_cost=gold_cost, food_cost=RuleValue(value=None, unknown=True),
    )
    return DomesticRulesConfig(label="custom", verified=True, actions={kind: spec}, raw={})


def test_known_min_stamina_threshold_filters_out_insufficient_general():
    rules = _rules_with(
        "recruit_troops",
        min_stamina=RuleValue(value=60, unknown=False),
        gold_cost=RuleValue(value=None, unknown=True),
    )
    result = enumerate_legal_actions(
        _minimal_state_single_general(stamina=50, gold=500),
        player_faction_id=PLAYER_FACTION_ID, assigned_general_indices=frozenset(), rules=rules,
    )
    assert result == []


def test_known_min_stamina_threshold_allows_sufficient_general():
    rules = _rules_with(
        "recruit_troops",
        min_stamina=RuleValue(value=30, unknown=False),
        gold_cost=RuleValue(value=None, unknown=True),
    )
    result = enumerate_legal_actions(
        _minimal_state_single_general(stamina=50, gold=500),
        player_faction_id=PLAYER_FACTION_ID, assigned_general_indices=frozenset(), rules=rules,
    )
    assert len(result) == 1
    assert "min_general_stamina" not in result[0].unverified_constraints
    assert "gold_cost" in result[0].unverified_constraints  # 金钱阈值仍未知


def test_known_gold_cost_threshold_filters_out_insufficient_city():
    rules = _rules_with(
        "recruit_troops",
        min_stamina=RuleValue(value=None, unknown=True),
        gold_cost=RuleValue(value=99999, unknown=False),
    )
    result = enumerate_legal_actions(
        _minimal_state_single_general(stamina=50, gold=500),
        player_faction_id=PLAYER_FACTION_ID, assigned_general_indices=frozenset(), rules=rules,
    )
    assert result == []


def test_known_gold_cost_threshold_allows_sufficient_city():
    rules = _rules_with(
        "recruit_troops",
        min_stamina=RuleValue(value=None, unknown=True),
        gold_cost=RuleValue(value=100, unknown=False),
    )
    result = enumerate_legal_actions(
        _minimal_state_single_general(stamina=50, gold=500),
        player_faction_id=PLAYER_FACTION_ID, assigned_general_indices=frozenset(), rules=rules,
    )
    assert len(result) == 1


# ---------------------------------------------------------------------------
# is_general_in_city 默认假设 + 可覆盖
# ---------------------------------------------------------------------------


def test_default_is_general_in_city_uses_location_equals_city_index():
    city = _own_city(3, gold=0, food=0, dev_count=0, developed=0)
    matching = _general_full(0, faction_id=PLAYER_FACTION_ID, location=3, stamina=50)
    not_matching = _general_full(1, faction_id=PLAYER_FACTION_ID, location=4, stamina=50)
    assert default_is_general_in_city(matching, city) is True
    assert default_is_general_in_city(not_matching, city) is False


def test_custom_is_general_in_city_predicate_is_honored(rules):
    state = _build_state()
    # 自定义预测：把"在别处"的武将也当作在 city0，验证注入点确实生效。
    result = enumerate_legal_actions(
        state, player_faction_id=PLAYER_FACTION_ID,
        assigned_general_indices=frozenset({GENERAL_ALREADY_ASSIGNED}),
        rules=rules,
        is_general_in_city=lambda g, c: g.index == GENERAL_ELSEWHERE and c.index == OWN_CITY_WITH_SLOT,
    )
    assert any(a.general_index == GENERAL_ELSEWHERE for a in result)


# ---------------------------------------------------------------------------
# 可观测性：describe_action
# ---------------------------------------------------------------------------


def test_describe_action_produces_readable_summary(actions, rules):
    build_action = next(a for a in actions if isinstance(a, BuildFacilityAction))
    text = describe_action(build_action, rules)
    assert "设施建设" in text
    assert str(build_action.general_index) in text
    assert "未验证" in text
