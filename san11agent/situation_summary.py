"""M5：把 M2 的 VisibleGameState 摘要成给 LLM 看的局势文本。

核心约束（和 M4 LegalActions 完全相同的理由，见 legal_actions.py 模块说明）：
只能建立在 VisibleGameState 之上，不能引用 M1 完整 GameState 的类型。理由不
是重复一遍代码规范，而是实验前提本身——LLM 战略层的决策如果掺进了人类玩家
在界面上看不到的信息（未探明敌城的钱粮、没有情报的在野武将属性），那么"AI
和人类玩家站在同样的信息基础上决策"这个实验假设就被破坏了。这个约束在代码
层面通过下面两点强制，并由 `tests/test_situation_summary.py` 的架构守卫测试
守住：

1. 本模块只 `import` `.visible_state` 和 `.legal_actions`（后者本身也只
   建立在 VisibleGameState 之上，见其模块说明），完全不 import `game_state.py`。
2. `summarize_situation()` 的 `state` 参数类型标注是 VisibleGameState。

"武将当前在哪座城"的判定复用了 `legal_actions.default_is_general_in_city()`
里同一条未经验证的假设（`General.location == City.index`），没有重新发明
一份不一致的猜测——这条假设本身是否成立，见 docs/legal_actions_research.md
和 docs/verification_checklist.md 8.1/8.2 两项，本模块不重复讨论。
"""
from __future__ import annotations

from dataclasses import dataclass

from .legal_actions import default_is_general_in_city
from .visible_state import VisibleCityDetail, VisibleGameState, VisibleGeneralFull


@dataclass(frozen=True, kw_only=True)
class CitySituation:
    """一座城池摘要出来的局势条目。非己方/未探明的城池只有 index/name/faction_id
    可能有值——其余字段固定是 None，不是"读不到"和"看不到"混在一起的模糊 None
    （这两种 None 的区分方式跟 M2 的 VisibleCitySummary/VisibleCityDetail 拆分
    是同一个道理，见 visible_state.py 模块说明）。
    """

    index: int
    name: str
    is_own: bool
    faction_id: int | None
    gold: int | None = None
    food: int | None = None
    troops: int | None = None
    troop_capacity: int | None = None
    security: int | None = None
    development_slots_available: int | None = None


@dataclass(frozen=True, kw_only=True)
class IdleGeneralSituation:
    """一位"本回合还没被指派、体力大于0"的己方武将——摘要给 LLM 看，帮它判断
    "谁去镇守要地"这类意图有没有可用的人选。city_index 是按
    default_is_general_in_city() 猜出来的，猜不出来（比如武将在部队里）时是
    None，不代表这位武将不存在。
    """

    index: int
    name: str
    city_index: int | None
    stamina: int
    loyalty: int


@dataclass(frozen=True, kw_only=True)
class SituationSummary:
    """一次摘要的完整结果。turn 直接取 VisibleGlobalState.current_xun——项目
    目前唯一确认可靠的回合计数字段，见 offsets/pk_1.1_cn.json 和
    docs/verification_checklist.md 5.2（年/月/日字段仍未定位，current_xun 是
    唯一已知偏移，M1 起一直如此）。
    """

    turn: int
    player_faction_id: int
    own_cities: tuple[CitySituation, ...]
    other_visible_cities: tuple[CitySituation, ...]
    idle_own_generals: tuple[IdleGeneralSituation, ...]
    total_gold: int
    total_food: int
    faction_count: int


def _city_situation(city, *, is_own: bool) -> CitySituation:
    if isinstance(city, VisibleCityDetail):
        slots = city.development_land_count - city.developed_land_count
        return CitySituation(
            index=city.index, name=city.name, is_own=is_own, faction_id=city.faction_id,
            gold=city.gold, food=city.food, troops=city.troops, troop_capacity=city.troop_capacity,
            security=city.security, development_slots_available=slots,
        )
    return CitySituation(index=city.index, name=city.name, is_own=is_own, faction_id=city.faction_id)


