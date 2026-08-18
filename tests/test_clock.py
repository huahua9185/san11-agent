from __future__ import annotations

import pytest

from san11agent.clock import FakeClock


def test_fake_clock_starts_at_given_time():
    clock = FakeClock(start=5.0)
    assert clock.now() == 5.0


def test_fake_clock_sleep_advances_virtual_time_only():
    clock = FakeClock()
    clock.sleep(1.5)
    assert clock.now() == 1.5
    clock.sleep(0.5)
    assert clock.now() == 2.0


def test_fake_clock_advance_is_alias_for_sleep():
    clock = FakeClock()
    clock.advance(3.0)
    assert clock.now() == 3.0


def test_fake_clock_rejects_negative_start():
    with pytest.raises(ValueError):
        FakeClock(start=-1.0)


def test_fake_clock_rejects_negative_sleep():
    clock = FakeClock()
    with pytest.raises(ValueError):
        clock.sleep(-1.0)
