"""Proactive recall: retrieve archived evidence for a new user instruction (A1).

Mechanism from Eunoe (docs/papers.md): before a user message is answered,
BM25 over archived content no longer in context, with the best matches quoted
back verbatim in a block appended to that message. Adaptations:

- **Bounded, literal queries (q1, D28).** The query is built from the user's
  own text by a frozen policy, never passed through as FTS5 syntax. Every term
  is an FTS5 string of tokenizer sub-tokens, so operators, column filters,
  prefixes and quotes in the text are only ever searched as words.
- **Code first.** Identifiers, paths and error codes (runs containing digits,
  ``_``, ``/``, ``::``, internal capitals, a dot between two 2+-character parts,
  or backticks) outrank plain words, then terms keep their first-occurrence
  order. Hyphenated and abbreviated prose (``follow-up``, ``e.g.``) is not
  code. A run that splits becomes a phrase of its sub-tokens, so
  ``parse_config`` matches ``parse config`` adjacently, not either word alone.
- **Bounds.** At most 32 terms; long messages contribute their first 12,000
  and last 4,000 code points. Filler ("continue", "ok", "thanks") yields an
  empty query, recorded as such rather than searched.
- **Only what the view dropped (D26).** Candidates are the blocks the base view
  no longer shows: every block of a collapsed message, and the replaced block
  of a stubbed one (a tool result, or reasoning), older than the instruction.
  Text still verbatim in the view, system messages and excerpt text itself
  (never archived as a block) are never candidates.
- **Retrieval r1 (D29).** BM25 over chunks (D27), a relevance floor (one
  code-like term or two distinct terms in the chunk), ±4 lines of context,
  merged per block, each item capped at ``min(512, allocation − block overhead)`` tokens,
  then packed greedily in rank order (at most 8 items, 2 per source) against
  the exact count of the block as it renders, provenance included, so the
  charge never exceeds the allocation.
  Rank decides survival; the block renders chronologically (A1, D30).
- **No currency judgment.** Each item carries its turn and provenance; a
  high score does not make a statement current.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

QUERY_VERSION = "q1"
RETRIEVAL_VERSION = "r1"
MAX_HITS = 64
CONTEXT_LINES = 4
ITEM_CAP = 512
MIN_ITEM_TOKENS = 32
MAX_ITEMS = 8
MAX_PER_SOURCE = 2
MAX_RENDERS = 16
MAX_TERMS = 32
HEAD_CHARS = 12_000
TAIL_CHARS = 4_000

_RUN = re.compile(r"[\w.\-/:#@]+")
_SUBTOKEN = re.compile(r"[^\W_]+")  # unicode61: letters and digits; everything else separates
_BACKTICKED = re.compile(r"`([^`\n]+)`")
_INTERNAL_CAPITAL = re.compile(r"[a-z][A-Z]")
_DOTTED = re.compile(r"[^\W_]{2,}\.[^\W_]{2,}")

STOPWORDS = frozenset("""
a about above after again against all also am an and any are as at be because been before
being below between both but by can could did do does doing done down during each few for
from further get got had has have having he her here hers herself him himself his how i if
in into is it its itself just let me more most my myself no nor not now of off on once only
or other our ours ourselves out over own same she should so some such than that the their
theirs them themselves then there these they this those through to too under until up very
was we were what when where which while who whom why will with would you your yours
yourself yourselves
please thanks thank ok okay yes yeah sure continue go ahead next again also still now
""".split())


@dataclass(frozen=True)
class Query:
    """A built query: its terms (each a space-joined run of sub-tokens), the FTS5
    MATCH string, and why it is empty when it is."""

    terms: tuple[str, ...]
    match: str
    reason: str | None = None
    code_terms: int = 0  # the first ``code_terms`` terms are code-like


def _bounded(text: str) -> str:
    if len(text) <= HEAD_CHARS + TAIL_CHARS:
        return text
    return text[:HEAD_CHARS] + "\n" + text[-TAIL_CHARS:]


def _keep(subtokens: list[str]) -> bool:
    if len(subtokens) > 1:
        return any(len(s) > 1 for s in subtokens)  # "e.g." is not a term
    word = subtokens[0]
    if len(word) < 2:
        return False
    return word not in STOPWORDS


QUERY_POLICIES = ("q1", "q2")
Q2_BORROW = 8


def build_query(text: str, previous: str | None = None, version: str = QUERY_VERSION) -> Query:
    """The query for one user instruction (pure, deterministic).

    ``q2`` (a development variant) borrows up to ``Q2_BORROW`` terms from the
    ``previous`` instruction when this one yields fewer than 2 ("now do the same
    for it"); otherwise it equals ``q1``."""
    if version not in QUERY_POLICIES:
        raise ValueError(f"unknown query policy {version!r}")
    q = _build_query(text)
    if version == "q1" or len(q.terms) >= 2 or not previous:
        return q
    p = _build_query(previous)
    borrowed = [t for t in p.terms if t not in q.terms][:Q2_BORROW]
    if not borrowed:
        return q
    code = [t for t in q.terms[:q.code_terms]] + [t for t in p.terms[:p.code_terms] if t in borrowed]
    plain = [t for t in q.terms[q.code_terms:]] + [t for t in borrowed if t not in code]
    terms = tuple((code + plain)[:MAX_TERMS])
    match = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
    return Query(terms=terms, match=match, code_terms=min(len(code), len(terms)))


def _build_query(text: str) -> Query:
    text = _bounded(text)
    backticked = {m.lower() for span in _BACKTICKED.findall(text) for m in _RUN.findall(span)}
    code: list[str] = []
    plain: list[str] = []
    seen: set[str] = set()
    for run in _RUN.findall(text):
        subtokens = [s.lower() for s in _SUBTOKEN.findall(run)]
        if not subtokens or not _keep(subtokens):
            continue
        term = " ".join(subtokens)
        if term in seen:
            continue
        seen.add(term)
        is_code = (any(ch.isdigit() for ch in run) or "_" in run or "/" in run
                   or "::" in run or bool(_INTERNAL_CAPITAL.search(run))
                   or bool(_DOTTED.search(run)) or run.lower() in backticked)
        (code if is_code else plain).append(term)
    terms = tuple((code + plain)[:MAX_TERMS])
    if not terms:
        return Query(terms=(), match="", reason="empty_query")
    match = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
    return Query(terms=terms, match=match, code_terms=min(len(code), len(terms)))


def passes_floor(query: Query, text: str) -> bool:
    """The r1 relevance floor: ``text`` holds a code-like term, or two distinct terms
    (a term matches as a contiguous run of sub-tokens, as FTS5 phrases do)."""
    matched = _matched_terms(query, text)
    return any(i < query.code_terms for i in matched) or len(matched) >= 2


def _matched_terms(query: Query, text: str) -> list[int]:
    words = [w.lower() for w in _SUBTOKEN.findall(text)]
    joined = " " + " ".join(words) + " "
    return [i for i, t in enumerate(query.terms) if " " + t + " " in joined]


def _focus(query: Query, text: str, start: int, end: int, cap: int, count) -> tuple[int, int]:
    """The part of a hit chunk to centre an item on: its first to last matching
    line, or, when that exceeds ``cap``, the single best line (most code-like
    terms, then most terms, then earliest)."""
    lines: list[tuple[int, int, list[int]]] = []
    pos = start
    while pos < end:
        nl = text.find("\n", pos, end)
        stop = end if nl < 0 else nl + 1
        terms = _matched_terms(query, text[pos:stop])
        if terms:
            lines.append((pos, stop, terms))
        pos = stop
    if not lines:
        return start, end
    s, e = lines[0][0], lines[-1][1]
    if count(text[s:e]) <= cap:
        return s, e
    best = max(lines, key=lambda ln: (sum(1 for i in ln[2] if i < query.code_terms),
                                      len(ln[2]), -ln[0]))
    return best[0], best[1]


# -- candidates ------------------------------------------------------------------

_STUB_KINDS = {"tool": frozenset({"tool_result"}), "assistant": frozenset({"reasoning"})}


def candidates(items, manifest, host_seq: int) -> dict[str, frozenset[str] | None]:
    """Occurrences the base view no longer shows, with the block kinds it dropped
    (None: every block). Older than the host instruction; never system (D26)."""
    forms = dict(manifest)
    out: dict[str, frozenset[str] | None] = {}
    for item in items:
        if item.occ_id is None or item.seq is None or item.seq >= host_seq:
            continue
        role = item.message.get("role")
        form = forms.get(item.occ_id)
        if role == "system" or form not in ("collapsed", "stub"):
            continue
        out[item.occ_id] = None if form == "collapsed" else _STUB_KINDS.get(role, frozenset())
    return out


# -- ranges ----------------------------------------------------------------------

def _line_start(text: str, i: int) -> int:
    return text.rfind("\n", 0, i) + 1


def _expand(text: str, start: int, end: int, lines: int) -> tuple[int, int]:
    s = _line_start(text, start)
    for _ in range(lines):
        if s == 0:
            break
        s = _line_start(text, s - 1)
    e = text.find("\n", max(end - 1, start))
    e = len(text) if e < 0 else e
    for _ in range(lines):
        if e >= len(text):
            break
        nxt = text.find("\n", e + 1)
        e = len(text) if nxt < 0 else nxt
    return s, e


def _fit(text: str, hit: tuple[int, int], span: tuple[int, int], cap: int, count) -> tuple[int, int]:
    """The widest range around ``hit`` within ``span`` whose text fits ``cap``
    tokens, grown a line at a time alternately after and before the hit."""
    from .stubs import fit_prefix

    hs, he = hit
    if count(text[hs:he]) > cap:  # the hit chunk alone is too big: keep its head
        cut = fit_prefix(text[hs:he], lambda t: count(t) <= cap)
        return hs, hs + len(cut)
    s, e = hs, he
    grow_after = True
    while True:
        moved = False
        for side in ((True, False) if grow_after else (False, True)):
            if side and e < span[1]:
                nxt = text.find("\n", e + 1)
                ne = span[1] if nxt < 0 or nxt > span[1] else nxt
                if count(text[s:ne]) <= cap:
                    e, moved = ne, True
            elif not side and s > span[0]:
                ns = max(span[0], _line_start(text, s - 1))
                if count(text[ns:e]) <= cap:
                    s, moved = ns, True
        if not moved:
            return s, e
        grow_after = not grow_after


@dataclass
class _Candidate:
    rank: int
    score: float
    occ_id: str
    seq: int
    block_idx: int
    kind: str
    text: str  # the block's text with lone surrogates as U+FFFD (same offsets)
    exact: str  # the block's exact archived text
    hit: tuple[int, int]
    span: tuple[int, int]


def _quotable(text: str) -> str:
    """Lone surrogates (valid in JSON, archived exactly as WTF-8) become U+FFFD, one
    code point each, so offsets hold and the rendering can be stored and sent."""
    return "".join("\ufffd" if "\ud800" <= ch <= "\udfff" else ch for ch in text) \
        if any("\ud800" <= ch <= "\udfff" for ch in text) else text


class FtsExcerpts:
    """The Phase 3 excerpt source: q1 queries, r1 retrieval over the archive."""

    retrieval_version = RETRIEVAL_VERSION

    def __init__(self, store, counter, *, query_policy: str = QUERY_VERSION,
                 renderer: str = "x2"):
        if query_policy not in QUERY_POLICIES:
            raise ValueError(f"unknown query policy {query_policy!r}")
        self.store = store
        self.counter = counter
        self.query_version = query_policy
        self.renderer = renderer

    async def select(self, plan, base_view, allocation: int):
        from .excerpts import Selection

        host = next((i for i in plan.items if i.occ_id == plan.host_occ_id), None)
        cutoff = (host.seq or 1) - 1 if host is not None else 0

        def empty(reason: str, query: str = "") -> Selection:
            return Selection(query=query, query_version=self.query_version,
                             retrieval_version=self.retrieval_version,
                             archive_cutoff_seq=cutoff, items=(), reason=reason)

        if host is None or host.seq is None:
            return empty("no_host")
        found = candidates(plan.items, base_view.manifest, host.seq)
        if not found:
            return empty("nothing_absent")
        previous = next((_message_text(i.message) for i in reversed(plan.items)
                         if i.seq is not None and i.seq < host.seq
                         and i.message.get("role") == "user"), None)
        query = build_query(_message_text(host.message), previous, self.query_version)
        if not query.match:
            return empty("empty_query")
        cap = min(ITEM_CAP, allocation - self._overhead())
        if cap < MIN_ITEM_TOKENS:
            return empty("zero_allocation", query.match)
        ranked, reason = await self.store.read(
            lambda conn: self._rank(conn, query, found, base_view.included_excerpts, cap))
        if not ranked:
            return empty(reason, query.match)
        prov = _Provenance(plan.items)
        current_turn = prov.numbers.get(host.seq, 0)
        chosen = self._pack(ranked, allocation, prov, current_turn)
        if not chosen:
            return empty("no_fit", query.match)
        return Selection(query=query.match, query_version=self.query_version,
                         retrieval_version=self.retrieval_version, archive_cutoff_seq=cutoff,
                         items=self._items(chosen, prov))

    def _overhead(self) -> int:
        """Tokens a one-item block costs beyond its payload: block header, item
        header with the longest provenance, footer."""
        from .excerpts import Excerpt, render_block

        empty = render_block([Excerpt("x", 0, 0, "assistant", None, "")],
                             added_tokens=self.counter.added_token_strings,
                             renderer=self.renderer, current_turn=99_999)
        return self.counter.count(empty) + _HEADER_SLACK

    # -- retrieval (reader thread) ------------------------------------------------

    def _rank(self, conn, query: Query, found, included, cap: int):
        from . import search

        rows = conn.execute(
            "SELECT b.rowid, b.block_id, b.idx, b.kind, b.encoding, o.occ_id, o.seq"
            " FROM blocks b JOIN occurrences o ON o.occ_id = b.occ_id"
            " WHERE b.occ_id IN (SELECT value FROM json_each(?))",
            (json.dumps(sorted(found)),)).fetchall()
        blocks = {r[0]: r for r in rows if found[r[5]] is None or r[3] in found[r[5]]}
        hits = search.search_chunks(conn, query.match, block_rowids=list(blocks), limit=MAX_HITS)
        if not hits:
            return [], "no_match"
        taken = _included_ranges(conn, included)
        texts: dict[int, str] = {}
        merged: list[_Candidate] = []
        for rank, hit in enumerate(hits):
            if not passes_floor(query, hit.text):
                continue
            rowid, block_id, idx, kind, encoding, occ_id, seq = blocks[hit.block_rowid]
            if rowid not in texts:
                exact = search._block_text(conn, block_id, encoding)
                texts[rowid] = (_quotable(exact), exact)
            text, exact = texts[rowid]
            span = _expand(text, hit.start, hit.end, CONTEXT_LINES)
            if any(o == occ_id and b == idx and span[0] < e and s < span[1]
                   for o, b, s, e in taken):
                continue  # D26: never re-quote what an included block already shows
            same = next((c for c in merged if c.occ_id == occ_id and c.block_idx == idx
                         and span[0] <= c.span[1] and c.span[0] <= span[1]), None)
            if same is not None:  # overlapping or touching: one range, best rank kept
                same.span = (min(same.span[0], span[0]), max(same.span[1], span[1]))
                continue
            merged.append(_Candidate(rank, hit.score, occ_id, seq, idx, kind, text, exact,
                                     (hit.start, hit.end), span))
        if not merged:
            return [], "below_floor"
        count = self.counter.count
        for c in merged:
            if count(c.text[c.span[0]:c.span[1]]) > cap:
                c.hit = _focus(query, c.text, c.hit[0], c.hit[1], cap, count)
                c.span = _fit(c.text, c.hit, c.span, cap, count)
        return merged, None

    def _pack(self, ranked: list[_Candidate], allocation: int, prov,
              current_turn: int = 0) -> list[_Candidate]:
        """Greedy in rank order against the exact count of the block as it will render,
        provenance included. An item that overshoots is shrunk once by the measured
        excess (it keeps at least ``MIN_ITEM_TOKENS``), else skipped; at most
        ``MAX_RENDERS`` renders."""
        from .excerpts import render_block

        count = self.counter.count
        chosen: list[_Candidate] = []
        renders = 0

        def over(trial: list[_Candidate]) -> int:
            nonlocal renders
            renders += 1
            ordered = sorted(trial, key=lambda x: (x.seq, x.block_idx, x.span[0]))
            rendered = render_block([prov.excerpt(x) for x in ordered],
                                    added_tokens=self.counter.added_token_strings,
                                    renderer=self.renderer, current_turn=current_turn)
            return count(rendered) - allocation

        for c in ranked:
            if len(chosen) >= MAX_ITEMS or renders >= MAX_RENDERS:
                break
            if sum(1 for x in chosen if x.occ_id == c.occ_id) >= MAX_PER_SOURCE:
                continue
            excess = over(chosen + [c])
            if excess > 0 and renders < MAX_RENDERS:
                size = count(c.text[c.span[0]:c.span[1]])
                if size - excess - 2 >= MIN_ITEM_TOKENS:
                    c.span = _fit(c.text, c.hit, c.span, size - excess - 2, count)
                    excess = over(chosen + [c])
            if excess <= 0:
                chosen.append(c)
        return chosen

    def _items(self, chosen: list[_Candidate], prov):
        from .excerpts import SelectedExcerpt

        out = []
        for c in sorted(chosen, key=lambda x: x.rank):
            alias, turn, role, tool = prov.of(c)
            exact = c.exact[c.span[0]:c.span[1]]
            out.append(SelectedExcerpt(
                rank=c.rank, score=c.score, source_occ_id=c.occ_id, source_alias=alias,
                source_block=c.block_idx, start=c.span[0], end=c.span[1],
                source_sha256=hashlib.sha256(exact.encode("utf-8", "surrogatepass")).hexdigest(),
                turn_number=turn, role=role, tool_name=tool, text=c.text[c.span[0]:c.span[1]],
                source_seq=c.seq))
        return tuple(out)


class _Provenance:
    """Alias, turn, role and tool name of each candidate's source, from the plan."""

    def __init__(self, items):
        from .turns import turn_numbers

        self.by_occ = {i.occ_id: i for i in items if i.occ_id}
        self.numbers = turn_numbers(
            [(i.seq, i.message.get("role", "")) for i in items if i.seq is not None],
            {i.seq: _message_text(i.message) for i in items
             if i.seq is not None and i.message.get("role") == "user"})
        self.tools = {tc.get("id"): (tc.get("function") or {}).get("name")
                      for i in items for tc in (i.message.get("tool_calls") or [])}

    def of(self, c: _Candidate) -> tuple[str | None, int, str, str | None]:
        item = self.by_occ[c.occ_id]
        role = "reasoning" if c.kind == "reasoning" else item.message.get("role", "")
        tool = (self.tools.get(item.message.get("tool_call_id"))
                if item.message.get("role") == "tool" else None)
        return item.alias, self.numbers.get(c.seq, 0), role, tool

    def excerpt(self, c: _Candidate):
        from .excerpts import Excerpt

        alias, turn, role, tool = self.of(c)
        return Excerpt(alias or "", c.block_idx, turn, role, tool, c.text[c.span[0]:c.span[1]])


# Room per item for provenance when sizing the item cap before packing: alias, turn
# digits, role and a tool name of up to 64 safe characters (``excerpts._header_field``).
# Packing itself counts the real rendering.
_HEADER_SLACK = 40


def _included_ranges(conn, block_ids) -> list[tuple[str, int, int, int]]:
    if not block_ids:
        return []
    return conn.execute(
        "SELECT source_occ_id, source_block, start, \"end\" FROM excerpt_items"
        " WHERE block_id IN (SELECT value FROM json_each(?))",
        (json.dumps(sorted(block_ids)),)).fetchall()


def _message_text(message) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content
                         if isinstance(p, dict) and p.get("type") == "text")
    return ""
