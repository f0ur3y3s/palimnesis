"""Harness-written strings core must recognize, as adapter data (Phase 4B position 4, D90).

Some harnesses add user-role messages of their own: a prompt to continue after an
interrupted response, a follow-up after a length stop. Those start no turn and host no
excerpt (``archive.turns.is_instruction``). Each harness adapter declares its strings in
``integrations/<harness>/synthetic_user_prefixes.json``, with the probe that recorded
them; this module is their union as one flat list, so core never names a harness.
``tests/test_harness_strings.py`` keeps the two in step.

``ARGUMENT_PREVIEWS`` are the shapes in which a client resends a tool call whose
arguments never parsed as JSON (``integrations/<harness>/argument_previews.json``, D104).
"""

from __future__ import annotations

from typing import NamedTuple


class ArgumentPreview(NamedTuple):
    """Resent arguments ``{error_key: <parser message>, raw_key: <preview>}``. The
    preview is the raw text whole when it has at most ``keep_utf16_units`` UTF-16 code
    units, else that many units followed by ``marker`` with ``{omitted}`` the number of
    units left out."""

    error_key: str
    raw_key: str
    keep_utf16_units: int
    marker: str

SYNTHETIC_USER_PREFIXES: tuple[str, ...] = (
    "The previous response was interrupted. Continue from where you left off",
    "Your last response hit the output token limit (stop reason: length).",
)


ARGUMENT_PREVIEWS: tuple[ArgumentPreview, ...] = (
    ArgumentPreview("__parseError", "__rawJson", 512, "… [truncated {omitted} chars]"),
)
