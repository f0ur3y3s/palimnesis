"""Incremental server-sent-events parsing and OpenAI chat-stream assembly.

``SSEParser`` splits a byte stream into events per the WHATWG SSE grammar
(lines end in CRLF, LF or CR; a blank line dispatches) and keeps each event's
exact bytes, so a relay can forward what it received unchanged. Every input
byte belongs to exactly one dispatched event or to the pending tail that
``close()`` returns. Text is decoded only at event boundaries, so chunk
splits inside multibyte characters are harmless.

``ChatStream`` folds OpenAI Chat Completions chunk events into the generated
content, reasoning (``reasoning_content`` vendor extension), tool calls,
finish reason and usage of choice 0.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Event:
    raw: bytes
    data: str | None = None
    event: str | None = None
    comment: bool = False


class SSEParser:
    def __init__(self) -> None:
        self._buffer = b""
        self._event_raw = b""
        self._lines: list[bytes] = []

    def feed(self, chunk: bytes) -> list[Event]:
        self._buffer += chunk
        events = []
        while True:
            cr, lf = self._buffer.find(b"\r"), self._buffer.find(b"\n")
            ends = [i for i in (cr, lf) if i >= 0]
            if not ends:
                break
            end = min(ends)
            if end == cr:
                if end + 1 == len(self._buffer):
                    break  # a following LF may still arrive
                width = 2 if self._buffer[end + 1 : end + 2] == b"\n" else 1
            else:
                width = 1
            line = self._buffer[:end]
            self._event_raw += self._buffer[: end + width]
            self._buffer = self._buffer[end + width :]
            if line:
                self._lines.append(line)
            else:
                events.append(self._dispatch())
        return events

    def close(self) -> bytes:
        """Bytes of an event that never saw its terminating blank line."""
        pending = self._event_raw + self._buffer
        self.__init__()
        return pending

    def _dispatch(self) -> Event:
        data: list[str] = []
        name = None
        comment = False
        for raw_line in self._lines:
            line = raw_line.decode("utf-8")
            if line.startswith(":"):
                comment = True
                continue
            key, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if key == "data":
                data.append(value)
            elif key == "event":
                name = value
        event = Event(
            raw=self._event_raw,
            data="\n".join(data) if data else None,
            event=name,
            comment=comment and not data and name is None,
        )
        self._event_raw, self._lines = b"", []
        return event


@dataclass
class ChatStream:
    content: str = ""
    reasoning: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict | None = None
    error: dict | None = None
    done: bool = False

    def apply(self, event: Event) -> None:
        if event.data is None:
            return
        if event.data == "[DONE]":
            self.done = True
            return
        chunk = json.loads(event.data)
        if "error" in chunk:
            self.error = chunk["error"]
            return
        if chunk.get("usage"):
            self.usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            if choice.get("index", 0) != 0:
                raise ValueError("only choice 0 is supported (n > 1 is rejected upstream)")
            delta = choice.get("delta") or {}
            self.content += delta.get("content") or ""
            self.reasoning += delta.get("reasoning_content") or ""
            for part in delta.get("tool_calls") or []:
                self._merge_tool_call(part)
            if choice.get("finish_reason"):
                self.finish_reason = choice["finish_reason"]

    def _merge_tool_call(self, part: dict) -> None:
        index = part["index"]
        while len(self.tool_calls) <= index:
            self.tool_calls.append({"id": None, "name": "", "arguments": ""})
        call = self.tool_calls[index]
        if part.get("id"):
            call["id"] = part["id"]
        function = part.get("function") or {}
        call["name"] += function.get("name") or ""
        call["arguments"] += function.get("arguments") or ""
