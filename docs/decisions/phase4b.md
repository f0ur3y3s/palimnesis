# Decisions: Phase 4B (D80–)

[Index](README.md) · Material choices, their reasons and rejected alternatives; newest last.

## D80 — Source layout: subpackages by subsystem

Written on 2026-11-05, before any Phase 4B code, at the user's go-ahead. `src/palimnesis/` had 34 flat modules (about 11,800 lines), and Phase 4B adds a second client protocol.

1. **The layout.**

   | Package | Modules (old name if renamed) |
   | --- | --- |
   | `palimnesis` (the HTTP edge) | `api`, `cli`, `config`, `server`, `errors`, `sessions`, `capture` |
   | `protocols` | `chat`, `sse`, `assemble` |
   | `archive` | `store`, `ledger`, `rawarchive`, `rawdelta`, `addresses`, `fingerprint`, `transcript`, `turns`, `pipeline` (was `archive`) |
   | `view` | `builder` (was `view`), `engine` (was `viewengine`), `budget`, `stubs`, `catalog`, `affordances`, `cacheacct` |
   | `recall` | `proactive` (was `recall`), `search`, `excerpts`, `tools` (was `recalltools`) |
   | `transcripts` | `projection`, `projector` |
   | `upstreams` | `profile`, `strata/` (unchanged) |

   Phase 4B's Messages adapter goes in `protocols/`, beside `chat`.
2. **No behaviour change.**
   - Every module keeps its contents.
   - Imports inside `src/` are absolute (`from palimnesis.archive import ledger`) instead of relative.
   - The store's migration backfill target moved with its module (`palimnesis.recall.search:backfill_chunks`); it is looked up by name when an older archive migrates.
   - Logger names follow the modules (`palimnesis.view.engine`), still under `palimnesis`.
3. **Checks.**
   - Every module imports.
   - The full suite on pythia passes.
   - The two tests that name file locations were updated: the core/profile boundary test now lists the new paths, and the affordance-matrix test reads `docs/plan/phases/phase2.md`. That second one had been broken by the docs reorganization (`8df2a68`) and is fixed here.
4. **What keeps old names.** Decision and result entries written before D80 cite modules by the names they had then. `docs/glossary.md` and the living docs use the new ones.
5. **Rejected:**
   - Compatibility shims at the old import paths. They would keep two names for every module, with nothing outside this repo importing them.
   - Splitting `ledger` and `pipeline` internally. That is refactoring with its own review, not a move.

## D81 — Phase 4B scope decisions (user, 2026-11-05)

The user settled the Phase 4B plan's decisions that do not depend on probe evidence (`docs/plan/phases/phase4b.md` §4). Each took the plan's recommendation, except O-4B-7.

1. **O-4B-1 Upstream dialect: translate.** Anthropic Messages requests are parsed at the edge into the Chat-shaped neutral form, and Strata is called with Chat Completions.
   - Rejected: the client's dialect upstream, which forks counting, usage, the notes refresh and `--explain`, and meets Strata's `input_tokens: 1` usage on Messages.
   - Token parity with direct Messages is measured (M2) and reported.
2. **O-4B-3 Cells.** Required for the phase:
   - Pi on Chat Completions;
   - Pi on Messages;
   - Claude Code on Messages.

   OpenCode on Messages gets fixtures and a smoke run, and is advertised only if its probe passes. OpenCode on Chat Completions is already supported.
3. **O-4B-4 Association.**
   - Pi: an extension sets `X-Palimnesis-Session` from Pi's session id.
   - Claude Code: a per-process wrapper runs `palimnesis session new`/`url` and sets `ANTHROPIC_BASE_URL`.
   - Rejected for now: a generic `--identity-header` mapping, which is a new identity source under contracts §4.
4. **O-4B-6 History rewrites** (manual `/compact`, Claude Code `/clear` and `/rewind`): `409 history_divergence`, documented per harness, with detection proven structural. Accepting a compaction as a new branch waits for Phase 8 branching.
5. **O-4B-10 `count_tokens`:** relayed to the upstream, unarchived. Claude Code's own context limit is set high, as OpenCode's `limit.context` is.
6. **O-4B-11 Evaluation:**
   - 4B's gates are contract tests, live smoke, fault runs and transcript gates.
   - Needles and coding tasks against native compaction run on development data and are reported, not gated.
   - A fresh held-out set `ho4` is written by a separate author before any Pi or Claude Code run, and kept unseen for Phase 7.
7. **O-4B-7 Admission: measure 2 slots first, then build slot-aware admission.**
   - The user asked whether Strata could run more slots instead.
   - Strata has `--parallel N` and reports `total_slots` in `/props`. Its launch guide recommends 1 slot for a 12 GB card, and pythia's RTX 3060 runs at 11.3 of 12.3 GB at one slot.
   - So before admission is built, Strata on pythia is restarted with `--parallel 2` (the user approved the restart) and measured against the one-slot numbers: fit, expert cache, prefill and decode speed alone and with two concurrent requests, and prompt-cache reuse per slot.
   - Admission then dispatches up to the slot count the upstream reports, with a queue and `429` beyond it. Its H, K and Q values are set from the Pi and Claude Code timeout probes.
   - The test runs after the Strata Messages probes (M1–M5) finish, since it restarts the server they use.

Still open, pending probe evidence:
- O-4B-2: thinking signatures;
- O-4B-5: Pi's partial-replay retry;
- O-4B-8: Claude Code side calls;
- O-4B-9: Pi's `developer` and `store` defaults;
- O-4B-12: mid-conversation system messages;
- O-4B-13: Claude Code's fit at 32K.
