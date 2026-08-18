"""游戏窗口抽象：客户区坐标 -> 屏幕坐标（ClientToScreen），以及启动时的 DPI 感知设置。

跟 memory.py 的 ProcessMemoryReader/DumpMemoryReader 是同一个思路，分两套实现：
- Win32GameWindow：真实游戏窗口，通过 Win32 ClientToScreen 换算坐标（仅 Windows）。
- FakeGameWindow：离线测试用，假设客户区左上角对应屏幕上某个固定偏移，
  不做任何真实调用，只把上层（map_projection/execution）的坐标换算逻辑本身
  变得可测。
"""
from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass


class WindowError(Exception):
    """找不到游戏窗口，或 Win32 窗口调用失败。"""


class GameWindow(ABC):
    @abstractmethod
    def client_to_screen(self, x: int, y: int) -> tuple[int, int]:
        """把游戏客户区坐标转换成屏幕绝对坐标。"""


@dataclass(frozen=True)
class FakeGameWindow(GameWindow):
    """离线测试用：客户区左上角在屏幕上的位置固定为 origin，线性平移即可。

    不模拟窗口边框/标题栏/多显示器 DPI 缩放这些真实场景的复杂性——那些正是
    交给真实 Win32 ClientToScreen 处理的部分；Fake 版本只需要让依赖
    client_to_screen() 的上层逻辑本身可以离线测试。
    """

    origin: tuple[int, int] = (0, 0)

    def client_to_screen(self, x: int, y: int) -> tuple[int, int]:
        return (self.origin[0] + x, self.origin[1] + y)


def ensure_dpi_awareness() -> None:
    """程序启动时应调用一次（且只需一次）。

    设置 Per-Monitor DPI 感知，避免系统缩放（比如 125%/150% 显示缩放）导致
    ClientToScreen 换算出来的坐标和真实物理像素坐标对不上。优先用 Windows 8.1+
    的 SetProcessDpiAwareness(shcore.dll)，不可用时退化到 Windows Vista+ 的
    SetProcessDPIAware(user32.dll)。非 Windows 平台上是 no-op。

    两种方式都失败时不视为致命错误，只打印警告：DPI 没设对最坏后果是坐标
    整体偏移一个固定比例，这会在后续"点击后轮询确认"这一步被观察到并触发
    归位重试，不是静默的数据损坏，所以不需要在这里让程序直接退出。
    """
    if sys.platform != "win32":
        return
    import ctypes

    try:
        PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError) as exc:
        print(f"[警告] 设置 DPI 感知失败，坐标计算可能因系统缩放而偏移: {exc}", file=sys.stderr)


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)

    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    def _find_main_window_for_pid(pid: int) -> int:
        """枚举顶层窗口，找到属于该 pid、可见、有标题的第一个窗口。

        游戏主窗口具体该按什么条件查找（标题/类名/可见性）目前没有针对
        San11WPK.exe 实机验证过，这里用"可见 + 标题非空"这个通用启发式作为
        默认实现。如果实测发现游戏主窗口不满足这个条件（比如无边框全屏、
        标题为空），需要调整，见提交报告"设计取舍"一节。
        """
        result: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _callback(hwnd, _lparam):
            window_pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if window_pid.value != pid:
                return True
            if not _user32.IsWindowVisible(hwnd):
                return True
            if _user32.GetWindowTextLengthW(hwnd) == 0:
                return True
            result.append(hwnd)
            return False  # 找到一个就停止枚举

        _user32.EnumWindows(_callback, 0)
        if not result:
            raise WindowError(f"没有找到属于 pid={pid} 的可见窗口，游戏是否已完全启动？")
        return result[0]

    class Win32GameWindow(GameWindow):
        """真实游戏窗口。通过 ClientToScreen 把客户区坐标转成屏幕绝对坐标。"""

        def __init__(self, hwnd: int):
            self._hwnd = hwnd

        @classmethod
        def attach_by_pid(cls, pid: int) -> "Win32GameWindow":
            return cls(_find_main_window_for_pid(pid))

        @property
        def hwnd(self) -> int:
            return self._hwnd

        def client_to_screen(self, x: int, y: int) -> tuple[int, int]:
            point = _POINT(x, y)
            if not _user32.ClientToScreen(self._hwnd, ctypes.byref(point)):
                raise WindowError(
                    f"ClientToScreen 失败，error={ctypes.get_last_error()}（窗口可能已关闭）"
                )
            return (point.x, point.y)

else:  # pragma: no cover - 非 Windows 平台上这些符号仅用于类型引用/测试跳过

    def _find_main_window_for_pid(pid: int) -> int:
        raise NotImplementedError("Win32GameWindow 仅支持 Windows")

    class Win32GameWindow(GameWindow):  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise NotImplementedError("Win32GameWindow 仅支持 Windows")

        @classmethod
        def attach_by_pid(cls, pid: int) -> "Win32GameWindow":
            raise NotImplementedError("Win32GameWindow 仅支持 Windows")
