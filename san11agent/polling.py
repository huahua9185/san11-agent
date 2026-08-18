"""通用轮询/超时机制。

项目规格明确禁止用固定 sleep 等待动作生效：每个动作发出后必须轮询内存里的
状态标志确认生效，超时则报告失败（是否重试、要不要归位，是调用方
execution.py 的职责，这里只提供"在一个时间窗口内轮询直到条件成立或超时"
这一个可复用的原语，职责分开是为了这个函数本身可以被独立测试和复用）。

clock 参数可注入（见 clock.py），生产代码用 SystemClock，测试用 FakeClock——
FakeClock.sleep() 只推进虚拟时间，所以基于这个机制写的单元测试不会真的等待。
"""
from __future__ import annotations

from typing import Callable

from .clock import Clock


class PollTimeoutError(Exception):
    def __init__(self, description: str, attempts: int, elapsed: float):
        self.description = description
        self.attempts = attempts
        self.elapsed = elapsed
        super().__init__(
            f"轮询超时: {description}（尝试 {attempts} 次，耗时 {elapsed:.3f}s 后仍未满足条件）"
        )


def poll_until(
    condition: Callable[[], bool],
    *,
    timeout: float,
    interval: float,
    clock: Clock,
    description: str = "",
) -> int:
    """反复调用 condition()，每次失败后 clock.sleep(interval) 再重试，直到条件
    成立或总耗时超过 timeout。成功返回尝试次数；超时抛 PollTimeoutError。

    只负责"在一个时间窗口内轮询"，不做重试上层动作（比如重新点一次鼠标）——
    那属于 execution.py 里"失败即归位重来"的范畴。
    """
    if timeout < 0:
        raise ValueError("timeout 不能为负")
    if interval <= 0:
        raise ValueError("interval 必须 > 0")

    deadline = clock.now() + timeout
    attempts = 0
    while True:
        attempts += 1
        if condition():
            return attempts
        now = clock.now()
        if now >= deadline:
            raise PollTimeoutError(description, attempts, now)
        clock.sleep(min(interval, deadline - now))
