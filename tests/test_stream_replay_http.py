"""Phase 8 S5: idempotent replay of a completed keyed stream (plan §1.5, contracts §5–§6,
U7).

A repeated ``Idempotency-Key`` for a completed streamed request is answered from the
archive through the endpoint's emitter: no upstream call, no hidden tool re-run, also
after a restart. Promised: event order, content and terminal metadata (finish reason,
client-visible usage, message id, ``created``). Not promised: chunk boundaries or
timestamps. A keyed stream that produced only part of its output still gets
``ambiguous_retry``; a client asking to resume a stream (``Last-Event-ID``) gets 400
``resume_unsupported``. The terminal metadata is stored at the terminal commit in the
immutable ``stream_terminals`` table (migration 8)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from palimnesis.api import create_app
from palimnesis.config import Settings
from palimnesis.protocols.sse import ChatStream, SSEParser

from .archive_helpers import DONE, RESET, body, user
from .fake_upstream import FakeUpstream
from .servers import serve
from .test_hidden_loop_http import GREP, _masked, view_stack
from .test_view_http import SID as VIEW_SID
from .test_messages_http import anthropic_error, frames, mbody, mpost

SID = "ses_replay"
IDENT = {"id": "chatcmpl-r1", "object": "chat.completion.chunk", "created": 1700000123,
         "model": "m-up", "system_fingerprint": "fp-1"}


def _chunk(delta: dict | None, finish: str | None = None, **extra) -> bytes:
    choices = [] if delta is None else [{"index": 0, "delta": delta, "finish_reason": finish}]
    return b"data: " + json.dumps({**IDENT, "choices": choices, **extra}).encode() + b"\n\n"


USAGE = {"prompt_tokens": 40, "completion_tokens": 9, "total_tokens": 49,
         "prompt_tokens_details": {"cached_tokens": 32}}
FULL = [
    _chunk({"role": "assistant", "content": ""}),
    _chunk({"reasoning_content": "Look at "}),
    _chunk({"reasoning_content": "the file."}),
    _chunk({"content": "Reading "}),
    _chunk({"content": "it now."}),
    _chunk({"tool_calls": [{"index": 0, "id": "call_x1", "type": "function",
                            "function": {"name": "read", "arguments": ""}}]}),
    _chunk({"tool_calls": [{"index": 0, "function": {"arguments": "{\"path\": "}}]}),
    _chunk({"tool_calls": [{"index": 0, "function": {"arguments": "\"a.py\"}"}}]}),
    _chunk({}, "tool_calls"),
    _chunk(None, usage=USAGE),
    DONE,
]


def _post(url: str, payload: bytes, *, session: str = SID, headers=None) -> httpx.Response:
    with httpx.stream("POST", f"{url}/s/{session}/v1/chat/completions", content=payload,
                      headers=headers, timeout=60) as r:
        r.read()
    return r


def _seen(raw: bytes) -> ChatStream:
    s = ChatStream()
    for e in SSEParser().feed(raw):
        s.apply(e)
    return s


def _chunks(raw: bytes) -> list[dict]:
    return [json.loads(e.data) for e in SSEParser().feed(raw)
            if e.data is not None and e.data != "[DONE]"]


def _db(settings: Settings, sql: str, *args):
    c = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def _proxy(upstream_url: str, tmp_path: Path, **kw):
    s = Settings(upstream_base_url=upstream_url, db_path=tmp_path / "archive.db", **kw)
    return s, serve(create_app(s), palimnesis=True)


def _same_stream(first: bytes, again: bytes) -> None:
    a, b = _seen(first), _seen(again)
    assert (b.content, b.reasoning, b.tool_calls, b.finish_reason, b.usage, b.done, b.error) == \
        (a.content, a.reasoning, a.tool_calls, a.finish_reason, a.usage, a.done, a.error)
    # Terminal metadata: every chunk of the replay carries the original identity.
    ids = {(c.get("id"), c.get("created"), c.get("model"), c.get("system_fingerprint"))
           for c in _chunks(again)}
    assert ids == {(IDENT["id"], IDENT["created"], IDENT["model"], IDENT["system_fingerprint"])}
    assert again.count(b"[DONE]") == 1


# --- Chat ------------------------------------------------------------------------------

def test_a_completed_keyed_chat_stream_replays_from_the_archive_without_upstream(tmp_path):
    fake = FakeUpstream()
    with serve(fake.app()) as up:
        s, proxy = _proxy(up, tmp_path)
        with proxy as url:
            fake.respond_sse(FULL)
            payload = body([user("open a.py")])
            first = _post(url, payload, headers={"Idempotency-Key": "k1"})
            again = _post(url, payload, headers={"Idempotency-Key": "k1"})
    assert first.status_code == again.status_code == 200
    assert again.headers["content-type"].startswith("text/event-stream")
    _same_stream(first.content, again.content)
    assert len(fake.requests) == 1
    assert _db(s, "SELECT count(*) FROM attempts") == [(1,)]
    assert _db(s, "SELECT count(*) FROM occurrences WHERE source = 'generated'") == [(1,)]
    assert _db(s, "SELECT count(*) FROM events WHERE kind = 'stream_replayed'") == [(1,)]


def test_the_terminal_metadata_is_stored_once_and_immutable(tmp_path):
    fake = FakeUpstream()
    with serve(fake.app()) as up:
        s, proxy = _proxy(up, tmp_path)
        with proxy as url:
            fake.respond_sse(FULL)
            assert _post(url, body([user("open a.py")])).status_code == 200
    rows = _db(s, "SELECT chunk_id, created, model, system_fingerprint, finish_reason, usage,"
                  " message_id FROM stream_terminals")
    assert rows == [("chatcmpl-r1", 1700000123, "m-up", "fp-1", "tool_calls", json.dumps(USAGE), None)]
    assert _db(s, "PRAGMA user_version")[0][0] >= 8
    c = sqlite3.connect(s.db_path)
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("UPDATE stream_terminals SET finish_reason = 'stop'")
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("DELETE FROM stream_terminals")
    c.close()


def test_a_replay_works_after_a_restart(tmp_path):
    fake = FakeUpstream()
    payload = body([user("open a.py")])
    with serve(fake.app()) as up:
        s, proxy = _proxy(up, tmp_path)
        with proxy as url:
            fake.respond_sse(FULL)
            first = _post(url, payload, headers={"Idempotency-Key": "k1"})
        s, proxy = _proxy(up, tmp_path)
        with proxy as url:
            again = _post(url, payload, headers={"Idempotency-Key": "k1"})
    assert again.status_code == 200
    _same_stream(first.content, again.content)
    assert len(fake.requests) == 1


def test_a_keyed_stream_cut_mid_output_is_ambiguous_not_replayed(tmp_path):
    fake = FakeUpstream()
    payload = body([user("open a.py")])
    with serve(fake.app()) as up:
        s, proxy = _proxy(up, tmp_path)
        with proxy as url:
            fake.respond_sse(FULL[:4] + [(0.1, RESET)])
            _post(url, payload, headers={"Idempotency-Key": "k1"})
            r = _post(url, payload, headers={"Idempotency-Key": "k1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ambiguous_retry"
    assert r.headers["x-should-retry"] == "false"
    assert len(fake.requests) == 1


def test_hidden_tools_are_not_rerun_and_stay_hidden_in_a_replay(tmp_path):
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, settings):
        fake.respond_turn("Checking. ", reasoning="think ", calls=[GREP])
        fake.respond_turn("It is in read 3.")
        messages = _masked()
        payload = body(messages, max_completion_tokens=8192)
        first = httpx.post(f"{url}/s/{VIEW_SID}/v1/chat/completions", content=payload,
                           headers={"Idempotency-Key": "k9"}, timeout=60)
        n = len(fake.requests)
        again = httpx.post(f"{url}/s/{VIEW_SID}/v1/chat/completions", content=payload,
                           headers={"Idempotency-Key": "k9"}, timeout=60)
    assert first.status_code == again.status_code == 200, again.content[:300]
    a, b = _seen(first.content), _seen(again.content)
    assert b.content == a.content == "Checking. It is in read 3."
    assert b.reasoning == a.reasoning and b.tool_calls == a.tool_calls == []
    assert b.finish_reason == a.finish_reason and b.usage == a.usage
    assert b"palimnesis" not in again.content
    assert len(fake.requests) == n == 2


# --- Messages --------------------------------------------------------------------------

def _summary(r: httpx.Response) -> dict:
    fs = frames(r)
    names = [n for n, _ in fs]
    start = next(d for n, d in fs if n == "message_start")["message"]
    blocks: list[list] = []
    for n, d in fs:
        if n == "content_block_start":
            blocks.append([d["content_block"]["type"], "", d["content_block"].get("id"),
                           d["content_block"].get("name")])
        elif n == "content_block_delta":
            delta = d["delta"]
            blocks[-1][1] += delta.get("text") or delta.get("thinking") or delta.get("partial_json") or ""
    end = next(d for n, d in fs if n == "message_delta")
    collapsed = [x for i, x in enumerate(names) if i == 0 or x != names[i - 1]]
    return {"events": collapsed, "id": start["id"], "model": start["model"], "blocks": blocks,
            "stop": end["delta"]["stop_reason"], "usage": end["usage"]}


def test_a_completed_keyed_messages_stream_replays_the_same_events(tmp_path):
    fake = FakeUpstream()
    payload = mbody([{"role": "user", "content": "open a.py"}])
    with serve(fake.app()) as up:
        s, proxy = _proxy(up, tmp_path)
        with proxy as url:
            fake.respond_sse(FULL)
            first = mpost(url, payload, headers={"Idempotency-Key": "k2"})
            again = mpost(url, payload, headers={"Idempotency-Key": "k2"})
    assert first.status_code == again.status_code == 200, again.content[:300]
    assert _summary(again) == _summary(first)
    assert len(fake.requests) == 1
    (mid,) = _db(s, "SELECT message_id FROM stream_terminals")[0]
    assert mid == _summary(first)["id"]


# --- resume ----------------------------------------------------------------------------

def test_a_resume_request_is_refused_before_acceptance(tmp_path):
    fake = FakeUpstream()
    with serve(fake.app()) as up:
        s, proxy = _proxy(up, tmp_path)
        with proxy as url:
            chat = _post(url, body([user("hi")]), headers={"Last-Event-ID": "7"})
            msgs = mpost(url, mbody([{"role": "user", "content": "hi"}]),
                         headers={"Last-Event-ID": "7"})
    assert chat.status_code == 400 and chat.json()["error"]["code"] == "resume_unsupported"
    assert chat.headers["x-should-retry"] == "false"
    anthropic_error(msgs, 400, "resume_unsupported")
    assert fake.requests == []
    assert _db(s, "SELECT count(*) FROM requests") == [(0,)]
