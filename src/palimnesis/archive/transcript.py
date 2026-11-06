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
  present it must be equal. Tool calls must match by id and name exactly;
  arguments match when the strings are equal or both parse to equal JSON
  values (OpenCode resends ``JSON.stringify`` of the parsed arguments).
  Booleans never equal numbers. Any arguments also match ``"{}"``: OpenCode resends a
  call it did not run with empty arguments, whether its arguments never parsed as JSON
  (D68) or the turn was interrupted while the call ran (D73, ``docs/harnesses.md``).
  Known limit: an edit that blanks a call's arguments to ``"{}"`` is not detected; the
  archive keeps the generated arguments.
- A changed system message before the first non-system message is a new
  context version (D10.5), not divergence. OpenCode embeds the date there.

Incomplete generated turns (a stream that failed after output) come back
from OpenCode flattened (``docs/probes/opencode_partials.md``):
- content is ``D[:k]``, where ``D`` is reasoning then text as Palimnesis sent it,
  with no separator. For a composite turn (several upstream calls, D51) it is all the
  reasoning, then all the text, of the first ``k`` streamed characters
  (``docs/probes/opencode_hidden_stream.md``);
- ``reasoning_content`` is empty or absent;
- a partial tool call keeps its streamed id and name, with arguments
  replaced by ``"{}"``.

Such a message matches with acknowledged extent ``k`` (D10.3). The same
applies to a complete turn whose delivery never completed: a crash after
its final commit leaves the client holding only a prefix.

A partial may be *omitted*: it stays archived but is superseded, and the resend
aligns past it (D10.4). OpenCode drops a reply interrupted from the client side
(results R9), anywhere. Pi drops every failed partial, server-failed ones included, on
both protocols and with its retries on or off (``docs/probes/pi.md`` HP4.3, O-4B-5,
D82), from the very next request on: a server-failed partial may be left out when it is
the newest archived turn or was already superseded, never once a request resent it
(D95).
A reply with no text and no tool calls renders nothing upstream, so it may be omitted
anywhere; Pi drops one whose text is empty or whitespace (D97). A turn the length stop
cut short may be omitted too: Pi treats it like a failed one
(``eval/probes/pi_proxy_faults.py``, D94). Any other complete turn the client received in
full may not be omitted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from palimnesis.protocols.chat import Message, content_sha256


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
    cancelled: bool = False  # the client disconnected from this attempt
    truncated: bool = False  # complete, but ended by the length stop (finish_reason "length")
    delivered: bool = True  # the full response was written to the client
    attempt_id: str | None = None  # the attempt that generated it (generated and internal rows)
    # A composite visible turn (D51): the occurrences of one attempt's upstream calls and
    # the hidden results between them, in seq order. ``text``, ``reasoning`` and
    # ``tool_calls`` are what the client saw; ``stream`` is each part's reasoning and
    # text as (kind, text) in the order they were streamed.
    parts: tuple[str, ...] = ()
    stream: tuple[tuple[str, str], ...] = ()

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
        cancelled: bool = False,
        delivered: bool = True,
        attempt_id: str | None = None,
        truncated: bool = False,
    ) -> "Archived":
        return cls(occ_id, "assistant", "generated", view=view, text=text,
                   reasoning=reasoning, tool_calls=tool_calls, complete=complete,
                   cancelled=cancelled, delivered=delivered, attempt_id=attempt_id,
                   truncated=truncated)


@dataclass(frozen=True)
class Extend:
    """Client messages [0, matched) are archived; the rest are new.

    ``partials`` lists (position, acknowledged extent) for incomplete
    generated turns the client resent flattened. ``aligned[i]`` is the
    archived occurrence client message ``i`` matched; ``superseded`` lists
    client-cancelled partials the resend omitted.
    """

    matched: int
    context_changed: tuple[int, ...] = ()
    partials: tuple[tuple[int, int], ...] = ()
    aligned: tuple[str, ...] = field(default=(), compare=False)
    superseded: tuple[str, ...] = field(default=(), compare=False)


@dataclass(frozen=True)
class Prefix:
    """The client resent only archived messages [0, matched): a retry."""

    matched: int
    context_changed: tuple[int, ...] = ()
    partials: tuple[tuple[int, int], ...] = ()
    aligned: tuple[str, ...] = field(default=(), compare=False)
    superseded: tuple[str, ...] = field(default=(), compare=False)


@dataclass(frozen=True)
class Divergence:
    index: int
    reason: str


def _block_text(message: Message, kind: str) -> str | None:
    for block in message.blocks:
        if block.kind == kind:
            return block.text
    return None


def _no_constant(name: str):
    raise ValueError(f"{name} is not JSON")  # JSON.parse rejects NaN and Infinity


def _strict(text: str):
    return json.loads(text, parse_constant=_no_constant)


