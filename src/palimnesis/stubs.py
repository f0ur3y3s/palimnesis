"""Versioned stub text and Unicode-safe exact chunking for masked content.

Implements ARC's observation stubs (docs/papers.md): a masked item becomes an
id plus metadata plus head/tail previews, and older stubs collapse to bare
ids. Adaptations, all from docs/plans/phase2.md and D14:

- sizes are tokens under an injected ``count`` (the pinned tokenizer in
  production), not characters;
- addresses are ``§ALIAS.N`` (block N of the occurrence); the database stores
  aliases without ``§``;
- a run of collapsed messages becomes one user-role span note (D14.13), since
  bare ids forever are unbounded.

Exactness (v1_plan "Archival exactness"): previews and chunks are exact
substrings of the archived text. Offsets are in code points. Cuts back off
over combining marks, ZWJ, variation selectors, emoji modifiers, tag
characters, regional-indicator pairs, CRLF and surrogate pairs, so a cut
never lands inside a user-perceived character when a whole one fits. Lone
surrogates are kept (WTF-8). Sizing is a galloping binary search over
character cuts, so text is never decoded from a byte cut and U+FFFD is
never produced. Hangul jamo sequences and other extended grapheme rules are
not modelled; a cut there is still exact, only less tidy.

Every function is pure and makes no upstream calls.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from typing import Callable, Iterator

STUB_FORMAT = "s1"
HINT_S1 = "archived exactly; not shown"
TOOL_RESULT_HEAD_TOKENS = 192
TOOL_RESULT_TAIL_TOKENS = 96
REASONING_HEAD_TOKENS = 64
REASONING_TAIL_TOKENS = 32

Count = Callable[[str], int]

_ZWJ = "\u200d"
_ALIAS_CHARS = frozenset("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


# --- safe cut points ---------------------------------------------------------


def _is_extender(ch: str) -> bool:
    """A code point that attaches to the one before it."""
    cp = ord(ch)
    return (
        ch == _ZWJ
        or unicodedata.category(ch) in ("Mn", "Me", "Mc")  # includes variation selectors
        or 0x1F3FB <= cp <= 0x1F3FF  # emoji skin-tone modifiers
        or 0xE0020 <= cp <= 0xE007F  # emoji tag characters
    )


def _is_regional(ch: str) -> bool:
    return 0x1F1E6 <= ord(ch) <= 0x1F1FF


def is_safe_cut(text: str, i: int) -> bool:
    """Whether cutting ``text`` at code-point offset ``i`` keeps clusters whole."""
    if i <= 0 or i >= len(text):
        return True
    prev, ch = text[i - 1], text[i]
    if prev == "\r" and ch == "\n":
        return False
    if prev == _ZWJ or _is_extender(ch):
        return False
    if "\ud800" <= prev <= "\udbff" and "\udc00" <= ch <= "\udfff":
        return False
    if _is_regional(prev) and _is_regional(ch):
        run = 0
        while i - 1 - run >= 0 and _is_regional(text[i - 1 - run]):
            run += 1
        return run % 2 == 0
    return True


def _largest(limit: int, fits: Callable[[int], bool]) -> int:
    """Largest n in [0, limit] with fits(n), given fits(0); galloping then bisection."""
    good, probe = 0, 1
    while probe <= limit and fits(probe):
        good, probe = probe, probe * 2
    bad = min(probe, limit + 1)
    while bad - good > 1:
        mid = (good + bad) // 2
        if fits(mid):
            good = mid
        else:
            bad = mid
    return good


def fit_prefix(text: str, fits: Callable[[str], bool]) -> str:
    """The longest prefix of ``text`` ending on a safe cut with ``fits(prefix)``.

    ``fits("")`` must hold. The result is checked, not assumed, so a counter
    that is not monotone over prefixes still never yields an oversized prefix."""
    limit = len(text)
    while True:
        end = _largest(limit, lambda n: fits(text[:n]))
        while end > 0 and not is_safe_cut(text, end):
            end -= 1
        if fits(text[:end]):
            return text[:end]
        limit = end - 1


def _fit_suffix_start(text: str, floor: int, fits: Callable[[str], bool]) -> int:
    """Smallest safe start >= floor with ``fits(text[start:])``."""
    n, limit = len(text), len(text) - floor
    while True:
        start = n - _largest(limit, lambda k: fits(text[n - k:]))
        while start < n and not is_safe_cut(text, start):
            start += 1
        if fits(text[start:]):
            return start
        limit = n - start - 1


# --- chunks ------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    """One exact piece of an archived text. ``sha256`` covers the whole text
    (as encoded by ``encoding``), so reassembly can be verified end to end."""

    offset: int
    length: int
    total_length: int
    encoding: str
    sha256: str
    next_offset: int | None
    text: str


def encoding_of(text: str) -> str:
    """``wtf-8`` when the text holds a surrogate code point, else ``utf-8`` (D10.15)."""
    return "wtf-8" if any("\ud800" <= ch <= "\udfff" for ch in text) else "utf-8"


def _bytes(text: str) -> bytes:
    return text.encode("utf-8", "surrogatepass")


def chunks(text: str, max_tokens: int, *, count: Count) -> Iterator[Chunk]:
    """Split ``text`` into exact chunks of at most ``max_tokens`` each.

    Cuts prefer safe points; when not even one whole cluster fits, a chunk is
    cut at a plain code point, which still reassembles exactly. Empty text is
    one empty chunk. Raises ``ValueError`` when no single code point fits."""
    total = len(text)
    encoding = encoding_of(text)
    sha = hashlib.sha256(_bytes(text)).hexdigest()
    if total == 0:
        yield Chunk(0, 0, 0, encoding, sha, None, "")
        return
    offset = 0
    while offset < total:
        rest = text[offset:]
        piece = fit_prefix(rest, lambda s: count(s) <= max_tokens)
        if not piece:
            length = _largest(len(rest), lambda n: count(rest[:n]) <= max_tokens)
            if length == 0:
                raise ValueError(
                    f"max_tokens={max_tokens} is smaller than the code point at offset {offset}"
                )
            piece = rest[:length]
        end = offset + len(piece)
        yield Chunk(offset, len(piece), total, encoding, sha, end if end < total else None, piece)
        offset = end


# --- stub text (format s1) ---------------------------------------------------


def _check_alias(alias: str) -> None:
    if not alias or any(ch not in _ALIAS_CHARS for ch in alias):
        raise ValueError(f"alias must be the stored form (Crockford base32, no §): {alias!r}")


def bare_ref(alias: str, block: int | None = None) -> str:
    """``§ALIAS`` or ``§ALIAS.N``: the collapsed form of a stub."""
    _check_alias(alias)
    return f"§{alias}" if block is None else f"§{alias}.{block}"


def _lines(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}" if n == 1 else f"{n:,} {word}s"


def _snap_head(text: str, end: int) -> int:
    """Pull a head cut back to the end of its last whole line, if it has one."""
    newline = text.rfind("\n", 0, end)
    return newline + 1 if 0 <= newline and newline + 1 < end else end


def _snap_tail(text: str, start: int, stop: int) -> int:
    """Push a tail cut forward to the start of its first whole line, if it has one."""
    if start == 0 or text[start - 1] == "\n":
        return start
    newline = text.find("\n", start, stop)
    return newline + 1 if 0 <= newline and newline + 1 < stop else start


def _stub(kind: str, alias: str, block: int, text: str, count: Count,
          head_tokens: int, tail_tokens: int) -> str:
    _check_alias(alias)
    sha = hashlib.sha256(_bytes(text)).hexdigest()[:6]
    header = (f"[palimnesis {STUB_FORMAT} {bare_ref(alias, block)} {kind} · {count(text):,} tok · "
              f"{_plural(_lines(text), 'line')} · sha {sha}]")
    if not text:
        return header
    if count(text) <= head_tokens + tail_tokens:
        return f"{header}\n{text}"
    head_end = len(fit_prefix(text, lambda s: count(s) <= head_tokens))
    head_end = _snap_head(text, head_end)
    tail_start = _fit_suffix_start(text, head_end, lambda s: count(s) <= tail_tokens)
    tail_start = _snap_tail(text, tail_start, len(text))
    head, middle, tail = text[:head_end], text[head_end:tail_start], text[tail_start:]
    if not middle:
        return f"{header}\n{text}"
    return (f"{header}\n{head}{'' if head.endswith(chr(10)) or not head else chr(10)}"
            f"…[{count(middle):,} tok not shown]…\n"
            f"{tail}{'' if tail.endswith(chr(10)) or not tail else chr(10)}"
            f"[{HINT_S1}]")


def tool_result_stub(alias: str, block: int, text: str, *, count: Count,
                     head_tokens: int = TOOL_RESULT_HEAD_TOKENS,
                     tail_tokens: int = TOOL_RESULT_TAIL_TOKENS) -> str:
    """The s1 stub for a masked tool result: header, head preview, omission
    marker, tail preview, hint. A text that fits both previews is shown whole."""
    return _stub("tool_result", alias, block, text, count, head_tokens, tail_tokens)


def reasoning_stub(alias: str, block: int, text: str, *, count: Count,
                   head_tokens: int = REASONING_HEAD_TOKENS,
                   tail_tokens: int = REASONING_TAIL_TOKENS) -> str:
    """The s1 stub for masked reasoning (D14.12); same layout as a tool result."""
    return _stub("reasoning", alias, block, text, count, head_tokens, tail_tokens)


def span_note(first_alias: str, last_alias: str, n_messages: int, *,
              tokens: int | None = None) -> str:
    """The proxy-authored user-role note standing for a collapsed span (D14.13)."""
    span = bare_ref(first_alias) if first_alias == last_alias else (
        f"{bare_ref(first_alias)}–{bare_ref(last_alias)}")
    size = "" if tokens is None else f" · {tokens:,} tok"
    return (f"[palimnesis {STUB_FORMAT} span {span} · {_plural(n_messages, 'message')}{size} · "
            f"{HINT_S1}]")
