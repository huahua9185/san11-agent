"""全进程内存扫描：跟 mem_dump.py/mem_diff.py（辅助工具一）配合使用的辅助工具三。

背景：验证清单阶段5要定位的 `global.phase`/`camera.*`/`selection.selected_city_index`
三组字段，2026-08-19 用"在 GAME_DATA_BASE 附近抓一小段区域做前后对比"的方法
（`mem_snapshot.py`/`mem_diff.py`）连续测了两次（菜单开合、拖动地图），
`GAME_DATA_BASE+0x0` 起 0x300 字节范围内**一个字节都没变化**——见
docs/offset_research.md 相关记录。这说明这几个字段大概率不在这个"游戏世界
数据"结构体附近，而是在进程里另一块完全独立的内存（比如引擎自己维护的
UI/摄像机管理器对象），需要真正意义上的"全内存前后对比"才能定位，不能再
靠"猜一个小范围"碰运气。

设计取舍（跟 mem_dump.py/mem_diff.py 保持同一套原则，找不到的不猜）：

1. **默认只扫 `MEM_PRIVATE` 类型的已提交(`MEM_COMMIT`)、可读区域**——这是
   典型的堆/栈动态分配内存，UI 状态这类"运行时对象的字段"更可能长在这里，
   而不是 `MEM_IMAGE`（exe/dll 的静态镜像，GAME_DATA_BASE 本身就属于这类，
   已经证明不含这几个字段）或 `MEM_MAPPED`（内存映射文件）。`--include-image`
   可以选择性地把镜像区域也扫进来，但那会把总扫描量从"进程私有堆的实际
   工作集"（通常几十到一百多MB量级）拉高到"整个PE镜像"（这个游戏实测
   `SizeOfImage` 高达约153MB，见 docs/offset_research.md 7.3节），显著变慢，
   默认不开。
2. **单个区域超过 `max_region_size`（默认64MB）会被跳过**，避免个别巨大
   的私有内存块（比如某些游戏引擎的大块预分配缓冲区）拖垮整次扫描耗时。
3. **对比算法用"按块跳过"策略**（`find_changed_spans`）：先按 `block_size`
   （默认4096字节）整块比较，块内容完全相同就跳过整块（利用 Python bytes
   比较是 C 层实现，比逐字节 Python 循环快得多），只有块内容不同时才逐字节
   定位精确的变化区间。这是纯算法层面的优化，不改变"能找到哪些变化"这个
   结果，只是让"游戏进程里大部分内存其实没变"这个常见情况处理得更快。
4. **完整快照落盘用 gzip+pickle**（都是标准库，符合本项目"运行时零第三方
   依赖"的一贯做法），不是 mem_dump.py 那种 JSON+base64 格式——量级不同：
   `mem_dump.py` 抓的是几百字节到几KB的小区域，JSON 可读性优先；这里可能是
   几十到上百MB，JSON+base64（体积再膨胀33%）不现实，gzip 对内存里大量
   重复/零字节的区域压缩效果通常也不错。

跟 GAME_DATA_BASE 锚点解析完全独立：这里的地址都是运行时 `VirtualQueryEx`
枚举出来的，不依赖、也不会覆盖已知的 offsets/ui_layout 文件里任何字段。
"""
from __future__ import annotations

import gzip
import pickle
import sys
from dataclasses import dataclass
from pathlib import Path

from .mem_diff import interpret_bytes

# --- Windows 内存区域常量（跟 VirtualQueryEx 返回的 MEMORY_BASIC_INFORMATION 对应）---

MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000
MEM_MAPPED = 0x40000
MEM_IMAGE = 0x1000000

PAGE_GUARD = 0x100
_READABLE_BASE_PROTECT = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}  # RO/RW/WC/ER/ERW/EWC，不含 NOACCESS

DEFAULT_MAX_REGION_SIZE = 64 * 1024 * 1024
DEFAULT_BLOCK_SIZE = 4096


class MemScanError(Exception):
    """全内存扫描相关的错误（枚举/读取失败、快照文件格式不对等）。"""


