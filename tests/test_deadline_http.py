"""Request-wide deadline D after acceptance (contracts §5; docs/plans/phase3.md S8)."""

from __future__ import annotations

import json
import socket
import time

import httpx

from .test_view_http import rows, view_stack

SID = "deadline-1"


def _body(stream: bool) -> bytes:
    return json.dumps({"model": "m", "stream": stream, "max_completion_tokens": 64,
                       "messages": [{"role": "user", "content": "count slowly"}]}).encode()


def _chunk(text: str) -> bytes:
    return b"data: " + json.dumps({"choices": [{"index": 0, "delta": {"content": text}}]}).encode() + b"\n\n"


def _events(settings):
    return [(k, json.loads(p)) for k, p in rows(
        settings, "SELECT kind, payload FROM events WHERE kind NOT IN ('upstream_call')"
                  " ORDER BY event_id")]


def test_a_deadline_before_the_first_byte_is_a_504_and_releases_the_upstream(tmp_path):
    with view_stack(tmp_path, deadline_s=0.5) as (fake, url, settings):
        fake.respond_json(b'{"choices":[]}', delay=5.0)
        t = time.monotonic()
        r = httpx.post(f"{url}/s/{SID}/v1/chat/completions", content=_body(False), timeout=10)
        elapsed = time.monotonic() - t
        deadline = time.monotonic() + 3
        while not fake.abandoned and time.monotonic() < deadline:
            time.sleep(0.05)

    assert r.status_code == 504
    assert r.json()["error"]["code"] == "deadline_exceeded"
    assert r.headers["x-should-retry"] == "false"
    assert elapsed < 2.5
    assert fake.abandoned  # the upstream saw the proxy leave
    failed = [p for k, p in _events(settings) if k == "attempt_failed"]
    assert failed and failed[-1]["reason"] == "deadline_exceeded"


def test_a_deadline_mid_stream_ends_with_an_error_event_and_closes_the_upstream(tmp_path):
    chunks = [_chunk("one ")] + [(0.3, _chunk(f"{i} ")) for i in range(30)] + [b"data: [DONE]\n\n"]
    with view_stack(tmp_path, deadline_s=1.0) as (fake, url, settings):
        fake.respond_sse(chunks)
        with httpx.stream("POST", f"{url}/s/{SID}/v1/chat/completions", content=_body(True),
                          timeout=10) as r:
            text = b"".join(r.iter_raw()).decode()
        deadline = time.monotonic() + 3
        while not fake.closed_streams and time.monotonic() < deadline:
            time.sleep(0.05)

    assert r.status_code == 200
    assert "one " in text and "[DONE]" not in text
    assert '"deadline_exceeded"' in text.rstrip().splitlines()[-1]
    assert fake.closed_streams and not fake.completed_streams
    failed = [p for k, p in _events(settings) if k == "attempt_failed"]
    assert failed and failed[-1]["reason"] == "deadline_exceeded"


def test_a_client_that_stops_reading_cannot_hold_the_upstream_past_the_deadline(tmp_path):
    # ~8 s of paced output, 2 KB per chunk: still producing when the deadline hits.
    big = [(0.02, _chunk("x" * 2000)) for _ in range(400)] + [b"data: [DONE]\n\n"]
    with view_stack(tmp_path, deadline_s=1.0) as (fake, url, settings):
        fake.respond_sse(big)
        host, port = url.removeprefix("http://").split(":")
        sock = socket.create_connection((host, int(port)))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        body = _body(True)
        sock.sendall(b"POST /s/" + SID.encode() + b"/v1/chat/completions HTTP/1.1\r\n"
                     b"host: x\r\ncontent-type: application/json\r\n"
                     b"content-length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
        # Never read: the proxy's sends block once the socket buffers fill.
        deadline = time.monotonic() + 6
        while not fake.closed_streams and time.monotonic() < deadline:
            time.sleep(0.05)
        sock.close()

    assert fake.closed_streams and not fake.completed_streams
    deadline = time.monotonic() + 3
    failed = []
    while not failed and time.monotonic() < deadline:
        failed = [p for k, p in _events(settings) if k in ("attempt_failed", "delivery_failed")]
        time.sleep(0.05)
    assert failed and failed[-1]["reason"] == "deadline_exceeded"


def test_requests_within_the_deadline_are_unaffected(tmp_path):
    with view_stack(tmp_path, deadline_s=5.0) as (fake, url, settings):
        fake.respond_sse([_chunk("hi"), b'data: {"choices":[{"index":0,"delta":{},'
                          b'"finish_reason":"stop"}]}\n\n', b"data: [DONE]\n\n"])
        with httpx.stream("POST", f"{url}/s/{SID}/v1/chat/completions", content=_body(True),
                          timeout=10) as r:
            text = b"".join(r.iter_raw()).decode()

    assert "[DONE]" in text
    assert [k for k, _ in _events(settings)][-1] == "delivery_completed"
