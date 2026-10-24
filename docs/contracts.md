# Contracts

The specification for proxy behavior. Rules are stated over values read at runtime; measured numbers live in `docs/results.md` and probe reports, defaults in `src/mnemon/config.py`. Each clause is **[enforced]** (tested now), **[defined]** (specified; phase noted) or **[pending]** (awaiting named evidence).

Symbols: `n_ctx` upstream context capacity · `R` per-call generation reserve · `M` safety margin · `F` non-evictable input (system, tool schemas, current user input, generation preamble) · `A` request-wide generation allowance · `D` request-wide deadline.

## 1. Upstream facts are read, not assumed

- `n_ctx`, `build_info` and the chat-template hash come from `GET /props` at startup and after every reconnect or upstream 5xx. **[defined, Ph2]**
- A template or build differing from the pinned values (`capabilities.md`) disables rewriting; passthrough continues. **[defined, Ph2]**
- Counting renders the pinned template with the pinned tokenizer; `POST /v1/messages/count_tokens` cross-checks; per-call `usage` reconciles. Persistent drift raises `M` or rejects. **[defined, Ph2]**

## 2. Budgets

Before every upstream call, with `I` the rendered input:

- `I ≤ input_budget`, where `input_budget = min(configured_input_budget, n_ctx − R − M)`.
- `I + R + M ≤ n_ctx`.

The upstream silently clamps oversized output limits, so Mnemon enforces both itself. **[defined, Ph2]**

- **Floor.** If `F + min_recent + R + M > n_ctx` at startup, rewriting is refused with a message naming each term; passthrough continues. **[defined, Ph2]**
- **Per request.** If `F + R + M > n_ctx`, return a structured pre-inference budget error. Never truncate system instructions, tool schemas or current user input. **[defined, Ph2]**
- **Capacity change.** When `n_ctx` changes, budgets are recomputed before the next call; in-flight requests keep the budget they were admitted under. **[defined, Ph2]**

## 3. Protocol preservation

- **Passthrough** relays request and response bytes unchanged. It drops hop-by-hop headers, headers named in `Connection`, and `x-mnemon-*` headers, and adds none of its own. It relays every method (including `HEAD` and `OPTIONS`), the raw query string, repeated response headers, and the upstream's `Date` and `Server`, and streams SSE chunks as they arrive. A client disconnect at any stage (body read, waiting for upstream headers, streaming) closes the upstream request. **[enforced]**
- **Unreachable upstream** (connect or transport failure before response headers) returns `502`, code `upstream_unreachable`, in the endpoint's error shape. In passthrough nothing is archived, so it carries `x-should-retry: true`. **[enforced]**
- **Archive mode** (`--db`, the default) rewrites `POST /v1/chat/completions` only. Other `POST` endpoints get `400 unsupported_feature`; `GET`, `HEAD` and `OPTIONS` pass through. **[enforced]**
- **Rewriting** accepts only requests inside `capabilities.md` (allowlist rules in D11). Anything else is rejected before acceptance with `400`, code `unsupported_feature` and `x-should-retry: false`, and nothing is archived. Fields are never dropped silently. **[enforced]**
- **Upstream EOF** without the endpoint's terminal event (`[DONE]`, `message_stop`) is an upstream failure, never a successful stop. On rewritten streams the finish chunk is held until `[DONE]`, so a stream cut short after it still ends in the error event. In passthrough the client sees the same abrupt close it would see directly. **[enforced]**
- **Error shape.** Proxy-originated errors use the client endpoint's shape: OpenAI `{"error":{message,type,code,param}}`, Anthropic `{"type":"error","error":{type,message}}`. **[enforced]** Upstream errors are re-enveloped only on rewritten routes. **[defined, Ph3]**

## 4. Session identity

- A session comes from the `/s/<id>/` path prefix, the `X-Mnemon-Session` header, or both.
- Disagreement is rejected (`session_mismatch`); absence is rejected (`session_required`).
- IDs are 1–128 characters of `[A-Za-z0-9._-]`, start alphanumeric, and contain no `..` and no trailing `.`. Anything else is `invalid_session_id`, including percent-encoded characters.
- `/s/` is a reserved prefix: `/s/<id>` with no further path routes to the upstream root, and upstream paths beginning with `/s/` are unreachable.

All of the above are **[enforced]**.

- IDs are routing keys, not secrets. The proxy binds to loopback by default; URLs and bodies stay out of operational logs.
- Each harness adapter documents its association strategy in `harnesses.md`. Content hashes are lookup hints only, never identity. **[enforced for OpenCode: one OpenCode session ID is one Mnemon session]**
- **Branches.** Phase 1 allows one serialized branch per session. Divergence, edits and concurrent conflicting requests get defined errors, never silent merges. **[enforced]**
- **Reconciliation** (D10.3–D10.5, `mnemon.transcript`). Each resend is compared position by position with the archived visible history:
  - Client messages match by content hash.
  - Generated turns match semantically: text, reasoning (optional but equal when present), and tool calls with JSON-equal arguments.
  - A changed system message before the first non-system message is a new context version, not a divergence.
  - A flattened partial matches with its acknowledged extent.
  **[enforced]**

