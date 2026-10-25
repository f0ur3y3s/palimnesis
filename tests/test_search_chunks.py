"""Chunk-level full-text index for proactive recall (docs/plans/phase3.md §2, D27)."""

from __future__ import annotations

import json
import random
import sqlite3

import pytest

from palimnesis import search
from palimnesis.search import CHUNK_CHARS, CHUNK_LINES, chunk_spans
from palimnesis.store import Store
from palimnesis.stubs import is_safe_cut

from .test_search_index import _accept, _request


@pytest.fixture
async def store(tmp_path):
    s = Store.open(tmp_path / "archive.db")
    yield s
    s.close()


def _lines(n, fill="lorem ipsum dolor"):
    return "\n".join(f"{fill} {i}" for i in range(n))


@pytest.mark.parametrize("seed", range(20))
def test_chunks_tile_the_text_within_line_and_char_limits_at_safe_cuts(seed):
    rng = random.Random(seed)
    pieces = ["word ", "\n", "x" * rng.randint(1, 3000), "é", "👍🏽", "\r\n", "🇯🇵", " "]
    text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 400)))

    spans = chunk_spans(text)

    assert [s for s, _ in spans] == [0] + [e for _, e in spans[:-1]]
    assert (spans[-1][1] if spans else 0) == len(text)
    for start, end in spans:
        assert 0 < end - start <= CHUNK_CHARS
        assert text[start:end].count("\n") <= CHUNK_LINES
        assert is_safe_cut(text, start) and is_safe_cut(text, end)


def test_a_long_line_is_cut_at_whitespace_not_inside_a_word():
    text = ("token " * 1000).strip()

    spans = chunk_spans(text)

    assert len(spans) > 1
    for start, end in spans[:-1]:
        assert text[end - 1] == " " or text[end] == " "


async def _hits(store, query, **kw):
    return await store.read(lambda c: search.search_chunks(c, query, **kw))


async def test_a_dense_hit_inside_a_long_block_outranks_a_sparse_hit(store):
    long = _lines(3000).split("\n")
    long[1500] = "the alpha omega handshake failed"
    await _accept(store, _request({"role": "user", "content": "\n".join(long)}))
    await _accept(store, _request({"role": "user", "content": "alpha only here"}), session="s2")

    hits = await _hits(store, '"alpha" OR "omega"')

    best = hits[0]
    assert "alpha omega handshake" in best.text
    assert best.end - best.start <= CHUNK_CHARS
    assert {h.text for h in hits[1:]} == {"alpha only here"}


async def test_search_is_limited_to_candidate_blocks(store):
    await _accept(store, _request({"role": "user", "content": "kestrel in session one"}))
    await _accept(store, _request({"role": "user", "content": "kestrel in session two"}), session="s2")
    everything = await _hits(store, '"kestrel"')
    one = [h for h in everything if "one" in h.text]

    limited = await _hits(store, '"kestrel"', block_rowids=[one[0].block_rowid])

    assert [h.text for h in limited] == ["kestrel in session one"]
    assert await _hits(store, '"kestrel"', block_rowids=[]) == []


async def test_ties_break_by_newest_source_then_block_then_offset(store):
    for session in ("s1", "s2", "s3"):
        await _accept(store, _request({"role": "user", "content": "osprey"}), session=session)

    hits = await _hits(store, '"osprey"')

    assert len(hits) == 3 and len({h.score for h in hits}) == 1
    assert hits == sorted(hits, key=lambda h: (h.score, -h.seq, h.block_idx, h.start, h.rowid))


async def test_rebuild_restores_chunks_and_clear_removes_them(store):
    await _accept(store, _request({"role": "user", "content": "heron nesting"}))
    await store.write(search.clear)
    assert await _hits(store, '"heron"') == []

    await store.write(search.rebuild)

    assert [h.text for h in await _hits(store, '"heron"')] == ["heron nesting"]


async def test_opening_a_version_4_archive_backfills_the_chunk_index(tmp_path):
    db = tmp_path / "archive.db"
    s = Store.open(db)
    await _accept(s, _request({"role": "user", "content": "plover migration"}))
    s.close()
    raw = sqlite3.connect(db)  # simulate an archive written before migration 5
    raw.execute("DROP TABLE fts_chunks")
    raw.execute("DROP TABLE chunk_map")
    raw.execute("PRAGMA user_version = 4")
    raw.commit()
    raw.close()

    s = Store.open(db)
    try:
        hits = await s.read(lambda c: search.search_chunks(c, '"plover"'))
    finally:
        s.close()

    assert [h.text for h in hits] == ["plover migration"]
