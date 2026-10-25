"""palimnesis.catalog: bounded keyset pages over every occurrence of a branch (slice 8, GL4)."""

from __future__ import annotations

import asyncio
import json
import math
import sqlite3

import pytest

from palimnesis import addresses, catalog, ledger
from palimnesis.chat import parse
from palimnesis.fingerprint import fingerprint_v1
from palimnesis.store import Store

P, C = catalog.PAGE_SIZE, catalog.ENTRY_TOKENS


def byte_tokens(text: str) -> int:
    return len(text.encode("utf-8", "surrogatepass")) // 4


def word_tokens(text: str) -> int:
    return len(text.split())


def char_tokens(text: str) -> int:
    return len(text)


def _accept(store: Store, session: str, contents: list[str]):
    """Send one request whose messages are user turns with these contents."""
    req = parse(json.dumps({"model": "m", "stream": True, "messages": [
        {"role": "user", "content": c} for c in contents]}).encode())
    fp = fingerprint_v1(ledger.ENDPOINT_CHAT, session, ledger.branch_id_for(session),
                        json.loads(req.raw))
    return asyncio.run(store.write(lambda c: ledger.accept(
        c, session_id=session, association="path", req=req, fingerprint=fp,
        retry_hint=None, live=set())))


def _build(path, sessions: dict[str, list[str]]) -> None:
    store = Store.open(path)
    try:
        for session, contents in sessions.items():
            if contents:
                _accept(store, session, contents)
            else:
                asyncio.run(store.write(lambda c: ledger.ensure_session(c, session, "path")))
    finally:
        store.close()


def _connect(path) -> sqlite3.Connection:
    return sqlite3.connect(path, isolation_level=None)


def _walk(conn, branch_id, count=word_tokens, **kw) -> list[catalog.Page]:
    pages = [catalog.first(conn, branch_id, count=count, **kw)]
    while pages[-1].next is not None:
        pages.append(catalog.next(conn, branch_id, pages[-1].next, count=count, **kw))
    return pages


BRANCH = ledger.branch_id_for("s1")


@pytest.fixture(scope="module")
def thousand(tmp_path_factory):
    path = tmp_path_factory.mktemp("catalog") / "archive.db"
    _build(path, {"s1": [f"message {i}" for i in range(1, 1001)], "s2": ["other branch"]})
    return path


@pytest.mark.parametrize("n", [0, 1, 20, 21, 1000])
def test_catalog_first_next_covers_every_occurrence(tmp_path, thousand, n):
    path = thousand if n == 1000 else tmp_path / "archive.db"
    if n != 1000:
        _build(path, {"s1": [f"message {i}" for i in range(1, n + 1)]})
    conn = _connect(path)

    pages = _walk(conn, BRANCH)

    assert len(pages) == max(1, math.ceil(n / P))
    assert [p.number for p in pages] == list(range(1, len(pages) + 1))
    assert all(len(p.entries) <= P for p in pages)
    entries = [e for p in pages for e in p.entries]
    assert [e.seq for e in entries] == list(range(1, n + 1))
    assert [e.preview for e in entries] == [f"message {i}" for i in range(1, n + 1)]
    for e in entries:
        assert addresses.resolve(conn, "s1", e.alias) == addresses.Hit(e.occ_id)
        assert e.text == f"§{e.alias} {e.seq} user text 2 - message {e.seq}"


def test_catalog_page_k_direct(tmp_path):
    path = tmp_path / "archive.db"
    _build(path, {"s1": [f"message {i}" for i in range(1, 46)]})
    conn = _connect(path)

    third = catalog.page(conn, BRANCH, 3, count=word_tokens)
    walked = _walk(conn, BRANCH)

    assert third.number == 3 and third.next is None
    assert [e.seq for e in third.entries] == [41, 42, 43, 44, 45]
    assert catalog.page(conn, BRANCH, 2, count=word_tokens) == walked[1]
    assert catalog.page(conn, BRANCH, 1, count=word_tokens) == walked[0]
    for bad in (0, -1, 4, 10**9):
        with pytest.raises(catalog.CatalogError):
            catalog.page(conn, BRANCH, bad, count=word_tokens)


ADVERSARIAL = [
    "\U0001F600" * 2000,                      # 4-byte code points
    "x" * 5000,                               # one enormous word
    "a " * 3000,                              # many tiny words
    "\n\n\t  " * 500 + "late text",           # leading whitespace only
    "e\u0301" * 1000,                         # combining marks
    "\U0001F468\u200d\U0001F469\u200d\U0001F467" * 300,
    "\ud83d" * 50 + "lone surrogates",
]


@pytest.mark.parametrize("counter", [byte_tokens, char_tokens, word_tokens])
def test_catalog_page_token_bound_adversarial_previews(tmp_path, counter):
    path = tmp_path / "archive.db"
    contents = (ADVERSARIAL * 4)[:P + 3]
    _build(path, {"s1": contents})
    conn = _connect(path)

    pages = _walk(conn, BRANCH, count=counter)

    for page in pages:
        assert sum(counter(e.text) for e in page.entries) <= P * C
        for e in page.entries:
            assert counter(e.text) <= C
            assert len(e.preview) <= catalog.PREVIEW_CHARS
            assert "\n" not in e.text and "\ufffd" not in e.text
            assert contents[e.seq - 1].split() == [] or " ".join(
                contents[e.seq - 1].split()).startswith(e.preview)
    if counter is word_tokens:  # additive over newline joins
        assert all(counter(p.text) <= P * C for p in pages)


