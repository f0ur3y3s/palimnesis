"""Recorded upstream streams and harness exchanges relay byte-for-byte.

Fixtures are real captures: Strata SSE (`eval/probes/fixtures/*.sse`) covering
reasoning, tool deltas, parallel tools, length stops, keepalives and a stream
truncated by a server death; and OpenCode 2.1.4 exchanges captured live
(`eval/fixtures/opencode-2.1.4/live/exchanges`). Responses are re-chunked at
small odd sizes so chunk boundaries split events and multibyte characters.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from palimnesis.capture import load_exchanges

ROOT = Path(__file__).resolve().parents[1]
STRATA_SSE = sorted((ROOT / "eval" / "probes" / "fixtures").glob("*.sse"))
OPENCODE_LIVE = load_exchanges(ROOT / "eval" / "fixtures" / "opencode-2.1.4" / "live" / "exchanges")


def _rechunk(data: bytes, size: int = 7) -> list[bytes]:
    return [data[i : i + size] for i in range(0, len(data), size)]


def _relay(stack, session: str, path: str, body: bytes, response: bytes) -> bytes:
    stack.upstream.respond_sse(_rechunk(response))
    with httpx.stream(
        "POST", f"{stack.proxy_url}/s/{session}{path}", content=body
    ) as r:
        assert r.status_code == 200
        return r.read()


def test_fixture_sets_are_present():
    assert len(STRATA_SSE) >= 10
    assert len(OPENCODE_LIVE) == 10


@pytest.mark.parametrize("fixture", STRATA_SSE, ids=lambda p: p.stem)
def test_recorded_strata_stream_relays_unchanged(stack, fixture):
    recorded = fixture.read_bytes()
    path = "/v1/messages" if fixture.stem.startswith("sse_an") else "/v1/chat/completions"

    assert _relay(stack, "fixtures", path, b"{}", recorded) == recorded


@pytest.mark.parametrize("ex", OPENCODE_LIVE, ids=lambda e: str(e.started_ns))
def test_recorded_opencode_exchange_relays_unchanged(stack, ex):
    received = _relay(stack, ex.session, ex.path, ex.request_body, ex.response_body)

    assert received == ex.response_body
    [got] = stack.upstream.requests
    assert got.path == ex.path
    assert got.body == ex.request_body
