"""按键/鼠标输入后端抽象。

两套实现：
- SendInputBackend：Win32 SendInput（仅 Windows），真正把输入注入系统。
- FakeInputBackend：只记录调用，不发送任何真实输入，供离线单元测试使用，
  也可以在 CLI 里用作"演练模式"防止误操作真实鼠标键盘（见 cli.py 的
  select-city 子命令，默认就是这个，要加 --live 才会换成 SendInputBackend）。

已知限制（已在提交报告"设计取舍"一节列出）：SendInput 注入的是标准 Win32
输入消息。如果 San11WPK.exe 是用 DirectInput 或原始输入(Raw Input)直接轮询
硬件状态、而不是从系统消息队列取输入，SendInput 可能不会被游戏感知到——
这一点在游戏能实际运行之前无法验证。如果验证后发现确实不行，备选方案是
pydirectinput 或虚拟 HID 驱动，需要你确认后再切换实现，不在这次改动范围内。
"""
from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# 常用虚拟键码 (Virtual-Key Codes)，只列出目前用得到的几个。
VK_ESCAPE = 0x1B
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28

_VALID_BUTTONS = frozenset({"left", "right"})


class InputBackend(ABC):
    """键鼠输入的抽象接口。

    坐标一律是屏幕绝对坐标（调用方已经用 GameWindow.client_to_screen 转换过），
    这一层不关心客户区/DPI。
    """

    @abstractmethod
    def move_mouse(self, x: int, y: int) -> None: ...

    @abstractmethod
    def mouse_down(self, button: str = "left") -> None: ...

    @abstractmethod
    def mouse_up(self, button: str = "left") -> None: ...

    @abstractmethod
    def key_down(self, vk: int) -> None: ...

    @abstractmethod
    def key_up(self, vk: int) -> None: ...

    def click(self, x: int, y: int, button: str = "left") -> None:
        if button not in _VALID_BUTTONS:
            raise ValueError(f"未知按钮 {button!r}，必须是 {sorted(_VALID_BUTTONS)} 之一")
        self.move_mouse(x, y)
        self.mouse_down(button)
        self.mouse_up(button)

    def key_press(self, vk: int) -> None:
        self.key_down(vk)
        self.key_up(vk)


@dataclass(frozen=True)
class RecordedCall:
    method: str
    args: tuple
    kwargs: dict = field(default_factory=dict)


