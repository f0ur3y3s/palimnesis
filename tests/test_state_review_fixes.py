"""Phase 4A review fixes (D106): provenance never changes what the model sees.

The protocol review of S0–S7 found that archiving a refresh's output could veto its state
version: a lone surrogate in the reasoning (an emoji split across stream pieces, which
Strata produces) or any error while recording sources rolled the version back, so the
model lost a state phase-4b would have rendered. Outputs are now stored as WTF-8 bytes,
and outputs and sources are recorded under a savepoint whose failure is itself recorded.
The other findings are tested here too: turn files and block indices, the CLI's raw view
of notes taken from the reasoning, insert guards, the v6 to v7 migration, and ambiguous
and cross-session aliases."""

from __future__ import annotations

import json
import sqlite3

import pytest

from palimnesis.archive import addresses, ledger
from palimnesis.archive.store import Store
from palimnesis.cli import main
from palimnesis.view.builder import notes_block

from .archive_helpers import DONE, chunk
from .test_notes_http import BUDGET, _body, _messages, _notes_rows, _sent
from .test_notes_n2_http import _notes
from .test_view_http import SID, post, rows, view_stack

N2 = dict(input_budget=BUDGET, notes_tokens=2048, notes_format="n2")
NOTES = "Objective\nShip it.\nRequirements and constraints\n- keep tabs\nDead ends\n- none"


def test_a_split_surrogate_in_the_reasoning_keeps_the_state(tmp_path):
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_sse([chunk({"role": "assistant", "content": ""}),
                          chunk({"reasoning_content": "rocket \ud83d"}),
                          chunk({"reasoning_content": "\ude80 done"}),
                          chunk({"content": NOTES}), chunk({}, "stop"), DONE])
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    assert _notes_rows(s) == [(1, "committed", None, NOTES)]
    assert {"role": "user", "content": notes_block(1, NOTES)} in _sent(fake, 1)
    [(reasoning,)] = rows(s, "SELECT reasoning FROM notes_outputs")
    # The stream keeps the two halves as they came: two lone surrogates, not one emoji.
    assert reasoning.decode("utf-8", "surrogatepass") == "rocket " + chr(0xD83D) + chr(0xDE80) + " done"


def test_a_provenance_failure_never_vetoes_the_version(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("sources broke")

    monkeypatch.setattr(ledger, "record_state_sources", broken)
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_counted(NOTES)
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    assert _notes_rows(s) == [(1, "committed", None, NOTES)]
    assert {"role": "user", "content": notes_block(1, NOTES)} in _sent(fake, 1)
    assert rows(s, "SELECT count(*) FROM notes_outputs") == [(0,)]  # rolled back with it
    [(payload,)] = rows(s, "SELECT payload FROM events WHERE kind = 'notes_provenance_failed'")
    assert json.loads(payload)["error"] == "RuntimeError"


def test_turn_zero_and_block_indices_are_checked(tmp_path):
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_counted(NOTES + "\n- see turn-0000.md, turn-0001.md and turn-12345.md")
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    sources = rows(s, "SELECT token, status FROM notes_sources ORDER BY idx")
    assert sources == [("turn-0000", "valid"), ("turn-0001", "valid"), ("turn-12345", "unknown")]


def test_ambiguous_and_cross_session_aliases(tmp_path):
    db = tmp_path / "archive.db"
    Store.open(db).close()
    conn = sqlite3.connect(db)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)")]
        conn.execute("PRAGMA foreign_keys = OFF")
        for sid in ("one", "two"):
            values = {c: "x" for c in cols}
            values.update(session_id=sid, created_at=0.0)
            conn.execute(f"INSERT INTO sessions ({','.join(cols)}) VALUES "
                         f"({','.join('?' * len(cols))})", [values[c] for c in cols])
        conn.executemany("INSERT INTO aliases VALUES (?, ?, ?)", [
            ("one", "ABCDEF1", "occ_a"), ("one", "ABCDEF2", "occ_b"), ("two", "QQQQQQ", "occ_c")])
        assert isinstance(addresses.resolve(conn, "one", "ABCDEF"), addresses.Ambiguous)
        assert isinstance(addresses.resolve(conn, "one", "QQQQQQ"), addresses.Unknown)
        assert ledger.source_status(conn, "one", "alias", "ABCDEF", turns=0) == ("ambiguous", None)
        assert ledger.source_status(conn, "one", "alias", "QQQQQQ", turns=0) == ("unknown", None)
    finally:
        conn.close()


