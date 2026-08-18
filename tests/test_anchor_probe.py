from __future__ import annotations

import json
from pathlib import Path

import pytest

from san11agent.anchor_probe import (
    format_candidate_result,
    format_report,
    load_candidates_file,
    probe_candidates,
)
from san11agent.memory import DumpMemoryReader
from san11agent.offsets import AnchorSpec, load_offsets

FIXTURES = Path(__file__).resolve().parent / "fixtures"
OFFSETS_TEST = FIXTURES / "offsets_test.json"
DUMP_TEST = FIXTURES / "synthetic_dump.json"


@pytest.fixture()
def offsets():
    return load_offsets(OFFSETS_TEST)


@pytest.fixture()
def reader():
    # synthetic_dump.json 里的数据区固定从地址 0x1000 开始（见
    # tests/fixtures/build_synthetic_dump.py），已知正确的 game_data_base 就是 0x1000。
    # 这里把 module_base 重设成 0，方便用简单直观的 rva 值（比如 0x1000）测试
    # static_rva 候选，而不必依赖 synthetic_dump.json 里 module_base 和数据区地址之间
    # 的具体数值关系（那个 module_base 只是为了配合生产 offsets 文件的 assumed_image_base
    # 摆的占位值，和这份 dump 的数据区地址没有算术关系）。
    original = DumpMemoryReader.from_json_file(DUMP_TEST)
    data = original.read_bytes(0x1000, 0x900)
    return DumpMemoryReader({0x1000: data}, module_base=0x0)


def _anchor(**overrides) -> AnchorSpec:
    base = dict(
        resolution_method="fixed_for_fixture",
        rva=None,
        pointer_chain=None,
        fixture_absolute_address=None,
        observed_absolute_address=None,
        confidence="unknown",
        note="test",
    )
    base.update(overrides)
    return AnchorSpec(**base)


def test_correct_absolute_candidate_passes(reader, offsets):
    candidates = [("正确候选", _anchor(fixture_absolute_address=0x1000))]
    results = probe_candidates(reader, offsets, candidates)
    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].game_data_base == 0x1000
    assert results[0].state is not None
    assert results[0].state.global_state.scenario_id == 3


def test_static_rva_candidate_passes_when_correct(reader, offsets):
    # reader.module_base == 0，所以 rva=0x1000 就是绝对地址 0x1000（正确值）。
    candidates = [("静态RVA候选", _anchor(resolution_method="static_rva", rva=0x1000))]
    results = probe_candidates(reader, offsets, candidates)
    assert results[0].ok is True


def test_shifted_candidate_fails_validation(reader, offsets):
    # 偏移4字节后，scenario_id 字段实际读到的是原本 start_year(=190) 的值，
    # 190 超出 offsets_test.json 里 scenario_id_range=[1,10] 的预期范围。
    candidates = [("偏移候选", _anchor(fixture_absolute_address=0x1004))]
    results = probe_candidates(reader, offsets, candidates)
    assert results[0].ok is False
    assert "剧本编号" in results[0].reason


def test_unreadable_candidate_reports_read_failure(reader, offsets):
    candidates = [("越界候选", _anchor(fixture_absolute_address=0x99999999))]
    results = probe_candidates(reader, offsets, candidates)
    assert results[0].ok is False
    assert "读取内存失败" in results[0].reason


def test_pointer_chain_candidate_dereference_failure_is_reported(reader, offsets):
    # module_base=0，chain[0]=0x9999999 本身就读不到 -> resolve_anchor 内部
    # read_u32 会抛 MemoryReadError，probe_candidates 需要接住它而不是让它冒泡。
    candidates = [("坏指针链候选", _anchor(resolution_method="pointer_chain", pointer_chain=[0x9999999, 0x10]))]
    results = probe_candidates(reader, offsets, candidates)
    assert results[0].ok is False
    assert "锚点解析失败" in results[0].reason


def test_multiple_candidates_mixed_results(reader, offsets):
    candidates = [
        ("正确", _anchor(fixture_absolute_address=0x1000)),
        ("错误", _anchor(fixture_absolute_address=0x1004)),
    ]
    results = probe_candidates(reader, offsets, candidates)
    assert [r.ok for r in results] == [True, False]


def test_load_candidates_file_reuses_anchor_parsing(tmp_path):
    payload = {
        "candidates": [
            {"label": "候选A", "resolution_method": "static_rva", "rva": "0x1958"},
            {"resolution_method": "fixed_for_fixture", "fixture_absolute_address": "0x1000"},
        ]
    }
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    candidates = load_candidates_file(path)
    assert len(candidates) == 2
    assert candidates[0][0] == "候选A"
    assert candidates[0][1].rva == 0x1958
    assert candidates[1][0] == "候选2"  # 没给 label 时自动编号
    assert candidates[1][1].fixture_absolute_address == 0x1000


def test_load_candidates_file_rejects_empty_list(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"candidates": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_candidates_file(path)


def test_format_report_mentions_pass_fail_and_recommendation(reader, offsets):
    candidates = [
        ("正确候选", _anchor(fixture_absolute_address=0x1000)),
        ("错误候选", _anchor(fixture_absolute_address=0x1004)),
    ]
    results = probe_candidates(reader, offsets, candidates)
    report = format_report(results)
    assert "通过" in report
    assert "未通过" in report
    assert '推荐候选: "正确候选"' in report


def test_format_report_all_failed_gives_guidance(reader, offsets):
    candidates = [("错误候选", _anchor(fixture_absolute_address=0x1004))]
    results = probe_candidates(reader, offsets, candidates)
    report = format_report(results)
    assert "没有候选通过校验" in report


def test_format_candidate_result_single(reader, offsets):
    candidates = [("正确候选", _anchor(fixture_absolute_address=0x1000))]
    results = probe_candidates(reader, offsets, candidates)
    text = format_candidate_result(1, 1, results[0])
    assert "候选 [1/1]" in text
    assert "GAME_DATA_BASE = 0x1000" in text
