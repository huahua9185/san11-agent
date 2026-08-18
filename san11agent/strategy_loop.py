"""M5：主循环——串起"读状态 -> （每 N 回合）调 LLM 更新备忘录与意图 -> 战术层
出动作 -> 执行 -> 推进回合"这条完整链路。对应项目规格的 M5 验收目标：

    跑通"AI 决策 -> 执行 -> 推进回合"的完整循环，能连续自动推进若干回合。

**本次不接真实游戏、不接真实 LLM**（用户明确要求）。两处都是可替换的抽象：

- `GameStateSource`：读状态 + 推进回合。真实实现需要 M1 的内存读取 + M2 的
  `filter_game_state()` + 一个真正"点结束内政"之类的 Execute 动作（目前完全
  没有实现，M3 的 Execute 只做到了"点选城池"这一条最小链路），这次只提供
  `FakeGameStateSource`，包一份可变的 VisibleGameState，`advance_turn()`
  只是把 `current_xun` 加一，模拟"回合真的推进了"，不代表真的操作了游戏。
- `ActionExecutor`：把 `Action` 变成真实键鼠输入。这一环完全没有真实实现
  （跟 M3 `select_city` 之外的一切内政动作 Execute 一样，属于"等真实游戏
  能跑再做"的范围），这次复用 M3 `FakeInputBackend` 的思路，提供
  `FakeActionExecutor`——只记录调用，不做任何真实操作。

**LLM 调用节奏**：`StrategyLoopConfig.llm_call_interval` 控制"每 N 回合调用
一次"，用 `state.global_state.current_xun % N == 0` 判断，外加"从来没有成功
调用过 LLM"时强制调用一次（否则如果 N 不整除起始回合数，可能永远轮不到）。

**LLM 返回非法/无法解析内容时的处理策略**（对应规格要求的"处理策略"）：
1. `parse_llm_response()` 抛 `StrategyParseError`（格式/类型/枚举取值不对）：
   本回合保留上一轮的 `StrategicIntent` 不变，记一条 `strategy.llm_response_invalid`
   日志，`_consecutive_llm_failures` 计数 +1。
2. `strategy_memo.write_memo()` 抛 `StrategyMemoTooLongError`（格式对，但正文
   超预算）：新 intent 仍然采用（intent 解析已经成功，跟备忘录是否能落盘是
   两件独立的事），但备忘录文件保持旧内容不变，记一条
   `strategy.memo_write_rejected` 日志。
3. `strategy_memo.read_memo()` 抛 `StrategyMemoCorruptedError`（文件被外部
   改动/损坏）：尝试 `restore_backup()` 回退到上一版；如果连备份都没有，
   让异常继续往上抛——这种情况已经不是"LLM 说了不合规范的话"能解决的问题，
   需要人工介入，主循环不应该假装什么都没发生。
4. 连续失败达到 `max_consecutive_llm_failures` 次：抛 `StrategyLoopError`
   停止循环，而不是无限拿着一个可能早就过期的旧 intent 静默空转——这是本
   模块的一个明确取舍，如果你认为"哪怕 LLM 一直失败也应该继续用旧 intent
   跑下去、不停止"更符合预期，把这个阈值调大或改成 None（不设上限）即可，
   见提交报告"需要你确认的取舍"一节。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from . import strategy_memo
from .action_log import ActionLog
from .domestic_rules import DomesticRulesConfig
from .domestic_tactics import TacticalDecision, select_domestic_actions
from .intent import DEFAULT_INTENT, StrategicIntent
from .legal_actions import Action, enumerate_legal_actions
from .situation_summary import render_situation_text, summarize_situation
from .strategy_llm import StrategyLLM, StrategyParseError, build_strategy_prompt, parse_llm_response
from .visible_state import VisibleGameState


class StrategyLoopError(Exception):
    """主循环因为不可恢复的情况停止（连续多次 LLM 输出无法使用、或备忘录
    损坏且没有可用备份）。
    """


class GameStateSource(ABC):
    """读局势 + 推进回合的抽象。真实实现留给下一个里程碑（依赖 M1 内存读取 +
    M2 过滤器 + 尚不存在的"结束本回合内政"Execute 动作）。
    """

    @abstractmethod
    def read(self) -> VisibleGameState: ...

    @abstractmethod
    def advance_turn(self) -> None:
        """推进到下一回合。假实现只是让 current_xun 加一，不代表真的操作了
        游戏——真实实现需要真正点击游戏里的"结束内政"之类的输入。
        """


class FakeGameStateSource(GameStateSource):
    """离线测试/空跑用：包一份可变的 VisibleGameState，advance_turn() 只把
    current_xun 加一。不模拟任何游戏规则的副作用（比如动作执行后金钱/粮草
    真的减少）——这次的验收目标是"循环本身能连续推进若干回合"，不是"模拟
    完整的游戏经济"，见提交报告范围说明。
    """

    def __init__(self, state: VisibleGameState):
        self._state = state

    def read(self) -> VisibleGameState:
        return self._state

    def advance_turn(self) -> None:
        self._state.global_state.current_xun += 1


@dataclass(frozen=True, kw_only=True)
class ExecutionOutcome:
    action: Action
    result: str
    detail: str = ""


class ActionExecutor(ABC):
    """把一个 Action 真正变成游戏操作的抽象。真实实现（Execute）本次完全
    没有做，见模块说明。
    """

    @abstractmethod
    def execute(self, action: Action) -> ExecutionOutcome: ...


class FakeActionExecutor(ActionExecutor):
    """复用 M3 FakeInputBackend 的思路：只记录调用，不做任何真实操作。
    on_execute 是可选回调，供测试观察/在回调里模拟"执行后状态发生了变化"。
    """

    def __init__(self, *, on_execute=None):
        self.calls: list[Action] = []
        self._on_execute = on_execute

    def execute(self, action: Action) -> ExecutionOutcome:
        self.calls.append(action)
        if self._on_execute:
            self._on_execute(action)
        return ExecutionOutcome(action=action, result="sent", detail="FakeActionExecutor：未真正执行，仅记录调用")


@dataclass(frozen=True, kw_only=True)
class StrategyLoopConfig:
    llm_call_interval: int = 5
    max_memo_body_chars: int = strategy_memo.DEFAULT_MAX_BODY_CHARS
    max_consecutive_llm_failures: int = 3


@dataclass(frozen=True, kw_only=True)
class TurnResult:
    """一回合空跑的完整结果，供测试断言、也供调用方做进一步的可观测性展示。"""

    turn: int
    llm_called: bool
    intent: StrategicIntent
    decisions: tuple[TacticalDecision, ...]
    outcomes: tuple[ExecutionOutcome, ...]


class StrategyLoop:
    def __init__(
        self,
        *,
        state_source: GameStateSource,
        player_faction_id: int,
        rules: DomesticRulesConfig,
        strategy_llm: StrategyLLM,
        action_executor: ActionExecutor,
        memo_path: str | Path,
        action_log: ActionLog,
        config: StrategyLoopConfig = StrategyLoopConfig(),
    ):
        self._state_source = state_source
        self._player_faction_id = player_faction_id
        self._rules = rules
        self._llm = strategy_llm
        self._executor = action_executor
        self._memo_path = Path(memo_path)
        self._log = action_log
        self._config = config

        self._current_intent: StrategicIntent = DEFAULT_INTENT
        self._llm_called_at_least_once = False
        self._consecutive_llm_failures = 0

    @property
    def current_intent(self) -> StrategicIntent:
        return self._current_intent

    def run_turns(self, n: int) -> list[TurnResult]:
        return [self.run_one_turn() for _ in range(n)]

    def run_one_turn(self) -> TurnResult:
        state = self._state_source.read()
        turn = state.global_state.current_xun

        should_call_llm = (not self._llm_called_at_least_once) or (turn % self._config.llm_call_interval == 0)
        if should_call_llm:
            self._call_llm(state, turn)

        # 一将一令，每回合从空集合重新开始——本回合内没有跨调用持久化的
        # "已指派"状态，跟 legal_actions.py 里同一个概念的说明一致。
        assigned: frozenset[int] = frozenset()
        legal = enumerate_legal_actions(state, self._player_faction_id, assigned, self._rules)
        decisions = select_domestic_actions(self._current_intent, legal, self._rules)

        outcomes = []
        for decision in decisions:
            outcome = self._executor.execute(decision.action)
            outcomes.append(outcome)
            self._log.record(
                intent=f"tactical.{decision.action.kind.value}",
                params={
                    "general_index": decision.general_index,
                    "city_index": decision.city_index,
                    "focus": decision.focus.value,
                },
                result=outcome.result,
                detail=decision.reason,
            )

        self._state_source.advance_turn()

        return TurnResult(
            turn=turn, llm_called=should_call_llm, intent=self._current_intent,
            decisions=tuple(decisions), outcomes=tuple(outcomes),
        )

    def _call_llm(self, state: VisibleGameState, turn: int) -> None:
        memo = self._read_memo_with_recovery(turn)

        summary = summarize_situation(state, self._player_faction_id)
        situation_text = render_situation_text(summary)
        prompt = build_strategy_prompt(
            turn=turn, situation_text=situation_text, memo_text=memo.body,
            max_memo_chars=self._config.max_memo_body_chars,
        )
        raw_response = self._llm.decide(prompt)

        try:
            parsed = parse_llm_response(raw_response, turn=turn)
        except StrategyParseError as exc:
            self._consecutive_llm_failures += 1
            self._log.record(
                intent="strategy.llm_response_invalid",
                params={"turn": turn, "consecutive_failures": self._consecutive_llm_failures},
                result="failure",
                detail=str(exc),
            )
            if self._consecutive_llm_failures >= self._config.max_consecutive_llm_failures:
                raise StrategyLoopError(
                    f"LLM 连续 {self._consecutive_llm_failures} 次返回无法解析的内容，停止循环。"
                    f"最后一次错误: {exc}"
                ) from exc
            return  # 保留上一轮的 intent 和备忘录，本次调用作废

        self._current_intent = parsed.intent
        self._llm_called_at_least_once = True
        self._consecutive_llm_failures = 0

        try:
            strategy_memo.write_memo(
                self._memo_path,
                strategy_memo.StrategyMemo(turn=turn, body=parsed.memo_body),
                max_body_chars=self._config.max_memo_body_chars,
            )
        except strategy_memo.StrategyMemoTooLongError as exc:
            self._log.record(
                intent="strategy.memo_write_rejected", params={"turn": turn}, result="failure", detail=str(exc)
            )
        else:
            self._log.record(
                intent="strategy.memo_updated", params={"turn": turn}, result="success",
                detail=f"body_chars={len(parsed.memo_body)}",
            )

        self._log.record(
            intent="strategy.intent_updated",
            params={"turn": turn, "default_focus": parsed.intent.default_focus.value},
            result="success",
            detail=parsed.intent.rationale,
        )

    def _read_memo_with_recovery(self, turn: int) -> strategy_memo.StrategyMemo:
        try:
            return strategy_memo.read_memo(self._memo_path)
        except strategy_memo.StrategyMemoCorruptedError as exc:
            self._log.record(
                intent="strategy.memo_corrupted", params={"turn": turn}, result="failure", detail=str(exc)
            )
            try:
                return strategy_memo.restore_backup(self._memo_path)
            except strategy_memo.StrategyMemoError as recovery_exc:
                raise StrategyLoopError(
                    f"战略备忘录损坏且没有可用备份，无法自动恢复，需要人工介入: {recovery_exc}"
                ) from recovery_exc
