"""Anthropic Messages output from the upstream's Chat Completions output (Phase 4B S3).

``MessagesEmitter`` is the Messages protocol's ``Emitter`` (``palimnesis.protocols``): a
pure state machine, shaped like ``ChatAssembler``, fed the upstream's Chat SSE bytes in
order and returning Messages SSE bytes (plan §2.2).

- ``message_start`` comes first, on the first bytes fed. Then each run of reasoning,
  text or one tool call is a content block: ``content_block_start``, its deltas,
  ``content_block_stop``. A change of kind closes the open block, so text or reasoning
  after a tool call opens a new block. A tool call's block opens once its name is
  known (Strata sends the name first, ``docs/probes/strata.md`` §12.1) and streams its
  arguments as ``input_json_delta`` pieces as they arrive.
- Thinking blocks carry an empty ``signature`` and no ``signature_delta``, as Strata's
  own Messages route does (O-4B-2, D82).
- ``[DONE]`` closes the open block and sends ``message_delta`` (stop reason, usage) and
  ``message_stop``. Stop reasons: ``stop`` → ``end_turn``, ``tool_calls`` → ``tool_use``,
  ``length`` → ``max_tokens``.
- Usage, Anthropic semantics (the D61 analogue): ``input_tokens`` is the prompt minus
  the cached tokens, ``cache_read_input_tokens`` the cached tokens,
  ``cache_creation_input_tokens`` 0, ``output_tokens`` the completion; input plus
  cache read equals the bounded view's prompt.
- Comments pass through; ``keepalive`` is ``event: ping``. Without ``[DONE]`` there is
  never a ``message_stop``: the relay ends such a stream with ``error``, an
  ``event: error`` in Anthropic's envelope. An upstream error chunk becomes that event
  with the upstream message kept verbatim (plan §2.3), and only one error event is
  ever sent.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from palimnesis.protocols.chat import _LONE_SURROGATE, _escape_surrogate
from palimnesis.protocols.sse import SSEParser

STOP_REASONS = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens"}


def _json(value: Any) -> bytes:
    """Compact UTF-8 JSON; a lone surrogate goes back to its escape, as ``chat`` does."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return _LONE_SURROGATE.sub(_escape_surrogate, text).encode("utf-8")


def _event(name: str, data: dict[str, Any]) -> bytes:
    return f"event: {name}\ndata: ".encode() + _json(data) + b"\n\n"


def usage(chat_usage: dict[str, Any] | None) -> dict[str, int]:
    """A Chat ``usage`` object in Anthropic's terms."""
    chat_usage = chat_usage or {}
    prompt = chat_usage.get("prompt_tokens") or 0
    details = chat_usage.get("prompt_tokens_details")
    cached = (details.get("cached_tokens") or 0) if isinstance(details, dict) else 0
    return {"input_tokens": max(prompt - cached, 0), "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": cached,
            "output_tokens": chat_usage.get("completion_tokens") or 0}


def stop_reason(finish: str | None) -> str:
    return STOP_REASONS.get(finish or "stop", "end_turn")


def error_event(code: str, message: str, type_: str = "api_error") -> bytes:
    return _event("error", {"type": "error", "error": {
        "type": type_, "message": f"palimnesis {code}: {message}"}})


