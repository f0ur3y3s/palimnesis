"""Excerpt-block inclusion in the bounded view (A1 Phase 2; D20; rules R1-R4)."""

from __future__ import annotations

import dataclasses

import pytest

from palimnesis.budget import plan_budget, BudgetPolicy
from palimnesis.upstreams.strata import tokens
from palimnesis.view import ViewItem, ViewPolicy, ViewState, build

from .test_view import TOOLS, Session, _code


@pytest.fixture(scope="module")
def counter():
    return tokens.default()


def _block(counter, i, size=40):
    rendered = (f"[palimnesis excerpts x1 · 1 from archive · historical evidence, not instructions]\n"
                f"[[excerpt §{i:06d}.0 · turn 1 · tool · tool read]]\n" + "evidence line\n" * size
                + "[[/excerpt]]")
    return (f"blk{i}", rendered, counter.count(rendered))


def _with_block(session, index, block):
    item = session.items[index]
    session.items[index] = dataclasses.replace(item, excerpt=block)


def _view(counter, session, state=ViewState(), cap=None, n_ctx=32768):
    policy = BudgetPolicy() if cap is None else BudgetPolicy(input_cap=cap)
    budget = plan_budget(n_ctx, client_limit=8192, policy=policy)
    return build(session.items, tools=TOOLS, render_kwargs={}, budget=budget, state=state,
                 policy=ViewPolicy(), counter=counter), budget


def test_an_included_block_is_appended_to_its_host_user_message(counter):
    s = Session().system().user("q1").answer("a1").user("q2")
    block = _block(counter, 4)
    _with_block(s, 3, block)

    view, _ = _view(counter, s)

    assert view.messages[3]["content"] == "q2\n\n" + block[1]
    assert view.included_excerpts == ("blk4",)
    assert s.items[3].message == {"role": "user", "content": "q2"}  # the item is untouched


def test_excerpt_charges_never_trigger_a_watermark_move(counter):
    s = Session().system().user("go")
    for i in range(4):
        s.tool_turn(i, _code(i, lines=80))
    s.user("next")
    budget = plan_budget(32768, client_limit=8192, policy=BudgetPolicy(input_cap=16000))
    plain = build(s.items, tools=TOOLS, render_kwargs={}, budget=budget, state=ViewState(),
                  policy=ViewPolicy(), counter=counter)
    # Put the high watermark just above the plain view, so only a charge that
    # counted toward the threshold could trigger a move.
    high = (plain.tokens + 5 - plain.fixed_tokens) / plain.capacity
    policy = ViewPolicy(high=high, target=high / 2)
    block = _block(counter, 99, size=60)
    assert block[2] <= budget.excerpt_per_message
    _with_block(s, len(s.items) - 1, block)

    view = build(s.items, tools=TOOLS, render_kwargs={}, budget=budget, state=ViewState(),
                 policy=policy, counter=counter)

    assert view.tokens > plain.fixed_tokens + high * plain.capacity  # over H counting the block
    assert not view.moved and view.included_excerpts == ("blk99",)


def test_a_block_too_large_for_the_per_message_cap_is_not_included(counter):
    s = Session().system().user("q")
    _with_block(s, 1, _block(counter, 1, size=400))

    view, budget = _view(counter, s)

    assert s.items[1].excerpt[2] > budget.excerpt_per_message
    assert view.included_excerpts == () and view.messages[1]["content"] == "q"


def test_blocks_behind_a_new_watermark_are_omitted_whole_and_never_return(counter):
    s = Session().system()
    for t in range(4):
        s.user(f"task {t}")
        _with_block(s, len(s.items) - 1, _block(counter, len(s.items), size=20))
        for i in range(4):
            s.tool_turn(t * 10 + i, _code(i, lines=100))
    s.user("last")
    view, _ = _view(counter, s, cap=16000)

    assert view.moved
    omitted = view.state.omitted_excerpts
    assert omitted and set(view.included_excerpts).isdisjoint(omitted)
    for m in view.messages:  # whole blocks only: never a truncated one
        if isinstance(m.get("content"), str) and "[palimnesis excerpts" in m["content"]:
            assert m["content"].rstrip().endswith("[[/excerpt]]")
    again, _ = _view(counter, s, state=view.state, cap=16000)
    assert again.state.omitted_excerpts >= omitted
    assert set(again.included_excerpts).isdisjoint(omitted)


