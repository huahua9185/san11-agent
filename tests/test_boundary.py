"""M2 信息边界过滤器的核心测试：完整 GameState vs 过滤后的 VisibleGameState 逐字段对照。

刻意不复用 M1 的 memory/offsets/perception 链路——boundary.py 本身是纯函数
（GameState -> VisibleGameState），这里直接在 Python 里手工构造 GameState
fixture，让过滤器测试完全独立于"怎么从内存读出 GameState"这件事，符合
"过滤器要能独立测试，用离线合成 fixture，不依赖真实游戏进程"的要求。
"""
from __future__ import annotations

import dataclasses

import pytest

from san11agent.boundary import FREE_AGENT_FACTION_ID, filter_game_state
from san11agent.game_state import Force, City, Faction, GameState, General, GlobalState, Troop
from san11agent.visibility import StaticVisibilitySource
from san11agent.visible_state import (
    VisibleCityDetail,
    VisibleCitySummary,
    VisibleFactionFull,
    VisibleFactionPublic,
    VisibleGameState,
    VisibleGeneralFull,
    VisibleGeneralPublic,
    VisibleGlobalState,
    VisibleTroop,
)

PLAYER_FACTION_ID = 0
ENEMY_FACTION_ID = 1

# 城池 index=2 已探明，troop index=2 在视野内，general index=3 已被发现（在野）。
EXPLORED_CITY_INDEX = 2
VISIBLE_TROOP_INDEX = 2
DISCOVERED_FREE_GENERAL_INDEX = 3
UNDISCOVERED_FREE_GENERAL_INDEX = 2


