"""Scriptable Anthropic Messages fault server for Claude Code probes (Phase 4B S0, HC1-HC9).

A deterministic stand-in for a Messages upstream on loopback. It answers every path
Claude Code may use on its base URL and logs each request (arrival time, method, path,
query, headers with credentials redacted, full JSON body) to a JSONL file:

- ``POST */v1/messages``: the scenario. Each request that carries ``tools`` is a "main"
  attempt; the scenario's step N answers attempt N (the last step repeats). Requests
  without tools (titles, quota checks, other side queries) always get a well-formed
  answer and do not consume steps, so side traffic cannot shift a fault scenario.
  A Stream step answering a non-streaming request is answered with one JSON message.
- ``POST */v1/messages/count_tokens``: ``--count-tokens {404,200}``.
- ``HEAD|GET */api/hello``: ``--hello-status`` (default 404).
- ``GET */v1/models``: ``--models {404,200}``.
- anything else: 404, logged.

Content is produced by a responder that reads the request, so tool loops can be driven
from the prompt: a user text containing ``@@tool NAME {json}`` directives makes the
model call those tools one per response, in order; once all have results, it answers
with text. ``@@think`` makes it emit a thinking block first, signed per ``--sig``:
``none`` (no ``signature_delta``; the block keeps ``signature: ""`` from
``content_block_start``, as Strata streams it), ``empty`` (``signature_delta`` with
``""``) or ``opaque`` (a base64 string). ``--think`` emits thinking on every answer.

Validators reproduce upstream rejections to exercise Claude Code's recovery paths:
``--reject-system-role`` answers 400 to any ``role: system`` entry in ``messages``
(``--system-role-wording`` chooses the error text), ``--reject-empty-signature`` answers
400 to any thinking block whose signature is ``""``.

Raw asyncio HTTP/1.1, like ``opencode_fault_server.py``, for byte-level control (delayed
status line, SSE comments, clean EOF versus RST, hangs).

Usage:
    uv run python eval/probes/cc_fault_server.py --scenario ok --port 18600 --log run.jsonl
    uv run python eval/probes/cc_fault_server.py --list

It fabricates every response; never proxy it to a real provider.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import hashlib
import json
import re
import socket
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REDACT_HEADERS = {"x-api-key", "authorization", "cookie", "proxy-authorization"}

# ---------------------------------------------------------------------------
# Steps


@dataclass
class Status:
    """Error response with an Anthropic error envelope."""

    status: int
    headers: dict[str, str] = field(default_factory=dict)
    message: str = "fault server error"
    etype: str = "api_error"
    header_delay: float = 0.0


@dataclass
class Stream:
    """SSE response. ``steps`` are tuples:

    ("start",)                 message_start
    ("content",)               the responder's blocks (thinking/text/tool_use), each
                               start/deltas/stop
    ("finish",)                message_delta (stop_reason from the content) + message_stop
    ("text_open", s)           content_block_start(text) + one delta, block left open
    ("ping",)                  event: ping
    ("pings", interval, total) event: ping every interval for total seconds
    ("comment", text)          ": text"
    ("comments", interval, total, text)
    ("error", etype, message)  event: error
    ("sleep", s)

    ``end``: "eof" (clean end of chunked body), "abort" (RST), "hang" (wait for client).
    """

    steps: list[tuple]
    end: str = "eof"
    headers: dict[str, str] = field(default_factory=dict)
    header_delay: float = 0.0


def ok(headers: dict | None = None) -> Stream:
    return Stream([("start",), ("content",), ("finish",)], headers=headers or {})


NO_RETRY = {"x-should-retry": "false"}
YES_RETRY = {"x-should-retry": "true"}

SCENARIOS: dict[str, tuple[str, list]] = {
    "ok": ("Always a well-formed answer.", [ok()]),
    "ok_ping_first": (
        "ping before message_start, then a well-formed answer.",
        [Stream([("ping",), ("start",), ("ping",), ("content",), ("finish",)])],
    ),
    # Retry codes
    "s500": ("HTTP 500 every attempt.", [Status(500)]),
    "s529": ("HTTP 529 overloaded_error every attempt.", [Status(529, {}, "Overloaded", "overloaded_error")]),
    "s500_then_ok": ("500, then OK.", [Status(500), ok()]),
    "s500_noretry": ("500 + x-should-retry: false.", [Status(500, NO_RETRY)]),
    "s400_retry_true": ("400 + x-should-retry: true, then OK.", [Status(400, YES_RETRY, "bad request", "invalid_request_error"), ok()]),
    "s409": ("409 every attempt.", [Status(409, {}, "request already in progress", "invalid_request_error")]),
    "s409_noretry": ("409 + x-should-retry: false.", [Status(409, NO_RETRY, "request already in progress", "invalid_request_error")]),
    "s429_ra5_then_ok": ("429 retry-after: 5, then OK.", [Status(429, {"retry-after": "5"}, "queue full", "rate_limit_error"), ok()]),
    "s429_ra90": ("429 retry-after: 90 every attempt.", [Status(429, {"retry-after": "90"}, "queue full", "rate_limit_error")]),
    "s429_noretry": ("429 + x-should-retry: false.", [Status(429, NO_RETRY, "queue full", "rate_limit_error")]),
    "s400": ("400 invalid_request_error.", [Status(400, {}, "bad request from fault server", "invalid_request_error")]),
    # Stream failures
    "start_eof_then_ok": ("message_start, clean EOF; then OK.", [Stream([("start",)], "eof"), ok()]),
    "start_eof_noretry_then_ok": ("message_start, EOF, x-should-retry: false; then OK.", [Stream([("start",)], "eof", NO_RETRY), ok()]),
    "start_abort_then_ok": ("message_start, 1 s, RST; then OK.", [Stream([("start",), ("sleep", 1.0)], "abort"), ok()]),
    "partial_eof_then_ok": ("message_start + open text block, EOF; then OK.", [Stream([("start",), ("text_open", "Partial answer ATTEMPT")], "eof"), ok()]),
    "partial_abort_then_ok": ("message_start + open text, 1 s, RST; then OK.", [Stream([("start",), ("text_open", "Partial answer ATTEMPT"), ("sleep", 1.0)], "abort"), ok()]),
    "partial_eof_noretry_then_ok": ("open text, EOF, x-should-retry: false; then OK.", [Stream([("start",), ("text_open", "Partial answer ATTEMPT")], "eof", NO_RETRY), ok()]),
    "error_event_then_ok": ("message_start + event: error (api_error); then OK.", [Stream([("start",), ("error", "api_error", "upstream failed")]), ok()]),
    "error_event_overloaded_then_ok": ("message_start + event: error (overloaded_error); then OK.", [Stream([("start",), ("error", "overloaded_error", "Overloaded")]), ok()]),
    "error_event_noretry_then_ok": ("message_start + event: error, x-should-retry: false; then OK.", [Stream([("start",), ("error", "api_error", "upstream failed")], "eof", NO_RETRY), ok()]),
    "partial_error_event_then_ok": ("open text + event: error; then OK.", [Stream([("start",), ("text_open", "Partial answer ATTEMPT"), ("error", "api_error", "upstream failed")]), ok()]),
    "partial_error_event_noretry_then_ok": ("open text + event: error, x-should-retry: false; then OK.", [Stream([("start",), ("text_open", "Partial answer ATTEMPT"), ("error", "api_error", "upstream failed")], "eof", NO_RETRY), ok()]),
    "complete_then_eof_then_ok": ("full content blocks but no message_delta/stop, EOF; then OK.", [Stream([("start",), ("content",)], "eof"), ok()]),
    "complete_then_eof_noretry_then_ok": ("full content blocks, no message_delta/stop, EOF, x-should-retry: false; then OK.", [Stream([("start",), ("content",)], "eof", NO_RETRY), ok()]),
    "complete_then_error_event_then_ok": ("full content blocks, then event: error; then OK.", [Stream([("start",), ("content",), ("error", "api_error", "upstream failed")]), ok()]),
    "complete_then_error_event_noretry_then_ok": ("full content blocks, event: error, x-should-retry: false; then OK.", [Stream([("start",), ("content",), ("error", "api_error", "upstream failed")], "eof", NO_RETRY), ok()]),
    "complete_then_abort_then_ok": ("full content blocks, 1 s, RST; then OK.", [Stream([("start",), ("content",), ("sleep", 1.0)], "abort"), ok()]),
    # Header wait and idle
    "header_delay8": ("Status line delayed 8 s, then OK.", [Stream(ok().steps, header_delay=8.0), ok()]),
    "idle_after_start_then_ok": ("message_start, then silence; then OK.", [Stream([("start",)], "hang"), ok()]),
    "headers_only_idle_then_ok": ("headers, no event, silence; then OK.", [Stream([], "hang"), ok()]),
    "comments_40_then_ok": ("headers, ': keep-alive' every 5 s for 40 s, then answer.", [Stream([("comments", 5.0, 40.0, " keep-alive"), ("start",), ("content",), ("finish",)])]),
    "start_comments_40_then_ok": ("message_start, comments every 5 s for 40 s, then answer.", [Stream([("start",), ("comments", 5.0, 40.0, " keep-alive"), ("content",), ("finish",)])]),
    "pings_40_then_ok": ("headers, ping every 5 s for 40 s, then answer.", [Stream([("pings", 5.0, 40.0), ("start",), ("content",), ("finish",)])]),
    "start_pings_40_then_ok": ("message_start, ping every 5 s for 40 s, then answer.", [Stream([("start",), ("pings", 5.0, 40.0), ("content",), ("finish",)])]),
    "start_comments_330": ("message_start, comments every 15 s for 330 s, then answer; then OK.", [Stream([("start",), ("comments", 15.0, 330.0, " keep-alive"), ("content",), ("finish",)]), ok()]),
    "start_pings_330": ("message_start, ping every 15 s for 330 s, then answer; then OK.", [Stream([("start",), ("pings", 15.0, 330.0), ("content",), ("finish",)]), ok()]),
    "comments_330": ("headers only, comments every 15 s for 330 s, then answer; then OK.", [Stream([("comments", 15.0, 330.0, " keep-alive"), ("start",), ("content",), ("finish",)]), ok()]),
    "pings_330": ("headers only, ping every 15 s for 330 s, then answer; then OK.", [Stream([("pings", 15.0, 330.0), ("start",), ("content",), ("finish",)]), ok()]),
    "start_comments_660": ("message_start, comments every 15 s for 660 s, then answer; then OK.", [Stream([("start",), ("comments", 15.0, 660.0, " keep-alive"), ("content",), ("finish",)]), ok()]),
    "start_pings_660": ("message_start, ping every 15 s for 660 s, then answer; then OK.", [Stream([("start",), ("pings", 15.0, 660.0), ("content",), ("finish",)]), ok()]),
    # Length
    "max_tokens_stop": ("text with stop_reason max_tokens.", [Stream([("start",), ("content",), ("finish", "max_tokens")])]),
}


# ---------------------------------------------------------------------------
# Responder

TOOL_RE = re.compile(r"@@tool\s+(\w+)\s+(\{.*?\})(?=\s*(?:@@|$))", re.S)


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(b.get("text", ""))
    return "\n".join(out)


def _has_tool_result(content) -> bool:
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def plan_blocks(body: dict, attempt: int | None, opts) -> tuple[list[dict], str]:
    """Return (blocks, stop_reason) for this request."""
    msgs = [m for m in body.get("messages", []) if m.get("role") in ("user", "assistant")]
    # Find the last user turn that is plain text (no tool_result): the "instruction".
    instr_idx = None
    for i in range(len(msgs) - 1, -1, -1):
        m = msgs[i]
        if m["role"] == "user" and not _has_tool_result(m["content"]) and _text_of(m["content"]).strip():
            instr_idx = i
            break
    instr = _text_of(msgs[instr_idx]["content"]) if instr_idx is not None else ""
    done_calls = sum(
        1
        for m in msgs[(instr_idx or 0) + 1:]
        if m["role"] == "user" and _has_tool_result(m["content"])
    )
    tools = [(n, json.loads(a)) for n, a in TOOL_RE.findall(instr)]
    blocks: list[dict] = []
    tag = f"attempt-{attempt}" if attempt else "aux"
    if opts.think or "@@think" in instr:
        blocks.append({"type": "thinking", "thinking": f"Thinking about {tag} step {done_calls}."})
    if "@@thinkonly" in instr and msgs and msgs[-1] is msgs[instr_idx or 0]:
        # A response that is only a thinking block (tail-drop probe).
        return blocks or [{"type": "thinking", "thinking": f"Only thinking {tag}."}], "end_turn"
    if done_calls < len(tools) and body.get("tools"):
        name, inp = tools[done_calls]
        n = sum(1 for _ in msgs)
        blocks.append({"type": "tool_use", "id": f"toolu_fault_{n:03d}_{done_calls}", "name": name, "input": inp})
        return blocks, "tool_use"
    if not body.get("tools"):
        text = f"Side answer {tag}"
    elif tools:
        text = f"DONE after {done_calls} tool calls ({tag})."
    else:
        text = f"OK from cc fault server ({tag})."
    blocks.append({"type": "text", "text": text})
    return blocks, "end_turn"


def signature_for(opts, thinking: str) -> str | None:
    if opts.sig == "none":
        return None
    if opts.sig == "empty":
        return ""
    return base64.b64encode(hashlib.sha256(thinking.encode()).digest() * 2).decode()


# ---------------------------------------------------------------------------
# Server


class Log:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._f = path.open("a", encoding="utf-8")
        self.t0 = time.monotonic()

    def write(self, record: dict) -> None:
        record = {"t": round(time.monotonic() - self.t0, 3), "wall": round(time.time(), 3), **record}
        self._f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._f.flush()


def redact_headers(headers: list[list[str]]) -> list[list[str]]:
    out = []
    for k, v in headers:
        if k.lower() in REDACT_HEADERS:
            v = f"<redacted len={len(v)}>"
        out.append([k, v])
    return out


class FaultServer:
    def __init__(self, scenario: str, log: Log, opts) -> None:
        self.name = scenario
        self.plan = SCENARIOS[scenario][1]
        self.log = log
        self.opts = opts
        self.attempts = 0
        self.seq = 0
        self.conns = 0

    def step_for(self, attempt: int):
        return self.plan[min(attempt, len(self.plan)) - 1]

    async def handle(self, reader, writer) -> None:
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
        except (ConnectionError, asyncio.IncompleteReadError, OSError) as e:
            self.log.write({"event": "conn_error", "conn": conn, "error": repr(e)})
        finally:
            self.log.write({"event": "disconnect", "conn": conn})
            with contextlib.suppress(Exception):
                writer.close()

    async def _read_request(self, reader):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, ConnectionError):
            return None
        lines = head.decode("latin-1").split("\r\n")
        method, target, version = lines[0].split(" ", 2)
        headers = []
        for line in lines[1:]:
            if line:
                k, _, v = line.partition(":")
                headers.append([k.strip(), v.strip()])
        h = {k.lower(): v for k, v in headers}
        body = b""
        if "content-length" in h:
            body = await reader.readexactly(int(h["content-length"]))
        elif h.get("transfer-encoding", "").lower() == "chunked":
            while True:
                size = int((await reader.readuntil(b"\r\n")).strip().split(b";")[0], 16)
                if size == 0:
                    await reader.readuntil(b"\r\n")
                    break
                body += await reader.readexactly(size)
                await reader.readexactly(2)
        return {"method": method, "target": target, "headers": headers, "body": body}

    async def _respond(self, conn, req, reader, writer) -> bool:
        self.seq += 1
        seq = self.seq
        path, _, query = req["target"].partition("?")
        try:
            body = json.loads(req["body"]) if req["body"] else None
        except ValueError:
            body = None
        kind = "other"
        if path.endswith("/v1/messages/count_tokens"):
            kind = "count_tokens"
        elif path.endswith("/v1/messages"):
            kind = "messages"
        elif path.endswith("/api/hello"):
            kind = "hello"
        elif path.endswith("/v1/models"):
            kind = "models"
        attempt = None
        step = None
        is_main = kind == "messages" and isinstance(body, dict) and bool(body.get("tools"))
        streaming = isinstance(body, dict) and bool(body.get("stream"))
        if is_main:
            self.attempts += 1
            attempt = self.attempts
            step = self.step_for(attempt)
        if self.opts.raw_dir and req["body"]:
            (Path(self.opts.raw_dir) / f"req-{seq:03d}.json").write_bytes(req["body"])
        self.log.write({
            "event": "request", "seq": seq, "conn": conn, "kind": kind, "main": is_main,
            "stream": streaming, "attempt": attempt, "method": req["method"], "path": path,
            "query": query, "headers": redact_headers(req["headers"]),
            "body_bytes": len(req["body"]),
            "body": body if body is not None else req["body"].decode("utf-8", "replace"),
            "scenario": self.name, "step": _describe(step),
        })
        if kind == "hello":
            await self._write_json(writer, self.opts.hello_status, {} if self.opts.hello_status == 200 else _err("not_found_error", "not found"), head_only=req["method"] == "HEAD")
            return True
        if kind == "count_tokens":
            if self.opts.count_tokens == 200 and isinstance(body, dict):
                n = max(1, len(json.dumps(body)) // 4)
                await self._write_json(writer, 200, {"input_tokens": n})
            else:
                await self._write_json(writer, 404, _err("not_found_error", "not found"))
            return True
        if kind == "models":
            if self.opts.models == 200:
                await self._write_json(writer, 200, {"data": [{"type": "model", "id": "fault-model", "display_name": "Fault", "created_at": "2026-01-01T00:00:00Z"}], "has_more": False, "first_id": "fault-model", "last_id": "fault-model"})
            else:
                await self._write_json(writer, 404, _err("not_found_error", "not found"))
            return True
        if kind != "messages" or not isinstance(body, dict):
            await self._write_json(writer, 404, _err("not_found_error", "not found"))
            return True
        # Validators
        rej = self._validate(body)
        if rej is not None:
            await self._write_json(writer, 400, _err("invalid_request_error", rej))
            self.log.write({"event": "response", "seq": seq, "attempt": attempt, "status": 400, "rejected": rej})
            return True
        # Reported usage: --usage-input N (fixed) or "body" (request bytes / 4, a crude
        # stand-in for a real count so Claude Code's context estimate is realistic).
        u = self.opts.usage_input
        self.in_tokens = max(1, len(req["body"]) // 4) if u == "body" else int(u)
        if step is None:
            step = ok()
        if isinstance(step, Status):
            if step.header_delay:
                await asyncio.sleep(step.header_delay)
            await self._write_json(writer, step.status, _err(step.etype, step.message), step.headers)
            self.log.write({"event": "response", "seq": seq, "attempt": attempt, "status": step.status})
            return True
        blocks, stop = plan_blocks(body, attempt, self.opts)
        if not streaming:
            if step.header_delay:
                await asyncio.sleep(step.header_delay)
            msg = self._message(body, blocks, stop)
            await self._write_json(writer, 200, msg, step.headers)
            self.log.write({"event": "response", "seq": seq, "attempt": attempt, "status": 200, "nonstream": True, "stop_reason": stop})
            return True
        return await self._write_stream(reader, writer, step, attempt, body, blocks, stop)

    def _validate(self, body: dict) -> str | None:
        msgs = body.get("messages", [])
        if self.opts.reject_system_role:
            for i, m in enumerate(msgs):
                if m.get("role") == "system":
                    return self.opts.system_role_wording.replace("{i}", str(i))
        if self.opts.reject_empty_signature:
            for i, m in enumerate(msgs):
                c = m.get("content")
                if isinstance(c, list):
                    for j, b in enumerate(c):
                        if isinstance(b, dict) and b.get("type") == "thinking" and not b.get("signature"):
                            return f"messages.{i}.content.{j}: Invalid `signature` in `thinking` block"
        return None

    def _message(self, body, blocks, stop) -> dict:
        content = []
        for b in blocks:
            b = dict(b)
            if b["type"] == "thinking":
                b["signature"] = signature_for(self.opts, b["thinking"]) or ""
            content.append(b)
        return {
            "id": f"msg_fault_{self.seq:04d}", "type": "message", "role": "assistant",
            "model": body.get("model", "fault"), "content": content, "stop_reason": stop,
            "stop_sequence": None,
            "usage": {"input_tokens": self.in_tokens, "output_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        }

    async def _write_json(self, writer, status, obj, headers=None, head_only=False) -> None:
        data = json.dumps(obj).encode()
        head = [f"HTTP/1.1 {status} {_reason(status)}", "content-type: application/json", f"content-length: {len(data)}", "request-id: req_fault"]
        head += [f"{k}: {v}" for k, v in (headers or {}).items()]
        writer.write(("\r\n".join(head) + "\r\n\r\n").encode() + (b"" if head_only else data))
        await writer.drain()

    async def _write_stream(self, reader, writer, step: Stream, attempt, body, blocks, stop) -> bool:
        seq = self.seq
        if step.header_delay:
            self.log.write({"event": "header_delay", "seq": seq, "attempt": attempt, "seconds": step.header_delay})
            try:
                data = await asyncio.wait_for(reader.read(1), timeout=step.header_delay)
            except (TimeoutError, asyncio.TimeoutError):
                data = None
            except (ConnectionError, OSError):
                data = b""
            if data == b"":
                self.log.write({"event": "client_gone", "seq": seq, "attempt": attempt, "during": "header_delay"})
                return False
        head = ["HTTP/1.1 200 OK", "content-type: text/event-stream", "cache-control: no-cache", "transfer-encoding: chunked", "request-id: req_fault"]
        head += [f"{k}: {v}" for k, v in step.headers.items()]
        t_start = time.monotonic()
        try:
            writer.write(("\r\n".join(head) + "\r\n\r\n").encode())
            await writer.drain()
            self.log.write({"event": "headers_sent", "seq": seq, "attempt": attempt})

            async def send(data: bytes) -> None:
                writer.write(b"%x\r\n" % len(data) + data + b"\r\n")
                await writer.drain()

            async def ev(name: str, obj: dict) -> None:
                await send(f"event: {name}\ndata: ".encode() + json.dumps(obj).encode() + b"\n\n")

            index = 0
            for s in step.steps:
                k = s[0]
                if k == "start":
                    await ev("message_start", {"type": "message_start", "message": {
                        "id": f"msg_fault_{seq:04d}", "type": "message", "role": "assistant",
                        "model": body.get("model", "fault"), "content": [], "stop_reason": None,
                        "stop_sequence": None, "usage": {"input_tokens": self.in_tokens, "output_tokens": 0}}})
                elif k == "content":
                    for b in blocks:
                        if b["type"] == "thinking":
                            await ev("content_block_start", {"type": "content_block_start", "index": index, "content_block": {"type": "thinking", "thinking": "", "signature": ""}})
                            for w in _split(b["thinking"]):
                                await ev("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "thinking_delta", "thinking": w}})
                            sig = signature_for(self.opts, b["thinking"])
                            if sig is not None:
                                await ev("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "signature_delta", "signature": sig}})
                        elif b["type"] == "text":
                            await ev("content_block_start", {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}})
                            for w in _split(b["text"]):
                                await ev("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": w}})
                        elif b["type"] == "tool_use":
                            await ev("content_block_start", {"type": "content_block_start", "index": index, "content_block": {"type": "tool_use", "id": b["id"], "name": b["name"], "input": {}}})
                            js = json.dumps(b["input"])
                            for i in range(0, len(js), 12):
                                await ev("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "input_json_delta", "partial_json": js[i:i + 12]}})
                        await ev("content_block_stop", {"type": "content_block_stop", "index": index})
                        index += 1
                elif k == "finish":
                    reason = s[1] if len(s) > 1 else stop
                    await ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": reason, "stop_sequence": None}, "usage": {"input_tokens": self.in_tokens, "output_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}})
                    await ev("message_stop", {"type": "message_stop"})
                elif k == "text_open":
                    await ev("content_block_start", {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}})
                    await ev("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": s[1].replace("ATTEMPT", f"attempt-{attempt}")}})
                elif k == "ping":
                    await ev("ping", {"type": "ping"})
                elif k in ("pings", "comments"):
                    interval, total = s[1], s[2]
                    elapsed = 0.0
                    while elapsed < total:
                        await asyncio.sleep(interval)
                        elapsed += interval
                        if k == "pings":
                            await ev("ping", {"type": "ping"})
                        else:
                            await send(b":" + s[3].encode() + b"\n\n")
                        self.log.write({"event": f"{k[:-1]}_sent", "seq": seq, "attempt": attempt, "elapsed": elapsed})
                elif k == "comment":
                    await send(b":" + s[1].encode() + b"\n\n")
                elif k == "error":
                    await ev("error", {"type": "error", "error": {"type": s[1], "message": s[2]}})
                elif k == "sleep":
                    await asyncio.sleep(s[1])
                self.log.write({"event": "step_sent", "seq": seq, "attempt": attempt, "step": list(s), "since_headers": round(time.monotonic() - t_start, 3)})
            if step.end == "eof":
                writer.write(b"0\r\n\r\n")
                await writer.drain()
                self.log.write({"event": "stream_end", "seq": seq, "attempt": attempt, "end": "eof"})
                return True
            if step.end == "abort":
                sock = writer.get_extra_info("socket")
                if sock is not None:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                writer.transport.abort()
                self.log.write({"event": "stream_end", "seq": seq, "attempt": attempt, "end": "abort"})
                return False
            self.log.write({"event": "hang_start", "seq": seq, "attempt": attempt})
            with contextlib.suppress(ConnectionError, OSError):
                await reader.read(1)
            self.log.write({"event": "client_gone", "seq": seq, "attempt": attempt, "during": "hang", "since_headers": round(time.monotonic() - t_start, 3)})
            return False
        except (ConnectionError, OSError) as e:
            self.log.write({"event": "client_gone", "seq": seq, "attempt": attempt, "error": repr(e), "since_headers": round(time.monotonic() - t_start, 3)})
            return False


def _err(etype: str, message: str) -> dict:
    return {"type": "error", "error": {"type": etype, "message": message}}


def _split(text: str) -> list[str]:
    words = text.split(" ")
    return [w if i == 0 else " " + w for i, w in enumerate(words)]


def _reason(status: int) -> str:
    return {200: "OK", 400: "Bad Request", 404: "Not Found", 409: "Conflict", 429: "Too Many Requests",
            500: "Internal Server Error", 502: "Bad Gateway", 503: "Service Unavailable", 529: "Overloaded"}.get(status, "Status")


def _describe(step) -> str | None:
    if step is None:
        return None
    if isinstance(step, Status):
        return f"status {step.status} headers={step.headers}"
    return f"stream end={step.end} headers={step.headers} header_delay={step.header_delay} steps={step.steps}"


async def _serve(args) -> None:
    log = Log(Path(args.log))
    if args.raw_dir:
        Path(args.raw_dir).mkdir(parents=True, exist_ok=True)
    server = FaultServer(args.scenario, log, args)
    srv = await asyncio.start_server(server.handle, args.host, args.port)
    port = srv.sockets[0].getsockname()[1]
    log.write({"event": "listening", "scenario": args.scenario, "port": port, "description": SCENARIOS[args.scenario][0], "opts": {k: v for k, v in vars(args).items() if k not in ("log",)}})
    print(json.dumps({"listening": f"http://{args.host}:{port}", "scenario": args.scenario}), flush=True)
    async with srv:
        await srv.serve_forever()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenario", default="ok")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--log", default="cc_fault_server.jsonl")
    p.add_argument("--raw-dir")
    p.add_argument("--hello-status", type=int, default=404)
    p.add_argument("--count-tokens", type=int, default=404, choices=[200, 404])
    p.add_argument("--models", type=int, default=404, choices=[200, 404])
    p.add_argument("--sig", default="none", choices=["none", "empty", "opaque"])
    p.add_argument("--think", action="store_true")
    p.add_argument("--reject-system-role", action="store_true")
    p.add_argument("--system-role-wording", default='messages.{i}: Unexpected role "system". The input message role must be one of "user" or "assistant"')
    p.add_argument("--reject-empty-signature", action="store_true")
    p.add_argument("--usage-input", default="100", help='input_tokens to report: an integer or "body" (bytes/4)')
    p.add_argument("--list", action="store_true")
    return p


def main() -> None:
    args = build_parser().parse_args()
    if args.list:
        for name, (desc, _) in SCENARIOS.items():
            print(f"{name:36} {desc}")
        return
    if args.scenario not in SCENARIOS:
        sys.exit(f"unknown scenario {args.scenario!r}; use --list")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_serve(args))


if __name__ == "__main__":
    main()
