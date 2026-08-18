"""M5：StrategyLLM 抽象/假后端/提示词组织/输出解析的单元测试。全部离线——
FakeStrategyLLM 从不联网，不调用任何真实模型。
"""
from __future__ import annotations

import json

import pytest

from san11agent.intent import CityDirective, DomesticFocus
from san11agent.strategy_llm import (
    FakeStrategyLLM,
    StrategyParseError,
    build_strategy_prompt,
    format_strategy_response,
    parse_llm_response,
)


def _prompt():
    return build_strategy_prompt(turn=5, situation_text="局势文本", memo_text="备忘录文本")


# ---------------------------------------------------------------------------
# StrategyPrompt / build_strategy_prompt
# ---------------------------------------------------------------------------


def test_prompt_render_includes_all_three_sections():
    prompt = _prompt()
    text = prompt.render()
    assert "局势文本" in text
    assert "备忘录文本" in text
    assert "回合 5" in text
    assert "JSON" in prompt.instructions


def test_prompt_instructions_lists_valid_focus_values():
    prompt = _prompt()
    for value in ("economy", "agriculture", "military", "security", "balanced"):
        assert value in prompt.instructions


def test_prompt_instructions_mentions_char_budget():
    prompt = build_strategy_prompt(turn=1, situation_text="", memo_text="", max_memo_chars=1234)
    assert "1234" in prompt.instructions


# ---------------------------------------------------------------------------
# FakeStrategyLLM
# ---------------------------------------------------------------------------


def test_fake_strategy_llm_returns_scripted_responses_in_order():
    llm = FakeStrategyLLM(["response1", "response2"])
    assert llm.decide(_prompt()) == "response1"
    assert llm.decide(_prompt()) == "response2"


def test_fake_strategy_llm_records_call_history():
    llm = FakeStrategyLLM(["r1"])
    prompt = _prompt()
    llm.decide(prompt)
    assert len(llm.calls) == 1
    assert llm.calls[0].prompt is prompt
    assert llm.calls[0].raw_response == "r1"


def test_fake_strategy_llm_raises_when_scripted_responses_exhausted():
    llm = FakeStrategyLLM(["only_one"])
    llm.decide(_prompt())
    with pytest.raises(IndexError):
        llm.decide(_prompt())


def test_fake_strategy_llm_accepts_callable_driver():
    def driver(prompt):
        return f"turn={prompt.turn}"

    llm = FakeStrategyLLM(driver)
    assert llm.decide(build_strategy_prompt(turn=7, situation_text="", memo_text="")) == "turn=7"


# ---------------------------------------------------------------------------
# format_strategy_response + parse_llm_response 往返
# ---------------------------------------------------------------------------


def test_format_then_parse_round_trips():
    raw = format_strategy_response(
        "更新后的备忘录正文",
        default_focus=DomesticFocus.MILITARY,
        city_directives=[CityDirective(city_index=1, focus=DomesticFocus.SECURITY, garrison_general_index=9)],
        target_faction_index=2,
        expansion_notes="向东扩张",
        rationale="因为东边势力弱",
    )
    parsed = parse_llm_response(raw, turn=5)

    assert parsed.memo_body == "更新后的备忘录正文"
    assert parsed.intent.turn == 5
    assert parsed.intent.default_focus == DomesticFocus.MILITARY
    assert parsed.intent.city_directives == (
        CityDirective(city_index=1, focus=DomesticFocus.SECURITY, garrison_general_index=9),
    )
    assert parsed.intent.target_faction_index == 2
    assert parsed.intent.expansion_notes == "向东扩张"
    assert parsed.intent.rationale == "因为东边势力弱"


def test_parse_llm_response_allows_omitting_optional_fields():
    raw = json.dumps({"memo": "正文", "intent": {}})
    parsed = parse_llm_response(raw, turn=1)
    assert parsed.intent.default_focus == DomesticFocus.BALANCED
    assert parsed.intent.city_directives == ()
    assert parsed.intent.target_faction_index is None


# ---------------------------------------------------------------------------
# parse_llm_response 的容错：非法/无法解析内容一律 fail closed
# ---------------------------------------------------------------------------


def test_parse_rejects_non_json():
    with pytest.raises(StrategyParseError):
        parse_llm_response("这不是 JSON，是 LLM 的闲聊", turn=1)


def test_parse_rejects_json_that_is_not_an_object():
    with pytest.raises(StrategyParseError):
        parse_llm_response("[1, 2, 3]", turn=1)


def test_parse_rejects_missing_memo_field():
    raw = json.dumps({"intent": {"default_focus": "balanced"}})
    with pytest.raises(StrategyParseError):
        parse_llm_response(raw, turn=1)


def test_parse_rejects_non_string_memo_field():
    raw = json.dumps({"memo": 123, "intent": {}})
    with pytest.raises(StrategyParseError):
        parse_llm_response(raw, turn=1)


def test_parse_rejects_missing_intent_field():
    raw = json.dumps({"memo": "正文"})
    with pytest.raises(StrategyParseError):
        parse_llm_response(raw, turn=1)


def test_parse_rejects_invalid_default_focus_value():
    raw = json.dumps({"memo": "正文", "intent": {"default_focus": "conquer_the_world"}})
    with pytest.raises(StrategyParseError):
        parse_llm_response(raw, turn=1)


def test_parse_rejects_city_directive_missing_city_index():
    raw = json.dumps({"memo": "正文", "intent": {"city_directives": [{"focus": "economy"}]}})
    with pytest.raises(StrategyParseError):
        parse_llm_response(raw, turn=1)


def test_parse_rejects_city_directive_with_invalid_focus():
    raw = json.dumps(
        {"memo": "正文", "intent": {"city_directives": [{"city_index": 0, "focus": "not_a_real_focus"}]}}
    )
    with pytest.raises(StrategyParseError):
        parse_llm_response(raw, turn=1)


def test_parse_rejects_non_integer_city_index():
    raw = json.dumps(
        {"memo": "正文", "intent": {"city_directives": [{"city_index": "zero", "focus": "economy"}]}}
    )
    with pytest.raises(StrategyParseError):
        parse_llm_response(raw, turn=1)


def test_parse_rejects_non_integer_target_faction_index():
    raw = json.dumps({"memo": "正文", "intent": {"target_faction_index": "one"}})
    with pytest.raises(StrategyParseError):
        parse_llm_response(raw, turn=1)


def test_parse_error_message_is_specific_about_the_bad_field():
    raw = json.dumps({"memo": "正文", "intent": {"default_focus": "bogus"}})
    with pytest.raises(StrategyParseError, match="default_focus"):
        parse_llm_response(raw, turn=1)
