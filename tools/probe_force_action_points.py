"""Read a static-analysis candidate; this is not a verified gameplay API.

Only explicitly requested force indices are read. Does not send input, inject,
pause, write memory, or feed candidate values into the strategy loop.
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


def probe(force_indices: list[int]) -> dict:
    if not force_indices or any(not 0 <= index <= 46 for index in force_indices):
        raise ValueError("Select at least one distinct index within the statically observed 0..46 bound")
    if len(set(force_indices)) != len(force_indices):
        raise ValueError("Duplicate force indices")
    root = Path(__file__).resolve().parents[1]
    offsets = load_offsets(root / "offsets/pk_1.1_cn.json")
    with ProcessMemoryReader.attach_by_name("San11WPK.exe") as reader:
        binary, _, digest = verified_image(reader)
        base = resolve_anchor(reader, offsets)
        rows = []
        for index in force_indices:
            address = base + 0xB20C + index * 0x50
            first = reader.read_bytes(address, 0x50)
            second = reader.read_bytes(address, 0x50)
            rows.append({"force_index": index, "record_address": hex(address),
                         "faction_id_existing_layout": struct.unpack_from("<i", first, 4)[0],
                         "force_number_existing_layout": struct.unpack_from("<i", first, 8)[0],
                         "commander_existing_layout": struct.unpack_from("<i", first, 12)[0],
                         "candidate_action_points_u8_at_0x2c": first[0x2C],
                         "candidate_field_stable_across_two_reads": first[0x2C] == second[0x2C],
                         "record_stable_across_two_reads": first == second})
        return {"captured_at_utc": datetime.now(timezone.utc).isoformat(),
                "status": "candidate_only_requires_ui_and_before_after_verification",
                "source": "ReadProcessMemory, no input or memory writes", "pid": reader.pid,
                "executable": str(binary), "sha256": digest,
                "module_base": hex(reader.module_base), "game_data_base": hex(base), "rows": rows,
                "limitations": ["Byte meaning and ownership are not dynamically verified",
                                "A live process need not contain a loaded game",
                                "Do not use these values as verified LegalActions constraints"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-index", type=int, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output exists; select a new observation path")
    try:
        observation = probe(args.force_index)
    except Exception as error:
        parser.exit(1, f"Candidate probe unavailable: {error}\n")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as output:
        json.dump(observation, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({"out": str(args.out.resolve()), "rows": observation["rows"]}, ensure_ascii=False))
