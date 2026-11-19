# Decisions: Phase 4A (D105–)

[Index](README.md) · Material choices, their reasons and rejected alternatives; newest last.

## D105: Phase 4A plan decisions (2026-11-18)

The plan is `docs/plan/phases/phase4a.md` (planner output, 2026-11-18). The user asked to proceed without being asked. Its two user questions were therefore settled on the planner's recommendation, and they are recorded here so they can be revisited.

1. **The state is the working notes.** 4A evolves the notes, without a parallel mechanism: the code keeps `notes`, and contracts §17 names them the pinned state.
   - Rejected: a separate `state_versions` table and its own block. That means two refresh paths, two S terms and two sets of cache rules for one job.
2. **No `palimnesis_state_update` tool** (the plan's U1; a departure from v1's named deliverable). The model writes the state through D72's proxy-triggered refresh, which the user chose over a hidden tool (D72, choice B).
   - **Why not a tool:**
     - R32: hidden tools failed both held-out gates, with invalid ids and 2.2× the prompt tokens.
     - Messages offers no hidden tools (contracts §16), so a tool would split behaviour by protocol.
     - A commit in the middle of a turn re-reads everything after the system message.
   - **Revisit** only if Phase 7 shows state going stale within a turn. The name stays reserved under `palimnesis_`.
3. **The slot stays 2,048 tokens**, a deviation from v1's 800.
   - **Evidence:** R41 passed held-out at 2,048; R34-C showed cuts losing the last sections; n2 sizes its request to S.
   - **Optional:** an 800 arm is a reported development run only if slot time allows.
   - **Deferred:** scaling S with the budget.
4. **The refresh output and its provenance are archived** (store v7: `notes_outputs`, `notes_sources`). Then the originals of a cut stay retrievable, and every version names its cutoff, call id and formats.
   - **Not indexed.** State text is not indexed for recall: it would turn the model's own claims into evidence (D66, D71).
5. **GL1 is met by measurement.**
   - `state_marginal_tokens` is recorded on every `state_commit` pair.
   - `eval/replay.py --explain --by-cause` reports re-read tokens and time per cause.
   - Every development archive must show 0 unexplained changes.
6. **The priority cut needs evidence.** It is built only if more than 10% of committed versions in the S10 baseline dropped a line under *Requirements and constraints* or *Dead ends*. Otherwise it is deferred, with the measured rate recorded.
7. **n3 ("Useful addresses") is one candidate arm.** `a4-trn3h` runs on development data and is reported. A default change is a separate decision, frozen before Phase 7.
8. **Conflict and provenance rules** as in the plan, §1.5. The notes header is unchanged.
9. **No background or fallback refresh.** There is one slot, and contracts §8 has no background inference. A failed refresh keeps the previous version.
10. **Legitimacy.**
    - **Gates.** 4A's gates are the deterministic tests and GL1. GL2 is reported on development data against Phase 7's bars, for information.
    - **Held-out sets.** `ho4` stays unseen (D96). ho3, judged in R41, is retired to development data (the D69 pattern), at the cost of spending it.