def test_catalog_cursor_uses_index_rows_le_p_plus_1(thousand):
    conn = _connect(thousand)
    statements: list[str] = []
    conn.set_trace_callback(statements.append)

    first = catalog.first(conn, BRANCH, count=word_tokens)
    catalog.next(conn, BRANCH, first.next, count=word_tokens)
    catalog.page(conn, BRANCH, 37, count=word_tokens)
    conn.set_trace_callback(None)

    on_occurrences = [s for s in statements if "occurrences" in s]
    assert on_occurrences
    for sql in on_occurrences:
        plan = " | ".join(row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + sql))
        assert "SCAN o" not in plan and "SCAN occurrences" not in plan, plan
        assert "(branch_id=? AND seq>?)" in plan, plan
        assert f"LIMIT {P + 1}" in sql, sql


def test_catalog_cursor_stable_after_appends(tmp_path):
    path = tmp_path / "archive.db"
    contents = [f"message {i}" for i in range(1, 26)]
    _build(path, {"s1": contents})
    conn = _connect(path)
    first = catalog.first(conn, BRANCH, count=word_tokens)
    second = catalog.next(conn, BRANCH, first.next, count=word_tokens)
    assert second.next is None and len(second.entries) == 5
    conn.close()

    store = Store.open(path)
    try:
        _accept(store, "s1", contents + ["message 26", "message 27", "message 28"])
    finally:
        store.close()
    conn = _connect(path)

    again = catalog.next(conn, BRANCH, first.next, count=word_tokens)
    assert catalog.first(conn, BRANCH, count=word_tokens) == first
    assert again.cursor == second.cursor
    assert again.entries[:5] == second.entries
    assert [e.seq for e in again.entries] == list(range(21, 29))


def test_bad_cursor_error_no_substitution(thousand):
    conn = _connect(thousand)
    mine = catalog.first(conn, BRANCH, count=word_tokens).next
    other_branch = ledger.branch_id_for("s2")
    _, branch_hash, seq, p = mine.split(".")

    bad = [
        "", "garbage", "cat1", "cat2." + mine[5:], mine + ".1",
        f"cat1.{branch_hash}.x.{p}", f"cat1.{branch_hash}.-20.{p}",
        f"cat1.{branch_hash}.{seq}.10",     # issued for another page size
        f"cat1.{branch_hash}.7.{p}",        # not on a page boundary
        f"cat1.{branch_hash}.2000.{p}",     # past the end
        f"cat1.{branch_hash}.1000.{p}",     # the end itself: no next page there
        f"cat1.{'0' * len(branch_hash)}.{seq}.{p}",
    ]
    for cursor in bad:
        with pytest.raises(catalog.CatalogError):
            catalog.next(conn, BRANCH, cursor, count=word_tokens)
    with pytest.raises(catalog.CatalogError, match="another branch"):
        catalog.next(conn, other_branch, mine, count=word_tokens)
    with pytest.raises(catalog.CatalogError):
        catalog.first(conn, "nope/main", count=word_tokens)


def test_catalog_flags_masked_superseded_internal(tmp_path):
    path = tmp_path / "archive.db"
    _build(path, {"s1": ["one", "two", "three"]})
    conn = _connect(path)
    occ = {e.seq: e.occ_id for e in catalog.first(conn, BRANCH, count=word_tokens).entries}
    # Fixture rows the Phase 3 internal-tool path and a superseding request would write.
    conn.execute("BEGIN")
    conn.execute(
        "INSERT INTO occurrences VALUES ('occ_internal', ?, 4, NULL, 'assistant', 'internal',"
        " 'internal_tool', NULL, NULL, '{}', '')", (BRANCH,))
    conn.execute("INSERT INTO blocks VALUES ('blk_internal', 'occ_internal', 0, 'tool_call',"
                 " 'utf-8', '{\"id\": \"c1\", \"name\": \"palimnesis_recall\"}')")
    conn.execute("INSERT INTO segments VALUES ('blk_internal', 0, ?)", (b'{"id": "X"}',))
    alias = addresses.issue_alias(conn, "s1", "occ_internal")
    conn.execute("INSERT INTO events (kind, payload, at) VALUES ('partial_superseded', ?, 0)",
                 (json.dumps({"occ_id": occ[2]}),))
    conn.execute("COMMIT")

    entries = catalog.first(conn, BRANCH, count=word_tokens, masked={occ[1]}).entries

    assert [e.flags for e in entries] == [("masked",), ("superseded",), (), ("internal",)]
    assert entries[0].text.split()[5] == "masked"
    assert entries[2].text.split()[5] == "-"
    assert entries[3].text == f'§{alias} 4 assistant tool_call 2 internal palimnesis_recall({{"id": "X"}})'
