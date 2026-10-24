"""Raw request archive: byte-exact reconstruction through delta chains (GL2)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mnemon.rawarchive import RawArchiveError, get_raw, put_raw
from mnemon.store import Store

LIVE = sorted(
    (Path(__file__).resolve().parents[1] / "eval/fixtures/opencode-2.1.4/live/exchanges").glob(
        "*/*/request.body"
    )
)


@pytest.fixture
async def store(tmp_path):
    s = Store.open(tmp_path / "archive.db")

    def setup(c):
        for sid in ("s1", "s2"):
            c.execute("INSERT INTO sessions VALUES (?, 1.0, 'path')", (sid,))
            c.execute("INSERT INTO branches VALUES (?, ?, NULL, NULL, 1.0)", (f"{sid}-main", sid))

    await s.write(setup)
    yield s
    s.close()


async def _put(store, body, session="s1", **kw):
    return await store.write(lambda c: put_raw(c, session, f"{session}-main", body, **kw))


async def _get(store, raw_id):
    return await store.read(lambda c: get_raw(c, raw_id))


def _row(store_path, raw_id):
    c = sqlite3.connect(store_path)
    try:
        return c.execute(
            "SELECT format, base_raw_id, depth FROM raw_bodies WHERE raw_id = ?", (raw_id,)
        ).fetchone()
    finally:
        c.close()


@pytest.mark.parametrize("variant", [1, 2])
async def test_live_opencode_bodies_reconstruct_byte_for_byte(store, variant):
    bodies = [p.read_bytes() for p in LIVE]
    ids = [await _put(store, b, variant=variant) for b in bodies]

    assert [await _get(store, i) for i in ids] == bodies


async def test_consecutive_bodies_chain_as_deltas(store, tmp_path):
    first = await _put(store, b'{"messages":[1]}')
    second = await _put(store, b'{"messages":[1,2]}')

    assert _row(tmp_path / "archive.db", first) == (0, None, 0)
    # v2 (prefix + middle + suffix length) is the default (D12).
    assert _row(tmp_path / "archive.db", second) == (2, first, 1)


async def test_chains_never_cross_sessions(store, tmp_path):
    await _put(store, b'{"messages":[1]}', session="s1")
    other = await _put(store, b'{"messages":[1,2]}', session="s2")

    assert _row(tmp_path / "archive.db", other)[:2] == (0, None)


async def test_schema_change_forces_a_snapshot(store, tmp_path):
    await _put(store, b'{"messages":[1],"tools":[]}')
    changed = await _put(store, b'{"messages":[1,2],"tools":[1]}', schema_changed=True)

    assert _row(tmp_path / "archive.db", changed)[0] == 0


async def test_chain_depth_is_bounded_by_periodic_snapshots(store, tmp_path):
    body = b'{"messages":[' + b"0" * 200
    ids = []
    for i in range(7):
        body += b",%d" % i
        ids.append(await _put(store, body + b"]}", max_depth=3))

    depths = [_row(tmp_path / "archive.db", i)[2] for i in ids]
    assert depths == [0, 1, 2, 3, 0, 1, 2]


async def test_unknown_raw_id_is_an_error(store):
    with pytest.raises(RawArchiveError, match="no raw body"):
        await _get(store, 999)


def _tamper(path, sql, *params):
    """Bypass the archive's protections the way an outside process could."""
    c = sqlite3.connect(path)
    try:
        c.execute("DROP TRIGGER raw_bodies_no_update")
        c.execute("DROP TRIGGER raw_bodies_no_delete")
        c.execute(sql, params)
        c.commit()
    finally:
        c.close()


async def test_corrupt_base_raises_instead_of_returning_wrong_bytes(store, tmp_path):
    base = await _put(store, b'{"messages":["hello"]}')
    child = await _put(store, b'{"messages":["hello","world"]}')
    store.close()
    _tamper(tmp_path / "archive.db", "UPDATE raw_bodies SET payload = ? WHERE raw_id = ?", b'{"messages":["jello"]}', base)

    reopened = Store.open(tmp_path / "archive.db")
    try:
        with pytest.raises(RawArchiveError):
            await reopened.read(lambda c: get_raw(c, child))
    finally:
        reopened.close()


async def test_missing_base_raises(store, tmp_path):
    base = await _put(store, b'{"messages":["hello"]}')
    child = await _put(store, b'{"messages":["hello","world"]}')
    store.close()
    _tamper(tmp_path / "archive.db", "DELETE FROM raw_bodies WHERE raw_id = ?", base)

    reopened = Store.open(tmp_path / "archive.db")
    try:
        with pytest.raises(RawArchiveError, match="missing"):
            await reopened.read(lambda c: get_raw(c, child))
    finally:
        reopened.close()


async def test_online_backup_copy_reconstructs(store, tmp_path):
    bodies = [p.read_bytes() for p in LIVE[:4]]
    ids = [await _put(store, b) for b in bodies]

    target = sqlite3.connect(tmp_path / "backup.db")
    await store.read(lambda c: c.backup(target))
    target.close()
    store.close()

    restored = Store.open(tmp_path / "backup.db")
    try:
        assert [await restored.read(lambda c, i=i: get_raw(c, i)) for i in ids] == bodies
    finally:
        restored.close()