## 5. Client timeouts and retries

Per-harness facts (header wait, read-idle, total deadline, retry triggers, behavior after partial streams) live in `harnesses.md` and come from captured fixtures. **[verified for OpenCode 2.1.4: `docs/probes/opencode_faults.md`]**

- **Response headers** for streaming requests go out within `H` (default 10 s) of arrival, even while queued. **[defined, Ph3]**
- **Keepalive.** From the moment headers are sent, while queued, prefilling or recalling, an SSE comment is sent at least every `K` (default 15 s), where `K ≤ min(client read-idle) / 4`. Comments reset the client's idle timer (verified for OpenCode, direct and through the proxy). Keepalives are not progress and do not extend `D`. **[defined, Ph3]**
- **Deadline.** `D` (default 600 s) starts at arrival and covers queueing, inference, recall and delivery. A harness with no total deadline gets the configured `D` (a policy, not a derived value). For non-streaming clients, `D + response margin ≤` the client's read allowance. **[defined, Ph3]**
- **Retry headers** (`x-stainless-retry-count` and the like) are bounded hints only (parsed 0–100, otherwise ignored). They are excluded from fingerprints and never treated as identity. **[enforced]**
- **Rewritten streams** carry `x-should-retry: false` on every streaming 200. Mnemon, not the harness, owns recovery of a stream it accepted. A failure after the stream starts ends with the endpoint's in-stream error event (`upstream_stream_failed`, or `archive_unavailable` when storage fails) before a clean close, never a bare close. This is the only server-side signal that stops OpenCode's continue-after-partial path. **[enforced]**

Proxy-originated statuses, chosen so a harness never retries into a duplicate generation. Statuses and `x-should-retry` behavior were verified against OpenCode 2.1.4 (`docs/probes/opencode_faults.md`).

| Situation | Status, code | Headers | |
| --- | --- | --- | --- |
| Identity | 400 `session_*`, `invalid_session_id` | `x-should-retry: false` | **[enforced]** |
| Unsupported feature or invalid body | 400 `unsupported_feature`, `invalid_body` | `x-should-retry: false` | **[enforced]** |
| Budget | 400 | `x-should-retry: false` | [defined, Ph2] |
| Edited, truncated or forged history (D10.1) | 409 `history_divergence` | `x-should-retry: false` | **[enforced]** |
| Different request while one is active (D10.2) | 409 `session_busy` | `x-should-retry: false` | **[enforced]** |
| Matching request in progress | 409 `request_in_progress` | `x-should-retry: false` | **[enforced]** |
| Matching request already answered (fully or partly), answer absent from resend | 409 `ambiguous_retry` | `x-should-retry: false` | **[enforced]** |
| Idempotency key bound to another request | 409 `idempotency_conflict` | `x-should-retry: false` | **[enforced]** |
| Repeated key for a completed stream | 409 `streaming_replay_unsupported` | `x-should-retry: false` | **[enforced]** until Ph8 |
| Archive cannot commit the input (D10.16) | 503 `archive_unavailable` | `retry-after: 2`, `x-should-retry: true` | **[enforced]** |
| Upstream unreachable or failed before a usable response, after acceptance | 502 `upstream_unreachable` or `upstream_failed` | `x-should-retry: false` | **[enforced]** |
| Upstream non-200 after acceptance | relayed status and body | `x-should-retry: false` | **[enforced]** |
| Upstream unreachable in passthrough | 502 `upstream_unreachable` | `x-should-retry: true` | **[enforced]** |
| Overload (queue full) | 429 | `retry-after` (seconds until a slot is realistically free) | [defined, Ph3] |
| Deadline expired before first byte | 504 | `x-should-retry: false` | [defined, Ph3] |
| Failure after stream start | endpoint's in-stream error event, then close | `x-should-retry: false` (sent with the 200) | **[enforced]** |

## 6. Idempotency and request fingerprints

**[enforced]** (`mnemon.fingerprint`, `mnemon.ledger`)

- **Key.** An optional `Idempotency-Key` header, scoped to (session, branch) and bound atomically to a fingerprint before inference. None of the current harnesses send one.
- **Fingerprint v1.** SHA-256 of canonical JSON over: endpoint, session, branch, `model`, generation settings, `tools`, `tool_choice`, the full visible message list (which stands for the visible parent, D10.17), and every other top-level field not listed as transport-only. The parent occurrence ID is stored on the request row.
  - Transport-only fields: `stream`, `stream_options`, all HTTP headers, the key itself.
  - Canonical form: object keys sorted, arrays in order, strings exact (no Unicode normalization), numbers as parsed (`1` ≠ `1.0`).
