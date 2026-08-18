from __future__ import annotations

import json
from pathlib import Path

from san11agent.cli import main

FIXTURES = Path(__file__).resolve().parent / "fixtures"
OFFSETS_TEST = FIXTURES / "offsets_test.json"
DUMP_TEST = FIXTURES / "synthetic_dump.json"


def test_snapshot_json_mode(capsys):
    code = main(["snapshot", "--offsets", str(OFFSETS_TEST), "--dump", str(DUMP_TEST)])
    assert code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["global_state"]["scenario_id"] == 3
    assert len(payload["generals"]) == 2
    assert payload["generals"][0]["name"] == "曹操"


def test_snapshot_summary_mode(capsys):
    code = main(["snapshot", "--offsets", str(OFFSETS_TEST), "--dump", str(DUMP_TEST), "--summary"])
    assert code == 0
    out = capsys.readouterr().out
    assert "剧本 3" in out
    assert "许昌" in out


def test_snapshot_requires_dump_or_process(capsys):
    try:
        main(["snapshot", "--offsets", str(OFFSETS_TEST)])
        assert False, "应该抛出 SystemExit"
    except SystemExit as exc:
        assert exc.code != 0
