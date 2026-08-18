"""地图格子坐标 -> 客户区屏幕坐标的换算。

依赖两类目前都是 unknown/未测量的输入：
- CameraState（execution_state.py，从内存读，见 offsets/pk_1.1_cn.json 的
  camera struct，M3 阶段仍是 unknown）
- ui_layout 里的 map_viewport 元素（M3 阶段完全没有真实截图测量数据，
  见 ui_layout/pk_1.1_cn.json）

换算公式本身是这次新写的代码逻辑（不是从任何资料里抄来的"事实"），按最简单
的"正交网格 + 统一缩放"假设实现：

    client_x = viewport.x + (tile.x - camera.offset_x) * viewport.tile_width * zoom_scale
    client_y = viewport.y + (tile.y - camera.offset_y) * viewport.tile_height * zoom_scale
    zoom_scale = camera.zoom_level / ZOOM_LEVEL_DENOMINATOR

这个公式尚未经真实游戏验证，包含至少以下未经确认的假设，已在
docs/execution_research.md 和提交报告"设计取舍"一节列出，需要你在游戏可运行
后帮忙确认或修正：
1. 地图是正交网格而不是错位的菱形/六边形网格（三国志11地图观感上更接近
   菱形网格，如果实际如此，这个公式需要换成菱形坐标变换）。
2. zoom_level 是一个可以线性换算成缩放比例的整数（比如 100=100%），
   而不是索引进一张预设缩放表。
3. camera.offset_x/offset_y 的单位是"格子"而不是"像素"。
任何一条假设错了，这个函数算出来的屏幕坐标都会是错的——但错误会在执行层
"点击后轮询选中状态超时"这一步被观察到并触发归位重试，不会静默产生一个
看起来成功、实际点错地方的结果。
"""
from __future__ import annotations

from dataclasses import dataclass

from .execution_state import CameraState
from .ui_layout import UIElement

ZOOM_LEVEL_DENOMINATOR = 100


@dataclass(frozen=True)
class TileCoord:
    x: int
    y: int


@dataclass(frozen=True)
class ScreenPoint:
    x: int
    y: int


class MapProjectionError(Exception):
    """无法完成地图坐标换算——摄像机字段或地图视口配置仍是 unknown/未测量。"""


def project_tile_to_client(
    tile: TileCoord, camera: CameraState, viewport: UIElement
) -> ScreenPoint | None:
    """把地图格子坐标换算成客户区坐标。

    返回 None 表示算出来的坐标落在 viewport 矩形之外（调用方需要先滚动地图，
    见 execution.py 的 _reveal()）。camera 任一字段是 None，或者 viewport 没有
    tile_width/tile_height 时，直接抛 MapProjectionError——不猜测默认摄像机
    位置（比如"假设摄像机在原点"），那同样是编数据。
    """
    if camera.offset_x is None or camera.offset_y is None or camera.zoom_level is None:
        raise MapProjectionError(
            "无法换算地图坐标：camera.offset_x/offset_y/zoom_level 至少有一项是 unknown "
            "(见 offsets 文件 camera struct 和 docs/execution_research.md)。在这些内存"
            "字段被定位之前，地图点击这条链路无法在真实游戏上使用。"
        )
    viewport.require_known()
    if viewport.tile_width is None or viewport.tile_height is None:
        raise MapProjectionError(
            f"无法换算地图坐标：ui_layout 元素 {viewport.name!r} 没有 "
            f"tile_width/tile_height，需要实测游戏地图每格的像素尺寸。"
        )
    if viewport.width is None or viewport.height is None:
        raise MapProjectionError(
            f"无法判断目标是否在视野内：ui_layout 元素 {viewport.name!r} 没有 width/height。"
        )

    zoom_scale = camera.zoom_level / ZOOM_LEVEL_DENOMINATOR
    client_x = viewport.x + round((tile.x - camera.offset_x) * viewport.tile_width * zoom_scale)
    client_y = viewport.y + round((tile.y - camera.offset_y) * viewport.tile_height * zoom_scale)

    if not (viewport.x <= client_x < viewport.x + viewport.width):
        return None
    if not (viewport.y <= client_y < viewport.y + viewport.height):
        return None
    return ScreenPoint(client_x, client_y)
