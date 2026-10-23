"""Locate San11 city command menus from a screenshot (research tool).

The game positions its left-click command menu relative to the cursor/edge, so a fixed
``ui_layout`` offset is not reliable. This tool detects the menu's on-screen
rectangle from a screenshot instead. It is intentionally a research tool and
uses Pillow/numpy from the DSH bundled runtime; it is not imported by the
production package.

Usage (bundled Python):
    python tools/locate_menu.py shot.png --near 1200,430
"""
from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image


def _components(mask: np.ndarray, min_area: int):
    seen = np.zeros(mask.shape, bool)
    out = []
    h, w = mask.shape
    for yy in range(h):
        for xx in range(w):
            if not mask[yy, xx] or seen[yy, xx]:
                continue
            q = deque([(yy, xx)])
            seen[yy, xx] = True
            minx = maxx = xx
            miny = maxy = yy
            n = 0
            while q:
                cy, cx = q.popleft()
                n += 1
                minx, maxx = min(minx, cx), max(maxx, cx)
                miny, maxy = min(miny, cy), max(maxy, cy)
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        q.append((ny, nx))
            if n >= min_area:
                out.append({"area": n, "left": minx, "top": miny, "right": maxx, "bottom": maxy})
    return out


def _dark_buttons(arr: np.ndarray):
    r, g, b = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)
    mask = (r < 70) & (g < 95) & (b < 105)
    return _components(mask, 150)


def _teal_borders(arr: np.ndarray):
    r, g, b = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)
    mask = (r < 170) & (g > 100) & (b > 100) & ((g - r) > 25)
    return _components(mask, 80)


def _score(box, near):
    cx = (box["left"] + box["right"]) / 2
    cy = (box["top"] + box["bottom"]) / 2
    return (cx - near[0]) ** 2 + (cy - near[1]) ** 2


def detect(image_path: Path, near: tuple[int, int]):
    arr = np.array(Image.open(image_path).convert("RGB"))
    dark = _dark_buttons(arr)
    teal = _teal_borders(arr)
    # Top menu buttons are dark, roughly 50-100 px wide and 12-30 px tall.
    top = [b for b in dark if 35 <= (b["right"] - b["left"]) <= 120 and 10 <= (b["bottom"] - b["top"]) <= 35]
    top = sorted(top, key=lambda b: (_score(b, near), b["top"]))[:8]
    # Submenu outer frame is a taller teal/dark connected region.
    sub = [b for b in teal if (b["right"] - b["left"]) >= 60 and (b["bottom"] - b["top"]) >= 100]
    sub = sorted(sub, key=lambda b: _score(b, near))[:5]
    return {"image": str(image_path), "near": list(near), "top_candidates": top, "submenu_candidates": sub}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--near", default="0,0", help="click point x,y for ranking")
    args = parser.parse_args()
    x, y = (int(v) for v in args.near.split(","))
    print(json.dumps(detect(args.image, (x, y)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
