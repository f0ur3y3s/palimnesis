"""Archive store: durability settings, immutability and connection policy.

Tests run against real SQLite files (seam S in docs/plans/phase1.md).
"""

from __future__ import annotations

import asyncio
import sqlite3
import time

import pytest

from palimnesis.store import IMMUTABLE_TABLES, Store, StoreError


@pytest.fixture
async def store(tmp_path):
    s = Store.open(tmp_path / "archive.db")
    yield s
    s.close()


def _seed(c: sqlite3.Connection) -> None:
    """One row in every archive table, satisfying foreign keys."""
    c.execute("INSERT INTO sessions VALUES ('s1', 1.0, 'path')")
    c.execute("INSERT INTO branches VALUES ('b1', 's1', NULL, NULL, 1.0)")
    c.execute(
        "INSERT INTO raw_bodies VALUES (1, 's1', 'b1', 0, NULL, 0, 0, 0, x'7b7d', 2, x'00', 1.0)"
    )
    c.execute(
        "INSERT INTO requests VALUES ('r1', 's1', 'b1', '/v1/chat/completions', 1, 1, 'fp',"
        " 1, NULL, NULL, NULL, '{}', 1.0)"
    )
    c.execute("INSERT INTO idempotency_bindings VALUES ('s1', 'b1', 'k1', 'r1', 'fp', 1)")
    c.execute("INSERT INTO attempts VALUES ('a1', 'r1', 1, 1.0)")
    c.execute(
        "INSERT INTO occurrences VALUES ('o1', 'b1', 1, NULL, 'user', 'both', 'client',"
        " 'r1', NULL, '{}', 'h')"
    )
    c.execute("INSERT INTO generations VALUES ('g1', 'a1', 'o1', 1)")
    c.execute("INSERT INTO blocks VALUES ('k1', 'o1', 0, 'text', 'utf-8', '{}')")
    c.execute("INSERT INTO segments VALUES ('k1', 0, x'6869')")
    c.execute("INSERT INTO visible_map VALUES ('k1', 0, 2, 'k1', 0)")
    c.execute("INSERT INTO events (request_id, attempt_id, kind, payload, at) VALUES ('r1', 'a1', 'accepted_input', '{}', 1.0)")
    c.execute("INSERT INTO prepared_responses VALUES ('r1', 200, '[]', x'7b7d')")
    c.execute("INSERT INTO aliases VALUES ('s1', 'ABCDEF', 'o1')")


async def test_wal_and_full_synchronous_are_read_back_on_writer_and_reader(store):
    d = await store.diagnostics()

    assert d["writer"] == {"journal_mode": "wal", "synchronous": "FULL"}
    assert d["reader"] == {"journal_mode": "wal", "synchronous": "FULL"}


async def test_normal_synchronous_is_explicit_and_reported(tmp_path):
    s = Store.open(tmp_path / "a.db", synchronous="NORMAL")
    try:
        d = await s.diagnostics()
    finally:
        s.close()

    assert d["writer"]["synchronous"] == "NORMAL"
    assert d["power_loss_durable"] is False


async def test_full_mode_claims_power_loss_durability_only_when_set(store):
    assert (await store.diagnostics())["power_loss_durable"] is True


def test_unknown_synchronous_mode_is_refused(tmp_path):
    with pytest.raises(StoreError, match="synchronous"):
        Store.open(tmp_path / "a.db", synchronous="OFF")


def test_database_that_cannot_use_wal_refuses_to_open():
    # An in-memory database reports journal_mode=memory, not wal.
    with pytest.raises(StoreError, match="journal_mode"):
        Store.open(":memory:")


@pytest.mark.parametrize("table", IMMUTABLE_TABLES)
async def test_archive_rows_cannot_be_updated(store, table):
    await store.write(_seed)

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await store.write(lambda c: c.execute(f"UPDATE {table} SET rowid = rowid"))


@pytest.mark.parametrize("table", IMMUTABLE_TABLES)
async def test_archive_rows_cannot_be_deleted(store, table):
    await store.write(_seed)

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await store.write(lambda c: c.execute(f"DELETE FROM {table}"))


