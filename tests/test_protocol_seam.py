"""The client-protocol seam (Phase 4B S1).

Archive mode picks a ``ClientProtocol`` by request path. The protocol parses the body
into the neutral form, names the endpoint archived on the request row, and makes the
emitter that turns the upstream's Chat output into the client's bytes. The upstream
call is always Chat. Core modules never key off a harness name or ``User-Agent``.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from palimnesis import protocols

from .archive_helpers import answer, body, chunk, lifecycle_stack, user

SRC = Path(__file__).resolve().parents[1] / "src" / "palimnesis"
HARNESS_TOKENS = {"opencode", "claude", "pi"}


def _tokens(identifier: str) -> set[str]:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", identifier).lower().split("_")
    return {w for w in words if w}


def _identifiers(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield node.attr
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node.name
        elif isinstance(node, ast.arg):
            yield node.arg
        elif isinstance(node, ast.alias):
            yield from (node.name.split(".") + ([node.asname] if node.asname else []))
        elif isinstance(node, ast.keyword) and node.arg:
            yield node.arg


def test_core_never_keys_off_harness_or_user_agent():
    """Position 4: harness specifics live in adapters (``integrations/``), never in core.
    No core identifier names a harness, and no core code reads ``User-Agent``."""
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith("integrations/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for name in _identifiers(tree):
            if _tokens(name) & HARNESS_TOKENS:
                offenders.append(f"{rel}: identifier {name}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
                value = node.value.decode("latin-1") if isinstance(node.value, bytes) else node.value
                if value.strip().lower() == "user-agent":
                    offenders.append(f"{rel}: reads {value!r}")
    assert offenders == []


def test_each_protocol_serves_its_own_endpoint_and_nothing_else():
    assert protocols.for_path("/v1/chat/completions") is protocols.CHAT
    assert protocols.for_path("/v1/messages") is protocols.MESSAGES
    assert protocols.CHAT.endpoint == protocols.UPSTREAM_ENDPOINT
    for path in ("/v1/messages/count_tokens", "/v1/messages/batches", "/v1/completions",
                 "/v1/chat/completions/", "/v1/responses"):
        assert protocols.for_path(path) is None


class TaggingEmitter(protocols.ChatEmitter):
    """Marks every byte string it emits, so the test can see the emitter was used."""

    def feed(self, data: bytes) -> bytes:
        return b"".join(b": via-test\n" + e + b"\n\n" for e in data.split(b"\n\n") if e)

    def body(self, data: bytes) -> bytes:
        return json.dumps({"wrapped": json.loads(data)}).encode()

    def error(self, code: str, message: str) -> bytes:
        return b"event: test-error\ndata: " + code.encode() + b"\n\n"


TEST_PATH = "/v1/test/chat"


@pytest.fixture
def test_protocol(monkeypatch):
    parsed: list[bytes] = []

    def parse(raw: bytes):
        parsed.append(raw)
        return protocols.CHAT.parse(raw)

    proto = replace(protocols.CHAT, name="test", endpoint=TEST_PATH, parse=parse,
                    emitter=TaggingEmitter)
    monkeypatch.setitem(protocols._BY_ENDPOINT, TEST_PATH, proto)
    return parsed


def _post(stack, path: str, payload: bytes, query: str = "", session: str = "seam-1"):
    import httpx

    url = f"{stack.proxy_url}/s/{session}{path}" + (f"?{query}" if query else "")
    with httpx.stream("POST", url, content=payload, timeout=30) as r:
        r.read()
    return r


def _endpoints(stack) -> list[str]:
    with stack.db() as c:
        return [e for (e,) in c.execute("SELECT endpoint FROM requests ORDER BY arrived_at")]


def test_archive_route_dispatches_by_path(tmp_path, test_protocol):
    with lifecycle_stack(tmp_path) as stack:
        stack.upstream.respond_sse(answer("hello"))
        r = _post(stack, TEST_PATH, body([user("hi")]), query="beta=true")

        assert r.status_code == 200
        assert b": via-test\n" in r.content and b"hello" in r.content
        [sent] = stack.upstream.requests
        assert (sent.path, sent.query) == ("/v1/chat/completions", "")
        assert _endpoints(stack) == [TEST_PATH]

        # The Chat route is unchanged: upstream bytes relayed as they came, query kept.
        stack.upstream.respond_sse(answer("plain"))
        r = _post(stack, "/v1/chat/completions", body([user("hi")]), query="x=1",
                  session="seam-2")
        assert r.status_code == 200 and b"via-test" not in r.content
        assert (stack.upstream.requests[-1].path, stack.upstream.requests[-1].query) == (
            "/v1/chat/completions", "x=1")


@pytest.mark.parametrize("path, anthropic", [("/v1/messages/batches", True),
                                             ("/v1/completions", False)])
def test_a_path_with_no_protocol_is_refused_before_acceptance(tmp_path, path, anthropic):
    with lifecycle_stack(tmp_path) as stack:
        r = _post(stack, path, body([user("hi")]))
        assert stack.upstream.requests == []
        assert stack.count("requests") == 0

    assert r.status_code == 400
    error = r.json()["error"]
    if anthropic:
        assert r.json()["type"] == "error" and "unsupported_feature" in error["message"]
    else:
        assert error["code"] == "unsupported_feature"


def test_a_non_streaming_body_goes_through_the_emitter(tmp_path, test_protocol):
    upstream_body = {"id": "x", "object": "chat.completion", "model": "m",
                     "choices": [{"index": 0, "finish_reason": "stop",
                                  "message": {"role": "assistant", "content": "hello"}}]}
    with lifecycle_stack(tmp_path) as stack:
        stack.upstream.respond_json(json.dumps(upstream_body).encode())
        r = _post(stack, TEST_PATH, body([user("hi")], stream=False))

    assert r.status_code == 200
    assert r.json() == {"wrapped": upstream_body}


def test_an_in_stream_failure_uses_the_emitters_error_event(tmp_path, test_protocol):
    with lifecycle_stack(tmp_path) as stack:
        stack.upstream.respond_sse([chunk({"role": "assistant", "content": ""}),
                                    chunk({"content": "partial"})])  # EOF without [DONE]
        r = _post(stack, TEST_PATH, body([user("hi")]))

    assert r.status_code == 200
    assert r.content.endswith(b"event: test-error\ndata: upstream_stream_failed\n\n")
    assert b'"error"' not in r.content


def test_a_restart_replans_with_the_protocol_of_the_archived_request(tmp_path, test_protocol):
    """``ledger.replan`` reparses an archived raw body with the protocol named by its row."""
    from palimnesis.archive import ledger

    with lifecycle_stack(tmp_path) as stack:
        stack.upstream.respond_sse(answer("hello"))
        assert _post(stack, TEST_PATH, body([user("hi")])).status_code == 200
        with stack.db() as c:
            request_id, branch_id = c.execute(
                "SELECT request_id, branch_id FROM requests").fetchone()
            test_protocol.clear()
            req, _ = ledger.replan(c, branch_id, request_id, 2**62)

    assert len(test_protocol) == 1 and req.messages[0].role == "user"
