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

## D112: The trap-design standard, as built for the S8 pilot (2026-11-19)

R61 showed that 4A's traps separated nothing: neither arm repeated any of them in 30 runs. Phase 7's "0/20 repeated dead ends" gate means something only if the warned-off approach is a real temptation. This entry fixes the standard, and S8 tests it on development data before any held-out task is written (plan §1.2).

1. **T1–T7** are the plan's criteria (plan §1.2): tempting, passes a quick check, needed late, independent of the constraints, detectable, a separate outcome, and out of view when needed. `eval/tasks/AUTHORING.md` gives authors the same rules as instructions, without results or rationale.
2. **Module fields.** The task-module contract is in D114.2. S7 added:
   - **`TRAP_WARNING`:** the exact warning sentence in `TURNS[0]`. The probe strips it and `TRAP`, and the lint requires it.
   - **Trap patterns are alternatives.** At least one `TRAP_PATTERNS` entry must match the trap solution's code, and none may match the reference, the pre-trap stub or the trap turn's request. This is `--check-reference`'s pattern check, aligned with the lint.
   - **Trap solutions also pass every `test_c*`.** That is stricter than required, and it supports T4: no constraint rules the trap out.
3. **The temptation probe (T1, `eval/tasks/trap_probe.py`).**
   - **What is sent.** The trap turn's request, sent directly to the upstream with no proxy, in a fresh conversation (a system message and one user message). It includes the workspace as it stands at that turn: every file from the reference except the files the trap solution replaces, which stay as stubs.
   - **What is left out:** files over 8,000 characters (the long document and the big suite), any history, and the warning.
   - **No sampling parameters** are sent. The model name comes from `/props`.
   - **Scoring.** Three samples. T1 passes when D109's classifier finds trap code in at least 2 of them.
   - **Consequence for authors:** the trap turn's code must live in its own file or files.
   - **Never run live yet.** The S8 pilot is its first live run.
4. **The pilot tasks, dev-t6..t10.** All five have `TRAP_TURN` 6, which is turn 7, after both suite runs. Each passes `--check-reference` on every check: contract, reference, stub, trap and patterns.

   | Task | X, the warned-off approach | Y, why it fails |
   |---|---|---|
   | dev-t6 | `round()` for a whole-number percentage | 84.5 becomes 84, and the grade band drops |
   | dev-t7 | `json.dump(..., indent=2)` without `ensure_ascii=False` | "Zürich" is written escaped |
   | dev-t8 | `urllib.parse.quote(name)`, default `safe="/"` | "AC/DC" becomes two path segments |
   | dev-t9 | `sorted(..., reverse=True)` for "most points first" | ties come out Z to A instead of A to Z |
   | dev-t10 | `textwrap.wrap(text, width)` with hyphen breaks left on | "Weston-super-Mare" is split at a hyphen |

5. **Validation (S8).** The pass conditions are the plan's V1–V3:
   - V1: T1 passes on at least 4 of the 5 tasks;
   - V2: T7 holds in every `a4-d77` and `a4-tr` run;
   - V3: at least one D109 `code` repeat across `a4-tr` and arm 1.
   If V1 or V3 fails, this standard is revised once and piloted again before any authoring starts.
6. **Not yet built at S8.** There was no tool for the independence check (no 4-word run shared with an earlier set), and the needle `strata` field format was not pinned. Both are built in D113.
7. **First pilot result: V1 failed, so the standard is revised once** (2026-11-19).
   - **The probe.** Run on pythia and Zeus, both on Strata 0.1.58 at a real 32K, 3 samples per task. T1 passed on 1 of 5 tasks: dev-t7, 3/3. dev-t6, t8, t9 and t10 each scored 0/3.
   - **What the model wrote instead:**
     - dev-t6: `int(x + 0.5)`, which rounds half up correctly;
     - dev-t8: `quote(name, safe="")`, also correct;
     - dev-t10: its own word-wrapper, never `textwrap`;
     - dev-t9: one sample was correct, but another wrote `rows.sort(key=lambda r: -r.points)`. That keeps ties in input order, a real variant of the trap, which the `reverse=True` pattern missed.
   - **The lesson.** The model already knows the standard library's well-known pitfalls, so a trap built on one does not tempt it. The trap that worked (dev-t7) fails only because of a fact about the task: the data contains non-ASCII names, and nothing visible at the trap turn shows it.
   - **The revision**, applied once (plan §1.2):
     - **T1a.** X is the right approach for everything visible at the trap turn: the request, the workspace and the visible tests. Its failure Y depends on a task-specific fact (about the data, a consumer or the environment) that only the turn-1 warning states. It must not be general programming knowledge.
     - **T5a.** `TRAP_PATTERNS` cover X's common variants, not only one spelling. dev-t9's miss shows why.
   - **Next.** dev-t6, t8, t9 and t10 are rewritten under T1a and T5a, keeping their themes where they fit. Then the probe runs again. If V1 fails again, the pilot is reported as is, and authoring waits for the user's decision.
8. **Second probe after the revision: V1 passes, 5 of 5** (2026-11-19).
   - **The rewritten traps** (`f5aee75`), each failing only on a fact the warning alone states:
     - dev-t6: a board that never rounds up;
     - dev-t8: names that arrive decomposed (NFD) while the site keys by composed form (NFC);
     - dev-t9: ties broken by the season's total score;
     - dev-t10: a printer that measures lines in UTF-8 bytes.
   - **The probe**, run on Zeus (0.1.58, 32K), 3 samples per task: dev-t6 2/3, dev-t8 3/3, dev-t9 3/3, dev-t10 3/3. dev-t7 was 3/3 in probe 1.
   - **Every hit was read by hand and is the real trap:** `quote(…, safe="")` without NFC, character-length line widths, `int(x + 0.5)`, and ordering by points alone or by points then name.
   - **Caution for V3.** The dev-t8 pattern (quote with no `normalize(` in the same text) and the dev-t10 pattern (`len(word)` and the like) can fire on correct code. Every pilot `code` hit is therefore read by hand before it counts.
9. **After the pilot (R64, 2026-11-20).**
   - **A `code` hit counts as a repeat only when that run's `test_t_*` also fails.** When the two disagree, a person reads the run and records the verdict before it counts. The pilot's one disagreement was a false hit: dev-t10 `a4-tr`, on correct code. The 2 genuine repeats (dev-t6, dev-t8) had both.
     - `report.py --phase7` applies this. Each suite run gets a verdict: `repeat`, `clean` or `disputed`. A disputed run fails the trap gate until `--trap-reviews FILE` records its hand verdict (`{"task:arm": {"repeat": bool, "note": …}}`). The report lists disputed and reviewed runs. A check with no trap tests falls back to the `code` hit alone.
   - **dev-t10's `len()` pattern now fires only on a comparison or a sum** (`len(word) > width`, `len(current) + 1 + …`). The false hit was the slice `word[len(piece):]`. `tests/test_trap_standard.py` keeps the lines that pilot runs falsely matched. With the new patterns, re-scoring the pilot leaves dev-t10 with 0 `code` hits and keeps both genuine repeats. The pilot was run once; the patterns are not re-piloted.
   - **Authors are told the same** (`AUTHORING.md` §1.5): a pattern should match X as it is used, not a name that correct code also uses.

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
   - **Pi.** At S1, Pi's drivers refused every held-out set that was not retired. D113.3 lets Pi's task driver run ho4.
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
   No task text, constraint, trap, needle, history or answer was shown. Every later search left those paths out. ho4 is still treated as unseen. While building S7, a repo-wide search for "four-word" also printed two comment lines from `eval/needle_gen_ho4.py`, about its phrasing bank and its check. No content was shown. The remedy is to keep tooling searches away from held-out paths: `eval/heldout.py` holds the set names, so nothing needs to search those paths again.

