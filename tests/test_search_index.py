"""Full-text index over archived blocks: derived, rebuildable (plan slice 14)."""

from __future__ import annotations

import json

import pytest

from palimnesis import ledger, search
from palimnesis.chat import parse
from palimnesis.fingerprint import fingerprint_v1
from palimnesis.store import Store


@pytest.fixture
async def store(tmp_path):
    s = Store.open(tmp_path / "archive.db")
    yield s
    s.close()


def _request(*messages):
    return parse(json.dumps({"model": "m", "stream": True, "messages": list(messages)}).encode())


async def _accept(store, req, session="s1"):
    fp = fingerprint_v1(ledger.ENDPOINT_CHAT, session, ledger.branch_id_for(session),
                        json.loads(req.raw))
    return await store.write(lambda c: ledger.accept(
        c, session_id=session, association="path", req=req, fingerprint=fp, retry_hint=None))


async def _search(store, query):
    return await store.read(lambda c: search.search_text(c, query))


async def test_client_messages_are_searchable_once_accepted(store):
    await _accept(store, _request({"role": "user", "content": "please refactor parse_config()"}))

    assert await _search(store, "refactor") == ["please refactor parse_config()"]


async def test_generated_text_split_across_batches_is_indexed_whole_at_completion(store):
    plan = await _accept(store, _request({"role": "user", "content": "hi"}))
    gen = ledger.Generation(plan)
    await store.write(lambda c: ledger.commit_batch(c, gen, [("text", "text", "the quick bro", {})], 0))
    await store.write(lambda c: ledger.commit_batch(c, gen, [("text", "text", "wn fox", {})], 10))

    assert await _search(store, "brown") == []  # not indexed until the attempt ends
    await store.write(lambda c: ledger.finish_attempt(c, gen, "turn_complete", finish_reason="stop"))

    assert await _search(store, "brown") == ["the quick brown fox"]


async def test_partial_output_is_indexed_when_the_attempt_fails(store):
    plan = await _accept(store, _request({"role": "user", "content": "hi"}))
    gen = ledger.Generation(plan)
    await store.write(lambda c: ledger.commit_batch(c, gen, [("reasoning", "reasoning", "zebra plan", {})], 0))
    await store.write(lambda c: ledger.finish_attempt(c, gen, "attempt_failed", reason="eof"))

    assert await _search(store, "zebra") == ["zebra plan"]


async def test_rebuild_restores_the_index_from_the_archive(store):
    await _accept(store, _request({"role": "user", "content": "alpha beta"}))
    await store.write(search.clear)
    assert await _search(store, "alpha") == []

    await store.write(search.rebuild)

    assert await _search(store, "alpha") == ["alpha beta"]


async def test_index_is_not_part_of_the_immutable_archive(store):
    await _accept(store, _request({"role": "user", "content": "gamma"}))

    await store.write(search.clear)  # must not raise: derived data
