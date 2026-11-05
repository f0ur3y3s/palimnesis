"""Lookup budget per instruction through the archive relay (Phase 3B S10b, F3 / D67).

At most 16 hidden calls per turn: from the latest instruction in the branch, counting
archived internal results after it plus the calls already answered in this response.
When spent, each further hidden call gets the turn-limit text. OpenCode's length
follow-up is synthetic, so it starts no turn and resets nothing; a genuine user
instruction does. The per-response limits of §2.4 (8 calls, 4 continuations) stay,
so a turn of 16 spans at least two client requests here."""

from __future__ import annotations

import json

from palimnesis.archive import pipeline as archive

from .test_hidden_loop_http import _messages, _post, _seen
from .test_view_http import history, view_stack

# Spec literals (plan phase3b, "Delta: R29 fixes before D64", F3).
TURN_LIMIT = ("limit reached: no more archive lookups until the next user message. "
              "Continue from what you have.")
RESPONSE_LIMIT = ("limit reached: no more archive lookups in this response. "
                  "Answer from what you have.")
# OpenCode 2.1.4's follow-up after a ``length`` stop, verbatim
# (eval/fixtures/opencode-2.1.4/hidden_stream/b_length_text/req-03.json).
LENGTH_FOLLOW_UP = ("Your last response hit the output token limit (stop reason: length). Do not "
                    "apologize, recap, or repeat yourself. Break the remaining work into smaller "
                    "pieces.")
INSTRUCTION = "find every helper named f*_1 and tell me where each is defined"


def _grep(i):
    return (f"call_g{i}", "palimnesis_grep",
            json.dumps({"query": f"f{i}_1", "mode": "text", "scope": "all"}))


def _greps(start, n):
    return [_grep(i) for i in range(start, start + n)]


def _ids(start, n):
    return [f"call_g{i}" for i in range(start, start + n)]


def _external(n):
    return (f"call_e{n}", "read", json.dumps({"path": f"x{n}.py"}))


def _resent(text, n):
    """The assistant message as the client saw it: visible text and the external call."""
    call_id, name, arguments = _external(n)
    return [{"role": "assistant", "content": text, "tool_calls": [
                {"id": call_id, "type": "function",
                 "function": {"name": name, "arguments": arguments}}]},
            {"role": "tool", "tool_call_id": call_id, "content": f"x{n} = 1"}]


def _results(raw: bytes, ids) -> list:
    """The tool results the upstream received for these hidden call ids."""
    by_id = {m.get("tool_call_id"): m.get("content") for m in _messages(raw)
             if m["role"] == "tool"}
    return [by_id.get(i) for i in ids]


def _answered(result) -> bool:
    return (isinstance(result, str) and result.startswith("[palimnesis_grep")
            and result not in (TURN_LIMIT, RESPONSE_LIMIT))


def _spend_16_with_tool_results(fake, url, messages):
    """One instruction; two client requests of 8 hidden calls each, with an external
    tool result between them. Returns the client's messages after both."""
    fake.respond_turn("Looking. ", calls=[*_greps(0, 8), _external(1)])
    r1 = _post(url, messages)
    assert [c["name"] for c in _seen(r1).tool_calls] == ["read"]
    messages = messages + _resent("Looking. ", 1)
    fake.respond_turn("More. ", calls=[*_greps(8, 8), _external(2)])
    r2 = _post(url, messages)
    assert [c["name"] for c in _seen(r2).tool_calls] == ["read"]
    # Calls 1-8 were answered from the archive: a response's results reach the
    # upstream in the next request, in its newest group.
    first = _results(fake.requests[1].body, _ids(0, 8))
    assert all(_answered(r) for r in first), first
    return messages + _resent("More. ", 2)


def _assert_second_eight_answered(fake):
    """Calls 9-16 (the second request's) as the third request's first call received them."""
    second = _results(fake.requests[2].body, _ids(8, 8))
    assert all(_answered(r) for r in second), second


def _base():
    return history(30) + [{"role": "assistant", "content": "ok"},
                          {"role": "user", "content": INSTRUCTION}]


def test_the_turn_budget_constants():
    assert getattr(archive, "MAX_TURN_HIDDEN_CALLS", None) == 16
    assert getattr(archive, "TURN_LIMIT_RESULT", None) == TURN_LIMIT
    assert archive.MAX_HIDDEN_CALLS == 8  # the per-response cap is unchanged


