"""M5：战术执行层（内政）——把高层 StrategicIntent 翻译成具体动作。

项目规格 3.4 节："战术执行层：用规则或搜索算法把意图翻译成具体动作。"本次
只实现内政这一半（对应 M4 `enumerate_legal_actions()` 枚举的动作），出征/
战斗相关的战术翻译留给未来有战斗执行层之后再做。

**本模块的核心约束，和 M4 的"只能从合法动作里选"是同一条原则的延续**：
`select_domestic_actions()` 返回的每个 `TacticalDecision.action`，必须是
传入的 `legal_actions` 参数里的同一个对象（不是"字段恰好相等的另一个对象"，
是同一个 Python 对象）——本模块只允许"挑选"，不允许"编造"。这是把 M4
"LegalActions：AI 不需要猜规则，也不会输出非法指令"这条保证，原样传递到
战术层的关键：如果战术层可以自己拼一个新的 Action 对象返回，M4 的保证在
这一层就失效了。`tests/test_domestic_tactics.py` 用 `is` 身份检查（不是
`==` 结构相等检查）守住这一点。

实现方式是纯规则：先按 `general_index` 把 `legal_actions` 分组（M4 的
enumerate_legal_actions() 保证同一位武将在结果里只会出现在一座城，见下面
的防御性检查），再按这座城对应的意图重心（`intent.directive_for(city_index)`）
查一张"这种重心优先选哪类动作"的表，选第一个该武将实际拥有的匹配动作；
一条都不匹配时退化成"随便选这位武将合法动作里的第一条"（保底：只要
legal_actions 里这位武将有动作，战术层一定会给他分配一条，不会漏派）。
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from .domestic_rules import DomesticRulesConfig
from .intent import DomesticFocus, StrategicIntent
from .legal_actions import Action, ActionKind, BuildFacilityAction, describe_action


class TacticalError(Exception):
    """战术层遇到违反自身假设的输入（不是"意图不合法"，是"legal_actions 本身
    结构不符合预期"），fail closed 而不是猜一个动作出来。
    """


@dataclass(frozen=True, kw_only=True)
class TacticalDecision:
    """战术层对一位武将的分配结果，连同"为什么选它"一起记录——这一层的
    可观测性尤其重要（项目要求"优先保证可观测性——这一层尤其重要，要能看清
    LLM 为什么做了某个决策、意图怎么变成动作的"），所以 reason 不是可选项。
    """

    action: Action
    general_index: int
    city_index: int
    focus: DomesticFocus
    reason: str


# 每种内政重心，优先尝试的 ActionKind 顺序。排在前面的先试，武将在这条动作
# 上没有对应的合法动作就往后退，全部试完还没有就走最终的"保底随便选"分支。
# 2026-08-18：原先 ECONOMY 首选 LEVY_GOLD、AGRICULTURE 首选 LEVY_FOOD，但实机
# 截图确认"征收"指令在三国志11里根本不存在（金粮按回合自动结算），两个
# ActionKind 已删除，见 docs/offset_research.md 第8.2节①。删除后这两个重心
# 都改为首选 BUILD_FACILITY——它们之间的区别由下面的
# _FOCUS_FACILITY_PREFERENCE 承担（ECONOMY 选市场系、AGRICULTURE 选农场系），
# 这比原来靠两个不存在的指令来区分更贴近游戏真实机制。
_FOCUS_ACTION_PRIORITY: dict[DomesticFocus, tuple[ActionKind, ...]] = {
    DomesticFocus.ECONOMY: (
        ActionKind.BUILD_FACILITY, ActionKind.TRAIN_TROOPS,
        ActionKind.SECURITY_PATROL, ActionKind.RECRUIT_TROOPS,
        ActionKind.DIPLOMACY, ActionKind.STRATAGEM,
    ),
    DomesticFocus.AGRICULTURE: (
        ActionKind.BUILD_FACILITY, ActionKind.SECURITY_PATROL,
        ActionKind.TRAIN_TROOPS, ActionKind.RECRUIT_TROOPS,
        ActionKind.DIPLOMACY, ActionKind.STRATAGEM,
    ),
    DomesticFocus.MILITARY: (
        ActionKind.RECRUIT_TROOPS, ActionKind.TRAIN_TROOPS, ActionKind.BUILD_FACILITY,
        ActionKind.SECURITY_PATROL,
        ActionKind.DIPLOMACY, ActionKind.STRATAGEM,
    ),
    DomesticFocus.SECURITY: (
        ActionKind.SECURITY_PATROL, ActionKind.BUILD_FACILITY,
        ActionKind.TRAIN_TROOPS, ActionKind.RECRUIT_TROOPS,
        ActionKind.DIPLOMACY, ActionKind.STRATAGEM,
    ),
    DomesticFocus.BALANCED: (
        ActionKind.SECURITY_PATROL, ActionKind.RECRUIT_TROOPS,
        ActionKind.TRAIN_TROOPS, ActionKind.BUILD_FACILITY,
        ActionKind.DIPLOMACY, ActionKind.STRATAGEM,
    ),
}

# BUILD_FACILITY 命中时，按重心进一步优先选哪种 facility_type 子类型
# （id 取自 rules/domestic_actions_pk_1.1_cn.json 的 facility_types）。
# 一条都不在该武将的可选项里时，退回选第一个可用的子类型。
_FOCUS_FACILITY_PREFERENCE: dict[DomesticFocus, tuple[str, ...]] = {
    DomesticFocus.ECONOMY: ("market",),
    DomesticFocus.AGRICULTURE: ("farm",),
    DomesticFocus.MILITARY: ("barracks", "stable"),
    DomesticFocus.SECURITY: ("crossbow_tower",),
    DomesticFocus.BALANCED: (),
}


def _pick_facility(candidates: Sequence[BuildFacilityAction], focus: DomesticFocus) -> BuildFacilityAction:
    for facility_type in _FOCUS_FACILITY_PREFERENCE.get(focus, ()):
        for action in candidates:
            if action.facility_type == facility_type:
                return action
    return candidates[0]


def _pick_action(actions: Sequence[Action], focus: DomesticFocus) -> tuple[Action, str]:
    by_kind: dict[ActionKind, list[Action]] = defaultdict(list)
    for action in actions:
        by_kind[action.kind].append(action)

    for kind in _FOCUS_ACTION_PRIORITY[focus]:
        candidates = by_kind.get(kind)
        if not candidates:
            continue
        if kind is ActionKind.BUILD_FACILITY:
            chosen = _pick_facility(candidates, focus)  # type: ignore[arg-type]
        else:
            chosen = candidates[0]
        return chosen, f"聚焦={focus.value}，命中优先级顺序里的 {kind.value}"

    # 优先级表里列出的类型（已经覆盖全部 8 种 ActionKind）在这位武将身上一条
    # 都没有合法动作可选——理论上不该发生，但保底选第一条，保证不漏派这位
    # 武将，而不是让他这个回合完全不动。
    fallback = actions[0]
    return fallback, f"聚焦={focus.value} 下优先级列表未命中，保底选择 {fallback.kind.value}"


def select_domestic_actions(
    intent: StrategicIntent, legal_actions: Sequence[Action], rules: DomesticRulesConfig
) -> list[TacticalDecision]:
    """核心约束见模块说明：返回的每个 action 必须是 legal_actions 里的同一个
    对象。实现上天然满足——candidates/chosen 全程直接来自对 legal_actions 的
    分组，从未构造过任何新的 Action 实例。
    """
    by_general: dict[int, list[Action]] = defaultdict(list)
    for action in legal_actions:
        by_general[action.general_index].append(action)

    decisions: list[TacticalDecision] = []
    for general_index, actions_for_general in by_general.items():
        distinct_cities = {a.city_index for a in actions_for_general}
        if len(distinct_cities) > 1:
            raise TacticalError(
                f"武将 {general_index} 在 legal_actions 里出现于多座城池 {sorted(distinct_cities)}，"
                "违反 enumerate_legal_actions() '一位武将只属于一座城'的假设，战术层无法安全分配。"
            )
        city_index = next(iter(distinct_cities))
        focus = intent.directive_for(city_index).focus
        action, reason = _pick_action(actions_for_general, focus)
        decisions.append(
            TacticalDecision(
                action=action, general_index=general_index, city_index=city_index, focus=focus,
                reason=f"{reason} | {describe_action(action, rules)}",
            )
        )
    return decisions
