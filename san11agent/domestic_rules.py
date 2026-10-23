"""加载并校验 rules/*.json 内政动作规则表。

跟 offsets.py 是同一种做法（数值找不到可靠依据时标 unknown，不猜测填值），
但 unknown 语义不同——见 rules/schema.json 顶部说明：offsets 里 unknown 字段
被读取会直接报错拒绝（因为那是"内存地址，读错了会读到垃圾甚至崩溃"）；这里
unknown 字段被 legal_actions.py 使用时不会报错，而是被当作"这条规则暂不
限制"处理，并记录进枚举出的 Action.unverified_constraints，交给上层/人工
复核。原因见 rules/domestic_actions_pk_1.1_cn.json 的 meta.description：这份
表里要确认的大多是游戏规则数值本身（没有实机可跑，也没有找到权威资料），
不是内存偏移，如果沿用 offsets 的"拒绝读取"语义，LegalActions 在当前阶段
会完全产出不了任何动作，失去脚手架的意义。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class DomesticRulesError(Exception):
    """规则表文件格式错误。"""


@dataclass(frozen=True)
class RuleValue:
    """一个数值型规则（体力/金/粮消耗阈值等）。"""

    value: int | None
    unknown: bool
    confidence: str = "none"
    source: str = ""
    note: str = ""

    @property
    def is_known(self) -> bool:
        return not self.unknown and self.value is not None


_UNKNOWN_RULE_VALUE = RuleValue(value=None, unknown=True)


@dataclass(frozen=True)
class SubTypeSpec:
    id: str
    display_name_cn: str
    note: str = ""
    # 子类型自己的建设/发动费用。2026-08-18 起 build_facility 的 19 种设施各自
    # 有实机确认的资金造价（50~400 不等），所以费用必须按子类型表达——动作层级
    # 的 ActionRuleSpec.gold_cost 对 build_facility 而言没有统一值，仍是 unknown。
    # 未提供时默认 unknown，语义与其它 RuleValue 一致（不拦截、只标记未验证）。
    gold_cost: RuleValue = _UNKNOWN_RULE_VALUE
    # 2026-08-20 新增，仅 facility_types 用：设施耐久初始值（官方手册），语义
    # 同 gold_cost——按子类型区分，未提供时 unknown。
    durability: RuleValue = _UNKNOWN_RULE_VALUE
    # 2026-08-20 新增，仅 facility_types 用：设施效果的官方手册原文描述。效果
    # 种类因设施而异（收入加成/相邻倍率/每回合可执行次数/特殊限制等），没有
    # 统一成单一数值字段——保留原文比强行结构化更诚实，见 rules/schema.json。
    effect_note: str = ""


@dataclass(frozen=True)
class ActionRuleSpec:
    kind: str
    display_name_cn: str
    requires_own_city: bool
    requires_facility_slot: bool
    min_general_stamina: RuleValue
    gold_cost: RuleValue
    food_cost: RuleValue
    # 基础行動力标价；有条件折扣时不能直接用作硬性余额门槛。
    action_points_cost: RuleValue = _UNKNOWN_RULE_VALUE
    sub_types: dict[str, SubTypeSpec] = field(default_factory=dict)
    note: str = ""
    # 已核实有效费用，未知时不把手册基础标价当实际费用。
    # 2026-10-23仅生产巡察由REA检查/扣费路径确认，见相应研究报告。
    effective_action_points_cost: RuleValue = _UNKNOWN_RULE_VALUE


@dataclass(frozen=True)
class DomesticRulesConfig:
    label: str
    verified: bool
    actions: dict[str, ActionRuleSpec]
    raw: dict[str, Any] = field(repr=False)

    def action(self, kind: str) -> ActionRuleSpec:
        if kind not in self.actions:
            raise DomesticRulesError(f"规则表里没有动作类型 {kind!r}")
        return self.actions[kind]

    def has_action(self, kind: str) -> bool:
        return kind in self.actions


_SUB_TYPE_KEYS = ("facility_types", "equipment_types", "tech_types", "diplomacy_types", "stratagem_types")


def _load_rule_value(raw: dict[str, Any] | None) -> RuleValue:
    if raw is None:
        return _UNKNOWN_RULE_VALUE
    if "unknown" not in raw:
        raise DomesticRulesError("规则数值缺少必填的 unknown 标记")
    unknown = bool(raw["unknown"])
    value = raw.get("value")
    if not unknown and value is None:
        raise DomesticRulesError("规则数值 unknown=false 但没有给 value，格式不一致")
    return RuleValue(
        value=value,
        unknown=unknown,
        confidence=raw.get("confidence", "none"),
        source=raw.get("source", ""),
        note=raw.get("note", ""),
    )


def _load_sub_types(raw_action: dict[str, Any]) -> dict[str, SubTypeSpec]:
    sub_types: dict[str, SubTypeSpec] = {}
    for key in _SUB_TYPE_KEYS:
        raw_map = raw_action.get(key)
        if not raw_map:
            continue
        for sub_id, sub_raw in raw_map.items():
            if "display_name_cn" not in sub_raw:
                raise DomesticRulesError(f"子类型 {sub_id!r} 缺少 display_name_cn")
            if sub_id in sub_types:
                raise DomesticRulesError(f"子类型 id {sub_id!r} 在多个 *_types 分组里重复出现")
            sub_types[sub_id] = SubTypeSpec(
                id=sub_id,
                display_name_cn=sub_raw["display_name_cn"],
                note=sub_raw.get("note", ""),
                gold_cost=_load_rule_value(sub_raw.get("gold_cost")),
                durability=_load_rule_value(sub_raw.get("durability")),
                effect_note=sub_raw.get("effect_note", ""),
            )
    return sub_types


def _load_action_rule(kind: str, raw: dict[str, Any]) -> ActionRuleSpec:
    if "display_name_cn" not in raw or "requires_own_city" not in raw:
        raise DomesticRulesError(f"动作类型 {kind!r} 缺少 display_name_cn 或 requires_own_city")
    effective_cost = _load_rule_value(raw.get("effective_action_points_cost"))
    if effective_cost.is_known and (
        type(effective_cost.value) is not int or effective_cost.value < 0
    ):
        raise DomesticRulesError(f"动作类型 {kind!r} 的有效行動力费用必须是非负整数")
    return ActionRuleSpec(
        kind=kind,
        display_name_cn=raw["display_name_cn"],
        requires_own_city=bool(raw["requires_own_city"]),
        requires_facility_slot=bool(raw.get("requires_facility_slot", False)),
        min_general_stamina=_load_rule_value(raw.get("min_general_stamina")),
        gold_cost=_load_rule_value(raw.get("gold_cost")),
        food_cost=_load_rule_value(raw.get("food_cost")),
        action_points_cost=_load_rule_value(raw.get("action_points_cost")),
        effective_action_points_cost=effective_cost,
        sub_types=_load_sub_types(raw),
        note=raw.get("note", ""),
    )


def load_domestic_rules(path: str | Path) -> DomesticRulesConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))

    if "meta" not in raw or "actions" not in raw:
        raise DomesticRulesError("规则表文件缺少顶层字段 meta 或 actions")

    meta = raw["meta"]
    if "label" not in meta or "verified" not in meta:
        raise DomesticRulesError("规则表 meta 缺少 label 或 verified")

    actions = {
        kind: _load_action_rule(kind, raw_action) for kind, raw_action in raw["actions"].items()
    }

    return DomesticRulesConfig(
        label=meta["label"],
        verified=bool(meta["verified"]),
        actions=actions,
        raw=raw,
    )
