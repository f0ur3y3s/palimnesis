"""Opt-in capture of raw proxied exchanges for baselines and replay fixtures.

Layout: ``<capture_dir>/<session>/<started_ns>-<nonce>/`` holding
``request.json`` + ``request.body`` (written on arrival) and ``response.json`` +
``response.body`` (written when the response ends, complete or not). Captures
contain conversation bodies, so they are never written unless configured.
Credential headers are redacted.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Iterable, Mapping

import anyio

log = logging.getLogger(__name__)

REDACTED = "<redacted>"
_SECRET_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "x-api-key", "api-key", "cookie"}
)


@dataclass(frozen=True)
class Exchange:
    session: str
    started_ns: int
    method: str
    path: str
    query: str
    request_headers: dict[str, str]
    request_body: bytes
    status: int | None
    response_headers: dict[str, str]
    response_body: bytes
    complete: bool


Headers = Mapping[str, str] | Iterable[tuple[bytes, bytes]]


def _redact(headers: Headers) -> dict[str, str]:
    """Lower-cased, credential-redacted headers; repeated names are comma-joined."""
    items = (
        headers.items()
        if isinstance(headers, Mapping)
        else ((k.decode("latin-1"), v.decode("latin-1")) for k, v in headers)
    )
    out: dict[str, str] = {}
    for key, value in items:
        key = key.lower()
        value = REDACTED if key in _SECRET_HEADERS else value
        out[key] = f"{out[key]}, {value}" if key in out else value
    return out


class CaptureRecorder:
    def __init__(self, capture_dir: Path) -> None:
        self._root = Path(capture_dir)

    async def record(
        self,
        *,
        session: str,
        method: str,
        path: str,
        query: str,
        request_headers: Headers,
        request_body: bytes,
        status: int,
        response_headers: Headers,
        response: AsyncIterator[bytes],
    ) -> AsyncIterator[bytes]:
        """Relay ``response`` unchanged while capturing it.

        Capture fails open: a write error is logged and the relay continues.
        """
        started_ns = time.time_ns()
        folder = self._root / session / f"{started_ns:020d}-{uuid.uuid4().hex[:8]}"
        request_meta = {
            "session": session,
            "started_ns": started_ns,
            "method": method,
            "path": path,
            "query": query,
            "headers": _redact(request_headers),
        }
        capturing = await _attempt(_write_request, folder, request_meta, request_body)
        if not capturing:
            async for chunk in response:
                yield chunk
            return
        chunks: list[bytes] = []
        complete = False
        try:
            async for chunk in response:
                chunks.append(chunk)
                yield chunk
            complete = True
        finally:
            response_meta = {
                "status": status,
                "headers": _redact(response_headers),
                "complete": complete,
            }
            # The relay may be finishing because it was cancelled; the
            # capture of a partial exchange must still land.
            with anyio.CancelScope(shield=True):
                await _attempt(_write_response, folder, response_meta, b"".join(chunks))


async def _attempt(write, *args) -> bool:
    try:
        await anyio.to_thread.run_sync(write, *args)
        return True
    except OSError as e:
        log.warning("capture write failed (%s); relaying without capture", type(e).__name__)
        return False


def _write_request(folder: Path, meta: dict, body: bytes) -> None:
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "request.body").write_bytes(body)
    (folder / "request.json").write_text(json.dumps(meta, indent=2), "utf-8")


def _write_response(folder: Path, meta: dict, body: bytes) -> None:
    (folder / "response.body").write_bytes(body)
    (folder / "response.json").write_text(json.dumps(meta, indent=2), "utf-8")


def load_exchanges(capture_dir: Path) -> list[Exchange]:
    """All captured exchanges, oldest first. Unfinished ones are incomplete."""
    exchanges = []
    for request_meta_path in Path(capture_dir).glob("*/*/request.json"):
        folder = request_meta_path.parent
        req = json.loads(request_meta_path.read_text("utf-8"))
        resp_path = folder / "response.json"
        resp = json.loads(resp_path.read_text("utf-8")) if resp_path.exists() else {}
        body_path = folder / "response.body"
        exchanges.append(
            Exchange(
                session=req["session"],
                started_ns=req["started_ns"],
                method=req["method"],
                path=req["path"],
                query=req["query"],
                request_headers=req["headers"],
                request_body=(folder / "request.body").read_bytes(),
                status=resp.get("status"),
                response_headers=resp.get("headers", {}),
                response_body=body_path.read_bytes() if body_path.exists() else b"",
                complete=resp.get("complete", False),
            )
        )
    return sorted(exchanges, key=lambda e: (e.started_ns, e.session))
