"""内存读取抽象层。

两套实现：
- ProcessMemoryReader：通过 Win32 ReadProcessMemory 读取真实游戏进程（仅 Windows）。
- DumpMemoryReader：从离线内存 dump（一组 {地址: 字节} 区域）读取，供单元测试和
  将来的真实内存 dump 回放使用，不依赖真实进程、不依赖 Windows。

GameState 解析代码（perception.py）只依赖 MemoryReader 这个抽象接口，不关心
数据到底来自真实进程还是离线 dump。
"""
from __future__ import annotations

import json
import struct
import sys
from abc import ABC, abstractmethod
from base64 import b64decode
from dataclasses import dataclass
from pathlib import Path


class MemoryReadError(Exception):
    """读取内存失败（地址不可读、进程已退出、dump 里没有覆盖该地址等）。"""


class MemoryReader(ABC):
    """只读内存访问接口。地址一律是完整的绝对地址（由调用方用 module_base+RVA 算好再传入）。"""

    @property
    @abstractmethod
    def module_base(self) -> int:
        """主模块（游戏 exe）在当前地址空间里的加载基址。"""

    @abstractmethod
    def read_bytes(self, address: int, size: int) -> bytes:
        raise NotImplementedError

    def read_u8(self, address: int) -> int:
        return self.read_bytes(address, 1)[0]

    def read_i8(self, address: int) -> int:
        return struct.unpack_from("<b", self.read_bytes(address, 1))[0]

    def read_u16(self, address: int) -> int:
        return struct.unpack_from("<H", self.read_bytes(address, 2))[0]

    def read_i16(self, address: int) -> int:
        return struct.unpack_from("<h", self.read_bytes(address, 2))[0]

    def read_u32(self, address: int) -> int:
        return struct.unpack_from("<I", self.read_bytes(address, 4))[0]

    def read_i32(self, address: int) -> int:
        return struct.unpack_from("<i", self.read_bytes(address, 4))[0]

    def read_f32(self, address: int) -> float:
        return struct.unpack_from("<f", self.read_bytes(address, 4))[0]

    def read_fixed_str(self, address: int, size: int, encoding: str = "gbk") -> str:
        raw = self.read_bytes(address, size)
        raw = raw.split(b"\x00", 1)[0]
        return raw.decode(encoding, errors="replace")

    def read_i32_array(self, address: int, count: int) -> list[int]:
        raw = self.read_bytes(address, count * 4)
        return list(struct.unpack_from(f"<{count}i", raw))


# ---------------------------------------------------------------------------
# 离线 dump 实现（测试 / fixture 用）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Region:
    start: int
    data: bytes

    @property
    def end(self) -> int:
        return self.start + len(self.data)


class DumpMemoryReader(MemoryReader):
    """从一组内存区域（地址 -> 字节）里读取数据，不要求区域连续。

    dump 文件格式（JSON）：
        {
          "module_base": "0x00400000",
          "regions": [
            {"address": "0x07201958", "data_base64": "..."},
            ...
          ]
        }

    这是本项目自定义的最简单可用格式，专门为离线单元测试 fixture 设计。
    等拿到真实进程的内存 dump 后，可以再写一个转换脚本把常见 dump 格式
    （比如完整进程内存镜像）转换成这个格式，或者直接扩展 MemoryReader
    支持连续大块 dump ——这里不预先做，等真的需要时再做。
    """

    def __init__(self, regions: dict[int, bytes], module_base: int):
        self._regions = [_Region(addr, data) for addr, data in sorted(regions.items())]
        self._module_base = module_base

    @property
    def module_base(self) -> int:
        return self._module_base

    def read_bytes(self, address: int, size: int) -> bytes:
        end = address + size
        for region in self._regions:
            if region.start <= address and end <= region.end:
                start_off = address - region.start
                return region.data[start_off:start_off + size]
        raise MemoryReadError(
            f"dump 里没有覆盖地址范围 [0x{address:X}, 0x{end:X})，"
            f"已加载区域: {[(hex(r.start), hex(r.end)) for r in self._regions]}"
        )

    @classmethod
    def from_json_file(cls, path: str | Path) -> "DumpMemoryReader":
        # utf-8-sig：Windows 上不少工具（包括 PowerShell 的 File.WriteAllText(...,
        # Encoding.UTF8)）会给 UTF-8 文件加 BOM，这里做兼容，有没有 BOM 都能读。
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        module_base = int(data["module_base"], 16)
        regions = {}
        for region in data["regions"]:
            addr = int(region["address"], 16)
            regions[addr] = b64decode(region["data_base64"])
        return cls(regions, module_base)


