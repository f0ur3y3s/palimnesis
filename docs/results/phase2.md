# Results: Phase 2 (R12–R17)

[Index](README.md) · Append-only; each entry names its commit, configuration and hardware.

## R12 — Bounded-view watermark frequency, re-read and builder latency (Phase 2 GL7, 2026-10-25)

`python eval/bench_view.py` (defaults: 300K ingress tokens per session, seed 11). Pure, using `palimnesis.view.build` and the Strata 0.1.48 profile counter. It ran from the working tree at `1929c5c` with `src/` clean. `1929c5c`'s `src/` differs from `ae71004` only in docstrings, and only `eval/bench_view.py` was uncommitted. A rerun from a `git archive` export of `fb9b263` (D23, D24) gave identical move, re-read and excerpt counts in all 18 sessions, with latencies within ±10%. Hardware as R6; Python 3.12.13, tokenizers 0.23.3. Each session uses a fresh counter, warmed by a throwaway session with another seed. Policy: D14.6 (H 0.90, T 0.50, `min_recent` 4,096); excerpt caps D20.2. `q_msg`/`Q` were 972/2,432 at 24,320 and 1,920/4,096 at 48,000.

**Workloads.** Sessions are OpenCode-shaped: live body 0's system prompt and real tools array, so F is ~5.0K. A request is built after every user message and every tool result, carrying the persisted view state.

- `tool_heavy`: 4–12 tool groups per user message, with log-uniform outputs of 200–6,000 tokens.
- `chatty`: user 10–150 tokens and answer 30–400 tokens, with reasoning.
- `big_single`: one output of 3,000–15,000 tokens per user message.

**Measures.**

- *Ingress* is new content tokens, counted per message.
- *Re-read* is the moved view's tokens after its token LCP with the previous request (`counter.layout` ids). "est" is `len − StrataCacheModel.expected`, an estimate.

Arm `none`:

| Workload | Budget | Requests / ingress | Moves per 100K (watermark, collapse) | Ingress between moves, median | Re-read per move, median: LCP / est | Amortized re-read per ingress token | Append re-read, median |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tool_heavy | 24,320 | 209 / 317,778 | 11.96 (38, 36) | 7,699 | 8,170 / 8,216 | 0.98 | 838 |
| tool_heavy | 48,000 | 209 / 317,778 | 5.35 (17, 16) | 16,567 | 19,343 / 19,367 | 1.03 | 925 |
| chatty | 24,320 | 758 / 300,012 | 14.00 (42, 42) | 6,914 | 8,280 / 8,304 | 1.16 | 405 |
| chatty | 48,000 | 758 / 300,012 | 6.00 (18, 18) | 15,356 | 19,386 / 19,400 | 1.16 | 408 |
| big_single | 24,320 | 60 / 301,187 | 8.63 (26, 21) | 11,014 | 10,419 / 10,444 | 0.91 | 391 |
| big_single | 48,000 | 60 / 301,187 | 3.98 (12, 7) | 23,564 | 19,122 / 19,135 | 0.63 | 451 |

- **Move frequency.** A move comes every ~7K ingress tokens at 32K capacity and every ~15–24K at 64K, so frequency scales with 1/budget, not with turn count.
- **Re-read per move.** Each move re-reads about T minus the ~5K head: ~8.2K at 24,320 and ~19.3K at 48,000. That is ~1 re-read token per ingress token, amortized.
- **Checkpoint model.** The model's estimate is within 0.3% of the LCP figure, because the system root (≥ 2,048 tokens) is always a checkpoint.
- **Collapse.** Most watermark moves also collapse a span: 16 of 17 tool_heavy moves at 48K. Collapse reached the watermark itself only in big_single at 24,320 (17 of 26 moves). Elsewhere a band of s1 stubs stays visible: 1–36 in the final views.
- **Budget.** 0 of 6,162 views (all 18 sessions) exceeded the budget, and every layout length equalled `view.tokens`.

