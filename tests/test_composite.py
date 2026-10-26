"""Composite visible turns (Phase 3B S2; plan §2.1, D51).

One visible assistant response can span several upstream calls: each call is its own
generation, and the hidden recall results between them are internal rows. The client
sees one message (text and reasoning in stream order, external calls only). The
archive reconciles the client's resend against that composite, and renders the
upstream history as the model saw it: every part with its own reasoning and calls,
the hidden results in call order. Expected bodies are literal messages."""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from palimnesis import ledger, search
from palimnesis.chat import parse
from palimnesis.fingerprint import fingerprint_v1
from palimnesis.ledger import Generation, Rejection
from palimnesis.store import Store

SID = "comp"
SYSTEM = {"role": "system", "content": "You are a coding agent."}
ASK = {"role": "user", "content": "What did the log say about E-4123?"}
RECALL_ARGS = '{"id": "§ABCDEF.0"}'
RESULT = "[palimnesis_recall §ABCDEF.0 tool_result · 0–40 of 40]\nline 123: E-4123 kilnworks ok"


@pytest.fixture
def store(tmp_path):
    s = Store.open(tmp_path / "archive.db")
    yield s
    s.close()


def _write(store, fn):
    return asyncio.run(store.write(fn))


def _accept(store, messages):
    req = parse(json.dumps({"model": "m", "stream": True, "messages": messages}).encode())
    fp = fingerprint_v1(ledger.ENDPOINT_CHAT, SID, ledger.branch_id_for(SID), json.loads(req.raw))
    return _write(store, lambda c: ledger.accept(c, session_id=SID, association="path", req=req,
                                                 fingerprint=fp, retry_hint=None, live=set()))


def _hidden_turn(store, plan, *, second_text="E-4123 means the kiln was fine.",
                 external=None, finish="turn_complete", delivered=True):
    """Part 1: reasoning, text, a hidden recall call; its result; part 2: reasoning,
    text and optionally external calls."""
    g1 = Generation(plan)
    _write(store, lambda c: ledger.commit_batch(c, g1, [
        ("reasoning", "reasoning", "I should look it up.", {}),
        ("text", "text", "Let me check. ", {}),
        ("tool_call", ("tool", 0), RECALL_ARGS,
         {"id": "call_r1", "name": "palimnesis_recall", "internal": True}),
    ], 0))
    _write(store, lambda c: ledger.commit_internal_result(
        c, g1, "call_r1", "palimnesis_recall", RESULT, {"ok": True}))
    g2 = _write(store, lambda c: ledger.next_generation(c, g1))
    parts = [("reasoning", "reasoning", "Found it.", {}), ("text", "text", second_text, {})]
    for i, (cid, name, args) in enumerate(external or []):
        parts.append(("tool_call", ("tool", i), args, {"id": cid, "name": name}))
    _write(store, lambda c: ledger.commit_batch(c, g2, parts, 10))
    if finish:
        _write(store, lambda c: ledger.finish_attempt(c, g2, finish))
    if delivered:
        _write(store, lambda c: ledger.record_delivery(c, plan, "delivery_completed"))
    return g1, g2


def _upstream(plan) -> list[dict]:
    return json.loads(plan.upstream_body)["messages"]


PART1 = {"role": "assistant", "content": "Let me check. ", "reasoning_content": "I should look it up.",
         "tool_calls": [{"id": "call_r1", "type": "function",
                         "function": {"name": "palimnesis_recall", "arguments": RECALL_ARGS}}]}
RESULT_MSG = {"role": "tool", "tool_call_id": "call_r1", "content": RESULT}
PART2 = {"role": "assistant", "content": "E-4123 means the kiln was fine.",
         "reasoning_content": "Found it."}
VISIBLE = "Let me check. E-4123 means the kiln was fine."


def test_resend_of_the_composite_renders_every_part_and_result_upstream(store):
    plan = _accept(store, [SYSTEM, ASK])
    _hidden_turn(store, plan)
    nxt = _accept(store, [SYSTEM, ASK, {"role": "assistant", "content": VISIBLE},
                          {"role": "user", "content": "thanks"}])
    assert _upstream(nxt) == [SYSTEM, ASK, PART1, RESULT_MSG, PART2,
                              {"role": "user", "content": "thanks"}]


def test_reasoning_resent_in_stream_order_also_matches(store):
    plan = _accept(store, [SYSTEM, ASK])
    _hidden_turn(store, plan)
    nxt = _accept(store, [SYSTEM, ASK, {"role": "assistant", "content": VISIBLE,
                                        "reasoning_content": "I should look it up.Found it."},
                          {"role": "user", "content": "thanks"}])
    assert _upstream(nxt)[2:5] == [PART1, RESULT_MSG, PART2]


def test_each_part_and_result_is_its_own_view_item_in_seq_order(store):
    plan = _accept(store, [SYSTEM, ASK])
    g1, g2 = _hidden_turn(store, plan)
    nxt = _accept(store, [SYSTEM, ASK, {"role": "assistant", "content": VISIBLE},
                          {"role": "user", "content": "thanks"}])
    occs = [i.occ_id for i in nxt.items]
    seqs = [i.seq for i in nxt.items]
    assert occs[2] == g1.occ_id and occs[4] == g2.occ_id and occs[3] not in (g1.occ_id, g2.occ_id)
    assert seqs == sorted(seqs) and None not in seqs
    assert [i.message for i in nxt.items][2:5] == [PART1, RESULT_MSG, PART2]


@pytest.mark.parametrize("content", ["Let me check. ", "E-4123 means the kiln was fine.",
                                     VISIBLE + "!"])
