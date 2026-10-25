"""A transcript-search tool loop through the proxy (A1 GL9, GL10; plan S9).

The model looks something up in its transcript files with the harness's own
tools: grep, then a bounded read. Each step is an ordinary tool step, so the
excerpt block of the instruction, the archived reasoning of earlier tool calls
and the prefix must all survive the loop and a proxy restart.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from palimnesis.projector import session_dir

from .test_recall_http import NEEDLE, _with_needle
from .test_view_http import DONE, SID, body, post, rows, view_stack

REPLAY = Path(__file__).resolve().parents[1] / "eval" / "replay.py"
QUESTION = "where did ERR_ZX81 come from?"


def _sse(*chunks: dict) -> bytes:
    return b"".join(b"data: " + json.dumps({"choices": [c]}).encode() + b"\n\n" for c in chunks) \
        + b"data: [DONE]\n\n"


def _tool_call(call_id: str, name: str, args: dict, reasoning: str) -> bytes:
    return _sse({"index": 0, "delta": {"reasoning_content": reasoning}},
                {"index": 0, "delta": {"tool_calls": [{"index": 0, "id": call_id, "type": "function",
                                                       "function": {"name": name,
                                                                    "arguments": json.dumps(args)}}]}},
                {"index": 0, "delta": {}, "finish_reason": "tool_calls"})


def _assistant_call(call_id: str, name: str, args: dict) -> dict:
    # As OpenCode resends it: the tool call, without the reasoning.
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function",
         "function": {"name": name, "arguments": json.dumps(args)}}]}


def _upstream_messages(fake, i):
    return json.loads(fake.requests[i].body)["messages"]


def _host(messages):
    return next(m for m in messages if m["role"] == "user" and m["content"].startswith(QUESTION))


def test_a_grep_then_bounded_read_loop_keeps_excerpts_reasoning_and_prefix_across_a_restart(tmp_path):
    where = str(session_dir(tmp_path / "transcripts", SID))
    grep = {"pattern": "ERR_ZX81", "path": where}
    read = {"filePath": f"{where}/turn-0001.md", "offset": 50, "limit": 20}
    hit_lines = "\n".join(f"line {n}: " + ("context" if n != 57 else NEEDLE) for n in range(50, 70))
    messages = _with_needle() + [{"role": "assistant", "content": "done"},
                                 {"role": "user", "content": QUESTION}]
    with view_stack(tmp_path, input_budget=8000) as (fake, url, settings):
        fake.respond_sse([_tool_call("call_g", "grep", grep, "Search the transcript.")])
        post(url, body(messages, max_completion_tokens=8192))
        messages += [_assistant_call("call_g", "grep", grep),
                     {"role": "tool", "tool_call_id": "call_g",
                      "content": f"{where}/turn-0001.md:57: {NEEDLE}"}]
        fake.respond_sse([_tool_call("call_r", "read", read, "Read around line 57.")])
        post(url, body(messages, max_completion_tokens=8192))
        messages += [_assistant_call("call_r", "read", read),
                     {"role": "tool", "tool_call_id": "call_r", "content": hit_lines}]
        fake.respond_sse([DONE])
        post(url, body(messages, max_completion_tokens=8192))
    messages += [{"role": "assistant", "content": "ok"},
                 {"role": "user", "content": "thanks, now fix it"}]
    with view_stack(tmp_path, input_budget=8000) as (fake2, url, settings):
        fake2.respond_sse([DONE])
        post(url, body(messages, max_completion_tokens=8192))

    steps = [_upstream_messages(fake, i) for i in range(3)] + [_upstream_messages(fake2, 0)]
    # The instruction's excerpt block is identical in every step, restart included.
    hosts = [_host(m)["content"] for m in steps]
    assert NEEDLE in hosts[0] and "[palimnesis excerpts x1" in hosts[0]
    assert all(h == hosts[0] for h in hosts)
    # Archived reasoning of the earlier tool calls is restored (contracts §9).
    calls = [m for m in steps[3] if m.get("tool_calls")
             and m["tool_calls"][0]["id"] in ("call_g", "call_r")]
    assert [m.get("reasoning_content") for m in calls] == ["Search the transcript.",
                                                          "Read around line 57."]
    # The bounded read reaches the model verbatim, then and after the restart.
    for m in steps[2:]:
        assert any(x.get("role") == "tool" and x.get("content") == hit_lines for x in m)
    # Every step after the first is a pure append; the archive explains each call.
    out = subprocess.run([sys.executable, str(REPLAY), "--explain", str(settings.db_path), "--json"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    causes = [json.loads(p)["cause"] for (p,) in rows(
        settings, "SELECT payload FROM events WHERE kind = 'upstream_call' ORDER BY rowid")]
    assert causes[1:] == ["append", "append", "append"]


def test_an_oversized_transcript_read_is_stubbed_and_a_narrowed_read_passes_verbatim(tmp_path):
    where = str(session_dir(tmp_path / "transcripts", SID))
    wide = {"filePath": f"{where}/turn-0001.md"}
    narrow = {"filePath": f"{where}/turn-0001.md", "offset": 1490, "limit": 20}
    whole = "\n".join(f"{n}: " + ("x " * 12 if n != 1500 else NEEDLE) for n in range(3000))
    window = "\n".join(whole.split("\n")[1490:1510])
    messages = _with_needle() + [{"role": "assistant", "content": "done"},
                                 {"role": "user", "content": QUESTION}]
    with view_stack(tmp_path, input_budget=8000) as (fake, url, _):
        fake.respond_sse([_tool_call("call_w", "read", wide, "Read the turn.")])
        post(url, body(messages, max_completion_tokens=8192))
        messages += [_assistant_call("call_w", "read", wide),
                     {"role": "tool", "tool_call_id": "call_w", "content": whole}]
        fake.respond_sse([_tool_call("call_n", "read", narrow, "Too long; narrow it.")])
        post(url, body(messages, max_completion_tokens=8192))
        messages += [_assistant_call("call_n", "read", narrow),
                     {"role": "tool", "tool_call_id": "call_n", "content": window}]
        fake.respond_sse([DONE])
        post(url, body(messages, max_completion_tokens=8192))

    after_wide, after_narrow = _upstream_messages(fake, 1), _upstream_messages(fake, 2)
    stubbed = next(m for m in after_wide if m.get("tool_call_id") == "call_w")
    assert stubbed["content"].startswith("[palimnesis s1") and "3,000 lines" in stubbed["content"]
    assert any(m.get("tool_call_id") == "call_n" and m["content"] == window for m in after_narrow)
    assert NEEDLE in window
