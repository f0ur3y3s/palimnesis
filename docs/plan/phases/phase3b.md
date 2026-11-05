# Phase 3B plan: hidden recall tools

> **Status:** built and run; both held-out gates failed (R32), so hidden recall tools stay off by default and there is no `phase-3b` tag (D64).

Planner output, 2026-10-26, at `9482265` (S12). A1's "Optional Phase 3B" section governs, and v1_plan Phase 3 sets the scope. The user chose 3B after R25 (coding gate failed at 32K) and R25-E (about half of 68 transcript lookups were overhead). User decisions on the open items are recorded in the Delta section.

## Core positions

1. **One seam per concern.**
   - Stream rewriting goes in a protocol-keyed assembler, `palimnesis/assemble.py` (OpenAI Chat). It is protocol plumbing and needs no citation.
   - The continuation loop goes in `ArchiveHandler._run`.
   - Tool execution goes in `palimnesis/recalltools.py`, which cites ARC.
   - No core module names a harness.
2. **Nothing changes until a `palimnesis_*` call happens.** A response with one generation keeps today's storage, bytes and cache behaviour.
3. **The hidden tools appear only once something is hidden.** They are fixed per session at the first masked view, together with the addendum (the D36 pattern).
4. **The gate is judged on a fresh held-out set.** The R25 set has been seen, and 3B's design came from analysing it.

## Findings in current code

1. **The relay forwards raw upstream bytes.** `archive._stream` sends tool-call deltas, the finish chunk and `[DONE]` unchanged. Nothing classifies, re-indexes or suppresses them.
2. **One generation per attempt.** `ledger._ensure_occurrence` hardcodes `generations.ordinal = 1`, and `Generation` holds a single occurrence.
3. **Client messages are always rendered from the client's copy.** `ledger._upstream_body` splices only `view='internal'` rows. A response split across continuations would render twice or fail reconciliation.
4. **A Phase 1 carry-over is still open (D13).** Internal rows from superseded or cancelled attempts are still spliced.
5. **Grep has no session scope.** `search.search_chunks` has no session or branch filter (v1: "scope retrieval to the authorized session"). `index_occurrence` would also index recall results, which are copies of archived text.
6. **Partial matching assumes one generation.** `transcript._matches_partial` builds the sent text as `reasoning + text`. A composite response must use stream order.
7. **The allowance equals the per-call reserve.** `budget.plan_budget` has a single cap, `reserve_cap` 8192. With OpenCode's 8192, one thinking-heavy continuation would use up the whole request-wide allowance A.
8. **Accounting assumes one call per attempt.** `cacheacct.Accountant.begin` sets `call_id = attempt_id`. `_rerender` takes the tools from the client's raw body and does not know about continuations or injected tools.
9. **Reserved names are not enforced.** `chat.parse` does not reject client tools named `palimnesis_*`.
10. **Building blocks that already exist:**
    - schema: `occurrences.view` / `source='internal_tool'`, `generations.ordinal`;
    - `addresses.resolve` (Unknown/Ambiguous with suggestions);
    - `stubs.chunks` (`next_offset`);
    - `catalog.first/next/page`;
    - drafts t1/t2, a1/a2, s0/s2/s3 in `affordances.py`.

    Tool JSON schemas are not registered anywhere yet.

## 1. Triage: the items Phase 3 moved to 3B (class c)

| Item | 3B disposition |
|---|---|
| Internal calls and results never external | Built (S5) |
| Mixed and parallel calls, malformed arguments | Built (S5) |
| §7 continuation accounting; the allowance cannot be reset | Built (S5), with a separate A cap (O-B3) |
| Model-facing address resolution | `palimnesis_recall` (S4) |
| RE2 regex, multiline patterns | `palimnesis_grep` regex mode (S4) |
| Cancellation that also prevents continuation | S5, plus probe P4 |
| Tool blocks hidden until classified | `assemble.py` (S1) |
| Reasoning goldens through internal calls | S7 |
| A/B affordance matrix | S10 (O-B4) |
| FIFO admission, 429, slot held across continuations | Still deferred to Ph4B (O4). Known limit: another session can slip into Strata's queue between continuations. Measured by D39 foreign activity per continuation. |
| Anthropic Messages assembler | Deferred to Ph4B with the `/v1/messages` archive route |

