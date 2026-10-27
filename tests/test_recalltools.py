"""palimnesis.recalltools: the hidden recall tools' results (Phase 3B S4; plan §2.5).

The tools run against a real archive built through ``ledger.accept``. Expected text
comes from the literal messages archived, never from the module's own helpers."""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from palimnesis import ledger, recalltools as rt
from palimnesis.chat import parse
from palimnesis.fingerprint import fingerprint_v1
from palimnesis.store import Store


def char_tokens(text: str) -> int:
    return len(text)


LOG = "\n".join(f"line {i}: E-{4000 + i} kilnworks ramp_{i} ok" for i in range(300))
SPEC = "Use interpolate_ramp_curve() for the ramp.\nNever touch hotfix/46003-kilnworks-temperature."
MULTI = "héllo wörld 🙂 — ünïcode\n" * 40 + "tail \ud800 lone"


def _messages(tag: str):
    return [
        {"role": "system", "content": "You are a coding agent."},
        {"role": "user", "content": f"{tag}: read the log"},
        {"role": "assistant", "content": None, "reasoning_content": "Plan: read it.",
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "read", "arguments": "{\"path\": \"log.txt\"}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": LOG},
        {"role": "assistant", "content": SPEC},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c2", "type": "function",
                         "function": {"name": "read", "arguments": "{\"path\": \"u.txt\"}"}}]},
        {"role": "tool", "tool_call_id": "c2", "content": MULTI},
        {"role": "user", "content": f"{tag}: now fix it"},
    ]


def _accept(store: Store, session: str, messages):
    req = parse(json.dumps({"model": "m", "stream": True, "messages": messages}).encode())
    fp = fingerprint_v1(ledger.ENDPOINT_CHAT, session, ledger.branch_id_for(session),
                        json.loads(req.raw))
    return asyncio.run(store.write(lambda c: ledger.accept(
        c, session_id=session, association="path", req=req, fingerprint=fp,
        retry_hint=None, live=set())))


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("rt") / "archive.db"
    store = Store.open(path)
    try:
        _accept(store, "s1", _messages("one"))
        _accept(store, "s2", _messages("two"))
    finally:
        store.close()
    conn = sqlite3.connect(path, isolation_level=None)
    yield conn
    conn.close()


def _address(conn, session: str, seq: int, kind: str) -> str:
    alias, idx = conn.execute(
        "SELECT a.alias, b.idx FROM occurrences o JOIN aliases a ON a.target_id = o.occ_id"
        " JOIN blocks b ON b.occ_id = o.occ_id"
        " WHERE o.branch_id = ? AND o.seq = ? AND b.kind = ?",
        (ledger.branch_id_for(session), seq, kind)).fetchone()
    return f"§{alias}.{idx}"


def _ctx(conn, session="s1", max_tokens=2048, hidden=None, **kw):
    return rt.Context(conn=conn, session_id=session, branch_id=ledger.branch_id_for(session),
                      count=char_tokens, max_tokens=max_tokens, hidden=hidden, **kw)


def _call(ctx, name, **args):
    return rt.run(name, json.dumps(args), ctx)


def _body(result) -> str:
    """The content after the one-line header."""
    return result.text.split("\n", 1)[1]


# --- palimnesis_recall -------------------------------------------------------------


def test_recall_returns_the_exact_block_with_its_range_and_hash(db):
    r = _call(_ctx(db), "palimnesis_recall", id=_address(db, "s1", 5, "text"))
    assert r.ok
    assert _body(r) == SPEC
    assert f"0–{len(SPEC)} of {len(SPEC)}" in r.text.splitlines()[0]
    assert r.meta["start"] == 0 and r.meta["end"] == len(SPEC) and r.meta["next_offset"] is None


@pytest.mark.parametrize("limit_tokens", [120, 200, 1000])
def test_recall_pages_reassemble_exactly_property(db, limit_tokens):
    addr = _address(db, "s1", 7, "tool_result")
    ctx, offset, parts = _ctx(db, max_tokens=limit_tokens), 0, []
    while offset is not None:
        r = _call(ctx, "palimnesis_recall", id=addr, offset=offset)
        assert r.ok and len(_body(r)) <= limit_tokens
        parts.append(_body(r))
        offset = r.meta["next_offset"]
    # Shown text quotes the lone surrogate as U+FFFD, one code point, so offsets hold.
    assert "".join(parts) == MULTI.replace("\ud800", "�")
    assert r.meta["sha256"] == rt.sha256_of(MULTI)


