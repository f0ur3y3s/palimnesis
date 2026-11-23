"""Phase 8 S8: failure modes and limits (plan §1.5, contracts §5 and §8, U8, D132).

- 413 ``request_too_large`` before acceptance for a body over ``max_body_bytes``;
- 507 ``archive_full`` before acceptance when the archive's volume has less free space than
  ``min_free_bytes``;
- a full archive after acceptance (``PALIMNESIS_MAX_PAGE_COUNT``) takes the
  ``archive_unavailable`` paths and keeps the accepted history;
- a full disk during transcript publication never fails a request, and the publication is
  done again at the next start;
- a slot held by other work past the ceiling marks the upstream unhealthy: 503
  ``upstream_unhealthy`` until it is idle again."""

from __future__ import annotations

import errno
import json
import sqlite3
import time

import httpx
import pytest

from palimnesis.api import create_app
from palimnesis.archive import integrity
from palimnesis.config import Settings
from palimnesis.transcripts import projector

from .archive_helpers import DONE, answer, assistant, body, chunk, user
from .fake_upstream import FakeUpstream
from .servers import serve
from .test_messages_http import anthropic_error, mbody, mpost

SID = "ses_limits"


def _stack(tmp_path, **kw):
    fake = FakeUpstream()
    up = serve(fake.app())
    return fake, up, kw


def _post(url, payload, session=SID, headers=None, timeout=30) -> httpx.Response:
    with httpx.stream("POST", f"{url}/s/{session}/v1/chat/completions", content=payload,
                      headers=headers, timeout=timeout) as r:
        r.read()
    return r


def _rows(db, sql, *args):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def _app(up, tmp_path, **kw):
    s = Settings(upstream_base_url=up, db_path=tmp_path / "archive.db", **kw)
    return s, serve(create_app(s), palimnesis=True)


# --- 413 ---------------------------------------------------------------------------------

def test_an_oversized_body_is_413_before_acceptance_on_both_protocols(tmp_path):
    fake = FakeUpstream()
    big = "x" * 5000
    with serve(fake.app()) as up:
        s, proxy = _app(up, tmp_path, max_body_bytes=4096)
        with proxy as url:
            chat = _post(url, body([user(big)]))
            msgs = mpost(url, mbody([{"role": "user", "content": big}]))
            small = (fake.respond_sse(answer("ok")), _post(url, body([user("hi")])))[1]
    assert chat.status_code == 413 and chat.json()["error"]["code"] == "request_too_large"
    assert chat.headers["x-should-retry"] == "false"
    anthropic_error(msgs, 413, "request_too_large")
    assert small.status_code == 200
    assert len(fake.requests) == 1  # only the small one
    assert _rows(s.db_path, "SELECT count(*) FROM requests") == [(1,)]


def test_an_oversized_body_without_content_length_is_413_while_it_streams(tmp_path):
    fake = FakeUpstream()
    with serve(fake.app()) as up:
        s, proxy = _app(up, tmp_path, max_body_bytes=4096)
        with proxy as url:
            def gen():
                payload = body([user("y" * 9000)])
                for i in range(0, len(payload), 1000):
                    yield payload[i:i + 1000]
            r = httpx.post(f"{url}/s/{SID}/v1/chat/completions", content=gen(), timeout=30)
    assert r.status_code == 413 and r.json()["error"]["code"] == "request_too_large"
    assert fake.requests == []


# --- 507 ---------------------------------------------------------------------------------

def test_too_little_free_disk_is_507_before_acceptance(tmp_path):
    fake = FakeUpstream()
    with serve(fake.app()) as up:
        s, proxy = _app(up, tmp_path, min_free_bytes=10 ** 18)  # more than any disk has
        with proxy as url:
            r = _post(url, body([user("hi")]))
            m = mpost(url, mbody([{"role": "user", "content": "hi"}]))
    assert r.status_code == 507 and r.json()["error"]["code"] == "archive_full"
    assert r.headers["x-should-retry"] == "false"
    anthropic_error(m, 507, "archive_full")
    assert fake.requests == []
    assert _rows(s.db_path, "SELECT count(*) FROM requests") == [(0,)]


