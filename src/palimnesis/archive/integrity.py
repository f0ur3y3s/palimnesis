"""Archive integrity after a crash or restart (Phase 8 S7, D131; ``check --archive`` in S9).

``check(conn)`` returns a list of problems, empty when the archive is sound:

- SQLite's own ``integrity_check`` and ``foreign_key_check``;
- no branch left with an active request (run after ``ledger.recover``, with no proxy
  serving), and no attempt with more than one terminal event or none at all;
- the derived full-text indexes equal a rebuild: the archive is copied to memory,
  ``search.rebuild`` runs there, and the block index is compared token instance by token
  instance (``fts5vocab`` ``instance``: term, block rowid, offset), the chunk index by
  term and document counts (``fts5vocab`` ``row``, since chunk rowids depend on insertion
  order) plus the chunk map's spans.

It reads only; the comparison runs on the in-memory copy.
"""

from __future__ import annotations

import sqlite3
from collections import Counter

from palimnesis.archive.ledger import TERMINAL_EVENTS
from palimnesis.recall import search


def _vocab(conn: sqlite3.Connection, table: str, kind: str) -> Counter:
    name = f"_v_{table}_{kind}"
    conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS temp.{name} USING fts5vocab(main, {table}, {kind})")
    return Counter(conn.execute(f"SELECT * FROM temp.{name}").fetchall())


def _fts(conn: sqlite3.Connection) -> list[str]:
    mem = sqlite3.connect(":memory:")
    try:
        conn.backup(mem)
        search.rebuild(mem)
        out = []
        if _vocab(conn, "fts_blocks", "instance") != _vocab(mem, "fts_blocks", "instance"):
            out.append("fts_blocks differs from a rebuild")
        if _vocab(conn, "fts_chunks", "row") != _vocab(mem, "fts_chunks", "row"):
            out.append("fts_chunks differs from a rebuild")
        span = "SELECT block_rowid, start, \"end\" FROM chunk_map"
        if Counter(conn.execute(span).fetchall()) != Counter(mem.execute(span).fetchall()):
            out.append("chunk_map differs from a rebuild")
        return out
    finally:
        mem.close()


def check(conn: sqlite3.Connection) -> list[str]:
    out = []
    ic = [r[0] for r in conn.execute("PRAGMA integrity_check").fetchall()]
    if ic != ["ok"]:
        out += [f"integrity_check: {x}" for x in ic]
    out += [f"foreign_key_check: {row}" for row in conn.execute("PRAGMA foreign_key_check")]
    out += [f"branch {b} has active request {r}" for b, r in conn.execute(
        "SELECT branch_id, active_request_id FROM branch_heads WHERE active_request_id IS NOT NULL")]
    marks = ",".join("?" * len(TERMINAL_EVENTS))
    out += [f"attempt {a} has {n} terminal events" for a, n in conn.execute(
        f"SELECT attempt_id, count(*) FROM events WHERE kind IN ({marks})"
        " AND attempt_id IS NOT NULL GROUP BY attempt_id HAVING count(*) > 1", TERMINAL_EVENTS)]
    out += [f"attempt {a} has no terminal event" for (a,) in conn.execute(
        f"SELECT a.attempt_id FROM attempts a WHERE NOT EXISTS (SELECT 1 FROM events e"
        f" WHERE e.attempt_id = a.attempt_id AND e.kind IN ({marks}))"
        " AND NOT EXISTS (SELECT 1 FROM events e WHERE e.request_id = a.request_id"
        f" AND e.attempt_id IS NULL AND e.kind IN ({marks}))", TERMINAL_EVENTS * 2)]
    out += _fts(conn)
    return out
