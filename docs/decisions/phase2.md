# Decisions: Phase 2 (D14–D25)

[Index](README.md) · Material choices, their reasons and rejected alternatives; newest last.

## D14 — Phase 2 design decisions (user, 2026-10-24)

From `docs/plan/phases/phase2.md` §Decisions. The user chose items 1–3 and accepted the planner's recommendations for the rest.

1. **Masking is overflow-triggered, before Phase 3 recall exists.** The view is always built and counted. The client body is forwarded byte-identical until the view would cross the high watermark. Past it, masking is deterministic and oldest-first with stubs and stable aliases, under hysteresis. `--view off` disables masking but keeps budgets. Masked detail beyond the stub previews is not model-recallable until Phase 3; this is a known limit.
2. **Pins are vendored.** The Qwen `tokenizer.json` and the chat template live in `pins/strata-0.1.48/` with SHA-256s and are verified on load.
3. **Input budget cap is 48K.** `input_budget = min(48000, n_ctx − R − M)`: 24,320 at 32K capacity, 48,000 at 64K.
4. **Catalog and recall slots are reserved now:** P = min(1024, 5%·B_in) and Q = min(4096, 10%·B_in), rendered empty in Phase 2.
5. **Stubs.** Addresses are `§ALIAS.N`. Stub format `s1` is versioned, and a format change is a recorded, one-time invalidation.
6. **Watermarks:** H = 0.90, T = 0.50 of maskable capacity, with `min_recent` = 4,096 tokens. Revisit after `bench_view`.
7. **Catalog pages:** p = 20 entries of at most c = 48 tokens each.
8. **Cache accounting** lives in `events` rows. Token sequences are held in memory and re-rendered deterministically after a restart.
9. **Pin mismatch or floor failure** puts the proxy in view-disabled mode: archive and forward as in Phase 1, with diagnostics.
10. **Budget-rejected input** is rejected before acceptance; nothing is archived.
11. **Generation reserve:** `R_req = min(client limit, 8192)`. The upstream limit is rewritten when it is absent or above the cap, so Strata's silent clamp never fires.
12. **Masked reasoning** becomes a reasoning stub, a declared §9 view transform.
13. **Collapsed spans** become one proxy-authored user-role note. The template forbids non-leading system messages.
14. **Contracts §10 allowed causes** gain "view policy/format version change" and "capacity/budget change".

## D15 — Other model backends (llama.cpp and others) are a v2 item (user, 2026-10-24)

v1 keeps the plan's scope: one Strata instance. No upstream-profile abstraction is built in v1. `palimnesis.pins`, `palimnesis.upstream_facts` and the Phase 2 cache accounting stay Strata-specific.

**What v1 already offers another OpenAI-compatible server:** `--passthrough` works against any OpenAI-compatible server. Archive mode's session routing, reconciliation, archive and SSE relay key off the Chat Completions protocol, not the backend.

**What v2 needs for a new backend:** an upstream profile per backend and version, built from the profile's own probe suite (`eval/probes/` style), never from assumed defaults. It bundles:
- **Pins:** the chat template, tokenizer and preprocessing rules for the served model.
- **Facts reader:** context size, build and template identity. llama.cpp's `/props` is similar to Strata's, but each field needs verifying.
- **Counting cross-check:** e.g. llama.cpp `/tokenize` in place of Strata's `count_tokens`.
- **Cache-reuse model:** llama.cpp prefix reuse, not Strata's 6-checkpoint model. This feeds the expected-reuse estimates and the reuse classes.
- **Measured behavior:** error shapes, output-limit clamping, cancellation and slot release, keepalive cadence, reasoning carryover.

Rejected for v1: adding the profile seam during Phase 2. It is cheap but outside the v1 scope, and the user chose to defer it.

## D16 — Stub, chunk and catalog details (Phase 2 slices 6, 8, 11)

Choices made while implementing `palimnesis.stubs`, `palimnesis.catalog` and `palimnesis.affordances` that the plan left open.

