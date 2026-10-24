"""Scriptable fake upstream used by deterministic proxy tests.

Tests queue responses with ``respond_json``/``respond_sse`` and then inspect
``requests`` (what the upstream actually received) and ``closed_streams``
(streams the upstream saw terminate early because the reader went away).
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field

from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse


@dataclass
class ReceivedRequest:
    method: str
    path: str
    query: str
    headers: dict[str, str]
    body: bytes


@dataclass
class _Scripted:
    status: int
    headers: dict[str, str]
    body: bytes | None = None
    chunks: list[tuple[float, bytes]] | None = None
    delay: float = 0.0
    extra_headers: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class FakeUpstream:
    requests: list[ReceivedRequest] = field(default_factory=list)
    closed_streams: list[str] = field(default_factory=list)
    completed_streams: list[str] = field(default_factory=list)
    # Requests whose client went away while the upstream was still "working"
    # on them, before any response headers were sent.
    abandoned: list[str] = field(default_factory=list)
    _script: list[_Scripted] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def respond_json(
        self,
        body: bytes,
        status: int = 200,
        headers: dict[str, str] | None = None,
        *,
        delay: float = 0.0,
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> None:
        """Queue a buffered response sent after ``delay`` seconds of "work".

        ``extra_headers`` are appended raw, so names may repeat.
        """
        hdrs = {"content-type": "application/json", **(headers or {})}
        self._script.append(
            _Scripted(
                status=status,
                headers=hdrs,
                body=body,
                delay=delay,
                extra_headers=extra_headers or [],
            )
        )

    def respond_sse(
        self,
        chunks: list[bytes | tuple[float, bytes]],
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Queue a streamed response; a ``(delay_s, data)`` item sleeps first."""
        timed = [c if isinstance(c, tuple) else (0.0, c) for c in chunks]
        hdrs = {"content-type": "text/event-stream", **(headers or {})}
        self._script.append(_Scripted(status=status, headers=hdrs, chunks=timed))

    def app(self) -> FastAPI:
        app = FastAPI()

        @app.api_route(
            "/{path:path}",
            methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"],
        )
        async def handle(path: str, request: Request) -> Response:
            body = await request.body()
            with self._lock:
                self.requests.append(
                    ReceivedRequest(
                        method=request.method,
                        path=request.url.path,
                        query=request.url.query,
                        headers={k.lower(): v for k, v in request.headers.items()},
                        body=body,
                    )
                )
                scripted = self._script.pop(0) if self._script else None
            if scripted is None:
                return Response(b'{"error":"unscripted"}', status_code=599)
            if scripted.chunks is None:
                if not await self._work(request, scripted.delay):
                    return Response(status_code=499)
                response = Response(
                    scripted.body, status_code=scripted.status, headers=scripted.headers
                )
                response.raw_headers.extend(
                    (k.encode("latin-1"), v.encode("latin-1"))
                    for k, v in scripted.extra_headers
                )
                return response
            label = request.url.path
            return StreamingResponse(
                self._stream(label, scripted.chunks),
                status_code=scripted.status,
                headers=scripted.headers,
            )

        return app

    async def _work(self, request: Request, delay: float) -> bool:
        """Sleep ``delay``; False (and recorded) if the client left meanwhile."""
        deadline = asyncio.get_running_loop().time() + delay
        while asyncio.get_running_loop().time() < deadline:
            if await request.is_disconnected():
                with self._lock:
                    self.abandoned.append(request.url.path)
                return False
            await asyncio.sleep(0.02)
        return True

    async def _stream(self, label: str, chunks: list[tuple[float, bytes]]):
        finished = False
        try:
            for delay, data in chunks:
                if delay:
                    await asyncio.sleep(delay)
                yield data
            finished = True
        finally:
            target = self.completed_streams if finished else self.closed_streams
            with self._lock:
                target.append(label)
