"""Process-crash recovery (GL6): a real `mnemon serve` subprocess is killed at
deterministic points (MNEMON_CRASH_AT → os._exit) and restarted on the same
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

from mnemon.capture import load_exchanges
from mnemon.ledger import branch_id_for, load_archived

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
def mnemon_process(upstream_url: str, db: Path, crash_at: str | None = None):
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if k != "MNEMON_CRASH_AT"}
    if crash_at:
        env["MNEMON_CRASH_AT"] = crash_at
    proc = subprocess.Popen(
        [sys.executable, "-m", "mnemon", "serve", "--upstream", upstream_url,
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


def _rows(db: Path, sql: str, *params):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return c.execute(sql, params).fetchall()
    finally:
        c.close()


def _history(db: Path):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return load_archived(c, branch_id_for(SESSION))
    finally:
        c.close()


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
    with mnemon_process(upstream_url, db, crash_at="after_accept") as (url, proc):
        with pytest.raises(httpx.TransportError):
            _post(url, L0.request_body)
        assert proc.wait(timeout=10) == 77

    assert fake.requests == []  # died before calling the upstream
    kinds = [k for (k,) in _rows(db, "SELECT kind FROM events ORDER BY event_id")]
    assert kinds == ["accepted_input", "attempt_started"]

    with mnemon_process(upstream_url, db) as (url, _):
        fake.respond_sse([L0.response_body])
        r = _post(url, L0.request_body)

    assert r.status_code == 200 and r.content == L0.response_body
    assert _rows(db, "SELECT count(*) FROM requests") == [(1,)]
    assert _rows(db, "SELECT n FROM attempts ORDER BY n") == [(1,), (2,)]
    kinds = [k for (k,) in _rows(db, "SELECT kind FROM events ORDER BY event_id")]
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
    with mnemon_process(upstream_url, db, crash_at="after_batch_1") as (url, proc):
        with pytest.raises(httpx.TransportError):
            _post(url, body)
        assert proc.wait(timeout=10) == 77

    [*_, partial] = _history(db)
    assert (partial.source, partial.text, partial.complete) == ("generated", "one ", False)

    with mnemon_process(upstream_url, db) as (url, _):
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
    with mnemon_process(upstream_url, db, crash_at="after_prepare") as (url, proc):
        with pytest.raises(httpx.TransportError):
            _post(url, body, key)
        assert proc.wait(timeout=10) == 77

    with mnemon_process(upstream_url, db) as (url, _):
        keyed = _post(url, body, key)
        keyless = _post(url, body)

    assert keyed.status_code == 200 and keyed.content == answer
    assert keyless.status_code == 409 and keyless.json()["error"]["code"] == "ambiguous_retry"
    assert len(fake.requests) == 1
