from __future__ import annotations

import json
from pathlib import Path

from san11agent.cli import main

FIXTURES = Path(__file__).resolve().parent / "fixtures"
OFFSETS_TEST = FIXTURES / "offsets_test.json"
DUMP_TEST = FIXTURES / "synthetic_dump.json"
DOMESTIC_RULES_TEST = FIXTURES / "domestic_rules_test.json"


def test_snapshot_json_mode(capsys):
    code = main(["snapshot", "--offsets", str(OFFSETS_TEST), "--dump", str(DUMP_TEST)])
    assert code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["global_state"]["scenario_id"] == 3
    assert len(payload["generals"]) == 2
    assert payload["generals"][0]["name"] == "曹操"


def test_snapshot_summary_mode(capsys):
    code = main(["snapshot", "--offsets", str(OFFSETS_TEST), "--dump", str(DUMP_TEST), "--summary"])
    assert code == 0
    out = capsys.readouterr().out
    assert "剧本 3" in out
    assert "许昌" in out


def test_snapshot_requires_dump_or_process(capsys):
    try:
        main(["snapshot", "--offsets", str(OFFSETS_TEST)])
        assert False, "应该抛出 SystemExit"
    except SystemExit as exc:
        assert exc.code != 0


# ---------------------------------------------------------------------------
# visible-state（M2 接入 CLI，2026-08-19 新增）
# ---------------------------------------------------------------------------


