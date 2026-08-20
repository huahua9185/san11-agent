"""地图格子坐标 -> 客户区屏幕坐标的换算。

依赖两类输入：
- CameraState（execution_state.py，从内存读，见 offsets/pk_1.1_cn.json 的
  camera struct，`offset_x`/`offset_y`/`zoom_level` 三个字段目前仍然
  unknown——还没在内存里定位到，见 docs/execution_research.md 7.9/7.11节
  多次尝试的记录）
- ui_layout 里的 map_viewport 元素：`x`/`y`/`width`/`height`（视口矩形）
  和 `tile_width`/`tile_height`（单个格子菱形的水平/垂直对角线像素长度）
  2026-08-19 已经用 GetCursorPos+ScreenToClient 现场测量（471,12,1772,1542
  和 184x135），见 ui_layout/pk_1.1_cn.json 和 docs/execution_research.md
  7.10节——但只测了1个视口、1个格子，样本量很小。

2026-08-19 之前公式一直是"正交网格 + 统一缩放"，用户已经确认地图默认
渲染是**等距 (isometric) 投影**、格子在屏幕上是菱形不是正方形（旋转视角
能让格子变成正方形，说明底层坐标系仍是正交的，只是默认相机角度把它渲染
成菱形，见 docs/execution_research.md 3.1/7.6节）。现在换成等距变换：

    half_w = viewport.tile_width / 2
    half_h = viewport.tile_height / 2
    dx = tile.x - camera.offset_x
    dy = tile.y - camera.offset_y
    center_x = viewport.x + viewport.width / 2
    center_y = viewport.y + viewport.height / 2
    client_x = center_x + (dx - dy) * half_w * zoom_scale
    client_y = center_y + (dx + dy) * half_h * zoom_scale
    zoom_scale = camera.zoom_level / ZOOM_LEVEL_DENOMINATOR

这个公式尚未经真实游戏验证，包含至少以下未经确认的假设：
1. **`camera.offset_x/offset_y` 对应的格子，投影到视口的正中心**——而不是
   视口左上角或其他参考点。这是这次新引入的假设（之前正交版本假设的是
   "映射到视口左上角"），改成视口中心是因为"摄像机偏移=当前屏幕中心对着
   哪个格子"是绝大多数游戏摄像机的通行约定，比左上角更符合直觉，但两种
   假设目前都没有真实数据能验证，camera 字段本身还没定位到，无法回放
   验证。
2. **tile.x 增大往右下移动、tile.y 增大往左下移动（标准菱形网格的对角线
   方向约定）**——这次的像素测量只量了单个格子自己的四个顶点（上下顶点
   x坐标一致、左右顶点y坐标一致，证实了"这是一个菱形"），**没有测量
   相邻两个格子的中心点来验证这个方向约定**，所以"哪个方向对应+x、哪个
   方向对应+y"仍然是猜测，不是实测结论。
3. zoom_level 是一个可以线性换算成缩放比例的整数（比如 100=100%），
   而不是索引进一张预设缩放表。
4. camera.offset_x/offset_y 的单位是"格子"而不是"像素"。
5. `viewport.tile_width`/`tile_height` 这两个值本身只测了一个格子、一次
   测量（见 ui_layout/pk_1.1_cn.json 对应 note），是否所有格子/所有地图
   位置都是这个尺寸未经验证（等距投影下理论上应该处处一致，但没有交叉
   测量确认）。
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
    half_w = viewport.tile_width / 2
    half_h = viewport.tile_height / 2
    dx = tile.x - camera.offset_x
    dy = tile.y - camera.offset_y
    center_x = viewport.x + viewport.width / 2
    center_y = viewport.y + viewport.height / 2
    client_x = round(center_x + (dx - dy) * half_w * zoom_scale)
    client_y = round(center_y + (dx + dy) * half_h * zoom_scale)

    if not (viewport.x <= client_x < viewport.x + viewport.width):
        return None
    if not (viewport.y <= client_y < viewport.y + viewport.height):
        return None
    return ScreenPoint(client_x, client_y)
