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
TRANSPORT_ONLY_FIELDS = frozenset({"stream", "stream_options"})
RETRY_HINT_HEADERS = ("x-stainless-retry-count",)
MAX_RETRY_HINT = 100


def fingerprint_v1(endpoint: str, session: str, branch: str, request: Mapping) -> str:
    semantic = {k: v for k, v in request.items() if k not in TRANSPORT_ONLY_FIELDS}
    canonical = json.dumps(
        {"v": FINGERPRINT_VERSION, "endpoint": endpoint, "session": session,
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
