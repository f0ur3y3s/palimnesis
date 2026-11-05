# Phase 4B plan: harness expansion

> **Status:** S0 probes done (Strata §13, `pi.md`, `claude_code.md`); every decision settled (D81, D82, which also corrects positions 3 and 6). One Strata slot kept (O-4B-7, D83). S1 done (D83). S2 done (D84). S3 done (D85). Late system kept as `system`, counter c5 (D86). Next: S4 and S5, S6 alongside, then the rest of S7.

Planner output, 2026-11-05, at `8df2a68` (after `phase-3`, R42). Module paths follow D80's layout.

Scope:
- v1_plan "Phase 4B — Harness expansion";
- the Phase 3 deferrals to 4B: O4 (proxy FIFO admission, `429`, header deadline H and keepalives) and the contracts §3 Anthropic re-envelope;
- the Anthropic part of O-B8.

Phase 4A (pinned state) is out of scope. Working notes change only where a second protocol requires it, and under core position 2 that is nowhere.

## Core positions

1. **What 4B is.** Two client protocols and three harnesses get archive mode, each with a documented subset:
   - OpenAI Chat Completions: OpenCode (done), Pi.
   - Anthropic Messages: Claude Code, Pi, and OpenCode only if decision O-4B-3 includes it.

   It also ships per-harness setup, new-session and resume instructions, verified native-compaction settings, transcript-gate verdicts, and O4.

   **What 4B is not:**
   - a new recall mechanism, or a change to `a4-d77`;
   - hidden recall tools on Messages;
   - branching, or streaming replay (Ph8);
   - a held-out performance gate per harness (O-4B-11).
2. **Client protocol at the edge, one upstream dialect inside (O-4B-1).**
   - A protocol adapter parses the client body into the neutral typed form the core already uses: `chat.Message`/`Block`, Chat-shaped. The adapter also:
     - fingerprints the request;
     - emits the client's stream and error shapes;
     - picks the keepalive format.
   - The upstream call stays in the profile's dialect: Chat Completions to Strata.
   - Several parts then need no protocol branch:
     - the view, budgets, excerpts, the a3 addendum and the working-notes refresh, which `pipeline._refresh_notes_once` already renders with `chat.render_messages`;
     - cache accounting (`cacheacct`, `CrossCheck.usage`);
     - the pinned counter and the canary.
   - **Rejected:** an upstream dialect that follows the client's. It would fork rendering, usage parsing, the notes call and `--explain` per dialect, and Strata's own Messages route reports `input_tokens: 1` in final usage (`docs/probes/strata.md` §5).
3. **The neutral form is Chat-shaped, and the split is deterministic.**
   - The Messages adapter maps one Anthropic message to one or more neutral messages:
     - a user message's `tool_result` blocks become `tool` messages, in order;
     - its text blocks become one `user` message after them;
     - an assistant message's `thinking` blocks become `reasoning`, `text` blocks become text, and `tool_use` blocks become `tool_call`s whose `input` is serialized as canonical JSON.
   - `cache_control` is excluded from the content hash and from the neutral blocks. Claude Code moves its breakpoint every turn [docs, unverified on the wire], so a hash that kept it would make every resend a divergence.
   - Because the split is a pure function, resends split the same way, and `transcript` alignment works unchanged.
   - The raw body is archived exactly, as today.
   - **Rejected:** one occurrence holding mixed blocks. It touches the view builder, `stubs`, `turns`, `projection` and reconciliation.
4. **Harness specifics live in adapters, never in core.**
   - The adapters are `integrations/pi/`, `integrations/claude-code/` and `docs/harnesses.md`.
   - `turns.SYNTHETIC_USER_PREFIXES` already holds OpenCode strings in core. It becomes adapter-declared data that core reads as one flat list (`palimnesis/harness_strings.py`, no harness names).
   - A protocol-neutral rule is added: a user message carrying any tool result is never an instruction.
   - The AST boundary test (`tests/test_profile.py`) gains a check that no core module contains "opencode", "claude" or "pi" identifiers or keys off `User-Agent`.
5. **Advertise per cell only on evidence.**
   - A harness × protocol cell becomes "supported" in `capabilities.md` only after its probes, recorded fixtures and live smoke pass.
   - Otherwise it stays "planned" or "rejected", with the reason (the D37/O5 pattern).
   - Transcript fallback is claimed per harness only after its gate passes.
6. **O4 lands here.**
   - With three harnesses on one Strata slot, proxy admission stops being optional.
   - The keepalive format is keyed by protocol: an SSE comment for Chat (verified for OpenCode), and `event: ping` for Messages (per the Anthropic spec; whether Claude Code recognizes it is probe HC5).

