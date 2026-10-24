"""Phase 0 passthrough: the proxy is byte-transparent apart from session routing."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest


def test_post_body_reaches_upstream_unchanged_with_session_prefix_stripped(stack):
    # Deliberately odd formatting: passthrough must not re-serialize JSON.
    body = b'{ "model":"m",\n  "messages":[{"role":"user","content":"h\\u00e9 \xc3\xa9"}] }'
    stack.upstream.respond_json(b'{"id":"x"}')

    r = httpx.post(
        f"{stack.proxy_url}/s/sess-1/v1/chat/completions",
        content=body,
        headers={"content-type": "application/json"},
    )

    assert r.status_code == 200
    assert r.content == b'{"id":"x"}'
    [got] = stack.upstream.requests
    assert got.method == "POST"
    assert got.path == "/v1/chat/completions"
    assert got.body == body


def test_client_headers_and_query_are_forwarded_but_mnemon_headers_are_not(stack):
    stack.upstream.respond_json(b"{}")

    httpx.post(
        f"{stack.proxy_url}/s/sess-1/v1/chat/completions?beta=true",
        content=b"{}",
        headers={
            "authorization": "Bearer local",
            "x-stainless-retry-count": "0",
            "anthropic-version": "2023-06-01",
            "x-mnemon-session": "sess-1",
        },
    )

    [got] = stack.upstream.requests
    assert got.query == "beta=true"
    assert got.headers["authorization"] == "Bearer local"
    assert got.headers["x-stainless-retry-count"] == "0"
    assert got.headers["anthropic-version"] == "2023-06-01"
    assert "x-mnemon-session" not in got.headers
    assert got.headers["host"] == stack.upstream_url.removeprefix("http://")


def test_upstream_error_status_headers_and_body_are_relayed_unchanged(stack):
    error = b'{"error":{"message":"context overflow","type":"invalid_request_error"}}'
    stack.upstream.respond_json(error, status=400, headers={"x-request-id": "abc"})

    r = httpx.post(f"{stack.proxy_url}/s/sess-1/v1/chat/completions", content=b"{}")

    assert r.status_code == 400
    assert r.content == error
    assert r.headers["x-request-id"] == "abc"
    assert r.headers["content-type"] == "application/json"


def test_header_only_session_routes_unprefixed_paths(stack):
    stack.upstream.respond_json(b"{}")

    r = httpx.post(
        f"{stack.proxy_url}/v1/chat/completions",
        content=b"{}",
        headers={"x-mnemon-session": "sess-1"},
    )

    assert r.status_code == 200
    [got] = stack.upstream.requests
    assert got.path == "/v1/chat/completions"


def test_mismatched_path_and_header_session_is_rejected_before_upstream(stack):
    r = httpx.post(
        f"{stack.proxy_url}/s/sess-1/v1/chat/completions",
        content=b"{}",
        headers={"x-mnemon-session": "sess-2"},
    )

    assert r.status_code == 400
    assert r.json()["error"]["code"] == "session_mismatch"
    assert r.json()["error"]["type"] == "invalid_request_error"
    assert r.headers["x-should-retry"] == "false"
    assert stack.upstream.requests == []


def test_request_without_session_is_rejected_before_upstream(stack):
    r = httpx.post(f"{stack.proxy_url}/v1/chat/completions", content=b"{}")

    assert r.status_code == 400
    assert r.json()["error"]["code"] == "session_required"
    assert stack.upstream.requests == []


def test_rejections_on_anthropic_routes_use_the_anthropic_error_shape(stack):
    r = httpx.post(f"{stack.proxy_url}/s/bad..id/v1/messages", content=b"{}")

    assert r.status_code == 400
    assert r.json()["type"] == "error"
    assert r.json()["error"]["type"] == "invalid_request_error"
    assert "Session identifiers" in r.json()["error"]["message"]
    assert stack.upstream.requests == []


SSE = [
    b'data: {"choices":[{"delta":{"reasoning_content":"th"}}]}\n\n',
    b'data: {"choices":[{"delta":{"content":"h\xc3',  # split multibyte char
    b'\xa9"}}]}\n\n',
    b": keepalive\n\n",
    b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
    b"data: [DONE]\n\n",
]


def test_sse_stream_is_relayed_byte_for_byte(stack):
    stack.upstream.respond_sse(SSE)

    with httpx.stream(
        "POST", f"{stack.proxy_url}/s/sess-1/v1/chat/completions", content=b"{}"
    ) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        received = b"".join(r.iter_raw())

    assert received == b"".join(SSE)


def test_sse_chunks_reach_the_client_before_the_upstream_finishes(stack):
    stack.upstream.respond_sse([b"data: first\n\n", (1.5, b"data: [DONE]\n\n")])

    start = time.monotonic()
    with httpx.stream(
        "POST", f"{stack.proxy_url}/s/sess-1/v1/chat/completions", content=b"{}"
    ) as r:
        first = next(r.iter_raw())
        first_at = time.monotonic() - start

    assert first == b"data: first\n\n"
    assert first_at < 1.0


def test_client_disconnect_closes_the_upstream_stream(stack):
    slow = [b"data: 1\n\n"] + [(0.05, b"data: n\n\n")] * 200
    stack.upstream.respond_sse(slow)

    with httpx.stream(
        "POST", f"{stack.proxy_url}/s/sess-1/v1/chat/completions", content=b"{}"
    ) as r:
        next(r.iter_raw())
    # Leaving the block closes the client connection mid-stream.

    assert _eventually(lambda: stack.upstream.closed_streams == ["/v1/chat/completions"])
    assert stack.upstream.completed_streams == []


def _eventually(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


# --- Phase 0 protocol review findings -------------------------------------


def test_client_disconnect_before_upstream_headers_abandons_the_upstream_request(stack):
    # Non-streaming upstreams send headers only when generation ends; a client
    # that leaves earlier must not keep the upstream slot busy.
    stack.upstream.respond_json(b"{}", delay=5.0)

    with pytest.raises(httpx.ReadTimeout):
        httpx.post(
            f"{stack.proxy_url}/s/sess-1/v1/chat/completions", content=b"{}", timeout=0.3
        )

    assert _eventually(lambda: stack.upstream.abandoned == ["/v1/chat/completions"])


def test_unreachable_upstream_returns_a_shaped_502(dead_upstream_stack):
    r = httpx.post(
        f"{dead_upstream_stack.proxy_url}/s/sess-1/v1/chat/completions", content=b"{}"
    )

    assert r.status_code == 502
    assert r.json()["error"]["code"] == "upstream_unreachable"
    assert r.headers["x-should-retry"] == "true"


def test_unreachable_upstream_on_anthropic_route_uses_anthropic_shape(dead_upstream_stack):
    r = httpx.post(f"{dead_upstream_stack.proxy_url}/s/sess-1/v1/messages", content=b"{}")

    assert r.status_code == 502
    assert r.json()["type"] == "error"


def test_query_string_reaches_upstream_byte_for_byte(stack):
    stack.upstream.respond_json(b"{}")

    httpx.post(
        httpx.URL(f"{stack.proxy_url}/s/sess-1/v1/x", query=b"flag&d=%7e&e=a+b&e=c"),
        content=b"{}",
    )

    [got] = stack.upstream.requests
    assert got.query == "flag&d=%7e&e=a+b&e=c"


def test_proxy_adds_no_request_headers_of_its_own(stack):
    stack.upstream.respond_json(b"{}")

    with httpx.Client() as client:
        client.headers.clear()  # send only what this test names
        client.post(
            f"{stack.proxy_url}/s/sess-1/v1/chat/completions",
            content=b"{}",
            headers={"x-custom": "1"},
        )

    [got] = stack.upstream.requests
    assert set(got.headers) == {"host", "content-length", "x-custom"}


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS", "GET", "DELETE"])
def test_every_method_is_relayed(stack, method):
    stack.upstream.respond_json(b"", status=200, headers={"x-probe": "ok"})

    r = httpx.request(method, f"{stack.proxy_url}/s/sess-1/api/hello")

    assert r.status_code == 200
    assert r.headers["x-probe"] == "ok"
    [got] = stack.upstream.requests
    assert (got.method, got.path) == (method, "/api/hello")


def test_response_headers_keep_repeats_and_are_not_duplicated_by_the_proxy(stack):
    stack.upstream.respond_json(
        b"{}", extra_headers=[("set-cookie", "a=1"), ("set-cookie", "b=2")]
    )

    r = httpx.post(f"{stack.proxy_url}/s/sess-1/v1/chat/completions", content=b"{}")

    assert r.headers.get_list("set-cookie") == ["a=1", "b=2"]
    assert len(r.headers.get_list("server")) == 1
    assert len(r.headers.get_list("date")) == 1


def test_encoded_slash_in_session_segment_is_rejected_not_rerouted(stack):
    r = httpx.post(f"{stack.proxy_url}/s/a%2Fb/v1/chat/completions", content=b"{}")

    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_session_id"
    assert stack.upstream.requests == []


def test_bare_session_prefix_routes_to_upstream_root(stack):
    stack.upstream.respond_json(b"{}")

    r = httpx.get(f"{stack.proxy_url}/s/sess-1")

    assert r.status_code == 200
    [got] = stack.upstream.requests
    assert got.path == "/"


def test_repeated_session_headers_that_disagree_are_rejected(stack):
    r = httpx.post(
        f"{stack.proxy_url}/v1/chat/completions",
        content=b"{}",
        headers=[("x-mnemon-session", "sess-1"), ("x-mnemon-session", "sess-2")],
    )

    assert r.status_code == 400
    assert r.json()["error"]["code"] == "session_mismatch"
    assert stack.upstream.requests == []


async def test_proxy_refuses_requests_without_lifespan_startup():
    from mnemon.api import create_app
    from mnemon.config import Settings

    app = create_app(Settings(upstream_base_url="http://127.0.0.1:1"))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/s/sess-1/v1/models",
        "raw_path": b"/s/sess-1/v1/models",
        "query_string": b"",
        "headers": [],
    }

    messages = [{"type": "http.request", "body": b"", "more_body": False}]

    async def receive():
        # Like a server: the body, then block until the client leaves.
        if messages:
            return messages.pop()
        await asyncio.Event().wait()

    async def send(message):
        pass

    with pytest.raises(RuntimeError, match="lifespan"):
        await app(scope, receive, send)
