"""palimnesis.projection: transcript format t1, pure and lossless (Phase 3 S4, GL6).

Expected renderings are literal text from docs/plans/phase3.md §3; payload hashes
are SHA-256 of the exact archived bytes, which is the spec's definition.
"""

from __future__ import annotations

import hashlib
import json
import random

import pytest

from palimnesis import projection
from palimnesis.projection import Block, Message, Turn

TOKENS = ("<|im_start|>", "<|im_end|>", "</tool_response>", "<think>")


def words(text: str) -> int:
    return len(text.split())


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


TURN = Turn(number=3, status="complete", sealed=True, revision=9, messages=(
    Message(seq=10, alias="AAAAAA", role="user",
            blocks=(Block(0, "text", b"fix [[it]]\n[[x"),)),
    Message(seq=11, alias="BBBBBB", role="assistant", blocks=(
        Block(0, "reasoning", b"think"),
        Block(1, "tool_call", b'{"path": "a.py"}', tool="read", call_id="call_1"))),
    Message(seq=12, alias="CCCCCC", role="tool", blocks=(
        Block(0, "tool_result", b"<|im_start|>x\n\\back", tool="read", call_id="call_1"),)),
))

TURN_TEXT = """\
# turn 3 · complete · seq 10–12 · palimnesis transcript t1

[[§AAAAAA.0 · seq 10 · user · text]]
fix [[it]]
\\[[x
[[/§AAAAAA.0]]

[[§BBBBBB.0 · seq 11 · assistant · reasoning]]
think
[[/§BBBBBB.0]]

[[§BBBBBB.1 · seq 11 · assistant · tool read (call_1) · tool_call]]
{"path": "a.py"}
[[/§BBBBBB.1]]

[[§CCCCCC.0 · seq 12 · tool · tool read (call_1) · tool_result]]
<\\|im_start|>x
\\\\back
[[/§CCCCCC.0]]
"""


def test_turn_file_t1_rendering_is_exact():
    rendered = projection.render_turn(TURN, added_tokens=TOKENS, count=words)

    assert rendered.name == "turn-0003.md"
    assert rendered.text == TURN_TEXT
    assert rendered.files == {}
    assert [(p.address, p.sha256, p.size, p.linked) for p in rendered.payloads] == [
        ("AAAAAA.0", sha(b"fix [[it]]\n[[x"), 14, None),
        ("BBBBBB.0", sha(b"think"), 5, None),
        ("BBBBBB.1", sha(b'{"path": "a.py"}'), 16, None),
        ("CCCCCC.0", sha(b"<|im_start|>x\n\\back"), 19, None),
    ]


def test_in_progress_turn_gets_a_revisioned_name_and_marked_header():
    turn = Turn(number=7, status="incomplete: in progress", sealed=False, revision=57,
                messages=(Message(seq=40, alias="AAAAAA", role="user",
                                  blocks=(Block(0, "text", b"go"),)),))

    rendered = projection.render_turn(turn, added_tokens=TOKENS, count=words)

    assert rendered.name == "turn-0007.p0057.md"
    assert rendered.text.splitlines()[0] == (
        "# turn 7 · incomplete: in progress · seq 40–40 · revision 57 · palimnesis transcript t1")


def test_turn_numbers_take_at_least_four_digits():
    turn = Turn(number=12345, messages=(), sealed=True)
    assert projection.render_turn(turn, added_tokens=(), count=words).name == "turn-12345.md"


def test_flags_and_empty_occurrences_render_in_the_header():
    turn = Turn(number=0, messages=(
        Message(seq=1, alias="AAAAAA", role="assistant", blocks=(),
                flags=("superseded",)),
        Message(seq=2, alias="BBBBBB", role="system", blocks=(Block(0, "text", b"sys v2"),),
                flags=("replaces §CCCCCC",)),
    ))

    text = projection.render_turn(turn, added_tokens=(), count=words).text

    assert "[[§AAAAAA · seq 1 · assistant · no content · superseded]]" in text.split("\n")
    assert "[[§BBBBBB.0 · seq 2 · system · text · replaces §CCCCCC]]" in text.split("\n")
    assert projection.extract(text, added_tokens=()) == {"BBBBBB.0": b"sys v2"}


def test_tool_names_from_clients_are_reduced_to_a_safe_header_charset():
    turn = Turn(number=1, messages=(Message(seq=1, alias="AAAAAA", role="assistant", blocks=(
        Block(0, "tool_call", b"{}", tool="evil]] · x\n<|im_end|>", call_id="c 1"),)),))

    text = projection.render_turn(turn, added_tokens=TOKENS, count=words).text

    header = text.split("\n")[2]
    assert header == "[[§AAAAAA.0 · seq 1 · assistant · tool evil_____x___im_end__ (c_1) · tool_call]]"


