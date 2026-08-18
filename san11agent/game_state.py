"""GameState 数据结构。

这一层只是"解析出来的原始游戏内存数据"，还没有做 M2 的人类可见信息过滤。
M1 阶段允许出现完整的、未过滤的全势力数据——过滤是下一个里程碑的事。

字段里但凡对应 offsets 文件中 unknown=true 的，一律是 Optional 并默认 None，
不编造默认值。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GlobalState:
    scenario_id: int
    start_year: int
    start_month: int
    start_day: int
    emperor_general_id: int
    difficulty: int
    death_setting: int
    current_xun: int
    current_year: int | None = None
    current_month: int | None = None
    current_day: int | None = None
    phase: int | None = None


@dataclass
class General:
    index: int
    # name 是"姓+名"拼接出来的完整姓名（比如"張角"），不是内存里的单一字段——
    # 2026-08-18 实机验证发现原资料标注的那个 56 字节 name 字段其实是
    # 姓(5) + 名(5) + 字(46) 三段定长子结构，此前解析代码在第一个 0x00 处截断，
    # 导致 1100 位武将里 849 位只读出了姓（"張"而不是"張角"）。
    # 拆出来的三段放在本类末尾（带默认值），这样已有的构造调用不用全部改。
    # 见 docs/offset_research.md 第 7.5 / 8.4 节。
    name: str
    portrait_id: int
    gender: int
    debut_year: int
    birth_year: int
    death_year: int
    force_id: int
    faction_id: int
    location: int
    identity: int
    office: int
    loyalty: int
    merit: int
    base_stats: bytes
    special_skill_id: int
    stamina: int
    garrison_count: int
    health: int
    display_stats_wound: bytes
    display_stats_normal: bytes
    # 姓 / 名 / 字 三段原始子字段。name 就是 surname + given_name。
    # 默认空字符串是为了兼容"只声明了旧 name 字段"的 offsets 文件（见
    # perception._general_name_parts 的退路说明）以及直接构造 General 的测试。
    surname: str = ""
    given_name: str = ""
    courtesy_name: str = ""


@dataclass
class City:
    index: int
    name: str
    province: int
    adjacent_cities: list[int]
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
    faction_id: int | None = None
    map_x: int | None = None
    map_y: int | None = None


@dataclass
class Troop:
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
class Faction:
    index: int
    ruler_general_id: int
    advisor_general_id: int
    relations_table: bytes
    player_marker: int
    researching_tech_id: int
    skill_points: int


@dataclass
class Force:
    """军团（Force）——势力麾下的一支独立编制的军队，不是"部队"(Troop，
    具体带兵出征的那支)，也不是"势力"(Faction，政治实体本身)。2026-08-18
    才在真实进程上首次探得的结构体，见 docs/offset_research.md 第7.10节。

    这是目前项目里唯一能从 General.force_id / City.force_id 正确推导出
    真正政治势力归属的路径：General/City.force_id -> Force[force_id].faction_id
    -> Faction[faction_id]。General.faction_id / Troop.faction_id 这两个
    字段本身不能直接当作势力ID用，见对应字段的 note。
    """
    index: int
    faction_id: int
    force_number: int
    commander_general_id: int


@dataclass
class GameState:
    global_state: GlobalState
    generals: list[General] = field(default_factory=list)
    cities: list[City] = field(default_factory=list)
    troops: list[Troop] = field(default_factory=list)
    factions: list[Faction] = field(default_factory=list)
    forces: list[Force] = field(default_factory=list)
