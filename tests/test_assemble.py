"""palimnesis.assemble: one visible stream from one or more upstream calls (Phase 3B S1;
plan §2.2, D52, S0 delta 1).

Inputs are real Strata 0.1.48 streams recorded on Zeus (``eval/probes/fixtures/p17_*``,
docs/probes/strata.md §12.1); a test decides which tool names are hidden."""

from __future__ import annotations

import json
from pathlib import Path

from palimnesis.assemble import ChatAssembler
from palimnesis.sse import ChatStream, SSEParser

FIXTURES = Path(__file__).resolve().parents[1] / "eval" / "probes" / "fixtures"


def events(name: str):
    raw = (FIXTURES / f"{name}.sse").read_bytes()
    parser = SSEParser()
    out = parser.feed(raw)
    assert parser.close() == b""
    return raw, out


def hidden(*names):
    return lambda name: name in names


def run(asm: ChatAssembler, evs) -> tuple[bytes, list]:
    asm.begin()
    client, parts = b"", []
    for e in evs:
        out = asm.feed(e)
        client += out.client
        parts += out.parts
    return client, parts


def client_view(data: bytes) -> ChatStream:
    stream = ChatStream()
    for e in SSEParser().feed(data):
        stream.apply(e)
    return stream


def chunks(data: bytes) -> list[dict]:
    return [json.loads(e.data) for e in SSEParser().feed(data)
            if e.data is not None and e.data != "[DONE]"]


def test_a_call_with_no_hidden_tool_is_relayed_byte_for_byte():
    raw, evs = events("p17_parallel_off_0")
    asm = ChatAssembler(hidden("palimnesis_recall"))
    client, _ = run(asm, evs)
    assert asm.hidden_calls == [] and asm.continues is False
    client += asm.terminal()
    assert client == raw


def test_hidden_calls_never_reach_the_client_and_the_stream_waits_for_a_continuation():
    raw, evs = events("p17_parallel_off_0")  # two get_weather calls, hidden here
    asm = ChatAssembler(hidden("get_weather"))
    client, parts = run(asm, evs)
    assert asm.continues is True
    assert b"get_weather" not in client and b"tool_calls" not in client
    assert b"[DONE]" not in client and b"finish_reason\": \"tool_calls" not in client
    calls = asm.hidden_calls
    expected = client_view(raw).tool_calls  # three get_weather calls in this recording
    assert [(c.id, c.name, c.arguments) for c in calls] == [
        (e["id"], e["name"], e["arguments"]) for e in expected]
    assert {p[3].get("internal") for p in parts if p[0] == "tool_call"} == {True}


def test_a_continuation_joins_the_first_message_and_ends_once():
    _, first = events("p17_parallel_off_0")
    raw2, second = events("p17_single_off_0")
    hide = {"on": True}
    asm = ChatAssembler(lambda name: hide["on"])
    c1, _ = run(asm, first)
    hide["on"] = False
    c2, _ = run(asm, second)  # this call's get_weather is external
    tail = asm.terminal()
    out = chunks(c1 + c2 + tail)
    assert {c["id"] for c in out} == {chunks(c1)[0]["id"]}  # one message id throughout
    assert sum(1 for c in out if c["choices"] and "role" in c["choices"][0]["delta"]) == 1
    assert (c1 + c2 + tail).count(b"[DONE]") == 1
    finishes = [c["choices"][0]["finish_reason"] for c in out
                if c["choices"] and c["choices"][0].get("finish_reason")]
    assert finishes == ["tool_calls"]
    seen = client_view(c1 + c2 + tail)
    assert [c["name"] for c in seen.tool_calls] == ["get_weather"]
    assert seen.tool_calls[0]["id"] == client_view(raw2).tool_calls[0]["id"]


def test_external_calls_after_hidden_ones_are_renumbered_densely():
    raw, evs = events("p17_parallel_off_0")  # three calls; the first is hidden
    seen_names = []

    def is_hidden(name):
        seen_names.append(name)
        return len(seen_names) == 1  # the first call hidden, the second external

    asm = ChatAssembler(is_hidden)
    client, _ = run(asm, evs)
    client += asm.terminal()
    view = client_view(client)
    upstream = client_view(raw).tool_calls
    assert view.tool_calls == upstream[1:]
    indices = {tc["index"] for c in chunks(client) for ch in c["choices"]
               for tc in ch["delta"].get("tool_calls") or []}
    assert indices == {0, 1}
    assert asm.continues is False  # an external call waits for the harness


def test_text_after_a_hidden_call_is_visible_and_archived():
    raw, evs = events("p17_after_a_on_0")  # reasoning, call, then text
    upstream = client_view(raw)
    asm = ChatAssembler(hidden(upstream.tool_calls[0]["name"]))
    client, parts = run(asm, evs)
    view = client_view(client)
    assert view.content == upstream.content and view.reasoning == upstream.reasoning
    assert view.tool_calls == []
    archived_text = "".join(p[2] for p in parts if p[0] == "text")
    assert archived_text == upstream.content


def test_deltas_are_forwarded_as_they_arrive():
    _, evs = events("p17_after_a_on_0")
    asm = ChatAssembler(hidden("nothing"))
    asm.begin()
    reasoning_event = next(e for e in evs if e.data and "reasoning_content" in e.data)
    assert asm.feed(reasoning_event).client == reasoning_event.raw


def test_terminal_usage_sums_completion_tokens_and_reports_the_last_prompt():
    _, first = events("p17_parallel_off_0")
    _, second = events("p17_single_off_0")
    u1 = client_view(b"".join(e.raw for e in first)).usage
    u2 = client_view(b"".join(e.raw for e in second)).usage
    hide = {"on": True}
    asm = ChatAssembler(lambda name: hide["on"])
    run(asm, first)
    hide["on"] = False
    run(asm, second)
    usage = client_view(asm.terminal()).usage
    assert usage["prompt_tokens"] == u2["prompt_tokens"]
    assert usage["completion_tokens"] == u1["completion_tokens"] + u2["completion_tokens"]
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
    assert [u["completion_tokens"] for u in asm.call_usages] == [u1["completion_tokens"],
                                                                u2["completion_tokens"]]


def test_terminal_can_end_with_a_length_stop():
    _, first = events("p17_parallel_off_0")
    asm = ChatAssembler(hidden("get_weather"))
    client, _ = run(asm, first)
    tail = asm.terminal(finish_reason="length")
    finishes = [c["choices"][0]["finish_reason"] for c in chunks(client + tail)
                if c["choices"] and c["choices"][0].get("finish_reason")]
    assert finishes == ["length"] and tail.endswith(b"data: [DONE]\n\n")


def test_keep_alive_comments_are_relayed():
    raw, evs = events("p17_single_off_0")
    asm = ChatAssembler(hidden("get_weather"))
    client, _ = run(asm, evs)
    assert client.count(b": keep-alive") == raw.count(b": keep-alive") > 0