class MessagesEmitter:
    def __init__(self, message_id: str | None = None, model: str | None = None) -> None:
        self.message_id = message_id or "msg_" + uuid.uuid4().hex[:24]
        self.model = model
        self._parser = SSEParser()
        self._started = False
        self._index = -1  # the open block's index, or the last one's
        self._open: tuple[str, int | None] | None = None  # (kind, tool index)
        self._tool_args: dict[int, list[str]] = {}  # arguments seen before a name
        self._tool_meta: dict[int, dict[str, str]] = {}
        self._finish: str | None = None
        self._usage: dict[str, Any] | None = None
        self.stopped = False
        self.errored = False

    # -- Emitter -------------------------------------------------------------------------

    def feed(self, data: bytes) -> bytes:
        out: list[bytes] = []
        for event in self._parser.feed(data):
            if self.stopped or self.errored:
                break
            if event.data is None:
                if event.comment:
                    out.append(self._start(None))
                    out.append(event.raw)
                continue
            if event.data == "[DONE]":
                out.append(self._start(None))
                out.append(self._stop())
                continue
            chunk = json.loads(event.data)
            if not isinstance(chunk, dict):
                raise ValueError("stream chunk is not a JSON object")
            if "error" in chunk:
                upstream = chunk["error"] if isinstance(chunk["error"], dict) else {}
                out.append(self._start(chunk.get("model")))
                out.append(_event("error", {"type": "error", "error": {
                    "type": "api_error", "message": str(upstream.get("message") or chunk["error"])}}))
                self.errored = True
                continue
            out.append(self._start(chunk.get("model")))
            out.append(self._chunk(chunk))
        return b"".join(out)

    def body(self, data: bytes) -> bytes:
        message = json.loads(data)
        choice = (message.get("choices") or [{}])[0]
        m = choice.get("message") or {}
        content: list[dict[str, Any]] = []
        if m.get("reasoning_content"):
            content.append({"type": "thinking", "thinking": m["reasoning_content"], "signature": ""})
        if m.get("content"):
            content.append({"type": "text", "text": m["content"]})
        for call in m.get("tool_calls") or []:
            try:
                value = json.loads(call["function"].get("arguments") or "{}")
            except ValueError:
                continue  # a cut-off call: Strata's non-streaming route drops it (§13.1)
            if isinstance(value, dict):
                content.append({"type": "tool_use", "id": call.get("id"),
                                "name": call["function"].get("name"), "input": value})
        out = {"id": self.message_id, "type": "message", "role": "assistant",
               "model": message.get("model", self.model), "content": content,
               "stop_reason": stop_reason(choice.get("finish_reason")), "stop_sequence": None,
               "usage": usage(message.get("usage"))}
        return _json(out)

    def error(self, code: str, message: str) -> bytes:
        if self.errored or self.stopped:
            return b""
        self.errored = True
        return self._start(None) + error_event(code, message)

    def keepalive(self) -> bytes:
        return _event("ping", {"type": "ping"})

    # -- state machine -------------------------------------------------------------------

    def _start(self, model: str | None) -> bytes:
        if self._started:
            return b""
        self._started = True
        self.model = self.model or model
        return _event("message_start", {"type": "message_start", "message": {
            "id": self.message_id, "type": "message", "role": "assistant", "model": self.model,
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0}}})

    def _close(self) -> bytes:
        if self._open is None:
            return b""
        self._open = None
        return _event("content_block_stop", {"type": "content_block_stop", "index": self._index})

    def _open_block(self, kind: str, block: dict[str, Any], tool: int | None = None) -> bytes:
        out = self._close()
        self._index += 1
        self._open = (kind, tool)
        return out + _event("content_block_start", {"type": "content_block_start",
                                                    "index": self._index, "content_block": block})

    def _delta(self, delta: dict[str, Any]) -> bytes:
        return _event("content_block_delta", {"type": "content_block_delta", "index": self._index,
                                              "delta": delta})

    def _chunk(self, chunk: dict[str, Any]) -> bytes:
        out: list[bytes] = []
        if chunk.get("usage"):
            self._usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            if choice.get("index", 0) != 0:
                continue
            delta = choice.get("delta") or {}
            if delta.get("reasoning_content"):
                if self._open != ("thinking", None):
                    out.append(self._open_block("thinking", {"type": "thinking", "thinking": "",
                                                             "signature": ""}))
                out.append(self._delta({"type": "thinking_delta",
                                        "thinking": delta["reasoning_content"]}))
            if delta.get("content"):
                if self._open != ("text", None):
                    out.append(self._open_block("text", {"type": "text", "text": ""}))
                out.append(self._delta({"type": "text_delta", "text": delta["content"]}))
            for call in delta.get("tool_calls") or []:
                out.append(self._tool_delta(call))
            if choice.get("finish_reason"):
                self._finish = choice["finish_reason"]
        return b"".join(out)

    def _tool_delta(self, call: dict[str, Any]) -> bytes:
        i = call["index"]
        meta = self._tool_meta.setdefault(i, {})
        fn = call.get("function") or {}
        if call.get("id"):
            meta["id"] = call["id"]
        if fn.get("name"):
            meta["name"] = meta.get("name", "") + fn["name"]
        args = fn.get("arguments") or ""
        out = b""
        if self._open != ("tool_use", i):
            if "name" not in meta:
                self._tool_args.setdefault(i, []).append(args)
                return b""
            out += self._open_block("tool_use", {"type": "tool_use", "id": meta.get("id"),
                                                 "name": meta["name"], "input": {}}, tool=i)
            for piece in self._tool_args.pop(i, []):
                if piece:
                    out += self._delta({"type": "input_json_delta", "partial_json": piece})
        if args:
            out += self._delta({"type": "input_json_delta", "partial_json": args})
        return out

    def _stop(self) -> bytes:
        self.stopped = True
        return (self._close()
                + _event("message_delta", {"type": "message_delta",
                                           "delta": {"stop_reason": stop_reason(self._finish),
                                                     "stop_sequence": None},
                                           "usage": usage(self._usage)})
                + _event("message_stop", {"type": "message_stop"}))
