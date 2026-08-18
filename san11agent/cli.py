"""M1 命令行工具：打印一份局势快照。

用法：
    # 离线 dump / fixture 模式（不需要游戏在跑）
    python -m san11agent.cli snapshot --offsets offsets/pk_1.1_cn.json --dump path/to/dump.json

    # 真实进程模式（当前 anchor 未解析出来之前会直接报错，这是预期行为）
    python -m san11agent.cli snapshot --offsets offsets/pk_1.1_cn.json --process san11pk.exe
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="san11agent", description="三国志11PK 内存读取 M1 命令行工具")
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot", help="解析并打印一份局势快照")
    snap.add_argument("--offsets", required=True, help="offsets json 文件路径")
    snap.add_argument("--dump", help="离线内存 dump json 文件路径（与 --process 二选一）")
    snap.add_argument("--process", help="游戏进程名，例如 san11pk.exe（与 --dump 二选一）")
    snap.add_argument("--no-validate", action="store_true", help="跳过启动常量校验")
    snap.add_argument("--summary", action="store_true", help="打印简要摘要而不是完整 JSON")
    snap.set_defaults(func=cmd_snapshot)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
