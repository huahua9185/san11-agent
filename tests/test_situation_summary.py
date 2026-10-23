"""M5：局势摘要模块的单元测试，包含架构守卫（只能建立在 VisibleGameState 之上）
和摘要内容正确性两部分，风格上跟 tests/test_legal_actions.py 保持一致——直接
手工构造 VisibleGameState fixture，不经过 M1/M2 链路。
"""
from __future__ import annotations

import ast
import inspect
import typing
from pathlib import Path

from san11agent.situation_summary import (
    SituationSummary,
    render_situation_text,
    summarize_situation,
)
from san11agent.visible_state import (
    VisibleCityDetail,
    VisibleCitySummary,
    VisibleFactionPublic,
    VisibleGameState,
    VisibleGeneralFull,
    VisibleGlobalState,
)

PLAYER_FACTION_ID = 0
ENEMY_FACTION_ID = 1

OWN_CITY = 0
OWN_CITY_FULL = 1
ENEMY_CITY = 2
UNKNOWN_OWNERSHIP_CITY = 3

GENERAL_IDLE = 0
GENERAL_ASSIGNED = 1
GENERAL_NO_STAMINA = 2
GENERAL_ELSEWHERE = 3


def test_summary_excludes_acted_and_labels_unknown():
    state = _build_state()
    general = next(g for g in state.generals if g.index == GENERAL_IDLE)
    general.has_acted = True
    assert general.index not in {g.index for g in summarize_situation(state, PLAYER_FACTION_ID).idle_own_generals}
    general.has_acted = None
    summary = summarize_situation(state, PLAYER_FACTION_ID)
    assert next(g for g in summary.idle_own_generals if g.index == general.index).has_acted is None
    assert "行动状态=未知" in render_situation_text(summary)


def _global_state(xun: int = 12) -> VisibleGlobalState:
    return VisibleGlobalState(
        scenario_id=1, start_year=190, start_month=1, start_day=1,
        emperor_general_id=0, difficulty=1, death_setting=0, current_xun=xun,
        current_year=190, current_month=1, current_day=1, phase=1,
    )


def _own_city(index: int, *, gold: int, food: int, dev_count: int, developed: int) -> VisibleCityDetail:
    return VisibleCityDetail(
        index=index, name=f"city{index}", province=0, adjacent_cities=[],
        faction_id=PLAYER_FACTION_ID, map_x=0, map_y=0,
        governor_general_id=0, force_id=0, troop_capacity=100, troops=50,
        gold=gold, food=food, trade_price=10, has_merchant=1, morale=80,
        security=70, policy=0, target=0,
        development_land_count=dev_count, developed_land_count=developed,
        domestic_land_x=10, domestic_land_y=20,
    )


def _general(index: int, *, faction_id: int, location: int, stamina: int) -> VisibleGeneralFull:
    return VisibleGeneralFull(
        index=index, name=f"g{index}", portrait_id=0, gender=0, debut_year=0,
        birth_year=0, death_year=-1, faction_id=faction_id, identity=0, office=0,
        location=location, special_skill_id=-1,
        display_stats_wound=b"\x00" * 5, display_stats_normal=b"\x00" * 5,
        loyalty=75, merit=0, stamina=stamina, garrison_count=0, health=1, force_id=faction_id,
    )


def _build_state() -> VisibleGameState:
    cities = [
        _own_city(OWN_CITY, gold=500, food=8000, dev_count=5, developed=3),
        _own_city(OWN_CITY_FULL, gold=1000, food=100, dev_count=4, developed=4),
        VisibleCitySummary(
            index=ENEMY_CITY, name="敌城", province=1, adjacent_cities=[],
            faction_id=ENEMY_FACTION_ID, map_x=50, map_y=50,
        ),
        VisibleCitySummary(
            index=UNKNOWN_OWNERSHIP_CITY, name="归属未知城", province=2, adjacent_cities=[],
            faction_id=None, map_x=None, map_y=None,
        ),
    ]
    generals = [
        _general(GENERAL_IDLE, faction_id=PLAYER_FACTION_ID, location=OWN_CITY, stamina=50),
        _general(GENERAL_ASSIGNED, faction_id=PLAYER_FACTION_ID, location=OWN_CITY, stamina=50),
        _general(GENERAL_NO_STAMINA, faction_id=PLAYER_FACTION_ID, location=OWN_CITY, stamina=0),
        _general(GENERAL_ELSEWHERE, faction_id=PLAYER_FACTION_ID, location=999, stamina=100),
    ]
    factions = [
        VisibleFactionPublic(index=PLAYER_FACTION_ID, ruler_general_id=0, advisor_general_id=-1, player_marker=1),
        VisibleFactionPublic(index=ENEMY_FACTION_ID, ruler_general_id=10, advisor_general_id=-1, player_marker=0),
    ]
    return VisibleGameState(global_state=_global_state(), generals=generals, cities=cities, troops=[], factions=factions)


