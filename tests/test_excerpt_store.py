"""Excerpt blocks in the archive (A1): immutable, one per host user message, all fields."""

from __future__ import annotations

import sqlite3

import pytest

from palimnesis import ledger
from palimnesis.excerpts import Selection, SelectedExcerpt
from palimnesis.store import Store


@pytest.fixture
async def store(tmp_path):
    s = Store.open(tmp_path / "archive.db")

    def seed(c):
        c.execute("INSERT INTO sessions VALUES ('s', 1.0, 'path')")
        c.execute("INSERT INTO branches VALUES ('s/main', 's', NULL, NULL, 1.0)")
        c.execute("INSERT INTO raw_bodies VALUES (1, 's', 's/main', 0, NULL, 0, 0, 0, x'7b7d', 2, x'00', 1.0)")
        c.execute("INSERT INTO requests VALUES ('r1', 's', 's/main', '/v1/chat/completions', 1, 1,"
                  " 'fp', 1, NULL, NULL, NULL, '{}', 1.0)")
        c.execute("INSERT INTO attempts VALUES ('a1', 'r1', 1, 1.0)")
        for seq, occ in ((1, "src"), (2, "host")):
            c.execute("INSERT INTO occurrences VALUES (?, 's/main', ?, NULL, 'user', 'both',"
                      " 'client', 'r1', NULL, '{}', 'h')", (occ, seq))

    await s.write(seed)
    yield s
    s.close()


SELECTION = Selection(
    query="parse config", query_version="q0", retrieval_version="r0", archive_cutoff_seq=1,
    items=(SelectedExcerpt(rank=1, score=3.5, source_occ_id="src", source_alias="AAAAAA",
                           source_block=0, start=0, end=11, source_sha256="ab" * 32,
                           turn_number=1, role="user", tool_name=None, text="parse config"),),
)


def _record(c, selection=SELECTION, rendered="[palimnesis excerpts x1 · 1 …]", charge=12):
    plan = ledger.Plan("s", "s/main", "r1", "a1", b"", True)
    return ledger.record_excerpts(c, plan, host_occ_id="host", selection=selection,
                                  rendered=rendered, token_charge=charge, allocation=972,
                                  base_view_n=0, base_watermark_seq=0, base_collapse_seq=0,
                                  renderer_version="x1", profile_id="strata-0.1.48@test")


async def test_a_recorded_selection_round_trips_every_field(store):
    block_id = await store.write(_record)

    block = await store.read(lambda c: ledger.excerpt_block(c, "host"))

    assert block.block_id == block_id
    assert (block.status, block.rendered, block.token_charge, block.allocation) == (
        "selected", "[palimnesis excerpts x1 · 1 …]", 12, 972)
    assert (block.query, block.query_version, block.retrieval_version, block.renderer_version,
            block.archive_cutoff_seq, block.base_view_n) == ("parse config", "q0", "r0", "x1", 1, 0)
    [item] = block.items
    assert (item.source_occ_id, item.start, item.end, item.turn_number, item.role,
            item.tool_name, item.score) == ("src", 0, 11, 1, "user", None, 3.5)


async def test_an_empty_selection_is_recorded_too(store):
    empty = Selection(query="", query_version="q0", retrieval_version="r0",
                      archive_cutoff_seq=1, items=())

    await store.write(lambda c: _record(c, selection=empty, rendered="", charge=0))

    block = await store.read(lambda c: ledger.excerpt_block(c, "host"))
    assert (block.status, block.rendered, block.items) == ("empty", "", ())


async def test_a_host_message_gets_at_most_one_block(store):
    await store.write(_record)

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await store.write(_record)


async def test_excerpt_rows_are_immutable(store):
    await store.write(_record)
    for sql in ("UPDATE excerpt_blocks SET rendered = 'x'", "DELETE FROM excerpt_blocks",
                "UPDATE excerpt_items SET end = 3", "DELETE FROM excerpt_items"):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            await store.write(lambda c, sql=sql: c.execute(sql))


async def test_blocks_for_a_branch_are_listed_by_host(store):
    block_id = await store.write(_record)

    blocks = await store.read(lambda c: ledger.excerpt_blocks(c, "s/main"))

    assert list(blocks) == ["host"] and blocks["host"].block_id == block_id


async def test_unknown_host_has_no_block(store):
    assert await store.read(lambda c: ledger.excerpt_block(c, "nope")) is None
