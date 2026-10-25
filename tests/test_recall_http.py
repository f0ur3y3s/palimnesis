"""Proactive recall through the proxy (A1 Phase 3; docs/plans/phase3.md §2)."""

from __future__ import annotations

import json

from .test_view_http import DONE, _code, body, history, post, rows, upstream_tokens, view_stack

NEEDLE = "ERR_ZX81 raised by flux_capacitor.sync() after 3 retries"


def _with_needle(turns=30, at=7):
    messages = history(turns)
    tool = next(m for m in messages if m.get("tool_call_id") == f"call_{at}")
    lines = tool["content"].split("\n")
    lines[40] = NEEDLE
    tool["content"] = "\n".join(lines)
    return messages


def _excerpt_rows(settings):
    return rows(settings, "SELECT status, reason, query, token_charge, allocation_tokens, rendered"
                          " FROM excerpt_blocks ORDER BY created_at")


def _last_user(raw: bytes) -> str:
    return [m for m in json.loads(raw)["messages"] if m["role"] == "user"][-1]["content"]


def test_a_needle_masked_by_this_request_is_quoted_back_to_the_upstream_only(tmp_path):
    question = "why did flux_capacitor raise ERR_ZX81?"
    messages = _with_needle() + [{"role": "assistant", "content": "done"},
                                 {"role": "user", "content": question}]
    with view_stack(tmp_path, input_budget=8000) as (fake, url, settings):
        fake.respond_sse([DONE])
        r = post(url, body(messages, max_completion_tokens=8192))

    assert r.status_code == 200
    sent = fake.requests[-1].body
    upstream_user = _last_user(sent)
    assert upstream_user.startswith(question + "\n\n[palimnesis excerpts x1")
    assert NEEDLE in upstream_user
    assert NEEDLE not in r.text
    assert upstream_tokens(sent) <= 8000
    [(status, reason, query, charge, allocation, rendered)] = _excerpt_rows(settings)
    assert (status, reason) == ("selected", None)
    assert query.startswith('"flux capacitor" OR "err zx81"')
    assert 0 < charge <= allocation and NEEDLE in rendered
    # the archived user message is the client's text, unchanged
    assert rows(settings, "SELECT count(*) FROM fts_blocks WHERE fts_blocks MATCH"
                          " '\"palimnesis excerpts\"'") == [(0,)]


def test_an_unmasked_session_searches_nothing_and_stays_byte_identical(tmp_path):
    messages = history(2) + [{"role": "assistant", "content": "done"},
                             {"role": "user", "content": "what does f0_3 return?"}]
    data = body(messages, max_completion_tokens=8192)
    with view_stack(tmp_path) as (fake, url, settings):
        fake.respond_sse([DONE])
        assert post(url, data).status_code == 200

    assert fake.requests[-1].body == data
    assert [(s, r) for s, r, *_ in _excerpt_rows(settings)] == [("empty", "nothing_absent")]


def test_continue_records_an_empty_query(tmp_path):
    messages = _with_needle() + [{"role": "assistant", "content": "done"},
                                 {"role": "user", "content": "continue"}]
    with view_stack(tmp_path, input_budget=8000) as (fake, url, settings):
        fake.respond_sse([DONE])
        post(url, body(messages, max_completion_tokens=8192))

    assert "[palimnesis excerpts" not in _last_user(fake.requests[-1].body)
    assert [(s, r) for s, r, *_ in _excerpt_rows(settings)] == [("empty", "empty_query")]


def test_content_still_verbatim_in_the_view_is_not_quoted_again(tmp_path):
    messages = _with_needle(turns=30, at=29) + [{"role": "assistant", "content": "done"},
                                                {"role": "user", "content": "why ERR_ZX81?"}]
    with view_stack(tmp_path, input_budget=8000) as (fake, url, settings):
        fake.respond_sse([DONE])
        post(url, body(messages, max_completion_tokens=8192))

    sent = fake.requests[-1].body.decode()
    assert sent.count("ERR_ZX81 raised") == 1  # the verbatim tool output only
    assert [(s, r) for s, r, *_ in _excerpt_rows(settings)] == [("empty", "no_match")]


def test_a_query_with_no_archived_match_records_no_match(tmp_path):
    messages = _with_needle() + [{"role": "assistant", "content": "done"},
                                 {"role": "user", "content": "deploy the kubernetes cluster"}]
    with view_stack(tmp_path, input_budget=8000) as (fake, url, settings):
        fake.respond_sse([DONE])
        post(url, body(messages, max_completion_tokens=8192))

    assert [(s, r) for s, r, *_ in _excerpt_rows(settings)] == [("empty", "no_match")]


def test_recall_off_selects_nothing(tmp_path):
    question = "why did flux_capacitor raise ERR_ZX81?"
    messages = _with_needle() + [{"role": "assistant", "content": "done"},
                                 {"role": "user", "content": question}]
    with view_stack(tmp_path, input_budget=8000, recall="off") as (fake, url, settings):
        fake.respond_sse([DONE])
        post(url, body(messages, max_completion_tokens=8192))

    assert NEEDLE not in _last_user(fake.requests[-1].body)