Excerpt arms. A block on every new user message (`every`) or on every third (`third`) is sized `min(q_msg, allocation)` from a real earlier span. *Starved* means the allocation was below `q_msg`.

| Workload | Budget | `every`: starved, omissions per 100K | `third`: starved, omissions per 100K | Amortized re-read `every` / `third` |
| --- | --- | --- | --- | --- |
| tool_heavy | 24,320 | 0/23 (0%), 6.9 | 0/8 (0%), 2.2 | 1.00 / 0.98 |
| tool_heavy | 48,000 | 0/23 (0%), 6.9 | 0/8 (0%), 2.2 | 1.04 / 1.04 |
| chatty | 24,320 | 414/758 (55%), 236.0 | 0/253 (0%), 82.3 | 1.29 / 1.21 |
| chatty | 48,000 | 437/758 (58%), 219.7 | 5/253 (2%), 81.3 | 1.21 / 1.18 |
| big_single | 24,320 | 0/30 (0%), 9.3 | 0/10 (0%), 3.0 | 0.93 / 0.91 |
| big_single | 48,000 | 7/30 (23%), 8.6 | 0/10 (0%), 3.0 | 0.67 / 0.65 |

- Starvation is a chatty-workload effect. `Q` holds about 2.1–2.5 full blocks, and omissions wait for a threshold event (D20.1).
- No move was ever caused by excerpts. The rebuild after attaching a block never moved the view (0 of 2,046 rebuilds). That is the case `ArchiveHandler._bound` would not persist.
- Excerpts add 0–11% to amortized re-read.

Build latency (`build`, including the exact count) at 48,000, in ms. "Plain" is a build that did not move; "identical" is a rebuild of the final state with every fragment cached.

| Workload | Arm | Moves / requests | All p50 / p95 | Plain p50 / p95 | Move p50 / p95 | Identical rebuild p95 |
| --- | --- | --- | --- | --- | --- | --- |
| tool_heavy | none | 17/209 | 9.9 / 117.0 | 9.8 / 13.5 | 123.7 / 151.2 | 8.7 |
| tool_heavy | every | 17/209 | 9.5 / 112.9 | 9.4 / 13.8 | 117.6 / 150.2 | 8.8 |
| chatty | none | 18/758 | 8.5 / 10.8 | 8.4 / 10.5 | 116.9 / 131.3 | 8.9 |
| chatty | every | 18/758 | 8.5 / 11.5 | 8.4 / 10.9 | 115.9 / 149.7 | 9.1 |
| big_single | none | 12/60 | 9.6 / 91.4 | 6.6 / 20.8 | 79.8 / 94.8 | 3.7 |
| big_single | every | 12/60 | 11.8 / 98.2 | 7.3 / 22.6 | 82.5 / 115.7 | 3.9 |

**The latency target (p95 ≤ 30 ms at 48K, warm) is met for builds that do not move, and missed for moves.**

- Plain builds run at p95 10.5–22.6 ms.
- A move build has p50 80–124 ms and p95 95–175 ms, with a maximum of 192 ms. Each probe of the watermark and collapse binary searches renders and counts the whole view.
- The overall p95 therefore fails wherever moves exceed 5% of requests: tool_heavy at 110–117 ms, big_single at 86–98 ms.
- The cost is small next to the move's own re-read prefill: ~19K tokens, ~47–62 s at R14's measured 2.4–3.2 ms per token, an estimate.

GL7 (report watermark frequency against ingress, with no universal gate) is met.

## R13 — `bench_archive` rerun: TTFB growth with BranchCache, metadata with excerpt rows (Phase 2, 2026-10-25)

`python eval/bench_archive.py --turns 200 --e2e-turns 50 --repeats 1`, run from a `git archive` export of `1929c5c` plus the uncommitted eval changes. Hardware and SQLite 3.53.1 as R6; FULL, v2 deltas.

