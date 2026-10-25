# Phase 2 plan: bounded view, catalog and cache instrumentation

Planner output, 2026-10-24, after `phase-1`. Decisions are recorded at the end and in `docs/decisions.md` once resolved.

## Core positions

1. **The view is always built and counted.** Every request goes through the view builder, so budgets hold on every call (§2).
   - Below the high watermark the view is the full history, and its upstream body is the client's `req.raw` byte-for-byte (fast path).
   - Masking starts only when the view would cross the high watermark. Such sessions fail today at Strata's `n_ctx` 400, because OpenCode's shipped config never compacts.
   - `--view off` keeps counting and budget errors but never masks.
   - OpenCode's message structure is unchanged, and reconciliation still runs against the client's full resend.
2. **The upstream body is a render of the view** (supersedes D10.9). Messages come from the archive under a persisted view version. When the rendered messages are JSON-equal to the client's and no settings are rewritten, `req.raw` is forwarded unchanged.
3. **Masking decisions are persisted and monotone.** Each is an immutable `view_versions` row, so a restart reproduces identical tokens. A masked item stays masked until Phase 3 recall.

## Modules

### `palimnesis.pins`

Vendored `pins/strata-0.1.48/` holding:
- `chat_template.jinja` (sha256 `12827f…`);
- Qwen `tokenizer.json`;
- `PIN.json` with build_info, the sha256s, the tokenizer revision and Strata's preprocessing rules (bare tools, string arguments parsed to mappings, `reasoning_content`).

All of it is verified when loaded.

### `palimnesis.tokens`

- `render(messages, tools, effort, enable_thinking)`: jinja2 `ImmutableSandboxedEnvironment` with HF `tojson` (`ensure_ascii=False`, no key sorting). This is p02's renderer, moved into the package.
- `count(text)`.
- Fragment cache: the render is split before each added special token, and fragment counts are cached by `sha256(fragment) + pin_id` in an in-memory LRU plus a derived `token_counts` table.
- Startup self-test of fragment additivity, falling back to full counts.
- The final count before dispatch is always exact.

### `palimnesis.upstream_facts`

- `GET /props` at startup. Facts are marked stale after a transport error, a 5xx, or a context-window 400, and re-read before the next build. They are fetched lazily if the upstream is unreachable at startup.
- A pin mismatch puts the proxy in **view-disabled mode**: archive and forward the client body as in Phase 1, with diagnostics.
- A startup canary compares local counts with `POST /v1/messages/count_tokens`.

### `palimnesis.budget` (pure)

- `R_req = min(client limit or R_cap, R_cap)`.
- `B_in = min(configured, n_ctx − R_req − M_eff)`.
- `check_fixed(F)` raises `BudgetError(terms)` when F (system, bare tools, current user, preamble) leaves no room.
- Startup floor: `F_min + min_recent + R + M ≤ n_ctx`.
- The upstream `max_completion_tokens` is set to `R_req` when absent or above the cap, so Strata's silent clamp never fires.
- The budget snapshot rides on the `Plan`.

### `palimnesis.view` (pure; ARC and Complexity Trap)

`build(archived_branch, prev_view_version, facts, budget, policy, counter) -> View`. It takes no HTTP client.

Components follow ARC's `K = B + M + R + P + Q + η`:

| Component | Content |
| --- | --- |
| B | System and tools; non-evictable |
| S | Pinned state; 0 until Phase 4A |
| M_mask | The masked region's representation |
| R_recent | Recent window, verbatim |
| P | Catalog page; reserved in Phase 2, rendered empty |
| Q | Recall slot; reserved in Phase 2, rendered empty |

Rules:
- **Groups.** An assistant message with `tool_calls` and all of its tool results form one unit. Boundaries fall only between groups or at user messages.
- **Masking tiers, oldest first, before watermark W:**
  1. Tool results over ρ = 64 tokens become stubs; shorter ones stay inline (ARC).
  2. Reasoning becomes a reasoning stub.
  3. When stubs alone cannot reach the target, the oldest masked span collapses into one proxy-authored user-role span note naming its alias range. *As built, ARC's intermediate bare-id tier is skipped (D16.6).*
- **Oversized newest output** is masked in place with a head/tail stub. It is already archived, because accept commits first.
- **Non-evictable overflow** gets a structured error, never truncation.
- **Reasoning carryover (§9).** Archived reasoning is rendered for every assistant turn:
  - flattened partials are split at their extent;
  - superseded partials are excluded;
  - internal occurrences are spliced at their aligned position, except those of superseded attempts.
