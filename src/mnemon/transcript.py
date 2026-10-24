"""Reconcile a client's resent history against the archived visible history.

Clients resend their whole visible transcript on every request. The archive
holds what was actually accepted and generated, including internal
occurrences the client never sees (``view='internal'``), which are skipped
here. Comparison is positional: identical text at two positions is two
occurrences, never a shortcut match.

Matching rules:
- Client-sourced occurrences match by ``content_sha256`` (role and exact
  block bytes).
- Generated assistant occurrences match semantically, because the client
  re-serializes what it received. Text must be equal, with null, empty and
  absent content all equal to ``""``. Reasoning may be omitted, but if
  present it must be equal. Tool calls must match by (id, name, arguments)
  exactly.
- A changed system message before the first non-system message is a new
  context version (D10.5), not divergence. OpenCode embeds the date there.

Incomplete generated turns (a stream that failed after output) come back
from OpenCode flattened (``docs/probes/opencode_partials.md``):
- content is ``D[:k]``, where ``D`` is reasoning then text as Mnemon sent it,
  with no separator;
- ``reasoning_content`` is empty or absent;
- a partial tool call keeps its streamed id and name, with arguments
  replaced by ``"{}"``.

Such a message matches with acknowledged extent ``k`` (D10.3). A resend that
omits an archived partial was never observed and is divergence.
"""

from __future__ import annotations

from dataclasses import dataclass

from .chat import Message, content_sha256


@dataclass(frozen=True)
class Archived:
    occ_id: str
    role: str
    source: str  # client | client_import | generated | internal_tool
    view: str = "both"
    content_sha256: str | None = None
    text: str = ""
    reasoning: str = ""
    tool_calls: tuple[dict, ...] = ()
    complete: bool = True

    @classmethod
    def from_client(cls, occ_id: str, message: Message, source: str = "client") -> "Archived":
        return cls(occ_id, message.role, source, content_sha256=content_sha256(message))

    @classmethod
    def generated(
        cls,
        occ_id: str,
        *,
        text: str,
        reasoning: str,
        tool_calls: tuple[dict, ...],
        complete: bool,
        view: str = "both",
    ) -> "Archived":
        return cls(occ_id, "assistant", "generated", view=view, text=text,
                   reasoning=reasoning, tool_calls=tool_calls, complete=complete)


@dataclass(frozen=True)
class Extend:
    """Client messages [0, matched) are archived; the rest are new.

    ``partials`` lists (position, acknowledged extent) for incomplete
    generated turns the client resent flattened.
    """

    matched: int
    context_changed: tuple[int, ...] = ()
    partials: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class Prefix:
    """The client resent only archived messages [0, matched): a retry."""

    matched: int
    context_changed: tuple[int, ...] = ()
    partials: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class Divergence:
    index: int
    reason: str


def _block_text(message: Message, kind: str) -> str | None:
    for block in message.blocks:
        if block.kind == kind:
            return block.text
    return None


def _tool_calls(message: Message) -> tuple[dict, ...]:
    return tuple(
        {"id": b.tool_call_id, "name": b.name, "arguments": b.text}
        for b in message.blocks
        if b.kind == "tool_call"
    )


def _matches_partial(message: Message, archived: Archived) -> tuple[str | None, int]:
    """(reason or None, acknowledged extent) for an incomplete generated turn."""
    if _block_text(message, "reasoning"):
        return "a resent partial carries reasoning; it was never completed", 0
    sent = archived.reasoning + archived.text
    text = _block_text(message, "text") or ""
    if not sent.startswith(text):
        return "partial text is not a prefix of what was generated", 0
    calls = _tool_calls(message)
    expected = tuple(
        {"id": c["id"], "name": c["name"], "arguments": "{}"} for c in archived.tool_calls
    )
    if calls != expected[: len(calls)] or (calls and len(calls) != len(expected)):
        return "partial tool calls differ from what was generated", 0
    return None, len(text)


def _matches_generated(message: Message, archived: Archived) -> str | None:
    """None if ``message`` is the client's copy of a complete ``archived`` turn."""
    if (_block_text(message, "text") or "") != archived.text:
        return "assistant text differs from what was generated"
    reasoning = _block_text(message, "reasoning")
    if reasoning is not None and reasoning != archived.reasoning:
        return "assistant reasoning differs from what was generated"
    if _tool_calls(message) != tuple(archived.tool_calls):
        return "assistant tool calls differ from what was generated"
    return None


def _mismatch(message: Message, archived: Archived) -> str | None:
    if archived.source == "generated":
        return _matches_generated(message, archived)
    if message.role == "assistant" and archived.role != "assistant":
        return "assistant message was not generated by Mnemon"
    if message.role != archived.role or content_sha256(message) != archived.content_sha256:
        return "message differs from archived history"
    return None


def reconcile(messages: tuple[Message, ...], archived: list[Archived]):
    visible = [a for a in archived if a.view != "internal"]
    context_changed: list[int] = []
    partials: list[tuple[int, int]] = []
    leading_system = True
    for i, (message, past) in enumerate(zip(messages, visible)):
        leading_system = leading_system and message.role == "system" and past.role == "system"
        if past.source == "generated" and not past.complete:
            if message.role != "assistant":
                return Divergence(i, "the archived partial assistant turn was omitted")
            reason, extent = _matches_partial(message, past)
            if reason is None:
                partials.append((i, extent))
                continue
            return Divergence(i, reason)
        reason = _mismatch(message, past)
        if reason is None:
            continue
        if leading_system:
            context_changed.append(i)
            continue
        return Divergence(i, reason)
    matched = min(len(messages), len(visible))
    outcome = Prefix if len(messages) <= len(visible) else Extend
    return outcome(matched, tuple(context_changed), tuple(partials))
