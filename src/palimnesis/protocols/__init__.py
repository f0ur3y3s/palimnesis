"""Client protocols: request parsing and stream handling per wire protocol.

A ``ClientProtocol`` is the edge between a client's wire protocol and the core
(Phase 4B position 2, slice S1). It parses the client's body into the neutral,
Chat-shaped ``chat.ChatRequest`` the archive, view and recall already use, names
the endpoint archived on each request row and fingerprinted (contracts §6), lists
the transport-only fields the fingerprint ignores, and makes the per-response
``Emitter`` that turns the upstream's output into the client's bytes. The upstream
call stays in the profile's dialect, OpenAI Chat Completions, whatever the client
speaks, so the emitter's input is always Chat: SSE events or a JSON body. The
client's query string reaches the upstream only when the client spoke that dialect.

The core picks a protocol by request path only (``for_path``), never by harness or
``User-Agent``. Chat relays the upstream's bytes unchanged, as before the seam existed;
Anthropic Messages (``messages``, ``messages_emit``) maps both ways. A session speaks
one protocol, fixed by its first request (``ledger.accept``).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from palimnesis.protocols import chat, messages
from palimnesis.protocols.messages_emit import MessagesEmitter

#: The upstream dialect's endpoint: every upstream call in archive mode goes here.
UPSTREAM_ENDPOINT = "/v1/chat/completions"


class Emitter(Protocol):
    """Client bytes for one visible response, fed the upstream dialect's output in order."""

    def feed(self, data: bytes) -> bytes:
        """Client bytes for complete upstream SSE events (raw Chat event bytes)."""

    def body(self, data: bytes) -> bytes:
        """The client body for a non-streaming upstream JSON body."""

    def error(self, code: str, message: str) -> bytes:
        """An in-stream error event, sent when a response fails after it started."""

    def keepalive(self) -> bytes:
        """Bytes that keep an idle stream alive without changing its content."""

    def upstream_error(self, status: int, data: bytes) -> bytes | None:
        """The client body for an upstream non-200 response after acceptance, or None to
        relay the upstream's own body and headers (contracts §3)."""

    def error_body(self, data: bytes) -> bytes:
        """An in-stream error event carrying an error response body of this protocol's
        shape, for an error that arrives after admission already started the stream."""


@dataclass(frozen=True)
class ClientProtocol:
    name: str
    endpoint: str  # the client path archived on the request row and fingerprinted
    transport_fields: frozenset[str]  # top-level fields the fingerprint ignores (§6)
    parse: Callable[[bytes], chat.ChatRequest]  # raises chat.Unsupported / chat.InvalidBody
    emitter: Callable[..., Emitter]  # called with model=<the client's requested model>
    # Query strings accepted on the endpoint, or None for any (relayed to the upstream
    # only when the client spoke its dialect).
    queries: frozenset[str] | None = None
    # Whether the hidden recall tools may be offered (Phase 3B; Chat only, position 1).
    hidden_tools: bool = False
    # Keys left out of the fingerprint at any depth (§6): content that renders nothing.
    ignored_keys: frozenset[str] = frozenset()


class ChatEmitter:
    """OpenAI Chat Completions clients get the upstream's own bytes."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model

    def feed(self, data: bytes) -> bytes:
        return data

    def body(self, data: bytes) -> bytes:
        return data

    def error(self, code: str, message: str) -> bytes:
        payload = {"error": {"message": message, "type": "server_error", "code": code}}
        return b"data: " + json.dumps(payload).encode() + b"\n\n"

    def keepalive(self) -> bytes:
        return b": keepalive\n\n"

    def upstream_error(self, status: int, data: bytes) -> bytes | None:
        return None

    def error_body(self, data: bytes) -> bytes:
        try:
            doc = json.loads(data)
        except ValueError:
            doc = None
        if not (isinstance(doc, dict) and "error" in doc):
            text = data.decode("utf-8", "replace").strip() or "upstream error"
            doc = {"error": {"message": text, "type": "server_error", "code": "upstream_failed"}}
        return b"data: " + json.dumps(doc, ensure_ascii=False).encode("utf-8") + b"\n\n"


CHAT = ClientProtocol(
    name="chat",
    endpoint="/v1/chat/completions",
    transport_fields=frozenset({"stream", "stream_options"}),
    parse=chat.parse,
    emitter=ChatEmitter,
    hidden_tools=True,
)


MESSAGES = ClientProtocol(
    name="messages",
    endpoint="/v1/messages",
    transport_fields=frozenset({"stream"}),
    parse=messages.parse,
    emitter=MessagesEmitter,
    # Claude Code and Pi join ``?beta=true`` (HC1, HP1); Strata ignores it (M5).
    queries=frozenset({"", "beta=true"}),
    ignored_keys=frozenset({"cache_control"}),
)
#: Relayed unarchived in archive mode (O-4B-10): a count changes nothing.
COUNT_TOKENS_ENDPOINT = "/v1/messages/count_tokens"

_BY_ENDPOINT = {p.endpoint: p for p in (CHAT, MESSAGES)}


def for_path(api_path: str) -> ClientProtocol | None:
    """The protocol serving ``POST api_path`` in archive mode, or None if none does."""
    return _BY_ENDPOINT.get(api_path)
