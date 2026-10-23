"""Keep one portable REA/Ghidra session for explicit read-only research requests.

Uses the installed MCP Python client and public REA stdio entry point. Requests
are JSON lines on stdin: {"name": ..., "arguments": {...}, "label": ...}.
Full responses go to the selected directory; stdout contains compact summaries.
Send {"name": "close_binary"} to close the owned analysis session and exit.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ALLOWED = {"open_binary", "close_binary", "resolve_containing_procedure", "analyze_function",
           "xrefs", "procedure_pseudo_code", "procedure_callers", "procedure_callees", "inspect_analysis_view"}


def value_of(response: dict) -> dict:
    if response.get("structuredContent") is not None:
        return response["structuredContent"]
    for item in response.get("content", []):
        if item.get("type") == "text":
            try:
                return json.loads(item["text"])
            except ValueError:
                pass
    return {}


async def run(output: Path, plan: Path | None, inbox: Path | None) -> None:
    root = Path(__file__).resolve().parents[1]
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["GHIDRA_INSTALL_DIR"] = str(root / ".rea-tools/ghidra_12.1.4_PUBLIC")
    env["JAVA_HOME"] = str(root / ".rea-tools/jdk-21.0.12.1+1")
    env["REA_ANALYSIS_PROVIDER"] = "ghidra"
    env["PATH"] = str(Path(env["JAVA_HOME"]) / "bin") + os.pathsep + env.get("PATH", "")
    launcher = Path(os.environ["APPDATA"]) / "npm/node_modules/rea-agents/scripts/rea.mjs"
    server = StdioServerParameters(command="node", args=[str(launcher), "mcp"], env=env)
    initial = json.loads(plan.read_text(encoding="utf-8")) if plan else []
    with (root / ".rea-tools/rea-research-session.log").open("a", encoding="utf-8") as log:
        async with stdio_client(server, errlog=log) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=600) as session:
                await session.initialize()
                print('{"status":"connected"}', flush=True)
                count = 0
                name = None
                idle_since = None
                try:
                    while True:
                        if initial:
                            request = initial.pop(0)
                        elif inbox is not None:
                            inbox.mkdir(parents=True, exist_ok=True)
                            pending = sorted(inbox.glob("*.request.json"))
                            if not pending:
                                if idle_since is None:
                                    idle_since = asyncio.get_running_loop().time()
                                    print('{"status":"awaiting_request_file"}', flush=True)
                                if asyncio.get_running_loop().time() - idle_since > 900:
                                    break
                                await asyncio.sleep(1)
                                continue
                            request_path = pending[0]
                            request = json.loads(request_path.read_text(encoding="utf-8-sig"))
                            request_path.rename(request_path.with_suffix(".consumed"))
                            idle_since = None
                        else:
                            print('{"status":"awaiting_request"}', flush=True)
                            line = await asyncio.wait_for(asyncio.to_thread(sys.stdin.readline), timeout=900)
                            if not line:
                                break
                            request = json.loads(line)
                        name = request["name"]
                        if name not in ALLOWED:
                            raise ValueError(f"Operation outside read-only research scope: {name}")
                        label = request.get("label", f"{count:03d}_{name}")
                        if not re.fullmatch(r"[a-zA-Z0-9_-]+", label):
                            raise ValueError("Invalid evidence label")
                        destination = output / (label + ".json")
                        if destination.exists():
                            raise ValueError(f"Evidence already exists: {destination}")
                        print(json.dumps({"status":"running", "operation":name, "label":label}), flush=True)
                        result = await session.call_tool(name, request.get("arguments", {}))
                        raw = result.model_dump(mode="json", by_alias=True, exclude_none=True)
                        with destination.open("x", encoding="utf-8") as stream:
                            json.dump(raw, stream, ensure_ascii=False, indent=2)
                            stream.write("\n")
                        evidence = value_of(raw)
                        norm = evidence.get("normalized_result", evidence.get("result"))
                        summary = {"status":"saved", "operation":name, "path":str(destination),
                                   "evidence_id":evidence.get("evidence_id"), "isError":raw.get("isError", False)}
                        if name in {"resolve_containing_procedure", "xrefs", "open_binary"}:
                            summary["result"] = norm
                        if name == "analyze_function" and isinstance(norm, dict):
                            summary["procedure"] = norm.get("procedure")
                            summary["pseudocode_chars"] = len(norm.get("pseudocode", ""))
                        print(json.dumps(summary, ensure_ascii=False), flush=True)
                        count += 1
                        if name == "close_binary":
                            return
                finally:
                    if name != "close_binary":
                        await session.call_tool("close_binary", {})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--inbox", type=Path, help="Optional request directory for non-interactive exec sessions")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(run(args.out, args.plan, args.inbox))
