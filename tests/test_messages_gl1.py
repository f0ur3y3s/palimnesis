"""GL1 archive contracts on the Messages route (Phase 4B §5's requirement map).

Recall, streaming, cancellation, recovery, sessions and the allowance, each pinned for a
Messages client: the behaviour the Chat route already has, through the S1 seam.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager

import httpx
import pytest

from palimnesis.api import create_app
from palimnesis.config import Settings

from .archive_helpers import DONE, answer, chunk
from .fake_upstream import FakeUpstream
from .servers import serve
from .test_excerpts_http import SeededExcerpts

SID = "gl1-msg"


@contextmanager
def stack(tmp_path, fake=None, **settings):
    fake = fake or FakeUpstream()
    with serve(fake.app()) as upstream_url:
        s = Settings(upstream_base_url=upstream_url, db_path=tmp_path / "archive.db", **settings)
        with serve(create_app(s), palimnesis=True) as url:
            yield fake, url, s


def mbody(messages, stream=True, **top) -> bytes:
    return json.dumps({"model": "m", "max_tokens": 8192, "stream": stream, "system": "S",
                       **top, "messages": messages}).encode()


def mpost(url, payload, *, session=SID, headers=None, path=None) -> httpx.Response:
    target = path or f"{url}/s/{session}/v1/messages?beta=true"
    with httpx.stream("POST", target, content=payload, headers=headers, timeout=30) as r:
        r.read()
    return r


def rows(db, sql):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


FIRST = [{"role": "user", "content": "use tabs, never spaces"}]
SECOND = FIRST + [{"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
                  {"role": "user", "content": "now indent it"}]


def test_excerpts_on_messages_host_and_absent_from_client_stream(tmp_path):
    with stack(tmp_path, excerpt_source=SeededExcerpts()) as (fake, url, s):
        fake.respond_sse(answer("ok"))
        assert mpost(url, mbody(FIRST)).status_code == 200
        fake.respond_sse(answer("done"))
        r = mpost(url, mbody(SECOND))

    assert r.status_code == 200
    sent = json.loads(fake.requests[-1].body)["messages"]
    assert sent[-1]["content"].startswith("now indent it\n\n[palimnesis excerpts x2")
    assert b"palimnesis excerpts" not in r.content
    hosts = rows(s.db_path, "SELECT count(*) FROM excerpt_blocks WHERE status = 'selected'")
    assert hosts[0][0] >= 1


def test_notes_refresh_chat_upstream_for_messages_client(tmp_path):
    from .test_notes_http import BUDGET, NOTES

    def code(i):
        return "\n".join(f"def f{i}_{n}(x): return x * {n}  # {n}" for n in range(80))

    messages = []
    for t in range(3):
        messages.append({"role": "user", "content": f"Instruction {t}: implement part {t}."})
        for i in range(6):
            call = f"call_{t}_{i}"
            messages.append({"role": "assistant", "content": [
                {"type": "tool_use", "id": call, "name": "read", "input": {}}]})
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": call, "content": code(t * 6 + i)}]})
    messages.append({"role": "assistant", "content": [{"type": "text", "text": "done"}]})
    messages.append({"role": "user", "content": "Instruction 3: finish."})
    read = {"name": "read", "description": "read a file", "input_schema": {"type": "object"}}
    with stack(tmp_path, input_budget=BUDGET, notes_tokens=2048) as (fake, url, s):
        fake.respond_counted(NOTES)
        fake.respond_counted("visible answer")
        r = mpost(url, mbody(messages, tools=[read]))
        notes = rows(s.db_path, "SELECT status FROM notes_versions")

    assert r.status_code == 200 and b"visible answer" in r.content
    assert notes == [("committed",)]
    refresh, main = (json.loads(q.body) for q in fake.requests)
    assert refresh["messages"][-1]["role"] == "user" and "notes" in refresh["messages"][-1]["content"]
    assert any("palimnesis notes" in str(m.get("content")) for m in main["messages"])
    assert fake.requests[0].path == fake.requests[1].path == "/v1/chat/completions"
    assert b"palimnesis notes" not in r.content


def test_messages_deltas_forwarded_before_upstream_completes(tmp_path):
    slow = [chunk({"role": "assistant", "content": ""}), chunk({"content": "first "})] + \
        [(0.25, chunk({"content": f"{i} "})) for i in range(8)] + [chunk({}, "stop"), DONE]
    with stack(tmp_path) as (fake, url, s):
        fake.respond_sse(slow)
        seen = []
        with httpx.stream("POST", f"{url}/s/{SID}/v1/messages", content=mbody(FIRST), timeout=30) as r:
            for piece in r.iter_raw():
                seen.append((time.monotonic(), piece))
                if b'"text":"first "' in piece:
                    first_at = time.monotonic()

    end = seen[-1][0]
    assert end - first_at >= 1.5  # the first delta reached the client long before the end
    body = b"".join(p for _, p in seen)
    assert body.index(b"first ") < body.index(b"message_stop")


def test_messages_commit_before_forward(tmp_path):
    """Every text the client received is already archived when it arrives (D10, §11)."""
    with stack(tmp_path) as (fake, url, s):
        fake.respond_sse([chunk({"role": "assistant", "content": ""}), chunk({"content": "alpha "}),
                          (0.5, chunk({"content": "beta"})), chunk({}, "stop"), DONE])
        archived_at_first = []
        with httpx.stream("POST", f"{url}/s/{SID}/v1/messages", content=mbody(FIRST), timeout=30) as r:
            for piece in r.iter_raw():
                if b'"text":"alpha "' in piece and not archived_at_first:
                    archived_at_first = rows(s.db_path, "SELECT CAST(s.bytes AS TEXT) FROM segments s"
                                                        " JOIN blocks b USING (block_id) JOIN occurrences o"
                                                        " USING (occ_id) WHERE o.source = 'generated'")

    assert any("alpha" in t for (t,) in archived_at_first)


def test_messages_disconnect_closes_upstream_records_cancelled(tmp_path):
    slow = [chunk({"role": "assistant", "content": ""})] + \
        [(0.2, chunk({"content": f"{i} "})) for i in range(40)] + [chunk({}, "stop"), DONE]
    with stack(tmp_path) as (fake, url, s):
        fake.respond_sse(slow)
        with httpx.stream("POST", f"{url}/s/{SID}/v1/messages", content=mbody(FIRST), timeout=30) as r:
            for piece in r.iter_raw():
                if b"text_delta" in piece:
                    break
        deadline = time.monotonic() + 5
        while not fake.closed_streams and time.monotonic() < deadline:
            time.sleep(0.05)
        time.sleep(0.3)
        events = [k for (k,) in rows(s.db_path, "SELECT kind FROM events ORDER BY event_id")]

    assert fake.closed_streams and not fake.completed_streams
    assert "cancelled" in events and "turn_complete" not in events


def test_session_mismatch_on_messages_anthropic_envelope(tmp_path):
    with stack(tmp_path) as (fake, url, s):
        r = mpost(url, mbody(FIRST), headers={"X-Palimnesis-Session": "other-id"})
        missing = mpost(url, mbody(FIRST), path=f"{url}/v1/messages")

    for resp, code in ((r, "session_mismatch"), (missing, "session_required")):
        assert resp.status_code == 400
        doc = resp.json()
        assert doc["type"] == "error" and code in doc["error"]["message"]
    assert fake.requests == []


def test_messages_allowance_cap_and_length_stop(tmp_path):
    """§7: the client limit is ``max_tokens``; a length stop is ``max_tokens`` to the client."""
    with stack(tmp_path) as (fake, url, s):
        fake.respond_sse([chunk({"role": "assistant", "content": ""}), chunk({"content": "cut"}),
                          chunk({}, "length"), DONE])
        r = mpost(url, mbody(FIRST, max_tokens=50000))

    sent = json.loads(fake.requests[0].body)
    limit = sent.get("max_tokens", sent.get("max_completion_tokens"))
    assert limit is not None and limit <= 24_576  # the request-wide allowance cap (§7)
    stops = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")
             and '"message_delta"' in line]
    assert stops and stops[0]["delta"]["stop_reason"] == "max_tokens"


def test_hidden_tools_not_offered_on_messages(tmp_path):
    def code(i):
        return "\n".join(f"line {i}-{n} " * 6 for n in range(120))

    messages = [{"role": "user", "content": "go"}]
    for i in range(20):
        messages += [{"role": "assistant", "content": [{"type": "tool_use", "id": f"c{i}", "name": "read",
                                                        "input": {}}]},
                     {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"c{i}",
                                                   "content": code(i)}]}]
    messages += [{"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
                 {"role": "user", "content": "next"}]
    read = {"name": "read", "description": "read", "input_schema": {"type": "object"}}
    with stack(tmp_path, input_budget=8000, hidden_tools="t1") as (fake, url, s):
        fake.respond_sse(answer("fine"))
        r = mpost(url, mbody(messages, tools=[read]))
        fixed = rows(s.db_path, "SELECT count(*) FROM events WHERE kind = 'hidden_tools_fixed'")

    assert r.status_code == 200
    sent = json.loads(fake.requests[-1].body)
    assert [t["function"]["name"] for t in sent["tools"]] == ["read"]
    assert fixed[0][0] == 0


@pytest.mark.parametrize("crash_at", ["after_accept", "after_batch_1"])
def test_crash_recovery_on_messages(tmp_path, crash_at):
    """The crash points of ``test_crash_recovery`` through the Messages route: a crash after
    acceptance retries cleanly; a crash after a batch keeps the partial, and Pi's resend
    without it (O-4B-5) goes on."""
    from .test_crash_recovery import palimnesis_process

    fake = FakeUpstream()
    db = tmp_path / "archive.db"
    with serve(fake.app()) as upstream_url:
        fake.respond_sse([chunk({"role": "assistant", "content": ""}), chunk({"content": "one "}),
                          (0.3, chunk({"content": "two"})), chunk({}, "stop"), DONE])
        with palimnesis_process(upstream_url, db, crash_at=crash_at) as (url, proc):
            with pytest.raises(httpx.TransportError):
                mpost(url, mbody(FIRST))
            assert proc.wait(timeout=10) == 77
        fake.respond_sse(answer("again"))
        with palimnesis_process(upstream_url, db) as (url, _):
            if crash_at == "after_accept":
                r = mpost(url, mbody(FIRST))  # the same request, retried
            else:
                r = mpost(url, mbody(FIRST + [{"role": "user", "content": "go on"}]))

    assert r.status_code == 200, r.content[:300]
    assert b"message_stop" in r.content
    # after_accept dies before any upstream call: only the retry reaches it.
    assert len(fake.requests) == (1 if crash_at == "after_accept" else 2)
