"""One visible OpenAI Chat stream assembled from one or more upstream calls (D52).

Protocol plumbing for hidden recall tools (Phase 3B). The archive relay feeds each
upstream call's SSE events to a ``ChatAssembler``; it returns the bytes the client gets
and the parts the archive stores (``ledger.commit_batch``), and tells the relay whether
the call ended on hidden tool calls only, so a continuation follows.

- **Tool calls are classified at their first delta**, which always carries the name
  (docs/probes/strata.md §12.1). Hidden calls are archived with ``internal: true`` and
  never forwarded. External calls stream as they arrive, renumbered densely across the
  whole visible message.
- **Text and reasoning stream as they arrive**, including text after a hidden call.
- **One message.** Every chunk after the first call carries the first call's ``id``,
  ``created`` and ``model``; later role chunks are dropped. Each call's finish chunk and
  ``[DONE]`` are held; ``terminal`` emits exactly one, with usage reporting the last
  call's prompt and the summed completion tokens (D61).
- **Unchanged when nothing is hidden.** A single call with no hidden tool call is relayed
  byte for byte, its own finish chunk and ``[DONE]`` included.
- Keep-alive comments and error events pass through; the relay judges errors.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from palimnesis.protocols.sse import Event


@dataclass
class HiddenCall:
    index: int  # the upstream call's tool index
    id: str
    name: str
    arguments: str = ""


@dataclass
class Out:
    client: bytes = b""
    parts: list = field(default_factory=list)  # (kind, key, text, meta) for commit_batch


def _sse(obj: dict) -> bytes:
    # ASCII escapes: generated text can carry lone surrogates, which UTF-8 cannot encode.
    return b"data: " + json.dumps(obj).encode("ascii") + b"\n\n"


class ChatAssembler:
    def __init__(self, is_hidden: Callable[[str | None], bool]) -> None:
        self.is_hidden = is_hidden
        self.identity: tuple | None = None  # (id, created, model) of the first call
        self.calls = 0
        self.next_index = 0  # the next client tool-call index
        self.hidden_total = 0
        self.call_usages: list[dict] = []
        self.hidden_calls: list[HiddenCall] = []
        self.external = 0
        self.finish: str | None = None
        self._held: list[Event] = []
        self._map: dict[int, int | None] = {}

    def begin(self) -> None:
        """Start the next upstream call of this visible message."""
        self.calls += 1
        self.hidden_calls, self.external, self.finish = [], 0, None
        self._held, self._map = [], {}

    @property
    def continues(self) -> bool:
        """The call ended on hidden calls only: resolve them and call again."""
        return bool(self.hidden_calls) and self.external == 0

    def feed(self, event: Event) -> Out:
        if event.data is None:
            return Out(event.raw)  # keep-alive comments
        if event.data == "[DONE]":
            self._held.append(event)
            return Out()
        chunk = json.loads(event.data)
        if not isinstance(chunk, dict) or "error" in chunk:
            return Out(event.raw)
        if self.identity is None:
            self.identity = (chunk.get("id"), chunk.get("created"), chunk.get("model"))
        if chunk.get("usage"):
            self.call_usages.append(chunk["usage"])
        changed = self.calls > 1
        parts: list = []
        choices = []
        finishing = False
        for choice in chunk.get("choices") or []:
            delta = dict(choice.get("delta") or {})
            if choice.get("finish_reason"):
                self.finish = choice["finish_reason"]
                finishing = True
            if self.calls > 1 and "role" in delta:
                del delta["role"]
                if delta.get("content") == "":
                    del delta["content"]
            if delta.get("reasoning_content"):
                parts.append(("reasoning", "reasoning", delta["reasoning_content"], {}))
            if delta.get("content"):
                parts.append(("text", "text", delta["content"], {}))
            if "tool_calls" in delta:
                shown = []
                for i, part in enumerate(delta["tool_calls"] or []):
                    up = part.get("index", i)
                    function = part.get("function") or {}
                    if up not in self._map:
                        if self.is_hidden(function.get("name")):
                            self._map[up] = None
                            self.hidden_calls.append(HiddenCall(up, part.get("id"),
                                                                function.get("name")))
                            self.hidden_total += 1
                        else:
                            self._map[up] = self.next_index
                            self.next_index += 1
                            self.external += 1
                    target = self._map[up]
                    args = function.get("arguments") or ""
                    meta = {"id": part.get("id"), "name": function.get("name")}
                    if target is None:
                        meta["internal"] = True
                        next(c for c in self.hidden_calls if c.index == up).arguments += args
                        changed = True
                    else:
                        if target != up:
                            part = {**part, "index": target}
                            changed = True
                        shown.append(part)
                    parts.append(("tool_call", ("tool", up), args, meta))
                if shown:
                    delta["tool_calls"] = shown
                else:
                    del delta["tool_calls"]
            choices.append({**choice, "delta": delta})
        if finishing:
            self._held.append(event)
            return Out(b"", parts)
        if not changed:
            return Out(event.raw, parts)
        if all(not c["delta"] for c in choices) and not chunk.get("usage"):
            return Out(b"", parts)
        out = {**chunk, "choices": choices}
        out["id"], out["created"], out["model"] = self.identity
        return Out(_sse(out), parts)

    def terminal(self, finish_reason: str | None = None) -> bytes:
        """The one finish chunk and ``[DONE]`` that end the visible message."""
        if self.calls == 1 and not self.hidden_total and finish_reason in (None, self.finish):
            return b"".join(e.raw for e in self._held)
        if finish_reason is None and self.finish == "length":
            finish_reason = "length"  # cut off, even inside an external call (contracts §7)
        if finish_reason is None:
            finish_reason = "tool_calls" if self.external else (
                "stop" if self.finish in (None, "tool_calls") else self.finish)
        chunk_id, created, model = self.identity or (None, None, None)
        chunk = {"id": chunk_id, "object": "chat.completion.chunk", "created": created,
                 "model": model, "choices": [{"index": 0, "delta": {},
                                              "finish_reason": finish_reason}]}
        if self.call_usages:
            last = self.call_usages[-1]
            completion = sum(u.get("completion_tokens") or 0 for u in self.call_usages)
            usage = {**last, "completion_tokens": completion,
                     "total_tokens": (last.get("prompt_tokens") or 0) + completion}
            chunk["usage"] = usage
        return _sse(chunk) + b"data: [DONE]\n\n"
