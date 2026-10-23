"""巡察后置验证器测试。

全部离线：只构造 VisibleGameState 前后快照，不读真实内存、不发送输入。
"""
from __future__ import annotations

import pytest

from san11agent.legal_actions import SecurityPatrolAction
from san11agent.patrol_verification import (
    CheckStatus,
    PatrolExpectation,
    VerificationStatus,
    capture_patrol_snapshot,
    verify_patrol_action,
)
from san11agent.visible_state import (
    VisibleCityDetail,
    VisibleCitySummary,
    VisibleForce,
    VisibleGameState,
    VisibleGeneralFull,
    VisibleGlobalState,
)

PLAYER_FACTION_ID = 0
CITY_INDEX = 12
FORCE_INDEX = 0
GENERAL_INDEX = 343


def _global_state() -> VisibleGlobalState:
    return VisibleGlobalState(
        scenario_id=1, start_year=190, start_month=1, start_day=1,
        emperor_general_id=0, difficulty=1, death_setting=0, current_xun=1,
        current_year=190, current_month=1, current_day=1, phase=1,
    )


def _city(
    *, gold: int = 4200, security: int = 80, force_id: int = FORCE_INDEX
) -> VisibleCityDetail:
    return VisibleCityDetail(
        index=CITY_INDEX,
        name="陈留",
        province=0,
        adjacent_cities=[],
        faction_id=PLAYER_FACTION_ID,
        map_x=0,
        map_y=0,
        governor_general_id=GENERAL_INDEX,
        force_id=force_id,
        troop_capacity=100000,
        troops=18000,
        gold=gold,
        food=37550,
        trade_price=10,
        has_merchant=1,
        morale=80,
        security=security,
        policy=0,
        target=0,
        development_land_count=12,
        developed_land_count=4,
        domestic_land_x=103,
        domestic_land_y=74,
    )


def _general(
    index: int = GENERAL_INDEX, *, has_acted: bool | None = False
) -> VisibleGeneralFull:
    return VisibleGeneralFull(
        index=index,
        name=f"g{index}",
        portrait_id=0,
        gender=0,
        debut_year=0,
        birth_year=0,
        death_year=-1,
        faction_id=PLAYER_FACTION_ID,
        identity=3,
        office=0,
        location=CITY_INDEX,
        special_skill_id=-1,
        display_stats_wound=b"\x00" * 5,
        display_stats_normal=b"\x00" * 5,
        loyalty=100,
        merit=0,
        stamina=100,
        garrison_count=0,
        health=1,
        force_id=FORCE_INDEX,
        has_acted=has_acted,
    )


def _state(
    *,
    action_points: int | None = 55,
    gold: int = 4200,
    security: int = 80,
    has_acted: bool | None = False,
    with_force: bool = True,
    full_city: bool = True,
) -> VisibleGameState:
    city = (
        _city(gold=gold, security=security)
        if full_city
        else VisibleCitySummary(
            index=CITY_INDEX,
            name="陈留",
            province=0,
            adjacent_cities=[],
            faction_id=PLAYER_FACTION_ID,
            map_x=0,
            map_y=0,
        )
    )
    return VisibleGameState(
        global_state=_global_state(),
        generals=[_general(has_acted=has_acted)],
        cities=[city],
        forces=[VisibleForce(FORCE_INDEX, PLAYER_FACTION_ID, action_points)] if with_force else [],
        factions=[],
        troops=[],
    )


def _action() -> SecurityPatrolAction:
    return SecurityPatrolAction(general_index=GENERAL_INDEX, city_index=CITY_INDEX)


def test_confirmed_patrol_effect():
    before = _state()
    after = _state(action_points=35, gold=4100, security=91, has_acted=True)

    result = verify_patrol_action(before, after, _action())

    assert result.status is VerificationStatus.CONFIRMED
    assert result.check("action_points").status is CheckStatus.PASS
    assert result.check("gold").status is CheckStatus.PASS
    assert result.check("security").status is CheckStatus.PASS
    assert result.check(f"general[{GENERAL_INDEX}].has_acted").status is CheckStatus.PASS
    assert result.to_dict()["status"] == "confirmed"


def test_action_points_shortfall_fails():
    before = _state()
    after = _state(action_points=34, gold=4100, security=91, has_acted=True)

    result = verify_patrol_action(before, after, _action())

    assert result.status is VerificationStatus.FAILED
    assert result.check("action_points").status is CheckStatus.FAIL


def test_gold_shortfall_fails():
    before = _state()
    after = _state(action_points=35, gold=4099, security=91, has_acted=True)

    result = verify_patrol_action(before, after, _action())

    assert result.status is VerificationStatus.FAILED
    assert result.check("gold").status is CheckStatus.FAIL


def test_security_not_increasing_fails():
    before = _state()
    after = _state(action_points=35, gold=4100, security=80, has_acted=True)

    result = verify_patrol_action(before, after, _action())

    assert result.status is VerificationStatus.FAILED
    assert result.check("security").status is CheckStatus.FAIL


def test_general_still_not_acted_fails():
    before = _state()
    after = _state(action_points=35, gold=4100, security=91, has_acted=False)

    result = verify_patrol_action(before, after, _action())

    assert result.status is VerificationStatus.FAILED
    assert result.check(f"general[{GENERAL_INDEX}].has_acted").status is CheckStatus.FAIL


def test_missing_force_balance_is_inconclusive():
    before = _state(with_force=False)
    after = _state(action_points=35, gold=4100, security=91, has_acted=True, with_force=False)

    result = verify_patrol_action(before, after, _action())

    assert result.status is VerificationStatus.INCONCLUSIVE
    assert result.check("action_points").status is CheckStatus.UNKNOWN


def test_summary_city_is_inconclusive():
    before = _state(full_city=False)
    after = _state(action_points=35, gold=4100, security=91, has_acted=True, full_city=False)

    result = verify_patrol_action(before, after, _action())

    assert result.status is VerificationStatus.INCONCLUSIVE
    assert result.check("gold").status is CheckStatus.UNKNOWN
    assert result.check("security").status is CheckStatus.UNKNOWN


def test_actor_already_acted_before_is_inconclusive():
    before = _state(has_acted=True)
    after = _state(action_points=35, gold=4100, security=91, has_acted=True)

    result = verify_patrol_action(before, after, _action())

    assert result.status is VerificationStatus.INCONCLUSIVE
    assert result.check(f"general[{GENERAL_INDEX}].has_acted").status is CheckStatus.UNKNOWN


def test_multi_general_patrol_requires_every_actor_acted():
    before = _state()
    before.generals.append(_general(85, has_acted=False))
    after = _state(action_points=35, gold=4100, security=91, has_acted=True)
    after.generals.append(_general(85, has_acted=False))

    result = verify_patrol_action(before, after, _action(), extra_general_indices=(85,))

    assert result.status is VerificationStatus.FAILED
    assert result.check(f"general[{GENERAL_INDEX}].has_acted").status is CheckStatus.PASS
    assert result.check("general[85].has_acted").status is CheckStatus.FAIL


def test_expectation_requires_at_least_one_general():
    with pytest.raises(ValueError):
        PatrolExpectation(city_index=CITY_INDEX, general_indices=())


def test_capture_keeps_unknown_values_as_none():
    state = _state(with_force=False, full_city=False)
    expectation = PatrolExpectation.from_action(_action())

    snapshot = capture_patrol_snapshot(state, expectation)

    assert snapshot.force_index is None
    assert snapshot.action_points is None
    assert snapshot.gold is None
    assert snapshot.security is None
    assert snapshot.has_acted == ((GENERAL_INDEX, False),)