- **Output:** `View(messages, manifest, tokens, view_version, components)`, where the manifest lists `(occ_id, form, token_range)`.

### `palimnesis.stubs` (pure)

- Format `s1`: `[palimnesis s1 §K7Q2MX.0 tool_result · 18,432 tok · 412 lines · sha 3f9a1c]`, a head preview of at most 192 tokens, `…[N tok not shown]…`, and a tail preview of at most 96 tokens.
- `chunks(text, max_tokens)` yields `{offset, length, total_length, encoding, sha256, next_offset}`.
- Cuts land on code-point boundaries and back off over combining marks, ZWJ and variation selectors.
- Sizing is by binary search over character cuts, so no U+FFFD is ever produced.

### `palimnesis.watermark` (pure)

Units are exact rendered tokens.

- Maskable capacity: `C = B_in − P − Q − F`.
- Trigger: the view is above `H = F + h·C`.
- Then W advances, masking oldest first, until `I ≤ T = F + t·C`. The window never shrinks below `min_recent` (4,096) plus the current group.
- Hard rule: `I ≤ B_in`.
- Each move inserts an immutable `view_versions` row (migration 3).

### `palimnesis.catalog`

- Entries cover every occurrence, flagged (masked, superseded, internal): `§alias seq role kind tokens flags preview`.
- A page holds p entries of at most c tokens each.
- Opaque keyset cursors over `UNIQUE(branch_id, seq)` read at most p+1 rows. `first`, `next` and `page(k)` are provided, so every entry is reachable in ⌈N/p⌉ pages.
- CLI: `palimnesis catalog`.

### `palimnesis.cacheacct`

- For each upstream call, an immutable `upstream_call` event records:
  - `view_id`, local I, `prompt_tokens`, `cached_tokens`, `prompt_ms`;
  - `lcp_tokens` against the previous call on the branch, plus the global predecessor;
  - the first differing manifest segment, the cause, `expected_reuse_est` (labeled an estimate) and the reuse class.
- Causes: system change, effort or thinking change, tool change, watermark move or collapse, model or template change, view policy or format change, capacity or budget change. Anything else is **unexplained**.
- Reuse classes: full / append, checkpoint-limited, restart or eviction.
- Previous-call tokens are kept in memory and recomputed by deterministic re-render after a restart.

### Drift (§1.3)

- Every call compares local I with `usage.prompt_tokens`.
- A difference sets `M_eff = M + 2·max recent drift`, capped at 2048.
- 3 consecutive drifts, or one drift over 1024, switches to view-disabled mode.

### R8 fix

An in-process `BranchCache`, validated per request by `(count, max seq)` and extended incrementally, makes accept's database work O(new messages).

### Budget error

`400 context_budget_exceeded`, `x-should-retry: false`, naming F, R, M and `n_ctx` with their values. It is raised before acceptance, so nothing is archived.

## Requirement → test

Seams: P pure · S store · H HTTP through the fake upstream · E eval · L live · D docs.

Fixtures:
- RF: `render_*.txt` and `template_render_check.json`.
- LV: the 10 live bodies with their usage.
- SYN: generated sessions.

