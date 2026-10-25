"""Full-text index over archived blocks (derived, rebuildable).

``fts_blocks`` is a contentless FTS5 table whose rowid is the indexed block's
``blocks.rowid``; the text itself lives only in ``segments``. Client blocks
are indexed when accepted; generated blocks once their attempt ends, so
words split across stream batches are indexed whole. ``rebuild`` restores
the index from the immutable archive at any time.

``fts_chunks`` (migration 5, D27) indexes the same text in chunks of at most
``CHUNK_LINES`` lines and ``CHUNK_CHARS`` code points, mapped back to exact
code-point ranges by ``chunk_map``. Proactive recall ranks chunks, not
blocks: BM25's length normalization would otherwise bury one dense hit
inside a long tool output.

This is lexical search (FTS5, ``unicode61`` tokens), not regex.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from .stubs import is_safe_cut

CHUNK_LINES = 24
CHUNK_CHARS = 1536


def _block_text(conn: sqlite3.Connection, block_id: str, encoding: str) -> str:
    data = b"".join(
        row[0]
        for row in conn.execute(
            "SELECT bytes FROM segments WHERE block_id = ? ORDER BY seq", (block_id,)
        )
    )
    return data.decode("utf-8", "surrogatepass" if encoding == "wtf-8" else "strict")


def chunk_spans(text: str) -> list[tuple[int, int]]:
    """Contiguous ``(start, end)`` code-point ranges tiling ``text``: each at most
    ``CHUNK_LINES`` newlines and ``CHUNK_CHARS`` code points, cut at a line end,
    else at whitespace, else at any safe cut (never inside a cluster)."""
    spans: list[tuple[int, int]] = []
    n, start = len(text), 0
    while start < n:
        end, newlines = start, 0
        limit = min(n, start + CHUNK_CHARS)
        while end < limit:
            if text[end] == "\n":
                newlines += 1
                if newlines == CHUNK_LINES:
                    end += 1
                    break
            end += 1
        if end < n and end == limit and text[end - 1] != "\n":
            cut = text.rfind("\n", start, end) + 1
            if cut <= start:
                cut = max(text.rfind(" ", start, end), text.rfind("\t", start, end)) + 1
            if cut > start + CHUNK_CHARS // 2 or (cut > start and "\n" in text[start:end]):
                end = cut
        while end < n and end > start + 1 and not is_safe_cut(text, end):
            end -= 1
        if not is_safe_cut(text, end):  # one cluster longer than the window
            while end < n and not is_safe_cut(text, end):
                end += 1
        spans.append((start, end))
        start = end
    return spans


def _indexable(conn: sqlite3.Connection, block_id: str, encoding: str) -> str:
    # SQLite stores valid UTF-8 only; lone surrogates (WTF-8 blocks) are indexed
    # as "?", one code point each, so offsets still match the archived text.
    return _block_text(conn, block_id, encoding).encode("utf-8", "replace").decode("utf-8")


def _index_chunks(conn: sqlite3.Connection, rowid: int, text: str) -> None:
    for (chunk,) in conn.execute("SELECT rowid FROM chunk_map WHERE block_rowid = ?",
                                 (rowid,)).fetchall():
        conn.execute("DELETE FROM fts_chunks WHERE rowid = ?", (chunk,))
    conn.execute("DELETE FROM chunk_map WHERE block_rowid = ?", (rowid,))
    for start, end in chunk_spans(text):
        cur = conn.execute("INSERT INTO chunk_map (block_rowid, start, \"end\") VALUES (?, ?, ?)",
                           (rowid, start, end))
        conn.execute("INSERT INTO fts_chunks (rowid, text) VALUES (?, ?)",
                     (cur.lastrowid, text[start:end]))


def index_occurrence(conn: sqlite3.Connection, occ_id: str) -> None:
    for rowid, block_id, encoding in conn.execute(
        "SELECT rowid, block_id, encoding FROM blocks WHERE occ_id = ?", (occ_id,)
    ).fetchall():
        conn.execute("DELETE FROM fts_blocks WHERE rowid = ?", (rowid,))
        text = _indexable(conn, block_id, encoding)
        conn.execute("INSERT INTO fts_blocks (rowid, text) VALUES (?, ?)", (rowid, text))
        _index_chunks(conn, rowid, text)


def backfill_chunks(conn: sqlite3.Connection) -> None:
    """Migration 5: chunk every archived block (the block index already exists)."""
    for rowid, block_id, encoding in conn.execute(
        "SELECT rowid, block_id, encoding FROM blocks").fetchall():
        _index_chunks(conn, rowid, _indexable(conn, block_id, encoding))


def clear(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM fts_blocks")
    conn.execute("DELETE FROM fts_chunks")
    conn.execute("DELETE FROM chunk_map")


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


@dataclass(frozen=True)
class ChunkHit:
    """One matching chunk: its exact source range and BM25 score (lower is better)."""

    rowid: int
    block_rowid: int
    block_id: str
    block_idx: int
    occ_id: str
    seq: int
    start: int
    end: int
    score: float
    text: str


def search_chunks(conn: sqlite3.Connection, match: str, *,
                  block_rowids: list[int] | None = None, limit: int = 64) -> list[ChunkHit]:
    """Chunks matching an FTS5 ``match`` string, best first. Ties break by the
    newest source occurrence, then block index, start offset and chunk rowid,
    so the order is total. ``block_rowids`` limits the search to those blocks."""
    if not match or block_rowids == []:
        return []
    where = "" if block_rowids is None else (
        " AND m.block_rowid IN (SELECT value FROM json_each(?))")
    params: list = [match]
    if block_rowids is not None:
        params.append(json.dumps(sorted(set(block_rowids))))
    params.append(limit)
    rows = conn.execute(
        "SELECT m.rowid, m.block_rowid, b.block_id, b.idx, b.encoding, o.occ_id, o.seq,"
        " m.start, m.\"end\", bm25(fts_chunks) AS score"
        " FROM fts_chunks f JOIN chunk_map m ON m.rowid = f.rowid"
        " JOIN blocks b ON b.rowid = m.block_rowid JOIN occurrences o ON o.occ_id = b.occ_id"
        f" WHERE fts_chunks MATCH ?{where}"
        " ORDER BY score, o.seq DESC, b.idx, m.start, m.rowid LIMIT ?",
        params,
    ).fetchall()
    hits = []
    for rowid, block_rowid, block_id, idx, encoding, occ_id, seq, start, end, score in rows:
        text = _indexable(conn, block_id, encoding)[start:end]
        hits.append(ChunkHit(rowid, block_rowid, block_id, idx, occ_id, seq, start, end,
                             score, text))
    return hits
