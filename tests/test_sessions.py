"""Session identity: explicit, validated, and never silently chosen between sources."""

from __future__ import annotations

import pytest

from mnemon.sessions import SessionError, resolve_session


def test_path_identifier_alone_is_the_session():
    assert resolve_session(path_id="proj-a.2026_10", header_id=None) == "proj-a.2026_10"


def test_header_identifier_alone_is_the_session():
    assert resolve_session(path_id=None, header_id="abc") == "abc"


def test_agreeing_path_and_header_resolve_to_that_session():
    assert resolve_session(path_id="abc", header_id="abc") == "abc"


def test_disagreeing_path_and_header_are_rejected_not_chosen_between():
    with pytest.raises(SessionError) as e:
        resolve_session(path_id="abc", header_id="abd")
    assert e.value.code == "session_mismatch"


def test_missing_identity_is_rejected():
    with pytest.raises(SessionError) as e:
        resolve_session(path_id=None, header_id=None)
    assert e.value.code == "session_required"


@pytest.mark.parametrize(
    "bad",
    ["", "a" * 129, "has space", "slash/inside", "dot..", ".hidden", "é", "a\nb"],
)
def test_malformed_identifiers_are_rejected(bad):
    with pytest.raises(SessionError) as e:
        resolve_session(path_id=bad, header_id=None)
    assert e.value.code == "invalid_session_id"


def test_maximum_length_identifier_is_accepted():
    assert resolve_session(path_id="a" * 128, header_id=None) == "a" * 128


@pytest.mark.parametrize("bad", ["abc.", "a%2Fb"])
def test_identifiers_that_alias_on_windows_or_encode_paths_are_rejected(bad):
    with pytest.raises(SessionError) as e:
        resolve_session(path_id=bad, header_id=None)
    assert e.value.code == "invalid_session_id"
