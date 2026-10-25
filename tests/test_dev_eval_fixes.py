"""Regressions for the Phase 3 development evaluation's defects (R21)."""

from __future__ import annotations

import json

from palimnesis.upstreams.strata import tokens

from .test_transcript_loop_http import _sse
from .test_view_http import DONE, body, history, post, view_stack

COUNTER = tokens.default()
TRUNCATED = '{"path":"notes.txt","content":"abc'  # cut off by finish_reason "length"


def _count(raw: bytes) -> int:
    return COUNTER.count_messages(**tokens.render_args_from_openai(json.loads(raw)))


# R21-A: a resent tool call whose arguments are cut-off JSON rendered as an error locally,
# so the view build failed and the whole history went upstream. Strata renders it (#510).
def test_a_resent_call_with_cut_off_arguments_is_still_bounded(tmp_path):
    messages = history(30) + [{"role": "assistant", "content": "ok"},
                              {"role": "user", "content": "save the notes"}]
    with view_stack(tmp_path, input_budget=8000, transcripts_enabled=False) as (fake, url, _):
        fake.respond_sse([_sse({"index": 0, "delta": {"tool_calls": [{
            "index": 0, "id": "call_w", "type": "function",
            "function": {"name": "read", "arguments": TRUNCATED}}]}},
            {"index": 0, "delta": {}, "finish_reason": "length"})])
        assert post(url, body(messages, max_completion_tokens=2048)).status_code == 200
        messages = messages + [
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_w", "type": "function",
                "function": {"name": "read", "arguments": TRUNCATED}}]},
            {"role": "tool", "tool_call_id": "call_w", "content": "error: invalid arguments"}]
        fake.respond_sse([DONE])
        assert post(url, body(messages, max_completion_tokens=2048)).status_code == 200

    assert _count(fake.requests[-1].body) <= 8000
    sent = json.loads(fake.requests[-1].body)["messages"]
    assert sent[-2]["tool_calls"][0]["function"]["arguments"] == TRUNCATED
    assert len(sent) < len(messages)

