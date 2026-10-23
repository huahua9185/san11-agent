"""Read explicitly selected general records for action-flag research only.

No input, suspension, injection, or writes to game memory. Candidate masks are
reported as raw observations, not exposed to the strategy or legal-action code.
"""
from __future__ import annotations

import argparse
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

from capture_runtime_code import ProcessMemoryReader, verified_image
from san11agent.offsets import load_offsets
from san11agent.perception import resolve_anchor


def probe(indices: list[int]) -> dict:
    root = Path(__file__).resolve().parents[1]
    offsets = load_offsets(root / "offsets/pk_1.1_cn.json")
    spec = offsets.struct("general")
    if not indices or len(set(indices)) != len(indices):
        raise ValueError("Select distinct general indices")
    if any(not 0 <= index < (spec.count or 0) for index in indices):
        raise ValueError("General index outside configured table")
    with ProcessMemoryReader.attach_by_name("San11WPK.exe") as reader:
        binary, _, digest = verified_image(reader)
        base = resolve_anchor(reader, offsets)
        rows = []
        for index in indices:
            address = base + spec.base_offset + index * spec.struct_size
            first = reader.read_bytes(address, spec.struct_size)
            second = reader.read_bytes(address, spec.struct_size)
            rows.append({
                "general_index": index, "record_address": hex(address),
                "record_stable_across_two_reads": first == second,
                "raw_hex": first.hex(),
                "candidate_flags_u32_at_0x124": struct.unpack_from("<I", first, 0x124)[0],
                "candidate_bit0_at_0x124": bool(first[0x124] & 1),
                "raw_stamina_u8_at_0x128": first[0x128],
                "candidate_five_u16_at_0x12a": list(struct.unpack_from("<5H", first, 0x12A)),
            })
        return {
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "research_candidates_only", "pid": reader.pid,
            "source": "ReadProcessMemory; no input or memory writes",
            "executable": str(binary), "sha256": digest,
            "module_base": hex(reader.module_base), "game_data_base": hex(base),
            "rows": rows,
            "limitations": ["No gameplay or UI state transition in this capture",
                            "Two equal reads do not prove a cross-record atomic snapshot",
                            "Candidate meaning requires static and controlled runtime evidence"],
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--general-index", type=int, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output exists; select a new observation path")
    observation = probe(args.general_index)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(observation, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"path": str(args.out), "rows": [
        {k: v for k, v in row.items() if k != "raw_hex"} for row in observation["rows"]
    ]}, ensure_ascii=False))