1. **Stub s1 layout.**
   - A header, a head preview and a tail preview cut at safe character boundaries (snapped to whole lines when a line break falls inside a preview), then the closing hint `[archived exactly; not shown]`.
   - Text that fits within both preview caps is shown whole with no marker; empty text gets the header alone.
   - Reasoning stubs use 64/32-token caps.
2. **Arm D of the Phase 3 matrix gets its own format.** The matrix describes arm D's stub as "alias and size only", but s1 has previews. Arm D will use a header-only format `s0`, registered before Phase 3 runs. s1 is unchanged.
3. **Chunks.**
   - `sha256` covers the whole text, not the chunk.
   - Offsets count code points.
   - If not even one whole character fits the budget, the cut falls mid-character. The result is still exact on reassembly but is flagged; `ValueError` if not one code point fits.
4. **Catalog cursors.**
   - A cursor must sit on a page boundary, match the page size and belong to the branch.
   - Pages read at most p+1 rows through the `(branch_id, seq)` index.
   - `page(k)` relies on per-branch seqs being dense from 1 and raises if that breaks.
   - "Superseded" covers replaced context versions as well as `partial_superseded` partials.
5. **Masking must pay.** Texts within the preview caps (about 65–288 tokens) produce stubs no smaller than the original. The watermark logic stubs an item only when the stub is smaller.
6. **ARC's bare-id tier is skipped** (paper-fidelity review, Phase 2). ARC first collapses older stubs to bare `§id` references, then further. Palimnesis goes from s1 stubs straight to one span note naming the first and last alias of the run. Per-message bare references grow without bound, and that growth is what span collapse exists to stop. The middle aliases remain addressable and listed in the internal catalog, and the Phase 3 transcript files will expose them. `stubs.bare_ref` stays available for that.

## D17 — The project is named Palimnesis (user amendment 1, 2026-10-24)

*Palin* ("again") + *mnēsis* ("remembering"). The name echoes a palimpsest, a manuscript scraped and overwritten, and inverts it: in Palimnesis nothing is ever overwritten, and the original can always be read again.

The rename reaches the package and CLI (`palimnesis`), the headers `X-Palimnesis-Session` and `X-Palimnesis-Kind` (all `x-palimnesis-*` headers are stripped before forwarding), the env vars `PALIMNESIS_*`, the default archive `%LOCALAPPDATA%\palimnesis\palimnesis.db`, the OpenCode provider and plugin, docs and agent roles. Model-facing text follows: stubs read `[palimnesis s1 …]` and future tools are `palimnesis_*`.

Unchanged: the repo folder, git history, and recorded evidence (`eval/fixtures/`, `eval/probes/fixtures/`, the vendored pins), which must stay byte-exact. The release is pre-1.0, so there are no compatibility aliases.

## D18 — MIT license (user, 2026-10-24)

Palimnesis is MIT-licensed (`LICENSE`), matching Eunoe, the MIT project behind amendment A1. Vendored third-party files keep their own licenses: the Qwen tokenizer and chat template are Apache-2.0 per the model repository (`THIRD_PARTY_NOTICES.md`). Eunoe is credited as a design influence; if any of its code is ever incorporated, its MIT notice must be reproduced.

## D15 amended — upstream-profile seam in v1, llama.cpp profile later (user, 2026-10-24)

Supersedes D15's "no seam in v1" because amendment A1 names Strata *or* llama.cpp.
- Phase 2 builds a backend-neutral upstream profile, so budgeting, views and the A1 retrieval code do not depend on Strata specifics. The profile covers pins, facts reader, counting cross-check, cache-reuse model and error mapping.
- v1 ships and evaluates only the Strata 0.1.48 profile.
- A llama.cpp profile, with its own probe suite, remains later work. Until it exists, capabilities advertise Strata only.

## D19 — Amendment A1 adopted: proactive recall and transcript files (user, 2026-10-24)

