"""Lossless raw-body delta codec (v1_plan "Archival exactness and stable addresses").

A raw request body is stored either whole or as a delta against a parent body
from the same session/branch (the raw-storage parent, distinct from the
logical conversation parent). Everything works on bytes: a prefix or suffix
boundary may split a UTF-8 character; only the reconstructed body is decoded.

Record formats (``Delta.format``):

- ``0`` snapshot: ``payload`` is the whole body; ``prefix_len == suffix_len == 0``.
- ``1`` prefix+suffix: ``parent[:prefix_len] + payload``; ``suffix_len == 0``.
- ``2`` prefix+middle+suffix_len: ``parent[:prefix_len] + payload +
  parent[len(parent) - suffix_len:]`` (empty when ``suffix_len == 0``). The
  suffix is measured on the bytes after the common prefix in both bodies, so
  the reused head and tail never overlap in either body (D10.7: both formats
  exist; v2 is adopted only on measured savings).

``decode`` checks the format, non-negative lengths, ``prefix_len <=
len(parent)``, ``suffix_len <= len(parent) - prefix_len``, the reconstructed
length and the SHA-256 of the whole body, and raises ``DeltaError`` rather
than ever returning wrong bytes. A snapshot ignores any parent supplied.

``choose`` is the pure snapshot policy. ``depth`` is the number of deltas
between the parent and its nearest snapshot (a snapshot parent has depth 0);
the new record would sit at ``depth + 1``, and a snapshot is taken when that
exceeds ``max_depth``. So with the default 32 a chain is one snapshot followed
by at most 32 deltas. It also snapshots with no (usable) parent, on a
system/tool-schema change, and when ``stored_size`` of the delta is not
strictly smaller than the snapshot's.

``stored_size`` is payload bytes plus ``RECORD_OVERHEAD``, a notional
fixed-width header shared by all formats; the parent reference belongs to the
archive row, not to this codec.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


class DeltaError(Exception):
    """A record cannot be reconstructed to exactly the body it was made from."""


SNAPSHOT = 0
PREFIX_SUFFIX = 1
PREFIX_MIDDLE_SUFFIX = 2


@dataclass(frozen=True)
class Delta:
    format: int
    prefix_len: int
    payload: bytes
    suffix_len: int
    total_len: int
    sha256: bytes


def _common_prefix(a: bytes, b: bytes) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def snapshot(body: bytes) -> Delta:
    return Delta(SNAPSHOT, 0, body, 0, len(body), hashlib.sha256(body).digest())


def _common_suffix(a: bytes, b: bytes) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[-1 - i] == b[-1 - i]:
        i += 1
    return i


def encode(parent: bytes, body: bytes, variant: int) -> Delta:
    if variant not in (1, 2):
        raise ValueError(f"unknown delta variant {variant!r}; expected 1 or 2")
    digest = hashlib.sha256(body).digest()
    p = _common_prefix(parent, body)
    if variant == 1:
        return Delta(PREFIX_SUFFIX, p, body[p:], 0, len(body), digest)
    # Suffix measured on the bytes after the prefix in both bodies, so the
    # reused head and tail never overlap in either one.
    s = _common_suffix(parent[p:], body[p:])
    return Delta(PREFIX_MIDDLE_SUFFIX, p, body[p : len(body) - s], s, len(body), digest)


def decode(delta: Delta, parent: bytes | None) -> bytes:
    fmt, prefix_len, suffix_len = delta.format, delta.prefix_len, delta.suffix_len
    if fmt not in (SNAPSHOT, PREFIX_SUFFIX, PREFIX_MIDDLE_SUFFIX):
        raise DeltaError(f"unknown delta format {fmt!r}")
    if prefix_len < 0 or suffix_len < 0:
        raise DeltaError("negative reuse length")
    if fmt == SNAPSHOT:
        if prefix_len or suffix_len:
            raise DeltaError("snapshot record reuses parent bytes")
        body = delta.payload
    else:
        if parent is None:
            raise DeltaError("delta record requires its parent body")
        if fmt == PREFIX_SUFFIX and suffix_len:
            raise DeltaError("v1 record carries a suffix length")
        if prefix_len > len(parent):
            raise DeltaError("prefix length exceeds parent length")
        if suffix_len > len(parent) - prefix_len:
            raise DeltaError("reused prefix and suffix overlap in the parent")
        tail = parent[len(parent) - suffix_len :] if suffix_len else b""
        body = parent[:prefix_len] + delta.payload + tail
    if len(body) != delta.total_len:
        raise DeltaError("reconstructed length does not match total length")
    if hashlib.sha256(body).digest() != delta.sha256:
        raise DeltaError("reconstructed body does not match its SHA-256")
    return body


# Fixed-width record header: format (1) + prefix_len (8) + suffix_len (8)
# + total_len (8) + sha256 (32). Identical for every format.
RECORD_OVERHEAD = 57


def stored_size(delta: Delta) -> int:
    return len(delta.payload) + RECORD_OVERHEAD


def choose(
    parent: bytes | None,
    body: bytes,
    *,
    depth: int,
    max_depth: int = 32,
    schema_changed: bool,
    variant: int,
) -> Delta:
    full = snapshot(body)
    if parent is None or schema_changed or depth + 1 > max_depth:
        return full
    delta = encode(parent, body, variant)
    return delta if stored_size(delta) < stored_size(full) else full
