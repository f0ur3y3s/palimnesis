"""The hidden recall loop through the archive relay (Phase 3B S5; plan §2.2–§2.4,
contracts §7, D52–D56).

A masked session with hidden tools: when the model calls ``palimnesis_*`` tools, the
proxy answers them itself and calls the upstream again; the client sees one message."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from palimnesis import archive
from palimnesis.sse import ChatStream, SSEParser

from .test_view_http import body, history, post, rows, upstream_tokens, view_stack

REPLAY = Path(__file__).resolve().parents[1] / "eval" / "replay.py"
GREP = ("call_h1", "palimnesis_grep", '{"query": "f3_7", "mode": "text", "scope": "all"}')
RECALL_BAD = ("call_h2", "palimnesis_recall", '{"id": "§ZZZZZZ.0"}')
EXTERNAL = ("call_e1", "read", '{"path": "x.py"}')


def _turn(messages, user, answer="ok"):
    return messages + [{"role": "assistant", "content": answer}, {"role": "user", "content": user}]


def _masked(user="where is f3_7 defined?"):
    return _turn(history(30), user)


def _seen(r) -> ChatStream:
    stream = ChatStream()
    for e in SSEParser().feed(r.content):
        stream.apply(e)
    return stream


def _messages(raw: bytes) -> list[dict]:
    return json.loads(raw)["messages"]


def _post(url, messages, **kw):
    return post(url, body(messages, max_completion_tokens=kw.pop("limit", 8192), **kw))


def test_a_hidden_call_is_answered_and_the_client_sees_one_message(tmp_path):
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, settings):
        fake.respond_turn("Checking. ", calls=[GREP])
        fake.respond_turn("It is in read 3.")
        r = _post(url, _masked())

    seen = _seen(r)
    assert r.status_code == 200 and seen.done and seen.error is None
    assert seen.content == "Checking. It is in read 3." and seen.tool_calls == []
    assert seen.finish_reason == "stop"
    assert b"palimnesis" not in r.content and r.content.count(b"[DONE]") == 1
    assert len(fake.requests) == 2
    second = _messages(fake.requests[1].body)
    assert second[-2]["tool_calls"][0]["function"]["name"] == "palimnesis_grep"
    assert second[-2]["content"] == "Checking. "
    assert second[-1]["role"] == "tool" and second[-1]["tool_call_id"] == "call_h1"
    assert "def f3_7" in second[-1]["content"] and "§" in second[-1]["content"]
    assert upstream_tokens(fake.requests[1].body) <= 8000
    assert rows(settings, "SELECT count(*) FROM generations") == [(2,)]
    assert rows(settings, "SELECT count(*) FROM occurrences WHERE source = 'internal_tool'") == [(1,)]
    assert rows(settings, "SELECT count(*) FROM events WHERE kind = 'turn_complete'") == [(1,)]


def test_the_next_turn_resends_one_message_and_the_upstream_sees_every_part(tmp_path):
    messages = _masked()
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, _):
        fake.respond_turn("Checking. ", calls=[GREP])
        fake.respond_turn("It is in read 3.")
        _post(url, messages)
        fake.respond_turn("Done.")
        r = _post(url, _turn(messages, "thanks", "Checking. It is in read 3."))

    assert r.status_code == 200
    up = _messages(fake.requests[-1].body)
    names = [tc["function"]["name"] for m in up for tc in m.get("tool_calls") or []]
    assert "palimnesis_grep" in names or any("§" in (m.get("content") or "") for m in up)
    assert up[-1] == {"role": "user", "content": "thanks"}


def test_mixed_calls_answer_the_hidden_one_and_hand_the_external_one_to_the_client(tmp_path):
    messages = _masked()
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, _):
        fake.respond_turn("Looking. ", calls=[GREP, EXTERNAL])
        r = _post(url, messages)
        seen = _seen(r)
        assert len(fake.requests) == 1  # the harness runs the external call first
        assert [c["name"] for c in seen.tool_calls] == ["read"]
        assert seen.finish_reason == "tool_calls" and b"palimnesis" not in r.content
        resent = {"role": "assistant", "content": "Looking. ", "tool_calls": [
            {"id": "call_e1", "type": "function",
             "function": {"name": "read", "arguments": '{"path": "x.py"}'}}]}
        fake.respond_turn("Read it.")
        r2 = _post(url, messages + [resent, {"role": "tool", "tool_call_id": "call_e1",
                                             "content": "x = 1"}])

    assert r2.status_code == 200
    up = _messages(fake.requests[-1].body)
    roles = [(m["role"], m.get("tool_call_id")) for m in up[-3:]]
    assert roles == [("assistant", None), ("tool", "call_h1"), ("tool", "call_e1")]


def test_an_error_result_is_answered_and_counted(tmp_path):
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, settings):
        fake.respond_turn(calls=[RECALL_BAD])
        fake.respond_turn("I could not find it.")
        r = _post(url, _masked())

    assert _seen(r).content == "I could not find it."
    result = _messages(fake.requests[1].body)[-1]["content"]
    assert result.startswith("error (unknown_address)")


def test_too_many_continuations_end_with_a_length_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "MAX_CONTINUATIONS", 2)
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, settings):
        for i in range(5):
            fake.respond_turn(f"step {i}. ", calls=[(f"call_{i}", "palimnesis_catalog", "{}")])
        r = _post(url, _masked())

    seen = _seen(r)
    assert len(fake.requests) == 3  # the first call and two continuations
    assert seen.finish_reason == "length" and seen.content == "step 0. step 1. step 2. "
    # every hidden call has a result, so later renders never carry a call without one
    calls = rows(settings, "SELECT count(*) FROM blocks WHERE kind = 'tool_call'"
                           " AND json_extract(meta, '$.internal')")[0][0]
    results = rows(settings, "SELECT count(*) FROM occurrences WHERE source = 'internal_tool'")
    assert results == [(calls,)]


def test_the_allowance_is_shared_and_never_reset(tmp_path):
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, _):
        fake.respond_turn("one. ", calls=[GREP], completion_tokens=3000)
        fake.respond_turn("two.", completion_tokens=10)
        r = _post(url, _masked(), limit=5000)

    assert _seen(r).finish_reason == "stop"
    second = json.loads(fake.requests[1].body)
    assert second["max_completion_tokens"] == 2000  # 5,000 allowed − 3,000 used
    assert _seen(r).usage["completion_tokens"] == 3010


def test_no_continuation_starts_with_less_than_1024_tokens_of_allowance(tmp_path):
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, _):
        fake.respond_turn("one. ", calls=[GREP], completion_tokens=4500)
        r = _post(url, _masked(), limit=5000)

    assert len(fake.requests) == 1 and _seen(r).finish_reason == "length"


def test_continuations_are_explained_across_a_restart(tmp_path):
    messages = _masked()
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, settings):
        fake.respond_turn("Checking. ", calls=[GREP])
        fake.respond_turn("It is in read 3.")
        _post(url, messages)
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, settings):
        fake.respond_turn("Done.")
        assert _post(url, _turn(messages, "thanks", "Checking. It is in read 3.")).status_code == 200

    calls = [json.loads(p) for (p,) in rows(
        settings, "SELECT payload FROM events WHERE kind = 'upstream_call' ORDER BY event_id")]
    assert "internal_continuation" in calls[1]["cause"].split(",")
    assert len({c["call_id"] for c in calls}) == 3
    report = subprocess.run([sys.executable, str(REPLAY), "--explain", str(settings.db_path)],
                            capture_output=True, text=True)
    assert report.returncode == 0, report.stdout


def test_a_session_without_hidden_tools_relays_as_before(tmp_path):
    with view_stack(tmp_path, input_budget=8000) as (fake, url, _):
        fake.respond_turn("plain")
        r = _post(url, _masked())

    assert _seen(r).content == "plain" and len(fake.requests) == 1


@pytest.mark.parametrize("stream", [False])
def test_non_streaming_requests_get_no_hidden_tools(tmp_path, stream):
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, _):
        fake.respond_counted(stream=False)
        post(url, body(_masked(), max_completion_tokens=8192, stream=False))

    tools = [t["function"]["name"] for t in json.loads(fake.requests[-1].body).get("tools") or []]
    assert not any(n.startswith("palimnesis_") for n in tools)


def test_a_continuation_records_no_view_move_of_its_own_when_nothing_grew(tmp_path):
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, settings):
        fake.respond_turn(calls=[("call_c", "palimnesis_catalog", "{}")])
        fake.respond_turn(calls=[("call_d", "palimnesis_catalog", '{"page": 1}')])
        fake.respond_turn("done")
        _post(url, _masked("go on"))  # no excerpt selection: the base view's state stands

    moves = rows(settings, "SELECT watermark_seq, collapse_seq FROM view_versions ORDER BY n")
    assert len(moves) == len(set(moves))  # no version repeats the one before it



def test_reasoning_carries_through_a_continuation_the_next_turn_and_a_restart(tmp_path):
    """§9 through hidden calls: each part keeps its own reasoning upstream, whether or not
    the client resends it, and a restart renders the same tokens."""
    messages = _masked()
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, _):
        fake.respond_turn("Checking. ", reasoning="Search first.", calls=[GREP])
        fake.respond_turn("It is in read 3.", reasoning="Found the definition.")
        r = _post(url, messages)
        assert _seen(r).reasoning == "Search first.Found the definition."
        second = _messages(fake.requests[1].body)
        assert second[-2]["reasoning_content"] == "Search first."
        fake.respond_turn("Done.")
        _post(url, _turn(messages, "thanks", "Checking. It is in read 3."))
        live = _messages(fake.requests[-1].body)
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, _):
        fake.respond_turn("More.")
        resent = _turn(_turn(messages, "thanks", "Checking. It is in read 3."), "more", "Done.")
        resent[-4]["reasoning_content"] = "Search first.Found the definition."
        assert _post(url, resent).status_code == 200
        restarted = _messages(fake.requests[-1].body)

    parts = [m for m in live if m.get("reasoning_content") in ("Search first.",
                                                               "Found the definition.")]
    assert [p["reasoning_content"] for p in parts] == ["Search first.", "Found the definition."]
    # the same upstream history after a restart, with or without the resent reasoning
    assert restarted[:len(live)] == live


def test_transcripts_show_hidden_results_flagged_and_verify(tmp_path):
    from palimnesis import cli
    from palimnesis.projector import session_dir

    from .test_view_http import SID

    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, settings):
        fake.respond_turn("Checking. ", calls=[GREP])
        fake.respond_turn("It is in read 3.")
        _post(url, _masked())
    root = tmp_path / "transcripts"
    args = ["--db", str(settings.db_path), "--root", str(root)]
    assert cli.main(["transcripts", "rebuild", SID, *args]) == 0
    assert cli.main(["transcripts", "verify", SID, *args]) == 0
    turns = sorted(session_dir(root, SID).glob("turn-*.md"))
    last = turns[-1].read_text(encoding="utf-8")
    result = [line for line in last.splitlines() if "tool_result" in line and "call_h1" in line]
    assert result and "internal" in result[0]