def _typed(value):
    """``value`` with booleans kept apart from numbers (in Python, True == 1)."""
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, dict):
        return {k: _typed(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_typed(v) for v in value]
    return value


def _same_arguments(sent: str, resent: str) -> bool:
    if sent == resent or resent == "{}":  # a call OpenCode did not run (D68, D73)
        return True
    try:
        parsed = _strict(sent)
    except ValueError:
        return False
    try:
        return _typed(parsed) == _typed(_strict(resent))
    except ValueError:
        return False


def _same_calls(resent: tuple[dict, ...], archived: tuple[dict, ...]) -> bool:
    return len(resent) == len(archived) and all(
        r["id"] == a["id"] and r["name"] == a["name"]
        and _same_arguments(a["arguments"], r["arguments"])
        for r, a in zip(resent, archived)
    )


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
    text = _block_text(message, "text") or ""
    if archived.stream:
        if text != flattened(archived.stream, len(text)):
            return "partial text is not what was streamed, flattened", 0
    elif not (archived.reasoning + archived.text).startswith(text):
        return "partial text is not a prefix of what was generated", 0
    calls = _tool_calls(message)
    expected = tuple(
        {"id": c["id"], "name": c["name"], "arguments": "{}"} for c in archived.tool_calls
    )
    if calls != expected[: len(calls)] or (calls and len(calls) != len(expected)):
        return "partial tool calls differ from what was generated", 0
    return None, len(text)


def flattened(stream: tuple[tuple[str, str], ...], k: int) -> str:
    """What a client flattens the first ``k`` streamed characters into: their reasoning,
    then their text."""
    reasoning, text = [], []
    for kind, piece in stream:
        if k <= 0:
            break
        (reasoning if kind == "reasoning" else text).append(piece[:k])
        k -= len(piece)
    return "".join(reasoning) + "".join(text)


def _matches_generated(message: Message, archived: Archived) -> str | None:
    """None if ``message`` is the client's copy of a complete ``archived`` turn."""
    if message.role != "assistant":
        return "a generated assistant turn was replaced by another role"
    text = _block_text(message, "text") or ""
    # Pi resends whitespace-only text as no text (pi.md HP3, D97).
    if text != archived.text and not (not text and not archived.text.strip()):
        return "assistant text differs from what was generated"
    reasoning = _block_text(message, "reasoning")
    if reasoning is not None and reasoning != archived.reasoning:
        return "assistant reasoning differs from what was generated"
    if not _same_calls(_tool_calls(message), tuple(archived.tool_calls)):
        return "assistant tool calls differ from what was generated"
    return None


def _mismatch(message: Message, archived: Archived) -> str | None:
    if archived.source == "generated":
        return _matches_generated(message, archived)
    if message.role == "assistant" and archived.role != "assistant":
        return "assistant message was not generated by Palimnesis"
    if message.role != archived.role or content_sha256(message) != archived.content_sha256:
        return "message differs from archived history"
    return None


def reconcile(messages: tuple[Message, ...], archived: list[Archived],
              already_superseded: frozenset[str] = frozenset()):
    """``already_superseded`` holds occurrences an earlier request left out (D95)."""
    visible = [a for a in archived if a.view != "internal"]

    def omittable(j: int, past: Archived) -> bool:
        # A failed or length-stopped turn may be left out where Pi leaves it out: from the
        # first request after it (it is the newest archived turn) and every one after
        # (already superseded). Deleting one the client had resent is a divergence
        # (protocol review, D95).
        return j == len(visible) - 1 or past.occ_id in already_superseded

    context_changed: list[int] = []
    partials: list[tuple[int, int]] = []
    aligned: list[str] = []
    superseded: list[str] = []
    leading_system = True
    i = j = 0
    while i < len(messages) and j < len(visible):
        message, past = messages[i], visible[j]
        leading_system = leading_system and message.role == "system" and past.role == "system"
        unfinished = past.source == "generated" and (not past.complete or not past.delivered)
        if unfinished:
            following = visible[j + 1] if j + 1 < len(visible) else None
            if (past.cancelled and not past.complete and following is not None
                    and following.source == "generated" and following.complete
                    and _mismatch(message, following) is None):
                # The client holds the complete answer that followed the cancel;
                # prefer it over reading the message as a flattened partial.
                superseded.append(past.occ_id)
                j += 1
                continue
            if message.role != "assistant":
                # An incomplete answer may be left out of the resend, whether the client
                # cancelled it, saw nothing of it (only hidden calls, D51) or saw it fail
                # (O-4B-5, D82): it is superseded, never merged.
                unseen = not (past.text or past.reasoning or past.tool_calls)
                if not past.complete and (past.cancelled or unseen or omittable(j, past)):
                    superseded.append(past.occ_id)
                    j += 1
                    continue
                return Divergence(i, "the archived partial assistant turn was omitted")
            if not (past.complete and _matches_generated(message, past) is None):
                reason, extent = _matches_partial(message, past)
                if reason is not None:
                    if past.cancelled and not past.complete:
                        # e.g. the answer from a retry that followed the cancel
                        superseded.append(past.occ_id)
                        j += 1
                        continue
                    return Divergence(i, reason)
                partials.append((i, extent))
        elif (past.source == "generated" and past.complete and message.role != "assistant"
              and not past.text.strip() and not past.tool_calls and not past.parts
              and omittable(j, past)):
            # A reply with no text and no tool calls renders nothing upstream (#843, D41);
            # Pi leaves it out of the resend (D97). Superseded: nothing the model saw changes.
            # Narrowed as D95: only where Pi leaves it out, so a turn a later request resent
            # (and its sealed transcript) is never superseded after the fact. A composite
            # turn's hidden calls do render, so it never qualifies (protocol review).
            superseded.append(past.occ_id)
            j += 1
            continue
        elif past.truncated and message.role != "assistant" and omittable(j, past):
            # A reply the length stop cut short, left out of the resend (D94): superseded.
            superseded.append(past.occ_id)
            j += 1
            continue
        else:
            reason = _mismatch(message, past)
            if reason is not None:
                if not leading_system:
                    return Divergence(i, reason)
                context_changed.append(i)
        aligned.append(past.occ_id)
        i += 1
        j += 1
    outcome = Extend if i < len(messages) else Prefix
    return outcome(i, tuple(context_changed), tuple(partials), tuple(aligned), tuple(superseded))