11. **Refreshes that never render** (D93's known cost) are measured in the S10 archives. Skipping them is deferred, because it would change `a4-d77`.
12. **Host and context for S10** (the plan's U2).
    - **Zeus.** The user made it available for testing again (2026-11-18). Every arm of a comparison runs there: Strata 0.1.57, accepted by its counts (D102), at an emulated 32K (`--input-budget 24320`), without restarting Strata.
    - **Before any run:** `palimnesis check` passes, and the counting cases match.
    - **Fallback.** If Zeus is busy, the whole comparison moves to pythia (0.1.58, 64K, also at an emulated 32K). Arms are never split across hosts or builds (D48, D76, D103).
    - **The 64K report run** stays on pythia as it stands.
    - **Protocol.** The full evaluation protocol is written as its own decision entry before the first S10 run.

## D106: Phase 4A reviews of S0–S8: provenance never changes what the model sees (2026-11-18)

A protocol review and a cache audit covered S0–S8 before any evaluation run. The cache audit found no unexplained change, and confirmed the S0 fixture is `phase-4b`'s bytes. Each fix below has its test first (`tests/test_state_review_fixes.py`, `tests/test_state_cost.py`, `tests/test_state_golden.py`).

1. **Provenance could veto a version (protocol review, high).**
   - **The failure.** A refresh's reasoning can hold a lone surrogate, an emoji split across deltas, which Strata produces. The new `notes_outputs` insert encoded it strictly, so the whole notes write rolled back and the model lost a state `phase-4b` would have rendered. An error while recording sources had the same effect.
   - **Storage.** Content and reasoning are now stored as WTF-8 bytes (`BLOB`), as the archive stores other text.
   - **A savepoint.** Outputs and sources are recorded under a savepoint inside the version's transaction. A failure rolls back only them and records `notes_provenance_failed`; the version commits as before.
2. **No branch scan under the write lock** (both reviews). Checking a cited turn file read the whole branch inside `BEGIN IMMEDIATE`. The highest turn is now counted from the request before the write (`pipeline._highest_turn`).
   - **Turn files.** `turn-0000`, the system prompt's file, is valid, and turn numbers may have more than four digits.
   - **Blocks.** A cited `§ALIAS.N` is `valid` only if block N exists.
3. **`palimnesis state --raw` for notes taken from the reasoning** marked lines of the cut text instead of the reasoning's draft that `dropped` indexes. It now shows the draft.
   - **Clear refusals.** The CLI refuses `--raw` and `--sources` without `--version`, and explains an archive older than v7 instead of raising.
   - **Uncut failures.** A failed refresh whose cut never ran stores `dropped` as null, shown as `-`.
4. **The marginal cost** (`state_marginal_tokens`, cache audit). It now aligns turns after the notes block once notes blocks are set aside. The old positional comparison undercounted a first notes block with no other change. It also ends at the generation prompt.
   - **Literal values.** The tests check the scenario's literal values (143 and 1,920 tokens) and three hand-built layouts.
   - **Known imprecision.** The cut lands at the start of a segment, so unchanged results earlier in the same tool-result run are not counted.
5. **`--by-cause`.**
   - It splits a commit's re-read into the state's share and the rest (`with_state_tokens`), and reports each refresh call's own re-read.
   - It drops `completion_tokens`, which `upstream_call` events never carry.
   - It counts pairs with no measurable re-read apart.
6. **The golden.**
   - **Exact text.** It compares normalised body text exactly, not parsed JSON.
   - **Aliases.** It keeps alias lengths in their placeholders.
   - **No transcript paths.** It runs without transcript files, because their temporary root put a path of varying length into the system message, which moved token counts and excerpt cuts.
   - **Deterministic ids.** Record ids come from a counter, because aliases hash from ids and their characters move token counts.
   - **A second session, `rich`.** It covers notes taken from the reasoning with a split surrogate, a cut citing an alias by block, cited turn files, and four selected excerpts. Without fix 1 it fails.
   - **Recording.** Both fixtures were recorded on `phase-4b` code in a worktree, and both pass there and on the current code, twice each.
7. **Claims cut back to what is enforced.**
   - **Crash between version and move (a known limit).** The plan said a retry or restart never refreshes twice for one move. A crash or cancel between the version's commit and the view move's commit refreshes again; this predates 4A and is now a known limit in contracts §17.
   - **Smaller fixes.** The excerpt isolation test now requires a selected excerpt. `archive_seq` takes `seq is not None`. New tests cover the insert guards on both new tables, a v6 to v7 migration that keeps its notes, and ambiguous and cross-session aliases.
8. **Retiring ho3 (D105.10)** moved the tests that guard held-out sets to `heldout4`.

## D107: Phase 4A evaluation protocol (S10), fixed before any run (2026-11-18)

Written before the first S10 run, as D105.12 requires. Everything here is development data. It is reported against Phase 7's bars for information and gates nothing (D105.10). `ho4` is never opened (D96).

1. **Host and build.**
   - **Where.** Every arm of a comparison runs on Zeus (`http://192.168.1.19:8080`): Strata 0.1.57, model `qwen3.8-flash-next-iq3_xxs`, `n_ctx` 131,072, `--parallel 1`. Zeus is accepted by its counts (D102; `palimnesis check` passed on 2026-11-18).
   - **Context.** Emulated 32K: `--input-budget 24320 --expect-n-ctx 131072` (O2). Runs are labelled emulated; emulated 32K is not real 32K.
   - **Before each run** `run.py` reads `/props` and refuses another `n_ctx`. Nothing restarts Strata.
   - **Fallback.** If Zeus is busy or its build changes mid-comparison, the comparison stops. It restarts from its first run on one host and build, never split (D48, D76, D103).
2. **Harness.** OpenCode 2.1.4 on this Windows machine, through `eval/tasks/run.py`. Runs are sequential (D39), with the 30-minute turn kill, and each kill is reported.
3. **Retired sets may emulate.** Retired sets (ho2, ho3) are development data, so they may now run at an emulated budget (`run.budget_refusal`; tested). An unretired held-out set still runs only at the real context (O2).
4. **Arms.**
   - **Baseline:** `a4-d77`, `serve`'s defaults. It measures GL1 and gives GL2's numbers.
   - **Ablation:** `a4-tr`, which is `a4-d77` without notes.
   - The configuration is fixed for each whole run.
5. **Tasks.** dev-t1..t5, ho2-t1..t5 and ho3-t1..t5: 15 tasks, one attempt per task and arm, run in that order, the baseline arm first. A rerun is allowed only for an infrastructure abort, with a recorded `--reason`.
6. **Measured on every archive.**
   - The D44.6 gate inputs `run.py` records: 0 over budget, 0 leaks or echoes, `--explain` 0 unexplained, `transcripts verify` passing.
   - `eval/replay.py --explain --by-cause` (GL1), and `eval/state_eval.py` (GL2).
7. **GL2 counting.**
   - **Eligibility.** A task's constraints and trap count only when at least 3 watermark or collapse moves follow the first instruction, where every task states them.
   - **Constraints.** Held means `test_c<N>` passes.
   - **Trap repeats.** Detected by `TRAP_PATTERNS` (8 tasks). The 7 tasks without patterns, and every doubtful hit, are reviewed by hand from the archive and the final workspace, and that review is recorded.
8. **The priority cut (D105.6).** It is decided from the baseline's committed versions: the share whose cut dropped a line under *Requirements and constraints* or *Dead ends*, read from `notes_outputs.dropped`.
9. **Reporting.**
   - Per arm: tasks passed, constraints held of those eligible, trap repeats of those eligible, refresh count and failures, cut rate, cited-address status counts, `state_marginal_tokens`, and re-read per cause. Rates carry Wilson intervals.
   - Arm against arm: paired by task, with discordant counts. One attempt per task shows direction, not effect size.
10. **Not in this evaluation.**
    - The n3 candidate arm: S9 is not built. It is a later decision, if the baseline shows a need.
    - The dev-state needle set (plan §4): not built. GL2 uses tasks only.
    - The 64K report run: later, on pythia as it stands.
    - The Pi Messages neutrality smoke: later, once Pi is set up on this machine.
