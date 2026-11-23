"""Phase 8 S7: the crash and concurrency matrix (plan §1.5, contracts §11, D131).

A real ``palimnesis serve`` subprocess on a masked session (a collapse moves the view and
refreshes the notes) is stopped at each boundary, either by its own ``os._exit``
(``PALIMNESIS_CRASH_AT``) while a second session's request waits for the slot, or by an
external kill while paused there (``PALIMNESIS_PAUSE_AT``): 10 boundaries x 2 protocols.
After a restart on the same archive:

- the archive passes ``palimnesis.archive.integrity.check`` (integrity, foreign keys, no
  active branch, one terminal event per attempt, FTS equal to a rebuild);
- what was committed before the boundary is there, and nothing after it;
- the interrupted attempt is abandoned, never resumed by the proxy;
- the transcripts verify, and the client's keyed resend gets the answer: a replay when the
  turn had completed, a new attempt otherwise."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from palimnesis.archive import integrity

from .fake_upstream import FakeUpstream
from .servers import serve
from .test_notes_http import BUDGET, NOTES, _messages
from .test_view_http import TOOLS

ANSWER = "visible answer"
A, B = "crash-a", "crash-b"


def _reply(doc: dict) -> str:
    """Notes for the proxy's refresh call, the visible answer for anything else."""
    last = doc["messages"][-1].get("content")
    text = last if isinstance(last, str) else json.dumps(last)
    return NOTES if "[palimnesis notes request]" in text else ANSWER


def _queue(fake: FakeUpstream, n: int = 12) -> None:
    for _ in range(n):
        fake.respond_counted(_reply)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def proxy(upstream: str, db: Path, *, crash_at=None, pause_at=None, marker=None):
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PALIMNESIS_CRASH", "PALIMNESIS_PAUSE"))}
    if crash_at:
        env["PALIMNESIS_CRASH_AT"] = crash_at
    if pause_at:
        env["PALIMNESIS_PAUSE_AT"], env["PALIMNESIS_PAUSE_FILE"] = pause_at, str(marker)
    proc = subprocess.Popen(
        [sys.executable, "-m", "palimnesis", "serve", "--upstream", upstream, "--db", str(db),
         "--port", str(port), "--input-budget", str(BUDGET)],
        env=env, stdout=subprocess.DEVNULL,
        stderr=open(db.parent / f"proxy-{port}.log", "wb"))  # read on failure
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while True:
        try:
            httpx.get(f"{url}/health", timeout=0.5)
            break
        except httpx.TransportError:
            if proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError((db.parent / f"proxy-{port}.log").read_text(errors="replace"))
            time.sleep(0.1)
    try:
        yield url, proc
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=15)


# --- the two protocols ----------------------------------------------------------------

def _chat(messages) -> tuple[str, bytes]:
    return "/v1/chat/completions", json.dumps(
        {"model": "m", "messages": messages, "tools": TOOLS, "stream": True,
         "max_completion_tokens": 8192}).encode()


def _anthropic(messages) -> list[dict]:
    out: list[dict] = []
    for m in messages[1:]:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            c = m["tool_calls"][0]
            out.append({"role": "assistant", "content": [{"type": "tool_use", "id": c["id"],
                        "name": c["function"]["name"], "input": {}}]})
        elif m["role"] == "tool":
            out.append({"role": "user", "content": [{"type": "tool_result",
                        "tool_use_id": m["tool_call_id"], "content": m["content"]}]})
        else:
            out.append({"role": "assistant", "content": m["content"]})
    merged: list[dict] = []
    for m in out:  # Messages alternates roles: join consecutive assistant turns
        if merged and merged[-1]["role"] == m["role"] == "assistant":
            prev = merged[-1]["content"]
            prev = prev if isinstance(prev, list) else [{"type": "text", "text": prev}]
            cur = m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]
            merged[-1] = {"role": "assistant", "content": prev + cur}
        else:
            merged.append(m)
    return merged


