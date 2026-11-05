# Contracts

The specification for proxy behavior. Rules are stated over values read at runtime; measured numbers live in `docs/results/` and probe reports, defaults in `src/palimnesis/config.py`. Each clause is **[enforced]** (tested now), **[defined]** (specified; phase noted) or **[pending]** (awaiting named evidence).

Symbols: `n_ctx` upstream context capacity · `R` per-call generation reserve · `M` safety margin · `F` non-evictable input (system, tool schemas, current user input, generation preamble) · `A` request-wide generation allowance · `D` request-wide deadline.

## 1. Upstream facts are read, not assumed

- `n_ctx`, `build_info` and the chat-template hash come from the upstream profile's facts reader (Strata: `GET /props`). They are read at startup and again after any transport error, 5xx, or context-window 400. **[enforced]**
- **Pin mismatch.** A template, build or `count_tokens` canary that differs from the pinned profile disables bounded views. The proxy still archives and forwards, as in Phase 1 (D14.9). A build matches when it is the pin's own or one the pin lists as verified equivalent, with its evidence (D76). **[enforced]**
- **Core is backend-neutral.** Backend specifics live behind `palimnesis.upstreams.profile` (D21). Core modules never import a backend, which an AST boundary test enforces. **[enforced]**
- Counting renders the pinned template with the pinned tokenizer, as Strata 0.1.48 encodes: without the tokenizer's NFC normalizer (D47), with added-token strings inside messages counted as text (D46), and with no tool schemas when `tool_choice` is `"none"` (D50). It is cross-checked at startup by a `count_tokens` canary. Every call's `usage.prompt_tokens` is reconciled with the local count. Drift raises `M` (D22.4); persistent or large drift disables bounded views. **[enforced]**

## 2. Budgets

Before every upstream call, with `I` the rendered input:

- `I ≤ input_budget`, where `input_budget = min(configured_input_budget, n_ctx − R − M)`.
- `I + R + M ≤ n_ctx`.

The upstream silently clamps oversized output limits, so Palimnesis enforces both itself. The upstream output limit is set to the reserve whenever the client's limit is absent or larger (D14.11). **[enforced]**

