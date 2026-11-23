"""Phase 8 S9: archive operations (plan §1.5, contracts §11 and §14, D133).

``palimnesis export / delete / backup / restore`` and ``check --archive``, and the
migration guard: exact bytes round-trip through export; delete cascades through every
table, the full-text indexes and the transcript directory, and is refused while a proxy
serves the archive or while a fork depends on the session; backup is consistent while a
stream is running; restore validates before it replaces anything; an archive newer than
the code is refused; every historical schema migrates forward."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

import httpx
import pytest

from palimnesis.api import create_app
from palimnesis.archive import integrity, ops, store
from palimnesis.archive.store import Store, StoreError
from palimnesis.cli import main
from palimnesis.config import Settings
from palimnesis.transcripts import projector

from .archive_helpers import DONE, answer, assistant, body, chunk, user
from .fake_upstream import FakeUpstream
from .servers import serve

A, B = "ses_a", "ses_b"


def _post(url, session, payload):
    with httpx.stream("POST", f"{url}/s/{session}/v1/chat/completions", content=payload,
                      timeout=30) as r:
        r.read()
    return r


def _archive(tmp_path) -> tuple[Path, dict[str, bytes]]:
    """Two sessions, two turns each, with transcripts; returns the db and the bodies sent."""
    fake = FakeUpstream()
    db, sent = tmp_path / "archive.db", {}
    with serve(fake.app()) as up:
        s = Settings(upstream_base_url=up, db_path=db, transcripts=tmp_path / "t")
        with serve(create_app(s), palimnesis=True) as url:
            for sid in (A, B):
                fake.respond_sse(answer(f"{sid} one"))
                p1 = body([user(f"{sid} first é中")])
                assert _post(url, sid, p1).status_code == 200
                fake.respond_sse(answer(f"{sid} two"))
                p2 = body([user(f"{sid} first é中"), assistant(f"{sid} one"), user("next")])
                assert _post(url, sid, p2).status_code == 200
                sent[sid] = [p1, p2]
            deadline = time.monotonic() + 10
            while (projector.interrupted_sessions(tmp_path / "t")
                   or not (projector.session_dir(tmp_path / "t", B) / "index.md").exists()):
                assert time.monotonic() < deadline
                time.sleep(0.1)
    return db, sent


def _ids(db, session) -> set[str]:
    c = sqlite3.connect(db)
    try:
        b = f"{session}/main" if False else c.execute(
            "SELECT branch_id FROM branches WHERE session_id = ?", (session,)).fetchone()[0]
        ids = {session, b}
        for sql in ("SELECT request_id FROM requests WHERE session_id = ?",
                    "SELECT occ_id FROM occurrences WHERE branch_id = ?"):
            ids |= {r[0] for r in c.execute(sql, (session if "requests" in sql else b,))}
        return ids
    finally:
        c.close()


def _mentions(db, ids: set[str]) -> list[str]:
    """Every table cell, in any table, equal to one of ``ids``."""
    c = sqlite3.connect(db)
    out = []
    try:
        for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'"
                              " AND name NOT LIKE 'fts_%' AND name NOT LIKE 'sqlite_%'"):
            cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
            for col in cols:
                n = c.execute(f'SELECT count(*) FROM "{t}" WHERE "{col}" IN ({",".join("?" * len(ids))})',
                              tuple(ids)).fetchone()[0]
                if n:
                    out.append(f"{t}.{col}: {n}")
    finally:
        c.close()
    return out


# --- export -------------------------------------------------------------------------------

def test_export_round_trips_exact_bytes_with_their_hashes(tmp_path):
    db, sent = _archive(tmp_path)
    out = tmp_path / "a.jsonl"
    assert main(["export", A, str(out), "--db", str(db)]) == 0
    lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    kinds = [x["type"] for x in lines]
    assert kinds[0] == "session" and kinds.count("request") == 2
    reqs = [x for x in lines if x["type"] == "request"]
    assert [base64.b64decode(r["body_b64"]) for r in reqs] == sent[A]
    assert all(hashlib.sha256(base64.b64decode(r["body_b64"])).hexdigest() == r["body_sha256"]
               for r in reqs)
    occs = [x for x in lines if x["type"] == "occurrence"]
    c = sqlite3.connect(db)
    try:
        for o in occs:
            for b in o["blocks"]:
                raw = base64.b64decode(b["bytes_b64"])
                assert hashlib.sha256(raw).hexdigest() == b["sha256"]
                stored = b"".join(r[0] for r in c.execute(
                    "SELECT s.bytes FROM segments s JOIN blocks k ON k.block_id = s.block_id"
                    " WHERE k.occ_id = ? AND k.idx = ? ORDER BY s.seq", (o["occ_id"], b["idx"])))
                assert raw == stored
    finally:
        c.close()
    assert any("é中" in base64.b64decode(b["bytes_b64"]).decode() for o in occs for b in o["blocks"])
    assert B not in out.read_text(encoding="utf-8")


def test_export_of_an_unknown_session_fails(tmp_path):
    db, _ = _archive(tmp_path)
    assert main(["export", "ses_none", str(tmp_path / "x.jsonl"), "--db", str(db)]) != 0


# --- delete -------------------------------------------------------------------------------

def test_delete_cascades_everywhere_and_leaves_the_other_session_whole(tmp_path):
    db, _ = _archive(tmp_path)
    gone = _ids(db, A)
    kept_before = _mentions(db, _ids(db, B))
    assert main(["delete", A, "--yes", "--db", str(db), "--root", str(tmp_path / "t")]) == 0
    assert _mentions(db, gone) == []
    assert _mentions(db, _ids(db, B)) == kept_before
    c = sqlite3.connect(db)
    try:
        assert integrity.check(c) == []  # indexes equal a rebuild: A's text is gone from FTS
        assert c.execute("SELECT count(*) FROM fts_blocks WHERE fts_blocks MATCH 'ses_a'").fetchone()[0] == 0
    finally:
        c.close()
    assert not projector.session_dir(tmp_path / "t", A).exists()
    assert projector.session_dir(tmp_path / "t", B).exists()
    with pytest.raises(StoreError):  # triggers are back: rows stay immutable
        c = sqlite3.connect(db)
        try:
            try:
                c.execute("DELETE FROM sessions")
            except sqlite3.DatabaseError as e:
                raise StoreError(str(e))
        finally:
            c.close()


def test_delete_needs_yes_and_is_refused_while_a_proxy_serves(tmp_path):
    db, _ = _archive(tmp_path)
    assert main(["delete", A, "--db", str(db)]) != 0  # no --yes
    held = Store.open(db)  # the running proxy's lock
    try:
        assert main(["delete", A, "--yes", "--db", str(db)]) != 0
    finally:
        held.close()
    assert _mentions(db, {A})


def test_delete_is_refused_while_a_fork_depends_on_the_session(tmp_path):
    db, _ = _archive(tmp_path)
    fake = FakeUpstream()
    with serve(fake.app()) as up:
        s = Settings(upstream_base_url=up, db_path=db, transcripts=tmp_path / "t")
        with serve(create_app(s), palimnesis=True) as url:
            assert httpx.post(f"{url}/palimnesis/sessions/{A}/fork", json={"at_turn": 1,
                              "session": "ses_f"}, timeout=30).status_code == 200
    assert main(["delete", A, "--yes", "--db", str(db)]) != 0
    assert main(["delete", "ses_f", "--yes", "--db", str(db)]) == 0  # the fork first
    assert main(["delete", A, "--yes", "--db", str(db)]) == 0
    c = sqlite3.connect(db)
    try:
        assert integrity.check(c) == []
    finally:
        c.close()


# --- backup and restore -------------------------------------------------------------------

def test_a_backup_taken_during_a_stream_is_consistent(tmp_path):
    db, _ = _archive(tmp_path)
    fake = FakeUpstream()
    dest = tmp_path / "backup.db"
    with serve(fake.app()) as up:
        s = Settings(upstream_base_url=up, db_path=db, transcripts=tmp_path / "t")
        with serve(create_app(s), palimnesis=True) as url:
            fake.respond_sse([chunk({"role": "assistant", "content": ""})]
                             + [(0.05, chunk({"content": f"w{i} "})) for i in range(30)]
                             + [chunk({}, "stop"), DONE])
            t = threading.Thread(target=lambda: _post(url, "ses_c", body([user("stream")])))
            t.start()
            time.sleep(0.6)  # mid-stream
            assert main(["backup", str(dest), "--db", str(db)]) == 0
            t.join(timeout=30)
    c = sqlite3.connect(dest)
    try:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        c.close()
    # The copy holds the stream in flight, as a crash would; restoring it recovers it.
    restored = tmp_path / "restored.db"
    assert main(["restore", str(dest), "--db", str(restored), "--root", str(tmp_path / "t2")]) == 0
    c = sqlite3.connect(restored)
    try:
        assert integrity.check(c) == []
        assert c.execute("SELECT count(*) FROM events WHERE kind = 'attempt_abandoned'").fetchone()[0] == 1
    finally:
        c.close()


def test_restore_validates_then_replaces_and_rebuilds_the_transcripts(tmp_path):
    db, _ = _archive(tmp_path)
    good = tmp_path / "good.db"
    assert main(["backup", str(good), "--db", str(db)]) == 0
    main(["delete", A, "--yes", "--db", str(db), "--root", str(tmp_path / "t")])
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a database" * 100)
    assert main(["restore", str(bad), "--db", str(db), "--root", str(tmp_path / "t")]) != 0
    assert _mentions(db, {A}) == []  # nothing replaced
    held = Store.open(db)
    try:
        assert main(["restore", str(good), "--db", str(db), "--root", str(tmp_path / "t")]) != 0
    finally:
        held.close()
    assert main(["restore", str(good), "--db", str(db), "--root", str(tmp_path / "t")]) == 0
    assert _mentions(db, {A})
    assert main(["transcripts", "verify", A, "--db", str(db), "--root", str(tmp_path / "t")]) == 0
    assert main(["check", "--archive", "--db", str(db)]) == 0


# --- schema versions ----------------------------------------------------------------------

def test_an_archive_newer_than_the_code_is_refused(tmp_path):
    db = tmp_path / "new.db"
    Store.open(db).close()
    c = sqlite3.connect(db)
    c.execute(f"PRAGMA user_version = {len(store.MIGRATIONS) + 1}")
    c.close()
    with pytest.raises(StoreError, match="newer"):
        Store.open(db)
    with pytest.raises(StoreError, match="newer"):
        ops.restore(db, tmp_path / "other.db", root=tmp_path / "t")


@pytest.mark.parametrize("version", range(1, len(store.MIGRATIONS)))
def test_every_historical_schema_migrates_forward(version, tmp_path):
    path = tmp_path / f"v{version}.db"
    conn = sqlite3.connect(path, isolation_level=None)
    for migration in store.MIGRATIONS[:version]:
        script, backfill = migration if isinstance(migration, tuple) else (migration, None)
        for statement in store._split_statements(script):
            conn.execute(statement)
    conn.execute(f"PRAGMA user_version = {version}")
    conn.execute("INSERT INTO sessions VALUES ('s', 1.0, 'path')")
    conn.execute("INSERT INTO branches VALUES ('s/main', 's', NULL, NULL, 1.0)")
    conn.execute("INSERT INTO occurrences VALUES ('o', 's/main', 1, NULL, 'user', 'both',"
                 " 'client', NULL, NULL, '{}', 'h')")
    conn.execute("INSERT INTO blocks VALUES ('b', 'o', 0, 'text', 'utf-8', '{}')")
    conn.execute("INSERT INTO segments VALUES ('b', 0, CAST('hello' AS BLOB))")
    conn.close()
    Store.open(path).close()
    c = sqlite3.connect(path)
    try:
        assert c.execute("PRAGMA user_version").fetchone()[0] == len(store.MIGRATIONS)
        assert c.execute("SELECT CAST(bytes AS TEXT) FROM segments").fetchall() == [("hello",)]
    finally:
        c.close()
