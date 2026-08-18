"""M4 LegalActions：给定当前人类可见状态（VisibleGameState），枚举出内政阶段
"这一步可以合法执行的动作"完整列表——结构化 Action 对象，不是字符串。

核心约束（项目规格 3.3 节）：LegalActions 必须建立在 M2 的 VisibleGameState
之上，不能碰完整 GameState。理由：如果 AI 提议动作时用到了人类玩家在界面上
根本看不到的信息（比如未探明敌城的钱粮、没有己方情报的在野武将属性），那么
"AI 不需要猜规则、也不会输出非法指令"这个实验前提本身就被破坏了——LegalActions
的合法性判断，必须只用人类也能看到的信息来做。这个约束通过下面两点在代码
层面强制：
1. enumerate_legal_actions() 的状态参数类型标注是 VisibleGameState，本模块
   完全不 import game_state.py 里的 GameState/General/City/Troop/Faction。
2. 判断"这位武将/这座城是否可以被用来发起动作"时，用 isinstance() 检查它是不是
   VisibleGeneralFull/VisibleCityDetail（M2 里"信息充分"这一档的具体类型），
   而不是假设某个字段一定存在——按 M2 的白名单设计，看不到的字段在 Visible*
   对象上根本不存在，试图访问会直接 AttributeError，不会有编造/过期数据的
   风险。见 tests/test_legal_actions.py 的架构守卫测试。

不在本次范围内（详见 docs/legal_actions_research.md）：
- Execute（把 Action 真正转换成键鼠输入执行）——等真实游戏能跑时再做。
- 战斗/战略阶段动作。
- 武将适性/特技对动作合法性的限制——GameState 数据模型目前完全没有解析
  "兵科适性"这类字段（M1 没做，见 docs/offset_research.md），special_skill_id
  虽然存在但没有任何地方定义每个 id 对应什么效果，无法用来做门槛判断，只能
  跳过，不猜测。
- "一回合一将一令"里的"是否已指派"状态——这不是游戏内存里的字段，是本次
  对局过程中 agent 自己发出过的指令历史，所以设计成显式传入的
  assigned_general_indices 参数，调用方（未来的对局循环）自己维护，跟
  visibility.py 里 player_faction_id 必须显式传入是同一种理由（这类信息
  本来就是操作方自己已知的，不需要也不应该靠猜内存字段语义来推导）。

资源/体力门槛来自 domestic_rules.py 加载的规则表（rules/*.json）。规则表里
大量数值目前是 unknown——这不是内存偏移问题，是游戏规则本身没有实机验证
途径，见 rules/domestic_actions_pk_1.1_cn.json。unknown 的规则不会被用来
拒绝任何动作（视为"暂不限制"），但会被记录进对应 Action.unverified_constraints，
提醒下游"这条动作没有经过真实资源检查"。
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum

from .domestic_rules import ActionRuleSpec, DomesticRulesConfig, RuleValue
from .visible_state import (
    VisibleCityDetail,
    VisibleCitySummary,
    VisibleFactionPublic,
    VisibleGameState,
    VisibleGeneralFull,
)


class ActionKind(Enum):
    BUILD_FACILITY = "build_facility"
    RECRUIT_TROOPS = "recruit_troops"
    TRAIN_TROOPS = "train_troops"
    SECURITY_PATROL = "security_patrol"
    LEVY_GOLD = "levy_gold"
    LEVY_FOOD = "levy_food"
    DIPLOMACY = "diplomacy"
    STRATAGEM = "stratagem"


@dataclass(frozen=True, kw_only=True)
class ActionBase:
    general_index: int
    city_index: int
    # 本次动作枚举时哪些约束因为规则表 unknown 而没有真正检查——观测用，
    # 不代表动作一定不合法，只代表"这一项没有被验证过"。
    unverified_constraints: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class BuildFacilityAction(ActionBase):
    """设施建设：开发用地上建一处设施。target_tile 精度有限，见模块说明。"""

    kind: ActionKind = field(default=ActionKind.BUILD_FACILITY, init=False)
    facility_type: str
    target_tile: tuple[int, int] | None


@dataclass(frozen=True, kw_only=True)
class RecruitTroopsAction(ActionBase):
    """征兵。征哪支具体部队不在枚举范围内，见模块说明。"""

    kind: ActionKind = field(default=ActionKind.RECRUIT_TROOPS, init=False)


@dataclass(frozen=True, kw_only=True)
class TrainTroopsAction(ActionBase):
    """训练。"""

    kind: ActionKind = field(default=ActionKind.TRAIN_TROOPS, init=False)


@dataclass(frozen=True, kw_only=True)
class SecurityPatrolAction(ActionBase):
    """治安/巡查——本次设计里合并为一个动作类型，见规则表 note。"""

    kind: ActionKind = field(default=ActionKind.SECURITY_PATROL, init=False)


@dataclass(frozen=True, kw_only=True)
class LevyGoldAction(ActionBase):
    """征收（金）。"""

    kind: ActionKind = field(default=ActionKind.LEVY_GOLD, init=False)


@dataclass(frozen=True, kw_only=True)
class LevyFoodAction(ActionBase):
    """征收（粮）。"""

    kind: ActionKind = field(default=ActionKind.LEVY_FOOD, init=False)


@dataclass(frozen=True, kw_only=True)
class DiplomacyAction(ActionBase):
    """外交。目标势力是否已建立联系未建模，见模块说明。"""

    kind: ActionKind = field(default=ActionKind.DIPLOMACY, init=False)
    target_faction_index: int
    diplomacy_type: str


@dataclass(frozen=True, kw_only=True)
class StratagemAction(ActionBase):
    """计略。目标城池可达性未建模，见模块说明。"""

    kind: ActionKind = field(default=ActionKind.STRATAGEM, init=False)
    target_city_index: int
    stratagem_type: str


Action = (
    BuildFacilityAction
    | RecruitTroopsAction
    | TrainTroopsAction
    | SecurityPatrolAction
    | LevyGoldAction
    | LevyFoodAction
    | DiplomacyAction
    | StratagemAction
)


GeneralInCityPredicate = Callable[[VisibleGeneralFull, VisibleCityDetail], bool]


def default_is_general_in_city(general: VisibleGeneralFull, city: VisibleCityDetail) -> bool:
    """默认假设：General.location 在武将驻扎于某城池时等于该城池的 index。

    这是基于 offsets/pk_1.1_cn.json 里 location 字段现有注释推出的猜测——
    该字段注明">87 表示在部队中，减87=部队ID"，暗示<=87 的取值可能是别的编码
    （比如城池 index：游戏共 42 座城，0~41 都落在这个范围内），但资料没有
    明确证实"不在部队中时 location == 所在城池 index"这件事。这是需要你确认
    的假设之一，见 docs/legal_actions_research.md。如果假设不对，调用
    enumerate_legal_actions() 时传入自定义的 is_general_in_city 覆盖它。
    """
    return general.location == city.index


def _check_resource(current: int, rule: RuleValue, name: str, unverified: list[str]) -> bool:
    if not rule.is_known:
        unverified.append(name)
        return True
    return current >= rule.value


def _stamina_and_resource_check(
    general: VisibleGeneralFull, city: VisibleCityDetail, rule: ActionRuleSpec
) -> tuple[bool, tuple[str, ...]]:
    unverified: list[str] = []
    stamina_ok = _check_resource(general.stamina, rule.min_general_stamina, "min_general_stamina", unverified)
    gold_ok = _check_resource(city.gold, rule.gold_cost, "gold_cost", unverified)
    food_ok = _check_resource(city.food, rule.food_cost, "food_cost", unverified)
    return (stamina_ok and gold_ok and food_ok), tuple(unverified)


def _simple_actions(
    general: VisibleGeneralFull, city: VisibleCityDetail, rules: DomesticRulesConfig
) -> list[Action]:
    out: list[Action] = []
    for kind, cls in (
        (ActionKind.RECRUIT_TROOPS, RecruitTroopsAction),
        (ActionKind.TRAIN_TROOPS, TrainTroopsAction),
        (ActionKind.SECURITY_PATROL, SecurityPatrolAction),
        (ActionKind.LEVY_GOLD, LevyGoldAction),
        (ActionKind.LEVY_FOOD, LevyFoodAction),
    ):
        if not rules.has_action(kind.value):
            continue
        rule = rules.action(kind.value)
        ok, unverified = _stamina_and_resource_check(general, city, rule)
        if not ok:
            continue
        out.append(cls(general_index=general.index, city_index=city.index, unverified_constraints=unverified))
    return out


def _facility_actions(
    general: VisibleGeneralFull, city: VisibleCityDetail, rules: DomesticRulesConfig
) -> list[Action]:
    if not rules.has_action(ActionKind.BUILD_FACILITY.value):
        return []
    rule = rules.action(ActionKind.BUILD_FACILITY.value)
    if rule.requires_facility_slot:
        available_slots = city.development_land_count - city.developed_land_count
        if available_slots <= 0:
            return []
    ok, unverified = _stamina_and_resource_check(general, city, rule)
    if not ok:
        return []
    # target_tile 只能取城池唯一的一组 domestic_land_x/y 坐标，不是空位列表里
    # 具体某一格——精度有限，见模块说明，固定标记为未验证约束。
    target_tile = (city.domestic_land_x, city.domestic_land_y)
    tile_unverified = unverified + ("target_tile_precision",)
    return [
        BuildFacilityAction(
            general_index=general.index,
            city_index=city.index,
            facility_type=facility_id,
            target_tile=target_tile,
            unverified_constraints=tile_unverified,
        )
        for facility_id in rule.sub_types
    ]


def _diplomacy_actions(
    general: VisibleGeneralFull,
    city: VisibleCityDetail,
    other_factions: Sequence[VisibleFactionPublic],
    rules: DomesticRulesConfig,
) -> list[Action]:
    if not rules.has_action(ActionKind.DIPLOMACY.value):
        return []
    rule = rules.action(ActionKind.DIPLOMACY.value)
    ok, unverified = _stamina_and_resource_check(general, city, rule)
    if not ok:
        return []
    return [
        DiplomacyAction(
            general_index=general.index,
            city_index=city.index,
            target_faction_index=faction.index,
            diplomacy_type=diplomacy_id,
            unverified_constraints=unverified,
        )
        for faction in other_factions
        for diplomacy_id in rule.sub_types
    ]


def _stratagem_actions(
    general: VisibleGeneralFull,
    city: VisibleCityDetail,
    enemy_cities: Sequence[VisibleCitySummary],
    rules: DomesticRulesConfig,
) -> list[Action]:
    if not rules.has_action(ActionKind.STRATAGEM.value):
        return []
    rule = rules.action(ActionKind.STRATAGEM.value)
    ok, unverified = _stamina_and_resource_check(general, city, rule)
    if not ok:
        return []
    return [
        StratagemAction(
            general_index=general.index,
            city_index=city.index,
            target_city_index=target.index,
            stratagem_type=stratagem_id,
            unverified_constraints=unverified,
        )
        for target in enemy_cities
        for stratagem_id in rule.sub_types
    ]


def enumerate_legal_actions(
    state: VisibleGameState,
    player_faction_id: int,
    assigned_general_indices: frozenset[int],
    rules: DomesticRulesConfig,
    *,
    is_general_in_city: GeneralInCityPredicate = default_is_general_in_city,
) -> list[Action]:
    """枚举内政阶段当前所有合法动作。

    只依赖 state（VisibleGameState）能看到的信息 + 显式传入的
    player_faction_id / assigned_general_indices / rules，不读取任何完整
    GameState 才有、VisibleGameState 没有的字段——这是本次 M4 的核心约束，
    见模块顶部说明与 tests/test_legal_actions.py 的架构守卫测试。

    约束覆盖情况（详见 docs/legal_actions_research.md）：
    - 武将已被指派：靠 assigned_general_indices 排除。
    - 体力：general.stamina > 0 是硬性门槛；具体每种动作的体力/金/粮消耗
      阈值来自 rules，未知时不拦，记录进 unverified_constraints。
    - 设施建设位是否可用：development_land_count - developed_land_count > 0。
    - 武将是否在这座城：is_general_in_city()，默认实现见 default_is_general_in_city，
      是一个未经验证的假设。
    - 城池是否己方：city.faction_id == player_faction_id。
    - 武将适性/特技：数据模型里没有可用字段，完全没有实现，见模块说明。
    """
    own_cities = [
        city
        for city in state.cities
        if isinstance(city, VisibleCityDetail) and city.faction_id == player_faction_id
    ]
    own_generals = [
        general
        for general in state.generals
        if isinstance(general, VisibleGeneralFull)
        and general.faction_id == player_faction_id
        and general.index not in assigned_general_indices
        and general.stamina > 0
    ]
    other_factions = [f for f in state.factions if f.index != player_faction_id]
    enemy_cities = [
        city
        for city in state.cities
        if city.faction_id is not None and city.faction_id != player_faction_id
    ]

    actions: list[Action] = []
    for city in own_cities:
        generals_here = [g for g in own_generals if is_general_in_city(g, city)]
        for general in generals_here:
            actions.extend(_simple_actions(general, city, rules))
            actions.extend(_facility_actions(general, city, rules))
            actions.extend(_diplomacy_actions(general, city, other_factions, rules))
            actions.extend(_stratagem_actions(general, city, enemy_cities, rules))
    return actions


def describe_action(action: Action, rules: DomesticRulesConfig) -> str:
    """人类可读的动作摘要，纯粹为了可观测性（调试/日志用），不是 Execute 的输入格式。"""
    rule = rules.actions.get(action.kind.value)
    name = rule.display_name_cn if rule else action.kind.value
    text = f"[武将{action.general_index}] 在 [城池{action.city_index}] 执行 {name}"
    if isinstance(action, BuildFacilityAction):
        sub = rule.sub_types.get(action.facility_type) if rule else None
        label = sub.display_name_cn if sub else action.facility_type
        text += f"（{label}，目标格 {action.target_tile}）"
    elif isinstance(action, DiplomacyAction):
        sub = rule.sub_types.get(action.diplomacy_type) if rule else None
        label = sub.display_name_cn if sub else action.diplomacy_type
        text += f"（{label} -> 势力{action.target_faction_index}）"
    elif isinstance(action, StratagemAction):
        sub = rule.sub_types.get(action.stratagem_type) if rule else None
        label = sub.display_name_cn if sub else action.stratagem_type
        text += f"（{label} -> 城池{action.target_city_index}）"
    if action.unverified_constraints:
        text += f" [未验证: {', '.join(action.unverified_constraints)}]"
    return text
