# Phase 7 plan: candidate evaluation

Written 2026-11-19 at `a6301d0` (tag `phase-4a`). Module paths follow D80. Decisions start at D111, in a new file, `docs/decisions/phase7.md`. Planning never opened, read, grepped or listed `eval/tasks/ho4_*`, `eval/needles/heldout4/` or `eval/needle_gen_ho4.py`.

**Scope:**
- v1_plan "Phase 7 — Candidate evaluation": its preamble, the four test families, the gate table and the statistics paragraphs.
- A1 "Evaluation": arms, metrics, 32K then 64K, and freezing before held-out data.
- The contract clauses whose gates Phase 7 reads: §2 budgets, §7 limits, §8 scheduling, §10 cache accounting, §11 durability, §12 capture and privacy, §13 and §14 recall, §15 hidden tools, §16 client protocols, §17 pinned state.
- Phase 7 is a provisional checkpoint. Phase 8 makes the final decision.

## Core positions

1. **Phases 5 and 6 are skipped for now** (D111, user decision).
   - **Why.**
     - The pinned state already beat the no-state ablation on decision and constraint retention: 14/15 tasks against 10/15, and 44/45 constraints against 36/45 (R61). It also beat native compaction on ho3 (R41).
     - Phase 5's own green light asks for "paired decision-recall results [that] justify cost versus Phase 4A". There is no evidence yet of a gap a summary DAG would close.
     - Phase 6 needs held-out paraphrased needles and an embedding stack that nothing so far has called for.
   - **Reversible.** Either phase can return before Phase 8. If one does, its gates become mandatory, and Phase 8 reruns the affected comparisons.
   - **Recorded as deferrals, not passes:** Phase 6's paraphrased-needle row and Phase 5's summary cost.
2. **What is evaluated is frozen.**
   - **Candidate:** `a4-d77` = `serve`'s defaults (D78), at the freeze commit F.
   - **Baseline:** arm 1, OpenCode's own compaction through `--passthrough`, with `limit.context` = n_ctx (D44.1, D48.6).
   - **No tuning in Phase 7.** The only `src/` change allowed is instrumentation (S2). The S0 goldens (`tests/test_state_golden.py`) guard that the upstream bytes do not change.
   - **Hidden tools.** `--hidden-tools` is declared experimental and not claimed for release (D111). R32 failed both of its gates, so no Phase 7 row applies to it.
3. **Confirmatory evidence comes from one harness and one build:** OpenCode 2.1.4 on pythia and Zeus, split by task, both on Strata 0.1.58 (D111.6), at a real `n_ctx` of 32,768, with no emulated budget (O2).
   - **Why 32K.** At 64K the task shape barely crosses the budget: R26 recorded 5 view moves over five tasks.
   - **64K** is reported only (A1).
   - **Pi** is reported on ho4 if the user agrees (U4). OMP gets no held-out claim.
4. **Harness-neutral tooling.**
   - New eval code reads tool calls by protocol (Chat `tool_calls`, Messages `tool_use`), never by harness name.
   - Harness specifics stay in `oc_harness`, `pi_task` and the adapters.
5. **Held-out data stays unseen by the lead until the verdict.**
   - Every gate, statistic, order and stopping rule is written in D115 before any held-out run.
   - After the verdict, ho4 and ho5 retire to development data, as ho2 and ho3 did (D69).

## Findings in current code

- **F1. Gate constants are Phase 3's.**
  - `report.NEEDLE_GATE` is 0.85; Phase 7 needs 0.95.
  - `SET_SHAPE` assumes 12×10 histories × questions.
  - `coding_gate` compares success counts within one 5-task set. It has no McNemar across tasks and nothing per constraint. (`mcnemar_exact` exists, but only for pooled needle pairs.)
- **F2. Refresh calls have no timing** (R61). `#notes` calls record `prompt_ms` 0, and `upstream_call` events carry no `completion_tokens` (D106.5). Whether the gap is in the tap's parsing of non-streamed replies or in the proxy's event is **unverified**.
- **F3. No record of host epoch.** Nothing records boot id, Strata start time or a relaunch, so D108's confound was found by hand.
- **F4. Trap detection reads only the Palimnesis archive.**
  - Arm 1 (passthrough) has no `archive.db`, so its trap repeats cannot be detected the same way.
  - Eligibility is judged at the end of the session, not at the turn where the trap is needed.
  - 7 of 15 dev, ho2 and ho3 tasks have no `TRAP_PATTERNS`.
