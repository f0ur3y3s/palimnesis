"""Upstream facts are read, not assumed (contracts §1.1, §1.2).

``fetch_facts`` reads ``GET /props`` (1 s timeout) into ``UpstreamFacts``: ``n_ctx``,
``build_info`` and the SHA-256 of ``chat_template``. ``UpstreamState`` holds the last
facts for one upstream:

- ``observe(status, body)`` / ``mark_stale(reason)`` mark them stale after a transport
  error, a 5xx, or a context-window 400; ``refresh`` re-reads them before the next
  build. A failed read keeps the cached facts (still stale) or, at startup, none:
  they are then fetched lazily on the next ``refresh``.
- ``mismatches`` compares ``build_info`` and the template hash with the pin.
- ``canary`` compares local counts with ``POST /v1/messages/count_tokens`` on
  ``CANARY_CASES``; it runs after the first good read and again whenever the build or
  template changes or the previous run was inconclusive.
- ``pinned_ok`` is true only with facts present, no pin mismatch and a passing canary.
  Otherwise the caller runs in view-disabled mode (D14.9).

Canary conversion (``anthropic_to_render_args``), the subset the canary uses: ``system``
(string or text blocks, joined) becomes a leading system message; user text stays the
content; user ``tool_result`` blocks (string content or text blocks) become ``tool``
messages; assistant ``thinking`` blocks become ``reasoning_content``, ``text`` blocks the
content and ``tool_use`` blocks ``tool_calls`` with mapping arguments; tools pass through
``tokens.bare_tool`` (``input_schema`` -> ``parameters``); ``thinking.type == "disabled"``
sets ``enable_thinking=False``; ``output_config.effort`` sets the effort. Other block
types are rejected.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from . import pins, tokens

PROPS_TIMEOUT_S = 1.0
COUNT_TOKENS_TIMEOUT_S = 5.0
CANARY_MODEL = "palimnesis-canary"

_TH = "Let me think about this carefully step by step with many words of reasoning here."
_WEATHER = {
    "name": "get_weather",
    "description": "Get the current weather for a city.",
    "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
}

# Small Anthropic-shaped requests. Names are the matching count_tokens.json cases.
CANARY_CASES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("system_plus_user", {"system": "You are terse.", "messages": [{"role": "user", "content": "Q1"}]}),
    (
        "prior_turn_thinking_thinking_disabled",
        {
            "messages": [
                {"role": "user", "content": "Q1"},
                {"role": "assistant", "content": [{"type": "thinking", "thinking": _TH, "signature": "x"},
                                                  {"type": "text", "text": "Answer one."}]},
                {"role": "user", "content": "Q2"},
            ],
            "thinking": {"type": "disabled"},
        },
    ),
    (
        "tool_turn_think",
        {
            "messages": [
                {"role": "user", "content": "Weather in Paris?"},
                {"role": "assistant", "content": [
                    {"type": "thinking", "thinking": _TH, "signature": "x"},
                    {"type": "tool_use", "id": "c1", "name": "get_weather", "input": {"city": "Paris"}}]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "Sunny 20C"}]},
            ],
            "tools": [_WEATHER],
        },
    ),
)


class FactsUnavailable(Exception):
    """``/props`` could not be read or parsed."""


@dataclass(frozen=True)
class UpstreamFacts:
    n_ctx: int
    build_info: str
    chat_template_sha256: str
    model_alias: str | None = None
    total_slots: int | None = None


@dataclass(frozen=True)
class CanaryCase:
    name: str
    local: int
    remote: int | None


@dataclass(frozen=True)
class CanaryResult:
    # True all equal; False a count differed; None inconclusive (endpoint unavailable).
    ok: bool | None
    cases: tuple[CanaryCase, ...] = ()
    error: str | None = None


async def fetch_facts(
    client: httpx.AsyncClient, base_url: str, *, timeout: float = PROPS_TIMEOUT_S
) -> UpstreamFacts:
    try:
        r = await client.get(f"{base_url.rstrip('/')}/props", timeout=timeout)
    except httpx.HTTPError as exc:
        raise FactsUnavailable(f"GET /props failed: {type(exc).__name__}") from exc
    if r.status_code != 200:
        raise FactsUnavailable(f"GET /props returned {r.status_code}")
    try:
        props = r.json()
        template = props["chat_template"]
        return UpstreamFacts(
            n_ctx=int(props["default_generation_settings"]["n_ctx"]),
            build_info=str(props["build_info"]),
            chat_template_sha256=hashlib.sha256(template.encode("utf-8")).hexdigest(),
            model_alias=props.get("model_alias"),
            total_slots=props.get("total_slots"),
        )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise FactsUnavailable(f"GET /props malformed: {exc!r}") from exc


def pin_mismatches(facts: UpstreamFacts, pin: pins.Pin) -> tuple[str, ...]:
    out = []
    if facts.build_info != pin.build_info:
        out.append(f"build_info: {facts.build_info!r} != pinned {pin.build_info!r}")
    if facts.chat_template_sha256 != pin.template_sha256:
        out.append(f"chat_template_sha256: {facts.chat_template_sha256} != pinned {pin.template_sha256}")
    return tuple(out)


def staleness_reason(status: int | None, body: bytes = b"") -> str | None:
    """Why an upstream outcome invalidates the facts; ``status=None`` is a transport error."""
    if status is None:
        return "transport_error"
    if status >= 500:
        return "upstream_5xx"
    if status == 400 and b"exceeds the context window" in body:
        return "context_window_400"
    return None


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence):
        parts = []
        for block in content:
            if not (isinstance(block, Mapping) and block.get("type") == "text"):
                raise ValueError(f"unsupported content block {block!r}")
            parts.append(block["text"])
        return "".join(parts)
    if content is None:
        return ""
    raise ValueError(f"unsupported content {content!r}")


def anthropic_to_render_args(body: Mapping[str, Any]) -> dict[str, Any]:
    """Render arguments for an Anthropic Messages body (see module docstring for scope)."""
    messages: list[dict[str, Any]] = []
    if body.get("system"):
        messages.append({"role": "system", "content": _text(body["system"])})
    for m in body.get("messages", []):
        content = m.get("content")
        if isinstance(content, str):
            messages.append({"role": m["role"], "content": content})
            continue
        if m["role"] == "user":
            text = []
            for block in content:
                if block.get("type") == "tool_result":
                    messages.append({"role": "tool", "tool_call_id": block.get("tool_use_id"),
                                     "content": _text(block.get("content"))})
                elif block.get("type") == "text":
                    text.append(block["text"])
                else:
                    raise ValueError(f"unsupported user block {block.get('type')!r}")
            if text:
                messages.append({"role": "user", "content": "".join(text)})
        elif m["role"] == "assistant":
            out: dict[str, Any] = {"role": "assistant", "content": ""}
            reasoning, text, calls = [], [], []
            for block in content:
                kind = block.get("type")
                if kind == "thinking":
                    reasoning.append(block["thinking"])
                elif kind == "text":
                    text.append(block["text"])
                elif kind == "tool_use":
                    calls.append({"id": block["id"], "type": "function",
                                  "function": {"name": block["name"], "arguments": block.get("input", {})}})
                else:
                    raise ValueError(f"unsupported assistant block {kind!r}")
            out["content"] = "".join(text)
            if reasoning:
                out["reasoning_content"] = "".join(reasoning)
            if calls:
                out["tool_calls"] = calls
            messages.append(out)
        else:
            raise ValueError(f"unsupported role {m['role']!r}")
    thinking = body.get("thinking")
    output_config = body.get("output_config")
    return {
        "messages": messages,
        "tools": body.get("tools") or None,
        "effort": output_config.get("effort") if isinstance(output_config, Mapping) else None,
        "enable_thinking": False if isinstance(thinking, Mapping) and thinking.get("type") == "disabled" else None,
    }


async def run_canary(
    client: httpx.AsyncClient,
    base_url: str,
    counter: tokens.Tokens | None = None,
    *,
    timeout: float = COUNT_TOKENS_TIMEOUT_S,
) -> CanaryResult:
    counter = counter or tokens.default()
    url = f"{base_url.rstrip('/')}/v1/messages/count_tokens"
    cases = []
    for name, body in CANARY_CASES:
        local = counter.count_messages(**anthropic_to_render_args(body))
        try:
            r = await client.post(url, json={"model": CANARY_MODEL, **body}, timeout=timeout)
            remote = int(r.json()["input_tokens"]) if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            return CanaryResult(None, tuple(cases), f"count_tokens failed: {type(exc).__name__}")
        if remote is None:
            return CanaryResult(None, tuple(cases), f"count_tokens returned {r.status_code}")
        cases.append(CanaryCase(name, local, remote))
    return CanaryResult(all(c.local == c.remote for c in cases), tuple(cases))


class UpstreamState:
    """Current facts for one upstream, their staleness and the pin verdict."""

    def __init__(self, base_url: str, pin: pins.Pin, counter: tokens.Tokens | None = None) -> None:
        self.base_url = base_url
        self.pin = pin
        self.counter = counter
        self.facts: UpstreamFacts | None = None
        self.stale = True
        self.stale_reason: str | None = "not_fetched"
        self.mismatches: tuple[str, ...] = ()
        self.canary: CanaryResult | None = None
        self.last_error: str | None = None
        self._canary_for: tuple[str, str] | None = None

    def mark_stale(self, reason: str) -> None:
        self.stale = True
        self.stale_reason = reason

    def observe(self, status: int | None, body: bytes = b"") -> bool:
        """Mark stale if this upstream outcome invalidates the facts; returns whether it did."""
        reason = staleness_reason(status, body)
        if reason is not None:
            self.mark_stale(reason)
        return reason is not None

    @property
    def pinned_ok(self) -> bool:
        return (
            self.facts is not None
            and not self.mismatches
            and self.canary is not None
            and self.canary.ok is True
        )

    async def refresh(self, client: httpx.AsyncClient) -> UpstreamFacts | None:
        """Re-read facts if stale (or never read); returns the facts now held."""
        if self.stale or self.facts is None:
            try:
                facts = await fetch_facts(client, self.base_url)
            except FactsUnavailable as exc:
                self.last_error = str(exc)
                return self.facts
            self.facts = facts
            self.stale = False
            self.stale_reason = None
            self.last_error = None
            self.mismatches = pin_mismatches(facts, self.pin)
        facts = self.facts
        identity = (facts.build_info, facts.chat_template_sha256)
        if not self.mismatches and (
            self.canary is None or self.canary.ok is None or self._canary_for != identity
        ):
            self.canary = await run_canary(client, self.base_url, self.counter)
            self._canary_for = identity
        return facts

    def diagnostics(self) -> dict[str, Any]:
        return {
            "pin": self.pin.id,
            "pinned_ok": self.pinned_ok,
            "stale": self.stale,
            "stale_reason": self.stale_reason,
            "last_error": self.last_error,
            "facts": None if self.facts is None else self.facts.__dict__.copy(),
            "mismatches": list(self.mismatches),
            "canary": None if self.canary is None else {
                "ok": self.canary.ok,
                "error": self.canary.error,
                "cases": [c.__dict__.copy() for c in self.canary.cases],
            },
        }