## Findings in current code

- **Archive route.** `api._archive_route` rejects every POST except `ledger.ENDPOINT_CHAT`. The query string never reaches the archive route, so `?beta=true` is neither accepted nor rejected explicitly.
- **Hardcoded in `archive.pipeline.ArchiveHandler.__call__`**, all of which must move behind the adapter:
  - `chat.parse`;
  - `fingerprint_v1(ledger.ENDPOINT_CHAT, …)`;
  - `_error_event`'s OpenAI shape;
  - raw relay of Chat SSE bytes in `_stream`.
- **Chat-only constants.** `ledger._extend` writes `ENDPOINT_CHAT` on every request row, and `fingerprint.TRANSPORT_ONLY_FIELDS` is Chat-only.
- **Errors.** `errors.error_response` already shapes proxy errors as Anthropic for `/v1/messages*` (D5). Upstream non-200 responses are relayed raw (contracts §3, [defined, Ph4B]).
- **Streams.** `sse.ChatStream` and `assemble.ChatAssembler` are Chat-only. The Messages emitter is new; Messages hidden tools are not built (position 1).
- **Canary mapping.** `upstreams/strata/facts.anthropic_to_render_args` already maps a Messages subset to render arguments for the canary:
  - it joins text blocks with `""`;
  - it maps `thinking.disabled` and `output_config.effort`.

  It is the starting evidence for the adapter mapping, not proof for forms the canary does not cover.
- **Pi's defaults.** `chat` rejects the `developer` role, text-part arrays and `store`. Pi sends all three by default [static, unverified on the wire].
- **Base URLs.** `cli` `session new` already prints `openai_base_url` and `anthropic_base_url`. OpenCode's Anthropic base must include `/v1` (`docs/probes/harnesses.md`).

## 1. Probes first (S0)

Every harness fact below comes from 2026-10-24 static reading (`docs/probes/harnesses.md`) and is **unverified on the wire** until captured.

S0 first records the installed Pi and Claude Code versions, and re-pins if they moved past 1.4.0 and 2.1.310. Whether either is installed on pythia is **unverified**.

**Hosts.**
- **Strata facts:** only pythia (D76, 0.1.54 at 32K), idle-gated per D39, synthetic bodies.
- **Harness probes:** scripted fake servers on loopback, runnable on any host.
- **mbp** (192.168.1.8; M2 Pro; LM Studio on :8080; OpenAI-compatible; not Strata):
  - It may be used, through `serve --passthrough --capture-dir`, to capture real-model request shapes, URL joining and tool loops for Pi (Chat) while pythia is busy with evaluation.
  - Whether LM Studio serves `/v1/messages` is **unverified**. If it does not, Claude Code and Pi-Messages shape captures use the scripted fake Messages server, or the request half of a 404 exchange.
  - No bounded-view run or evaluation happens on mbp (no pinned profile, D15 amended).
  - OS-dependent facts found there (stdin quoting, paths) are re-verified on the evaluation host.

**Strata `/v1/messages` on pythia** (`eval/probes/p21_*`–`p25_*`, report in `docs/probes/strata.md` §13):

