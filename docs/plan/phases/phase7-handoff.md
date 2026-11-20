# Phase 7 handoff (state on 2026-11-19, evening)

For whoever continues Phase 7. Read `CLAUDE.md`, then `docs/plan/phases/phase7.md` (the plan) and `docs/decisions/phase7.md` (D111: the user's scope, host and size decisions). This file says where the work stands. Delete it once its open items are closed.

## Done

| Item | Where |
|---|---|
| Phase 4A closed, tag `phase-4a` | `a6301d0`; R61–R63 in `docs/results/phase4a.md`; D108–D110 |
| Test cleanup: 16 redundant tests dropped, 3 merged | `ba3b992`; suite 2,035 passed, 3 skipped |
| Phase 7 plan and D111 | `864c3c6` |
| Zeus moved to Strata 0.1.58, accepted by its counts | `2775624` (D111.7) |
| S0: `capabilities.md` names hidden tools as experimental and the harness scope of quality claims | `b2bff9a` |

## In flight when this was written

Four tooling agents were building S1–S7 in separate git worktrees. Run `git worktree list` and `git branch` to find their branches; each was told to commit on its branch and not push.
- **S1 + S4:** an unseen-set registry and the unlock file (`eval/heldout_unlock.json` naming D115); a SHA-256 seal manifest; trap hits read from captured bodies by protocol (Chat `tool_calls`, Messages `tool_use`) so arm 1 is covered; need-turn eligibility; `test_t_*` scored apart from success; `--check-reference` runs `TRAP_SOLUTION`.
- **S2 + S3:** diagnose and fix the missing `prompt_ms` and `completion_tokens` on notes-refresh calls (tap or proxy; the S0 goldens must stay byte-identical); totals include refresh and compaction calls; a host-epoch record before and after each run; a flag for a pair split across epochs.
- **S5 + S6 (MERGED to main as `a43031e`; 31 tests pass):** `report.py --phase7` (2×2 table, McNemar, Newcombe interval, constraint task-bootstrap, needle gate at 0.95, traps, per-host breakdown); `eval/phase7_schedule.py` (seeded host draw, task order, arm order, 5 repeats); `eval/needle_strata.py`.
- **S7:** `eval/tasks/AUTHORING.md` (the author brief), `eval/tasks/trap_probe.py` (the temptation probe), and dev-t6..t10 written to the trap standard.

**The trap contract both S4 and S7 implement:**
- `TRAP_TURN`: a 0-based index into `TURNS`, at least 5. That request does not restate the warning.
- `TRAP_SOLUTION`: path → content, an overlay on `REFERENCE`. It passes the visible tests and `test_f_*`, and fails at least one hidden `test_t_*`.
- `test_t_*`: never counts toward success or constraints.
- `TRAP_PATTERNS`: D109's rule.

## Next steps

1. **Review and merge each branch into `main`.** The S1/S4 and S2/S3 branches both touch `eval/tasks/run.py`. Run the full suite after merging (about 12 minutes on Windows: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`). Commit and push to main directly; there are no long-lived branches. Stage explicit paths. Commits never mention AI tools.
2. **Write D112** (the trap standard T1–T7, as built) and **D114** (the Phase 7 tooling) in `docs/decisions/phase7.md`, and add their rows to `docs/decisions/README.md`.
3. **S8 pilot.** Relaunch both hosts at a real 32K. Run the temptation probe, then `a4-d77`, `a4-tr` and arm 1 on dev-t6..t10. Pass conditions V1–V3 are in plan §1.2. If V1 or V3 fails, revise D112 once and re-pilot. Write R64.
4. **Then S9:** held-out authoring by four separate author sessions. Seal (D113) and freeze (D115) before any held-out run (S10, S11).

## Hosts

- **pythia** (`ssh pythia`, Linux): Strata 0.1.58 at 64K, started by `~/strata-start.sh` (32K preset). The 64K start script is `strata-start-64k.sh`; see memory and D76/D103. Phase 7 needs it at a real 32K for S8–S11, then back to 64K.
- **Zeus** (`ssh zeus`, Windows, 192.168.1.19:8080): Strata 0.1.58 since D111.7, currently at 128K.
  - **Relaunch:** run `strata launch` (command in D108 and memory) detached through `Invoke-CimMethod Win32_Process Create`, or it dies when ssh closes. For 32K, pass `--context 32k`.
  - **Windows Update:** it restarted Zeus mid-run once (D108). Pause it for the whole run window.
  - **Accepting a build:** `palimnesis check --upstream http://192.168.1.19:8080`, plus probes p04, p12, p14 and p15 with `STRATA_URL` set. Revert the fixture files afterwards.

## Rules that must not slip

- **ho4 is never opened** (D96): not `eval/tasks/ho4_*`, `eval/needles/heldout4/` or `eval/needle_gen_ho4.py`. Nor is any heldout5/6 data, once it exists, until D115 is committed and the unlock file names the set.
- **Reruns only for infrastructure failures**, with `--reason` (D44.7). Every deviation from the plan gets a decision entry.
- **Reviewers report; they never edit.** Haiku-tier reviews were about 30% wrong on test redundancy, so verify every claim before acting on it.

## Known loose ends

- `palimnesis setup omp` needs rerunning for `~/.omp/agent` (it is the user's local config).
- The 64K report run from 4A was dropped; Phase 7 reports 64K instead (D111).
- Reviewer merges that were not applied: the cross-file eval merges, the `test_transcript.py` omission cases, the heading-style tests (they run at different budgets), and the CLI negative-flag tests. All are cosmetic.
