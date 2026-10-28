"""A complete turn whose tool-call arguments are not JSON, resent by the client with
arguments "{}" (OpenCode 2.1.4, docs/harnesses.md; R31, D68), through the fake upstream."""

from __future__ import annotations

import json

import pytest

from .archive_helpers import DONE, answer, body, chunk, lifecycle_stack, user

SID = "unparsable-args-1"
CUT = '{"filePath": "notes.txt", "content": "unterminated'


@pytest.fixture
def lc(tmp_path):
    with lifecycle_stack(tmp_path) as s:
        yield s


def _call_turn(lc, arguments: str) -> None:
    lc.upstream.respond_sse([
        chunk({"role": "assistant", "content": "", "reasoning_content": "write it"}),
        chunk({"tool_calls": [{"index": 0, "id": "call_w1", "type": "function",
                               "function": {"name": "write", "arguments": arguments}}]}),
        chunk({}, "tool_calls"), DONE])
    assert lc.post(SID, body([user("write notes")])).status_code == 200


def _resend(lc, arguments: str):
    lc.upstream.respond_sse(answer("retrying"))
    return lc.post(SID, body([
        user("write notes"),
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "call_w1", "type": "function",
                         "function": {"name": "write", "arguments": arguments}}]},
        {"role": "tool", "tool_call_id": "call_w1",
         "content": "The arguments provided to the tool are invalid: " + CUT},
    ]))


def test_unparsable_arguments_resent_as_an_empty_object_extend_the_session(lc):
    _call_turn(lc, CUT)

    r = _resend(lc, "{}")

    assert r.status_code == 200, r.content[:300]
    upstream = json.loads(lc.upstream.requests[-1].body)["messages"]
    # Upstream gets the client's copy, as for a partial tool call and as passthrough would.
    assert upstream[1]["tool_calls"][0]["function"]["arguments"] == "{}"
    assert upstream[2]["role"] == "tool"
    with lc.db() as c:  # the archive still holds what the model generated
        archived = [b for (b,) in c.execute(
            "SELECT s.bytes FROM segments s JOIN blocks b ON b.block_id = s.block_id"
            " WHERE b.kind = 'tool_call'")]
    assert archived == [CUT.encode()]


INTERRUPTED = '{"error":{"type":"aborted","message":"Tool execution interrupted: read"},"content":[]}'


def test_an_interrupted_call_resent_with_empty_arguments_extends_the_session(lc):
    """R34, D73: a turn killed while OpenCode ran a complete, valid call; OpenCode resends
    the call with arguments "{}" and its aborted result."""
    _call_turn(lc, '{"filePath": "notes.txt"}')
    lc.upstream.respond_sse(answer("retrying"))
    r = lc.post(SID, body([
        user("write notes"),
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "call_w1", "type": "function",
                         "function": {"name": "write", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_w1", "content": INTERRUPTED},
    ]))

    assert r.status_code == 200, r.content[:300]
    with lc.db() as c:  # the archive still holds what the model generated
        archived = [b for (b,) in c.execute(
            "SELECT s.bytes FROM segments s JOIN blocks b ON b.block_id = s.block_id"
            " WHERE b.kind = 'tool_call'")]
    assert archived == [b'{"filePath": "notes.txt"}']


def test_json_arguments_resent_with_other_values_still_diverge(lc):
    _call_turn(lc, '{"filePath": "notes.txt"}')

    r = _resend(lc, '{"filePath": "other.txt"}')

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "history_divergence"
