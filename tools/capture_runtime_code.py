"""Read six bounded code ranges to compare loaded bytes with the verified EXE.

No debugger attach, breakpoints, injection, target launch or memory writes.
Run only when the game can start in a local desktop session.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from san11agent.memory import ProcessMemoryReader
from collect_static_research import EXPECTED_SHA256


def verified_image(reader: ProcessMemoryReader) -> tuple[Path, bytes, str]:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    query = kernel.QueryFullProcessImageNameW
    query.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    query.restype = ctypes.c_int
    name_buffer = ctypes.create_unicode_buffer(32768)
    size = ctypes.c_ulong(len(name_buffer))
    if not query(reader.raw_handle, 0, name_buffer, ctypes.byref(size)):
        raise OSError(ctypes.get_last_error(), "Cannot verify process executable identity")
    binary = Path(name_buffer.value)
    data = binary.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError("Running executable differs from the selected baseline")
    return binary, data, digest


def capture(leads_path: Path) -> dict:
    leads = json.loads(leads_path.read_text(encoding="utf-8"))
    if leads["sha256"] != EXPECTED_SHA256:
        raise ValueError("Static leads do not match the selected baseline")
    with ProcessMemoryReader.attach_by_name("San11WPK.exe") as reader:
        binary, data, digest = verified_image(reader)
        original_base = int(leads["image_base"], 16)
        comparisons = []
        for seed in leads["candidate_excerpts"]:
            if seed["status"] != "candidate_only":
                continue
            va = int(seed["va"], 16)
            runtime_address = reader.module_base + va - original_base
            first = reader.read_bytes(runtime_address, 128)
            second = reader.read_bytes(runtime_address, 128)
            disk = data[seed["file_offset"]:seed["file_offset"] + 128]
            comparisons.append({"historical_va": seed["va"], "rva": hex(va - original_base),
                                "runtime_address": hex(runtime_address), "bytes": first.hex(),
                                "stable_across_two_reads": first == second,
                                "identical_to_disk": first == disk,
                                "runtime_sha256": hashlib.sha256(first).hexdigest(),
                                "disk_sha256": hashlib.sha256(disk).hexdigest()})
        return {"source": "ReadProcessMemory observation, not REA static Evidence",
                "pid": reader.pid, "executable": str(binary), "sha256": digest,
                "module_base": hex(reader.module_base), "comparisons": comparisons,
                "limitations": ["Only six historical candidate ranges; identities remain unverified",
                                "Different bytes can result from relocation, patching or transformation",
                                "No inference of protection scheme or game state from byte differences"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--leads", type=Path, default=Path(__file__).resolve().parents[1] / "docs/rea/static_leads_2026-10-15.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output already exists; select a new evidence path")
    try:
        result = capture(args.leads)
    except Exception as error:
        parser.exit(1, f"Runtime capture unavailable: {error}\n")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({"out": str(args.out.resolve()), "pid": result["pid"],
                      "ranges": len(result["comparisons"])}, ensure_ascii=False))
