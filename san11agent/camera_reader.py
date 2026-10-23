"""读取 d3d9 代理 DLL 暴露的实时 view/projection 矩阵。

代理 `tools/d3d9_camera_proxy/d3d9_proxy.cpp` 在游戏进程内创建命名共享内存
``Local\\San11Camera``，结构固定为：

```text
LONG   version
DWORD  view_sequence
DWORD  projection_sequence
float  view[16]
float  projection[16]
```

本模块只读该映射；不发送输入、不写游戏内存。共享内存不存在时抛
``CameraReadError``，调用方必须显式处理，不能拿全零矩阵继续算。
"""
from __future__ import annotations

import ctypes
import struct
import sys
from dataclasses import dataclass

from .map_camera import CameraMatrices


MAPPING_NAME = r"Local\San11Camera"
SHARED_LAYOUT = struct.Struct("<iII16f16f")
SHARED_SIZE = SHARED_LAYOUT.size  # 140


class CameraReadError(RuntimeError):
    """共享内存不存在、尺寸不对或内容不合法。"""


@dataclass(frozen=True)
class CameraSnapshot:
    version: int
    view_sequence: int
    projection_sequence: int
    view: tuple[tuple[float, float, float, float], ...]
    projection: tuple[tuple[float, float, float, float], ...]

    def as_camera(self, screen_width: int, screen_height: int) -> CameraMatrices:
        return CameraMatrices(
            view=self.view,
            projection=self.projection,
            screen_width=screen_width,
            screen_height=screen_height,
        )


def _rows(flat: tuple[float, ...]) -> tuple[tuple[float, float, float, float], ...]:
    return tuple(tuple(flat[i * 4:(i + 1) * 4]) for i in range(4))


def parse_camera_shared(data: bytes) -> CameraSnapshot:
    """Parse the 140-byte shared-memory payload (pure, testable)."""
    if len(data) < SHARED_SIZE:
        raise CameraReadError(f"camera shared memory too short: {len(data)} < {SHARED_SIZE}")
    values = SHARED_LAYOUT.unpack_from(data, 0)
    version, view_sequence, projection_sequence = values[:3]
    flat = values[3:]
    view = _rows(flat[:16])
    projection = _rows(flat[16:32])
    if version < 0:
        raise CameraReadError("negative camera version")
    if not any(value != 0.0 for row in view for value in row):
        raise CameraReadError("camera view matrix is all zero")
    if not any(value != 0.0 for row in projection for value in row):
        raise CameraReadError("camera projection matrix is all zero")
    return CameraSnapshot(
        version=version,
        view_sequence=view_sequence,
        projection_sequence=projection_sequence,
        view=view,
        projection=projection,
    )


def read_camera_mapping() -> CameraSnapshot:
    """Read the live shared-memory snapshot; Windows-only."""
    if sys.platform != "win32":
        raise CameraReadError("camera shared memory is Windows-only")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenFileMappingW.argtypes = [
        ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p,
    ]
    kernel32.OpenFileMappingW.restype = ctypes.c_void_p
    kernel32.MapViewOfFile.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t,
    ]
    kernel32.MapViewOfFile.restype = ctypes.c_void_p
    kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    kernel32.UnmapViewOfFile.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    handle = kernel32.OpenFileMappingW(0x0004, 0, MAPPING_NAME)  # FILE_MAP_READ
    if not handle:
        raise CameraReadError(
            f"cannot open {MAPPING_NAME}: Win32 {ctypes.get_last_error()}"
        )
    try:
        pointer = kernel32.MapViewOfFile(handle, 0x0004, 0, 0, SHARED_SIZE)
        if not pointer:
            raise CameraReadError(
                f"cannot map {MAPPING_NAME}: Win32 {ctypes.get_last_error()}"
            )
        try:
            data = ctypes.string_at(pointer, SHARED_SIZE)
        finally:
            kernel32.UnmapViewOfFile(pointer)
    finally:
        kernel32.CloseHandle(handle)
    return parse_camera_shared(data)
