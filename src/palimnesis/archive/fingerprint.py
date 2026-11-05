"""Request fingerprints and retry hints (contracts §5, §6).

Fingerprint v1 is SHA-256 over canonical JSON of the endpoint, session,
branch and every top-level request field except transport-only ones. The
full visible message list stands for the visible parent (D10.17).
Canonical form: object keys sorted, arrays in order, strings exact (no
Unicode normalization), numbers as parsed (``1`` and ``1.0`` differ). Any
change to this function's output requires bumping ``FINGERPRINT_VERSION``.

Retry-count headers are bounded hints only: never identity, never part of
the fingerprint.
"""

from __future__ import annotations

import hashlib
import json
from typing import Mapping

FINGERPRINT_VERSION = 1
# v2 is v1 with ``ignored_keys`` dropped at any depth (Messages: ``cache_control``, D95);
# Chat ignores none and stays v1, so its fingerprints are unchanged.
FINGERPRINT_VERSION_IGNORING = 2
TRANSPORT_ONLY_FIELDS = frozenset({"stream", "stream_options"})
RETRY_HINT_HEADERS = ("x-stainless-retry-count",)
MAX_RETRY_HINT = 100


def _without(value, keys: frozenset[str]):
    if isinstance(value, Mapping):
        return {k: _without(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [_without(v, keys) for v in value]
    return value


def fingerprint_v1(endpoint: str, session: str, branch: str, request: Mapping,
                   transport_fields: frozenset[str] = TRANSPORT_ONLY_FIELDS,
                   ignored_keys: frozenset[str] = frozenset()) -> str:
    """``transport_fields`` are the client protocol's top-level transport-only fields
    (``ClientProtocol.transport_fields``; the default is Chat's). ``ignored_keys`` are keys
    dropped at any depth (Messages: ``cache_control``, which moves every turn and renders
    nothing). Chat ignores none, so its fingerprints are unchanged."""
    semantic = {k: v for k, v in request.items() if k not in transport_fields}
    if ignored_keys:
        semantic = _without(semantic, ignored_keys)
    canonical = json.dumps(
        {"v": FINGERPRINT_VERSION_IGNORING if ignored_keys else FINGERPRINT_VERSION,
         "endpoint": endpoint, "session": session,
         "branch": branch, "request": semantic},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8", "surrogatepass")).hexdigest()


def parse_retry_hint(headers: Mapping[str, str]) -> int | None:
    lowered = {k.lower(): v for k, v in headers.items()}
    for name in RETRY_HINT_HEADERS:
        value = lowered.get(name)
        if value is None:
            continue
        if len(value) <= 3 and value.isascii() and value.isdigit():
            hint = int(value)
            return hint if hint <= MAX_RETRY_HINT else None
        return None
    return None
