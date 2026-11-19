"""Phase 4A S6: ``palimnesis state SESSION`` inspects a session's pinned state, read-only.

Each version with its status, reason, cutoff and cut; ``--version N`` prints one
version's text, ``--raw`` its whole archived output with the lines the cut left out
marked, ``--sources`` the addresses it cites; ``--json`` the same as data."""

from __future__ import annotations

import json
import sqlite3

from palimnesis.cli import main

from .test_notes_n2_http import _notes
from .test_notes_http import BUDGET, _body, _messages
from .test_state_golden import scenario
from .test_view_http import SID, post, view_stack


def _run(capsys, *args) -> tuple[int, str]:
    code = main(["state", SID, *args])
    return code, capsys.readouterr().out


def test_state_cli_lists_versions_with_status_reason_cutoff(tmp_path, capsys):
    scenario(tmp_path)
    code, out = _run(capsys, "--db", str(tmp_path / "archive.db"))
    assert code == 0
    lines = [l for l in out.splitlines() if l.startswith("v")]
    assert len(lines) == 2
    assert all("committed" in l and "cutoff" in l and "#notes" in l for l in lines)
    assert "from_reasoning" in lines[0] and "sources 2" in lines[0]


def test_state_cli_prints_one_version_and_its_raw_output(tmp_path, capsys):
    reply = _notes(60)
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048, notes_format="n2") as (
            fake, url, s):
        fake.respond_counted(reply)
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    code, text = _run(capsys, "--db", str(s.db_path), "--version", "1")
    assert code == 0 and "- dead fact 0" in text and "- dead fact 59" not in text
    code, raw = _run(capsys, "--db", str(s.db_path), "--version", "1", "--raw")
    assert code == 0 and "- dead fact 59" in raw
    dropped = [l for l in raw.splitlines() if l.startswith("- ") and "(cut)" in l]
    kept = [l for l in raw.splitlines() if l.startswith("  ")]
    assert dropped and kept and any("dead fact 59" in l for l in dropped)


def test_state_cli_sources_and_json(tmp_path, capsys):
    scenario(tmp_path)
    db = str(tmp_path / "archive.db")
    code, out = _run(capsys, "--db", db, "--json")
    assert code == 0
    data = json.loads(out)
    assert [v["n"] for v in data["versions"]] == [1, 2]
    assert {"status", "reason", "call_id", "archive_seq", "cut_lines", "sources"} <= set(
        data["versions"][0])
    code, out = _run(capsys, "--db", db, "--version", "2", "--sources")
    assert code == 0


def test_state_cli_opens_read_only(tmp_path, capsys):
    scenario(tmp_path)
    db = tmp_path / "archive.db"
    before = db.stat().st_mtime_ns
    assert _run(capsys, "--db", str(db))[0] == 0
    assert db.stat().st_mtime_ns == before
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT count(*) FROM notes_versions").fetchone()[0] == 2
    finally:
        conn.close()


def test_state_cli_unknown_version_is_an_error(tmp_path, capsys):
    scenario(tmp_path)
    assert _run(capsys, "--db", str(tmp_path / "archive.db"), "--version", "9")[0] == 2
