"""Build an analysis-only PE copy with stable loaded .text bytes.

All other sections remain disk bytes. This is a hybrid, not a complete dump,
and must never be executed or substituted for the installed game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from capture_runtime_code import ProcessMemoryReader, verified_image
from collect_static_research import EXPECTED_SHA256


def derive(leads_path: Path, output: Path) -> dict:
    manifest_path = output.with_suffix(output.suffix + ".provenance.json")
    if output.exists() or manifest_path.exists():
        raise ValueError("Select new absent output and provenance paths")
    leads = json.loads(leads_path.read_text(encoding="utf-8"))
    if leads["sha256"] != EXPECTED_SHA256:
        raise ValueError("Unverified leads identity")
    sections = [s for s in leads["sections"] if s["name"] == ".text"]
    if len(sections) != 1:
        raise ValueError("Expected exactly one .text section")
    section = sections[0]
    with ProcessMemoryReader.attach_by_name("San11WPK.exe") as reader:
        source, disk, digest = verified_image(reader)
        if reader.module_base != int(leads["image_base"], 16):
            raise ValueError("Relocated image requires explicit relocation handling; refusing hybrid copy")
        address = reader.module_base + section["rva"]
        loaded = reader.read_bytes(address, section["raw_size"])
        again = reader.read_bytes(address, section["raw_size"])
        if loaded != again:
            raise ValueError(".text changed during capture; refusing unstable evidence")
        offset = section["raw_offset"]
        if offset + len(loaded) > len(disk):
            raise ValueError("Section exceeds source file")
        derived = bytearray(disk)
        derived[offset:offset + len(loaded)] = loaded
        provenance = {"source_kind": "hybrid analysis artifact, not shipped original",
                      "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                      "pid": reader.pid, "module_base": hex(reader.module_base),
                      "original_path": str(source), "original_sha256": digest,
                      "derived_path": str(output.resolve()),
                      "derived_sha256": hashlib.sha256(derived).hexdigest(),
                      "replaced_section": section, "stable_across_two_reads": True,
                      "loaded_text_sha256": hashlib.sha256(loaded).hexdigest(),
                      "disk_text_sha256": hashlib.sha256(disk[offset:offset + len(loaded)]).hexdigest(),
                      "limitations": ["Only .text is loaded-memory evidence; all other sections remain disk bytes",
                                      "No execution or functional-equivalence claim", "No game state or candidate function semantics verified",
                                      "Do not execute this file or overwrite the installed EXE"]}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as artifact:
        artifact.write(derived)
    with manifest_path.open("x", encoding="utf-8") as manifest:
        json.dump(provenance, manifest, ensure_ascii=False, indent=2)
        manifest.write("\n")
    return provenance


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--leads", type=Path, default=Path(__file__).resolve().parents[1] / "docs/rea/static_leads_2026-10-15.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(derive(args.leads, args.out), ensure_ascii=False))