@dataclass(frozen=True)
class RegionInfo:
    base_address: int
    region_size: int
    state: int
    protect: int
    type: int


# --- 纯逻辑部分：不依赖 ctypes/Windows，可在任何平台离线测试 -----------------


def is_readable_protect(protect: int) -> bool:
    """protect 是否允许读取——排除 PAGE_GUARD 修饰位和 PAGE_NOACCESS。"""
    if protect & PAGE_GUARD:
        return False
    return (protect & 0xFF) in _READABLE_BASE_PROTECT


def should_scan_region(
    region: RegionInfo,
    *,
    only_private: bool = True,
    max_region_size: int = DEFAULT_MAX_REGION_SIZE,
) -> bool:
    """判断一个枚举出来的内存区域值不值得抓取——已提交、可读、类型/大小符合预期。"""
    if region.state != MEM_COMMIT:
        return False
    if not is_readable_protect(region.protect):
        return False
    if only_private and region.type != MEM_PRIVATE:
        return False
    if region.region_size <= 0 or region.region_size > max_region_size:
        return False
    return True


def find_changed_spans(
    base_address: int, old: bytes, new: bytes, *, block_size: int = DEFAULT_BLOCK_SIZE
) -> list[tuple[int, bytes, bytes]]:
    """对比两段等长字节，找出全部变化的连续区间，返回 (绝对地址, 旧字节, 新字节) 列表。

    "按块跳过"：先按 block_size 整块比较（`bytes.__eq__` 是 C 层实现，比逐字节
    Python 循环快得多），块内容相同直接跳过；只有块不同才逐字节定位精确边界。
    结果跟"从头到尾逐字节比较"完全等价，只是常见的"大部分内存没变"场景下快
    得多——这是全内存扫描能在交互式会话里可用的关键，见模块文档第3条。
    """
    if len(old) != len(new):
        raise MemScanError(f"find_changed_spans 要求 old/new 等长，收到 {len(old)} vs {len(new)}")
    spans: list[tuple[int, bytes, bytes]] = []
    n = len(old)
    i = 0
    while i < n:
        j = min(i + block_size, n)
        if old[i:j] != new[i:j]:
            k = i
            while k < j:
                if old[k] != new[k]:
                    m = k + 1
                    while m < j and old[m] != new[m]:
                        m += 1
                    spans.append((base_address + k, old[k:m], new[k:m]))
                    k = m
                else:
                    k += 1
        i = j
    return spans


@dataclass(frozen=True)
class FullDiffReport:
    changed_spans: list[tuple[int, bytes, bytes]]
    matched_region_count: int
    resized_regions: list[tuple[int, int, int]]  # (地址, 旧大小, 新大小)——同一地址但区域变了大小，跳过精细diff
    only_in_old: list[tuple[int, int]]  # (地址, 大小)——旧快照有、新快照没有的区域（比如内存被释放）
    only_in_new: list[tuple[int, int]]  # 反过来——新分配的区域，UI打开时如果确实新分配了对象，这里可能有信号


def diff_full_snapshots(
    old: dict[int, bytes], new: dict[int, bytes], *, block_size: int = DEFAULT_BLOCK_SIZE
) -> FullDiffReport:
    """对比两份全内存快照（地址 -> 字节的 dict），只对"两份快照里地址和大小都
    匹配"的区域做精细字节级 diff；地址只在一边出现、或同一地址两边大小不同
    的区域，单独列出来（不硬凑字节对比，那样对比不出有意义的结果）。
    """
    old_keys, new_keys = set(old), set(new)
    matched = old_keys & new_keys

    changed_spans: list[tuple[int, bytes, bytes]] = []
    resized: list[tuple[int, int, int]] = []
    matched_count = 0
    for addr in sorted(matched):
        old_data, new_data = old[addr], new[addr]
        if len(old_data) != len(new_data):
            resized.append((addr, len(old_data), len(new_data)))
            continue
        matched_count += 1
        changed_spans.extend(find_changed_spans(addr, old_data, new_data, block_size=block_size))

    only_in_old = sorted((a, len(old[a])) for a in (old_keys - new_keys))
    only_in_new = sorted((a, len(new[a])) for a in (new_keys - old_keys))
    return FullDiffReport(changed_spans, matched_count, resized, only_in_old, only_in_new)


