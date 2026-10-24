"""Scriptable OpenAI Chat Completions fault server for harness timeout/retry probes.

A deterministic stand-in for an upstream: each POST to ``*/chat/completions`` is one
attempt, and the selected scenario says what attempt N receives (the last entry
repeats). Every request (arrival time, headers, full body) and every response
milestone is appended to a JSONL log, so attempt counts, inter-attempt delays and
request-body differences can be read back afterwards.

It is a raw asyncio HTTP/1.1 server rather than an ASGI app because the probes need
byte-level control that frameworks hide: delaying the status line, ending a chunked
body cleanly versus dropping the connection without the terminating chunk, and
writing SSE comment lines.

Usage:
    uv run python eval/probes/opencode_fault_server.py --scenario s500 --port 18500 --log run.jsonl
    uv run python eval/probes/opencode_fault_server.py --list

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
import time
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Response steps


@dataclass
class Status:
    """Non-streaming error response with a JSON body."""

    status: int
    headers: dict[str, str] = field(default_factory=dict)
    message: str = "fault server error"
    header_delay: float = 0.0


@dataclass
class Stream:
    """SSE response. ``steps`` are tuples:

    ("role",) ("text", s) ("reasoning", s) ("finish", reason) ("usage",) ("done",)
    ("sleep", seconds) ("comment", text) ("comments", interval_s, total_s, text)
    ("error", message)  -- an in-stream ``data: {"error": {...}}`` event

    ``end``: "eof" ends the chunked body cleanly; "abort" closes the socket without
    the terminating chunk (RST); "hang" never ends (the client must time out).
    Put a ("sleep", s) before "abort": on Windows an RST discards data the client has
    not yet read, so an immediate reset can erase the chunks just written.
    """

    steps: list[tuple]
    end: str = "eof"
    headers: dict[str, str] = field(default_factory=dict)
    header_delay: float = 0.0


def ok() -> Stream:
    return Stream(
        [
            ("role",),
            ("text", "OK from fault server"),
            ("finish", "stop"),
            ("usage",),
            ("done",),
        ]
    )


NO_RETRY = {"x-should-retry": "false"}

SCENARIOS: dict[str, tuple[str, list]] = {
    "ok": ("Always a well-formed stream.", [ok()]),
    # 1. Plain 5xx
    "s500": ("HTTP 500 every attempt.", [Status(500)]),
    "s502": ("HTTP 502 every attempt.", [Status(502)]),
    "s503": ("HTTP 503 every attempt.", [Status(503)]),
    # 2. 429 / should-retry / 400
    "s429_ra2": (
        "HTTP 429 with retry-after: 2.",
        [Status(429, {"retry-after": "2"}, "rate limited")],
    ),
    "s429": ("HTTP 429 without retry-after.", [Status(429, {}, "rate limited")]),
    "s429_noretry": (
        "HTTP 429 + x-should-retry: false.",
        [Status(429, NO_RETRY, "rate limited")],
    ),
    "s500_noretry": ("HTTP 500 + x-should-retry: false.", [Status(500, NO_RETRY)]),
    "s400": (
        "HTTP 400 every attempt.",
        [Status(400, {}, "bad request from fault server")],
    ),
    "s409": (
        "HTTP 409 every attempt.",
        [Status(409, {}, "request already in progress")],
    ),
    "s409_noretry": (
        "HTTP 409 + x-should-retry: false.",
        [Status(409, NO_RETRY, "request already in progress")],
    ),
    "s429_ra15_then_ok": (
        "HTTP 429 with retry-after: 15, then OK.",
        [Status(429, {"retry-after": "15"}, "rate limited"), ok()],
    ),
    "s503_ra12_then_ok": (
        "HTTP 503 with retry-after: 12, then OK.",
        [Status(503, {"retry-after": "12"}, "overloaded"), ok()],
    ),
    "s429_ram9000_then_ok": (
        "HTTP 429 with retry-after-ms: 9000, then OK.",
        [Status(429, {"retry-after-ms": "9000"}, "rate limited"), ok()],
    ),
    "s503_then_ok": ("503 twice, then OK.", [Status(503), Status(503), ok()]),
    # 3. Role chunk only
    "role_only_eof": ("Role chunk, then clean EOF.", [Stream([("role",)], "eof")]),
    "role_only_eof_noretry": (
        "Role chunk, clean EOF, x-should-retry: false.",
        [Stream([("role",)], "eof", NO_RETRY)],
    ),
    "role_only_abort": (
        "Role chunk, 1 s pause, then connection reset.",
        [Stream([("role",), ("sleep", 1.0)], "abort")],
    ),
    "role_only_abort_noretry": (
        "Role chunk, 1 s pause, connection reset, x-should-retry: false.",
        [Stream([("role",), ("sleep", 1.0)], "abort", NO_RETRY)],
    ),
    # 4. Partial visible text
    "partial_eof": (
        "Role + partial text, clean EOF, every attempt.",
        [Stream([("role",), ("text", "Partial answer ATTEMPT")], "eof")],
    ),
    "partial_eof_then_ok": (
        "Role + partial text + EOF, then OK.",
        [Stream([("role",), ("text", "Partial answer ATTEMPT")], "eof"), ok()],
    ),
    "partial_abort_then_ok": (
        "Role + partial text, 1 s pause, connection reset, then OK.",
        [
            Stream(
                [("role",), ("text", "Partial answer ATTEMPT"), ("sleep", 1.0)], "abort"
            ),
            ok(),
        ],
    ),
    "partial_eof_noretry": (
        "Role + partial text + EOF with x-should-retry: false, then OK.",
        [
            Stream([("role",), ("text", "Partial answer ATTEMPT")], "eof", NO_RETRY),
            ok(),
        ],
    ),
    "partial_reasoning_then_ok": (
        "Role + reasoning_content + partial text + EOF, then OK.",
        [
            Stream(
                [
                    ("role",),
                    ("reasoning", "Thinking about ATTEMPT"),
                    ("text", "Partial answer ATTEMPT"),
                ],
                "eof",
            ),
            ok(),
        ],
    ),
    "reasoning_only_then_ok": (
        "Role + reasoning_content only + EOF, then OK.",
        [Stream([("role",), ("reasoning", "Thinking about ATTEMPT")], "eof"), ok()],
    ),
    # Mid-stream error signalling
    "error_event_then_ok": (
        "Role + in-stream error event (no text), EOF; then OK.",
        [Stream([("role",), ("error", "upstream failed")], "eof"), ok()],
    ),
    "error_event_noretry": (
        "Role + in-stream error event (no text), EOF, x-should-retry: false.",
        [Stream([("role",), ("error", "upstream failed")], "eof", NO_RETRY)],
    ),
    "partial_error_event_then_ok": (
        "Role + partial text + in-stream error event, EOF; then OK.",
        [
            Stream(
                [
                    ("role",),
                    ("text", "Partial answer ATTEMPT"),
                    ("error", "upstream failed"),
                ],
                "eof",
            ),
            ok(),
        ],
    ),
    "partial_error_event_noretry": (
        "Role + partial text + in-stream error event, EOF, x-should-retry: false; then OK.",
        [
            Stream(
                [
                    ("role",),
                    ("text", "Partial answer ATTEMPT"),
                    ("error", "upstream failed"),
                ],
                "eof",
                NO_RETRY,
            ),
            ok(),
        ],
    ),
    "idle_after_role_noretry_then_ok": (
        "Role chunk, then silence (hang), x-should-retry: false; then OK.",
        [Stream([("role",)], "hang", NO_RETRY), ok()],
    ),
    "partial_finish_error_then_ok": (
        "Role + partial text + finish_reason error, [DONE]; then OK.",
        [
            Stream(
                [
                    ("role",),
                    ("text", "Partial answer ATTEMPT"),
                    ("finish", "error"),
                    ("done",),
                ],
                "eof",
            ),
            ok(),
        ],
    ),
    # 5. Terminal-marker variants
    "finish_no_done": (
        "Text + finish_reason stop + usage, EOF without [DONE].",
        [
            Stream(
                [
                    ("role",),
                    ("text", "Complete answer ATTEMPT"),
                    ("finish", "stop"),
                    ("usage",),
                ],
                "eof",
            )
        ],
    ),
    "done_no_finish": (
        "Text + [DONE], no finish_reason.",
        [Stream([("role",), ("text", "Complete answer ATTEMPT"), ("done",)], "eof")],
    ),
    # 6. Header wait
    "header_delay8": (
        "Status line delayed 8 s, then OK.",
        [Stream(ok().steps, header_delay=8.0)],
    ),
    # 7. Read idle
    "idle_after_role": (
        "Role chunk, then silence (hang).",
        [Stream([("role",)], "hang")],
    ),
    "idle_after_role_then_ok": (
        "Role chunk, then silence (hang); then OK.",
        [Stream([("role",)], "hang"), ok()],
    ),
    "idle_after_text_then_ok": (
        "Role + partial text, then silence (hang); then OK.",
        [Stream([("role",), ("text", "Partial answer ATTEMPT")], "hang"), ok()],
    ),
    "keepalive_comments": (
        "Headers, ': keep-alive' every 2 s for 15 s, then a full answer.",
        [Stream([("comments", 2.0, 15.0, " keep-alive")] + ok().steps)],
    ),
    "keepalive_after_role": (
        "Role chunk, ': keep-alive' every 2 s for 15 s, then the rest of the answer.",
        [
            Stream(
                [
                    ("role",),
                    ("comments", 2.0, 15.0, " keep-alive"),
                    ("text", "OK after keepalive"),
                    ("finish", "stop"),
                    ("usage",),
                    ("done",),
                ]
            )
        ],
    ),
    # 8. Length
    "length": (
        "Text + finish_reason length, every attempt.",
        [
            Stream(
                [
                    ("role",),
                    ("text", "Truncated answer ATTEMPT"),
                    ("finish", "length"),
                    ("usage",),
                    ("done",),
                ]
            )
        ],
    ),
}


# ---------------------------------------------------------------------------
# Server


class Log:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._f = path.open("a", encoding="utf-8")
        self.t0 = time.monotonic()

    def write(self, record: dict) -> None:
        record = {
            "t": round(time.monotonic() - self.t0, 3),
            "wall": time.time(),
            **record,
        }
        self._f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._f.flush()


class FaultServer:
    def __init__(self, scenario: str, log: Log) -> None:
        self.name = scenario
        self.plan = SCENARIOS[scenario][1]
        self.log = log
        self.attempts = 0
        self.seq = 0
        self.conns = 0

    def step_for(self, attempt: int):
        return self.plan[min(attempt, len(self.plan)) - 1]

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.conns += 1
        conn = self.conns
        peer = writer.get_extra_info("peername")
        self.log.write(
            {"event": "connect", "conn": conn, "peer": list(peer) if peer else None}
        )
        try:
            while True:
                req = await self._read_request(reader)
                if req is None:
                    break
                keep = await self._respond(conn, req, reader, writer)
                if not keep:
                    break
        except (ConnectionError, asyncio.IncompleteReadError) as e:
            self.log.write({"event": "conn_error", "conn": conn, "error": repr(e)})
        finally:
            self.log.write({"event": "disconnect", "conn": conn})
            with contextlib.suppress(OSError):
                writer.close()

    async def _read_request(self, reader: asyncio.StreamReader):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except asyncio.IncompleteReadError:
            return None
        lines = head.decode("latin-1").split("\r\n")
        method, target, version = lines[0].split(" ", 2)
        headers: list[list[str]] = []
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
        return {
            "method": method,
            "target": target,
            "version": version,
            "headers": headers,
            "body": body,
        }

    async def _respond(
        self,
        conn: int,
        req: dict,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> bool:
        self.seq += 1
        is_chat = req["method"] == "POST" and req["target"].split("?")[0].endswith(
            "/chat/completions"
        )
        attempt = None
        step = None
        if is_chat:
            self.attempts += 1
            attempt = self.attempts
            step = self.step_for(attempt)
        try:
            body_json = json.loads(req["body"]) if req["body"] else None
        except ValueError:
            body_json = None
        self.log.write(
            {
                "event": "request",
                "seq": self.seq,
                "conn": conn,
                "attempt": attempt,
                "method": req["method"],
                "target": req["target"],
                "headers": req["headers"],
                "body": body_json
                if body_json is not None
                else req["body"].decode("utf-8", "replace"),
                "scenario": self.name,
                "step": _describe(step),
            }
        )
        if not is_chat:
            await self._write_status(writer, 404, {}, "not found")
            return True
        model = (body_json or {}).get("model", "fault")
        if isinstance(step, Status):
            if step.header_delay:
                await asyncio.sleep(step.header_delay)
            await self._write_status(writer, step.status, step.headers, step.message)
            self.log.write(
                {
                    "event": "response",
                    "seq": self.seq,
                    "attempt": attempt,
                    "status": step.status,
                }
            )
            return True
        return await self._write_stream(reader, writer, step, attempt, model)

    async def _write_status(
        self, writer, status: int, headers: dict, message: str
    ) -> None:
        body = json.dumps(
            {"error": {"message": message, "type": "fault_server", "code": status}}
        ).encode()
        head = [
            f"HTTP/1.1 {status} {_reason(status)}",
            "content-type: application/json",
            f"content-length: {len(body)}",
        ]
        head += [f"{k}: {v}" for k, v in headers.items()]
        writer.write(("\r\n".join(head) + "\r\n\r\n").encode() + body)
        await writer.drain()

    async def _write_stream(
        self, reader, writer, step: Stream, attempt: int, model: str
    ) -> bool:
        seq = self.seq
        if step.header_delay:
            self.log.write(
                {
                    "event": "header_delay",
                    "seq": seq,
                    "attempt": attempt,
                    "seconds": step.header_delay,
                }
            )
            # Wait out the delay, but notice (and timestamp) a client that gives up first.
            try:
                data = await asyncio.wait_for(reader.read(1), timeout=step.header_delay)
            except TimeoutError:
                data = None
            except (ConnectionError, OSError):
                data = b""
            if data == b"":
                self.log.write(
                    {
                        "event": "client_gone",
                        "seq": seq,
                        "attempt": attempt,
                        "during": "header_delay",
                    }
                )
                return False
        head = [
            "HTTP/1.1 200 OK",
            "content-type: text/event-stream",
            "cache-control: no-cache",
            "transfer-encoding: chunked",
        ]
        head += [f"{k}: {v}" for k, v in step.headers.items()]
        try:
            writer.write(("\r\n".join(head) + "\r\n\r\n").encode())
            await writer.drain()
            self.log.write({"event": "headers_sent", "seq": seq, "attempt": attempt})
            cid = f"chatcmpl-fault-{attempt}"
            created = int(time.time())

            def chunk(delta: dict, finish=None, usage=None, choices=True) -> bytes:
                obj = {
                    "id": cid,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]
                    if choices
                    else [],
                }
                if usage is not None:
                    obj["usage"] = usage
                return b"data: " + json.dumps(obj).encode() + b"\n\n"

            async def send(data: bytes) -> None:
                writer.write(b"%x\r\n" % len(data) + data + b"\r\n")
                await writer.drain()

            for s in step.steps:
                kind = s[0]
                if kind == "role":
                    await send(chunk({"role": "assistant", "content": ""}))
                elif kind == "text":
                    text = s[1].replace("ATTEMPT", f"attempt-{attempt}")
                    for word in _split(text):
                        await send(chunk({"content": word}))
                elif kind == "reasoning":
                    text = s[1].replace("ATTEMPT", f"attempt-{attempt}")
                    for word in _split(text):
                        await send(chunk({"reasoning_content": word}))
                elif kind == "finish":
                    await send(chunk({}, finish=s[1]))
                elif kind == "usage":
                    await send(
                        chunk(
                            {},
                            usage={
                                "prompt_tokens": 10,
                                "completion_tokens": 5,
                                "total_tokens": 15,
                            },
                            choices=False,
                        )
                    )
                elif kind == "error":
                    err = {
                        "error": {"message": s[1], "type": "server_error", "code": 500}
                    }
                    await send(b"data: " + json.dumps(err).encode() + b"\n\n")
                elif kind == "done":
                    await send(b"data: [DONE]\n\n")
                elif kind == "sleep":
                    await asyncio.sleep(s[1])
                elif kind == "comment":
                    await send(b":" + s[1].encode() + b"\n\n")
                elif kind == "comments":
                    interval, total, text = s[1], s[2], s[3]
                    elapsed = 0.0
                    while elapsed < total:
                        await asyncio.sleep(interval)
                        elapsed += interval
                        await send(b":" + text.encode() + b"\n\n")
                        self.log.write(
                            {
                                "event": "comment_sent",
                                "seq": seq,
                                "attempt": attempt,
                                "elapsed": elapsed,
                            }
                        )
                self.log.write(
                    {
                        "event": "step_sent",
                        "seq": seq,
                        "attempt": attempt,
                        "step": list(s),
                    }
                )
            if step.end == "eof":
                writer.write(b"0\r\n\r\n")
                await writer.drain()
                self.log.write(
                    {
                        "event": "stream_end",
                        "seq": seq,
                        "attempt": attempt,
                        "end": "eof",
                    }
                )
                return True
            if step.end == "abort":
                sock = writer.get_extra_info("socket")
                if sock is not None:
                    # SO_LINGER 0 => RST instead of FIN, a hard transport failure.
                    sock.setsockopt(
                        socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                    )
                writer.transport.abort()
                self.log.write(
                    {
                        "event": "stream_end",
                        "seq": seq,
                        "attempt": attempt,
                        "end": "abort",
                    }
                )
                return False
            # hang: send nothing more; wait until the client closes its side.
            self.log.write({"event": "hang_start", "seq": seq, "attempt": attempt})
            try:
                await reader.read(1)
            except (ConnectionError, OSError):
                pass
            self.log.write(
                {
                    "event": "client_gone",
                    "seq": seq,
                    "attempt": attempt,
                    "during": "hang",
                }
            )
            return False
        except (ConnectionError, OSError) as e:
            self.log.write(
                {
                    "event": "client_gone",
                    "seq": seq,
                    "attempt": attempt,
                    "error": repr(e),
                }
            )
            return False


def _split(text: str) -> list[str]:
    words = text.split(" ")
    return [w if i == 0 else " " + w for i, w in enumerate(words)]


def _reason(status: int) -> str:
    return {
        200: "OK",
        400: "Bad Request",
        404: "Not Found",
        429: "Too Many Requests",
        500: "Internal Server Error",
        502: "Bad Gateway",
        503: "Service Unavailable",
    }.get(status, "Status")


def _describe(step) -> str | None:
    if step is None:
        return None
    if isinstance(step, Status):
        return f"status {step.status} headers={step.headers} header_delay={step.header_delay}"
    return f"stream end={step.end} headers={step.headers} header_delay={step.header_delay} steps={step.steps}"


async def _serve(args) -> None:
    log = Log(Path(args.log))
    server = FaultServer(args.scenario, log)

    srv = await asyncio.start_server(server.handle, args.host, args.port)
    port = srv.sockets[0].getsockname()[1]
    log.write(
        {
            "event": "listening",
            "scenario": args.scenario,
            "port": port,
            "description": SCENARIOS[args.scenario][0],
        }
    )
    print(
        json.dumps(
            {"listening": f"http://{args.host}:{port}", "scenario": args.scenario}
        ),
        flush=True,
    )
    async with srv:
        await srv.serve_forever()


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--scenario", default="ok")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--log", default="fault_server.jsonl")
    p.add_argument("--list", action="store_true", help="list scenarios and exit")
    args = p.parse_args()
    if args.list:
        for name, (desc, _) in SCENARIOS.items():
            print(f"{name:28} {desc}")
        return
    if args.scenario not in SCENARIOS:
        sys.exit(f"unknown scenario {args.scenario!r}; use --list")
    try:
        asyncio.run(_serve(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
