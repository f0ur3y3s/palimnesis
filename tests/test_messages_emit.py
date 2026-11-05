"""The Messages emitter (Phase 4B S3): upstream Chat SSE in, Anthropic Messages SSE out.

Pure tests of ``palimnesis.protocols.messages_emit.MessagesEmitter``. The expected event
sequences follow the plan (§2.2), the Anthropic streaming format, and Strata 0.1.54's own
Messages route (``docs/probes/strata.md`` §13.1) where the two could differ.
"""

from __future__ import annotations

import json

from palimnesis.protocols.messages_emit import MessagesEmitter

DONE = b"data: [DONE]\n\n"


def chunk(delta: dict | None = None, finish: str | None = None, usage: dict | None = None,
          choices: bool = True) -> bytes:
    obj: dict = {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "m"}
    obj["choices"] = [{"index": 0, "delta": delta or {}, "finish_reason": finish}] if choices else []
    if usage is not None:
        obj["usage"] = usage
    return b"data: " + json.dumps(obj).encode() + b"\n\n"


def call(i: int, *, id_: str | None = None, name: str | None = None, args: str = "") -> dict:
    fn: dict = {"arguments": args}
    if name is not None:
        fn["name"] = name
    c: dict = {"index": i, "function": fn}
    if id_ is not None:
        c.update(id=id_, type="function")
    return {"tool_calls": [c]}


def events(raw: bytes) -> list[tuple[str, dict]]:
    out = []
    for frame in raw.decode().split("\n\n"):
        if not frame or frame.startswith(":"):
            continue
        lines = dict(line.split(": ", 1) for line in frame.split("\n"))
        data = json.loads(lines["data"])
        assert data["type"] == lines["event"]
        out.append((lines["event"], data))
    return out


def run(*parts: bytes, emitter: MessagesEmitter | None = None) -> list[tuple[str, dict]]:
    e = emitter or MessagesEmitter(message_id="msg_test")
    return events(b"".join(e.feed(p) for p in parts))


USAGE = {"prompt_tokens": 1000, "completion_tokens": 42, "total_tokens": 1042,
         "prompt_tokens_details": {"cached_tokens": 960}}


def test_emitter_lifecycle_text_thinking_tool_use():
    out = run(chunk({"role": "assistant", "content": ""}),
              chunk({"reasoning_content": "Let me "}), chunk({"reasoning_content": "look."}),
              chunk({"content": "Reading."}),
              chunk(call(0, id_="call_abc", name="read")), chunk(call(0, args='{"path"')),
              chunk(call(0, args=':"a.txt"}')),
              chunk(finish="tool_calls"), chunk(usage=USAGE, choices=False), DONE)

    assert [(n, d.get("index"), (d.get("content_block") or d.get("delta") or {}).get("type"))
            for n, d in out] == [
        ("message_start", None, None),
        ("content_block_start", 0, "thinking"),
        ("content_block_delta", 0, "thinking_delta"), ("content_block_delta", 0, "thinking_delta"),
        ("content_block_stop", 0, None),
        ("content_block_start", 1, "text"), ("content_block_delta", 1, "text_delta"),
        ("content_block_stop", 1, None),
        ("content_block_start", 2, "tool_use"),
        ("content_block_delta", 2, "input_json_delta"), ("content_block_delta", 2, "input_json_delta"),
        ("content_block_stop", 2, None),
        ("message_delta", None, None), ("message_stop", None, None)]
    start = out[0][1]["message"]
    assert (start["id"], start["role"], start["model"], start["content"]) == ("msg_test", "assistant", "m", [])
    assert out[1][1]["content_block"] == {"type": "thinking", "thinking": "", "signature": ""}
    assert "".join(d["delta"]["thinking"] for n, d in out if d.get("delta", {}).get("type") == "thinking_delta") == "Let me look."
    assert out[8][1]["content_block"] == {"type": "tool_use", "id": "call_abc", "name": "read", "input": {}}
    assert "".join(d["delta"]["partial_json"] for _, d in out[9:11]) == '{"path":"a.txt"}'


