# Phase 7 handoff (state on 2026-11-20)

For whoever continues Phase 7. Read `CLAUDE.md`, then `docs/plan/phases/phase7.md` (the plan) and `docs/decisions/phase7.md`:
- D111: the user's scope, host and size decisions, and Zeus on 0.1.58;
- D112: the trap standard, the first pilot result and its revision;
- D114: the tooling as built.

This file says where the work stands. Delete it once its open items are closed.

## Done (all on `main`, pushed)

- Phase 4A closed and tagged `phase-4a`.
- The test cleanup, the Phase 7 plan and D111.
- Zeus moved to Strata 0.1.58.
- S0.
- **S1–S7 merged**:
  - unseen-set unlock and seal (`eval/heldout.py`);
  - traps for any arm, with need-turn eligibility;
  - serving metrics: refresh calls now record `prompt_ms` and `completion_tokens` (a proxy change, protocol-reviewed, with contracts §10 corrected);
  - the host epoch;
  - `report.py --phase7` and `eval/phase7_schedule.py`;
  - `eval/needle_strata.py`;
  - `AUTHORING.md`, `trap_probe.py` and dev-t6..t10.
- The full suite passes except one known flake, `test_admission_http.py::test_fifo_one_dispatch_across_sessions`. It asserts the order in which clients see responses finish, and it fails about 1 run in 5 on this machine, before Phase 7 too. It is timing-sensitive, not a regression.
- **Both hosts run Strata 0.1.58 at a real 32K, and both pass `palimnesis check`.**
  - pythia was switched from 64K with `~/strata-start.sh`. Switch it back to 64K after S11 with `~/strata-start-64k.sh`.
  - Zeus was relaunched with `--context 32k`. Windows Update on Zeus is paused until 2026-12-20 (registry pause keys).

## S8 pilot: done (R64)

- V1 5/5, V2 10/10 and V3 met: 2 genuine repeats, both in `a4-tr` (dev-t6, dev-t8). See `docs/results/phase7.md`.
- `captures/collect-phase7-pilot.py` prints the per-run table to stdout. It does not rewrite `captures/phase7-pilot-summary.json`, which is stale.
- Both pilot follow-ups are done (D112.9): dev-t10's patterns are tightened, and `report.py --phase7` counts a repeat only when a `code` hit and a failed `test_t_*` agree. A disputed run needs `--trap-reviews`.

## S9: done (D113.8–12)

- `a647c79` committed the 52 held-out files: ho5-t1..t20, ho6-t1..t10, the four generators and 18 histories. They were committed by path, without reading.
- `eval/heldout_hashes.json` seals them. `tests/test_phase7_heldout.py::test_phase7_seal_covers_authored_files_and_history_shape` checks the hashes and shapes.
- **Pre-seal checks, all passing:**
  - `--check-reference` on all 30 tasks;
  - each generator's `--check`;
  - declared strata, and coverage of at least 35 per level;
  - independence from the earlier sets;
  - T1 probes. Revised tasks had to pass two consecutive runs.
- **Cross-author overlap** is recorded in D113.11, not gated (user decision).
- **Exposures to the lead:** parts of ho6-t9 and the old ho6-t8, which was replaced. Both are reserve tasks (D113.12).
- **Never edit a sealed file.** Any change breaks `verify` and needs a decision entry.

## S10: done (D115)

- **The rehearsal** ran on retired ho3 at `a892e4a`. It exercised the pipeline end to end, and the proxy showed no defect.
- **Report gaps it found,** now fixed test-first in `eval/report.py`: the trap scan runs inside the report, the per-archive gates are shown, and pairs split across host epochs are flagged with a sensitivity table.
- **D115 freezes the protocol.** The freeze commit F carries D115, `eval/phase7_schedule_d115.json` and `eval/heldout_unlock.json` (heldout4 and heldout5; heldout6 stays locked). After F, only `eval/` and `docs/` may change.

## Next: S11, the held-out runs (D115)

- **Before starting:**
  - pause Windows Update on Zeus (now the only task host) and on the driver workstation;
  - turn off automatic reboots on pythia;
  - check free disk space on every host.
- **Run one stream per host from the workstation,** on a clean tree. D115.11 put the tasks on Zeus only and the needles on pythia:
  - `captures/run-phase7-s11.ps1 -HostName zeus -Upstream http://192.168.1.19:8080` runs the 25 task pairs, then the repeats;
  - `captures/run-phase7-s11.ps1 -HostName pythia -Upstream http://192.168.1.173:8080` runs all 30 needle histories.
  - **If a stream stops,** decide whether the stop was an infrastructure failure. If it was, rerun that step with `-Start N -Reason TEXT`. If not, resume with `-Start N+1`. Record either choice.
- **Report:**
  - `report.py --phase7 captures/phase7-s11-<sha>/zeus/tasks --schedule eval/phase7_schedule_d115.json --trap-suite ho5`;
  - `--needle-run` once for each of `pythia/needles-heldout4` and `pythia/needles-heldout5`, with `--needle-dirs eval/needles/heldout4,eval/needles/heldout5`.
- **Then Pi on ho4** (D115.8).

## Rules that must not slip

- **ho4 is never opened** (D96): not `eval/tasks/ho4_*`, `eval/needles/heldout4/` or `eval/needle_gen_ho4.py`. Exclude these paths from every grep; two agents leaked header and comment lines that way (D114.7). heldout5 data gets the same care until its runs finish, and heldout6 stays sealed for Phase 8.
- **Reruns only for infrastructure failures**, with `--reason`. Every deviation from the plan gets a decision entry. Commit and push to main; stage explicit paths; commits never mention AI tools.
- **Verify agent and reviewer claims before acting on them.**

## Hosts

- **pythia:** `ssh pythia`; Strata from `~/.local/share/strata/components/control/0.1.58`, started by the scripts above.
- **Zeus:** `ssh zeus`.
  - **Relaunch:** stop it, then `strata launch ... --context 32k`, detached through `Invoke-CimMethod Win32_Process Create` (D108, memory).
  - **Rollback to 0.1.57:** in D111.7.
