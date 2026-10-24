"""Request fingerprint v1 and retry hints (contracts §5, §6; D10.17)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mnemon.fingerprint import FINGERPRINT_VERSION, fingerprint_v1, parse_retry_hint

L0 = next(
    (Path(__file__).resolve().parents[1] / "eval/fixtures/opencode-2.1.4/live/exchanges").glob(
        "*/*/request.body"
    )
)
BASE = {"model": "m", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.5}


def fp(obj, endpoint="/v1/chat/completions", session="s1", branch="main"):
    return fingerprint_v1(endpoint, session, branch, obj)


def test_version_is_one():
    assert FINGERPRINT_VERSION == 1


def test_key_order_does_not_matter():
    reordered = {"temperature": 0.5, "messages": [{"content": "hi", "role": "user"}], "model": "m"}

    assert fp(reordered) == fp(BASE)


def test_integer_and_float_spellings_differ():
    assert fp({**BASE, "temperature": 1}) != fp({**BASE, "temperature": 1.0})


def test_strings_are_not_unicode_normalized():
    composed = {**BASE, "messages": [{"role": "user", "content": "café"}]}
    decomposed = {**BASE, "messages": [{"role": "user", "content": "café"}]}

    assert fp(composed) != fp(decomposed)


def test_transport_only_fields_are_excluded():
    assert fp({**BASE, "stream": True, "stream_options": {"include_usage": True}}) == fp(
        {**BASE, "stream": False}
    )


@pytest.mark.parametrize(
    "change",
    [
        {"temperature": 0.6},
        {"model": "other"},
        {"tools": []},
        {"messages": [{"role": "user", "content": "hi "}]},
        {"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "x"}]},
        {"max_completion_tokens": 10},
    ],
)
def test_semantic_fields_and_the_whole_history_change_the_fingerprint(change):
    assert fp({**BASE, **change}) != fp(BASE)


@pytest.mark.parametrize("scope", [{"session": "s2"}, {"branch": "b2"}, {"endpoint": "/v1/messages"}])
def test_endpoint_session_and_branch_are_part_of_the_fingerprint(scope):
    assert fp(BASE, **scope) != fp(BASE)


def test_fingerprint_v1_of_the_first_live_request_is_pinned():
    # Regression pin: any change to canonicalization must bump FINGERPRINT_VERSION.
    obj = json.loads(L0.read_bytes())

    assert fp(obj, session="ses_e906e5405ffeVfiX2TzyrOhErb") == PINNED_L0


PINNED_L0 = "7f940814879ac3feccb3efcad8e30d9de89a1a29c62b9ec68f585a8a499abc00"


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"x-stainless-retry-count": "0"}, 0),
        ({"x-stainless-retry-count": "3"}, 3),
        ({"X-Stainless-Retry-Count": "100"}, 100),
        ({"x-stainless-retry-count": "101"}, None),
        ({"x-stainless-retry-count": "-1"}, None),
        ({"x-stainless-retry-count": "2.5"}, None),
        ({"x-stainless-retry-count": "1e2"}, None),
        ({"x-stainless-retry-count": " 4"}, None),
        ({"x-stainless-retry-count": "٣"}, None),  # non-ASCII digit
        ({"x-stainless-retry-count": "9" * 400}, None),
        ({"retry-count": "2"}, None),
        ({}, None),
    ],
)
def test_retry_hint_accepts_only_small_ascii_integers(headers, expected):
    assert parse_retry_hint(headers) == expected
