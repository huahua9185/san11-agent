"""完整的动作日志。

项目规格第5节要求：每个动作记录时间、意图、参数、执行结果、执行前后的关键
状态差异。这里的 ActionLog 是纯内存记录 + 可选 JSONL 序列化，不依赖任何真实
I/O，方便在测试里直接断言记录内容，也方便真实执行时落盘审计。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .clock import Clock


def diff_state(
    before: Mapping[str, Any] | None, after: Mapping[str, Any] | None
) -> dict[str, tuple[Any, Any]]:
    """只保留发生变化的键，值是 (旧值, 新值)。

    before/after 任一为 None 时视为空字典（比如动作执行前还没能读到任何状态）。
    """
    before = before or {}
    after = after or {}
    keys = set(before) | set(after)
    return {k: (before.get(k), after.get(k)) for k in keys if before.get(k) != after.get(k)}


@dataclass(frozen=True)
class ActionLogEntry:
    timestamp: float
    intent: str
    params: dict[str, Any]
    result: str
    state_diff: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ActionLog:
    """动作日志收集器。

    timestamp 来自注入的 Clock，跟 polling.py 用的是同一个时钟——日志里的时间戳
    和轮询超时计算的时间基准一致，方便事后核对"轮询超时那一刻和日志时间对不对得上"。
    """

    def __init__(self, clock: Clock):
        self._clock = clock
        self.entries: list[ActionLogEntry] = []

    def record(
        self,
        intent: str,
        params: Mapping[str, Any],
        result: str,
        *,
        state_before: Mapping[str, Any] | None = None,
        state_after: Mapping[str, Any] | None = None,
        detail: str = "",
    ) -> ActionLogEntry:
        entry = ActionLogEntry(
            timestamp=self._clock.now(),
            intent=intent,
            params=dict(params),
            result=result,
            state_diff=diff_state(state_before, state_after),
            detail=detail,
        )
        self.entries.append(entry)
        return entry

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(e.to_dict(), ensure_ascii=False) for e in self.entries)