| Requirement | Tests / measurement | Seam |
| --- | --- | --- |
| GL1: fits or structured error | `test_view_never_exceeds_budget_property`, `test_every_upstream_body_recounts_within_budget_and_capacity`, `test_fixed_overhead_overflow_400_context_budget_exceeded_nothing_archived`, `test_budget_error_names_terms_should_retry_false`, `test_upstream_max_completion_tokens_capped_to_reserve` | P, H |
| GL2: oversized newest output | `test_oversized_newest_tool_output_archived_exact_then_stubbed` | H+S |
| GL2: user / system / schemas | `test_oversized_current_user_input_rejected_not_truncated`, `test_oversized_system_or_tools_rejected`, `test_old_oversized_user_message_masked_as_history` | H |
| GL2: Unicode | `test_stub_preview_cuts_unicode_safe`, `test_chunks_roundtrip_with_metadata`, `test_token_sizing_never_emits_replacement_char` | P |
| GL2: many small messages | `test_5000_one_word_turns_collapse_to_span_within_budget`, `test_tool_groups_never_split_property` | P |
| GL3: versions and A/B matrix | `test_stub_s1_golden_text`, `test_affordance_versions_registered`, `docs/affordances.md` | P, D |
| GL4: catalog reach | `test_catalog_first_next_covers_every_occurrence`, `test_catalog_page_k_direct`, `test_catalog_page_token_bound_adversarial_previews`, `test_catalog_cursor_uses_index_rows_le_p_plus_1`, `test_catalog_cursor_stable_after_appends`, `test_bad_cursor_error_no_substitution` | S |
| GL5: zero upstream calls from the builder | `test_builder_signature_has_no_client` (socket-deny), `test_one_upstream_chat_post_per_client_request_when_masking` | P, H |
| GL6: every invalidation explained | `test_cause_*`, `test_unexplained_change_fails`, `eval/replay.py --explain` (LV and a 300-turn SYN session) | P, E |
| GL7: watermark frequency vs ingress | `eval/bench_view.py` (workloads × budgets; moves per 100K ingress tokens, reread per move, amortized reread) | E |
| GL8: reuse and prefill by cause | live forced-budget OpenCode run; `test_checkpoint_limited_classification`, `test_restart_eviction_classified` | L/E, P |
| §1.1 | `test_props_read_at_startup`, `test_props_refreshed_after_5xx_transport_error_context_400` | H |
| §1.2 | `test_template_hash_mismatch_view_disabled_archive_continues`, `test_build_info_mismatch_…`, `test_canary_count_mismatch_…` | H |
| §1.3 | `test_local_render_equals_render_fixtures_text`, `test_local_count_equals_check_json`, `test_local_count_equals_live_usage_prompt_tokens`, `test_fragment_sum_equals_full_count`, `test_drift_raises_margin_then_disables`, `test_startup_canary_uses_count_tokens` | P, H |
| §2 floor and capacity change | `test_startup_floor_failure_names_terms_view_disabled`, `test_n_ctx_change_recomputed_before_next_call`, `test_in_flight_keeps_admitted_budget` | H |
| §9 (without recall) | `test_view_reinserts_reasoning_client_omitted`, `test_view_tokens_equal_client_tokens_on_live_bodies`, `test_restart_rebuilds_identical_view_tokens`, `test_flattened_partial_split_superseded_excluded`, `test_internal_occ_of_superseded_attempt_not_rendered` | P, S, H |
| §9 recall continuations | deferred to Phase 3 | — |
| §10 | cacheacct tests, `test_upstream_call_event_fields` | P, H |
| Masked spans keep addresses | `test_every_masked_item_has_resolvable_alias_and_catalog_entry` | S |
| R8 | `test_accept_sql_statements_constant_over_200_turns`; bench_archive TTFB flat | S, E |
| Builder latency | bench_view: build + count p95 ≤ 30 ms at 48K, warm | E |
| §7, §8, keepalives, recall | deferred to Phase 3 | — |

### Phase 3 A/B matrix (defined now, run in Phase 3)

Arms:

| Arm | Stub | Addendum | Tool description |
| --- | --- | --- | --- |
| A | s2 head/tail | a1 | t1 terse |
| B | s3 (s2 plus inline recall hint) | a1 | t1 |
| C | s2 | a0 (none) | t2 guided |
| D | s1 (alias and size only) | a1 | t2 |

- **Data:** stratified development needles, labeled recall-needed and recall-unneeded situations, and 5 development coding tasks. Runs are paired, with prompts fixed per arm.
- **Metrics:** retention, appropriate recall, unnecessary calls, invalid ids, task success, added tokens, latency.
- **Selection rule:**
  1. Reject arms with an invalid-id rate above 5%.
  2. Rank by retention.
  3. Break ties by fewest unnecessary calls, then by tokens.
- **Freeze** the selected arm before held-out runs.

## Slices

| # | Slice | Depends on |
| --- | --- | --- |
| 1 | Pins and `tokens` (vendored assets, goldens, fragment additivity) | — |
| 2 | `upstream_facts`, fake `/props` and `count_tokens`, view-disabled mode, canary | 1 |
| 3 | `budget`, pre-acceptance 400, `R_req` cap, floor | 2 |
| 4 | `BranchCache` and token-count cache (R8) | — |
| 5 | View render without masking: carryover, partials, internal splice, raw fast path; replaces `ledger._upstream_body` | 1, 4 |
| 6 | `stubs` and `chunks` | 1 |
| 7 | Watermark, tiers, groups, oversized newest, collapse, `view_versions` | 3, 5, 6 |
| 8 | Catalog and CLI | 6 |
| 9 | Cache accounting, causes, `replay --explain` | 5, 7 |
| 10 | Drift reconciliation | 2, 9 |
| 11 | `affordances.md` and version constants | 6 |
| 12 | Measurements: bench_view, bench_archive rerun, live forced-budget run | 7, 9, 10 |
| 13 | Docs; protocol, cache and paper-fidelity reviews | all |

