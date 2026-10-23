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

from san11agent.domestic_rules import (
    ActionRuleSpec,
    DomesticRulesConfig,
    RuleValue,
    SubTypeSpec,
    load_domestic_rules,
)
from san11agent.legal_actions import (
    Action,
    ActionKind,
    BuildFacilityAction,
    DiplomacyAction,
    MerchantAction,
    ProduceEquipmentAction,
    RecruitGeneralAction,
    RecruitTroopsAction,
    ResearchTechAction,
    RewardAction,
    SeekTalentAction,
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
GENERAL_LOYALTY_MAXED = 7  # 己方、在 city0、忠诚已满100 -> 不应该成为褒赏目标

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


def _general_full(
    index: int, *, faction_id: int, location: int, stamina: int, loyalty: int = 80
) -> VisibleGeneralFull:
    return VisibleGeneralFull(
        index=index, name=f"g{index}", portrait_id=0, gender=0, debut_year=0,
        birth_year=0, death_year=-1, faction_id=faction_id, identity=0, office=0,
        location=location, special_skill_id=-1,
        display_stats_wound=b"\x00" * 5, display_stats_normal=b"\x00" * 5,
        loyalty=loyalty, merit=0, stamina=stamina, garrison_count=0, health=1, force_id=faction_id,
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
        _general_full(
            GENERAL_LOYALTY_MAXED, faction_id=PLAYER_FACTION_ID, location=OWN_CITY_WITH_SLOT,
            stamina=50, loyalty=100,
        ),
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
    assert general_indices == {GENERAL_AT_CITY0, GENERAL_AT_CITY1, GENERAL_LOYALTY_MAXED}


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


def test_produce_equipment_actions_enumerated_for_each_equipment_type(actions):
    equipment_actions = [a for a in actions if isinstance(a, ProduceEquipmentAction)]
    assert {a.equipment_type for a in equipment_actions} == {"spear", "crossbow"}


def test_produce_equipment_not_gated_by_facility_slot(actions):
    # 跟 build_facility 不同，生產兵裝不需要空余开发用地，两座己方城池都应该产生动作。
    equipment_actions = [a for a in actions if isinstance(a, ProduceEquipmentAction)]
    assert {a.city_index for a in equipment_actions} == {OWN_CITY_WITH_SLOT, OWN_CITY_FULL}


def test_produce_equipment_facility_precondition_is_marked_unverified(actions):
    # 鍛冶廠/廄舍/工房/造船廠这个前置条件目前没有数据模型可以检查，固定标记未验证。
    equipment_actions = [a for a in actions if isinstance(a, ProduceEquipmentAction)]
    assert equipment_actions
    for a in equipment_actions:
        assert "facility_precondition" in a.unverified_constraints


def test_research_tech_actions_enumerated_for_each_tech_type(actions):
    tech_actions = [a for a in actions if isinstance(a, ResearchTechAction)]
    assert {a.tech_type for a in tech_actions} == {"spear_training", "elite_cavalry"}


def test_research_tech_not_gated_by_facility_slot(actions):
    tech_actions = [a for a in actions if isinstance(a, ResearchTechAction)]
    assert {a.city_index for a in tech_actions} == {OWN_CITY_WITH_SLOT, OWN_CITY_FULL}


def test_research_tech_prerequisite_and_points_are_marked_unverified(actions):
    # 研究顺序前置链、势力级"技巧P"资源检查都不存在，固定标记未验证。
    tech_actions = [a for a in actions if isinstance(a, ResearchTechAction)]
    assert tech_actions
    for a in tech_actions:
        assert "tech_prerequisite_chain" in a.unverified_constraints
        assert "tech_points_cost" in a.unverified_constraints


def test_merchant_and_seek_talent_produced_with_no_target(actions):
    assert any(isinstance(a, MerchantAction) for a in actions)
    assert any(isinstance(a, SeekTalentAction) for a in actions)


def test_reward_targets_own_generals_in_same_city_excluding_loyalty_maxed(actions):
    reward_actions = [a for a in actions if isinstance(a, RewardAction)]
    targets_at_city0 = {
        a.target_general_index for a in reward_actions if a.city_index == OWN_CITY_WITH_SLOT
    }
    # city0 只有 GENERAL_AT_CITY0（忠诚80）和 GENERAL_LOYALTY_MAXED（忠诚100）两个
    # 己方在场武将，后者应该被排除；GENERAL_AT_CITY0 可以把自己当目标（手册没有
    # 禁止自我褒赏）。
    assert targets_at_city0 == {GENERAL_AT_CITY0}


def test_recruit_general_targets_enemy_general_regardless_of_acting_city(actions):
    recruit_actions = [a for a in actions if isinstance(a, RecruitGeneralAction)]
    assert recruit_actions
    assert all(a.target_general_index == GENERAL_ENEMY for a in recruit_actions)
    # 两座己方城池的武将都应该能把这个目标枚举出来（目标候选跟发起城池无关）。
    assert {a.city_index for a in recruit_actions} == {OWN_CITY_WITH_SLOT, OWN_CITY_FULL}


def test_recruit_general_eligibility_is_marked_unverified(actions):
    recruit_actions = [a for a in actions if isinstance(a, RecruitGeneralAction)]
    assert recruit_actions
    for a in recruit_actions:
        assert "recruit_general_eligibility" in a.unverified_constraints


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
    # 2026-08-18 levy_gold/levy_food 两个 ActionKind 已删除（游戏里没有'征收'指令）。
    # 2026-08-20 新增 produce_equipment（2种兵装）、research_tech（2种技巧）、
    # merchant/seek_talent（简单动作，+2）、reward（同城己方武将，忠诚<100）、
    # recruit_general（GENERAL_ENEMY 这一个目标）。同时新增了 GENERAL_LOYALTY_MAXED
    # （city0 的第二个己方在场武将，忠诚100，用来测试 reward 的排除逻辑），
    # 城0现在有2个行动武将，城1还是1个。
    # 每个 city0 的行动武将：2(设施)+2(兵装)+2(技巧)+5(简单动作:徵兵/訓練/巡察/
    #   商人/探索人材)+1(褒赏，只有GENERAL_AT_CITY0忠诚<100合格)+1(登庸,目标
    #   GENERAL_ENEMY)+4(外交 2子类型x2势力)+1(计略) = 18，共2个武将 = 36
    # city1 的行动武将（开发位已满，0种设施）：0+2+2+5+1(褒赏自己)+1+4+1 = 16
    assert len(actions) == 52


def test_unknown_cost_rules_never_block_but_are_recorded(actions):
    recruit_actions = [a for a in actions if isinstance(a, RecruitTroopsAction)]
    assert recruit_actions
    for a in recruit_actions:
        assert set(a.unverified_constraints) == {
            "min_general_stamina", "gold_cost", "food_cost", "general_action_state",
            "action_points_cost", "action_points_balance",
        }


def test_general_action_state_blocks_acted_and_marks_unknown(rules):
    state = _build_state()
    general = next(g for g in state.generals if g.index == GENERAL_AT_CITY0)
    for value in (True, False, None):
        general.has_acted = value
        candidates = [a for a in enumerate_legal_actions(state, PLAYER_FACTION_ID, frozenset(), rules)
                      if a.general_index == general.index]
        if value is True:
            assert candidates == []  # Stamina remains positive and caller history is empty.
        else:
            assert candidates
            assert all(("general_action_state" in a.unverified_constraints) == (value is None)
                       for a in candidates)


def _patrol_only_with_effective_cost(rules, *, effective=True):
    from dataclasses import replace
    spec = replace(
        rules.action("security_patrol"),
        action_points_cost=RuleValue(20, unknown=False),
        effective_action_points_cost=RuleValue(20, unknown=not effective),
    )
    return replace(rules, actions={"security_patrol": spec})


@pytest.mark.parametrize("points, allowed", [(0, False), (19, False), (20, True), (35, True)])
def test_patrol_uses_effective_cost_and_force_balance(rules, points, allowed):
    from san11agent.visible_state import VisibleForce
    state = _build_state()
    state.forces = [VisibleForce(0, PLAYER_FACTION_ID, points)]
    actions = enumerate_legal_actions(state, PLAYER_FACTION_ID, frozenset(),
                                     _patrol_only_with_effective_cost(rules))
    assert bool(actions) is allowed
    assert all("action_points_cost" not in a.unverified_constraints and
               "action_points_balance" not in a.unverified_constraints for a in actions)
    assert all("patrol_preconditions" in a.unverified_constraints for a in actions)


def test_base_price_is_not_a_verified_effective_cost(rules):
    from san11agent.visible_state import VisibleForce
    state = _build_state()
    state.forces = [VisibleForce(0, PLAYER_FACTION_ID, 0)]
    actions = enumerate_legal_actions(state, PLAYER_FACTION_ID, frozenset(),
                                     _patrol_only_with_effective_cost(rules, effective=False))
    assert actions  # Research candidates, not certified executable instructions.
    assert all("action_points_cost" in a.unverified_constraints for a in actions)


def test_city_uses_its_own_force_budget_not_other_own_force(rules):
    from san11agent.visible_state import VisibleForce
    state = _build_state()
    state.cities[1].force_id = 1
    state.forces = [VisibleForce(0, PLAYER_FACTION_ID, 19), VisibleForce(1, PLAYER_FACTION_ID, 20)]
    actions = enumerate_legal_actions(state, PLAYER_FACTION_ID, frozenset(),
                                     _patrol_only_with_effective_cost(rules))
    assert actions
    assert {a.city_index for a in actions} == {OWN_CITY_FULL}


@pytest.mark.parametrize("force_kind", ["missing", "unknown", "enemy", "duplicate"])
def test_missing_or_ambiguous_own_force_balance_is_marked(rules, force_kind):
    from san11agent.visible_state import VisibleForce
    state = _build_state()
    state.forces = {
        "missing": [],
        "unknown": [VisibleForce(0, PLAYER_FACTION_ID, None)],
        "enemy": [VisibleForce(0, ENEMY_FACTION_ID, 255)],
        "duplicate": [VisibleForce(0, PLAYER_FACTION_ID, 20), VisibleForce(0, PLAYER_FACTION_ID, 200)],
    }[force_kind]
    actions = enumerate_legal_actions(state, PLAYER_FACTION_ID, frozenset(),
                                     _patrol_only_with_effective_cost(rules))
    assert actions
    assert all("action_points_balance" in a.unverified_constraints for a in actions)


def test_same_force_cities_get_alternatives_not_separate_reserved_budgets(rules):
    from san11agent.visible_state import VisibleForce
    state = _build_state()
    state.forces = [VisibleForce(0, PLAYER_FACTION_ID, 20)]
    before = state.forces[0].action_points
    actions = enumerate_legal_actions(state, PLAYER_FACTION_ID, frozenset(),
                                     _patrol_only_with_effective_cost(rules))
    assert {a.city_index for a in actions} == {OWN_CITY_WITH_SLOT, OWN_CITY_FULL}
    assert state.forces[0].action_points == before  # Enumeration does not spend or reserve.


@pytest.mark.parametrize("security, allowed", [(99, True), (100, False)])
def test_patrol_requires_security_below_native_cap(rules, security, allowed):
    from san11agent.visible_state import VisibleForce
    state = _build_state()
    state.cities = state.cities[:1]
    state.cities[0].security = security
    state.forces = [VisibleForce(0, PLAYER_FACTION_ID, 20)]
    actions = enumerate_legal_actions(state, PLAYER_FACTION_ID, frozenset(),
                                     _patrol_only_with_effective_cost(rules))
    assert bool(actions) is allowed


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
# 子类型金价：设施/兵装/技巧/外交各子类型的 gold_cost 必须真正参与过滤。
# 动作级 build_facility.gold_cost 等仍是 unknown，不能因此掩盖已知子类型价格。
# ---------------------------------------------------------------------------


def _rules_with_subtypes(
    kind: str,
    sub_types: dict[str, SubTypeSpec],
    *,
    requires_facility_slot: bool = False,
) -> DomesticRulesConfig:
    spec = ActionRuleSpec(
        kind=kind,
        display_name_cn=kind,
        requires_own_city=True,
        requires_facility_slot=requires_facility_slot,
        min_general_stamina=RuleValue(value=0, unknown=False),
        gold_cost=RuleValue(value=None, unknown=True),
        food_cost=RuleValue(value=0, unknown=False),
        sub_types=sub_types,
    )
    return DomesticRulesConfig(label="subtype-cost", verified=True, actions={kind: spec}, raw={})


def _subtype(sub_id: str, gold: int | None, *, unknown: bool = False) -> SubTypeSpec:
    return SubTypeSpec(
        id=sub_id,
        display_name_cn=sub_id,
        gold_cost=RuleValue(value=gold, unknown=unknown),
    )


@pytest.mark.parametrize(
    ("gold", "expected"),
    [
        (49, set()),
        (50, {"cheap"}),
        (199, {"cheap"}),
        (200, {"cheap", "expensive"}),
    ],
)
def test_facility_subtype_gold_cost_filters_by_known_price(gold, expected):
    rules = _rules_with_subtypes(
        "build_facility",
        {"cheap": _subtype("cheap", 50), "expensive": _subtype("expensive", 200)},
        requires_facility_slot=True,
    )
    result = enumerate_legal_actions(
        _minimal_state_single_general(stamina=50, gold=gold),
        player_faction_id=PLAYER_FACTION_ID, assigned_general_indices=frozenset(), rules=rules,
    )
    facility_actions = [a for a in result if isinstance(a, BuildFacilityAction)]
    assert {a.facility_type for a in facility_actions} == expected
    assert all("gold_cost" not in a.unverified_constraints for a in facility_actions)


def test_equipment_subtype_gold_cost_filters_by_known_price():
    rules = _rules_with_subtypes(
        "produce_equipment",
        {"spear": _subtype("spear", 700), "warship": _subtype("warship", 2000)},
    )
    result = enumerate_legal_actions(
        _minimal_state_single_general(stamina=50, gold=700),
        player_faction_id=PLAYER_FACTION_ID, assigned_general_indices=frozenset(), rules=rules,
    )
    equipment_actions = [a for a in result if isinstance(a, ProduceEquipmentAction)]
    assert {a.equipment_type for a in equipment_actions} == {"spear"}
    assert all("gold_cost" not in a.unverified_constraints for a in equipment_actions)
    assert all("facility_precondition" in a.unverified_constraints for a in equipment_actions)


def test_tech_subtype_gold_cost_filters_by_known_price():
    rules = _rules_with_subtypes(
        "research_tech",
        {"level1": _subtype("level1", 1000), "level2": _subtype("level2", 2000)},
    )
    result = enumerate_legal_actions(
        _minimal_state_single_general(stamina=50, gold=1000),
        player_faction_id=PLAYER_FACTION_ID, assigned_general_indices=frozenset(), rules=rules,
    )
    tech_actions = [a for a in result if isinstance(a, ResearchTechAction)]
    assert {a.tech_type for a in tech_actions} == {"level1"}
    assert all("gold_cost" not in a.unverified_constraints for a in tech_actions)
    assert all("tech_prerequisite_chain" in a.unverified_constraints for a in tech_actions)


def test_diplomacy_subtype_gold_cost_filters_by_known_minimum():
    rules = _rules_with_subtypes(
        "diplomacy",
        {"goodwill": _subtype("goodwill", 1000), "break_alliance": _subtype("break_alliance", 0)},
    )
    state = _build_state()
    state.cities[OWN_CITY_WITH_SLOT].gold = 500
    actions = [
        a for a in enumerate_legal_actions(
            state, PLAYER_FACTION_ID, frozenset(), rules,
        )
        if isinstance(a, DiplomacyAction) and a.city_index == OWN_CITY_WITH_SLOT
    ]
    assert {a.diplomacy_type for a in actions} == {"break_alliance"}

    state.cities[OWN_CITY_WITH_SLOT].gold = 1000
    actions = [
        a for a in enumerate_legal_actions(
            state, PLAYER_FACTION_ID, frozenset(), rules,
        )
        if isinstance(a, DiplomacyAction) and a.city_index == OWN_CITY_WITH_SLOT
    ]
    assert {a.diplomacy_type for a in actions} == {"goodwill", "break_alliance"}
    assert all("gold_cost" not in a.unverified_constraints for a in actions)


def test_unknown_subtype_gold_cost_keeps_candidate_with_marker():
    rules = _rules_with_subtypes(
        "build_facility",
        {"unknown_price": _subtype("unknown_price", None, unknown=True)},
        requires_facility_slot=True,
    )
    result = enumerate_legal_actions(
        _minimal_state_single_general(stamina=50, gold=0),
        player_faction_id=PLAYER_FACTION_ID, assigned_general_indices=frozenset(), rules=rules,
    )
    facility_actions = [a for a in result if isinstance(a, BuildFacilityAction)]
    assert len(facility_actions) == 1
    assert "gold_cost" in facility_actions[0].unverified_constraints


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


def test_describe_action_includes_equipment_display_name(actions, rules):
    equipment_action = next(a for a in actions if isinstance(a, ProduceEquipmentAction))
    text = describe_action(equipment_action, rules)
    assert "生產兵裝" in text
    assert equipment_action.equipment_type in {"spear", "crossbow"}
    assert ("槍" in text) or ("弩" in text)


def test_describe_action_includes_tech_display_name(actions, rules):
    tech_action = next(a for a in actions if isinstance(a, ResearchTechAction))
    text = describe_action(tech_action, rules)
    assert "研究技巧" in text
    assert tech_action.tech_type in {"spear_training", "elite_cavalry"}
    assert ("鍛鍊槍兵" in text) or ("精銳騎兵" in text)


def test_describe_action_includes_reward_and_recruit_general_targets(actions, rules):
    reward_action = next(a for a in actions if isinstance(a, RewardAction))
    text = describe_action(reward_action, rules)
    assert "褒賞" in text
    assert str(reward_action.target_general_index) in text

    recruit_action = next(a for a in actions if isinstance(a, RecruitGeneralAction))
    text = describe_action(recruit_action, rules)
    assert "登庸武將" in text
    assert str(recruit_action.target_general_index) in text
