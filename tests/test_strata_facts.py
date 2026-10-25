"""Upstream facts (contracts §1.1, §1.2): /props read, staleness, pin comparison, canary.

HTTP runs against tests/fake_upstream.py on real loopback sockets. Expected counts for
the canary come from eval/probes/fixtures/count_tokens.json (the live server's answers).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from palimnesis.upstreams.strata import errors, pins, tokens
from palimnesis.upstreams.strata import facts as upstream_facts
from palimnesis.upstreams.strata.facts import UpstreamState

from .fake_upstream import FakeUpstream
from .servers import serve

PROBES = Path(__file__).resolve().parents[1] / "eval" / "probes" / "fixtures"
SERVER_COUNTS = {k: v["body"]["input_tokens"]
                 for k, v in json.loads((PROBES / "count_tokens.json").read_text(encoding="utf-8")).items()
                 if v["status"] == 200}


@pytest.fixture
def fake():
    f = FakeUpstream()
    with serve(f.app()) as url:
        f.url = url
        yield f


def _strata_count_tokens(body: dict) -> int:
    """Answer like the recorded server: look the canary body up in count_tokens.json."""
    for name, case in upstream_facts.CANARY_CASES:
        if body == {"model": upstream_facts.CANARY_MODEL, **case}:
            return SERVER_COUNTS[name]
    raise AssertionError(f"unexpected count_tokens body {body}")


async def test_props_read_at_startup(fake):
    fake.props_n_ctx = 32768
    async with httpx.AsyncClient() as client:
        facts = await upstream_facts.fetch_facts(client, fake.url)
    assert facts.n_ctx == 32768
    assert facts.build_info == "Strata 0.1.48"
    assert facts.chat_template_sha256 == "12827f24b742ea4e80cdc12dbcf9622227056b9f797252a3149263d4f9aaadce"
    assert fake.props_requests == 1
    assert fake.requests == []  # /props never consumes or records into the response script


async def test_props_does_not_consume_scripted_responses(fake):
    fake.respond_json(b'{"ok":true}')
    async with httpx.AsyncClient() as client:
        await upstream_facts.fetch_facts(client, fake.url)
        r = await client.post(f"{fake.url}/v1/chat/completions", content=b"{}")
    assert r.content == b'{"ok":true}'


async def test_props_timeout_or_5xx_is_unavailable(fake):
    async with httpx.AsyncClient() as client:
        fake.props_delay = 0.5
        with pytest.raises(upstream_facts.FactsUnavailable):
            await upstream_facts.fetch_facts(client, fake.url, timeout=0.1)
        fake.props_delay = 0.0
        fake.props_status = 503
        with pytest.raises(upstream_facts.FactsUnavailable):
            await upstream_facts.fetch_facts(client, fake.url)


@pytest.mark.parametrize(
    "status,body,reason",
    [
        (None, b"", "transport_error"),
        (500, b"", "upstream_5xx"),
        (503, b'{"error":{"type":"server_error","message":"the engine stopped unexpectedly"}}', "upstream_5xx"),
        (400, b'{"error":{"type":"invalid_request_error","message":"request exceeds the context window: '
              b'prompt (70475 tokens) leaves no room to answer in the context (65536); requests are never '
              b'truncated"}}', "context_window_400"),
        (400, b'{"error":{"type":"invalid_request_error","message":"No messages provided."}}', None),
        (200, b"", None),
    ],
)
def test_staleness_signals(status, body, reason):
    assert errors.staleness_reason(status, body) == reason


async def test_props_refreshed_after_5xx_transport_error_context_400(fake):
    fake.count_tokens_handler = _strata_count_tokens
    state = UpstreamState(fake.url, pins.load(), tokens.default())
    async with httpx.AsyncClient() as client:
        await state.refresh(client)
        assert state.facts.n_ctx == 65536 and not state.stale
        await state.refresh(client)  # fresh facts are not re-read
        assert fake.props_requests == 1
        for status, body in [(None, b""), (502, b""), (400, b"request exceeds the context window: x")]:
            fake.props_n_ctx += 1024
            assert state.observe(status, body) is True
            assert state.stale
            await state.refresh(client)
            assert not state.stale and state.facts.n_ctx == fake.props_n_ctx
        assert fake.props_requests == 4
        assert state.observe(400, b"No messages provided.") is False and not state.stale


async def test_unreachable_at_startup_fetched_lazily_and_stale_facts_kept(fake):
    fake.count_tokens_handler = _strata_count_tokens
    state = UpstreamState(fake.url, pins.load(), tokens.default())
    async with httpx.AsyncClient() as client:
        fake.props_status = 503
        assert await state.refresh(client) is None
        assert state.stale and not state.pinned_ok
        fake.props_status = 200
        assert (await state.refresh(client)).n_ctx == 65536
        assert state.pinned_ok
        state.mark_stale("upstream_5xx")
        fake.props_status = 503
        facts = await state.refresh(client)
        assert facts is not None and facts.n_ctx == 65536 and state.stale  # cached, retried next build


async def test_pinned_upstream_is_ok(fake):
    fake.count_tokens_handler = _strata_count_tokens
    state = UpstreamState(fake.url, pins.load(), tokens.default())
    async with httpx.AsyncClient() as client:
        await state.refresh(client)
    assert state.mismatches == ()
    assert state.canary.ok is True
    assert state.pinned_ok


async def test_template_hash_mismatch_not_pinned_ok(fake):
    fake.count_tokens_handler = _strata_count_tokens
    fake.props_chat_template = fake.props_chat_template + "\n"
    state = UpstreamState(fake.url, pins.load(), tokens.default())
    async with httpx.AsyncClient() as client:
        await state.refresh(client)
    assert not state.pinned_ok
    assert [m.split(":")[0] for m in state.mismatches] == ["chat_template_sha256"]


async def test_build_info_mismatch_not_pinned_ok(fake):
    fake.count_tokens_handler = _strata_count_tokens
    fake.props_build_info = "Strata 0.1.49"
    state = UpstreamState(fake.url, pins.load(), tokens.default())
    async with httpx.AsyncClient() as client:
        await state.refresh(client)
    assert not state.pinned_ok
    assert state.mismatches == ("build_info: 'Strata 0.1.49' != pinned 'Strata 0.1.48'",)


def test_canary_conversion_matches_recorded_server_counts():
    """The documented Anthropic -> render conversion reproduces the server's counts."""
    for name, case in upstream_facts.CANARY_CASES:
        args = upstream_facts.anthropic_to_render_args(case)
        assert tokens.count_messages(**args) == SERVER_COUNTS[name], name


