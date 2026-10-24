"""Stable, session-scoped short addresses for archived records.

Internally every record has a full collision-resistant ID. The model-facing
address is a short alias: the shortest prefix (at least ``MIN_LENGTH``) of
the Crockford base32 encoding of ``hashfn(target_id)`` that is not already
issued in the session. Aliases are stored when issued and never reassigned,
so a later collision extends the *new* alias and an issued one keeps its
meaning. ``<alias>.<n>`` addresses block ``n`` of the target.

Resolution only ever returns the record an alias was issued for. Anything
else is ``Ambiguous`` (a prefix shared by several aliases) or ``Unknown``
(with suggestions); a near miss is never substituted.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from typing import Callable

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
MIN_LENGTH = 6
MAX_SUGGESTIONS = 5
_NORMALIZE = str.maketrans({"I": "1", "L": "1", "O": "0"})


@dataclass(frozen=True)
class Hit:
    target_id: str
    block: int | None = None


@dataclass(frozen=True)
class Ambiguous:
    candidates: list[str]


@dataclass(frozen=True)
class Unknown:
    suggestions: list[str] = field(default_factory=list)


def _sha256(target_id: str) -> bytes:
    return hashlib.sha256(target_id.encode("utf-8")).digest()


def _base32(data: bytes) -> str:
    bits = int.from_bytes(data, "big")
    n = len(data) * 8 // 5
    shift = len(data) * 8 - 5
    return "".join(CROCKFORD[(bits >> (shift - 5 * i)) & 31] for i in range(n))


def issue_alias(
    conn: sqlite3.Connection,
    scope_session_id: str,
    target_id: str,
    *,
    hashfn: Callable[[str], bytes] = _sha256,
) -> str:
    """Return the target's alias, issuing one if it has none. Runs in the caller's transaction."""
    row = conn.execute(
        "SELECT alias FROM aliases WHERE target_id = ?", (target_id,)
    ).fetchone()
    if row:
        return row[0]
    encoded = _base32(hashfn(target_id))
    for length in range(MIN_LENGTH, len(encoded) + 1):
        alias = encoded[:length]
        taken = conn.execute(
            "SELECT 1 FROM aliases WHERE scope_session_id = ? AND alias = ?",
            (scope_session_id, alias),
        ).fetchone()
        if not taken:
            conn.execute(
                "INSERT INTO aliases VALUES (?, ?, ?)", (scope_session_id, alias, target_id)
            )
            return alias
    raise ValueError(f"hash of {target_id!r} is exhausted without a free alias")


def _parse(text: str) -> tuple[str, int | None] | None:
    alias, dot, block = text.strip().upper().translate(_NORMALIZE).partition(".")
    if not alias or any(ch not in CROCKFORD for ch in alias):
        return None
    if not dot:
        return alias, None
    if not block.isdigit():
        return None
    return alias, int(block)


def _distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def resolve(conn: sqlite3.Connection, scope_session_id: str, text: str):
    parsed = _parse(text)
    if parsed is None:
        return Unknown()
    alias, block = parsed
    row = conn.execute(
        "SELECT target_id FROM aliases WHERE scope_session_id = ? AND alias = ?",
        (scope_session_id, alias),
    ).fetchone()
    if row:
        return Hit(row[0], block)
    extensions = [
        r[0]
        for r in conn.execute(
            "SELECT alias FROM aliases WHERE scope_session_id = ? AND substr(alias, 1, ?) = ?"
            " ORDER BY alias",
            (scope_session_id, len(alias), alias),
        )
    ]
    if len(extensions) > 1:
        return Ambiguous(extensions)
    if extensions:
        return Unknown(extensions)
    near = conn.execute(
        "SELECT alias FROM aliases WHERE scope_session_id = ? AND substr(alias, 1, 2) = ?",
        (scope_session_id, alias[:2]),
    ).fetchall()
    ranked = sorted((_distance(alias, a), a) for (a,) in near)
    return Unknown([a for d, a in ranked if d <= 2][:MAX_SUGGESTIONS])
