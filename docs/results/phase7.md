# Phase 7 results

## R64: S8 development pilot (2026-11-20)

- **Setup (D111, D112):**
  - OpenCode through `eval/tasks/run.py`, one attempt per run. Three arms: `a4-d77` (notes), `a4-tr` (no notes) and arm 1 (native compaction).
  - Tasks dev-t6..t10 after the T1a/T5a revision (`324150b`). All three arms of a task ran back to back on one host at a real 32K on Strata 0.1.58: dev-t7 and dev-t9 on pythia, dev-t6, dev-t8 and dev-t10 on Zeus.
  - Started at `487add0`. Later arms ran at `6807018`, with the tasks, `run.py`, `src/` and `state_eval` unchanged between the two. Records are in `captures/phase7-pilot-487add0/<arm>/<task>/` (gitignored).
- **V1 (T1 on at least 4 of 5 tasks): pass, 5/5.** The second temptation probe after the revision (D112.8); the first probe gave 1/5.
- **V2 (T7 in every `a4-d77` and `a4-tr` run): pass, 10/10.** `trap_eligible_at_need` held in every run, so the warning was out of view at the trap turn. It also held in all 5 arm-1 runs.
- **V3 (at least one `code` repeat across `a4-tr` and arm 1): pass, 2 genuine repeats, both in `a4-tr`:**
  - dev-t6: `(total + 50) // 100` written into `markbook/report.py`; `test_t_never_rounded_up` fails.
  - dev-t8: the undecomposed quoting written into `crate/links.py`, also in the final file; `test_t_decomposed_names` fails.
  - Each was confirmed three ways: the pattern, the failing hidden trap test, and reading the code.

| Task | `a4-d77` | `a4-tr` | arm 1 |
|---|---|---|---|
| dev-t6 | pass, no repeat | pass, **repeat** | pass, no repeat (7 compactions) |
| dev-t7 | pass, no repeat | pass, no repeat | pass, no repeat (15) |
| dev-t8 | pass, no repeat | pass, **repeat** | pass, no repeat (17) |
| dev-t9 | pass, no repeat | pass, no repeat | **fail 3/4**, no repeat (14) |
| dev-t10 | pass, no repeat | pass, false `code` hit | pass, no repeat (7) |

- Constraints were 3/3 in all 15 runs. Trap repeats: 0 of 5 with notes, 2 of 5 without, 0 of 5 with native compaction.
- **Hits read by hand:**
  - **dev-t10 `a4-tr` is a false positive.** The `code` hit in `labelprint/layout.py` is correct code (`len(s.encode("utf-8"))`), and `test_t_*` passes. The dev-t10 patterns must be tightened.
  - **Every `doubtful` hit was correct as `doubtful`.**
    - Arm 1's and `a4-d77`'s write hits with no path are scratch scripts under OpenCode's temp folder (`oc/tmp/opencode/`), outside the workspace.
    - The remaining hits are shell or `execute` checks.
  - **Arm 1 dev-t8 has no repeat.** Its edit of `crate/links.py` normalizes to NFC before quoting, so the pattern correctly misses it.
- **Arm 1 dev-t9's failure is not the trap.** `test_f_parse` errors because a score with a space before it (`' 12'`) is rejected instead of stripped. The trap test passes. No turn states the whitespace rule, so the miss is not attributed to compaction dropping an instruction.
- **Carried into the standard (before held-out runs):**
  - When a `code` hit and the task's `test_t_*` result disagree, a person reviews the run before it counts.
  - Tighten dev-t10's patterns.
- **Not a result:** this is development data with one attempt per cell. It shows that the traps can separate arms, which 4A's could not (0 repeats in 30 runs, R61). It says nothing about the size of the effect.

## R65: S11 held-out comparison, OpenCode (2026-11-20 to 2026-11-22)

- **Setup (D115):**
  - Freeze commit F is `d77720d`. The runs used `617ff65`; between the two, only `docs/` and the Zeus sampling fix changed (D115.11, D115.12).
  - The 25 task pairs (ho4-t1..t5, ho5-t1..t20) ran on Zeus. The 30 needle histories (heldout4 h1–h12, heldout5 h1–h18) ran on pythia, both at a real 32K on Strata 0.1.58 with sampling 1.0 / 0.95 / 20.
  - Records are in `captures/phase7-s11-617ff65/` (gitignored).
  - No attempt was missing, aborted or rerun, and no pair was split across host epochs.
