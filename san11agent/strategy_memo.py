"""M5：战略备忘录——LLM 自己维护的持久化文件，读写模块。

项目规格 3.4 节："战略备忘录：一个由 LLM 自己维护的持久化文件，记录当前
目标、对各势力的判断、未来几年的规划。每次调用时读入、更新后写回。长线
一致性靠它，不靠塞历史进上下文。"

三个设计问题（本模块的核心取舍，见提交报告"需要你确认的取舍"一节）：

1. **格式**：Markdown 正文 + 一段极简的 "---" 包裹的元数据头（`schema_version`
   /`turn`/`checksum`，纯 `key: value`，手写解析，不引入 PyYAML——本项目
   到现在为止运行时零第三方依赖，见 README，不想为这一个文件破例）。正文
   完全是 LLM 自己组织的自由 Markdown，人类和 LLM 都好读好改；元数据头只
   服务于程序校验，LLM 不需要关心它（写回时由 `write_memo()` 自动生成，
   不需要 LLM 自己拼接）。

2. **避免损坏**：
   - **原子写**：先写到同目录下的 `.tmp` 临时文件，再用 `os.replace()`
     覆盖目标路径——`os.replace` 在 POSIX 和 Windows 上都是原子操作，中途
     崩溃不会留下"写了一半"的备忘录文件。
   - **保留上一版备份**：覆盖前把当前文件复制成 `<path>.bak`（只保留一份，
     不是完整版本历史——如果你想要更完整的历史，见提交报告里的备选方案）。
   - **校验**：写入时把正文的 sha256 前16位存进元数据头；读取时重新计算
     校验，对不上就是文件在写入流程之外被改动/损坏（比如手工编辑漏改了
     校验值、或者磁盘错误），抛 `StrategyMemoCorruptedError`，不会把可能
     损坏的内容悄悄喂给 LLM。调用方（`strategy_loop.py`）捕获这个错误后
     可以选择 `restore_backup()` 回退到上一版。

3. **长度控制**：`write_memo()` 接受 `max_body_chars` 参数（默认见
   `DEFAULT_MAX_BODY_CHARS`），正文超过这个字符数直接拒绝写入（抛
   `StrategyMemoTooLongError`），不做自动截断/自动摘要——截断可能从句子
   中间切断丢失语义，自动摘要需要额外一次 LLM 调用，这次不做（本次范围
   完全离线、不调用任何真实 LLM）。这意味着"控制长度"这件事目前完全依赖
   prompt 里告诉 LLM 预算（见 `strategy_llm.build_strategy_prompt`）、以及
   LLM 本身愿不愿意遵守——如果真实 LLM 持续不遵守预算，备忘录会卡在"每次
   都被拒绝写入、永远用旧版本"的状态，这是一个需要你确认是否可接受的取舍，
   见提交报告。
"""
from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_MAX_BODY_CHARS = 6000

DEFAULT_BODY = (
    "## 当前目标\n\n（尚无记录，等待第一次 LLM 战略层调用写入）\n\n"
    "## 势力判断\n\n（尚无记录）\n\n"
    "## 未来规划\n\n（尚无记录）\n"
)


class StrategyMemoError(Exception):
    """战略备忘录读写相关错误的基类。"""


class StrategyMemoFormatError(StrategyMemoError):
    """文件内容不符合"元数据头 + 正文"的基本格式（不是校验问题，是格式本身解析不出来）。"""


class StrategyMemoCorruptedError(StrategyMemoError):
    """格式能解析，但正文的校验和与元数据头记录的不一致——文件在写入流程之外被改动或损坏。"""


class StrategyMemoTooLongError(StrategyMemoError):
    """新正文超过长度预算，拒绝写入（旧文件保持不变）。"""