def test_the_17th_hidden_call_of_a_turn_across_requests_gets_the_turn_limit(tmp_path):
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, _):
        messages = _spend_16_with_tool_results(fake, url, _base())
        fake.respond_turn(calls=_greps(16, 2))  # the 17th and 18th
        fake.respond_turn("Done.")
        r3 = _post(url, messages)

    assert len(fake.requests) == 4
    _assert_second_eight_answered(fake)
    assert _results(fake.requests[3].body, _ids(16, 2)) == [TURN_LIMIT, TURN_LIMIT]
    seen = _seen(r3)
    assert seen.content == "Done." and seen.finish_reason == "stop"
    assert b"palimnesis" not in r3.content


def test_a_hidden_call_after_the_turn_limit_in_a_later_continuation_ends_with_length(tmp_path):
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, _):
        messages = _spend_16_with_tool_results(fake, url, _base())
        fake.respond_turn("Checking. ", calls=_greps(16, 1))  # refused: the turn is spent
        fake.respond_turn("Again. ", calls=_greps(17, 1))  # a further call after a refusal
        fake.respond_turn("never")
        r3 = _post(url, messages)

    _assert_second_eight_answered(fake)
    assert _results(fake.requests[3].body, _ids(16, 1)) == [TURN_LIMIT]
    assert len(fake.requests) == 4  # no call after the second one
    seen = _seen(r3)
    assert seen.finish_reason == "length" and seen.content == "Checking. Again. "


def test_the_length_follow_up_does_not_reset_the_turn_budget(tmp_path):
    messages = _base()
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, _):
        fake.respond_turn(calls=_greps(0, 8))
        fake.respond_turn("Partial. ")
        r1 = _post(url, messages)
        assert _seen(r1).content == "Partial. "
        assert all(_answered(r) for r in _results(fake.requests[1].body, _ids(0, 8)))
        messages = messages + [{"role": "assistant", "content": "Partial. "},
                               {"role": "user", "content": LENGTH_FOLLOW_UP}]
        fake.respond_turn(calls=_greps(8, 8))
        fake.respond_turn("More. ")
        _post(url, messages)
        assert all(_answered(r) for r in _results(fake.requests[3].body, _ids(8, 8)))
        messages = messages + [{"role": "assistant", "content": "More. "},
                               {"role": "user", "content": LENGTH_FOLLOW_UP}]
        fake.respond_turn(calls=_greps(16, 2))
        fake.respond_turn("Done.")
        r3 = _post(url, messages)

    assert len(fake.requests) == 6
    assert _results(fake.requests[5].body, _ids(16, 2)) == [TURN_LIMIT, TURN_LIMIT]
    assert _seen(r3).content == "Done."


def test_a_new_instruction_resets_the_turn_budget(tmp_path):
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, _):
        messages = _spend_16_with_tool_results(fake, url, _base())
        fake.respond_turn(calls=_greps(16, 1))
        fake.respond_turn("Spent.")
        _post(url, messages)
        _assert_second_eight_answered(fake)
        assert _results(fake.requests[3].body, _ids(16, 1)) == [TURN_LIMIT]
        messages = messages + [{"role": "assistant", "content": "Spent."},
                               {"role": "user", "content": "now check f20_1 and f21_1"}]
        fake.respond_turn(calls=_greps(20, 2))
        fake.respond_turn("Both found.")
        r4 = _post(url, messages)

    assert len(fake.requests) == 6
    assert all(_answered(r) for r in _results(fake.requests[5].body, _ids(20, 2)))
    assert _seen(r4).content == "Both found." and _seen(r4).finish_reason == "stop"


def test_a_call_refused_for_result_room_does_not_spend_the_turn_budget(tmp_path, monkeypatch):
    """Protocol review: only answered calls count (D67). With 15 answered and no result
    room left, the first call's room refusal must not turn the second into a turn-limit
    refusal that a later response would contradict."""
    messages = _base()
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, _):
        fake.respond_turn("Looking. ", calls=[*_greps(0, 8), _external(1)])
        _post(url, messages)
        messages = messages + _resent("Looking. ", 1)
        fake.respond_turn("More. ", calls=[*_greps(8, 7), _external(2)])
        _post(url, messages)
        messages = messages + _resent("More. ", 2)
        monkeypatch.setattr(archive, "RESULT_SHARE", 10**9)  # no result room at all
        fake.respond_turn(calls=_greps(15, 2))
        fake.respond_turn("Done.")
        _post(url, messages)

    assert _results(fake.requests[3].body, _ids(15, 2)) == [RESPONSE_LIMIT, RESPONSE_LIMIT]
