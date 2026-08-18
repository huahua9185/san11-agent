from __future__ import annotations

import sys

import pytest

from san11agent.input_backend import VK_ESCAPE, FakeInputBackend, InputBackend


def test_fake_input_backend_click_records_move_and_button_events():
    backend = FakeInputBackend()
    backend.click(100, 200)

    methods = [c.method for c in backend.calls]
    assert methods == ["move_mouse", "mouse_down", "mouse_up", "click"]
    assert backend.calls[0].args == (100, 200)
    assert backend.calls[1].args == ("left",)
    assert backend.calls[3].args == (100, 200, "left")


def test_fake_input_backend_click_rejects_unknown_button():
    backend = FakeInputBackend()
    with pytest.raises(ValueError):
        backend.click(0, 0, button="middle")


def test_fake_input_backend_click_invokes_on_click_callback():
    seen = []
    backend = FakeInputBackend(on_click=lambda x, y, button: seen.append((x, y, button)))
    backend.click(5, 6)
    assert seen == [(5, 6, "left")]


def test_fake_input_backend_key_press_records_down_up_and_invokes_callback():
    seen = []
    backend = FakeInputBackend(on_key_press=lambda vk: seen.append(vk))
    backend.key_press(VK_ESCAPE)

    methods = [c.method for c in backend.calls]
    assert methods == ["key_down", "key_up", "key_press"]
    assert seen == [VK_ESCAPE]


def test_fake_input_backend_is_an_input_backend():
    assert isinstance(FakeInputBackend(), InputBackend)


@pytest.mark.skipif(sys.platform != "win32", reason="SendInputBackend 仅支持 Windows")
def test_to_absolute_normalizes_into_0_65535_range():
    from san11agent.input_backend import _to_absolute

    assert _to_absolute(0, 0, 1920, 1080) == (0, 0)
    assert _to_absolute(1919, 1079, 1920, 1080) == (65535, 65535)
    # 屏幕正中间大致对应归一化坐标的正中间
    mid_x, mid_y = _to_absolute(960, 540, 1920, 1080)
    assert abs(mid_x - 32768) < 100
    assert abs(mid_y - 32768) < 100


@pytest.mark.skipif(sys.platform != "win32", reason="SendInputBackend 仅支持 Windows")
def test_to_absolute_rejects_non_positive_screen_size():
    from san11agent.input_backend import _to_absolute

    with pytest.raises(ValueError):
        _to_absolute(0, 0, 0, 1080)


@pytest.mark.skipif(sys.platform != "win32", reason="SendInputBackend 仅支持 Windows")
def test_send_input_backend_is_constructible_without_sending_anything():
    # 构造函数本身不应该发送任何真实输入——这里只验证类型关系，不调用任何
    # 会真的移动鼠标/发送按键的方法（那些没有离线测试覆盖，见提交报告）。
    from san11agent.input_backend import SendInputBackend

    backend = SendInputBackend()
    assert isinstance(backend, InputBackend)
