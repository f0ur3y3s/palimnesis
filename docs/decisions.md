# Decisions

Material choices, their reasons and rejected alternatives. Newest last.

## D1 — Python 3.12 via uv, dependencies pinned by `uv.lock` (Phase 0)

The machine's default Python is 3.14; the plan targets 3.12, so the project pins `.python-version` to 3.12 and uv provides it. Exact versions live in `uv.lock`. Verified on Windows 11 / Python 3.12: `google-re2 1.1.20251105` installs from a wheel and matches; bundled SQLite 3.53.1 has FTS5. The Phase 3 risk "RE2 may not install on Windows" is cleared for this target.

## D2 — Harness-neutral core; first harness chosen from evidence (Phase 0)

Pi, OpenCode and Claude Code are evaluated on equal criteria (`docs/probes/harnesses.md`). No harness is favored for being already configured locally. Core code keys off protocol, not harness.

## D3 — Passthrough is a byte relay independent of normalization (Phase 0)

The passthrough forwards request bytes and streams `aiter_raw()` response bytes unchanged, including content-encoding; it never parses or re-serializes JSON. Normalization (Phase 1+) is a separate path, per "Keep unmodified passthrough independent from normalization."

## D4 — Session routing: `/s/<id>/…` prefix and/or `X-Mnemon-Session` (Phase 0)

The prefix is stripped before forwarding; one route serves both API styles (`/s/<id>/v1` OpenAI base, `/s/<id>` Anthropic base) because both append `/v1/...`. Header-only requests on unprefixed paths are accepted for clients that cannot preserve a path prefix. Missing identity is rejected (`session_required`) even in passthrough, so later archiving phases never inherit unsessioned traffic. Path/header disagreement is rejected (`session_mismatch`).

Identifier grammar: 1–128 chars of `[A-Za-z0-9._-]`, starting alphanumeric, no `..`, no trailing `.`. Rejected alternative: accepting any URL-safe string, which would let traversal-looking IDs into future file and DB keys. The trailing-dot rule exists because Windows strips trailing dots, so `abc.` and `abc` would alias as capture directories. Windows device names (`CON`, `NUL`) remain valid IDs; capture fails open for them, and the archive keys sessions in SQLite, not on the filesystem.

The session segment is parsed from the raw request target, so `/s/a%2Fb/...` is rejected rather than decoded into a different route. `/s/` is reserved: upstream paths under it are unreachable through the proxy.

## D5 — Proxy-originated errors use the endpoint's error shape (Phase 0)

`/v1/messages*` gets Anthropic's `{"type":"error","error":{...}}` with the Mnemon code in the message; everything else gets OpenAI's `{"error":{"message","type","code","param"}}`. Status 400 for identity errors: neither the OpenAI nor the Anthropic SDK retries 400 (to be confirmed against each pinned SDK in `docs/harnesses.md`).

## D6 — Opt-in raw capture as the baseline/fixture pipeline (Phase 0)

`--capture-dir` writes each exchange's exact request/response bytes (credentials redacted) so any harness pointed at the proxy produces replayable fixtures. Request is written on arrival, response on completion or cancellation (marked `complete: false`); writes run off the event loop and the final write is shielded from cancellation. Captures buffer each response in memory: acceptable for an opt-in diagnostic, not for the archive path.

## D7 — First harness: OpenCode 2.1.4 over Chat Completions (Phase 0)

User's choice after the equal comparison in `docs/probes/harnesses.md`. OpenCode sends an exact `x-opencode-session-id` and can route per-session base URLs via its `model.request` plugin hook. Its non-linear defaults (title generation, `subagent` tool) are disabled by config; undo/revert/fork have no switch and fall to Phase 1 divergence rejection. Pi and Claude Code follow in Phase 4B.

## D8 — Contracts are parametric over runtime capacity (Phase 0)

Strata changed `n_ctx` from 32768 to 65536 mid-probe, so contracts state budgets as formulas over values read from `/props` (`input_budget = min(configured, n_ctx − R − M)`), with a startup floor check (`F + min_recent + R + M ≤ n_ctx`) that disables rewriting rather than failing every request. Measured numbers live in `results.md`. At 32K with `R = 8192`, `M = 256` the input budget is 24,320; whether OpenCode's fixed overhead `F` leaves a useful recent window at 32K is measured from live captures, not assumed.

## D9 — The proxy is a raw ASGI application (Phase 0 review)

