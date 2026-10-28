"""Working notes in the view (D72, R33-D).

Pure tests of ``palimnesis.view.build``. With ``ViewPolicy(notes_tokens=S)``, S tokens are
reserved out of the maskable capacity, as excerpts' Q is. A view whose state names a
notes version (``ViewState.notes``, its number and text in ``notes``) renders that text as one user-role block right after
the last collapsed run, and lists it in the manifest as ``(notes:<id>, "notes")``. A
build that moves the collapse boundary also returns ``refresh``: the request rendered
under the state it started from, plus the refresh prompt, within the input budget. That
is what the proxy's refresh call sends."""

from __future__ import annotations

import pytest

from palimnesis.budget import BudgetPolicy, plan_budget
from palimnesis.upstreams.strata import tokens
from palimnesis.view import NOTES_PROMPT, ViewPolicy, ViewState, build, notes_block

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


def test_the_notes_block_follows_the_last_collapsed_run(counter):
    s = _long()
    policy = ViewPolicy(notes_tokens=2048)
    moved = _view(counter, s, policy)
    state = moved.state.__class__(**{**moved.state.__dict__, "notes": "notes_1"})

    view = _view(counter, s, policy, state=state, notes={"notes_1": (1, "Objective: finish.")})

    k = next(i for i, m in enumerate(view.messages) if m.get("content") == notes_block(1, "Objective: finish."))
    assert _is_span(view.messages[k - 1])
    assert not any(_is_span(m) for m in view.messages[k + 1:])
    assert ("notes:notes_1", "notes") in view.manifest
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
