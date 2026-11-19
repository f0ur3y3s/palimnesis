"""Phase 4A S7: the pinned state is the same for every client protocol (D105, position 4).

One conversation sent once as Anthropic Messages and once as Chat Completions gives the
same refresh call upstream (always Chat, D83), the same committed state and the same
archived provenance. Core keys off neither protocol nor harness for the state."""

from __future__ import annotations

import json

import httpx

from .test_messages_gl1 import mbody, mpost, rows, stack
from .test_notes_http import BUDGET, NOTES
from .test_state_golden import ALIAS


def _code(i):
    return "\n".join(f"def f{i}_{n}(x): return x * {n}  # {n}" for n in range(80))


def _messages_conversation():
    out = []
    for t in range(3):
        out.append({"role": "user", "content": f"Instruction {t}: implement part {t}."})
        for i in range(6):
            call = f"call_{t}_{i}"
            out.append({"role": "assistant", "content": [
                {"type": "tool_use", "id": call, "name": "read", "input": {}}]})
            out.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": call, "content": _code(t * 6 + i)}]})
    out.append({"role": "assistant", "content": [{"type": "text", "text": "done"}]})
    out.append({"role": "user", "content": "Instruction 3: finish."})
    return out


def _chat_conversation():
    out = [{"role": "system", "content": "S"}]
    for t in range(3):
        out.append({"role": "user", "content": f"Instruction {t}: implement part {t}."})
        for i in range(6):
            call = f"call_{t}_{i}"
            out.append({"role": "assistant", "content": None, "tool_calls": [
                {"id": call, "type": "function", "function": {"name": "read", "arguments": "{}"}}]})
            out.append({"role": "tool", "tool_call_id": call, "content": _code(t * 6 + i)})
    out.append({"role": "assistant", "content": "done"})
    out.append({"role": "user", "content": "Instruction 3: finish."})
    return out


READ_MESSAGES = {"name": "read", "description": "read a file", "input_schema": {"type": "object"}}
READ_CHAT = {"type": "function", "function": {"name": "read", "description": "read a file",
                                              "parameters": {"type": "object"}}}


def _named(raw: bytes) -> dict:
    """The body with each archive alias (hashed from random ids) named by first use."""
    seen: dict[str, str] = {}
    text = ALIAS.sub(lambda m: "§A" + seen.setdefault(m.group(1), str(len(seen) + 1)),
                     raw.decode("utf-8"))
    return json.loads(text)


def _state(db):
    return rows(db, "SELECT v.status, v.text, o.content, o.archive_seq, o.prompt_format,"
                    " o.header, o.dropped FROM notes_versions v"
                    " JOIN notes_outputs o USING (notes_id)")


def test_state_refresh_identical_for_chat_and_messages_clients(tmp_path):
    # Transcript paths name the archive folder and session; leave them out of the comparison.
    settings = dict(input_budget=BUDGET, notes_tokens=2048, notes_format="n2",
                    transcripts_enabled=False)
    (tmp_path / "m").mkdir()
    (tmp_path / "c").mkdir()
    with stack(tmp_path / "m", **settings) as (fake_m, url, s_m):
        fake_m.respond_counted(NOTES)
        fake_m.respond_counted("visible answer")
        assert mpost(url, mbody(_messages_conversation(), tools=[READ_MESSAGES])).status_code == 200
    with stack(tmp_path / "c", **settings) as (fake_c, url, s_c):
        fake_c.respond_counted(NOTES)
        fake_c.respond_counted("visible answer")
        body = json.dumps({"model": "m", "max_completion_tokens": 8192, "stream": True,
                           "tools": [READ_CHAT], "messages": _chat_conversation()}).encode()
        r = httpx.post(f"{url}/s/gl1-chat/v1/chat/completions", content=body, timeout=30)
        assert r.status_code == 200

    refresh_m, refresh_c = (_named(f.requests[0].body) for f in (fake_m, fake_c))
    assert refresh_m["messages"] == refresh_c["messages"]
    assert refresh_m["tools"] == refresh_c["tools"]
    assert _state(s_m.db_path) == _state(s_c.db_path) != []