# --- a full archive after acceptance ------------------------------------------------------

def test_a_full_archive_after_acceptance_keeps_the_accepted_history(tmp_path, monkeypatch):
    fake = FakeUpstream()
    with serve(fake.app()) as up:
        s, proxy = _app(up, tmp_path)
        with proxy as url:
            fake.respond_sse(answer("A1"))
            assert _post(url, body([user("U1")])).status_code == 200
        pages = _rows(s.db_path, "PRAGMA page_count")[0][0]
        monkeypatch.setenv("PALIMNESIS_MAX_PAGE_COUNT", str(pages + 2))
        s, proxy = _app(up, tmp_path)
        with proxy as url:
            fake.respond_sse([chunk({"role": "assistant", "content": ""})]
                             + [chunk({"content": "z" * 4000}) for _ in range(40)]
                             + [chunk({}, "stop"), DONE])
            r = _post(url, body([user("U1"), assistant("A1"), user("U2 " + "q" * 3000)]))
    assert r.status_code in (200, 503), r.text[:300]
    if r.status_code == 503:
        assert r.json()["error"]["code"] == "archive_unavailable"
    else:
        assert b"archive_unavailable" in r.content  # the in-stream error, never success
        assert b"[DONE]" not in r.content
    monkeypatch.delenv("PALIMNESIS_MAX_PAGE_COUNT")
    c = sqlite3.connect(s.db_path)
    try:
        assert integrity.check(c) == []
        texts = [t for (t,) in c.execute(
            "SELECT CAST(s.bytes AS TEXT) FROM segments s JOIN blocks b ON b.block_id = s.block_id"
            " JOIN occurrences o ON o.occ_id = b.occ_id ORDER BY o.seq, b.idx, s.seq")]
    finally:
        c.close()
    assert texts[:2] == ["U1", "A1"]  # the earlier history is intact


# --- projection ENOSPC --------------------------------------------------------------------

def test_a_full_disk_during_publication_never_fails_the_request(tmp_path, monkeypatch):
    def full(self, data):
        raise OSError(errno.ENOSPC, "No space left on device")

    fake = FakeUpstream()
    with serve(fake.app()) as up:
        monkeypatch.setattr(projector._Writer, "_stage", full)
        s, proxy = _app(up, tmp_path, transcripts=tmp_path / "t")
        with proxy as url:
            fake.respond_sse(answer("A1"))
            r = _post(url, body([user("U1")]))
            time.sleep(1.0)  # the projector runs in the background
        monkeypatch.undo()
        assert r.status_code == 200
        assert projector.interrupted_sessions(tmp_path / "t") == [SID]
        s, proxy = _app(up, tmp_path, transcripts=tmp_path / "t")
        with proxy as url:  # the next start publishes it again
            deadline = time.monotonic() + 10
            while projector.interrupted_sessions(tmp_path / "t") and time.monotonic() < deadline:
                time.sleep(0.1)
    assert projector.interrupted_sessions(tmp_path / "t") == []
    assert (projector.session_dir(tmp_path / "t", SID) / "manifest.json").exists()


# --- the slot ceiling ---------------------------------------------------------------------

def test_a_slot_held_past_the_ceiling_marks_the_upstream_unhealthy(tmp_path):
    fake = FakeUpstream()
    fake.props_body = None
    with serve(fake.app()) as up:
        s, proxy = _app(up, tmp_path, slot_ceiling_s=0.5, input_budget=8000)
        with proxy as url:
            fake.status_busy = True  # another client's work never ends
            r1 = _post(url, body([user("U1")]))
            r2 = _post(url, body([user("U1")]), session="ses_other")
            fake.status_busy = False  # it ends: dispatch resumes
            fake.respond_sse(answer("A"))
            r3 = _post(url, body([user("U3")]), session="ses_third")
    for r in (r1, r2):
        assert r.status_code == 503 and r.json()["error"]["code"] == "upstream_unhealthy", r.text[:300]
        assert r.headers["x-should-retry"] == "false"
    assert r3.status_code == 200
    assert len([q for q in fake.requests if q.path.endswith("/chat/completions")]) == 1