## 2. Design

### 2.1 Storage (D51)

- **Each upstream call is its own generation.** It gets a `generations` row (ordinal k) and its own `view='both'` generated occurrence. The first one is created exactly as today.
- **Internal calls are flagged when their block is created.** The tool_call block meta carries `"internal": true`. That is possible because Strata sends the name in the first delta (verified on bazzite, `sse_oa_tool.sse`; re-verify on Zeus in P1).
- **Results are internal rows.** Each internal result is a `source='internal_tool'`, `view='internal'` occurrence whose envelope holds `{source_address, start, end, sha256}`.
- **One composite visible turn.** `ledger.load_archived` folds the generations of one attempt into a composite `Archived`:
  - text and reasoning concatenated in ordinal order, with a new `sent` field in stream order;
  - external calls only;
  - `parts=(occ…)`.
- **Reconciliation** matches the client's resend against the composite.
- **Upstream rendering.** `_upstream_body` renders an aligned composite from its parts: each generation with its reasoning and all of its calls. Results follow in call order, mixing internal rows with the client's own tool messages.
- **Superseded attempts.** Parts from superseded or cancelled attempts are skipped (closes D13).
- **No migration.** The flag lives in meta JSON.
- **Rejected alternative:** a separate `view='visible'` occurrence plus `visible_map`. It requires knowing at the first token whether a response will continue, and it changes storage for every response.

### 2.2 Interception and stream assembly (D52)

`assemble.ChatAssembler` is a pure state machine with input `(Event, classify)` and output `(client_bytes, archive_parts, decision)`.

- **Forwarded promptly:** text and reasoning deltas.
- **Classified at the first tool delta.** A reserved prefix means internal; anything else is external.
- **Internal calls** are buffered and never forwarded.
- **External calls** are re-indexed to dense client indices. They are buffered until complete (the next index starts, or the finish chunk arrives), so an incomplete external call is never emitted.
- **Comments** (keep-alives) are relayed.
- **Every generation after the first.** Its role chunk is dropped. Its chunk `id`, `created` and `model` are rewritten to the first generation's values.
- **Intermediate finish chunks, usage and `[DONE]`** are suppressed. Exactly one terminal sequence is emitted.
- **Commit before forward still holds per batch.** Rewritten chunks are proxy-authored bytes, and the archive stores parts.
- **Non-streaming clients** get one assembled JSON body, committed before delivery.
- **Visible usage (D61).**
  - It reports the last call's `prompt_tokens`, `cached_tokens`, and `completion_tokens` summed over all calls.
  - Internal totals go to `upstream_call` and `allowance` events, never into client JSON.

### 2.3 Mixed, parallel, malformed and reserved (D53, D54)

