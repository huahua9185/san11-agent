"""Collect bounded static leads; never execute or modify the game.

Requires an existing capstone installation for candidate instruction excerpts.
The output is supplemental Python evidence, not REA decompilation or runtime proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

EXPECTED_SHA256 = "f2a304b118e72673f4a788b1e87322fa891ff57218a8b89e671d4f8cb6aca041"
SEEDS = {
    0x0047C4C0: "historical city-to-facility candidate",
    0x004C0C30: "historical city-information candidate",
    0x004C8720: "historical general-information candidate",
    0x004824B0: "historical year candidate",
    0x004824F0: "historical month candidate",
    0x00482530: "historical day candidate",
}
TERMS = ("都市", "徵兵", "巡察", "訓練", "行動力", "決定", "取消")


def collect(binary: Path, resource_evidence: Path) -> dict:
    data = binary.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError("Binary SHA-256 does not match the selected research baseline")
    evidence = json.loads(resource_evidence.read_text(encoding="utf-8"))
    inventory = evidence["normalized_result"]
    if inventory["artifact"]["sha256"].lower() != digest:
        raise ValueError("REA resource evidence belongs to another binary")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[:2] != b"MZ" or data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("Invalid PE signature")
    machine, count = struct.unpack_from("<HH", data, pe + 4)
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    optional = pe + 24
    if machine != 0x14C or struct.unpack_from("<H", data, optional)[0] != 0x10B:
        raise ValueError("This collector supports only the verified PE32 x86 baseline")
    image_base = struct.unpack_from("<I", data, optional + 28)[0]
    sections = []
    for i in range(count):
        pos = optional + optional_size + i * 40
        name = data[pos:pos + 8].split(b"\0", 1)[0].decode("ascii", "replace")
        virtual_size, rva, raw_size, raw_offset = struct.unpack_from("<IIII", data, pos + 8)
        flags = struct.unpack_from("<I", data, pos + 36)[0]
        if raw_offset + raw_size > len(data):
            raise ValueError("Section exceeds artifact bytes")
        sections.append(dict(name=name, rva=rva, virtual_size=virtual_size,
                             raw_offset=raw_offset, raw_size=raw_size, flags=flags))

    def mapping(offset: int) -> dict:
        matches = [s for s in sections if s["raw_offset"] <= offset < s["raw_offset"] + s["raw_size"]]
        if len(matches) != 1:
            return {"file_offset": offset, "va": None, "section": None}
        s = matches[0]
        return {"file_offset": offset, "va": hex(image_base + s["rva"] + offset - s["raw_offset"]), "section": s["name"]}

    strings = []
    for term in TERMS:
        for encoding in ("cp950", "utf-16le"):
            pattern = term.encode(encoding)
            start = 0
            hits = []
            while (pos := data.find(pattern, start)) >= 0:
                hits.append(mapping(pos))
                start = pos + 1
            strings.append({"term": term, "encoding": encoding, "matches": hits,
                            "limitation": "Byte matches alone do not establish string boundaries or UI usage"})

    resource_strings = []
    for resource in inventory["resources"]:
        if resource["type"] != {"kind": "id", "id": 6}:
            continue
        loc = resource["payload"]["location"]
        payload = data[loc["offset"]:loc["offset"] + loc["bytes"]]
        if hashlib.sha256(payload).hexdigest() != resource["payload"]["sha256"]:
            raise ValueError("Resource payload digest mismatch")
        cursor = 0
        for slot in range(16):
            length = struct.unpack_from("<H", payload, cursor)[0]
            cursor += 2
            text = payload[cursor:cursor + length * 2].decode("utf-16le")
            if len(payload[cursor:cursor + length * 2]) != length * 2:
                raise ValueError("Truncated string-table entry")
            if text and any(term in text for term in TERMS):
                resource_strings.append({"text": text, "resource_index": resource["index"],
                                         "slot": slot, "file_offset": loc["offset"] + cursor})
            cursor += length * 2

    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    disassembler = Cs(CS_ARCH_X86, CS_MODE_32)
    excerpts = []
    for va, label in SEEDS.items():
        rva = va - image_base
        matches = [s for s in sections if s["rva"] <= rva < s["rva"] + s["raw_size"]]
        if len(matches) != 1:
            excerpts.append({"va": hex(va), "label": label, "status": "unmapped"})
            continue
        s = matches[0]
        offset = s["raw_offset"] + rva - s["rva"]
        bound = min(offset + 128, s["raw_offset"] + s["raw_size"])
        instructions = [{"va": hex(ins.address), "bytes": ins.bytes.hex(),
                         "mnemonic": ins.mnemonic, "operands": ins.op_str}
                        for ins in disassembler.disasm(data[offset:bound], va)]
        excerpts.append({"va": hex(va), "label": label, "file_offset": offset,
                         "section": s["name"], "executable_section": bool(s["flags"] & 0x20000000),
                         "status": "candidate_only", "instructions": instructions})
    return {"source": "supplemental Python/Capstone static inspection",
            "binary": str(binary.resolve()), "sha256": digest, "machine": hex(machine),
            "image_base": hex(image_base),
            "entry_rva": hex(struct.unpack_from("<I", data, optional + 16)[0]),
            "rea_resource_evidence_id": evidence["evidence_id"],
            "limitations": ["No target execution or memory observation", "Historical function identities remain unverified",
                            "Linear disassembly does not prove function boundaries or control flow"],
            "sections": sections, "string_matches": strings,
            "matching_resource_strings": resource_strings, "candidate_excerpts": excerpts}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--resources", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = collect(args.binary, args.resources)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(args.out.resolve()), "sha256": report["sha256"],
                      "string_hits": sum(len(x["matches"]) for x in report["string_matches"]),
                      "matching_resource_strings": len(report["matching_resource_strings"]),
                      "candidate_excerpts": len(report["candidate_excerpts"])}, ensure_ascii=False))