The Phase 0 protocol review found four fidelity bugs that all came from framework layers between the client and the bytes:

- FastAPI routing returned 405 for `HEAD` and `OPTIONS` and decoded `%2F` into the route.
- httpx `params=` re-encoded the query (`%7e` became `~`, a bare `flag` became `flag=`).
- `client.build_request` injected `accept`, `accept-encoding` and `user-agent`.
- Starlette only watched for disconnect once a `StreamingResponse` started, so a client leaving before upstream headers kept Strata's single slot busy.

`mnemon.api.Proxy` now handles the ASGI scope directly. It works on `raw_path`, `query_string` and the raw header list, builds an `httpx.Request` without client defaults, and runs a disconnect watcher in a task group for the whole relay. uvicorn runs with its own `Server` and `Date` headers off (`mnemon.server`), so the upstream's are relayed once. Paired p95 overhead dropped from 3.1–4.3 ms to 1.9–3.8 ms.

## D10 — Phase 1 lifecycle and storage decisions (user, 2026-10-24)

Resolved from `docs/plans/phase1.md` §Decisions. The user chose items 1–3 and 11 explicitly and accepted the planner's recommendations for the rest.

1. **Divergence:** `409 history_divergence` with `x-should-retry: false`. The message gives the message index and says to start a new session. It includes no content.
2. **Conflicting concurrent request:** `409 session_busy` with `x-should-retry: false`.
3. **Continue-after-partial resend:** accepted as an extension. The flattened text maps back to the archived partial and the acknowledged extent is recorded. The upstream view renders reasoning and text split at that extent.
4. **Resend omitting an incomplete partial:** *Amended twice; current rule in D13.1.*
   - The slice-0 probe showed OpenCode never omits a partial after a *server-side* failure, so the omission was first made divergence.
   - The live run (R9) then showed OpenCode *does* omit a reply interrupted from the *client* side, which bricked the session.
   - D13.1 restores the user's original choice, superseded-partial acceptance, for client-cancelled attempts only.
