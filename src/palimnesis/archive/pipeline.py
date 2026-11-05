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
database or client applies backpressure to upstream reads. The request-wide
deadline ``D`` (contracts §5) bounds how long that can last: at ``D`` after
arrival the upstream response is closed, releasing its slot, the attempt is
recorded as failed with ``deadline_exceeded``, and the client gets a 504 if no
response has started, else the in-stream error event. Final sends to a
client that stopped reading get ``FINAL_SEND_S`` before the connection is
abandoned.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import sqlite3
import threading

from dataclasses import replace

import anyio
import httpx

from palimnesis.view import cacheacct

from palimnesis.protocols import chat

from palimnesis.archive import ledger

from palimnesis.recall import proactive as recall

from palimnesis.recall import tools as recalltools

from palimnesis.recall import search
from palimnesis.errors import error_response
from palimnesis.archive.fingerprint import fingerprint_v1, parse_retry_hint
from palimnesis.view.budget import BudgetError
from palimnesis.protocols.assemble import ChatAssembler
from palimnesis.protocols.sse import ChatStream, SSEParser
from palimnesis.archive.turns import is_instruction
from palimnesis.view.builder import fit_notes, notes_block, notes_from_reasoning
from palimnesis.view.engine import EXCERPT_FORMAT, VIEW_FORMAT, ViewEngine
from palimnesis.archive.store import Store

log = logging.getLogger(__name__)

CRASH_EXIT_CODE = 77
# Only [DONE] (and perhaps a keepalive) may follow the finish chunk.
MAX_EVENTS_AFTER_FINISH = 32
BATCH_MAX_BYTES = 16 * 1024
READ_QUEUE_CHUNKS = 64
FINAL_SEND_S = 2.0
_EOF = object()

# Hidden recall loop limits per visible response (Phase 3B, D55, D56; S0 delta 4).
MAX_CONTINUATIONS = 4
MAX_HIDDEN_CALLS = 8
ALLOWANCE_CAP = 24_576  # request-wide output allowance A's cap; R stays the per-call reserve
MIN_CONTINUATION_ALLOWANCE = 1_024  # below this Strata gives thinking no budget (§12.2)
RESULT_SHARE = 4  # hidden results take at most a quarter of the input budget per response
RESULT_CAPS = {recalltools.RECALL: 2_048, recalltools.GREP: 1_024, recalltools.CATALOG: 1_024}
LIMIT_RESULT = ("limit reached: no more archive lookups in this response. "
                "Answer from what you have.")
# Per instruction turn, across responses and synthetic follow-ups (D67, R29).
MAX_TURN_HIDDEN_CALLS = 16
NOTES_REFRESH_S = 180.0  # D72: a refresh slower than this fails; the request goes on
TURN_LIMIT_RESULT = ("limit reached: no more archive lookups until the next user message. "
                     "Continue from what you have.")


def _masked(state) -> bool:
    return bool(state.watermark_seq or state.collapse_seq or state.oversized)


def crash_point(name: str) -> None:
    """Deterministic process death for crash-recovery tests (``PALIMNESIS_CRASH_AT``)."""
    if os.environ.get("PALIMNESIS_CRASH_AT") == name:
        os._exit(CRASH_EXIT_CODE)


def _error_event(code: str, message: str) -> bytes:
    payload = {"error": {"message": message, "type": "server_error", "code": code}}
    return b"data: " + json.dumps(payload).encode() + b"\n\n"


