"""mem_scan.py 纯逻辑部分的离线测试——区域过滤规则、按块跳过的 diff 算法、
多区域快照对比。不依赖 ctypes/Windows/真实进程，可以在任何平台跑。
"""
from __future__ import annotations

import pytest

from san11agent.mem_scan import (
    MEM_COMMIT,
    MEM_IMAGE,
    MEM_PRIVATE,
    MemScanError,
    RegionInfo,
    diff_full_snapshots,
    find_changed_spans,
    find_toggled_spans,
    format_full_diff_report,
    format_toggled_spans,
    is_readable_protect,
    should_scan_region,
)

MEM_RESERVE = 0x2000
PAGE_NOACCESS = 0x01
PAGE_READONLY = 0x02
PAGE_READWRITE = 0x04
PAGE_EXECUTE_READWRITE = 0x40
PAGE_GUARD = 0x100


# -- is_readable_protect() --------------------------------------------------


def test_is_readable_protect_true_for_common_readable_flags():
    assert is_readable_protect(PAGE_READONLY) is True
    assert is_readable_protect(PAGE_READWRITE) is True
    assert is_readable_protect(PAGE_EXECUTE_READWRITE) is True


def test_is_readable_protect_false_for_noaccess():
    assert is_readable_protect(PAGE_NOACCESS) is False


def test_is_readable_protect_false_when_guard_bit_set():
    # PAGE_READWRITE 本身可读，但叠加 PAGE_GUARD 修饰位后不该被当作可读
    assert is_readable_protect(PAGE_READWRITE | PAGE_GUARD) is False


# -- should_scan_region() ---------------------------------------------------


def _region(*, state=MEM_COMMIT, protect=PAGE_READWRITE, type_=MEM_PRIVATE, size=0x1000):
    return RegionInfo(base_address=0x10000000, region_size=size, state=state, protect=protect, type=type_)


def test_should_scan_region_accepts_committed_readable_private():
    assert should_scan_region(_region()) is True


def test_should_scan_region_rejects_uncommitted():
    assert should_scan_region(_region(state=MEM_RESERVE)) is False


def test_should_scan_region_rejects_unreadable_protect():
    assert should_scan_region(_region(protect=PAGE_NOACCESS)) is False


def test_should_scan_region_rejects_image_type_by_default():
    assert should_scan_region(_region(type_=MEM_IMAGE)) is False


def test_should_scan_region_allows_image_type_when_only_private_false():
    assert should_scan_region(_region(type_=MEM_IMAGE), only_private=False) is True


def test_should_scan_region_rejects_oversized_region():
    assert should_scan_region(_region(size=0x1000), max_region_size=0x800) is False


def test_should_scan_region_rejects_zero_size():
    assert should_scan_region(_region(size=0)) is False


# -- find_changed_spans() ---------------------------------------------------


def test_find_changed_spans_no_change_returns_empty():
    data = b"\x00" * 10000
    assert find_changed_spans(0x1000, data, data) == []


def test_find_changed_spans_finds_single_byte_change_across_block_boundary():
    old = bytearray(9000)
    new = bytearray(old)
    new[5000] = 0xFF  # 落在第二个 4096 字节块里
    spans = find_changed_spans(0x2000, bytes(old), bytes(new), block_size=4096)
    assert spans == [(0x2000 + 5000, b"\x00", b"\xff")]


def test_find_changed_spans_finds_multiple_disjoint_changes():
    old = bytearray(200)
    new = bytearray(old)
    new[10] = 1
    new[10 + 1] = 2
    new[100] = 9
    spans = find_changed_spans(0, bytes(old), bytes(new), block_size=64)
    addrs = [s[0] for s in spans]
    assert addrs == [10, 100]
    assert spans[0][2] == b"\x01\x02"
    assert spans[1][2] == b"\x09"


