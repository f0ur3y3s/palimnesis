"""Bounded views through the proxy (Phase 2 integration; D14)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

import httpx
import pytest

from mnemon import tokens
from mnemon.api import create_app
from mnemon.config import Settings

from .fake_upstream import FakeUpstream
from .servers import serve

SID = "view-1"
TOOLS = [{"type": "function", "function": {"name": "read", "description": "read a file",
                                           "parameters": {"type": "object", "properties": {}}}}]
DONE = (b'data: {"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n")


@contextmanager
def view_stack(tmp_path, **settings):
    fake = FakeUpstream()
    with serve(fake.app()) as upstream_url:
        s = Settings(upstream_base_url=upstream_url, db_path=tmp_path / "archive.db", **settings)
        with serve(create_app(s), mnemon=True) as proxy_url:
            yield fake, proxy_url, s


def _code(i, lines):
    return "\n".join(f"def f{i}_{n}(x): return x * {n}  # {n}" for n in range(lines))


def history(turns, lines=80):
    messages = [{"role": "system", "content": "You are a coding agent."},
                {"role": "user", "content": "refactor the project"}]
    for i in range(turns):
        messages.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": f"call_{i}", "type": "function", "function": {"name": "read", "arguments": "{}"}}]})
        messages.append({"role": "tool", "tool_call_id": f"call_{i}", "content": _code(i, lines)})
    return messages


def body(messages, **settings) -> bytes:
    return json.dumps({"model": "m", "messages": messages, "tools": TOOLS, "stream": True,
                       **settings}).encode()


def post(proxy_url, data: bytes) -> httpx.Response:
    with httpx.stream("POST", f"{proxy_url}/s/{SID}/v1/chat/completions", content=data,
                      timeout=60) as r:
        r.read()
    return r


def upstream_tokens(raw: bytes) -> int:
    return tokens.default().count_messages(**tokens.render_args_from_openai(json.loads(raw)))


def rows(settings, sql):
    c = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


def test_small_request_with_its_own_limit_is_forwarded_byte_identical(tmp_path):
    with view_stack(tmp_path) as (fake, url, _):
        data = body(history(2), max_completion_tokens=8192)
        fake.respond_sse([DONE])
        assert post(url, data).status_code == 200

    assert fake.requests[-1].body == data


def test_missing_output_limit_is_set_to_the_generation_reserve(tmp_path):
    with view_stack(tmp_path) as (fake, url, _):
        data = body(history(2))
        fake.respond_sse([DONE])
        post(url, data)

    sent = json.loads(fake.requests[-1].body)
    assert sent.pop("max_completion_tokens") == 8192
    assert sent == json.loads(data)


def test_history_over_the_budget_is_masked_within_it_and_the_view_is_recorded(tmp_path):
    with view_stack(tmp_path, input_budget=8000) as (fake, url, settings):
        data = body(history(30), max_completion_tokens=8192)
        fake.respond_sse([DONE])
        r = post(url, data)

    assert r.status_code == 200
    sent = fake.requests[-1].body
    assert upstream_tokens(sent) <= 8000
    assert "[mnemon s1" in sent.decode()
    [(n, cause)] = rows(settings, "SELECT n, cause FROM view_versions")
    assert n == 1 and cause in ("watermark_move", "collapse")
    # the archive keeps the full history (plus the generated answer) regardless of the view
    assert rows(settings, "SELECT count(*) FROM occurrences")[0][0] == len(json.loads(data)["messages"]) + 1


def test_follow_up_requests_keep_the_masked_prefix_stable(tmp_path):
    with view_stack(tmp_path, input_budget=8000) as (fake, url, settings):
        messages = history(30)
        fake.respond_sse([DONE])
        post(url, body(messages, max_completion_tokens=8192))
        messages += [{"role": "assistant", "content": "ok"}, {"role": "user", "content": "next"}]
        fake.respond_sse([DONE])
        assert post(url, body(messages, max_completion_tokens=8192)).status_code == 200

    first, second = (json.loads(r.body)["messages"] for r in fake.requests[-2:])
    assert second[:len(first)] == first  # appended, no further masking
    assert len(rows(settings, "SELECT * FROM view_versions")) == 1


def test_non_evictable_input_over_the_budget_is_rejected_before_archiving(tmp_path):
    with view_stack(tmp_path, input_budget=4000) as (fake, url, settings):
        data = body([{"role": "user", "content": "word " * 6000}])
        r = post(url, data)

    assert r.status_code == 400
    assert r.json()["error"]["code"] == "context_budget_exceeded"
    assert r.headers["x-should-retry"] == "false"
    assert fake.requests == []
    assert rows(settings, "SELECT count(*) FROM requests") == [(0,)]


def test_pin_mismatch_disables_the_view_but_still_archives(tmp_path):
    fake = FakeUpstream()
    fake.props_build_info = "Strata 9.9.9"
    with serve(fake.app()) as upstream_url:
        s = Settings(upstream_base_url=upstream_url, db_path=tmp_path / "a.db", input_budget=8000)
        with serve(create_app(s), mnemon=True) as url:
            data = body(history(30), max_completion_tokens=8192)
            fake.respond_sse([DONE])
            assert post(url, data).status_code == 200

    assert fake.requests[-1].body == data  # unbounded, as in Phase 1
    assert rows(s, "SELECT count(*) FROM requests") == [(1,)]


def test_view_off_rejects_over_budget_history_instead_of_masking(tmp_path):
    with view_stack(tmp_path, input_budget=8000, view="off") as (fake, url, settings):
        r = post(url, body(history(30), max_completion_tokens=8192))

    assert r.status_code == 400 and r.json()["error"]["code"] == "context_budget_exceeded"
    assert fake.requests == []


@pytest.mark.parametrize("stage", ["prepare", "build"])
def test_an_unexpected_view_failure_falls_back_to_the_unbounded_body(tmp_path, monkeypatch, stage):
    from mnemon import viewengine

    def boom(*args, **kwargs):
        raise RuntimeError("view bug")

    monkeypatch.setattr(viewengine.ViewEngine, "_prepare" if stage == "prepare" else "build", boom)
    with view_stack(tmp_path) as (fake, url, _):
        data = body(history(2), max_completion_tokens=8192)
        fake.respond_sse([DONE])
        r = post(url, data)

    assert r.status_code == 200
    assert fake.requests[-1].body == data