`docs/plan/amendments/A1-proactive-recall.md` amends `docs/plan/v1_plan.md` from Phase 2 on. Consequences for work already done or planned:
- **Recall slot.** D14.4's reserved recall slot Q becomes the `recall_excerpts` allocation, with a per-message cap and an active-view total cap. It may fall to zero, never displaces non-evictable input, and never touches the generation reserve.
- **Excerpt blocks** are immutable per accepted user message. They render after the user text in the internal copy only, never in the harness-visible transcript. The view builder may omit a whole block deterministically; each change is a recorded invalidation with hysteresis.
- **Catalog stays internal.** `palimnesis.catalog` remains a bounded index and the transcript index's source. There are no model-facing catalog tools in Phase 2 (none were built).
- **Phase 3** becomes proactive recall plus transcript-file fallback, with a harness capability gate: the first harness must demonstrably read the transcript directory.
- **Hidden recall tools** (`palimnesis_recall`, `palimnesis_grep`, catalog navigation, internal interception, hidden continuations) move to optional Phase 3B. `docs/affordances.md`'s A/B matrix of hidden-tool variants is a Phase 3B matrix. Phase 3 selects query policy, excerpt format, caps and the transcript-search addendum on development data instead.
- **Evaluation** runs at 32K, then 64K, with the five arms A1 lists.
- **Eunoe's evidence** (`docs/papers.md`) motivates but does not establish results at 32–64K.

## D20 — Phase 2 excerpt policy and slots (user, 2026-10-24)

From the Phase 2 delta plan, `docs/plan/phases/phase2.md` §Delta.

1. **Old excerpt blocks are dropped only at threshold events** (watermark or collapse moves, budget changes), where the prefix is invalidated anyway. Between events a new user message may get a reduced or zero allocation. `bench_view` measures this starvation, and Phase 3 may change the policy on development data.
2. **Excerpt caps, Phase 2 defaults:**
   - per message `q_msg = min(2048, 4%·B_in)`;
   - active-view total `Q = min(4096, 10%·B_in)`, D14.4's formula;
   - effective total `Q_eff = min(Q, max(0, B_in − P − F − min_recent))`.

   That is 972 / 2,432 tokens at 32K and 1,920 / 4,096 at 64K. Excerpts never count in F, never touch R or M, never trigger a watermark move, and never cause a BudgetError: their allocation shrinks to zero first. Phase 3 selects the final caps on development data.
3. **The catalog slot is P = 0 until Phase 3B.** A1 removed model-facing catalog navigation, so the component stays in the budget but reserves nothing. Existing views see a one-time recorded budget change.

## D21 — Upstream-profile seam layout (Phase 2 slice A; implements D15 amended)

- **Core interface.** `palimnesis/profile.py` holds the backend-neutral Protocols (`runtime_checkable`):
  - `Counter`: `added_token_strings`, `count`, `count_cached`, `count_messages`, `render_args`;
  - `FactsReader`: `facts`, `stale`, `pinned_ok`, `refresh`, `mark_stale`, `observe`, `diagnostics`;
  - `CrossCheck`: `canary`, `usage → Usage(prompt_tokens, cached_tokens, prompt_ms)`;
  - `CacheReuseModel`: `expected`;
  - `ErrorMap`: `staleness_reason`, `is_context_overflow`.

  These are bundled with `TemplateRules` in a frozen `UpstreamProfile`, alongside the neutral `UpstreamFacts(n_ctx, identity)`.
- **Strata profile.** Everything Strata-specific lives in `palimnesis/upstreams/strata/`:
  - `pins.py` and `pins_data/` (bytes unchanged);
  - `tokens.py`;
  - `facts.py` (formerly `upstream_facts.py`; the `/props` record is `Props`);
  - `errors.py`;
  - `cache.py` (`StrataCacheModel`, filled in by slice 9).
- **Loading.** `profile.load(name, base_url)` resolves names through a string registry. `Settings.profile` defaults to `strata-0.1.48`; there is no CLI flag while only one profile exists. An unknown name fails before the server starts.
- **Template rules.** A profile declaring rules the core does not implement runs view-disabled (contracts §9: a template revision is a pinned-value change, not a runtime branch).
- **Boundary.** `tests/test_profile.py` walks every core module's imports and fails on any Strata import. A toy profile (character counter) drives the full view path end to end.
- **Note.** Earlier decision and plan entries name the pre-move module paths; they are historical records and are left as written.