- **F5. 4A's traps were not tempting.** Both arms had 0/30 repeats (R61). dev-t1's trap is also ruled out by constraint C1 and caught by the visible tests.
- **F6. Run order was fixed** (baseline arm first, R61). No tool randomizes or interleaves arms.
- **F7. Pi's task and needle drivers refuse held-out sets.**
- **F8. Unseen sets are a hard-coded tuple.** `state_eval.REFUSED_SETS = ("heldout4",)`. Nothing unlocks it after the freeze, and there is no `heldout5`.
- **F9. Needles carry only a `category`.** There are no labels for source role, placement, masking depth or distractors.

## 1. Design

### 1.1 Held-out sets

| Set | Needles | Tasks | Status |
|---|---|---|---|
| `heldout4` (D96) | 12 histories × 10 = 120 | ho4-t1..t5 | written, unseen, sealed |
| `heldout5` (new, S9) | 18 histories × 10 = 180, stratified (§1.3) | ho5-t1..t20 (U2), each meeting the trap standard (§1.2) | written by separate authors, sealed before F |
| `heldout6` (optional reserve, U2) | — | 10 tasks | sealed for Phase 8's reruns |

- **Totals:** 300 held-out needles and 25 held-out tasks.

**How new held-out data gets written.** This follows D62.3, D77.3 and D96, with these improvements:
1. **A written author brief**, committed before authoring (`eval/tasks/AUTHORING.md`). It holds only:
   - the task skeleton (8 turns, restart before turn 5, a 7–14K document read, ~10–12K suite runs, D45.7);
   - the constraint rules;
   - the trap-design standard (§1.2);
   - the needle stratification table (§1.3);
   - the independence rules.
   It contains no results or design rationale.
2. **Several authors, for diversity.** Four separate author sessions write 5 tasks and about 45 needles each, with disjoint themes per author.
   - **They read only:** the brief, `eval/tasks/common.py`, two development task modules as format examples, and the skeleton of `eval/needle_gen.py`.
   - **They do not read:** `src/`, `docs/results/`, D69 onward, or each other's output.
   - Who wrote what is recorded per task.
3. **The author's checks:**
   - `--check-reference`: the reference passes; the stub fails; the trap solution passes the visible tests but fails `test_t_*` and matches `TRAP_PATTERNS`;
   - the generator's `--check` reproduces the files byte for byte;
   - independence from dev, ho, ho2, ho3 and ho4: no shared 4-word run, with pass/fail output only;
   - the temptation probe (§1.2, T1).
   The author reports only per-task pass/fail counts.
4. **Sealing.** The lead commits by path without reading. D113 records the SHA-256 of every file. A test checks the hashes and the shapes only (the D106.8 pattern).
5. **Unlock.** Analysis tools refuse unseen sets until a committed `eval/heldout_unlock.json` names the set and D115 (S10). Run drivers accept unseen sets only at a clean commit that carries D115.