def test_a_cited_block_must_exist(tmp_path):
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_counted(NOTES)
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200
    conn = sqlite3.connect(f"file:{s.db_path}?mode=ro", uri=True)
    try:
        session = conn.execute("SELECT session_id FROM sessions").fetchone()[0]
        alias, target = conn.execute(
            "SELECT a.alias, a.target_id FROM aliases a JOIN blocks b ON b.occ_id = a.target_id"
            " LIMIT 1").fetchone()
        assert ledger.source_status(conn, session, "alias", f"{alias}.0", turns=0) == ("valid", target)
        assert ledger.source_status(conn, session, "alias", f"{alias}.99", turns=0) == ("unknown", target)
    finally:
        conn.close()


def test_state_cli_raw_shows_the_reasoning_draft_for_notes_from_reasoning(tmp_path, capsys):
    draft = _notes(60)
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_sse([chunk({"role": "assistant", "content": ""}),
                          chunk({"reasoning_content": "Drafting.\n" + draft}),
                          chunk({}, "stop"), DONE])
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    assert main(["state", SID, "--db", str(s.db_path), "--version", "1", "--raw"]) == 0
    out = capsys.readouterr().out
    cut = [l for l in out.splitlines() if l.endswith("(cut)")]
    assert any("dead fact 59" in l for l in cut)
    assert not any("Drafting." in l for l in out.splitlines()[:3])


def test_state_cli_flags_need_a_version(tmp_path, capsys):
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_counted(NOTES)
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200
    assert main(["state", SID, "--db", str(s.db_path), "--raw"]) == 2


@pytest.mark.parametrize("table", ["notes_outputs", "notes_sources"])
def test_insert_or_replace_is_refused(tmp_path, table):
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_counted(NOTES + "\n- turn-0001")
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200
    conn = sqlite3.connect(s.db_path)
    try:
        row = conn.execute(f"SELECT * FROM {table} LIMIT 1").fetchone()
        assert row is not None
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(f"INSERT OR REPLACE INTO {table} VALUES ({','.join('?' * len(row))})", row)
        for statement in (f"UPDATE {table} SET notes_id = notes_id", f"DELETE FROM {table}"):
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(statement)
    finally:
        conn.close()


def test_a_v6_archive_migrates_and_keeps_its_notes(tmp_path):
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_counted(NOTES)
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200
    raw = sqlite3.connect(s.db_path)  # an archive written before migration 7
    raw.execute("DROP TABLE notes_sources")
    raw.execute("DROP TABLE notes_outputs")
    raw.execute("PRAGMA user_version = 6")
    raw.commit()
    raw.close()

    Store.open(s.db_path).close()
    conn = sqlite3.connect(s.db_path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
        assert conn.execute("SELECT status, text FROM notes_versions").fetchall() == [("committed", NOTES)]
        assert conn.execute("SELECT count(*) FROM notes_outputs").fetchone()[0] == 0
    finally:
        conn.close()


def test_state_cli_on_a_v6_archive_says_so(tmp_path, capsys):
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_counted(NOTES)
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200
    raw = sqlite3.connect(s.db_path)
    raw.execute("DROP TABLE notes_sources")
    raw.execute("DROP TABLE notes_outputs")
    raw.commit()
    raw.close()
    assert main(["state", SID, "--db", str(s.db_path)]) == 2
    assert "migrate" in capsys.readouterr().err
