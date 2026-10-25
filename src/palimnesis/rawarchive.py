"""Raw accepted request bodies, stored as verified delta chains.

Each body is stored against the previous raw body of the same session and
branch (the raw-storage parent, distinct from the logical conversation
parent) using ``palimnesis.rawdelta``, with snapshots per its policy. Retrieval
walks the chain back to its snapshot and decodes forward, verifying every
step's length and SHA-256: a damaged or missing ancestor raises rather than
yielding different bytes. Both functions run inside the caller's transaction.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time

from . import rawdelta
from .rawdelta import Delta, DeltaError

# v2 adopted per D10.7 / D12: 68.6% smaller on the live replay, 56-58% on
# 200-turn replays (results R6), because OpenCode's tools follow messages.
DEFAULT_VARIANT = rawdelta.PREFIX_MIDDLE_SUFFIX
DEFAULT_MAX_DEPTH = 32
# Bodies recently written or verified, so put_raw need not rebuild the parent
# chain per insert. A hit is used only if it matches the row's stored SHA-256.
# (A rolled-back insert frees its raw_id, but any reuse goes through put_raw,
# which overwrites the entry first; the check is defence in depth.)
_RECENT_LIMIT = 64
_recent: dict[tuple[str, int], bytes] = {}


class RawArchiveError(Exception):
    pass


def _delta(row) -> Delta:
    fmt, prefix_len, suffix_len, payload, total_len, sha256 = row
    return Delta(fmt, prefix_len, payload, suffix_len, total_len, sha256)


def put_raw(
    conn: sqlite3.Connection,
    session_id: str,
    branch_id: str,
    body: bytes,
    *,
    schema_changed: bool = False,
    variant: int = DEFAULT_VARIANT,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> int:
    parent = conn.execute(
        "SELECT raw_id, depth, sha256 FROM raw_bodies WHERE session_id = ? AND branch_id = ?"
        " ORDER BY raw_id DESC LIMIT 1",
        (session_id, branch_id),
    ).fetchone()
    parent_id, parent_depth, parent_sha = parent if parent else (None, 0, None)
    parent_body = _cached_get(conn, parent_id, parent_sha) if parent_id is not None else None
    delta = rawdelta.choose(
        parent_body,
        body,
        depth=parent_depth,
        max_depth=max_depth,
        schema_changed=schema_changed,
        variant=variant,
    )
    is_snapshot = delta.format == rawdelta.SNAPSHOT
    cursor = conn.execute(
        "INSERT INTO raw_bodies (session_id, branch_id, format, base_raw_id, depth,"
        " prefix_len, suffix_len, payload, total_len, sha256, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            branch_id,
            delta.format,
            None if is_snapshot else parent_id,
            0 if is_snapshot else parent_depth + 1,
            delta.prefix_len,
            delta.suffix_len,
            delta.payload,
            delta.total_len,
            delta.sha256,
            time.time(),
        ),
    )
    _remember(conn, cursor.lastrowid, body)
    return cursor.lastrowid


def _db_key(conn: sqlite3.Connection, raw_id: int) -> tuple[str, int]:
    return (conn.execute("PRAGMA database_list").fetchone()[2], raw_id)


def _remember(conn: sqlite3.Connection, raw_id: int, body: bytes) -> None:
    _recent[_db_key(conn, raw_id)] = body
    while len(_recent) > _RECENT_LIMIT:
        _recent.pop(next(iter(_recent)))


def _cached_get(conn: sqlite3.Connection, raw_id: int, sha256: bytes) -> bytes:
    body = _recent.get(_db_key(conn, raw_id))
    if body is None or hashlib.sha256(body).digest() != sha256:
        body = get_raw(conn, raw_id)
        _remember(conn, raw_id, body)
    return body


def get_raw(conn: sqlite3.Connection, raw_id: int) -> bytes:
    chain: list[Delta] = []
    current = raw_id
    while current is not None:
        row = conn.execute(
            "SELECT format, prefix_len, suffix_len, payload, total_len, sha256, base_raw_id"
            " FROM raw_bodies WHERE raw_id = ?",
            (current,),
        ).fetchone()
        if row is None:
            if current == raw_id:
                raise RawArchiveError(f"no raw body {raw_id}")
            raise RawArchiveError(f"raw body {raw_id}: ancestor {current} is missing")
        chain.append(_delta(row[:6]))
        current = row[6]
        if len(chain) > DEFAULT_MAX_DEPTH * 4:
            raise RawArchiveError(f"raw body {raw_id}: delta chain does not terminate")
    body = None
    try:
        for delta in reversed(chain):
            body = rawdelta.decode(delta, body)
    except DeltaError as e:
        raise RawArchiveError(f"raw body {raw_id} failed verification: {e}") from e
    return body
