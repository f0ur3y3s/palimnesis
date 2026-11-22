# Phase 8 plan: operational hardening and the final release decision

Planned at `45a92e2` on 2026-11-22, from `v1_plan.md` (Phase 8 and the gate table above it), D117.5 and R65–R67. The open decisions (§6) are the user's. Planning never opened ho6 (`eval/tasks/ho6_*`, `eval/needles/heldout6/`) or `captures/`. ho6's size comes from `eval/heldout.py:53` and the hash manifest: **10 tasks, no needles**.

## Core positions

1. **Every `src/` change lands before the Phase 8 freeze commit F8.** The confirmatory runs then bind to the release commit. After F8 only `eval/` and `docs/` may change, as in D115.1, and a defect means a full rerun (D44.8).
2. **The candidate changes.** The notes fix changes what the model sees, so `a4-d77` is replaced. The new label is suggested as `a8-…` and is named in the decision that flips the default. Phase 7's quality results then describe `a4-d77` only (§3).
3. **One host: Zeus** (Strata 0.1.58, real 32K, one slot, 1.0 / 0.95 / 20 through the `-t1` config, D115.12).
   - Tasks and needles both run there.
   - Windows Update on Zeus is paused only until 2026-12-20, so the pause must be extended before the confirmatory runs.
   - POSIX-only checks need Linux (U11).
4. **The core stays harness-neutral.** Notes, replay, fork, disk admission and the CLI key off the protocol. How OpenCode and Pi react to a 507 or a 413 is probed, not assumed.
5. **ho4 and ho5 are retired to development data** (D117.4). They may be used to choose the notes fix and to validate the needle instrument. ho6 and the new heldout7 are confirmatory only.

## What exists today (checked in the code)

| Plan item | Today | Phase 8 gap |
|---|---|---|
| Passthrough flag | `serve --passthrough`, `test_passthrough.py` | regression only |
| Diagnostics | `palimnesis check` (`cli.py:482`) | no archive integrity check |
| Inspection CLI | `catalog`, `excerpts`, `state`, `transcripts` | — |
| Export, deletion, backup and restore | **none** | everything. §11 and §14 already promise deletion cascades |
| Migrations | forward-only `user_version` (`store.py:441`) | no refusal of an archive newer than the code |
| Busy database | `busy_timeout` 5000; tests for a commit that fails at input and mid-stream | busy during backup, projection and notes commit |
| Disk full | **none** | SQLITE_FULL and ENOSPC handling; disk admission |
| Deadline and malformed stream | tested | link to "accepted history is never lost" |
| Body size limit | **none** (planned in `phase1.md:110`, never built) | 413 before acceptance |
| Crash points | `pipeline.crash_point` at accept, excerpt commit, prepare and batch; projector publish; 6 tests | no notes or view points, no external kill, no concurrency |
| Streaming replay | keyed replay of a stream returns 409 (`ledger.py:907`) | replay |
| Fork | schema fields only; divergence returns 409 | a defined fork |
| Notes | n2 prompt says "replace any earlier notes" (`builder.py:96`, `:127`); `fit_notes` keeps k lines per section | nothing carries a previous version's lines |

Unverified: whether R65's lost warnings were dropped by the model or cut by `fit_notes`. The cut lines are recorded in `notes_outputs.dropped`, and S1 settles this.

## 1. Design

### 1.1 Notes keep user-stated failures (format n3)

- **Prompt.** The n2 prompt, plus one instruction under Dead ends: carry forward every earlier Dead-ends entry, and quote the user's words for anything they said was already tried and failed.
- **The guarantee: a deterministic carry** (a pure function, `carry_dead_ends(previous_text, reply)`).
  - Every previous Dead-ends line missing from the new reply is appended under the new Dead-ends heading. "Missing" is judged after normalizing whitespace and case.
  - The merge runs before `fit_notes`. With n3, Dead ends is kept whole and the other sections are cut to k lines.
  - Carried lines can leave only past a cap (U2). Lines removed that way go to `dropped`.
- **What it promises:** once any version records a failure, a later rewrite cannot drop it by leaving it out.
- **What it doesn't:** that v1 records the failure at all. If S1 finds a v1 that missed it, D65's pinned instructions enter the S3 pilot as a second arm.
- **Provenance and versioning.**
  - `notes_outputs` keeps the raw reply.
  - The version text is the merged text.
  - The `notes_version` event gains a `carried` count, which is a number only (§17).
  - `policy_version` becomes `+notes{S}n3h2`.
  - The n2 code and its goldens stay unchanged.