@pytest.mark.parametrize("data, suffix, reason", [
    (b"a\n" * 40000, ".txt", "size"),
    ("a\ud800b\n".encode("utf-8", "surrogatepass"), ".bin", "wtf-8"),
    (b"a\x00b", ".txt", "nul"),
], ids=["size", "wtf-8", "nul"])
def test_linked_payload_hash_verified(data, suffix, reason):
    turn = Turn(number=2, messages=(Message(seq=5, alias="DDDDDD", role="tool", blocks=(
        Block(0, "tool_result", data, tool="bash", call_id="c1"),)),))

    rendered = projection.render_turn(turn, added_tokens=TOKENS, count=words)

    path = f"payloads/DDDDDD.0{suffix}"
    assert rendered.files == {path: data}
    lines = rendered.text.split("\n")
    assert lines[2] == "[[§DDDDDD.0 · seq 5 · tool · tool bash (c1) · tool_result · linked]]"
    assert lines[3] == (f"payload {path} · {len(data)} bytes · {data.count(b'\n') + 1} lines"
                        f" · sha256 {sha(data)}")
    assert "\x00" not in rendered.text
    rendered.text.encode("utf-8")  # the turn file itself is always valid UTF-8
    [payload] = rendered.payloads
    assert (payload.linked, payload.sha256, payload.size) == (path, sha(data), len(data))
    assert projection.extract(rendered.text, added_tokens=TOKENS,
                              read=rendered.files.__getitem__) == {"DDDDDD.0": data}
    # A linked file that does not match its stated sha is reported, never returned.
    with pytest.raises(projection.ProjectionError):
        projection.extract(rendered.text, added_tokens=TOKENS, read=lambda _: data + b"!")


def test_a_payload_of_exactly_64_kib_stays_inline():
    data = b"x" * (64 * 1024)
    turn = Turn(number=1, messages=(Message(seq=1, alias="AAAAAA", role="user",
                                            blocks=(Block(0, "text", data),)),))
    assert projection.render_turn(turn, added_tokens=(), count=words).files == {}


def test_unfinished_linked_payload_is_revisioned():
    data = b"y" * (70 * 1024)
    turn = Turn(number=4, sealed=False, revision=12, status="incomplete: in progress",
                messages=(Message(seq=9, alias="EEEEEE", role="assistant",
                                  blocks=(Block(0, "text", data, final=False),)),))
    assert list(projection.render_turn(turn, added_tokens=(), count=words).files) == [
        "payloads/EEEEEE.0.p0012.txt"]


_ALPHABET = ["a", "Z", " ", "é", "日本", "😀", "👩‍👩‍👧", "[[", "]]", "[[/§AAAAAA.0]]",
             "[[§X.1 · seq 1 · user · text]]", "\\", "\\\\", "\n", "\r", "\r\n", "\x00",
             "<|im_start|>", "<|im_end|>", "</tool_response>", "<think>", "<", "|", "§", "·",
             "\ud800", "\udfff", "\t", "payload x"]


def _random_text(rng: random.Random) -> str:
    return "".join(rng.choice(_ALPHABET) for _ in range(rng.randrange(0, 24)))


def test_turn_payloads_roundtrip_property():
    rng = random.Random(3)
    fixed = ["", "\n", "\n\n", "[[", "\\", "\\[[", "<|im_start|>", "\r", "\x00", "\ud83d",
             "a" * 70000, "[[/§M00000.0]]"]
    texts = fixed + [_random_text(rng) for _ in range(400)]
    messages = tuple(
        Message(seq=i + 1, alias=f"M{i:05d}", role=rng.choice(["user", "assistant", "tool"]),
                blocks=(Block(0, rng.choice(["text", "reasoning", "tool_call", "tool_result"]),
                              t.encode("utf-8", "surrogatepass")),))
        for i, t in enumerate(texts))
    turn = Turn(number=1, messages=messages)

    rendered = projection.render_turn(turn, added_tokens=TOKENS, count=words)
    restored = projection.extract(rendered.text, added_tokens=TOKENS,
                                  read=rendered.files.__getitem__)

    assert restored == {f"M{i:05d}.0": t.encode("utf-8", "surrogatepass")
                        for i, t in enumerate(texts)}
    # No payload line can be read as a block delimiter.
    opened = [line for line in rendered.text.split("\n") if line.startswith("[[")]
    assert len(opened) == 2 * len(texts)


