"""Excerpt selection on the archive path (A1 Phase 2 slice E): persisted before
inference, frozen across retries and restarts, never harness-visible."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

import httpx
import pytest

from palimnesis.api import create_app
from palimnesis.config import Settings
from palimnesis.excerpts import Selection, SelectedExcerpt
from palimnesis.ledger import branch_id_for, load_archived

from .fake_upstream import FakeUpstream
from .servers import serve

SID = "exc-1"
DONE = (b'data: {"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n")


class SeededExcerpts:
    """Selects the session's first user message as evidence for every new instruction."""

    query_version = "seed"
    retrieval_version = "seed"

    def __init__(self):
        self.calls = 0

    async def select(self, plan, base_view, allocation):
        self.calls += 1
        first = next((i for i in plan.items if i.message.get("role") == "user"), None)
        if first is None or first.occ_id is None or allocation <= 0:
            return Selection("", "seed", "seed", 0, ())
        text = first.message["content"]
        return Selection(query="seeded", query_version="seed", retrieval_version="seed",
                         archive_cutoff_seq=first.seq or 0, items=(SelectedExcerpt(
                             rank=1, score=1.0, source_occ_id=first.occ_id,
                             source_alias=first.alias, source_block=0, start=0, end=len(text),
                             source_sha256="0" * 64, turn_number=1, role="user", tool_name=None,
                             text=text),))


@contextmanager
def stack(tmp_path, source, fake=None):
    fake = fake or FakeUpstream()
    with serve(fake.app()) as upstream_url:
        s = Settings(upstream_base_url=upstream_url, db_path=tmp_path / "archive.db",
                     excerpt_source=source)
        with serve(create_app(s), palimnesis=True) as url:
            yield fake, url, s


def post(url, messages, **extra):
    data = json.dumps({"model": "m", "stream": True, "max_completion_tokens": 8192,
                       "messages": messages, **extra}).encode()
    with httpx.stream("POST", f"{url}/s/{SID}/v1/chat/completions", content=data, timeout=30) as r:
        r.read()
    return r


def rows(settings, sql):
    c = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


FIRST = [{"role": "user", "content": "use tabs, never spaces"}]
SECOND = FIRST + [{"role": "assistant", "content": "ok"}, {"role": "user", "content": "now indent it"}]


def test_the_upstream_sees_the_block_but_the_archive_and_client_do_not(tmp_path):
    source = SeededExcerpts()
    with stack(tmp_path, source) as (fake, url, settings):
        fake.respond_sse([DONE])
        post(url, FIRST)
        fake.respond_sse([DONE])
        r = post(url, SECOND)

    assert r.status_code == 200
    sent = json.loads(fake.requests[-1].body)["messages"]
    assert sent[-1]["content"].startswith("now indent it\n\n[palimnesis excerpts x1")
    assert "use tabs, never spaces" in sent[-1]["content"]
    assert b"palimnesis excerpts" not in r.content
    c = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    try:
        history = load_archived(c, branch_id_for(SID))
        user_texts = [c.execute("SELECT group_concat(CAST(s.bytes AS TEXT), '') FROM blocks b"
                                " JOIN segments s USING (block_id) WHERE b.occ_id = ?",
                                (a.occ_id,)).fetchone()[0] for a in history if a.role == "user"]
    finally:
        c.close()
    assert user_texts == ["use tabs, never spaces", "now indent it"]


def test_the_selection_is_committed_before_the_upstream_sees_the_request(tmp_path):
    import threading
    import time

    source = SeededExcerpts()
    with stack(tmp_path, source) as (fake, url, settings):
        fake.respond_sse([DONE])
        post(url, FIRST)
        fake.respond_sse([(1.5, DONE)])  # hold the response open
        before = len(fake.requests)
        worker = threading.Thread(target=post, args=(url, SECOND))
        worker.start()
        deadline = time.monotonic() + 10
        while len(fake.requests) == before and time.monotonic() < deadline:
            time.sleep(0.01)
        # The upstream has the request; its selection must already be durable.
        during = rows(settings, "SELECT status, token_charge FROM excerpt_blocks"
                                " ORDER BY created_at")
        worker.join()

    assert len(during) == 2
    assert during[-1][0] == "selected" and during[-1][1] > 0


def test_retries_and_restarts_reuse_the_stored_selection(tmp_path):
    source = SeededExcerpts()
    with stack(tmp_path, source) as (fake, url, settings):
        fake.respond_sse([DONE])
        post(url, FIRST)
        fake.respond_json(b'{"error":"busy"}', status=503)
        assert post(url, SECOND).status_code == 503
        calls = source.calls
        fake.respond_sse([DONE])
        assert post(url, SECOND).status_code == 200  # keyless retry, same request
        assert source.calls == calls
        first_body = fake.requests[-1].body

    restarted = SeededExcerpts()
    with stack(tmp_path, restarted) as (fake, url, settings):
        resend = SECOND + [{"role": "assistant", "content": "ok"}, {"role": "user", "content": "thanks"}]
        fake.respond_sse([DONE])
        assert post(url, resend).status_code == 200
        later = json.loads(fake.requests[-1].body)["messages"]

    assert restarted.calls == 1  # only the new "thanks" message
    assert later[2]["content"] == json.loads(first_body)["messages"][2]["content"]


def test_tool_result_requests_get_no_selection(tmp_path):
    source = SeededExcerpts()
    tool_turn = FIRST + [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function",
                                                              "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "result"}]
    tools = [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}]
    tool_answer = (b'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"c1",'
                   b'"type":"function","function":{"name":"f","arguments":"{}"}}]},'
                   b'"finish_reason":"tool_calls"}]}\n\ndata: [DONE]\n\n')
    with stack(tmp_path, source) as (fake, url, settings):
        fake.respond_sse([tool_answer])
        post(url, FIRST, tools=tools)
        calls = source.calls
        fake.respond_sse([DONE])
        assert post(url, tool_turn, tools=tools).status_code == 200

    assert source.calls == calls
    assert rows(settings, "SELECT count(*) FROM excerpt_blocks") == [(1,)]


def test_the_default_source_records_empty_selections_and_changes_nothing(tmp_path):
    with stack(tmp_path, None) as (fake, url, settings):
        fake.respond_sse([DONE])
        post(url, FIRST)
        fake.respond_sse([DONE])
        post(url, SECOND)

    assert [r[0] for r in rows(settings, "SELECT status FROM excerpt_blocks")] == ["empty", "empty"]
    assert "palimnesis excerpts" not in fake.requests[-1].body.decode()


def test_excerpt_text_is_not_full_text_indexed(tmp_path):
    from palimnesis.search import search_text

    with stack(tmp_path, SeededExcerpts()) as (fake, url, settings):
        fake.respond_sse([DONE])
        post(url, FIRST)
        fake.respond_sse([DONE])
        post(url, SECOND)

    c = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    try:
        assert search_text(c, "historical") == []
    finally:
        c.close()


class BrokenExcerpts:
    query_version = "broken"
    retrieval_version = "broken"

    async def select(self, plan, base_view, allocation):
        raise RuntimeError("retrieval bug")


def test_a_failing_excerpt_source_never_fails_the_request(tmp_path):
    with stack(tmp_path, BrokenExcerpts()) as (fake, url, settings):
        fake.respond_sse([DONE])
        r = post(url, FIRST)

    assert r.status_code == 200
    assert "palimnesis excerpts" not in fake.requests[-1].body.decode()
    assert rows(settings, "SELECT count(*) FROM excerpt_blocks") == [(0,)]
