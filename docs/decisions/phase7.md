# Phase 7 decisions

## D111: Phase 7 scope, hosts and the user's protocol choices (2026-11-19)

The Phase 7 plan (`docs/plan/phases/phase7.md`) left five questions to the user (U1–U5). This entry records their answers, the scope they set, and the consequences. D115, the frozen held-out protocol, inherits all of it.

1. **Phases 5 and 6 are skipped for now** (user decision).
   - **Why.**
     - The pinned state already retains decisions and constraints well (R61) and beat native compaction on ho3 (R41).
     - Phase 5's own green light asks that its cost be justified against Phase 4A, and nothing shows a gap a summary DAG would close.
     - Phase 6's paraphrased retrieval has no evidence of need.
   - **Reversible.** Either phase can return before Phase 8. Its gates then become mandatory, and the affected comparisons are rerun.
   - **Phase 7 rows they own** (paraphrased needles, summary cost) are deferrals, not passes.
2. **Candidate and baseline.**
   - The candidate is `a4-d77`, `serve`'s defaults (D78), frozen at the freeze commit F.
   - The baseline is arm 1, OpenCode's own compaction (D44.1).
   - `--hidden-tools` is experimental and not claimed for release. R32 failed both of its gates.
3. **Harness scope (U4).**
   - **OpenCode 2.1.4 is the confirmatory harness.**
   - **Pi 1.5.0** runs ho4's 5 tasks on Chat, `a4-d77` against its own compaction, reported only. This needs a held-out unlock in `pi_task.py`.
   - **OMP** gets no held-out quality claim.
   - `docs/capabilities.md` says so for OMP and hidden tools.
4. **Held-out size (U2).**
   - 20 new tasks and 180 new needles form `heldout5`. With ho4's 5 tasks and 120 needles, that makes 25 tasks and 300 needles.
   - A sealed 10-task reserve (`heldout6`) is kept for Phase 8's reruns.
   - Four separate author sessions write them under the plan's §1.1 process.
5. **Needle scoring (U5).** The 95% gate uses loose exact (R19), as D44.4 and D77 did. Strict exact is reported.
6. **Hosts (U1, U3): pythia and Zeus, split by task.**
   - **Context.** Both run Strata at a real `n_ctx` of 32,768 for the pilot and the held-out runs. There is no emulated budget (O2). pythia goes back to 64K afterwards, and 64K is a reported run only.
   - **Split.** Tasks are allocated to hosts by a seeded draw, fixed in D115. Both arms of a task run on the same host, back to back, in seeded order. A McNemar pair never spans hosts.
   - **One build.** D48, D76 and D103 do not allow a comparison to span builds, and Zeus runs 0.1.57 while pythia runs 0.1.58.
     - Before the pilot, Zeus is moved to 0.1.58, accepted by its counts (D102: `palimnesis check` and the counting cases).
     - If that cannot be done, host becomes a stratum. The 2×2 table and McNemar are reported per host and pooled, and the pooled result is labelled as spanning two builds.
   - **Host stability.**
     - **Zeus:** Windows Update is paused for the whole run window, and active hours are set to cover it (D108).
     - **pythia:** automatic reboots are off.
     - **Both:** every run records the host epoch (plan S3).
   - **Timing.** The hosts differ in speed, so latency and prompt time are compared within a host only.
   - **Cost.** About 5 days of slot time, spread over two hosts.
