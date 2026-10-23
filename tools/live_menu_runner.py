"""Research-only live menu geometry runner.

Captures a San11 client screenshot, detects the top/sub menu rectangles, and
emits ``MenuGeometry`` JSON. It does **not** send input; it is the bridge
between the screenshot detector and ``ActionMenuExecutor`` locators.

Run with the DSH bundled Python (Pillow/numpy available):
    python tools/live_menu_runner.py --pid 1234 --near 1200,430 --out top.json
    python tools/live_menu_runner.py --image tests/.../submenu.png --near 1300,430
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageGrab

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from san11agent.menu_locator import MenuGeometry
from san11agent.window import Win32GameWindow, ensure_dpi_awareness
from tools.locate_menu import _dark_buttons, _teal_borders


def _center(box):
    return (box["left"] + box["right"]) / 2, (box["top"] + box["bottom"]) / 2


def _dedup_rows(boxes):
    rows = []
    for box in sorted(boxes, key=lambda b: _center(b)[1]):
        cy = _center(box)[1]
        if rows and abs(cy - rows[-1]["cy"]) <= 7:
            if (box["right"] - box["left"]) > (rows[-1]["box"]["right"] - rows[-1]["box"]["left"]):
                rows[-1] = {"cy": cy, "box": box}
        else:
            rows.append({"cy": cy, "box": box})
    return rows


def _groups(rows):
    groups = []
    current = []
    for row in rows:
        if not current or 24 <= row["cy"] - current[-1]["cy"] <= 46:
            current.append(row)
        else:
            if len(current) >= 3:
                groups.append(current)
            current = [row]
    if len(current) >= 3:
        groups.append(current)
    return groups


def detect_top(arr: np.ndarray, near: tuple[int, int]) -> MenuGeometry | None:
    boxes = [
        b for b in _dark_buttons(arr)
        if 45 <= (b["right"] - b["left"]) <= 120 and 12 <= (b["bottom"] - b["top"]) <= 32
    ]
    near_x, near_y = near
    boxes = [b for b in boxes if abs(_center(b)[0] - near_x) < 180 and abs(_center(b)[1] - near_y) < 360]
    # A vertical menu is a column of boxes with nearly the same x range.
    clusters = []
    for box in sorted(boxes, key=lambda b: _center(b)[0]):
        cx = _center(box)[0]
        if clusters and abs(cx - clusters[-1]["cx"]) <= 14:
            clusters[-1]["boxes"].append(box)
        else:
            clusters.append({"cx": cx, "boxes": [box]})
    if not clusters:
        return None
    cluster = max(clusters, key=lambda c: len(c["boxes"]))
    group = sorted(cluster["boxes"], key=lambda b: b["top"])
    gaps = [
        _center(group[i + 1])[1] - _center(group[i])[1]
        for i in range(len(group) - 1)
    ]
    gaps = [gap for gap in gaps if gap >= 15]
    item_height = int(round(statistics.median(gaps))) if gaps else 34
    top = min(b["top"] for b in group)
    bottom = max(b["bottom"] for b in group)
    count = max(2, round((bottom - top) / item_height)) if item_height else len(group)
    left = min(b["left"] for b in group)
    right = max(b["right"] for b in group)
    # City top menu is 6 items, ~34 px each, one narrow column. Reject the
    # false "city list/other panel" detections that caused a wrong click.
    # The city top menu is exactly six commands (都市/軍事/人材/外交/計略/君主).
    if count != 6 or not (25 <= item_height <= 45) or not (40 <= right - left <= 120):
        return None
    if abs((left + right) / 2 - near_x) > 180:
        return None
    return MenuGeometry(
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        item_height=item_height,
        count=count,
    )


def detect_sub(arr: np.ndarray, near: tuple[int, int]) -> MenuGeometry | None:
    boxes = [b for b in _teal_borders(arr) if (b["right"] - b["left"]) >= 55 and (b["bottom"] - b["top"]) >= 90]
    if not boxes:
        return None
    near_x, near_y = near
    box = min(boxes, key=lambda b: (_center(b)[0] - near_x) ** 2 + (_center(b)[1] - near_y) ** 2)
    # Estimate item height/count from dark button rows inside the frame.
    dark = [
        b for b in _dark_buttons(arr)
        if box["left"] - 5 <= _center(b)[0] <= box["right"] + 5
        and box["top"] - 5 <= _center(b)[1] <= box["bottom"] + 5
        and 45 <= (b["right"] - b["left"]) <= 120
        and 12 <= (b["bottom"] - b["top"]) <= 32
    ]
    rows = _dedup_rows(dark)
    gaps = [rows[i + 1]["cy"] - rows[i]["cy"] for i in range(len(rows) - 1)]
    item_height = int(round(statistics.median(gaps))) if gaps else 34
    count = len(rows) if len(rows) >= 2 else max(1, round((box["bottom"] - box["top"]) / item_height))
    if not (3 <= count <= 10) or not (25 <= item_height <= 45):
        return None
    if not (55 <= box["right"] - box["left"] <= 180):
        return None
    return MenuGeometry(
        left=box["left"], top=box["top"], right=box["right"], bottom=box["bottom"],
        item_height=item_height, count=count,
    )


def capture_client(window) -> np.ndarray:
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    ctypes.windll.user32.GetClientRect(window.hwnd, ctypes.byref(rect))
    pt = wintypes.POINT(0, 0)
    ctypes.windll.user32.ClientToScreen(window.hwnd, ctypes.byref(pt))
    image = ImageGrab.grab(
        bbox=(pt.x, pt.y, pt.x + rect.right, pt.y + rect.bottom),
        all_screens=True,
    )
    return np.array(image.convert("RGB"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--near", default="0,0", help="menu click point x,y")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    near = tuple(int(v) for v in args.near.split(","))

    if args.image:
        arr = np.array(Image.open(args.image).convert("RGB"))
    elif args.pid:
        ensure_dpi_awareness()
        window = Win32GameWindow.attach_by_pid(args.pid)
        arr = capture_client(window)
    else:
        parser.error("need --pid or --image")

    result = {
        "near": list(near),
        "top": None,
        "sub": None,
    }
    for name, detector in (("top", detect_top), ("sub", detect_sub)):
        geometry = detector(arr, near)
        if geometry is not None:
            result[name] = {
                "left": geometry.left, "top": geometry.top,
                "right": geometry.right, "bottom": geometry.bottom,
                "item_height": geometry.item_height, "count": geometry.item_count,
            }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
