"""Working notes in the view (D72, R33-D).

Pure tests of ``palimnesis.view.builder.build``. With ``ViewPolicy(notes_tokens=S)``, S tokens are
reserved out of the maskable capacity, as excerpts' Q is. A view whose state names a
notes version (``ViewState.notes``, its number and text in ``notes``) renders that text as one user-role block right after
the last collapsed run, and lists it in the manifest as ``(notes:<id>, "notes")``. A
build that moves the collapse boundary also returns ``refresh``: the request rendered
under the state it started from, plus the refresh prompt, within the input budget. That
is what the proxy's refresh call sends."""

from __future__ import annotations

import pytest

from palimnesis.view.budget import BudgetPolicy, plan_budget
from palimnesis.upstreams.strata import tokens
from palimnesis.view.builder import NOTES_PROMPT, ViewPolicy, ViewState, build, notes_block

from .test_view import TOOLS, Session, _code

SPAN = "[palimnesis s1 span"


@pytest.fixture(scope="module")
def counter():
    return tokens.default()


def _budget():
    return plan_budget(32768, client_limit=8192, policy=BudgetPolicy())


def _view(counter, session, policy, state=ViewState(), notes=None):
    return build(session.items, tools=TOOLS, render_kwargs={}, budget=_budget(), state=state,
                 policy=policy, counter=counter, notes=notes)


def _long(turns=3, groups=6, words=150):
    """About 21K tokens of assistant text and short results: over H, under B_in, and
    stubs cannot shrink it, so a move collapses."""
    s = Session().system()
    for t in range(turns):
        s.user(f"Instruction {t}: implement part {t}.")
        for i in range(groups):
            s.tool_turn(t * 100 + i, "ok")
            s.answer(" ".join(f"w{t}_{i}_{k}" for k in range(words)))
    return s.user("Now finish the last part.")


def _is_span(m):
    return m["role"] == "user" and str(m.get("content")).startswith(SPAN)


def test_notes_are_off_by_default():
    assert ViewPolicy().notes_tokens == 0
    assert ViewState().notes is None


def test_the_notes_slot_comes_out_of_the_maskable_capacity(counter):
    s = _long()
    plain = _view(counter, s, ViewPolicy())
    slotted = _view(counter, s, ViewPolicy(notes_tokens=2048))

    assert slotted.capacity == plain.capacity - 2048


def test_a_collapse_move_returns_the_refresh_request(counter):
    s = _long()
    view = _view(counter, s, ViewPolicy(notes_tokens=2048))

    assert view.state.collapse_seq > 0 and view.refresh is not None
    unmoved = _view(counter, s, ViewPolicy(notes_tokens=2048, high=float("inf")))
    assert view.refresh.messages[:-1] == unmoved.messages  # the request as it was before
    assert view.refresh.messages[-1] == {"role": "user", "content": NOTES_PROMPT}
    assert view.refresh.tokens <= _budget().input_budget
    assert view.refresh.manifest[-1] == ("notes-request", "notes_request")


def test_no_refresh_without_the_slot_or_without_a_collapse(counter):
    assert _view(counter, _long(), ViewPolicy()).refresh is None
    small = Session().system().user("hi").tool_turn(1, "ok").user("next")
    assert _view(counter, small, ViewPolicy(notes_tokens=2048)).refresh is None


def test_the_notes_block_sits_right_after_the_system_message(counter):
    s = _long()
    policy = ViewPolicy(notes_tokens=2048)
    moved = _view(counter, s, policy)
    state = moved.state.__class__(**{**moved.state.__dict__, "notes": "notes_1"})

    view = _view(counter, s, policy, state=state, notes={"notes_1": (1, "Objective: finish.")})

    assert view.messages[0]["role"] == "system"
    assert view.messages[1] == {"role": "user", "content": notes_block(1, "Objective: finish.")}
    assert _is_span(view.messages[2])
    assert view.manifest[1] == ("notes:notes_1", "notes")
    assert view.moved is False and view.tokens <= _budget().input_budget


def test_the_block_names_its_version_and_says_the_user_wins():
    text = notes_block(3, "Objective: finish.")
    assert text.startswith("[palimnesis notes · v3 ·")
    assert "the user's messages win" in text and text.endswith("Objective: finish.")


def test_notes_without_a_collapse_are_not_rendered(counter):
    s = Session().system().user("hi").tool_turn(1, "ok").user("next")
    view = _view(counter, s, ViewPolicy(notes_tokens=2048), state=ViewState(notes="notes_1"),
                 notes={"notes_1": (1, "Objective: x.")})

    assert not any("palimnesis notes" in str(m.get("content")) for m in view.messages)


def test_a_refresh_that_would_overflow_stubs_the_newest_large_results_first(counter):
    s = _long()
    s.tool_turn(999, _code(999, lines=150))  # a large newest result pushes it over B_in

    view = _view(counter, s, ViewPolicy(notes_tokens=2048))

    assert view.refresh is not None and view.refresh.tokens <= _budget().input_budget


def _notes_of(counter, tokens_wanted):
    words, text = 0, ""
    while counter.count_cached(notes_block(99, text)) < tokens_wanted - 20:
        words += 50
        text = " ".join(f"n{k}" for k in range(words))
    return text


@pytest.mark.parametrize("lines", [850, 880, 910, 940, 970])
def test_a_committed_block_of_the_slot_never_forces_another_move(counter, lines):
    policy = ViewPolicy(notes_tokens=2048)
    s = _long()
    s.tool_turn(999, _code(999, lines=lines))  # newest result near B_in by itself
    first = _view(counter, s, policy)
    state = first.state.__class__(**{**first.state.__dict__, "notes": "n1"})

    again = _view(counter, s, policy, state=state, notes={"n1": (99, _notes_of(counter, 2048))})

    assert again.moved is False and again.tokens <= _budget().input_budget



def _pinned_session():
    s = Session().system()
    for t in range(4):
        s.user(f"Rule {t}: keep it short.")
        for i in range(6):
            s.tool_turn(t * 100 + i, "ok")
            s.answer(" ".join(f"w{t}_{i}_{k}" for k in range(150)))
    return s


def test_the_block_never_moves_past_a_kept_message_between_moves(counter):
    """Cache audit 1: a later collapse past a pinned instruction must not move the block."""
    from palimnesis.view.cacheacct import describe

    policy = ViewPolicy(notes_tokens=2048, pin_tokens=4096)
    s = _pinned_session().user("Go on.")
    first = _view(counter, s, policy)
    state = first.state.__class__(**{**first.state.__dict__, "notes": "n1"})
    v1 = _view(counter, s, policy, state=state, notes={"n1": (1, "Objective: a.")})
    for i in range(12):
        s.tool_turn(900 + i, "ok")
        s.answer(" ".join(f"x{i}_{k}" for k in range(150)))
    v2 = _view(counter, s, policy, state=v1.state, notes={"n1": (1, "Objective: a.")})

    assert v2.state.collapse_seq > v1.state.collapse_seq
    for v in (v1, v2):
        assert v.messages[1]["content"].startswith("[palimnesis notes")
        assert describe(s.items, v) is not None