**Script changes.**

- The fake upstream's usage now reports the exact local count of each body. R8's made-up `5000 + i` would make the Phase 2 drift monitor disable views after three requests.
- The snapshot adds `view_versions`, `excerpt_blocks`, `excerpt_items` and per-kind event counts.

Part 1 reproduces R6/R8 exactly: v2 saves 68.6% / 56.3% / 58.0%.

End to end, 50 turns at shipped defaults (views on, 48K budget). The 26.1K-token final view never masks, so there are no view versions.

| | R8 | R13 |
| --- | --- | --- |
| TTFB p50, first 10 / last 10 | 8.2 / 16.0 ms | **16.7 / 30.3 ms** |
| Metadata excluding raw bodies | 512 KB | 627 KB (`events` 143 KB) |
| `raw_bodies` | 201 KB | 201 KB |
| `events` | 400 | 451 (+50 `upstream_call`, +1 `excerpts_selected`) |
| `excerpt_blocks` / `excerpt_items` / `view_versions` | — | 1 (status `empty`) / 0 / 0 |

- **Growth.** Metadata grows 8.8 KB per request from 25 to 50 turns. The `events` table accounts for ~2.8 KB of that, mostly `upstream_call` payloads.
- **Excerpt rows.** They add one row per genuine new user instruction; the synthetic session has one.

**The target (last-10 p50 within 2 ms of first-10) is not met.** TTFB still grows. Five interleaved repeats, using per-turn medians, show where.

| Mode | First 10 → last 10 p50 | Slope |
| --- | --- | --- |
| Views on (default) | 23.2 → 43.5 ms | 0.51 ms/turn |
| View-disabled (pin mismatch) | 17.5 → 25.8 ms | 0.21 ms/turn |
| `--view off` (single runs) | — | 0.56–0.69 ms/turn |

Run-to-run noise is about ±5 ms. Component timings, first 10 → last 10 p50, in ms:

| Component | First 10 | Last 10 |
| --- | --- | --- |
| `chat.parse` | 0.7 | 3.7 |
| `ledger.accept` | 2.0 | 5.2 |
| `view.build` | 1.3 | 5.4 |
| Accounting `layout`, in a worker thread | 1.5 | 3.7 |

