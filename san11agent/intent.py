"""M5：高层战略意图的结构化类型体系。

项目规格 3.4 节要求 LLM 战略层的输出是"高层意图"，不是自由文本——下游的
战术执行层（`domestic_tactics.py`）必须能直接消费它、程序也必须能验证它是否
合法（比如 `default_focus` 是不是已知枚举值），而不是每次都靠字符串匹配去
猜测 LLM 想干什么。这是本模块存在的理由：把"内政重心/谁去镇守/攻打哪个
势力/往哪个方向扩张"这几项规格里点名的高层意图，落成可以被程序检查、被
`==` 比较、被测试断言的 dataclass，而不是一段话。

本次战术执行层只实现了内政（见 `domestic_tactics.py` 模块说明），所以
`target_faction_index` / `expansion_notes` 这两个字段目前只被 LLM 写入、被
`ActionLog`/摘要记录下来，不驱动任何实际动作选择——它们对应规格里"攻打哪个
势力""往哪个方向扩张"这两项，等未来的战斗/战略执行层做出来后才会真正消费。
这次先把类型占位占好，避免下一个里程碑还要重新设计 Intent 的顶层结构。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DomesticFocus(Enum):
    """内政重心，对应项目规格"高层意图"里的"内政重心"一项。

    只有这 5 种取值——不用自由文本的原因见模块说明：`domestic_tactics.py`
    靠这个枚举去查一张固定的"这种重心优先选哪类动作"的表，取值集合必须是
    封闭的、程序能穷举校验的。
    """

    ECONOMY = "economy"  # 金钱优先：征收金、建市场
    AGRICULTURE = "agriculture"  # 粮食优先：征收粮、建农田
    MILITARY = "military"  # 军事优先：征兵/训练、建兵营马厩
    SECURITY = "security"  # 治安优先：治安巡查、建弩楼
    BALANCED = "balanced"  # 均衡：不特别偏向某一类


@dataclass(frozen=True, kw_only=True)
class CityDirective:
    """针对单座城池覆盖默认内政重心。

    对应规格里"谁去镇守要地"的记录位：`garrison_general_index` 目前只是
    LLM 写下来的一个标记，`domestic_tactics.py` 不会读它、也不会因此把某位
    武将排除出内政动作分配——"镇守"在没有战斗/出征层的当前阶段没有可执行的
    含义，这是有意的占位，不是遗漏，见提交报告"需要你确认的取舍"一节。
    """

    city_index: int
    focus: DomesticFocus
    garrison_general_index: int | None = None


@dataclass(frozen=True, kw_only=True)
class StrategicIntent:
    """一次 LLM 战略层调用产出的高层意图快照。

    `turn` 记录这个意图是在哪个回合由 LLM 产出的，方便下游/日志判断"这个
    意图是不是已经过期太久还在被沿用"（比如 LLM 调用间隔 N 很大、又连续
    解析失败时，主循环会一直复用同一个旧 `StrategicIntent`，见 `strategy_loop.py`）。
    """

    turn: int
    default_focus: DomesticFocus = DomesticFocus.BALANCED
    city_directives: tuple[CityDirective, ...] = ()
    target_faction_index: int | None = None
    expansion_notes: str = ""
    rationale: str = ""

    def directive_for(self, city_index: int) -> CityDirective:
        """给定城池，返回对它生效的 CityDirective——有显式覆盖就用覆盖，
        否则回退成一个用 default_focus 合成的"虚拟"CityDirective。
        """
        for directive in self.city_directives:
            if directive.city_index == city_index:
                return directive
        return CityDirective(city_index=city_index, focus=self.default_focus)


DEFAULT_INTENT = StrategicIntent(turn=0)
"""主循环在第一次成功调用 LLM 之前使用的安全默认值：均衡重心、无城池覆盖。"""