def test_recall_offset_and_limit_are_code_points(db):
    r = _call(_ctx(db), "palimnesis_recall", id=_address(db, "s1", 4, "tool_result"),
              offset=7, limit=10)
    assert _body(r) == LOG[7:17] and r.meta["next_offset"] == 17


def test_recall_an_occurrence_with_several_blocks_lists_them_without_content(db):
    addr = _address(db, "s1", 3, "tool_call").rsplit(".", 1)[0]
    r = _call(_ctx(db), "palimnesis_recall", id=addr)
    assert r.ok and "Plan: read it." not in r.text and "log.txt" not in r.text
    assert f"{addr}.0" in r.text and f"{addr}.1" in r.text


@pytest.mark.parametrize("bad", ["§ZZZZZZZ.0", "not an address", "§", ""])
def test_recall_unknown_ids_return_errors_never_content(db, bad):
    r = _call(_ctx(db), "palimnesis_recall", id=bad)
    assert not r.ok and r.meta["error"] == "unknown_address"
    assert SPEC not in r.text and "kilnworks" not in r.text


def test_recall_suggests_near_aliases_without_substituting(db):
    addr = _address(db, "s1", 5, "text")
    alias = addr[1:].split(".")[0]
    near = "§" + alias[:-1] + ("0" if alias[-1] != "0" else "1") + ".0"
    r = _call(_ctx(db), "palimnesis_recall", id=near)
    assert not r.ok and alias in r.text and SPEC not in r.text


def test_recall_never_resolves_another_sessions_address(db):
    r = _call(_ctx(db, "s1"), "palimnesis_recall", id=_address(db, "s2", 5, "text"))
    assert not r.ok and r.meta["error"] == "unknown_address"


def test_recall_block_number_out_of_range_is_an_error(db):
    addr = _address(db, "s1", 5, "text").rsplit(".", 1)[0] + ".9"
    r = _call(_ctx(db), "palimnesis_recall", id=addr)
    assert not r.ok and r.meta["error"] == "unknown_block"


# --- palimnesis_grep, text mode ----------------------------------------------------


def test_grep_text_finds_code_punctuation_as_phrases(db):
    r = _call(_ctx(db, hidden=None), "palimnesis_grep", query="hotfix/46003-kilnworks-temperature",
              mode="text", scope="all")
    assert r.ok and _address(db, "s1", 5, "text") in r.text


@pytest.mark.parametrize("query", ['NEAR(a b)', 'col:value', '"unbalanced', 'ramp_1*', 'a OR', '^start'])
def test_grep_text_quotes_operators_literally(db, query):
    r = _call(_ctx(db), "palimnesis_grep", query=query, mode="text", scope="all")
    assert r.ok or r.meta["error"] == "empty_query"


def test_grep_is_scoped_to_the_session_branch(db):
    r = _call(_ctx(db, "s1"), "palimnesis_grep", query="two now fix", mode="text", scope="all")
    assert r.ok and "no matches" in r.text


def test_grep_hidden_scope_searches_only_what_the_view_hides(db):
    log_occ = db.execute("SELECT occ_id FROM occurrences WHERE branch_id = ? AND seq = 4",
                         (ledger.branch_id_for("s1"),)).fetchone()[0]
    hidden = {log_occ: frozenset({"tool_result"})}
    found = _call(_ctx(db, hidden=hidden), "palimnesis_grep", query="E-4123", mode="text")
    shown = _call(_ctx(db, hidden=hidden), "palimnesis_grep", query="interpolate_ramp_curve",
                  mode="text")
    assert found.ok and _address(db, "s1", 4, "tool_result") in found.text
    assert shown.ok and "no matches" in shown.text


def test_grep_never_searches_the_system_message(db):
    r = _call(_ctx(db), "palimnesis_grep", query="coding agent", mode="text", scope="all")
    assert r.ok and "no matches" in r.text


