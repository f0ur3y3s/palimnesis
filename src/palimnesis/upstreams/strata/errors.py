"""Strata 0.1.48 error shapes (contracts §1.2; docs/probes/strata.md).

A transport error or a 5xx may mean the server restarted, possibly with another
context size or build, so the facts are re-read. A context overflow is a 400 whose
message reads ``request exceeds the context window: ...`` (recorded live).
"""

from __future__ import annotations

_CONTEXT_WINDOW = b"exceeds the context window"


def is_context_overflow(status: int | None, body: bytes = b"") -> bool:
    return status == 400 and _CONTEXT_WINDOW in body


def staleness_reason(status: int | None, body: bytes = b"") -> str | None:
    """Why an upstream outcome invalidates the facts; ``status=None`` is a transport error."""
    if status is None:
        return "transport_error"
    if status >= 500:
        return "upstream_5xx"
    if is_context_overflow(status, body):
        return "context_window_400"
    return None


class StrataErrors:
    """``palimnesis.profile.ErrorMap`` for Strata."""

    def staleness_reason(self, status: int | None, body: bytes = b"") -> str | None:
        return staleness_reason(status, body)

    def is_context_overflow(self, status: int | None, body: bytes = b"") -> bool:
        return is_context_overflow(status, body)
