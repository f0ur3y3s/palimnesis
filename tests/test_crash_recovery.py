"""Process-crash recovery (GL6): a real `palimnesis serve` subprocess is killed at
deterministic points (PALIMNESIS_CRASH_AT → os._exit) and restarted on the same
archive. Committed input, output batches and prepared responses survive;
interrupted attempts are abandoned, never resumed silently (D10.12).
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from palimnesis.capture import load_exchanges
from palimnesis.ledger import branch_id_for, load_archived

from .fake_upstream import FakeUpstream
from .servers import serve

ROOT = Path(__file__).resolve().parents[1]
L0 = load_exchanges(ROOT / "eval/fixtures/opencode-2.1.4/live/exchanges")[0]
SESSION = "crash-1"
URL = f"/s/{SESSION}/v1/chat/completions"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def palimnesis_process(upstream_url: str, db: Path, crash_at: str | None = None):
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if k != "PALIMNESIS_CRASH_AT"}
    if crash_at:
        env["PALIMNESIS_CRASH_AT"] = crash_at
    proc = subprocess.Popen(
        [sys.executable, "-m", "palimnesis", "serve", "--upstream", upstream_url,
         "--db", str(db), "--port", str(port)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    while True:
        try:
            # Unsessioned: answered locally (400), never reaches the upstream.
            httpx.get(f"{url}/health", timeout=0.5)
            break
        except httpx.TransportError:
            if proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(proc.stderr.read().decode(errors="replace"))
            time.sleep(0.1)
    try:
        yield url, proc
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=10)


def _read(db: Path, fn):
    """Read the archive the way an outside observer would, right after a kill.

    A process killed mid-WAL leaves its -shm needing recovery, which a read-only
    connection cannot perform, and Windows may still hold the dead process's
    handles for a moment: retry briefly on that transient error only."""
    deadline = time.monotonic() + 5
    while True:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return fn(c)
        except sqlite3.OperationalError as e:
            if "disk I/O error" not in str(e) or time.monotonic() > deadline:
                raise
        finally:
            c.close()
        time.sleep(0.1)


def _rows(db: Path, sql: str, *params):
    return _read(db, lambda c: c.execute(sql, params).fetchall())


def _history(db: Path):
    return _read(db, lambda c: load_archived(c, branch_id_for(SESSION)))


@pytest.fixture
def upstream():
    fake = FakeUpstream()
    with serve(fake.app()) as url:
        yield fake, url


def _post(url: str, body: bytes, headers=None) -> httpx.Response:
    with httpx.stream("POST", url + URL, content=body, headers=headers, timeout=20) as r:
        r.read()
    return r


def test_crash_after_input_commit_then_identical_resend_gets_a_new_attempt(upstream, tmp_path):
    fake, upstream_url = upstream
    db = tmp_path / "archive.db"
    with palimnesis_process(upstream_url, db, crash_at="after_accept") as (url, proc):
        with pytest.raises(httpx.TransportError):
            _post(url, L0.request_body)
        assert proc.wait(timeout=10) == 77

    assert fake.requests == []  # died before calling the upstream
    kinds = [k for (k,) in _rows(db, "SELECT kind FROM events ORDER BY event_id")]
    assert kinds == ["accepted_input", "attempt_started"]

    with palimnesis_process(upstream_url, db) as (url, _):
        fake.respond_sse([L0.response_body])
        r = _post(url, L0.request_body)

    assert r.status_code == 200 and r.content == L0.response_body
    assert _rows(db, "SELECT count(*) FROM requests") == [(1,)]
    assert _rows(db, "SELECT n FROM attempts ORDER BY n") == [(1,), (2,)]
    kinds = [k for (k,) in _rows(db, "SELECT kind FROM events ORDER BY event_id")
             if k != "upstream_call"]  # cache accounting follows delivery (contracts §10)
    assert "attempt_abandoned" in kinds and kinds[-1] == "delivery_completed"
    assert [(a.role, a.source) for a in _history(db)] == [
        ("system", "client"), ("user", "client"), ("assistant", "generated")]


def test_crash_after_a_batch_commit_keeps_the_partial_and_refuses_silent_regeneration(upstream, tmp_path):
    fake, upstream_url = upstream
    db = tmp_path / "archive.db"
    body = json.dumps({"model": "m", "stream": True,
                       "messages": [{"role": "user", "content": "count"}]}).encode()
    fake.respond_sse([
        b'data: {"choices":[{"index":0,"delta":{"content":"one "}}]}\n\n',
        (0.2, b'data: {"choices":[{"index":0,"delta":{"content":"two"}}]}\n\n'),
        b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n',
        b"data: [DONE]\n\n",
    ])
    with palimnesis_process(upstream_url, db, crash_at="after_batch_1") as (url, proc):
        with pytest.raises(httpx.TransportError):
            _post(url, body)
        assert proc.wait(timeout=10) == 77

    [*_, partial] = _history(db)
    assert (partial.source, partial.text, partial.complete) == ("generated", "one ", False)

    with palimnesis_process(upstream_url, db) as (url, _):
        r = _post(url, body)

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ambiguous_retry"
    assert len(fake.requests) == 1  # no second generation


def test_crash_after_prepared_response_replays_it_by_key_without_inference(upstream, tmp_path):
    fake, upstream_url = upstream
    db = tmp_path / "archive.db"
    body = json.dumps({"model": "m", "messages": [{"role": "user", "content": "hi"}]}).encode()
    answer = json.dumps({"choices": [{"index": 0, "finish_reason": "stop",
                                      "message": {"role": "assistant", "content": "hello"}}]}).encode()
    fake.respond_json(answer)
    key = {"Idempotency-Key": "k-1"}
    with palimnesis_process(upstream_url, db, crash_at="after_prepare") as (url, proc):
        with pytest.raises(httpx.TransportError):
            _post(url, body, key)
        assert proc.wait(timeout=10) == 77

    with palimnesis_process(upstream_url, db) as (url, _):
        keyed = _post(url, body, key)
        keyless = _post(url, body)

    assert keyed.status_code == 200 and keyed.content == answer
    assert keyless.status_code == 409 and keyless.json()["error"]["code"] == "ambiguous_retry"
    assert len(fake.requests) == 1


def test_crash_after_the_terminal_commit_before_forwarding_accepts_the_continue(upstream, tmp_path):
    # Review item 5: the turn is complete in the archive but the client only
    # received the first two batches, so OpenCode sends a flattened Continue.
    fake, upstream_url = upstream
    db = tmp_path / "archive.db"
    body = json.dumps({"model": "m", "stream": True,
                       "messages": [{"role": "user", "content": "q"}]}).encode()
    fake.respond_sse([
        b'data: {"choices":[{"index":0,"delta":{"reasoning_content":"think "}}]}\n\n',
        (0.3, b'data: {"choices":[{"index":0,"delta":{"content":"answer"}}]}\n\n'),
        (0.3, b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
              b"data: [DONE]\n\n"),
    ])
    with palimnesis_process(upstream_url, db, crash_at="after_batch_3") as (url, proc):
        with pytest.raises(httpx.TransportError):
            _post(url, body)
        assert proc.wait(timeout=10) == 77

    cont = json.dumps({"model": "m", "stream": True, "messages": [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "think answer", "reasoning_content": ""},
        {"role": "user", "content": "The previous response was interrupted. Continue from "
                                    "where you left off without repeating completed content."},
    ]}).encode()
    with palimnesis_process(upstream_url, db) as (url, _):
        fake.respond_sse([b'data: {"choices":[{"index":0,"delta":{"content":"."},"finish_reason":"stop"}]}\n\n',
                          b"data: [DONE]\n\n"])
        r = _post(url, cont)

    assert r.status_code == 200, r.content[:300]
    sent = json.loads(fake.requests[-1].body)["messages"][1]
    assert (sent["reasoning_content"], sent["content"]) == ("think ", "answer")


def test_crash_after_the_excerpt_commit_reuses_the_stored_selection(upstream, tmp_path):
    fake, upstream_url = upstream
    db = tmp_path / "archive.db"
    body = json.dumps({"model": "m", "stream": True, "max_completion_tokens": 8192,
                       "messages": [{"role": "user", "content": "hello"}]}).encode()
    with palimnesis_process(upstream_url, db, crash_at="after_excerpt_commit") as (url, proc):
        with pytest.raises(httpx.TransportError):
            _post(url, body)
        assert proc.wait(timeout=10) == 77

    assert fake.requests == []
    with palimnesis_process(upstream_url, db) as (url, _):
        fake.respond_sse([b'data: {"choices":[{"index":0,"delta":{"content":"hi"},'
                          b'"finish_reason":"stop"}]}\n\n', b"data: [DONE]\n\n"])
        assert _post(url, body).status_code == 200

    assert _rows(db, "SELECT count(*) FROM excerpt_blocks") == [(1,)]


def test_a_retry_after_a_crash_before_the_excerpt_commit_selects_once(upstream, tmp_path):
    # D31: the crash left the instruction accepted with no excerpt row; the retry
    # (no inference has happened) selects for it, exactly once.
    fake, upstream_url = upstream
    db = tmp_path / "archive.db"
    body = json.dumps({"model": "m", "stream": True, "max_completion_tokens": 8192,
                       "messages": [{"role": "user", "content": "hello there"}]}).encode()
    with palimnesis_process(upstream_url, db, crash_at="after_accept") as (url, proc):
        with pytest.raises(httpx.TransportError):
            _post(url, body)
        assert proc.wait(timeout=10) == 77
    assert _rows(db, "SELECT count(*) FROM excerpt_blocks") == [(0,)]

    with palimnesis_process(upstream_url, db) as (url, _):
        fake.respond_sse([b'data: {"choices":[{"index":0,"delta":{"content":"hi"},'
                          b'"finish_reason":"stop"}]}\n\n', b"data: [DONE]\n\n"])
        assert _post(url, body).status_code == 200

    assert _rows(db, "SELECT status, reason FROM excerpt_blocks") == [("empty", "nothing_absent")]
