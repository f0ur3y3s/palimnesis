"""Archive-mode handling of ``POST /v1/chat/completions``.

Order of operations (contracts §3, §5, §11; D10):

1. Parse and reject unsupported requests before anything is archived.
2. ``ledger.accept`` commits the raw body, request, new occurrences and the
   attempt, or rejects the request (409 divergence, busy, retry conflicts).
3. Call the upstream with the reconstructed model view.
4. Streaming: parse upstream SSE incrementally. A batch is whatever has
   arrived by the time the read queue drains (capped at ``BATCH_MAX_BYTES``):
   paced decoding commits and forwards each event as it comes, bursts
   coalesce. Commit each batch's generated content, then forward that
   batch's original bytes. A fixed age timer was rejected: on Windows its
   15.6 ms tick granularity added ~34 ms per token while a FULL commit takes
   ~1 ms (results R7). The finish chunk is held until ``[DONE]``. Any
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
import os
import sqlite3

import anyio
import httpx

from . import chat, ledger
from .errors import error_response
from .fingerprint import fingerprint_v1, parse_retry_hint
from .budget import BudgetError
from .sse import SSEParser
from .viewengine import VIEW_FORMAT, ViewEngine
from .store import Store

log = logging.getLogger(__name__)

CRASH_EXIT_CODE = 77
# Only [DONE] (and perhaps a keepalive) may follow the finish chunk.
MAX_EVENTS_AFTER_FINISH = 32
BATCH_MAX_BYTES = 16 * 1024
READ_QUEUE_CHUNKS = 64
_EOF = object()


def crash_point(name: str) -> None:
    """Deterministic process death for crash-recovery tests (``MNEMON_CRASH_AT``)."""
    if os.environ.get("MNEMON_CRASH_AT") == name:
        os._exit(CRASH_EXIT_CODE)


def _error_event(code: str, message: str) -> bytes:
    payload = {"error": {"message": message, "type": "server_error", "code": code}}
    return b"data: " + json.dumps(payload).encode() + b"\n\n"


def _with_no_retry(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    kept = [(k, v) for k, v in headers if k.lower() not in (b"x-should-retry", b"content-length")]
    return kept + [(b"x-should-retry", b"false")]


class ArchiveHandler:
    def __init__(self, store: Store, client: httpx.AsyncClient, upstream_base: httpx.URL,
                 forward_headers, views=None) -> None:
        self.store = store
        self.views = views  # mnemon.viewengine.ViewEngine, or None for no bounded views
        self.client = client
        self.upstream_base = upstream_base
        self.forward_headers = forward_headers  # filtered client headers for upstream
        # Request IDs being relayed by this process (see ledger.accept).
        self.live: set[str] = set()
        self.branches = ledger.BranchCache()

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
        prepared = None
        if self.views is not None and await self.views.ready(self.client):
            try:
                prepared = await self.views.prepare(req)
            except BudgetError as e:
                await error_response(api_path, 400, "context_budget_exceeded", str(e))(
                    scope, receive, send)
                return
            except Exception:
                # A view defect must not fail the request: archive and forward
                # unbounded, as when views are disabled (D14.9).
                log.exception("bounded view preparation failed; forwarding unbounded")
                prepared = None
        str_headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in headers}
        idem_key = next((v for k, v in str_headers.items() if k.lower() == "idempotency-key"), None)
        fingerprint = fingerprint_v1(ledger.ENDPOINT_CHAT, session, ledger.branch_id_for(session),
                                     json.loads(body))
        try:
            # Shielded: once the accept transaction is submitted it commits even if
            # the client leaves, so its outcome must be observed and cleaned up here.
            with anyio.CancelScope(shield=True):
                plan = await self.store.write(lambda c: ledger.accept(
                    c, session_id=session, association=association, req=req,
                    fingerprint=fingerprint, retry_hint=parse_retry_hint(str_headers),
                    idem_key=idem_key, live=self.live, cache=self.branches))
        except ledger.Rejection as e:
            await error_response(api_path, e.status, e.code, e.message, retry=e.retry)(
                scope, receive, send)
            return
        except Exception as e:
            log.exception("archive write failed before acceptance")
            # Only a transient database condition is worth a client retry.
            transient = isinstance(e, sqlite3.OperationalError)
            response = error_response(api_path, 503, "archive_unavailable",
                                      "Mnemon could not archive the request.", type_="api_error",
                                      retry=transient)
            if transient:
                response.headers["retry-after"] = "2"
            await response(scope, receive, send)
            return

        gen = ledger.Generation(plan)
        try:
            crash_point("after_accept")
            if plan.replay is not None:
                await self._send_replay(send, plan.replay)
                return
            if prepared is not None and not await self._bound(scope, receive, send, req, gen,
                                                              prepared, api_path):
                return
            await self._run(scope, receive, send, gen, api_path, headers)
        except BaseException:
            # Cancellation (client disconnect) or an unexpected failure: record it
            # if storage allows, never claim success. ledger.interrupt runs after
            # any terminal write already queued, so it never adds a second one.
            if plan.replay is None and not gen.delivered:
                with anyio.CancelScope(shield=True):
                    try:
                        await self.store.write(lambda c: ledger.interrupt(c, gen))
                    except Exception:
                        log.exception("could not record the interrupted attempt")
            raise
        finally:
            self.live.discard(plan.request_id)

    async def _bound(self, scope, receive, send, req, gen, prepared, api_path) -> bool:
        """Replace the planned body with the bounded view; False if it cannot fit."""
        plan = gen.plan
        try:
            view = await self.views.build(prepared, plan)
        except BudgetError as e:
            await self.store.write(lambda c: ledger.finish_attempt(
                c, gen, "attempt_failed", reason="context_budget_exceeded"))
            await error_response(api_path, 400, "context_budget_exceeded", str(e))(
                scope, receive, send)
            return False
        except Exception:
            log.exception("bounded view build failed; forwarding unbounded")
            return True
        if view.moved:
            cause = ViewEngine.cause(plan.view_state, view.state)
            await self.store.write(lambda c: ledger.record_view(
                c, plan, view.state, budget=ViewEngine.snapshot(prepared.budget), cause=cause,
                **VIEW_FORMAT))
        plan.upstream_body = ViewEngine.body(req, plan, prepared, view)
        return True

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
        upstream_headers = [(k, v) for k, v in self.forward_headers(headers)
                            if k.lower() != b"accept-encoding"]
        # The relay parses what it archives, so ask for an uncompressed body.
        upstream_headers.append((b"accept-encoding", b"identity"))
        request = httpx.Request("POST", self.upstream_base.copy_with(raw_path=target),
                                headers=upstream_headers, content=plan.upstream_body)
        try:
            upstream = await self.client.send(request, stream=True)
        except httpx.TransportError as e:
            if self.views is not None:
                self.views.upstream.mark_stale("transport_error")
            await self.store.write(lambda c: ledger.finish_attempt(
                c, gen, "attempt_failed", reason="upstream_unreachable", error=type(e).__name__))
            await error_response(api_path, 502, "upstream_unreachable",
                                 "Mnemon could not reach the upstream server.",
                                 type_="api_error")(scope, receive, send)
            return
        try:
            if upstream.status_code != 200:
                await self._relay_upstream_error(scope, receive, send, gen, upstream, api_path)
            elif plan.stream:
                await self._stream(send, gen, upstream)
            else:
                await self._buffered(scope, receive, send, gen, upstream, api_path)
        finally:
            with anyio.CancelScope(shield=True):
                await upstream.aclose()

    async def _upstream_failed(self, scope, receive, send, gen, api_path: str,
                               reason: str, message: str) -> None:
        """Shaped 502 after acceptance: input is archived, so no client retry (§5)."""
        await self.store.write(lambda c: ledger.finish_attempt(
            c, gen, "attempt_failed", reason=reason))
        await error_response(api_path, 502, "upstream_failed", message,
                             type_="api_error")(scope, receive, send)

    async def _relay_upstream_error(self, scope, receive, send, gen, upstream: httpx.Response,
                                    api_path: str) -> None:
        try:
            body = await upstream.aread()
        except httpx.TransportError:
            await self._upstream_failed(scope, receive, send, gen, api_path, "upstream_reset",
                                        "The upstream failed while sending an error response.")
            return
        if self.views is not None:
            self.views.upstream.observe(upstream.status_code, body)
        await self.store.write(lambda c: ledger.finish_attempt(
            c, gen, "attempt_failed", reason="upstream_status", status=upstream.status_code))
        headers = _with_no_retry(_response_headers(upstream))
        await send({"type": "http.response.start", "status": upstream.status_code, "headers": headers})
        await send({"type": "http.response.body", "body": body, "more_body": False})

    async def _buffered(self, scope, receive, send, gen, upstream: httpx.Response,
                        api_path: str) -> None:
        try:
            body = await upstream.aread()
        except httpx.TransportError:
            await self._upstream_failed(scope, receive, send, gen, api_path, "upstream_reset",
                                        "The upstream connection failed mid-response.")
            return
        headers = _with_no_retry(_response_headers(upstream))
        try:
            message = json.loads(body)
            if not isinstance(message, dict):
                raise ValueError("response is not a JSON object")
            parts = ledger.deltas(message)
            finish = (message.get("choices") or [{}])[0].get("finish_reason")
        except (ValueError, AttributeError, TypeError, KeyError, IndexError):
            await self._upstream_failed(scope, receive, send, gen, api_path,
                                        "malformed_upstream_body",
                                        "The upstream returned a malformed response.")
            return

        def commit(c):
            ledger.commit_batch(c, gen, parts, 0)
            ledger.finish_attempt(c, gen, "turn_complete", finish_reason=finish,
                                  usage=message.get("usage"))
            ledger.prepare_response(c, gen, 200, [(k.decode("latin-1"), v.decode("latin-1"))
                                                  for k, v in headers], body)

        try:
            await self.store.write(commit)
        except Exception as e:
            log.warning("non-streaming response could not be archived: %s", e)
            await self._upstream_failed(
                scope, receive, send, gen, api_path, "archive_failed",
                "Mnemon could not archive the upstream response.")
            return
        crash_point("after_prepare")
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": body, "more_body": False})
        gen.forwarded = len(body)
        await self._delivered(gen)

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
        batches = {"n": 0}

        async def flush(terminal: bool = False) -> None:
            nonlocal pending
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
            batches["n"] += 1
            crash_point(f"after_batch_{batches['n']}")
            if data:
                await send({"type": "http.response.body", "body": data, "more_body": True})
                gen.forwarded += len(data)
            pending = []
            if terminal:
                held.clear()

        async with anyio.create_task_group() as tg:
            tg.start_soon(read_upstream)
            outcome = None
            try:
                while outcome is None:
                    if pending and queue.empty():
                        await flush()
                    item = await queue.get()
                    if item is _EOF:
                        outcome = "eof"
                        break
                    if isinstance(item, Exception):
                        outcome = "transport_error"
                        break
                    for event in parser.feed(item):
                        self._observe(event, state)
                        if state["error"]:
                            # Nothing after an upstream error event is relayed;
                            # a later [DONE] must not turn the failure into success.
                            pending.append(event)
                            outcome = "upstream_error_event"
                            break
                        (held if state["finish"] or held else pending).append(event)
                        if len(held) > MAX_EVENTS_AFTER_FINISH:
                            raise ValueError("too many events after the finish chunk")
                        if state["done"]:
                            outcome = "done"
                            break
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
            except Exception as e:
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
        await self._delivered(gen)

    async def _delivered(self, gen: ledger.Generation) -> None:
        # The server write is complete; a client that disconnects right after
        # reading everything must not turn this record into a failure.
        with anyio.CancelScope(shield=True):
            await self.store.write(lambda c: ledger.record_delivery(
                c, gen.plan, "delivery_completed", bytes_forwarded=gen.forwarded))
        gen.delivered = True

    @staticmethod
    def _observe(event, state: dict) -> None:
        if event.data is None:
            return
        if event.data == "[DONE]":
            state["done"] = True
            return
        chunk = json.loads(event.data)
        if not isinstance(chunk, dict):
            raise ValueError("stream chunk is not a JSON object")
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
