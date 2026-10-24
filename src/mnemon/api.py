"""HTTP surface: session-prefixed routes relayed to the upstream.

A raw ASGI application rather than a framework router, so the relay works on
the exact request target, query bytes and header list, and so a client
disconnect is observed at every stage (body read, waiting for upstream
headers, streaming) and closes the upstream request.
"""

from __future__ import annotations

import logging

import anyio
import httpx

from . import ledger
from .archive import ArchiveHandler
from .capture import CaptureRecorder
from .config import Settings
from .errors import error_response
from .sessions import SessionError, resolve_session
from .store import Store

log = logging.getLogger(__name__)

SESSION_PREFIX = b"/s/"
SESSION_HEADER = b"x-mnemon-session"

# Hop-by-hop headers (RFC 9110 §7.6.1) plus framing the relay recomputes.
_HOP_BY_HOP = frozenset(
    {
        b"connection",
        b"keep-alive",
        b"proxy-authenticate",
        b"proxy-authorization",
        b"proxy-connection",
        b"te",
        b"trailer",
        b"transfer-encoding",
        b"upgrade",
    }
)
_REQUEST_ONLY = frozenset({b"host", b"content-length"})


def _filter_headers(
    headers: list[tuple[bytes, bytes]], drop: frozenset[bytes] = frozenset()
) -> list[tuple[bytes, bytes]]:
    """Drop hop-by-hop headers, any named in Connection, and Mnemon's own."""
    listed = {
        token.strip().lower()
        for name, value in headers
        if name.lower() == b"connection"
        for token in value.split(b",")
    }
    return [
        (name, value)
        for name, value in headers
        if (lower := name.lower()) not in _HOP_BY_HOP
        and lower not in listed
        and lower not in drop
        and not lower.startswith(b"x-mnemon-")
    ]


def split_session_prefix(raw_path: bytes) -> tuple[str | None, bytes]:
    """``/s/<id>/rest`` → (``<id>``, ``/rest``); other paths have no path session."""
    if not raw_path.startswith(SESSION_PREFIX):
        return None, raw_path
    segment, _, rest = raw_path[len(SESSION_PREFIX) :].partition(b"/")
    return segment.decode("latin-1"), b"/" + rest


def _session_header(headers: list[tuple[bytes, bytes]]) -> str | None:
    """The X-Mnemon-Session value; repeated headers must agree."""
    values = {value for key, value in headers if key.lower() == SESSION_HEADER}
    if len(values) > 1:
        raise SessionError(
            "session_mismatch", "Repeated X-Mnemon-Session headers carry different values."
        )
    return values.pop().decode("latin-1") if values else None


class Proxy:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.upstream_base = httpx.URL(settings.upstream_base_url)
        self.recorder = (
            CaptureRecorder(settings.capture_dir) if settings.capture_dir else None
        )
        self.client: httpx.AsyncClient | None = None
        self.store: Store | None = None
        self.archive: ArchiveHandler | None = None

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
        elif scope["type"] == "http":
            await self._http(scope, receive, send)

    async def _lifespan(self, receive, send) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                self.client = httpx.AsyncClient(timeout=None)
                if self.settings.db_path is not None:
                    self.store = Store.open(self.settings.db_path, self.settings.synchronous)
                    abandoned = await self.store.write(ledger.recover)
                    if abandoned:
                        log.warning("marked %d interrupted attempt(s) abandoned", abandoned)
                    self.archive = ArchiveHandler(
                        self.store, self.client, self.upstream_base,
                        lambda headers: _filter_headers(headers, drop=_REQUEST_ONLY),
                    )
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await self.client.aclose()
                if self.store is not None:
                    self.store.close()
                await send({"type": "lifespan.shutdown.complete"})
                return

    async def _http(self, scope, receive, send) -> None:
        if self.client is None:
            raise RuntimeError(
                "Proxy has no upstream client: run it under a server with ASGI "
                "lifespan enabled (see mnemon.server.uvicorn_config)."
            )
        raw_path = scope.get("raw_path") or scope["path"].encode("latin-1")
        path_session, upstream_path = split_session_prefix(raw_path)
        api_path = upstream_path.decode("latin-1")
        headers = list(scope["headers"])
        try:
            session = resolve_session(path_session, _session_header(headers))
        except SessionError as e:
            await error_response(api_path, 400, e.code, e.message)(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break

        async with anyio.create_task_group() as tg:

            async def cancel_on_disconnect() -> None:
                while (await receive())["type"] != "http.disconnect":
                    pass
                tg.cancel_scope.cancel()

            tg.start_soon(cancel_on_disconnect)
            if self.archive is not None and scope["method"] == "POST":
                await self._archive_route(
                    scope, receive, send, session, path_session, api_path, headers, bytes(body)
                )
            else:
                await self._relay(
                    scope, receive, send, session, upstream_path, headers, bytes(body)
                )
            tg.cancel_scope.cancel()

    async def _archive_route(
        self, scope, receive, send, session, path_session, api_path, headers, body
    ) -> None:
        if api_path != ledger.ENDPOINT_CHAT:
            response = error_response(
                api_path, 400, "unsupported_feature",
                f"POST {api_path} is not supported in archive mode; run with "
                "--passthrough to relay it unarchived.",
            )
            await response(scope, receive, send)
            return
        await self.archive(
            scope, receive, send, session=session, api_path=api_path, headers=headers,
            body=body, association="path" if path_session is not None else "header",
        )

    async def _relay(
        self, scope, receive, send, session, upstream_path, headers, body
    ) -> None:
        api_path = upstream_path.decode("latin-1")
        query: bytes = scope.get("query_string", b"")
        target = self.upstream_base.raw_path.rstrip(b"/") + upstream_path
        if query:
            target += b"?" + query
        request = httpx.Request(
            scope["method"],
            self.upstream_base.copy_with(raw_path=target),
            headers=_filter_headers(headers, drop=_REQUEST_ONLY),
            content=body,
        )
        try:
            upstream = await self.client.send(request, stream=True)
        except httpx.TransportError as e:
            log.warning("upstream unreachable: %s", type(e).__name__)
            response = error_response(
                api_path,
                502,
                "upstream_unreachable",
                "Mnemon could not reach the upstream server.",
                type_="api_error",
                retry=True,
            )
            await response(scope, receive, send)
            return

        try:
            response_headers = _filter_headers(upstream.headers.raw)
            await send(
                {
                    "type": "http.response.start",
                    "status": upstream.status_code,
                    "headers": response_headers,
                }
            )
            relay = upstream.aiter_raw()
            if self.recorder is not None:
                relay = self.recorder.record(
                    session=session,
                    method=scope["method"],
                    path=api_path,
                    query=query.decode("latin-1"),
                    request_headers=headers,
                    request_body=body,
                    status=upstream.status_code,
                    response_headers=response_headers,
                    response=relay,
                )
            async for chunk in relay:
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            with anyio.CancelScope(shield=True):
                await upstream.aclose()


def create_app(settings: Settings) -> Proxy:
    return Proxy(settings)
