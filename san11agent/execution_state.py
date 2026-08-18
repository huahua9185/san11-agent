"""M3 执行层需要、但不属于 M1 GameState 概念范围的两类"当前 UI 状态"：

- CameraState：决定地图渲染的摄像机偏移/缩放，map_projection.py 用它把地图
  格子坐标反算成屏幕坐标。
- SelectionState：当前被选中的城池，execution.py 用它轮询确认"点击城池"这个
  动作是否生效。

两者都复用 perception.py 的 read_struct_fields()——同一套"按 offsets 字段表
读内存"的机制，只是这两个 struct 是单例（count=1），不是数组。这两组字段
目前预计都是 unknown（M3 阶段没有专门为它们做内存研究，见
docs/execution_research.md），读取时和 M1/M2 一致：unknown 字段安静返回 None，
不报错、不编数据，调用方（map_projection.py / execution.py）自己决定"这个
字段是 None 的时候该怎么办"（通常是显式报错，拒绝在没有依据的情况下继续）。
"""
from __future__ import annotations

from dataclasses import dataclass

from .memory import MemoryReader
from .offsets import OffsetsConfig
from .perception import read_struct_fields


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
    f = read_struct_fields(reader, offsets, game_data_base, "selection")
    return SelectionState(selected_city_index=f.get("selected_city_index"))
