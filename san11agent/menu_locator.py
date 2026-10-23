"""菜单检测结果 -> 可点击坐标的纯几何层。

检测本身（从截图中找菜单矩形）属于研究工具；生产执行层只依赖这个
``MenuGeometry`` 契约。这样离线测试不需要 Pillow/截图，也能验证
“检测到菜单后按第 N 项点击”的坐标计算。
"""
from __future__ import annotations

from dataclasses import dataclass

from .map_projection import ScreenPoint


@dataclass(frozen=True)
class MenuGeometry:
    left: int
    top: int
    right: int
    bottom: int
    item_height: int
    count: int | None = None

    def __post_init__(self) -> None:
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError("menu bounds must have positive width/height")
        if self.item_height <= 0:
            raise ValueError("item_height must be positive")
        if self.count is not None and self.count <= 0:
            raise ValueError("count must be positive when provided")

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def item_count(self) -> int:
        if self.count is not None:
            return self.count
        return max(0, self.height // self.item_height)

    def item_center(self, index: int) -> ScreenPoint:
        if index < 0 or index >= self.item_count:
            raise IndexError(f"menu item {index} out of range [0,{self.item_count})")
        return ScreenPoint(
            (self.left + self.right) // 2,
            self.top + self.item_height // 2 + index * self.item_height,
        )
