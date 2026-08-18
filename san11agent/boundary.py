"""M2 信息边界过滤器：GameState（完整、未过滤）-> VisibleGameState（人类可见）。

完整的信息边界定义见 docs/visibility_research.md 与项目规格文档，这里只放
"谁能看到什么"的判定逻辑本身。判定逻辑依赖 visibility.VisibilitySource 回答
三个跟"探明/视野/发现"有关的问题——这一层不关心答案是离线合成的
（StaticVisibilitySource，测试用）还是来自真实进程（目前是
UnresolvedVisibilitySource，因为相关内存字段还没找到，见同一份文档）。

FREE_AGENT_FACTION_ID：约定 faction_id == -1 表示"在野/无势力归属"。这是根据
M1 现有代码里其它字段的既有惯例推出来的（比如 General.death_year、
General.special_skill_id、Troop.vice_general_*_id 在"无"的情况下都是 -1）。
2026-08-18 实机验证：真实进程里 1100 个武将中有 413 个 faction_id 精确等于
-1，数量上与"剧本1(黄巾之乱)里大部分历史人物尚未登场/未被招揽"的预期相符，
-1 作为"无归属"哨兵值的假设成立，见 docs/offset_research.md 第7.10节。

⚠️ 但同一次验证也发现：对于**有归属**的武将，faction_id 的具体数值不是
简单的"势力（势力=lord的政权）索引"——驻守在城池里、未随部队出征的武将，
faction_id 精确等于其 location（=所在城池的 index），这意味着这个字段在
"有归属"的情况下实际反映的更可能是"当前指派/绑定的对象"而不是稳定的政治
势力归属，用它做"是否属于某个具体势力"的比较时要小心，"-1 vs 非-1"这个
二元判断（本模块唯一用到的用法）依然可靠，但不要扩展为"faction_id 相等
就代表同一个势力"，同上文档第7.9/7.10节有完整记录。
"""
from __future__ import annotations

