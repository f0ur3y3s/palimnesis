"""Harness strings and the instruction rule (Phase 4B S7, position 4).

Harness-written user messages are declared by each adapter
(``integrations/<harness>/synthetic_user_prefixes.json``) and read by core as one flat
list (``palimnesis.harness_strings``). Core rules hold per protocol shape, not per harness.
"""

from __future__ import annotations

import json
from pathlib import Path

from palimnesis import harness_strings
from palimnesis.archive.turns import is_instruction, turn_numbers
from palimnesis.protocols import messages

INTEGRATIONS = Path(__file__).resolve().parents[1] / "integrations"


def _declared() -> list[str]:
    out = []
    for path in sorted(INTEGRATIONS.glob("*/synthetic_user_prefixes.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for entry in doc["prefixes"]:
            assert entry["text"] and entry["evidence"], path  # every string names its probe
            out.append(entry["text"])
    return out


def test_harness_synthetic_prefixes_from_adapter_data():
    assert list(harness_strings.SYNTHETIC_USER_PREFIXES) == _declared()
    for prefix in harness_strings.SYNTHETIC_USER_PREFIXES:
        assert not is_instruction("user", prefix + " and more")
    assert is_instruction("user", "Please continue from where you left off")  # not a prefix


def _body(msgs) -> bytes:
    return json.dumps({"model": "m", "max_tokens": 64, "messages": msgs}).encode()


def test_user_message_with_tool_result_never_instruction():
    """A Messages user turn holding only tool results becomes ``tool`` messages: no user
    message, so no instruction and no new turn. The harnesses probed never put text
    beside a tool result (269 Claude Code requests, 8 Pi tool-result turns; D90)."""
    req = messages.parse(_body([
        {"role": "user", "content": "Read a.txt"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "c", "name": "read",
                                           "input": {"path": "a.txt"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c", "content": "x"}]}]))
    roles = [m.role for m in req.messages]

    assert roles == ["user", "assistant", "tool"]
    assert turn_numbers(enumerate(roles)) == {0: 1, 1: 1, 2: 1}


def test_a_late_system_entry_starts_no_turn():
    """Claude Code's environment entry after the first user message (HC3, D86)."""
    req = messages.parse(_body([
        {"role": "user", "content": "Fix the bug"},
        {"role": "system", "content": "# Environment\nYou have been invoked in ..."},
        {"role": "assistant", "content": "On it."},
        {"role": "user", "content": "Also add a test"}]))
    roles = [m.role for m in req.messages]

    assert roles == ["user", "system", "assistant", "user"]
    assert turn_numbers(enumerate(roles)) == {0: 1, 1: 1, 2: 1, 3: 2}
