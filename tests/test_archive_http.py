"""Archive mode end to end: OpenCode traffic through the proxy into the archive.

HTTP seam with the fake upstream replaying recorded Strata responses. The
archive database is the product's durable output, so tests inspect it
read-only through ``mnemon.ledger`` readers on a plain SQLite connection.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from mnemon.capture import load_exchanges
from mnemon.ledger import branch_id_for, load_archived
from mnemon.rawarchive import get_raw
from mnemon.sse import ChatStream, SSEParser

ROOT = Path(__file__).resolve().parents[1]
LIVE = load_exchanges(ROOT / "eval/fixtures/opencode-2.1.4/live/exchanges")
SESSION = LIVE[0].session
URL = f"/s/{SESSION}/v1/chat/completions"


def rechunk(data: bytes, size: int = 97) -> list[bytes]:
    return [data[i : i + size] for i in range(0, len(data), size)]


def assembled(sse: bytes) -> ChatStream:
    parser, stream = SSEParser(), ChatStream()
    for event in parser.feed(sse):
        stream.apply(event)
    return stream


@contextmanager
def archive_db(stack):
    conn = sqlite3.connect(f"file:{stack.settings.db_path}?mode=ro", uri=True)
    try:
        yield conn
    finally:
        conn.close()


def post_stream(stack, body: bytes, url: str = URL, headers=None) -> httpx.Response:
    with httpx.stream("POST", stack.proxy_url + url, content=body, headers=headers, timeout=30) as r:
        r.read()
    return r


def test_one_live_exchange_is_relayed_unchanged_and_archived(archive_stack):
    ex = LIVE[0]
    archive_stack.upstream.respond_sse(rechunk(ex.response_body))

    r = post_stream(archive_stack, ex.request_body)

    assert r.status_code == 200
    assert r.content == ex.response_body
    assert r.headers["x-should-retry"] == "false"
    [upstream] = archive_stack.upstream.requests
    assert upstream.body == ex.request_body

    expected = assembled(ex.response_body)
    with archive_db(archive_stack) as c:
        history = load_archived(c, branch_id_for(SESSION))
        [raw_id] = [row[0] for row in c.execute("SELECT raw_id FROM requests")]
        assert get_raw(c, raw_id) == ex.request_body
    assert [(a.role, a.source) for a in history] == [
        ("system", "client"), ("user", "client"), ("assistant", "generated")]
    generated = history[-1]
    assert generated.complete
    assert (generated.text, generated.reasoning) == (expected.content, expected.reasoning)
    assert list(generated.tool_calls) == expected.tool_calls


def test_ten_live_requests_reconcile_as_extensions_and_reach_upstream_unchanged(archive_stack):
    for ex in LIVE:
        archive_stack.upstream.respond_sse(rechunk(ex.response_body))
        r = post_stream(archive_stack, ex.request_body)
        assert r.status_code == 200, r.content[:300]
        assert r.content == ex.response_body

    assert [u.body for u in archive_stack.upstream.requests] == [ex.request_body for ex in LIVE]
    last = json.loads(LIVE[-1].request_body)["messages"]
    with archive_db(archive_stack) as c:
        history = load_archived(c, branch_id_for(SESSION))
        raws = [get_raw(c, rid) for (rid,) in c.execute("SELECT raw_id FROM requests ORDER BY arrived_at")]
    assert len(history) == len(last) + 1
    assert [a.role for a in history[:-1]] == [m["role"] for m in last]
    assert all(a.complete for a in history if a.source == "generated")
    assert raws == [ex.request_body for ex in LIVE]


def test_each_batch_is_committed_before_the_client_receives_it(archive_stack):
    first = b'data: {"choices":[{"index":0,"delta":{"role":"assistant","content":"Hel"}}]}\n\n'
    rest = [
        b'data: {"choices":[{"index":0,"delta":{"content":"lo"},"finish_reason":"stop"}]}\n\n',
        b"data: [DONE]\n\n",
    ]
    archive_stack.upstream.respond_sse([first, (1.0, rest[0]), rest[1]])
    body = json.dumps({"model": "m", "stream": True,
                       "messages": [{"role": "user", "content": "hi"}]}).encode()

    with httpx.stream("POST", archive_stack.proxy_url + URL, content=body, timeout=30) as r:
        chunks = r.iter_raw()
        received = next(chunks)
        assert b'"Hel"' in received
        with archive_db(archive_stack) as c:
            during = load_archived(c, branch_id_for(SESSION))
        b"".join(chunks)

    assert during[-1].source == "generated"
    assert during[-1].text == "Hel"
    assert during[-1].complete is False
    with archive_db(archive_stack) as c:
        after = load_archived(c, branch_id_for(SESSION))
    assert (after[-1].text, after[-1].complete) == ("Hello", True)