- **Primary (D115.4): inconclusive.**
  - `a4-d77` succeeded on 19/25 tasks and arm 1 on 18/25, with b = 3 and c = 2.
  - The paired difference is +0.040, with a Newcombe 95% interval of −0.151 to +0.228. The exact McNemar p = 1.
  - The gate (successes ≥ arm 1's) passes. But |b − c| = 1 is inconclusive under D115.6, so the question goes to Phase 8 with ho6. No equivalence or noninferiority is claimed.
- **Constraints: pass.**
  - `a4-d77` held 69/75 (92.0%), with a bootstrap 95% interval of 84.0–98.7%. Arm 1 held 63/75 (84.0%).
  - `a4-d77` is ahead on all three constraint types. Per task, it kept all constraints in 7 tasks where arm 1 didn't, against 2 the other way (exploratory p = 0.18).
- **Per-archive gates: pass, 25/25.** That means 0 over budget, 0 leaks, `--explain` clean and transcripts verify.
- **Traps (ho5): fail.**
  - `a4-d77` has 3/20 repeats: ho5-t2, ho5-t4 and ho5-t13. Arm 1 also has 3/20: ho5-t2, ho5-t5 and ho5-t11.
  - The blind review (D116) cleared all 8 disputed runs.
  - In all 3 `a4-d77` repeats, the notes recorded the turn-1 warning at first, and a later notes rewrite dropped it before the trap turn:
    - ho5-t13: present in v1–v4, gone from v5;
    - ho5-t4: present in v1, gone from v2;
    - ho5-t2: present in v1–v6, gone around v7.
  - In every ho5 run of both arms, the warning's full text had already left the view by the trap turn.
- **Needles: fail.**
  - Loose exact was 225/300 (75.0%): Wilson 69.8–79.6%, history-clustered bootstrap 65.0–84.7%, strict exact 162.
  - heldout4 scored 114/120 (95.0%) and heldout5 111/180 (61.7%). Every miss returned status 200 with no errors.
  - In 60 of the 69 heldout5 misses the answer contained the gold value inside prose.
  - heldout5 splits by needle generator:
    - a: 22/50;
    - b: 47/50 (asks "Code only", "bare identifier");
    - c: 30/40;
    - d: 12/40 (conversational questions).
  - The gate mostly measured how questions were phrased, not recall. "Gold value in the answer" is 285/300; that count is post hoc and exploratory.
- **Time and kills (informational, Zeus only):**

| | `a4-d77` | arm 1 |
|---|---|---|
| Upstream calls | 2,365 | 4,431 |
| Total latency | 24,388 s | 49,803 s |
| Turns killed at 30 min (of 200) | 0 | 10 |
| Turns exiting nonzero | 0 | 22 |
| Compaction calls | 0 | 650 |
| Lookups | 7 | — |

- **Repeats (descriptive, 5 tasks × 2 arms):**
  - Success flipped in 4 of 10 arm-runs: ho5-t6, ho4-t2 and ho5-t2 for arm 1, and ho4-t4 for `a4-d77`.
  - Trap-test outcomes flipped in 3 of 6.
  - A single attempt per task at sampling temperature 1.0 is noisy. The primary difference of one task is well within that noise.

## R66: Pi on ho4 (D115.8, reported only, 2026-11-22)

- **Setup:** Pi 1.5.0 on Chat, at `7d9d534`, on pythia at 32K. Tasks and arm orders followed the schedule's ho4 entries (D117.1). Records are in `captures/phase7-pi-7d9d534/` (gitignored).
- **Results:**
  - Success was 4/5 for each arm. `a4-d77` missed ho4-t2 (2/3); arm 1 missed ho4-t4 (3/4).
  - Constraints were 15/15 against 13/15.
  - Per-archive gates: 5/5 pass.
- **Pi's native compaction at 32K:**
  - Arm 1 compacted 115 times over 5 tasks.
  - In ho4-t5, ho4-t4 and ho4-t1, compaction repeatedly failed with "Summarization failed: generation hit the token cap and the summary is incomplete", including context-overflow recoveries.
  - `a4-d77` never triggered Pi's compaction.
  - Total latency was 9,222 s against 22,900 s. Turns killed: 0 against 7 (of 40).
- **What it shows:** the proxy works on held-out tasks through a second harness with every gate clean. At 5 pairs it says nothing about effect size.

## R67: Phase 7 gate summary (2026-11-22)

| Gate (D115) | Result |
|---|---|
| Primary: `a4-d77` successes ≥ arm 1 | PASS, 19 vs 18; inconclusive (b − c = 1, D115.6) → Phase 8 |
| Constraints ≥ 90% | PASS, 92.0% |
| Traps: 0 ho5 repeats | **FAIL**, 3/20 (notes rewrites dropped the warning) |
| Needles: loose exact ≥ 95% | **FAIL**, 75.0% (question phrasing; heldout4 95.0%) |
| Per-archive gates | PASS, 25/25 (and Pi 5/5) |

- **Phase 7 does not establish that `a4-d77` beats native compaction on task success.**
- **What it does show:**
  - `a4-d77` keeps more early constraints;
  - it uses about half the calls and latency, with no turn kills;
  - its proxy invariants hold on held-out work through two harnesses.
- **Its trap weakness has a known cause.**
- **Carried into Phase 8 (D117):**
  - notes must keep user-stated failures;
  - every needle question needs a fixed answer-format instruction, plus a pre-seal check of answer shape;
  - more than one attempt per task, or more tasks;
  - ho6 is the only remaining sealed set.

## R68: Phase 8 S1: where the warning left the notes (2026-11-22)

- **What was audited:** `eval/notes_audit.py` over the 20 retired ho5 `a4-d77` archives from S11, at `617ff65`.
  - The warning is detected by the code it puts in backticks. ho5-t3, t5 and t19 have none, so they can't be judged.
  - ho5-t2 (`.date()`) and t18 (`sorted()`) use generic fragments, so their results are unreliable. R65's hand trace stands for t2.
  - That leaves 15 tasks with a usable reading.
- **Loss mechanism: the model, not the cut.** In the 7 tasks where the notes in force at the trap turn had lost the warning, every loss was an omission by the model's rewrite (`omitted`), not a `fit_notes` cut. The tasks are ho5-t4, t6, t10, t13, t14, t16 and t20.
  - Only ho5-t6 ever lost it to a cut (at v8), and by the trap turn it was an omission there too.
  - 3 of the 7 omissions became trap repeats (t4, t13 and, from R65, t2).
- **Counterfactual: carry Dead ends only (plan §1.1).**
  - It keeps the warning in 5 of the 7: t6, t10, t14, t16 and t20.
  - It misses **ho5-t4 and ho5-t13**, two of the three repeats. There the model recorded the warning under Requirements, Decisions or Objective, never under Dead ends.
  - ho5-t2's hand trace also puts it under Current step and Decisions.
- **Counterfactual: carry Dead ends, Requirements and Decisions.** It keeps the warning in all 7 but adds 7,900–34,500 characters, far beyond the 2,048-token notes slot.
- **Size.** The Dead-ends carry alone adds up to 8,143 characters (about 2,000 tokens, an estimate), and the largest replies are already 4,700–7,600 characters.
  - A cap is needed.
  - A cap that evicts the oldest lines first would evict a turn-1 warning first.
- **What it means for U1 (decided in D121):**
  - The planned Dead-ends carry is necessary but not sufficient.
  - The prompt must also make the model put user-stated failures under Dead ends.
  - The cap must keep the earliest recorded lines.
  - Pinned instructions (D65) remain the alternative arm for the S3 pilot.

## R69: Phase 8 S3 pilot: choosing the notes candidate (2026-11-23)

- **What ran:** D125's protocol, headless on Zeus at `8b4da2f`.
  - 33 attempts: dev-t6..t10 and the retired ho5-t2, t4 and t13 in round 1; the three ho5 tasks again in round 2.
  - Each attempt was run on three arms: `a4-d77` (control, notes n2), `a4-n3`, and `a4-n3p` (n3 plus pinned instructions).
  - It took 6.3 h: 33 of 33 steps, no reruns, no stops (`captures/phase8-s3-64fc02e/pilot-run`).
- **Report** (`pilot_s3.py report`, the D126 rule, with `eval/phase8_trap_reviews_s3.json` and `eval/phase8_retention_reviews_s3.json`):

  | arm | trap repeats | warning lost | warning held | success | constraints | kept at need (ho5-t4, t13) | notes chars |
  |---|---|---|---|---|---|---|---|
  | `a4-d77` | 3/11 | r1 ho5-t4, r2 ho5-t2 | r2 ho5-t4 | 11/11 | 30/33 | 3/4 | 4,736 |
  | `a4-n3` | 1/11 | none | r2 ho5-t4 | 10/11 | 31/33 | 4/4 | 5,531 |
  | `a4-n3p` | 1/11 | none | r2 ho5-t4 | 10/11 | 33/33 | 4/4 | 5,306 |

  - The 10 disputed attempts (3 control, 3 `a4-n3`, 4 `a4-n3p`) were all judged not repeats in a blind review (D126.3).
  - ho5-t2 was read by hand. The n3 arms quoted the warning verbatim in all four attempts; the control paraphrased it once and lost it once (D126.4).
- **Retention.** n3 kept the warning at every trap turn read. At the trap turn's first request, the warning sat in the notes block almost word for word in 21 of 22 n3 attempts. The control lost it, paraphrased it or kept it as a rule without the failure story.
- **The shared repeat is not forgetting.** Round-2 ho5-t4's trap turn asks for each household's "whole-crate count closest to it", one name at a time. All three arms wrote `round()`, two of them with the warning quoted in their notes. One wrote the conflict into its docstring and followed the instruction anyway. Notes cannot prevent that. S14's gate still counts it.
- **Selection.** Under D125 as fixed, no arm qualified (V-n2 allowed 0 repeats). Under D126's amendment (post hoc; see its caveats), both n3 arms pass V-n1, V-n2 and no-regression, and `a4-n3` wins by D125.5. It is named **`a8`**, and `serve` defaults to n3.
- **Costs and open points:**
  - n3 notes are 12–17% longer, partly because the carry repeats reworded Dead-ends lines (D126.7, open).
  - The two n3 task failures were r2 ho5-t2 (`a4-n3`) and dev-t9 (`a4-n3p`), one each, within the no-regression margin.
  - 2 ho5-t4 attempts per arm is a small sample. The confirmation is the sealed ho6 run (S14).

## R71: Phase 8 S7 crash and kill matrix (2026-11-23)

- **The matrix** (`tests/test_crash_matrix.py`, D131), in the suite:
  - a process exit at each new point (before and after the notes commit, after the view record, after the terminal commit), with a second session's request waiting for the slot;
  - an external kill (TerminateProcess) at 10 boundaries for each client protocol, Chat and Messages.
  
  After every restart the archive passes `integrity.check`, the transcripts verify, and the keyed resend gets the answer. All 24 pass.
- **Kill trials** (`eval/kill_trials.py --n 50 --seed 1`, at `6f22728` from a pinned worktree, Windows, fake upstream, so no model). The kill came at a uniform 0–2 s into a one-second stream; the actual range was 0.004–1.985 s.

  | Archive state at the kill | Trials | Outcome of the keyed resend after restart |
  |---|---|---|
  | partial output | 27 | `409 ambiguous_retry` (D130) |
  | turn complete | 18 | the answer, replayed from the archive |
  | accepted, no output | 4 | the answer, from a new attempt |
  | nothing accepted | 1 | the answer |
  
  **Passed 50/50.** Every trial left a sound archive (integrity, foreign keys, one terminal event per attempt, FTS equal to a rebuild) and transcripts that verify.
- **Found on the way and fixed** (D131): an attempt abandoned at restart left its partial output unindexed (the first 4-trial smoke run failed 3/4); a transcript publication cut short was never redone; a fork indexed hidden results. An earlier, interrupted run at `1ba5972` is not counted: from trial 30 on, it was running uncommitted code.
- **Not covered:** power loss (U9), Linux (U11 pending), and kills inside SQLite's own commit, which the boundaries bracket but do not split.

## R70: Phase 8 S4 needle instrument on retired heldout5 (2026-11-23)

- **What ran:** `eval/s4_validation.py`, headless on Zeus at `3e3f810` behind the full readiness gate (`captures/phase8-s4-3e3f810/validation-run`), 8 of 8 steps, no reruns, about 2.7 h.
  - 18 histories, 180 questions, 3 samples per question, each sent straight to Strata with its evidence in view and scored with the frozen loose scorer.
  - A question passes on 3 of 3.
  - "Original" is the question as written; "format" is its stem plus the fixed sentence for its kind (D127).
- **Questions passing (3/3):**

  | generator | original | format |
  |---|---|---|
  | a | 39/50 | 46/50 |
  | b | 48/50 | 49/50 |
  | c | 26/40 | 37/40 |
  | d | 32/40 | 40/40 |
  | **all** | **145/180 (80.6%)** | **172/180 (95.6%)** |

- **The expectation holds.** The original phrasing flags a, c and d, and passes b. b's fixed short endings were already near the rule, matching its 47/50 in R65. Under the format rule every generator rises.
- **Where the originals failed:**
  - a's `irrelevant_matches` (0/5; "Cabinet code.");
  - c's `mid_task` (0/4) and `superseded` (3/8);
  - d's `irrelevant_matches` (0/4).
- **What the format rule fixed:** a and d's `irrelevant_matches` (5/5, 4/4), c's `mid_task` (4/4), a's `multi_fact` (5/5), and c's `vague` (8/8).
- **Residual misses under the format rule:** 8, concentrated in two places.
  - a's `oversized_read` (2/5): the kept content ending "Give the marker without the label." conflicts with "exactly as recorded".
  - c's `superseded` (5/8): branch strings typed as identifiers.
  
  Authoring under the rule catches these: a question that fails the probe has its stem revised and needs two consecutive 3/3 passes (AUTHORING.md §4.7).
- **What it means for heldout7 (S12):** every question is written to the rule and passes the probe before sealing. The needle gate then measures recall, not phrasing.