from .game_state import City, Faction, GameState, General, GlobalState, Troop
from .visibility import VisibilitySource
from .visible_state import (
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

FREE_AGENT_FACTION_ID = -1


def _filter_global_state(g: GlobalState) -> VisibleGlobalState:
    return VisibleGlobalState(
        scenario_id=g.scenario_id,
        start_year=g.start_year,
        start_month=g.start_month,
        start_day=g.start_day,
        emperor_general_id=g.emperor_general_id,
        difficulty=g.difficulty,
        death_setting=g.death_setting,
        current_xun=g.current_xun,
        current_year=g.current_year,
        current_month=g.current_month,
        current_day=g.current_day,
        phase=g.phase,
    )


def _to_general_public(g: General) -> VisibleGeneralPublic:
    return VisibleGeneralPublic(
        index=g.index,
        name=g.name,
        portrait_id=g.portrait_id,
        gender=g.gender,
        debut_year=g.debut_year,
        birth_year=g.birth_year,
        death_year=g.death_year,
        faction_id=g.faction_id,
        identity=g.identity,
        office=g.office,
        location=g.location,
        special_skill_id=g.special_skill_id,
        display_stats_wound=g.display_stats_wound,
        display_stats_normal=g.display_stats_normal,
    )


def _to_general_full(g: General) -> VisibleGeneralFull:
    return VisibleGeneralFull(
        index=g.index,
        name=g.name,
        portrait_id=g.portrait_id,
        gender=g.gender,
        debut_year=g.debut_year,
        birth_year=g.birth_year,
        death_year=g.death_year,
        faction_id=g.faction_id,
        identity=g.identity,
        office=g.office,
        location=g.location,
        special_skill_id=g.special_skill_id,
        display_stats_wound=g.display_stats_wound,
        display_stats_normal=g.display_stats_normal,
        loyalty=g.loyalty,
        merit=g.merit,
        stamina=g.stamina,
        garrison_count=g.garrison_count,
        health=g.health,
        force_id=g.force_id,
    )


def _filter_general(
    g: General, player_faction_id: int, visibility: VisibilitySource
) -> VisibleGeneralPublic | None:
    if g.faction_id == player_faction_id:
        return _to_general_full(g)
    if g.faction_id == FREE_AGENT_FACTION_ID:
        if visibility.is_general_discovered(g.index):
            return _to_general_public(g)
        return None
    # 有明确势力归属（非己方、非在野）的已登场武将：公开属性允许暴露。
    return _to_general_public(g)


def _to_city_summary(c: City) -> VisibleCitySummary:
    return VisibleCitySummary(
        index=c.index,
        name=c.name,
        province=c.province,
        adjacent_cities=list(c.adjacent_cities),
        faction_id=c.faction_id,
        map_x=c.map_x,
        map_y=c.map_y,
    )


def _to_city_detail(c: City) -> VisibleCityDetail:
    return VisibleCityDetail(
        index=c.index,
        name=c.name,
        province=c.province,
        adjacent_cities=list(c.adjacent_cities),
        faction_id=c.faction_id,
        map_x=c.map_x,
        map_y=c.map_y,
        governor_general_id=c.governor_general_id,
        force_id=c.force_id,
        troop_capacity=c.troop_capacity,
        troops=c.troops,
        gold=c.gold,
        food=c.food,
        trade_price=c.trade_price,
        has_merchant=c.has_merchant,
        morale=c.morale,
        security=c.security,
        policy=c.policy,
        target=c.target,
        development_land_count=c.development_land_count,
        developed_land_count=c.developed_land_count,
        domestic_land_x=c.domestic_land_x,
        domestic_land_y=c.domestic_land_y,
    )


def _filter_city(
    c: City, player_faction_id: int, visibility: VisibilitySource
) -> VisibleCitySummary:
    is_own = c.faction_id == player_faction_id
    detail_visible = is_own or visibility.is_city_explored(c.index)
    if detail_visible:
        return _to_city_detail(c)
    return _to_city_summary(c)


def _to_visible_troop(t: Troop) -> VisibleTroop:
    return VisibleTroop(
        index=t.index,
        type=t.type,
        commander_general_id=t.commander_general_id,
        vice_general_1_id=t.vice_general_1_id,
        vice_general_2_id=t.vice_general_2_id,
        troop_count=t.troop_count,
        morale=t.morale,
        gold=t.gold,
        food=t.food,
        status=t.status,
        status_duration=t.status_duration,
        x=t.x,
        y=t.y,
        has_acted=t.has_acted,
        faction_id=t.faction_id,
        equipment_slots=t.equipment_slots,
        current_unit_type=t.current_unit_type,
        display_stats=t.display_stats,
        display_attack=t.display_attack,
        display_defense=t.display_defense,
        display_construction=t.display_construction,
    )


def _filter_troop(
    t: Troop, player_faction_id: int, visibility: VisibilitySource
) -> VisibleTroop | None:
    is_own = t.faction_id == player_faction_id
    if is_own or visibility.is_troop_visible(t.index):
        return _to_visible_troop(t)
    return None


def _to_faction_public(f: Faction) -> VisibleFactionPublic:
    return VisibleFactionPublic(
        index=f.index,
        ruler_general_id=f.ruler_general_id,
        advisor_general_id=f.advisor_general_id,
        player_marker=f.player_marker,
    )


def _to_faction_full(f: Faction) -> VisibleFactionFull:
    return VisibleFactionFull(
        index=f.index,
        ruler_general_id=f.ruler_general_id,
        advisor_general_id=f.advisor_general_id,
        player_marker=f.player_marker,
        researching_tech_id=f.researching_tech_id,
        skill_points=f.skill_points,
    )


def _filter_faction(f: Faction, player_faction_id: int) -> VisibleFactionPublic:
    if f.index == player_faction_id:
        return _to_faction_full(f)
    return _to_faction_public(f)


def filter_game_state(state: GameState, visibility: VisibilitySource) -> VisibleGameState:
    """把完整 GameState 过滤成人类可见的 VisibleGameState。

    过滤规则（对应项目规格里的信息边界定义）：
    - 全局参数（回合/日期/剧本等）：始终全部可见。
    - 己方势力的城池/武将/部队/势力自身记录：全部字段可见。
    - 非己方城池：默认只暴露地理与归属（VisibleCitySummary）；
      visibility.is_city_explored() 为真时才额外暴露经营细节（VisibleCityDetail）。
    - 非己方部队：默认整支隐藏；visibility.is_troop_visible() 为真时才可见，
      可见时字段与己方部队一样完整（部队没有"部分可见"这一档）。
    - 有势力归属的非己方武将：视为"已登场"，公开属性可见（VisibleGeneralPublic）。
    - 在野（无势力归属）武将：默认隐藏；visibility.is_general_discovered()
      为真时才以公开属性可见。
    - 非己方势力：只暴露君主/军师/玩家标记（VisibleFactionPublic），研究中技巧、
      技巧点、势力好感度表始终不暴露。
    """
    player_faction_id = visibility.player_faction_id
    return VisibleGameState(
        global_state=_filter_global_state(state.global_state),
        generals=[
            v
            for v in (_filter_general(g, player_faction_id, visibility) for g in state.generals)
            if v is not None
        ],
        cities=[_filter_city(c, player_faction_id, visibility) for c in state.cities],
        troops=[
            v
            for v in (_filter_troop(t, player_faction_id, visibility) for t in state.troops)
            if v is not None
        ],
        factions=[_filter_faction(f, player_faction_id) for f in state.factions],
    )
