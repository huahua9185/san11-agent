"""对比两份或多份内存快照（mem_snapshot.py 抓的，或任何 DumpMemoryReader 能
加载的 dump json），定位哪些地址在操作前后发生了变化。

用于验证清单阶段5"定位缺失内存字段"：不用在 Cheat Engine 里手动比对，直接
diff 出候选偏移的地址范围、变化前后的字节内容，以及按几种常见数值类型的解读，
从噪音里挑出候选字段。

设计取舍（写进最终报告，供用户确认）：
- diff 只对比两份快照"都覆盖到"的地址范围；只在一份里出现的区域不参与比较
  （调用方如果关心，可以自己查 DumpMemoryReader.regions 的覆盖范围）。
- 3 份以上快照时按时间顺序做"相邻两两 diff"（transition），而不是"全部对同一
  个基准快照分别 diff"——这样更贴近"抓一份、操作一下、再抓一份、再操作一下……"
  这种连续操作的真实用法，不需要每次操作前都倒回同一个基准状态。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from .memory import DumpMemoryReader


@dataclass(frozen=True)
class ByteSpan:
    """一段连续的、"变了"或"没变"状态一致的字节区间。"""

    start: int
    old: bytes
    new: bytes
    changed: bool

    @property
    def length(self) -> int:
        return len(self.old)

    @property
    def end(self) -> int:
        return self.start + self.length


def _region_overlaps(
    before_regions: list[tuple[int, bytes]], after_regions: list[tuple[int, bytes]]
):
    """产出两份快照里 (region, region) 两两之间的重叠地址范围 [start, end)。

    假设同一份快照内部的 regions 互不重叠（mem-dump 正常使用不会产生重叠区域）。
    """
    for b_start, b_data in before_regions:
        b_end = b_start + len(b_data)
        for a_start, a_data in after_regions:
            a_end = a_start + len(a_data)
            lo, hi = max(b_start, a_start), min(b_end, a_end)
            if lo < hi:
                yield lo, hi


def _group_spans(start: int, old: bytes, new: bytes) -> list[ByteSpan]:
    spans: list[ByteSpan] = []
    n = len(old)
    i = 0
    while i < n:
        changed = old[i] != new[i]
        j = i + 1
        while j < n and (old[j] != new[j]) == changed:
            j += 1
        spans.append(ByteSpan(start=start + i, old=old[i:j], new=new[i:j], changed=changed))
        i = j
    return spans


def diff_snapshots(
    before: DumpMemoryReader,
    after: DumpMemoryReader,
    *,
    address_min: int | None = None,
    address_max: int | None = None,
) -> list[ByteSpan]:
    """逐字节对比两份快照里都覆盖到的地址范围，按"变了/没变"状态分组成连续区间，
    按起始地址升序返回。
    """
    spans: list[ByteSpan] = []
    for lo, hi in _region_overlaps(before.regions, after.regions):
        if address_min is not None:
            lo = max(lo, address_min)
        if address_max is not None:
            hi = min(hi, address_max)
        if lo >= hi:
            continue
        old = before.read_bytes(lo, hi - lo)
        new = after.read_bytes(lo, hi - lo)
        spans.extend(_group_spans(lo, old, new))
    spans.sort(key=lambda s: s.start)
    return spans


def filter_spans(spans: list[ByteSpan], *, show: str = "changed", min_bytes: int = 1) -> list[ByteSpan]:
    """show: "changed"（默认，只看变了的）/ "unchanged"（只看没变的）/ "all"。
    min_bytes: 只对 changed 的区间生效——变化字节数小于这个值的区间会被过滤掉，
    帮助从"整块内存都在轻微抖动"的噪音里挑出变化幅度更大的候选。
    """
    if show not in ("changed", "unchanged", "all"):
        raise ValueError(f"show 必须是 changed/unchanged/all 之一，收到 {show!r}")
    result = []
    for s in spans:
        if show == "changed" and not s.changed:
            continue
        if show == "unchanged" and s.changed:
            continue
        if s.changed and s.length < min_bytes:
            continue
        result.append(s)
    return result


def sort_spans(spans: list[ByteSpan], *, by: str = "address") -> list[ByteSpan]:
    if by == "address":
        return sorted(spans, key=lambda s: s.start)
    if by == "bytes":
        return sorted(spans, key=lambda s: s.length, reverse=True)
    raise ValueError(f"sort 必须是 address/bytes 之一，收到 {by!r}")


def interpret_bytes(data: bytes) -> str:
    """把一段字节按几种常见类型试着解读，帮助人眼判断候选字段的类型/含义。

    不假设字段类型——这正是这段区间"还不知道是什么"的探索阶段，所以把常见
    的几种解读都列出来，由人来判断哪种解读看起来"像"（比如像不像一个合理的
    数值，或者像不像 GBK 编码的武将姓名）。
    """
    parts = [f"hex={data.hex()}"]
    n = len(data)
    if n == 1:
        parts.append(f"u8={data[0]}")
        parts.append(f"i8={struct.unpack('<b', data)[0]}")
    elif n == 2:
        parts.append(f"u16={struct.unpack('<H', data)[0]}")
        parts.append(f"i16={struct.unpack('<h', data)[0]}")
    elif n == 4:
        parts.append(f"u32={struct.unpack('<I', data)[0]}")
        parts.append(f"i32={struct.unpack('<i', data)[0]}")
        parts.append(f"f32={struct.unpack('<f', data)[0]:.4g}")
    text = data.split(b"\x00", 1)[0]
    if text:
        try:
            decoded = text.decode("gbk")
            if decoded.isprintable():
                parts.append(f"gbk={decoded!r}")
        except UnicodeDecodeError:
            pass
    return " ".join(parts)


def format_span(span: ByteSpan, *, base_address: int | None = None) -> str:
    loc = f"0x{span.start:08X}"
    if base_address is not None:
        rel = span.start - base_address
        sign = "+" if rel >= 0 else "-"
        loc += f" (base{sign}0x{abs(rel):X})"
    if not span.changed:
        return f"{loc}  {span.length} 字节未变化  {interpret_bytes(span.old)}"
    return (
        f"{loc}  {span.length} 字节变化\n"
        f"    旧: {interpret_bytes(span.old)}\n"
        f"    新: {interpret_bytes(span.new)}"
    )


def format_report(spans: list[ByteSpan], *, base_address: int | None = None, limit: int | None = None) -> str:
    if not spans:
        return (
            "（没有符合条件的地址区间——如果预期应该有变化，检查一下 "
            "--show/--min-bytes/地址范围过滤条件是不是太严格了）"
        )
    shown = spans if limit is None else spans[:limit]
    lines = [format_span(s, base_address=base_address) for s in shown]
    if limit is not None and len(spans) > limit:
        lines.append(f"... 还有 {len(spans) - limit} 项被 --limit 截断，未显示")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 多份快照交叉比对
# ---------------------------------------------------------------------------


def changed_addresses(before: DumpMemoryReader, after: DumpMemoryReader) -> set[int]:
    """把 diff_snapshots 的结果展开成单字节地址集合，供交叉比对做集合运算用。"""
    result: set[int] = set()
    for span in diff_snapshots(before, after):
        if span.changed:
            result.update(range(span.start, span.end))
    return result


def _spans_from_addresses(addresses: set[int]) -> list[tuple[int, int]]:
    """把一组零散地址合并成连续区间 [start, end)，只用于展示，不带字节内容
    （交叉比对是集合运算的结果，取交集/差集后不再对应某一次具体的 old/new 字节对）。
    """
    if not addresses:
        return []
    ordered = sorted(addresses)
    spans = []
    start = prev = ordered[0]
    for addr in ordered[1:]:
        if addr == prev + 1:
            prev = addr
            continue
        spans.append((start, prev + 1))
        start = prev = addr
    spans.append((start, prev + 1))
    return spans


@dataclass(frozen=True)
class CrossCompareResult:
    transition_labels: list[str]
    transition_changed: list[set[int]]
    intersection: set[int]
    exclusive: dict[int, set[int]]  # transition 下标 -> 只在这次过渡里变化的地址


def cross_compare(snapshots: list[DumpMemoryReader], labels: list[str]) -> CrossCompareResult:
    """对一串按时间顺序排列的快照做"相邻两两 diff"，再做交叉分析。

    transition i 是 snapshots[i] -> snapshots[i+1] 之间的变化。至少需要 3 份快照
    （构成至少 2 次过渡）交叉比对才有意义。
    """
    if len(snapshots) < 3:
        raise ValueError("交叉比对至少需要 3 份快照（构成至少 2 次过渡）")
    transition_labels = [f"{labels[i]} -> {labels[i + 1]}" for i in range(len(snapshots) - 1)]
    transition_changed = [
        changed_addresses(snapshots[i], snapshots[i + 1]) for i in range(len(snapshots) - 1)
    ]
    intersection = set.intersection(*transition_changed) if transition_changed else set()
    exclusive: dict[int, set[int]] = {}
    for i, addrs in enumerate(transition_changed):
        others: set[int] = set()
        for j, other_addrs in enumerate(transition_changed):
            if j != i:
                others |= other_addrs
        exclusive[i] = addrs - others
    return CrossCompareResult(transition_labels, transition_changed, intersection, exclusive)


def format_cross_compare(result: CrossCompareResult, *, base_address: int | None = None) -> str:
    def fmt_addr(addr: int) -> str:
        if base_address is not None:
            rel = addr - base_address
            sign = "+" if rel >= 0 else "-"
            return f"0x{addr:08X} (base{sign}0x{abs(rel):X})"
        return f"0x{addr:08X}"

    def fmt_spans(addrs: set[int]) -> str:
        spans = _spans_from_addresses(addrs)
        if not spans:
            return "  (无)"
        return "\n".join(f"  {fmt_addr(s)} ~ {fmt_addr(e - 1)} ({e - s} 字节)" for s, e in spans)

    lines = ["== 交叉比对（相邻快照两两 diff） =="]
    for label, addrs in zip(result.transition_labels, result.transition_changed):
        lines.append(f"过渡「{label}」变化字节数: {len(addrs)}")
    lines.append("")
    lines.append(
        f"所有过渡都变化的地址（{len(result.intersection)} 字节）——"
        "可能是这类操作的稳定信号，也可能是和操作本身无关、每次都在变的噪音"
        "（比如帧计数器/心跳时钟），请结合是否每次都做了同类操作自行判断："
    )
    lines.append(fmt_spans(result.intersection))
    lines.append("")
    for i, label in enumerate(result.transition_labels):
        excl = result.exclusive[i]
        lines.append(f"仅在过渡「{label}」中变化的地址（{len(excl)} 字节，其它过渡都没变）：")
        lines.append(fmt_spans(excl))
        lines.append("")
    return "\n".join(lines).rstrip()