- **Citation:** the builder docstring cites R33-D, D72 and the context-engineering cookbook, and names the carry as the adaptation.

### 1.2 The needle instrument

- **Answer-format rule** (AUTHORING.md §2, `eval/needle_format.py`).
  - Every question ends with exactly one fixed sentence chosen by answer kind: identifier, number, path, value, or list with a named separator.
  - The evidence for the rule is R65: generator b's "Code only" questions scored 47/50, and generator d's conversational questions scored 12/40.
- **Answer-shape probe** (`eval/needle_shape_probe.py`).
  - It sends each question direct to Strata with the evidence in view, and checks it with the frozen `needle.normalize_loose`.
  - It passes on 3 of 3 samples, which tests phrasing, not recall.
  - It reports counts only. A revised question needs two consecutive passes.
- **Validated on retired heldout5** before any authoring. It should flag generators a, c and d and pass b. With the format sentence added, the questions should pass.

### 1.3 Confirmatory sizing: ho6 alone is not enough

- **What ho6 supplies:** 10 tasks and 0 needles. ho6-t9 is partly exposed to the lead (D113.12).
- **What that rules out:**
  - The needle gate is impossible with ho6 alone.
  - The trap gate ("0/20") is impossible with 10 tasks.
  - At around 30 constraints, one miss moves the constraint rate 3.3 points.
- **McNemar power floor.** With d discordant pairs all one way, the minimum two-sided p is 2^(1−d):

| d | 4 | 5 | 6 | 7 |
|---|---|---|---|---|
| min p | 0.125 | 0.0625 | 0.03125 | 0.0156 |

  - Unbalanced splits need more pairs: 8–1 gives 0.039, and 10–2 gives 0.039.
  - Phase 7 had 5 discordant pairs in 25 tasks. At N = 10 that means about 2–4 pairs, so the best attainable p is 0.125–0.5.
- **Repeat variance.** Success flipped in 4 of 10 arm-runs (R65).
  - A majority of 3 attempts cuts misclassification from 0.20 to 0.10 at a per-run p of 0.8, and from 0.30 to 0.22 at p = 0.7.
  - Extra attempts never add independent pairs (`v1_plan:336`).

| Option | Tasks | Attempts per arm | Pair-runs | Zeus slot hours (estimate) |
|---|---|---|---|---|
| A: ho6, k = 1 | 10 | 1 | 10 | ~9 |
| B: ho6, k = 3 | 10 | 3 | 30 | ~28 |
| C: ho6 + ho7 (20), k = 1 | 30 | 1 | 30 | ~28 |
| **D: ho6 + ho7 (20), k = 3, majority** | 30 | 3 | 90 | ~83 |
| E: ho6 + ho7 (30), k = 1 | 40 | 1 | 40 | ~37 |

