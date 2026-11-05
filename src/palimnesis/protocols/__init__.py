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
``User-Agent``. Chat is the only protocol registered here; it relays the upstream's
bytes unchanged, as before the seam existed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from palimnesis.protocols import chat

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


@dataclass(frozen=True)
class ClientProtocol:
    name: str
    endpoint: str  # the client path archived on the request row and fingerprinted
    transport_fields: frozenset[str]  # top-level fields the fingerprint ignores (§6)
    parse: Callable[[bytes], chat.ChatRequest]  # raises chat.Unsupported / chat.InvalidBody
    emitter: Callable[[], Emitter]


class ChatEmitter:
    """OpenAI Chat Completions clients get the upstream's own bytes."""

    def feed(self, data: bytes) -> bytes:
        return data

    def body(self, data: bytes) -> bytes:
        return data

    def error(self, code: str, message: str) -> bytes:
        payload = {"error": {"message": message, "type": "server_error", "code": code}}
        return b"data: " + json.dumps(payload).encode() + b"\n\n"

    def keepalive(self) -> bytes:
        return b": keepalive\n\n"


CHAT = ClientProtocol(
    name="chat",
    endpoint="/v1/chat/completions",
    transport_fields=frozenset({"stream", "stream_options"}),
    parse=chat.parse,
    emitter=ChatEmitter,
)

_BY_ENDPOINT = {p.endpoint: p for p in (CHAT,)}


def for_path(api_path: str) -> ClientProtocol | None:
    """The protocol serving ``POST api_path`` in archive mode, or None if none does."""
    return _BY_ENDPOINT.get(api_path)