def format_full_diff_report(report: FullDiffReport, *, min_bytes: int = 1, limit: int | None = None) -> str:
    lines = [
        f"匹配区域数（参与逐字节对比）: {report.matched_region_count}",
        f"大小变化的区域（跳过精细diff）: {len(report.resized_regions)}",
        f"仅在旧快照存在的区域: {len(report.only_in_old)}",
        f"仅在新快照存在的区域: {len(report.only_in_new)}",
        "",
    ]
    filtered = [s for s in report.changed_spans if len(s[1]) >= min_bytes]
    filtered.sort(key=lambda s: s[0])
    lines.append(f"变化的字节区间: {len(filtered)} 处（--min-bytes={min_bytes} 过滤后）")
    shown = filtered if limit is None else filtered[:limit]
    for addr, old_data, new_data in shown:
        lines.append(f"0x{addr:08X}  {len(old_data)} 字节变化")
        lines.append(f"    旧: {interpret_bytes(old_data)}")
        lines.append(f"    新: {interpret_bytes(new_data)}")
    if limit is not None and len(filtered) > limit:
        lines.append(f"... 还有 {len(filtered) - limit} 处被 --limit 截断，未显示")
    if report.only_in_new:
        lines.append("")
        lines.append("仅在新快照里出现的区域（可能是操作触发的新内存分配）：")
        for addr, size in report.only_in_new[: (limit or len(report.only_in_new))]:
            lines.append(f"  0x{addr:08X} ~ 0x{addr + size:08X} ({size} 字节)")
    return "\n".join(lines)


def find_toggled_spans(
    before: dict[int, bytes], during: dict[int, bytes], after: dict[int, bytes]
) -> list[tuple[int, bytes, bytes]]:
    """找"操作前"和"操作后"值相同、但"操作中"不同的字节区间——即"变了又变
    回来"的信号，返回 (地址, before/after共同值, during时的值) 列表。

    为什么需要这个：全内存扫描量级下（本项目实测约200MB、298个区域），仅仅
    对比两份快照会把大量跟本次操作无关的背景噪音（帧计数器、动画、音效
    缓冲区等每隔几秒就自然变化的字节）也当成候选，见 docs/execution_research.md
    第7节实测记录（idle 状态下几秒内就有4000+处字节变化）。"去了又回来"这个
    条件能排掉单调递增/持续变化的噪音（那些字节不会在操作结束后精确变回
    操作前的值），把候选范围压缩到"这次操作特有的状态切换"，是定位
    global.phase 这类"离散状态标志位"更有针对性的方法，比 mem_diff.py 的
    cross_compare()（只看"两次过渡是否都变了"，不检查是否变回原值）更严格。

    只对三份快照里"地址和大小都匹配"的区域生效，跟 diff_full_snapshots() 一致
    ——地址/大小对不上的区域没法做这种逐字节比较，直接跳过不参与。
    """
    matched = set(before) & set(during) & set(after)
    results: list[tuple[int, bytes, bytes]] = []
    for addr in sorted(matched):
        b, d, a = before[addr], during[addr], after[addr]
        if len(b) != len(d) or len(d) != len(a):
            continue
        if b == a and b != d:
            results.extend(find_changed_spans(addr, b, d))
    return results


def format_toggled_spans(spans: list[tuple[int, bytes, bytes]], *, min_bytes: int = 1, limit: int | None = None) -> str:
    filtered = [s for s in spans if len(s[1]) >= min_bytes]
    filtered.sort(key=lambda s: s[0])
    lines = [f"'操作前后相同、操作中不同'的字节区间: {len(filtered)} 处（--min-bytes={min_bytes} 过滤后）"]
    shown = filtered if limit is None else filtered[:limit]
    for addr, stable_val, during_val in shown:
        lines.append(f"0x{addr:08X}  {len(stable_val)} 字节")
        lines.append(f"    操作前/后(稳定): {interpret_bytes(stable_val)}")
        lines.append(f"    操作中: {interpret_bytes(during_val)}")
    if limit is not None and len(filtered) > limit:
        lines.append(f"... 还有 {len(filtered) - limit} 处被 --limit 截断，未显示")
    return "\n".join(lines)


