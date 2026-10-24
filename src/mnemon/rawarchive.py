"""Raw accepted request bodies, stored as verified delta chains.

Each body is stored against the previous raw body of the same session and
branch (the raw-storage parent, distinct from the logical conversation
parent) using ``mnemon.rawdelta``, with snapshots per its policy. Retrieval
walks the chain back to its snapshot and decodes forward, verifying every
step's length and SHA-256: a damaged or missing ancestor raises rather than
yielding different bytes. Both functions run inside the caller's transaction.
"""

from __future__ import annotations

import sqlite3
import time

from . import rawdelta
from .rawdelta import Delta, DeltaError

DEFAULT_VARIANT = rawdelta.PREFIX_SUFFIX
DEFAULT_MAX_DEPTH = 32


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
        "SELECT raw_id, depth FROM raw_bodies WHERE session_id = ? AND branch_id = ?"
        " ORDER BY raw_id DESC LIMIT 1",
        (session_id, branch_id),
    ).fetchone()
    parent_id, parent_depth = parent if parent else (None, 0)
    parent_body = get_raw(conn, parent_id) if parent_id is not None else None
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
    return cursor.lastrowid


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
