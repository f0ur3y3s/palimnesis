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
class Segment:
    """One rendered turn of a prompt: its kind, the messages it renders and its tokens.

    ``kind`` is ``head`` (leading system messages, tool schemas and settings preamble),
    ``user``, ``assistant``, ``tool`` (a run of tool results), ``generation`` (the
    generation prompt) or ``unmapped`` (the profile could not map this turn)."""

    kind: str
    messages: tuple[int, ...]  # indices into the rendered messages
    start: int
    end: int


@dataclass(frozen=True)
class Layout:
    """A prompt as the upstream tokenizes it, split into rendered turns."""

    ids: tuple[int, ...]
    segments: tuple[Segment, ...]

    @property
    def generation_start(self) -> int:
        """Where the generation prompt starts (the end when there is none)."""
        last = self.segments[-1] if self.segments else None
        return last.start if last is not None and last.kind == "generation" else len(self.ids)

    def segment_at(self, position: int) -> int | None:
        """Index of the segment holding token ``position`` (None past the end)."""
        for i, s in enumerate(self.segments):
            if s.start <= position < s.end:
                return i
        return None


def common_prefix(a: Sequence[int], b: Sequence[int]) -> int:
    """Length of the longest common prefix of two token sequences."""
    n = min(len(a), len(b))
    i, step = 0, 1024
    while i + step <= n and tuple(a[i:i + step]) == tuple(b[i:i + step]):
        i += step
    while i < n and a[i] == b[i]:
        i += 1
    return i


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

    def encode(self, text: str) -> list[int]:
        """Token ids of ``text`` as the upstream tokenizes it (``len == count(text)``)."""
        ...

    def layout(self, messages: Sequence[Mapping[str, Any]],
               tools: Sequence[Mapping[str, Any]] | None = None, **kw: Any) -> Layout:
        """The rendered prompt's token ids split into turns (``len(ids) == count_messages``)."""
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
    def expected(self, previous: Layout | None, current: Layout) -> int:
        """Estimated prompt tokens the upstream reuses for ``current`` right after it
        served ``previous`` (an estimate: other clients, restarts and eviction can lower
        the real figure)."""
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
