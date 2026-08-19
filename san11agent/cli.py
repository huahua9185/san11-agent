"""M1 命令行工具：打印一份局势快照。

用法：
    # 离线 dump / fixture 模式（不需要游戏在跑）
    python -m san11agent.cli snapshot --offsets offsets/pk_1.1_cn.json --dump path/to/dump.json

    # 真实进程模式（2026-08-18 起 anchor 已能解析，见 offsets/pk_1.1_cn.json）
    # 注意：实机确认的真实进程名是 San11WPK.exe（Steam 繁体中文版），不是 san11pk.exe
    python -m san11agent.cli snapshot --offsets offsets/pk_1.1_cn.json --process San11WPK.exe
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from .memory import DumpMemoryReader, MemoryReader
from .offsets import load_offsets
from .perception import AnchorResolutionError, ValidationError, parse_game_state


def _game_state_to_jsonable(state) -> dict:
    def convert(obj):
        # 故意不用 dataclasses.asdict()：它会一次性把整棵树递归拍平成普通
        # dict/list，导致下面手写的 bytes -> hex 转换永远碰不到已经被拍平、
        # 埋在深处字典里的 bytes 字段（比如武将的 base_stats）。自己按字段递归。
        if dataclasses.is_dataclass(obj):
            return {f.name: convert(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
        if isinstance(obj, bytes):
            return obj.hex()
        if isinstance(obj, list):
            return [convert(v) for v in obj]
        return obj

    return convert(state)


def _build_reader(args: argparse.Namespace) -> MemoryReader:
    if args.dump:
        return DumpMemoryReader.from_json_file(args.dump)
    if args.process:
        if sys.platform != "win32":
            raise SystemExit("真实进程模式只支持 Windows")
        from .memory import ProcessMemoryReader  # 延迟导入，非 Windows 平台上避免报错

        return ProcessMemoryReader.attach_by_name(args.process)
    raise SystemExit("必须指定 --dump 或 --process 之一")


def cmd_snapshot(args: argparse.Namespace) -> int:
    offsets = load_offsets(args.offsets)

    if args.process and not offsets.verified:
        print(
            f"[警告] offsets 文件 {args.offsets} 的 meta.verified=false，"
            f"从未在真实进程上验证过，读到的数据可能是错的。",
            file=sys.stderr,
        )

    try:
        reader = _build_reader(args)
    except Exception as exc:  # noqa: BLE001 - CLI 顶层，转成明确退出信息
        print(f"[错误] 无法建立内存读取通道: {exc}", file=sys.stderr)
        return 1

    try:
        state = parse_game_state(reader, offsets, validate=not args.no_validate)
    except AnchorResolutionError as exc:
        print(f"[错误] 无法解析 GAME_DATA_BASE 锚点: {exc}", file=sys.stderr)
        return 2
    except ValidationError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 3
    finally:
        close = getattr(reader, "close", None)
        if close:
            close()

    payload = _game_state_to_jsonable(state)
    if args.summary:
        _print_summary(state)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _print_summary(state) -> None:
    g = state.global_state
    print(f"剧本 {g.scenario_id} | 开局 {g.start_year}-{g.start_month}-{g.start_day} | 当前第 {g.current_xun} 旬")
    print(f"势力数: {len(state.factions)}  城池数: {len(state.cities)}  武将数: {len(state.generals)}  部队数: {len(state.troops)}")
    for city in state.cities[:5]:
        print(f"  城池[{city.index}] {city.name}: 兵力={city.troops}/{city.troop_capacity} 钱={city.gold} 粮={city.food}")
    if len(state.cities) > 5:
        print(f"  ... 其余 {len(state.cities) - 5} 座城池省略")


def _parse_int_set(raw: str | None) -> frozenset[int]:
    """把 "1,2,3" 这样的逗号分隔字符串解析成 frozenset[int]，空/None 时返回空集合。"""
    if not raw:
        return frozenset()
    return frozenset(int(x) for x in raw.split(",") if x.strip())


def _build_static_visibility(args: argparse.Namespace):
    """M2 命令行入口共用：拼一个 StaticVisibilitySource。

    2026-08-19 新增（M2/M4 接入 CLI）。为什么不是 UnresolvedVisibilitySource：
    真实进程场景下 `探明/视野/发现` 这三个问题的内存字段仍然 unknown（见
    docs/visibility_research.md），`UnresolvedVisibilitySource` 对任何非己方
    城池/部队/在野武将都会直接抛 `VisibilityUnknownError`——在真实存档里
    这几乎必然触发（几乎不可能所有非己方实体都恰好是己方）,会让这两个
    命令在真实进程下完全用不了。所以命令行默认改用 `StaticVisibilitySource`，
    三个集合不显式传就是空集合——即"除己方外，默认一律当作未探明/不可见/
    未发现"，这正是过滤器本身"默认不暴露"的既定保守策略，不是新引入的
    猜测，只是把它变成一个可以真正跑起来的默认值。想要开放某些已知已探明
    的城池/可见部队/已发现武将，用 `--explored-cities`/`--visible-troops`/
    `--discovered-generals` 显式传入。
    """
    from .visibility import StaticVisibilitySource

    return StaticVisibilitySource(
        args.player_faction_id,
        explored_city_indices=_parse_int_set(args.explored_cities),
        visible_troop_indices=_parse_int_set(args.visible_troops),
        discovered_general_indices=_parse_int_set(args.discovered_generals),
    )


def _parse_game_state_from_args(args: argparse.Namespace):
    offsets = load_offsets(args.offsets)
    if args.process and not offsets.verified:
        print(
            f"[警告] offsets 文件 {args.offsets} 的 meta.verified=false，"
            f"从未在真实进程上验证过，读到的数据可能是错的。",
            file=sys.stderr,
        )
    reader = _build_reader(args)
    try:
        return parse_game_state(reader, offsets, validate=not args.no_validate)
    finally:
        close = getattr(reader, "close", None)
        if close:
            close()


def cmd_visible_state(args: argparse.Namespace) -> int:
    """M2 命令行入口：把完整 GameState 过滤成 VisibleGameState 并打印。

    2026-08-19 新增。boundary.py 此前只能通过 Python API 调用，这里补上
    对应的 CLI 子命令，跟 `snapshot` 是同一套读取逻辑，只是多一步过滤。
    """
    from .boundary import filter_game_state

    try:
        state = _parse_game_state_from_args(args)
    except AnchorResolutionError as exc:
        print(f"[错误] 无法解析 GAME_DATA_BASE 锚点: {exc}", file=sys.stderr)
        return 2
    except ValidationError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 - CLI 顶层，转成明确退出信息
        print(f"[错误] 无法建立内存读取通道: {exc}", file=sys.stderr)
        return 1

    visibility = _build_static_visibility(args)
    visible = filter_game_state(state, visibility)

    if args.summary:
        _print_visible_summary(visible, visibility.player_faction_id)
    else:
        print(json.dumps(_game_state_to_jsonable(visible), ensure_ascii=False, indent=2))
    return 0


def _print_visible_summary(visible, player_faction_id: int) -> None:
    g = visible.global_state
    print(f"剧本 {g.scenario_id} | 开局 {g.start_year}-{g.start_month}-{g.start_day} | 当前第 {g.current_xun} 旬")
    print(f"玩家势力: {player_faction_id}")
    own_cities = [c for c in visible.cities if c.faction_id == player_faction_id]
    print(f"可见城池数: {len(visible.cities)}（其中己方 {len(own_cities)} 座） | 可见武将数: {len(visible.generals)} | 可见部队数: {len(visible.troops)}")
    for city in own_cities[:5]:
        detail = f"兵力={city.troops}/{city.troop_capacity} 钱={city.gold} 粮={city.food}" if hasattr(city, "gold") else "(仅摘要)"
        print(f"  己方城池[{city.index}] {city.name}: {detail}")
    if len(own_cities) > 5:
        print(f"  ... 其余 {len(own_cities) - 5} 座己方城池省略")


def cmd_legal_actions(args: argparse.Namespace) -> int:
    """M4 命令行入口：枚举当前内政阶段的全部合法动作并打印。

    2026-08-19 新增。legal_actions.py 此前只能通过 Python API 调用。这条
    命令串起完整链路：读内存 -> M1 GameState -> M2 过滤 -> M4 枚举，跟真实
    生产代码路径一致（不是单独拼一份手工构造的测试数据）。
    """
    from .boundary import filter_game_state
    from .domestic_rules import load_domestic_rules
    from .legal_actions import describe_action, enumerate_legal_actions

    try:
        state = _parse_game_state_from_args(args)
    except AnchorResolutionError as exc:
        print(f"[错误] 无法解析 GAME_DATA_BASE 锚点: {exc}", file=sys.stderr)
        return 2
    except ValidationError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 - CLI 顶层，转成明确退出信息
        print(f"[错误] 无法建立内存读取通道: {exc}", file=sys.stderr)
        return 1

    try:
        rules = load_domestic_rules(args.rules)
    except Exception as exc:  # noqa: BLE001 - CLI 顶层，转成明确退出信息
        print(f"[错误] 无法加载规则表 {args.rules}: {exc}", file=sys.stderr)
        return 1

    visibility = _build_static_visibility(args)
    visible = filter_game_state(state, visibility)
    assigned = _parse_int_set(args.assigned_generals)

    actions = enumerate_legal_actions(visible, args.player_faction_id, assigned, rules)
    print(f"共 {len(actions)} 条合法动作（玩家势力={args.player_faction_id}，已排除已指派武将={sorted(assigned) or '无'}）")
    for action in actions:
        print(f"  {describe_action(action, rules)}")
    return 0


def cmd_select_city(args: argparse.Namespace) -> int:
    """M3 执行链路最小命令行入口：点选一座城池并轮询确认选中状态变更。

    默认是演练模式（不加 --live）：坐标计算、轮询、动作日志全部照常跑，但
    键鼠输入走 FakeInputBackend，不会真的动这台机器的鼠标键盘，窗口坐标换算
    也走 FakeGameWindow（假设客户区左上角就是屏幕原点）——这条链路目前在真实
    游戏上跑不起来（camera/selection 内存字段、map_viewport 界面坐标都还是
    unknown，见 offsets/pk_1.1_cn.json 和 ui_layout/pk_1.1_cn.json），演练模式
    至少能验证代码本身跑不跑得通、轮询/重试/日志的行为对不对。--live 模式
    会改用真实的 SendInputBackend + Win32GameWindow，仅供游戏能运行、且 anchor
    问题解决之后使用；出于安全，必须显式加这个参数才会发送真实输入。
    """
    from .action_log import ActionLog
    from .clock import SystemClock
    from .execution import CitySelector, ExecutionConfig, ExecutionFailedError
    from .input_backend import FakeInputBackend, InputBackend
    from .map_projection import TileCoord
    from .ui_layout import load_ui_layout
    from .window import FakeGameWindow, GameWindow, ensure_dpi_awareness

    ensure_dpi_awareness()

    offsets = load_offsets(args.offsets)
    ui_layout = load_ui_layout(args.ui_layout)

    try:
        reader = _build_reader(args)
    except Exception as exc:  # noqa: BLE001 - CLI 顶层，转成明确退出信息
        print(f"[错误] 无法建立内存读取通道: {exc}", file=sys.stderr)
        return 1

    input_backend: InputBackend
    window: GameWindow
    if args.live:
        if sys.platform != "win32":
            print("[错误] --live 只支持 Windows", file=sys.stderr)
            return 1
        if not args.process:
            print("[错误] --live 模式必须搭配 --process", file=sys.stderr)
            return 1
        from .input_backend import SendInputBackend
        from .window import Win32GameWindow

        input_backend = SendInputBackend()
        window = Win32GameWindow.attach_by_pid(reader.pid)  # type: ignore[attr-defined]
    else:
        print("[提示] 演练模式（未加 --live）：不会发送任何真实键鼠输入。", file=sys.stderr)
        input_backend = FakeInputBackend()
        window = FakeGameWindow()

    clock = SystemClock()
    action_log = ActionLog(clock)
    selector = CitySelector(
        reader=reader,
        offsets=offsets,
        ui_layout=ui_layout,
        input_backend=input_backend,
        window=window,
        clock=clock,
        action_log=action_log,
        config=ExecutionConfig(poll_timeout=args.poll_timeout),
    )

    result = 0
    try:
        selector.select_city(args.city_index, TileCoord(args.tile_x, args.tile_y))
        print(f"城池 {args.city_index} 选中确认成功。")
    except ExecutionFailedError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        result = 4
    except Exception as exc:  # noqa: BLE001 - CLI 顶层，转成明确退出信息
        print(f"[错误] {exc}", file=sys.stderr)
        result = 5
    finally:
        close = getattr(reader, "close", None)
        if close:
            close()
        print(action_log.to_jsonl())

    return result


def cmd_mem_dump(args: argparse.Namespace) -> int:
    """辅助工具一（写端）：从真实进程（或已有 dump，用于重新切片/改标签）抓一份
    原始内存快照，写成 DumpMemoryReader 能直接识别的 json，供 mem-diff 对比。
    """
    from .mem_snapshot import RegionSpecError, parse_region_spec, write_snapshot_file

    try:
        regions = [parse_region_spec(spec) for spec in args.region]
    except RegionSpecError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    try:
        reader = _build_reader(args)
    except Exception as exc:  # noqa: BLE001 - CLI 顶层，转成明确退出信息
        print(f"[错误] 无法建立内存读取通道: {exc}", file=sys.stderr)
        return 1

    try:
        payload = write_snapshot_file(args.out, reader, regions, label=args.label)
    except Exception as exc:  # noqa: BLE001 - CLI 顶层，转成明确退出信息
        print(f"[错误] 抓取快照失败: {exc}", file=sys.stderr)
        return 1
    finally:
        close = getattr(reader, "close", None)
        if close:
            close()

    total_bytes = sum(r["size"] for r in payload["regions"])
    print(f"已写出快照: {args.out}")
    print(f"  module_base=0x{int(payload['module_base'], 16):X}  区域数={len(regions)}  共 {total_bytes} 字节")
    for addr, size in regions:
        print(f"  区域 0x{addr:X} ~ 0x{addr + size:X} ({size} 字节)")
    return 0


def cmd_mem_diff(args: argparse.Namespace) -> int:
    """辅助工具一（diff 端）：对比两份或多份内存快照，定位哪些地址发生了变化。"""
    from .mem_diff import cross_compare, diff_snapshots, filter_spans, format_cross_compare, format_report, sort_spans
    from .memory import DumpMemoryReader

    if len(args.snapshots) < 2:
        print("[错误] mem-diff 至少需要 2 份快照", file=sys.stderr)
        return 1

    try:
        readers = [DumpMemoryReader.from_json_file(p) for p in args.snapshots]
    except Exception as exc:  # noqa: BLE001 - CLI 顶层，转成明确退出信息
        print(f"[错误] 加载快照失败: {exc}", file=sys.stderr)
        return 1

    labels = [Path(p).name for p in args.snapshots]
    base_address = int(args.base, 16) if args.base else None
    address_min = int(args.address_min, 16) if args.address_min else None
    address_max = int(args.address_max, 16) if args.address_max else None

    for i in range(len(readers) - 1):
        spans = diff_snapshots(readers[i], readers[i + 1], address_min=address_min, address_max=address_max)
        spans = filter_spans(spans, show=args.show, min_bytes=args.min_bytes)
        spans = sort_spans(spans, by=args.sort)
        print(f"== {labels[i]} -> {labels[i + 1]} ==")
        print(format_report(spans, base_address=base_address, limit=args.limit))
        print()

    if len(readers) >= 3:
        result = cross_compare(readers, labels)
        print(format_cross_compare(result, base_address=base_address))

    return 0


def cmd_full_mem_dump(args: argparse.Namespace) -> int:
    """辅助工具三（写端）：枚举目标进程的私有已提交内存区域并全部抓取，写成
    gzip+pickle 的全内存快照，供 full-mem-diff 对比。用于定位 mem-dump/mem-diff
    在 GAME_DATA_BASE 附近找不到的字段（比如 global.phase），见 mem_scan.py
    模块文档。只支持 --process（真实进程），全内存扫描离线 dump 没有意义。
    """
    from .mem_scan import (
        DEFAULT_MAX_REGION_SIZE,
        capture_full_snapshot,
        enumerate_regions,
        save_full_snapshot,
        should_scan_region,
    )
    from .memory import ProcessMemoryReader

    if not args.process:
        print("[错误] full-mem-dump 只支持 --process（真实进程）", file=sys.stderr)
        return 1
    if sys.platform != "win32":
        print("[错误] full-mem-dump 只支持 Windows", file=sys.stderr)
        return 1

    max_region_size = int(args.max_region_size, 16) if args.max_region_size else DEFAULT_MAX_REGION_SIZE
    reader = ProcessMemoryReader.attach_by_name(args.process)
    try:
        print("[提示] 正在枚举内存区域……", file=sys.stderr)
        all_regions = enumerate_regions(reader)
        regions = [
            r for r in all_regions
            if should_scan_region(r, only_private=not args.include_image, max_region_size=max_region_size)
        ]
        total_bytes = sum(r.region_size for r in regions)
        print(
            f"[提示] 枚举到 {len(all_regions)} 个区域，其中 {len(regions)} 个符合扫描条件，"
            f"共 {total_bytes / 1024 / 1024:.1f} MB，开始抓取……",
            file=sys.stderr,
        )
        region_bytes = capture_full_snapshot(reader, regions)
        save_full_snapshot(args.out, reader.module_base, region_bytes, label=args.label)
    finally:
        reader.close()

    print(f"已写出全内存快照: {args.out}（{len(region_bytes)} 个区域）")
    return 0


def cmd_full_mem_diff(args: argparse.Namespace) -> int:
    """辅助工具三（diff 端）：对比两份 full-mem-dump 快照。"""
    from .mem_scan import diff_full_snapshots, format_full_diff_report, load_full_snapshot

    old = load_full_snapshot(args.old)
    new = load_full_snapshot(args.new)
    report = diff_full_snapshots(old["regions"], new["regions"])
    print(f"== {args.old} -> {args.new} ==")
    print(format_full_diff_report(report, min_bytes=args.min_bytes, limit=args.limit))
    return 0


def cmd_full_mem_toggle(args: argparse.Namespace) -> int:
    """辅助工具三（toggle 端）：对比"操作前/操作中/操作后"三份 full-mem-dump
    快照，只挑"操作前后相同、操作中不同"的字节——比 full-mem-diff 更能排除
    跟本次操作无关的背景噪音（帧计数器等持续变化、不会变回原值的字段），
    见 mem_scan.py find_toggled_spans() 文档。
    """
    from .mem_scan import find_toggled_spans, format_toggled_spans, load_full_snapshot

    before = load_full_snapshot(args.before)
    during = load_full_snapshot(args.during)
    after = load_full_snapshot(args.after)
    spans = find_toggled_spans(before["regions"], during["regions"], after["regions"])
    print(f"== {args.before} -> {args.during} -> {args.after} ==")
    print(format_toggled_spans(spans, min_bytes=args.min_bytes, limit=args.limit))
    return 0


def cmd_probe_anchor(args: argparse.Namespace) -> int:
    """辅助工具二：批量验证 GAME_DATA_BASE 候选地址，复用 perception.py 的启动常量校验。"""
    from .anchor_probe import format_report, load_candidates_file, probe_candidates
    from .offsets import AnchorSpec

    offsets = load_offsets(args.offsets)

    candidates: list[tuple[str, AnchorSpec]] = []
    if args.candidates_file:
        try:
            candidates.extend(load_candidates_file(args.candidates_file))
        except Exception as exc:  # noqa: BLE001 - CLI 顶层，转成明确退出信息
            print(f"[错误] 加载候选文件失败: {exc}", file=sys.stderr)
            return 1
    for rva in args.rva or []:
        candidates.append((f"命令行候选 --rva {rva}", AnchorSpec(
            resolution_method="static_rva", rva=int(rva, 16), pointer_chain=None,
            fixture_absolute_address=None, observed_absolute_address=None,
            confidence="unknown", note="来自命令行 --rva 参数",
        )))
    for absolute in args.absolute or []:
        candidates.append((f"命令行候选 --absolute {absolute}", AnchorSpec(
            resolution_method="fixed_for_fixture", rva=None, pointer_chain=None,
            fixture_absolute_address=int(absolute, 16), observed_absolute_address=None,
            confidence="unknown", note="来自命令行 --absolute 参数",
        )))
    for chain in args.pointer_chain or []:
        try:
            values = [int(x, 16) for x in chain.split(",")]
        except ValueError:
            print(f"[错误] --pointer-chain 参数 {chain!r} 不是逗号分隔的十六进制列表", file=sys.stderr)
            return 1
        candidates.append((f"命令行候选 --pointer-chain {chain}", AnchorSpec(
            resolution_method="pointer_chain", rva=None, pointer_chain=values,
            fixture_absolute_address=None, observed_absolute_address=None,
            confidence="unknown", note="来自命令行 --pointer-chain 参数",
        )))

    if not candidates:
        print(
            "[错误] 至少需要通过 --candidates-file / --rva / --absolute / --pointer-chain 之一提供候选",
            file=sys.stderr,
        )
        return 1

    try:
        reader = _build_reader(args)
    except Exception as exc:  # noqa: BLE001 - CLI 顶层，转成明确退出信息
        print(f"[错误] 无法建立内存读取通道: {exc}", file=sys.stderr)
        return 1

    try:
        results = probe_candidates(reader, offsets, candidates)
    finally:
        close = getattr(reader, "close", None)
        if close:
            close()

    print(format_report(results))
    return 0 if any(r.ok for r in results) else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="san11agent", description="三国志11PK 内存读取/执行工具")
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot", help="解析并打印一份局势快照")
    snap.add_argument("--offsets", required=True, help="offsets json 文件路径")
    snap.add_argument("--dump", help="离线内存 dump json 文件路径（与 --process 二选一）")
    snap.add_argument("--process", help="游戏进程名，例如 San11WPK.exe（Steam 繁体中文版，与 --dump 二选一）")
    snap.add_argument("--no-validate", action="store_true", help="跳过启动常量校验")
    snap.add_argument("--summary", action="store_true", help="打印简要摘要而不是完整 JSON")
    snap.set_defaults(func=cmd_snapshot)

    def _add_visibility_args(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--player-faction-id", type=int, required=True,
            help="玩家自己所属势力在 faction 数组里的 index（不从内存派生，见 visibility.py 模块文档）",
        )
        p.add_argument(
            "--explored-cities", help="已探明的非己方城池 index，逗号分隔（例如 3,7,12），默认空（一律当作未探明）",
        )
        p.add_argument(
            "--visible-troops", help="视野内的非己方部队 index，逗号分隔，默认空（一律当作不可见）",
        )
        p.add_argument(
            "--discovered-generals", help="已发现的在野武将 index，逗号分隔，默认空（一律当作未发现）",
        )

    visible_state = sub.add_parser(
        "visible-state", help="M2：把完整 GameState 过滤成人类可见的 VisibleGameState 并打印"
    )
    visible_state.add_argument("--offsets", required=True, help="offsets json 文件路径")
    visible_state.add_argument("--dump", help="离线内存 dump json 文件路径（与 --process 二选一）")
    visible_state.add_argument("--process", help="游戏进程名，例如 San11WPK.exe（与 --dump 二选一）")
    visible_state.add_argument("--no-validate", action="store_true", help="跳过启动常量校验")
    visible_state.add_argument("--summary", action="store_true", help="打印简要摘要而不是完整 JSON")
    _add_visibility_args(visible_state)
    visible_state.set_defaults(func=cmd_visible_state)

    legal_actions_cmd = sub.add_parser(
        "legal-actions", help="M4：枚举当前内政阶段的全部合法动作（读内存 -> M1 -> M2 过滤 -> M4 枚举）"
    )
    legal_actions_cmd.add_argument("--offsets", required=True, help="offsets json 文件路径")
    legal_actions_cmd.add_argument("--rules", required=True, help="内政规则表 json 文件路径，例如 rules/domestic_actions_pk_1.1_cn.json")
    legal_actions_cmd.add_argument("--dump", help="离线内存 dump json 文件路径（与 --process 二选一）")
    legal_actions_cmd.add_argument("--process", help="游戏进程名，例如 San11WPK.exe（与 --dump 二选一）")
    legal_actions_cmd.add_argument("--no-validate", action="store_true", help="跳过启动常量校验")
    legal_actions_cmd.add_argument(
        "--assigned-generals", help="本回合已经指派过指令的武将 index，逗号分隔，默认空（无人被排除）",
    )
    _add_visibility_args(legal_actions_cmd)
    legal_actions_cmd.set_defaults(func=cmd_legal_actions)

    select_city = sub.add_parser(
        "select-city", help="M3：点选一座城池并轮询确认选中状态变更（默认演练模式，不发送真实输入）"
    )
    select_city.add_argument("--offsets", required=True, help="offsets json 文件路径")
    select_city.add_argument("--ui-layout", required=True, help="ui_layout json 文件路径")
    select_city.add_argument("--dump", help="离线内存 dump json 文件路径（与 --process 二选一）")
    select_city.add_argument("--process", help="游戏进程名，例如 San11WPK.exe（Steam 繁体中文版，与 --dump 二选一）")
    select_city.add_argument("--city-index", type=int, required=True, help="目标城池在 city 数组里的 index")
    select_city.add_argument("--tile-x", type=int, required=True, help="目标城池的地图格子 X 坐标")
    select_city.add_argument("--tile-y", type=int, required=True, help="目标城池的地图格子 Y 坐标")
    select_city.add_argument("--poll-timeout", type=float, default=2.0, help="每次轮询确认的超时秒数")
    select_city.add_argument(
        "--live", action="store_true",
        help="使用真实 SendInput 键鼠输入和真实游戏窗口（默认关闭，走 Fake 后端演练）",
    )
    select_city.set_defaults(func=cmd_select_city)

    mem_dump = sub.add_parser(
        "mem-dump", help="辅助工具一（写端）：从真实进程抓一份原始内存快照，写成 dump json"
    )
    mem_dump.add_argument("--dump", help="以已有 dump json 作为数据源（与 --process 二选一，用于重新切片/改标签）")
    mem_dump.add_argument("--process", help="游戏进程名，例如 San11WPK.exe（Steam 繁体中文版，与 --dump 二选一）")
    mem_dump.add_argument(
        "--region", action="append", required=True,
        help="要抓取的地址范围，格式 ADDR:SIZE（十六进制），可重复指定多个区域，例如 --region 0x07201958:0x1000",
    )
    mem_dump.add_argument("--out", required=True, help="输出的快照 json 文件路径")
    mem_dump.add_argument(
        "--label", help="给这份快照起个名字，方便后续 diff 报告里辨认，例如 'before-switch-to-domestic'"
    )
    mem_dump.set_defaults(func=cmd_mem_dump)

    mem_diff = sub.add_parser(
        "mem-diff", help="辅助工具一（diff 端）：对比两份或多份 mem-dump 快照，定位哪些地址发生了变化"
    )
    mem_diff.add_argument(
        "snapshots", nargs="+",
        help="按时间顺序排列的快照 json 文件路径（至少2份；3份及以上会额外做相邻快照的交叉比对）",
    )
    mem_diff.add_argument(
        "--min-bytes", type=int, default=1, help="只显示变化字节数 >= 这个值的区间（默认1，即显示所有变化）"
    )
    mem_diff.add_argument("--address-min", help="只对比这个地址（十六进制）及以上的区域")
    mem_diff.add_argument("--address-max", help="只对比这个地址（十六进制）以下的区域")
    mem_diff.add_argument(
        "--show", choices=["changed", "unchanged", "all"], default="changed",
        help="显示变化的/未变化的/全部区间（默认只显示变化的）",
    )
    mem_diff.add_argument(
        "--sort", choices=["address", "bytes"], default="address",
        help="按地址升序，或按变化字节数从多到少排序（默认按地址）",
    )
    mem_diff.add_argument("--limit", type=int, help="每次过渡最多显示多少条区间（默认不限制）")
    mem_diff.add_argument(
        "--base", help="一个十六进制基址（比如已知的 GAME_DATA_BASE），报告里额外用相对偏移显示每个地址"
    )
    mem_diff.set_defaults(func=cmd_mem_diff)

    full_mem_dump = sub.add_parser(
        "full-mem-dump",
        help="辅助工具三（写端）：枚举+抓取目标进程全部私有已提交内存区域，供 full-mem-diff 定位 GAME_DATA_BASE 附近找不到的字段",
    )
    full_mem_dump.add_argument("--process", required=True, help="游戏进程名，例如 San11WPK.exe")
    full_mem_dump.add_argument("--out", required=True, help="输出的全内存快照文件路径（gzip+pickle 格式）")
    full_mem_dump.add_argument("--label", help="给这份快照起个名字，方便后续 diff 报告里辨认")
    full_mem_dump.add_argument(
        "--include-image", action="store_true",
        help="连 MEM_IMAGE（exe/dll 镜像，比如 GAME_DATA_BASE 所在的那块）也扫进来，默认只扫 MEM_PRIVATE（堆/栈），量级小很多",
    )
    full_mem_dump.add_argument(
        "--max-region-size", help="单个区域超过这个大小（十六进制）就跳过，默认 0x4000000（64MB）"
    )
    full_mem_dump.set_defaults(func=cmd_full_mem_dump)

    full_mem_diff = sub.add_parser(
        "full-mem-diff", help="辅助工具三（diff 端）：对比两份 full-mem-dump 快照，定位哪些地址发生了变化"
    )
    full_mem_diff.add_argument("old", help="较早抓的全内存快照文件路径")
    full_mem_diff.add_argument("new", help="较晚抓的全内存快照文件路径")
    full_mem_diff.add_argument(
        "--min-bytes", type=int, default=1, help="只显示变化字节数 >= 这个值的区间（默认1）"
    )
    full_mem_diff.add_argument("--limit", type=int, help="最多显示多少条变化区间（默认不限制）")
    full_mem_diff.set_defaults(func=cmd_full_mem_diff)

    full_mem_toggle = sub.add_parser(
        "full-mem-toggle",
        help="辅助工具三（toggle端）：对比操作前/操作中/操作后三份 full-mem-dump 快照，只挑'前后相同、中间不同'的字节，排除背景噪音",
    )
    full_mem_toggle.add_argument("before", help="操作前抓的全内存快照")
    full_mem_toggle.add_argument("during", help="操作中/操作后立刻抓的全内存快照")
    full_mem_toggle.add_argument("after", help="撤销操作、回到和 before 相同状态后抓的全内存快照")
    full_mem_toggle.add_argument("--min-bytes", type=int, default=1, help="只显示变化字节数 >= 这个值的区间（默认1）")
    full_mem_toggle.add_argument("--limit", type=int, help="最多显示多少条区间（默认不限制）")
    full_mem_toggle.set_defaults(func=cmd_full_mem_toggle)

    probe_anchor = sub.add_parser(
        "probe-anchor", help="辅助工具二：批量验证 GAME_DATA_BASE 候选地址，复用启动常量校验逻辑"
    )
    probe_anchor.add_argument("--offsets", required=True, help="offsets json 文件路径（用来读 struct 布局和 validation 预期值）")
    probe_anchor.add_argument("--dump", help="离线内存 dump json 文件路径（与 --process 二选一）")
    probe_anchor.add_argument("--process", help="游戏进程名，例如 San11WPK.exe（Steam 繁体中文版，与 --dump 二选一）")
    probe_anchor.add_argument("--candidates-file", help="候选锚点列表 json 文件（格式见 anchor_probe.load_candidates_file 文档）")
    probe_anchor.add_argument("--rva", action="append", help="候选 RVA（十六进制，相对模块基址），可重复指定")
    probe_anchor.add_argument("--absolute", action="append", help="候选绝对地址（十六进制），可重复指定")
    probe_anchor.add_argument(
        "--pointer-chain", action="append",
        help="候选指针链，逗号分隔的十六进制列表，例如 0x1958,0x10,0x20，可重复指定",
    )
    probe_anchor.set_defaults(func=cmd_probe_anchor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
