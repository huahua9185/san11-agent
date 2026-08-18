from __future__ import annotations

import base64

import pytest

from san11agent.mem_snapshot import (
    RegionSpecError,
    capture_snapshot,
    parse_region_spec,
    write_snapshot_file,
)
from san11agent.memory import DumpMemoryReader


@pytest.fixture()
def reader():
    return DumpMemoryReader({0x1000: bytes(range(64))}, module_base=0x00400000)


def test_parse_region_spec_valid():
    assert parse_region_spec("0x1000:0x20") == (0x1000, 0x20)
    assert parse_region_spec("1000:20") == (0x1000, 0x20)  # 0x 前缀可选


def test_parse_region_spec_rejects_bad_format():
    with pytest.raises(RegionSpecError):
        parse_region_spec("0x1000")  # 缺少 :SIZE
    with pytest.raises(RegionSpecError):
        parse_region_spec("0x1000:0x10:0x20")  # 多了一段
    with pytest.raises(RegionSpecError):
        parse_region_spec("zzzz:0x10")  # 地址不是十六进制
    with pytest.raises(RegionSpecError):
        parse_region_spec("0x1000:0")  # 大小必须 > 0


def test_capture_snapshot_reads_requested_regions(reader):
    payload = capture_snapshot(reader, [(0x1000, 8), (0x1010, 4)], label="test-label")
    assert payload["module_base"] == "0x400000"
    assert payload["label"] == "test-label"
    assert len(payload["regions"]) == 2
    first = payload["regions"][0]
    assert first["address"] == "0x1000"
    assert first["size"] == 8
    assert base64.b64decode(first["data_base64"]) == bytes(range(8))


def test_capture_snapshot_rejects_empty_regions(reader):
    with pytest.raises(ValueError):
        capture_snapshot(reader, [])


def test_write_snapshot_file_round_trips_through_dump_reader(reader, tmp_path):
    out_path = tmp_path / "snap.json"
    write_snapshot_file(out_path, reader, [(0x1000, 16)], label="switch-to-domestic-before")

    loaded = DumpMemoryReader.from_json_file(out_path)
    assert loaded.module_base == 0x00400000
    assert loaded.read_bytes(0x1000, 16) == bytes(range(16))


def test_write_snapshot_file_ignored_extra_keys_still_loadable(reader, tmp_path):
    # captured_at/label/note 这些额外元数据字段不能影响 DumpMemoryReader 的正常加载。
    out_path = tmp_path / "snap.json"
    payload = write_snapshot_file(out_path, reader, [(0x1000, 4)], label="l", note="n")
    assert "captured_at" in payload
    DumpMemoryReader.from_json_file(out_path)  # 不应抛异常
