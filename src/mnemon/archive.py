"""Archive-mode handling of ``POST /v1/chat/completions``.

Order of operations (contracts §3, §5, §11; D10):

1. Parse and reject unsupported requests before anything is archived.
2. ``ledger.accept`` commits the raw body, request, new occurrences and the
   attempt, or rejects the request (409 divergence, busy, retry conflicts).
3. Call the upstream with the reconstructed model view.
4. Streaming: parse upstream SSE incrementally. Batch events (age, size or
   terminal), commit each batch's generated content, then forward that
   batch's original bytes. The finish chunk is held until ``[DONE]``. Any
   failure after the 200 ends the body with an in-stream error event, and
   every streaming 200 carries ``x-should-retry: false``.
5. Non-streaming: commit the generated turn and the prepared response, then
   deliver it.

Queues between the upstream reader and the committer are bounded, so a slow
database or client applies backpressure to upstream reads.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time

import anyio
import httpx

from . import chat, ledger
from .errors import error_response
from .fingerprint import fingerprint_v1, parse_retry_hint
from .sse import SSEParser
from .store import Store

log = logging.getLogger(__name__)

BATCH_MAX_AGE_S = 0.025
BATCH_MAX_BYTES = 16 * 1024
READ_QUEUE_CHUNKS = 64
_EOF = object()


def _error_event(code: str, message: str) -> bytes:
    payload = {"error": {"message": message, "type": "server_error", "code": code}}
    return b"data: " + json.dumps(payload).encode() + b"\n\n"


def _with_no_retry(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    kept = [(k, v) for k, v in headers if k.lower() not in (b"x-should-retry", b"content-length")]
    return kept + [(b"x-should-retry", b"false")]


class ArchiveHandler:
    def __init__(self, store: Store, client: httpx.AsyncClient, upstream_base: httpx.URL,
                 forward_headers) -> None:
        self.store = store
        self.client = client
        self.upstream_base = upstream_base
        self.forward_headers = forward_headers  # filtered client headers for upstream

    async def __call__(self, scope, receive, send, *, session: str, api_path: str,
                       headers: list[tuple[bytes, bytes]], body: bytes, association: str) -> None:
        try:
            req = chat.parse(body)
        except chat.Unsupported as e:
            await error_response(api_path, 400, e.code, f"{e.field}: {e}")(scope, receive, send)
            return
        except chat.InvalidBody as e:
            await error_response(api_path, 400, "invalid_body", str(e))(scope, receive, send)
            return
        str_headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in headers}
        idem_key = next((v for k, v in str_headers.items() if k.lower() == "idempotency-key"), None)
        fingerprint = fingerprint_v1(ledger.ENDPOINT_CHAT, session, ledger.branch_id_for(session),
                                     json.loads(body))
        try:
            plan = await self.store.write(lambda c: ledger.accept(
                c, session_id=session, association=association, req=req,
                fingerprint=fingerprint, retry_hint=parse_retry_hint(str_headers),
                idem_key=idem_key))
        except ledger.Rejection as e:
            await error_response(api_path, e.status, e.code, e.message, retry=e.retry)(
                scope, receive, send)
            return
        except Exception:
            log.exception("archive write failed before acceptance")
            response = error_response(api_path, 503, "archive_unavailable",
                                      "Mnemon could not archive the request.", type_="api_error",
                                      retry=True)
            response.headers["retry-after"] = "2"
            await response(scope, receive, send)
            return

        if plan.replay is not None:
            await self._send_replay(send, plan.replay)
            return

        gen = ledger.Generation(plan)
        try:
            await self._run(scope, receive, send, gen, api_path, headers)
        except BaseException:
            # Cancellation (client disconnect) or an unexpected failure: record it
            # if storage allows, never claim success.
            with anyio.CancelScope(shield=True):
                try:
                    if gen.finished:
                        await self.store.write(lambda c: ledger.record_delivery(
                            c, plan, "delivery_failed", bytes_forwarded=gen.forwarded))
                    else:
                        await self.store.write(lambda c: ledger.finish_attempt(
                            c, gen, "cancelled", forwarded=gen.forwarded))
                except Exception:
                    log.exception("could not record the interrupted attempt")
            raise

    async def _send_replay(self, send, replay: dict) -> None:
        headers = [(k.encode("latin-1"), v.encode("latin-1")) for k, v in replay["headers"]]
        await send({"type": "http.response.start", "status": replay["status"], "headers": headers})
        await send({"type": "http.response.body", "body": replay["body"], "more_body": False})

    async def _run(self, scope, receive, send, gen: ledger.Generation, api_path, headers) -> None:
        plan = gen.plan
        target = self.upstream_base.raw_path.rstrip(b"/") + api_path.encode("latin-1")
        query = scope.get("query_string", b"")
        if query:
            target += b"?" + query
        request = httpx.Request("POST", self.upstream_base.copy_with(raw_path=target),
                                headers=self.forward_headers(headers), content=plan.upstream_body)
        try:
            upstream = await self.client.send(request, stream=True)
        except httpx.TransportError as e:
            await self.store.write(lambda c: ledger.finish_attempt(
                c, gen, "attempt_failed", reason="upstream_unreachable", error=type(e).__name__))
            await error_response(api_path, 502, "upstream_unreachable",
                                 "Mnemon could not reach the upstream server.",
                                 type_="api_error")(scope, receive, send)
            return
        try:
            if upstream.status_code != 200:
                await self._relay_upstream_error(send, gen, upstream)
            elif plan.stream:
                await self._stream(send, gen, upstream)
            else:
                await self._buffered(send, gen, upstream)
        finally:
            with anyio.CancelScope(shield=True):
                await upstream.aclose()

    async def _relay_upstream_error(self, send, gen, upstream: httpx.Response) -> None:
        body = await upstream.aread()
        await self.store.write(lambda c: ledger.finish_attempt(
            c, gen, "attempt_failed", reason="upstream_status", status=upstream.status_code))
        headers = _with_no_retry(_response_headers(upstream))
        await send({"type": "http.response.start", "status": upstream.status_code, "headers": headers})
        await send({"type": "http.response.body", "body": body, "more_body": False})

    async def _buffered(self, send, gen, upstream: httpx.Response) -> None:
        body = await upstream.aread()
        headers = _with_no_retry(_response_headers(upstream))
        try:
            message = json.loads(body)
            parts = ledger.deltas(message)
            finish = (message.get("choices") or [{}])[0].get("finish_reason")
        except ValueError:
            await self.store.write(lambda c: ledger.finish_attempt(
                c, gen, "attempt_failed", reason="malformed_upstream_body"))
            raise

        def commit(c):
            ledger.commit_batch(c, gen, parts, 0)
            ledger.finish_attempt(c, gen, "turn_complete", finish_reason=finish,
                                  usage=message.get("usage"))
            ledger.prepare_response(c, gen, 200, [(k.decode("latin-1"), v.decode("latin-1"))
                                                  for k, v in headers], body)

        await self.store.write(commit)
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": body, "more_body": False})
        gen.forwarded = len(body)
        await self.store.write(lambda c: ledger.record_delivery(
            c, gen.plan, "delivery_completed", bytes_forwarded=gen.forwarded))

    async def _stream(self, send, gen, upstream: httpx.Response) -> None:
        await send({"type": "http.response.start", "status": 200,
                    "headers": _with_no_retry(_response_headers(upstream))})
        queue: asyncio.Queue = asyncio.Queue(maxsize=READ_QUEUE_CHUNKS)

        async def read_upstream() -> None:
            try:
                async for chunk in upstream.aiter_raw():
                    await queue.put(chunk)
                await queue.put(_EOF)
            except httpx.TransportError as e:
                await queue.put(e)

        parser = SSEParser()
        pending: list = []  # events awaiting commit + forward
        held: list = []  # the finish chunk and anything after it, until [DONE]
        state = {"finish": None, "usage": None, "done": False, "error": None}
        started = None

        async def flush(terminal: bool = False) -> None:
            nonlocal pending, started
            batch = pending + (held if terminal else [])
            parts = []
            for event in batch:
                if event.data is None or event.data == "[DONE]":
                    continue
                parts += ledger.deltas(json.loads(event.data))
            data = b"".join(e.raw for e in batch)
            forwarded_before = gen.forwarded

            def commit(c):
                ledger.commit_batch(c, gen, parts, forwarded_before)
                if terminal:
                    ledger.finish_attempt(c, gen, "turn_complete", finish_reason=state["finish"],
                                          usage=state["usage"])

            await self.store.write(commit)
            if data:
                await send({"type": "http.response.body", "body": data, "more_body": True})
                gen.forwarded += len(data)
            pending, started = [], None
            if terminal:
                held.clear()

        async with anyio.create_task_group() as tg:
            tg.start_soon(read_upstream)
            outcome = None
            try:
                while outcome is None:
                    timeout = None
                    if pending:
                        timeout = max(0.0, started + BATCH_MAX_AGE_S - time.monotonic())
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout)
                    except asyncio.TimeoutError:
                        await flush()
                        continue
                    if item is _EOF:
                        outcome = "eof"
                        break
                    if isinstance(item, Exception):
                        outcome = "transport_error"
                        break
                    for event in parser.feed(item):
                        self._observe(event, state)
                        (held if state["finish"] or held else pending).append(event)
                        if started is None and not held:
                            started = time.monotonic()
                        if state["done"]:
                            outcome = "done"
                        elif state["error"]:
                            outcome = "upstream_error_event"
                    if outcome is None and sum(len(e.raw) for e in pending) >= BATCH_MAX_BYTES:
                        await flush()
                if outcome == "done":
                    await flush(terminal=True)
                else:
                    await flush()
                    reason = {"eof": "eof_without_done", "transport_error": "upstream_reset",
                              "upstream_error_event": "upstream_error_event"}[outcome]
                    await self.store.write(lambda c: ledger.finish_attempt(
                        c, gen, "attempt_failed", reason=reason, forwarded=gen.forwarded))
                    error = _error_event("upstream_stream_failed",
                                         "The upstream stream ended before completing.")
                    await send({"type": "http.response.body", "body": error, "more_body": True})
                    gen.forwarded += len(error)
            except (ValueError, OSError, RuntimeError, sqlite3.Error) as e:
                # A batch could not be parsed or committed: forward nothing more.
                log.warning("stream relay stopped: %s", e)
                try:
                    await self.store.write(lambda c: ledger.finish_attempt(
                        c, gen, "attempt_failed", reason="relay_error", error=type(e).__name__))
                except Exception:
                    log.exception("could not record relay failure")
                await send({"type": "http.response.body", "more_body": True,
                            "body": _error_event("archive_unavailable",
                                                 "Mnemon could not archive the response.")})
            finally:
                tg.cancel_scope.cancel()
        await send({"type": "http.response.body", "body": b"", "more_body": False})
        await self.store.write(lambda c: ledger.record_delivery(
            c, gen.plan, "delivery_completed", bytes_forwarded=gen.forwarded))

    @staticmethod
    def _observe(event, state: dict) -> None:
        if event.data is None:
            return
        if event.data == "[DONE]":
            state["done"] = True
            return
        chunk = json.loads(event.data)
        if "error" in chunk:
            state["error"] = chunk["error"]
            return
        if chunk.get("usage"):
            state["usage"] = chunk["usage"]
        for choice in chunk.get("choices") or []:
            if choice.get("finish_reason"):
                state["finish"] = choice["finish_reason"]


def _response_headers(upstream: httpx.Response) -> list[tuple[bytes, bytes]]:
    from .api import _filter_headers

    return _filter_headers(upstream.headers.raw)