8. **Phase 7 reports combine independent host run directories.** Keep one task attempt manifest per host so simultaneous writes cannot race. `report.py --phase7` accepts another task run directory through `--pool` and rejects a task recorded in multiple directories. Repeat `--needle-run` to combine separate history runs. The report enforces the unlock for declared task sets, attempt task IDs and needle directories before using sealed results or scoring keys.

## D113: Held-out authoring and seal (S9, from 2026-11-20)

Red tests first: `tests/test_independence.py` and `tests/test_eval_needle_strata.py`. This replaces D112.6's "not yet built".

1. **The independence check (`eval/independence.py`)** compares new task modules and needle histories with dev, ho, ho2, ho3 and ho4, by default. It prints only pass or fail per file, with counts.
   - **Wording** is prose only:
     - a module's string literals and comments; a string that is itself Python code (a reference, a stub, a test file) adds only its own comments, docstrings and strings;
     - a history's user and assistant text and step text, not tool output (as ho2's generator does).
     - Words are letters only. A path, an identifier, a number or a backtick span breaks a four-word run.
   - **Identifiers:** the packages, modules, functions and classes that embedded code defines. Names under 3 characters, names starting with `_` or `test`, and the harness paths `tests`, `docs` and `_check` are left out. They are matched whole and case-sensitive.
   - **Planted values:** the ho2 rule. A needle answer or part with a letter must not occur in an earlier history; a numeric one must not be an earlier answer.
   - **What is exempt:**
     - runs in `eval/tasks/common.py` and in the fixed wording of turns 1, 3, 5 and 7 of dev-t6..t10 (`AUTHORING.md` §3);
     - **any run or identifier that two or more earlier sets already share.**
   - **Why the two-set rule (a deviation from a literal reading of plan §1.1).** Calibrated on ho3, which was written apart from dev, ho and ho2, the literal rule failed every ho3 file. The shared runs were mostly:
     - generic English ("and tell me what", "run the full suite");
     - the lead's own header comments;
     - the task skeleton's names: `errors`, `legacy` and the hidden-test harness.
     With the exemption, ho3's identifier hits fall from 42 to 1 and its shared wording runs from 503 to 295. What remains is mostly ho3 reusing ho2's request and comment phrasing, which is what the brief forbids. Wording copied from a single earlier set still fails.
   - **`--explain`** lists what is shared with dev, ho, ho2 and ho3. ho4 and every `--also` file (other authors' work) are sealed: their matches are counted, never shown (D96). Calibration ran against dev, ho and ho2 only, and no ho4 text was printed.
2. **The needle `strata` format is pinned** (`eval/needle_strata.py`):
   - **The format.** A question step carries `"strata"` with exactly the keys `source_role`, `placement`, `planned_depth` and `distractors`, at the levels the labeler computes. `other` and `unlocated` cannot be declared.
   - **The author check.** `--check` (`check_declared`) requires each declared level to equal the computed one, so the per-level counts measure the files, not intent. A depth between bins must be moved into one.
   - **The lead's check.** `--coverage [MIN]` counts declared needles per level over a set and fails below 30 (plan §1.3).
   - **The brief.** `AUTHORING.md` §2 gives the exact keys, levels and token bounds: 12,160, 24,320–48,640 and 72,960, which are 0.5x, 1–2x and 3x of B_in. These replace the rounded figures it had before.
3. **Pi may run ho4's tasks (D111.3)** (`eval/tasks/pi_task.py`).
   - It runs them on Chat only, never against the fake upstream, with `a4-d77` and Pi's own compaction. The results are reported only.
   - The unlock and the clean tree are still checked first, by `run.task_refusal` (`heldout.run_refusal`), so a locked ho4 is refused before Pi's own rules.
   - heldout5 and heldout6 stay refused for Pi. Pi's needle driver is unchanged: Pi runs no held-out needles.
4. **Wave 1 enforces T2 in `--check-reference`.** The trap implementation must pass every constraint check as well as the visible and functional tests. The reference checker previously accepted a trap solution that broke a constraint. The regression test isolates that case with a changed function signature.
5. **Wave 2 can cover the strata without using ho4 labels.** Each of the 18 histories keeps ten questions and the existing paste and restart positions. The second identifier question asks for a current identifier that replaced an earlier value, so it is also scored in the superseded category. One superseded item per history would cap ho5 coverage for that level at 18. Two make the minimum of 30 possible before the protocol freeze, when the ho4 labels are still unavailable.
6. **The fixed trap warning has two exempt four-word runs.** The author brief specifies “Also, we already tried X, and it failed because Y.” The independence check exempts “also we already tried” and “and it failed because” as prescribed wording. Runs that include the approach or failure remain subject to the check.
7. **OpenCode preflight requires at least one selected history.** A set-qualified selector such as `ho3-h1` previously returned success for zero histories. An empty selection now fails, and `--histories h1` imported the retired history faithfully at 101/101 messages using OpenCode 2.1.4.
8. **Who wrote what.** Four author sessions, each in its own domain, wrote the held-out files. Later sessions with the same assignments fixed them under the same reading rules: the brief, `common.py`, their format examples and their own files only.

   | Author | Domain | ho5 tasks | ho6 tasks | Generator and histories |
   |---|---|---|---|---|
   | A | farming, gardening, bees, orchards, weather stations | t1–t5 | t1–t3 | `needle_gen_ho5_a.py`, h1–h5 |
   | B | libraries, museums, archives | t6–t10 | t4–t6 | `needle_gen_ho5_b.py`, h6–h10 |
   | C | clinic, pharmacy, veterinary admin | t11–t15 | t7–t8 | `needle_gen_ho5_c.py`, h11–h14 |
   | D | municipal and civic services | t16–t20 | t9–t10 | `needle_gen_ho5_d.py`, h15–h18 |
9. **Pre-seal checks (2026-11-20).** The lead ran these on a clean checkout of `2d29048` plus the uncommitted files and saw only pass/fail and counts.
   - **`--check-reference`:** all 30 tasks pass.
   - **The four generators' `--check`:** each reproduces its files byte for byte.
   - **Declared strata:** all 18 histories pass.
   - **Coverage:** at least 35 needles per level, against a floor of 30.
   - **Independence from earlier sets:** four tasks failed, each with one four-word run: ho5-t17, ho6-t3, ho6-t9 and ho6-t10.
     - In three of them the run was the prescribed “it failed because” plus the article that began Y. The D113.6 exemption covers “and it failed because” but not that run.
     - The authors reworded the Y clauses (ho6-t3: the short-form `TRAP` text).
     - After the fixes, every file passes.
10. **The probe re-run, and a stricter bar for revisions.** Every task was probed again: A and B on pythia, C and D on Zeus (driven from pythia over the LAN). Both hosts run 0.1.58 at 32K with the same model.
    - **The first round failed eight tasks:** ho5-t4, ho5-t11, ho5-t12, ho6-t4, ho6-t5, ho6-t6, ho6-t8 and ho6-t9.
    - **Why the bar changed.** The first revision of ho5-t4 passed 2/3 for its author, then 0/3 on the lead's rerun. A single 2/3 pass can be chance.
    - **The new bar:** a revised task must pass two consecutive probe runs on the same final revision.
    - **ho5-t4:** revision 2 passed 3/3 and 2/3 for its author and 3/3 for the lead. Its `TRAP_PATTERNS` gained other spellings of the same approach. Scoring still needs a failed `test_t_*` as well (D112.9), so wider patterns alone cannot count a repeat.
    - **ho5-t11 and ho5-t12:** 2/3 on each of two runs. ho5-t12's change runs through the stub, document, tests, reference and trap solution.
    - **ho6-t9:** 3/3 for its author and 3/3 for the lead.
    - **ho6-t8:** still 1/3 after three revisions, and one of those revisions narrowed its patterns. It was replaced by a new task in a new theme, written by a fresh Author C session that never read the old file. The new task passed 3/3 on each of two runs.
    - **ho6-t4..t6:** a fresh Author B session revised all three. Each passed 3/3 on two consecutive runs.
      - ho6-t4 needed three revisions and ho6-t6 four, the last one allowed. ho6-t5 needed one.
      - The changes: an already-written helper or module in the initial repository, a reworded trap-turn request, and new example values in the visible tests and the matching functional test.
      - Their trap patterns and hidden trap tests are unchanged.
    - **The tasks never revised** passed their single run at 2/3 or better.
11. **Cross-author overlap is reported, not gated (user decision, 2026-11-20).**
    - On the final files, the cross-author check (each author's files with `--also` the others') fails 20 task files, with 69 four-word runs and 4 identifiers in all.
      - The new ho6-t8 accounts for 16 of those runs.
      - No needle file or generator fails it.
    - Plan §1.1 requires independence from the earlier sets only.
    - The matches are sealed, so authors could reword only blindly. Many matches likely come from the brief's own fixed phrasing.
    - The counts are recorded here, and the check does not block the seal.
12. **What reached the lead (exposures).**
    - **ho6-t3.** While fixing it, Author A bisected its own module against the sealed ho4 match. That session learned only that one of its own four-word runs occurs in ho4. No ho4 text was printed.
    - **ho6-t9.** Author D's fix report named ho6-t9's package and module, the topic of the trap-turn request, and the helper it added. The lead now knows part of ho6-t9's trap setup.
    - **ho6-t8.** Author C's report described the old ho6-t8's trap, which has since been replaced.
    - Both ho6-t9 and ho6-t8 are in the Phase 8 reserve, not in the Phase 7 scoring set.
    - Later author briefs limit reports to pass/fail, counts and a fixed list of generic location words.

## D115: The frozen held-out protocol (S10, 2026-11-20)

This entry is the protocol of plan §1.4, fixed before any held-out run. It inherits D111. Nothing in it may change after the first held-out run. A defect stops the runs (D44.8).

1. **What is compared.**
   - **The freeze commit F** is the commit that carries this entry.
     - The candidate is `a4-d77`, `serve`'s defaults (D78), at F.
     - After F, commits may change only `eval/` and `docs/`. The S0 goldens guard the upstream bytes.
   - **The baseline** is arm 1: `serve --passthrough`, OpenCode's own compaction, `limit.context` 32,768 (D44.1).
   - **Both arms:**
     - OpenCode 2.1.4;
     - `limit.output` 8,192;
     - a fresh git workspace, archive and OpenCode home per attempt (`run.materialize`, D45.9.3);
     - a 30-minute turn limit (D44, D77.5), with kills reported per arm.
2. **Hosts and the run streams.**
   - **The hosts.** pythia (192.168.1.173) and Zeus (192.168.1.19). Both run Strata 0.1.58 at a real `n_ctx` of 32,768 with one slot, the same model and no emulated budget (O2). Zeus's build was accepted by its counts (D111.7).
   - **The driver.** Each host is driven from the lead's Windows workstation, as in the S8 pilot. There is one run stream per host, and each writes its own attempt manifest (D114.8).
   - **The host epoch** (`gate_inputs.host_epoch`) is recorded before and after every run.
   - **Before S11:**
     - automatic reboots are off on pythia;
     - Windows Update is paused on Zeus (until 2026-12-20) and on the driver workstation;
     - every host has free disk space.
3. **Schedule.** `eval/phase7_schedule.py --seed 115` over ho4-t1..t5 and ho5-t1..t20, committed as `eval/phase7_schedule_d115.json`.
   - **Split.** pythia runs 13 tasks (3 ho4, 10 ho5) and Zeus runs 12 (2 ho4, 10 ho5). Both arms of a task run back to back, on its host, in the listed order.
   - **Repeats.** ho5-t6, ho4-t2, ho5-t2, ho5-t10 and ho4-t4 run on their listed hosts after all primary runs. They are descriptive only and never counted as pairs. Attempt 1 is the designated attempt.
   - **Needles come first,** on `a4-d77` only.
     - pythia runs the odd-numbered histories of each set: ho4-h1, h3 … h11 and ho5-h1, h3 … h17.
     - Zeus runs the even-numbered ones.
     - Each host writes its own needle run directory, and `report.py --needle-run` is repeated to combine them.
   - **Run directories (from the rehearsal).** Each host has one task run directory, and its attempt manifest holds both arms of every primary task. The manifest designates the latest attempt, so the repeats go in a separate run directory and never supersede a primary attempt. Each host writes one needle run directory per set. The report pools the two hosts' task directories with `--pool` and lists all four needle directories with `--needle-run`.
   - **The driver** (`captures/run-phase7-s11.ps1 -HostName H -Upstream U`) prints the host's numbered plan and runs it in order. It stops on any nonzero exit. The lead then either reruns that step for an infrastructure failure (`-Start N -Reason TEXT`, D44.7) or resumes at the next step (`-Start N+1`), and the choice is recorded.
4. **Primary comparison and gate.**
   - **What is compared.** Task success means every `test_f_*` passes. It is measured per task on the designated attempt of each arm, over 25 tasks.
   - **The gate (mandatory):** `a4-d77`'s successes must be at least arm 1's, on the observed counts.
   - **What is reported:**
     - the full 2×2 table, with b and c;
     - the paired difference, with a Newcombe paired 95% interval;
     - a two-sided exact McNemar at α = 0.05. This is the one confirmatory test.
   - **What is not claimed:** equivalence or noninferiority. A nonsignificant result is not equivalence.
   - **Missing data.** A missing, aborted or killed attempt counts as a failure.
5. **Secondary gates and reports.** Their p-values are labelled exploratory.
   - **Constraints.** Observed ≥ 90% for `a4-d77`, over every constraint of every task. An ineligible constraint is not dropped; its eligibility is reported. Per-constraint and per-task tables are reported, with a task-clustered bootstrap (10,000 resamples, seed 44).
   - **Traps.** The declared trap suite is ho5 (`--trap-suite ho5`). `a4-d77` must have 0 of the 20 ho5 tasks with a `code` repeat. The report runs `state_eval`'s trap scan on each designated attempt: from its archive, or from the captured bodies for arm 1. A repeat counts only when a `code` hit and a failed `test_t_*` agree (D112.9). A disputed hit is reviewed blind to arm, with arm labels stripped, and the review is recorded (`--trap-reviews`). Arm 1's repeats and ho4's traps are reported only.
   - **Needles.** Loose exact ≥ 95% over all 300 (R19, D111.5). Reported with:
     - the count;
     - a Wilson interval;
     - a history-clustered bootstrap (10,000 resamples, seed 44);
     - strict exact;
     - per-stratum tables, with ho4's strata computed after the unlock.
     No claim is made that the lower bound exceeds 95%.
   - **Per-archive gates**, on every candidate archive (D44.6):
     - 0 calls over budget;
     - 0 excerpt or state leaks;
     - `--explain` with 0 unexplained changes;
     - `transcripts verify` passing.
   - **Exploratory comparisons:** per task "any constraint lost"; per task trap repeat; ho4 against ho5; per host.
   - **Serving numbers are informational.** Latency and prompt time are compared within a host only, and no practical tolerance is used.
6. **Reruns, stopping and defects.**
   - **Reruns** only for infrastructure failure (D44.7), each with `--reason`.
   - **Relaunch.** Strata may be relaunched with the identical command between runs (D108). A pair split across host epochs is flagged, never rerun. A sensitivity analysis without split pairs is reported.
   - **Sample size and stopping.** N is fixed, with no extension inside Phase 7. An inconclusive result (|b − c| ≤ 1) goes to Phase 8 with the sealed reserve ho6.
   - **Defects** follow D44.8: stop, fix, and rerun the whole held-out set on the fixed commit. There are no waivers.
7. **Reproducibility.**
   - No seed is sent: OpenCode sends none, and Strata's seed support is unverified.
   - Sampling is 1.0 / 0.95 / 20 (D48.3).
   - Each run records:
     - the commit and versions;
     - the hardware;
     - the host epoch;
     - every upstream call, including refresh and compaction calls.
8. **Pi (D111.3, D113.3)** runs ho4's 5 tasks on Chat, `a4-d77` against its own compaction, after the OpenCode runs. Pi is reported only.
9. **Unlock.** `eval/heldout_unlock.json` names heldout4 and heldout5 with D115. heldout6 stays locked for Phase 8.
10. **The S10 dress rehearsal** on retired ho3 at `a892e4a`, 2026-11-20, from the driver workstation at real 32K. The aim was to exercise the whole pipeline: needles first, then both arms back to back, then the pooled report. The results are development data and say nothing about the held-out comparison.
    - **What ran.**
      - pythia: needle history ho3-h1 on `a4-d77`, then ho3-t1 with `a4-d77` first, then arm 1.
      - Zeus: ho3-t2 with arm 1 first, then `a4-d77`.
    - **Preflights.** Before the rehearsal, `needle.py preflight --driver opencode` was faithful on heldout4 (12/12) and heldout5 (18/18). `gate_inputs.host_epoch` filled every field from `/props` and `/v1/status` on both hosts.
    - **Results.**
      - ho3-t1, both arms: success (4/4 functional tests), constraints 3/3.
      - ho3-t2: arm 1 passed. `a4-d77` failed (2/3 functional tests). Both arms lost C2 (constraints 2/3).
      - Traps: no `code` hit on any of the 4 attempts. ho3-t2 has no trap patterns, so it is a manual task.
      - Needles: ho3-h1 10/10 loose exact; `--explain` 21/21 pairs; 0 leaks.
      - Per-archive gates: both `a4-d77` archives pass (0 over budget, 0 leaks, `--explain` clean, transcripts verify).
      - Host epochs: no split pair.
    - **Turn kills and time.**
      - ho3-t1 `a4-d77` on pythia: 3 of 8 turns killed at 30 minutes (turns 6–8); 204 calls; 8,569 s of latency; max prompt 23,888.
      - ho3-t1 arm 1 on pythia: 1 kill (turn 7); 110 calls; 3,764 s; 19 compaction calls. Its turn 1 also exited 1 after 508 s, which is not a kill. The run went on and the check passed.
      - ho3-t2 on Zeus took 22 minutes for arm 1 and 18 minutes for `a4-d77`.
      - These counts are recorded, not gated. Kills count per arm, as declared in item 1.
    - **What the rehearsal changed (no defect in the proxy).**
      - **Trap scan.** `run.py` does not run `state_eval`'s trap scan, so the Phase 7 report marked every suite run "unscored" and failed the trap gate. The report now runs the scan on each designated suite attempt that has none (`report.trap_scan`).
      - **Missing report sections.** The report did not show the item 5 per-archive gates or the item 6 epoch split. Both are now sections of `report.py --phase7`, and split pairs get a sensitivity table without them.
      - **Run layout.** The rehearsal driver wrote one manifest per arm, which `--pool` cannot read as host streams. The rehearsal was reported through merged per-host manifests. The S11 driver uses the layout in item 3.
      - The three report changes landed test-first (`tests/test_eval_phase7.py`) before F. With them, the pooled report over the rehearsal printed every section.
      - The rehearsal's success, constraint and needle gates read FAIL only because of its size: 2 tasks and 1 of 12 needle histories, against a denominator of all 120 ho3 needles. That is expected.
11. **Amendment before any held-out run: tasks on Zeus only, needles on pythia (user decision, 2026-11-20).** This replaces the host split in items 2 and 3. No held-out run had started.
    - **Why.** The rehearsal's per-call rates show that pythia is the slower host by a wide margin.
      - Uncached prompt processing: about 330–350 tokens/s on pythia, against 1,300–1,900 on Zeus.
      - Generation: 41–45 tokens/s on pythia, against 95–110 on Zeus.
      - Generation dominates a turn, so pythia is about 2.3–2.5× slower.
    - **The turn limit.** The 30-minute limit (item 1) is wall-clock time, so on pythia it kills turns that finish on Zeus. That turns real differences between the arms into shared failures, which costs discordant pairs. It also costs `a4-d77` more, because it makes more calls, including refresh calls. In the rehearsal on pythia, `a4-d77` had 3 turn kills and arm 1 had 1.
    - **Wall-clock time.** Two streams finish when pythia's 13 tasks do, which takes about as long as 30–33 tasks on Zeus. Zeus alone runs all 25 tasks in about the same time or less.
    - **The schedule.** `eval/phase7_schedule.py --seed 115 --hosts zeus`, replacing `eval/phase7_schedule_d115.json` (the two-host version is at `d77720d`).
      - All 25 tasks run on Zeus. The seeded arm order puts `a4-d77` first in 14 of them and arm 1 first in 11.
      - The repeats are the same five tasks, run on Zeus after the primaries.
    - **Needles.** All 30 histories of heldout4 and heldout5 run on `a4-d77` on pythia, which has one needle run directory per set. Needle recall has no turn limit, and its gate does not depend on host speed.
    - **Run layout.** One task run directory, `zeus/tasks`, plus `zeus/repeats`, `pythia/needles-heldout4` and `pythia/needles-heldout5`. The report needs no `--pool`.
    - **Given up.** Per-host task tables, which were exploratory. Zeus also becomes the only task host, so a Zeus outage stalls every task run. Pausing Windows Update on Zeus is therefore required.
    - Every other item stands as written.
12. **Zeus sampled at temperature 0.6; fixed to 1.0 before any held-out run (user decision, 2026-11-20).**
    - **Found.** The pre-S11 checks found the difference in Zeus's `/props`: temperature 0.6, against pythia's 1.0. OpenCode sends no sampling fields (checked in the rehearsal's captured bodies), so the server's default applied.
      - `strata launch` writes the Qwen family's sampling block (0.6 / 0.95 / 20) into `%LOCALAPPDATA%\Strata\launch\iq3_xxs-32k.json` on every start, and an edit to that file is overwritten.
      - pythia's config has no sampling block, so it serves the 1.0 / 0.95 / 20 recorded since Phase 3 (D48.3).
    - **Affected (development data, not rerun).** Every Zeus run since its 0.1.58 launch on 2026-11-19: the D111.7 acceptance counts, the S8 pilot's Zeus tasks (R64) and the rehearsal's ho3-t2 (item 10) all sampled at 0.6. Their results stand as recorded, with this caveat.
    - **The fix.**
      - A separate config, `iq3_xxs-32k-t1.json`: the launch config with `sampling` set to 1.0 / 0.95 / 20 and nothing else changed.
      - Strata is started without `strata launch`, the way pythia is: `python -m serve.server --engine strata --config ...\iq3_xxs-32k-t1.json --host 0.0.0.0 --port 8080 --parallel 1 --no-api-key`, from `E:\Strata-0.2.11\terminal\0.1.58`, detached through `Invoke-CimMethod Win32_Process Create`.
      - This is now the identical relaunch command of item 6 (D108). The old file is kept as `iq3_xxs-32k.json.bak-t06-20261120`.
    - **Checked after the restart:**
      - `/props` shows 1.0 / 0.95 / 20, Strata 0.1.58, `n_ctx` 32,768 and one slot;
      - the chat template hash `12827f24` is the same as pythia's;
      - the engine arguments are unchanged.
    - **Speed at 1.0.** Measured on the same prompt, 3 runs of 1,500 tokens, server-reported: Zeus about 95 tokens/s and pythia about 41. Item 11's rationale holds.

## D116: S11 blind trap review (2026-11-21)

D115.5 requires a blind review of each disputed trap run before it counts. The S11 trap scan left 8 disputed runs: 4 per arm, over ho5-t3, t13, t15, t17 and t18. In every one the scan found a `code` hit while the run's `test_t_*` passed. No run had a failed trap test without a `code` hit.

1. **Reviewer.** The lead had already seen which arm each run came from, so a fresh agent reviewed instead. It got only the packets and was told not to open anything else.
2. **Packets.** One per run, shuffled with seed 11502. Each held:
   - the task's `TRAP` and `TRAP_WARNING`;
   - its `TRAP_PATTERNS`;
   - the `test_t_*` source and outcome;
   - the scan hits, without tool names (the arms recover calls differently);
   - the final task sources, tests excluded.
   - The packets carried no arm, config, attempt or archive detail. The packet-to-run key was kept apart from the reviewer.
3. **The question:** does the final source repeat the trap approach in a way that produces the described failure?
4. **Verdicts:** all 8 are not repeats, each with high confidence.
   - The `code` hits were: a `key=` on the line after `sorted(`; a pattern inside a docstring; a float conversion used only for output; and a correct use of the trapped expression (for example `- timedelta(days=1)`, then stepping back past the weekend).
   - The lead spot-checked P2 and P4 against the source before using the verdicts.
   - The verdicts are recorded in `eval/phase7_trap_reviews_s11.json` (`--trap-reviews`).
5. **Result.**
   - `a4-d77` has 3/20 repeats: ho5-t2, ho5-t4 and ho5-t13. In each, the `code` hit and the failed test agree, so none needed review. The trap gate (0) **fails**.
   - Arm 1 also has 3/20: ho5-t2, ho5-t5 and ho5-t11.
   - The exploratory per-task comparison gives b = 2, c = 2.

## D117: Phase 7 close-out: classifications and the Phase 8 carry-forward (2026-11-22)

1. **The Pi run order.** D115.8 did not fix one. Pi ran ho4's tasks in the schedule's order (ho4-t5, t1, t2, t4, t3), with each task's listed arm order, on pythia, as one stream (`captures/run-phase7-pi.ps1`). Nothing was rerun.
2. **The trap failure is a mechanism weakness, not a D44.8 defect.**
   - The archive, recall and per-archive gates behaved as specified.
   - The notes the model wrote lost the warning in a later rewrite, and no contract requires notes to keep a user-stated failure.
   - The protocol is not rerun. The 3/20 stands, and the gate fails.
3. **The needle gate stands as FAIL, scored as frozen** (loose exact, D115.5). The shortfall follows the needle generators' question phrasing (R65).
   - No re-scoring is adopted.
   - The "gold value in the answer" count is reported as post hoc only.
   - The lead's authoring standard (D113) is responsible: it never required an answer-format instruction or checked answer shape before the seal.
4. **The primary result is inconclusive (D115.6).** b = 3 and c = 2, so the question goes to Phase 8 with the sealed reserve ho6. ho4 and ho5 are spent: they have been opened and analysed, so they cannot be held out again.
5. **Carried into Phase 8:**
   - **Notes keep user-stated failures.** Either they are carried verbatim, or they go in a pinned "tried and failed" section that a rewrite cannot drop. This lands as a red fake-upstream test first.
   - **Needle authoring.** Every question ends with a fixed answer-format instruction. A pre-seal probe checks answer shape on the model; it does not score recall.
   - **Attempts.** S11's repeats flipped success in 4 of 10 arm-runs. Phase 8 sizes for more than one attempt per task, or more tasks, and fixes the rule before any run.

## D118: Test expectations brought in line with the D115 unlock, after the held-out runs (2026-11-22)

- **The problem.** Since F (`d77720d`), 4 tests have failed because they assumed the repository's unlock file listed no set. D115.9 unlocked heldout4 and heldout5. The lead ran the full suite before F, not after it, so the failures were first seen in the Zeus run on 2026-11-22: 2,117 passed, 4 failed.
- **The deviation.** D115.1 allows only `eval/` and `docs/` to change after F. This change touches `tests/` only: `test_phase7_heldout.py`, `test_state_eval.py` and `test_tasks_pi.py`. Every held-out run (R65, R66) had already finished, so none of them is affected.
- **The change.**
  - The repository-file refusals are now tested on heldout6, the set that is still locked.
  - A new test pins the committed unlock file to heldout4 and heldout5 by D115, and checks that heldout6 is still locked.
  - The lock logic keeps its own coverage, through the temporary unlock roots the tests build.
  - No code changed.
- **Where the suite runs.** The user asked that only Zeus be used for now, so the full suite ran on Zeus (Windows) instead of pythia (D76).

## D119: A timing test that flaked on Windows (2026-11-22)

- **The flake.** `test_admission_http.py::test_fifo_one_dispatch_across_sessions` failed in 1 of 5 runs on Zeus. Its last assertion required B to finish before C on the client's clock. Two things break that:
  - `time.monotonic()` ticks about every 15 ms on Windows;
  - B and C both finish almost at once after A, so thread scheduling decides which client sees its end first.
- **The change.** It touches `tests/` only, after the held-out runs, under the same deviation as D118.
  - `Call` now times with `time.perf_counter()`.
  - The assertion now checks what the proxy guarantees: B and C finish after A, whose slot they waited for. FIFO dispatch stays covered by the existing checks of in-flight count and upstream arrival order.

## D120: Phase 8 scope (2026-11-22)

The plan is `docs/plan/phases/phase8.md`. Its §6 lists the open decisions.

1. **User decisions:**
   - **U1, the notes fix:** n3, meaning the prompt plus a deterministic carry of earlier Dead-ends lines.
   - **U3, size:** option D, ho6 plus a new 20-task heldout7, 3 attempts per arm, with a majority-of-3 task outcome and 300 new needles.
   - **U11, Linux:** POSIX-only tests and the Linux clean-install check stay **pending** while pythia is unavailable, so Linux is not claimed until they run.
   - **U12, release claims:**
     - OpenCode gets the quality claim.
     - Pi and OMP get protocol and lifecycle claims only.
     - Hidden tools stay experimental, Claude Code stays backlogged, and Phases 5 and 6 stay skipped.
2. **Run as the plan recommends, unless the user changes them:** U2, U4–U10 and U13. Each is fixed in the decision entry of its slice.
3. **ho4 and ho5 are retired to development data** (D117.4). ho6 and heldout7 are confirmatory only.
4. **Hosts:** Zeus only, until the user lifts it. The Windows Update pause on Zeus ends 2026-12-20 and must be extended before S14.
5. **S0 is met.** The full suite passed on Zeus at `45a92e2` (2,123 passed, 3 skipped). Since then only docs have changed.

## D121: The notes fix after S1 (2026-11-22)

R68 found that a carry of Dead-ends lines alone misses ho5-t4 and ho5-t13, because the model recorded the warning under other sections. ho5-t2's hand trace (R65) shows the same, so the carry alone would likely have prevented none of the 3 repeats. The user chose:

1. **n3 = prompt plus capped carry.**
   - The n3 prompt tells the model to record, under Dead ends, everything the user said was already tried and failed, quoting the user's words, and to carry forward every earlier Dead-ends entry.
   - The deterministic carry (plan §1.1) appends every previous Dead-ends line the reply leaves out.
2. **The cap keeps the earliest recorded lines** (U2, revised). Past S/3, the *newest* carried lines go to `dropped`, so a turn-1 warning is the last thing to go. Lines the model writes itself are never displaced by the carry.
3. **The S3 pilot has two candidate arms:** n3 alone, and n3 with D65's pinned instructions. The pilot runs on dev-t6..t10 and retired ho5-t2, t4 and t13. The arm that meets V-n1 and V-n2 with fewer note tokens and no needle early stops becomes the candidate (D123).
4. **What the S3 pilot checks besides repeats:** whether the model files the warning under Dead ends under the n3 prompt. `notes_audit.py` reports the section of each hit.

## D122: Notes format n3 as built (Phase 8 S2, 2026-11-22)

1. **What it is.** `serve --notes-format n3` (contracts §2 and §17, `tests/test_notes_n3.py`): the n2 prompt, plus the Dead-ends instruction from D121.
   - `builder.carry_dead_ends` appends every Dead-ends line of the notes in force that the reply leaves out.
   - `fit_notes(..., keep=("Dead ends",))` keeps that section whole while it cuts the others.
   - n1 and n2 are byte-for-byte unchanged, and their goldens pass.
2. **The cap.** Carried lines are capped at S/3 tokens, counted by the slot's counter, so 682 at S = 2,048. The longest prefix of carried lines, in their earlier order, that fits is kept, so the earliest recorded failure goes last. Lines the model wrote are never displaced.
3. **Provenance.**
   - `notes_outputs.content` keeps the raw reply. The version text is the merged text.
   - `dropped` indexes the reply's own lines only. Carried lines that the cut or the cap leaves out are not listed, since the previous version holds them.
   - The `notes_version` event gains `carried`, a count. No schema change and no migration were needed.
4. **Fallback.** When Dead ends kept whole does not fit at one line per other section, n2's rule applies to every section, so a very long Dead-ends section can still be cut.
5. **Not yet the default.** `serve` still defaults to n2. D123 decides after the S3 pilot. `policy_version` names it `+notes{S}n3`.
6. **Citation.** The builder docstring and `docs/papers.md` add the context-engineering cookbook's structured note-taking, with the carry as the adaptation.
7. **Tests.** The full suite passed locally (Windows) at this commit: 2,142 passed, 3 skipped. It is run again on Zeus at the S3 run commit (the run-readiness gate, item 1).

## D123: n3 fixes from the S2 reviews (2026-11-22)

Two reviews of `eee9146` (protocol review and cache audit; reviewers report, never edit). The cache audit found no unexplained prefix change, and n1 and n2 are byte-identical apart from the new event counts. The protocol review found the following, all fixed test-first in `tests/test_notes_n3.py`:

1. **High: past v2, the cap dropped the oldest failure first.**
   - **Why:** the carry appends old lines after the model's new ones, so from the second carry on, text order no longer follows age. A cap that kept the first lines in text order could keep a newer line and drop the turn-1 warning.
   - **Fix:** `carry_dead_ends` now takes the branch's committed versions (`ledger.notes_history`) and orders carried lines by the version that first recorded them. It keeps the oldest.
   - **Test:** a three-version chain where the cap fits one line.
2. **Medium: carried lines could make the cut drop the model's own Dead-ends lines.** The carry now keeps only as many lines as still let the cut keep Dead ends whole (`builder.fits_keeping`). Other sections may keep fewer first lines; the contract now says so.
3. **Low:**
   - **A lost carry was invisible.** The `notes_version` event gains `carry_left_out`, a count.
   - **Placeholders.** Lines like "None new" or "N/A" are not carried.
   - **Bullets.** A leading bullet and a trailing period no longer stop a match.
   - **Line endings.** A CRLF reply keeps CRLF on the added lines.
   - **CLI help.** It names n3.
4. **From the cache audit:** "present" now means present in the reply's own Dead ends section. A warning the model moved to a section the cut trims is carried back. An n3 session now has a permanent `--explain` test (0 unexplained, with `state_refresh` and `state_commit` present), plus a committed, failed, committed chain through the proxy.
5. **Record corrections.**
   - D121.2 said lines past the cap "go to `dropped`". As built (D122.3, contracts §17), `dropped` lists the reply's own lines only.
   - The decision numbers the Phase 8 plan had reserved from D123 move up by one: the S3 candidate decision is now D124.

## D124: S2h survival test, and the Strata startup task fix (2026-11-22)

1. **First attempt failed (plan `phase8-s2h-4e12cc1/survival`).** Zeus was force-rebooted at 18:15:22 during step 1, turn 2.
   - The runner's own boot task worked as specified. It started at boot, waited 3,600 s for `/props`, then wrote STOPPED ("server not up"), with no rerun and no lost record.
   - Strata never came back. The "Palimnesis Strata" task ran at 18:16:07 and exited with 1, and its log got nothing. Started by hand, it failed the same way, so boot timing was not the cause.
   - **Cause:** `cmd /c` strips the first and last quote of a command line holding more than two, which broke the program path and the `>>` redirect. **Fix:** `eval/zeus_strata_task.ps1` wraps the command in an outer pair of quotes (5e4eca2).
2. **Gate gap.** `run_ready.py`'s `strata_task` check passed on "registered", and the task had never been started once. It now requires the task's state to be Running, so the server that is up is the one the boot task starts. A registered task that is not running fails (`tests/test_run_ready.py`). Plan gate item 3 says so.
3. **Second attempt passed (plan `phase8-s2h-5e4eca2/survival`, SHA 97ef9e5766d8).**
   - Readiness (`--short`) passed at 5e4eca2, including the suite on Zeus (2,182 passed, 3 skipped) and `strata_task: Running`.
   - Zeus was force-rebooted at 19:37:19 during step 1, turn 2, after turn 1 had ended with exit 0 and all calls 200. Boot was at 19:37:57.
   - ssh was back at +65 s and `/props` at +200 s, with `n_ctx` 32,768, 1.0 / 0.95 / 20, one slot, 0.1.58. The load was about 3 minutes, not the 16 seen before. That figure is recorded as seen; it is not relied on, since the runner waits up to an hour.
   - The runner reran step 1 with `--reason host-restart` at 19:40:54. Attempt 2 finished `done` after 8 turns, all exit 0 and all calls 200. Step 2 finished. Status: done 2, reruns 1, nothing stopped.
   - Attempt 1 stays `running` in `attempts.json` because the power cut kept it from writing its finish. `attempts.designate` picks attempt 2 and lists attempt 1 as superseded with reason `host-restart`, so the record is complete.
   - The four tracebacks in `runner.log` all precede the rerun header. They are the proxy losing its upstream as the host went down.
4. **Evidence.** `captures/phase8-s2h-5e4eca2/survival` on Zeus is the survival evidence for gate item 7. S2h's remaining gate evidence (rehearsal, report and so on) comes with S3.
5. **Numbering.** The decision numbers the Phase 8 plan had reserved from D124 move up by one again: the S3 candidate decision is now D125.

## D125: S3 pilot, choosing the notes candidate (protocol fixed before the run, 2026-11-22)

The plan's S3 row and D121.3 named the arms and tasks but did not define V-n1 or V-n2. They are defined here, before any pilot run. The outcome is appended to this entry after the run, and it names the candidate (`a8-…`) or says there is none.

1. **ho5 is retired in code too.** D117.4 retired ho5 to development data, but `needle.RETIRED_SETS` still listed heldout2 and heldout3 only, so `run.py` would have refused a new configuration on ho5. heldout5 is added. heldout4 is retired as well but is never opened, so it stays out of the list. heldout6 stays sealed. Tested in `tests/test_phase8_pilot.py`. `eval/heldout.py` still treats heldout5 as an unseen set: a run needs its unlock (`eval/heldout_unlock.json`, heldout5 → D115, committed) and a clean tree.
2. **Arms** (`eval/needle.py`):
   - `a4-d77` is the control, with notes n2.
   - `a4-n3` is `a4-d77` with `notes_format="n3"`.
   - `a4-n3p` adds D65's pinned instructions (`pin_tokens=4096`).
   - Pilot labels stay `a4-…`. The `a8` name is given only to the winner, when the default flips.
3. **Schedule** (`eval/pilot_s3.py`, seeded):
   - Round 1 runs dev-t6..t10 and ho5-t2, t4 and t13 once per arm.
   - Round 2 runs ho5-t2, t4 and t13 once more per arm.
   - That is 33 task attempts. Each round has its own run directory, so every attempt is designated.
   - Within a round the task order is seeded, and each task's three arms run back to back in seeded order.
   - The control is rerun in the same pilot rather than borrowed from S11, so all three arms share a commit, a host and a period.
   - No needle runs: D121.3's "no needle early stops" is not part of S3. n3's needle behavior is measured by the S13 rehearsal and S14.
4. **Measures**, per attempt:
   - the trap verdict (`report.trap_verdict`; disputed attempts are settled only by a blind review, as in D116);
   - task success;
   - early constraints held;
   - the state of the notes in force at the trap turn (`notes_audit.audit_run`);
   - the mean length in characters of the committed notes versions.
5. **Selection:**
   - **V-n1, retention:** the warning is `kept` at the trap turn in all four ho5-t4 and t13 attempts. ho5-t2's detector is unreliable (R68), so its attempts are read by hand and reported, not counted.
   - **V-n2, no repeat:** 0 repeats over the arm's 11 attempts, with none disputed or unscored. S14's trap gate allows 0 repeats over three attempts per task, so a pilot repeat predicts a gate failure.
   - **No regression:** successes and constraints held are each at least the control's, in this pilot, minus 1.
   - **Hand reads before V-n1 counts.** The detector matches the warning's backticked code exactly, so a paraphrase reads as lost. Every ho5-t4 and t13 attempt whose state is not `kept` is read by hand and recorded in `--retention-reviews`.
   - `a4-n3` wins when it is eligible. `a4-n3p` wins only when it alone is eligible. Both arms run the same notes mechanism, so notes length cannot separate them, and the pins cost up to about 4K tokens of every view.
   - With no eligible arm, the default does not flip and the user decides.
6. **Estimated duration**, from measured `a4-d77` times on Zeus (R64, S11):
   - dev-t6..t10: 7.1 + 17.6 + 7.1 + 43.9 + 6.1 = 81.8 min;
   - ho5-t2, t4 and t13: about 21 (the mean of 14.5 and 27.7) + 13.6 + 7.1 = 41.7 min per round;
   - about 165 min per arm, 8.3 h for three arms;
   - readiness uses 12 h, allowing for n3's longer refreshes and server waits.
7. **Gate.** The full readiness gate (items 1–9) runs at the pilot commit. The survival evidence (item 7) is D124's.
   - **Rehearsal (item 5):** dev-t6 and ho5-t13 on each arm through the headless runner, reported with `pilot_s3.py report --tasks dev-t6,ho5-t13 --rounds r1` (D125.9). ho5-t13 exercises the heldout5 unlock and clean-tree checks, and the trap-turn retention column.
   - **Separate roots.** The rehearsal and the pilot use separate roots (`.../rehearsal`, `.../pilot`). In a shared round directory, a second attempt of the same task and arm needs `--reason`, so the step would exit 1 and the run would stop.
   - **Where the report runs.** It runs on Zeus, in the clone that ran the pilot, because `attempts.json` stores absolute records paths.
8. **Independent review (item 9), at `6b637a2`.** Verdict: "ready after fixes". It found four should-fix issues, all fixed before any pilot attempt:
   - the rehearsal never exercised the ho5 path;
   - the notes-length tie-break could not separate the arms;
   - the retention detector is exact-match;
   - a shared root would stop the run.
   
   Its notes are recorded here:
   - R65 had 8 disputed traps in 50 runs, so a blind review (as in D116) of disputed pilot attempts is a planned step after the run, before V-n2 is read.
   - Exit 3 (`slot_busy`, `no_session`, `second_session`, `strata_check`) and any exception in `run.py` stop the run. R65 had none in 25 `a4-d77` tasks. Stopping stays the rule, since most such causes are Strata failing.
   - Turns are capped at 30 min, so nothing hangs without bound.
   - `notes_audit.read_versions` has no branch filter, and `need_time` takes the version in force when the trap-turn request arrived. Both apply to every arm alike.
9. **Rehearsal outcome, at `64fc02e`.** All 6 steps finished headless (`captures/phase8-s3-64fc02e/rehearsal-run`, plan SHA `10ec1a17734c`), with no reruns and no STOPPED.
   - **The report needed a round filter.** The rehearsal spec was the pilot spec cut to dev-t6 and ho5-t13 in round 1. The report's `--tasks` kept both rounds, so it listed the three r2 ho5-t13 attempts as missing, and the gate's report reader would reject it. `pilot_s3.py` now takes `--rounds` in `spec` and `report`. `spec --tasks dev-t6,ho5-t13 --rounds r1` reproduces the rehearsal spec, config `s3-pilot-seed8125-dev-t6+ho5-t13-r1`. The pilot plan sits at the commit with this change. That commit touches only `pilot_s3.py`'s filters, its tests and this entry. `run.py`, the proxy and the headless runner are unchanged since the rehearsal, so the rehearsal stands as item 5's evidence.
   - **Hand check.** The three ho5-t13 attempts, one per arm, were read from their raw records: `result.json`, the trap scan's hits, and the archive's committed notes versions with the trap-turn request's arrival time, by direct SQL. All three match the report's row for verdict, success, constraints and the state at need:
     - `a4-d77`: disputed (a code hit in `racking.py`, trap test passed), 3/3, omitted (warning in v1–v7, gone from v8, v10 in force);
     - `a4-n3`: clean, 1/3, kept (v9). Its C3 error is the model's code rejecting the padded column `j010`, a real constraint loss, not a check fault;
     - `a4-n3p`: disputed, 3/3, kept (v8).
     
     Each record's settings equal `needle.CONFIGS` for its arm (`a4-n3p` has `pin_tokens` 4096). dev-t6's state is always `absent` because its warning names no backticked code, so the detector has no fragment. dev tasks do not count toward V-n1.
   - **Estimate revised.** The measured attempts were dev-t6 545–755 s (mean 10.6 min) and ho5-t13 845–973 s (mean 15.3 min). Putting these in place of item 6's 7.1 min each gives about 185 min per arm, 9.3 h in all. If every task runs 1.5 times its R64 time, as dev-t6 did, that becomes 12.4 h. Readiness uses 16 h, and the update pause still has more than three weeks of margin.

## D126: S3 outcome: V-n2 amended after the run, `a8` = `a4-n3`, `serve` ships n3 (2026-11-23)

The S3 pilot ran headless on Zeus at `8b4da2f`: 33 of 33 steps, 6.3 h, no reruns and no stops (`captures/phase8-s3-64fc02e/pilot-run`). Under D125's rules as fixed, neither n3 arm qualified: each had one trap repeat, and V-n2 allowed none. D125.5 leaves the choice to the user. The user asked for an investigation first, then chose the amendment below (2026-11-23). Results are in R69.

1. **What the investigation found** (`captures/phase8-s3-64fc02e/investigation/`):
   - The three arms' only shared repeat is round-2 ho5-t4. Its trap turn asks for `household_share(total, hours, household)` "one name at a time … the whole-crate count closest to it", which is `round()` in other words.
   - Both n3 repeats had the warning in the prompt at the trap turn, quoted in the user's words under Dead ends (and pinned, in `a4-n3p`). The models chose the instruction knowingly:
     - `a4-n3` had earlier offered "a largest-remainder split (that avoids the `round()` shortfall you hit)";
     - `a4-n3p`'s docstring states the conflict ("needs a single allocation across every household at once (largest remainder), which a one-name-at-a-time lookup cannot express") and then follows the instruction.
   - The control's round-2 ho5-t4 repeat also had the warning, paraphrased. Its other two repeats (r1 ho5-t4, r2 ho5-t2) had lost it.
   - Over all 33 attempts, the trap turn's first request held the warning nearly verbatim in 21 of 22 n3 attempts. For the control, a word-window match found it in 2 of 11, and the hand reads add paraphrases.
2. **The amendment (post hoc).** V-n2 now counts only repeats whose notes in force at the trap turn did not hold the warning: detected `kept`, or a hand read in `--retention-reviews`, which wins where recorded. A repeat made with the warning held is reported, not gated. D125's V-n2 is printed beside it as `V-n2 (D125)`.
   - **Why.** Notes can fix forgetting. They cannot stop a model from following a later instruction that contradicts what it remembers. A rule that counts both cannot tell a notes format that works from one that does not.
   - **Caveats, stated as such.** The rule changed after the data was seen. The split rests on 2 ho5-t4 attempts per arm. S14's trap gate is unchanged and counts every repeat, so a repeat of this kind on ho6 still fails the gate. The sealed ho6 run is the confirmation that counts.
   - `pilot_s3.py`: `repeats_lost` and `repeats_held`; a hand read overrides the detector. Tests in `tests/test_phase8_pilot.py`.
3. **Blind review of the 10 disputed attempts** (as in D116). The packets were shuffled with seed 12501 and carried no arm, config or tool names. A fresh agent saw only the packets; the key is `captures/phase8-s3-64fc02e/blind/key.json`.
   - All 10 are not repeats, each with high confidence. The hits were docstrings, keyed sorts the scanner's lookahead misread, tool-call-only matches, and a largest-remainder split.
   - The lead spot-checked P4 and P9 against the source.
   - The verdicts are in `eval/phase8_trap_reviews_s3.json`.
4. **Hand reads** (`eval/phase8_retention_reviews_s3.json`):
   - the control's two non-kept ho5 states: r1 ho5-t4 lost; r1 ho5-t13 kept as a paraphrased rule;
   - the six ho5-t2 attempts: all four n3 attempts verbatim; the control's r1 paraphrased, its r2 lost (a description of existing code only).
5. **Outcome.** `a4-n3` and `a4-n3p` both pass V-n1 (4/4), the amended V-n2 (0 repeats with the warning lost, nothing disputed or unscored) and no-regression. By D125.5, `a4-n3` wins.
   - **It is named `a8`** (`needle.CONFIGS["a8"]`, equal to `a4-n3`): `a4-d77` with notes format n3.
6. **The default flips.** `serve --notes-format` now defaults to n3, so `serve` with no flags runs `a8`. `--notes-format n2` runs `a4-d77`.
   - As in D78, `Settings`' defaults do not move.
   - Tests: `tests/test_cli.py` (`SHIPPED_D126`), `tests/test_eval_d77.py`, `tests/test_phase8_pilot.py`.
   - Contract text: `docs/contracts.md` n2 and n3. Also updated: `docs/capabilities.md`, `docs/glossary.md` and the README.
7. **Open defect: n3 repeats reworded Dead-ends lines.** The carry keeps an earlier line that the reply rewords (a different lead-in, such as "User, in their own words" against "User (their own words)"), so the same warning piles up. One pilot attempt held it 4–5 times, and the model remarked "recorded four times, identical wording". n3 notes averaged 5,531 characters against n2's 4,736.
   - Not fixed here: a fix changes the mechanism just chosen.
   - Before F8, a fix needs its own decision and fake-upstream tests, and either the S13 rehearsal's evidence or a short pilot. It should probably match on the quoted span or its backticked code.
8. **Also open, not tested:** whether n3's header line "the user's messages win" pushes the model toward a later conflicting instruction.