# ---------------------------------------------------------------------------
# 真实 Windows 进程实现
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _psapi = ctypes.WinDLL("psapi", use_last_error=True)

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010

    class _MODULEINFO(ctypes.Structure):
        _fields_ = [
            ("lpBaseOfDll", ctypes.c_void_p),
            ("SizeOfImage", wintypes.DWORD),
            ("EntryPoint", ctypes.c_void_p),
        ]

    def _enum_pids() -> list[int]:
        arr_size = 1024
        while True:
            pids = (wintypes.DWORD * arr_size)()
            bytes_returned = wintypes.DWORD()
            ok = _psapi.EnumProcesses(
                ctypes.byref(pids), ctypes.sizeof(pids), ctypes.byref(bytes_returned)
            )
            if not ok:
                raise MemoryReadError("EnumProcesses 调用失败")
            count = bytes_returned.value // ctypes.sizeof(wintypes.DWORD)
            if count < arr_size:
                return list(pids[:count])
            arr_size *= 2  # 缓冲区不够大，扩容重试

    def _open_process(pid: int) -> int:
        handle = _kernel32.OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
        )
        if not handle:
            raise MemoryReadError(
                f"OpenProcess(pid={pid}) 失败（可能权限不足，或进程已退出），"
                f"error={ctypes.get_last_error()}"
            )
        return handle

    def _get_process_image_name(handle: int) -> str | None:
        buf = ctypes.create_unicode_buffer(260)
        n = _psapi.GetModuleBaseNameW(handle, None, buf, 260)
        return buf.value if n else None

    def _get_main_module_base(handle: int) -> int:
        modules = (ctypes.c_void_p * 1)()
        needed = wintypes.DWORD()
        ok = _psapi.EnumProcessModules(
            handle, ctypes.byref(modules), ctypes.sizeof(modules), ctypes.byref(needed)
        )
        if not ok:
            raise MemoryReadError(f"EnumProcessModules 失败，error={ctypes.get_last_error()}")
        return modules[0] or 0

    def find_pid_by_process_name(process_name: str) -> int | None:
        """按可执行文件名（如 san11pk.exe，大小写不敏感）查找进程 PID。找不到返回 None。"""
        target = process_name.lower()
        for pid in _enum_pids():
            if pid == 0:
                continue
            try:
                handle = _open_process(pid)
            except MemoryReadError:
                continue
            try:
                name = _get_process_image_name(handle)
            finally:
                _kernel32.CloseHandle(handle)
            if name and name.lower() == target:
                return pid
        return None

    class ProcessMemoryReader(MemoryReader):
        """通过 ReadProcessMemory 读取真实游戏进程内存。"""

        def __init__(self, pid: int):
            self._pid = pid
            self._handle = _open_process(pid)
            self._module_base = _get_main_module_base(self._handle)

        @classmethod
        def attach_by_name(cls, process_name: str) -> "ProcessMemoryReader":
            pid = find_pid_by_process_name(process_name)
            if pid is None:
                raise MemoryReadError(f"没有找到名为 {process_name} 的进程，游戏是否已启动？")
            return cls(pid)

        @property
        def pid(self) -> int:
            return self._pid

        @property
        def module_base(self) -> int:
            return self._module_base

        def read_bytes(self, address: int, size: int) -> bytes:
            buf = ctypes.create_string_buffer(size)
            bytes_read = ctypes.c_size_t()
            ok = _kernel32.ReadProcessMemory(
                self._handle, ctypes.c_void_p(address), buf, size, ctypes.byref(bytes_read)
            )
            if not ok or bytes_read.value != size:
                raise MemoryReadError(
                    f"ReadProcessMemory(0x{address:X}, {size}) 失败，"
                    f"error={ctypes.get_last_error()}"
                )
            return buf.raw

        def close(self) -> None:
            if self._handle:
                _kernel32.CloseHandle(self._handle)
                self._handle = 0

        def __enter__(self) -> "ProcessMemoryReader":
            return self

        def __exit__(self, *exc_info) -> None:
            self.close()

else:  # pragma: no cover - 非 Windows 平台上这些符号仅用于类型引用/测试跳过

    def find_pid_by_process_name(process_name: str) -> int | None:
        raise NotImplementedError("ProcessMemoryReader 仅支持 Windows")

    class ProcessMemoryReader(MemoryReader):  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise NotImplementedError("ProcessMemoryReader 仅支持 Windows")
