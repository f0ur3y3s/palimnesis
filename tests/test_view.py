"""Bounded view builder (pure seam; plan slices 5 and 7, D14).

Counts use the real pinned counter, so token bounds are exact.
"""

from __future__ import annotations

import json
import random

import pytest

from palimnesis import tokens
from palimnesis.budget import BudgetError, BudgetPolicy, plan_budget
from palimnesis.view import ViewItem, ViewPolicy, ViewState, build

TOOLS = [{"type": "function", "function": {"name": "read", "description": "read a file",
                                           "parameters": {"type": "object", "properties": {
                                               "path": {"type": "string"}}}}}]


@pytest.fixture(scope="module")
def counter():
    return tokens.default()


class Session:
    """Builds ViewItems with seqs, aliases and groups like the archive would."""

    def __init__(self):
        self.items: list[ViewItem] = []

    def add(self, message: dict) -> "Session":
        seq = len(self.items) + 1
        self.items.append(ViewItem(message=message, occ_id=f"occ{seq}", seq=seq,
                                   alias=f"{seq:06d}"))
        return self

    def system(self, text="You are a coding agent."):
        return self.add({"role": "system", "content": text})

    def user(self, text):
        return self.add({"role": "user", "content": text})

    def tool_turn(self, i, output, reasoning=""):
        call = {"id": f"call_{i}", "type": "function",
                "function": {"name": "read", "arguments": json.dumps({"path": f"f{i}.py"})}}
        self.add({"role": "assistant", "content": None, "reasoning_content": reasoning,
                  "tool_calls": [call]})
        return self.add({"role": "tool", "tool_call_id": f"call_{i}", "content": output})

    def answer(self, text):
        return self.add({"role": "assistant", "content": text})


def _budget(n_ctx=32768, cap=None):
    policy = BudgetPolicy() if cap is None else BudgetPolicy(input_cap=cap)
    return plan_budget(n_ctx, client_limit=8192, policy=policy)


def _view(counter, session, state=ViewState(), budget=None, policy=ViewPolicy()):
    return build(session.items, tools=TOOLS, render_kwargs={}, budget=budget or _budget(),
                 state=state, policy=policy, counter=counter)


def _code(i, lines=60):
    return "\n".join(f"def f{i}_{n}(x):\n    return x * {n}  # line {n}" for n in range(lines))


def test_small_session_is_the_full_history_unchanged(counter):
    s = Session().system().user("hi").tool_turn(1, "short output").answer("done").user("next")

    view = _view(counter, s)

    assert view.messages == [i.message for i in s.items]
    assert view.moved is False and view.state == ViewState()
    assert view.tokens == counter.count_messages(view.messages, TOOLS)


def test_crossing_the_high_watermark_masks_oldest_tool_outputs_down_to_the_target(counter):
    # Few large outputs: stubbing alone reaches the target, so nothing collapses.
    s = Session().system().user("refactor everything")
    for i in range(12):
        s.tool_turn(i, _code(i, lines=200))
    s.user("now summarize")
    budget = _budget()

    view = _view(counter, s, budget=budget)

    assert view.moved and view.state.watermark_seq > 0
    assert view.tokens <= budget.input_budget
    fixed, capacity = view.fixed_tokens, view.capacity
    assert view.tokens <= fixed + 0.50 * capacity + 1
    masked = [m for m in view.messages if m["role"] == "tool" and m["content"].startswith("[palimnesis s1")]
    assert masked and all("tool_result" in m["content"] for m in masked)
    # oldest first: masked tool messages precede every verbatim one
    flags = [m["content"].startswith("[palimnesis") for m in view.messages if m["role"] == "tool"]
    assert flags == sorted(flags, reverse=True)
    # the current user message and the newest group stay verbatim
    assert view.messages[-1] == {"role": "user", "content": "now summarize"}
    assert view.messages[-2] == s.items[-2].message
    # tool-call ids and pairing are preserved
    assert view.state.collapse_seq == 0
    assert [m.get("tool_call_id") for m in view.messages if m["role"] == "tool"] == [
        i.message.get("tool_call_id") for i in s.items if i.message["role"] == "tool"]


def test_watermark_lands_on_a_group_boundary(counter):
    s = Session().system().user("go")
    for i in range(40):
        s.tool_turn(i, _code(i))
    s.user("next")

    view = _view(counter, s)

    boundary = next(i for i in s.items if i.seq == view.state.watermark_seq)
    assert boundary.message["role"] in ("user", "assistant")


def test_rebuilding_from_the_persisted_state_is_identical_and_does_not_move(counter):
    s = Session().system().user("go")
    for i in range(40):
        s.tool_turn(i, _code(i))
    s.user("next")
    first = _view(counter, s)

    again = _view(counter, s, state=first.state)

    assert again.messages == first.messages and again.moved is False


def test_watermark_is_monotone_and_hysteresis_avoids_moving_every_turn(counter):
    s = Session().system().user("go")
    for i in range(40):
        s.tool_turn(i, _code(i))
    s.user("next")
    state = _view(counter, s).state
    moves = 0
    for i in range(40, 46):
        s.tool_turn(i, _code(i, lines=20))
        view = _view(counter, s, state=state)
        assert view.state.watermark_seq >= state.watermark_seq
        moves += view.moved
        state = view.state

    assert moves <= 2


