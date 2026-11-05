"""The Anthropic Messages archive route (Phase 4B S4), end to end through the fake upstream.

A Messages client's body is archived exactly, parsed into the neutral form, and sent
upstream as Chat Completions (position 2); the client gets Messages back (S3's emitter).
Errors before acceptance use Anthropic's envelope. A session speaks one protocol.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

import httpx
import pytest

from palimnesis.api import create_app
from palimnesis.config import Settings
from palimnesis.upstreams.strata import tokens

from .archive_helpers import DONE, answer, chunk, lifecycle_stack
from .fake_upstream import FakeUpstream
from .servers import serve

SID = "msg-1"
SYSTEM = "You are terse."
WEATHER = {"name": "get_weather", "description": "Get the weather.",
           "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}}}


def mbody(messages, *, stream=True, **top) -> bytes:
    return json.dumps({"model": "m", "max_tokens": 4096, "stream": stream, "system": SYSTEM,
                       **top, "messages": messages}, ensure_ascii=False).encode()


def mpost(url: str, payload: bytes, *, session: str = SID, path: str = "/v1/messages",
          query: str = "beta=true", headers=None) -> httpx.Response:
    target = f"{url}/s/{session}{path}" + (f"?{query}" if query else "")
    with httpx.stream("POST", target, content=payload, headers=headers, timeout=60) as r:
        r.read()
    return r


def frames(r: httpx.Response) -> list[tuple[str, dict]]:
    out = []
    for frame in r.content.decode().split("\n\n"):
        if frame and not frame.startswith(":"):
            lines = dict(line.split(": ", 1) for line in frame.split("\n"))
            out.append((lines["event"], json.loads(lines["data"])))
    return out


def anthropic_error(r: httpx.Response, status: int, code: str) -> None:
    assert r.status_code == status, r.content[:300]
    doc = r.json()
    assert doc["type"] == "error" and code in doc["error"]["message"], doc
    assert r.headers["x-should-retry"] == "false"


def count(db, sql: str):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


@contextmanager
def stack(tmp_path, **settings):
    fake = FakeUpstream()
    with serve(fake.app()) as upstream_url:
        s = Settings(upstream_base_url=upstream_url, db_path=tmp_path / "archive.db", **settings)
        with serve(create_app(s), palimnesis=True) as proxy_url:
            yield fake, proxy_url, s


def tool_turn() -> list[bytes]:
    return [chunk({"role": "assistant", "content": ""}),
            chunk({"reasoning_content": "Check the weather."}),
            chunk({"content": "Looking it up."}),
            chunk({"tool_calls": [{"index": 0, "id": "call_aaa", "type": "function",
                                   "function": {"name": "get_weather", "arguments": ""}}]}),
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"city": '}}]}),
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"Oslo"}'}}]}),
            chunk({}, "tool_calls"), DONE]


def test_messages_stream_archived_and_resend_reconciles(tmp_path):
    cc = {"type": "ephemeral"}
    first = [{"role": "user", "content": [{"type": "text", "text": "Weather in Oslo?",
                                           "cache_control": cc}]}]
    with stack(tmp_path) as (fake, url, s):
        fake.respond_sse(tool_turn())
        r1 = mpost(url, mbody(first, tools=[WEATHER]))
        events = frames(r1)
        # The client resends what it received: thinking with an empty signature, the
        # text, the call with its input parsed; cache_control moved to the new message.
        resend = [{"role": "user", "content": "Weather in Oslo?"},
                  {"role": "assistant", "content": [
                      {"type": "thinking", "thinking": "Check the weather.", "signature": ""},
                      {"type": "text", "text": "Looking it up."},
                      {"type": "tool_use", "id": "call_aaa", "name": "get_weather",
                       "input": {"city": "Oslo"}}]},
                  {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_aaa",
                                                "content": "12 C", "cache_control": cc}]}]
        fake.respond_sse(answer("It is 12 C."))
        r2 = mpost(url, mbody(resend, tools=[WEATHER]))
        endpoints = count(s.db_path, "SELECT endpoint FROM requests ORDER BY arrived_at")
        roles = count(s.db_path, "SELECT role, source FROM occurrences ORDER BY seq")

    assert r1.status_code == 200 and r1.headers["content-type"].startswith("text/event-stream")
    assert [n for n, _ in events] == [
        "message_start", "content_block_start", "content_block_delta", "content_block_stop",
        "content_block_start", "content_block_delta", "content_block_stop",
        "content_block_start", "content_block_delta", "content_block_delta", "content_block_stop",
        "message_delta", "message_stop"]
    assert events[-2][1]["delta"]["stop_reason"] == "tool_use"
    assert r2.status_code == 200, r2.content[:300]
    assert [n for n, _ in frames(r2)][-1] == "message_stop"
    assert endpoints == [("/v1/messages",), ("/v1/messages",)]
    assert roles == [("system", "client"), ("user", "client"), ("assistant", "generated"),
                     ("tool", "client"), ("assistant", "generated")]
    sent = json.loads(fake.requests[1].body)
    assert sent["messages"][2]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert sent["messages"][3] == {"role": "tool", "tool_call_id": "call_aaa", "content": "12 C"}


def test_upstream_body_is_chat_and_counts_within_budget(tmp_path):
    def code(i):
        return "\n".join(f"def f{i}_{n}(x): return x * {n}  # {n}" for n in range(80))

    messages = [{"role": "user", "content": "refactor the project"}]
    for i in range(30):
        messages.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": f"call_{i}", "name": "read", "input": {}}]})
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"call_{i}", "content": code(i)}]})
    messages.append({"role": "assistant", "content": [{"type": "text", "text": "done"}]})
    messages.append({"role": "user", "content": "next"})
    read = {"name": "read", "description": "read a file", "input_schema": {"type": "object"}}
    with stack(tmp_path, input_budget=8000, hidden_tools="t1") as (fake, url, s):
        fake.respond_sse(answer("ok"))
        r = mpost(url, mbody(messages, tools=[read]))

    assert r.status_code == 200, r.content[:300]
    [sent] = fake.requests
    assert (sent.path, sent.query) == ("/v1/chat/completions", "")
    doc = json.loads(sent.body)
    assert doc["messages"][0]["role"] == "system"
    assert doc["messages"][0]["content"].startswith(SYSTEM)  # then the a3 addendum (D36)
    assert doc["stream_options"] == {"include_usage": True}
    assert [t["function"]["name"] for t in doc["tools"]] == ["read"]  # no hidden tools (§1)
    assert tokens.default().count_messages(**tokens.render_args_from_openai(doc)) <= 8000
    assert any("palimnesis" in str(m.get("content")) for m in doc["messages"])  # masked


def test_messages_nonstream_committed_before_delivery(tmp_path):
    upstream = {"id": "x", "object": "chat.completion", "model": "m",
                "usage": {"prompt_tokens": 30, "completion_tokens": 3},
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "Hi."}}]}
    payload = mbody([{"role": "user", "content": "hi"}], stream=False)
    with stack(tmp_path) as (fake, url, s):
        fake.respond_json(json.dumps(upstream).encode())
        r1 = mpost(url, payload, headers={"Idempotency-Key": "k1"})
        r2 = mpost(url, payload, headers={"Idempotency-Key": "k1"})  # replayed from the archive

    assert r1.status_code == 200
    doc = r1.json()
    assert (doc["type"], doc["role"], doc["content"], doc["stop_reason"]) == (
        "message", "assistant", [{"type": "text", "text": "Hi."}], "end_turn")
    assert doc["usage"]["input_tokens"] == 30 and doc["usage"]["output_tokens"] == 3
    assert r2.status_code == 200 and r2.json() == doc
    assert len(fake.requests) == 1


def test_idempotency_and_streaming_key_409_on_messages(tmp_path):
    payload = mbody([{"role": "user", "content": "hi"}])
    with stack(tmp_path) as (fake, url, s):
        fake.respond_sse(answer("A"))
        assert mpost(url, payload, headers={"Idempotency-Key": "k2"}).status_code == 200
        streaming = mpost(url, payload, headers={"Idempotency-Key": "k2"})
        other = mpost(url, mbody([{"role": "user", "content": "other"}]),
                      headers={"Idempotency-Key": "k2"})

    anthropic_error(streaming, 409, "streaming_replay_unsupported")
    anthropic_error(other, 409, "idempotency_conflict")
    assert len(fake.requests) == 1


def test_beta_query_accepted_other_query_rejected(tmp_path):
    with stack(tmp_path) as (fake, url, s):
        fake.respond_sse(answer("A"))
        ok = mpost(url, mbody([{"role": "user", "content": "hi"}]), query="beta=true")
        bad = mpost(url, mbody([{"role": "user", "content": "hi"}]), session="msg-2",
                    query="beta=true&x=1")
        n = count(s.db_path, "SELECT count(*) FROM requests WHERE session_id = 'msg-2'")[0][0]

    assert ok.status_code == 200 and fake.requests[0].query == ""
    anthropic_error(bad, 400, "unsupported_feature")
    assert n == 0 and len(fake.requests) == 1


def test_count_tokens_relayed_unarchived(tmp_path):
    with stack(tmp_path) as (fake, url, s):
        fake.count_tokens_handler = lambda body: 123
        r = mpost(url, json.dumps({"model": "m", "messages": [{"role": "user", "content": "hi"}]})
                  .encode(), path="/v1/messages/count_tokens")
        archived = count(s.db_path, "SELECT count(*) FROM requests")[0][0]

    assert r.status_code == 200 and r.json() == {"input_tokens": 123}
    assert fake.count_tokens_requests[-1]["messages"] == [{"role": "user", "content": "hi"}]
    assert archived == 0


def test_protocol_fixed_per_session(tmp_path):
    chat_body = json.dumps({"model": "m", "stream": True,
                            "messages": [{"role": "user", "content": "hi"}]}).encode()
    with stack(tmp_path) as (fake, url, s):
        fake.respond_sse(answer("A"))
        first = mpost(url, mbody([{"role": "user", "content": "hi"}]))
        then_chat = mpost(url, chat_body, path="/v1/chat/completions", query="")
        fake.respond_sse(answer("B"))
        chat_first = mpost(url, chat_body, session="chat-1", path="/v1/chat/completions", query="")
        then_messages = mpost(url, mbody([{"role": "user", "content": "hi"}]), session="chat-1")

    assert first.status_code == 200 and chat_first.status_code == 200
    assert then_chat.status_code == 400
    assert then_chat.json()["error"]["code"] == "session_protocol_mismatch"
    anthropic_error(then_messages, 400, "session_protocol_mismatch")
    assert len(fake.requests) == 2


def test_reserved_palimnesis_tool_name_rejected_on_messages(tmp_path):
    with stack(tmp_path) as (fake, url, s):
        r = mpost(url, mbody([{"role": "user", "content": "hi"}],
                             tools=[{**WEATHER, "name": "palimnesis_recall"}]))
        n = count(s.db_path, "SELECT count(*) FROM requests")[0][0]

    anthropic_error(r, 400, "unsupported_feature")
    assert n == 0 and fake.requests == []


def test_budget_error_anthropic_envelope_before_acceptance(tmp_path):
    huge = " ".join(f"word{i}" for i in range(12000))
    with stack(tmp_path, input_budget=8000) as (fake, url, s):
        r = mpost(url, mbody([{"role": "user", "content": huge}]))
        n = count(s.db_path, "SELECT count(*) FROM requests")[0][0]

    anthropic_error(r, 400, "context_budget_exceeded")
    assert n == 0 and fake.requests == []


@pytest.mark.parametrize("path", ["/v1/messages/batches", "/v1/complete"])
def test_other_anthropic_posts_are_refused_in_the_anthropic_envelope(tmp_path, path):
    with stack(tmp_path) as (fake, url, s):
        r = mpost(url, mbody([{"role": "user", "content": "hi"}]), path=path)

    assert r.status_code == 400 and fake.requests == []
    if path.startswith("/v1/messages"):
        anthropic_error(r, 400, "unsupported_feature")


def test_an_in_stream_failure_ends_with_an_anthropic_error_event(tmp_path):
    with lifecycle_stack(tmp_path) as lc:
        lc.upstream.respond_sse([chunk({"role": "assistant", "content": ""}),
                                 chunk({"content": "partial"})])  # EOF without [DONE]
        r = mpost(lc.proxy_url, mbody([{"role": "user", "content": "hi"}]))

    names = [n for n, _ in frames(r)]
    assert r.status_code == 200 and names[-1] == "error" and "message_stop" not in names
    assert r.headers["x-should-retry"] == "false"


# --- S5: errors and in-stream failures on Messages (plan §2.3) -----------------------------

@pytest.mark.parametrize("status, upstream, kind", [
    (400, {"error": {"type": "invalid_request_error",
                     "message": "request exceeds the context window: prompt (35480 tokens)"}},
     "invalid_request_error"),
    (503, {"error": {"code": 503, "message": "Loading model", "type": "unavailable_error"}},
     "api_error"),
    (429, {"error": {"type": "rate_limit_error", "message": "admission full",
                     "code": "admission_full"}}, "rate_limit_error"),
    (404, {"error": {"message": "not found"}}, "not_found_error"),
])
def test_upstream_non200_reenveloped_status_and_message_kept(tmp_path, status, upstream, kind):
    with stack(tmp_path) as (fake, url, s):
        fake.respond_json(json.dumps(upstream).encode(), status=status)
        r = mpost(url, mbody([{"role": "user", "content": "hi"}]))

    assert r.status_code == status
    assert r.headers["x-should-retry"] == "false"
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"type": "error", "error": {"type": kind,
                                                   "message": upstream["error"]["message"]}}


def test_an_upstream_error_that_is_not_json_keeps_its_text(tmp_path):
    with stack(tmp_path) as (fake, url, s):
        fake.respond_json(b"Bad Gateway", status=502, headers={"content-type": "text/plain"})
        r = mpost(url, mbody([{"role": "user", "content": "hi"}]))

    assert r.status_code == 502
    assert r.json() == {"type": "error", "error": {"type": "api_error", "message": "Bad Gateway"}}


def test_chat_clients_still_get_the_upstream_error_unchanged(tmp_path):
    raw = b'{"error":{"code":503,"message":"Loading model","type":"unavailable_error"}}'
    chat_body = json.dumps({"model": "m", "stream": True,
                            "messages": [{"role": "user", "content": "hi"}]}).encode()
    with stack(tmp_path) as (fake, url, s):
        fake.respond_json(raw, status=503)
        r = mpost(url, chat_body, path="/v1/chat/completions", query="")

    assert r.status_code == 503 and r.content == raw


def test_failure_after_start_messages_error_event_no_retry_header(tmp_path):
    with stack(tmp_path) as (fake, url, s):
        fake.respond_sse([chunk({"role": "assistant", "content": ""}), chunk({"content": "half"}),
                          b'data: {"error":{"message":"engine died; the next request restarts it",'
                          b'"type":"api_error"}}\n\n', DONE])
        r = mpost(url, mbody([{"role": "user", "content": "hi"}]))

    names = [n for n, _ in frames(r)]
    assert r.status_code == 200 and r.headers["x-should-retry"] == "false"
    assert names.count("error") == 1 and "message_stop" not in names
    assert frames(r)[-1][1]["error"]["message"] == "engine died; the next request restarts it"


def test_deadline_after_start_messages_error_event(tmp_path):
    slow = [chunk({"content": "one "})] + [(0.3, chunk({"content": f"{i} "})) for i in range(30)] + [DONE]
    with stack(tmp_path, deadline_s=1.0) as (fake, url, s):
        fake.respond_sse(slow)
        r = mpost(url, mbody([{"role": "user", "content": "count slowly"}]))

    out = frames(r)
    assert r.status_code == 200 and out[-1][0] == "error"
    assert "deadline_exceeded" in out[-1][1]["error"]["message"]
    assert "message_stop" not in [n for n, _ in out]


def test_deadline_before_start_is_a_504_in_the_anthropic_envelope(tmp_path):
    with stack(tmp_path, deadline_s=0.5) as (fake, url, s):
        fake.respond_json(b'{"choices":[]}', delay=5.0)
        r = mpost(url, mbody([{"role": "user", "content": "hi"}], stream=False))

    anthropic_error(r, 504, "deadline_exceeded")