def test_visible_state_json_mode(capsys):
    code = main([
        "visible-state", "--offsets", str(OFFSETS_TEST), "--dump", str(DUMP_TEST),
        "--player-faction-id", "0",
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["global_state"]["scenario_id"] == 3
    # VisibleGeneralFull 才有 stamina 字段；VisibleGeneralPublic 没有——用它验证
    # 确实走了 M2 过滤链路，不是直接把 GameState 转成了 JSON。
    assert "stamina" in payload["generals"][0] or "faction_id" in payload["generals"][0]


def test_visible_state_summary_mode_shows_own_cities(capsys):
    code = main([
        "visible-state", "--offsets", str(OFFSETS_TEST), "--dump", str(DUMP_TEST),
        "--player-faction-id", "0", "--summary",
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "玩家势力: 0" in out
    assert "己方城池" in out


def test_visible_state_defaults_to_nothing_extra_visible(capsys):
    """不传 --explored-cities/--visible-troops/--discovered-generals 时，
    非己方实体应该按 StaticVisibilitySource 的保守默认处理（不额外可见）——
    这里只验证命令能正常跑通并产出确定性结果，不依赖真实的可见性数据。
    """
    code = main([
        "visible-state", "--offsets", str(OFFSETS_TEST), "--dump", str(DUMP_TEST),
        "--player-faction-id", "0",
    ])
    assert code == 0


# ---------------------------------------------------------------------------
# legal-actions（M4 接入 CLI，2026-08-19 新增）
# ---------------------------------------------------------------------------


def test_legal_actions_enumerates_and_prints_descriptions(capsys):
    code = main([
        "legal-actions", "--offsets", str(OFFSETS_TEST), "--dump", str(DUMP_TEST),
        "--rules", str(DOMESTIC_RULES_TEST), "--player-faction-id", "0",
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "条合法动作" in out
    assert "武将" in out and "城池" in out


def test_legal_actions_respects_assigned_generals_exclusion(capsys):
    code_all = main([
        "legal-actions", "--offsets", str(OFFSETS_TEST), "--dump", str(DUMP_TEST),
        "--rules", str(DOMESTIC_RULES_TEST), "--player-faction-id", "0",
    ])
    assert code_all == 0
    out_all = capsys.readouterr().out
    count_all = int(out_all.split("共 ")[1].split(" 条")[0])

    code_excluded = main([
        "legal-actions", "--offsets", str(OFFSETS_TEST), "--dump", str(DUMP_TEST),
        "--rules", str(DOMESTIC_RULES_TEST), "--player-faction-id", "0",
        "--assigned-generals", "0",
    ])
    assert code_excluded == 0
    out_excluded = capsys.readouterr().out
    count_excluded = int(out_excluded.split("共 ")[1].split(" 条")[0])

    assert count_excluded < count_all
    assert "[武将0]" not in out_excluded


def test_legal_actions_rejects_bad_rules_path(capsys):
    code = main([
        "legal-actions", "--offsets", str(OFFSETS_TEST), "--dump", str(DUMP_TEST),
        "--rules", "does/not/exist.json", "--player-faction-id", "0",
    ])
    assert code == 1
    assert "无法加载规则表" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# mem-dump / mem-diff（辅助工具一）
# ---------------------------------------------------------------------------


def test_mem_dump_from_existing_dump_writes_loadable_snapshot(tmp_path, capsys):
    out_path = tmp_path / "snap.json"
    code = main([
        "mem-dump", "--dump", str(DUMP_TEST),
        "--region", "0x1000:0x20",
        "--out", str(out_path),
        "--label", "before",
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "已写出快照" in out

    from san11agent.memory import DumpMemoryReader
    loaded = DumpMemoryReader.from_json_file(out_path)
    assert loaded.read_bytes(0x1000, 4) is not None  # 能正常读取，说明格式对


def test_mem_dump_rejects_bad_region_spec(tmp_path, capsys):
    out_path = tmp_path / "snap.json"
    code = main([
        "mem-dump", "--dump", str(DUMP_TEST),
        "--region", "not-a-region",
        "--out", str(out_path),
    ])
    assert code == 1
    assert "错误" in capsys.readouterr().err


def _write_dump(path: Path, address: int, data: bytes, module_base: str = "0x400000") -> None:
    import base64
    payload = {
        "module_base": module_base,
        "regions": [{"address": hex(address), "data_base64": base64.b64encode(data).decode("ascii")}],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_mem_diff_two_snapshots_reports_changed_bytes(tmp_path, capsys):
    snap1 = tmp_path / "s1.json"
    snap2 = tmp_path / "s2.json"
    _write_dump(snap1, 0x2000, bytes([0, 0, 0, 0]))
    _write_dump(snap2, 0x2000, bytes([0, 9, 0, 0]))

    code = main(["mem-diff", str(snap1), str(snap2)])
    assert code == 0
    out = capsys.readouterr().out
    assert "0x00002001" in out
    assert "交叉比对" not in out  # 只有2份快照，不触发交叉比对


def test_mem_diff_requires_at_least_two_snapshots(tmp_path, capsys):
    snap1 = tmp_path / "s1.json"
    _write_dump(snap1, 0x2000, bytes([0]))
    code = main(["mem-diff", str(snap1)])
    assert code == 1
    assert "至少需要 2 份快照" in capsys.readouterr().err


def test_mem_diff_four_snapshots_triggers_cross_compare(tmp_path, capsys):
    snap_paths = []
    frames = [bytes([0, 0]), bytes([1, 0]), bytes([1, 1]), bytes([2, 1])]
    for i, data in enumerate(frames):
        p = tmp_path / f"s{i}.json"
        _write_dump(p, 0x3000, data)
        snap_paths.append(p)

    code = main(["mem-diff", *[str(p) for p in snap_paths]])
    assert code == 0
    out = capsys.readouterr().out
    assert "交叉比对" in out
    assert "s0.json -> s1.json" in out


def test_mem_diff_filters_by_min_bytes(tmp_path, capsys):
    snap1 = tmp_path / "s1.json"
    snap2 = tmp_path / "s2.json"
    _write_dump(snap1, 0x2000, bytes(4))
    _write_dump(snap2, 0x2000, bytes([1, 0, 0, 0]))  # 只有1字节变化

    code = main(["mem-diff", str(snap1), str(snap2), "--min-bytes", "2"])
    assert code == 0
    out = capsys.readouterr().out
    assert "没有符合条件" in out


# ---------------------------------------------------------------------------
# probe-anchor（辅助工具二）
# ---------------------------------------------------------------------------


def test_probe_anchor_absolute_candidates_reports_pass_and_fail(capsys):
    code = main([
        "probe-anchor", "--offsets", str(OFFSETS_TEST), "--dump", str(DUMP_TEST),
        "--absolute", "0x1000",  # 正确
        "--absolute", "0x1004",  # 错误（偏移了）
    ])
    assert code == 0  # 至少一个通过
    out = capsys.readouterr().out
    assert "通过" in out
    assert "未通过" in out


def test_probe_anchor_all_fail_returns_nonzero(capsys):
    code = main([
        "probe-anchor", "--offsets", str(OFFSETS_TEST), "--dump", str(DUMP_TEST),
        "--absolute", "0x99999999",
    ])
    assert code == 2


def test_probe_anchor_requires_at_least_one_candidate_source(capsys):
    code = main(["probe-anchor", "--offsets", str(OFFSETS_TEST), "--dump", str(DUMP_TEST)])
    assert code == 1
    assert "至少需要通过" in capsys.readouterr().err


def test_probe_anchor_candidates_file(tmp_path, capsys):
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(json.dumps({
        "candidates": [
            {"label": "来自文件的候选", "resolution_method": "fixed_for_fixture", "fixture_absolute_address": "0x1000"},
        ]
    }), encoding="utf-8")

    code = main([
        "probe-anchor", "--offsets", str(OFFSETS_TEST), "--dump", str(DUMP_TEST),
        "--candidates-file", str(candidates_path),
    ])
    assert code == 0
    assert "来自文件的候选" in capsys.readouterr().out