def _checksum(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class StrategyMemo:
    """一份战略备忘录的内存表示：正文 + 它是哪个回合写入的。"""

    turn: int
    body: str
    schema_version: int = SCHEMA_VERSION


def _serialize(memo: StrategyMemo) -> str:
    header = (
        "---\n"
        f"schema_version: {memo.schema_version}\n"
        f"turn: {memo.turn}\n"
        f"checksum: {_checksum(memo.body)}\n"
        "---\n"
    )
    return header + memo.body


def _parse_header(header_text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in header_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            raise StrategyMemoFormatError(f"元数据头里有一行不是 key: value 格式: {line!r}")
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def _parse(text: str) -> StrategyMemo:
    if not text.startswith("---\n"):
        raise StrategyMemoFormatError("文件必须以 '---' 开头的元数据头开始")
    end_marker = "\n---\n"
    end_index = text.find(end_marker, 4)
    if end_index == -1:
        raise StrategyMemoFormatError("找不到元数据头的结束 '---' 标记")
    header_text = text[4:end_index]
    body = text[end_index + len(end_marker) :]

    fields = _parse_header(header_text)
    for required in ("schema_version", "turn", "checksum"):
        if required not in fields:
            raise StrategyMemoFormatError(f"元数据头缺少必填字段 {required!r}")

    try:
        schema_version = int(fields["schema_version"])
        turn = int(fields["turn"])
    except ValueError as exc:
        raise StrategyMemoFormatError(f"元数据头 schema_version/turn 必须是整数: {exc}") from exc

    if schema_version != SCHEMA_VERSION:
        raise StrategyMemoFormatError(
            f"元数据头 schema_version={schema_version}，本模块只认识 {SCHEMA_VERSION}"
        )

    expected_checksum = fields["checksum"]
    actual_checksum = _checksum(body)
    if expected_checksum != actual_checksum:
        raise StrategyMemoCorruptedError(
            f"正文校验和不匹配（元数据头记录 {expected_checksum}，实际算出 {actual_checksum}）"
            "——文件可能在写入流程之外被改动或损坏。"
        )

    return StrategyMemo(turn=turn, body=body, schema_version=schema_version)


def read_memo(path: str | Path) -> StrategyMemo:
    """读取一份战略备忘录。文件不存在时返回一份带默认模板正文、turn=0 的备忘录
    （不是错误——第一次调用 LLM 战略层之前，本来就不存在任何历史备忘录）。
    """
    path = Path(path)
    if not path.exists():
        return StrategyMemo(turn=0, body=DEFAULT_BODY)
    text = path.read_text(encoding="utf-8")
    return _parse(text)


def write_memo(
    path: str | Path, memo: StrategyMemo, *, max_body_chars: int = DEFAULT_MAX_BODY_CHARS
) -> None:
    """原子写入一份新的战略备忘录，写入前把当前文件备份成 <path>.bak。

    正文超过 max_body_chars 时拒绝写入并抛 StrategyMemoTooLongError，目标
    文件（和 .bak）都不会被改动——调用方应该保留旧的 StrategyMemo 继续使用。
    """
    if len(memo.body) > max_body_chars:
        raise StrategyMemoTooLongError(
            f"备忘录正文 {len(memo.body)} 字符，超过预算 {max_body_chars} 字符，拒绝写入"
        )

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _serialize(memo)

    if path.exists():
        backup_path = _backup_path(path)
        shutil.copyfile(path, backup_path)

    tmp_path = path.parent / (path.name + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)  # os.replace()，同一文件系统内是原子操作


def _backup_path(path: Path) -> Path:
    return path.parent / (path.name + ".bak")


def restore_backup(path: str | Path) -> StrategyMemo:
    """把 <path>.bak 恢复成当前文件，返回恢复后的内容。

    没有备份文件时抛 StrategyMemoError——调用方（strategy_loop.py）在
    read_memo() 抛出 StrategyMemoCorruptedError 时可以选择调用这个函数回退，
    但如果连备份都没有（比如第一次写入就损坏），没有更早的已知good状态可以
    回退，只能显式报错而不是编一份空白备忘录出来冒充"恢复成功"。
    """
    path = Path(path)
    backup_path = _backup_path(path)
    if not backup_path.exists():
        raise StrategyMemoError(f"没有可用的备份文件 {backup_path}，无法恢复")
    shutil.copyfile(backup_path, path)
    return read_memo(path)
