"""A complete turn whose tool-call arguments are not JSON, resent by the client with
arguments "{}" (OpenCode 2.1.4, docs/harnesses.md; R31, D68), through the fake upstream."""

from __future__ import annotations

import json
from pathlib import Path

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



# OMP 18.16.0 resends a call whose arguments never parsed as {"__parseError", "__rawJson"}:
# its ``qwt`` keeps the first 512 UTF-16 code units and appends "… [truncated N chars]"
# (N in code units), or keeps a string of at most 512 units whole (D104). The literal
# fixture is the resend recorded in R58.
FIXTURE = json.loads((Path(__file__).resolve().parents[1] / "eval" / "fixtures" / "omp-18.16.0"
                      / "length_stopped_call.json").read_text(encoding="utf-8"))


def _generate(lc, arguments: str, finish: str = "length", call_id: str = "call_w1") -> None:
    lc.upstream.respond_sse([
        chunk({"role": "assistant", "content": ""}),
        chunk({"tool_calls": [{"index": 0, "id": call_id, "type": "function",
                               "function": {"name": "write", "arguments": arguments}}]}),
        chunk({}, finish), DONE])
    assert lc.post(SID, body([user("build game")])).status_code == 200


def _resend_preview(lc, arguments: str, call_id: str = "call_w1"):
    lc.upstream.respond_sse(answer("continuing"))
    return lc.post(SID, body([
        user("build game"),
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": call_id, "type": "function",
                         "function": {"name": "write", "arguments": arguments}}]},
        {"role": "tool", "tool_call_id": call_id,
         "content": "Tool call was not executed because the assistant hit its output token limit"},
    ]))


def _js_preview(raw: str) -> str:
    """OMP's ``qwt`` (512 UTF-16 code units), written out for the test's own inputs."""
    units = raw.encode("utf-16-le", "surrogatepass")
    if len(units) <= 1024:
        return raw
    head = units[:1024].decode("utf-16-le", "surrogatepass")
    return f"{head}… [truncated {len(units) // 2 - 512} chars]"


def _wrapper(preview: str, error: str = "Unterminated string") -> str:
    return json.dumps({"__parseError": error, "__rawJson": preview}, ensure_ascii=False)


def test_recorded_preview_of_a_length_stopped_call_reconciles(lc):
    _generate(lc, FIXTURE["generated_arguments"], call_id=FIXTURE["call_id"])
    r = _resend_preview(lc, FIXTURE["resent_arguments"], call_id=FIXTURE["call_id"])
    assert r.status_code == 200, r.content[:300]
    upstream = json.loads(lc.upstream.requests[-1].body)["messages"]
    # Upstream gets the client's copy, as for "{}" (D68); the archive keeps the generation.
    assert upstream[1]["tool_calls"][0]["function"]["arguments"] == FIXTURE["resent_arguments"]
    with lc.db() as c:
        archived = [b for (b,) in c.execute(
            "SELECT s.bytes FROM segments s JOIN blocks b ON b.block_id = s.block_id"
            " WHERE b.kind = 'tool_call'")]
    assert archived == [FIXTURE["generated_arguments"].encode()]


def test_short_invalid_arguments_kept_whole_reconcile(lc):
    _generate(lc, CUT, finish="tool_calls")
    r = _resend_preview(lc, _wrapper(CUT))
    assert r.status_code == 200, r.content[:300]


def test_preview_counts_utf16_code_units(lc):
    cut = '{"path":"index.html","content":"' + ("🚀" * 300)
    _generate(lc, cut)
    r = _resend_preview(lc, _wrapper(_js_preview(cut)))
    assert r.status_code == 200, r.content[:300]


@pytest.mark.parametrize("change", ["prefix", "count", "valid_json"])
def test_preview_that_does_not_match_the_generation_diverges(lc, change):
    cut = '{"path":"index.html","content":"' + ("x" * 600)
    generated = '{"path":"index.html","content":"' + ("x" * 600) + '"}' if change == "valid_json" else cut
    _generate(lc, generated)
    preview = _js_preview(cut)
    if change == "prefix":
        preview = cut[:511] + "y" + preview[512:]
    elif change == "count":
        preview = preview.replace("truncated ", "truncated 1")
    r = _resend_preview(lc, _wrapper(preview))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "history_divergence"
