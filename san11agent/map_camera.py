"""地图坐标到 D3D9 屏幕坐标的候选链路。

这里刻意分成两层：

- ``MapCalibration``：城市对象 ``+0x1C/+0x20`` 的 (map_x, map_y) 到世界
  坐标 (world_x, 0, world_z) 的仿射。系数来自 2026-10-23 的 4K 四城静止
  相机验证（平原/小沛/濮陽/陳留），仍属**候选**，不是生产 offsets 的一部分。
- ``CameraMatrices``：D3D9 的 view/projection 矩阵。矩阵必须由调用方从
  trace/运行时取得；本模块不假装知道它们的地址。

D3D9 固定功能使用行向量约定：``clip = world_row * view * projection``。
矩阵按 4 行、每行 4 个 float 传入。该模块不发送输入、不写内存。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


Matrix4 = Sequence[Sequence[float]]


@dataclass(frozen=True)
class MapCalibration:
    """world_x = xx*map_x + xy*map_y + x0, world_z = zx*map_x + zy*map_y + z0."""

    xx: float
    xy: float
    x0: float
    zx: float
    zy: float
    z0: float

    def map_to_world(self, map_x: float, map_y: float) -> tuple[float, float, float]:
        """Return ``(world_x, 0.0, world_z)``; the map plane is y=0."""
        return (
            self.xx * map_x + self.xy * map_y + self.x0,
            0.0,
            self.zx * map_x + self.zy * map_y + self.z0,
        )


# 4K 四城验证结果。不要把这里的系数当成所有分辨率/所有视角的最终事实：
# 它只说明“在这组地图/相机数据下，城市坐标经过约 20 倍缩放和少量旋转后
# 能重投影到正确屏幕位置”。换地图/换相机后仍应重新验证。
DEFAULT_MAP_CALIBRATION = MapCalibration(
    xx=19.886052141042683,
    xy=0.2369451393790314,
    x0=565.1875792680657,
    zx=0.27223148156167554,
    zy=20.20238763173404,
    z0=520.4224581284507,
)


@dataclass(frozen=True)
class CameraMatrices:
    view: Matrix4
    projection: Matrix4
    screen_width: int
    screen_height: int


def _validate_matrix(matrix: Matrix4, name: str) -> list[list[float]]:
    rows = [list(row) for row in matrix]
    if len(rows) != 4 or any(len(row) != 4 for row in rows):
        raise ValueError(f"{name} must be a 4x4 matrix")
    return [[float(value) for value in row] for row in rows]


def _multiply_row_vector(vector: Sequence[float], matrix: Matrix4) -> list[float]:
    return [
        sum(vector[i] * matrix[i][j] for i in range(4))
        for j in range(4)
    ]


def project_world(
    world: Sequence[float],
    camera: CameraMatrices,
) -> tuple[float, float]:
    """Project a world-space point with a D3D9 view/projection pair.

    Returns client-space ``(x, y)``. Raises ``ValueError`` for a degenerate
    homogeneous coordinate or invalid screen size.
    """
    if len(world) != 3:
        raise ValueError("world must have exactly 3 components")
    if camera.screen_width <= 0 or camera.screen_height <= 0:
        raise ValueError("screen dimensions must be positive")

    view = _validate_matrix(camera.view, "view")
    projection = _validate_matrix(camera.projection, "projection")
    point = [float(world[0]), float(world[1]), float(world[2]), 1.0]

    view_point = _multiply_row_vector(point, view)
    clip = _multiply_row_vector(view_point, projection)
    if abs(clip[3]) < 1e-12:
        raise ValueError("degenerate projection (w is zero)")

    ndc_x = clip[0] / clip[3]
    ndc_y = clip[1] / clip[3]
    client_x = (ndc_x * 0.5 + 0.5) * camera.screen_width
    client_y = (1.0 - (ndc_y * 0.5 + 0.5)) * camera.screen_height
    return client_x, client_y


def project_map_point(
    map_x: float,
    map_y: float,
    camera: CameraMatrices,
    calibration: MapCalibration = DEFAULT_MAP_CALIBRATION,
) -> tuple[float, float]:
    """Convenience wrapper: map cell -> world -> client screen."""
    world = calibration.map_to_world(map_x, map_y)
    return project_world(world, camera)
