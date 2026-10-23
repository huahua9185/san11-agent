"""M2 的"人类可见"状态：白名单式数据结构。

设计原则——默认不暴露，显式列出可见字段：
这里的每个 dataclass 只声明"确认允许暴露给 LLM"的字段。GameState（M1）里任何
没有在这里显式列出的字段，天生就不存在于这些类型上：读取一个被过滤掉的字段
会直接 AttributeError，而不是悄悄返回 None 或者过期数据。新增一个 GameState
字段时，如果不特地在这里也加一行，它不会自动出现在 VisibleGameState 里——
不可能"忘了过滤"而默默泄漏。

按信息边界要求，同一类实体按"是否需要额外权限才能看到细节"拆成两级类型，
而不是用一个大 dataclass + 一堆 Optional 字段：
- 城池：VisibleCitySummary（任何人都能看到的：名称/地理/归属）
        vs VisibleCityDetail（己方城池 或 已探明的敌方城池才有：兵力/钱粮/内政等）
- 武将：VisibleGeneralPublic（已登场武将的公开属性）
        vs VisibleGeneralFull（仅己方武将：额外带忠诚度/功勋/体力/健康度等内部数值）
- 势力：VisibleFactionPublic（君主/军师等公开信息）
        vs VisibleFactionFull（仅己方势力：额外带研究中技巧/技巧点）
用子类型而不是"字段设为 None"来表达"这一级信息你看不到"，是刻意选择：
`city.gold` 在summary城池上根本不存在这个属性，比 `city.gold is None`
（还需要额外分清"内存里没读到"和"信息边界不让看"这两种完全不同的 None）
要强得多，也更容易在测试里断言"这个字段确实拿不到"。

以下字段永远不出现在任何 Visible* 类型里，无论己方还是他方，任何情况都排除：
- Faction.relations_table（对其他势力的好感度原始数值）——即使是己方势力，
  暴露的也是原始好感度数字而不是游戏界面上会显示的粗粒度外交状态，
  这本身就是"隐藏数值"，不是"界面公开显示的信息"。
- General.base_stats（武将的真实内部属性值）——游戏界面实际显示给玩家看的
  是 display_stats_normal / display_stats_wound（两者可能因未验证的"显示模糊
  化"机制而与真实值不同）。既然 M2 的目标是还原"人类玩家在界面上能看到的"，
  这里统一只暴露 display_* 字段，不区分己方/他方——己方武将不受模糊化影响时，
  display_* 本来就等于真实值，所以不会丢失己方视角下的任何有效信息。
  这一条在报告里作为"已解决的设计问题"列出，供你复核。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VisibleGlobalState:
    """全局参数对任何玩家都是公开信息，字段与 GameState.GlobalState 一一对应。"""

    scenario_id: int
    start_year: int
    start_month: int
    start_day: int
    emperor_general_id: int
    difficulty: int
    death_setting: int
    current_xun: int
    current_year: int | None
    current_month: int | None
    current_day: int | None
    phase: int | None


@dataclass
class VisibleGeneralPublic:
    """已登场武将（有势力归属，或在野但已被发现）的公开属性。"""

    index: int
    name: str
    portrait_id: int
    gender: int
    debut_year: int
    birth_year: int
    death_year: int
    faction_id: int
    identity: int
    office: int
    location: int
    special_skill_id: int
    display_stats_wound: bytes
    display_stats_normal: bytes


@dataclass
class VisibleGeneralFull(VisibleGeneralPublic):
    """己方武将额外可见的内部数值：忠诚度/功勋/体力/健康度/驻守兵力/军团归属。

    force_id（军团ID）只放在己方专属这一档，不放进 Public 档：它是不是也该对
    "已登场的他方武将"公开，规格文档没有明确提到"军团"这个概念，保守起见先
    按"己方全部数据"原则只保证己方可见，具体是否该对他方也公开留给你确认，
    见提交报告。
    """

    loyalty: int
    merit: int
    stamina: int
    garrison_count: int
    health: int
    force_id: int
    has_acted: bool | None = None


@dataclass
class VisibleCitySummary:
    """任何城池都至少暴露这些——地图上看得到的归属与地理位置。"""

    index: int
    name: str
    province: int
    adjacent_cities: list[int]
    faction_id: int | None
    map_x: int | None
    map_y: int | None


@dataclass
class VisibleCityDetail(VisibleCitySummary):
    """己方城池，或已探明的敌方城池，才额外暴露的内部经营细节。"""

    governor_general_id: int
    force_id: int
    troop_capacity: int
    troops: int
    gold: int
    food: int
    trade_price: int
    has_merchant: int
    morale: int
    security: int
    policy: int
    target: int
    development_land_count: int
    developed_land_count: int
    domestic_land_x: int
    domestic_land_y: int


@dataclass
class VisibleTroop:
    """部队没有"部分可见"这一档：要么在视野内完整可见，要么整支从列表里消失。"""

    index: int
    type: int
    commander_general_id: int
    vice_general_1_id: int
    vice_general_2_id: int
    troop_count: int
    morale: int
    gold: int
    food: int
    status: int
    status_duration: int
    x: int
    y: int
    has_acted: int
    faction_id: int
    equipment_slots: bytes
    current_unit_type: int
    display_stats: bytes
    display_attack: int
    display_defense: int
    display_construction: int


@dataclass
class VisibleFactionPublic:
    """任何势力都公开的信息：君主/军师身份、是否是玩家自己。"""

    index: int
    ruler_general_id: int
    advisor_general_id: int
    player_marker: int


@dataclass
class VisibleFactionFull(VisibleFactionPublic):
    """仅己方势力额外可见：研究中的技巧、技巧点。"""

    researching_tech_id: int
    skill_points: int


@dataclass
class VisibleForce:
    """仅己方军团的行動力余额；多个都市可能引用同一军团。"""

    index: int
    faction_id: int
    action_points: int | None = None


@dataclass
class VisibleGameState:
    global_state: VisibleGlobalState
    generals: list[VisibleGeneralPublic] = field(default_factory=list)
    cities: list[VisibleCitySummary] = field(default_factory=list)
    troops: list[VisibleTroop] = field(default_factory=list)
    factions: list[VisibleFactionPublic] = field(default_factory=list)
    forces: list[VisibleForce] = field(default_factory=list)
