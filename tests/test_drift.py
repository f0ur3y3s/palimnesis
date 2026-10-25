"""Count drift (contracts §1.3; plan Phase 2 slice 10).

Every accounted call compares the local count I with the upstream's
``usage.prompt_tokens``, read through the profile. A difference writes a ``count_drift``
event and raises the margin to ``M_eff = min(2048, M + 2·max recent drift)``; three
consecutive drifts, or one over 1024, disable the view.
"""

from __future__ import annotations

import json
import logging

from palimnesis import profile

from .fake_upstream import FakeUpstream
from .test_cacheacct_http import acct_stack, body, events, history, post, turn
from .test_profile import ToyCache, ToyCounter, ToyCrossCheck, ToyErrors, ToyFacts


def test_no_drift_no_event(tmp_path):
    messages = history(2)
    with acct_stack(tmp_path) as (fake, url, settings):
        for i in range(3):
            fake.respond_counted()
            assert post(url, body(messages)).status_code == 200
            messages = turn(messages, user=f"next {i}")

    calls = events(settings)
    assert len(calls) == 3
    assert all(c["prompt_tokens"] == c["input_tokens"] for c in calls)
    assert events(settings, "count_drift") == []
    assert {c["budget"]["margin"] for c in calls} == {256}


def test_drift_raises_margin_then_disables(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="palimnesis.viewengine")
    messages = history(1)
    sent = []
    small = FakeUpstream()
    small.props_n_ctx = 20_000
    with acct_stack(tmp_path, fake=small) as (fake, url, settings):
        for i in range(4):
            fake.respond_counted(drift=10)
            data = body(messages)
            data = json.dumps({k: v for k, v in json.loads(data).items()
                               if k != "max_completion_tokens"}).encode()
            assert post(url, data).status_code == 200
            sent.append(json.loads(fake.requests[-1].body))
            messages = turn(messages, user=f"next {i}")

    drifts = events(settings, "count_drift")
    calls = events(settings)
    assert [(d["drift"], d["consecutive"], d["margin"], d["disabled"]) for d in drifts] == [
        (10, 1, 276, False), (10, 2, 276, False), (10, 3, 276, True)]
    assert all(d["upstream"] == d["local"] + 10 for d in drifts)
    # n_ctx 20,000: B_in = 20,000 − 8,192 − 256 = 11,552 at first, then 11,532 with
    # M_eff = 256 + 2·10; the per-message excerpt cap 4% of B_in shrinks with it.
    assert [c["budget"]["margin"] for c in calls[:3]] == [256, 276, 276]
    assert [c["budget"]["input_budget"] for c in calls[:3]] == [11552, 11532, 11532]
    assert [c["budget"]["excerpt_per_message"] for c in calls[:3]] == [462, 461, 461]
    # The third consecutive drift disabled the view: the fourth request goes as sent.
    assert calls[3]["view_mode"] == "disabled" and calls[3]["cause"] == "view_disabled"
    assert all(s["max_completion_tokens"] == 8192 for s in sent[:3])
    assert "max_completion_tokens" not in sent[3]
    assert any("bounded views disabled" in r.getMessage() and "consecutive count drifts"
               in r.getMessage() for r in caplog.records)


def test_one_large_drift_disables_and_margin_is_capped(tmp_path):
    messages = history(1)
    with acct_stack(tmp_path) as (fake, url, settings):
        fake.respond_counted(drift=-900)
        post(url, body(messages))
        messages = turn(messages)
        fake.respond_counted(drift=1500)
        post(url, body(messages))
        messages = turn(messages, user="again")
        fake.respond_counted()
        post(url, body(messages))

    first, big = events(settings, "count_drift")
    calls = events(settings)
    # min(2048, 256 + 2·900) = 2048: the margin is capped.
    assert (first["drift"], first["margin"], first["disabled"]) == (-900, 2048, False)
    assert calls[1]["budget"]["margin"] == 2048
    assert (big["drift"], big["consecutive"], big["disabled"]) == (1500, 2, True)
    assert calls[2]["view_mode"] == "disabled"


# --- the usage is read through the profile, not parsed as Strata's ---


class ToyUsage(ToyCrossCheck):
    def usage(self, payload):
        toy = payload.get("toy_usage")
        return profile.Usage(toy["in"], toy["hit"], 3.5) if toy else None


def toy_usage_profile(base_url):
    return profile.UpstreamProfile(
        id="toy-usage", counter=ToyCounter(), facts=ToyFacts(), cross_check=ToyUsage(),
        cache_model=ToyCache(), errors=ToyErrors(),
        rules=profile.TemplateRules(reasoning_every_turn=True, leading_system_only=True))


def test_usage_read_through_profile(tmp_path, monkeypatch):
    monkeypatch.setitem(profile.REGISTRY, "toy-usage", f"{__name__}:toy_usage_profile")
    final = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             # Strata-shaped usage the toy profile does not read...
             "usage": {"prompt_tokens": 1, "prompt_tokens_details": {"cached_tokens": 1}},
             # ...and the toy upstream's own.
             "toy_usage": {"in": 4321, "hit": 17}}
    chunks = [b'data: {"choices":[{"index":0,"delta":{"content":"ok"}}]}\n\n',
              b"data: " + json.dumps(final).encode() + b"\n\n", b"data: [DONE]\n\n"]
    with acct_stack(tmp_path, profile="toy-usage") as (fake, url, settings):
        fake.respond_sse(chunks)
        assert post(url, body(history(1))).status_code == 200

    [call] = events(settings)
    sent = json.loads(fake.requests[-1].body)
    local = ToyCounter().count_messages(sent["messages"], sent["tools"])
    assert call["input_tokens"] == local
    assert (call["prompt_tokens"], call["cached_tokens"], call["prompt_ms"]) == (4321, 17, 3.5)
    [drift] = events(settings, "count_drift")
    assert (drift["local"], drift["upstream"], drift["drift"]) == (local, 4321, 4321 - local)
