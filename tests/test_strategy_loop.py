"""M5：主循环端到端测试——完全离线，假 LLM + 假状态源 + 假执行后端，验证
"读状态 -> (每N回合)调LLM -> 战术层出动作 -> 执行 -> 推进回合"这条链路能连续
空跑若干回合，以及 LLM 输出非法/无法解析/超长时的处理策略。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from san11agent.action_log import ActionLog
from san11agent.clock import FakeClock
from san11agent.domestic_rules import DomesticRulesConfig
from san11agent.domestic_rules import load_domestic_rules
from san11agent.intent import DEFAULT_INTENT, DomesticFocus
from san11agent.legal_actions import LevyGoldAction
from san11agent.strategy_llm import FakeStrategyLLM, format_strategy_response
from san11agent.strategy_loop import (
    FakeActionExecutor,
    FakeGameStateSource,
    StrategyLoop,
    StrategyLoopConfig,
    StrategyLoopError,
)
from san11agent import strategy_memo
from san11agent.visible_state import (
    VisibleCityDetail,
    VisibleCitySummary,
    VisibleFactionPublic,
    VisibleGameState,
    VisibleGeneralFull,
    VisibleGlobalState,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_RULES = REPO_ROOT / "tests" / "fixtures" / "domestic_rules_test.json"

PLAYER_FACTION_ID = 0
ENEMY_FACTION_ID = 1
OWN_CITY = 0
ENEMY_CITY = 1
GENERAL_A = 0


def _rules() -> DomesticRulesConfig:
    return load_domestic_rules(TEST_RULES)


def _initial_state(xun: int = 1) -> VisibleGameState:
    global_state = VisibleGlobalState(
        scenario_id=1, start_year=190, start_month=1, start_day=1,
        emperor_general_id=0, difficulty=1, death_setting=0, current_xun=xun,
        current_year=190, current_month=1, current_day=1, phase=1,
    )
    city = VisibleCityDetail(
        index=OWN_CITY, name="city0", province=0, adjacent_cities=[],
        faction_id=PLAYER_FACTION_ID, map_x=0, map_y=0,
        governor_general_id=0, force_id=0, troop_capacity=100, troops=50,
        gold=500, food=8000, trade_price=10, has_merchant=1, morale=80,
        security=80, policy=0, target=0,
        development_land_count=5, developed_land_count=3,
        domestic_land_x=10, domestic_land_y=20,
    )
    enemy_city = VisibleCitySummary(
        index=ENEMY_CITY, name="敌城", province=1, adjacent_cities=[],
        faction_id=ENEMY_FACTION_ID, map_x=1, map_y=1,
    )
    general = VisibleGeneralFull(
        index=GENERAL_A, name="g0", portrait_id=0, gender=0, debut_year=0,
        birth_year=0, death_year=-1, faction_id=PLAYER_FACTION_ID, identity=0, office=0,
        location=OWN_CITY, special_skill_id=-1,
        display_stats_wound=b"\x00" * 5, display_stats_normal=b"\x00" * 5,
        loyalty=80, merit=0, stamina=50, garrison_count=0, health=1, force_id=PLAYER_FACTION_ID,
    )
    factions = [
        VisibleFactionPublic(index=PLAYER_FACTION_ID, ruler_general_id=0, advisor_general_id=-1, player_marker=1),
        VisibleFactionPublic(index=ENEMY_FACTION_ID, ruler_general_id=1, advisor_general_id=-1, player_marker=0),
    ]
    return VisibleGameState(
        global_state=global_state, generals=[general], cities=[city, enemy_city], troops=[], factions=factions
    )


def _make_loop(
    *,
    memo_path: Path,
    llm,
    config: StrategyLoopConfig = StrategyLoopConfig(),
    state=None,
    executor=None,
) -> tuple[StrategyLoop, FakeActionExecutor, ActionLog]:
    action_log = ActionLog(FakeClock())
    executor = executor or FakeActionExecutor()
    loop = StrategyLoop(
        state_source=FakeGameStateSource(state or _initial_state()),
        player_faction_id=PLAYER_FACTION_ID,
        rules=_rules(),
        strategy_llm=llm,
        action_executor=executor,
        memo_path=memo_path,
        action_log=action_log,
        config=config,
    )
    return loop, executor, action_log


def _valid_response(turn: int, *, focus: DomesticFocus = DomesticFocus.ECONOMY) -> str:
    return format_strategy_response(f"turn {turn} 备忘录正文", default_focus=focus, rationale=f"turn{turn}理由")


# ---------------------------------------------------------------------------
# 主链路：连续空跑若干回合
# ---------------------------------------------------------------------------


def test_loop_runs_several_turns_offline_and_advances_turn_counter(tmp_path):
    llm = FakeStrategyLLM(lambda prompt: _valid_response(prompt.turn))
    loop, executor, log = _make_loop(memo_path=tmp_path / "memo.md", llm=llm, config=StrategyLoopConfig(llm_call_interval=3))

    results = loop.run_turns(6)

    assert [r.turn for r in results] == [1, 2, 3, 4, 5, 6]
    # 第一次调用强制触发（此前从未成功调用过），此后按 turn % 3 == 0 触发。
    assert [r.llm_called for r in results] == [True, False, True, False, False, True]
    assert len(llm.calls) == 3


def test_loop_executes_tactical_decisions_every_turn(tmp_path):
    llm = FakeStrategyLLM(lambda prompt: _valid_response(prompt.turn))
    loop, executor, log = _make_loop(memo_path=tmp_path / "memo.md", llm=llm)

    results = loop.run_turns(4)

    for result in results:
        assert len(result.decisions) == 1
        assert result.decisions[0].general_index == GENERAL_A
    assert len(executor.calls) == 4
    assert all(isinstance(a, LevyGoldAction) for a in executor.calls)  # ECONOMY 重心 -> LevyGoldAction


def test_loop_persists_memo_to_disk_after_successful_llm_call(tmp_path):
    memo_path = tmp_path / "memo.md"
    llm = FakeStrategyLLM(lambda prompt: _valid_response(prompt.turn))
    loop, _, _ = _make_loop(memo_path=memo_path, llm=llm, config=StrategyLoopConfig(llm_call_interval=1))

    loop.run_turns(2)

    memo = strategy_memo.read_memo(memo_path)
    assert "turn 2" in memo.body
    assert memo.turn == 2


def test_loop_action_log_records_tactical_and_strategy_entries(tmp_path):
    llm = FakeStrategyLLM(lambda prompt: _valid_response(prompt.turn))
    loop, _, log = _make_loop(memo_path=tmp_path / "memo.md", llm=llm, config=StrategyLoopConfig(llm_call_interval=1))

    loop.run_turns(1)

    intents = {e.intent for e in log.entries}
    assert "strategy.memo_updated" in intents
    assert "strategy.intent_updated" in intents
    assert any(i.startswith("tactical.") for i in intents)


# ---------------------------------------------------------------------------
# LLM 返回非法/无法解析内容
# ---------------------------------------------------------------------------


def test_invalid_llm_response_keeps_previous_intent_and_does_not_crash(tmp_path):
    llm = FakeStrategyLLM(["这不是合法的 JSON 输出"])
    loop, executor, log = _make_loop(
        memo_path=tmp_path / "memo.md", llm=llm, config=StrategyLoopConfig(llm_call_interval=1)
    )

    result = loop.run_one_turn()

    assert loop.current_intent is DEFAULT_INTENT
    assert result.llm_called is True
    failure_entries = [e for e in log.entries if e.intent == "strategy.llm_response_invalid"]
    assert len(failure_entries) == 1
    # 依然产出了动作（用的是默认意图），循环没有因为 LLM 输出非法就整体停摆。
    assert result.decisions


def test_consecutive_invalid_responses_stop_loop_after_threshold(tmp_path):
    llm = FakeStrategyLLM(lambda prompt: "始终非法")
    loop, _, log = _make_loop(
        memo_path=tmp_path / "memo.md", llm=llm,
        config=StrategyLoopConfig(llm_call_interval=1, max_consecutive_llm_failures=2),
    )

    with pytest.raises(StrategyLoopError):
        loop.run_turns(5)

    failure_entries = [e for e in log.entries if e.intent == "strategy.llm_response_invalid"]
    assert len(failure_entries) == 2  # 第2次失败触发停止，不会有第3次尝试


def test_valid_response_after_failures_resets_failure_counter(tmp_path):
    responses = iter(["非法1", "非法2", None])  # 第3次单独处理成合法响应

    def driver(prompt):
        raw = next(responses)
        return raw if raw is not None else _valid_response(prompt.turn)

    llm = FakeStrategyLLM(driver)
    loop, _, log = _make_loop(
        memo_path=tmp_path / "memo.md", llm=llm,
        config=StrategyLoopConfig(llm_call_interval=1, max_consecutive_llm_failures=3),
    )

    loop.run_turns(3)  # 两次失败 + 一次成功，没有达到失败阈值，不应该抛错

    assert loop.current_intent.default_focus == DomesticFocus.ECONOMY
    failure_entries = [e for e in log.entries if e.intent == "strategy.llm_response_invalid"]
    assert len(failure_entries) == 2


# ---------------------------------------------------------------------------
# 备忘录正文超长
# ---------------------------------------------------------------------------


def test_memo_too_long_rejected_but_intent_still_applied(tmp_path):
    memo_path = tmp_path / "memo.md"
    llm = FakeStrategyLLM(lambda prompt: _valid_response(prompt.turn, focus=DomesticFocus.MILITARY))
    loop, _, log = _make_loop(
        memo_path=memo_path, llm=llm,
        config=StrategyLoopConfig(llm_call_interval=1, max_memo_body_chars=5),
    )

    loop.run_one_turn()

    assert loop.current_intent.default_focus == DomesticFocus.MILITARY  # intent 仍然采用
    assert not memo_path.exists()  # 备忘录写入被拒绝，文件从未被创建
    failure_entries = [e for e in log.entries if e.intent == "strategy.memo_write_rejected"]
    assert len(failure_entries) == 1


# ---------------------------------------------------------------------------
# 备忘录文件损坏
# ---------------------------------------------------------------------------


def test_corrupted_memo_recovers_from_backup(tmp_path):
    memo_path = tmp_path / "memo.md"
    strategy_memo.write_memo(memo_path, strategy_memo.StrategyMemo(turn=1, body="第一版"))
    strategy_memo.write_memo(memo_path, strategy_memo.StrategyMemo(turn=2, body="第二版"))
    tampered = memo_path.read_text(encoding="utf-8").replace("第二版", "损坏内容")
    memo_path.write_text(tampered, encoding="utf-8")

    llm = FakeStrategyLLM(lambda prompt: _valid_response(prompt.turn))
    loop, _, log = _make_loop(memo_path=memo_path, llm=llm, config=StrategyLoopConfig(llm_call_interval=1))

    loop.run_one_turn()  # 不应该抛出，应该自动回退到 .bak 再继续

    corrupted_entries = [e for e in log.entries if e.intent == "strategy.memo_corrupted"]
    assert len(corrupted_entries) == 1


def test_corrupted_memo_without_backup_raises(tmp_path):
    memo_path = tmp_path / "memo.md"
    strategy_memo.write_memo(memo_path, strategy_memo.StrategyMemo(turn=1, body="唯一版本"))
    tampered = memo_path.read_text(encoding="utf-8").replace("唯一版本", "损坏内容")
    memo_path.write_text(tampered, encoding="utf-8")
    # 只写过一次，从未触发过备份（见 strategy_memo.write_memo 首次写入不生成
    # .bak 的说明），所以这里天然没有备份可用，不需要再手动删除。

    llm = FakeStrategyLLM(lambda prompt: _valid_response(prompt.turn))
    loop, _, _ = _make_loop(memo_path=memo_path, llm=llm, config=StrategyLoopConfig(llm_call_interval=1))

    with pytest.raises(StrategyLoopError):
        loop.run_one_turn()
