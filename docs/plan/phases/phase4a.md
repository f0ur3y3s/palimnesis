# Phase 4A plan: pinned state

Written 2026-11-18 at `a6f65d2` (after `phase-4b`, R60). Module paths follow D80. Decisions are D105 onward (`docs/decisions/phase4a.md`).

**Scope:**
- v1_plan "Phase 4A — Pinned state" and its two green lights.
- The contract clauses it touches: cache behaviour (§10 `state_commit`/`state_refresh`, placement cost), budgets (§2, the notes slot S), model-facing affordances (versioned, A/B on development data, frozen before held-out), durability (§11) and scheduling (§8).
- A1's evaluation rules.
- R42's open item: how the working notes relate to the pinned state.

## Core positions

1. **The working notes are the pinned state.** 4A grows them; it adds no second mechanism.
   - D72, D74 and D75 already ship most of what 4A asks for, as `a4-d77` (D78):
     - a model-written, versioned, immutable state (`notes_versions`, numbered per branch, named by `ViewState.notes`);
     - sections for objective, current step, requirements and constraints, decisions, done so far and dead ends;
     - a deterministic cut (n2 `fit_notes`);
     - a fixed place;
     - its own cache causes (`state_commit`, `state_refresh`).
   - Code names stay `notes`. Contracts gain §17, "Pinned state".
2. **4A adds provenance, retrievability and measurement, not model-facing change.**
   - **What it adds**, deterministic and test-first:
     - the whole refresh reply and its reasoning are archived;
     - each version records its provenance;
     - the addresses the state cites are recorded and resolved;
     - each state commit records its prefix cost, reported per cause.
   - **Upstream bytes.** `a4-d77`'s upstream bytes do not change. A golden test guards this.
   - **Model-facing variants** (n3 "useful addresses", a priority cut, an 800-token slot) sit behind flags, run on development data only, and are reported.
