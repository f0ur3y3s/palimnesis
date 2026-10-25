"""The upstream-profile seam (D15 amended; Phase 2 delta slice A).

Core modules see an upstream only through ``palimnesis.profile``: a counter, a facts
reader, a counting cross-check, a cache-reuse model, an error map and template rules.
These tests pin that boundary: the core never imports the Strata profile, a toy profile
drives a bounded view end to end, and the Strata profile bundles its parts.
"""

from __future__ import annotations

import ast
import json
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from palimnesis import profile
from palimnesis.api import create_app
from palimnesis.config import Settings

from .fake_upstream import FakeUpstream
from .servers import serve

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "palimnesis"
PROBES = ROOT / "eval" / "probes" / "fixtures"
STRATA = "palimnesis.upstreams.strata"
TEMPLATE_SHA = "12827f24b742ea4e80cdc12dbcf9622227056b9f797252a3149263d4f9aaadce"

SID = "profile-1"
TOOLS = [{"type": "function", "function": {"name": "read", "description": "read a file",
                                           "parameters": {"type": "object", "properties": {}}}}]
DONE = (b'data: {"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n")


# --- a toy profile: characters for tokens, fixed facts, a cross-check that always agrees ---


class ToyCounter:
    added_token_strings: tuple[str, ...] = ()

    def count(self, text: str) -> int:
        return len(text)

    def count_cached(self, text: str) -> int:
        return len(text)

    def count_messages(self, messages, tools=None, **kw) -> int:
        return len(json.dumps([messages, tools], ensure_ascii=False))

    def render_args(self, body):
        return body.get("tools") or None, {}

    def encode(self, text: str) -> list[int]:
        return [ord(c) for c in text]

    def layout(self, messages, tools=None, **kw) -> profile.Layout:
        ids = tuple(self.encode(json.dumps([messages, tools], ensure_ascii=False)))
        return profile.Layout(ids, (profile.Segment("unmapped", (), 0, len(ids)),))


class ToyFacts:
    def __init__(self) -> None:
        self.facts = profile.UpstreamFacts(n_ctx=65536, identity=("toy", "1"))
        self.stale = False
        self.pinned_ok = True
        self.refreshes = 0

    async def refresh(self, client):
        self.refreshes += 1
        return self.facts

    def mark_stale(self, reason: str) -> None:
        self.stale = True

    def observe(self, status, body=b"") -> bool:
        return False

    def diagnostics(self) -> dict:
        return {"toy": True}


class ToyCrossCheck:
    async def canary(self, client):
        return None

    def usage(self, payload):
        return None


class ToyCache:
    def expected(self, previous_render, render) -> int:
        return 0


class ToyErrors:
    def staleness_reason(self, status, body=b""):
        return "transport_error" if status is None else None

    def is_context_overflow(self, status, body=b"") -> bool:
        return False


def toy_profile(base_url: str, rules: profile.TemplateRules | None = None) -> profile.UpstreamProfile:
    return profile.UpstreamProfile(
        id="toy-1", counter=ToyCounter(), facts=ToyFacts(), cross_check=ToyCrossCheck(),
        cache_model=ToyCache(), errors=ToyErrors(),
        rules=rules or profile.TemplateRules(reasoning_every_turn=True, leading_system_only=True))


def toy_profile_no_reasoning_carryover(base_url: str) -> profile.UpstreamProfile:
    return toy_profile(base_url, profile.TemplateRules(reasoning_every_turn=False,
                                                       leading_system_only=True))


@contextmanager
def toy_stack(tmp_path, monkeypatch, name="toy-1", target="toy_profile", **settings):
    monkeypatch.setitem(profile.REGISTRY, name, f"{__name__}:{target}")
    fake = FakeUpstream()
    with serve(fake.app()) as upstream_url:
        s = Settings(upstream_base_url=upstream_url, db_path=tmp_path / "archive.db",
                     profile=name, **settings)
        with serve(create_app(s), palimnesis=True) as proxy_url:
            yield fake, proxy_url


def history(turns, lines=80):
    messages = [{"role": "system", "content": "You are a coding agent."},
                {"role": "user", "content": "refactor the project"}]
    for i in range(turns):
        messages.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": f"call_{i}", "type": "function", "function": {"name": "read", "arguments": "{}"}}]})
        messages.append({"role": "tool", "tool_call_id": f"call_{i}",
                         "content": "\n".join(f"def f{i}_{n}(x): return x * {n}" for n in range(lines))})
    return messages


def post(proxy_url, messages, **settings) -> tuple[bytes, httpx.Response]:
    data = json.dumps({"model": "m", "messages": messages, "tools": TOOLS, "stream": True,
                       **settings}).encode()
    with httpx.stream("POST", f"{proxy_url}/s/{SID}/v1/chat/completions", content=data,
                      timeout=60) as r:
        r.read()
    return data, r


# --- boundary ---


def _imported_modules(path: Path) -> list[str]:
    """Absolute module names imported by ``path`` (relative imports resolved)."""
    package = list(path.relative_to(SRC.parent).parts[:-1])
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            module = ".".join(base + ([node.module] if node.module else []))
            out.append(module)
            out += [f"{module}.{alias.name}" for alias in node.names]
    return out


def test_core_modules_do_not_import_strata_profile():
    core = [p for p in SRC.rglob("*.py") if not p.relative_to(SRC).as_posix().startswith("upstreams/strata/")]
    assert {p.name for p in core} >= {"profile.py", "viewengine.py", "archive.py", "api.py", "view.py"}
    offenders = {p.relative_to(SRC).as_posix(): m for p in core for m in _imported_modules(p)
                 if m == STRATA or m.startswith(STRATA + ".")}
    assert offenders == {}
    # The only mention is the profile registry's string.
    assert profile.REGISTRY[profile.DEFAULT_PROFILE] == f"{STRATA}:profile"


# --- the core through a toy profile ---


def test_view_engine_end_to_end_with_toy_profile(tmp_path, monkeypatch):
    with toy_stack(tmp_path, monkeypatch, input_budget=8000) as (fake, url):
        fake.respond_sse([DONE])
        data, r = post(url, history(30), max_completion_tokens=8192)

    assert r.status_code == 200
    toy = ToyCounter()
    full = json.loads(data)
    assert toy.count_messages(full["messages"], TOOLS) > 8000  # over budget as sent
    sent = json.loads(fake.requests[-1].body)
    assert toy.count_messages(sent["messages"], sent["tools"]) <= 8000  # masked within it
    assert "[palimnesis s1" in fake.requests[-1].body.decode()
    # The toy profile answered for facts and counts: the Strata endpoints were never asked.
    assert fake.props_requests == 0 and fake.count_tokens_requests == []


def test_unsupported_template_rules_view_disabled(tmp_path, monkeypatch):
    with toy_stack(tmp_path, monkeypatch, name="toy-norc",
                   target="toy_profile_no_reasoning_carryover", input_budget=8000) as (fake, url):
        fake.respond_sse([DONE])
        data, r = post(url, history(30), max_completion_tokens=8192)

    assert r.status_code == 200
    assert fake.requests[-1].body == data  # unbounded, as when the pin does not match


def test_unknown_profile_rejected_at_startup(tmp_path):
    with pytest.raises(profile.UnknownProfile, match="no-such-backend.*strata-0.1.48"):
        profile.load("no-such-backend", "http://127.0.0.1:1")
    with pytest.raises(profile.UnknownProfile, match="no-such-backend"):
        create_app(Settings(upstream_base_url="http://127.0.0.1:1", db_path=tmp_path / "a.db",
                            profile="no-such-backend"))


# --- the Strata profile ---


@pytest.fixture
def fake():
    f = FakeUpstream()
    with serve(f.app()) as url:
        f.url = url
        yield f


async def test_strata_profile_bundles_counter_facts_crosscheck_cache_errors_rules(fake):
    p = profile.load(profile.DEFAULT_PROFILE, fake.url)
    assert p.id == "strata-0.1.48"
    for part, proto in [(p.counter, profile.Counter), (p.facts, profile.FactsReader),
                        (p.cross_check, profile.CrossCheck), (p.cache_model, profile.CacheReuseModel),
                        (p.errors, profile.ErrorMap)]:
        assert isinstance(part, proto), proto.__name__

    # Counter: the pinned template and tokenizer; the recorded server count (count_tokens.json).
    assert p.counter.count_messages([{"role": "user", "content": "Q1"}],
                                    enable_thinking=False) == 14  # user_only_thinking_disabled
    tools, kw = p.counter.render_args({"messages": [], "tools": TOOLS, "reasoning_effort": "low"})
    assert tools == TOOLS and kw == {"effort": "low", "enable_thinking": None}
    assert {"<|im_start|>", "<|im_end|>", "<tool_response>", "</tool_response>", "<think>",
            "</think>"} <= set(p.counter.added_token_strings)

    # Facts reader plus startup canary, against the fake's recorded /props.
    async with httpx.AsyncClient() as client:
        await p.facts.refresh(client)
    assert p.facts.facts == profile.UpstreamFacts(n_ctx=65536, identity=("Strata 0.1.48", TEMPLATE_SHA))
    assert p.facts.pinned_ok and not p.facts.stale
    assert len(fake.count_tokens_requests) >= 2
    assert p.facts.observe(502, b"") is True and p.facts.stale

    # Error map (recorded Strata context-window 400).
    overflow = (b'{"error":{"type":"invalid_request_error","message":"request exceeds the context '
                b'window: prompt (70475 tokens) leaves no room to answer in the context (65536); '
                b'requests are never truncated"}}')
    assert p.errors.is_context_overflow(400, overflow) is True
    assert p.errors.is_context_overflow(400, b'{"error":{"message":"No messages provided."}}') is False
    assert p.errors.staleness_reason(400, overflow) == "context_window_400"
    assert p.errors.staleness_reason(None) == "transport_error"
    assert p.errors.staleness_reason(503) == "upstream_5xx"

    assert p.rules == profile.TemplateRules(reasoning_every_turn=True, leading_system_only=True)
    # Cache-reuse model (docs/probes/strata.md §7; probed in tests/test_cacheacct.py).
    layout = p.counter.layout([{"role": "user", "content": "Q1"}], enable_thinking=False)
    assert len(layout.ids) == 14 and layout.segments[-1].kind == "generation"
    assert p.cache_model.expected(None, layout) == 0
    assert p.cache_model.expected(layout, layout) == layout.generation_start


def test_usage_parsed_through_profile():
    events = (PROBES / "sse_oa_include_usage.sse").read_bytes().split(b"\n\n")
    final = [e for e in events if e.startswith(b"data: {")][-1]
    p = profile.load(profile.DEFAULT_PROFILE, "http://127.0.0.1:1")
    usage = p.cross_check.usage(json.loads(final[len(b"data: "):]))
    assert usage == profile.Usage(prompt_tokens=28, cached_tokens=21, prompt_ms=217.3)
    assert p.cross_check.usage({"usage": {"prompt_tokens": 5}}) == profile.Usage(5, 0, None)
    assert p.cross_check.usage({"choices": []}) is None
