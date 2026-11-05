"""Harness-written user messages that are not user instructions (Phase 4B position 4).

Some harnesses add user-role messages of their own: a prompt to continue after an
interrupted response, a follow-up after a length stop. Those start no turn and host no
excerpt (``archive.turns.is_instruction``). Each harness adapter declares its strings in
``integrations/<harness>/synthetic_user_prefixes.json``, with the probe that recorded
them; this module is their union as one flat list, so core never names a harness.
``tests/test_harness_strings.py`` keeps the two in step.
"""

from __future__ import annotations

SYNTHETIC_USER_PREFIXES: tuple[str, ...] = (
    "The previous response was interrupted. Continue from where you left off",
    "Your last response hit the output token limit (stop reason: length).",
)
