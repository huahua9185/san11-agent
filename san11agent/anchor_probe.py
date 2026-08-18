"""批量验证 GAME_DATA_BASE 候选地址。

复用 perception.py 已有的解析/校验逻辑（resolve_anchor / parse_global_state /
parse_generals / parse_cities / parse_factions / validate_constants），不重新
实现一遍常量校验——这里只是"对每个候选跑一遍同一套校验，把结果整理成人可读
的报告"这一层胶水代码。

用途：配合验证清单阶段3的锚点定位。手头有几个候选 RVA/指针链/绝对地址（比如
Cheat Engine 指针扫描给出的几条候选链），不用在 CE 里一个个手动读、凭肉眼判断
"这段字节像不像武将姓名"，而是让每个候选都跑一遍"武将数=1100/城池数=42/
势力数=42/剧本编号/开局年份"这套现成的启动校验，直接看哪个候选通过。

刻意不解析 troop——validate_constants() 本身不检查它，而 troop.base_offset
在生产 offsets 文件里还有独立未决的问题（见验证清单4.2），不应该拖累锚点候选
本身的验证。
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

from .game_state import GameState
from .memory import MemoryReader, MemoryReadError
from .offsets import AnchorSpec, OffsetsConfig, load_anchor_candidate
from .perception import (
    AnchorResolutionError,
    ValidationError,
    parse_cities,
    parse_factions,
    parse_generals,
    parse_global_state,
    resolve_anchor,
    validate_constants,
)


@dataclass(frozen=True)
class CandidateResult:
    label: str
    anchor: AnchorSpec
    game_data_base: int | None
    ok: bool
    reason: str
    state: GameState | None = None


def load_candidates_file(path: str | Path) -> list[tuple[str, AnchorSpec]]:
    """候选文件格式：
        {"candidates": [
            {"label": "...", "resolution_method": "static_rva", "rva": "0x..."},
            {"label": "...", "resolution_method": "pointer_chain", "pointer_chain": ["0x...", "0x..."]},
            {"label": "...", "resolution_method": "fixed_for_fixture", "fixture_absolute_address": "0x..."}
        ]}
    每个候选条目的形状和 offsets 文件里的 anchor 字段完全一致，字段解析直接复用
    offsets.load_anchor_candidate()。label 可省略，省略时自动编号。
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    entries = raw.get("candidates")
    if not entries:
        raise ValueError(f"{path} 里没有 candidates 列表，或者是空的")
    result = []
    for i, entry in enumerate(entries):
        label = entry.get("label") or f"候选{i + 1}"
        result.append((label, load_anchor_candidate(entry)))
    return result


def probe_candidates(
    reader: MemoryReader,
    offsets: OffsetsConfig,
    candidates: list[tuple[str, AnchorSpec]],
) -> list[CandidateResult]:
    results = []
    for label, anchor_spec in candidates:
        candidate_offsets = dataclasses.replace(offsets, anchor=anchor_spec)
        try:
            game_data_base = resolve_anchor(reader, candidate_offsets)
        except (AnchorResolutionError, MemoryReadError) as exc:
            # pointer_chain 候选在解引用中间环节读取失败时，resolve_anchor 内部
            # 会直接抛出 MemoryReadError（不是 AnchorResolutionError），这里一并接住。
            results.append(CandidateResult(label, anchor_spec, None, False, f"锚点解析失败: {exc}"))
            continue

        try:
            state = GameState(
                global_state=parse_global_state(reader, offsets, game_data_base),
                generals=parse_generals(reader, offsets, game_data_base),
                cities=parse_cities(reader, offsets, game_data_base),
                factions=parse_factions(reader, offsets, game_data_base),
            )
        except (MemoryReadError, AnchorResolutionError) as exc:
            results.append(CandidateResult(label, anchor_spec, game_data_base, False, f"读取内存失败: {exc}"))
            continue

        try:
            validate_constants(offsets, state)
        except ValidationError as exc:
            results.append(CandidateResult(label, anchor_spec, game_data_base, False, str(exc), state))
            continue

        results.append(CandidateResult(label, anchor_spec, game_data_base, True, "通过全部启动常量校验", state))
    return results


def _anchor_desc(anchor: AnchorSpec) -> str:
    if anchor.resolution_method == "static_rva":
        return f"static_rva rva=0x{anchor.rva:X}"
    if anchor.resolution_method == "pointer_chain":
        chain = ", ".join(hex(x) for x in (anchor.pointer_chain or []))
        return f"pointer_chain [{chain}]"
    if anchor.resolution_method == "fixed_for_fixture":
        return f"绝对地址 0x{anchor.fixture_absolute_address:X}"
    return anchor.resolution_method


def format_candidate_result(index: int, total: int, result: CandidateResult) -> str:
    lines = [f'候选 [{index}/{total}] "{result.label}" ({_anchor_desc(result.anchor)})']
    if result.game_data_base is not None:
        lines.append(f"  GAME_DATA_BASE = 0x{result.game_data_base:X}")
    if result.ok:
        assert result.state is not None
        g = result.state.global_state
        lines.append(
            "  结果: 通过\n"
            f"  剧本编号={g.scenario_id} 开局={g.start_year}-{g.start_month}-{g.start_day} "
            f"武将数={len(result.state.generals)} 城池数={len(result.state.cities)} "
            f"势力数={len(result.state.factions)}（均在预期范围内）\n"
            "  >>> 这个候选很可能就是正确的 GAME_DATA_BASE。下一步：把对应的 "
            "resolution_method/rva 或 pointer_chain 写入 offsets 文件的 anchor 字段，"
            "再跑一次 `snapshot --summary` 做最终确认，并按验证清单4.3 抽查具体字段数值"
            "（校验通过只说明数量/范围合理，不代表每个字段的偏移都对）。"
        )
    else:
        lines.append(f"  结果: 未通过\n  原因: {result.reason}")
    return "\n".join(lines)


def format_report(results: list[CandidateResult]) -> str:
    total = len(results)
    lines = [format_candidate_result(i + 1, total, r) for i, r in enumerate(results)]
    passed = [r for r in results if r.ok]
    lines.append("")
    lines.append(f"共测试 {total} 个候选，{len(passed)} 个通过校验。")
    if len(passed) == 1:
        lines.append(f'推荐候选: "{passed[0].label}"。')
    elif len(passed) > 1:
        lines.append(
            "多个候选都通过了校验——校验只能保证'读到的数量/范围合理'，不能唯一确定地址，"
            "建议用验证清单4.3 逐字段核对（比如具体武将姓名/属性）来最终确认用哪一个，"
            "也可能是多个候选算出了同一个实际地址（比如指针链和静态地址殊途同归）。"
        )
    else:
        lines.append(
            "没有候选通过校验。检查候选本身是否正确、offsets 文件里 general/city/faction "
            "的 base_offset 是否已知，或者游戏当前是否停在正式对局界面（不是剧本选择界面，"
            "见验证清单2.1）。"
        )
    return "\n".join(lines)
