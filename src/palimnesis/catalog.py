"""Bounded, paged catalog of every occurrence on a branch.

Implements ARC's paged catalog (docs/papers.md): the model can reach every
archived item through pages of bounded size, ``first``/``next`` cursors and
direct ``page(k)``, so N items need ⌈N/p⌉ pages. Adaptations (D14.7): pages
hold p = 20 entries of at most c = 48 tokens each under an injected
``count``, not characters; entries cover every occurrence, including masked,
superseded and internal ones, flagged as such.

Each entry is one line: ``§alias seq role kind tokens flags preview``.

- ``kind`` is the occurrence's block kinds in order, joined with ``+``.
- ``tokens`` is the sum of ``count`` over its blocks.
- ``flags`` is a comma list of ``masked`` (passed in by the caller, since
  the view owns masking), ``superseded`` (a ``partial_superseded`` event, or
  a later context version that replaced it) and ``internal``
  (``occurrences.view``), or ``-`` when none apply.
- ``preview`` is whitespace-collapsed content of at most 48 code points, cut
  on a safe boundary (``palimnesis.stubs``) and shortened until the line fits c.

Cursors are ``cat1.<branch-hash>.<seq>.<p>``: the exclusive lower seq bound
of a page, scoped to one branch and page size. A page reads at most p+1
occurrence rows through ``UNIQUE(branch_id, seq)``; the extra row only says
whether a next page exists. Seqs on a branch are dense from 1 (insert-only,
``ledger._next_seq``), so page k starts after seq (k−1)·p, and a cursor must
name such a boundary. A malformed, foreign or out-of-range cursor raises
``CatalogError``; it never yields another branch's rows.

Known cost: superseded flags read ``events`` without an index (one scan per
page). An index belongs with migration 3.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Callable, Iterable

from .stubs import fit_prefix

CURSOR_VERSION = "cat1"
PAGE_SIZE = 20
ENTRY_TOKENS = 48
PREVIEW_CHARS = 48

Count = Callable[[str], int]

_PREVIEW_ORDER = ("text", "tool_result", "tool_call", "reasoning")


class CatalogError(Exception):
    """A catalog request that cannot be served: bad cursor, page or branch."""


@dataclass(frozen=True)
class Entry:
    occ_id: str
    alias: str
    seq: int
    role: str
    kind: str
    tokens: int
    flags: tuple[str, ...]
    preview: str
    text: str


@dataclass(frozen=True)
class Page:
    number: int
    cursor: str
    entries: tuple[Entry, ...]
    next: str | None

    @property
    def text(self) -> str:
        return "\n".join(e.text for e in self.entries)


def branch_hash(branch_id: str) -> str:
    return hashlib.sha256(branch_id.encode("utf-8")).hexdigest()[:16]


def _cursor(branch_id: str, bound: int, page_size: int) -> str:
    return f"{CURSOR_VERSION}.{branch_hash(branch_id)}.{bound}.{page_size}"


def _parse_cursor(branch_id: str, cursor: str, page_size: int) -> int:
    parts = cursor.split(".") if isinstance(cursor, str) else []
    if len(parts) != 4 or parts[0] != CURSOR_VERSION:
        raise CatalogError(f"not a catalog cursor: {cursor!r}")
    _, scope, bound, size = parts
    if not re.fullmatch(r"[0-9a-f]{16}", scope) or not bound.isdigit() or not size.isdigit():
        raise CatalogError(f"malformed catalog cursor: {cursor!r}")
    if scope != branch_hash(branch_id):
        raise CatalogError("this cursor belongs to another branch")
    if int(size) != page_size:
        raise CatalogError(f"this cursor was issued for pages of {int(size)}, not {page_size}")
    if int(bound) % page_size:
        raise CatalogError("this cursor does not start a page")
    return int(bound)


def _require_branch(conn: sqlite3.Connection, branch_id: str) -> None:
    if conn.execute("SELECT 1 FROM branches WHERE branch_id = ?", (branch_id,)).fetchone() is None:
        raise CatalogError(f"unknown branch {branch_id!r}")


def _decode(data: bytes | None, encoding: str) -> str:
    if data is None:
        return ""
    return data.decode("utf-8", "surrogatepass" if encoding == "wtf-8" else "strict")


def _blocks(conn: sqlite3.Connection, occ_ids: list[str]) -> dict[str, list[tuple[str, dict, str]]]:
    out: dict[str, list[tuple[str, dict, str]]] = {o: [] for o in occ_ids}
    if not occ_ids:
        return out
    marks = ",".join("?" * len(occ_ids))
    current: dict[str, tuple[str, str, dict, list[str]]] = {}
    for block_id, occ_id, kind, encoding, meta, data in conn.execute(
        "SELECT b.block_id, b.occ_id, b.kind, b.encoding, b.meta, s.bytes FROM blocks b"
        " LEFT JOIN segments s ON s.block_id = b.block_id"
        f" WHERE b.occ_id IN ({marks}) ORDER BY b.occ_id, b.idx, s.seq",
        occ_ids,
    ):
        if block_id not in current:
            current[block_id] = (occ_id, kind, json.loads(meta), [])
        current[block_id][3].append(_decode(data, encoding))
    for occ_id, kind, meta, texts in current.values():  # dict keeps query order
        out[occ_id].append((kind, meta, "".join(texts)))
    return out


def _superseded(conn: sqlite3.Connection, occ_ids: list[str]) -> set[str]:
    if not occ_ids:
        return set()
    marks = ",".join("?" * len(occ_ids))
    return {
        occ_id
        for (occ_id,) in conn.execute(
            "SELECT CASE kind WHEN 'partial_superseded' THEN json_extract(payload, '$.occ_id')"
            " ELSE json_extract(payload, '$.supersedes') END AS target FROM events"
            " WHERE kind IN ('partial_superseded', 'context_version')"
            f" AND target IN ({marks})",
            occ_ids,
        )
    }


def _collapse(text: str, limit: int) -> str:
    """Whitespace runs as single spaces, stopping once ``limit`` chars are reached."""
    words: list[str] = []
    size = 0
    for match in re.finditer(r"\S+", text):
        words.append(match.group())
        size += len(match.group()) + 1
        if size > limit:
            break
    return " ".join(words)


def _preview_source(blocks: list[tuple[str, dict, str]]) -> str:
    for wanted in _PREVIEW_ORDER:
        parts = [
            f"{meta.get('name', '')}({content})" if kind == "tool_call" else content
            for kind, meta, content in blocks
            if kind == wanted
        ]
        if any(parts):
            return " ".join(parts)
    return ""


def _entry(row, blocks, flags: tuple[str, ...], count: Count, entry_tokens: int) -> Entry:
    occ_id, seq, role, alias = row
    kinds: list[str] = []
    for kind, _, _ in blocks:
        if kind not in kinds:
            kinds.append(kind)
    kind = "+".join(kinds) or "empty"
    tokens = sum(count(content) for _, _, content in blocks)
    head = f"§{alias or '?'} {seq} {role} {kind} {tokens} {','.join(flags) or '-'}"
    collapsed = _collapse(_preview_source(blocks), PREVIEW_CHARS)
    preview = fit_prefix(collapsed[:PREVIEW_CHARS + 1], lambda s: len(s) <= PREVIEW_CHARS)
    preview = fit_prefix(preview, lambda s: count(f"{head} {s}".rstrip()) <= entry_tokens)
    preview = preview.rstrip()
    if count(head) > entry_tokens:
        raise CatalogError(f"entry metadata for seq {seq} exceeds {entry_tokens} tokens")
    text = f"{head} {preview}" if preview else head
    return Entry(occ_id, alias or "", seq, role, kind, tokens, flags, preview, text)


def _page(conn: sqlite3.Connection, branch_id: str, bound: int, *, count: Count,
          masked: Iterable[str], page_size: int, entry_tokens: int) -> Page:
    rows = conn.execute(
        "SELECT o.occ_id, o.seq, o.role, a.alias, o.view FROM occurrences o"
        " LEFT JOIN aliases a ON a.target_id = o.occ_id"
        " WHERE o.branch_id = ? AND o.seq > ? ORDER BY o.seq LIMIT ?",
        (branch_id, bound, page_size + 1),
    ).fetchall()
    if bound and not rows:
        raise CatalogError("this cursor or page is past the end of the branch")
    if rows and rows[0][1] != bound + 1:
        raise CatalogError(f"branch {branch_id!r} has a seq gap after {bound}")
    more = len(rows) > page_size
    rows = rows[:page_size]
    occ_ids = [r[0] for r in rows]
    blocks = _blocks(conn, occ_ids)
    superseded = _superseded(conn, occ_ids)
    masked = set(masked)
    entries = []
    for occ_id, seq, role, alias, view in rows:
        flags = tuple(name for name, on in (("masked", occ_id in masked),
                                            ("superseded", occ_id in superseded),
                                            ("internal", view == "internal")) if on)
        entries.append(_entry((occ_id, seq, role, alias), blocks[occ_id], flags, count,
                              entry_tokens))
    last = rows[-1][1] if rows else bound
    return Page(bound // page_size + 1, _cursor(branch_id, bound, page_size), tuple(entries),
                _cursor(branch_id, last, page_size) if more else None)


def first(conn: sqlite3.Connection, branch_id: str, *, count: Count,
          masked: Iterable[str] = (), page_size: int = PAGE_SIZE,
          entry_tokens: int = ENTRY_TOKENS) -> Page:
    """Page 1 of the branch's catalog (empty for a branch with no occurrences)."""
    _require_branch(conn, branch_id)
    return _page(conn, branch_id, 0, count=count, masked=masked, page_size=page_size,
                 entry_tokens=entry_tokens)


def next(conn: sqlite3.Connection, branch_id: str, cursor: str, *, count: Count,  # noqa: A001
         masked: Iterable[str] = (), page_size: int = PAGE_SIZE,
         entry_tokens: int = ENTRY_TOKENS) -> Page:
    """The page a cursor names (a page's ``next``, or its own ``cursor``)."""
    _require_branch(conn, branch_id)
    bound = _parse_cursor(branch_id, cursor, page_size)
    return _page(conn, branch_id, bound, count=count, masked=masked, page_size=page_size,
                 entry_tokens=entry_tokens)


def page(conn: sqlite3.Connection, branch_id: str, k: int, *, count: Count,
         masked: Iterable[str] = (), page_size: int = PAGE_SIZE,
         entry_tokens: int = ENTRY_TOKENS) -> Page:
    """Page ``k`` (1-based) directly; out-of-range pages raise ``CatalogError``."""
    _require_branch(conn, branch_id)
    if not isinstance(k, int) or k < 1:
        raise CatalogError(f"page numbers start at 1, got {k!r}")
    return _page(conn, branch_id, (k - 1) * page_size, count=count, masked=masked,
                 page_size=page_size, entry_tokens=entry_tokens)
