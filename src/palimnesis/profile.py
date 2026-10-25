"""The upstream profile: everything the core knows about one backend and version (D15 amended).

Budgets, views and recall see an upstream only through an ``UpstreamProfile``:

- ``counter`` (``Counter``): exact prompt counts as the upstream renders them, plus the
  tokenizer's added-token strings (raw text containing one tokenizes as that token).
- ``facts`` (``FactsReader``): upstream facts read, never assumed (``n_ctx`` and an
  identity tuple), their staleness and the pin verdict ``pinned_ok``.
- ``cross_check`` (``CrossCheck``): the startup counting canary and per-call ``usage``
  parsing from a Chat Completions response.
- ``cache_model`` (``CacheReuseModel``): expected prefix-cache reuse.
- ``errors`` (``ErrorMap``): which upstream outcomes invalidate the facts, and which are
  context overflows.
- ``rules`` (``TemplateRules``): template behaviours the view builder relies on. A
  profile whose rules the core does not implement runs view-disabled (D14.9).

``load(name, base_url)`` resolves a profile name through ``REGISTRY``, a map of
``"module:callable"`` strings, so this module imports no backend. Backends live in
``palimnesis.upstreams.<backend>``; the core never imports them directly.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

DEFAULT_PROFILE = "strata-0.1.48"

REGISTRY: dict[str, str] = {
    "strata-0.1.48": "palimnesis.upstreams.strata:profile",
}


class UnknownProfile(ValueError):
    """The configured profile name is not in ``REGISTRY``."""


@dataclass(frozen=True)
class UpstreamFacts:
    """Backend-neutral facts: the context size and what identifies the served build."""

    n_ctx: int
    identity: tuple[str, ...]


@dataclass(frozen=True)
class Usage:
    """Per-call usage reported by the upstream."""

    prompt_tokens: int
    cached_tokens: int
    prompt_ms: float | None


@dataclass(frozen=True)
class TemplateRules:
    # Every earlier assistant turn renders with its reasoning (so masked reasoning is stubbed).
    reasoning_every_turn: bool
    # System messages are accepted only at the start (so span notes are user-role).
    leading_system_only: bool
    # Further named rules a profile declares; the core implements none yet.
    other: frozenset[str] = frozenset()


# The rules the view builder implements.
SUPPORTED_RULES = TemplateRules(reasoning_every_turn=True, leading_system_only=True)


def unsupported_rules(rules: TemplateRules) -> tuple[str, ...]:
    """The declared rules the core does not implement (empty: views may run)."""
    out = []
    if rules.reasoning_every_turn != SUPPORTED_RULES.reasoning_every_turn:
        out.append(f"reasoning_every_turn={rules.reasoning_every_turn}")
    if rules.leading_system_only != SUPPORTED_RULES.leading_system_only:
        out.append(f"leading_system_only={rules.leading_system_only}")
    out += sorted(rules.other - SUPPORTED_RULES.other)
    return tuple(out)


@runtime_checkable
class Counter(Protocol):
    @property
    def added_token_strings(self) -> tuple[str, ...]: ...

    def count(self, text: str) -> int: ...

    def count_cached(self, text: str) -> int: ...

    def count_messages(self, messages: Sequence[Mapping[str, Any]],
                       tools: Sequence[Mapping[str, Any]] | None = None, **kw: Any) -> int: ...

    def render_args(self, body: Mapping[str, Any]) -> tuple[list | None, dict[str, Any]]:
        """``(tools, kw)`` for ``count_messages`` from a Chat Completions body."""
        ...


@runtime_checkable
class FactsReader(Protocol):
    @property
    def facts(self) -> UpstreamFacts | None: ...

    @property
    def stale(self) -> bool: ...

    @property
    def pinned_ok(self) -> bool: ...

    async def refresh(self, client: Any) -> UpstreamFacts | None:
        """Re-read the facts (and re-run the cross-check) when needed; returns the facts held."""
        ...

    def mark_stale(self, reason: str) -> None: ...

    def observe(self, status: int | None, body: bytes = b"") -> bool:
        """Mark stale if this upstream outcome invalidates the facts; returns whether it did."""
        ...

    def diagnostics(self) -> dict[str, Any]: ...


@runtime_checkable
class CrossCheck(Protocol):
    async def canary(self, client: Any) -> Any:
        """Compare local counts with the upstream's own; the result has ``ok: bool | None``."""
        ...

    def usage(self, payload: Mapping[str, Any]) -> Usage | None:
        """Usage from a Chat Completions response or final chunk; None if it carries none."""
        ...


@runtime_checkable
class CacheReuseModel(Protocol):
    def expected(self, previous_render: str | None, render: str) -> int:
        """Prompt tokens the upstream should reuse for ``render`` after ``previous_render``."""
        ...


@runtime_checkable
class ErrorMap(Protocol):
    def staleness_reason(self, status: int | None, body: bytes = b"") -> str | None:
        """Why an outcome invalidates the facts; ``status=None`` is a transport error."""
        ...

    def is_context_overflow(self, status: int | None, body: bytes = b"") -> bool: ...


@dataclass(frozen=True)
class UpstreamProfile:
    id: str
    counter: Counter = field(repr=False)
    facts: FactsReader = field(repr=False)
    cross_check: CrossCheck = field(repr=False)
    cache_model: CacheReuseModel = field(repr=False)
    errors: ErrorMap = field(repr=False)
    rules: TemplateRules


def resolve(name: str) -> str:
    """The ``module:callable`` target for ``name``, or ``UnknownProfile``."""
    try:
        return REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(REGISTRY))
        raise UnknownProfile(f"unknown upstream profile {name!r}; known profiles: {known}") from None


def load(name: str, base_url: str) -> UpstreamProfile:
    """Build the named profile for the upstream at ``base_url``."""
    module, _, attr = resolve(name).partition(":")
    return getattr(importlib.import_module(module), attr)(base_url)
