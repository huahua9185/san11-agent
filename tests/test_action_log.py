from __future__ import annotations

import json

from san11agent.action_log import ActionLog, diff_state
from san11agent.clock import FakeClock


def test_diff_state_only_keeps_changed_keys():
    before = {"a": 1, "b": 2, "c": 3}
    after = {"a": 1, "b": 20, "d": 4}
    diff = diff_state(before, after)
    assert diff == {"b": (2, 20), "c": (3, None), "d": (None, 4)}


def test_diff_state_handles_none_inputs():
    assert diff_state(None, {"a": 1}) == {"a": (None, 1)}
    assert diff_state({"a": 1}, None) == {"a": (1, None)}
    assert diff_state(None, None) == {}


def test_action_log_record_uses_injected_clock_and_diffs_state():
    clock = FakeClock()
    log = ActionLog(clock)

    clock.advance(1.0)
    entry = log.record(
        "select_city",
        {"city_index": 3},
        "success",
        state_before={"selected_city_index": -1},
        state_after={"selected_city_index": 3},
    )

    assert entry.timestamp == 1.0
    assert entry.intent == "select_city"
    assert entry.params == {"city_index": 3}
    assert entry.result == "success"
    assert entry.state_diff == {"selected_city_index": (-1, 3)}
    assert log.entries == [entry]


def test_action_log_params_is_copied_not_aliased():
    clock = FakeClock()
    log = ActionLog(clock)
    params = {"x": 1}
    entry = log.record("noop", params, "success")
    params["x"] = 999
    assert entry.params == {"x": 1}


def test_action_log_to_jsonl_round_trips_each_entry():
    clock = FakeClock()
    log = ActionLog(clock)
    log.record("a", {"n": 1}, "success", state_before={"x": 1}, state_after={"x": 2})
    log.record("b", {"n": 2}, "timeout", detail="轮询超时")

    lines = log.to_jsonl().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["intent"] == "a"
    assert first["state_diff"] == {"x": [1, 2]}
    second = json.loads(lines[1])
    assert second["intent"] == "b"
    assert second["detail"] == "轮询超时"