- **Floor.** If `F + min_recent + S + R + M > n_ctx` at startup (S the working-notes slot, 0 when notes are off; R42), or after an `n_ctx` change, bounded views are refused with a message naming each term. Archiving and forwarding continue. **[enforced]**
- **Build failure.** If the view build fails for any reason other than a budget error, the request is forwarded with the client's full history, unbounded, and the proxy logs `bounded view build failed; forwarding unbounded` (D14.9). This is the one case where `I ≤ input_budget` is not enforced; the upstream's own `n_ctx` check still applies. **[enforced]**
- **Per request.** If the non-evictable input cannot fit, return `400 context_budget_exceeded` (`x-should-retry: false`) before acceptance, so nothing is archived. Never truncate system instructions, tool schemas or current user input. **[enforced]**
- **Capacity change.** When `n_ctx` changes, budgets are recomputed before the next call; in-flight requests keep the budget they were admitted under. **[enforced]**
- **Recall excerpts** (A1, D20).
  - **Caps.** A per-message cap `min(2048, 4%·B_in)` and an active-view total `min(4096, 10%·B_in)`.
  - **Effective total.** `min(Q, max(0, B_in − P − F − min_recent))`. It falls to zero before fixed input or the minimum recent window would give way.
  - **Never squeezes anything else.** Excerpts never count in F, never consume R or M, never move the watermark, and never cause a budget error.
  - **Catalog slot.** P is 0 until Phase 3B.
  - **Retrieval r2** (D71, `serve --retrieval r2`; `serve`'s default since D78) never quotes reasoning blocks; r1 (`--retrieval r1`) may.

  **[enforced]**
- **Bounded view** (`palimnesis.view.builder`, D14).
  - The view is the full history until it would exceed `H = F + 0.9·C`. Then it masks oldest-first to `T = F + 0.5·C`, at group boundaries only, and `I ≤ B_in` always holds.
  - Watermark and collapse boundaries are monotone and persisted in immutable `view_versions`, so a rebuild reproduces the same tokens.
  - The builder makes no upstream calls.
  - **Pinned instructions** (D65, `serve --pin-instructions TOKENS`; off by default).
    - A collapse move keeps behind its boundary every user instruction of at most 1,024 tokens, verbatim and in place. It keeps them newest first, while their total fits `min(pin_tokens, B_in / 6)`, and absorbs the rest.
    - Pins change only with a collapse move, and an absorbed message never returns.
    - When the view would otherwise exceed `B_in`, the collapse absorbs pins too.
  - **The current turn last** (D70, `serve --protect-turn`; on by default since D78, off with `--no-protect-turn`).
    - A collapse reaches only up to the current turn, which starts at the latest genuine instruction.
    - If the view still exceeds `T`, the turn's own largest tool results and reasoning are stubbed in place, never the newest group's.
    - The turn's own groups are collapsed, oldest first to `T`, only when the view still exceeds `H`.
  - **Working notes** (D72, `serve --notes TOKENS`; 2,048 by default since D78, off with `--notes 0`).
    - The notes slot S is reserved out of the maskable capacity, and the oversized and last-resort steps leave it free. The block's tokens never count toward `H` or `T`.
    - Admission counts S with the fixed input and the history's span residue, so a request that cannot fit once the notes are rendered is refused before acceptance (R42).
    - A move that advances the collapse boundary first sends one internal call upstream: the request as it rendered before the move, plus the notes prompt, within `B_in`. If that would exceed `B_in`, unmasked results and reasoning are stubbed newest first, the newest group's included, for this call only. The client sees nothing of it. Its upstream failures mark the facts stale as the client's own calls do (§1).
    - Its text, cut to fit S, becomes the next immutable notes version. It is rendered as one user-role block right after the leading system message once anything is collapsed.
    - A failed call keeps the notes the view had, and is recorded with its reason:
      - an HTTP status or a transport error;
      - the 180 s timeout;
      - an error event, a stream that ends without `[DONE]`, or an event the parser rejects, valid JSON of the wrong shape included (`malformed`);
      - a tool call, or no text (except as n2 allows below);
      - nothing fitting the slot, not even the block's header (`too_long`);
      - a refresh that cannot fit `B_in` even with every unmasked result stubbed: no call is sent (`over_budget`, R42).
    - A notes defect never fails the request.
    - **Format n2** (D74, `--notes-format n2`; the default since D78, n1 with `--notes-format n1`):
      - The prompt asks for the current step second, and for at most about 0.3 words per slot token, rounded to 100 and at least 100, as the reply.
      - Notes longer than S keep every section's heading and the same number k ≥ 1 of first non-blank lines in each section, the most that fits. Text before the first heading counts as a section without a heading. Text without section headings, or where not even one line per section fits, is cut at a line as in n1.
      - A heading is a line holding only a section's name (or its short key, such as *Current step*), in any case, optionally after Markdown heading marks, a number or bold, and before a parenthetical and a colon. Bullets and sentences are not headings.
      - A reply with no text is committed from its reasoning when the reasoning holds a draft of the notes: a run of headings in which at least three distinct sections have a line under them. A draft ends where a section repeats; the last such draft is taken, from its first heading to the end. It is recorded with reason `from_reasoning`. Reasoning never rescues a failed stream.
      - An unknown format is refused at startup.
      - The view's `policy_version` ends `+notes{S}n2`.
    - **Header h2** (D75, `--notes-header h2`; the default since D78, h1 with `--notes-header h1`): the block's header ends "the user's messages win. When you quote a value from these notes, write it out in full, exactly as recorded". Fitting to S counts the header in use. An unknown header is refused at startup. `policy_version` adds `h2` after the format (`+notes{S}h2`, `+notes{S}n2h2`).
    - The builder itself makes no upstream calls.

  **[enforced]**

## 3. Protocol preservation

- **Passthrough** relays request and response bytes unchanged. It drops hop-by-hop headers, headers named in `Connection`, and `x-palimnesis-*` headers, and adds none of its own. It relays every method (including `HEAD` and `OPTIONS`), the raw query string, repeated response headers, and the upstream's `Date` and `Server`, and streams SSE chunks as they arrive. A client disconnect at any stage (body read, waiting for upstream headers, streaming) closes the upstream request. **[enforced]**
- **Unreachable upstream** (connect or transport failure before response headers) returns `502`, code `upstream_unreachable`, in the endpoint's error shape. In passthrough nothing is archived, so it carries `x-should-retry: true`. **[enforced]**
- **Archive mode** (`--db`, the default) rewrites `POST` only on an endpoint that has a client protocol (`palimnesis.protocols`, chosen by path, never by harness or `User-Agent`): `/v1/chat/completions` and `/v1/messages` (§16). `POST /v1/messages/count_tokens` is relayed unarchived (O-4B-10). Other `POST` endpoints get `400 unsupported_feature`; `GET`, `HEAD` and `OPTIONS` pass through. The upstream call is always Chat Completions, whatever the client protocol, and the client's query string reaches it only when the client spoke Chat. On `/v1/messages` the only query accepted is `beta=true` (Claude Code and Pi join it); any other is `400 unsupported_feature` before acceptance. **[enforced]**
- **Rewriting** accepts only requests inside `capabilities.md` (allowlist rules in D11). Anything else is rejected before acceptance with `400`, code `unsupported_feature` and `x-should-retry: false`, and nothing is archived. Fields are never dropped silently. **[enforced]**
- **Reserved names.** Tool names starting `palimnesis_` belong to Palimnesis (Phase 3B). A client tool, or a tool call in the client's history, with such a name is rejected before acceptance with `400 unsupported_feature`. **[enforced]**
- **Upstream EOF** without the endpoint's terminal event (`[DONE]`, `message_stop`) is an upstream failure, never a successful stop. On rewritten streams the finish chunk is held until `[DONE]`, so a stream cut short after it still ends in the error event. In passthrough the client sees the same abrupt close it would see directly. **[enforced]**
- **Error shape.** Proxy-originated errors use the client endpoint's shape: OpenAI `{"error":{message,type,code,param}}`, Anthropic `{"type":"error","error":{type,message}}`. **[enforced]** Upstream non-200 responses after acceptance keep their status. Chat clients get the upstream's body unchanged; Messages clients get it in Anthropic's envelope, `{"type":"error","error":{type, message}}`, with the upstream's message verbatim and its type kept when it is one of Anthropic's, else the status's (`400` → `invalid_request_error`, `429` → `rate_limit_error`, others `api_error`). **[enforced]**

## 4. Session identity

- A session comes from the `/s/<id>/` path prefix, the `X-Palimnesis-Session` header, or both.
- Disagreement is rejected (`session_mismatch`); absence is rejected (`session_required`).
- IDs are 1–128 characters of `[A-Za-z0-9._-]`, start alphanumeric, and contain no `..` and no trailing `.`. Anything else is `invalid_session_id`, including percent-encoded characters.
- `/s/` is a reserved prefix: `/s/<id>` with no further path routes to the upstream root, and upstream paths beginning with `/s/` are unreachable.

All of the above are **[enforced]**.

- IDs are routing keys, not secrets. The proxy binds to loopback by default; URLs and bodies stay out of operational logs.
- Each harness adapter documents its association strategy in `harnesses.md`. Content hashes are lookup hints only, never identity. **[enforced for OpenCode: one OpenCode session ID is one Palimnesis session]**
- **One protocol per session.** A session's first request fixes its client protocol. A request on another protocol's endpoint gets `400 session_protocol_mismatch` before acceptance. **[enforced]**
- **Branches.** Phase 1 allows one serialized branch per session. Divergence, edits and concurrent conflicting requests get defined errors, never silent merges. **[enforced]**
- **Reconciliation** (D10.3–D10.5, `palimnesis.archive.transcript`). Each resend is compared position by position with the archived visible history:
  - Client messages match by content hash.
  - Generated turns match semantically: text, reasoning (optional but equal when present), and tool calls with JSON-equal arguments. Booleans never equal numbers. Any arguments also match the client's `{}`, OpenCode's resend of a call it did not run: arguments that never parsed (D68), or a call interrupted while it ran (D73). An edit that blanks arguments to `{}` is therefore not detected; the archive keeps the generated arguments.
  - A changed system message before the first non-system message is a new context version, not a divergence.
  - A flattened partial matches with its acknowledged extent, and so does a complete turn whose delivery never completed.
  - An incomplete partial may be omitted, whether the client cancelled it or saw it fail; it stays archived and is superseded (D13.1, extended by O-4B-5: Pi leaves every failed partial out, D91). So may a turn the length stop cut short, which Pi drops the same way (D94). Any other complete turn may not be omitted.
  **[enforced]**

## 5. Client timeouts and retries

Per-harness facts (header wait, read-idle, total deadline, retry triggers, behavior after partial streams) live in `harnesses.md` and come from captured fixtures. **[verified for OpenCode 2.1.4: `docs/probes/opencode_faults.md`]**

- **Response headers** for streaming requests go out within `H` (default 10 s) of arrival, even while queued or while the notes refresh runs (`palimnesis.admission.StreamGate`). An error after the proxy sent them early becomes the protocol's in-stream error event. **[enforced]** (O4)
- **Keepalive.** From the moment headers are sent, while queued, prefilling or recalling, the client protocol's keepalive goes out whenever `K` (default 15 s) passes with nothing sent: an SSE comment on Chat, `event: ping` on Messages. `K ≤ min(client read-idle) / 4`: OpenCode, Claude Code (HC5) and Pi (HP4) reset their idle timers on either, and Claude Code and Pi kill a stream after 300 s of silence. Keepalives are not progress and do not extend `D`. **[enforced]** (O4; Strata itself sends comments every 10 s during its own queueing and prefill, `docs/probes/strata.md` §10)
- **Deadline.** `D` (default 600 s) starts at arrival and covers queueing, inference, recall and delivery. A harness with no total deadline gets the configured `D` (a policy, not a derived value). For non-streaming clients, `D + response margin ≤` the client's read allowance. At `D` after acceptance the upstream response is closed, releasing its slot, and the attempt is recorded as failed (`deadline_exceeded`). A client that stopped reading cannot hold the upstream past `D`. Time in the proxy's queue counts against `D`; an entry that expires there is never dispatched. **[enforced]**
- **Retry headers** (`x-stainless-retry-count` and the like) are bounded hints only (parsed 0–100, otherwise ignored). They are excluded from fingerprints and never treated as identity. **[enforced]**
- **Rewritten streams** carry `x-should-retry: false` on every streaming 200. Palimnesis, not the harness, owns recovery of a stream it accepted. A failure after the stream starts ends with the endpoint's in-stream error event (`upstream_stream_failed`, or `archive_unavailable` when storage fails) before a clean close, never a bare close. This is the only server-side signal that stops OpenCode's continue-after-partial path. **[enforced]**

Proxy-originated statuses, chosen so a harness never retries into a duplicate generation. Statuses and `x-should-retry` behavior were verified against OpenCode 2.1.4 (`docs/probes/opencode_faults.md`).

| Situation | Status, code | Headers | |
| --- | --- | --- | --- |
| Identity | 400 `session_*`, `invalid_session_id` | `x-should-retry: false` | **[enforced]** |
| Unsupported feature or invalid body | 400 `unsupported_feature`, `invalid_body` | `x-should-retry: false` | **[enforced]** |
| Budget | 400 `context_budget_exceeded` | `x-should-retry: false` | **[enforced]** |
| Edited, truncated or forged history (D10.1) | 409 `history_divergence` | `x-should-retry: false` | **[enforced]** |
| Different request while one is active (D10.2) | 409 `session_busy` | `x-should-retry: false` | **[enforced]** |
| Matching request in progress | 409 `request_in_progress` | `x-should-retry: false` | **[enforced]** |
| Matching request already answered (fully or partly), answer absent from resend | 409 `ambiguous_retry` | `x-should-retry: false` | **[enforced]** |
| Idempotency key bound to another request | 409 `idempotency_conflict` | `x-should-retry: false` | **[enforced]** |
| Repeated key for a completed stream | 409 `streaming_replay_unsupported` | `x-should-retry: false` | **[enforced]** until Ph8 |
| Archive cannot commit the input (D10.16) | 503 `archive_unavailable` | `retry-after: 2`, `x-should-retry: true` | **[enforced]** |
| Upstream unreachable or failed before a usable response, after acceptance | 502 `upstream_unreachable` or `upstream_failed` | `x-should-retry: false` | **[enforced]** |
| Upstream non-200 after acceptance | relayed status; body relayed (Chat) or re-enveloped (Messages, §3) | `x-should-retry: false` | **[enforced]** |
| Upstream unreachable in passthrough | 502 `upstream_unreachable` | `x-should-retry: true` | **[enforced]** |
| Overload (queue full) | 429 `queue_full`, before acceptance (nothing archived) | `retry-after` (default 15 s), `x-should-retry: true` | **[enforced]** (O4) |
| Deadline expired before first byte | 504 `deadline_exceeded` | `x-should-retry: false` | **[enforced]** |
| Deadline expired after the stream started | in-stream `deadline_exceeded` event, then close | `x-should-retry: false` (sent with the 200) | **[enforced]** |
| Failure after stream start | endpoint's in-stream error event (Chat `data: {"error":…}`; Messages one `event: error`, never `message_stop`), then close | `x-should-retry: false` (sent with the 200) | **[enforced]** |

## 6. Idempotency and request fingerprints

**[enforced]** (`palimnesis.archive.fingerprint`, `palimnesis.archive.ledger`)

- **Key.** An optional `Idempotency-Key` header, scoped to (session, branch) and bound atomically to a fingerprint before inference. None of the current harnesses send one.
- **Fingerprint v1.** SHA-256 of canonical JSON over: endpoint, session, branch, `model`, generation settings, `tools`, `tool_choice`, the full visible message list (which stands for the visible parent, D10.17), and every other top-level field not listed as transport-only. The parent occurrence ID is stored on the request row.
  - Transport-only fields: the client protocol's (Chat: `stream`, `stream_options`), all HTTP headers, the key itself.
  - The endpoint is the client protocol's, and it is stored on the request row, so a restart re-parses the archived body with the same protocol.
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

A visible response is one upstream call, or several when hidden recall tools answer the model's `palimnesis_*` calls in between (Phase 3B, §15). **[enforced]**

- **Allowance.** `A = min(client limit, 24,576)`.
  - Client limit, OpenAI: `max_completion_tokens`, else `max_tokens`; Strata gives `max_completion_tokens` precedence the same way (probe p16). Anthropic: `max_tokens`.
  - Absent client limit: the cap.
- **Consumption** is upstream `completion_tokens` (includes reasoning and tool-call arguments), summed over all calls of one visible response. A later call never resets it.
- **Each continuation** is capped at `min(A − consumed, R)`, and starts only with at least 1,024 tokens left: below that Strata gives thinking no budget and the call can end mid-reasoning (`docs/probes/strata.md` §12.2). Its input is bounded again (§2).
- **Exhaustion.** Too little allowance for a continuation, or a limit of §15 reached, ends the response with the length stop. Every hidden call made by then has a result in the archive, so later renders never hold a call without one. OpenCode answers a length stop with a follow-up turn of its own (`harnesses.md`).
- **Deadline expiry** cancels upstream work and returns the timeout error (§5); `D` covers every call of the response.
- **Reporting.** The client's usage reports the last call's prompt and the summed completion tokens. Each call's own usage is in its `upstream_call` event.
  - Messages clients get it in Anthropic's terms (§16): `input_tokens` = prompt − cached, `cache_read_input_tokens` = cached, `cache_creation_input_tokens` = 0, `output_tokens` = the summed completion. Input plus cache read equals the bounded view's prompt.

## 8. Scheduling and slot release

**[enforced]** (O4, `palimnesis.admission`, D89) in archive mode; passthrough relays without admission.

- **Dispatch.** A bounded FIFO (capacity `Q`, default 8) feeds the upstream's slots: `total_slots` from `/props`, one on pythia (D83). A request reserves its place before acceptance, so a full queue is a 429 with nothing archived, and waits for its slot after acceptance.
  - Duplicates and branch conflicts are resolved in acceptance, before a request waits.
  - Cancelled or expired entries leave the queue without inference.
  - With one slot, the upstream's `/status` guards dispatch, because other clients share it: dispatch waits while it shows work running or queued. An upstream without the route never holds dispatch back.
- **Slot ownership.** An active request holds the slot across all its upstream calls: the notes refresh, hidden continuations and the answer. It releases the slot on completion, failure, cancellation, or when it returns external tool calls.
- **Background work.** Non-inference background work (transcript projection, stub warm-up) runs off the request path and never uses the upstream slot (D35, D25). Background inference, when a later phase adds it, starts only when no foreground request is active or queued. **[enforced for non-inference work]**
- **Released** means the upstream no longer lists the request as active; the `/status` guard waits for it. The expected bound is under 1 s during decode and one prefill chunk at the measured prefill rate during prefill. **[defined]** Past a hard ceiling (default 60 s) the upstream would be marked unhealthy and dispatch stop; until that lands, the guard waits within each request's `D`.

## 9. Reasoning carryover

**[enforced for ordinary turns]**: archived reasoning is restored when the client omits it. The parts specific to hidden proxy continuations move to optional Phase 3B (A1).

- The pinned template renders `reasoning_content` for **every** earlier assistant turn, and an empty think block where there is none. Palimnesis reconstructs archived reasoning for every rendered assistant turn so upstream input matches what the model saw, whether or not the client resends it.
- **Except turns the upstream renders as nothing.** Strata drops a completed assistant turn with no text, image or tool calls, reasoning included (#843); the final message always renders. A profile declares this as `TemplateRules.drops_empty_assistant`. Counting, layouts, the view's recent window and masking all treat such a turn as zero tokens: it is never stubbed and never reported as evicted (D41, D42). The `count_tokens` canary includes one, so a server that renders them fails the pin check. **[enforced]**
- **Transcript-search steps are ordinary tool steps.** The model's grep and read calls on transcript files are harness tool calls, archived and restored like any other (A1 GL10; `tests/test_transcript_loop_http.py`). **[enforced]**
- A template revision that changes this rule is a pinned-value change (§1), not a runtime branch.
- Reasoning-effort and thinking toggles alter the first system message, so they are full-prefix invalidation causes.

## 10. Cache accounting

**[enforced]** (`palimnesis.view.cacheacct`, D22)

- Every pair of consecutive upstream calls records the token longest common prefix (LCP), the cached tokens reported by the upstream, and the invalidation cause.
- **Allowed causes:** append, watermark move, collapse, oversized output, excerpt included, excerpt omitted, system change (context version), tool change, effort or thinking change, capacity/budget change, view policy/format version change, model or template change. A call inside one visible response that extends the call before it is `internal_continuation` (§15). These are recorded as `append`, `internal_continuation`, `watermark_move`, `collapse`, `oversized_output`, `excerpt_included`, `excerpt_omitted`, `system_change`, `tool_change`, `effort_change`, `capacity_budget_change`, `view_format_change` and `model_template_change`, plus `first_call` and `view_disabled` (bounded views off; no LCP is recorded). With working notes (D72), the internal refresh call `<attempt>#notes` is `state_refresh` when it extends the call before it; one that changes earlier tokens (the addendum it is first to carry, or a result it stubbed to fit `B_in`) is analysed like any other call (R42), and a view whose first change is its notes block is `state_commit`. A call that is its own refresh call without the notes prompt is `state_refresh` too: the move hid nothing visible (protect-turn kept the whole current turn), so no notes block renders (D93). The transcript addendum (D36) is part of the presentation format: its appearance, change or removal is `view_format_change`. It is fixed per session and names a session directory whose path never changes, so it is byte-stable from one call to the next. A change between `tool_choice: "none"` and other values changes whether tool schemas render, so it is `tool_change` (D50). A call's identity includes the counter revision, so a pair whose earlier call was counted by another revision, and cannot be re-rendered to its recorded count, is `model_template_change` (D46). State commits, catalog navigation, summary activation and branches join the list when their phases exist. Anything else is `unexplained`, and `eval/replay.py --explain` fails on it.
- **Reuse is checkpoint-based.** The upstream resumes from its last checkpoint at or before the first changed token. Reported reuse below the LCP is expected and recorded as checkpoint-limited, not unexplained.
- Restart and eviction reduce reuse without any input change. The class `restart_or_eviction` means only "below the checkpoint estimate": it also covers Strata no longer holding a checkpoint the model assumed, with no restart (D50).
- Latency-derived estimates are labeled as estimates.

## 11. Durability and isolation

**[enforced]** Process-crash recovery is tested at three crash points (`tests/test_crash_recovery.py`). Power-loss durability is not claimed until separately tested (Ph8).

- SQLite runs with `journal_mode=WAL` and `synchronous=FULL`, both read back on every connection. `NORMAL` is an explicit, reported option and never carries the power-loss claim.
- **Commit order.**
  - Accepted input and branch assignment commit before inference.
  - Each bounded output batch commits, with its transcript mapping, before it is forwarded.
  - Turn-completion markers are separate, so a crash leaves an explicit incomplete turn.
- No write transaction is held across inference. Blocking database work runs off the event loop.
- Archive rows are immutable, enforced by database triggers on any connection: UPDATE and DELETE abort, and unique-key insert guards block `INSERT OR REPLACE`. Store connections also deny DDL. User-invoked deletion (Ph8) is the only exception. Derived tables (`branch_heads`, `fts_blocks`) are mutable and rebuildable.
- An interrupted attempt is marked abandoned on restart, or on the next request when its terminal event could not be written. It is never resumed automatically.
- Recall preserves role and provenance. Historical tool output is never promoted to system authority.
- **Excerpt blocks** (A1).
  - **Storage.** Blocks are immutable rows (`excerpt_blocks`, `excerpt_items`), one per genuine user instruction. Each is committed with its selection before inference, and retries and restarts reuse the stored rendering.
  - **Placement.** They appear only in the upstream copy of their host user message, never in the archive's copy of that message, the client response, the full-text index, or a system message.
  - **Delimiters.** Payloads are escaped so they cannot close a block or contain special tokens.
  - **Deletion** (Ph8) must cascade to these tables.

  **[enforced]**

## 12. Capture

**[enforced]**

- Raw exchange capture writes only when `--capture-dir` is set, and only in `--passthrough` mode. Archive mode refuses the flag because it stores exact request bodies itself.
- Credentials are redacted: `authorization`, `proxy-authorization`, `x-api-key`, `api-key`, `cookie`.
- Exchanges cut short by disconnect are recorded as `complete: false`.
- Capture fails open: a write error is logged and the relay continues unchanged.
- Each exchange's `request.json` and `response.json` appear whole (written under a temporary name, then renamed) and only after their body file, so the capture directory can be read while the proxy is still writing.

## 13. Proactive recall

- **Host.** Excerpts are selected once per genuine new user instruction: the request's last new client message, a user message that is not a harness-synthetic prompt. Tool-result requests and context-version-only changes never host. A retry hosts only when its instruction has no stored selection (D31). **[enforced]**
- **Candidates.** Only blocks the base view no longer shows, older than the instruction; never system messages, text verbatim in the view, ranges already quoted by an included block, or excerpt text (D26). An unmasked session searches nothing and its upstream body stays byte-identical. **[enforced]**
- **Query.** Built by the frozen policy q1 from the instruction's own text; user text never reaches FTS5 as syntax (D28). **[enforced]**
- **Selection.** Retrieval r1 (D29, D38): ranking decides which items survive, the block renders chronologically, and its exact token charge never exceeds the allocation. A source that exceeds it selects nothing (`over_allocation`). Lone surrogates are quoted as U+FFFD. **[enforced]**
- **Persistence.** The selection, its versions (query, retrieval, renderer), archive cutoff, base view, source ranges with the SHA-256 of each excerpt, the frozen rendering, its charge, and the reason when empty are committed before inference. Requests and restarts reuse them. A source failure writes nothing and the request proceeds without excerpts. **[enforced]**
- **Latency.** Selection p95 ≤ 50 ms with 1M archived tokens in the session (`eval/bench_recall.py`; R18). **[defined]**

## 14. Transcript projection

- **What it is.** Per session, a derived transcript directory (D32) in format t1 (D33). It is a rebuildable projection of the archive, not part of it.
- **Exactness.** Every archived block appears once, verbatim after reversible escaping or as a linked exact-bytes file, verified by SHA-256. `palimnesis transcripts verify` checks the directory against the archive; `palimnesis transcripts rebuild` reproduces it byte for byte without inference. **[enforced]**
- **Consistency.** Publication follows D34 as amended by D63: `index.md` never names an incomplete file, every file `manifest.json` lists is write-once and matches it after a crash at any step, and the in-progress turn keeps its final name `turn-NNNN.md` (named `live` in the manifest) while it grows. Incomplete turns are marked in progress, cancelled, abandoned, failed or superseded. Turn 0's index line says it is the system prompt. **[enforced]**
- **Hidden results** (§15) appear in their turn as internal tool results, flagged `internal`. **[enforced]**
- **Isolation.** Projection runs off the request path, holds no write lock, makes no upstream call, and logs only counts and directory hashes. **[enforced]**
- **Access.** Files are 0700/0600 on POSIX and inherit the root's ACL on Windows. Harness permission rules do not confine them (D37.4). **[enforced on POSIX; Windows inherits]**
- **Harness access (the transcript gate).** OpenCode 2.1.4: passed (D37). Pi 1.5.0: passed live through the proxy; Pi has no permission system, and its `grep` reached the session directory the a3 addendum names with no prompt (R43, D93). Pi's default tools are `read`, `bash`, `edit` and `write`; `grep`, `find` and `ls` must be enabled for the addendum's recipe (`--tools` or `defaultTools`).
- **Deletion** (Ph8) must cascade to the projection.

## 15. Hidden recall tools (Phase 3B)

**[enforced]** when `--hidden-tools t1|t2` is set; off by default.

- **Offered.** The tools `palimnesis_recall`, `palimnesis_catalog` and `palimnesis_grep` are appended after the client's tools from a session's first masked view, fixed per session like the addendum (D54), and counted as fixed input before acceptance. Never with `tool_choice: "none"`, and only on streaming requests (D55).
- **Hidden.** A call whose name has the reserved prefix (§3) is never forwarded to the client. The proxy answers it from the archive (`palimnesis.recall.tools`, D57–D59) and calls the upstream again with the call and its result appended. Text and reasoning stream as they arrive; external calls stream renumbered densely; the client sees one message with one id, one finish chunk and one `[DONE]` (D52).
- **Mixed.** When a call carries hidden and external tool calls, the hidden ones are answered and archived, the external ones go to the client with `finish_reason: "tool_calls"`, and the next request renders all results after that call (D53).
- **Limits per response.** At most 4 continuations and 8 hidden calls; results take at most a quarter of the input budget, 2,048 tokens per recall and 1,024 per search or catalog page. A call beyond a limit gets a short "limit reached" result; a further hidden call ends the response with the length stop (§7).
- **Limit per instruction** (D67). At most 16 answered hidden calls from the latest user instruction, counted across responses. Synthetic prompts, including OpenCode's length follow-up, are not instructions. A call beyond it gets "limit reached: no more archive lookups until the next user message. Continue from what you have.", and is refused like a per-response limit.
- **Grep** never searches reasoning blocks (D66); recall still returns them by address.
- **Archive.** Each upstream call is its own generation; results are internal rows (`view='internal'`), never full-text indexed and never excerpted. The client's resend of the one visible message reconciles against the composite of those parts (D51); the upstream sees every part and result in order.
- **Results** are exact by address and range, never another record's content (contracts §11 provenance), and never exceed their cap under the pinned counter.

## 16. Client protocols (Phase 4B)

**[enforced]** (`palimnesis.protocols.messages`, `messages_emit`; route S4). Upstream non-200 responses are re-enveloped (§3).

- **One upstream dialect.** A client protocol parses the client's body into the neutral, Chat-shaped request; the upstream call is always Chat Completions (position 2, D83). The archive stores the client's raw body; `ChatRequest.chat_body` is the neutral Chat body.
- **Allowlist.** Every Messages field is mapped, accepted with no upstream effect, or rejected before acceptance with `400 unsupported_feature`, as for Chat (§3).
- **Mapping** (copies Strata 0.1.54's own Messages route, so the neutral body renders the same tokens: `docs/probes/strata.md` §13.2, D82, D84):

| Messages | Neutral Chat |
|---|---|
| `system` (string or text blocks) | One leading `system` message, blocks joined with `""`; a leading Claude Code billing stamp has `cch=` and the 4th `cc_version` part pinned to `f`s |
| User text blocks | One `user` message, joined with `""`, after the message's tool results |
| `tool_result` (string or text blocks, `is_error`) | A `tool` message per result, in order; text blocks joined with `""`; `is_error` not rendered |
| Assistant `thinking` / `text` / `tool_use` | `reasoning_content` / `content` (null when no text) / `tool_calls`; arguments are the input as compact JSON in the client's key order |
| `role: system`, anywhere | `system`, in place. Strata's Chat route renders one after the first position as `user`, as its Messages route does (O-4B-12), and the counter does the same (D86). It is fixed input and never a user instruction. |
| `tools[]` (`name`, `description`, `input_schema`) | Function tools; a missing `description` is `""` |
| `tool_choice` `auto` / `none` | `"auto"` / `"none"` |
| `thinking.type: disabled` | `reasoning_effort: "none"` (wins over an effort) |
| `output_config.effort` | `reasoning_effort` (`max` → `xhigh`) |
| `thinking.budget_tokens` (no effort given) | `reasoning_effort`: under 2,048 `low`, under 8,192 `medium`, else `xhigh` |
| `max_tokens`, `model`, `temperature`, `top_p`, `stream` | The same; a streaming request also gets `stream_options.include_usage` |
| `cache_control`, `signature`, `metadata.user_id`, `eager_input_streaming`, `thinking.display`, `thinking.type` `enabled`/`adaptive` | Accepted, not rendered |
| `redacted_thinking`, `image`, `document`, server tools and their blocks, `top_k`, `stop_sequences`, other `tool_choice` forms, `context_management`, unknown fields | Rejected |

- **No hidden recall tools** on Messages (Phase 4B position 1): `--hidden-tools` applies to Chat sessions only.
- **Emission** (`palimnesis.protocols.messages_emit`, S3).
  - The upstream's Chat stream becomes `message_start`, then a content block per run of reasoning (`thinking`), text or one tool call (`tool_use`, opened once its name is known, arguments as `input_json_delta`), then `message_delta` and `message_stop` at `[DONE]`. A change of kind closes the open block.
  - Stop reasons: `stop` → `end_turn`, `tool_calls` → `tool_use`, `length` → `max_tokens`. A tool call cut off by the length stop is streamed as Strata streams it: a closed `tool_use` block whose JSON does not parse.
  - Thinking blocks carry `signature: ""` and no `signature_delta` (O-4B-2).
  - Without `[DONE]` there is no `message_stop`: the stream ends with one `event: error` in Anthropic's envelope. An upstream error chunk becomes that event with its message verbatim.
  - Comments pass through; the proxy's own keepalive is `event: ping`.
  - Non-streaming: one Messages object. A tool call whose arguments do not parse is left out, as Strata's non-streaming route does.
- **Content identity.** A message's content hash covers only what renders, so a moved `cache_control` and a single text block sent as a string hash alike. The fingerprint (§6) covers the raw body minus `stream`.
