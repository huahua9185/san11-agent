"""加载 ui_layout/*.json —— 界面固定元素在客户区内的相对坐标表。

跟 offsets.py 的思路完全一致（同样是"找不到就标 unknown，不猜测填值"），只是
这里存的是屏幕像素坐标，不是内存偏移。之所以单独用一套文件格式而不是塞进
offsets/：这两类数据的来源、验证方式、变化频率完全不同——offsets 靠逆向内存
研究，ui_layout 靠实际截图/测量运行中的游戏窗口，混在一个文件里会让"这个
字段该找谁验证"变得含糊，见 offsets/schema.json 顶部的说明和这里的对照。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class UILayoutError(Exception):
    """ui_layout 文件格式错误，或者引用了标记为 unknown 的元素坐标却直接用。"""


@dataclass(frozen=True)
class UIElement:
    name: str
    x: int | None
    y: int | None
    width: int | None
    height: int | None
    tile_width: int | None
    tile_height: int | None
    unknown: bool
    note: str = ""

    def require_known(self) -> "UIElement":
        """在坐标换算代码里，任何要真正使用的元素坐标必须先过这一关，理由跟
        offsets.FieldSpec.require_known() 完全一样：让"这个坐标其实是 unknown，
        本不该被使用"这种错误在开发阶段就炸出来，而不是安静地点到屏幕上的
        某个随机位置。
        """
        if self.unknown or self.x is None or self.y is None:
            raise UILayoutError(
                f"界面元素 {self.name!r} 坐标未知（{self.note or '无说明'}），"
                f"不能用于点击/坐标换算。需要先用真实游戏截图测量并更新 ui_layout 文件。"
            )
        return self


@dataclass(frozen=True)
class UILayoutConfig:
    label: str
    verified: bool
    assumed_client_resolution: tuple[int, int] | None
    elements: dict[str, UIElement]

    def element(self, name: str) -> UIElement:
        if name not in self.elements:
            raise UILayoutError(f"ui_layout 文件里没有元素 {name!r}")
        return self.elements[name]


def _load_element(name: str, raw: dict[str, Any]) -> UIElement:
    if "unknown" not in raw:
        raise UILayoutError(f"元素 {name!r} 缺少必填的 unknown 标记")
    unknown = bool(raw["unknown"])
    x, y = raw.get("x"), raw.get("y")
    if not unknown and (x is None or y is None):
        raise UILayoutError(f"元素 {name!r} unknown=false 但没有给 x/y，格式不一致")
    return UIElement(
        name=name,
        x=x,
        y=y,
        width=raw.get("width"),
        height=raw.get("height"),
        tile_width=raw.get("tile_width"),
        tile_height=raw.get("tile_height"),
        unknown=unknown,
        note=raw.get("note", ""),
    )


def load_ui_layout(path: str | Path) -> UILayoutConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if "meta" not in raw or "elements" not in raw:
        raise UILayoutError("ui_layout 文件缺少 meta 或 elements 顶层字段")
    meta = raw["meta"]
    if "label" not in meta or "verified" not in meta:
        raise UILayoutError("ui_layout 文件 meta 缺少 label 或 verified")
    resolution = meta.get("assumed_client_resolution")
    elements = {name: _load_element(name, eraw) for name, eraw in raw["elements"].items()}
    return UILayoutConfig(
        label=meta["label"],
        verified=bool(meta["verified"]),
        assumed_client_resolution=tuple(resolution) if resolution else None,
        elements=elements,
    )
