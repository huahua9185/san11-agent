"""可注入时钟抽象。

polling.py 的通用轮询机制依赖它——生产代码用 SystemClock（真的 time.sleep()），
单元测试用 FakeClock（sleep() 只推进虚拟时间，不真的等待），这样基于轮询/超时/
重试写的测试可以在毫秒级跑完，而不用真的等游戏反应。
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod


class Clock(ABC):
    @abstractmethod
    def now(self) -> float:
        """单调递增的时间戳，单位秒。只用于测量经过时长，不代表真实墙钟时间。"""

    @abstractmethod
    def sleep(self, seconds: float) -> None:
        raise NotImplementedError


class SystemClock(Clock):
    """真实时钟：time.monotonic() + time.sleep()，供真实执行链路使用。"""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


class FakeClock(Clock):
    """测试用可控时钟：sleep() 只推进内部虚拟时间，不真的等待。

    这是"禁止用固定 sleep 等待"这条要求在测试侧的落地方式：凡是依赖
    polling.poll_until() 的代码，测试里都注入这个时钟，超时/重试逻辑
    照样能被完整覆盖，但整个测试套件不会因为轮询超时配置而真的变慢。
    """

    def __init__(self, start: float = 0.0):
        if start < 0:
            raise ValueError("start 不能为负")
        self._t = start

    def now(self) -> float:
        return self._t

    def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("sleep(seconds) 不能为负")
        self._t += seconds

    def advance(self, seconds: float) -> None:
        """测试里显式推进时间；语义等同 sleep()，只是名字在测试代码里读起来更直白。"""
        self.sleep(seconds)
