"""palimnesis.stubs: versioned stub text and Unicode-safe exact chunking (plan slice 6).

Counters are deterministic fakes; the real tokenizer is injected by the view.
"""

from __future__ import annotations

import hashlib
import random
import re

import pytest

from palimnesis import stubs


def byte_tokens(text: str) -> int:
    return len(text.encode("utf-8", "surrogatepass")) // 4


def word_tokens(text: str) -> int:
    return len(text.split())


def char_tokens(text: str) -> int:
    return len(text)


# Atoms are user-perceived characters: a cut inside one is a corruption.
ATOMS = [
    "a", "Z", " ", "\n", "\r\n", "\t", "漢", "字", "é",
    "e\u0301",                      # e + combining acute
    "a\u0301\u0323\u0302",          # stacked combining marks
    "\U0001F468\u200d\U0001F469\u200d\U0001F467\u200d\U0001F466",  # ZWJ family
    "\U0001F44D\U0001F3FD",         # thumbs up + skin tone
    "❤\ufe0f",                 # heart + variation selector 16
    "\U0001F1FA\U0001F1F8",         # regional-indicator flag
    "\ud83d",                       # lone high surrogate (WTF-8)
    "\ude00",                       # lone low surrogate
    "क\u093f",                      # Devanagari consonant + spacing vowel sign
]


def atom_text(rng: random.Random, n: int) -> tuple[str, set[int]]:
    """A random text and the set of offsets that fall between atoms."""
    parts, boundaries, offset = [], {0}, 0
    for _ in range(n):
        atom = rng.choice(ATOMS)
        # Two adjacent lone surrogates would form a pair; keep them lone.
        if parts and parts[-1] == "\ud83d" and atom == "\ude00":
            atom = "a"
        parts.append(atom)
        offset += len(atom)
        boundaries.add(offset)
    return "".join(parts), boundaries


def encode(text: str) -> bytes:
    return text.encode("utf-8", "surrogatepass")


# --- chunks ------------------------------------------------------------------


def test_chunks_roundtrip_with_metadata():
    text = "line one\r\nline two 漢字\n\U0001F468\u200d\U0001F469\u200d\U0001F467 end\ud83d!"
    parts = list(stubs.chunks(text, 3, count=byte_tokens))

    assert "".join(c.text for c in parts) == text
    assert len(parts) > 1
    sha = hashlib.sha256(encode(text)).hexdigest()
    offset = 0
    for i, chunk in enumerate(parts):
        assert chunk.offset == offset
        assert chunk.length == len(chunk.text)
        assert chunk.total_length == len(text)
        assert chunk.encoding == "wtf-8"
        assert chunk.sha256 == sha
        expected_next = None if i == len(parts) - 1 else offset + chunk.length
        assert chunk.next_offset == expected_next
        assert byte_tokens(chunk.text) <= 3
        offset += chunk.length
    assert offset == len(text)


def test_chunks_of_plain_text_are_utf8():
    [chunk] = stubs.chunks("hello", 100, count=byte_tokens)

    assert (chunk.offset, chunk.length, chunk.total_length, chunk.next_offset) == (0, 5, 5, None)
    assert chunk.encoding == "utf-8"
    assert chunk.sha256 == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_empty_text_is_one_empty_chunk():
    [chunk] = stubs.chunks("", 10, count=byte_tokens)

    assert chunk.text == ""
    assert (chunk.offset, chunk.length, chunk.total_length, chunk.next_offset) == (0, 0, 0, None)
    assert chunk.sha256 == hashlib.sha256(b"").hexdigest()


def test_whitespace_only_text_reassembles_exactly():
    text = " \t\r\n\r\n   \n\u00a0\u3000"
    assert "".join(c.text for c in stubs.chunks(text, 1, count=char_tokens)) == text