def test_find_changed_spans_raises_on_length_mismatch():
    with pytest.raises(MemScanError):
        find_changed_spans(0, b"\x00" * 10, b"\x00" * 20)


# -- diff_full_snapshots() ---------------------------------------------------


def test_diff_full_snapshots_matches_regions_by_address_and_size():
    old = {0x1000: b"\x00" * 100, 0x2000: b"\x01" * 50}
    new = {0x1000: b"\x00" * 99 + b"\xff", 0x2000: b"\x01" * 50}

    report = diff_full_snapshots(old, new)

    assert report.matched_region_count == 2
    assert report.changed_spans == [(0x1000 + 99, b"\x00", b"\xff")]
    assert report.resized_regions == []
    assert report.only_in_old == []
    assert report.only_in_new == []


def test_diff_full_snapshots_reports_only_in_old_and_new():
    old = {0x1000: b"\x00" * 10, 0x5000: b"\x01" * 10}
    new = {0x1000: b"\x00" * 10, 0x9000: b"\x02" * 20}

    report = diff_full_snapshots(old, new)

    assert report.only_in_old == [(0x5000, 10)]
    assert report.only_in_new == [(0x9000, 20)]
    assert report.changed_spans == []


def test_diff_full_snapshots_reports_resized_region_without_byte_diff():
    old = {0x1000: b"\x00" * 10}
    new = {0x1000: b"\x00" * 20}

    report = diff_full_snapshots(old, new)

    assert report.resized_regions == [(0x1000, 10, 20)]
    assert report.matched_region_count == 0
    assert report.changed_spans == []


# -- find_toggled_spans() ----------------------------------------------------


def test_find_toggled_spans_detects_value_that_reverts():
    before = {0x1000: bytes([0, 0, 5, 0])}
    during = {0x1000: bytes([0, 0, 9, 0])}  # 第3字节临时变成9
    after = {0x1000: bytes([0, 0, 5, 0])}  # 又变回5

    spans = find_toggled_spans(before, during, after)

    assert spans == [(0x1002, b"\x05", b"\x09")]


def test_find_toggled_spans_ignores_monotonic_noise_that_never_reverts():
    # 模拟一个持续递增、从不变回原值的帧计数器：before=1, during=2, after=3
    before = {0x1000: bytes([1])}
    during = {0x1000: bytes([2])}
    after = {0x1000: bytes([3])}

    spans = find_toggled_spans(before, during, after)

    assert spans == []


def test_find_toggled_spans_ignores_bytes_that_never_changed():
    before = {0x1000: bytes([7])}
    during = {0x1000: bytes([7])}
    after = {0x1000: bytes([7])}

    assert find_toggled_spans(before, during, after) == []


def test_find_toggled_spans_only_considers_regions_present_in_all_three():
    before = {0x1000: b"\x00", 0x2000: b"\x00"}
    during = {0x1000: b"\x01"}  # 0x2000 这次没抓到
    after = {0x1000: b"\x00", 0x2000: b"\x00"}

    spans = find_toggled_spans(before, during, after)

    assert spans == [(0x1000, b"\x00", b"\x01")]


def test_format_toggled_spans_includes_stable_and_during_labels():
    spans = [(0x3000, b"\x05", b"\x09")]
    text = format_toggled_spans(spans)
    assert "0x00003000" in text
    assert "操作前/后" in text
    assert "操作中" in text


def test_format_full_diff_report_filters_by_min_bytes_and_respects_limit():
    old = {0x1000: bytes(100)}
    new_data = bytearray(100)
    new_data[0] = 1
    new_data[50] = 2
    new_data[51] = 3
    new = {0x1000: bytes(new_data)}

    report = diff_full_snapshots(old, new)
    # 两处变化：1字节 和 2字节；min_bytes=2 应该只剩下那处2字节的
    text = format_full_diff_report(report, min_bytes=2)
    assert "1 处" in text
    assert "0x00001032" in text  # 0x1000 + 50，八位十六进制零填充格式
