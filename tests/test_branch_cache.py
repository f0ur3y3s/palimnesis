"""BranchCache: accept's archive reload is O(new rows), not O(history) (plan slice 4, R8)."""

from __future__ import annotations

import json

import pytest

from palimnesis import ledger
from palimnesis.chat import parse
from palimnesis.fingerprint import fingerprint_v1
from palimnesis.store import Store

SESSION = "cache-1"
BRANCH = ledger.branch_id_for(SESSION)


@pytest.fixture
async def store(tmp_path):
    s = Store.open(tmp_path / "archive.db")
    yield s
    s.close()


def _req(messages):
    return parse(json.dumps({"model": "m", "stream": True, "messages": messages}).encode())


async def _turn(store, cache, messages, answer, *, deliver=True, statements=None):
    req = _req(messages)
    fp = fingerprint_v1(ledger.ENDPOINT_CHAT, SESSION, BRANCH, json.loads(req.raw))

    def accept(c):
        if statements is not None:
            c.set_trace_callback(statements.append)
        try:
            return ledger.accept(c, session_id=SESSION, association="path", req=req,
                                 fingerprint=fp, retry_hint=None, cache=cache)
        finally:
            c.set_trace_callback(None)

    plan = await store.write(accept)
    gen = ledger.Generation(plan)
    await store.write(lambda c: ledger.commit_batch(c, gen, [("text", "text", answer, {})], 0))
    await store.write(lambda c: ledger.finish_attempt(c, gen, "turn_complete", finish_reason="stop"))
    if deliver:
        await store.write(lambda c: ledger.record_delivery(c, plan, "delivery_completed"))
    return messages + [{"role": "assistant", "content": answer}]


async def test_cached_history_equals_a_fresh_load_through_a_session(store):
    cache = ledger.BranchCache()
    history = [{"role": "system", "content": "sys 2026-10-24"}]
    for i in range(12):
        history = await _turn(store, cache, history + [{"role": "user", "content": f"u{i}"}],
                              f"a{i}", deliver=i % 3 != 0)
    # a context version mid-session (D10.5)
    history[0] = {"role": "system", "content": "sys 2026-10-25"}
    history = await _turn(store, cache, history + [{"role": "user", "content": "late"}], "z")

    fresh = await store.read(lambda c: ledger.load_archived(c, BRANCH))
    cached = await store.read(lambda c: ledger.load_archived(c, BRANCH, cache=cache))
    assert cached == fresh
    assert fresh[0].occ_id != (await store.read(
        lambda c: c.execute("SELECT occ_id FROM occurrences ORDER BY seq LIMIT 1").fetchone()[0]))


async def test_flags_of_recent_generated_turns_are_refreshed(store):
    cache = ledger.BranchCache()
    history = await _turn(store, cache, [{"role": "user", "content": "q"}], "a", deliver=False)
    before = await store.read(lambda c: ledger.load_archived(c, BRANCH, cache=cache))
    assert before[-1].delivered is False

    occ = before[-1].occ_id
    plan_row = await store.read(lambda c: c.execute(
        "SELECT r.request_id, a.attempt_id FROM requests r JOIN attempts a USING (request_id)"
        " ORDER BY r.arrived_at DESC LIMIT 1").fetchone())
    plan = ledger.Plan(SESSION, BRANCH, plan_row[0], plan_row[1], b"", True)
    await store.write(lambda c: ledger.record_delivery(c, plan, "delivery_completed"))

    after = await store.read(lambda c: ledger.load_archived(c, BRANCH, cache=cache))
    assert (after[-1].occ_id, after[-1].delivered) == (occ, True)


async def test_accept_does_constant_database_work_as_history_grows(store):
    cache = ledger.BranchCache()
    history: list[dict] = []
    counts = {}
    for i in range(120):
        statements: list[str] = []
        history = await _turn(store, cache, history + [{"role": "user", "content": f"u{i}"}],
                              f"a{i}", statements=statements)
        counts[i] = len(statements)

    assert counts[119] <= counts[10] + 2, (counts[10], counts[119])
