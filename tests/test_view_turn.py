"""The current turn's own work stays in view (R33-A, D70).

Pure tests of ``palimnesis.view.build`` with the real pinned counter. With
``ViewPolicy(protect_turn=True)``, a move first masks and collapses what lies before the
current turn (from the latest genuine instruction, ``turns.is_instruction``). Inside the
turn it then stubs the largest tool results and reasoning in place, never the newest
group's, and it collapses the turn's own groups only when the view still exceeds the high
watermark ``H``, down to the target ``T`` as before. ``ViewPolicy(protect_turn=...)`` is
built inside each test so each fails on its own while the knob is missing."""

from __future__ import annotations

import json
import random

import pytest

from palimnesis.budget import BudgetPolicy, plan_budget
from palimnesis.upstreams.strata import tokens
from palimnesis.view import ViewPolicy, ViewState, build

from .test_view import TOOLS, Session, _code

SPAN = "[palimnesis s1 span"
LENGTH_FOLLOW_UP = ("Your last response hit the output token limit (stop reason: length). Do not "
                    "apologize, recap, or repeat yourself. Break the remaining work into smaller "
                    "pieces.")
INSTRUCTION = "Implement the roster checker and run the tests."


@pytest.fixture(scope="module")
def counter():
    return tokens.default()


def _budget():
    return plan_budget(32768, client_limit=8192, policy=BudgetPolicy())


def _view(counter, session, policy, state=ViewState()):
    return build(session.items, tools=TOOLS, render_kwargs={}, budget=_budget(), state=state,
                 policy=policy, counter=counter)


def _is_span(message):
    return message["role"] == "user" and str(message.get("content")).startswith(SPAN)


def _forms(view):
    return dict(view.manifest)


def _seq(session, text):
    return next(i.seq for i in session.items if i.message.get("content") == text)


def _occ(session, call_id):
    """The occurrence of the tool result answering ``call_id``."""
    return next(i.occ_id for i in session.items if i.message.get("tool_call_id") == call_id)


def _turn(s, *, follow_up=False):
    """ho2-t3's turn 1 in miniature: six small steps, a large read, two small steps, and
    a newest read too large to share the view with the large one (R33-A)."""
    s.user(INSTRUCTION)
    for i in range(6):
        s.tool_turn(i, f"ok step {i}")
    if follow_up:
        s.user(LENGTH_FOLLOW_UP)
    s.tool_turn(10, _code(10, lines=420))
    for i in range(2):
        s.tool_turn(20 + i, f"ok step {20 + i}")
    return s.tool_turn(30, _code(30, lines=600))


def _limits(view):
    return view.fixed_tokens + 0.9 * view.capacity, view.fixed_tokens + 0.5 * view.capacity


def test_turn_protection_is_off_by_default_and_the_turn_is_then_collapsed(counter):
    assert getattr(ViewPolicy(), "protect_turn", None) is False
    s = _turn(Session().system())

    view = _view(counter, s, ViewPolicy())

    assert any(_is_span(m) for m in view.messages)  # the behaviour R33-A measured


def test_the_turns_own_steps_stay_while_stubbing_its_largest_result_suffices(counter):
    s = _turn(Session().system())

    view = _view(counter, s, ViewPolicy(protect_turn=True))

    forms = _forms(view)
    assert not any(_is_span(m) for m in view.messages)
    assert all(forms[_occ(s, f"call_{i}")] == "verbatim" for i in (0, 1, 2, 3, 4, 5, 20, 21))
    assert forms[_occ(s, "call_10")] == "stub"
    assert forms[_occ(s, "call_30")] == "verbatim"  # the newest result is never stubbed
    assert view.moved and view.tokens <= _budget().input_budget


def test_older_turns_are_collapsed_before_the_current_turn_is_touched(counter):
    s = Session().system().user("Read the whole package first.")
    for i in range(10):
        s.tool_turn(100 + i, _code(100 + i, lines=80))
    s.answer("Read it all.")
    s = _turn(s)

    view = _view(counter, s, ViewPolicy(protect_turn=True))

    start = _seq(s, INSTRUCTION)
    collapsed = [i.seq for i in s.items if _forms(view)[i.occ_id] == "collapsed"]
    assert collapsed and max(collapsed) < start
    assert all(_forms(view)[_occ(s, f"call_{i}")] == "verbatim" for i in range(6))
    assert view.tokens <= _budget().input_budget


