"""Strata versions are accepted by their counts, not by name (D102, contracts §1).

A build the pin does not list is accepted when the count_tokens canary passes. A changed
chat template is adopted when the canary passes with a counter that renders it, and the
shared counter then renders with it. Anything that counts differently stays a mismatch.
HTTP runs against tests/fake_upstream.py on real loopback sockets.
"""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from palimnesis.upstreams.strata import pins, tokens
from palimnesis.upstreams.strata import facts as upstream_facts
from palimnesis.upstreams.strata.facts import UpstreamState

from .fake_upstream import FakeUpstream
from .servers import serve
from .test_strata_facts import _strata_count_tokens

PREFIX = "Server note: be brief.\n"


@pytest.fixture
def fake():
    f = FakeUpstream()
    with serve(f.app()) as url:
        f.url = url
        yield f


def _counting_with(template: str):
    """A count_tokens handler that counts like a server rendering ``template``."""
    counter = tokens.Tokens(replace(pins.load(), chat_template=template))

    def handler(body: dict) -> int:
        args = upstream_facts.anthropic_to_render_args({k: v for k, v in body.items() if k != "model"})
        messages = tokens.preprocess_messages(args.pop("messages"))
        return counter.count_messages(messages, args.pop("tools", None), **args)
    return handler


async def _refresh(fake, counter):
    state = UpstreamState(fake.url, pins.load(), counter)
    async with httpx.AsyncClient() as client:
        await state.refresh(client)
    return state


async def test_an_unlisted_build_with_the_pinned_template_is_accepted_by_the_canary(fake):
    fake.props_build_info = "Strata 0.2.7"
    fake.count_tokens_handler = _strata_count_tokens
    state = await _refresh(fake, tokens.Tokens(pins.load()))

    assert state.mismatches == ()
    assert state.pinned_ok
    assert state.diagnostics()["accepted_by"] == "canary"


async def test_a_listed_build_is_accepted_as_pinned(fake):
    fake.count_tokens_handler = _strata_count_tokens
    state = await _refresh(fake, tokens.Tokens(pins.load()))
    assert state.pinned_ok and state.diagnostics()["accepted_by"] == "pinned"
    fake.props_build_info = "Strata 0.1.54"
    state = await _refresh(fake, tokens.Tokens(pins.load()))
    assert state.pinned_ok and state.diagnostics()["accepted_by"] == "equivalent"


async def test_an_unlisted_build_that_counts_differently_stays_off(fake):
    fake.props_build_info = "Strata 0.2.7"
    fake.count_tokens_handler = lambda body: _strata_count_tokens(body) + 1
    state = await _refresh(fake, tokens.Tokens(pins.load()))

    assert not state.pinned_ok
    assert state.canary is not None and state.canary.ok is False


async def test_a_changed_template_that_counts_like_the_server_is_adopted(fake):
    pinned = pins.load().chat_template
    fake.props_build_info = "Strata 0.2.7"
    fake.props_chat_template = PREFIX + pinned
    fake.count_tokens_handler = _counting_with(PREFIX + pinned)
    counter = tokens.Tokens(pins.load())
    messages = [{"role": "user", "content": "hi"}]
    before = counter.count_messages(messages, None)

    state = await _refresh(fake, counter)

    assert state.mismatches == ()
    assert state.pinned_ok
    assert state.diagnostics()["accepted_by"] == "canary, server template"
    # The shared counter now renders with the server's template.
    assert counter.render(messages).startswith(PREFIX.strip())
    assert counter.count_messages(messages, None) > before


async def test_a_changed_template_whose_counts_differ_is_a_mismatch(fake):
    pinned = pins.load().chat_template
    fake.props_chat_template = PREFIX + pinned
    fake.count_tokens_handler = _strata_count_tokens  # the server still counts the old way
    counter = tokens.Tokens(pins.load())

    state = await _refresh(fake, counter)

    assert not state.pinned_ok
    assert [m.split(":")[0] for m in state.mismatches] == ["chat_template_sha256"]
    assert state.diagnostics()["template_canary"]["ok"] is False
    assert not counter.render([{"role": "user", "content": "hi"}]).startswith(PREFIX.strip())


def test_adopting_a_template_on_one_upstream_leaves_others_alone():
    shared = tokens.default()
    mine = shared.fork()
    mine.adopt_template(PREFIX + pins.load().chat_template)
    messages = [{"role": "user", "content": "hi"}]
    assert mine.render(messages).startswith(PREFIX.strip())
    assert not shared.render(messages).startswith(PREFIX.strip())
    assert mine.count("same text") == shared.count("same text")


async def _accepted_on_the_pin(fake):
    fake.count_tokens_handler = _strata_count_tokens
    counter = tokens.Tokens(pins.load())
    state = await _refresh(fake, counter)
    assert state.pinned_ok
    return state, counter


async def test_views_stay_off_while_a_changed_templates_canary_runs(fake):
    import threading

    import anyio

    state, counter = await _accepted_on_the_pin(fake)
    gate = threading.Event()
    counting = _counting_with(PREFIX + pins.load().chat_template)
    fake.props_chat_template = PREFIX + pins.load().chat_template
    fake.count_tokens_handler = lambda body: (gate.wait(10), counting(body))[1]
    state.mark_stale("transport_error")  # e.g. Strata restarted on a new release

    async with httpx.AsyncClient() as client, anyio.create_task_group() as tg:
        tg.start_soon(state.refresh, client)
        await anyio.sleep(0.3)  # the template canary is waiting on the server
        assert not state.pinned_ok
        with anyio.fail_after(2):
            await state.refresh(client)  # another request's refresh does not wait for it
        assert not state.pinned_ok
        gate.set()

    assert state.pinned_ok
    assert counter.render([{"role": "user", "content": "hi"}]).startswith(PREFIX.strip())


async def test_an_inconclusive_canary_for_a_changed_template_is_retried(fake):
    state, counter = await _accepted_on_the_pin(fake)
    fake.props_chat_template = PREFIX + pins.load().chat_template
    fake.count_tokens_handler = None  # count_tokens unavailable while the server loads
    state.mark_stale("transport_error")
    async with httpx.AsyncClient() as client:
        await state.refresh(client)
        assert not state.pinned_ok
        assert state.template_canary is not None and state.template_canary.ok is None

        fake.count_tokens_handler = _counting_with(PREFIX + pins.load().chat_template)
        await state.refresh(client)  # facts are fresh, but the template is still undecided

    assert state.pinned_ok
    assert state.diagnostics()["accepted_by"] == "canary, server template"


async def test_diagnostics_never_carry_the_template_text(fake):
    # Diagnostics go to the operational log; the template is kilobytes of text.
    state = await _refresh(fake, tokens.Tokens(pins.load()))
    facts = state.diagnostics()["facts"]
    assert "chat_template" not in facts
    assert facts["chat_template_sha256"] == pins.load().template_sha256


async def test_a_server_that_leaves_out_build_info_is_judged_by_its_counts(fake):
    # Strata sets build_info only when its engine reports a version (its own test_server
    # checks the key is absent otherwise); since D102 the name decides nothing.
    fake.props_build_info = None
    fake.count_tokens_handler = _strata_count_tokens
    state = await _refresh(fake, tokens.Tokens(pins.load()))

    assert state.props is not None and state.props.build_info == "unknown"
    assert state.pinned_ok
    assert state.diagnostics()["accepted_by"] == "canary"
