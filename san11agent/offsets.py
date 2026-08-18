"""加载并校验 offsets/*.json 偏移表。

不使用外部 JSON Schema 校验库，手写校验逻辑，理由：
- 依赖越少，在目标机器（离线单机）上部署越省事
- offsets/schema.json 仍然作为人类可读的权威格式文档保留，
  本文件里的校验逻辑在语义上应当与它保持一致
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class OffsetsError(Exception):
    """offsets 文件格式错误，或者引用了字段却没检查 unknown 就直接用。"""


def _parse_hex(value: str | None) -> int | None:
    if value is None:
        return None
    return int(value, 16)


@dataclass(frozen=True)
class FieldSpec:
    name: str
    offset: int | None
    size: int | None
    type: str | None
    unknown: bool
    array_len: int | None = None
    confidence: str = "none"
    source: str = ""
    note: str = ""

    def require_known(self) -> "FieldSpec":
        """在解析代码里，任何要真正读取的字段必须先过这一关。

        目的是让"这个字段其实是 unknown，我们本不该读它"这种错误在开发阶段
        就炸出来，而不是安静地返回一个没有意义的数字。
        """
        if self.unknown or self.offset is None:
            raise OffsetsError(
                f"字段 {self.name!r} 在 offsets 文件里标记为 unknown（{self.note or '无说明'}），"
                f"不能读取。需要先由用户确认真实偏移。"
            )
        return self


@dataclass(frozen=True)
class StructSpec:
    name: str
    base_offset: int | None
    base_offset_candidates: list[dict[str, str]]
    struct_size: int | None
    count: int | None
    fields: dict[str, FieldSpec]

    def field(self, name: str) -> FieldSpec:
        if name not in self.fields:
            raise OffsetsError(f"结构体 {self.name!r} 没有字段 {name!r}")
        return self.fields[name]


@dataclass(frozen=True)
class AnchorSpec:
    resolution_method: str
    rva: int | None
    pointer_chain: list[int] | None
    fixture_absolute_address: int | None
    observed_absolute_address: int | None
    confidence: str
    note: str


@dataclass(frozen=True)
class OffsetsConfig:
    label: str
    process_name: str
    verified: bool
    game_version: str | None
    anchor: AnchorSpec
    structs: dict[str, StructSpec]
    validation: dict[str, Any]
    raw: dict[str, Any] = field(repr=False)

    def struct(self, name: str) -> StructSpec:
        if name not in self.structs:
            raise OffsetsError(f"offsets 文件里没有结构体 {name!r}")
        return self.structs[name]


_REQUIRED_TOP_KEYS = ("meta", "anchor", "structs")
_REQUIRED_META_KEYS = ("label", "process_name", "verified")
_VALID_RESOLUTION_METHODS = {"unknown", "static_rva", "pointer_chain", "fixed_for_fixture"}


def _load_field(name: str, raw: dict[str, Any]) -> FieldSpec:
    if "unknown" not in raw:
        raise OffsetsError(f"字段 {name!r} 缺少必填的 unknown 标记")
    unknown = bool(raw["unknown"])
    offset = _parse_hex(raw.get("offset"))
    if not unknown and offset is None:
        raise OffsetsError(f"字段 {name!r} unknown=false 但没有给 offset，格式不一致")
    return FieldSpec(
        name=name,
        offset=offset,
        size=raw.get("size"),
        type=raw.get("type"),
        unknown=unknown,
        array_len=raw.get("array_len"),
        confidence=raw.get("confidence", "none"),
        source=raw.get("source", ""),
        note=raw.get("note", ""),
    )


def _load_struct(name: str, raw: dict[str, Any]) -> StructSpec:
    if "base_offset" not in raw or "fields" not in raw:
        raise OffsetsError(f"结构体 {name!r} 缺少 base_offset 或 fields")
    fields = {
        field_name: _load_field(field_name, field_raw)
        for field_name, field_raw in raw["fields"].items()
    }
    return StructSpec(
        name=name,
        base_offset=_parse_hex(raw.get("base_offset")),
        base_offset_candidates=raw.get("base_offset_candidates") or [],
        struct_size=_parse_hex(raw.get("struct_size")),
        count=raw.get("count"),
        fields=fields,
    )


def _load_anchor(raw: dict[str, Any]) -> AnchorSpec:
    method = raw.get("resolution_method")
    if method not in _VALID_RESOLUTION_METHODS:
        raise OffsetsError(
            f"anchor.resolution_method={method!r} 不合法，必须是 {_VALID_RESOLUTION_METHODS} 之一"
        )
    pointer_chain = raw.get("pointer_chain")
    return AnchorSpec(
        resolution_method=method,
        rva=_parse_hex(raw.get("rva")),
        pointer_chain=[int(x, 16) for x in pointer_chain] if pointer_chain else None,
        fixture_absolute_address=_parse_hex(raw.get("fixture_absolute_address")),
        observed_absolute_address=_parse_hex(raw.get("observed_absolute_address")),
        confidence=raw.get("confidence", "none"),
        note=raw.get("note", ""),
    )


def load_anchor_candidate(raw: dict[str, Any]) -> AnchorSpec:
    """解析单个"候选锚点"描述——和 offsets 文件里 anchor 字段同样的 JSON 形状
    （resolution_method/rva/pointer_chain/fixture_absolute_address/...）。

    供 anchor_probe.py 批量验证 GAME_DATA_BASE 候选地址时复用，不需要另外
    实现一遍 hex 字符串 / 指针链解析逻辑。
    """
    return _load_anchor(raw)


def load_offsets(path: str | Path) -> OffsetsConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))

    missing = [k for k in _REQUIRED_TOP_KEYS if k not in raw]
    if missing:
        raise OffsetsError(f"offsets 文件缺少顶层字段: {missing}")

    meta = raw["meta"]
    missing_meta = [k for k in _REQUIRED_META_KEYS if k not in meta]
    if missing_meta:
        raise OffsetsError(f"offsets 文件 meta 缺少字段: {missing_meta}")

    anchor = _load_anchor(raw["anchor"])
    structs = {name: _load_struct(name, sraw) for name, sraw in raw["structs"].items()}

    return OffsetsConfig(
        label=meta["label"],
        process_name=meta["process_name"],
        verified=bool(meta["verified"]),
        game_version=meta.get("game_version"),
        anchor=anchor,
        structs=structs,
        validation=raw.get("validation", {}),
        raw=raw,
    )
