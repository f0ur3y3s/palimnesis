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

## D82 — Phase 4B decisions settled by the S0 probes (user, 2026-11-05)

The S0 probes are in `docs/probes/strata.md` §13, `docs/probes/pi.md` and `docs/probes/claude_code.md`. They gave the evidence for the six decisions D81 left open. The user took each recommendation, except O-4B-13.

1. **O-4B-2 Thinking signatures: `""`.**
   - Palimnesis streams thinking blocks to Messages clients with an empty signature, as Strata does.
   - Claude Code 2.1.318 replays `""` as thinking, also after a restart (HC4).
   - Pi 1.5.0 demotes it to text unless `compat.allowEmptySignature: true` (HP3), so the Pi adapter config ships that setting.
   - Rejected: an opaque proxy signature, a new mechanism and key that no advertised client needs.
2. **O-4B-5 A failed partial left out of the resend is accepted.**
   - Pi drops a failed partial from every later request, even with its retries off, on both protocols (HP4).
   - D13.1 is extended: a partial whose attempt ended with the proxy's own in-stream error may be omitted from the resend. It stays archived, marked superseded. This is a protocol-level rule, not keyed to Pi.
   - Rejected: keeping the 409, which leaves a Pi session unusable after one upstream failure.
3. **O-4B-8 Side calls: nothing to build.** Claude Code made no title, quota, summary or memory calls under the candidate env, interactively or in `-p` (HC2). `--side-model` is not built.
4. **O-4B-9 Pi's Chat defaults: adapter flags.**
   - `supportsDeveloperRole: false` and `supportsStore: false` exist and work (HP3), so the Pi adapter sets them.
   - Two forms have no switch, so the Chat subset accepts them:
     - user content as an array of text parts;
     - `content: null` on tool-call-only assistant turns.
5. **O-4B-12 Mid-conversation system entries: rendered as Strata renders them.**
   - Strata renders a later `role: system` message as a user message in place, on both routes (M2). Palimnesis maps it the same way and keeps the client's history as sent.
   - The local counter must be fixed for that shape, and for `reasoning_effort: "max"`, which it now refuses (M2, c4).
   - Rejected: a 400. Claude Code folds the entry into the previous user message and keeps the fold (HC3), which would change what the model sees.
6. **O-4B-13 Claude Code runs at 64K.**
   - Claude Code's fixed input is 18,812 tokens interactively (26 tools) and 16,024 in `-p` (HC3). At 32K the floor allows 18,176.
   - Claude Code work therefore runs against Strata restarted at 64K on pythia; the user approved that restart for Claude Code work. Results are reported per context, as R26 was.
   - Rejected for now: denying 17 tools to fit 32K (fixed input 3,784), which changes the harness from its shipped form.

**Corrections the probes make to the plan** (`docs/plan/phases/phase4b.md`):
- **Tool-call arguments keep their key order.** Sorting the keys changes the tokens and loses cache reuse (M2/M4), so "canonical JSON" in position 3 means the client's own serialization.
- **The adapter copies four Messages-route behaviours:**
  - the billing-header stamp handling;
  - `description: ""` for a tool without one;
  - `budget_tokens` mapped to an effort level;
  - effort `max` mapped to `xhigh`.
- **Keepalives, errors and the envelope.**
  - Strata sends only comment keepalives and never Anthropic's error envelope (M1, M3). Palimnesis produces `ping` and the envelope for Messages clients.
  - Claude Code accepts comments or `ping` as keepalives, including a `ping` before `message_start` (HC5). Pi's idle timer resets on either (HP4).
- **Claude Code's own limits.**
  - Claude Code checks its context against reported usage, so `CLAUDE_CODE_MAX_CONTEXT_TOKENS` must be 1,000,000 (HC6).
  - Claude Code never calls `count_tokens` (HC1), so O-4B-10's relay is a correctness fallback only.
- **Cache breakpoints.** Claude Code's moving `cache_control` turns a text-block list into a plain string on the next request. The adapter treats the two as equal content (HC3).

## D83: The client-protocol seam (Phase 4B S1) and one Strata slot

**Seam.** `palimnesis.protocols.ClientProtocol` is the edge between a client's wire protocol and the core. Chat Completions now sits behind it with no behaviour change (the full suite passes unchanged, 1,702 tests).
- A protocol has a name, its endpoint, its transport-only fields, a `parse` into the neutral Chat-shaped request, and an `emitter` factory.
- `api` picks the protocol by path (`protocols.for_path`). `archive.pipeline` parses, fingerprints and accepts with it. `archive.ledger` stores the endpoint on the request row, and `replan` re-parses an archived body with the protocol that row names.
- **Deviation from the plan's S1 row:** the error event and the keepalive are methods of the per-response `Emitter`, not fields of the protocol. A Messages error event or `ping` may depend on the stream's state (an open content block), so they live with the state machine that tracks it. The emitter also encodes a non-streaming body.
- **The upstream target is fixed.** Every archive-mode upstream call goes to `UPSTREAM_ENDPOINT` (`/v1/chat/completions`, position 2). The client's query string is relayed only when the client spoke that dialect, so `?beta=true` from a Messages client never reaches Strata's Chat route. No protocol flag is needed for this; it follows from the path.
- `test_core_never_keys_off_harness_or_user_agent` checks every core module's identifiers for `opencode`, `claude` and `pi` tokens and for code that reads `User-Agent`. `integrations/` is exempt.

**Slots (O-4B-7, measured).** Strata on pythia stays at one slot (`docs/probes/strata.md` §14).
- Two slots fit at 32K per slot, but the expert cache shrinks from 5.17 to 4.05 GiB and decode drops from 50.9 to 34.3 tok/s for a single request.
- Two concurrent requests finish at 59 and 62 s, against 27 and 54 s on one slot, because Strata still prefills one request at a time and decode stalls during the other's prefill.
- Admission (S6) reads `total_slots` from `/props` and dispatches up to it, so a larger card needs no code change.
