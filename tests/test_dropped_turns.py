"""Turns the upstream renders as nothing (D42): completed assistant turns with no text,
image or tool calls, which Strata drops (#843, D41). The view, the cache estimate and
``--explain`` treat them as the zero tokens they render."""

from __future__ import annotations

from palimnesis import profile
from palimnesis.budget import BudgetPolicy, plan_budget
from palimnesis.cacheacct import Call, describe, explain
from palimnesis.view import ViewItem, ViewPolicy, ViewState, build

STRATA = profile.load(profile.DEFAULT_PROFILE, "http://127.0.0.1:1")
COUNTER = STRATA.counter


def _code(i: int, n: int) -> str:
    return "\n".join(f"def h{i}_{k}(x): return x * {k}  # {k}" for k in range(n))


def _items(messages):
    return [ViewItem(m, f"occ{i + 1}", i + 1, f"A{i + 1:05d}", {"tool_result": 0, "reasoning": 0})
            for i, m in enumerate(messages)]


def _session(answer: str):
    """Six tool turns, then an answer with long reasoning: reasoning-only when ``answer``
    is "" (Strata renders none of it) or the same with visible text."""
    messages = [{"role": "system", "content": "You are a coding agent."}]
    for i in range(6):
        messages += [{"role": "user", "content": f"task {i}"},
                     {"role": "assistant", "content": None, "reasoning_content": "r",
                      "tool_calls": [{"id": f"c{i}", "type": "function",
                                      "function": {"name": "read", "arguments": "{}"}}]},
                     {"role": "tool", "tool_call_id": f"c{i}", "content": _code(i, 260)}]
    messages += [{"role": "assistant", "content": answer,
                  "reasoning_content": "long hidden deliberation " * 1200},
                 {"role": "user", "content": "next"}]
    return _items(messages)


def _build(items, **kw):
    budget = plan_budget(32768, client_limit=None, policy=BudgetPolicy(input_cap=14000))
    return build(items, tools=None, render_kwargs={}, budget=budget, state=kw.pop("state", ViewState()),
                 policy=ViewPolicy(), counter=COUNTER,
                 drops_empty_assistant=STRATA.rules.drops_empty_assistant, **kw)


def test_strata_declares_that_empty_assistant_turns_render_nothing():
    assert STRATA.rules.drops_empty_assistant is True
    assert profile.unsupported_rules(STRATA.rules) == ()


def test_unrendered_reasoning_does_not_count_toward_the_recent_window():
    # The recent window keeps min_recent tokens that render. A dropped turn renders
    # nothing, so the view is the one built as if the turn were not there at all.
    items = _session("")
    dropped = items[-2].occ_id
    hidden, absent = _build(items), _build(items[:-2] + items[-1:])

    assert [x for x in hidden.manifest if x[0] != dropped] == list(absent.manifest)
    assert (hidden.state.watermark_seq, hidden.state.collapse_seq) == \
        (absent.state.watermark_seq, absent.state.collapse_seq)
    assert hidden.tokens == absent.tokens


def test_a_dropped_turn_is_never_masked_or_reported_evicted():
    items = _session("")
    dropped = items[-2].occ_id
    view = _build(items)

    assert dict(view.manifest)[dropped] == "verbatim"
    assert dropped not in view.state.oversized
    assert dropped not in view.evicted_now


def test_checkpoints_follow_rendered_tokens_not_dropped_turns():
    reasoning = "Thinking about the answer at some length. " * 5
    system = {"role": "system", "content": "You are terse."}
    with_dropped, without = [system], [system]
    for i in range(8):
        user = {"role": "user", "content": f"Question {i}: say a number."}
        answer = {"role": "assistant", "content": "7" if i < 2 else "", "reasoning_content": reasoning}
        with_dropped += [user, answer]
        without += [user] + ([answer] if i < 2 else [])
    with_dropped.append({"role": "user", "content": "Final."})
    without.append({"role": "user", "content": "Final."})
    a, b = COUNTER.layout(with_dropped), COUNTER.layout(without)
    assert a.ids == b.ids

    assert STRATA.cache_model.checkpoints(a) == STRATA.cache_model.checkpoints(b)


def test_a_collapse_starting_at_a_dropped_turn_is_explained():
    messages = [{"role": "system", "content": "You are a coding agent."},
                {"role": "assistant", "content": "", "reasoning_content": "thinking " * 50},
                {"role": "user", "content": "task 1"},
                {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "c1", "content": _code(1, 40)},
                {"role": "user", "content": "task 2"},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": "task 3"}]
    items = _items(messages)
    budget = plan_budget(65536, client_limit=None, policy=BudgetPolicy())

    def call(seq, n):
        view = build(items, tools=None, render_kwargs={}, budget=budget,
                     state=ViewState(watermark_seq=seq, collapse_seq=seq), policy=ViewPolicy(),
                     counter=COUNTER, drops_empty_assistant=True)
        c = Call(call_id=f"c{n}", request_id=f"r{n}", branch_id="b", view_mode="on", view_n=n,
                 input_tokens=view.tokens, budget={"x": 1}, formats={"f": 1})
        c.turns = describe(items, view)
        c.layout = COUNTER.layout(view.messages, None)
        return c

    assert explain(call(0, 1), call(6, 2), STRATA.cache_model)["cause"] == "collapse"


def test_a_counter_revision_explains_a_call_that_no_longer_re_renders():
    # A previous call recorded under another counter revision cannot be re-rendered to
    # its recorded count after a restart; the pair is a model/template change (D46).
    from palimnesis.cacheacct import Call

    def call(n, identity, layout):
        c = Call(call_id=f"c{n}", request_id=f"r{n}", branch_id="b", view_mode="on", view_n=n,
                 input_tokens=10, budget={"x": 1}, formats={"f": 1})
        c.identity, c.layout = identity, layout
        return c

    layout = COUNTER.layout([{"role": "user", "content": "hi"}])
    prev = call(1, ["strata-0.1.48", "b", "t"], None)
    cur = call(2, ["strata-0.1.48", "b", "t", COUNTER.revision], layout)

    assert explain(prev, cur, STRATA.cache_model)["cause"] == "model_template_change"
    assert explain(call(1, cur.identity, None), cur, STRATA.cache_model)["cause"] == "unexplained"
