from __future__ import annotations

import sys

import pytest

from san11agent.window import FakeGameWindow, WindowError, ensure_dpi_awareness


def test_fake_game_window_default_origin_is_identity():
    window = FakeGameWindow()
    assert window.client_to_screen(10, 20) == (10, 20)


def test_fake_game_window_applies_origin_offset():
    window = FakeGameWindow(origin=(100, 50))
    assert window.client_to_screen(10, 20) == (110, 70)


def test_ensure_dpi_awareness_does_not_raise():
    # 不管平台，也不管这台机器上到底成不成功，这个函数按设计不应该抛异常
    # （失败只打印警告，见 window.py 的说明）——调用两次也应该是安全的。
    ensure_dpi_awareness()
    ensure_dpi_awareness()


@pytest.mark.skipif(sys.platform != "win32", reason="Win32GameWindow 仅支持 Windows")
def test_win32_game_window_attach_by_pid_raises_for_nonexistent_pid():
    from san11agent.window import Win32GameWindow

    with pytest.raises(WindowError):
        Win32GameWindow.attach_by_pid(999_999_999)
