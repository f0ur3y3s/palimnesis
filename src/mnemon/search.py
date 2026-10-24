"""Full-text index over archived blocks (derived, rebuildable).

``fts_blocks`` is a contentless FTS5 table whose rowid is the indexed block's
``blocks.rowid``; the text itself lives only in ``segments``. Client blocks
are indexed when accepted; generated blocks once their attempt ends, so
words split across stream batches are indexed whole. ``rebuild`` restores
the index from the immutable archive at any time.

This is lexical search (FTS5, ``unicode61`` tokens), not regex; the model
facing search tools and their syntax arrive in Phase 3.
"""

from __future__ import annotations

import sqlite3


def _block_text(conn: sqlite3.Connection, block_id: str, encoding: str) -> str:
    data = b"".join(
        row[0]
        for row in conn.execute(
            "SELECT bytes FROM segments WHERE block_id = ? ORDER BY seq", (block_id,)
        )
    )
    return data.decode("utf-8", "surrogatepass" if encoding == "wtf-8" else "strict")


def index_occurrence(conn: sqlite3.Connection, occ_id: str) -> None:
    for rowid, block_id, encoding in conn.execute(
        "SELECT rowid, block_id, encoding FROM blocks WHERE occ_id = ?", (occ_id,)
    ).fetchall():
        conn.execute("DELETE FROM fts_blocks WHERE rowid = ?", (rowid,))
        # SQLite stores valid UTF-8 only; lone surrogates (WTF-8 blocks) are
        # indexed as "?". The archive itself keeps the exact bytes.
        text = _block_text(conn, block_id, encoding)
        text = text.encode("utf-8", "replace").decode("utf-8")
        conn.execute("INSERT INTO fts_blocks (rowid, text) VALUES (?, ?)", (rowid, text))


def clear(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM fts_blocks")


def rebuild(conn: sqlite3.Connection) -> None:
    clear(conn)
    for (occ_id,) in conn.execute("SELECT occ_id FROM occurrences").fetchall():
        index_occurrence(conn, occ_id)


def search_text(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[str]:
    """Matching blocks' full text, best match first (diagnostic helper)."""
    rows = conn.execute(
        "SELECT b.block_id, b.encoding FROM fts_blocks f JOIN blocks b ON b.rowid = f.rowid"
        " WHERE fts_blocks MATCH ? ORDER BY rank LIMIT ?",
        (query, limit),
    ).fetchall()
    return [_block_text(conn, block_id, encoding) for block_id, encoding in rows]