def _build_state() -> GameState:
    global_state = GlobalState(
        scenario_id=3,
        start_year=190,
        start_month=1,
        start_day=1,
        emperor_general_id=0,
        difficulty=2,
        death_setting=1,
        current_xun=7,
        current_year=195,
        current_month=3,
        current_day=1,
        phase=1,
    )

    generals = [
        General(  # 0: 己方武将
            index=0, name="曹操", portrait_id=1, gender=0, debut_year=184,
            birth_year=155, death_year=-1, force_id=0, faction_id=PLAYER_FACTION_ID,
            location=0, identity=1, office=5, loyalty=100, merit=999,
            base_stats=bytes([96, 72, 90, 94, 96]), special_skill_id=-1,
            stamina=100, garrison_count=3, health=1,
            display_stats_wound=bytes([80, 60, 75, 80, 90]),
            display_stats_normal=bytes([96, 72, 90, 94, 96]),
        ),
        General(  # 1: 敌方（有势力归属）武将——已登场，公开属性可见
            index=1, name="刘备", portrait_id=2, gender=0, debut_year=184,
            birth_year=161, death_year=-1, force_id=1, faction_id=ENEMY_FACTION_ID,
            location=0, identity=1, office=5, loyalty=95, merit=500,
            base_stats=bytes([78, 75, 70, 70, 100]), special_skill_id=-1,
            stamina=90, garrison_count=1, health=1,
            display_stats_wound=bytes([60, 55, 60, 60, 85]),
            display_stats_normal=bytes([78, 75, 70, 70, 100]),
        ),
        General(  # 2: 在野、未被发现——必须完全不出现在输出里
            index=2, name="卧龙", portrait_id=3, gender=0, debut_year=207,
            birth_year=181, death_year=-1, force_id=-1, faction_id=FREE_AGENT_FACTION_ID,
            location=0, identity=0, office=0, loyalty=0, merit=0,
            base_stats=bytes([70, 30, 100, 95, 90]), special_skill_id=-1,
            stamina=100, garrison_count=0, health=1,
            display_stats_wound=bytes([50, 20, 80, 75, 90]),
            display_stats_normal=bytes([70, 30, 100, 95, 90]),
        ),
        General(  # 3: 在野、已被发现——公开属性可见
            index=3, name="凤雏", portrait_id=4, gender=0, debut_year=208,
            birth_year=179, death_year=-1, force_id=-1, faction_id=FREE_AGENT_FACTION_ID,
            location=0, identity=0, office=0, loyalty=0, merit=0,
            base_stats=bytes([65, 35, 95, 88, 60]), special_skill_id=-1,
            stamina=100, garrison_count=0, health=1,
            display_stats_wound=bytes([45, 25, 75, 70, 60]),
            display_stats_normal=bytes([65, 35, 95, 88, 60]),
        ),
    ]

    cities = [
        City(  # 0: 己方城池——细节始终可见
            index=0, name="许昌", province=0, adjacent_cities=[1, 2, -1, -1, -1, -1],
            governor_general_id=0, force_id=0, troop_capacity=5000, troops=3000,
            gold=5000, food=8000, trade_price=10, has_merchant=1, morale=80,
            security=90, policy=0, target=0, development_land_count=10,
            developed_land_count=8, domestic_land_x=12, domestic_land_y=34,
            faction_id=PLAYER_FACTION_ID, map_x=100, map_y=100,
        ),
        City(  # 1: 敌方城池、未探明——只暴露摘要
            index=1, name="成都", province=1, adjacent_cities=[0, 2, -1, -1, -1, -1],
            governor_general_id=1, force_id=1, troop_capacity=4000, troops=2500,
            gold=4000, food=7000, trade_price=12, has_merchant=0, morale=70,
            security=85, policy=1, target=1, development_land_count=9,
            developed_land_count=7, domestic_land_x=20, domestic_land_y=40,
            faction_id=ENEMY_FACTION_ID, map_x=200, map_y=150,
        ),
        City(  # 2: 敌方城池、已探明——暴露细节
            index=2, name="江陵", province=2, adjacent_cities=[0, 1, -1, -1, -1, -1],
            governor_general_id=1, force_id=1, troop_capacity=3000, troops=1500,
            gold=2000, food=3000, trade_price=8, has_merchant=1, morale=60,
            security=75, policy=2, target=2, development_land_count=5,
            developed_land_count=4, domestic_land_x=8, domestic_land_y=9,
            faction_id=ENEMY_FACTION_ID, map_x=180, map_y=160,
        ),
    ]

    troops = [
        Troop(  # 0: 己方部队——始终可见
            index=0, type=0, commander_general_id=0, vice_general_1_id=-1,
            vice_general_2_id=-1, troop_count=3000, morale=80, gold=100, food=200,
            status=0, status_duration=0, x=50, y=60, has_acted=0,
            faction_id=PLAYER_FACTION_ID, equipment_slots=bytes(96),
            current_unit_type=1, display_stats=bytes([80, 60, 70, 65, 75]),
            display_attack=55, display_defense=45, display_construction=30,
        ),
        Troop(  # 1: 敌方部队、视野外——必须完全不出现
            index=1, type=0, commander_general_id=1, vice_general_1_id=-1,
            vice_general_2_id=-1, troop_count=2500, morale=75, gold=90, food=180,
            status=0, status_duration=0, x=10, y=20, has_acted=0,
            faction_id=ENEMY_FACTION_ID, equipment_slots=bytes(96),
            current_unit_type=1, display_stats=bytes([78, 75, 70, 70, 100]),
            display_attack=50, display_defense=48, display_construction=25,
        ),
        Troop(  # 2: 敌方部队、视野内——可见且字段完整
            index=2, type=0, commander_general_id=1, vice_general_1_id=-1,
            vice_general_2_id=-1, troop_count=1500, morale=65, gold=50, food=100,
            status=0, status_duration=0, x=15, y=25, has_acted=1,
            faction_id=ENEMY_FACTION_ID, equipment_slots=bytes(96),
            current_unit_type=1, display_stats=bytes([70, 65, 60, 60, 90]),
            display_attack=40, display_defense=38, display_construction=20,
        ),
    ]

    factions = [
        Faction(
            index=PLAYER_FACTION_ID, ruler_general_id=0, advisor_general_id=-1,
            relations_table=bytes([50] * 47), player_marker=1,
            researching_tech_id=3, skill_points=120,
        ),
        Faction(
            index=ENEMY_FACTION_ID, ruler_general_id=1, advisor_general_id=-1,
            relations_table=bytes([30] * 47), player_marker=0,
            researching_tech_id=7, skill_points=80,
        ),
    ]

    # 2026-08-18：势力归属改走 force_id -> Force.faction_id 这条已验证链路
    # （见 san11agent/faction_resolve.py 模块文档），所以 fixture 必须提供 forces，
    # 否则 resolver 解析不出归属、所有记录都会被 fail-closed 成"非己方"。
    # 上面的武将/城池已经在用 force_id=0（己方）/1（敌方）/-1（在野），这里补上
    # 对应的军团记录即可。
    forces = [
        Force(index=0, faction_id=PLAYER_FACTION_ID, force_number=1, commander_general_id=0),
        Force(index=1, faction_id=ENEMY_FACTION_ID, force_number=1, commander_general_id=1),
    ]

    return GameState(
        global_state=global_state, generals=generals, cities=cities,
        troops=troops, factions=factions, forces=forces,
    )