def test_grep_pages_with_a_cursor_and_rejects_a_foreign_one(db):
    ctx = _ctx(db)
    p1 = _call(ctx, "palimnesis_grep", query=r"ramp_\d+ ok", mode="regex", scope="all")
    assert p1.ok and p1.meta["cursor"] is not None and p1.meta["hits"] == rt.GREP_PAGE
    p2 = _call(ctx, "palimnesis_grep", query=r"ramp_\d+ ok", mode="regex", scope="all",
               cursor=p1.meta["cursor"])
    assert p2.ok and set(p1.meta["addresses_lines"]).isdisjoint(p2.meta["addresses_lines"])
    other = _call(_ctx(db, "s2"), "palimnesis_grep", query=r"ramp_\d+ ok", mode="regex",
                  scope="all", cursor=p1.meta["cursor"])
    assert not other.ok and other.meta["error"] == "bad_cursor"


# --- palimnesis_grep, regex mode (RE2) ---------------------------------------------


def test_grep_regex_matches_across_lines(db):
    r = _call(_ctx(db), "palimnesis_grep", query=r"(?s)interpolate_ramp_curve.*hotfix/46003",
              mode="regex", scope="all")
    assert r.ok and _address(db, "s1", 5, "text") in r.text


@pytest.mark.parametrize("pattern", [r"(a)\1", r"(?=x)y", r"(?<!a)b"])
def test_grep_regex_unsupported_syntax_is_an_error_never_a_fallback(db, pattern):
    r = _call(_ctx(db), "palimnesis_grep", query=pattern, mode="regex", scope="all")
    assert not r.ok and r.meta["error"] == "regex_unsupported"


def test_grep_regex_pattern_length_is_capped(db):
    r = _call(_ctx(db), "palimnesis_grep", query="a" * (rt.MAX_PATTERN + 1), mode="regex",
              scope="all")
    assert not r.ok and r.meta["error"] == "pattern_too_long"


def test_grep_regex_stops_at_the_scan_cap(db, monkeypatch):
    monkeypatch.setattr(rt, "MAX_SCAN_BYTES", 100)
    r = _call(_ctx(db), "palimnesis_grep", query="zzz-never", mode="regex", scope="all")
    assert r.ok and r.meta["truncated"] == "scan_limit"


def test_grep_checks_cancellation_between_blocks(db):
    calls = []

    def cancelled():
        calls.append(1)
        return len(calls) > 1

    r = _call(_ctx(db, cancelled=cancelled), "palimnesis_grep", query="ok", mode="regex",
              scope="all")
    assert not r.ok and r.meta["error"] == "cancelled"


# --- palimnesis_catalog ------------------------------------------------------------


def test_catalog_pages_list_every_occurrence_of_the_branch(db):
    r = _call(_ctx(db), "palimnesis_catalog")
    n = db.execute("SELECT count(*) FROM occurrences WHERE branch_id = ?",
                   (ledger.branch_id_for("s1"),)).fetchone()[0]
    assert r.ok and len([l for l in r.text.splitlines() if l.startswith("§")]) == n
    assert _call(_ctx(db), "palimnesis_catalog", page=1).text == r.text
    assert not _call(_ctx(db), "palimnesis_catalog", page=99).ok


# --- arguments and size ------------------------------------------------------------


@pytest.mark.parametrize("name,args,error", [
    ("palimnesis_recall", "{", "invalid_arguments"),
    ("palimnesis_recall", "[]", "invalid_arguments"),
    ("palimnesis_recall", '{"offset": 1}', "invalid_arguments"),
    ("palimnesis_recall", '{"id": "§A.0", "offset": -1}', "invalid_arguments"),
    ("palimnesis_recall", '{"id": "§A.0", "extra": 1}', "invalid_arguments"),
    ("palimnesis_grep", '{"query": "x", "mode": "glob"}', "invalid_arguments"),
    ("palimnesis_grep", '{"query": "x", "scope": "everything"}', "invalid_arguments"),
    ("palimnesis_frobnicate", "{}", "unknown_tool"),
])
def test_malformed_calls_get_error_results(db, name, args, error):
    r = rt.run(name, args, _ctx(db))
    assert not r.ok and r.meta["error"] == error