async def test_startup_canary_uses_count_tokens(fake):
    fake.count_tokens_handler = _strata_count_tokens
    async with httpx.AsyncClient() as client:
        result = await upstream_facts.run_canary(client, fake.url, tokens.default())
    assert result.ok is True
    assert len(fake.count_tokens_requests) == len(upstream_facts.CANARY_CASES) >= 2
    assert all(c.local == c.remote for c in result.cases)


async def test_canary_count_mismatch_not_ok(fake):
    fake.count_tokens_handler = lambda body: _strata_count_tokens(body) + 1
    state = UpstreamState(fake.url, pins.load(), tokens.default())
    async with httpx.AsyncClient() as client:
        await state.refresh(client)
    assert state.mismatches == ()
    assert state.canary.ok is False
    assert not state.pinned_ok


async def test_canary_unavailable_is_inconclusive_and_retried(fake):
    fake.count_tokens_handler = None  # unscripted: the fake answers 599
    state = UpstreamState(fake.url, pins.load(), tokens.default())
    async with httpx.AsyncClient() as client:
        await state.refresh(client)
        assert state.canary.ok is None and not state.pinned_ok
        fake.count_tokens_handler = _strata_count_tokens
        state.mark_stale("transport_error")
        await state.refresh(client)
    assert state.canary.ok is True and state.pinned_ok