def _messages_api(messages) -> tuple[str, bytes]:
    tools = [{"name": t["function"]["name"], "description": t["function"].get("description", ""),
              "input_schema": t["function"]["parameters"]} for t in TOOLS]
    return "/v1/messages", json.dumps(
        {"model": "m", "max_tokens": 8192, "stream": True, "system": messages[0]["content"],
         "tools": tools, "messages": _anthropic(messages)}).encode()


PROTOCOLS = {"chat": _chat, "messages": _messages_api}


def _post(url, session, protocol, messages, key, timeout=30) -> httpx.Response:
    path, payload = PROTOCOLS[protocol](messages)
    with httpx.stream("POST", f"{url}/s/{session}{path}", content=payload,
                      headers={"Idempotency-Key": key}, timeout=timeout) as r:
        r.read()
    return r


def _text(r: httpx.Response) -> str:
    return r.text


# --- checks after a restart -------------------------------------------------------------

def _rows(db, sql, *args):
    deadline = time.monotonic() + 5
    while True:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return c.execute(sql, args).fetchall()
        except sqlite3.OperationalError as e:
            if "disk I/O error" not in str(e) or time.monotonic() > deadline:
                raise
        finally:
            c.close()
        time.sleep(0.1)


def _settled(db, upstream_url):
    """Restart once with nothing to do (recover marks the interrupted attempt), stop, and
    check the archive."""
    with proxy(upstream_url, db):
        pass
    deadline = time.monotonic() + 10
    while True:  # Windows may hold the stopped process's handles for a moment
        c = sqlite3.connect(db)
        try:
            return integrity.check(c)
        except sqlite3.OperationalError as e:
            if "disk I/O error" not in str(e) or time.monotonic() > deadline:
                raise
        finally:
            c.close()
        time.sleep(0.2)


def _verify(db, session) -> int:
    r = subprocess.run([sys.executable, "-m", "palimnesis", "transcripts", "verify", session,
                        "--db", str(db)], capture_output=True, text=True)
    if r.returncode:
        print("VERIFY", session, r.returncode, r.stdout[-800:], r.stderr[-800:])
    return r.returncode


def _verify_eventually(db, *sessions, timeout=20.0) -> bool:
    """The projector publishes in the background after a request: verify while the proxy
    still runs, until every session's transcripts verify."""
    deadline = time.monotonic() + timeout
    while True:
        if all(_verify(db, s) == 0 for s in sessions):
            return True
        if time.monotonic() > deadline:
            for log in sorted(Path(db).parent.glob("proxy-*.log")):
                print("LOG", log.name, log.read_text(errors="replace")[-1500:])
            return False
        time.sleep(0.5)


# --- os._exit at the new points, with a second session waiting ------------------------

NEW_POINTS = ["before_notes_commit", "after_notes_commit", "after_view_record",
              "after_terminal_commit"]


@pytest.mark.parametrize("point", NEW_POINTS)
def test_a_crash_at_a_new_point_with_a_second_session_waiting(point, tmp_path):
    fake = FakeUpstream()
    db = tmp_path / "archive.db"
    with serve(fake.app()) as up:
        fake.respond_counted(_reply)  # A's first call is held so B is accepted behind it
        fake._script[-1].delay = 0.8
        _queue(fake)
        with proxy(up, db, crash_at=point) as (url, p):
            got_b: dict = {}

            def b():
                try:
                    got_b["r"] = _post(url, B, "chat", [{"role": "user", "content": "hello B"}], "kb")
                except httpx.TransportError as e:
                    got_b["e"] = e

            t = threading.Thread(target=b)
            with pytest.raises(httpx.TransportError):
                threading.Timer(0.3, t.start).start()
                _post(url, A, "chat", _messages(), "ka")
            assert p.wait(timeout=15) == 77
            t.join(timeout=15)
        assert "e" in got_b  # B was waiting for the slot when the process died

        assert _settled(db, up) == []
        notes = _rows(db, "SELECT status FROM notes_versions")
        assert notes == ([] if point == "before_notes_commit" else [("committed",)])
        complete = _rows(db, "SELECT count(*) FROM events WHERE kind = 'turn_complete'")[0][0]
        assert complete == (1 if point == "after_terminal_commit" else 0)
        assert _rows(db, "SELECT count(*) FROM events WHERE kind = 'attempt_abandoned'")[0][0] >= 1

        n_up = len(fake.requests)
        with proxy(up, db) as (url, _):
            ra = _post(url, A, "chat", _messages(), "ka")
            rb = _post(url, B, "chat", [{"role": "user", "content": "hello B"}], "kb")
            assert _verify_eventually(db, A, B)
        assert ra.status_code == rb.status_code == 200, (ra.text[:300], rb.text[:300])
        assert ANSWER in ra.text and ANSWER in rb.text
        if point == "after_terminal_commit":
            assert len(fake.requests) == n_up + 1  # A replayed from the archive; B answered
        assert _settled(db, up) == []