## D22 — Cache accounting, reuse model and drift (Phase 2 slices 9–10)

1. **Every dispatched upstream call is recorded.** Each gets an immutable `upstream_call` event, written after delivery. Failed calls (503s, transport errors) are recorded too, with their `outcome` and null usage.
2. **Strata reuse model** (`StrataCacheModel`, always labeled an estimate):
   - The expected reuse is the latest checkpoint of the previous render at or before `min(LCP, generation start)`.
   - The candidate checkpoints are the six latest of: assistant-turn starts, the generation-prompt start, and multiples of 16,384 tokens. A system root is added when the system prompt is ≥ 2,048 tokens.
   - It reproduces the probe table (docs/probes/strata.md §7).
   - **Limit:** it sees only the previous call. When the server still holds an older checkpoint from an earlier call, the estimate is a lower bound, as in the probe's turn-4 edit: estimate 1,043, measured 2,656.
3. **Reuse classes, in order:**
   - `full`: cached ≥ `min(LCP, generation start)`.
   - `checkpoint_limited`: cached ≥ the estimate.
   - `restart_or_eviction`: anything lower. This includes Strata no longer holding a checkpoint the model assumed, with no restart (D50.3).
   - `unexplained`: an unexplained cause always gets this class.

   Causes are attributed from the first differing manifest segment (contracts §10). `eval/replay.py --explain` fails on any `unexplained`.
4. **Drift.**
   - "Recent" means the last 8 calls, and `M_eff = M + 2·max drift`, capped at 2,048.
   - Three consecutive drifts, or one drift over 1,024, disables bounded views until the process restarts. A miscounting renderer is a pin problem, not a transient one.
5. **Context versions keep their position.** A context version, such as OpenCode's daily date change in the system message, takes the view position (seq) of the occurrence it supersedes. Before this fix, view boundaries resolved to the start of history after a date change, and masked sessions failed with `context_budget_exceeded`.

## D23 — Phase 2 protocol-review fixes

1. **Escalation before a budget error.** After masking, collapse and excerpt omission, the view also stubs oversized reasoning in the recent window, not only tool output. If still over budget, it lets the window shrink below `min_recent` to the newest group and collapses everything older.
   - **What it prevents:** a session with a large fixed input (e.g. a 15K-token system prompt at 32K) whose reasoning-heavy recent window failed with `context_budget_exceeded` after acceptance, on every later turn.
   - **What remains:** a budget error after acceptance only when the newest group alone cannot fit. The next turn makes that group older and collapsible, so the session recovers.
2. **Known limit of `--view off`.** Its pre-acceptance check counts the client's messages. The upstream view also restores archived reasoning (§9), so an over-budget history can still be rejected after acceptance. `--view off` is a diagnostic mode.
3. **Startup canary.** An inconclusive canary (`count_tokens` unavailable) is re-run on the next refresh instead of disabling views for the process lifetime.
4. **CLI read-only opens** use a proper file URI, so `#`, `%` or `?` in a path cannot drop `mode=ro` or open another file.
5. **Excerpt path hardening.**
   - Excerpt header fields (alias, role, tool name) are reduced to a safe character set, so a client-chosen tool name cannot inject delimiters or special tokens.
   - An excerpt-source or rebuild failure falls back to answering without excerpts. A move caused by the rebuild is recorded.

## D24 — Phase 2 cache-audit fixes and logged policy limits

The independent cache audit re-rendered 789 consecutive upstream-call pairs across 17 scenarios, including restarts, date changes, effort, tool and `n_ctx` changes, drift and excerpts. It found no unexplained or misattributed pair.

