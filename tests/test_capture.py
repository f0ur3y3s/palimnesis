"""Opt-in exchange capture: exact bytes for baselines and replay fixtures."""

from __future__ import annotations

import shutil

import httpx

from mnemon.capture import load_exchanges

from .test_passthrough import SSE, _eventually


def test_non_streaming_exchange_is_captured_exactly_with_secrets_redacted(
    capturing_stack,
):
    s = capturing_stack
    body = b'{"model":"m","messages":[{"role":"user","content":"\xc3\xa9"}]}'
    s.upstream.respond_json(b'{"id":"r1"}', status=201, headers={"x-request-id": "q"})

    httpx.post(
        f"{s.proxy_url}/s/sess-1/v1/chat/completions?x=1",
        content=body,
        headers={
            "authorization": "Bearer secret",
            "x-api-key": "k",
            "api-key": "k2",
            "proxy-authorization": "Basic p",
            "cookie": "c=1",
            "x-other": "o",
        },
    )

    [ex] = _eventually_exchanges(s.settings.capture_dir)
    assert ex.session == "sess-1"
    assert ex.method == "POST"
    assert ex.path == "/v1/chat/completions"
    assert ex.query == "x=1"
    assert ex.request_body == body
    assert ex.request_headers["authorization"] == "<redacted>"
    for secret in ("x-api-key", "api-key", "proxy-authorization", "cookie"):
        assert ex.request_headers[secret] == "<redacted>"
    assert ex.request_headers["x-other"] == "o"
    assert ex.status == 201
    assert ex.response_headers["x-request-id"] == "q"
    assert ex.response_body == b'{"id":"r1"}'
    assert ex.complete is True


def test_streamed_exchange_is_captured_byte_for_byte(capturing_stack):
    s = capturing_stack
    s.upstream.respond_sse(SSE)

    with httpx.stream("POST", f"{s.proxy_url}/s/sess-1/v1/chat/completions", content=b"{}") as r:
        r.read()

    [ex] = _eventually_exchanges(s.settings.capture_dir)
    assert ex.response_body == b"".join(SSE)
    assert ex.complete is True


def test_exchange_cut_short_by_client_disconnect_is_captured_as_incomplete(
    capturing_stack,
):
    s = capturing_stack
    s.upstream.respond_sse([b"data: 1\n\n"] + [(0.05, b"data: n\n\n")] * 200)

    with httpx.stream("POST", f"{s.proxy_url}/s/sess-1/v1/chat/completions", content=b"{}") as r:
        next(r.iter_raw())

    [ex] = _eventually_exchanges(s.settings.capture_dir)
    assert ex.complete is False
    assert ex.response_body.startswith(b"data: 1\n\n")


def test_exchanges_load_in_arrival_order(capturing_stack):
    s = capturing_stack
    for i in range(3):
        s.upstream.respond_json(b"{}")
        httpx.post(f"{s.proxy_url}/s/sess-1/v1/chat/completions", content=b'{"n":%d}' % i)

    assert _eventually(lambda: len(load_exchanges(s.settings.capture_dir)) == 3)
    assert [ex.request_body for ex in load_exchanges(s.settings.capture_dir)] == [
        b'{"n":0}',
        b'{"n":1}',
        b'{"n":2}',
    ]


def _eventually_exchanges(capture_dir, n: int = 1):
    assert _eventually(lambda: len(load_exchanges(capture_dir)) == n)
    return load_exchanges(capture_dir)


def test_capture_failure_never_breaks_the_relayed_response(stack_with_broken_capture):
    s = stack_with_broken_capture
    s.upstream.respond_sse(SSE)

    with httpx.stream("POST", f"{s.proxy_url}/s/sess-1/v1/chat/completions", content=b"{}") as r:
        body = r.read()

    assert r.status_code == 200
    assert body == b"".join(SSE)


def test_nothing_is_written_to_disk_without_a_capture_dir(stack, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stack.upstream.respond_sse(SSE)

    with httpx.stream("POST", f"{stack.proxy_url}/s/sess-1/v1/chat/completions", content=b"{}") as r:
        r.read()

    assert list(tmp_path.iterdir()) == []


def test_response_write_failure_never_breaks_the_relayed_response(capturing_stack):
    s = capturing_stack
    s.upstream.respond_sse([b"data: 1\n\n", (0.5, b"data: 2\n\n"), b"data: [DONE]\n\n"])

    with httpx.stream("POST", f"{s.proxy_url}/s/sess-1/v1/chat/completions", content=b"{}") as r:
        chunks = r.iter_raw()
        first = next(chunks)
        # Replace the exchange folder with a file so the response write fails.
        [folder] = (s.settings.capture_dir / "sess-1").iterdir()
        shutil.rmtree(folder)
        folder.write_text("blocker")
        rest = b"".join(chunks)

    assert r.status_code == 200
    assert first + rest == b"data: 1\n\ndata: 2\n\ndata: [DONE]\n\n"