- **Delivery mode** (`stream`) is recorded with the binding. The same key with a different mode is a conflict.
- **Same key, different fingerprint** is a conflict. It never returns another request's response.
- **Completed non-streaming match** replays the committed result with no inference.
- **Streaming match** gets the 409 recovery response until Phase 8.
- **Keyless requests** match on (session, visible parent, fingerprint):
  - Outstanding match: in-progress response.
  - Match whose attempts produced no output: a new attempt on the same logical request (no new occurrences).
  - Match that produced output, complete or partial, absent from the resend: `ambiguous_retry` (D10.12).
  - A new identical user occurrence extending a later visible parent is a new occurrence.

## 7. Request-wide generation and time limits

**[defined, Ph3]**

- **Allowance.** `A = min(client limit, configured cap)`.
  - Client limit, OpenAI: `max_completion_tokens`, else `max_tokens`. Anthropic: `max_tokens`.
  - Absent client limit: the cap.
- **Consumption** is upstream `completion_tokens` (includes reasoning and tool-call arguments), summed over all internal calls for one visible response.
- **Each continuation** is capped at `min(A − consumed, n_ctx − I − M)`. Replaying a completed result does not reset consumption.
- **Exhaustion** ends with the endpoint's length stop when the emitted structure can close validly, otherwise the partial-stream error. Never a normal stop, never an incomplete tool call.
- **Deadline expiry** cancels upstream work and returns the timeout error.
- **Reporting.** Visible usage and total internal usage are reported separately.

## 8. Scheduling and slot release

**[defined, Ph3]**

- **Single dispatch.** A bounded FIFO (capacity `Q`) feeds one upstream dispatch at a time.
  - Duplicates and branch conflicts are resolved before a request enqueues.
  - Cancelled or expired entries leave the queue without inference.
  - The upstream's `/status` guards dispatch because other clients share it.
- **Slot ownership.** An active request holds the slot across its internal continuations. It releases the slot on completion, failure, cancellation, or when it returns external tool calls.
- **Background work** starts only when no foreground request is active or queued.
- **Released** means the upstream no longer lists the request as active. The expected bound is under 1 s during decode and one prefill chunk at the measured prefill rate during prefill. Past the hard ceiling (default 60 s), the upstream is marked unhealthy and dispatch stops.

## 9. Reasoning carryover

**[defined, Ph3]**

- The pinned template renders `reasoning_content` for **every** earlier assistant turn, and an empty think block where there is none. Mnemon reconstructs archived reasoning for every rendered assistant turn so upstream input matches what the model saw, whether or not the client resends it.
- A template revision that changes this rule is a pinned-value change (§1), not a runtime branch.
- Reasoning-effort and thinking toggles alter the first system message, so they are full-prefix invalidation causes.

## 10. Cache accounting

**[defined, Ph2]**

- Every pair of consecutive upstream calls records the token longest common prefix (LCP), the cached tokens reported by the upstream, and the invalidation cause.
- **Allowed causes:** watermark move, state commit, catalog navigation, recall-buffer eviction, summary activation, system or tool change, effort or thinking change, branch, model or template change.
- **Reuse is checkpoint-based.** The upstream resumes from its last checkpoint at or before the first changed token. Reported reuse below the LCP is expected and recorded as checkpoint-limited, not unexplained.
- Restart and eviction reduce reuse without any input change.
- Latency-derived estimates are labeled as estimates.

## 11. Durability and isolation

**[enforced]** except recall provenance (Ph3). Process-crash recovery is tested at three crash points (`tests/test_crash_recovery.py`). Power-loss durability is not claimed until separately tested (Ph8).

- SQLite runs with `journal_mode=WAL` and `synchronous=FULL`, both read back on every connection. `NORMAL` is an explicit, reported option and never carries the power-loss claim.
- **Commit order.**
  - Accepted input and branch assignment commit before inference.
  - Each bounded output batch commits, with its transcript mapping, before it is forwarded.
  - Turn-completion markers are separate, so a crash leaves an explicit incomplete turn.
- No write transaction is held across inference. Blocking database work runs off the event loop.
- Archive rows are immutable, enforced by database triggers on any connection: UPDATE and DELETE abort, and unique-key insert guards block `INSERT OR REPLACE`. Store connections also deny DDL. User-invoked deletion (Ph8) is the only exception. Derived tables (`branch_heads`, `fts_blocks`) are mutable and rebuildable.
- An interrupted attempt is marked abandoned on restart, or on the next request when its terminal event could not be written. It is never resumed automatically.
- Recall preserves role and provenance. Historical tool output is never promoted to system authority.

## 12. Capture

**[enforced]**

- Raw exchange capture writes only when `--capture-dir` is set.
- Credentials are redacted: `authorization`, `proxy-authorization`, `x-api-key`, `api-key`, `cookie`.
- Exchanges cut short by disconnect are recorded as `complete: false`.
- Capture fails open: a write error is logged and the relay continues unchanged.
