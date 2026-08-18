"""M5：LLM 战略层接口——抽象 + 假后端 + 提示词组织 + 输出解析。

项目规格 3.4 节："LLM 战略层：每 N 个回合调用一次。输入是摘要化的局势 + 战略
备忘录，输出是高层意图。"

**本次不接任何真实 LLM API**（用户明确要求）。`StrategyLLM` 是这一层唯一的
抽象接口，真实实现（调用 Claude/GPT 等 API）留给下一个里程碑；这次只提供
`FakeStrategyLLM`——可脚本化返回预设的原始文本，供离线测试和 `strategy_loop.py`
的空跑验证使用。

**为什么 `StrategyLLM.decide()` 返回原始字符串，而不是直接返回
`StrategicIntent`**：这是刻意的设计，用来贴近真实 LLM 的调用形态——真实 LLM
返回的是文本（哪怕是要求了 JSON 格式的文本），可能格式错误、可能漏字段、
可能夹带解释性废话。把"调用 LLM"和"解析 LLM 输出"分成两步（`decide()` +
`parse_llm_response()`），"LLM 返回非法/无法解析内容时怎么办"这个问题就能
在解析这一步独立处理、独立测试，不需要每个 `StrategyLLM` 实现自己各写一套
解析和容错逻辑。

**输出格式选择 JSON**：没有选自由文本 + 正则/关键词提取，是因为结构化意图
（第4节）本身有嵌套字段（`city_directives` 是一个列表），JSON 是最不容易
产生"这段话到底是什么意思"歧义的格式，也是目前主流 LLM API 原生支持"要求
按 schema 输出"的格式（tool use / JSON mode）。这是一个需要你确认的选择——
如果你更倾向于别的结构化格式（比如更严格的 tool-use 强制 schema，或者更
宽松的自由文本 + 单独一次"提取"调用），见提交报告"需要你确认的取舍"一节。
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .intent import CityDirective, DomesticFocus, StrategicIntent
from .strategy_memo import DEFAULT_MAX_BODY_CHARS

_VALID_FOCUS_VALUES = tuple(f.value for f in DomesticFocus)


class StrategyParseError(Exception):
    """LLM 返回的原始文本无法被解析成合法的 (memo_body, StrategicIntent)。

    携带具体原因（哪个字段、为什么不合法），供 strategy_loop.py 记录进
    ActionLog 做可观测性——"LLM 说了什么导致被拒绝"应该能在日志里查到，不能
    只是一个笼统的"解析失败"。
    """


@dataclass(frozen=True)
class StrategyPrompt:
    """一次 LLM 战略层调用的完整输入。三段拼起来就是最终喂给 LLM 的文本，
    拆开保留是为了测试/日志能分别检查"局势摘要对不对""备忘录有没有传进去"，
    不用整段字符串做子串匹配。
    """

    turn: int
    situation_text: str
    memo_text: str
    instructions: str

    def render(self) -> str:
        return (
            f"# 回合 {self.turn} 战略决策\n\n"
            f"## 当前局势\n{self.situation_text}\n\n"
            f"## 战略备忘录（上一次调用留下的，可能为空）\n{self.memo_text}\n\n"
            f"## 输出要求\n{self.instructions}\n"
        )


_INSTRUCTIONS_TEMPLATE = """请只输出一个 JSON 对象（不要有任何 JSON 之外的说明文字），格式如下：

{{
  "memo": "<更新后的战略备忘录正文，Markdown，不超过 {max_memo_chars} 字符>",
  "intent": {{
    "default_focus": "<{focus_values} 之一>",
    "city_directives": [
      {{"city_index": <int>, "focus": "<同上>", "garrison_general_index": <int 或 null>}}
    ],
    "target_faction_index": <int 或 null，暂不驱动任何动作，仅记录>,
    "expansion_notes": "<自由文本，暂不驱动任何动作，仅记录>",
    "rationale": "<这次决策的理由，供人工复核>"
  }}
}}

