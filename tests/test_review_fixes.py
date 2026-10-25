"""Regression tests for the Phase 1 independent review findings (items 1-7)."""

from __future__ import annotations

import json
import sqlite3
import time

import httpx
import pytest

from palimnesis import ledger
from palimnesis.ledger import branch_id_for, load_archived
from palimnesis.store import Store

from .archive_helpers import (
    CONTINUE_TEXT, DONE, answer, body, chunk, eventually, lifecycle_stack, sse_data, user,
)

SID = "review-1"


@pytest.fixture
def lc(tmp_path):
    with lifecycle_stack(tmp_path) as s:
        yield s


def history(lc, session=SID):
    with lc.db() as c:
        return load_archived(c, branch_id_for(session))


def error_events(r: httpx.Response) -> list[dict]:
    out = []
    for data in sse_data(r.content):
        try:
            obj = json.loads(data)
        except ValueError:
            continue
        if isinstance(obj, dict) and "error" in obj:
            out.append(obj["error"])
    return out


# 1. Upstream error event followed by [DONE] is a failure, not a completed turn.
def test_upstream_error_event_then_done_in_one_read_is_a_failed_partial(lc):
    upstream_error = b'data: {"error":{"message":"oom","type":"server_error"}}\n\n'
    lc.upstream.respond_sse([
        chunk({"role": "assistant", "content": "", "reasoning_content": "think"}),
        (0.2, chunk({"content": "par"})),
        (0.2, upstream_error + DONE),
    ])

    r = lc.post(SID, body([user("q")]))

    assert r.status_code == 200
    assert any(e.get("code") == "upstream_stream_failed" for e in error_events(r))
    [*_, partial] = history(lc)
    assert (partial.text, partial.reasoning, partial.complete) == ("par", "think", False)
    assert lc.events("turn_complete") == []

    # OpenCode's next turn resends the flattened partial; the session continues.
    lc.upstream.respond_sse(answer("ok"))
    follow = lc.post(SID, body([user("q"), {"role": "assistant", "content": "thinkpar",
                                             "reasoning_content": ""}, user("next")]))
    assert follow.status_code == 200, follow.content[:300]


# 2. A client that disconnects while its request is being accepted does not wedge the session.
def test_disconnect_during_accept_leaves_the_session_usable(lc, monkeypatch):
    real_accept = ledger.accept

    def slow_accept(conn, **kw):
        time.sleep(0.6)
        return real_accept(conn, **kw)

    monkeypatch.setattr(ledger, "accept", slow_accept)
    with pytest.raises(httpx.ReadTimeout):
        httpx.post(lc.url(SID), content=body([user("q")]), timeout=0.2)
    time.sleep(0.8)  # the accept transaction commits after the client left
    monkeypatch.setattr(ledger, "accept", real_accept)

    assert eventually(lambda: len(lc.events("cancelled")) == 1)
    lc.upstream.respond_sse(answer("A"))
    r = lc.post(SID, body([user("q")]))

    assert r.status_code == 200, r.content[:300]


# 3. A keyless retry of an old request after the branch moved on is not appended.
def test_stale_retry_after_the_branch_advanced_is_rejected(lc):
    lc.upstream.respond_json(b'{"error":"busy"}', status=503)
    first = lc.post(SID, body([user("U1")]))
    assert first.status_code == 503

    lc.upstream.respond_sse(answer("A2"))
    second = lc.post(SID, body([user("U1"), user("U2")]))
    assert second.status_code == 200

    stale = lc.post(SID, body([user("U1")]))

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "history_divergence"
    assert stale.headers["x-should-retry"] == "false"
    assert [a.role for a in history(lc)] == ["user", "user", "assistant"]
    assert len(lc.upstream.requests) == 2


# 4. A non-streaming commit failure is a shaped, non-retryable error.
def test_nonstream_commit_failure_is_shaped_and_not_retried(lc):
    no_id = json.dumps({"choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None,
        "tool_calls": [{"type": "function", "function": {"name": "f", "arguments": "{}"}}]}}]})
    lc.upstream.respond_json(no_id.encode())

    r = lc.post(SID, body([user("q")], stream=False))

    assert r.status_code in (502, 503)
    assert r.headers["x-should-retry"] == "false"
    assert "error" in r.json()
    assert len(lc.events("attempt_failed")) == 1
    assert lc.events("cancelled") == []