1. **Fixed: excerpt churn under a moving per-message cap.** A budget change that shrinks `q_msg` (client `max_tokens` changes, `n_ctx` changes, drift margin at 32K) is a threshold event. Blocks then over the cap are added to `omitted_excerpts` and the view version is recorded with cause `excerpt_omitted`. Previously the cap was re-checked on every build, so a block flipped in and out as the client limit alternated, re-reading everything after it each call. With omission monotone (D20 R2), re-including an older block cannot happen.
2. **Logged for `bench_view`, not fixed: moves can come almost every turn.** When `min_recent` holds the watermark back, the view lands above T. At small budgets with large outputs it then crosses H nearly every turn: 21 of 24 calls moved at a 12K budget. The hysteresis parameters (D14.6) are revisited with `bench_view` data.
3. **Logged, not fixed: an oversized newest output over-collapses.** The watermark and collapse searches run while the oversized newest output is still verbatim, so they take the last candidate before that output is stubbed. This discards more context and cache than needed. The ordering fix (stub the newest output first when it alone exceeds the window) is a Phase 2 follow-up tracked with `bench_view`.
4. **Disabled-mode audit gap.** `view_disabled` and `first_call` are recorded causes; contracts §10 now lists them. Calls in disabled mode record no LCP, so their prefix changes are not audited.

## D25 — Builder latency: off-path stub warm-up; Phase 2 latency gates

R12 measured warm builds at 48K that do not move the view at p95 ≤ 22.6 ms. Builds that move it reached p95 95–175 ms, so all builds together missed the 30 ms target. Profiling located the cost:

- **Not rendering.** Moves made 14 template renders each; cutting them to 8 changed the time by under 10%.
- **Cold stubs and fragments.** Most of the cost was fitting s1 stub previews for newly masked messages, a bisection over uncached prefix counts at about 4.5 ms per stub. The rest was counting each masked message's rendered fragment for the first time.

Changes. All are exact: views, counts and every R12 count are unchanged.

1. **Stub cache across builds.** Stubs are memoized process-wide, keyed by kind, alias, block, the SHA-256 of the text, preview caps and counter. The bounded LRU holds 4,096 stubs, not texts.
2. **Off-path warm-up.** After each build, `ViewEngine` hands the request's items to one background worker while the upstream generates. The worker renders the session once with every unfixed message masked (`view.warm`), which fills the stub and fragment caches for any later move.
   - A newer request supersedes a pending warm-up rather than queueing behind it.
   - Failures are logged and builds compute on demand.
   - `--view off` skips it.
3. **Per-build measurement memo.** The searches and the final view no longer re-render states already counted.
4. **Sandbox check memo.** The jinja sandbox's attribute check is memoized by (type, attribute). The check depends on nothing else, so this is exact.
5. **Rejected: an estimate-guided search.** It cut renders from 14 to 8 per move with identical results but gained under 10%, which did not justify the extra search logic.

**Gate dispositions (Phase 2).**

- **Builder latency** (plan: build + count p95 ≤ 30 ms at 48K, warm). Met on `tool_heavy` (24.8–26.6 ms) and `chatty` (3.9–4.5 ms). Missed on `big_single` (37.4–38.6 ms), which is accepted:
  - Its moves are triggered by a 3K–15K-token output that arrives in the same request, so that output's stub cannot be prepared beforehand.
  - A move precedes a re-read of ~19K tokens, about 60 s of prefill at 48K (R14, scaled). A 45 ms build adds under 0.1% to that request.
  - Incremental rendering would remove the remainder. It is not scheduled.
- **R8 "bench_archive TTFB flat"** is reinterpreted as *no per-request history reload*.
  - **Met.** The statement count is constant over 200 turns (`test_accept_sql_statements_constant_over_200_turns`).
  - **What still grows** (R13, R16), from first-10 to last-10 over 50 turns, is CPU linear in the client body:
    - JSON parse, 0.7 → 3.7 ms;
    - transcript alignment in accept, 2.0 → 5.2 ms;
    - view render and count, bounded by the input budget.
  - **Why the original wording is dropped:** a parser cannot be flat in the size of its input.
  - **Phase 3 candidate:** incremental alignment against the BranchCache, so that accept is O(new messages).