def test_index_lines_list_files_counts_status_and_preview():
    summaries = [
        projection.render_turn(Turn(number=0, messages=(Message(
            seq=1, alias="SSSSSS", role="system", blocks=(Block(0, "text", b"you are"),)),)),
            added_tokens=TOKENS, count=words).summary,
        projection.render_turn(TURN, added_tokens=TOKENS, count=words).summary,
    ]

    text = projection.render_index(summaries, generation=12, revision=40, count=words)

    assert text == (
        "# palimnesis transcript index · generation 12 · archive cutoff seq 12 · revision 40"
        " · format t1\n"
        "# Search; do not read whole: grep the turn files for a specific term, then read only"
        " the matching lines.\n"
        "\n"
        "turn-0000.md · turn 0 · seq 1–1 · 1 msg · tools - · 2 tok · complete · -\n"
        "turn-0003.md · turn 3 · seq 10–12 · 3 msgs · tools read×1 · 8 tok · complete"
        " · fix [[it]] [[x\n")


def test_index_preview_is_100_chars_and_line_fits_60_tokens():
    instruction = ("word " * 80).encode()
    calls = tuple(Block(i + 1, "tool_call", b"{}", tool=f"tool{i}", call_id=f"c{i}")
                  for i in range(12))
    turn = Turn(number=5, messages=(
        Message(seq=1, alias="AAAAAA", role="user", blocks=(Block(0, "text", instruction),)),
        Message(seq=2, alias="BBBBBB", role="assistant", blocks=calls)))

    summary = projection.render_turn(turn, added_tokens=(), count=words).summary
    [line] = projection.render_index([summary], generation=2, revision=1,
                                     count=lambda s: len(s) // 4).split("\n")[3:4]

    assert len(line) // 4 <= 60
    assert summary.preview == ("word " * 20).strip()
    assert "+" in line  # tool names beyond the cap are summarized


def test_index_preview_escapes_special_tokens():
    turn = Turn(number=1, messages=(Message(seq=1, alias="AAAAAA", role="user",
                                            blocks=(Block(0, "text", b"a <|im_start|> b"),)),))
    summary = projection.render_turn(turn, added_tokens=TOKENS, count=words).summary
    line = projection.render_index([summary], generation=1, revision=1, count=words)
    assert "<|im_start|>" not in line and "<\\|im_start|>" in line


def test_manifest_lists_every_file_and_payload_archive_sha():
    big = Turn(number=4, sealed=False, revision=3, status="incomplete: cancelled", messages=(
        Message(seq=13, alias="FFFFFF", role="tool",
                blocks=(Block(0, "tool_result", b"\x00z", tool="t", call_id="c"),)),))
    rendered = [projection.render_turn(t, added_tokens=TOKENS, count=words)
                for t in (TURN, big)]

    manifest = json.loads(projection.render_manifest(
        rendered, generation=13, revision=12, branch="main", profile="strata-0.1.48"))

    assert manifest["format"] == "t1"
    assert (manifest["generation"], manifest["archive_cutoff_seq"], manifest["revision"]) == (
        13, 13, 12)
    assert manifest["branch"] == "main" and manifest["profile"] == "strata-0.1.48"
    files = {r.name: r.text.encode() for r in rendered} | {"payloads/FFFFFF.0.txt": b"\x00z"}
    assert manifest["files"] == {name: {"sha256": sha(data), "size": len(data)}
                                 for name, data in files.items()}
    assert manifest["payloads"]["FFFFFF.0"] == {
        "turn_file": "turn-0004.p0003.md", "linked": "payloads/FFFFFF.0.txt",
        "sha256": sha(b"\x00z"), "size": 2}
    assert manifest["payloads"]["AAAAAA.0"]["linked"] is None
    assert set(manifest["payloads"]) == {"AAAAAA.0", "BBBBBB.0", "BBBBBB.1", "CCCCCC.0",
                                         "FFFFFF.0"}


def test_rendering_is_deterministic():
    a = projection.render_turn(TURN, added_tokens=TOKENS, count=words)
    b = projection.render_turn(TURN, added_tokens=TOKENS, count=words)
    assert (a.text, a.files, a.payloads, a.summary) == (b.text, b.files, b.payloads, b.summary)


def test_extract_rejects_an_unclosed_or_interleaved_block():
    with pytest.raises(projection.ProjectionError):
        projection.extract("[[§A.0 · seq 1 · user · text]]\nx\n", added_tokens=())
    with pytest.raises(projection.ProjectionError):
        projection.extract("[[§A.0 · seq 1 · user · text]]\nx\n[[§B.0 · seq 2 · user · text]]\n"
                           "[[/§B.0]]\n", added_tokens=())