7. **Zeus moved to Strata 0.1.58 (2026-11-19, user request), accepted by its counts (D102).**
   - **How.** `strata update` offers only the newest release (0.1.62). Pointing it at the v0.2.12 release feed, which lists 0.1.58, is refused, because Zeus had already accepted a newer feed and the updater blocks replays. The replay protection was left in place. Instead:
     - **Engine 0.1.58** (`windows-x86_64-cuda-cuda13`) went in through `strata components install-file`. The package came from release v0.2.12 and its SHA-256 matched `SHA256SUMS.txt`. The installer checked its signature and every file, then test-started it: the model loaded and answered one token before the switch.
     - **Control 0.1.58** was unpacked from the same release's zip into `E:\Strata-0.2.11\terminal\0.1.58`, and the `current` junction now points there (`strata --version`: build 0.1.58).
     - **Rollback.** 0.1.57 stays installed: `strata components use 0.1.57`, and repoint `current` at `terminal\0.1.57`.
   - **Acceptance.**
     - `/props`: `build_info` "Strata 0.1.58", `n_ctx` 131,072, one slot, and the pinned chat template (`12827f24…`), the same as pythia.
     - `palimnesis check`: PASS upstream, PASS bounded views (`canary`).
     - Counting probes p04, p12, p14 and p15: every count equals the recorded fixtures. Two old p04 cases are no longer produced by the current probe; they are missing, not mismatched.
   - **One build.** Both hosts now run 0.1.58, so the pooled Phase 7 comparison does not span builds (item 6). Zeus still runs at 128K until the pilot relaunches it at 32K.

## D114: Phase 7 tooling as built (S1–S6, 2026-11-19)

Red tests first for each slice: `tests/test_phase7_heldout.py`, `tests/test_phase7_traps.py`, `tests/test_eval_phase7.py`, `tests/test_eval_phase7_tooling.py`, `tests/test_serving_metrics_http.py` and `tests/test_eval_needle_strata.py`.

1. **Unseen sets and unlock (S1, `eval/heldout.py`).**
   - **The sets.** `UNSEEN_SETS` is heldout4, heldout5 and heldout6. Task ids are ho4-t1..t5, ho5-t1..t20 and ho6-t1..t10. A listed task whose module does not exist fails with a clear error only when it is run.
   - **Unlocking a set needs all three of:**
     - `eval/heldout_unlock.json` names the set with a decision id (`{"unlocked": {"heldoutN": "D115"}}`);
     - a heading `## D115:` exists in `docs/decisions/`;
     - the unlock file is committed (tracked, and clean in `git status`).
   - **Who checks what.** Analysis tools (`state_eval`, `report.py`) refuse a locked set; their message keeps "D96". Run drivers also need a clean tree.
   - **Seal.** `heldout.py seal` and `verify` record and check the SHA-256 of each sealed file in `eval/heldout_hashes.json`, printing only paths and pass or fail.
   - **Pi.** Pi's drivers still refuse every held-out set that is not retired. Unlocking ho4 for Pi (D111.3) is a separate change before S11.
2. **Traps for any arm (S4, `eval/state_eval.py`, `eval/tasks/run.py`).**
   - **Captured bodies.** Trap hits are also read from the captured upstream request bodies, by protocol: Chat `tool_calls[].function`, and Messages `tool_use` blocks. Calls are deduplicated by id, or by position, name and arguments when there is no id. This covers arm 1, which has no archive. The archive path and the bodies path share D109's classifier.
   - **Need-turn eligibility.** The trap counts only if the warning had left the view when the trap turn's request arrived. Results report `trap_eligible_at_need` and `trap_repeat_at_need`.
     - **Archive:** take the view version in force when the first client user message containing `TURNS[TRAP_TURN]` arrived (whitespace normalized). The trap is eligible if that version's `collapse_seq` is at or past the statement's seq.
     - **Bodies:** in the first body whose user message contains the trap-turn text, the trap is eligible if no message (and no string `system`) still contains `TURNS[0]` in full.
   - **Scoring.** `score_check` reports `trap_tests` (`passed`, `failed`, `total`) apart from success, which still means every `test_f_*` passes.
   - **`--check-reference`** checks a task's `TRAP_SOLUTION`:
     - it passes every visible test (each `test_*.py` in `files()`) and every `test_f_*`;
     - it fails at least one `test_t_*`;
     - `TRAP_PATTERNS` match it and not the reference.
   - **The task-module trap contract:**
     - `TRAP_TURN`: an int, at least 5 and less than `len(TURNS)`;
     - `TRAP_SOLUTION`: path → full text, overlaid on `REFERENCE`;
     - hidden `test_t_*` tests, never counted toward success or constraints;
     - `TRAP_PATTERNS`, required whenever there is a trap solution.
   - **Not yet tested on real captures.** The bodies path has only seen synthetic bodies. The S10 dress rehearsal must run it on real OpenCode arm-1 captures.
