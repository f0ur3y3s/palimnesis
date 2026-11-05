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