def test_short_tool_results_stay_inline_and_stubs_are_used_only_when_smaller(counter):
    s = Session().system().user("go")
    for i in range(40):
        s.tool_turn(i, "ok" if i % 2 else _code(i))
    s.user("next")

    view = _view(counter, s)

    forms = dict(view.manifest)
    short = [i.occ_id for i in s.items if i.message.get("content") == "ok"]
    assert view.moved and len(short) == 20
    assert all(forms[o] in ("verbatim", "collapsed") for o in short)  # never stubbed
    assert any(forms[i.occ_id] == "stub" for i in s.items if i.message["role"] == "tool")


def test_reasoning_in_the_masked_region_becomes_a_reasoning_stub(counter):
    s = Session().system().user("go")
    for i in range(40):
        s.tool_turn(i, _code(i), reasoning="I should read the next file carefully. " * 30)
    s.user("next")

    view = _view(counter, s)

    stubbed = [m for m in view.messages if m["role"] == "assistant"
               and str(m.get("reasoning_content", "")).startswith("[palimnesis s1")]
    assert stubbed and all("reasoning" in m["reasoning_content"] for m in stubbed)


def test_many_small_turns_collapse_into_a_span_note_within_budget(counter):
    s = Session().system()
    for i in range(2500):
        s.user(f"note {i}").answer(f"ack {i}")
    s.user("final question")
    budget = _budget()

    view = _view(counter, s, budget=budget)

    assert view.tokens <= budget.input_budget
    assert view.messages[0]["role"] == "system"
    assert view.messages[1]["role"] == "user" and view.messages[1]["content"].startswith("[palimnesis s1 span")
    assert view.messages[-1]["content"] == "final question"
    assert view.state.collapse_seq > 0


def test_oversized_newest_tool_output_is_stubbed_in_place(counter):
    s = Session().system().user("read the log").tool_turn(1, _code(1, lines=6000))
    budget = _budget()

    view = _view(counter, s, budget=budget)

    assert view.tokens <= budget.input_budget
    assert view.messages[-1]["role"] == "tool" and view.messages[-1]["content"].startswith("[palimnesis s1")
    assert view.state.oversized == frozenset({"occ4"})


def test_fixed_input_that_cannot_fit_is_a_budget_error(counter):
    s = Session().system().user("x " * 30000)

    with pytest.raises(BudgetError):
        _view(counter, s)


def test_every_masked_item_is_listed_with_its_alias(counter):
    s = Session().system().user("go")
    for i in range(40):
        s.tool_turn(i, _code(i))
    s.user("next")

    view = _view(counter, s)

    for occ_id, form in view.manifest:
        item = next(i for i in s.items if i.occ_id == occ_id)
        if form != "verbatim":
            text = json.dumps(view.messages, ensure_ascii=False)
            assert f"§{item.alias}" in text or form == "collapsed"


@pytest.mark.parametrize("seed", range(6))
def test_random_sessions_never_exceed_the_budget(counter, seed):
    rng = random.Random(seed)
    s = Session().system()
    state = ViewState()
    budget = _budget(n_ctx=rng.choice([32768, 65536]))
    for turn in range(30):
        s.user(f"task {turn}")
        for k in range(rng.randint(0, 4)):
            s.tool_turn(turn * 10 + k, _code(k, lines=rng.randint(1, 120)),
                        reasoning="think " * rng.randint(0, 80))
        s.answer("done " * rng.randint(1, 30))
        view = _view(counter, s, state=state, budget=budget)
        assert view.tokens <= budget.input_budget
        assert view.tokens == counter.count_messages(view.messages, TOOLS)
        assert view.state.watermark_seq >= state.watermark_seq
        state = view.state


def test_a_long_agentic_turn_after_one_user_message_collapses_within_budget(counter):
    # OpenCode: one instruction followed by dozens of tool groups in the same turn.
    s = Session().system().user("refactor the project")
    for i in range(30):
        s.tool_turn(i, _code(i, lines=80))
    budget = _budget(cap=8000)

    view = _view(counter, s, budget=budget)

    assert view.tokens <= 8000
    assert view.messages[1] == {"role": "user", "content": "refactor the project"}
    assert view.messages[2]["content"].startswith("[palimnesis s1 span")
    assert view.messages[-1] == s.items[-1].message or view.messages[-1]["content"].startswith("[palimnesis")


def test_a_message_kept_verbatim_inside_the_masked_region_stays_kept_on_later_turns(counter):
    s = Session().system().user("refactor the project")
    for i in range(30):
        s.tool_turn(i, _code(i, lines=80))
    first = _view(counter, s, budget=_budget(cap=8000))
    s.answer("ok").user("next")

    second = _view(counter, s, state=first.state, budget=_budget(cap=8000))

    assert second.messages[:len(first.messages)] == first.messages or second.moved
    assert {"role": "user", "content": "refactor the project"} in second.messages