**Power, and so how many tasks.**
- **The floor.** The exact two-sided McNemar's minimum p with d discordant pairs is 2^(1−d). It needs d ≥ 6, all favouring one arm, for p < 0.05. More balanced splits need more pairs: 8–1 gives 0.039, 9–1 gives 0.021, 10–2 gives 0.039, while 7–1 gives 0.070.
- **Expected discordance.** Earlier held-out comparisons with arm 1 had 20–40% discordant tasks (R25, R32, R41). At N = 25 that is about 5–10 discordant pairs, so significance is possible only if one arm wins most of them. At N = 20 it is often out of reach.
- **Recommendation: N = 25** (ho4's 5 plus 20 new). The gate stays the observed rate; significance is not a gate. N = 30 would add about 13 h of slot time for 1–2 more expected discordant pairs.

### 1.2 Trap-design standard (D112)

A trap is the "already tried X, it failed because Y" note in turn 1. Each held-out task in the declared trap suite meets T1–T7.

| # | Criterion | How it is checked |
|---|---|---|
| T1 | **Tempting.** X is the shortest or most idiomatic fix for the late request; without the warning, the model picks it. | Temptation probe: the trap turn's request with the workspace at that point, no history and no warning, sent directly to Strata (no proxy, no compaction), 3 samples. Passes if trap code (D109 `code`) appears in ≥ 2 of 3. This measures the model only, never an arm. |
| T2 | **Passes a quick check.** The trap solution passes every visible test; only the hidden `test_t_*` (and Y) catches it. | `--check-reference` with a new `TRAP_SOLUTION` overlay |
| T3 | **Needed late.** The code where X applies is requested at turn ≥ 6 (`TRAP_TURN`). That request neither restates the warning nor names X or Y. | Lint test; the brief |
| T4 | **Independent of the constraints.** No stated constraint implies avoiding X. | Author's declaration; reviewed at S9 |
| T5 | **Detectable.** `TRAP_PATTERNS` match the trap solution and not the reference, and `test_t_*` fails the trap solution. | `--check-reference` |
| T6 | **A separate outcome.** `test_t_*` is not part of `test_f_*`, so success and trap are scored apart. | `score_check` test |
| T7 | **Out of view when needed.** In the pilot, the turn-1 statement has left the candidate's view (collapsed) before `TRAP_TURN`. | `state_eval` need-turn eligibility (S4); dev pilot |

**Validating the standard on development data** (S8, no held-out data used):
- The lead writes dev-t6..t10 under the standard.
- **Pass conditions:**
  - V1: T1 passes on at least 4 of 5 tasks.
  - V2: T7 holds in every `a4-d77` and `a4-tr` run.
  - V3: at least one trap repeat (D109 `code`) occurs across `a4-tr` and arm 1 on dev-t6..t10. This shows the traps can separate arms, which 4A's could not.
- **If V1 or V3 fails,** the standard is revised once (D112 amended) and re-piloted before any authoring starts.
- **Declared trap suite** = ho5's 20 traps. ho4's 5 traps predate the standard and are reported, not gated.

### 1.3 Needle design (reuses `needle.py --driver opencode` and `report.py`)

- **Shape.** ho5 keeps the 10-step skeleton and A1's categories (identifier, vague, superseded, irrelevant_matches, oversized_read, mid_task, multi_fact, restart_multi_eviction). Each question declares `strata`:
  - **source role:** user instruction, user paste, assistant statement, or tool output (read, grep, shell);
  - **placement:** first, middle or last third of the history;
  - **planned depth:** the fact sits less than 0.5×, 1–2×, or more than 3× B_in before the question;
  - **distractors:** none, a near-miss key, a superseded value, or 3 or more lexical decoys.
- **Balance is marginal,** not a full factorial: at least 30 needles per level across the 300, with ho5 supplying what ho4's computed labels lack.
- **Measured depth** is reported, not gated: whether the fact was in view verbatim, in an excerpt only, or absent, and how many view moves had passed.
- **ho4 labels** are computed after the freeze by a pure stratifier (S6) from the `evidence` positions and the archive, without the lead reading them.
- **Development needles:** dev-h1..h6 plus the retired ho2 and ho3 sets. They are used only to validate the stratifier and the report in the S10 dress rehearsal, never to select anything.
- **Scoring:** loose exact (R19), as in D44.4 (U5). Strict is reported. Every non-answer, early stop or timeout is a miss. History-clustered bootstrap (D45.9.4) and Wilson intervals.
- **Run on the candidate only,** as in D44 and D77: the needle gate is the candidate's.

### 1.4 Protocol to freeze (D115, written before any held-out run)

| Item | Setting |
|---|---|
| Configurations | `a4-d77` at F (a later commit may change only `eval/` and docs); arm 1 as in D44.1 at n_ctx; OpenCode 2.1.4, `limit.output` 8,192 |
| Host | pythia and Zeus, split by a seeded task draw with both arms of a task on one host (D111.6); Strata 0.1.58 on both, accepted by counts (D102), or host as a stratum; `n_ctx` 32,768, one slot, D39 gate; `/props` checked before and after every run |
| Primary comparison | Task success (all `test_f_*`), `a4-d77` against arm 1, one designated attempt per task and arm, 25 tasks |
| Gate (mandatory) | `a4-d77` successes ≥ arm 1's (observed). Report the full 2×2 table, b and c, the paired difference with a Newcombe paired interval, and a two-sided exact McNemar at α = 0.05. No equivalence or noninferiority claim |
| Multiplicity | One confirmatory test. Secondaries are exploratory, with their p-values labelled so: per task "any constraint lost", per task trap repeat, and ho4 against ho5 |
| Constraints | Observed ≥ 90% over every constraint of every task (about 75). Ineligible ones are not dropped; eligibility is reported. Per-constraint and per-task tables; a task-clustered bootstrap (10,000 resamples, seed fixed in D115) |
| Traps | 0/20 `code` repeats (D109) on ho5 for `a4-d77`. Doubtful hits are reviewed blind to arm (labels stripped) and the review is recorded. Arm 1 is reported |
| Needles | Loose exact ≥ 95% over all 300. Count, Wilson and bootstrap intervals; no claim that the lower bound exceeds 95% |
| Per-archive gates | D44.6 inputs: 0 over budget, 0 excerpt or state leaks, `--explain` 0 unexplained, `transcripts verify` passing |
| Order | Tasks in a seeded random order. Each task's two arms run back to back, in seeded random order (`eval/phase7_schedule.py`, seed fixed in D115). Needles first, as in D77.8 |
| Repeats | 5 tasks drawn by seed before any run, both arms, after the primary runs. Descriptive only; never counted as pairs |
| Sampling and stopping | Fixed N. No extension inside Phase 7. An inconclusive result (\|b − c\| ≤ 1) goes to Phase 8 with the sealed reserve, if one is written |
| Reruns | Only for infrastructure failure (D44.7). A relaunch with the identical command is allowed between runs (D108). A pair split across host epochs is flagged, never rerun, and a sensitivity analysis without split pairs is reported |
| Defects | D44.8: stop, fix, then rerun the whole held-out set on the fixed commit. No waivers |
| Turn limit | 30 minutes per turn for both arms (D44, D77.5); kills reported per arm |
| Reproducibility | No seed is sent (OpenCode sends none; Strata's seed support is unverified). Sampling 1.0 / 0.95 / 20 (D48.3). Record commit, versions, hardware, cache warmness (epoch) and every upstream call, including refresh and compaction calls |

## 2. Slices

Seams: P pure · H fake-upstream HTTP · E eval · L live · D docs. Every tooling slice starts with red tests.

| # | Slice | Red tests | Code | Contract or docs |
|---|---|---|---|---|
| S0 | Preconditions | — | Full suite green on pythia at a clean tree | D111 (scope); `capabilities.md`: hidden tools experimental |
| S1 | Unseen sets and unlock | `test_unseen_sets_refused_without_unlock`, `test_unlock_needs_committed_protocol`, `test_heldout5_shape_and_hashes` (shapes only) (P) | `needle.SETS`/`UNSEEN_SETS`, `state_eval`, `run.TASKS`, `report.SET_SHAPE` | — |
| S2 | Serving metrics | `test_nonstreaming_refresh_records_timings_and_completion_tokens` (tap, H); if the gap is in the proxy, `test_notes_refresh_upstream_call_records_prompt_ms` (H), with the S0 goldens unchanged; `test_task_totals_include_refresh_and_compaction_calls`, `test_ttfvc_per_turn` (P) | `needle.Tap`/`parse_usage` or `pipeline` events; `run.py` totals | §10 or §17 text if events change |
| S3 | Host epoch | `test_epoch_recorded_before_after_each_run`, `test_pair_split_across_epochs_flagged` (P) | `run.py`, `needle_opencode.py`: boot id, Strata start time, `/props`, `nvidia-smi` memory | — |
| S4 | Traps for any arm | `test_trap_hits_from_chat_bodies_passthrough_arm`, `test_trap_hits_from_messages_bodies`, `test_need_turn_eligibility_collapsed_before_trap_turn`, `test_arm1_eligibility_compaction_before_trap_turn`, `test_t_scored_apart_from_success`, `test_check_reference_runs_trap_solution` (P/E) | `state_eval` (keyed by protocol), `run.score_check`, `--check-reference` | — |
| S5 | Phase 7 report and schedule | `test_mcnemar_literal` ((6,0)→0.03125, (5,0)→0.0625, (8,1)→0.0391), `test_missing_or_aborted_counts_as_failure`, `test_constraint_task_cluster_bootstrap_literal`, `test_needle_gate_095_over_300`, `test_schedule_seeded_reproducible_and_balanced` (P) | `report.py --phase7`, `eval/phase7_schedule.py` | — |
| S6 | Needle stratifier | `test_strata_dev_h1_literal`, `test_measured_depth_from_view_versions` (P) | `eval/needle_strata.py` | — |
| S7 | Trap standard and probe | `test_trap_probe_strips_warning_direct_upstream` (H, fake), `test_trap_suite_lint` (P) | `eval/tasks/trap_probe.py`; `AUTHORING.md`; dev-t6..t10 | D112 |
| S8 | Development pilot (L) | — | Temptation probes; `a4-d77`, `a4-tr` and arm 1 on dev-t6..t10 at real 32K | D112 amended if V1 or V3 fails; R64 |
| S9 | Held-out authoring | Authors' checks (§1.1) | ho5 (and the ho6 reserve) | D113 (hashes, authors) |
| S10 | Freeze and dress rehearsal | — | `needle.py preflight` on ho4 and ho5 (pass/fail only); the full pipeline on retired ho3 (2 tasks × 2 arms, plus 1 history) at F; the unlock file | D114 (tooling), D115 (protocol) |
| S11 | Held-out runs (L) | — | Needles, then 25 tasks per the schedule, then repeats; the 64K report if U1 allows | R65–R67 |
| S12 | Deterministic and lifecycle | Full suite at F; `archive_size.py` on held-out archives against R49's ±15% model | — | Pending list for Phase 8 |
| S13 | Reviews, results, tag | — | protocol-reviewer (S2), cache-auditor (every `--explain`), eval-runner; paper-fidelity n/a (no new mechanism) | R68 gate summary; tag `phase-7` |

**Order:**
1. S0.
2. S1–S7 in parallel; S7's brief is committed before S9 starts.
3. S8, which needs Strata at real 32K (U1).
4. S9, after S8 validates the standard.
5. S10, S11, S12, S13.

**Decisions:**
- D111: scope (Phases 5 and 6 skipped, hidden tools unclaimed, harness scope);
- D112: trap standard;
- D113: held-out authoring and seal;
- D114: Phase 7 tooling;
- D115: held-out protocol;
- later entries only for events, such as a D108-style relaunch.

## 3. Requirement → test / measurement / deferral

| Requirement | Test, measurement or deferral |
|---|---|
| A provisional checkpoint; Phase 8 checks pending, not passed | R68 marks each Phase 8 item "pending" |
| Existing contract failures still block claimed capabilities | S12: full suite at F, 0 failures |
| Same model, actual capacity, output reservation, tasks, initial repo and seeds | D115: pythia at real 32K (O2 refusal, `budget_refusal`); `limit.output` 8,192 for both arms; a fresh git workspace per run (`run.materialize`); seeds unverified and recorded |
| Isolated stores, reset repos | Existing per-attempt workspace, archive and OpenCode home (D45.9.3); checked in the S10 rehearsal |
| Record commit, versions, hardware, cache warmness, all proxy calls | D45.9.9 provenance; S3 epoch; S2 refresh calls; tap bodies |
| **Family 1:** ≥ 300 needles, stratified, held-out | ho4 (120) + ho5 (180); S6 strata; S11; per-stratum tables |
| Paraphrased retrieval (Phase 6) | Deferred: Phase 6 skipped (D111) |
| **Family 2:** ≥ 20 tasks crossing the budget, executable outcomes, early constraints, traps | 25 held-out tasks at real 32K (≥ 3 moves checked by `state_eval`); hidden checks; T1–T7 |
| **Family 3:** first visible content, latency, prefill and decode, internal iterations, all tokens, background work, cache reuse | S2 plus the existing taps; `--explain --by-cause`; refresh calls counted as internal iterations; background work 0 by design (D105.9); arm 1's compaction calls counted |
| **Family 4:** lifecycle tests | Identity: `test_passthrough.py`, `test_messages_gl1.py`. Forks and divergence: `test_archive_lifecycle.py`, `test_transcript.py`. Repetition: `test_identical_*`. Oversized input: `test_view.py`, `test_view_http.py`, `test_transcript_loop_http.py`. Mixed calls: hidden tools only, experimental (D111). Cancellation: lifecycle and `messages_gl1`. Retries: `test_review_fixes.py`, `test_crash_recovery.py`. Stale indexes: `test_transcripts*.py` rebuild, `test_strata_facts.py` staleness. Boundary crashes: `test_crash_recovery.py`, with ≥ 20 forced kills **pending (Phase 8)** |
| Needle exact match ≥ 95%, count and CI | S5 `needle_gate` at 0.95; D115 |
| Task success ≥ native, discordant pairs reported | S5 `--phase7`; D115 |
| Early constraints ≥ 90%, absolute failures | S4 and S5; per-constraint table |
| Repeated dead ends 0/20 | ho5 trap suite; S4; blind review |
| Upstream over budget 0; rejections apart | D44.6 input on every candidate archive; front-tap rejections |
| Internal tools exposed 0 | Excerpt and state leak scans per archive; §15 fixtures (`test_hidden_loop_http.py`) |
| Prefix changes all attributed | `--explain` 0 unexplained on every candidate archive; cache-auditor (S13) |
| Serving efficiency (informational; includes refresh and summaries) | S2; per-task paired ratios; regressions listed. Summaries: arm 1's compactions, n/a for the candidate (no Phase 5) |
| Durability and reconciliation | Deterministic suite passes for declared capabilities; branching, streaming replay and the crash matrix **pending (Phase 8)** |
| Output, time and backpressure limits | `test_deadline_http.py`, `test_messages_gl1.py` allowance, `test_admission_http.py`, the stalled-writer fixtures (Phase 3) |
| Physical storage growth | Scaling measured (R49 model checked in S12); enforced disk admission **pending (Phase 8 resource limits; capabilities: no disk budget)** |
| Every advertised capability | D111 scope: OpenCode confirmatory; Pi reported (U4); OMP and hidden tools have no quality claim |
| Freeze before held-out; no waivers | D115 before S11; D44.8 |
| Predeclared exact McNemar, α, primary comparison, multiplicity | D115 |
| Full table, difference, uncertainty, power floor | S5 report; §1.1 |
| Nonsignificance ≠ equivalence | R68 wording; D115 |
| Repeats not counted as independent pairs; task-level outcome declared | D115: attempt 1 designated; repeats descriptive |
| Cluster-aware intervals | History bootstrap (needles), task bootstrap (constraints) |
| Practical tolerances kept apart | D115: none used; serving numbers informational |
| Sampling and stopping rule | Fixed N; reserve to Phase 8 (D115) |
| Affordance selection separate | Nothing selected; frozen since D78 |
| A1 arms 2 and 3 | Deferred: measured on development data in R20; the candidate is arm 4 |
| A1: 32K then 64K | 32K confirmatory; 64K reported (U1) |
| A1: fallback use, unnecessary lookups, round trips, allocated memory | `report.py` needle metrics; S3 `nvidia-smi` |
| §12 privacy | Capture only under `--capture-dir`; S2 events carry numbers, never text (test) |
| Harness-neutral core | S4 keyed by protocol; AST seam test unchanged |

## 4. Costs

pythia at 32K. From R41: `a4-d77` about 46 min per task, arm 1 about 105 min.

| Work | Slot hours |
|---|---|
| Pilot S8 (probes, plus 5 tasks × 3 arms) | ~17 |
| Dress rehearsal S10 | ~5 |
| Needles, 300 | ~5 |
| Tasks, 25 pairs | ~64 |
| Repeats, 5 pairs | ~13 |
| 64K report (optional) | ~10 |
| **Total** | **~105–115 h, about 5 days continuous** |

Authoring (S9) uses agent time and about 1 h of probe slot time.

## 5. Risks

- **The needle bar is tight.** R41 had 115/120 = 95.8% loose and 94.2% strict. A few "extra text" answers decide the gate.
- **Hard traps may fail the 0/20 gate.** That is the point, but it is a real risk to the gate.
- **Arm 1 on a slow host** hits the 30-minute kill often (11 kills in R41). The rule is predeclared and the same for both arms.
- **The defect rule costs about 3 days per rerun.** The S10 dress rehearsal is the mitigation.
- **Host stability.** pythia is Linux, so Windows Update does not apply. Before S11:
  - turn off automatic reboots and package-triggered restarts;
  - run drivers outside the SSH login (D40, `KillUserProcesses`);
  - check disk space;
  - stop other services (D76).
  - If Zeus is used (U3), Windows Update is paused for the run window (D108).
- **ho4's traps predate the standard.** They are reported only.
- **Author correlation.** Mitigated by four authors.

## The user's answers (D111)

- **U1, U3:** pythia and Zeus, split by task, both at real 32K. Zeus moves to 0.1.58 first, or host becomes a stratum. pythia goes back to 64K afterwards; 64K is reported only.
- **U2:** 20 new tasks and 180 needles (`heldout5`), plus a sealed 10-task reserve (`heldout6`).
- **U4:** OpenCode is confirmatory. Pi on ho4 (Chat) is reported. OMP and hidden tools have no quality claim.
- **U5:** loose exact for the 95% gate; strict reported.
