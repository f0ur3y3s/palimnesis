"""Proxy admission (O4; Phase 4B S6; contracts §5, §8).

One FIFO with capacity Q feeds the upstream's slots (``total_slots`` from ``/props``, one on
pythia, D83). A full queue is a 429 before acceptance. A streaming request gets its
response headers within H of arrival, even while queued or while its notes refresh runs,
then the client protocol's keepalive whenever K passes with nothing sent (a comment on
Chat, ``event: ping`` on Messages). Queue time counts against D. A request holds the slot
across all of its upstream calls. The upstream's ``/status`` guards dispatch, because
other clients share it.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager

import httpx
import pytest

from palimnesis.api import create_app
from palimnesis.config import Settings

from .archive_helpers import DONE, answer, chunk
from .fake_upstream import FakeUpstream
from .servers import serve


@contextmanager
def stack(tmp_path, **settings):
    fake = FakeUpstream()
    with serve(fake.app()) as upstream_url:
        s = Settings(upstream_base_url=upstream_url, db_path=tmp_path / "archive.db", **settings)
        with serve(create_app(s), palimnesis=True) as proxy_url:
            yield fake, proxy_url, s


def chat(text: str, stream: bool = True) -> bytes:
    return json.dumps({"model": "m", "stream": stream,
                       "messages": [{"role": "user", "content": text}]}).encode()


def messages(text: str) -> bytes:
    return json.dumps({"model": "m", "max_tokens": 256, "stream": True,
                       "messages": [{"role": "user", "content": text}]}).encode()


def slow(text: str, seconds: float, pieces: int = 5) -> list:
    return ([chunk({"role": "assistant", "content": ""})]
            + [(seconds / pieces, chunk({"content": f"{text}{i} "})) for i in range(pieces)]
            + [chunk({}, "stop"), DONE])


class Call:
    """A request in a thread, recording when headers and the body arrived."""

    def __init__(self, url: str, session: str, payload: bytes, path="/v1/chat/completions",
                 timeout: float = 30):
        self.headers_at = self.done_at = None
        self.response = self.error = None
        self.body = b""
        self.t0 = time.monotonic()

        def run():
            try:
                with httpx.stream("POST", f"{url}/s/{session}{path}", content=payload,
                                  timeout=timeout) as r:
                    self.headers_at = time.monotonic() - self.t0
                    self.response = r
                    for piece in r.iter_raw():
                        self.body += piece
                self.done_at = time.monotonic() - self.t0
            except Exception as e:  # noqa: BLE001 - surfaced by the test
                self.error = e

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def join(self, timeout: float = 30) -> "Call":
        self.thread.join(timeout)
        return self


def requests_count(db) -> int:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT count(*) FROM requests").fetchone()[0]
    finally:
        conn.close()


def test_fifo_one_dispatch_across_sessions(tmp_path):
    with stack(tmp_path) as (fake, url, s):
        fake.respond_sse(slow("a", 1.0))
        fake.respond_sse(answer("b"))
        fake.respond_sse(answer("c"))
        a = Call(url, "s-a", chat("first"))
        time.sleep(0.2)
        b = Call(url, "s-b", chat("second"))
        time.sleep(0.1)
        c = Call(url, "s-c", chat("third"))
        time.sleep(0.3)
        in_flight = len(fake.requests)
        for call in (a, b, c):
            call.join()

    assert in_flight == 1  # B and C wait for A's slot
    assert [json.loads(r.body)["messages"][-1]["content"] for r in fake.requests] == [
        "first", "second", "third"]
    assert all(call.response.status_code == 200 for call in (a, b, c))
    assert a.t0 + a.done_at < b.t0 + b.done_at < c.t0 + c.done_at


def test_queue_full_429_retry_after(tmp_path):
    with stack(tmp_path, queue_capacity=1) as (fake, url, s):
        fake.respond_sse(slow("a", 1.0))
        fake.respond_sse(answer("b"))
        a = Call(url, "s-a", chat("first"))
        time.sleep(0.2)
        b = Call(url, "s-b", chat("second"))
        time.sleep(0.2)
        full = httpx.post(f"{url}/s/s-c/v1/chat/completions", content=chat("third"), timeout=10)
        full_messages = httpx.post(f"{url}/s/s-d/v1/messages", content=messages("fourth"),
                                   timeout=10)
        archived_during = requests_count(s.db_path)
        a.join(), b.join()

    assert full.status_code == 429
    assert full.json()["error"]["code"] == "queue_full"
    assert int(full.headers["retry-after"]) > 0
    assert full.headers["x-should-retry"] == "true"
    assert full_messages.status_code == 429 and full_messages.json()["type"] == "error"
    assert archived_during == 2  # A and B; the refused requests were never accepted
    assert len(fake.requests) == 2


@pytest.mark.parametrize("protocol", ["chat", "messages"])
def test_keepalive_comment_chat_ping_messages_every_K(tmp_path, protocol):
    path, payload = (("/v1/chat/completions", chat("second")) if protocol == "chat"
                     else ("/v1/messages", messages("second")))
    with stack(tmp_path, header_wait_s=0.3, keepalive_s=0.25) as (fake, url, s):
        fake.respond_sse(slow("a", 1.5))
        fake.respond_sse(answer("b"))
        a = Call(url, "s-a", chat("first"))
        time.sleep(0.1)
        b = Call(url, "s-b", payload, path=path)
        a.join(), b.join()

    assert b.response.status_code == 200
    assert b.headers_at < 0.9 and b.headers_at < a.done_at  # within H, while still queued
    assert b.response.headers["x-should-retry"] == "false"
    assert b.response.headers["content-type"].startswith("text/event-stream")
    if protocol == "chat":
        assert b.body.count(b": keepalive\n\n") >= 3
        assert b'"b"' in b.body and b.body.rstrip().endswith(b"data: [DONE]")
    else:
        assert b.body.count(b"event: ping\n") >= 3
        assert b.body.rstrip().endswith(b'{"type":"message_stop"}')
        assert b.body.count(b"event: message_start") == 1


def test_headers_within_H_while_queued_and_during_notes_refresh(tmp_path):
    from .test_notes_http import BUDGET, NOTES, _body, _messages

    with stack(tmp_path, header_wait_s=0.3, keepalive_s=0.25, input_budget=BUDGET,
               notes_tokens=2048) as (fake, url, s):
        fake.respond_sse([(1.2, chunk({"content": NOTES})), chunk({}, "stop"), DONE])  # refresh
        fake.respond_counted("visible answer")
        call = Call(url, "s-notes", _body(_messages())).join()

    assert call.response.status_code == 200
    assert call.headers_at < 0.9
    assert call.body.count(b": keepalive\n\n") >= 3
    assert b"visible answer" in call.body and len(fake.requests) == 2


def test_an_error_after_early_headers_is_an_in_stream_event(tmp_path):
    with stack(tmp_path, header_wait_s=0.2, keepalive_s=0.2) as (fake, url, s):
        fake.respond_json(b'{"error":{"code":503,"message":"Loading model","type":"unavailable_error"}}',
                          status=503, delay=0.8)
        call = Call(url, "s-err", chat("hi")).join()

    assert call.response.status_code == 200  # headers went out before the upstream answered
    last = call.body.rstrip().split(b"\n\n")[-1]
    assert last.startswith(b"data: ") and b"Loading model" in last


def test_queue_time_counts_against_D_and_expired_entry_never_dispatched(tmp_path):
    with stack(tmp_path, deadline_s=0.6) as (fake, url, s):
        fake.status_busy = True  # another client holds the upstream
        r = httpx.post(f"{url}/s/s-x/v1/chat/completions", content=chat("hi", stream=False),
                       timeout=10)

    assert r.status_code == 504 and r.json()["error"]["code"] == "deadline_exceeded"
    assert fake.requests == []


def test_cancelled_queued_entry_never_dispatched(tmp_path):
    with stack(tmp_path) as (fake, url, s):
        fake.respond_sse(slow("a", 1.0))
        fake.respond_sse(answer("c"))
        a = Call(url, "s-a", chat("first"))
        time.sleep(0.2)
        b = Call(url, "s-b", chat("second"), timeout=0.3)  # gives up while queued
        time.sleep(0.5)
        c = Call(url, "s-c", chat("third"))
        a.join(), b.join(), c.join()

    assert b.error is not None
    assert [json.loads(r.body)["messages"][-1]["content"] for r in fake.requests] == [
        "first", "third"]


def test_slot_held_across_notes_refresh_and_hidden_continuation(tmp_path):
    from .test_notes_http import BUDGET, NOTES, _body, _messages

    with stack(tmp_path, input_budget=BUDGET, notes_tokens=2048) as (fake, url, s):
        fake.respond_sse([(0.6, chunk({"content": NOTES})), chunk({}, "stop"), DONE])
        fake.respond_counted("visible answer")
        fake.respond_sse(answer("other"))
        a = Call(url, "s-notes", _body(_messages()))
        time.sleep(0.2)
        b = Call(url, "s-other", chat("other session"))
        a.join(), b.join()

    contents = [json.loads(r.body)["messages"][-1].get("content") for r in fake.requests]
    assert len(contents) == 3 and contents[-1] == "other session"


def test_status_guard_waits_for_foreign_work(tmp_path):
    with stack(tmp_path) as (fake, url, s):
        fake.status_busy = True
        fake.respond_sse(answer("a"))
        a = Call(url, "s-a", chat("first"))
        time.sleep(0.6)
        dispatched_while_busy = len(fake.requests)
        fake.status_busy = False
        a.join()

    assert dispatched_while_busy == 0
    assert a.response.status_code == 200 and len(fake.requests) == 1
    assert fake.status_requests >= 2
