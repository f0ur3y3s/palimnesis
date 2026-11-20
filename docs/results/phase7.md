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