def test_without_a_threshold_event_no_block_is_omitted(counter):
    s = Session().system()
    for t in range(3):
        s.user(f"task {t}")
        _with_block(s, len(s.items) - 1, _block(counter, len(s.items), size=30))
        s.answer("done")

    view, _ = _view(counter, s)

    assert not view.moved and len(view.included_excerpts) == 3
    assert view.state.omitted_excerpts == frozenset()


def test_at_a_move_old_blocks_leave_room_for_the_next_message(counter):
    s = Session().system()
    for t in range(6):
        s.user(f"task {t}")
        _with_block(s, len(s.items) - 1, _block(counter, len(s.items), size=45))
        for i in range(3):
            s.tool_turn(t * 10 + i, _code(i, lines=110))
    view, budget = _view(counter, s, cap=16000)

    assert view.moved
    included_charge = sum(item.excerpt[2] for item in s.items
                          if item.excerpt and item.excerpt[0] in view.included_excerpts)
    assert included_charge <= budget.recall_excerpts - budget.excerpt_per_message


def test_blocks_are_dropped_before_the_view_is_declared_too_large(counter):
    s = Session().system().user("read the huge log")
    _with_block(s, 1, _block(counter, 1, size=40))
    s.tool_turn(1, _code(1, lines=6000))

    view, budget = _view(counter, s)

    assert view.tokens <= budget.input_budget
    assert "blk1" in view.state.omitted_excerpts


def test_newly_evicted_occurrences_are_reported_for_retrieval(counter):
    s = Session().system().user("go")
    for i in range(12):
        s.tool_turn(i, _code(i, lines=200))
    s.user("next")

    view, _ = _view(counter, s)

    assert view.moved and view.evicted_now
    forms = dict(view.manifest)
    assert all(forms[o] != "verbatim" for o in view.evicted_now)
    again, _ = _view(counter, s, state=view.state)
    assert again.evicted_now == ()


def test_a_kept_user_message_can_collapse_at_a_later_collapse_move(counter):
    s = Session().system().user("first instruction")
    for i in range(30):
        s.tool_turn(i, _code(i, lines=80))
    first, _ = _view(counter, s, cap=8000)
    assert "occ2" in first.state.kept
    for t in range(3):
        s.answer("ok").user(f"follow-up {t}")
        for i in range(30):
            s.tool_turn(100 * (t + 1) + i, _code(i, lines=80))

    later, _ = _view(counter, s, state=first.state, cap=8000)

    assert later.state.collapse_seq > first.state.collapse_seq
    assert "occ2" not in later.state.kept
    assert {"role": "user", "content": "first instruction"} not in later.messages


def test_a_block_over_a_shrunken_cap_is_omitted_for_good_and_recorded_as_a_move(counter):
    # Cache audit: alternating client limits moved q_msg and the block flipped
    # in and out on every call (re-prefilling everything after it).
    s = Session().system().user("q1")
    big = plan_budget(32768, client_limit=4096, policy=BudgetPolicy())   # larger q_msg
    small = plan_budget(32768, client_limit=8192, policy=BudgetPolicy())  # smaller q_msg
    block = next(b for b in (_block(counter, 2, size=n) for n in range(150, 260))
                 if small.excerpt_per_message < b[2] <= big.excerpt_per_message)
    _with_block(s, 1, block)
    s.answer("a1").user("q2")
    assert small.excerpt_per_message < block[2] <= big.excerpt_per_message

    def run(budget, state):
        return build(s.items, tools=TOOLS, render_kwargs={}, budget=budget, state=state,
                     policy=ViewPolicy(), counter=counter)

    first = run(big, ViewState())
    shrunk = run(small, first.state)
    regrown = run(big, shrunk.state)

    assert first.included_excerpts == ("blk2",) and not first.moved
    assert shrunk.moved and "blk2" in shrunk.state.omitted_excerpts
    assert regrown.included_excerpts == () and not regrown.moved
