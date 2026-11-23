"""The archive integrity checker (Phase 8 S7, D131): sound archives pass, and each kind of
damage a crash or a bug could leave is named."""

from __future__ import annotations

import json
import sqlite3

import httpx

from palimnesis.archive import integrity

from .archive_helpers import answer, assistant, body, lifecycle_stack, user
from .test_hidden_loop_http import GREP, _masked, _post, view_stack
from .test_view_http import SID as VIEW_SID


def _check(db) -> list[str]:
    c = sqlite3.connect(db)
    try:
        return integrity.check(c)
    finally:
        c.close()


def _archive(tmp_path):
    with lifecycle_stack(tmp_path) as lc:
        lc.upstream.respond_sse(answer("A1"))
        assert lc.post("s1", body([user("U1 alpha")])).status_code == 200
        lc.upstream.respond_sse(answer("A2 beta"))
        assert lc.post("s1", body([user("U1 alpha"), assistant("A1"), user("U2")])).status_code == 200
        assert httpx.post(f"{lc.proxy_url}/palimnesis/sessions/s1/fork", json={"at_turn": 1},
                          timeout=30).status_code == 200
    return tmp_path / "archive.db"


def test_a_sound_archive_with_a_fork_passes(tmp_path):
    assert _check(_archive(tmp_path)) == []


def test_a_forked_hidden_loop_archive_passes_internal_results_stay_unindexed(tmp_path):
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, settings):
        fake.respond_turn("Checking. ", calls=[GREP])
        fake.respond_turn("It is in read 3.")
        assert _post(url, _masked()).status_code == 200
        assert httpx.post(f"{url}/palimnesis/sessions/{VIEW_SID}/fork", json={"at_turn": 2},
                          timeout=30).status_code == 200
    assert _check(settings.db_path) == []


def _damage(db, *sql):
    c = sqlite3.connect(db)
    for s in sql:
        c.execute(s)
    c.commit()
    c.close()


def test_a_missing_index_entry_is_named(tmp_path):
    db = _archive(tmp_path)
    _damage(db, "DELETE FROM fts_blocks WHERE rowid = (SELECT max(rowid) FROM blocks)")
    assert "fts_blocks differs from a rebuild" in _check(db)


def test_a_missing_chunk_is_named(tmp_path):
    db = _archive(tmp_path)
    _damage(db, "DELETE FROM chunk_map WHERE rowid = (SELECT max(rowid) FROM chunk_map)")
    assert "chunk_map differs from a rebuild" in _check(db)


def test_a_branch_left_active_is_named(tmp_path):
    db = _archive(tmp_path)
    _damage(db, "UPDATE branch_heads SET active_request_id = 'req_x' WHERE branch_id ="
                " (SELECT min(branch_id) FROM branch_heads)")
    assert any("has active request req_x" in p for p in _check(db))


def test_attempts_need_exactly_one_terminal_event(tmp_path):
    db = _archive(tmp_path)
    c = sqlite3.connect(db)
    att, req = c.execute("SELECT attempt_id, request_id FROM attempts LIMIT 1").fetchone()
    c.execute("INSERT INTO events (request_id, attempt_id, kind, payload, at)"
              " VALUES (?, ?, 'cancelled', '{}', 0)", (req, att))
    c.execute("INSERT INTO attempts VALUES ('att_orphan', ?, 99, 0)", (req,))
    c.commit()
    c.close()
    got = _check(db)
    assert f"attempt {att} has 2 terminal events" in got
    assert "attempt att_orphan has no terminal event" in got
    assert json  # noqa: imported for symmetry with other archive tests