| Probe | Must establish (today's status) |
|---|---|
| M1 stream shapes | Event order, `message_start` usage, `content_block_*` for thinking, text and `tool_use`; `input_json_delta` granularity; `tool_use` id format; `stop_reason` on a length stop (only `end_turn` and `tool_use` seen; `max_tokens` **unverified**); comments rather than `ping`; EOF on engine death. Verified on 0.1.48 only (§5, §6). |
| M2 rendering parity | `count_tokens(Messages body)` against the local count of the adapter's neutral form, case by case: multi-block `system`; several text blocks in one user message (join **unverified**); `tool_result` with text-block arrays; `is_error`; `tool_result` plus text in one message; mid-conversation `role: system` (**unverified**: 400, merged or rendered); `cache_control`; `thinking` with and without a signature; `thinking.type: adaptive` and `budget_tokens` (**unverified**); every `output_config.effort` value; `tool_choice` forms; `top_k`; `stop_sequences`; `metadata`. Each field is classed as rendered, ignored or 400. |
| M3 errors | Malformed body, unknown role, overflow and an engine-down shape on Messages for 0.1.54. Known on 0.1.48: no Anthropic envelope (§8). Needed for arm 1 and for passthrough documentation. |
| M4 cross-dialect reuse | A conversation primed through Messages, then extended through Chat, reuses the checkpoint (equal ids) **[unverified]**. Supports arm comparability, not a gate. |
| M5 `?beta=true`, `anthropic-beta` | Accepted by Strata directly (needed for arm 1 passthrough) **[unverified]**. |

**Pi** (`eval/probes/pi_fault_server.py`, `pi_probe.py`; report `docs/probes/pi.md`):

| Probe | Must establish |
|---|---|
| HP1 joining | Chat base `/s/<id>/v1` joins to `/s/<id>/v1/chat/completions`; Anthropic base `/s/<id>` joins to `/s/<id>/v1/messages?beta=true` [static]. |
| HP2 association | An extension using `before_provider_headers` sets `X-Palimnesis-Session` to Pi's session id [inferred]. What `/new`, `/fork`, `/clone`, `/resume` and `/tree` send, and across restarts. |
| HP3 shapes, both protocols | `developer` role, `store: false`, `reasoning_effort`, `max_completion_tokens` shrinking with a large `contextWindow`, tool shapes, `cache_control`, `eager_input_streaming`. Thinking replay with a `""` signature, with and without `compat.allowEmptySignature` (otherwise demoted to text [static]). Resend fidelity across turns and after a restart. |
| HP4 timeouts and retries | Header wait and idle (300 s [static]); whether comments or `ping` reset idle. Retry triggers, including 409, 429 and `retry-after`; `x-should-retry`. **What the agent retry resends after a partial**: the same prefix with the partial omitted [static], with `retry.enabled` true and false. |
| HP5 compaction | `compaction.enabled: false` verified with a forced overflow; the manual `/compact` request shape captured for S8. |
| HP6 F and gate | System-prompt and tool tokens (F) at 32K. Whether Pi's read, grep and bash reach the transcript root without prompts; Pi permissions are **unverified**. |
| HP7 driving | Non-interactive mode and session-file import for needle histories (**unverified**). |

**Claude Code** (`eval/probes/cc_fault_server.py`, Messages SSE; `cc_probe.py`; report `docs/probes/claude_code.md`):

| Probe | Must establish |
|---|---|
| HC1 joining | `/s/<id>` joins to `/s/<id>/v1/messages?beta=true`; `HEAD /api/hello` and its handling of a 404; `count_tokens`; `/v1/models` [static]. |
| HC2 traffic inventory | Every request on the base URL across start, a tool loop, idle, `/clear` and exit, under the candidate env (below). Covers title, `quota_check`, away summary, memory and side queries, and which requests are non-streaming. A `quota_check` archived as a session's first turn would make the real first request diverge. |
| HC3 shapes | Body fields after `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`; betas; system blocks and whether the billing-header line varies per request (`CLAUDE_CODE_ATTRIBUTION_HEADER=0`); mid-conversation system entries; `metadata.user_id`; `cache_control` movement; tool count and size (F); `thinking` and `max_tokens`. |
| HC4 thinking | Replay of a `""` signature against an opaque proxy signature; tail-drop of unsigned thinking; the signature-error strip path. |
| HC5 timeouts and retries | `API_TIMEOUT_MS` header wait. Event and byte watchdogs: **does a comments-only wait over 300 s kill the stream, and does `event: ping` keep it alive?** Retry codes, `x-should-retry`, the non-streaming fallback with and without `CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK=1`, what follows a partial, and in-stream `error` events. |
| HC6 compaction | `DISABLE_AUTO_COMPACT=1` against `DISABLE_COMPACT=1`; the client blocking limit under `CLAUDE_CODE_MAX_CONTEXT_TOKENS`; `context_management` absent; the `/compact` shape for S8. |
| HC7 resume | Fidelity of the `claude --resume` resend against the archive; the `/rewind` shape. |
| HC8 gate | `-p` mode reads and greps the transcript directory through `--add-dir` or `permissions.additionalDirectories`, with no prompt. |
| HC9 driving | `-p --output-format stream-json`, and history import through a hand-built session file (**unverified** feasibility). |

**OpenCode on Messages** (OC-A1, only if O-4B-3 includes it): the base `/s/<id>/v1`, and whether unsigned thinking is demoted to text [inferred].

## 2. Design

**2.1 The Messages subset** (`palimnesis/protocols/messages.py`, allowlist-strict like D11). Every field is either mapped, rejected before acceptance, or documented as accepted with no upstream effect. Nothing is dropped silently.

| Accepted | Mapping or note |
|---|---|
| `model`, `max_tokens`, `stream`, `temperature`, `top_p` | As on Chat. `max_tokens` is the client limit of §7. |
| `system` (string or text blocks) | One leading system message, joined as Strata joins (M2). |
| `messages`: text, `thinking`, `tool_use`, `tool_result` (string or text blocks; `is_error`) | As in position 3. `is_error` is mapped per M2, keeping Strata's own rendering, and the flag stays in block meta. |
| `tools[]` (`name`, `description`, `input_schema`, `cache_control`, `eager_input_streaming`) | Bare tool form. The last two have no upstream effect. |
| `tool_choice` `auto` / `none` | Others rejected, as on Chat. |
| `thinking` `enabled` / `disabled` / `adaptive`; `output_config.effort` | Mapped per M2 to `reasoning_effort` and `enable_thinking`. `budget_tokens` is rejected if M2 shows Strata ignores it, to avoid a misstated claim. |
| `metadata.user_id` | Accepted, no upstream effect, excluded from the fingerprint (identity hint only, contracts §4). |
| `?beta=true`; `anthropic-version` and `anthropic-beta` headers | Transport-only. Betas enable nothing beyond the allowlisted body. |
| **Rejected:** `redacted_thinking`, image, document, server tools, `stop_sequences`, `top_k`, other `tool_choice` forms, unknown fields | `400 unsupported_feature` in the Anthropic envelope. |
| **Mid-conversation `role: system`** | Per O-4B-12. |

**2.2 Emission** (`palimnesis/protocols/messages_emit.py`, a pure state machine shaped like `ChatAssembler`).
- **Stream conversion.** Upstream Chat events become `message_start`, then per block `content_block_start`/`_delta`/`_stop`, then `message_delta` and `message_stop`.
  - Text and thinking are forwarded promptly.
  - `tool_use` input is streamed as `input_json_delta` once the name is known; Strata sends the name first (§12.1).
  - Text after a call opens a new block, and reasoning after a call opens a new thinking block.
- **Mappings.**
  - `stop_reason`: `stop` → `end_turn`, `tool_calls` → `tool_use`, `length` → `max_tokens`.
  - Usage, Anthropic semantics: `input_tokens` = prompt − cached, `cache_read_input_tokens` = cached, `cache_creation_input_tokens` = 0, `output_tokens` = summed completion (D61 analogue). So input plus cache_read equals the bounded view's prompt.
- **Signatures** per O-4B-2.
- **Commit before forward** holds: parsed deltas are committed, then the proxy-authored bytes for that batch are sent.
- **EOF without `[DONE]`** gives an `event: error` in the stream, never `message_stop`.
- **Non-streaming** responses get one Messages JSON body, committed before delivery.

**2.3 Errors.**
- Upstream non-200 after acceptance keeps its status and is re-enveloped for Messages clients as `{"type":"error","error":{"type", "message": <upstream message verbatim>}}`, with `x-should-retry: false`.
  - The message is kept verbatim because Claude Code's own heuristics match on wording (context limit, unexpected role, signature) [static].
  - Chat clients are unchanged.
- In-stream errors follow the protocol: Chat `data: {"error":…}`; Messages `event: error`.

**2.4 Identity.**

| Harness | Association |
|---|---|
| OpenCode | Plugin, unchanged. |
| Pi | The `integrations/pi/` extension sets `X-Palimnesis-Session` from Pi's session id (HP2). Fallback: a per-session `PI_CODING_AGENT_DIR`. |
| Claude Code | A wrapper, `integrations/claude-code/palimnesis-claude.{sh,ps1}`, runs `palimnesis session new` or `session url <id>` and sets `ANTHROPIC_BASE_URL` per process. `/clear`, `/resume` to another session and `/rewind` reach the archive as divergence (409, never merged); `harnesses.md` says to restart through the wrapper. |

A session's client protocol is fixed by its first request. Another protocol gets `400 session_protocol_mismatch`.

**2.5 Admission (O4, contracts §5 and §8).**
- `palimnesis/admission.py`: a bounded FIFO of capacity Q and one upstream dispatch.
- Duplicates and conflicts are resolved in `ledger.accept` before enqueue. The deadline D runs from arrival.
- A full queue gets `429` with `retry-after`.
- **Response headers within H.** Streaming requests get headers (`x-should-retry: false`) within H, then keepalives every K.
  - For Messages, `message_start` is sent at dispatch.
  - `ping` is allowed before it if HC5 shows Claude Code tolerates that; otherwise `message_start` goes first with the locally counted input.
- **Slot ownership.** The slot is held across the notes refresh and hidden continuations. It is released when the response returns or when external tool calls are returned.
- **Upstream activity guard.** A profile protocol, `SlotProbe` (Strata: `/status`), extends D21.

**2.6 Compaction and discontinuity.**
- Discontinuity is detected structurally: reconciliation position by position, never matching on summary text.
- Accepting a compaction as an explicit discontinuity needs branch machinery (Ph8); see O-4B-6.

## 3. Slices

Each slice is a red→green tracer. Seam H = fake-upstream HTTP; P = pure function.

| # | Slice | Red tests first | Code | Contract text |
|---|---|---|---|---|
| S0 | Probes M1–M5, HP1–7, HC1–9 | — | `eval/probes/`, fault servers | `docs/probes/*`; `harnesses.md` facts |
| S1 | Client-protocol seam; Chat moved behind it, no behavior change | Existing suite green; `test_core_never_keys_off_harness_or_user_agent` (AST); `test_archive_route_dispatches_by_path` (H) | `protocols/__init__.py` (`ClientProtocol`: parse, endpoint, transport fields, emitter, error event, keepalive), a Chat adapter over `protocols/chat.py`; `api`, `archive.pipeline`, `archive.ledger` take the endpoint from the adapter | §3 archive-mode wording |
| S2 | Messages parse and neutral split | `test_messages_rejects_unknown_fields_at_every_level`, `test_tool_results_and_text_split_deterministically`, `test_cache_control_moves_keep_content_hash`, `test_tool_use_input_round_trips_exact_json`, `test_redacted_thinking_image_document_server_tool_rejected`, `test_parity_corpus_counts_equal_recorded_count_tokens` (M2 fixture) (all P) | `protocols/messages.py`, `archive.fingerprint` transport fields per endpoint | New §16 Client protocols (mapping table) |
| S3 | Emitter | `test_emitter_lifecycle_text_thinking_tool_use`, `test_stop_reason_and_usage_mapping`, `test_text_or_reasoning_after_call_opens_new_block`, `test_eof_without_done_is_error_event_not_message_stop`, `test_signature_rule` (O-4B-2) (all P) | `protocols/messages_emit.py` | §3, §7 Messages usage |
| S4 | Messages archive route | `test_messages_stream_archived_and_resend_reconciles`, `test_messages_nonstream_committed_before_delivery`, `test_beta_query_accepted_other_query_rejected`, `test_count_tokens_relayed_unarchived` (O-4B-10), `test_protocol_fixed_per_session`, `test_reserved_palimnesis_tool_name_rejected_on_messages`, `test_budget_error_anthropic_envelope_before_acceptance`, `test_idempotency_and_streaming_key_409_on_messages`, `test_upstream_body_is_chat_and_counts_within_budget` (all H) | `api`, `archive.pipeline`, `archive.ledger` (`ENDPOINT_MESSAGES`) | §3 endpoints; §6 fingerprint fields |
| S5 | Errors and in-stream failures | `test_upstream_non200_reenveloped_status_and_message_kept`, `test_failure_after_start_messages_error_event_no_retry_header`, `test_deadline_after_start_messages_error_event` (H) | `errors`, `archive.pipeline` | §3 re-envelope [enforced]; §5 table |
| S6 | Admission (O4) | `test_fifo_one_dispatch_across_sessions`, `test_queue_full_429_retry_after`, `test_headers_within_H_while_queued_and_during_notes_refresh`, `test_keepalive_comment_chat_ping_messages_every_K`, `test_cancelled_or_expired_queued_entry_never_dispatched`, `test_queue_time_counts_against_D`, `test_slot_held_across_notes_refresh_and_hidden_continuation`, `test_status_guard_waits_for_foreign_work` (H) | `admission.py`, `upstreams.profile.SlotProbe`, `upstreams/strata` | §5 H/K, §8 → [enforced] |
| S7 | Instruction rule and harness strings | `test_user_message_with_tool_result_never_instruction`, `test_harness_synthetic_prefixes_from_adapter_data` (P); `test_cc_interrupt_marker_hosts_no_excerpt` (H, recorded fixture) | `archive.turns`, `harness_strings.py` | §13 host rule |
| S8 | Discontinuity fixtures | Per harness: `test_<h>_manual_compact_request_is_divergence` (captured bodies); `test_summary_shaped_text_in_ordinary_turn_is_accepted` (H) | none expected | §4 |
| S9 | Pi adapter | Recorded HP3 bodies replayed: `test_pi_chat_session_round_trip`, `test_pi_messages_session_round_trip`, `test_pi_retry_after_partial_policy` (O-4B-5) (H) | `integrations/pi/` (models.json, settings.json, extension); Chat additions per O-4B-9 | §4 association; capabilities rows |
| S10 | Claude Code adapter | Recorded HC3/HC7 bodies: `test_cc_session_round_trip_and_resume`, `test_cc_nonstream_fallback_resend_policy`, `test_cc_side_call_policy` (O-4B-8) (H) | `integrations/claude-code/` (env, settings.json, wrapper) | §4; capabilities rows |
| S11 | Reasoning goldens on Messages | `test_messages_tool_loop_rendered_tokens_golden_next_turn_restart` (P, H) | — | §9 thinking blocks |
| S12 | Cache accounting on Messages archives | `test_messages_session_explain_zero_unexplained`, `test_cache_control_move_is_not_a_prefix_change` (H) | `view.cacheacct` if needed | §10 note |
| S13 | Transcript gates and live smoke per cell | Probes HP6, HC8 (L) | — | §14 access per harness |
| S14 | Eval drivers and runs (§6) | Driver unit tests (`test_eval_pi`, `test_eval_cc`) | `eval/pi_harness.py`, `eval/cc_harness.py`, `tasks/run.py --harness` | — |
| S15 | Contracts, docs, three reviews, `results/`, tag `phase-4b` | — | — | all |

Order:
1. S0.
2. S1 to S5, with S6 and S7 in parallel with S2 to S5.
3. S8 to S12, then S13, S14 and S15.

## 4. Decisions for the user

1. **O-4B-1 Upstream dialect.**
   - (a) Translate Messages to Chat upstream.
   - (b) Use the client's dialect upstream.
   - **Recommendation: (a)** (position 2). M2 measures token parity with direct Messages, which is reported and needed for arm fairness. (b) forks counting, usage, the notes call and `--explain`.
2. **O-4B-2 Thinking signatures.**
   - (a) `""`, as Strata sends.
   - (b) An opaque proxy signature: base64 HMAC-SHA256 of the block's archived sha256 under a per-archive key, sent as `signature_delta` at block end.
   - (c) No thinking in the client stream.
   - **Recommendation:** (a) if HP3, HC4 and OC-A1 show every advertised client replays `""` as thinking; otherwise (b).
   - (c) is rejected: Claude Code's event watchdog during long reasoning, and no visible progress.
   - Strata ignores input signatures (§2).
3. **O-4B-3 Cells to advertise.**
   - **Recommendation:** Pi-Chat, Pi-Messages (a second Messages SDK at little cost) and Claude Code-Messages are required.
   - OpenCode-Messages gets deterministic fixtures and smoke only, advertised if OC-A1 passes.
4. **O-4B-4 Association for Pi and Claude Code.**
   - **Recommendation:** Pi through the header extension; Claude Code through the per-process wrapper (2.4).
   - Rejected for now: a `--identity-header` option mapping a harness's own session header (for example `X-Claude-Code-Session-Id`) to a session. It is a new identity source under contracts §4 and needs its own mismatch rules.
5. **O-4B-5 A server-failed partial omitted from the resend** (Pi's agent retry replays the prefix [static]).
   - (a) Keep it as divergence or `ambiguous_retry`, and ship `retry.enabled: false`.
   - (b) Extend D13.1: a partial whose attempt ended with the proxy's in-stream error may be omitted and is superseded.
   - **Recommendation:** (b) if HP4 shows Pi omits it even with retries off, because otherwise one upstream failure bricks the session; else (a).
6. **O-4B-6 Manual or harness compaction.**
   - **Recommendation:** keep `409 history_divergence` and document it per harness, with detection proven structural (S8).
   - Accepting a compaction as an explicit discontinuity is deferred to Ph8 with branching.
7. **O-4B-7 O4 in 4B.**
   - **Recommendation:** yes, with H 10 s, K 15 s (≤ ¼ of the smallest verified read-idle), Q 4, and `retry-after` capped at 30 s.
   - The cap is because Claude Code stops retrying past about 60 s [static].
8. **O-4B-8 Side calls that cannot be disabled** (HC2).
   - (a) A `--side-model NAME` option: requests naming that model are relayed unarchived. It is model-based and harness-neutral.
   - (b) Reject them.
   - **Recommendation:** only if HC2 finds such calls; (a) then.
9. **O-4B-9 Pi's Chat defaults** (`developer`, `store`).
   - **Recommendation:** Pi `compat` flags in the adapter config (`supportsDeveloperRole: false`; a `store` switch, existence **unverified**).
   - Only if no flag exists: accept `store: false` as no-effect, and a leading `developer` message as system, after an M2-style parity check.
10. **O-4B-10 `count_tokens` in archive mode.**
    - **Recommendation:** relay it to the upstream, unarchived. It is stateless and truthful.
    - Set `CLAUDE_CODE_MAX_CONTEXT_TOKENS` large so the client's own blocking limit never fires (the analogue of OpenCode's `limit.context`).
11. **O-4B-11 Evaluation legitimacy.**
    - **Recommendation:** 4B gates are contracts, live smoke, transcript gates and fault runs. Performance runs on development data are reported, not gated.
    - A fresh `ho4` (all three harnesses) is written by a separate author before any Pi or Claude Code run, and kept unseen for Phase 7.
    - Alternative: a D77-style gate per harness now, at about 30–40 slot-hours more on pythia (estimate).
12. **O-4B-12 Claude Code's mid-conversation system entries.**
    - **Recommendation:** if M2 shows Strata renders them on Messages, map them to Strata's rendering.
    - Otherwise reject with `400 unsupported_feature` and verbatim text naming the role, then test whether Claude Code's strip-and-retry fires (HC3).
    - This is protocol behavior, not a Claude Code branch.
13. **O-4B-13 Context for Claude Code.**
    - Claude Code's F is **unverified**. With the D79 floor (`F + min_recent + S + R + M`, so `F + 4096 + 2048 + 8192 + 256 ≤ 32768`), bounded views refuse at 32K if F is above 18,176.
    - **Recommendation:** measure in HC3. If it does not fit, either:
      - run Claude Code at 64K, a Strata restart that needs the user's approval (D39, D40); or
      - trim tools with `--disallowedTools`, recorded as a harness setting.

New decision entries, numbered from D81 once settled:
- the client-protocol seam (S1);
- the Messages subset and split;
- the emitter and usage;
- signatures;
- association;
- admission;
- harness strings and the instruction rule;
- discontinuity;
- the 4B evaluation protocol, written before any Pi or Claude Code run.

## 5. Requirement → test / measurement / deferral

Seams: P pure · H fake-upstream HTTP · E eval · L live · D docs.

| Requirement | Test or measurement | Seam |
|---|---|---|
| **GL1** archive contracts per advertised harness | S4 and S9/S10 round trips; recorded-fixture replays per cell; crash points (`test_crash_recovery` parametrized by protocol) | H |
| GL1 recall | `test_excerpts_on_messages_host_and_absent_from_client_stream`; transcript gates HP6, HC8; notes refresh on a Messages session (`test_notes_refresh_chat_upstream_for_messages_client`) | H, L |
| GL1 streaming | S3 emitter tests; `test_messages_deltas_forwarded_before_upstream_completes`, `test_messages_commit_before_forward` | P, H |
| GL1 cancellation | `test_messages_disconnect_closes_upstream_records_cancelled`; queued cancellation (S6); live slot release on pythia, under 1 s during decode (§9 threshold) | H, L |
| GL1 recovery | `test_messages_restart_reconstructs_identical_view_tokens` (S11); fault runs HP4/HC5 through the proxy: no silent duplicate generation; restart coding task per harness | H, E |
| **GL2** path preservation, joining | HP1, HC1, OC-A1 captures; `test_beta_query_accepted_other_query_rejected` | L, H |
| GL2 path/header conflict | `test_session_mismatch_on_messages_anthropic_envelope`, `test_protocol_fixed_per_session` | H |
| **GL3** native compaction verified | HP5, HC6 (forced-overflow runs, no compaction request seen); OpenCode D37 setting carried over | L |
| GL3 detection not summary-shaped | S8 pair per harness | H |
| **GL4** state-independent fixtures | Every 4B fixture runs with `Settings` defaults (no state); suite passes without Phase 4A | H |
| v1 4B: versions, extensions and settings recorded | `capabilities.md` and `harnesses.md` rows from S0 | D |
| v1 4B: session-URL setup, new and resume per harness | `harnesses.md` per harness; wrapper and extension smoke | D, L |
| §3 re-envelope (deferred from Ph3) | S5 | H |
| §3 unsupported fields rejected, never dropped | S2 rejection tests; §16 table | P |
| §3 EOF without `message_stop` | S3, `test_messages_upstream_eof_error_event` | P, H |
| §2 budgets on Messages requests | `test_upstream_body_is_chat_and_counts_within_budget`, budget-error envelope | H |
| §4 reconciliation on resend | S4; HC7, HP3 resend-fidelity replays | H |
| §5 H, K, 429; §8 FIFO, slot, guard (O4) | S6; live K recognition from HP4/HC5 | H, L |
| §5 per-harness timeout and retry facts | HP4, HC5 → `harnesses.md` | L, D |
| §6 fingerprints for Messages | `test_messages_fingerprint_excludes_transport_and_cache_control` | P |
| §7 allowance from `max_tokens`; length → `max_tokens` stop | `test_messages_allowance_cap_and_length_stop` | H |
| §9 thinking carryover | S11 goldens | P, H |
| §10 0 unexplained on Messages | S12; `--explain` on every live Messages archive | H, E |
| §13 host rule with tool-result messages | S7 | P, H |
| §14 transcript access per harness | Gates HP6, HC8, else proactive-only row | L, D |
| §15 hidden tools on Messages | **Deferred**: not offered (off by default; R32 failed its gates); `test_hidden_tools_not_offered_on_messages` | H |
| Streaming replay on Messages | 409 until Ph8 (S4 test) | H |
| Model-facing configuration unchanged | `test_eval_d77` unchanged; `serve` defaults equal `a4-d77` for both protocols | H |

## 6. Evaluation

All runs are on pythia at `n_ctx` 32768 with the pin and canary passing (D77.2).
- Claude Code runs at 64K only if O-4B-13 requires it.
- Real harnesses run sequentially, under the D39 gate, and 30-minute turn kills are reported.
- The configuration is `a4-d77`, unchanged.

| Run | Per harness (Pi-Chat, Pi-Messages, Claude Code; OpenCode-Messages smoke only) | Status |
|---|---|---|
| Live smoke | Scripted multi-turn task with tool loops through every path the harness uses (streaming; non-streaming where HC2 finds it) | gate (GL1) |
| Fault runs through the proxy | HP4/HC5 matrices with the shipped settings: no silent duplicate generation, `x-should-retry` honored, keepalive recognized | gate |
| Transcript gate | Grep plus bounded read of an evicted needle (A1 gate) | gate per fallback claim |
| Restart and cancellation | Proxy restart mid-task; Ctrl-C mid-stream with slot release measured | gate |
| D44.6 inputs on every live archive | 0 over budget, 0 excerpt text visible, `--explain` 0 unexplained, `transcripts verify` | gate |
| Development needles | dev-h1..h6 (60) via the harness driver, arm 4 only | reported |
| Coding against native compaction | dev-t1..t5 plus the ho2 tasks (development per D69). Arm 4 against arm 1: Pi `compaction.enabled: true`, `contextWindow` 32768; Claude Code autocompact with window 32768; both through `--passthrough` (arm 1 Claude Code goes to Strata `/v1/messages` directly, M5) | reported |
| Held-out | None in 4B (O-4B-11); `ho4` written and committed unseen for Phase 7 | deferred |

- **Slot-time estimate:** about 4 h of needles and about 25–35 h of tasks (2 harnesses × 5 tasks × 2 arms at about 1.5 h each on pythia, D76).
- **mbp:** captures only, never evaluation.
- **Results:** R43 onward, per host and build.

## 7. Risks and deferred

**Risks.**
- **Claude Code's fixed input may not fit 32K** (O-4B-13).
- **Claude Code's side calls and quota probes,** if they can't be switched off (HC2), could seed or fork sessions.
- **Feature-flag-dependent behavior.** Claude Code is pinned with `DISABLE_GROWTHBOOK=1`; behavior can still change per build.
- **Claude Code's watchdogs** may not accept comments (HC5), which is why `ping` is used on Messages.
- **Translation parity gaps** (M2) shift what the model sees between arm 1 and arm 4. They are reported, and they block a cell only if content is lost.
- **Pi's partial-replay retry** (O-4B-5).
- **Unsigned-thinking demotion breaking reconciliation** (O-4B-2).
- **Admission adds a queue for OpenCode too.** It changes when headers are sent, so the opencode_faults matrix reruns.
- **Harness drift.** Static facts are about two weeks old, and the harness versions may have moved.

**Deferred, with reasons.**
- Hidden recall tools and the Anthropic assembler: off by default, failed gates (R32).
- Accepting compaction as a discontinuity, and branching: Ph8.
- An identity-header alias (O-4B-4).
- Images, documents, `redacted_thinking`, server tools, `stop_sequences`: no harness need, and no Strata vision on pythia.
- OpenAI Responses: no advertised harness needs it.
- Held-out performance per harness: Phase 7 on `ho4`.
- llama.cpp and LM Studio profiles: D15 amended.
- Streaming replay: Ph8.