def _with_no_retry(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    kept = [(k, v) for k, v in headers if k.lower() not in (b"x-should-retry", b"content-length")]
    return kept + [(b"x-should-retry", b"false")]


class ArchiveHandler:
    def __init__(self, store: Store, client: httpx.AsyncClient, upstream_base: httpx.URL,
                 forward_headers, views=None, deadline_s: float = 600.0,
                 on_change=None, addendum_for=None, hidden_tools=None) -> None:
        self.store = store
        # (version, schemas) of the hidden recall tools, or None (Phase 3B, D54).
        self.hidden_tools = hidden_tools
        # session id -> (addendum id, text) for the upstream system message, or None (D36).
        self.addendum_for = addendum_for
        self.deadline_s = deadline_s
        # Called with the session id after accept and after each attempt ends, from the
        # event loop; it must not block (palimnesis.transcripts.projector.Projector.trigger).
        self.on_change = on_change
        self.views = views  # palimnesis.view.engine.ViewEngine, or None for no bounded views
        self.client = client
        self.upstream_base = upstream_base
        self.forward_headers = forward_headers  # filtered client headers for upstream
        # Request IDs being relayed by this process (see ledger.accept).
        self.live: set[str] = set()
        self.branches = ledger.BranchCache()
        # Cache accounting and count drift (contracts §10, §1.3) for bounded views.
        self.accounts = (cacheacct.Accountant(views.profile, store, views)
                         if views is not None else None)

    async def __call__(self, scope, receive, send, *, session: str, api_path: str,
                       headers: list[tuple[bytes, bytes]], body: bytes, association: str) -> None:
        expires = anyio.current_time() + self.deadline_s
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
            candidate = self.addendum_for(session) if self.addendum_for else None
            if candidate is not None:
                # The text actually applied is the one fixed earlier, if any (D36).
                fixed = await self.store.read(lambda c: ledger.fixed_addendum(
                    c, ledger.branch_id_for(session)))
                if fixed is not None:
                    candidate = (fixed["addendum_id"], fixed["text"])
            extra = self.views.counter.count(candidate[1]) + 2 if candidate else 0
            tools = await self._hidden_tools_for(session, req)
            try:
                prepared = await self.views.prepare(req, extra, tools or [])
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
                                      "Palimnesis could not archive the request.", type_="api_error",
                                      retry=transient)
            if transient:
                response.headers["retry-after"] = "2"
            await response(scope, receive, send)
            return

        gen = ledger.Generation(plan)
        if plan.replay is None:
            self._changed(session)
        started = False

        async def tracked(message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            crash_point("after_accept")
            if plan.replay is not None:
                await self._send_replay(send, plan.replay)
                return
            with anyio.move_on_after(max(0.0, expires - anyio.current_time())) as window:
                if prepared is not None and not await self._bound(scope, receive, tracked, req,
                                                                  gen, prepared, api_path,
                                                                  headers):
                    return
                if plan.hidden_loop and plan.stream and plan.view is not None:
                    await self._hidden(scope, receive, tracked, gen, api_path, headers, req)
                else:
                    await self._run(scope, receive, tracked, gen, api_path, headers)
            if window.cancelled_caught and not gen.delivered:
                await self._expired(scope, receive, send, gen, api_path, started)
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
            if plan.replay is None:
                self._changed(session)

    async def _hidden_tools_for(self, session: str, req) -> list | None:
        """The hidden tool schemas this request would carry once fixed: the session's fixed
        ones, else the configured ones; None when off or with ``tool_choice: "none"``."""
        if (self.hidden_tools is None or not req.stream
                or req.settings.get("tool_choice") == "none"):
            return None
        fixed = await self.store.read(lambda c: ledger.fixed_hidden_tools(
            c, ledger.branch_id_for(session)))
        return fixed["tools"] if fixed else self.hidden_tools[1]

    def _changed(self, session: str) -> None:
        if self.on_change is None:
            return
        try:
            self.on_change(session)
        except Exception as e:  # noqa: BLE001 - a projection never fails a request
            log.warning("archive change hook failed: %s", type(e).__name__)

    async def _bound(self, scope, receive, send, req, gen, prepared, api_path,
                     headers=()) -> bool:
        """Replace the planned body with the bounded view; False if it cannot fit."""
        plan = gen.plan
        candidate = self.addendum_for(plan.session_id) if self.addendum_for else None
        if candidate is not None:
            fixed = await self.store.read(lambda c: ledger.fixed_addendum(c, plan.branch_id))
            plan.addendum = fixed["text"] if fixed else None
        offered = (self.hidden_tools is not None and req.stream
                   and req.settings.get("tool_choice") != "none")
        if offered:
            fixed_tools = await self.store.read(
                lambda c: ledger.fixed_hidden_tools(c, plan.branch_id))
            if fixed_tools is not None:
                plan.hidden_tools = fixed_tools["tools"]
                prepared = replace(prepared, tools=[*(prepared.tools or []), *plan.hidden_tools])
        elif self.hidden_tools is not None and req.stream:
            # Not offered here (tool_choice "none"), but a session that has them still
            # answers a copied palimnesis_* call itself: one is never relayed (§15).
            plan.hidden_loop = await self.store.read(
                lambda c: ledger.fixed_hidden_tools(c, plan.branch_id)) is not None
        try:
            view = await self.views.build(prepared, plan)
            pending_addendum = candidate is not None and plan.addendum is None
            pending_tools = offered and plan.hidden_tools is None
            if (pending_addendum or pending_tools) and _masked(view.state):
                # The first view that hides anything fixes the session's addendum (D36)
                # and hidden tools (D54); until then the body stays the client's.
                def fix(c):
                    addendum = (ledger.fix_addendum(c, plan, *candidate) if pending_addendum
                                else plan.addendum)
                    tools = (ledger.fix_hidden_tools(c, plan, *self.hidden_tools)
                             if pending_tools else plan.hidden_tools)
                    return addendum, tools

                plan.addendum, plan.hidden_tools = await self.store.write(fix)
                if pending_tools:
                    prepared = replace(prepared,
                                       tools=[*(prepared.tools or []), *plan.hidden_tools])
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
        if view.refresh is not None:
            view = await self._refresh_notes(scope, req, plan, prepared, view, api_path, headers)
        elif view.refresh_skipped:
            await self._record_skipped_refresh(plan)
        selected = None
        hosted = any(i.excerpt for i in plan.items if i.occ_id == plan.host_occ_id)
        if plan.host_occ_id is not None and not hosted:
            try:
                selected = await self.views.select(prepared, plan, view)
            except Exception:
                # An excerpt defect must not fail the request: answer without excerpts.
                # No row is written, so a later request may select for this host.
                log.exception("excerpt selection failed; continuing without excerpts")
                selected = None

        def commit(c):
            # The view move and the excerpt selection land together, before inference.
            if view.moved:
                ledger.record_view(c, plan, view.state, budget=ViewEngine.snapshot(prepared.budget),
                                   cause=ViewEngine.cause(plan.view_state, view.state),
                                   **self.views.view_format)
            view_id, view_n, _ = ledger.latest_view(c, plan.branch_id)
            block_id = None
            if selected is not None:
                selection, rendered, charge, allocation = selected
                block_id = ledger.record_excerpts(
                    c, plan, host_occ_id=plan.host_occ_id, selection=selection,
                    rendered=rendered, token_charge=charge, allocation=allocation,
                    base_view_n=view_n,
                    base_watermark_seq=view.state.watermark_seq,
                    base_collapse_seq=view.state.collapse_seq,
                    renderer_version=getattr(self.views, "excerpt_renderer", EXCERPT_FORMAT),
                    profile_id=self.views.profile.id)
            return block_id, view_id, view_n

        if view.moved or selected is not None:
            try:
                block_id, plan.view_id, plan.view_n = await self.store.write(commit)
            except Exception:
                if selected is None:
                    raise
                # An excerpt row that cannot be stored must not fail the request (§13):
                # commit the view move alone and answer without excerpts.
                log.exception("excerpt selection could not be stored; continuing without")
                selected = None
                block_id, plan.view_id, plan.view_n = await self.store.write(commit)
            crash_point("after_excerpt_commit")
            if selected is not None and selected[1]:
                plan.items = [replace(i, excerpt=(block_id, selected[1], selected[2]))
                              if i.occ_id == plan.host_occ_id else i for i in plan.items]
                plan.view_state = view.state
                try:
                    rebuilt = await self.views.build(prepared, plan)
                except Exception:
                    log.exception("view rebuild with excerpts failed; sending the base view")
                else:
                    if rebuilt.moved:  # e.g. an R3 omission the new block triggered
                        def record(c):
                            view_id = ledger.record_view(
                                c, plan, rebuilt.state,
                                budget=ViewEngine.snapshot(prepared.budget),
                                cause=ViewEngine.cause(view.state, rebuilt.state), **self.views.view_format)
                            return view_id, ledger.latest_view(c, plan.branch_id)[1]

                        # The call is attributed to the view it sends (contracts §10).
                        plan.view_id, plan.view_n = await self.store.write(record)
                    view = rebuilt
        plan.upstream_body = ViewEngine.body(req, plan, prepared, view)
        plan.view, plan.prepared = view, prepared
        plan.hidden_loop = plan.hidden_loop or bool(plan.hidden_tools)
        return True

    async def _refresh_notes(self, scope, req, plan, prepared, view, api_path, headers):
        """D72: before older messages leave the view, one internal upstream call asks the
        model to rewrite its working notes from the request as it rendered before the
        move. A committed version is rendered in the view returned; a failed one keeps the
        notes the view had. Nothing reaches the client, and a notes defect never fails
        the request: any error returns ``view`` unchanged."""
        try:
            return await self._refresh_notes_once(scope, req, plan, prepared, view, api_path,
                                                  headers)
        except Exception as e:  # noqa: BLE001 - cancellation still propagates
            log.warning("notes refresh skipped: %s", type(e).__name__)
            return view

    async def _record_skipped_refresh(self, plan) -> None:
        """A collapse whose refresh could not fit B_in sends no call; the notes the view
        had stay, and the failure is recorded as ``over_budget`` (contracts §2, R42)."""
        base_n = plan.view_n
        try:
            await self.store.write(lambda c: ledger.record_notes(
                c, plan, base_view_n=base_n, text="", status="failed", reason="over_budget"))
        except Exception as e:  # noqa: BLE001 - a notes defect never fails the request
            log.warning("notes refresh skip not recorded: %s", type(e).__name__)

    async def _refresh_notes_once(self, scope, req, plan, prepared, view, api_path, headers):
        overrides = {prepared.limit_field: prepared.budget.reserve, "stream": True,
                     "stream_options": {"include_usage": True}}
        if plan.hidden_tools:
            overrides["tools"] = prepared.tools
        refresh_plan = copy.copy(plan)
        refresh_plan.view, refresh_plan.prepared = view.refresh, prepared
        refresh_plan.upstream_body = chat.render_messages(req, view.refresh.messages, overrides)
        call = (self.accounts.begin(refresh_plan, self.views.mode, f"{plan.attempt_id}#notes")
                if self.accounts is not None else None)
        stream, reason, status, outcome = ChatStream(), None, None, "ok"
        try:
            with anyio.move_on_after(NOTES_REFRESH_S) as window:
                request = self._request(scope, api_path, headers, refresh_plan.upstream_body)
                try:
                    upstream = await self.client.send(request, stream=True)
                    try:
                        if upstream.status_code != 200:
                            failure = await upstream.aread()
                            reason, status = "upstream_status", upstream.status_code
                            # A 5xx or a context-window 400 invalidates the facts, as on
                            # the client's own call (contracts §1).
                            self.views.profile.facts.observe(status, failure)
                        else:
                            parser = SSEParser()
                            try:
                                async for chunk in upstream.aiter_raw():
                                    for event in parser.feed(chunk):
                                        stream.apply(event)
                            # An event the parser rejects: bad JSON, or valid JSON of the
                            # wrong shape (``data: 42``, a tool-call delta without an index).
                            except (ValueError, TypeError, AttributeError, KeyError,
                                    IndexError):
                                reason = "malformed"
                    finally:
                        with anyio.CancelScope(shield=True):
                            await upstream.aclose()
                except httpx.TransportError:
                    reason = "transport_error"
                    profile = self.views.profile
                    profile.facts.mark_stale(profile.errors.staleness_reason(None))
            if window.cancelled_caught:
                reason = "timeout"
            written, source = stream.content.strip(), None
            if (not written and self.views.view_policy.notes_format == "n2"
                    and (drafted := notes_from_reasoning(stream.reasoning))):
                written, source = drafted, "from_reasoning"  # D74
            if reason is None:
                reason = ("upstream_error" if stream.error else "incomplete" if not stream.done
                          else "tool_call" if stream.tool_calls
                          else "empty" if not written else None)
            text = "" if reason else await anyio.to_thread.run_sync(self._fit_notes, written)
            if reason is None and not text:
                reason = "too_long"
            outcome = reason or "ok"
        except BaseException:
            outcome = "cancelled"
            raise
        finally:
            if call is not None:
                usage = {"usage": stream.usage} if stream.usage else None
                await self.accounts.finish(refresh_plan, call, usage, outcome)
        base_n = plan.view_n

        def record(c):
            return ledger.record_notes(c, plan, base_view_n=base_n, text=text,
                                       status="failed" if reason else "committed",
                                       reason=f"{reason}:{status}" if status
                                       else reason or source)

        notes_id, n = await self.store.write(record)
        if reason:
            return view
        notes = {notes_id: (n, text)}
        state = replace(view.state, notes=notes_id)
        rebuilt = await self.views.build(prepared, replace(plan, view_state=state, notes=notes))
        # Only once the view naming them is built: a rebuild that raises returns the
        # previous view, whose notes the plan must still hold (protocol review, R42).
        plan.notes = notes
        # A rebuild that moves again keeps what it evicted visible to retrieval (A1).
        evicted = tuple(dict.fromkeys((*view.evicted_now, *rebuilt.evicted_now)))
        return replace(rebuilt, moved=True, evicted_now=evicted)

    def _fit_notes(self, text: str) -> str:
        """``text`` cut so its rendered block fits the notes slot (D72, D74)."""
        policy = self.views.view_policy
        # The header is counted at a 6-digit version, never below the real one.
        limit = policy.notes_tokens - 8  # the message's own template tokens
        count = self.views.counter.count_cached

        def fits(t: str) -> bool:
            return count(notes_block(999_999, t, policy.notes_header)) <= limit

        return fit_notes(text, fits, sections=policy.notes_format == "n2")

    async def _expired(self, scope, receive, send, gen, api_path: str, started: bool) -> None:
        """Deadline D passed after acceptance; the upstream is already closed."""
        with anyio.CancelScope(shield=True):
            try:
                await self.store.write(lambda c: ledger.expire(c, gen))
            except Exception:
                log.exception("could not record the expired attempt")
        with anyio.move_on_after(FINAL_SEND_S, shield=True):
            if not started:
                await error_response(api_path, 504, "deadline_exceeded",
                                     "The request did not complete within its deadline.",
                                     type_="api_error")(scope, receive, send)
                return
            await send({"type": "http.response.body", "more_body": True,
                        "body": _error_event("deadline_exceeded",
                                             "The request did not complete within its deadline.")})
            await send({"type": "http.response.body", "body": b"", "more_body": False})

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
        call = (self.accounts.begin(plan, self.views.mode) if self.accounts is not None
                else None)
        try:
            await self._call(scope, receive, send, gen, api_path, request)
        finally:
            if call is not None:
                await self.accounts.finish(plan, call, gen.usage_payload, gen.call_outcome)

    async def _call(self, scope, receive, send, gen, api_path, request) -> None:
        plan = gen.plan
        try:
            upstream = await self.client.send(request, stream=True)
        except httpx.TransportError as e:
            gen.call_outcome = "transport_error"
            if self.views is not None:
                facts, errors = self.views.profile.facts, self.views.profile.errors
                facts.mark_stale(errors.staleness_reason(None))
            await self.store.write(lambda c: ledger.finish_attempt(
                c, gen, "attempt_failed", reason="upstream_unreachable", error=type(e).__name__))
            await error_response(api_path, 502, "upstream_unreachable",
                                 "Palimnesis could not reach the upstream server.",
                                 type_="api_error")(scope, receive, send)
            return
        try:
            if upstream.status_code != 200:
                gen.call_outcome = "upstream_status"
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
            self.views.profile.facts.observe(upstream.status_code, body)
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

        gen.usage_payload, gen.call_outcome = message, "ok"

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
                "Palimnesis could not archive the upstream response.")
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
        state = {"finish": None, "usage": None, "usage_chunk": None, "done": False, "error": None}
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
                    gen.usage_payload, gen.call_outcome = state["usage_chunk"], "ok"
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
                                                 "Palimnesis could not archive the response.")})
            finally:
                tg.cancel_scope.cancel()
        await send({"type": "http.response.body", "body": b"", "more_body": False})
        await self._delivered(gen)

    # --- hidden recall loop (Phase 3B, D52–D56) ----------------------------------------

    def _request(self, scope, api_path: str, headers, body: bytes) -> httpx.Request:
        target = self.upstream_base.raw_path.rstrip(b"/") + api_path.encode("latin-1")
        query = scope.get("query_string", b"")
        if query:
            target += b"?" + query
        upstream_headers = [(k, v) for k, v in self.forward_headers(headers)
                            if k.lower() != b"accept-encoding"]
        upstream_headers.append((b"accept-encoding", b"identity"))
        return httpx.Request("POST", self.upstream_base.copy_with(raw_path=target),
                             headers=upstream_headers, content=body)

    async def _hidden(self, scope, receive, send, gen, api_path, headers, req) -> None:
        """One visible response across upstream calls: answer hidden ``palimnesis_*``
        calls here and call again until the model answers, hands an external call to the
        client, or a limit ends it with ``length`` (contracts §7). Any failure ends with
        the endpoint's error, in-stream once the response has started (contracts §5)."""
        started = False

        async def tracked(message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self._hidden_loop(scope, receive, tracked, gen, api_path, headers, req)
        except Exception as e:
            log.warning("hidden recall loop stopped: %s", type(e).__name__)
            with anyio.CancelScope(shield=True):
                try:
                    await self.store.write(lambda c: ledger.fail(c, gen, "relay_error",
                                                                 error=type(e).__name__))
                except Exception:
                    log.exception("could not record the hidden loop failure")
            if started:
                await send({"type": "http.response.body", "more_body": True,
                            "body": _error_event("archive_unavailable",
                                                 "Palimnesis could not complete the response.")})
                await send({"type": "http.response.body", "body": b"", "more_body": False})
            else:
                await error_response(api_path, 502, "upstream_failed",
                                     "Palimnesis could not complete the response.",
                                     type_="api_error")(scope, receive, send)

    async def _hidden_loop(self, scope, receive, send, gen, api_path, headers, req) -> None:
        plan = gen.plan
        prepared, view = plan.prepared, plan.view
        asm = ChatAssembler(lambda name: bool(name) and name.startswith(chat.RESERVED_PREFIX))
        client_limit = req.settings.get(prepared.limit_field)
        allowance = min(client_limit or ALLOWANCE_CAP, ALLOWANCE_CAP)
        result_room = prepared.budget.input_budget // RESULT_SHARE
        call_plan, k = plan, 1
        calls_made = continuations = 0
        refused = False
        since = next((item.seq for item in reversed(plan.items)
                      if item.seq is not None and item.message.get("role") == "user"
                      and is_instruction("user", item.message.get("content")
                                         if isinstance(item.message.get("content"), str) else "")),
                     0)
        turn_spent = await self.store.read(
            lambda c: ledger.turn_hidden_calls(c, plan.branch_id, since))
        while True:
            asm.begin()
            call_id = plan.attempt_id if k == 1 else f"{plan.attempt_id}#{k}"
            ok = await self._hidden_call(scope, receive, send, gen, call_plan, asm, api_path,
                                         headers, call_id, first=k == 1)
            if not ok:
                return
            consumed = sum(u.get("completion_tokens") or 0 for u in asm.call_usages)
            stop = (refused or continuations >= MAX_CONTINUATIONS
                    or allowance - consumed < MIN_CONTINUATION_ALLOWANCE)
            results = []
            for call in asm.hidden_calls:
                if (stop and asm.continues) or calls_made >= MAX_HIDDEN_CALLS:
                    refused = True
                    results.append((call, recalltools.Result(LIMIT_RESULT, False,
                                                             {"error": "limit_reached"})))
                    continue
                if turn_spent + calls_made >= MAX_TURN_HIDDEN_CALLS:
                    refused = True
                    results.append((call, recalltools.Result(TURN_LIMIT_RESULT, False,
                                                             {"error": "limit_reached"})))
                    continue
                results.append((call, await self._resolve(call, call_plan, result_room)))
                result_room -= self.views.counter.count(results[-1][1].text)
                if results[-1][1].meta.get("error") == "limit_reached":
                    refused = True
                else:
                    calls_made += 1  # answered calls only, as the turn count (D67)
            if results:
                def commit(c):
                    for call, result in results:
                        ledger.commit_internal_result(c, gen, call.id, call.name, result.text,
                                                      {"ok": result.ok, **{
                                                          k: v for k, v in result.meta.items()
                                                          if k in ("error", "address")}})

                await self.store.write(commit)
            if not asm.continues or stop:
                finish = "length" if asm.continues else None
                await self._hidden_terminal(send, gen, asm, finish)
                return
            continuations += 1
            k += 1
            if gen.occ_id is not None:
                part = gen.occ_id
                await self.store.write(lambda c: search.index_occurrence(c, part))
            gen.__dict__.update(ledger.next_generation(None, gen).__dict__)
            call_plan = await self._continuation(req, plan, call_plan, prepared,
                                                 min(allowance - consumed, prepared.budget.reserve))
            if call_plan is None:
                await self._hidden_terminal(send, gen, asm, "length")
                return

    async def _resolve(self, call, call_plan, room: int):
        name = call.name
        cap = max(0, min(RESULT_CAPS.get(name, 1024), room))
        hidden = recall.candidates(call_plan.items, call_plan.view.manifest, 2**62)
        masked = [occ for occ, form in call_plan.view.manifest if form != "verbatim"]
        ctx = dict(session_id=call_plan.session_id, branch_id=call_plan.branch_id,
                   count=self.views.counter.count, max_tokens=cap, hidden=hidden, masked=masked)

        stopped = threading.Event()  # set when the request is cancelled or expires

        def run(conn):
            return recalltools.run(name, call.arguments, recalltools.Context(
                conn=conn, cancelled=stopped.is_set, **ctx))

        if cap < 1:
            return recalltools.Result(LIMIT_RESULT, False, {"error": "limit_reached"})
        try:
            return await self.store.read(run)
        except BaseException:
            stopped.set()  # the reader thread stops scanning at its next block
            raise

    async def _continuation(self, req, plan, call_plan, prepared, limit: int):
        """The next call's plan: the history so far plus this attempt's parts and results,
        bounded again (a move mid-response is recorded), with the per-call limit."""
        own = await self.store.read(lambda c: ledger.attempt_items(c, plan.attempt_id))
        base = [i for i in plan.items]
        # Build from the state the previous call sent, so a move is never recorded twice.
        next_plan = replace(call_plan, items=[*base, *own], view_state=call_plan.view.state)
        budget = replace(prepared.budget, rewrite_limit=limit)
        limited = replace(prepared, budget=budget)
        try:
            view = await self.views.build(limited, next_plan)
        except BudgetError:
            return None
        if view.moved:
            def record(c):
                view_id = ledger.record_view(c, next_plan, view.state,
                                             budget=ViewEngine.snapshot(prepared.budget),
                                             cause=ViewEngine.cause(next_plan.view_state,
                                                                    view.state), **self.views.view_format)
                return view_id, ledger.latest_view(c, plan.branch_id)[1]

            next_plan.view_id, next_plan.view_n = await self.store.write(record)
        next_plan.view_state = view.state
        next_plan.view, next_plan.prepared = view, limited
        next_plan.upstream_body = chat.render_messages(
            req, view.messages, {prepared.limit_field: limit, "tools": limited.tools})
        return next_plan

    async def _hidden_call(self, scope, receive, send, gen, call_plan, asm, api_path, headers,
                           call_id: str, first: bool) -> bool:
        """One upstream call of the loop; False when it failed (already recorded)."""
        request = self._request(scope, api_path, headers, call_plan.upstream_body)
        call = (self.accounts.begin(call_plan, self.views.mode, call_id)
                if self.accounts is not None else None)
        gen.usage_payload, gen.call_outcome = None, "incomplete"
        try:
            try:
                upstream = await self.client.send(request, stream=True)
            except httpx.TransportError as e:
                gen.call_outcome = "transport_error"
                await self.store.write(lambda c: ledger.finish_attempt(
                    c, gen, "attempt_failed", reason="upstream_unreachable",
                    error=type(e).__name__))
                if first:
                    await error_response(api_path, 502, "upstream_unreachable",
                                         "Palimnesis could not reach the upstream server.",
                                         type_="api_error")(scope, receive, send)
                else:
                    await self._stream_failed(send, gen)
                return False
            try:
                if upstream.status_code != 200:
                    gen.call_outcome = "upstream_status"
                    if first:
                        await self._relay_upstream_error(scope, receive, send, gen, upstream,
                                                         api_path)
                    else:
                        await upstream.aread()
                        await self.store.write(lambda c: ledger.finish_attempt(
                            c, gen, "attempt_failed", reason="upstream_status",
                            status=upstream.status_code))
                        await self._stream_failed(send, gen)
                    return False
                if first:
                    await send({"type": "http.response.start", "status": 200,
                                "headers": _with_no_retry(_response_headers(upstream))})
                return await self._hidden_stream(send, gen, asm, upstream)
            finally:
                with anyio.CancelScope(shield=True):
                    await upstream.aclose()
        finally:
            if call is not None:
                await self.accounts.finish(call_plan, call, gen.usage_payload, gen.call_outcome)

    async def _stream_failed(self, send, gen) -> None:
        error = _error_event("upstream_stream_failed", "The upstream stream ended before completing.")
        await send({"type": "http.response.body", "body": error, "more_body": True})
        gen.forwarded += len(error)
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def _hidden_stream(self, send, gen, asm, upstream) -> bool:
        """Relay one call through the assembler, committing each batch before it is
        forwarded. The call's finish and ``[DONE]`` are held by the assembler."""
        parser = SSEParser()
        state = {"finish": None, "usage": None, "usage_chunk": None, "done": False, "error": None}
        pending: list = []  # (client bytes, parts)

        async def flush() -> None:
            nonlocal pending
            if not pending:
                return
            parts = [p for _, ps in pending for p in ps]
            data = b"".join(b for b, _ in pending)
            forwarded_before = gen.forwarded
            await self.store.write(lambda c: ledger.commit_batch(c, gen, parts, forwarded_before))
            if data:
                await send({"type": "http.response.body", "body": data, "more_body": True})
                gen.forwarded += len(data)
            pending = []

        outcome = None
        try:
            async for chunk in upstream.aiter_raw():
                for event in parser.feed(chunk):
                    self._observe(event, state)
                    if state["error"]:
                        outcome = "upstream_error_event"
                        break
                    out = asm.feed(event)
                    pending.append((out.client, out.parts))
                    if state["done"]:
                        outcome = "done"
                        break
                if outcome is not None:
                    break
                await flush()
        except httpx.TransportError:
            outcome = "upstream_reset"
        if outcome == "done":
            gen.usage_payload, gen.call_outcome = state["usage_chunk"], "ok"
            await flush()
            return True
        await flush()
        reason = outcome or "eof_without_done"
        await self.store.write(lambda c: ledger.finish_attempt(
            c, gen, "attempt_failed", reason=reason, forwarded=gen.forwarded))
        await self._stream_failed(send, gen)
        return False

    async def _hidden_terminal(self, send, gen, asm, finish: str | None) -> None:
        """Commit the response's end, then send its one finish chunk and ``[DONE]``."""
        data = asm.terminal(finish)
        usage = next((json.loads(e.data).get("usage") for e in SSEParser().feed(data)
                      if e.data and e.data != "[DONE]"), None)

        def commit(c):
            ledger.finish_attempt(c, gen, "turn_complete", finish_reason=finish or asm.finish,
                                  usage=usage, calls=len(asm.call_usages))

        await self.store.write(commit)
        await send({"type": "http.response.body", "body": data, "more_body": True})
        gen.forwarded += len(data)
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
            state["usage_chunk"] = chunk
        for choice in chunk.get("choices") or []:
            if choice.get("finish_reason"):
                state["finish"] = choice["finish_reason"]


def _response_headers(upstream: httpx.Response) -> list[tuple[bytes, bytes]]:
    from palimnesis.api import _filter_headers

    return _filter_headers(upstream.headers.raw)