def _build_visibility() -> StaticVisibilitySource:
    return StaticVisibilitySource(
        _player_faction_id=PLAYER_FACTION_ID,
        explored_city_indices=frozenset({EXPLORED_CITY_INDEX}),
        visible_troop_indices=frozenset({VISIBLE_TROOP_INDEX}),
        discovered_general_indices=frozenset({DISCOVERED_FREE_GENERAL_INDEX}),
    )


@pytest.fixture()
def visible_state() -> VisibleGameState:
    return filter_game_state(_build_state(), _build_visibility())


# ---------------------------------------------------------------------------
# 全局参数：始终完整可见
# ---------------------------------------------------------------------------


def test_global_state_fully_visible(visible_state):
    assert visible_state.global_state == VisibleGlobalState(
        scenario_id=3, start_year=190, start_month=1, start_day=1,
        emperor_general_id=0, difficulty=2, death_setting=1, current_xun=7,
        current_year=195, current_month=3, current_day=1, phase=1,
    )


# ---------------------------------------------------------------------------
# 城池
# ---------------------------------------------------------------------------


def test_own_city_shows_full_detail(visible_state):
    own = next(c for c in visible_state.cities if c.index == 0)
    assert isinstance(own, VisibleCityDetail)
    assert own.gold == 5000
    assert own.food == 8000
    assert own.governor_general_id == 0
    assert own.force_id == 0


def test_unexplored_enemy_city_is_summary_only(visible_state):
    unexplored = next(c for c in visible_state.cities if c.index == 1)
    assert isinstance(unexplored, VisibleCitySummary)
    assert not isinstance(unexplored, VisibleCityDetail)
    assert unexplored.faction_id == ENEMY_FACTION_ID  # 归属本身始终公开
    # 内部详情字段在这个类型上根本不存在，不是等于 None
    for forbidden in ("gold", "food", "troops", "governor_general_id", "morale", "security"):
        assert not hasattr(unexplored, forbidden), f"{forbidden} 不应该出现在未探明城池上"


def test_explored_enemy_city_shows_full_detail(visible_state):
    explored = next(c for c in visible_state.cities if c.index == 2)
    assert isinstance(explored, VisibleCityDetail)
    assert explored.gold == 2000
    assert explored.troops == 1500


# ---------------------------------------------------------------------------
# 部队
# ---------------------------------------------------------------------------


def test_own_troop_visible(visible_state):
    indices = {t.index for t in visible_state.troops}
    assert 0 in indices


def test_fogged_enemy_troop_absent(visible_state):
    indices = {t.index for t in visible_state.troops}
    assert 1 not in indices


def test_visible_enemy_troop_present_with_full_fields(visible_state):
    troop = next(t for t in visible_state.troops if t.index == 2)
    assert isinstance(troop, VisibleTroop)
    assert troop.troop_count == 1500
    assert troop.faction_id == ENEMY_FACTION_ID


# ---------------------------------------------------------------------------
# 武将
# ---------------------------------------------------------------------------


def test_own_general_gets_full_tier_but_never_base_stats(visible_state):
    own = next(g for g in visible_state.generals if g.index == 0)
    assert isinstance(own, VisibleGeneralFull)
    assert own.loyalty == 100
    assert own.merit == 999
    assert own.force_id == 0
    assert not hasattr(own, "base_stats")  # 只暴露 display_stats_*，见 visible_state.py 模块说明
    assert own.display_stats_normal == bytes([96, 72, 90, 94, 96])


def test_enemy_general_with_faction_gets_public_tier(visible_state):
    enemy = next(g for g in visible_state.generals if g.index == 1)
    assert isinstance(enemy, VisibleGeneralPublic)
    assert not isinstance(enemy, VisibleGeneralFull)
    for forbidden in ("loyalty", "merit", "base_stats", "stamina", "garrison_count", "health"):
        assert not hasattr(enemy, forbidden), f"{forbidden} 不应该出现在非己方武将上"


def test_undiscovered_free_general_entirely_absent(visible_state):
    indices = {g.index for g in visible_state.generals}
    assert UNDISCOVERED_FREE_GENERAL_INDEX not in indices


def test_discovered_free_general_present_at_public_tier(visible_state):
    found = next(g for g in visible_state.generals if g.index == DISCOVERED_FREE_GENERAL_INDEX)
    assert isinstance(found, VisibleGeneralPublic)
    assert not isinstance(found, VisibleGeneralFull)