## Risks

- **Re-prefill per watermark move.**
  - At most 6 checkpoints are kept, so after a move reuse often falls back to the system root (~5K tokens). That means rereading about T tokens: ~25K at a 48K budget, ~50 s warm and up to ~3 min cold.
  - Strata's keepalives prevent timeouts, but the delay is visible.
  - Probe whether `strata_checkpoint` can pin the stable boundary.
- **No recall in Phase 2.** Masked detail beyond the previews is lost to the model. Listed as a known limit.
- **Renderer drift from Strata's preprocessing.** Covered by LV goldens plus per-call usage reconciliation.
- **Fragment additivity.** Checked by a self-test, with full counting as the fallback.
- **`/props` while Strata is busy** is unverified. Probe it in slice 2; use a 1 s timeout and fall back to cached facts.
- **OpenCode's daily date change and effort changes** invalidate the whole prefix. They are allowed causes and are reported.

## Paper fidelity

**Follows ARC:**
- stubs with id, metadata and previews;
- ρ inline threshold;
- deterministic, LLM-free masking and collapse (the bare-id tier is skipped, D16.6);
- the K decomposition;
- the paged catalog;
- proactive budgeting before each call. *Correction:* ARC's proactive mode estimates prompt length; exact counting with the pinned template is a Palimnesis adaptation.

**Follows Complexity Trap:** deterministic observation masking, keeping actions.

**Documented adaptations:**
- Hysteresis watermarks instead of a per-turn rolling window, to protect prefix and checkpoint reuse.
- Reasoning stubs and span collapse, because the template renders all reasoning and bare ids forever are unbounded.
- *Superseded by A1:* P reserves nothing until Phase 3B (D20.3); Q is the `recall_excerpts` allocation (D20.2), empty in production only because the Phase 2 source selects nothing.
- Token budgets instead of character budgets.

## Decisions

Resolved as D14 in `docs/decisions.md`.

## Delta (after A1 and amended D15, 2026-10-24)

Slices 1–8 and 11 stand as built. The remaining work is the new slices A–F, plus updates to slices 9, 10, the CLI, measurements and docs.

### Findings

- **Special-token injection.** The tokenizer extracts added tokens such as `<|im_start|>` from raw text, so excerpt escaping must cover the profile's added-token strings as well as the block delimiters.
- **Kept messages accumulate.** User messages in `ViewState.kept` never collapse, which conflicts with A1's "older spans may leave the active view". A later collapse move must be able to absorb them.
- **Floor check unwired.** `check_floor` is never called at startup.
- **Selection seam needed.** Phase 3 must persist its excerpt selection before inference, so Phase 2 provides that seam.

### Slices

| # | Slice | Depends on |
| --- | --- | --- |
| A | Upstream-profile seam: `palimnesis/profile.py` Protocols (Counter, FactsReader, CrossCheck, CacheReuseModel, ErrorMap, TemplateRules), Strata moved to `palimnesis/upstreams/strata/`, boundary tests | — |
| B | Budget `recall_excerpts` (per-message and total caps, `Q_eff` falling to zero, excluded from thresholds and F) | A |
| C | Migration 4 (`excerpt_blocks`, `excerpt_items`, immutable), `excerpts.py` renderer x1 with reversible escaping, `turns.py` | A |
| D | View inclusion policy R1–R4 (whole-block, monotone omission at threshold events only, all omitted before a BudgetError), `omitted_excerpts`, `evicted_now`, `kept` collapse fix | B, C |
| E | `ExcerptSource` seam (`NoExcerpts` / `SeededExcerpts`), selection persisted before inference, BranchCache, `after_excerpt_commit` crash point | D |
| F | Gap tests: floor wiring, `n_ctx` change, socket-deny builder, one POST per request, tool-group property | A |
| 9 | Cache accounting, Strata reuse model behind the profile, excerpt causes, `replay --explain` | A, E |
| 10 | Drift via `profile.cross_check.usage`; excerpt allocation recomputed | 9 |
| CLI | `--view`, `--input-budget`, `palimnesis catalog`, `palimnesis excerpts` | E |
| 12 | `bench_view` with excerpt arms, `bench_archive` rerun, live forced-budget run, live excerpt replay | 9, 10, CLI |
| 13 | Docs; protocol, cache and paper-fidelity reviews; tag `phase-2` | all |

The full requirement → test table is in the planner's report and is recorded as D20/D21 as each slice lands.
