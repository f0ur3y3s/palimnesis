"""Scriptable fake upstream used by deterministic proxy tests.

Tests queue responses with ``respond_json``/``respond_sse`` and then inspect
``requests`` (what the upstream actually received) and ``closed_streams``
(streams the upstream saw terminate early because the reader went away).

``GET /props`` is static: it answers from the recorded Strata ``props.json`` with the
mutable ``props_*`` attributes applied, never consumes the response script and is
counted in ``props_requests`` rather than ``requests``. When ``count_tokens_handler``
is set (by default an exact local count, like Strata), ``POST /v1/messages/count_tokens``
is answered by it and recorded in ``count_tokens_requests``; with ``None`` that route is
scripted like any other.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse


_PROBES = Path(__file__).resolve().parents[1] / "eval" / "probes" / "fixtures"


def _recorded_props() -> dict:
    return json.loads((_PROBES / "props.json").read_text(encoding="utf-8"))


def _recorded_template() -> str:
    return (_PROBES / "strata_chat_template.jinja").read_bytes().decode("utf-8")


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


def _local_count(body: dict) -> int:
    from mnemon import tokens
    from mnemon.upstream_facts import anthropic_to_render_args

    return tokens.default().count_messages(**anthropic_to_render_args(body))


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
    # Static GET /props (not scripted).
    props_n_ctx: int = 65536
    props_build_info: str = "Strata 0.1.48"
    props_chat_template: str = field(default_factory=_recorded_template)
    props_status: int = 200
    props_delay: float = 0.0
    props_requests: int = 0
    # POST /v1/messages/count_tokens handler: parsed body -> input_tokens. The
    # default counts exactly with the pinned template, as Strata does, so the
    # proxy's startup canary passes; None makes the route scripted.
    count_tokens_handler: Callable[[dict], int] | None = field(default=lambda body: _local_count(body))
    count_tokens_requests: list[dict] = field(default_factory=list)

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
            if request.method == "GET" and request.url.path == "/props":
                return await self._props()
            handler = self.count_tokens_handler
            if (
                handler is not None
                and request.method == "POST"
                and request.url.path == "/v1/messages/count_tokens"
            ):
                parsed = json.loads(body)
                with self._lock:
                    self.count_tokens_requests.append(parsed)
                return Response(
                    json.dumps({"input_tokens": handler(parsed)}).encode(),
                    media_type="application/json",
                )
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

    async def _props(self) -> Response:
        with self._lock:
            self.props_requests += 1
        if self.props_delay:
            await asyncio.sleep(self.props_delay)
        if self.props_status != 200:
            return Response(
                b'{"error":{"type":"server_error","message":"fake props failure"}}',
                status_code=self.props_status,
                media_type="application/json",
            )
        props = _recorded_props()
        props["default_generation_settings"]["n_ctx"] = self.props_n_ctx
        props["build_info"] = self.props_build_info
        props["chat_template"] = self.props_chat_template
        return Response(
            json.dumps(props, ensure_ascii=False).encode("utf-8"),
            media_type="application/json",
        )

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