async def test_insert_or_replace_cannot_overwrite_an_archive_row(store):
    await store.write(_seed)

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await store.write(
            lambda c: c.execute("INSERT OR REPLACE INTO sessions VALUES ('s1', 2.0, 'header')")
        )
    # A replace through a secondary unique key must not delete the old row either.
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await store.write(
            lambda c: c.execute(
                "INSERT OR REPLACE INTO occurrences VALUES ('o2', 'b1', 1, NULL, 'user',"
                " 'both', 'client', 'r1', NULL, '{}', 'h2')"
            )
        )


async def test_upsert_cannot_modify_an_archive_row(store):
    await store.write(_seed)

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await store.write(
            lambda c: c.execute(
                "INSERT INTO sessions VALUES ('s1', 2.0, 'header')"
                " ON CONFLICT(session_id) DO UPDATE SET association = 'header'"
            )
        )


async def test_plain_sqlite_connection_cannot_mutate_the_archive(store, tmp_path):
    await store.write(_seed)
    store.close()

    raw = sqlite3.connect(tmp_path / "archive.db")
    try:
        for sql in (
            "UPDATE segments SET bytes = x'00'",
            "DELETE FROM occurrences",
            "INSERT OR REPLACE INTO sessions VALUES ('s1', 9.0, 'x')",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                raw.execute(sql)
    finally:
        raw.close()


async def test_schema_changes_are_denied_on_store_connections(store):
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        await store.write(lambda c: c.execute("DROP TRIGGER sessions_no_update"))
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        await store.write(lambda c: c.execute("ALTER TABLE sessions ADD COLUMN x TEXT"))


async def test_derived_tables_remain_mutable(store):
    await store.write(_seed)

    def advance(c):
        c.execute("INSERT INTO branch_heads VALUES ('b1', 'o1', NULL, 1)")
        c.execute("UPDATE branch_heads SET version = 2 WHERE branch_id = 'b1'")

    await store.write(advance)

    assert await store.read(
        lambda c: c.execute("SELECT version FROM branch_heads").fetchone()[0]
    ) == 2


async def test_failed_write_rolls_back_every_statement(store):
    def half_then_fail(c):
        c.execute("INSERT INTO sessions VALUES ('s9', 1.0, 'path')")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await store.write(half_then_fail)

    assert await store.read(lambda c: c.execute("SELECT count(*) FROM sessions").fetchone()[0]) == 0


async def test_committed_writes_survive_reopen(store, tmp_path):
    await store.write(_seed)
    store.close()

    reopened = Store.open(tmp_path / "archive.db")
    try:
        assert await reopened.read(
            lambda c: c.execute("SELECT association FROM sessions").fetchone()[0]
        ) == "path"
    finally:
        reopened.close()


async def test_a_second_store_on_the_same_database_is_refused(store, tmp_path):
    with pytest.raises(StoreError, match="in use"):
        Store.open(tmp_path / "archive.db")


async def test_lock_is_released_on_close(tmp_path):
    Store.open(tmp_path / "a.db").close()
    Store.open(tmp_path / "a.db").close()


async def test_slow_database_work_does_not_block_the_event_loop(store):
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    await store.write(lambda c: time.sleep(0.3))
    task.cancel()

    # A blocked loop would tick at most once; ~15 ms Windows timer
    # granularity still allows well over 10 ticks in 0.3 s.
    assert ticks >= 10


async def test_view_versions_are_immutable(store):
    await store.write(_seed)

    def add_view(c):
        c.execute("INSERT INTO view_versions VALUES ('v1', 'b1', 1, 'r1', 'v1', 's1', 3, 0,"
                  " '{}', '{}', 'watermark_move', 1.0)")

    await store.write(add_view)
    for sql in ("UPDATE view_versions SET watermark_seq = 9", "DELETE FROM view_versions",
                "INSERT OR REPLACE INTO view_versions VALUES ('v1', 'b1', 1, 'r1', 'v1', 's1',"
                " 9, 0, '{}', '{}', 'x', 1.0)"):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            await store.write(lambda c, sql=sql: c.execute(sql))
