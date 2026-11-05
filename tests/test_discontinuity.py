"""Compaction is a discontinuity, detected structurally (Phase 4B S8; plan §2.6, O-4B-6).

A harness's own compaction rewrites the history it resends. Palimnesis never matches on
summary text: reconciliation compares position by position, so a rewritten history is a
409 ``history_divergence`` and is never merged, while the same words inside an ordinary
turn are just content. These tests replay recorded harness bodies (``eval/probes/
fixtures``) through the proxy.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

import httpx

from palimnesis.api import create_app
from palimnesis.config import Settings

from .archive_helpers import answer
from .fake_upstream import FakeUpstream
from .harness_replay import next_answer, pi_compat, recorded
from .servers import serve

@contextmanager
def stack(tmp_path, **settings):
    fake = FakeUpstream()
    with serve(fake.app()) as upstream_url:
        s = Settings(upstream_base_url=upstream_url, db_path=tmp_path / "archive.db", **settings)
        with serve(create_app(s), palimnesis=True) as proxy_url:
            yield fake, proxy_url, s


def post(url: str, session: str, path: str, body: dict) -> httpx.Response:
    return httpx.post(f"{url}/s/{session}{path}?beta=true", timeout=60,
                      content=json.dumps(body, ensure_ascii=False).encode())


def archived_requests(db) -> int:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT count(*) FROM requests").fetchone()[0]
    finally:
        conn.close()


def test_recorded_claude_code_compact_is_divergence(tmp_path):
    """Messages-protocol evidence from real bodies; Claude Code itself is not supported
    (D92). Claude Code 2.1.318, ``DISABLE_AUTO_COMPACT=1``, ``claude -p "/compact"
    --continue`` (HC6, run ``compact_auto_off``). Its summarizer request appends the summary prompt to
    the last user message and leaves out the answer to it; the request after compaction
    starts from the summary. Both rewrite archived history."""
    bodies = recorded("claude-code-2.1.318/compact_auto_off")
    assert len(bodies) == 5
    with stack(tmp_path) as (fake, url, s):
        for i in (1, 2):  # the two ordinary turns, answered as the fault server answered
            fake.respond_sse(answer(f"OK from cc fault server (attempt-{i})."))
            r = post(url, "cc-compact", "/v1/messages", bodies[i - 1])
            assert r.status_code == 200, r.content[:300]
        refused = [post(url, "cc-compact", "/v1/messages", b) for b in bodies[2:]]
        kept = archived_requests(s.db_path)

    for r in refused:
        assert r.status_code == 409, r.content[:300]
        assert r.json()["type"] == "error" and "history_divergence" in r.json()["error"]["message"]
        assert r.headers["x-should-retry"] == "false"
    assert kept == 2 and len(fake.requests) == 2


def test_summary_shaped_text_in_ordinary_turn_is_accepted(tmp_path):
    """The same words as a compaction, sent as a new turn that extends the history, are
    content: nothing matches on summary text (plan §2.6)."""
    summary = ("This session is being continued from a previous conversation that ran out of "
               "context. The summary below covers the earlier portion of the conversation.\n"
               "<summary>1. Primary Request and Intent: ...</summary>")
    first = {"model": "m", "max_tokens": 256, "stream": True, "system": "S",
             "messages": [{"role": "user", "content": "Start the refactor."}]}
    second = {**first, "messages": [*first["messages"],
                                    {"role": "assistant", "content": [{"type": "text", "text": "Done."}]},
                                    {"role": "user", "content": summary}]}
    with stack(tmp_path) as (fake, url, s):
        fake.respond_sse(answer("Done."))
        assert post(url, "sum-1", "/v1/messages", first).status_code == 200
        fake.respond_sse(answer("Continuing."))
        r = post(url, "sum-1", "/v1/messages", second)

    assert r.status_code == 200, r.content[:300]
    assert json.loads(fake.requests[-1].body)["messages"][-1]["content"] == summary


def test_pi_manual_compact_request_is_divergence(tmp_path):
    """Pi 1.5.0 ``compact`` (HP5, run ``hp5_manual_compact``, compaction otherwise off),
    sent as the adapter's compat flags send it. The summarizer request replaces the history
    with a summary prompt; the request after it starts from the summary."""
    bodies = [pi_compat(b) for b in recorded("pi-1.5.0/hp5_manual_compact")]
    assert len(bodies) == 4
    with stack(tmp_path) as (fake, url, s):
        for i in (0, 1):
            fake.respond_sse(next_answer(bodies, i))
            r = httpx.post(f"{url}/v1/chat/completions", headers={"X-Palimnesis-Session": "pi-c"},
                           content=json.dumps(bodies[i]).encode(), timeout=60)
            assert r.status_code == 200, r.content[:300]
        refused = [httpx.post(f"{url}/v1/chat/completions", headers={"X-Palimnesis-Session": "pi-c"},
                              content=json.dumps(b).encode(), timeout=60) for b in bodies[2:]]
        kept = archived_requests(s.db_path)

    for r in refused:
        assert r.status_code == 409 and r.json()["error"]["code"] == "history_divergence"
    assert kept == 2 and len(fake.requests) == 2
