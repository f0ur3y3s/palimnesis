# Phase 7 handoff (state on 2026-11-19, 20:40 EST)

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

## S8 pilot: in progress

- **V1 passed after the revision:** 5 of 5 tasks tempting, every hit read by hand (D112.8). The rewritten traps are on main (`324150b`).
- **Task runs at a real 32K**, all three arms of a task back to back on one host. Records go to `captures/phase7-pilot-487add0/<arm>/<task>/`.
  - **pythia:** dev-t7. Script `captures/run-phase7-pilot-t7.ps1`, log `captures/phase7-pilot-t7.log`. Started at `487add0`. Its later arms run at the newer commit, but dev-t7, `run.py`, `src/` and `state_eval` are identical between the two.
  - **Zeus:** dev-t6, then dev-t8. Script `captures/run-phase7-pilot.ps1 -Upstream http://192.168.1.19:8080 -Tasks "dev-t6,dev-t8"`, log `captures/phase7-pilot-zeus.log`.
  - **Next, on pythia, once dev-t7 is done:** `captures/run-phase7-pilot.ps1 -Upstream http://192.168.1.173:8080 -Tasks "dev-t9,dev-t10" -Tag pilot-<commit>`, at a clean tree.
- **Then:**
  - check V2 (T7 held in every `a4-d77` and `a4-tr` run, from `trap_eligible_at_need`) and V3 (at least one `code` repeat across `a4-tr` and arm 1; for arm 1, use `state_eval --bodies`);
  - read every `code` hit by hand, because the dev-t8 and dev-t10 patterns can fire on correct code;
  - write R64 in a new `docs/results/phase7.md`.

## After the pilot

- **S9: held-out authoring** by four separate author sessions, from `AUTHORING.md`.
  - First build the independence check (no 4-word run shared with an earlier set); it does not exist yet (D112.6).
  - Pin the needle `strata` field format.
  - Unlock ho4 for Pi (D114.1).
  - Seal everything (D113).
- **S10:** the dress rehearsal on retired ho3, including real arm-1 captures through the bodies trap path. Check the `/v1/status` field names on 0.1.58. Then freeze the protocol (D115).
- **S11:** the held-out runs, following the seeded schedule.

## Rules that must not slip

- **ho4 is never opened** (D96): not `eval/tasks/ho4_*`, `eval/needles/heldout4/` or `eval/needle_gen_ho4.py`. Exclude these paths from every grep; two agents leaked header and comment lines that way (D114.7). The same applies to heldout5/6 data until D115 and the unlock.
- **Reruns only for infrastructure failures**, with `--reason`. Every deviation from the plan gets a decision entry. Commit and push to main; stage explicit paths; commits never mention AI tools.
- **Verify agent and reviewer claims before acting on them.**

## Hosts

- **pythia:** `ssh pythia`; Strata from `~/.local/share/strata/components/control/0.1.58`, started by the scripts above.
- **Zeus:** `ssh zeus`.
  - **Relaunch:** stop it, then `strata launch ... --context 32k`, detached through `Invoke-CimMethod Win32_Process Create` (D108, memory).
  - **Rollback to 0.1.57:** in D111.7.
