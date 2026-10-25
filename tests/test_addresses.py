"""Stable addresses: issued aliases never change meaning (contracts; plan GL4)."""

from __future__ import annotations

import pytest

from palimnesis.addresses import Ambiguous, Hit, Unknown, issue_alias, resolve
from palimnesis.store import Store


@pytest.fixture
async def store(tmp_path):
    s = Store.open(tmp_path / "archive.db")

    def sessions(c):
        c.execute("INSERT INTO sessions VALUES ('s1', 1.0, 'path')")
        c.execute("INSERT INTO sessions VALUES ('s2', 1.0, 'path')")

    await s.write(sessions)
    yield s
    s.close()


def colliding(prefix: bytes):
    """A hash function that maps every target to digests sharing ``prefix``."""

    def hashfn(target_id: str) -> bytes:
        return prefix + target_id.encode()

    return hashfn


async def test_alias_is_six_crockford_characters_from_the_target_hash(store):
    alias = await store.write(
        lambda c: issue_alias(c, "s1", "occ-1", hashfn=lambda _: bytes(range(32)))
    )
    # Bytes 00 01 02 03 = 00000000 00000001 00000010 00000011; 5-bit groups
    # 00000 00000 00000 10000 00100 00000 → 0 0 0 G 4 0
    assert alias == "000G40"


async def test_issuing_twice_for_one_target_returns_the_same_alias(store):
    first = await store.write(lambda c: issue_alias(c, "s1", "occ-1"))
    second = await store.write(lambda c: issue_alias(c, "s1", "occ-1"))

    assert first == second


async def test_forced_collision_extends_the_second_alias_and_keeps_the_first(store):
    hashfn = colliding(b"\xff" * 8)
    first = await store.write(lambda c: issue_alias(c, "s1", "occ-1", hashfn=hashfn))
    second = await store.write(lambda c: issue_alias(c, "s1", "occ-2", hashfn=hashfn))

    assert len(first) == 6
    assert len(second) > 6 and second.startswith(first)
    assert await store.read(lambda c: resolve(c, "s1", first)) == Hit("occ-1")
    assert await store.read(lambda c: resolve(c, "s1", second)) == Hit("occ-2")


async def test_a_prefix_shared_by_several_aliases_is_ambiguous_not_guessed(store):
    hashfn = colliding(b"\xff" * 8)
    first = await store.write(lambda c: issue_alias(c, "s1", "occ-1", hashfn=hashfn))
    second = await store.write(lambda c: issue_alias(c, "s1", "occ-2", hashfn=hashfn))

    result = await store.read(lambda c: resolve(c, "s1", first[:4]))

    assert result == Ambiguous(sorted([first, second]))


async def test_unknown_alias_suggests_neighbours_and_never_substitutes(store):
    alias = await store.write(lambda c: issue_alias(c, "s1", "occ-1"))
    typo = alias[:5] + ("0" if alias[5] != "0" else "1")

    result = await store.read(lambda c: resolve(c, "s1", typo))

    assert isinstance(result, Unknown)
    assert result.suggestions == [alias]


async def test_aliases_are_scoped_to_their_session(store):
    alias = await store.write(lambda c: issue_alias(c, "s1", "occ-1"))

    assert isinstance(await store.read(lambda c: resolve(c, "s2", alias)), Unknown)


async def test_block_address_resolves_to_target_and_block_index(store):
    alias = await store.write(lambda c: issue_alias(c, "s1", "occ-1"))

    assert await store.read(lambda c: resolve(c, "s1", f"{alias}.3")) == Hit("occ-1", block=3)


@pytest.mark.parametrize("variant", ["lower", "confusable"])
async def test_crockford_input_normalization(store, variant):
    alias = await store.write(
        lambda c: issue_alias(c, "s1", "occ-1", hashfn=lambda _: b"\x00" * 32)
    )
    assert alias == "000000"
    typed = {"lower": "000000".lower(), "confusable": "0Oo0oO"}[variant]

    assert await store.read(lambda c: resolve(c, "s1", typed)) == Hit("occ-1")


@pytest.mark.parametrize("bad", ["", "  ", "AB$DEF", "ABCDEF.", "ABCDEF.x", "ABCDEF.-1"])
async def test_malformed_addresses_are_unknown(store, bad):
    await store.write(lambda c: issue_alias(c, "s1", "occ-1"))

    assert isinstance(await store.read(lambda c: resolve(c, "s1", bad)), Unknown)