3. **Serving metrics (S2).**
   - **The cause of the missing figures** (finding F2) was the proxy, not the tap. A refresh passed only its usage to cache accounting, and `ChatStream` dropped Strata's `timings`. Now refresh calls record `prompt_ms`, and every `upstream_call` event carries `completion_tokens`. These are numbers only (contracts §10). The upstream bytes are unchanged (S0 goldens).
   - **Totals.** `run.py` totals are reported combined and split into main, refresh and compaction calls.
   - **Time to first visible content** now comes from the front tap (the client's stream). A turn that starts with a refresh no longer gets one that is too early. The needle drivers still use the upstream tap; they are fixed or labelled before S11.
4. **Host epoch (S3, `eval/gate_inputs.py`).**
   - **The id.** The epoch is the first 16 hex digits of a SHA-256 over: the upstream URL, `build_info`, the `/v1/status` `engine`, the model, `n_ctx` and the `/v1/status` `started`. A relaunch changes it.
   - **When it is read.** `run.py` and the needle drivers read it before and after each run.
   - **Run flags:** a reading that failed, a changed epoch, a dropped `activity.requests` counter, and a dropped uptime.
   - **A pair is split** if either run is flagged, the readings differ, or a counter dropped between the two runs.
   - **Field names** come from the 0.1.48 status fixture. They are checked on 0.1.58 in the S10 rehearsal.
5. **Report and schedule (S5).**
   - **`report.py --phase7`** gives:
     - the 2×2 table;
     - a two-sided exact McNemar test;
     - Newcombe's paired interval (method 10), using z = 1.959964; it matches two published examples to six places;
     - the power floor;
     - the gate.
   - **Missing or aborted attempts** count as failures.
   - **Constraints** get a task-clustered bootstrap.
   - **Traps** use D109 `code` hits; `doubtful` hits await hand review.
   - **Needles** have a separate Phase 7 gate of 0.95, leaving Phase 3's 0.85 unchanged.
   - **Also:** a per-host breakdown, and exploratory secondaries labelled as such.
   - **`eval/phase7_schedule.py`** deals tasks to the two hosts by seed, alternating within each set, so each host's count and its count per set differ by at most one. Task order on each host and arm order within each task are seeded, and 5 repeat tasks are drawn.
6. **Needle strata (S6, `eval/needle_strata.py`).**
   - **Labels** are pure and come from the history's definition: source role, placement by token third, planned depth against B_in, and distractors. The superseded and irrelevant-matches categories fix the distractor label; otherwise lookalike values in earlier history decide it. A step can also declare its own `strata`.
   - **`measured_depth`** reports whether the fact was in view, only in an excerpt, or absent at the question's request, plus the view moves since the fact arrived.
   - **Limit.** Every masked tool result counts as out of view.
7. **Held-out integrity (D96).** While building S1, one early search printed a few lines from the ho4 files:
   - `SET = "heldout4"` from `eval/tasks/ho4_t*.py`;
   - header lines of `eval/needle_gen_ho4.py`: output path, set name, earlier folders, a function name and a docstring line.
   No task text, constraint, trap, needle, history or answer was shown. Every later search left those paths out. ho4 is still treated as unseen. The remedy is to keep tooling searches away from held-out paths: `eval/heldout.py` holds the set names, so nothing needs to search those paths again.
