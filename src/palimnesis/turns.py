"""Turn numbers for archived occurrences (A1: excerpt headers, transcript files).

A turn begins at each genuine user instruction; everything after it (assistant
turns, tool results) belongs to that turn until the next one. Occurrences before
the first instruction are turn 0. Harness-synthesized continuation prompts
(OpenCode's "The previous response was interrupted…", docs/probes/opencode_partials.md)
are user-role but not new instructions, so they do not start a turn.
"""

from __future__ import annotations

from typing import Iterable, Mapping

SYNTHETIC_USER_PREFIXES = ("The previous response was interrupted. Continue from where you left off",)


def is_instruction(role: str, text: str | None = None) -> bool:
    return role == "user" and not (text or "").startswith(SYNTHETIC_USER_PREFIXES)


def turn_numbers(seq_roles: Iterable[tuple[int, str]],
                 texts: Mapping[int, str] | None = None) -> dict[int, int]:
    texts = texts or {}
    turn = 0
    numbers: dict[int, int] = {}
    for seq, role in sorted(seq_roles):
        if is_instruction(role, texts.get(seq)):
            turn += 1
        numbers[seq] = turn
    return numbers