# ---------------------------------------------------------------------------
# 势力
# ---------------------------------------------------------------------------


def test_own_faction_gets_full_tier(visible_state):
    own = next(f for f in visible_state.factions if f.index == PLAYER_FACTION_ID)
    assert isinstance(own, VisibleFactionFull)
    assert own.researching_tech_id == 3
    assert own.skill_points == 120


def test_enemy_faction_gets_public_tier_only(visible_state):
    enemy = next(f for f in visible_state.factions if f.index == ENEMY_FACTION_ID)
    assert isinstance(enemy, VisibleFactionPublic)
    assert not isinstance(enemy, VisibleFactionFull)
    for forbidden in ("researching_tech_id", "skill_points"):
        assert not hasattr(enemy, forbidden)


def test_relations_table_never_exposed_for_any_faction(visible_state):
    # 好感度原始数值：无论己方还是敌方，任何情况都不应该出现在输出类型上。
    for faction in visible_state.factions:
        assert not hasattr(faction, "relations_table")


# ---------------------------------------------------------------------------
# 白名单性质本身的回归测试：
# Visible* 类型的字段集合是硬编码在这里的，任何人往这些类型上加字段都会让
# 这个测试炸掉，逼着做一次有意识的复核，而不是悄悄多暴露一个字段。
# ---------------------------------------------------------------------------


def _field_names(cls) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


def test_visible_general_public_field_whitelist_is_exact():
    assert _field_names(VisibleGeneralPublic) == {
        "index", "name", "portrait_id", "gender", "debut_year", "birth_year",
        "death_year", "faction_id", "identity", "office", "location",
        "special_skill_id", "display_stats_wound", "display_stats_normal",
    }


def test_visible_general_full_field_whitelist_is_exact():
    assert _field_names(VisibleGeneralFull) == _field_names(VisibleGeneralPublic) | {
        "loyalty", "merit", "stamina", "garrison_count", "health", "force_id",
    }


def test_visible_city_summary_field_whitelist_is_exact():
    assert _field_names(VisibleCitySummary) == {
        "index", "name", "province", "adjacent_cities", "faction_id", "map_x", "map_y",
    }


def test_visible_city_detail_field_whitelist_is_exact():
    assert _field_names(VisibleCityDetail) == _field_names(VisibleCitySummary) | {
        "governor_general_id", "force_id", "troop_capacity", "troops", "gold", "food",
        "trade_price", "has_merchant", "morale", "security", "policy", "target",
        "development_land_count", "developed_land_count", "domestic_land_x",
        "domestic_land_y",
    }


def test_visible_troop_field_whitelist_is_exact():
    assert _field_names(VisibleTroop) == {
        "index", "type", "commander_general_id", "vice_general_1_id",
        "vice_general_2_id", "troop_count", "morale", "gold", "food", "status",
        "status_duration", "x", "y", "has_acted", "faction_id", "equipment_slots",
        "current_unit_type", "display_stats", "display_attack", "display_defense",
        "display_construction",
    }


def test_visible_faction_public_field_whitelist_is_exact():
    assert _field_names(VisibleFactionPublic) == {
        "index", "ruler_general_id", "advisor_general_id", "player_marker",
    }


def test_visible_faction_full_field_whitelist_is_exact():
    assert _field_names(VisibleFactionFull) == _field_names(VisibleFactionPublic) | {
        "researching_tech_id", "skill_points",
    }


# ---------------------------------------------------------------------------
# 逐字段对照测试：完整 GameState 的字段集合 减去 Visible* 的字段集合，
# 就是"这一档理应看不到的字段"；对照过滤器的真实输出，确认这些字段在输出
# 对象上根本不存在（而不是存在但等于 None）。
# ---------------------------------------------------------------------------


def test_forbidden_city_fields_do_not_leak_on_unexplored_enemy_city(visible_state):
    forbidden = _field_names(City) - _field_names(VisibleCitySummary)
    unexplored = next(c for c in visible_state.cities if c.index == 1)
    leaked = [name for name in forbidden if hasattr(unexplored, name)]
    assert leaked == []


def test_forbidden_general_fields_do_not_leak_on_public_tier_general(visible_state):
    forbidden = _field_names(General) - _field_names(VisibleGeneralPublic)
    enemy = next(g for g in visible_state.generals if g.index == 1)
    leaked = [name for name in forbidden if hasattr(enemy, name)]
    assert leaked == []


