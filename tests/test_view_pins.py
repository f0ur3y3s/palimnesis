"""Instructions stay in view (Phase 3B S10b, F1 / D65; plan phase3b "Delta: R29 fixes").

Pure tests of ``palimnesis.view.build`` with the real pinned counter. A pinnable
message is a user instruction (``turns.is_instruction``) whose own content is at most
1,024 tokens; at each collapse move, pinnable messages behind the new boundary stay
verbatim in place, newest first, while their total fits
``min(pin_tokens, input_budget // 6)``. The rest are absorbed, and an absorbed
message stays collapsed. ``ViewPolicy(pin_tokens=...)`` is built inside each test so
each fails on its own while the knob is missing."""

from __future__ import annotations

import dataclasses
import random

import pytest

from palimnesis import view as view_module
from palimnesis.budget import BudgetError, BudgetPolicy, plan_budget
from palimnesis.upstreams.strata import tokens
from palimnesis.view import ViewPolicy, ViewState, build

from .test_view import TOOLS, Session, _code

SPAN = "[palimnesis s1 span"
INTERRUPTED = ("The previous response was interrupted. Continue from where you left off "
               "without repeating completed content.")
# OpenCode 2.1.4's length follow-up, verbatim (docs/probes/opencode_hidden_stream.md, LEN).
LENGTH_FOLLOW_UP = ("Your last response hit the output token limit (stop reason: length). Do not "
                    "apologize, recap, or repeat yourself. Break the remaining work into smaller "
                    "pieces.")
SHORT_RULES = ["Always indent with tabs in this repository.",
               "Never edit files under vendor/; Acme owns them.",
               "Run uv run pytest -q before every answer."]
CURRENT = "Name new helpers in snake_case with a verb first."


@pytest.fixture(scope="module")
def counter():
    return tokens.default()


def _budget(cap):
    return plan_budget(32768, client_limit=8192, policy=BudgetPolicy(input_cap=cap))


def _pins(pin_tokens, **kw):
    return ViewPolicy(pin_tokens=pin_tokens, **kw)


def _view(counter, session, budget, policy, state=ViewState()):
    return build(session.items, tools=TOOLS, render_kwargs={}, budget=budget, state=state,
                 policy=policy, counter=counter)


def _user(text):
    return {"role": "user", "content": text}


def _is_span(message):
    return message["role"] == "user" and str(message.get("content")).startswith(SPAN)


def _seq_of(session, text):
    return next(i.seq for i in session.items if i.message == _user(text))


def _history(texts, turns, current=CURRENT, tail=2):
    """Each text as a user message followed by ``turns`` tool groups, then the current
    instruction followed by ``tail`` tool groups (OpenCode's agentic turn)."""
    s = Session().system()
    for k, text in enumerate(texts):
        s.user(text)
        for i in range(turns):
            s.tool_turn(k * 100 + i, _code(i, lines=80))
    s.user(current)
    for i in range(tail):
        s.tool_turn(900 + i, _code(i, lines=80))
    return s


# --- constants and the knob -------------------------------------------------------


def test_pinning_is_off_by_default_and_the_per_message_cap_is_1024_tokens():
    assert getattr(view_module, "PIN_MESSAGE_TOKENS", None) == 1024
    assert getattr(ViewPolicy(), "pin_tokens", None) == 0


# --- (a) short instructions stay in place --------------------------------------------


def test_short_instructions_behind_a_collapse_stay_verbatim_in_place(counter):
    s = _history(SHORT_RULES, turns=8)
    budget = _budget(8000)

    plain = _view(counter, s, budget, _pins(0))
    pinned = _view(counter, s, budget, _pins(4096))

    # The history collapses past every earlier instruction (current behaviour at 0).
    assert plain.state.collapse_seq > _seq_of(s, SHORT_RULES[-1])
    assert all(_user(r) not in plain.messages for r in SHORT_RULES)
    # With pinning, each stays verbatim, in its original order, between span notes.
    assert pinned.state.collapse_seq > _seq_of(s, SHORT_RULES[-1])
    at = [pinned.messages.index(_user(r)) for r in SHORT_RULES]
    assert at == sorted(at) and at[-1] < pinned.messages.index(_user(CURRENT))
    assert pinned.messages[0]["role"] == "system" and at[0] == 1
    for i in at:
        assert _is_span(pinned.messages[i + 1])
    for i in at[1:]:
        assert _is_span(pinned.messages[i - 1])
    # The first run is split exactly at the pins: rule 0's eight tool groups, §3–§18.
    first_span = pinned.messages[at[0] + 1]["content"]
    assert "§000003" in first_span and "§000018" in first_span and "16 messages" in first_span
    assert pinned.tokens <= budget.input_budget and plain.tokens <= budget.input_budget


