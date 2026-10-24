"""Lossless raw-body delta codec (v1_plan "Archival exactness and stable addresses").

Expected values are worked by hand from literal bodies; the live-fixture test
checks exact reconstruction only.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from mnemon.rawdelta import (
    Delta,
    DeltaError,
    choose,
    decode,
    encode,
    snapshot,
    stored_size,
)


def sha(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


# ---- snapshot -------------------------------------------------------------


def test_snapshot_stores_whole_body_and_decodes_without_parent():
    body = b'{"m":[1]}'
    d = snapshot(body)
    assert d == Delta(
        format=0,
        prefix_len=0,
        payload=body,
        suffix_len=0,
        total_len=9,
        sha256=sha(body),
    )
    assert decode(d, None) == body


def test_snapshot_ignores_a_supplied_parent():
    assert decode(snapshot(b"new"), b"unrelated parent") == b"new"


# ---- v1: prefix + suffix ---------------------------------------------------


def test_v1_append_inside_closing_delimiters_stores_prefix_and_suffix():
    parent = b'{"m":[1]}'
    body = b'{"m":[1,2]}'
    d = encode(parent, body, 1)
    # '{"m":[1' is 7 bytes shared; the rest of the body is the suffix.
    assert d == Delta(
        format=1,
        prefix_len=7,
        payload=b",2]}",
        suffix_len=0,
        total_len=11,
        sha256=sha(body),
    )
    assert decode(d, parent) == body


# ---- v2: prefix + middle + suffix_len ---------------------------------------


def test_v2_insert_before_unchanged_tools_stores_only_the_middle():
    parent = b'{"m":[1],"tools":[T]}'  # 21 bytes
    body = b'{"m":[1,2],"tools":[T]}'  # 23 bytes
    d = encode(parent, body, 2)
    # Shared prefix '{"m":[1' (7); shared tail '],"tools":[T]}' (14); middle ',2'.
    assert d == Delta(
        format=2,
        prefix_len=7,
        payload=b",2",
        suffix_len=14,
        total_len=23,
        sha256=sha(body),
    )
    assert decode(d, parent) == body


# ---- edge cases, both variants ------------------------------------------------
# (parent, body, v1 (prefix_len, suffix bytes), v2 (prefix_len, middle, suffix_len))
EDGES = {
    "unchanged": (b"abc", b"abc", (3, b""), (3, b"", 0)),
    "empty_parent": (b"", b"xy", (0, b"xy"), (0, b"xy", 0)),
    "empty_body": (b"xy", b"", (0, b""), (0, b"", 0)),
    "empty_prefix": (b"Xbc", b"Ybc", (0, b"Ybc"), (0, b"Y", 2)),
    "empty_suffix": (b"abX", b"abY", (2, b"Y"), (2, b"Y", 0)),
    "pure_insertion": (b"ac", b"abc", (1, b"bc"), (1, b"b", 1)),
    "pure_deletion": (b"abc", b"ac", (1, b"c"), (1, b"", 1)),
    # A suffix measured on whole bodies would claim 4 shared tail bytes that
    # overlap the 4-byte prefix; measured after the prefix it is 0.
    "growth_no_overlap": (b"aaaa", b"aaaaaa", (4, b"aa"), (4, b"aa", 0)),
    "shrink_no_overlap": (b"aaaaaa", b"aaaa", (4, b""), (4, b"", 0)),
    # 'éx' -> 'èx': é=C3 A9, è=C3 A8; the prefix boundary splits the character.
    "utf8_2byte_prefix_split": (
        "éx".encode(),
        "èx".encode(),
        (1, b"\xa8x"),
        (1, b"\xa8", 1),
    ),
    # '😀 hi' -> '😁 hi': F0 9F 98 80 vs F0 9F 98 81; 3 of 4 bytes shared.
    "emoji_prefix_split": (
        "😀 hi".encode(),
        "😁 hi".encode(),
        (3, b"\x81 hi"),
        (3, b"\x81", 3),
    ),
    # 'é' -> 'ũ': C3 A9 vs C5 A9; the suffix boundary splits the character.
    "utf8_suffix_split": (
        "é".encode(),
        "ũ".encode(),
        (0, b"\xc5\xa9"),
        (0, b"\xc5", 1),
    ),
}


@pytest.mark.parametrize("case", EDGES.values(), ids=EDGES.keys())
def test_delta_edge_cases_v1(case):
    parent, body, (prefix_len, suffix), _ = case
    d = encode(parent, body, 1)
    assert (d.format, d.prefix_len, d.payload, d.suffix_len) == (
        1,
        prefix_len,
        suffix,
        0,
    )
    assert (d.total_len, d.sha256) == (len(body), sha(body))
    assert decode(d, parent) == body


@pytest.mark.parametrize("case", EDGES.values(), ids=EDGES.keys())
def test_delta_edge_cases_v2(case):
    parent, body, _, (prefix_len, middle, suffix_len) = case
    d = encode(parent, body, 2)
    assert (d.format, d.prefix_len, d.payload, d.suffix_len) == (
        2,
        prefix_len,
        middle,
        suffix_len,
    )
    assert (d.total_len, d.sha256) == (len(body), sha(body))
    assert decode(d, parent) == body


# ---- decode never returns wrong bytes ---------------------------------------

V1_PARENT, V1_BODY = b'{"m":[1]}', b'{"m":[1,2]}'
V2_PARENT, V2_BODY = b'{"m":[1],"tools":[T]}', b'{"m":[1,2],"tools":[T]}'


@pytest.mark.parametrize("variant", [1, 2])
def test_missing_parent_raises(variant):
    with pytest.raises(DeltaError):
        decode(encode(V2_PARENT, V2_BODY, variant), None)


def test_truncated_parent_shorter_than_prefix_raises():
    d = encode(V1_PARENT, V1_BODY, 1)  # prefix_len 7
    with pytest.raises(DeltaError):
        decode(d, V1_PARENT[:6])


def test_truncated_parent_where_v2_regions_would_overlap_raises():
    d = encode(V2_PARENT, V2_BODY, 2)  # prefix 7 + suffix 14 = all 21 parent bytes
    with pytest.raises(DeltaError):
        decode(d, V2_PARENT[:-1])


def test_v2_overlapping_regions_rejected_even_when_hash_matches():
    # parent 'abcd': prefix 'abc' (3) and final 2 bytes 'cd' share the 'c'.
    forged = b"abccd"
    d = Delta(
        format=2,
        prefix_len=3,
        payload=b"",
        suffix_len=2,
        total_len=5,
        sha256=sha(forged),
    )
    with pytest.raises(DeltaError):
        decode(d, b"abcd")


@pytest.mark.parametrize("variant", [0, 1, 2])
def test_corrupt_payload_raises(variant):
    d = snapshot(V2_BODY) if variant == 0 else encode(V2_PARENT, V2_BODY, variant)
    flipped = bytes([d.payload[0] ^ 0x01]) + d.payload[1:]
    with pytest.raises(DeltaError):
        decode(replace(d, payload=flipped), V2_PARENT)


@pytest.mark.parametrize("variant", [0, 1, 2])
def test_wrong_sha_raises(variant):
    d = snapshot(V2_BODY) if variant == 0 else encode(V2_PARENT, V2_BODY, variant)
    with pytest.raises(DeltaError):
        decode(replace(d, sha256=sha(b"something else")), V2_PARENT)


@pytest.mark.parametrize("variant", [1, 2])
def test_wrong_parent_of_same_length_raises(variant):
    d = encode(V2_PARENT, V2_BODY, variant)
    other = V2_PARENT.replace(b"m", b"n")  # inside the reused prefix
    with pytest.raises(DeltaError):
        decode(d, other)


@pytest.mark.parametrize("variant", [0, 1, 2])
def test_total_len_mismatch_raises(variant):
    d = snapshot(V2_BODY) if variant == 0 else encode(V2_PARENT, V2_BODY, variant)
    with pytest.raises(DeltaError):
        decode(replace(d, total_len=d.total_len + 1), V2_PARENT)


@pytest.mark.parametrize(
    "bad",
    [
        {"format": 3},
        {"format": 1, "suffix_len": 1},  # v1 has no suffix field
        {"format": 0, "prefix_len": 1},  # snapshot reuses nothing
        {"format": 2, "prefix_len": -1},
        {"format": 2, "suffix_len": -1},
    ],
    ids=[
        "unknown_format",
        "v1_with_suffix_len",
        "snapshot_with_prefix",
        "neg_prefix",
        "neg_suffix",
    ],
)
def test_malformed_record_raises(bad):
    d = encode(V2_PARENT, V2_BODY, 2)
    with pytest.raises(DeltaError):
        decode(replace(d, **bad), V2_PARENT)


def test_encode_rejects_unknown_variant():
    with pytest.raises(ValueError):
        encode(b"a", b"b", 3)


# ---- stored size ---------------------------------------------------------------


def test_stored_size_is_payload_plus_fixed_57_byte_header_for_every_format():
    # header: format 1 + prefix_len 8 + suffix_len 8 + total_len 8 + sha256 32
    assert stored_size(snapshot(b"abc")) == 60
    assert stored_size(encode(b"abX", b"abY", 1)) == 58  # payload 'Y'
    assert stored_size(encode(b"Xbc", b"Ybc", 2)) == 58  # middle 'Y'


# ---- snapshot / delta policy ----------------------------------------------------


@pytest.mark.parametrize("variant, payload", [(1, b',2],"tools":[T]}'), (2, b",2")])
def test_policy_uses_delta_when_parent_usable_and_delta_smaller(variant, payload):
    d = choose(V2_PARENT, V2_BODY, depth=0, schema_changed=False, variant=variant)
    assert (d.format, d.prefix_len, d.payload) == (variant, 7, payload)


def test_policy_snapshots_without_parent():
    d = choose(None, V2_BODY, depth=0, schema_changed=False, variant=2)
    assert (d.format, d.payload) == (0, V2_BODY)


@pytest.mark.parametrize("variant", [1, 2])
def test_snapshot_on_tool_change(variant):
    d = choose(V2_PARENT, V2_BODY, depth=0, schema_changed=True, variant=variant)
    assert (d.format, d.payload) == (0, V2_BODY)


@pytest.mark.parametrize("variant", [1, 2])
def test_snapshot_when_delta_not_smaller(variant):
    # Nothing shared: the delta payload 'xyz' equals the snapshot payload.
    d = choose(b"abc", b"xyz", depth=0, schema_changed=False, variant=variant)
    assert (d.format, d.payload) == (0, b"xyz")


@pytest.mark.parametrize("variant", [1, 2])
def test_snapshot_every_32(variant):
    # depth = deltas between the parent and its nearest snapshot (snapshot
    # parent: 0). A chain holds at most max_depth deltas after its snapshot.
    at_limit = choose(
        V2_PARENT, V2_BODY, depth=31, schema_changed=False, variant=variant
    )
    over = choose(V2_PARENT, V2_BODY, depth=32, schema_changed=False, variant=variant)
    assert at_limit.format == variant
    assert (over.format, over.payload) == (0, V2_BODY)


def test_depth_boundary_follows_max_depth():
    one = choose(
        V2_PARENT, V2_BODY, depth=0, max_depth=1, schema_changed=False, variant=1
    )
    two = choose(
        V2_PARENT, V2_BODY, depth=1, max_depth=1, schema_changed=False, variant=1
    )
    assert (one.format, two.format) == (1, 0)


# ---- live OpenCode bodies -------------------------------------------------------

LIVE = (
    Path(__file__).resolve().parent.parent
    / "eval/fixtures/opencode-2.1.4/live/exchanges"
)


def live_bodies() -> list[bytes]:
    folders = sorted(LIVE.glob("*/*/request.body"), key=lambda f: f.parent.name)
    return [f.read_bytes() for f in folders]


@pytest.mark.parametrize("variant", [1, 2])
def test_live_bodies_round_trip_as_a_chain(variant):
    bodies = live_bodies()
    assert len(bodies) == 10
    parent = None
    for depth, body in enumerate(bodies):
        if parent is not None:
            assert decode(encode(parent, body, variant), parent) == body
        chosen = choose(
            parent, body, depth=depth, schema_changed=False, variant=variant
        )
        assert decode(chosen, parent) == body
        parent = body