- **Recommendation: D.**
  - The task outcome is "succeeds in at least 2 of 3 attempts", with one McNemar at α = 0.05.
  - The gate is the observed rate (majority successes ≥ arm 1's). Significance is reported, not gated.
  - Needles: 300 in heldout7.
  - Total about 100 h on Zeus, including the pilot and the rehearsal.
- **No extension.** After ho7 no sealed material remains, so N is fixed. A small |b − c| is reported as limited power, never as equivalence.
- **heldout7 needs:**
  - 20 tasks under the full trap standard, each passing two consecutive probes;
  - 30 needle histories (300 needles) under the format rule, passing the shape probe, with at least 30 per stratum level;
  - independence from every earlier set, including sealed ho6, checked by counts only;
  - 4 fresh author sessions in new domains;
  - a fixed report vocabulary, hashes, and an unlock that names the new protocol entry.

### 1.4 The protocol to freeze (before any ho6 or ho7 run)

- **Arms:** candidate `a8` at F8; baseline arm 1 (D115.1).
- **Run conditions:** Zeus only, with the host epoch recorded before and after each run, Windows Update paused, and a 30-minute turn limit.
- **Schedule:** seeded, both arms back to back, arm order seeded per attempt.
- **Primary:** majority-of-3 McNemar. A missing or killed attempt counts as a failure.
- **Secondaries:**
  - constraints over all attempts, with a task-cluster bootstrap;
  - traps over the declared suite (U4);
  - needles at loose exact ≥ 95% over 300;
  - per-archive gates on every candidate archive;
  - a sensitivity analysis without ho6-t9.
- **Reruns:** only for infrastructure failure, with no waivers.

### 1.5 Hardening design notes

- **Streaming replay (§6).**
  - A completed keyed stream is replayed from the archive through the endpoint's emitter, with no upstream call and no re-run of hidden tools.
  - Terminal metadata is stored at the terminal commit in a new immutable table (migration 8): finish reason, client-visible usage, message id and `created`.
  - Promised: event order, content and terminal metadata. Not promised: chunk boundaries or timestamps (U7).
- **Delivery recovery.**
  - A completed keyed stream, including one whose delivery was cut, is replayed.
  - A partial keyed stream gets `ambiguous_retry`.
  - Keyless requests are unchanged.
  - Automatic resume is deferred: the plan makes it optional, and it is never done automatically.
- **Fork (U6).**
  - An explicit fork into a new session, `palimnesis session fork SRC --at TURN`.
  - The prefix is copied with its provenance, plus a `forked_from` record.
  - Divergence inside a session stays 409.
- **Disk (U8).**
  - `serve --min-free-bytes` refuses a request before acceptance with `507 archive_full` and `x-should-retry: false`.
  - SQLITE_FULL after acceptance takes the `archive_unavailable` paths.
  - Test seam: `PALIMNESIS_MAX_PAGE_COUNT` sets `PRAGMA max_page_count`.
- **Archive operations.**
  - `export SESSION OUT`: JSONL of exact bytes with their SHA-256, ids, notes and excerpts.
  - `delete SESSION --yes`: proxy stopped, cascades to every table, FTS and the projection, then VACUUM.
  - `backup DEST`: the SQLite online backup API, safe while serving.
  - `restore SRC`: proxy stopped; integrity and schema check, then projection rebuild and verify.
  - An archive newer than the code is refused.

## 2. Slices

Seams: P pure · H fake-upstream HTTP · X subprocess · C CLI · E eval · L live (Zeus) · D docs. Red tests land first in every slice.

| # | Goal | Red tests | Decisions and records |
|---|---|---|---|
| S0 | Preconditions: full suite green on Zeus | — | D120 (scope; ho4 and ho5 retired; Zeus only; Linux plan; Update pause extended) |
| S1 | Diagnose the notes loss on retired ho5: model omission or `fit_notes` cut; counterfactual n3 merge over the recorded replies; added notes tokens | `eval/notes_audit.py` tests on a literal fixture archive (P) | R68; D121 (U1) |
| S2 | Notes n3 | H: v1 has the line, the v2 reply lacks it, and the next upstream notes block still has it verbatim; P: carried lines survive the cut, the merge dedupes, overflow goes to `dropped`, `policy_version`; a failed refresh keeps the previous version; new n3 golden with n2 goldens unchanged; the event carries counts only | §2 and §17; D122 |
| S3 | Choose the candidate (dev-t6..t10, retired ho5 traps): `a4-d77` against n3 (plus pins if S1 says so), 2 attempts each on ho5-t2, t4 and t13 | — (L) | R69; D123 flips the default and names `a8` |
| S4 | Needle instrument: format rule and shape probe | P: format lint; H: the probe sends the evidence and question direct to upstream; P: it uses the frozen scorer and prints counts only | R70 (ho5 validation); D124 |
| S5 | Streaming idempotent replay (Chat and Messages), no re-run of hidden tools, replay after a restart, partial stream → 409, conflicts, resume unsupported → 400 | H | §5 and §6; D125 (U7) |
| S6 | Fork and delivery recovery | H/C: the copy keeps provenance; unknown source or turn → 400; the parent is unaffected; in-session divergence stays 409; X: never resumed automatically | §4, harnesses.md; D126, D127 |
| S7 | Crash and concurrency matrix: new points before and after the notes commit, after the view record and after the terminal commit, with a concurrent second session; after restart, integrity, foreign keys, committed rows, abandoned attempt, FTS = rebuild, transcripts verify; **20 forced external kills** (10 boundaries × 2 protocols), plus `eval/kill_trials.py` with N = 50 | X | §11; R71 |
| S8 | Failure modes and limits: accepted history kept under disk full, busy, timeout and malformed streams; disk admission (507); projection ENOSPC; 413 before acceptance; slot past ceiling marks the server unhealthy; backup during a stream | H/P; probe how OpenCode and Pi react to 507 and 413 | §5, §8; D128 (U8) |
| S9 | Export, delete, backup, restore, migration guard, `check --archive` | C/P: exact-bytes round trip; delete cascades; delete refused while serving; restore validates; newer schema refused; each historical migration | §11, §14, README retention limits; D129 |
| S10 | Guides tested on clean machines (U10) | — | D130; R72 |
| S11 | Reviews: protocol (capability matrix), cache audit (n3 causes), paper fidelity (n3) | — | `capabilities.md` for the release |
| S12 | heldout7 authoring and seal, after S4 | Authors' checks plus the shape probe | D131 |
| S13 | Freeze F8 and dress rehearsal on retired ho5 (2 tasks × 2 arms × 3 attempts, plus 1 history) | — | D132 (U3–U5); unlock ho6 and ho7 |
| S14 | Confirmatory runs: needles first, then the tasks | — (L) | R73 |
| S15 | Final checks: full suite at the release commit (Zeus plus Linux), change-set report from F to F8 | — | R74 gate summary and limitations; D133 final decision; tag `phase-8` |

**Order:**
1. S0.
2. Two parallel tracks: S1 → S2 → S3, and S4 → S12.
3. S5–S10 alongside both. None is model-facing.
4. S11 after S2 and S5–S9.
5. S13 once every `src/` slice is merged and S12 is sealed.
6. Then S14 and S15.

## 3. Which Phase 7 results stay applicable

| Change | Still applicable | No longer applicable |
|---|---|---|
| n3 notes and the new default (model-facing) | R65's arm-1 figures; R65's per-archive passes, which describe `a4-d77` only; R64 | Every R65 and R66 quality result for the release candidate, superseded by S14 |
| Needle format rule and shape probe (eval only) | R65 heldout4 95.0%, as history | The R65 needle FAIL stands for `a4-d77` (D117.3) |
| Attempts rule, replay, fork, crash and pause hooks, offline CLI | Everything | — |
| Disk admission, 413, slot ceiling | Everything below the limits. Confirm 0 such events in the S14 archives | — |
| Migration 8 | Everything | Rerun the per-archive gates on migrated copies of the R65 archives |

## 4. Deferred and not claimed

- Implicit branching on divergence (U6).
- Automatic interrupted-turn resume (optional in the plan).
- Power-loss durability (U9): not claimed, and documented as a limitation.
- Phase 5 and 6 rows: those phases were skipped (D111.1).
- Hidden tools: experimental (D111.2).
- POSIX file modes (§14): need Linux (U11), otherwise pending.

## 5. Risks

- About 100 h on one host, with the Windows Update pause ending 2026-12-20.
- Three attempts give the 0-repeat trap gate three times the chances to fail.
- The n3 carry could crowd the 2,048-token notes slot. S1 measures it.
- The 3/3 shape probe may force many revisions while authoring.

## 6. Open decisions (the user's)

| # | Decision | Recommendation |
|---|---|---|
| U1 | Notes fix: (a) n3 prompt plus a deterministic carry; (b) prompt only; (c) verbatim pinned instructions on by default | (a). Add (c) as a pilot arm only if S1 finds a v1 that missed the warning |
| U2 | Carry cap | S/3 (~680 tokens); past it, the oldest carried lines go to `dropped` |
| U3 | Confirmatory size | D: ho6 + 20-task ho7, 3 attempts per arm, majority outcome, ~100 h. Fallback C, ~28 h |
| U4 | Trap suite | All 30 tasks. A task counts as a repeat if any candidate attempt repeats |
| U5 | Stopping | Fixed N, no extension |
| U6 | Fork | Explicit fork into a new session; in-session divergence stays 409 |
| U7 | Replay fidelity | Re-render from the archive plus stored terminal metadata |
| U8 | Disk full | `507 archive_full` before acceptance, `--min-free-bytes` default 1 GiB, harness reactions probed first |
| U9 | Power loss | Not claimed |
| U10 | Clean installations | Windows 11 (Windows Sandbox on Zeus) and Linux (container or WSL2); macOS only if advertised |
| U11 | Linux tests while pythia is away | WSL2 or a container on Zeus |
| U12 | Release claims | OpenCode confirmatory; Pi and OMP for protocol and lifecycle only; hidden tools experimental; Claude Code backlogged; Phases 5 and 6 skipped |
| U13 | ho6-t9's exposure | Include it, flag it, report a sensitivity analysis without it |
