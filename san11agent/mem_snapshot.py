"""从真实进程（或已有 dump）捕获原始内存快照，写成 DumpMemoryReader 能直接
识别的 JSON 格式。

memory.py 里 DumpMemoryReader 的文档字符串一直提到"等拿到真实进程的内存 dump
后，可以再写一个转换脚本"——这里补上的就是"从真实进程写出这种格式"的一端。
写出来的文件可以直接喂给 `snapshot --dump`、也可以喂给 mem_diff.py 做前后对比，
不需要额外的转换步骤。

典型用法（阶段5"定位缺失内存字段"）：切换界面/推进时间/点城池前，抓一份快照；
操作完，再抓一份；用 mem-diff 直接 diff 出哪些地址变了。
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .memory import MemoryReader


class RegionSpecError(Exception):
    """--region 参数格式不对（不是合法的 ADDR:SIZE）。"""


def parse_region_spec(spec: str) -> tuple[int, int]:
    """解析 "ADDR:SIZE" 形式的区域描述，比如 "0x07201958:0x1000"。

    地址和大小都按十六进制解析（0x 前缀可选）。
    """
    parts = spec.split(":")
    if len(parts) != 2:
        raise RegionSpecError(f"区域描述 {spec!r} 格式不对，应为 ADDR:SIZE，例如 0x07201958:0x1000")
    addr_str, size_str = parts
    try:
        address = int(addr_str, 16)
        size = int(size_str, 16)
    except ValueError as exc:
        raise RegionSpecError(f"区域描述 {spec!r} 里的地址或大小不是合法的十六进制数: {exc}") from exc
    if size <= 0:
        raise RegionSpecError(f"区域描述 {spec!r} 的大小必须 > 0")
    return address, size


def capture_snapshot(
    reader: MemoryReader,
    regions: list[tuple[int, int]],
    *,
    label: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """从 reader 读出 regions 覆盖的所有字节，打包成 DumpMemoryReader.from_json_file
    能直接识别的字典（module_base + regions[].address/data_base64）。

    额外带上 captured_at/label/note 三个元数据字段——DumpMemoryReader 加载时会
    忽略它们（只读 module_base 和 regions[].address/data_base64），但能帮人在
    diff 报告里认出"这是哪次操作前/后抓的"。
    """
    if not regions:
        raise ValueError("regions 不能为空——至少要指定一个地址范围")
    region_payload = []
    for address, size in regions:
        data = reader.read_bytes(address, size)
        region_payload.append({
            "address": hex(address),
            "size": size,
            "data_base64": base64.b64encode(data).decode("ascii"),
        })
    return {
        "module_base": hex(reader.module_base),
        "label": label,
        "note": note,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "regions": region_payload,
    }


def write_snapshot_file(
    path: str | Path,
    reader: MemoryReader,
    regions: list[tuple[int, int]],
    *,
    label: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """capture_snapshot() 之后直接写到磁盘上，返回同一份 payload 方便调用方打印摘要。"""
    payload = capture_snapshot(reader, regions, label=label, note=note)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