@pytest.mark.parametrize("seed", range(40))
def test_chunks_cut_only_between_atoms_property(seed):
    rng = random.Random(seed)
    text, boundaries = atom_text(rng, rng.randint(0, 200))
    max_tokens = rng.randint(7, 40)  # >= the largest atom (ZWJ family: 25 bytes = 6 tokens)

    parts = list(stubs.chunks(text, max_tokens, count=byte_tokens))

    assert "".join(c.text for c in parts) == text
    for chunk in parts:
        assert chunk.offset in boundaries
        assert chunk.offset + chunk.length in boundaries
        assert byte_tokens(chunk.text) <= max_tokens
        assert "\ufffd" not in chunk.text
        assert encode(chunk.text).decode("utf-8", "surrogatepass") == chunk.text
    assert all(c.length > 0 for c in parts) or text == ""


def test_chunks_split_inside_a_cluster_only_when_no_whole_cluster_fits():
    family = "\U0001F468\u200d\U0001F469\u200d\U0001F467\u200d\U0001F466"  # 7 code points, 25 bytes
    parts = list(stubs.chunks(family, 2, count=byte_tokens))

    assert "".join(c.text for c in parts) == family
    assert all(byte_tokens(c.text) <= 2 for c in parts)


def test_chunks_reject_a_budget_no_single_code_point_fits():
    with pytest.raises(ValueError, match="max_tokens"):
        list(stubs.chunks("abc", 0, count=lambda s: len(s)))


# --- s1 stubs ----------------------------------------------------------------


ROWS = "".join(f"row {i:02d}\n" for i in range(40))


def test_stub_s1_golden_text():
    stub = stubs.tool_result_stub("K7Q2MX", 0, ROWS, count=word_tokens,
                                  head_tokens=4, tail_tokens=2)

    assert stub == (
        "[palimnesis s1 §K7Q2MX.0 tool_result · 80 tok · 40 lines · sha df8192]\n"
        "row 00\n"
        "row 01\n"
        "…[74 tok not shown]…\n"
        "row 39\n"
        "[archived exactly; not shown]"
    )


def test_stub_s1_header_uses_thousands_separators_and_defaults():
    text = "x " * 18432
    stub = stubs.tool_result_stub("K7Q2MX", 3, text, count=word_tokens)

    assert stub.splitlines()[0] == (
        f"[palimnesis s1 §K7Q2MX.3 tool_result · 18,432 tok · 1 line · "
        f"sha {hashlib.sha256(text.encode()).hexdigest()[:6]}]"
    )
    assert "…[18,144 tok not shown]…" in stub  # 18,432 − 192 head − 96 tail


def test_stub_that_fits_shows_everything_without_omission_marker():
    stub = stubs.tool_result_stub("K7Q2MX", 0, "short\noutput", count=word_tokens)

    assert stub == (
        "[palimnesis s1 §K7Q2MX.0 tool_result · 2 tok · 2 lines · sha "
        f"{hashlib.sha256(b'short' + b'\n' + b'output').hexdigest()[:6]}]\n"
        "short\noutput"
    )


def test_stub_of_empty_text_is_header_only():
    assert stubs.tool_result_stub("K7Q2MX", 0, "", count=word_tokens) == (
        "[palimnesis s1 §K7Q2MX.0 tool_result · 0 tok · 0 lines · sha e3b0c4]"
    )


def test_reasoning_stub_names_its_kind():
    text = "think " * 500
    stub = stubs.reasoning_stub("ABCDEF", 1, text, count=word_tokens)

    assert stub.startswith("[palimnesis s1 §ABCDEF.1 reasoning · 500 tok · 1 line · sha ")
    assert "tok not shown]…" in stub


def test_alias_must_be_the_stored_form_without_section_sign():
    with pytest.raises(ValueError):
        stubs.tool_result_stub("§K7Q2MX", 0, "x", count=word_tokens)


HINT = "[archived exactly; not shown]"
MARKER = re.compile(r"(?:^|(?<=\n))…\[[\d,]+ tok not shown\]…\n")


def _previews(stub: str, text: str) -> tuple[list[str], list[str]] | None:
    """Candidate (heads, tails) of a stub with an omission marker; None when
    nothing was omitted. A separator newline follows each preview unless it
    already ends a line, so the exact preview is one of two readings."""
    body = stub.split("\n", 1)[1]
    match = MARKER.search(body)
    if match is None:
        return None
    assert body.endswith("\n" + HINT)
    head_part, tail_part = body[:match.start()], body[match.end():-len(HINT)]
    assert head_part.endswith("\n") and tail_part.endswith("\n")
    heads = [h for h in (head_part, head_part[:-1]) if text.startswith(h)]
    tails = [t for t in (tail_part, tail_part[:-1]) if text.endswith(t)]
    assert heads and tails
    return heads, tails