@pytest.mark.parametrize("name,args", [
    ("palimnesis_recall", {"id": "LOG"}),
    ("palimnesis_grep", {"query": "ok", "mode": "regex", "scope": "all"}),
    ("palimnesis_catalog", {}),
])
def test_every_result_fits_max_tokens(db, name, args):
    if args.get("id") == "LOG":
        args = {"id": _address(db, "s1", 4, "tool_result")}
    r = _call(_ctx(db, max_tokens=300), name, **args)
    assert char_tokens(r.text) <= 300


def test_a_budget_too_small_for_any_result_is_an_error(db):
    r = _call(_ctx(db, max_tokens=10), "palimnesis_recall", id=_address(db, "s1", 5, "text"))
    assert not r.ok and r.meta["error"] == "no_room"


# --- grep skips reasoning (S10b, F2 / D66) -----------------------------------------
#
# The model's own reasoning, returned as a search hit, reads as evidence; grep never
# searches ``reasoning`` blocks in either scope, while recall still returns them.

GUESS = "I recall the vendor is Glimmerquack Industries; Moonwhistle sounds wrong."


def _reasoning_messages():
    return [
        {"role": "system", "content": "You are a coding agent."},
        {"role": "user", "content": "Which vendor does Moonwhistle supply? Read vendors.txt."},
        {"role": "assistant", "content": None, "reasoning_content": GUESS,
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "read",
                                      "arguments": "{\"path\": \"vendors.txt\"}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "vendor: Moonwhistle\nowner: Acme"},
        {"role": "assistant", "content": "Moonwhistle is Acme's vendor.",
         "reasoning_content": "Glimmerquack was my own guess; the file says Moonwhistle."},
        {"role": "user", "content": "Thanks."},
    ]


@pytest.fixture(scope="module")
def rdb(tmp_path_factory):
    path = tmp_path_factory.mktemp("rt_reasoning") / "archive.db"
    store = Store.open(path)
    try:
        _accept(store, "r1", _reasoning_messages())
    finally:
        store.close()
    conn = sqlite3.connect(path, isolation_level=None)
    yield conn
    conn.close()


def _everything_hidden(conn, session="r1"):
    """``hidden`` naming every occurrence of the branch with all its blocks."""
    occs = conn.execute("SELECT occ_id FROM occurrences WHERE branch_id = ?",
                        (ledger.branch_id_for(session),)).fetchall()
    return {occ: None for (occ,) in occs}


@pytest.mark.parametrize("mode,query", [("text", "Glimmerquack"), ("regex", "Glimmerquack")])
@pytest.mark.parametrize("scope", ["hidden", "all"])
def test_grep_never_finds_a_word_only_in_reasoning(rdb, mode, query, scope):
    ctx = _ctx(rdb, "r1", hidden=_everything_hidden(rdb))
    r = _call(ctx, "palimnesis_grep", query=query, mode=mode, scope=scope)
    assert r.ok and r.meta["hits"] == 0 and "no matches" in r.text
    assert "Glimmerquack" not in r.text


@pytest.mark.parametrize("scope", ["hidden", "all"])
def test_grep_finds_the_same_word_in_tool_results_and_user_text_but_not_reasoning(rdb, scope):
    ctx = _ctx(rdb, "r1", hidden=_everything_hidden(rdb))
    r = _call(ctx, "palimnesis_grep", query="Moonwhistle", mode="text", scope=scope)
    assert r.ok
    found = {line.split(" ", 1)[0] for line in r.text.splitlines()[1:]}
    assert _address(rdb, "r1", 4, "tool_result") in found
    assert _address(rdb, "r1", 2, "text") in found
    assert _address(rdb, "r1", 5, "text") in found
    assert _address(rdb, "r1", 3, "reasoning") not in found
    assert _address(rdb, "r1", 5, "reasoning") not in found
    assert all(" reasoning " not in line for line in r.text.splitlines()[1:])


def test_recall_still_returns_a_reasoning_block_by_address(rdb):
    r = _call(_ctx(rdb, "r1"), "palimnesis_recall", id=_address(rdb, "r1", 3, "reasoning"))
    assert r.ok and _body(r) == GUESS


def test_grep_cursors_carry_version_2_since_reasoning_left_the_search():
    """Protocol review: D66 changed the hit list, so cursors issued before it are refused."""
    from palimnesis import recalltools

    assert recalltools.GREP_CURSOR == "grep2"
