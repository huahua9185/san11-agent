"""M3 执行层需要、但不属于 M1 GameState 概念范围的两类"当前 UI 状态"：

- CameraState：决定地图渲染的摄像机偏移/缩放，map_projection.py 用它把地图
  格子坐标反算成屏幕坐标。
- SelectionState：当前被选中的城池，execution.py 用它轮询确认"点击城池"这个
  动作是否生效。

两者都优先复用 perception.py 的 read_struct_fields()——同一套"按 offsets
字段表读内存"的机制，只是这两个 struct 是单例（count=1），不是数组。

camera 字段目前仍是 unknown，读取时和 M1/M2 一致：unknown 字段安静返回 None，
调用方（map_projection.py / execution.py）自己决定"字段为 None 时怎么办"，
通常是显式报错。selection 的 offsets 字段也仍是 unknown，但已回退到
selection_reader 的纯悬停 A/B 链路；只有连该链路也读不到时才返回 None。
"""
from __future__ import annotations

from dataclasses import dataclass

from .memory import MemoryReader
from .offsets import OffsetsConfig
from .perception import read_struct_fields
from .selection_reader import read_selected_city


@dataclass(frozen=True)
class CameraState:
    offset_x: int | None
    offset_y: int | None
    zoom_level: int | None


@dataclass(frozen=True)
class SelectionState:
    selected_city_index: int | None


def parse_camera_state(reader: MemoryReader, offsets: OffsetsConfig, game_data_base: int) -> CameraState:
    f = read_struct_fields(reader, offsets, game_data_base, "camera")
    return CameraState(
        offset_x=f.get("offset_x"),
        offset_y=f.get("offset_y"),
        zoom_level=f.get("zoom_level"),
    )


def parse_selection_state(reader: MemoryReader, offsets: OffsetsConfig, game_data_base: int) -> SelectionState:
    """读取当前悬停/城池菜单选中的城池 index。

    优先使用 offsets 里显式配置的 `selection.selected_city_index`；该字段在
    生产 offsets 中仍是 unknown，于是回退到 2026-10-23 通过纯悬停 A/B 验证的
    `selection_reader`（`DAT_096a58f0+0x64` -> 城市对象 -> index）。两条路径
    都读不到时返回 `None`，不猜测默认值。
    """
    f = read_struct_fields(reader, offsets, game_data_base, "selection")
    configured = f.get("selected_city_index")
    if configured is not None:
        return SelectionState(selected_city_index=configured)

    selected = read_selected_city(reader, offsets, game_data_base)
    if selected is not None:
        return SelectionState(selected_city_index=selected.city_index)
    return SelectionState(selected_city_index=None)