def test_a_resend_that_is_not_the_whole_visible_text_diverges(store, content):
    plan = _accept(store, [SYSTEM, ASK])
    _hidden_turn(store, plan)
    with pytest.raises(Rejection) as e:
        _accept(store, [SYSTEM, ASK, {"role": "assistant", "content": content},
                        {"role": "user", "content": "thanks"}])
    assert e.value.code == "history_divergence"


def test_the_client_never_resends_hidden_calls_and_external_calls_match(store):
    plan = _accept(store, [SYSTEM, ASK])
    ext = [("call_e1", "read", '{"path": "kiln.log"}')]
    _hidden_turn(store, plan, external=ext)
    resent = {"role": "assistant", "content": VISIBLE, "tool_calls": [
        {"id": "call_e1", "type": "function", "function": {"name": "read",
                                                           "arguments": '{"path":"kiln.log"}'}}]}
    nxt = _accept(store, [SYSTEM, ASK, resent,
                          {"role": "tool", "tool_call_id": "call_e1", "content": "kiln ok"}])
    up = _upstream(nxt)
    assert up[2:4] == [PART1, RESULT_MSG]
    assert up[4]["tool_calls"][0]["id"] == "call_e1" and "palimnesis" not in json.dumps(up[4])
    assert up[5] == {"role": "tool", "tool_call_id": "call_e1", "content": "kiln ok"}


def test_a_resend_that_includes_a_hidden_call_diverges(store):
    plan = _accept(store, [SYSTEM, ASK])
    _hidden_turn(store, plan)
    leaked = {"role": "assistant", "content": VISIBLE, "tool_calls": [
        {"id": "call_r1", "type": "function", "function": {"name": "read", "arguments": "{}"}}]}
    with pytest.raises(Rejection):
        _accept(store, [SYSTEM, ASK, leaked, {"role": "user", "content": "thanks"}])


def test_a_flattened_partial_of_a_composite_is_judged_in_stream_order(store):
    plan = _accept(store, [SYSTEM, ASK])
    _hidden_turn(store, plan, finish="attempt_failed", delivered=False)
    # The client received r1, t1, r2 and part of t2, and flattens them as all reasoning,
    # then all text (docs/probes/opencode_hidden_stream.md, H1 c).
    flattened = "I should look it up." + "Found it." + "Let me check. " + "E-4123 means"
    nxt = _accept(store, [SYSTEM, ASK, {"role": "assistant", "content": flattened},
                          {"role": "user", "content": "go on"}])
    up = _upstream(nxt)
    # Part 1 was complete (its result exists); part 2 is cut where the client's copy ends.
    assert up[2:4] == [PART1, RESULT_MSG]
    assert up[4] == {"role": "assistant", "content": "E-4123 means", "reasoning_content": "Found it."}


def test_a_partial_cut_inside_part_one_drops_the_hidden_call_and_later_parts(store):
    plan = _accept(store, [SYSTEM, ASK])
    _hidden_turn(store, plan, finish="attempt_failed", delivered=False)
    nxt = _accept(store, [SYSTEM, ASK, {"role": "assistant", "content": "I should look it up.Let"},
                          {"role": "user", "content": "go on"}])
    up = _upstream(nxt)
    assert up[2] == {"role": "assistant", "content": "Let", "reasoning_content": "I should look it up."}
    assert up[3] == {"role": "user", "content": "go on"}


def test_a_cancelled_composite_the_client_dropped_leaves_no_hidden_rows_upstream(store):
    plan = _accept(store, [SYSTEM, ASK])
    _hidden_turn(store, plan, finish="cancelled", delivered=False)
    nxt = _accept(store, [SYSTEM, ASK, {"role": "user", "content": "try again"}])
    up = _upstream(nxt)
    assert "palimnesis_recall" not in json.dumps(up) and RESULT not in json.dumps(up)
    assert up == [SYSTEM, ASK, {"role": "user", "content": "try again"}]


def test_the_composite_survives_a_restart(store, tmp_path):
    plan = _accept(store, [SYSTEM, ASK])
    _hidden_turn(store, plan)
    store.close()
    reopened = Store.open(tmp_path / "archive.db")
    try:
        nxt = _accept(reopened, [SYSTEM, ASK, {"role": "assistant", "content": VISIBLE},
                                 {"role": "user", "content": "thanks"}])
        assert _upstream(nxt)[2:5] == [PART1, RESULT_MSG, PART2]
    finally:
        reopened.close()


def test_hidden_results_are_not_full_text_indexed(store, tmp_path):
    plan = _accept(store, [SYSTEM, ASK])
    _hidden_turn(store, plan)
    conn = sqlite3.connect(tmp_path / "archive.db")
    try:
        hits = search.search_chunks(conn, '"kilnworks"')
        assert hits == []  # the word occurs only inside the recall result
    finally:
        conn.close()


def test_a_single_generation_turn_is_unchanged(store):
    plan = _accept(store, [SYSTEM, ASK])
    g = Generation(plan)
    _write(store, lambda c: ledger.commit_batch(c, g, [("text", "text", "Plain answer.", {})], 0))
    _write(store, lambda c: ledger.finish_attempt(c, g, "turn_complete"))
    _write(store, lambda c: ledger.record_delivery(c, plan, "delivery_completed"))
    nxt = _accept(store, [SYSTEM, ASK, {"role": "assistant", "content": "Plain answer."},
                          {"role": "user", "content": "ok"}])
    assert json.loads(nxt.upstream_body)["messages"][2] == {"role": "assistant",
                                                             "content": "Plain answer."}
    assert nxt.upstream_body == parse(nxt.upstream_body).raw  # the client's body, unchanged