# --- external kills: 10 boundaries x 2 protocols ----------------------------------------

BOUNDARIES = ["after_accept", "before_notes_commit", "after_notes_commit", "after_view_record",
              "after_excerpt_commit", "after_batch_1", "after_terminal_commit",
              "publish_staged", "publish_after_files", "publish_after_index"]


@pytest.mark.parametrize("protocol", ["chat", "messages"])
@pytest.mark.parametrize("point", BOUNDARIES)
def test_an_external_kill_at_each_boundary(point, protocol, tmp_path):
    fake = FakeUpstream()
    db, marker = tmp_path / "archive.db", tmp_path / "paused"
    with serve(fake.app()) as up:
        _queue(fake)
        with proxy(up, db, pause_at=point, marker=marker) as (url, p):
            t = threading.Thread(target=lambda: _swallow(lambda: _post(url, A, protocol, _messages(), "ka", timeout=60)))
            t.start()
            deadline = time.monotonic() + 30
            while not marker.exists():
                assert time.monotonic() < deadline, f"{point} never reached"
                time.sleep(0.05)
            p.kill()  # external: TerminateProcess / SIGKILL while paused at the boundary
            p.wait(timeout=15)
            t.join(timeout=30)

        assert _settled(db, up) == []
        partial = _partial_output(db)
        with proxy(up, db) as (url, _):
            r = _post(url, A, protocol, _messages(), "ka")
            assert _verify_eventually(db, A)
        if partial:  # output archived without a terminal commit: never regenerated (D130)
            assert r.status_code == 409 and "ambiguous_retry" in r.text, r.text[:300]
        else:
            assert r.status_code == 200, r.text[:300]
            assert ANSWER in r.text
        assert _settled(db, up) == []


def _partial_output(db) -> bool:
    """The visible answer had archived output but no terminal commit when it died. Whether
    a kill at ``after_batch_1`` finds a partial depends on how the stream's bytes arrived
    (one read on Windows, several on Linux: S10)."""
    rows = _rows(db, "SELECT o.occ_id FROM occurrences o JOIN generations g"
                     " ON g.generation_id = o.generation_id WHERE o.source = 'generated'"
                     " AND NOT EXISTS (SELECT 1 FROM events e WHERE e.attempt_id = g.attempt_id"
                     " AND e.kind = 'turn_complete')"
                     " AND EXISTS (SELECT 1 FROM blocks b JOIN segments s ON s.block_id = b.block_id"
                     " WHERE b.occ_id = o.occ_id AND b.kind = 'text')")
    return bool(rows)


def _swallow(fn):
    try:
        fn()
    except httpx.TransportError:
        pass


def test_a_publication_cut_short_leaves_a_marker_that_names_its_session(tmp_path):
    from palimnesis.transcripts import projector

    root = tmp_path / "t"
    d = projector.session_dir(root, "ses.one")
    d.mkdir(parents=True)
    (d / projector.PUBLISHING).write_text("ses.one", encoding="utf-8")
    other = projector.session_dir(root, "ses-two")
    other.mkdir(parents=True)  # published to completion: no marker
    assert projector.interrupted_sessions(root) == ["ses.one"]
    assert projector.interrupted_sessions(tmp_path / "missing") == []