@pytest.mark.parametrize("seed", range(40))
def test_stub_preview_cuts_unicode_safe(seed):
    rng = random.Random(1000 + seed)
    text, boundaries = atom_text(rng, rng.randint(1, 400))
    head_tokens, tail_tokens = rng.randint(7, 60), rng.randint(7, 30)

    stub = stubs.tool_result_stub("K7Q2MX", 0, text, count=byte_tokens,
                                  head_tokens=head_tokens, tail_tokens=tail_tokens)

    assert "\ufffd" not in stub
    previews = _previews(stub, text)
    if previews is None:
        assert stub.split("\n", 1)[1] == text
        return
    heads, tails = previews
    assert any(len(h) in boundaries and byte_tokens(h) <= head_tokens for h in heads)
    assert any(len(text) - len(t) in boundaries and byte_tokens(t) <= tail_tokens
               for t in tails)
    assert min(map(len, heads)) + min(map(len, tails)) < len(text)


@pytest.mark.parametrize("counter", [byte_tokens, word_tokens, char_tokens])
@pytest.mark.parametrize("seed", range(10))
def test_stub_respects_token_caps(counter, seed):
    rng = random.Random(2000 + seed)
    text, _ = atom_text(rng, rng.randint(200, 2000))

    stub = stubs.tool_result_stub("K7Q2MX", 12, text, count=counter,
                                  head_tokens=50, tail_tokens=20)

    previews = _previews(stub, text)
    if previews is not None:
        heads, tails = previews
        assert any(counter(h) <= 50 for h in heads) and any(counter(t) <= 20 for t in tails)
    # Header, marker and hint are fixed overhead; previews add at most their caps.
    overhead = counter(stub.split("\n", 1)[0]) + counter("…[999,999 tok not shown]…") \
        + counter(HINT) + 8
    assert counter(stub) <= 50 + 20 + overhead


def test_token_sizing_never_emits_replacement_char():
    tricky = ("\ud83d" + "e\u0301" + "\U0001F468\u200d\U0001F469" + "漢" + "\r\n") * 300
    for cap in (1, 2, 3, 5, 8, 13):
        stub = stubs.tool_result_stub("K7Q2MX", 0, tricky, count=byte_tokens,
                                      head_tokens=cap, tail_tokens=cap)
        assert "\ufffd" not in stub
        assert "\ufffd" not in "".join(c.text for c in stubs.chunks(tricky, cap + 6,
                                                                       count=byte_tokens))
        encode(stub)  # every surrogate in it is one the original had


def test_crlf_is_never_split_by_a_preview():
    text = "a\r\n" * 100
    stub = stubs.tool_result_stub("K7Q2MX", 0, text, count=char_tokens,
                                  head_tokens=4, tail_tokens=4)
    # Head: 4 chars "a\r\na" snap back to the line end. Tail: the 4-char suffix
    # "\na\r\n" would split a CRLF, so it moves forward to "a\r\n".
    assert stub == (
        "[palimnesis s1 §K7Q2MX.0 tool_result · 300 tok · 100 lines · sha 516a01]\n"
        "a\r\n"
        "…[294 tok not shown]…\n"
        "a\r\n"
        "[archived exactly; not shown]"
    )


# --- bare refs and span notes ------------------------------------------------


def test_bare_ref():
    assert stubs.bare_ref("K7Q2MX") == "§K7Q2MX"
    assert stubs.bare_ref("K7Q2MX", 2) == "§K7Q2MX.2"


def test_span_note_text():
    assert stubs.span_note("AAAAAA", "BBBBBB", 37, tokens=12345) == (
        "[palimnesis s1 span §AAAAAA–§BBBBBB · 37 messages · 12,345 tok · "
        "archived exactly; not shown]"
    )
    assert stubs.span_note("AAAAAA", "AAAAAA", 1) == (
        "[palimnesis s1 span §AAAAAA · 1 message · archived exactly; not shown]"
    )
