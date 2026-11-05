"""The hidden recall tools: exact recall by address, search and catalog pages (Phase 3B).

Implements ARC's exact addressable recall (docs/papers.md): a masked record stays
reachable by its stable address, page by page, and the bounded catalog lists every
record. Adaptations (plan phase3b §2.5, D57–D59):

- **Results are tool results, never system text.** The proxy answers the model's
  ``palimnesis_*`` calls itself; the client never sees them (D52).
- **Exact by range.** ``palimnesis_recall`` returns code-point ranges of one archived
  block with the block's total length, its SHA-256 and the next offset, so pages
  reassemble exactly. Lone surrogates are shown as U+FFFD, one code point each, so
  offsets hold (D38.1); the hash covers the archived text.
- **Never a near miss.** Addresses resolve through ``palimnesis.archive.addresses`` in the
  session's scope only. Unknown and ambiguous ids return errors with suggestions,
  never another record's content.
- **Search is bounded and literal.** Text mode quotes every term as an FTS5 phrase
  of its unicode61 sub-tokens, joined with AND, so model text is never FTS syntax.
  Regex mode is RE2: linear time, no backreferences or lookaround, a pattern cap, a
  memory cap and a scan cap, cancellation checked between blocks, and no fallback
  to another dialect. RE2 errors are returned to the model, never logged.
- **Scope.** ``hidden`` (the default) searches only blocks the current view no longer
  shows (``recall.candidates``, the excerpt candidate set); ``all`` searches the
  whole branch. System messages, always in view, and recall results, copies of
  archived text, are never searched.
- **Catalog pages are ordinary tool results** (``palimnesis.view.catalog``), so model-facing
  navigation costs no reserved slot and never invalidates the prefix (D20.3).
- **Every result fits** the caller's ``max_tokens`` under the injected counter.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

import re2

from palimnesis.archive import addresses

from palimnesis.view import catalog
from palimnesis.recall.search import _block_text, search_chunks
from palimnesis.view.stubs import chunks, fit_prefix

Count = Callable[[str], int]

RECALL, GREP, CATALOG = "palimnesis_recall", "palimnesis_grep", "palimnesis_catalog"
TOOLS = (RECALL, GREP, CATALOG)

GREP_PAGE = 10
SNIPPET_CHARS = 200
MAX_PATTERN = 512
MAX_SCAN_BYTES = 32 << 20
RE2_MAX_MEM = 8 << 20
GREP_CURSOR = "grep2"  # grep2: reasoning left the search (D66)

_SUBTOKEN = re.compile(r"[^\W_]+")  # unicode61: letters and digits; everything else separates
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Result:
    """One tool result: the text the model reads, and what the archive records."""

    text: str
    ok: bool
    meta: dict = field(default_factory=dict)


@dataclass
class Context:
    """What a tool may read. ``hidden`` is ``recall.candidates`` for the current view:
    {occ_id: block kinds, or None for every block}; ``masked`` flags catalog entries."""

    conn: sqlite3.Connection
    session_id: str
    branch_id: str
    count: Count
    max_tokens: int
    hidden: Mapping[str, frozenset[str] | None] | None = None
    masked: Iterable[str] = ()
    cancelled: Callable[[], bool] = lambda: False


class _Error(Exception):
    def __init__(self, code: str, message: str, **meta: Any) -> None:
        super().__init__(message)
        self.code, self.message, self.meta = code, message, meta


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def _shown(text: str) -> str:
    return "".join("�" if "\ud800" <= ch <= "\udfff" else ch for ch in text)


def run(name: str, arguments: str, ctx: Context) -> Result:
    """Run one hidden tool call. Never raises for model input: every problem is an
    error result the model can read."""
    try:
        if name not in TOOLS:
            raise _Error("unknown_tool", f"there is no tool named {name}; "
                         f"the tools are {', '.join(TOOLS)}")
        args = _arguments(name, arguments)
        result = {RECALL: _recall, GREP: _grep, CATALOG: _catalog}[name](ctx, **args)
    except _Error as e:
        result = Result(f"error ({e.code}): {e.message}", False, {"error": e.code, **e.meta})
    if ctx.count(result.text) > ctx.max_tokens:
        text = fit_prefix(result.text, lambda s: ctx.count(s) <= ctx.max_tokens)
        result = Result(text, result.ok, {**result.meta, "cut": True})
    return result


# --- schemas (D54) -------------------------------------------------------------------

TOOLS_VERSIONS = ("t1", "t2")
_PARAMETERS = {
    RECALL: {"type": "object", "properties": {
        "id": {"type": "string"},
        "offset": {"type": "integer", "minimum": 0},
        "limit": {"type": "integer", "minimum": 1}}, "required": ["id"]},
    CATALOG: {"type": "object", "properties": {
        "cursor": {"type": "string"},
        "page": {"type": "integer", "minimum": 1}}},
    GREP: {"type": "object", "properties": {
        "query": {"type": "string"},
        "mode": {"type": "string", "enum": ["text", "regex"]},
        "scope": {"type": "string", "enum": ["hidden", "all"]},
        "cursor": {"type": "string"}}, "required": ["query", "mode"]},
}


def schemas(version: str) -> list[dict]:
    """The hidden tools as Chat Completions function tools, described by the registered
    affordance ``version`` (t1 or t2): one description line per tool."""
    from palimnesis.view.affordances import REGISTRY

    affordance = REGISTRY[version]
    if affordance.family != "tools":
        raise ValueError(f"{version!r} is not a tools affordance")
    described = {}
    for line in affordance.text.split("\n"):
        signature, _, description = line.partition(": ")
        described[signature.split("(", 1)[0]] = description
    return [{"type": "function", "function": {"name": name, "description": described[name],
                                              "parameters": _PARAMETERS[name]}}
            for name in (RECALL, CATALOG, GREP)]


# --- arguments ---------------------------------------------------------------------

_SCHEMAS: dict[str, dict[str, tuple[type, bool]]] = {
    RECALL: {"id": (str, True), "offset": (int, False), "limit": (int, False)},
    GREP: {"query": (str, True), "mode": (str, False), "scope": (str, False),
           "cursor": (str, False)},
    CATALOG: {"cursor": (str, False), "page": (int, False)},
}
_CHOICES = {"mode": ("text", "regex"), "scope": ("hidden", "all")}


def _arguments(name: str, raw: str) -> dict[str, Any]:
    try:
        args = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, AttributeError):
        raise _Error("invalid_arguments", "arguments must be a JSON object") from None
    if not isinstance(args, dict):
        raise _Error("invalid_arguments", "arguments must be a JSON object")
    schema = _SCHEMAS[name]
    for key, value in args.items():
        if key not in schema:
            raise _Error("invalid_arguments", f"unknown argument {key!r}; "
                         f"{name} takes {', '.join(schema)}")
        kind = schema[key][0]
        if value is None:
            continue
        if not isinstance(value, kind) or isinstance(value, bool):
            raise _Error("invalid_arguments", f"{key} must be a {kind.__name__}")
        if kind is int and value < 0:
            raise _Error("invalid_arguments", f"{key} must not be negative")
        if key in _CHOICES and value not in _CHOICES[key]:
            raise _Error("invalid_arguments", f"{key} must be one of {', '.join(_CHOICES[key])}")
    for key, (_, required) in schema.items():
        if required and args.get(key) is None:
            raise _Error("invalid_arguments", f"{key} is required")
    return {k: v for k, v in args.items() if v is not None}


# --- palimnesis_recall -------------------------------------------------------------


def _resolve(ctx: Context, address: str) -> tuple[str, str, int | None]:
    """(occ_id, alias, block) for an address in this session, or an error."""
    found = addresses.resolve(ctx.conn, ctx.session_id, address.lstrip("§"))
    if isinstance(found, addresses.Ambiguous):
        raise _Error("ambiguous_address", f"{address} matches several records: "
                     + ", ".join("§" + a for a in found.candidates))
    if isinstance(found, addresses.Unknown):
        hint = ("; did you mean " + ", ".join("§" + a for a in found.suggestions) + "?"
                if found.suggestions else "")
        raise _Error("unknown_address", f"no record {address} in this conversation{hint}")
    row = ctx.conn.execute(
        "SELECT a.alias FROM aliases a JOIN occurrences o ON o.occ_id = a.target_id"
        " WHERE a.scope_session_id = ? AND a.target_id = ? AND o.branch_id = ?",
        (ctx.session_id, found.target_id, ctx.branch_id)).fetchone()
    if row is None:
        raise _Error("unknown_address", f"no record {address} in this conversation")
    return found.target_id, row[0], found.block


def _blocks(conn: sqlite3.Connection, occ_id: str) -> list[tuple[int, str, str, str]]:
    return conn.execute("SELECT idx, kind, block_id, encoding FROM blocks WHERE occ_id = ?"
                        " ORDER BY idx", (occ_id,)).fetchall()


def _recall(ctx: Context, id: str, offset: int = 0, limit: int | None = None) -> Result:  # noqa: A002
    occ_id, alias, block = _resolve(ctx, id)
    blocks = _blocks(ctx.conn, occ_id)
    if block is None and len(blocks) == 1:
        block = blocks[0][0]
    if block is None:
        lines = [f"§{alias} has {len(blocks)} blocks; recall one by its address:"]
        for idx, kind, block_id, encoding in blocks:
            text = _block_text(ctx.conn, block_id, encoding)
            lines.append(f"§{alias}.{idx} {kind} · {len(text):,} code points")
        return Result("\n".join(lines), True, {"address": f"§{alias}", "blocks": len(blocks)})
    match = [b for b in blocks if b[0] == block]
    if not match:
        raise _Error("unknown_block", f"§{alias} has no block {block}; its blocks are "
                     + ", ".join(f"§{alias}.{b[0]}" for b in blocks))
    idx, kind, block_id, encoding = match[0]
    exact = _block_text(ctx.conn, block_id, encoding)
    total, sha = len(exact), sha256_of(exact)
    if offset > total:
        raise _Error("offset_out_of_range", f"offset {offset} is past the end ({total})")
    address = f"§{alias}.{idx}"

    def header(start: int, end: int, nxt: int | None) -> str:
        return (f"[{RECALL} {address} {kind} · {start}–{end} of {total} · sha256 {sha[:16]}"
                f" · next_offset {nxt if nxt is not None else 'none'}]\n")

    room = ctx.max_tokens - ctx.count(header(total, total, total))
    stop = total if limit is None else min(total, offset + limit)
    piece = _shown(exact)[offset:stop]
    if room < 1:
        raise _Error("no_room", "no room left for a result in this response")
    if piece:
        try:
            piece = next(chunks(piece, room, count=ctx.count)).text
        except ValueError:
            raise _Error("no_room", "no room left for a result in this response") from None
    end = offset + len(piece)
    nxt = end if end < total else None
    return Result(header(offset, end, nxt) + piece, True,
                  {"address": address, "occ_id": occ_id, "block_id": block_id, "start": offset,
                   "end": end, "total": total, "sha256": sha, "next_offset": nxt})


# --- palimnesis_grep ---------------------------------------------------------------


def _text_match(query: str) -> tuple[str, re.Pattern]:
    """The FTS5 match string, and a pattern that finds the first phrase in a hit chunk
    (to narrow the snippet to its line)."""
    phrases = [subs for word in query.split() if (subs := _SUBTOKEN.findall(word))]
    if not phrases:
        raise _Error("empty_query", "the query has no letters or digits to search for")
    locate = re.compile("|".join(r"(?<![^\W_])" + r"[\W_]+".join(map(re.escape, subs))
                                 + r"(?![^\W_])" for subs in phrases), re.IGNORECASE)
    return " AND ".join('"' + " ".join(subs) + '"' for subs in phrases), locate


def _scope_blocks(ctx: Context, scope: str, cutoff: int) -> list[tuple]:
    """(rowid, block_id, idx, kind, encoding, occ_id, seq, role) of searchable blocks,
    newest first. Reasoning is never searched: the model's own unverified claims would
    come back as evidence (D66)."""
    rows = ctx.conn.execute(
        "SELECT b.rowid, b.block_id, b.idx, b.kind, b.encoding, o.occ_id, o.seq, o.role"
        " FROM blocks b JOIN occurrences o ON o.occ_id = b.occ_id"
        " WHERE o.branch_id = ? AND o.seq <= ? AND o.role != 'system'"
        " AND o.source != 'internal_tool' AND b.kind != 'reasoning'"
        " ORDER BY o.seq DESC, b.idx",
        (ctx.branch_id, cutoff)).fetchall()
    if scope == "all":
        return rows
    hidden = ctx.hidden or {}
    return [r for r in rows if r[5] in hidden and (hidden[r[5]] is None or r[3] in hidden[r[5]])]


def _cursor(ctx: Context, key: str, cutoff: int, skip: int) -> str:
    return f"{GREP_CURSOR}.{catalog.branch_hash(ctx.branch_id)}.{key}.{cutoff}.{skip}"


def _parse_cursor(ctx: Context, cursor: str, key: str) -> tuple[int, int]:
    parts = cursor.split(".")
    if (len(parts) != 5 or parts[0] != GREP_CURSOR or not parts[3].isdigit()
            or not parts[4].isdigit()):
        raise _Error("bad_cursor", "not a cursor from palimnesis_grep")
    if parts[1] != catalog.branch_hash(ctx.branch_id) or parts[2] != key:
        raise _Error("bad_cursor", "this cursor belongs to another search; repeat the search "
                     "without a cursor")
    return int(parts[3]), int(parts[4])


def _line(text: str, i: int) -> int:
    return text.count("\n", 0, i) + 1


def _snippet(text: str, start: int, end: int) -> str:
    a = text.rfind("\n", 0, start) + 1
    b = text.find("\n", end)
    piece = _SPACE.sub(" ", text[a:len(text) if b < 0 else b]).strip()
    return piece if len(piece) <= SNIPPET_CHARS else fit_prefix(
        piece, lambda s: len(s) <= SNIPPET_CHARS - 1) + "…"


def _grep(ctx: Context, query: str, mode: str = "text", scope: str = "hidden",
          cursor: str | None = None) -> Result:
    key = hashlib.sha256(f"{mode}\0{scope}\0{query}".encode("utf-8", "surrogatepass")
                         ).hexdigest()[:12]
    if cursor is not None:
        cutoff, skip = _parse_cursor(ctx, cursor, key)
    else:
        cutoff = ctx.conn.execute("SELECT coalesce(max(seq), 0) FROM occurrences"
                                  " WHERE branch_id = ?", (ctx.branch_id,)).fetchone()[0]
        skip = 0
    rows = _scope_blocks(ctx, scope, cutoff)
    want = skip + GREP_PAGE + 1
    truncated = None
    hits: list[tuple[tuple, str, int, int]] = []  # (block row, shown text, start, end)
    if mode == "text":
        match, locate = _text_match(query)
        by_rowid = {r[0]: r for r in rows}
        texts: dict[int, str] = {}
        for h in search_chunks(ctx.conn, match, block_rowids=list(by_rowid), limit=want):
            row = by_rowid[h.block_rowid]
            if row[0] not in texts:
                texts[row[0]] = _shown(_block_text(ctx.conn, row[1], row[4]))
            found = locate.search(texts[row[0]], h.start, h.end)
            start, end = found.span() if found else (h.start, h.end)
            hits.append((row, texts[row[0]], start, end))
    else:
        if len(query) > MAX_PATTERN:
            raise _Error("pattern_too_long", f"patterns are limited to {MAX_PATTERN} characters")
        options = re2.Options()
        options.log_errors = False  # a rejected pattern is model text: never in the logs
        options.max_mem = RE2_MAX_MEM
        try:
            pattern = re2.compile(query, options)
        except re2.error as e:
            detail = e.args[0].decode("utf-8", "replace") if e.args and isinstance(
                e.args[0], bytes) else str(e)
            raise _Error("regex_unsupported", f"RE2 cannot compile this pattern ({detail}). "
                         "Backreferences and lookaround are not supported; use mode text, "
                         "or a simpler pattern.") from None
        scanned = 0
        for row in rows:
            if ctx.cancelled():
                raise _Error("cancelled", "the search was cancelled")
            text = _shown(_block_text(ctx.conn, row[1], row[4]))
            scanned += len(text.encode("utf-8"))
            if scanned > MAX_SCAN_BYTES:
                truncated = "scan_limit"
                break
            for m in pattern.finditer(text):
                if m.end() > m.start():
                    hits.append((row, text, m.start(), m.end()))
                    if len(hits) >= want:
                        break
            if len(hits) >= want:
                break
    page = hits[skip:skip + GREP_PAGE]
    more = len(hits) > skip + GREP_PAGE
    aliases = dict(ctx.conn.execute(
        "SELECT target_id, alias FROM aliases WHERE scope_session_id = ?"
        " AND target_id IN (SELECT value FROM json_each(?))",
        (ctx.session_id, json.dumps(sorted({r[5] for r, *_ in page})))).fetchall())
    lines, refs = [], []
    for (rowid, block_id, idx, kind, encoding, occ_id, seq, role), text, start, end in page:
        ref = f"§{aliases.get(occ_id, '?')}.{idx}"
        first, last = _line(text, start), _line(text, max(start, end - 1))
        span = f"L{first}" if first == last else f"L{first}-{last}"
        lines.append(f"{ref} seq {seq} {role} {kind} {span}: {_snippet(text, start, end)}")
        refs.append(f"{ref}:{span}")

    def render(n: int) -> tuple[str, str | None]:
        nxt = _cursor(ctx, key, cutoff, skip + n) if (n < len(lines) or more) else None
        head = (f"[{GREP} {mode} {scope} · hits {skip + 1}–{skip + n}"
                + (f" · next cursor {nxt}" if nxt else "") + "]") if n else (
            f"[{GREP} {mode} {scope} · no matches" + (" in what the view hides"
                                                      if scope == "hidden" else "") + "]")
        if truncated:
            head += " (scan limit reached; narrow the pattern)"
        return "\n".join([head, *lines[:n]]), nxt

    n = len(lines)
    text, nxt = render(n)
    while n and ctx.count(text) > ctx.max_tokens:
        n -= 1
        text, nxt = render(n)
    return Result(text, True, {"hits": n, "cursor": nxt, "addresses_lines": refs[:n],
                               "truncated": truncated})


# --- palimnesis_catalog ------------------------------------------------------------


def _catalog(ctx: Context, cursor: str | None = None, page: int | None = None) -> Result:
    try:
        if cursor is not None:
            p = catalog.next(ctx.conn, ctx.branch_id, cursor, count=ctx.count, masked=ctx.masked)
        elif page is not None:
            p = catalog.page(ctx.conn, ctx.branch_id, page, count=ctx.count, masked=ctx.masked)
        else:
            p = catalog.first(ctx.conn, ctx.branch_id, count=ctx.count, masked=ctx.masked)
    except catalog.CatalogError as e:
        raise _Error("bad_cursor" if cursor is not None else "bad_page", str(e)) from None
    if not p.entries:
        raise _Error("bad_page", f"page {p.number} is empty")
    head = f"[{CATALOG} page {p.number}" + (f" · next cursor {p.next}" if p.next else "") + "]"
    return Result("\n".join([head, p.text]), True,
                  {"page": p.number, "cursor": p.next, "entries": len(p.entries)})
