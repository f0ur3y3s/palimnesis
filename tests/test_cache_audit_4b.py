"""Fixes from the Phase 4B cache audit (D95)."""

from __future__ import annotations

from palimnesis.archive.ledger import _fold
from palimnesis.archive.transcript import Archived, Extend, reconcile
from palimnesis.protocols.chat import parse
from palimnesis.view.builder import ViewItem
from palimnesis.view.engine import with_addendum


def _item(role, content):
    return ViewItem({"role": role, "content": content}, None, None, None)


def test_the_addendum_never_joins_a_late_system_message():
    """A system message after the first position renders as a user turn (D86); the addendum
    joins only a leading system message, else gets its own at the start."""
    items = [_item("user", "Q1"), _item("assistant", "A1"), _item("system", "hook context"),
             _item("user", "Q2")]

    out = with_addendum(items, "ADDENDUM")

    assert [i.message for i in out] == [{"role": "system", "content": "ADDENDUM"},
                                        *[i.message for i in items]]
    leading = with_addendum([_item("system", "S"), *items], "ADDENDUM")
    assert leading[0].message == {"role": "system", "content": "S\n\nADDENDUM"}
    assert leading[3].message == {"role": "system", "content": "hook context"}


def test_a_composite_turn_keeps_the_length_stop_of_its_last_part():
    """D94 for a hidden-loop response that ends on the length stop: the folded turn is
    truncated, so Pi's resend without it supersedes it."""
    first = Archived.generated("p1", text="Looking. ", reasoning="", tool_calls=(), complete=True,
                               attempt_id="att-1", truncated=True)
    result = Archived("r1", "tool", "internal_tool", view="internal", attempt_id="att-1")
    last = Archived.generated("p2", text="cut", reasoning="", tool_calls=(), complete=True,
                              attempt_id="att-1", truncated=True)
    system = Archived.from_client("s", parse(b'{"messages":[{"role":"system","content":"S"}]}').messages[0])
    user = Archived.from_client("u", parse(b'{"messages":[{"role":"user","content":"Q"}]}').messages[0])

    folded = _fold([system, user, first, result, last])

    assert folded[2].truncated and folded[2].parts == ("p1", "r1", "p2")
    resend = parse(b'{"messages":[{"role":"system","content":"S"},{"role":"user","content":"Q"},'
                   b'{"role":"user","content":"next"}]}').messages
    outcome = reconcile(resend, folded)
    assert isinstance(outcome, Extend) and outcome.superseded == ("p1",)


def test_a_refresh_that_stubs_an_earlier_result_to_fit_is_state_refresh():
    """Found by the Pi needle driver's fake run (S14): a notes refresh stubbed a result the
    previous call showed in full, to fit B_in. The refresh carries no new view number, so
    the stub was unexplained; a refresh's own fit stubbing is the refresh (D95)."""
    from palimnesis.view.cacheacct import Call, Turn, _view_cause

    prev = Call(call_id="att_1", request_id="r1", branch_id="b", view_mode="on", view_n=3)
    refresh = Call(call_id="att_2#notes", request_id="r2", branch_id="b", view_mode="on", view_n=3)
    main = Call(call_id="att_2", request_id="r2", branch_id="b", view_mode="on", view_n=3)
    full, stub = Turn(("occ7",), "verbatim"), Turn(("occ7",), "stub")

    assert _view_cause(full, stub, prev, refresh) == "state_refresh"
    assert _view_cause(full, stub, prev, main) is None  # no move, not a refresh: unexplained