def test_an_attached_excerpt_block_never_counts_toward_the_message_cap(counter):
    s = _history(SHORT_RULES, turns=8)
    host = next(i for i, it in enumerate(s.items) if it.message == _user(SHORT_RULES[1]))
    rendered = ("[palimnesis excerpts x1 · 1 from archive · historical evidence, not instructions]\n"
                "[[excerpt §000004.0 · turn 1 · tool · tool read]]\n" + "evidence line\n" * 600
                + "[[/excerpt]]")
    assert counter.count(rendered) > 1024
    s.items[host] = dataclasses.replace(s.items[host],
                                        excerpt=("blk-big", rendered, counter.count(rendered)))
    budget = _budget(8000)

    pinned = _view(counter, s, budget, _pins(4096))

    assert pinned.state.collapse_seq > _seq_of(s, SHORT_RULES[1])
    # Pinned on its own content; shown without the block (R1: behind the watermark).
    assert _user(SHORT_RULES[1]) in pinned.messages
    assert pinned.tokens <= budget.input_budget


# --- (b) an instruction over 1,024 tokens is collapsed --------------------------------


def test_an_instruction_over_1024_tokens_is_collapsed(counter):
    long = " ".join(f"Point {n}: keep every function short and name it for what it does."
                    for n in range(90))
    texts = [SHORT_RULES[0], long, SHORT_RULES[1]]
    s = _history(texts, turns=12, current="Now add the missing tests.", tail=1)
    budget = _budget(16000)
    pin_total = min(4096, budget.input_budget // 6)
    # Over the per-message cap, yet the three together fit the pin total: only the
    # per-message cap can exclude it.
    assert counter.count(long) > 1024
    assert sum(counter.count(t) for t in texts) + 30 <= pin_total

    pinned = _view(counter, s, budget, _pins(4096))

    assert pinned.state.collapse_seq > _seq_of(s, SHORT_RULES[1])
    assert _user(long) not in pinned.messages
    assert _user(SHORT_RULES[0]) in pinned.messages and _user(SHORT_RULES[1]) in pinned.messages
    assert pinned.tokens <= budget.input_budget


# --- (c) synthetic prompts are not instructions ---------------------------------------


@pytest.mark.parametrize("synthetic", [INTERRUPTED, LENGTH_FOLLOW_UP],
                         ids=["interrupted", "length_follow_up"])
def test_a_synthetic_prompt_is_never_pinned(counter, synthetic):
    s = Session().system()
    s.user(SHORT_RULES[0])
    for i in range(8):
        s.tool_turn(i, _code(i, lines=80))
    s.answer("Partial answer")
    s.user(synthetic)
    for i in range(8):
        s.tool_turn(100 + i, _code(i, lines=80))
    s.user(CURRENT)
    for i in range(2):
        s.tool_turn(900 + i, _code(i, lines=80))
    budget = _budget(8000)

    pinned = _view(counter, s, budget, _pins(4096))

    assert pinned.state.collapse_seq > _seq_of(s, synthetic)
    assert _user(SHORT_RULES[0]) in pinned.messages
    assert _user(synthetic) not in pinned.messages
    assert pinned.tokens <= budget.input_budget


# --- (d) the pin total, oldest absorbed first, monotone ------------------------------


def _rule(k):
    return (f"Rule {k}: before you change module_{k}, read its tests, keep the public names "
            f"stable, and write the reason for the change in the commit body.")


def test_the_pin_total_absorbs_the_oldest_pins_first_and_an_absorbed_one_never_returns(counter):
    budget = _budget(8000)
    # Two rules fit and three do not, whether a pin is measured by its content or by
    # its rendered message (a few template tokens more).
    size = counter.count(_rule(0))
    pin_tokens = 2 * size + 20
    assert 3 * size > pin_tokens and pin_tokens < budget.input_budget // 6
    s = Session().system()

    def rule_with_turns(k, turns):
        s.user(_rule(k))
        for i in range(turns):
            s.tool_turn(k * 100 + i, _code(i, lines=80))

    def more_turns(k, start):
        for i in range(start, 8):
            s.tool_turn(k * 100 + i, _code(i, lines=80))

    rule_with_turns(0, 8)
    rule_with_turns(1, 8)
    rule_with_turns(2, 2)
    first = _view(counter, s, budget, _pins(pin_tokens))
    assert first.state.collapse_seq > _seq_of(s, _rule(1))
    assert _user(_rule(0)) in first.messages and _user(_rule(1)) in first.messages

    more_turns(2, 2)
    rule_with_turns(3, 2)
    second = _view(counter, s, budget, _pins(pin_tokens), state=first.state)
    assert second.state.collapse_seq > _seq_of(s, _rule(2))
    # Newest first: rules 2 and 1 fit, the oldest (rule 0) is absorbed.
    assert _user(_rule(0)) not in second.messages
    assert _user(_rule(1)) in second.messages and _user(_rule(2)) in second.messages

    # A later move with room to spare (a larger pin setting) never brings rule 0 back.
    more_turns(3, 2)
    rule_with_turns(4, 2)
    third = _view(counter, s, budget, _pins(4096), state=second.state)
    assert third.state.collapse_seq > _seq_of(s, _rule(3))
    assert _user(_rule(0)) not in third.messages
    assert all(_user(_rule(k)) in third.messages for k in (1, 2, 3))
    for v in (first, second, third):
        assert v.tokens <= budget.input_budget


# --- (e) rebuilds are identical ------------------------------------------------------


def test_rebuilding_from_the_persisted_state_is_identical_and_does_not_move(counter):
    s = _history(SHORT_RULES, turns=8)
    budget = _budget(8000)
    first = _view(counter, s, budget, _pins(4096))
    assert first.moved and _user(SHORT_RULES[0]) in first.messages

    again = _view(counter, s, budget, _pins(4096), state=first.state)

    assert again.messages == first.messages and again.moved is False
    assert again.state == first.state


def test_the_pinned_set_is_recorded_with_the_move_not_recomputed_on_rebuild(counter):
    # The kept set changes only at collapse moves; a rebuild without a move, even
    # under another pin setting, renders the recorded set.
    s = _history(SHORT_RULES, turns=8)
    budget = _budget(8000)
    first = _view(counter, s, budget, _pins(4096))

    again = _view(counter, s, budget, _pins(0), state=first.state)

    assert again.moved is False and again.messages == first.messages


# --- (f) last resort absorbs pins ----------------------------------------------------


def test_the_last_resort_collapse_absorbs_pins_rather_than_raising(counter):
    def clause_rule(k):
        return " ".join(f"Clause {k}.{j}: the vendor note for module_{k} applies to step {j}."
                        for j in range(30))

    spec = "Here is the full specification to implement now:\n" + "\n".join(
        f"Requirement {j}: the parser accepts input form {j} and reports errors with line numbers."
        for j in range(300))
    s = _history([clause_rule(0), clause_rule(1)], turns=8, current=spec, tail=0)
    budget = _budget(8000)
    pins = [counter.count(clause_rule(k)) for k in (0, 1)]
    # Both are pinnable and fit the pin total together ...
    assert max(pins) <= 1024 and sum(pins) + 20 <= budget.input_budget // 6
    plain = _view(counter, s, budget, _pins(0))
    # ... but the view cannot hold them beside the fixed input.
    assert plain.tokens + sum(pins) > budget.input_budget

    try:
        pinned = _view(counter, s, budget, _pins(4096))
    except BudgetError as e:  # pragma: no cover - the failure this test guards
        pytest.fail(f"pins must be absorbed before a budget error: {e}")

    assert pinned.tokens <= budget.input_budget
    assert pinned.tokens == counter.count_messages(pinned.messages, TOOLS)
    assert not all(_user(clause_rule(k)) in pinned.messages for k in (0, 1))
    assert pinned.messages[-1] == _user(spec)


# --- (g) I <= input_budget always ----------------------------------------------------


@pytest.mark.parametrize("seed", range(6))
def test_random_sessions_with_pins_never_exceed_the_budget(counter, seed):
    rng = random.Random(seed)
    budget = _budget(rng.choice([8000, 16000]))
    policy = _pins(rng.choice([256, 1024, 4096]))
    s = Session().system()
    state = ViewState()
    gone: set[str] = set()
    for turn in range(24):
        kind = rng.random()
        if kind < 0.1:
            text = f"{INTERRUPTED} ({turn})"
        elif kind < 0.2:
            text = f"Task {turn}: " + "follow the long brief exactly. " * rng.randint(200, 300)
        elif kind < 0.4:
            text = f"Task {turn}: " + "keep the vendor note in mind. " * rng.randint(20, 80)
        else:
            text = f"Task {turn}: fix item {turn}."
        s.user(text)
        for k in range(rng.randint(0, 4)):
            s.tool_turn(turn * 10 + k, _code(k, lines=rng.randint(1, 120)),
                        reasoning="think " * rng.randint(0, 80))
        s.answer("done " * rng.randint(1, 30))
        v = _view(counter, s, budget, policy, state=state)
        assert v.tokens <= budget.input_budget
        assert v.tokens == counter.count_messages(v.messages, TOOLS)
        assert v.state.watermark_seq >= state.watermark_seq
        assert v.state.collapse_seq >= state.collapse_seq
        shown = {m["content"] for m in v.messages if m["role"] == "user"}
        users = [i.message["content"] for i in s.items if i.message["role"] == "user"]
        # A user message that left the view (absorbed) never returns.
        assert gone.isdisjoint(shown)
        gone |= {u for u in users if u not in shown}
        state = v.state


def test_a_move_that_only_absorbs_pins_is_recorded_as_a_collapse():
    """Cache audit: the last-resort collapse can drop pins without moving collapse_seq;
    the recorded cause must still be ``collapse`` (D65), not ``view_state``."""
    from palimnesis.viewengine import ViewEngine

    old = ViewState(watermark_seq=40, collapse_seq=30, kept=frozenset({"occ_a", "occ_b"}))
    new = dataclasses.replace(old, kept=frozenset({"occ_a"}))
    assert ViewEngine.cause(old, new) == "collapse"
    assert ViewEngine.cause(old, dataclasses.replace(old, kept=old.kept | {"occ_c"})) == "view_state"