# ---------------------------------------------------------------------------
# 架构守卫：situation_summary 必须只建立在 VisibleGameState 之上
# ---------------------------------------------------------------------------


def test_module_does_not_bind_full_game_state_types():
    import san11agent.situation_summary as ss

    for name in ("GameState", "General", "City", "Troop", "Faction", "GlobalState"):
        assert not hasattr(ss, name), f"situation_summary.py 不应该引用完整 GameState 的 {name}"


def test_module_only_imports_from_visible_state_and_legal_actions():
    module_path = Path(inspect.getfile(summarize_situation))
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    from_imports = {(node.module or "").rsplit(".", 1)[-1] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "game_state" not in from_imports
    assert from_imports <= {"visible_state", "legal_actions", "__future__", "dataclasses"}


def test_summarize_situation_state_param_is_visible_game_state():
    hints = typing.get_type_hints(summarize_situation)
    assert hints["state"] is VisibleGameState


# ---------------------------------------------------------------------------
# 摘要内容
# ---------------------------------------------------------------------------


def test_summary_turn_comes_from_current_xun():
    summary = summarize_situation(_build_state(), PLAYER_FACTION_ID)
    assert summary.turn == 12


def test_own_cities_have_full_detail_fields():
    summary = summarize_situation(_build_state(), PLAYER_FACTION_ID)
    own = {c.index: c for c in summary.own_cities}
    assert set(own) == {OWN_CITY, OWN_CITY_FULL}
    assert own[OWN_CITY].gold == 500
    assert own[OWN_CITY].development_slots_available == 2  # 5 - 3


def test_other_visible_cities_include_enemy_and_unknown_ownership():
    summary = summarize_situation(_build_state(), PLAYER_FACTION_ID)
    other = {c.index: c for c in summary.other_visible_cities}
    assert set(other) == {ENEMY_CITY, UNKNOWN_OWNERSHIP_CITY}
    assert other[ENEMY_CITY].faction_id == ENEMY_FACTION_ID
    assert other[ENEMY_CITY].gold is None  # 摘要级别，看不到内部经营细节


def test_totals_only_sum_own_cities():
    summary = summarize_situation(_build_state(), PLAYER_FACTION_ID)
    assert summary.total_gold == 500 + 1000
    assert summary.total_food == 8000 + 100


def test_idle_generals_excludes_no_stamina_and_assigned():
    summary = summarize_situation(
        _build_state(), PLAYER_FACTION_ID, assigned_general_indices=frozenset({GENERAL_ASSIGNED})
    )
    indices = {g.index for g in summary.idle_own_generals}
    assert indices == {GENERAL_IDLE, GENERAL_ELSEWHERE}


def test_idle_general_city_index_uses_location_heuristic():
    summary = summarize_situation(_build_state(), PLAYER_FACTION_ID)
    by_index = {g.index: g for g in summary.idle_own_generals}
    assert by_index[GENERAL_IDLE].city_index == OWN_CITY
    assert by_index[GENERAL_ELSEWHERE].city_index is None  # location=999 匹配不到任何己方城池


def test_render_situation_text_is_deterministic_and_contains_key_numbers():
    summary = summarize_situation(_build_state(), PLAYER_FACTION_ID)
    text = render_situation_text(summary)
    assert isinstance(text, str)
    assert "第 12 旬" in text
    assert "city0" in text
    assert "敌城" in text
    # 两次渲染同一份 summary 必须完全一致，方便测试/日志做字符串比对。
    assert render_situation_text(summary) == text


def test_render_situation_text_accepts_empty_summary():
    empty = SituationSummary(
        turn=1, player_faction_id=0, own_cities=(), other_visible_cities=(),
        idle_own_generals=(), total_gold=0, total_food=0, faction_count=0,
    )
    text = render_situation_text(empty)
    assert "0座" in text