def summarize_situation(
    state: VisibleGameState, player_faction_id: int, assigned_general_indices: frozenset[int] = frozenset()
) -> SituationSummary:
    """从 VisibleGameState 生成结构化局势摘要。

    assigned_general_indices 跟 legal_actions.enumerate_legal_actions() 是
    同一个概念（本回合已经被指派过的武将），同样是显式传入而不是从内存猜——
    这是本回合对局循环自己维护的状态，不是游戏内存字段，理由见 legal_actions.py
    模块说明。默认空集合，方便只想看"全部己方武将现状"而不关心指派状态的调用方。
    """
    own_cities = tuple(
        _city_situation(c, is_own=True) for c in state.cities if c.faction_id == player_faction_id
    )
    other_visible_cities = tuple(
        _city_situation(c, is_own=False) for c in state.cities if c.faction_id != player_faction_id
    )

    own_city_details = [c for c in state.cities if isinstance(c, VisibleCityDetail) and c.faction_id == player_faction_id]
    idle_generals = []
    for general in state.generals:
        if not isinstance(general, VisibleGeneralFull):
            continue
        if general.faction_id != player_faction_id:
            continue
        if general.index in assigned_general_indices:
            continue
        if general.stamina <= 0:
            continue
        city_index = next(
            (c.index for c in own_city_details if default_is_general_in_city(general, c)), None
        )
        idle_generals.append(
            IdleGeneralSituation(
                index=general.index, name=general.name, city_index=city_index,
                stamina=general.stamina, loyalty=general.loyalty,
            )
        )

    total_gold = sum(c.gold for c in own_cities if c.gold is not None)
    total_food = sum(c.food for c in own_cities if c.food is not None)

    return SituationSummary(
        turn=state.global_state.current_xun,
        player_faction_id=player_faction_id,
        own_cities=own_cities,
        other_visible_cities=other_visible_cities,
        idle_own_generals=tuple(idle_generals),
        total_gold=total_gold,
        total_food=total_food,
        faction_count=len(state.factions),
    )


def _render_city_line(city: CitySituation) -> str:
    if city.gold is None:
        return f"  城池[{city.index}] {city.name}：归属=势力{city.faction_id}（未探明详情，仅摘要级别信息）"
    slot_text = "" if city.development_slots_available is None else f" 内政空位={city.development_slots_available}"
    return (
        f"  城池[{city.index}] {city.name}：兵力={city.troops}/{city.troop_capacity} "
        f"钱={city.gold} 粮={city.food} 治安={city.security}{slot_text}"
    )


def render_situation_text(summary: SituationSummary) -> str:
    """渲染成给 LLM 看的紧凑文本。纯格式化，不做任何决策逻辑——保持
    summarize_situation()（数据）和这里（展示）分离，方便测试和替换展示格式。
    """
    lines = [
        f"【全局】第 {summary.turn} 旬 | 势力数={summary.faction_count} "
        f"| 己方总钱={summary.total_gold} 己方总粮={summary.total_food}",
        f"【己方城池】({len(summary.own_cities)}座)",
    ]
    lines.extend(_render_city_line(c) for c in summary.own_cities)

    lines.append(f"【可见的非己方城池】({len(summary.other_visible_cities)}座，未探明的只显示归属)")
    lines.extend(_render_city_line(c) for c in summary.other_visible_cities)

    lines.append(f"【可指派的己方武将】(体力>0 且本回合尚未指派，共{len(summary.idle_own_generals)}位)")
    for g in summary.idle_own_generals:
        city_text = f"城池{g.city_index}" if g.city_index is not None else "位置未知（可能在部队中）"
        lines.append(f"  武将[{g.index}] {g.name}：所在={city_text} 体力={g.stamina} 忠诚={g.loyalty}")

    return "\n".join(lines)
