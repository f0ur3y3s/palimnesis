"""Helpers for archive-mode lifecycle tests at the HTTP seam.

The fake upstream here can also drop its connection mid-stream (``RESET``),
which the shared fake cannot. The archive database is inspected read-only.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx

from mnemon.api import create_app
from mnemon.config import Settings

from .fake_upstream import FakeUpstream
from .servers import serve

RESET = b"<<reset>>"
CONTINUE_TEXT = (
    "The previous response was interrupted. Continue from where you left off "
    "without repeating completed content."
)
CHAT = "/v1/chat/completions"


class ResettableUpstream(FakeUpstream):
    """A scripted chunk equal to ``RESET`` aborts the response mid-body."""

    async def _stream(self, label, chunks):
        finished = False
        try:
            for delay, data in chunks:
                if delay:
                    await asyncio.sleep(delay)
                if data == RESET:
                    raise ConnectionResetError("scripted upstream reset")
                yield data
            finished = True
        finally:
            target = self.completed_streams if finished else self.closed_streams
            with self._lock:
                target.append(label)


@dataclass
class LifecycleStack:
    upstream: ResettableUpstream
    proxy_url: str
    db_path: Path
    # Called synchronously when a request reaches the upstream, before it responds.
    on_upstream_request: Callable[[], None] | None = None

    def url(self, session: str) -> str:
        return f"{self.proxy_url}/s/{session}{CHAT}"

    def post(self, session: str, body: bytes, headers=None, timeout: float = 30) -> httpx.Response:
        with httpx.stream("POST", self.url(session), content=body, headers=headers,
                          timeout=timeout) as r:
            r.read()
        return r

    @contextmanager
    def db(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            yield conn
        finally:
            conn.close()

    def events(self, kind: str | None = None) -> list[tuple[str, dict]]:
        with self.db() as c:
            rows = c.execute("SELECT kind, payload FROM events ORDER BY event_id").fetchall()
        return [(k, json.loads(p)) for k, p in rows if kind is None or k == kind]

    def count(self, table: str) -> int:
        with self.db() as c:
            return c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


@contextmanager
def lifecycle_stack(tmp_path: Path) -> Iterator[LifecycleStack]:
    fake = ResettableUpstream()
    db_path = tmp_path / "archive.db"
    inner = fake.app()
    holder: list[LifecycleStack] = []

    async def hooked(scope, receive, send):
        if scope["type"] == "http" and holder and holder[0].on_upstream_request:
            holder[0].on_upstream_request()
        await inner(scope, receive, send)

    with serve(hooked) as upstream_url:
        settings = Settings(upstream_base_url=upstream_url, db_path=db_path)
        with serve(create_app(settings), mnemon=True) as proxy_url:
            holder.append(LifecycleStack(fake, proxy_url, db_path))
            yield holder[0]


def chunk(delta: dict, finish: str | None = None) -> bytes:
    """One Chat Completions stream chunk in the shape Strata and the fault server send."""
    obj = {"id": "chatcmpl-t", "object": "chat.completion.chunk", "created": 1,
           "model": "m", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    return b"data: " + json.dumps(obj).encode() + b"\n\n"


DONE = b"data: [DONE]\n\n"


def answer(text: str, finish: str = "stop") -> list[bytes]:
    """A complete streamed answer: role, text, finish, [DONE]."""
    return [chunk({"role": "assistant", "content": ""}), chunk({"content": text}),
            chunk({}, finish), DONE]


def body(messages: list[dict], stream: bool = True, **settings) -> bytes:
    return json.dumps({"model": "m", "messages": messages, **settings,
                       "stream": stream}).encode()


def user(text: str) -> dict:
    return {"role": "user", "content": text}


def assistant(text: str) -> dict:
    return {"role": "assistant", "content": text}


def sse_data(raw: bytes) -> list[str]:
    """``data:`` payloads of an SSE body, in order."""
    out = []
    for event in raw.replace(b"\r\n", b"\n").split(b"\n\n"):
        for line in event.split(b"\n"):
            if line.startswith(b"data:"):
                out.append(line[5:].strip().decode())
    return out


def eventually(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def in_thread(fn) -> tuple[threading.Thread, dict]:
    result: dict = {}

    def run():
        try:
            result["value"] = fn()
        except Exception as e:  # noqa: BLE001 - surfaced by the test
            result["error"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, result
