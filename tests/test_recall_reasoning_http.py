"""Excerpts never quote reasoning under retrieval r2 (R33-C, D71), through the proxy.

The model's earlier reasoning is unverified; quoted back as "historical evidence" it
returned the model's own inventions as if they were facts (R30-C, R33-C). Retrieval r2 is
r1 with reasoning blocks left out of the candidates, as D66 did for grep; r1 is kept
unchanged for the frozen configurations."""

from __future__ import annotations

import pytest

from .test_recall_http import _excerpt_rows, _last_user
from .test_view_http import DONE, body, history, post, view_stack

THOUGHT = "ERR_ZX81 comes from flux_capacitor.sync() retrying three times"
EVIDENCE = "ERR_ZX81 raised by flux_capacitor.sync() after 3 retries"
QUESTION = "why did flux_capacitor raise ERR_ZX81?"


def _messages(*, in_reasoning: bool, in_tool: bool):
    messages = history(30)
    if in_reasoning:
        call = next(m for m in messages if m.get("tool_calls")
                    and m["tool_calls"][0]["id"] == "call_7")
        call["reasoning_content"] = "Let me think.\n" + THOUGHT + "\nThat is my guess."
    if in_tool:
        tool = next(m for m in messages if m.get("tool_call_id") == "call_9")
        lines = tool["content"].split("\n")
        lines[40] = EVIDENCE
        tool["content"] = "\n".join(lines)
    return messages + [{"role": "assistant", "content": "done"},
                       {"role": "user", "content": QUESTION}]


def _run(tmp_path, messages, **settings):
    with view_stack(tmp_path, input_budget=8000, **settings) as (fake, url, s):
        fake.respond_sse([DONE])
        r = post(url, body(messages, max_completion_tokens=8192))
    assert r.status_code == 200
    return _last_user(fake.requests[-1].body), _excerpt_rows(s)


def test_retrieval_r1_still_quotes_reasoning(tmp_path):
    upstream_user, _ = _run(tmp_path, _messages(in_reasoning=True, in_tool=False))

    assert THOUGHT in upstream_user


def test_retrieval_r2_never_quotes_reasoning(tmp_path):
    upstream_user, rows = _run(tmp_path, _messages(in_reasoning=True, in_tool=False),
                               retrieval="r2")

    assert THOUGHT not in upstream_user
    assert [(status, reason) for status, reason, *_ in rows] == [("empty", "no_match")]


def test_retrieval_r2_still_quotes_tool_results(tmp_path):
    upstream_user, rows = _run(tmp_path, _messages(in_reasoning=True, in_tool=True),
                               retrieval="r2")

    assert EVIDENCE in upstream_user and THOUGHT not in upstream_user
    [(status, reason, *_)] = rows
    assert (status, reason) == ("selected", None)


def test_an_unknown_retrieval_version_is_refused():
    from palimnesis.recall.proactive import FtsExcerpts

    with pytest.raises(ValueError):
        FtsExcerpts(store=None, counter=None, retrieval="r9")