def test_forbidden_faction_fields_do_not_leak_on_public_tier_faction(visible_state):
    forbidden = _field_names(Faction) - _field_names(VisibleFactionPublic)
    enemy = next(f for f in visible_state.factions if f.index == ENEMY_FACTION_ID)
    leaked = [name for name in forbidden if hasattr(enemy, name)]
    assert leaked == []


# ---------------------------------------------------------------------------
# 回归测试：势力归属必须走 force 链路解析，不能用原始 faction_id 字段
#
# 上面那份 fixture 里 raw faction_id 恰好等于解析后的势力ID，所以它其实证明不了
# "确实用了 resolver"。这里刻意构造实机里的真实形态——武将的 faction_id 字段
# 装的是【所在城池 index】而不是势力ID，城池的 faction_id 干脆是 None——
# 在修复前，这两种记录都会被判成"非己方"（因为 3 != 28、None != 28），
# 玩家自己的武将和首都都会被降级/藏起来。
# 见 docs/offset_research.md 第 7.9/7.10 节。
# ---------------------------------------------------------------------------

_REAL_PLAYER_FACTION = 28   # 实机里张角的势力 index
_REAL_FORCE_ID = 5          # 张角麾下第一军团
_CITY_INDEX = 3             # 南皮


def _zhangjiao_state() -> GameState:
    g = dataclasses.replace(
        _build_state().generals[0],
        index=0,
        force_id=_REAL_FORCE_ID,
        faction_id=_CITY_INDEX,   # ← 实机里这个字段就是城池 index，不是势力ID
        location=_CITY_INDEX,
    )
    c = dataclasses.replace(
        _build_state().cities[0],
        index=_CITY_INDEX,
        force_id=_REAL_FORCE_ID,
        faction_id=None,          # ← 实机里 city.faction_id 至今 unknown，恒为 None
    )
    t = dataclasses.replace(
        _build_state().troops[0],
        index=0,
        commander_general_id=0,
        faction_id=-1,            # ← 实机里活跃部队这个字段就是 -1
    )
    base = _build_state()
    return dataclasses.replace(
        base,
        generals=[g], cities=[c], troops=[t],
        forces=[Force(index=_REAL_FORCE_ID, faction_id=_REAL_PLAYER_FACTION,
                      force_number=1, commander_general_id=0)],
    )


def _zhangjiao_visible() -> VisibleGameState:
    return filter_game_state(
        _zhangjiao_state(),
        StaticVisibilitySource(
            _player_faction_id=_REAL_PLAYER_FACTION,
            explored_city_indices=frozenset(),
            visible_troop_indices=frozenset(),
            discovered_general_indices=frozenset(),
        ),
    )


def test_own_general_recognized_despite_misleading_raw_faction_id():
    visible = _zhangjiao_visible()
    own = visible.generals[0]
    assert isinstance(own, VisibleGeneralFull), "己方武将必须拿到 full 档，说明走了 force 链路"
    assert own.faction_id == _REAL_PLAYER_FACTION, "暴露的应该是解析后的势力ID，不是原始的城池index"


def test_own_city_recognized_despite_unknown_raw_faction_id():
    visible = _zhangjiao_visible()
    own = visible.cities[0]
    assert isinstance(own, VisibleCityDetail), "己方城池必须拿到 detail 档（未探明也算，因为是自己的）"
    assert own.faction_id == _REAL_PLAYER_FACTION


def test_own_troop_recognized_despite_minus_one_raw_faction_id():
    visible = _zhangjiao_visible()
    assert len(visible.troops) == 1, "己方部队必须可见（视野表里没有它，只能靠归属判断）"
    assert visible.troops[0].faction_id == _REAL_PLAYER_FACTION


def test_resolution_failure_fails_closed_not_open():
    """军团表缺失时，绝不能把非己方误判成己方——宁可自己人也看不全。"""
    state = dataclasses.replace(_zhangjiao_state(), forces=[])
    visible = filter_game_state(
        state,
        StaticVisibilitySource(
            _player_faction_id=_REAL_PLAYER_FACTION,
            explored_city_indices=frozenset(),
            visible_troop_indices=frozenset(),
            discovered_general_indices=frozenset(),
        ),
    )
    assert not isinstance(visible.generals[0], VisibleGeneralFull), "解析不出来时不能给 full 档"
    assert not isinstance(visible.cities[0], VisibleCityDetail), "解析不出来时不能给 detail 档"
    assert visible.troops == [], "解析不出来且不在视野内的部队必须整支隐藏"
