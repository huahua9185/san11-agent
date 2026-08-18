from __future__ import annotations

import struct

import pytest

from san11agent.mem_diff import (
    cross_compare,
    diff_snapshots,
    filter_spans,
    format_cross_compare,
    format_report,
    interpret_bytes,
    sort_spans,
)
from san11agent.memory import DumpMemoryReader


def _reader(data: bytes, base: int = 0x1000, module_base: int = 0x400000) -> DumpMemoryReader:
    return DumpMemoryReader({base: data}, module_base=module_base)


def test_diff_detects_single_changed_byte():
    before = _reader(bytes([1, 2, 3, 4]))
    after = _reader(bytes([1, 2, 9, 4]))
    spans = diff_snapshots(before, after)
    changed = [s for s in spans if s.changed]
    assert len(changed) == 1
    span = changed[0]
    assert span.start == 0x1002
    assert span.length == 1
    assert span.old == bytes([3])
    assert span.new == bytes([9])


def test_diff_groups_contiguous_changed_bytes_into_one_span():
    before = _reader(bytes([0, 0, 0, 0, 0, 0]))
    after = _reader(bytes([0, 9, 9, 9, 0, 0]))
    spans = diff_snapshots(before, after)
    changed = [s for s in spans if s.changed]
    assert len(changed) == 1
    assert changed[0].start == 0x1001
    assert changed[0].length == 3


def test_diff_reports_unchanged_spans_too():
    before = _reader(bytes([1, 2, 3]))
    after = _reader(bytes([1, 9, 3]))
    spans = diff_snapshots(before, after)
    # 未变化的前后两段各自成一个 span，中间一个变化的 span
    assert [(s.start, s.length, s.changed) for s in spans] == [
        (0x1000, 1, False),
        (0x1001, 1, True),
        (0x1002, 1, False),
    ]


def test_diff_only_compares_overlapping_regions():
    before = DumpMemoryReader({0x1000: bytes([1, 2, 3, 4])}, module_base=0x400000)
    after = DumpMemoryReader({0x1002: bytes([9, 9, 9, 9])}, module_base=0x400000)
    spans = diff_snapshots(before, after)
    # 只有 0x1002~0x1004 是两份快照都覆盖的范围
    assert all(0x1002 <= s.start < 0x1004 for s in spans)
    total_len = sum(s.length for s in spans)
    assert total_len == 2


def test_diff_respects_address_range_filters():
    before = _reader(bytes(range(16)))
    after = _reader(bytes([255] * 16))
    spans = diff_snapshots(before, after, address_min=0x1004, address_max=0x1008)
    assert spans
    assert all(0x1004 <= s.start and s.end <= 0x1008 for s in spans)


def test_filter_spans_show_and_min_bytes():
    before = _reader(bytes([0, 0, 0, 0]))
    after = _reader(bytes([9, 0, 8, 8]))
    spans = diff_snapshots(before, after)

    changed_only = filter_spans(spans, show="changed")
    assert all(s.changed for s in changed_only)

    unchanged_only = filter_spans(spans, show="unchanged")
    assert all(not s.changed for s in unchanged_only)

    all_spans = filter_spans(spans, show="all")
    assert len(all_spans) == len(spans)

    big_only = filter_spans(spans, show="changed", min_bytes=2)
    assert all(s.length >= 2 for s in big_only)
    assert not any(s.length == 1 for s in big_only)


def test_filter_spans_rejects_bad_show():
    with pytest.raises(ValueError):
        filter_spans([], show="bogus")


def test_sort_spans_by_address_and_bytes():
    before = _reader(bytes(16))
    after_data = bytearray(16)
    after_data[0] = 1  # 1 字节变化 at 0x1000
    after_data[8:11] = [1, 2, 3]  # 3 字节变化 at 0x1008
    after = _reader(bytes(after_data))
    spans = filter_spans(diff_snapshots(before, after), show="changed")

    by_addr = sort_spans(spans, by="address")
    assert [s.start for s in by_addr] == sorted(s.start for s in spans)

    by_bytes = sort_spans(spans, by="bytes")
    assert by_bytes[0].length >= by_bytes[-1].length

    with pytest.raises(ValueError):
        sort_spans(spans, by="bogus")


def test_interpret_bytes_shows_numeric_and_string_readings():
    assert "u8=5" in interpret_bytes(bytes([5]))
    assert "u16=" in interpret_bytes(struct.pack("<H", 1000))
    assert "i32=" in interpret_bytes(struct.pack("<i", -5))
    name = "曹操".encode("gbk") + b"\x00\x00"
    assert "gbk='曹操'" in interpret_bytes(name)


def test_format_report_empty_and_nonempty():
    assert "没有符合条件" in format_report([])
    before = _reader(bytes([0]))
    after = _reader(bytes([1]))
    spans = filter_spans(diff_snapshots(before, after), show="changed")
    report = format_report(spans, base_address=0x1000)
    assert "0x00001000" in report
    assert "base+0x0" in report


def test_format_report_limit_truncates():
    # 不相邻的字节各自变化，制造出多个独立的 span，才能测 --limit 截断行为。
    before = _reader(bytes(8))
    after_data = bytearray(8)
    for i in range(0, 8, 2):
        after_data[i] = 1
    after = _reader(bytes(after_data))
    spans = filter_spans(diff_snapshots(before, after), show="changed")
    assert len(spans) > 1
    report = format_report(spans, limit=1)
    assert "被 --limit 截断" in report


def test_cross_compare_requires_at_least_three_snapshots():
    a = _reader(bytes(4))
    b = _reader(bytes(4))
    with pytest.raises(ValueError):
        cross_compare([a, b], ["a", "b"])


def test_cross_compare_intersection_and_exclusive():
    # 地址 0x1000 每次过渡都变化 -> 应该出现在交集里
    # 地址 0x1001 只在第一次过渡变化 -> 只在过渡0的 exclusive 里
    # 地址 0x1002 只在第二次过渡变化 -> 只在过渡1的 exclusive 里
    s0 = _reader(bytes([0, 0, 0, 0]))
    s1 = _reader(bytes([1, 1, 0, 0]))  # 过渡0: s0->s1，0x1000/0x1001 变化
    s2 = _reader(bytes([2, 1, 1, 0]))  # 过渡1: s1->s2，0x1000/0x1002 变化
    result = cross_compare([s0, s1, s2], ["s0", "s1", "s2"])

    assert result.intersection == {0x1000}
    assert result.exclusive[0] == {0x1001}
    assert result.exclusive[1] == {0x1002}

    report = format_cross_compare(result, base_address=0x1000)
    assert "交叉比对" in report
    assert "0x00001000" in report


def test_cross_compare_with_four_snapshots_labels_transitions():
    readers = [
        _reader(bytes([0, 0])),
        _reader(bytes([1, 0])),
        _reader(bytes([1, 1])),
        _reader(bytes([2, 1])),
    ]
    result = cross_compare(readers, ["s0", "s1", "s2", "s3"])
    assert result.transition_labels == ["s0 -> s1", "s1 -> s2", "s2 -> s3"]
    assert len(result.transition_changed) == 3