# 6. Lone surrogates in generated output round-trip and keep the session usable.
def test_lone_surrogate_in_generated_output_round_trips(lc):
    lc.upstream.respond_sse([b'data: {"choices":[{"index":0,"delta":{"content":"a\\ud83d"}}]}\n\n',
                             chunk({}, "stop"), DONE])

    r = lc.post(SID, body([user("q")]))

    assert r.status_code == 200 and error_events(r) == []
    assert history(lc)[-1].text == "a\ud83d"
    lc.upstream.respond_sse(answer("fine"))
    resend = json.dumps({"model": "m", "stream": True, "messages": [
        user("q"), {"role": "assistant", "content": "a\ud83d"}, user("next")]})
    follow = lc.post(SID, resend.encode("utf-8", "surrogatepass").replace(
        "\ud83d".encode("utf-8", "surrogatepass"), b"\\ud83d"))
    assert follow.status_code == 200, follow.content[:300]


# 7. Valid JSON that is not a chat chunk ends the stream with an error event, not a bare close.
@pytest.mark.parametrize("bad", [b"data: [1]\n\n", b'data: {"choices":[{"index":0,"delta":"x"}]}\n\n'])
def test_malformed_chunk_ends_with_an_error_event(lc, bad):
    lc.upstream.respond_sse([chunk({"role": "assistant", "content": "hi"}), (0.1, bad), DONE])

    r = lc.post(SID, body([user("q")]))

    assert r.status_code == 200
    assert error_events(r), r.content[-300:]
    assert lc.events("cancelled") == []
    assert len(lc.events("attempt_failed")) == 1


# Hardening: the archive path asks the upstream for an uncompressed body.
def test_archive_upstream_requests_ask_for_identity_encoding(lc):
    lc.upstream.respond_sse(answer("x"))

    lc.post(SID, body([user("q")]), headers={"accept-encoding": "gzip, br"})

    assert lc.upstream.requests[0].headers["accept-encoding"] == "identity"


# Hardening: only [DONE] may follow the finish chunk; a flood is a protocol error.
def test_events_after_the_finish_chunk_are_bounded(lc):
    flood = [chunk({}, "stop")] + [b": ping\n\n"] * 500 + [DONE]
    lc.upstream.respond_sse([chunk({"role": "assistant", "content": "x"}), (0.1, b"".join(flood))])

    r = lc.post(SID, body([user("q")]))

    assert error_events(r)
    assert lc.events("turn_complete") == []


# Migration: a v1 archive opened by this version gains a populated full-text index.
def test_v1_archive_migrates_and_indexes_existing_blocks(tmp_path):
    from palimnesis import store as store_module
    from palimnesis.search import search_text

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path, isolation_level=None)
    for statement in store_module._split_statements(store_module.MIGRATIONS[0]):
        conn.execute(statement)
    conn.execute("PRAGMA user_version = 1")
    conn.execute("INSERT INTO sessions VALUES ('s', 1.0, 'path')")
    conn.execute("INSERT INTO branches VALUES ('s/main', 's', NULL, NULL, 1.0)")
    conn.execute("INSERT INTO occurrences VALUES ('o', 's/main', 1, NULL, 'user', 'both',"
                 " 'client', NULL, NULL, '{}', 'h')")
    conn.execute("INSERT INTO blocks VALUES ('b', 'o', 0, 'text', 'utf-8', '{}')")
    conn.execute("INSERT INTO segments VALUES ('b', 0, CAST('legacy wording' AS BLOB))")
    conn.close()

    s = Store.open(path)
    try:
        import asyncio

        found = asyncio.run(s.read(lambda c: search_text(c, "legacy")))
    finally:
        s.close()

    assert found == ["legacy wording"]


def test_a_cancelled_partial_is_superseded_once_across_later_turns(lc):
    lc.upstream.respond_sse([chunk({"role": "assistant", "content": "", "reasoning_content": "hm"})]
                            + [(0.05, chunk({"reasoning_content": "m"}))] * 100)
    with httpx.stream("POST", lc.url(SID), content=body([user("q")]), timeout=30) as r:
        next(r.iter_raw())
    assert eventually(lambda: len(lc.events("cancelled")) == 1)

    for turn in range(2):
        lc.upstream.respond_sse(answer(f"A{turn}"))
        msgs = [user("q"), user("again")] + ([{"role": "assistant", "content": "A0"}, user("more")]
                                              if turn else [])
        r = lc.post(SID, body(msgs))
        assert r.status_code == 200, r.content[:300]

    assert len(lc.events("partial_superseded")) == 1