5. **Leading system message changes** (OpenCode's date and `<env>`): recorded as an immutable context version, an allowed invalidation cause. Edits to user, assistant or tool history remain divergence.
6. **First request with prior turns:** imported with `source=client_import`.
7. **Raw delta format:** v1 (prefix plus suffix) and v2 (prefix, middle and suffix length) are both implemented. Adopt v2 only if it saves ≥ 25% raw bytes on the live replay plus a synthetic 200-turn replay.
8. **Aliases:** stored, hash-derived Crockford base32, at least 6 characters, extended on collision, never reassigned. Blocks are `alias.N`.
9. **Upstream body in Ph1:** the client's verbatim message objects with internal occurrences spliced in. Full re-render from the archive comes in Ph2.
10. **Passthrough:** a global `--passthrough` flag only. In archive mode, `/v1/messages` and `/v1/responses` return `unsupported_feature`.
11. **DB location:** `%LOCALAPPDATA%\mnemon\mnemon.db` (XDG data dir elsewhere), overridable with `--db`, plus a single-process lock file.
12. **Incomplete turn after a crash:** marked abandoned on restart. Then:
    - an identical resend with no committed output gets a new attempt;
    - a Continue shape is accepted (3);
    - anything else gets `409 ambiguous_retry`;
    - there is no automatic resume.
13. **Finish chunk without `[DONE]`:** the finish chunk is held. EOF before `[DONE]` produces an in-stream error event (contracts §3).
14. **Top-level allowlist:** `temperature`, `top_p`, `seed`, `stop`, `presence_penalty`, `frequency_penalty`, `reasoning_effort` and `chat_template_kwargs.enable_thinking` are forwarded and fingerprinted. `developer` role and text-part arrays are rejected until a harness sends them.
15. **Lone surrogates:** stored as WTF-8 with an encoding tag.
16. **Input-commit failure:** `503 archive_unavailable`, `retry-after: 2`, retry allowed because nothing was accepted.
17. **Fingerprint parent:** the full visible message list stands for the visible parent. The parent occurrence ID is stored on the binding.

## D11 — Chat Completions parsing is allowlist-strict (Phase 1 slice 3)

`mnemon.chat` rejects whatever falls outside the declared subset, at every level. Rejection happens before acceptance, so nothing is archived or silently dropped (contracts §3).

- **Unknown keys** are rejected per message role (e.g. `user.name`, `reasoning_content` on a non-assistant message), inside each tool call, inside its `function`, and inside each `tools[i].function` (allowed: name, description, parameters, strict).
- **Content.** System, user and tool messages need string content; only assistant content may be null or absent. A tool message needs a string `tool_call_id`.
- **Types and counts.** An empty `messages` array is `InvalidBody`. `stream` must be a bool and `stream_options` an object. `n` is off the allowlist, so even `n: 1` is rejected.
- **Block order.** Assistant blocks are always reasoning, then text, then tool calls. The envelope keeps the client's key order for verbatim re-emission.
- **Hashing.** `content_sha256` covers role and blocks only, so key order and null-versus-absent content don't change it.
- **Error paths.** For duplicate keys and NaN/Infinity, the error names the path of the first occurrence in document order.

Loosening any of these is a capability change: add a test and a `capabilities.md` row.

## D12 — Tuning from the Phase 1 measurements (R6, R7 → R8)

1. **v2 raw deltas are the default.** They meet D10.7's bar on both required replays: 68.6% smaller on the live chain, 56.3% / 58.0% on 200-request synthetic chains. The saving is the ~11 KB tools array that follows `messages` in OpenCode bodies. Existing v1 rows stay readable: the format is per row.
2. **The stream relay flushes when its read queue drains**, not on a 25 ms age timer, still capped at 16 KiB per batch. On Windows the timer's 15.6 ms granularity made each paced token wait ~34 ms, while a FULL commit takes ~1 ms at p95. Paced tokens now commit and forward individually; bursts coalesce. Commit-before-forward is unchanged. Rejected: shortening the timer, because granularity makes any sub-16 ms age unreliable on Windows.
3. **Consecutive parts of one block in a batch are merged into one segment row**, cutting segment rows ~16× on recorded-shape streams. Under paced decoding each token is still its own batch and segment; that is the price of commit-before-forward and is reported, not hidden.
4. **`put_raw` reuses recently written or verified bodies** (64-entry cache, used only when the row's SHA-256 matches) instead of rebuilding the parent chain per insert.

## D13 — Phase 1 review and live-run fixes

From the independent review (REJECT, 7 confirmed findings) and the live archive run (R9). Every fix has a regression test (`tests/test_review_fixes.py`, `tests/test_transcript.py`, `tests/test_crash_recovery.py`).

1. **Client-cancelled partials may be omitted (R9).** A partial whose attempt ended `cancelled` (client disconnect) may be absent from the resend. It stays archived, is recorded as `partial_superseded`, and alignment continues past it. That includes a later answer sitting where the partial was. Server-failed partials still must be resent flattened (probe rules); omitting one is divergence. A keyless retry may reuse a request whose only output the client cancelled.
2. **Reconciliation reports its alignment.** The ledger addresses archived occurrences through `aligned` (client message → occurrence), not by position, for context versions, partial acknowledgements and upstream splicing.
3. **A complete turn whose delivery never completed may come back flattened.** A crash after the final commit, before forwarding, leaves the client holding a prefix; D10.3's partial rule applies.
4. **Stale retries are history divergence.** A keyless or keyed retry matching an older request is rejected with `409 history_divergence` once other turns follow that request. Previously its answer was appended after the later turns.
5. **An upstream error event is terminal.** Nothing after it, not even `[DONE]` in the same read, is relayed or can mark the turn complete.
6. **Every relay failure after the 200 ends with an error event**, including malformed but valid-JSON chunks. At most 32 events may follow the finish chunk.
7. **The accept transaction is shielded from client cancellation**, so its outcome is always cleaned up. `ledger.interrupt` records a disconnect after any queued terminal write and never adds a second terminal event.
8. **Failure codes.**
   - A non-streaming response that cannot be archived gets `502 upstream_failed`, `x-should-retry: false`.
   - Input-commit failures offer a retry (`503`, `retry-after: 2`) only for transient `sqlite3.OperationalError`.
9. **Encoding.** Generated blocks are tagged WTF-8, since lone `\uD83D` escapes occur in streamed text. The FTS index stores a `?`-replaced copy. The archive upstream request asks for `accept-encoding: identity`.
10. **Migration and capture.**
    - Migration 2 backfills the full-text index from existing blocks.
    - `--capture-dir` requires `--passthrough` instead of being silently ignored in archive mode.

Not changed: an FTS rowid can shift under `VACUUM`. Mnemon never runs `VACUUM`, and `search.rebuild` restores the index if a user does.