- **All internal.** Resolve every call, commit the results, continue once.
- **Mixed.** Resolve the internal calls, emit only the external ones with `finish_reason: tool_calls`, and wait for the harness. The next request renders all results in call order.
- **Untested forms are rejected,** with the in-stream error `unsupported_mixed_form`. Example: content after a tool call, if P1 shows Strata emits it.
- **Malformed internal arguments** (bad JSON, schema violation, or Strata's #510 text form) get an error result and count against the caps. Malformed external arguments are relayed unchanged.
- **Reserved names.**
  - A client tool named `palimnesis_*` gets `400 unsupported_feature` before acceptance.
  - A model call to an unknown `palimnesis_*` name gets an internal error result and is never forwarded.
- **Injection.**
  - The tool schemas (a frozen JSON per tools version) are appended after the client's tools at the first masked view and recorded as an `hidden_tools_fixed` event.
  - They are counted in F before acceptance, as in D38.2.
  - They are never injected when `tool_choice` is `"none"`.

### 2.4 Limits (D55, D56)

- **Allowance and per-call limit.** A = min(client limit, `allowance_cap`). Each continuation's upstream limit is min(A − consumed, R), with R still 8192 for budgeting.
- **Consumption** is upstream `completion_tokens`, persisted per attempt.
- **Before each continuation:**
  1. rebuild the view with `views.build`, through a new `ledger.continuation_items(conn, plan, upto_seq)`;
  2. check I ≤ B_in and I + R + M ≤ n_ctx.

  A watermark move mid-response is allowed and recorded.
- **Caps** (development-selected defaults):
  - at most 8 internal calls and 4 continuations per visible response;
  - results of at most 6,080 tokens per response at 32K (25% of B_in);
  - per call: recall at most 2,048 tokens, grep and catalog pages at most 1,024, and never more than the room left.
- **When a cap is reached.**
  - The call gets a text result: "limit reached; answer from what you have."
  - Another internal call after that, or no allowance left, ends the response with `finish_reason: "length"`, never `stop`.
  - Running out during an external call's arguments withholds that call (`call_withheld` event) and ends with `length`.
  - Removing the tools or switching to `tool_choice` `"none"` was rejected: the tools render before the system prompt, so either would force a re-read of the whole prompt.
- **Deadline D** covers the whole loop (the existing `move_on_after`).
- **Disconnect** cancels the scope, closes the upstream and starts no further continuation. Resolution checks for cancellation between scan units.

### 2.5 Tools (D57–D59; `recalltools.py`)

- **`palimnesis_recall(id, offset?, limit?)`**
  - `id` is resolved through `addresses.resolve`, scoped to the session. Unknown or ambiguous ids return an error with suggestions and never another record's content.
  - `§A.N` returns `stubs.chunks` of the exact block. `offset` and `limit` are in code points, capped by tokens. The result header carries the range, total length, sha and `next_offset`.
  - `§A` with several blocks lists its blocks and their sizes, with no content.
  - Lone surrogates are shown as U+FFFD, as in D38.1. The archive keeps the exact bytes.
- **`palimnesis_grep(query, mode, scope?, cursor?)`**
  - **Text mode:** the query's unicode61 sub-tokens become quoted phrases joined with AND, so FTS syntax cannot be injected. Search runs over `fts_chunks`, filtered by branch, ranked by BM25.
  - **Regex mode:** `google-re2` with `max_mem` 8 MiB, patterns of at most 512 characters, at most 32 MiB scanned per call, and cancellation checked per block. Compile errors (backreferences, lookaround) are reported explicitly. There is never a fallback to Python `re`.
  - **Scope:** `hidden` (the default, using `recall.candidates` on the current view; it excludes system messages, which are always in view) or `all`.
  - **Results:** 10 hits per page, each with address, turn, role, tool, line range and a snippet of at most 200 characters. The cursor binds the branch hash, query hash and cutoff seq, so pages stay stable as the archive grows.
  - Recall results are never searched.
- **`palimnesis_catalog(cursor?, page?)`**
  - It returns `catalog.first`, `next` or `page` as `Page.text`, p=20 entries of at most 48 tokens each.
  - Pages are ordinary tool results, so P stays 0 and catalog navigation is never a prefix-invalidation cause (D20.3 kept).
- **Recall results in other subsystems (D60).**
  - They are excluded from the FTS index and from excerpt candidates.
  - They are always linked in transcripts and flagged `internal`.
  - Once out of view they are masked like any tool output; there is no separate recall buffer.

### 2.6 Reasoning carryover

- **Upstream.** Every generation's reasoning is archived separately and rendered for every part, since the pinned template renders all earlier reasoning (§9).
- **Client.** The composite's reasoning is the concatenation in stream order. How OpenCode stores and resends reasoning that resumes after text is **unverified** and goes to harness probe H1.
- **Goldens:**
  - continuation tokens equal what the model saw;
  - the next user turn appends;
  - a restart re-renders the same tokens.

### 2.7 Cache accounting (§10)

- **New cause `internal_continuation`.** It covers an append-shaped call inside one visible response. Other causes (for example a watermark move) are joined with commas.
- **Injection** is recorded once as `tool_change,view_format_change`.
- **Call ids** become `attempt_id#k`.
- **`_rerender`** uses `continuation_items` and the fixed tools.
- **Expected reuse is not assumed.** Whether Strata can reuse the generated tokens of the previous call, beyond the generation-start checkpoint, is **unverified** and is measured by P3.

### 2.8 Evidence to collect first (S0)

**Strata, on Zeus.**

| Probe | Question |
|---|---|
| P1 `p17_tool_stream_shapes.py` | First-delta name and parallel indices on Control 0.2.3.1; content after a call; `length` during arguments |
| P2 `p18_small_limit_thinking.py` | The "25% wrap-up" rule at limits from 512 to 4096 (marked [docs] today) |
| P3 `p19_continuation_cache.py` | `cached_tokens` for a continuation against `StrataCacheModel` |
| P4 | Cancel during a second call, and release time |

**OpenCode, adapter side.** H1 `opencode_hidden_stream_probe.py` uses a scripted fake upstream to check:
- a composite stream: interleaved reasoning and text, rewritten ids, re-indexed calls;
- a text-only `length` stop;
- an in-stream error raised mid-continuation, and the flattened resend that follows.

Facts from H1 go to `harnesses.md`, not into core.

**Dependency.** `google-re2` 1.1.20251105 installs from a cp312 Windows wheel and rejects backreferences with an explicit error (checked 2026-10-26). On a rejected pattern it also writes an absl log line to stderr, which must stay out of operational logs.

### 2.9 Evaluation

**Arms:**
- 1: native compaction;
- 4: Phase 3 as frozen in D43;
- 5: excerpts plus hidden tools, using the arm selected from the matrix. Transcripts are still projected but not advertised (O-B2).

**Development** (32K emulated with `--input-budget 24320` on Zeus at 65536, per O2):
- matrix arms A–D (with s0 for arm D, D16.2) on the dev needles through the emulator;
- the top two arms on 5 development tasks: dev-t1..t3 plus new dev-t4 (a restart) and dev-t5 (a long agentic turn with information needs that arise mid-task). They are written from A1's categories, not from the content of ho-t*.
- The caps are selected and then frozen in `affordances.md` and a decision entry.

**Fresh held-out set (O-B1).**
- ho2-h1..h12 (120 needles) and ho2-t1..t5. Seeds and themes are disjoint from dev and ho, and the set is committed before any 3B run.
- Arms 1, 4 and 5 run at 32K (Zeus relaunched, D49), then arm 5 is reported at 64K.

**Metrics.** Everything A1 lists, plus:
- internal calls by tool;
- invalid-id rate;
- unnecessary calls;
- lookups, counted as internal plus harness calls.

**Slot time** (estimate): about 4 h of development needles, about 10 h of development tasks, about 25 h of held-out runs.

## 3. Slices

| # | Slice | Depends on |
|---|---|---|
| S0 | Probes P1–P4, H1, RE2 install check | — |
| S1 | `assemble.py` (pure) and Strata-shaped tool streams in `tests/fake_upstream.py` (from `sse_oa_tool*.sse`) | S0 |
| S2 | Composite storage: `load_archived`, `reconcile`, `_upstream_body` call-order rendering, the D13 skip | — |
| S3 | Reserved names, tool injection fixed at first mask, F counting | — |
| S4 | `recalltools.py`: recall, catalog, grep (FTS and RE2) | S0 |
| S5 | The loop in `archive._run`/`_stream`/`_buffered`: mixed, parallel, malformed, caps, allowance, deadline, cancellation; fix the R25-A race | S1–S4 |
| S6 | Cache accounting, `replan` and `--explain` for continuations | S5 |
| S7 | Reasoning goldens and restart | S5 |
| S8 | Exclusions (FTS, candidates, transcripts); R25-E path fixes if O-B5 | S2 |
| S9 | Eval: arm 5 config, internal metrics in `report.py`, dev-t4/t5, ho2 generation | S5 |
| S10 | Development matrix and freeze | S6–S9 |
| S11 | Fresh held-out at 32K (gate), 64K report | S10 |
| S12 | Contracts, three reviews, `results/`, tag `phase-3b` | all |

## Requirement → test / measurement / deferral

Seams: P pure · S store · H HTTP through the fake upstream · E eval · L live · D docs.

| Requirement | Test or measurement | Seam |
|---|---|---|
| Internal calls and results never external | `test_internal_call_and_result_never_reach_the_client_stream`, `test_non_streaming_hidden_continuation_returns_only_external_content`; leak scan on every archive | H, E |
| One visible message across continuations | `test_continuation_stream_keeps_first_id_and_single_terminal`; `test_assembler_suppresses_role_finish_done_and_remaps_indices` | H, P |
| Accompanying text never retracted | `test_text_before_internal_call_stays_visible_and_archived` | H |
| Mixed calls | `test_mixed_calls_resolve_internal_emit_external_reindexed`, `test_next_request_renders_results_in_call_order` | H |
| Parallel internal calls | `test_parallel_internal_calls_all_resolved_before_one_continuation` | H |
| Malformed arguments | `test_malformed_internal_arguments_get_error_result_and_count`, `test_malformed_external_arguments_relayed_unchanged` | H |
| Reserved names | `test_client_tool_named_palimnesis_rejected_before_acceptance`, `test_unknown_palimnesis_name_is_internal_error_never_forwarded` | H |
| Disconnect and cancellation prevent continuation | `test_disconnect_during_continuation_closes_upstream_records_cancelled`, `test_disconnect_during_internal_resolution_starts_no_continuation`; P4 release | H, L |
| Retry and reconciliation | `test_keyless_retry_after_failed_continuation_skips_superseded_internals`, `test_flattened_composite_partial_matches_in_stream_order`, `test_composite_resend_reconciles_with_external_calls_only` | H, P |
| Allowance shared, never reset (§7) | `test_allowance_shared_across_continuations_property`, `test_exhaustion_before_continuation_ends_with_length`, `test_length_during_external_arguments_withholds_call`, `test_exhaustion_after_several_continuations` | P, H |
| Deadline across continuations | `test_deadline_during_continuation_cancels_and_errors`; R25-A race fixed | H |
| Caps | `test_call_cap_returns_limit_result_then_length_stop`, `test_recall_result_capped_by_remaining_room` | H, P |
| Every continuation fits | `test_every_continuation_recounts_within_budget_and_capacity`; 0 over budget in eval | H, E |
| Exact reconstruction (empty, multibyte, WTF-8) | `test_recall_pages_reassemble_exactly_property` | P, S |
| Invalid ids never substitute | `test_recall_unknown_and_ambiguous_ids_return_errors_with_suggestions`; invalid-id rate | S, E |
| Full-text grep and code punctuation | `test_grep_text_quotes_operators_and_code_punctuation`, `test_grep_scoped_to_session_branch`, `test_grep_hidden_scope_excludes_in_view_and_system` | S |
| RE2 regex | `test_grep_regex_multiline`, `test_grep_regex_backreference_rejected_no_fallback`, `test_grep_regex_scan_caps_and_cancellation`, `test_re2_imports` | S, P |
| Catalog navigation bounded and complete | `test_catalog_tool_pages_reach_every_occurrence_within_page_cap` | S |
| Reasoning goldens | `test_hidden_continuation_rendered_tokens_golden_then_next_turn_then_restart` | P, H |
| Deltas early; tool blocks hidden until classified | `test_text_and_reasoning_deltas_forwarded_before_upstream_completes`, `test_external_call_buffered_until_complete` | H |
| Commit before forward; stalled writer | `test_continuation_batches_commit_before_forward`, `test_stalled_reader_during_continuation_bounded_and_closed` | H |
| Usage reporting (§7) | `test_final_usage_sums_completion_and_internal_totals_recorded` | H |
| §10 causes | `test_continuation_cause_internal_continuation`, `test_tool_injection_records_tool_change_once`, `test_rerender_of_continuation_call_after_restart`; `--explain` with 0 unexplained | H, E |
| Injection byte-stable and counted | `test_hidden_tools_fixed_at_first_mask_and_counted_before_acceptance` | H |
| Recall results not indexed; transcripts lossless | `test_internal_results_not_indexed_or_excerpted`, `test_transcript_links_internal_results_and_verifies` | S |
| Affordance matrix and freeze | S10 per the `affordances.md` rule | E |
| Needles and recall/restart coding task | S11 fresh gate (O-B6) | E, L |
| Repeated streaming key | Existing test (class a) | H |
| FIFO, 429, slot across continuations | Deferred to Ph4B (O4); foreign activity per continuation measured | D, E |
| Anthropic assembler; Pi and Claude Code | Deferred to Ph4B (no archive route for Messages yet) | D |

## Contract text changes

- **§2.** P stays 0. Injected schemas count in F. Result caps follow the remaining room.
- **§3.** The reserved `palimnesis_` prefix.
- **§5.** D covers continuations; comments are relayed.
- **§7.** Status becomes [enforced], with A cap ≠ R.
- **§8.** A known limit: the proxy does not hold the slot between continuations (Ph4B).
- **§9.** Reasoning per generation; composite reasoning in stream order.
- **§10.** The new cause `internal_continuation`.
- **§11.** Internal results immutable, never indexed; superseded parts never spliced.
- **§13.** Recall results are never candidates.
- **§14.** Recall results linked and flagged.
- **New §15, Hidden recall tools.**
- **`capabilities.md`.** A hidden-recall row per harness: OpenCode supported after H1; Pi and Claude Code Ph4B.

## New decisions (recommended as above)

- **D51** Composite visible turn.
- **D52** Assembler rules.
- **D53** Mixed calls and call-order results.
- **D54** Injection at first mask; reserved prefix.
- **D55** Caps and the `length` stop; tool removal rejected.
- **D56** `allowance_cap`.
- **D57** Recall semantics.
- **D58** Grep semantics.
- **D59** Catalog as tool results, P = 0.
- **D60** Recall-result exclusions.
- **D61** Visible usage.
- **D62** The 3B held-out protocol, written before any run (mirrors D44).

## Open decisions for the user

- **O-B1 Evaluation legitimacy.** (a) A fresh held-out set as the gate. (b) Reuse the R25 set, report only. (c) Both. Recommendation: (c). The gate is judged on the fresh set (ho2). Arm 5 on the old set runs only after that verdict, labelled "seen set, not evidence".
- **O-B2 Arm 5.** Recommendation: excerpts plus hidden tools, with the matrix addendum and no a3. A combined arm 6 only if slot time allows.
- **O-B3 Allowance.** Recommendation: `allowance_cap` 24,576 and OpenCode `limit.output: 24576` (an adapter config change), with R kept at 8,192.
- **O-B4 Matrix staging.** Recommendation: screen all 4 arms on development needles, then run the top 2 on 5 development tasks. This deviates from the predeclared "5 tasks per arm" and would be recorded.
- **O-B5 R25-E transcript fixes before the fresh baseline** (a stable in-progress name, turn 0 marked as the system prompt). Recommendation: yes, so that arm 4 is a fair comparison.
- **O-B6 Gates.** Recommendation: D44's gates unchanged, on ho2 at 32K (needles ≥ 85%, arm 5 coding ≥ arm 1, the restart task passes), plus invalid ids ≤ 5% and 0 internal leaks; one attempt per task. Alternative: two attempts per task, at about twice the slot time.
- **O-B7 Regex engine.** `google-re2` installs (§2.8), so regex mode uses it; no `regex`-module compatibility mode in 3B.
- **O-B8 Anthropic Messages assembler.** Recommendation: defer to Ph4B.

## Delta: user decisions (2026-10-26)

- **O-B1:** (c). A fresh held-out set (ho2) is generated and committed before any 3B run, and it alone decides the gate. Arm 5 on the R25 set runs only after the verdict, labelled "seen set, not evidence".
- **O-B6:** D44's gates on ho2 at 32K, plus invalid ids ≤ 5% and 0 internal leaks; one attempt per task.
- **O-B3:** `allowance_cap` 24,576, with the shipped OpenCode config's `limit.output` raised to 24576; R stays 8,192.
- **O-B5:** the R25-E transcript fixes land before the fresh baseline, so arm 4 runs with them.
- **O-B2, O-B4, O-B8:** taken as recommended (arm 5 as excerpts plus hidden tools without a3; screen the matrix on development needles, then the top 2 on 5 development tasks, recorded as a deviation; Anthropic assembler deferred to Ph4B).
- **O-B7:** settled by the install check (§2.8).

## Delta: S0 findings (2026-10-26; `docs/probes/strata.md` §12, `docs/probes/opencode_hidden_stream.md`)

1. **A call ends at the next index, the finish chunk, or a content delta.** With thinking on, Strata can stream text after a call (P1 c). The assembler treats a content delta as the end of the call before it. Text after an *internal* call is held with that part: it is visible text, forwarded and archived with the part, and the continuation still runs. `unsupported_mixed_form` is dropped. Text after an external call passes through as today; OpenCode stores it before the call, so a re-render then differs from the generated token order (inferred, recorded as a known limit).
2. **Partial composites flatten as all reasoning, then all text** (H1 c), not in stream order. Implemented in S2: `transcript.flattened`. Completed composites resend reasoning R1+R2 and text T1+T2 (H1 a), as planned.
3. **A `length` stop makes OpenCode send a follow-up turn at once** (H1 b), with a synthetic user message asking it to break the work into smaller pieces. The cap rule stays a `length` stop (contracts §7). The follow-up is a new instruction with a fresh allowance; this goes in `harnesses.md`.
4. **Continuation limits below 1024 get no thinking budget** (P2): the call can end in `length` with reasoning only. A continuation is therefore started only with at least 1,024 tokens of allowance left; with less, the response ends with `length` before the call.
5. **A continuation reuses prompt1 + completion1 − 1 tokens** on an idle server (P3). `StrataCacheModel` gains an append rule for `internal_continuation`: the expected reuse is the previous call's prompt plus its generated turn.

## Delta: review fixes (2026-10-26)

The protocol review and cache audit of S1–S8 found 2 blockers and several should-fix items; all are fixed test-first (`tests/test_hidden_loop_http.py`, `tests/test_composite.py`, `tests/test_assemble.py`). Corrections to this plan:

- **§2.2, D53.** Hidden results render in the order of the calls, among the client's results, because the pinned template pairs results by position (the plan's "call order" holds; D53's wording is corrected).
- **§2.7.** A move during a response is recorded by its own cause (`watermark_move`, `collapse`, ...), not joined with `internal_continuation`, which marks a pure append inside one response (contracts §10).
- **S0 delta 5 is not implemented.** `StrataCacheModel` still estimates a continuation's reuse at the previous generation-start checkpoint, 41–70 tokens low (P3). The value is labelled an estimate and no class depends on it.
- **Text after a hidden call** re-renders before the call (one content field per message), so a continuation's prompt differs from the generated order from there on. Recorded as a known limit beside the external-call case.
- **Requests without the tools** (`tool_choice: "none"`) in a session that has them still go through the hidden loop, so a copied `palimnesis_*` call is answered, never relayed; dropping the tools from such a request and restoring them costs two full re-reads (known limit).

## Delta: R29 fixes before D64 (2026-10-27)

Neither arm-5 variant matched arm 1 on the development tasks (R29). Every arm-5 miss lost a rule or note the user had typed:

| Miss | Rule or note that left the view | Recalled? |
|---|---|---|
| dev-t2 a5-D, C2 | turn-1 rules, gone by call 11 | never |
| dev-t3 a5-C, C1 | turn-1 rules, absent from call 52 | never |
| dev-t5, both arms | turn-3 vendor note | a5-D never; a5-C did, then lost track of it |

Two features of the proxy made it worse and caused both 30-minute timeouts:

- **Grep over the model's own reasoning.** It returned the model's earlier inventions as hits.
- **The per-response lookup cap ending in `length`.** OpenCode answered with a follow-up message that reset every count.

The user chose all three fixes below. Slice S10b lands them test-first; the top two arms then re-run, with the fixes, on the development needles (3 repeats) and the 5 development tasks before D64.

**F1 (D65): instructions stay in view.**
- `ViewPolicy.pin_tokens` (default 0, off), set with `serve --pin-instructions TOKENS`; the arm-5 development configurations set 4,096.
- **Pinnable:** a user message that is an instruction (`turns.is_instruction`) and whose own content is at most 1,024 tokens. An attached excerpt block never counts.
- **At each collapse move,** pinnable messages behind the new boundary stay verbatim in place, newest first, while their total fits `min(pin_tokens, input_budget // 6)`. They break span runs, as kept messages already do. The rest are absorbed.
- **The kept set changes only at collapse moves,** so it is recorded with the move (cause `collapse`) and rebuilds are identical. A message absorbed once stays collapsed.
- **Last resort:** when the view is still over the input budget, the collapse absorbs pins too.
- **Unchanged:** masking never rewrote user messages, and R1 still gives excerpts only to hosts at or after the watermark.

**F2 (D66): grep skips reasoning.**
- `palimnesis_grep` never searches `reasoning` blocks, in either scope.
- `palimnesis_recall` still returns them by address.
- Reason: the model's unverified reasoning, returned as a search hit, reads as evidence. This follows D60's exclusion of hidden results.

**F3 (D67): lookup budget per instruction.**
- **Follow-up is synthetic.** `turns.SYNTHETIC_USER_PREFIXES` gains OpenCode's length follow-up, "Your last response hit the output token limit (stop reason: length).", as a recorded harness string beside the interrupted-response prompt (`harnesses.md`). So the follow-up starts no turn: transcript turn numbers and the excerpts' "now turn N" no longer advance, and it hosts no excerpt.
  - This amends S0 delta 3: each response still gets a fresh allowance.
- **Budget.** At most 16 answered hidden calls per turn: from the latest instruction in the branch, counting archived internal results after it (refusals excluded) plus the calls already answered in this response.
  - Sixteen covers every clean turn observed: needle questions used at most 14 and clean task turns at most 8. The two runaway turns used 29 and 59.
- **When spent,** each further hidden call gets "limit reached: no more archive lookups until the next user message. Continue from what you have." It counts as refused under the existing rule, so a further hidden call in a later continuation ends with `length`.
- **Unchanged:** the per-response limits of §2.4.

## Delta: D64 freeze (2026-10-27)

S10 is closed. The fixes were re-run on development data (R30), and the user froze `a5-Dp` as arm 5 (D64).
- **S11** runs `a5-d64` = `a5-Dp`. It needs Zeus relaunched at `n_ctx` 32768 with the pin and canary passing (D62.1).
- **S12 gains one step**, taken only if D62's gates pass:
  - `serve`'s defaults become a5-Dp as a whole (`s0`, `a1`, `t2`, `--pin-instructions 4096`);
  - the shipped OpenCode config's `limit.output` becomes 24576;
  - `a4-d43` names Phase 3's stub, tools and pins itself.

  Until then the defaults stay Phase 3's (D64.5).
