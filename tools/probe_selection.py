"""Read-only selection probe for the controlled A/B city-selection experiment.

Polls the candidate command-manager selection pointer and writes one JSON line per
sample. It never sends input, writes game memory, or calls game functions.

Usage:
    python tools/probe_selection.py --seconds 180 --interval 0.5 \
        --out docs/rea/2026-10-23-selection-ab/probe.jsonl
"""
from __future__ import annotations

import argparse
import json
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

from capture_runtime_code import ProcessMemoryReader, verified_image
from san11agent.offsets import load_offsets
from san11agent.perception import resolve_anchor

COMMAND_MANAGER_GLOBAL = 0x96A58F0
CONTEXT_GLOBAL = 0x091BA048
SELECTED_OBJECT_OFFSET = 0x64
MAP_OBJECT_BASE_OFFSET = 0x89730
MAP_OBJECT_STRIDE = 0x38
MAP_OBJECT_CAPACITY = 0x4000
CITY_BASE_OFFSET = 0x1D8
CITY_STRIDE = 0x248
CITY_COUNT = 42


def _u32(reader: ProcessMemoryReader, address: int) -> int:
    return struct.unpack("<I", reader.read_bytes(address, 4))[0]


def _i32(reader: ProcessMemoryReader, address: int) -> int:
    return struct.unpack("<i", reader.read_bytes(address, 4))[0]


def sample(reader: ProcessMemoryReader, offsets, game_data_base: int, module_base: int) -> dict:
    manager_va = module_base + (COMMAND_MANAGER_GLOBAL - 0x400000)
    manager = _u32(reader, manager_va)
    context_va = module_base + (CONTEXT_GLOBAL - 0x400000)
    context = _u32(reader, context_va)
    result: dict = {
        "manager_global": hex(manager_va),
        "manager": hex(manager),
        "context_global": hex(context_va),
        "context": hex(context),
        "context_0x13c": None,
        "context_0x140": None,
        "selected_object": None,
        "selected_object_index": None,
        "selected_city": None,
        "map_object_coord": None,
    }
    if context:
        result["context_0x13c"] = hex(_u32(reader, context + 0x13C))
        result["context_0x140"] = hex(_u32(reader, context + 0x140))
    if not manager:
        return result

    selected = _u32(reader, manager + SELECTED_OBJECT_OFFSET)
    result["selected_object"] = hex(selected)
    if not selected:
        return result

    object_base = game_data_base + MAP_OBJECT_BASE_OFFSET
    if object_base <= selected < object_base + MAP_OBJECT_CAPACITY * MAP_OBJECT_STRIDE:
        index = (selected - object_base) // MAP_OBJECT_STRIDE
        result["selected_object_index"] = index
        if 0 <= index < CITY_COUNT:
            city = game_data_base + CITY_BASE_OFFSET + index * CITY_STRIDE
            result["selected_city"] = {
                "index": index,
                "name": reader.read_fixed_str(city + 4, 8, encoding=offsets.text_encoding),
                "force_id": _i32(reader, city + 0x38),
            }
        result["map_object_coord"] = [
            _u32(reader, selected + 0x1C) >> 16,
            _u32(reader, selected + 0x20) & 0xFFFF,
        ]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=180.0)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--process", default="San11WPK.exe")
    args = parser.parse_args()
    if args.seconds <= 0 or args.interval <= 0:
        parser.error("seconds/interval must be > 0")

    offsets = load_offsets(Path(__file__).resolve().parents[1] / "offsets/pk_1.1_cn.json")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        parser.error(f"output already exists: {args.out}")

    with ProcessMemoryReader.attach_by_name(args.process) as reader:
        _, _, digest = verified_image(reader)
        game_data_base = resolve_anchor(reader, offsets)
        started = time.monotonic()
        last = None
        with args.out.open("x", encoding="utf-8") as stream:
            while time.monotonic() - started < args.seconds:
                now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                try:
                    current = sample(reader, offsets, game_data_base, reader.module_base)
                except Exception as exc:  # noqa: BLE001 - research probe, keep sampling
                    current = {"error": str(exc)}
                record = {
                    "captured_at_utc": now,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "sha256": digest,
                    "pid": reader.pid,
                    **current,
                }
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
                marker = "CHANGE " if last is not None and current != last else ""
                print(marker + json.dumps(record, ensure_ascii=False), flush=True)
                last = current
                time.sleep(args.interval)

    print(json.dumps({"status": "done", "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