3. **No `palimnesis_state_update` tool** (D105.2). The model writes the state through the existing proxy-triggered refresh (D72's choice B), for these reasons:
   - R32's hidden tools failed both held-out gates;
   - Messages has no hidden tools (contracts §16);
   - a commit in the middle of a turn re-reads everything after the system message.
4. **Harness-neutral.** The state path keys off neither protocol nor harness. The upstream is always Chat (D83), and OpenCode, Pi and OMP get the same state.
5. **Evaluation is development data, reported; contracts are the gates.** `ho4` is never opened (D96).

## Findings in current code

- **F1: the originals of the cut are lost.** `_refresh_notes_once` stores only `fit_notes(written)`. The reply before the cut and the refresh's reasoning are thrown away.
- **F2: provenance is thin.** `notes_versions` lacks:
  - the archive cutoff;
  - the refresh call id;
  - the prompt format and header;
  - what the cut dropped.
- **F3: no "useful addresses".** Whether the model cites `§ALIAS` addresses or `turn-NNNN` files is unmeasured.
- **F4: the cut treats sections equally.** How often a cut happens at S = 2,048 is unmeasured (F1).
- **F5: GL1 is half there.** `cacheacct.explain` labels `state_commit` and `state_refresh`, but records neither the prefix cost the commit itself adds nor a summary per cause.
- **F6: dead ends are never measured.** Tasks state a `TRAP`, but nothing detects a repeated one or counts the watermark moves since it was stated.
- **F7: refreshes that never render** (D93's known cost) are unmeasured.
- **F8: known limits carried over unchanged:**
  - no refresh inside hidden continuations;
  - `over_budget` with no call;
  - foreground refreshes only.

## 1. Design

1. **Where the state lives: unchanged.**
   - It is a user-role block after the leading system message.
   - S is reserved and counted in admission and the floor.
   - It is refreshed only on a collapse move.
2. **Provenance and outputs.** Store migration v7 adds two immutable tables:
   - **`notes_outputs`**, one row per refresh attempt that produced a stream, failed ones included:
     - the version it belongs to, `call_id`, `archive_seq`, `prompt_format`, `header`;
     - `content`, `reasoning`, `content_sha256`, `source` (`reply` or `from_reasoning`);
     - `dropped`: the line indices the cut left out.
   - **`notes_sources`**: `(notes_id, idx, token, kind, target_id, status)`, with `kind` either `alias` or `turn`, and `status` one of `valid`, `unknown` or `ambiguous`.
   - **Commit order.** Both commit in the same write as the version, before the rebuilt view is sent, off the event loop.
   - **Events.** They carry counts only, never text.
3. **Cut report.** A pure `fit_notes_report(text, fits, *, sections) -> (kept, dropped)`. Its rule is the same as `fit_notes`.
4. **Cited addresses.** A new pure module `view/state.py`.
   - `cited_addresses(text)` finds `§`-prefixed aliases (with an optional `.N` block) and `turn-NNNN` names. It never takes bare base32-looking words.
   - The addresses are resolved, scoped to the session. They are recorded and never rewritten.
5. **Conflict and provenance rules** (contracts §17):
   - The state is the model's own fallible text, rendered user-role. Precedence: system, then user instructions in view, then excerpts, then the state.
   - The newest committed version replaces older ones. A failed refresh keeps the previous one. A retry after a failed answer reuses the committed state; a crash between the version and the view move can refresh twice (known limit, D106).
   - The state is not a recall source: it is not indexed, not excerpted, not in transcripts and not in the client stream.
   - Every version names its request, base view, cutoff, call id and formats. Its full output is archived.
   - One serialized branch until Ph8.
6. **Prefix cost of a commit (GL1).**
   - For a `state_commit` pair, `explain` records `state_marginal_tokens`.
   - `eval/replay.py --explain --by-cause` sums per cause: pairs, re-read tokens and `prompt_ms`. It reports `#notes` calls separately.
7. **Variants behind flags**, off by default and development only. Each is named in `policy_version`.
   - `--notes-format n3`: n2 plus "Useful addresses".
   - `--notes-cut priority`: built only if the baseline shows cuts that drop constraint or dead-end lines (D105.6).

## 2. Slices

Seams: P pure · H fake-upstream HTTP · E eval · L live · D docs. Each slice is red tests first, then code, then contract text.

| # | Slice | Red tests | Code | Contract |
|---|---|---|---|---|
| S0 | Model-facing guard | `test_a4_d77_upstream_bodies_unchanged_by_phase_4a` (H, literal fixture recorded at `phase-4b`) | fixture | — |
| S1 | Cut report | `fit_notes_report` tests (P) | `view/builder.fit_notes_report` | — |
| S2 | Outputs and provenance archived | reply and reasoning archived, failed outputs, cutoff/call id/formats, immutability, commit before send, no state text in logs (H) | store v7, `ledger`, `pipeline` | §17, §11 |
| S3 | Cited addresses | extraction (P); valid/unknown/ambiguous recorded, never rewritten, cross-session unknown (H) | `view/state.py`, `ledger` | §17 |
| S4 | GL1 measurement | marginal tokens; cause iff notes changed; `--by-cause` (H) | `cacheacct.explain`, `eval/replay.py` | §10 |
| S5 | Conflict and isolation rules | placement, replacement, retry and restart, not indexed, not in stream or transcripts (H) | likely none | §17 |
| S6 | Inspection | `palimnesis state SESSION [--version N] [--raw] [--sources] [--json]`, read-only (H/P) | `cli` | README |
| S7 | Harness neutrality | the same refresh for Chat and Messages clients (H) | none | §17 |
| S8 | Eval tooling | trap patterns, moves-after-statement, attribution, `forbidden` scoring, refusing `ho4` (P/E) | `eval/state_eval.py`, task modules, `needle.py` | — |
| S9 | Flagged variants (optional) | n3 prompt, `policy_version`, priority cut (P/H) | `builder`, `config`, `cli` | §2 |
| S10 | Evaluation runs (§6) | — | — | — |
| S11 | Reviews, results, tag `phase-4a` | — | — | all |

**Order:** S0 to S4; then S5 to S8; then the S10 baseline; then S9 if triggered; then the S10 candidates; then S11.

## 3. Requirement → test / measurement / deferral

| Requirement | Test, measurement or deferral |
|---|---|
| Versioned goal, constraints, decisions, current step, dead ends | n2 sections (existing tests); S2 provenance |
| Useful addresses | S3 (cited and resolved); n3 under flag (S9); default flip deferred |
| `palimnesis_state_update` | Replaced by D72's refresh (D105.2) |
| Default 800-token cap | Deviation: 2,048 kept on R41's evidence (D105.3); an 800 arm only if slot time allows |
| Archive state versions and supporting addresses | Existing `notes_versions`; S2; S3 |
| Define conflicts and provenance | S5; S2; §17 |
| Drop low-priority entries deterministically; originals retrievable | S1, S2, S6; priority cut by D105.6. Model-facing access to dropped lines deferred (it would change t1/a3) |
| State aids navigation, never replaces instructions | S5; GL2's attribution |
| Optional fallback refresh | Deferred (D105.9) |
| Independently releasable from 4B | `Settings` defaults keep notes off; full suite green |
| **GL1** explicit invalidations with measured prefix impact | S4; `--explain` 0 unexplained and `--by-cause` on every S10 archive |
| **GL2** early constraints and already-tried tasks over several watermark moves | `state_eval.py`: counted only when at least 3 watermark moves follow the statement; trap detector; dev-state needles |
| Harness neutrality | S7; AST seam test |
| `a4-d77` unchanged | S0 golden; `test_eval_d77` |

## 4. Evaluation (S10)

- **Conditions** (D105.12):
  - All arms of one comparison run on one host and build, at one context.
  - Zeus (Strata 0.1.57, 128K) runs at an emulated 32K (`--input-budget 24320`) after `palimnesis check` passes by counts.
  - The 64K report run is on pythia as it stands.
  - Sequential under D39, with the 30-minute turn limit.

| Run | Arms | Data | Status |
|---|---|---|---|
| Baseline | `a4-d77` | dev-t1..t5, ho2-t1..t5, ho3-t1..t5 (retired, D105.10), OpenCode 2.1.4; dev-state needles (new) | GL1 measured; GL2 reported |
| Ablation | `a4-tr` (no state) | the same | reported |
| Candidate | `a4-trn3h`; priority cut only if triggered | dev-state needles, ho3 tasks | reported |
| Neutrality smoke | `a4-d77` | dev-t1 on Pi Messages | gate: D44.6 inputs, at least 1 committed version |
| 64K | `a4-d77` | ho3 tasks on pythia | reported |
| D44.6 inputs | all | — | gate |

- **Never used:** `ho4`, and arm 1 (Phase 7's comparison).

## 5. Risks and deferred

**Risks.**
- **Trap-pattern accuracy.** Doubtful hits are reviewed by hand.
- **Archive growth.** Archiving reasoning adds about 2–6K tokens per version.
- **ho3 is spent.** Retiring it uses up the last fresh set before Phase 7.
- **Emulated 32K** is not real 32K.
- **Zeus's equivalence** must be checked before any run.
- **Single attempts** show direction, not effect size.

**Deferred.**
- The state tool.
- Background refresh.
- Model-facing access to dropped lines.
- Slot scaling with the budget.
- Skipping refreshes that never render.
- State per branch (Ph8).
- Held-out judgement (Phase 7).
- D65 pins as a constraint floor.