def test_a_synthetic_follow_up_does_not_start_a_new_protected_turn(counter):
    s = _turn(Session().system(), follow_up=True)

    view = _view(counter, s, ViewPolicy(protect_turn=True))

    assert not any(_is_span(m) for m in view.messages)
    assert all(_forms(view)[_occ(s, f"call_{i}")] == "verbatim" for i in range(6))


def _write_turn(s, n, lines=40):
    """``n`` groups whose tool calls carry large arguments (whole-file writes): stubs
    cannot shrink them, so only a collapse can."""
    for i in range(n):
        call = {"id": f"call_w{i}", "type": "function", "function": {
            "name": "read", "arguments": json.dumps({"path": f"w{i}.py",
                                                     "content": _code(200 + i, lines=lines)})}}
        s.add({"role": "assistant", "content": None, "reasoning_content": "", "tool_calls": [call]})
        s.add({"role": "tool", "tool_call_id": f"call_w{i}", "content": "Wrote the file."})
    return s


def test_a_turn_too_large_for_stubs_is_collapsed_oldest_first_down_to_the_target(counter):
    s = _write_turn(Session().system().user(INSTRUCTION), 30)

    view = _view(counter, s, ViewPolicy(protect_turn=True))

    high, target = _limits(view)
    spans = [k for k, m in enumerate(view.messages) if _is_span(m)]
    assert spans  # inside the turn: nothing older exists
    assert view.tokens - view.excerpt_charge <= target
    assert _forms(view)[_occ(s, "call_w29")] == "verbatim"
    assert view.tokens <= _budget().input_budget


def test_a_view_between_target_and_high_after_stubbing_is_accepted_without_collapse(counter):
    s = _turn(Session().system())

    view = _view(counter, s, ViewPolicy(protect_turn=True))

    high, target = _limits(view)
    assert target < view.tokens - view.excerpt_charge <= high


def test_rebuilding_from_the_persisted_state_is_identical_and_does_not_move(counter):
    policy = ViewPolicy(protect_turn=True)
    s = _turn(Session().system())
    first = _view(counter, s, policy)

    again = _view(counter, s, policy, state=first.state)

    assert again.messages == first.messages and again.moved is False


def test_appending_inside_the_turn_keeps_earlier_stubs_and_only_adds(counter):
    policy = ViewPolicy(protect_turn=True)
    s = _turn(Session().system())
    first = _view(counter, s, policy)
    s.tool_turn(40, "ok step 40")

    after = _view(counter, s, policy, state=first.state)

    assert first.state.oversized <= after.state.oversized
    assert after.tokens <= _budget().input_budget


@pytest.mark.parametrize("seed", range(12))
def test_random_sessions_with_turn_protection_never_exceed_the_budget(counter, seed):
    rnd = random.Random(seed)
    policy = ViewPolicy(protect_turn=True)
    s = Session().system()
    state = ViewState()
    for turn in range(rnd.randint(2, 4)):
        s.user(f"Instruction {turn}: keep going.")
        for i in range(rnd.randint(3, 14)):
            k = turn * 100 + i
            if rnd.random() < 0.2:
                s.user(LENGTH_FOLLOW_UP)
            if rnd.random() < 0.3:
                _write_turn(s, 1, lines=rnd.choice([5, 30]))
            else:
                s.tool_turn(k, _code(k, lines=rnd.choice([1, 20, 120, 380])),
                            reasoning="x " * rnd.choice([0, 50, 400]))
            view = _view(counter, s, policy, state=state)
            assert view.tokens <= _budget().input_budget
            assert view.state.oversized >= state.oversized
            state = view.state


@pytest.mark.parametrize("seed", range(6))
def test_turn_stubbing_never_records_an_item_its_stub_leaves_unchanged(counter, seed):
    rnd = random.Random(100 + seed)
    policy = ViewPolicy(protect_turn=True)
    s = Session().system().user(INSTRUCTION)
    state = ViewState()
    for i in range(30):
        s.tool_turn(i, rnd.choice(["ok", "ok step", _code(i, lines=rnd.choice([30, 200]))]))
        view = _view(counter, s, policy, state=state)
        forms = _forms(view)
        assert all(forms[occ] != "verbatim" for occ in view.state.oversized)
        state = view.state


def test_tiny_results_a_stub_cannot_shrink_are_never_recorded_as_stubbed(counter):
    s = _write_turn(Session().system().user(INSTRUCTION), 30)

    view = _view(counter, s, ViewPolicy(protect_turn=True))

    forms = _forms(view)
    assert all(forms[occ] != "verbatim" for occ in view.state.oversized)
