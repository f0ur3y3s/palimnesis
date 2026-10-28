"""``serve --protect-turn`` through the proxy (D70): the upstream sees the current turn's
own steps, and the view version records the policy."""

from __future__ import annotations

import json

from .test_view_http import DONE, _code, body, post, rows, upstream_tokens, view_stack

INSTRUCTION = "Implement the roster checker and run the tests."


def _turn():
    messages = [{"role": "system", "content": "You are a coding agent."},
                {"role": "user", "content": INSTRUCTION}]

    def group(i, output):
        messages.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": f"call_{i}", "type": "function", "function": {"name": "read", "arguments": "{}"}}]})
        messages.append({"role": "tool", "tool_call_id": f"call_{i}", "content": output})

    for i in range(6):
        group(i, f"ok step {i}")
    group(10, _code(10, 420))
    group(30, _code(30, 600))
    return messages


def _send(tmp_path, **settings):
    with view_stack(tmp_path, input_budget=24_320, **settings) as (fake, url, s):
        fake.respond_sse([DONE])
        assert post(url, body(_turn(), max_completion_tokens=8192)).status_code == 200
    return json.loads(fake.requests[-1].body)["messages"], fake.requests[-1].body, s


def _spans(messages):
    return [m for m in messages if m["role"] == "user"
            and str(m.get("content")).startswith("[palimnesis s1 span")]


def test_without_the_flag_the_turns_steps_are_collapsed(tmp_path):
    messages, _, s = _send(tmp_path)

    assert _spans(messages)
    assert rows(s, "SELECT policy_version FROM view_versions")[-1] == ("v2",)


def test_with_the_flag_the_upstream_sees_the_turns_steps(tmp_path):
    messages, raw, s = _send(tmp_path, protect_turn=True)

    assert not _spans(messages)
    assert [m["content"] for m in messages if m["role"] == "tool"][:6] == \
        [f"ok step {i}" for i in range(6)]
    assert upstream_tokens(raw) <= 24_320
    assert rows(s, "SELECT policy_version FROM view_versions")[-1] == ("v2+turn",)
