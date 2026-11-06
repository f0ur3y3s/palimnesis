# Results

Measured results, append-only. Each entry names its commit (or "uncommitted" with the date), configuration and hardware. New entries go at the end of the newest file; start a new file when a phase begins.

| File | Entries |
| --- | --- |
| [phase0-1.md](phase0-1.md) | Phases 0 and 1 (R1–R11) |
| [phase2.md](phase2.md) | Phase 2 (R12–R17) |
| [phase3.md](phase3.md) | Phase 3, first gate (R18–R27) |
| [phase3b.md](phase3b.md) | Phase 3B, hidden recall tools (R28–R32) |
| [phase3-acceptance.md](phase3-acceptance.md) | Working notes and Phase 3 acceptance (R33–R42) |

## Index

| Entry | Title | File |
| --- | --- | --- |
| R1 | Passthrough overhead vs. fake upstream (Phase 0, 2026-10-24, pre-initial-commit) | [phase0-1.md](phase0-1.md) |
| R2 | OpenCode 2.1.4 live through passthrough; fixed overhead (Phase 0, 2026-10-24, uncommitted) | [phase0-1.md](phase0-1.md) |
| R3 | Passthrough overhead after the raw-ASGI rewrite (Phase 0, 2026-10-24, uncommitted) | [phase0-1.md](phase0-1.md) |
| R4 | Phase 0 gate (2026-10-24) | [phase0-1.md](phase0-1.md) |
| R5 | Cancellation to slot release through the proxy, live Strata (Phase 1 carry-over, 2026-10-24) | [phase0-1.md](phase0-1.md) |
| R6 | Raw archive growth, v1 vs v2 deltas, and archive-mode metadata (Phase 1 slice 16, 2026-10-24) | [phase0-1.md](phase0-1.md) |
| R7 | FULL vs NORMAL commit latency and archive relay delay (Phase 1 slice 16, 2026-10-24) | [phase0-1.md](phase0-1.md) |
| R8 | After D12 tuning (Phase 1, 2026-10-24, working tree after `fd1e34c`) | [phase0-1.md](phase0-1.md) |
| R9 | OpenCode 2.1.4 live through archive mode, with restart and client interrupt (Phase 1 live check, 2026-10-24) | [phase0-1.md](phase0-1.md) |
| R10 | Client-interrupt fix (D13.1) checked live (Phase 1, 2026-10-24) | [phase0-1.md](phase0-1.md) |
| R11 | Phase 1 gate (2026-10-24) | [phase0-1.md](phase0-1.md) |
| R12 | Bounded-view watermark frequency, re-read and builder latency (Phase 2 GL7, 2026-10-25) | [phase2.md](phase2.md) |
| R13 | `bench_archive` rerun: TTFB growth with BranchCache, metadata with excerpt rows (Phase 2, 2026-10-25) | [phase2.md](phase2.md) |
| R14 | Live forced-budget OpenCode run through bounded views (Phase 2 GL8, 2026-10-25) | [phase2.md](phase2.md) |
| R15 | Live excerpt replay: prefix reuse with blocks included vs omitted (Phase 2 GL8, 2026-10-25) | [phase2.md](phase2.md) |
| R16 | Builder latency after the off-path stub warm-up (Phase 2, D25, 2026-10-25) | [phase2.md](phase2.md) |
| R17 | Phase 2 gate summary (2026-10-25) | [phase2.md](phase2.md) |
| R18 | Proactive-recall selection latency at 1M archived tokens (Phase 3, 2026-10-25) | [phase3.md](phase3.md) |
| R19 | Phase 3 development needle set and the O3 hybrid emulator (S10, 2026-10-25) | [phase3.md](phase3.md) |
| R20 | Phase 3 development matrix at emulated 32K (S10, 2026-10-25, EMULATOR) | [phase3.md](phase3.md) |
| R21 | Defects found by the development runs (S10, 2026-10-25; A and B fixed by D41) | [phase3.md](phase3.md) |
| R22 | x1 against x2 on the fixed proxy, two runs each (S10, 2026-10-25, EMULATOR) | [phase3.md](phase3.md) |
| R23 | S11 tooling smoke runs through real OpenCode (development data only, 2026-10-25) | [phase3.md](phase3.md) |
| R24 | S11 development smoke on the final commit; held-out runs not started (2026-10-25) | [phase3.md](phase3.md) |
| R25 | S11 held-out at 32K (2026-10-25/26) | [phase3.md](phase3.md) |
| R26 | S11 held-out at 64K, reported only (D44.9; 2026-10-26) | [phase3.md](phase3.md) |
| R27 | Phase 3 gate summary (2026-10-26) | [phase3.md](phase3.md) |
| R28 | Phase 3B S10 development matrix: halted after arm B (2026-10-26, development data only) | [phase3b.md](phase3b.md) |
| R29 | Phase 3B S10: matrix resumed, development tasks, and why arm 5 lost to native compaction (2026-10-26/27, development data only) | [phase3b.md](phase3b.md) |
| R30 | Phase 3B S10b: the R29 fixes re-run on development data (2026-10-27, development data only) | [phase3b.md](phase3b.md) |
| R31 | S11 held-out at 32K, attempt 1: stopped on a proxy defect (2026-10-27) | [phase3b.md](phase3b.md) |
| R32 | S11 held-out at 32K, the D44.8 rerun: both Phase 3B gates fail (2026-10-27/28) | [phase3b.md](phase3b.md) |
| R33 | Why Palimnesis loses coding tasks: diagnosis from the ho2 records (2026-10-28, development data per D69) | [phase3-acceptance.md](phase3-acceptance.md) |
| R34 | The R33 fixes on ho2: current turn kept, no reasoning in excerpts, working notes (2026-10-28, development data per D69) | [phase3-acceptance.md](phase3-acceptance.md) |
| R35 | Working-notes format n2 on ho2 (2026-10-28, development data per D69) | [phase3-acceptance.md](phase3-acceptance.md) |
| R36 | `a4-trn2` on all of ho2: second attempts, ho2-t1, ho2-t5 and the needles (2026-10-28/29, development data per D69) | [phase3-acceptance.md](phase3-acceptance.md) |
| R37 | Which change brings R36's early stops on: ho2 needles without notes, and with notes n1 (2026-10-29, development data per D69) | [phase3-acceptance.md](phase3-acceptance.md) |
| R38 | Replaying the early stops directly against Strata, with the notes varied (2026-10-29, development data per D69) | [phase3-acceptance.md](phase3-acceptance.md) |
| R39 | Notes header h2 (D75) on the ho2 needles, ho2-t3 and ho2-t4 (2026-10-29, development data per D69) | [phase3-acceptance.md](phase3-acceptance.md) |
| R40 | `a4-trn2h` again: a second ho2 needle attempt, and ho2-t1, t2 and t5 (2026-10-29, development data per D69) | [phase3-acceptance.md](phase3-acceptance.md) |
| R41 | D77 held-out run: `a4-d77` on ho3 (2026-11-04/05, pythia, held-out per D77) | [phase3-acceptance.md](phase3-acceptance.md) |
| R42 | Phase 3 gate summary, second: accepted on the shipped configuration (2026-11-05) | [phase3-acceptance.md](phase3-acceptance.md) |
| R43 | Pi 1.5.0 live through Palimnesis: smoke on both protocols and the transcript gate (2026-11-05) | [phase4b.md](phase4b.md) |
| R44 | Pi's faults (34 runs), cancellation release and proxy restarts through Palimnesis (2026-11-05) | [phase4b.md](phase4b.md) |
| R45 | Pi's development needles through Palimnesis: 42/60, early stops from one cut answer (2026-11-05) | [phase4b.md](phase4b.md) |
| R46 | Where the wall-clock gain over native compaction comes from: summaries written, redone work, re-reading (2026-11-05) | [phase4b.md](phase4b.md) |
| R47 | Pi's development coding tasks on Chat: a4-d77 5/5 in 62 min against Pi's compaction 4/5 in 4.9 h (2026-11-06) | [phase4b.md](phase4b.md) |
| R48 | Pi's development needles on Messages: 51/60, 3 early stops (2026-11-06) | [phase4b.md](phase4b.md) |
| R49 | Archive size and how it grows: a measured model, within ±15% on nine archives (2026-11-06) | [phase4b.md](phase4b.md) |
