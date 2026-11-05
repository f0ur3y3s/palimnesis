"""Scriptable fault server for Pi probes: Chat Completions SSE and Anthropic Messages SSE.

A deterministic stand-in for an upstream (Phase 4B S0, probes HP1-HP7). Each POST to
``*/chat/completions`` or ``*/messages`` is one attempt, and the selected scenario says
what attempt N receives (the last entry repeats). The same protocol-neutral steps are
rendered as Chat chunks or as Anthropic events, chosen by the request path. Every
request (arrival time, target, headers, full body) and every response milestone is
appended to a JSONL log so attempt counts, gaps and body differences can be read back.

It is a raw asyncio HTTP/1.1 server, like ``opencode_fault_server.py``, because the
probes need byte-level control: delaying the status line, ending a chunked body cleanly
versus resetting the socket, and writing SSE comments or ``event: ping``.

Usage:
    uv run python eval/probes/pi_fault_server.py --scenario ok --port 18600 --log run.jsonl
    uv run python eval/probes/pi_fault_server.py --list

Never point this at, or proxy it to, a real model server; it fabricates every response.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import socket
import struct
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Response steps


@dataclass
class Status:
    """Non-streaming error response with a JSON body (OpenAI or Anthropic envelope)."""

    status: int
    headers: dict[str, str] = field(default_factory=dict)
    message: str = "fault server error"
    header_delay: float = 0.0


@dataclass
class Stream:
    """SSE response. ``steps`` are protocol-neutral tuples:

    ("start",)                    Chat: role chunk. Messages: message_start.
    ("text", s) ("reasoning", s)  visible text / reasoning (Messages: thinking block)
    ("sig", s)                    Messages only: signature_delta for the open thinking block
    ("tool_call", id, name, [arg_fragment, ...])
    ("finish", reason)            stop | tool_calls | length | error
                                  (Messages: closes blocks, message_delta with stop_reason)
    ("usage", prompt, completion) Chat: usage chunk. Messages: folded into message_delta.
    ("done",)                     Chat: data: [DONE]. Messages: message_stop.
    ("sleep", s) ("comment", text) ("comments", interval_s, total_s)
    ("pings", interval_s, total_s)  Messages-style ``event: ping`` (also sent to Chat)
    ("error", message)            Chat: data: {"error":...}. Messages: event: error.

    ``end``: "eof" ends the chunked body; "abort" resets the socket; "hang" never ends.
    Put a ("sleep", s) before "abort": on Windows an RST can discard unread data.
    """

    steps: list[tuple]
    end: str = "eof"
    headers: dict[str, str] = field(default_factory=dict)
    header_delay: float = 0.0


def answer(text: str = "OK from fault server", reasoning: str | None = None,
           prompt_tokens: int = 10) -> Stream:
    steps: list[tuple] = [("start",)]
    if reasoning:
        steps.append(("reasoning", reasoning))
    steps += [("text", text), ("finish", "stop"), ("usage", prompt_tokens, 5), ("done",)]
    return Stream(steps)


def tool_turn(call_id: str, name: str, args: dict, reasoning: str | None = None,
              text: str | None = None) -> Stream:
    raw = json.dumps(args)
    mid = len(raw) // 2
    steps: list[tuple] = [("start",)]
    if reasoning:
        steps.append(("reasoning", reasoning))
    if text:
        steps.append(("text", text))
    steps += [
        ("tool_call", call_id, name, [raw[:mid], raw[mid:]]),
        ("finish", "tool_calls"),
        ("usage", 10, 5),
        ("done",),
    ]
    return Stream(steps)


def ok() -> Stream:
    return answer()


NO_RETRY = {"x-should-retry": "false"}
PARTIAL = [("start",), ("reasoning", "Thinking ATTEMPT"), ("text", "Partial answer ATTEMPT")]

SCENARIOS: dict[str, tuple[str, list]] = {
    "ok": ("Always a well-formed answer.", [ok()]),
    "ok_reasoning": (
        "Always reasoning + text.",
        [answer("Answer ATTEMPT", reasoning="Reasoning for ATTEMPT")],
    ),
    "big_usage_then_ok": (
        "An answer reporting 30000 prompt tokens, then normal answers (compaction threshold).",
        [answer("Big ATTEMPT", prompt_tokens=30000), ok()],
    ),
    "tool_loop": (
        "read notes.txt (reasoning + call), final answer, then plain answers.",
        [
            tool_turn("call_pi_1", "read", {"path": "notes.txt"},
                      reasoning="I should read notes ATTEMPT", text="Reading ATTEMPT."),
            answer("The note says hello ATTEMPT", reasoning="Got the note ATTEMPT"),
            answer("Second turn answer ATTEMPT", reasoning="Second turn reasoning ATTEMPT"),
        ],
    ),
    "gate_read_grep_bash": (
        "Tool calls read, grep, bash on TARGET paths (substituted by the driver), then OK.",
        [],  # filled by the driver via --plan-json
    ),
    # HTTP status classes
    "s500_then_ok": ("HTTP 500, then OK.", [Status(500), ok()]),
    "s500": ("HTTP 500 every attempt.", [Status(500)]),
    "s409_then_ok": ("HTTP 409, then OK.", [Status(409, {}, "request already in progress"), ok()]),
    "s429_then_ok": ("HTTP 429 (no retry-after), then OK.", [Status(429, {}, "rate limited"), ok()]),
    "s429_ra7_then_ok": (
        "HTTP 429 + retry-after: 7, then OK.",
        [Status(429, {"retry-after": "7"}, "rate limited"), ok()],
    ),
    "s503_noretry_then_ok": (
        "HTTP 503 + x-should-retry: false, then OK.",
        [Status(503, NO_RETRY, "service unavailable"), ok()],
    ),
    "s409_shouldretry_then_ok": (
        "HTTP 409 + x-should-retry: true, then OK.",
        [Status(409, {"x-should-retry": "true"}, "request already in progress"), ok()],
    ),
    "s400_then_ok": ("HTTP 400, then OK.", [Status(400, {}, "bad request from fault server"), ok()]),
    "s400_overflow": (
        "HTTP 400 with llama.cpp's context-overflow wording, every attempt.",
        [Status(400, {}, "the request exceeds the available context size, try increasing it")],
    ),
    "s409_divergence_then_ok": (
        "HTTP 409 history_divergence (Palimnesis wording), then OK.",
        [Status(409, NO_RETRY, "palimnesis: history_divergence: resend does not match archive"), ok()],
    ),
    # Partials
    "partial_eof_then_ok": ("Reasoning + text, clean EOF; then OK.", [Stream(PARTIAL, "eof"), ok()]),
    "partial_abort_then_ok": (
        "Reasoning + text, 1 s, reset; then OK.",
        [Stream(PARTIAL + [("sleep", 1.0)], "abort"), ok()],
    ),
    "partial_error_then_ok": (
        "Reasoning + text + in-stream error (Palimnesis wording), EOF; then OK.",
        [Stream(PARTIAL + [("error", "palimnesis: upstream stream failed")], "eof"), ok()],
    ),
    "partial_error_noretry_then_ok": (
        "Reasoning + text + in-stream error, x-should-retry: false; then OK.",
        [Stream(PARTIAL + [("error", "palimnesis: upstream stream failed")], "eof", NO_RETRY), ok()],
    ),
    "partial_error_plain_then_ok": (
        "Reasoning + text + in-stream error with a non-retryable wording; then OK.",
        [Stream(PARTIAL + [("error", "palimnesis: upstream_stream_failed")], "eof"), ok()],
    ),
    "partial_tool_error_then_ok": (
        "Text + half a tool call + in-stream error; then OK.",
        [
            Stream(
                [("start",), ("text", "Let me look ATTEMPT"),
                 ("tool_call", "call_part_1", "read", ['{"path', '": "no']),
                 ("error", "palimnesis: upstream stream failed")],
                "eof",
            ),
            ok(),
        ],
    ),
    "role_only_eof_then_ok": ("Start only, clean EOF; then OK.", [Stream([("start",)], "eof"), ok()]),
    "partial_length": (
        "Text + finish length every attempt.",
        [Stream([("start",), ("text", "Truncated ATTEMPT"), ("finish", "length"), ("usage", 10, 5),
                 ("done",)])],
    ),
    # Timeouts (run with a short httpIdleTimeoutMs)
    "header_delay8_then_ok": (
        "Status line delayed 8 s, then OK.",
        [Stream(ok().steps, header_delay=8.0), ok()],
    ),
    "idle_after_start_then_ok": ("Start, then silence; then OK.", [Stream([("start",)], "hang"), ok()]),
    "idle_after_text_then_ok": (
        "Start + text, then silence; then OK.",
        [Stream([("start",), ("text", "Partial answer ATTEMPT")], "hang"), ok()],
    ),
    "comments_12s": (
        "': keep-alive' every 2 s for 12 s before the start event, then a full answer.",
        [Stream([("comments", 2.0, 12.0)] + ok().steps), ok()],
    ),
    "comments_after_start_12s": (
        "Start, ': keep-alive' every 2 s for 12 s, then the rest.",
        [Stream([("start",), ("comments", 2.0, 12.0), ("text", "OK after keepalive"),
                 ("finish", "stop"), ("usage", 10, 5), ("done",)]), ok()],
    ),
    "pings_after_start_12s": (
        "Start, 'event: ping' every 2 s for 12 s, then the rest.",
        [Stream([("start",), ("pings", 2.0, 12.0), ("text", "OK after pings"),
                 ("finish", "stop"), ("usage", 10, 5), ("done",)]), ok()],
    ),
    "pings_before_start_12s": (
        "'event: ping' every 2 s for 12 s before message_start, then the full answer.",
        [Stream([("pings", 2.0, 12.0)] + ok().steps), ok()],
    ),
    "finish_no_done": (
        "Text + finish + usage, no [DONE] / message_stop.",
        [Stream([("start",), ("text", "Complete ATTEMPT"), ("finish", "stop"), ("usage", 10, 5)])],
    ),
}


def plan_from_json(spec: list[dict]) -> list:
    """Build a plan from JSON: [{"status":500,...} | {"stream":[[...],...],"end":..}]."""
    out = []
    for item in spec:
        if "status" in item:
            out.append(Status(item["status"], item.get("headers", {}),
                              item.get("message", "fault server error"),
                              item.get("header_delay", 0.0)))
        else:
            out.append(Stream([tuple(s) for s in item["stream"]], item.get("end", "eof"),
                              item.get("headers", {}), item.get("header_delay", 0.0)))
    return out


# ---------------------------------------------------------------------------
# Server


class Log:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._f = path.open("a", encoding="utf-8")
        self.t0 = time.monotonic()
        self._lock = threading.Lock()

    def write(self, record: dict) -> None:
        record = {"t": round(time.monotonic() - self.t0, 3), "wall": time.time(), **record}
        with self._lock:
            self._f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._f.flush()


def _reason(status: int) -> str:
    return {200: "OK", 400: "Bad Request", 404: "Not Found", 409: "Conflict",
            429: "Too Many Requests", 500: "Internal Server Error", 502: "Bad Gateway",
            503: "Service Unavailable"}.get(status, "Status")


def _split(text: str) -> list[str]:
    parts, cur = [], ""
    for ch in text:
        cur += ch
        if ch == " ":
            parts.append(cur)
            cur = ""
    if cur:
        parts.append(cur)
    return parts


def _describe(step) -> str | None:
    if step is None:
        return None
    if isinstance(step, Status):
        return f"status {step.status} {step.headers or ''}".strip()
    return f"stream[{','.join(s[0] for s in step.steps)}] end={step.end} {step.headers or ''}".strip()


class FaultServer:
    def __init__(self, plan: list, name: str, log: Log) -> None:
        self.name = name
        self.plan = plan
        self.log = log
        self.attempts = 0
        self.seq = 0
        self.conns = 0

    def step_for(self, attempt: int):
        return self.plan[min(attempt, len(self.plan)) - 1]

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.conns += 1
        conn = self.conns
        self.log.write({"event": "connect", "conn": conn})
        try:
            while True:
                req = await self._read_request(reader)
                if req is None:
                    break
                if not await self._respond(conn, req, reader, writer):
                    break
        except (ConnectionError, asyncio.IncompleteReadError) as e:
            self.log.write({"event": "conn_error", "conn": conn, "error": repr(e)})
        finally:
            self.log.write({"event": "disconnect", "conn": conn})
            with contextlib.suppress(OSError):
                writer.close()

    async def _read_request(self, reader):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, ConnectionError):
            return None
        lines = head.decode("latin-1").split("\r\n")
        method, target, _version = lines[0].split(" ", 2)
        headers = []
        for line in lines[1:]:
            if line:
                k, _, v = line.partition(":")
                headers.append([k.strip(), v.strip()])
        h = {k.lower(): v for k, v in headers}
        if "content-length" in h:
            body = await reader.readexactly(int(h["content-length"]))
        elif h.get("transfer-encoding", "").lower() == "chunked":
            body = b""
            while True:
                size = int((await reader.readuntil(b"\r\n")).strip().split(b";")[0], 16)
                if size == 0:
                    await reader.readuntil(b"\r\n")
                    break
                body += await reader.readexactly(size)
                await reader.readexactly(2)
        else:
            body = b""
        return {"method": method, "target": target, "headers": headers, "body": body}

    async def _respond(self, conn, req, reader, writer) -> bool:
        self.seq += 1
        path = req["target"].split("?")[0]
        proto = None
        if req["method"] == "POST" and path.endswith("/chat/completions"):
            proto = "chat"
        elif req["method"] == "POST" and path.endswith("/messages"):
            proto = "messages"
        attempt = step = None
        if proto:
            self.attempts += 1
            attempt = self.attempts
            step = self.step_for(attempt)
        try:
            body_json = json.loads(req["body"]) if req["body"] else None
        except ValueError:
            body_json = None
        self.log.write({
            "event": "request", "seq": self.seq, "conn": conn, "attempt": attempt,
            "method": req["method"], "target": req["target"], "protocol": proto,
            "headers": req["headers"],
            "body": body_json if body_json is not None else req["body"].decode("utf-8", "replace"),
            "scenario": self.name, "step": _describe(step),
        })
        if not proto:
            await self._write_status(writer, 404, {}, "not found", "chat")
            return True
        model = (body_json or {}).get("model", "fault")
        if isinstance(step, Status):
            if step.header_delay:
                await asyncio.sleep(step.header_delay)
            await self._write_status(writer, step.status, step.headers, step.message, proto)
            self.log.write({"event": "response", "seq": self.seq, "attempt": attempt,
                            "status": step.status})
            return True
        return await self._write_stream(reader, writer, step, attempt, model, proto)

    async def _write_status(self, writer, status, headers, message, proto) -> None:
        if proto == "messages":
            err_type = {400: "invalid_request_error", 409: "invalid_request_error",
                        429: "rate_limit_error", 503: "overloaded_error"}.get(status, "api_error")
            obj = {"type": "error", "error": {"type": err_type, "message": message}}
        else:
            obj = {"error": {"message": message, "type": "fault_server", "code": status}}
        body = json.dumps(obj).encode()
        head = [f"HTTP/1.1 {status} {_reason(status)}", "content-type: application/json",
                f"content-length: {len(body)}"]
        head += [f"{k}: {v}" for k, v in headers.items()]
        writer.write(("\r\n".join(head) + "\r\n\r\n").encode() + body)
        await writer.drain()

    async def _write_stream(self, reader, writer, step: Stream, attempt, model, proto) -> bool:
        seq = self.seq
        if step.header_delay:
            self.log.write({"event": "header_delay", "seq": seq, "attempt": attempt,
                            "seconds": step.header_delay})
            try:
                data = await asyncio.wait_for(reader.read(1), timeout=step.header_delay)
            except TimeoutError:
                data = None
            except (ConnectionError, OSError):
                data = b""
            if data == b"":
                self.log.write({"event": "client_gone", "seq": seq, "attempt": attempt,
                                "during": "header_delay"})
                return False
        head = ["HTTP/1.1 200 OK", "content-type: text/event-stream", "cache-control: no-cache",
                "transfer-encoding: chunked"]
        head += [f"{k}: {v}" for k, v in step.headers.items()]
        r = _Renderer(proto, attempt, model)
        try:
            writer.write(("\r\n".join(head) + "\r\n\r\n").encode())
            await writer.drain()
            self.log.write({"event": "headers_sent", "seq": seq, "attempt": attempt})

            async def send(data: bytes) -> None:
                if data:
                    writer.write(b"%x\r\n" % len(data) + data + b"\r\n")
                    await writer.drain()

            for s in step.steps:
                kind = s[0]
                if kind == "sleep":
                    await asyncio.sleep(s[1])
                elif kind == "comment":
                    await send(f": {s[1]}\n\n".encode())
                elif kind in ("comments", "pings"):
                    interval, total = s[1], s[2]
                    t_end = time.monotonic() + total
                    while time.monotonic() < t_end:
                        await asyncio.sleep(interval)
                        if kind == "comments":
                            await send(b": keep-alive\n\n")
                        else:
                            await send(b'event: ping\ndata: {"type": "ping"}\n\n')
                        self.log.write({"event": kind[:-1], "seq": seq, "attempt": attempt})
                else:
                    for chunk in r.render(s):
                        await send(chunk)
            self.log.write({"event": "steps_done", "seq": seq, "attempt": attempt, "end": step.end})
            if step.end == "eof":
                writer.write(b"0\r\n\r\n")
                await writer.drain()
                return True
            if step.end == "abort":
                sock = writer.get_extra_info("socket")
                if sock is not None:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                writer.transport.abort()
                return False
            # hang: wait until the client goes away
            while True:
                data = await reader.read(1024)
                if not data:
                    self.log.write({"event": "client_gone", "seq": seq, "attempt": attempt,
                                    "during": "hang"})
                    return False
        except (ConnectionError, OSError) as e:
            self.log.write({"event": "client_gone", "seq": seq, "attempt": attempt,
                            "during": "stream", "error": repr(e)})
            return False


class _Renderer:
    """Renders neutral steps as Chat chunks or Anthropic Messages events."""

    def __init__(self, proto: str, attempt: int, model: str) -> None:
        self.proto = proto
        self.attempt = attempt
        self.model = model
        self.cid = f"chatcmpl-fault-{attempt}"
        self.created = int(time.time())
        self.block = None  # (index, kind) of the open Messages block
        self.index = -1
        self.usage = (10, 5)
        self.stop = None

    def _sub(self, s: str) -> str:
        return s.replace("ATTEMPT", f"attempt-{self.attempt}")

    # Chat -----------------------------------------------------------------
    def _chunk(self, delta, finish=None, usage=None, choices=True) -> bytes:
        obj = {"id": self.cid, "object": "chat.completion.chunk", "created": self.created,
               "model": self.model,
               "choices": [{"index": 0, "delta": delta, "finish_reason": finish}] if choices else []}
        if usage is not None:
            obj["usage"] = usage
        return b"data: " + json.dumps(obj).encode() + b"\n\n"

    # Messages ---------------------------------------------------------------
    @staticmethod
    def _ev(name: str, obj: dict) -> bytes:
        return f"event: {name}\ndata: {json.dumps(obj)}\n\n".encode()

    def _close(self) -> list[bytes]:
        if self.block is None:
            return []
        idx, _ = self.block
        self.block = None
        return [self._ev("content_block_stop", {"type": "content_block_stop", "index": idx})]

    def _open(self, kind: str, block: dict) -> list[bytes]:
        out = self._close()
        self.index += 1
        self.block = (self.index, kind)
        out.append(self._ev("content_block_start",
                            {"type": "content_block_start", "index": self.index,
                             "content_block": block}))
        return out

    def render(self, s: tuple) -> list[bytes]:
        kind = s[0]
        if self.proto == "chat":
            if kind == "start":
                return [self._chunk({"role": "assistant", "content": ""})]
            if kind == "text":
                return [self._chunk({"content": w}) for w in _split(self._sub(s[1]))]
            if kind == "reasoning":
                return [self._chunk({"reasoning_content": w}) for w in _split(self._sub(s[1]))]
            if kind == "sig":
                return []
            if kind == "tool_call":
                _, cid, name, frags = s
                out = [self._chunk({"tool_calls": [{"index": 0, "id": cid, "type": "function",
                                                    "function": {"name": name, "arguments": ""}}]})]
                out += [self._chunk({"tool_calls": [{"index": 0, "function": {"arguments": f}}]})
                        for f in frags]
                return out
            if kind == "finish":
                return [self._chunk({}, finish=s[1])]
            if kind == "usage":
                p, c = s[1], s[2]
                return [self._chunk({}, usage={"prompt_tokens": p, "completion_tokens": c,
                                               "total_tokens": p + c}, choices=False)]
            if kind == "done":
                return [b"data: [DONE]\n\n"]
            if kind == "error":
                return [b"data: " + json.dumps({"error": {"message": s[1], "type": "server_error",
                                                          "code": 500}}).encode() + b"\n\n"]
            raise ValueError(kind)
        # Messages
        if kind == "start":
            return [self._ev("message_start", {"type": "message_start", "message": {
                "id": f"msg_fault_{self.attempt}", "type": "message", "role": "assistant",
                "model": self.model, "content": [], "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 1}}})]
        if kind == "text":
            out = [] if self.block and self.block[1] == "text" else self._open(
                "text", {"type": "text", "text": ""})
            out += [self._ev("content_block_delta", {"type": "content_block_delta",
                                                     "index": self.index,
                                                     "delta": {"type": "text_delta", "text": w}})
                    for w in _split(self._sub(s[1]))]
            return out
        if kind == "reasoning":
            out = [] if self.block and self.block[1] == "thinking" else self._open(
                "thinking", {"type": "thinking", "thinking": "", "signature": ""})
            out += [self._ev("content_block_delta", {"type": "content_block_delta",
                                                     "index": self.index,
                                                     "delta": {"type": "thinking_delta",
                                                               "thinking": w}})
                    for w in _split(self._sub(s[1]))]
            return out
        if kind == "sig":
            return [self._ev("content_block_delta", {"type": "content_block_delta",
                                                     "index": self.index,
                                                     "delta": {"type": "signature_delta",
                                                               "signature": s[1]}})]
        if kind == "tool_call":
            _, cid, name, frags = s
            out = self._open("tool_use", {"type": "tool_use", "id": cid, "name": name, "input": {}})
            out += [self._ev("content_block_delta", {"type": "content_block_delta",
                                                     "index": self.index,
                                                     "delta": {"type": "input_json_delta",
                                                               "partial_json": f}})
                    for f in frags]
            return out
        if kind == "finish":
            self.stop = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens"}.get(
                s[1], s[1])
            return self._close()
        if kind == "usage":
            self.usage = (s[1], s[2])
            return [self._ev("message_delta", {"type": "message_delta",
                                               "delta": {"stop_reason": self.stop,
                                                         "stop_sequence": None},
                                               "usage": {"input_tokens": self.usage[0],
                                                         "output_tokens": self.usage[1]}})]
        if kind == "done":
            return [self._ev("message_stop", {"type": "message_stop"})]
        if kind == "error":
            return [self._ev("error", {"type": "error", "error": {"type": "api_error",
                                                                  "message": s[1]}})]
        raise ValueError(kind)


# ---------------------------------------------------------------------------
# Embedding and CLI


class ServerThread:
    """Runs a FaultServer on its own event loop in a daemon thread (for the probe driver)."""

    def __init__(self, plan: list, name: str, log_path: Path, port: int = 0) -> None:
        self.log = Log(log_path)
        self.server = FaultServer(plan, name, self.log)
        self.port = port
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def main():
            srv = await asyncio.start_server(self.server.handle, "127.0.0.1", self.port)
            self.port = srv.sockets[0].getsockname()[1]
            self._ready.set()
            async with srv:
                await srv.serve_forever()

        with contextlib.suppress(asyncio.CancelledError, RuntimeError):
            self._loop.run_until_complete(main())

    def start(self) -> ServerThread:
        self._thread.start()
        self._ready.wait(5)
        return self

    def stop(self) -> None:
        if self._loop:
            for task in asyncio.all_tasks(self._loop):
                self._loop.call_soon_threadsafe(task.cancel)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenario", default="ok")
    ap.add_argument("--plan-json", help="JSON file with a plan; overrides --scenario's plan")
    ap.add_argument("--port", type=int, default=18600)
    ap.add_argument("--log", type=Path, default=Path("pi_fault.jsonl"))
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list:
        for name, (desc, _) in SCENARIOS.items():
            print(f"{name:32s} {desc}")
        return
    plan = (plan_from_json(json.loads(args.plan_json.read_text())) if args.plan_json
            else SCENARIOS[args.scenario][1])
    log = Log(args.log)
    server = FaultServer(plan, args.scenario, log)

    async def run():
        srv = await asyncio.start_server(server.handle, "127.0.0.1", args.port)
        print(f"pi fault server '{args.scenario}' on 127.0.0.1:{args.port}", file=sys.stderr)
        async with srv:
            await srv.serve_forever()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())


if __name__ == "__main__":
    main()
