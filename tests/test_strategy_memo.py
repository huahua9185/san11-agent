"""M5：战略备忘录读写模块的单元测试。全部离线，用 tmp_path 临时目录，不依赖
任何真实文件系统之外的状态。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from san11agent.strategy_memo import (
    DEFAULT_BODY,
    StrategyMemo,
    StrategyMemoCorruptedError,
    StrategyMemoFormatError,
    StrategyMemoTooLongError,
    read_memo,
    restore_backup,
    write_memo,
)


def test_read_memo_missing_file_returns_default_template(tmp_path: Path):
    memo = read_memo(tmp_path / "memo.md")
    assert memo.turn == 0
    assert memo.body == DEFAULT_BODY


def test_write_then_read_round_trips(tmp_path: Path):
    path = tmp_path / "memo.md"
    write_memo(path, StrategyMemo(turn=3, body="## 目标\n打江陵\n"))

    loaded = read_memo(path)
    assert loaded.turn == 3
    assert loaded.body == "## 目标\n打江陵\n"


def test_written_file_has_visible_markdown_header_and_body(tmp_path: Path):
    path = tmp_path / "memo.md"
    write_memo(path, StrategyMemo(turn=1, body="正文内容"))

    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "schema_version:" in text
    assert "turn: 1" in text
    assert "checksum:" in text
    assert text.endswith("正文内容")


def test_write_creates_backup_of_previous_version(tmp_path: Path):
    path = tmp_path / "memo.md"
    write_memo(path, StrategyMemo(turn=1, body="第一版"))
    write_memo(path, StrategyMemo(turn=2, body="第二版"))

    backup_path = tmp_path / "memo.md.bak"
    assert backup_path.exists()
    backup_memo = read_memo(backup_path)
    assert backup_memo.body == "第一版"
    assert read_memo(path).body == "第二版"


def test_first_write_has_no_backup_to_create(tmp_path: Path):
    path = tmp_path / "memo.md"
    write_memo(path, StrategyMemo(turn=1, body="唯一版本"))
    assert not (tmp_path / "memo.md.bak").exists()


def test_write_rejects_body_over_char_budget(tmp_path: Path):
    path = tmp_path / "memo.md"
    write_memo(path, StrategyMemo(turn=1, body="旧版本"))

    with pytest.raises(StrategyMemoTooLongError):
        write_memo(path, StrategyMemo(turn=2, body="x" * 100), max_body_chars=50)

    # 拒绝写入后，旧文件必须保持不变，不能被部分覆盖。
    assert read_memo(path).body == "旧版本"


def test_write_does_not_leave_tmp_file_behind(tmp_path: Path):
    path = tmp_path / "memo.md"
    write_memo(path, StrategyMemo(turn=1, body="正文"))
    assert not (tmp_path / "memo.md.tmp").exists()


def test_read_detects_tampered_checksum_as_corrupted(tmp_path: Path):
    path = tmp_path / "memo.md"
    write_memo(path, StrategyMemo(turn=1, body="原始正文"))

    text = path.read_text(encoding="utf-8")
    tampered = text.replace("原始正文", "被篡改的正文，但校验和没有跟着更新")
    path.write_text(tampered, encoding="utf-8")

    with pytest.raises(StrategyMemoCorruptedError):
        read_memo(path)


def test_read_rejects_missing_header_marker(tmp_path: Path):
    path = tmp_path / "memo.md"
    path.write_text("没有元数据头，直接是正文", encoding="utf-8")

    with pytest.raises(StrategyMemoFormatError):
        read_memo(path)


def test_read_rejects_header_missing_required_field(tmp_path: Path):
    path = tmp_path / "memo.md"
    path.write_text("---\nschema_version: 1\nturn: 1\n---\n正文", encoding="utf-8")

    with pytest.raises(StrategyMemoFormatError):
        read_memo(path)  # 缺 checksum 字段


def test_restore_backup_recovers_previous_version(tmp_path: Path):
    path = tmp_path / "memo.md"
    write_memo(path, StrategyMemo(turn=1, body="第一版"))
    write_memo(path, StrategyMemo(turn=2, body="第二版"))

    # 模拟当前文件损坏
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("第二版", "损坏内容"), encoding="utf-8")
    with pytest.raises(StrategyMemoCorruptedError):
        read_memo(path)

    restored = restore_backup(path)
    assert restored.body == "第一版"
    assert read_memo(path).body == "第一版"


def test_restore_backup_without_any_backup_raises(tmp_path: Path):
    path = tmp_path / "memo.md"
    write_memo(path, StrategyMemo(turn=1, body="唯一版本"))

    with pytest.raises(Exception):
        restore_backup(path)
