"""select-city 子命令的 CLI 冒烟测试。

--dump 模式下 DumpMemoryReader 是只读、不会变化的，所以点击永远不会被"确认
生效"——这里只验证链路本身能跑通、超时后能干净地报错退出、动作日志能正常
打印，不验证"点击成功"这个结果（那依赖可写的假内存，已经在 test_execution.py
里用 CitySelector 直接覆盖过，不需要通过 CLI 重复测）。用很小的 --poll-timeout
让这个测试几百毫秒内跑完，不依赖真实游戏，也不会真的发送键鼠输入（默认
演练模式，未加 --live）。
"""
from __future__ import annotations

import json
from pathlib import Path

from san11agent.cli import main

FIXTURES = Path(__file__).resolve().parent / "fixtures"
OFFSETS_EXECUTION_TEST = FIXTURES / "offsets_execution_test.json"
UI_LAYOUT_TEST = FIXTURES / "ui_layout_test.json"
DUMP_EXECUTION_TEST = FIXTURES / "synthetic_execution_dump.json"


def test_select_city_dry_run_times_out_cleanly_against_readonly_dump(capsys):
    code = main([
        "select-city",
        "--offsets", str(OFFSETS_EXECUTION_TEST),
        "--ui-layout", str(UI_LAYOUT_TEST),
        "--dump", str(DUMP_EXECUTION_TEST),
        "--city-index", "3",
        "--tile-x", "5",
        "--tile-y", "5",
        "--poll-timeout", "0.05",
    ])

    assert code == 4  # ExecutionFailedError：--dump 是只读的，点击永远不会被确认
    captured = capsys.readouterr()
    assert "演练模式" in captured.err

    log_lines = [line for line in captured.out.splitlines() if line.strip()]
    assert log_lines  # 动作日志应该有内容
    parsed = [json.loads(line) for line in log_lines]
    assert any(entry["intent"] == "home" for entry in parsed)
    assert any(entry["intent"] == "select_city.attempt_failed" for entry in parsed)


def test_select_city_requires_dump_or_process(capsys):
    try:
        main([
            "select-city",
            "--offsets", str(OFFSETS_EXECUTION_TEST),
            "--ui-layout", str(UI_LAYOUT_TEST),
            "--city-index", "3",
            "--tile-x", "5",
            "--tile-y", "5",
        ])
        assert False, "应该抛出 SystemExit"
    except SystemExit as exc:
        assert exc.code != 0
