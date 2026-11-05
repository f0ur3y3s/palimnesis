"""Reasoning carryover and cache accounting on Messages archives (Phase 4B S11, S12).

A Messages tool loop with thinking, a moving ``cache_control`` breakpoint (Pi and Claude
Code both move it every turn, HP3/HC3) and a proxy restart. What the upstream renders for
each turn must equal what the model generated, rendered as Chat with its reasoning
(contracts §9), whatever the client resent of it; and every prompt-cache change between
calls must be explained (contracts §10).
"""

from __future__ import annotations

import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from palimnesis.api import create_app
from palimnesis.config import Settings
from palimnesis.upstreams.strata import tokens

from .fake_upstream import FakeUpstream
from .servers import serve

ROOT = Path(__file__).resolve().parents[1]
CC = {"type": "ephemeral"}
READ = {"name": "read", "description": "Read a file.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}}}
SYSTEM = "You are a coding agent."
COUNTER = tokens.default()


def mbody(messages) -> bytes:
    return json.dumps({"model": "m", "max_tokens": 4096, "stream": True, "system": SYSTEM,
                       "tools": [READ], "messages": messages}).encode()


def post(url: str, messages) -> httpx.Response:
    r = httpx.post(f"{url}/s/msg-loop/v1/messages?beta=true", content=mbody(messages), timeout=60)
    assert r.status_code == 200, r.content[:300]
    return r


def last_cached(messages: list) -> list:
    """The client's moving breakpoint: a block list with cache_control on the last
    message's last block, every earlier single-text user message back to a string."""
    out = []
    for i, m in enumerate(messages):
        content = m["content"]
        if isinstance(content, list) and m["role"] == "user" and len(content) == 1 \
                and content[0]["type"] == "text":
            content = content[0]["text"]
        if i == len(messages) - 1:
            blocks = ([{"type": "text", "text": content}] if isinstance(content, str)
                      else [dict(b) for b in content])
            blocks[-1] = {**blocks[-1], "cache_control": CC}
            content = blocks
        out.append({**m, "content": content})
    return out


def render(body: dict, generation: bool = True) -> str:
    args = tokens.render_args_from_openai(body)
    return COUNTER.render(args["messages"], args["tools"], effort=args["effort"],
                          add_generation_prompt=generation)


@contextmanager
def proxy(fake, upstream_url, db):
    s = Settings(upstream_base_url=upstream_url, db_path=db)
    with serve(create_app(s), palimnesis=True) as url:
        yield url, s


ASSISTANT_1 = {"role": "assistant", "content": [
    {"type": "thinking", "thinking": "Plan: read a.txt first.", "signature": ""},
    {"type": "text", "text": "Reading."},
    {"type": "tool_use", "id": "call_1", "name": "read", "input": {"path": "a.txt"}}]}
ASSISTANT_2 = {"role": "assistant", "content": [
    {"type": "thinking", "thinking": "It holds a greeting.", "signature": ""},
    {"type": "text", "text": "It says hi."}]}


@pytest.mark.parametrize("thinking", ["resent", "omitted"])
def test_messages_tool_loop_rendered_tokens_golden_next_turn_restart(tmp_path, thinking):
    def resent(message):
        if thinking == "resent":
            return message
        return {**message, "content": [b for b in message["content"] if b["type"] != "thinking"]}

    fake = FakeUpstream()
    turn1 = [{"role": "user", "content": "What is in a.txt?"}]
    turn2 = turn1 + [resent(ASSISTANT_1), {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "call_1", "content": "hi"}]}]
    turn3 = turn2 + [resent(ASSISTANT_2), {"role": "user", "content": "Thanks. Now b.txt?"}]
    with serve(fake.app()) as upstream_url:
        with proxy(fake, upstream_url, tmp_path / "a.db") as (url, s):
            fake.respond_turn("Reading.", reasoning="Plan: read a.txt first.",
                              calls=[("call_1", "read", '{"path": "a.txt"}')])
            post(url, last_cached(turn1))
            fake.respond_turn("It says hi.", reasoning="It holds a greeting.")
            post(url, last_cached(turn2))
        with proxy(fake, upstream_url, tmp_path / "a.db") as (url, s):  # a new process
            fake.respond_turn("Reading b.", reasoning="Next file.",
                              calls=[("call_2", "read", '{"path": "b.txt"}')])
            post(url, last_cached(turn3))
        explained = subprocess.run([sys.executable, str(ROOT / "eval" / "replay.py"),
                                    "--explain", str(s.db_path), "--json"],
                                   capture_output=True, text=True, timeout=120)

    b1, b2, b3 = (json.loads(r.body) for r in fake.requests)
    # Golden: what the model generated, as Chat with its reasoning (contracts §9).
    golden2 = {**b1, "messages": [*b1["messages"],
                                  {"role": "assistant", "content": "Reading.",
                                   "reasoning_content": "Plan: read a.txt first.",
                                   "tool_calls": [{"id": "call_1", "type": "function", "function": {
                                       "name": "read", "arguments": '{"path": "a.txt"}'}}]},
                                  {"role": "tool", "tool_call_id": "call_1", "content": "hi"}]}
    assert render(b2) == render(golden2)
    golden3 = {**b2, "messages": [*b2["messages"],
                                  {"role": "assistant", "content": "It says hi.",
                                   "reasoning_content": "It holds a greeting."},
                                  {"role": "user", "content": "Thanks. Now b.txt?"}]}
    assert render(b3) == render(golden3)
    # Across the restart the earlier prompt is a prefix of the next one, token for token.
    assert render(b3).startswith(render(b2, generation=False))
    assert explained.returncode == 0, explained.stdout[-1500:] + explained.stderr[-1500:]


def test_cache_control_move_is_not_a_prefix_change(tmp_path):
    fake = FakeUpstream()
    turn1 = [{"role": "user", "content": "What is in a.txt?"}]
    turn2 = turn1 + [ASSISTANT_1, {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "call_1", "content": "hi"}]}]
    with serve(fake.app()) as upstream_url:
        with proxy(fake, upstream_url, tmp_path / "a.db") as (url, s):
            fake.respond_turn("Reading.", reasoning="Plan: read a.txt first.",
                              calls=[("call_1", "read", '{"path": "a.txt"}')])
            post(url, last_cached(turn1))
            fake.respond_turn("It says hi.", reasoning="It holds a greeting.")
            post(url, last_cached(turn2))
    import sqlite3

    conn = sqlite3.connect(f"file:{s.db_path}?mode=ro", uri=True)
    causes = [json.loads(p)["cause"] for (p,) in conn.execute(
        "SELECT payload FROM events WHERE kind = 'upstream_call' ORDER BY event_id")]
    conn.close()

    b1, b2 = (json.loads(r.body) for r in fake.requests)
    assert b2["messages"][1] == {"role": "user", "content": "What is in a.txt?"}
    assert causes[1] == "append", causes