city_directives 可以是空列表——只想设置 default_focus 时不需要为每座城单独
写一条。"""


def build_strategy_prompt(
    *, turn: int, situation_text: str, memo_text: str, max_memo_chars: int = DEFAULT_MAX_BODY_CHARS
) -> StrategyPrompt:
    instructions = _INSTRUCTIONS_TEMPLATE.format(
        max_memo_chars=max_memo_chars, focus_values="|".join(_VALID_FOCUS_VALUES)
    )
    return StrategyPrompt(turn=turn, situation_text=situation_text, memo_text=memo_text, instructions=instructions)


class StrategyLLM(ABC):
    """LLM 战略层的抽象接口。真实实现（调用真实 API）不在本次范围内。"""

    @abstractmethod
    def decide(self, prompt: StrategyPrompt) -> str:
        """返回原始文本（未解析）。调用方必须自己走 parse_llm_response() 解析，
        并处理解析失败的情况——这一层不保证返回值是合法格式。
        """


@dataclass(frozen=True)
class StrategyLLMCallRecord:
    """一次调用的完整记录，供测试/日志检查"传进去的 prompt 和吐出来的原始
    文本分别是什么"，而不用重新拼一遍。
    """

    prompt: StrategyPrompt
    raw_response: str


class FakeStrategyLLM(StrategyLLM):
    """可脚本化的假 LLM 后端：从不联网、不调用任何真实模型。

    两种驱动方式：
    - responses 是一个字符串序列：按调用顺序依次返回，用尽后再调用会抛
      IndexError（比 StopIteration 更明确指出"是脚本没写够，不是正常结束"）。
    - responses 是一个 callable：每次调用时传入 StrategyPrompt，由它动态
      决定返回什么——用于需要"看到局势里的具体数字才能决定返回什么"的测试
      场景（比如模拟"LLM 前几次都返回非法内容，第3次才返回合法内容"）。
    """

    def __init__(self, responses: Sequence[str] | Callable[[StrategyPrompt], str]):
        self._responses = responses
        self._call_index = 0
        self.calls: list[StrategyLLMCallRecord] = []

    def decide(self, prompt: StrategyPrompt) -> str:
        if callable(self._responses):
            raw = self._responses(prompt)
        else:
            if self._call_index >= len(self._responses):
                raise IndexError(
                    f"FakeStrategyLLM 预设响应用尽：已调用 {self._call_index + 1} 次，"
                    f"只提供了 {len(self._responses)} 条预设响应"
                )
            raw = self._responses[self._call_index]
            self._call_index += 1
        self.calls.append(StrategyLLMCallRecord(prompt=prompt, raw_response=raw))
        return raw


@dataclass(frozen=True)
class ParsedStrategyResponse:
    memo_body: str
    intent: StrategicIntent


def format_strategy_response(
    memo_body: str,
    *,
    default_focus: DomesticFocus = DomesticFocus.BALANCED,
    city_directives: Sequence[CityDirective] = (),
    target_faction_index: int | None = None,
    expansion_notes: str = "",
    rationale: str = "",
) -> str:
    """反向工具函数：把一组结构化字段拼成 parse_llm_response() 能解析的 JSON
    字符串。主要供测试/FakeStrategyLLM 脚本化响应使用，避免每个测试都手写
    容易打错字的 JSON 字符串字面量。
    """
    payload = {
        "memo": memo_body,
        "intent": {
            "default_focus": default_focus.value,
            "city_directives": [
                {
                    "city_index": d.city_index,
                    "focus": d.focus.value,
                    "garrison_general_index": d.garrison_general_index,
                }
                for d in city_directives
            ],
            "target_faction_index": target_faction_index,
            "expansion_notes": expansion_notes,
            "rationale": rationale,
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def parse_llm_response(raw_text: str, *, turn: int) -> ParsedStrategyResponse:
    """把 LLM 的原始文本解析成 (备忘录正文, StrategicIntent)。

    任何结构/类型/取值不对的地方都会 fail closed——抛 StrategyParseError，
    不猜测、不给默认值悄悄补上（除了 city_directives/target_faction_index/
    expansion_notes/rationale 这几个规格里本来就允许"没有"的可选字段）。
    调用方（strategy_loop.py）收到异常后应该保留上一轮的 intent/memo 不变，
    见 strategy_loop.py 模块说明。

    注意：这里只做结构/类型/枚举取值校验，不检查 memo 的长度预算——长度是
    strategy_memo.write_memo() 的职责（单一事实来源），调用方需要分别处理
    两类失败：这里抛出代表"LLM 输出格式不对"，write_memo() 抛出代表"格式对，
    但正文太长"。
    """
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise StrategyParseError(f"LLM 返回内容不是合法 JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise StrategyParseError("LLM 返回内容顶层必须是一个 JSON 对象")

    memo_body = payload.get("memo")
    if not isinstance(memo_body, str):
        raise StrategyParseError("缺少字符串字段 'memo'")

    intent_raw = payload.get("intent")
    if not isinstance(intent_raw, dict):
        raise StrategyParseError("缺少对象字段 'intent'")

    default_focus_raw = intent_raw.get("default_focus", DomesticFocus.BALANCED.value)
    if default_focus_raw not in _VALID_FOCUS_VALUES:
        raise StrategyParseError(
            f"intent.default_focus 取值非法: {default_focus_raw!r}，必须是 {_VALID_FOCUS_VALUES} 之一"
        )

    directives: list[CityDirective] = []
    raw_directives = intent_raw.get("city_directives") or []
    if not isinstance(raw_directives, list):
        raise StrategyParseError("intent.city_directives 必须是列表")
    for i, raw_d in enumerate(raw_directives):
        if not isinstance(raw_d, dict):
            raise StrategyParseError(f"intent.city_directives[{i}] 必须是对象")
        if "city_index" not in raw_d or "focus" not in raw_d:
            raise StrategyParseError(f"intent.city_directives[{i}] 缺少 city_index 或 focus")
        city_index = raw_d["city_index"]
        if not isinstance(city_index, int) or isinstance(city_index, bool):
            raise StrategyParseError(f"intent.city_directives[{i}].city_index 必须是整数")
        focus_raw = raw_d["focus"]
        if focus_raw not in _VALID_FOCUS_VALUES:
            raise StrategyParseError(
                f"intent.city_directives[{i}].focus 取值非法: {focus_raw!r}"
            )
        garrison = raw_d.get("garrison_general_index")
        if garrison is not None and (not isinstance(garrison, int) or isinstance(garrison, bool)):
            raise StrategyParseError(
                f"intent.city_directives[{i}].garrison_general_index 必须是整数或 null"
            )
        directives.append(
            CityDirective(city_index=city_index, focus=DomesticFocus(focus_raw), garrison_general_index=garrison)
        )

    target_faction_index = intent_raw.get("target_faction_index")
    if target_faction_index is not None and (
        not isinstance(target_faction_index, int) or isinstance(target_faction_index, bool)
    ):
        raise StrategyParseError("intent.target_faction_index 必须是整数或 null")

    intent = StrategicIntent(
        turn=turn,
        default_focus=DomesticFocus(default_focus_raw),
        city_directives=tuple(directives),
        target_faction_index=target_faction_index,
        expansion_notes=str(intent_raw.get("expansion_notes", "")),
        rationale=str(intent_raw.get("rationale", "")),
    )
    return ParsedStrategyResponse(memo_body=memo_body, intent=intent)
