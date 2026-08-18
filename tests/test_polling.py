from __future__ import annotations

import pytest

from san11agent.clock import FakeClock
from san11agent.polling import PollTimeoutError, poll_until


def test_poll_until_returns_immediately_when_condition_already_true():
    clock = FakeClock()
    attempts = poll_until(lambda: True, timeout=5.0, interval=0.1, clock=clock)
    assert attempts == 1
    assert clock.now() == 0.0  # 没有真的睡眠


def test_poll_until_retries_until_condition_becomes_true_without_real_sleep():
    clock = FakeClock()
    calls = {"n": 0}

    def condition():
        calls["n"] += 1
        return calls["n"] >= 3

    attempts = poll_until(condition, timeout=5.0, interval=0.5, clock=clock)
    assert attempts == 3
    assert clock.now() == 1.0  # 两次 interval=0.5 的 sleep


def test_poll_until_raises_on_timeout():
    clock = FakeClock()
    with pytest.raises(PollTimeoutError) as excinfo:
        poll_until(lambda: False, timeout=1.0, interval=0.3, clock=clock, description="等待 X")
    assert "等待 X" in str(excinfo.value)
    assert clock.now() >= 1.0


def test_poll_until_rejects_bad_arguments():
    clock = FakeClock()
    with pytest.raises(ValueError):
        poll_until(lambda: True, timeout=-1.0, interval=0.1, clock=clock)
    with pytest.raises(ValueError):
        poll_until(lambda: True, timeout=1.0, interval=0.0, clock=clock)
