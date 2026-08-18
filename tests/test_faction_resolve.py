"""FactionResolver 的单元测试。

背景见 san11agent/faction_resolve.py 模块文档：General/Troop 的 faction_id 字段
不是稳定的势力ID（实机验证推翻了原资料的标注），真正的归属要走
force_id -> Force.faction_id 这一跳。这些测试锁住那条链路的行为，尤其是
"解析不出来时必须返回 None 而不是猜一个"这条 fail-closed 约定。
"""
from __future__ import annotations

import pytest

from san11agent.faction_resolve import (
    FREE_AGENT_FACTION_ID,
    NO_FORCE_ID,
    FactionResolver,
    is_free_agent,
)
from san11agent.game_state import City, Force, GameState, General, GlobalState, Troop

PLAYER_FACTION = 28  # 用张角在实机里的真实势力 index，避免和 force_id 数值混淆
ENEMY_FACTION = 11


def _general(index: int, *, force_id: int, faction_id: int) -> General:
    return General(
        index=index, name="某人", portrait_id=0, gender=0, debut_year=184,
        birth_year=155, death_year=-1, force_id=force_id, faction_id=faction_id,
        location=0, identity=3, office=0, loyalty=100, merit=0,
        base_stats=bytes(5), special_skill_id=-1, stamina=100,
        garrison_count=0, health=1, display_stats_wound=bytes(5),
        display_stats_normal=bytes(5),
    )


def _city(index: int, *, force_id: int) -> City:
    return City(
        index=index, name="某城", province=0, adjacent_cities=[-1] * 6,
        governor_general_id=0, force_id=force_id, troop_capacity=100000, troops=0,
        gold=0, food=0, trade_price=0, has_merchant=0, morale=0, security=0,
        policy=0, target=0, development_land_count=0, developed_land_count=0,
        domestic_land_x=0, domestic_land_y=0,
    )


def _troop(index: int, *, commander_general_id: int) -> Troop:
    return Troop(
        index=index, type=0, commander_general_id=commander_general_id,
        vice_general_1_id=-1, vice_general_2_id=-1, troop_count=6000, morale=80,
        gold=0, food=0, status=0, status_duration=0, x=0, y=0, has_acted=0,
        faction_id=-1,  # 实机里活跃部队这个字段就是 -1，故意照搬
        equipment_slots=bytes(96), current_unit_type=0, display_stats=bytes(5),
        display_attack=0, display_defense=0, display_construction=0,
    )


@pytest.fixture()
def resolver() -> FactionResolver:
    forces = [
        Force(index=5, faction_id=PLAYER_FACTION, force_number=1, commander_general_id=403),
        Force(index=6, faction_id=PLAYER_FACTION, force_number=2, commander_general_id=440),
        Force(index=9, faction_id=ENEMY_FACTION, force_number=1, commander_general_id=465),
    ]
    generals = [
        _general(403, force_id=5, faction_id=3),      # 驻守武将：faction_id 是城池index，不可信
        _general(171, force_id=9, faction_id=11),
        _general(700, force_id=NO_FORCE_ID, faction_id=FREE_AGENT_FACTION_ID),  # 在野
    ]
    return FactionResolver.from_parts(forces, generals)


# ---------------------------------------------------------------------------
# 核心：同一势力的多个军团要解析到同一个势力
# ---------------------------------------------------------------------------


def test_two_forces_of_same_faction_resolve_to_same_faction(resolver):
    """实机里张角麾下有两支军团(force 5/6)，都必须解析到同一个势力 28。
    这正是当初发现 Force 结构体的那条线索。"""
    assert resolver.faction_of_force(5) == PLAYER_FACTION
    assert resolver.faction_of_force(6) == PLAYER_FACTION
    assert resolver.faction_of_force(9) == ENEMY_FACTION


def test_general_faction_id_field_is_not_used_for_ownership(resolver):
    """武将[403] 的 faction_id 字段是 3（实机里这个值其实是所在城池 index），
    但真实势力归属是 28。解析结果必须来自 force 链路，不能是那个字段本身。"""
    g = _general(403, force_id=5, faction_id=3)
    assert g.faction_id == 3
    assert resolver.of_general(g) == PLAYER_FACTION


def test_city_uses_force_chain_not_unknown_faction_id_field(resolver):
    """City.faction_id 在 offsets 里至今是 unknown、解析恒为 None，
    城池归属必须靠 force_id 拿到。"""
    c = _city(3, force_id=5)
    assert c.faction_id is None
    assert resolver.of_city(c) == PLAYER_FACTION


def test_troop_resolves_through_commander(resolver):
    """部队没有 force_id，只能经主将绕两跳。⚠ 这条链路尚未实机验证。"""
    assert resolver.of_troop(_troop(6, commander_general_id=403)) == PLAYER_FACTION
    assert resolver.of_troop(_troop(7, commander_general_id=171)) == ENEMY_FACTION


# ---------------------------------------------------------------------------
# fail-closed：查不到就返回 None，绝不猜
# ---------------------------------------------------------------------------


def test_unknown_force_id_returns_none(resolver):
    assert resolver.faction_of_force(999) is None
    assert resolver.of_city(_city(1, force_id=999)) is None


def test_no_force_sentinel_returns_none(resolver):
    """force_id == -1 表示无归属（比如无人管辖的空城），不是"查不到"，
    但对下游一样是 None。"""
    assert resolver.faction_of_force(NO_FORCE_ID) is None
    assert resolver.of_city(_city(0, force_id=NO_FORCE_ID)) is None


def test_free_agent_general_resolves_to_none(resolver):
    g = _general(700, force_id=NO_FORCE_ID, faction_id=FREE_AGENT_FACTION_ID)
    assert is_free_agent(g) is True
    assert resolver.of_general(g) is None


def test_troop_with_invalid_commander_returns_none(resolver):
    assert resolver.of_troop(_troop(9, commander_general_id=-1)) is None
    assert resolver.of_troop(_troop(9, commander_general_id=99999)) is None


def test_empty_forces_resolves_everything_to_none():
    """offsets 文件没有定义 force 结构体时（老配置/游戏没加载存档），
    resolver 必须整体退化成"什么都不知道"，让调用方 fail-closed，
    而不是报错或者退回去用不可信的 faction_id 字段。"""
    empty = FactionResolver.from_parts([], [])
    assert empty.of_city(_city(3, force_id=5)) is None
    assert empty.of_general(_general(403, force_id=5, faction_id=3)) is None
    assert empty.of_troop(_troop(6, commander_general_id=403)) is None


def test_from_state_reads_forces_and_generals():
    state = GameState(
        global_state=GlobalState(
            scenario_id=0, start_year=184, start_month=1, start_day=1,
            emperor_general_id=-1, difficulty=2, death_setting=0, current_xun=30,
        ),
        generals=[_general(403, force_id=5, faction_id=3)],
        cities=[_city(3, force_id=5)],
        troops=[],
        factions=[],
        forces=[Force(index=5, faction_id=PLAYER_FACTION, force_number=1, commander_general_id=403)],
    )
    r = FactionResolver.from_state(state)
    assert r.of_city(state.cities[0]) == PLAYER_FACTION
    assert r.of_general(state.generals[0]) == PLAYER_FACTION


def test_negative_faction_id_in_force_record_is_ignored():
    """Force 记录本身 faction_id 为负（无效/未使用的军团槽位）时不建立映射。"""
    r = FactionResolver.from_parts(
        [Force(index=5, faction_id=-1, force_number=0, commander_general_id=-1)], []
    )
    assert r.faction_of_force(5) is None