- **Archive side.** BranchCache keeps the statement count constant (R8's reload is gone). Per-request parse and accept CPU still grows with body size: +6–8 ms over 50 turns, comparable to R8's +7.8 ms.
- **View side.** It adds ~12 ms more by turn 50: a full render and count of the view each request, plus the accounting layout. `--view off` adds a third whole-history count in `_prepare`.
- **Bound.** View-side growth is bounded by the input budget, not by history length. R12 measures ~9 ms p50 at 48K.

## R14 — Live forced-budget OpenCode run through bounded views (Phase 2 GL8, 2026-10-25)

**Setup.**

- Code: a `git archive` export of `1929c5c`. `fb9b263` (D23, D24) landed during the run and was not exercised live.
- Strata 0.1.48, `qwen3.8-flash-next-iq3_xxs`, `n_ctx` 65536, one shared slot, cold at request 1.
- OpenCode 2.1.4 with R9/R10 isolation (`--standalone`, isolated HOME, XDG, TEMP and config, `PWD` a fresh git repo, stdin at EOF).
- Topology as R9: archive with `--input-budget 12000` (`Q` 1,200, `q_msg` 480) and an ASGI tap, then `--passthrough --capture-dir` with a tap, then Strata.
- Evidence: `eval/fixtures/opencode-2.1.4/view-live/` (README, `summary.json`, scripts).

**Task.** Four turns in one session: build `stats.py` with tests, then add variance/stdev, percentile and zscore, running the tests each time.

**Results.**

- **Statuses.** All 18 requests returned 200, and OpenCode exited 0 on all four turns. The final files pass (`python test_stats.py` prints `OK`, re-run independently). After moves 1 and 2, the turn-3 answer read the file back and listed all six functions correctly. **The task succeeded.**
- **Budget.** Every upstream body counted ≤ 12,000 with the Strata counter (max 10,352). `input_tokens` equalled `usage.prompt_tokens` on 18 of 18, with no `count_drift` events.
- **Fast path.** Requests 1–11 forwarded the client body byte-identical. Requests 12–18 were rendered views.
- **View versions.** There were 3 rows, each with cause `watermark_move,collapse`. Each collapsed the whole masked region into one span note of 11, 18 and 24 messages; watermark seq equalled collapse seq (13, 20, 26). At this budget T (~7.9K) lies below F plus `min_recent`, so no s1 stub ever reached the model.

**Upstream calls.** There were 17 pairs: 14 `append` (13 `full`, 1 `checkpoint_limited`) and 3 moves. The move rows, with the estimate labeled as such:

| Call | I | lcp | cached | est | prompt_ms | Class | Cause |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 12 (move 1) | 9,552 | 4,969 | 4,966 | 4,966 | 14,645 | `checkpoint_limited` | `collapse` |
| 14 (move 2) | 9,972 | 4,984 | 4,966 | 4,966 | 14,500 | `checkpoint_limited` | `collapse` |
| 16 (move 3) | 9,636 | 4,984 | 4,966 | 4,966 | 14,171 | `checkpoint_limited` | `collapse` |

- **Deep re-read.** A move re-read 4,586–5,006 tokens in 14.2–14.6 s, about 3.1 ms per token. Reuse fell back to the system-root checkpoint, exactly as estimated.
- **Append turns.** Over n = 14, `prompt_ms` had a median of 762 (291–2,798) for a median of 34 uncached tokens. So a move costs about 19× an append turn here; scaled to 48K (~19.3K re-read, R12), that is ~60 s (estimate).
- **First call.** Cold: 16,436 ms for 5,021 tokens.
- **The one `checkpoint_limited` append.** It is call 4, the first request of turn 2: lcp 5,923, cached 5,918, est 5,918. Strata re-read the previous generation prompt, the 5 tokens at the end of the LCP.

**`eval/replay.py --explain`** on the archive exited 0: 18 calls, 17 pairs, 0 unexplained.

**Proxy pre-dispatch time** (archive tap arrival to upstream tap arrival): 2.6–29.8 ms on non-move requests, 55.1, 39.8 and 48.0 ms on moves, and 32.7 ms on the first request of the process.

GL8 (measured reuse and prefill by cause, estimates labeled) is met for the `append` and `watermark_move`/`collapse` causes. Other causes did not occur.

## R15 — Live excerpt replay: prefix reuse with blocks included vs omitted (Phase 2 GL8, 2026-10-25)

**Setup.**

- Run: `python eval/live_excerpt_replay.py --upstream http://192.168.1.173:8080 --turns 6`, defaults `--input-budget 16000` and `--max-tokens 2048`.
- Code, Strata and hardware as R14.
- In-process proxy: `create_app(Settings(excerpt_source=SpanExcerpts()))` under the production uvicorn config. `SpanExcerpts` is `SeededExcerpts`-like: it selects a prefix of the newest earlier archived tool result, cut to the allocation it is given, with exact boundaries and sha256.
- Bodies are OpenCode-shaped (live body 0's model and tools, streamed). Each turn asks the model to `read` `notes/partK.txt`, and the proxy-side driver answers with a 1,842-token file.
- Budget: `Q` 1,600 and `q_msg` 640.
- Requests were sequential, each waiting for an idle `/status`. Cached tokens show unbroken continuity, so no foreign request evicted this session.
- Evidence: `eval/fixtures/opencode-2.1.4/view-live/excerpt-replay.json`.

| Call | Request | Block on this request (allocation → charge) | I | lcp | cached | prompt_ms | Class, cause |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | t1 user | `empty` (nothing earlier to select) | 5,000 | — | 0 | 14,596 | first call |
| 2 | t1 tool | — | 6,905 | 5,000 | 5,047 | 10,801 | `full`, `append` |
| 3 | t2 user | **new, 640 → 640** | 7,621 | 6,905 | 6,900 | 4,206 | `checkpoint_limited`, `append` |
| 4 | t2 tool | block 1 kept in prefix | 9,578 | 7,621 | 7,723 | 10,753 | `full`, `append` |
| 5 | t3 user | **new, 640 → 640** | 10,368 | 9,578 | 9,685 | 3,961 | `full`, `append` |
| 6 | t3 tool | | 12,299 | 10,368 | 10,440 | 10,717 | `full`, `append` |
| 7 | t4 user | **new, starved, 320 → 320** | 12,696 | 12,299 | 12,335 | 3,182 | `full`, `append` |
| 8 | t4 tool | | 14,608 | 12,696 | 12,748 | 10,808 | `full`, `append` |
| 9 | t5 user | `empty`, allocation 0 (starved) | 14,695 | 14,608 | 14,654 | 750 | `full`, `append` |
| 10 | t5 tool | **threshold event**: view 1, `watermark_move,collapse,excerpt_omitted`; blocks 1–2 omitted, block 3 kept | 11,255 | 4,963 | 4,960 | 15,180 | `checkpoint_limited`, `collapse` |
| 11 | t6 user | **new, 640 → 640** (room freed by the omission) | 11,977 | 11,255 | 11,295 | 3,919 | `full`, `append` |
| 12 | t6 tool | | 13,921 | 11,977 | 12,061 | 10,747 | `full`, `append` |

- **Inclusion.** Including a block never broke the prefix: on every call after an inclusion, the LCP covered the previous request whole. The block itself is prefilled once. A user turn carrying a 320–640-token block took 3.2–4.2 s, against 0.75 s for a user turn without one; that is ~5.8 ms per token on incremental prefill.
- **Omission.** Blocks were omitted only at the threshold event, together with the watermark move and collapse, and reuse fell to the system root as estimated. The first difference is the collapse, so the omission added no invalidation of its own: 6,295 tokens were re-read in 15.2 s (2.4 ms per token).
- **Starvation.** It appeared as D20.1 allows: turns 4 and 5 got 320 and 0 tokens, and the next threshold event restored a full allocation.
- **Explain.** `replay.py --explain` exited 0: 12 calls, 11 pairs, 0 unexplained. `input_tokens` equalled `prompt_tokens` on 12 of 12, with no drift.

## R16 — Builder latency after the off-path stub warm-up (Phase 2, D25, 2026-10-25)

`python eval/bench_view.py` (all workloads, budgets and arms) and `--no-warm --budgets 64K`. Run on `fb9b263` plus the D25 changes in the working tree. The benches ran sequentially on an idle machine. Hardware as R6; Python 3.12.13, tokenizers 0.23.3, profile `strata-0.1.48`.

**Counts.** Every count is identical to R12: moves per 100K, collapse counts, re-read per move (LCP and estimate), starvation and omissions. View tokens and states are unchanged, as `test_warming_stubs_never_changes_a_view` checks.

**Latency at 48K, in ms.** "Plain" means builds that do not move the view. The `--no-warm` columns reproduce R12's cold-stub numbers.

| Workload | Arm | All p50 / p95 | Plain p50 / p95 | Move p50 / p95 | `--no-warm` all p95 / move p95 |
| --- | --- | --- | --- | --- | --- |
| tool_heavy | none | 3.5 / **26.5** | 3.3 / 6.3 | 27.3 / 33.1 | 88.3 / 125.2 |
| tool_heavy | every | 3.4 / **26.6** | 3.3 / 6.6 | 28.1 / 32.7 | 88.5 / 124.4 |
| chatty | none | 2.9 / **3.9** | 2.9 / 3.7 | 37.9 / 42.4 | 3.7 / 104.3 |
| chatty | every | 3.1 / **4.5** | 3.0 / 3.9 | 41.3 / 66.5 | 3.9 / 111.2 |
| big_single | none | 6.7 / **37.4** | 2.4 / 16.4 | 28.5 / 44.6 | 76.8 / 80.4 |
| big_single | every | 6.1 / **37.8** | 2.4 / 16.5 | 29.4 / 44.5 | 76.2 / 83.9 |

The `third` arm sits between `none` and `every`. At 24,320 every overall p95 is ≤ 18.3 ms except `big_single` at 35.4 ms.

**Target** (build + count p95 ≤ 30 ms at 48K, warm). Met on `tool_heavy` and `chatty`. Missed on `big_single` by 7–9 ms, which D25 accepts with its reason.

**bench_archive e2e, 50 turns** (`--turns 200 --e2e-turns 50 --repeats 1`, three runs). TTFB p50 rose from 24.1, 25.3 and 24.4 ms over the first 10 turns to 43.1, 42.6 and 43.3 ms over the last 10. This matches R13's five-repeat views-on figure (23.2 → 43.5 ms).

- **The warm-up does not help here.** This session never masks, so per-request cost is the body-linear parse, accept and count, plus a warm-up that overlaps the next request because the fake upstream answers instantly. A real upstream generates for seconds.
- **Metadata** is 627 KB, unchanged.
- **The R8 row** is disposed of in D25.

## R17 — Phase 2 gate summary (2026-10-25)

Code at the `phase-2` tag. Full suite: 882 passed.

| Gate | Evidence | Status |
| --- | --- | --- |
| GL1: fits or a structured error | View property and HTTP tests. 0 over-budget views in R12 (6,162 views) and R14 (max 10,352 of 12,000). D23 escalation before a budget error. | Met |
| GL2: oversized newest output, user/system/schemas, Unicode, many small messages | `test_view*`, `test_stubs`, `test_phase2_review_fixes` | Met. D24.3 logs over-collapse on an oversized newest output for follow-up. |
| GL3: versions and A/B matrix | `docs/affordances.md`, registry tests | Met. Phase 3B matrix defined (A1). |
| GL4: catalog reach | catalog tests | Met. Internal only after A1 (D19, D20.3, D16.6). |
| GL5: zero upstream calls from the builder | socket-deny and one-POST tests | Met |
| GL6: every invalidation explained | `--explain` exit 0 on 10 live bodies, R14 (17 pairs), R15 (12 calls), and the cache audit's 17 archives (789 pairs, none unexplained or misattributed). D24.1 churn fixed. | Met |
| GL7: watermark frequency vs ingress | R12: moves every 7–11K ingress tokens at 24,320 and every 15–24K at 48,000. Re-read per move about T. Amortized 0.63–1.16 re-read tokens per ingress token. | Met. D24.2 logs near-per-turn moves at small budgets with large outputs. |
| GL8: reuse and prefill by cause | R14: 3 moves, each re-reading 4.6–5.0K tokens in 14.2–14.6 s, matching the estimate; appends had a median prefill of 762 ms. R15: excerpt blocks never broke the prefix. | Met |
| §1–§6, §9 (ordinary turns), §10–§12 | contract tests. Protocol review: approved with conditions, all fixed (D23). | Met |
| R8 | constant SQL statements over 200 turns; R13, R16 | Met as reinterpreted (D25) |
| Builder latency | R16 | Met on 2 of 3 workloads. `big_single` 37–39 ms, accepted (D25). |
| Paper fidelity | review: no unexplained divergence. Doc corrections committed. | Met |

**Carried to Phase 3:**

- Proactive retrieval and transcript files (A1).
- The view-policy items in D24.2 and D24.3, with bench_view data.
- Incremental accept (D25).
