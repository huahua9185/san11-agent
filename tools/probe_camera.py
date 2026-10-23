"""Read-only camera calibration probe: selected city + cursor position.

The game's camera memory fields are still unknown. If the user hovers two cities
with known map coordinates, the isometric projection equations give the camera
offset/zoom mathematically. This tool records the paired samples; it never sends
input, writes memory, or calls game functions.

Usage:
    python tools/probe_camera.py --seconds 300 --interval 0.2 \
        --out docs/rea/2026-10-23-camera-calibration/probe.jsonl
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from capture_runtime_code import ProcessMemoryReader, verified_image
from san11agent.offsets import load_offsets
from san11agent.perception import resolve_anchor
from san11agent.selection_reader import read_selected_city
from san11agent.window import Win32GameWindow


def _cursor_client(hwnd: int) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    point = wintypes.POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
        return None, None
    screen = (point.x, point.y)
    if not ctypes.windll.user32.ScreenToClient(hwnd, ctypes.byref(point)):
        return screen, None
    return screen, (point.x, point.y)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=300.0)
    parser.add_argument("--interval", type=float, default=0.2)
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
        window = Win32GameWindow.attach_by_pid(reader.pid)
        started = time.monotonic()
        with args.out.open("x", encoding="utf-8") as stream:
            while time.monotonic() - started < args.seconds:
                screen, client = _cursor_client(window.hwnd)
                selected = read_selected_city(reader, offsets, game_data_base)
                record = {
                    "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "sha256": digest,
                    "pid": reader.pid,
                    "hwnd": hex(window.hwnd),
                    "cursor_screen": screen,
                    "cursor_client": client,
                    "selected_city": (
                        {
                            "index": selected.city_index,
                            "name": selected.city_name,
                            "map_x": selected.map_x,
                            "map_y": selected.map_y,
                            "object_address": hex(selected.object_address),
                        }
                        if selected is not None
                        else None
                    ),
                }
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
                time.sleep(args.interval)

    print(json.dumps({"status": "done", "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