def save_full_snapshot(
    path: str | Path, module_base: int, region_bytes: dict[int, bytes], *, label: str | None = None
) -> None:
    payload = {"module_base": module_base, "label": label, "regions": region_bytes}
    with gzip.open(path, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)


def load_full_snapshot(path: str | Path) -> dict:
    try:
        with gzip.open(path, "rb") as f:
            return pickle.load(f)
    except (OSError, pickle.UnpicklingError) as exc:
        raise MemScanError(f"加载全内存快照 {path!r} 失败: {exc}") from exc


# --- Windows 真实实现：枚举 + 抓取 -------------------------------------------

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    from .memory import MemoryReadError, ProcessMemoryReader

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _MEMORY_BASIC_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BaseAddress", ctypes.c_void_p),
            ("AllocationBase", ctypes.c_void_p),
            ("AllocationProtect", wintypes.DWORD),
            ("RegionSize", ctypes.c_size_t),
            ("State", wintypes.DWORD),
            ("Protect", wintypes.DWORD),
            ("Type", wintypes.DWORD),
        ]

    _kernel32.VirtualQueryEx.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(_MEMORY_BASIC_INFORMATION), ctypes.c_size_t,
    ]
    _kernel32.VirtualQueryEx.restype = ctypes.c_size_t

    def enumerate_regions(
        reader: ProcessMemoryReader, *, start: int = 0, end: int = 0x7FFF0000
    ) -> list[RegionInfo]:
        """从 start 到 end 依次调用 VirtualQueryEx 枚举目标进程的内存区域。

        end 默认 0x7FFF0000——32位进程用户态地址空间的常见上限（不满
        0x80000000 是刻意留一点余量，避免在地址空间边界处的整数溢出/查询
        行为不确定），San11WPK.exe 是32位进程（见 docs/offset_research.md
        7.1节 PE ImageBase 0x00400000），不需要扫到更高地址。
        """
        handle = reader.raw_handle
        regions: list[RegionInfo] = []
        addr = start
        mbi = _MEMORY_BASIC_INFORMATION()
        while addr < end:
            ret = _kernel32.VirtualQueryEx(handle, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi))
            if ret == 0:
                break  # 查询失败，通常表示到了可查询地址空间的末尾
            base = mbi.BaseAddress or addr
            size = mbi.RegionSize
            if size <= 0:
                break  # 防止在异常返回下死循环
            regions.append(RegionInfo(base_address=base, region_size=size, state=mbi.State, protect=mbi.Protect, type=mbi.Type))
            addr = base + size
        return regions

    def capture_full_snapshot(reader: ProcessMemoryReader, regions: list[RegionInfo]) -> dict[int, bytes]:
        """按 regions 逐个读取字节。个别区域枚举到了但读取瞬间已失效（比如刚好
        被释放）会被静默跳过，不算整体失败——这跟枚举时看到的状态本来就可能
        有微小的时间差，是这类"遍历运行中进程内存"操作的正常现象。
        """
        result: dict[int, bytes] = {}
        for region in regions:
            try:
                result[region.base_address] = reader.read_bytes(region.base_address, region.region_size)
            except MemoryReadError:
                continue
        return result

else:  # pragma: no cover - 非 Windows 平台仅用于类型引用/测试跳过

    def enumerate_regions(reader, *, start: int = 0, end: int = 0x7FFF0000) -> list[RegionInfo]:
        raise NotImplementedError("enumerate_regions 仅支持 Windows")

    def capture_full_snapshot(reader, regions: list[RegionInfo]) -> dict[int, bytes]:
        raise NotImplementedError("capture_full_snapshot 仅支持 Windows")