def test_stop_reason_and_usage_mapping():
    for finish, reason in (("stop", "end_turn"), ("tool_calls", "tool_use"), ("length", "max_tokens")):
        out = run(chunk({"content": "x"}), chunk(finish=finish, usage=USAGE), DONE)
        assert out[-2][1] == {"type": "message_delta",
                              "delta": {"stop_reason": reason, "stop_sequence": None},
                              "usage": {"input_tokens": 40, "cache_creation_input_tokens": 0,
                                        "cache_read_input_tokens": 960, "output_tokens": 42}}
    out = run(chunk({"content": "x"}), chunk(finish="stop"), DONE)
    assert out[-2][1]["usage"] == {"input_tokens": 0, "cache_creation_input_tokens": 0,
                                   "cache_read_input_tokens": 0, "output_tokens": 0}


def test_text_or_reasoning_after_call_opens_new_block():
    out = run(chunk(call(0, id_="c1", name="a", args="{}")),
              chunk({"content": "between"}),
              chunk(call(1, id_="c2", name="b", args="{}")),
              chunk({"reasoning_content": "again"}),
              chunk({"content": "end"}), chunk(finish="stop"), DONE)
    starts = [d["content_block"]["type"] for n, d in out if n == "content_block_start"]
    stops = [d["index"] for n, d in out if n == "content_block_stop"]

    assert starts == ["tool_use", "text", "tool_use", "thinking", "text"]
    assert stops == [0, 1, 2, 3, 4]


def test_arguments_before_the_name_wait_for_it_and_parallel_calls_get_their_own_blocks():
    out = run(chunk({"tool_calls": [{"index": 0, "id": "c1", "type": "function",
                                     "function": {"arguments": '{"a"'}}]}),
              chunk(call(0, name="first", args=":1}")),
              chunk(call(1, id_="c2", name="second", args='{"b":2}')),
              chunk(finish="tool_calls"), DONE)
    blocks = [d["content_block"] for n, d in out if n == "content_block_start"]
    pieces = [(d["index"], d["delta"]["partial_json"]) for n, d in out if n == "content_block_delta"]

    assert blocks == [{"type": "tool_use", "id": "c1", "name": "first", "input": {}},
                      {"type": "tool_use", "id": "c2", "name": "second", "input": {}}]
    assert pieces == [(0, '{"a"'), (0, ":1}"), (1, '{"b":2}')]
    assert out[-2][1]["delta"]["stop_reason"] == "tool_use"


def test_eof_without_done_is_error_event_not_message_stop():
    e = MessagesEmitter(message_id="msg_test")
    body = e.feed(chunk({"content": "partial"}) + chunk(finish="stop"))
    body += e.error("upstream_stream_failed", "The upstream stream ended before completing.")
    out = events(body)

    assert [n for n, _ in out][-1] == "error"
    assert "message_stop" not in [n for n, _ in out]
    assert out[-1][1] == {"type": "error", "error": {
        "type": "api_error",
        "message": "palimnesis upstream_stream_failed: The upstream stream ended before completing."}}
    assert e.error("again", "x") == b"" and e.feed(DONE) == b""


def test_an_upstream_error_chunk_keeps_its_message_and_is_the_only_error():
    e = MessagesEmitter(message_id="msg_test")
    body = e.feed(chunk({"content": "x"})
                  + b'data: {"error":{"message":"prompt too long for the context","type":"x"}}\n\n')
    body += e.error("upstream_stream_failed", "ended")
    out = events(body)

    assert [n for n, _ in out].count("error") == 1
    assert out[-1][1]["error"]["message"] == "prompt too long for the context"