class FakeInputBackend(InputBackend):
    """记录所有调用但不发送任何真实输入。

    on_click / on_key_press 是可选回调，供测试模拟"游戏对这次输入做出反应"——
    比如在回调里往 MutableMemoryReader 写入新的选中城池 ID，模拟游戏收到点击
    后更新了内存状态，这样上层的轮询逻辑就有真实变化可以观察，而不需要真的
    等待或猜测时序。
    """

    def __init__(self, *, on_click=None, on_key_press=None, on_move_mouse=None):
        self.calls: list[RecordedCall] = []
        self._on_click = on_click
        self._on_key_press = on_key_press
        self._on_move_mouse = on_move_mouse

    def move_mouse(self, x: int, y: int) -> None:
        self.calls.append(RecordedCall("move_mouse", (x, y)))
        if self._on_move_mouse:
            self._on_move_mouse(x, y)

    def mouse_down(self, button: str = "left") -> None:
        self.calls.append(RecordedCall("mouse_down", (button,)))

    def mouse_up(self, button: str = "left") -> None:
        self.calls.append(RecordedCall("mouse_up", (button,)))

    def key_down(self, vk: int) -> None:
        self.calls.append(RecordedCall("key_down", (vk,)))

    def key_up(self, vk: int) -> None:
        self.calls.append(RecordedCall("key_up", (vk,)))

    def click(self, x: int, y: int, button: str = "left") -> None:
        super().click(x, y, button)
        self.calls.append(RecordedCall("click", (x, y, button)))
        if self._on_click:
            self._on_click(x, y, button)

    def key_press(self, vk: int) -> None:
        super().key_press(vk)
        self.calls.append(RecordedCall("key_press", (vk,)))
        if self._on_key_press:
            self._on_key_press(vk)


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)

    _INPUT_MOUSE = 0
    _INPUT_KEYBOARD = 1

    _MOUSEEVENTF_MOVE = 0x0001
    _MOUSEEVENTF_ABSOLUTE = 0x8000
    _MOUSEEVENTF_LEFTDOWN = 0x0002
    _MOUSEEVENTF_LEFTUP = 0x0004
    _MOUSEEVENTF_RIGHTDOWN = 0x0008
    _MOUSEEVENTF_RIGHTUP = 0x0010

    _KEYEVENTF_KEYUP = 0x0002

    _SM_CXSCREEN = 0
    _SM_CYSCREEN = 1

    _ULONG_PTR = ctypes.c_size_t

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", _ULONG_PTR),
        ]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", _ULONG_PTR),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("union", _INPUT_UNION)]

    def _to_absolute(x: int, y: int, screen_w: int, screen_h: int) -> tuple[int, int]:
        """SendInput 的绝对坐标模式要求把屏幕像素坐标归一化到 [0, 65535] 区间。

        单独抽成不依赖 GetSystemMetrics 的纯函数，方便离线单元测试这段换算
        数学本身，不需要真的调用任何 Win32 API。
        """
        if screen_w <= 0 or screen_h <= 0:
            raise ValueError("screen_w/screen_h 必须 > 0")
        dx = round(x * 65535 / (screen_w - 1)) if screen_w > 1 else 0
        dy = round(y * 65535 / (screen_h - 1)) if screen_h > 1 else 0
        return dx, dy

    def _send(inp: _INPUT) -> None:
        n = _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
        if n != 1:
            raise OSError(f"SendInput 失败，error={ctypes.get_last_error()}")

    _MOUSE_BUTTON_FLAGS = {
        ("left", "down"): _MOUSEEVENTF_LEFTDOWN,
        ("left", "up"): _MOUSEEVENTF_LEFTUP,
        ("right", "down"): _MOUSEEVENTF_RIGHTDOWN,
        ("right", "up"): _MOUSEEVENTF_RIGHTUP,
    }

    class SendInputBackend(InputBackend):
        """真正把输入注入系统。构造本身不做任何操作，每次调用方法才发送一次
        SendInput——没有在自动化测试里实际调用过（会真的移动这台机器的鼠标/
        发送按键），见提交报告"哪些部分只能靠设计保证"一节。
        """

        def move_mouse(self, x: int, y: int) -> None:
            screen_w = _user32.GetSystemMetrics(_SM_CXSCREEN)
            screen_h = _user32.GetSystemMetrics(_SM_CYSCREEN)
            dx, dy = _to_absolute(x, y, screen_w, screen_h)
            mi = _MOUSEINPUT(dx, dy, 0, _MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE, 0, 0)
            _send(_INPUT(_INPUT_MOUSE, _INPUT_UNION(mi=mi)))

        def _mouse_button(self, button: str, phase: str) -> None:
            key = (button, phase)
            if key not in _MOUSE_BUTTON_FLAGS:
                raise ValueError(f"不支持的按钮/阶段组合: {key}")
            mi = _MOUSEINPUT(0, 0, 0, _MOUSE_BUTTON_FLAGS[key], 0, 0)
            _send(_INPUT(_INPUT_MOUSE, _INPUT_UNION(mi=mi)))

        def mouse_down(self, button: str = "left") -> None:
            self._mouse_button(button, "down")

        def mouse_up(self, button: str = "left") -> None:
            self._mouse_button(button, "up")

        def key_down(self, vk: int) -> None:
            ki = _KEYBDINPUT(vk, 0, 0, 0, 0)
            _send(_INPUT(_INPUT_KEYBOARD, _INPUT_UNION(ki=ki)))

        def key_up(self, vk: int) -> None:
            ki = _KEYBDINPUT(vk, 0, _KEYEVENTF_KEYUP, 0, 0)
            _send(_INPUT(_INPUT_KEYBOARD, _INPUT_UNION(ki=ki)))

else:  # pragma: no cover - 非 Windows 平台上这些符号仅用于类型引用/测试跳过

    def _to_absolute(x: int, y: int, screen_w: int, screen_h: int) -> tuple[int, int]:
        raise NotImplementedError("SendInputBackend 仅支持 Windows")

    class SendInputBackend(InputBackend):  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise NotImplementedError("SendInputBackend 仅支持 Windows")