def test_an_error_before_any_output_still_starts_the_message():
    out = events(MessagesEmitter(message_id="msg_test").error("deadline_exceeded", "late"))
    assert [n for n, _ in out] == ["message_start", "error"]


def test_signature_rule():
    """O-4B-2: thinking blocks carry an empty signature and no signature_delta (D82)."""
    out = run(chunk({"reasoning_content": "t"}), chunk({"content": "a"}), chunk(finish="stop"), DONE)

    assert out[1][1]["content_block"]["signature"] == ""
    assert not [d for _, d in out if d.get("delta", {}).get("type") == "signature_delta"]


def test_comments_pass_through_and_keepalive_is_ping():
    e = MessagesEmitter(message_id="msg_test")
    raw = e.feed(b": keep-alive\n\n") + e.feed(chunk({"content": "x"}))

    assert raw.index(b"event: message_start") < raw.index(b": keep-alive\n\n")
    assert events(e.keepalive()) == [("ping", {"type": "ping"})]


def test_split_events_across_feeds_and_empty_deltas_open_nothing():
    whole = chunk({"role": "assistant", "content": ""}) + chunk({"content": "héllo"}) + chunk(finish="stop") + DONE
    e = MessagesEmitter(message_id="msg_test")
    out = events(b"".join(e.feed(whole[i:i + 7]) for i in range(0, len(whole), 7)))

    assert [n for n, _ in out] == ["message_start", "content_block_start", "content_block_delta",
                                   "content_block_stop", "message_delta", "message_stop"]
    assert out[2][1]["delta"]["text"] == "héllo"


def test_non_streaming_body_is_one_messages_object():
    upstream = {"id": "x", "object": "chat.completion", "model": "m", "usage": USAGE,
                "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": "Reading.", "reasoning_content": "think",
                    "tool_calls": [
                        {"id": "c1", "type": "function",
                         "function": {"name": "read", "arguments": '{"z":1,"a":2}'}},
                        {"id": "c2", "type": "function",
                         "function": {"name": "write", "arguments": '{"cut'}}]}}]}
    out = json.loads(MessagesEmitter(message_id="msg_test").body(json.dumps(upstream).encode()))

    assert out == {"id": "msg_test", "type": "message", "role": "assistant", "model": "m",
                   "content": [{"type": "thinking", "thinking": "think", "signature": ""},
                               {"type": "text", "text": "Reading."},
                               {"type": "tool_use", "id": "c1", "name": "read", "input": {"z": 1, "a": 2}}],
                   "stop_reason": "tool_use", "stop_sequence": None,
                   "usage": {"input_tokens": 40, "cache_creation_input_tokens": 0,
                             "cache_read_input_tokens": 960, "output_tokens": 42}}
    assert list(out["content"][2]["input"]) == ["z", "a"]


def test_a_lone_surrogate_is_sent_escaped_as_valid_utf8():
    raw = b'data: {"choices":[{"index":0,"delta":{"content":"a\ud800b"}}]}\n\n'
    out = MessagesEmitter(message_id="msg_test").feed(raw)

    out.decode("utf-8")  # strict: no WTF-8 bytes reach the client
    assert b'"a\ud800b"' in out


def test_message_start_names_the_requested_model():
    """Protocol review (D95): a comment before the first chunk must not leave the model null."""
    out = events(MessagesEmitter(message_id="msg_test", model="qwen-x").feed(b": keep-alive\n\n"))
    assert out[0][1]["message"]["model"] == "qwen-x"


def test_an_error_still_follows_a_message_stop_that_was_never_sent():
    """Protocol review (D95): the relay asks for an error only when the response was not
    delivered; a message_stop encoded but lost must not suppress it."""
    e = MessagesEmitter(message_id="msg_test")
    e.feed(chunk({"content": "x"}) + chunk(finish="stop") + DONE)  # encoded, never sent

    assert [n for n, _ in events(e.error("archive_unavailable", "lost"))] == ["error"]
    assert e.error("again", "x") == b""
