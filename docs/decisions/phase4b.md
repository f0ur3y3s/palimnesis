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

## D84: The Messages subset and its neutral mapping (Phase 4B S2)

`palimnesis.protocols.messages.parse` maps a Messages body to the neutral Chat form as Strata 0.1.54's Messages route renders it. The M2 corpus is the test: every case the subset accepts counts, locally on its neutral body, exactly the prompt the Messages route rendered (`test_parity_corpus_counts_equal_recorded_count_tokens`, 45 cases), and the other 12 are rejected. Contracts §16 has the table. Choices the plan left open:

1. **`ChatRequest.neutral`.** The raw Anthropic body stays the archived `raw`. A new optional field carries the neutral Chat body, and `chat_body` returns whichever the upstream and the counter read. Chat requests leave it unset, so nothing changes for them.
2. **Assistant turns with no text have `content: null`,** not `""`. The archive rebuilds such a turn with null content (`ledger.message_dict`), and an empty text block would change the content hash against the generated turn. Both render the same tokens (parity cases with thinking and tool calls).
3. **`budget_tokens` maps to an effort level only.** Strata's Messages route also turns it into `reasoning_budget_tokens`, a hard cap on thinking. The Chat subset has no such field, so a Pi request (`budget_tokens: 7168`) thinks at `medium` with no cap through Palimnesis. That is a known difference from the direct Messages arm, recorded here rather than hidden; adding the field to the Chat subset is a later choice.
4. **Accepted with no effect:** `thinking.display` (Pi sends `summarized`), `eager_input_streaming` (Pi), `metadata.user_id` (Claude Code), `cache_control` with type `ephemeral` and an optional `ttl`, and `signature`.
5. **`is_error` is not in the neutral form.** Strata does not render it, so a resend that flips it is not a divergence. The raw body keeps it.
6. **Rejected where Strata would drop silently:** `redacted_thinking`, `document`, images and unknown block types. Strata leaves them out of the prompt. Accepting them would make the archive hold content the model never saw.
7. **Late `system`: superseded by D86.** The first draft mapped it to `user`, which the core would then take for a user instruction.
8. **Tool-call arguments are compact JSON in the client's key order.** Strata parses arguments into an object before rendering, so spacing does not reach the tokens; key order does (M2). The generated turn's archived arguments are the upstream's own string, so S4 must reconcile a resent `tool_use` input against it by JSON value in order, not by bytes.

## D85: The Messages emitter (Phase 4B S3)

`palimnesis.protocols.messages_emit.MessagesEmitter` implements the `Emitter` of D83 for Messages clients. It is a pure state machine over the upstream's Chat SSE bytes. Contracts §16 lists its output; the choices the plan left open:

1. **`message_start` reports `input_tokens: 0`.** The bounded view's prompt is only known from the final Chat usage, which `message_delta` carries. Plan §2.5 lets admission send `message_start` early with a locally counted input; S6 decides that, and the emitter takes no count until then.
2. **Cut-off tool calls copy Strata.** A length stop inside arguments streams a closed `tool_use` block with unparseable JSON (Strata's streaming route), and the non-streaming body leaves the call out (Strata's non-streaming route). Both arms then show a client the same thing.
3. **One error event.** An upstream error chunk becomes `event: error` with the upstream's message verbatim (plan §2.3: Claude Code matches on wording). The relay's own error after it is suppressed, so a client never sees two.
4. **Lone surrogates** in generated text are sent as `\u` escapes, so the client always gets strict UTF-8, as Chat clients get Strata's own escapes.
5. **Comments pass through** and the proxy's keepalive is `event: ping`. HC5 and HP4 show Claude Code and Pi accept both, also before `message_start`.

## D86: Late system messages stay `system`; counter c5

Supersedes D84 item 7, and settles the counter fix D82 asked for.

- **The neutral form keeps `role: system` wherever the client put it.** Strata 0.1.54 renders a system message after the first position as a `user` message in place, on its Chat route as on its Messages route (M2: mr 91 = cr 91). So the upstream sees exactly what the Messages route would show, with no mapping in the adapter.
- **The core then treats it correctly with no new rule.**
  - A system message is never a user instruction (`turns.is_instruction`), so Claude Code's environment entry at index 1 starts no turn and hosts no excerpt.
  - It is fixed input, never masked (`view.builder`), like the leading system prompt. Claude Code's entry is about 2,000 tokens (HC3: +1,971 in `-p`), counted in F before acceptance.
  - Chat clients that send a late system message get the same treatment.
- **The pinned counter now copies two Strata steps the c4 counter refused** (`COUNTER_REVISION` c5):
  - `late_system_to_user` before the template, in rendering, counting and turn layout;
  - the `EFFORT` table: `high`, `max` and `maximum` render as `xhigh`; `off`, `minimal`, `disabled` and `false` as `none`.
- **Evidence.** The M2 parity corpus counts exactly with late system messages kept as `system` (`test_parity_corpus_counts_equal_recorded_count_tokens`), and two counter tests pin the equivalences. Cache accounting records the counter revision per call, so calls counted by c4 and c5 compare as a counter change, not an unexplained one.

## D87: The Messages archive route (Phase 4B S4)

`POST /v1/messages` is archived like Chat (contracts §3, §16). The pieces:

1. **`protocols.MESSAGES`** registers the S2 parser and the S3 emitter at `/v1/messages`. Its transport-only field is `stream`.
2. **Query strings.** A protocol may list the query strings it accepts. Messages accepts none or `beta=true`, which Claude Code and Pi always join and Strata ignores (M5). Any other is refused before acceptance, so nothing reaches the archive that the proxy cannot interpret. Chat keeps relaying its query unchanged.
3. **`count_tokens` is relayed unarchived** (O-4B-10). It is a correctness fallback: Claude Code never calls it (HC1). The count is Strata's for the client's own body, not for the bounded view.
4. **One protocol per session.** `ledger.accept` refuses a request whose endpoint differs from the session's first with `400 session_protocol_mismatch`. A session mixing protocols would mix neutral messages whose hashes come from different mappings.
5. **Hidden recall tools are Chat-only** (`ClientProtocol.hidden_tools`). A Messages session is never offered them and never fixes them, as position 1 says.
6. **The resend of a generated `tool_use` needs no new rule.** Reconciliation already compares generated tool-call arguments as JSON values (D10), so Claude Code's re-serialized input matches Strata's spaced argument string. The S4 test resends exactly that.

## D88: Errors on Messages (Phase 4B S5)

- **Upstream non-200 after acceptance** keeps its status and `x-should-retry: false`. The emitter's `upstream_error` re-envelopes the body for Messages clients; Chat's returns None, so Chat clients keep the upstream's bytes and headers.
  - The message is the upstream's verbatim. Claude Code's recovery matches on wording, such as the context-limit text (plan §2.3).
  - The type is the upstream's when Anthropic defines it (Strata's own `rate_limit_error` for `admission_full`, `invalid_request_error`), otherwise the status's. Strata's `unavailable_error` on a 503 becomes `api_error`.
  - A body that is not JSON becomes the message as text.
- **In-stream failures and the deadline** were already routed through the emitter (D83, D85): one `event: error`, never `message_stop`. S5's tests pin them on the Messages route, with the deadline before and after the stream starts.

## D89: Proxy admission (O4; Phase 4B S6)

`palimnesis.admission` implements contracts §5 and §8 for archive mode. Settings: `queue_capacity` (Q, 8), `header_wait_s` (H, 10 s), `keepalive_s` (K, 15 s), `retry_after_s` (15 s).

1. **Reserve before acceptance, wait after it.** A request reserves a queue place before `ledger.accept`, so a full queue answers 429 `queue_full` with nothing archived and `x-should-retry: true`. Duplicates and conflicts are still resolved in acceptance (plan §2.5). The slot is awaited inside the deadline window, so queue time counts against `D`, and a cancelled or expired waiter leaves the queue without dispatch.
2. **Slots from the upstream's facts.** `UpstreamFacts.slots` carries Strata's `total_slots`, read on every decision; unknown means one. Pythia stays at one slot (D83).
3. **One gate per streaming response.** `StreamGate` sends the 200 headers itself if nothing started within H, then the protocol's keepalive whenever K passes with nothing sent. The keepalive comes from the emitter (D83): a comment for Chat, `event: ping` for Messages, which Claude Code and Pi accept even before `message_start` (HC5, HP4). After an early start, a pipeline error response becomes the protocol's in-stream error event (`Emitter.error_body`), so the client never sees a second status line.
4. **The `/status` guard, one slot only.** Before dispatch, `UpstreamProfile.slot_probe` (Strata: `GET /status`) is polled every 0.25 s while it shows `busy` or `queued`. With several slots the upstream is meant to be busy, so the guard is off. A route that is missing or slow (1 s) turns the probe off rather than holding dispatch.
5. **Deferred:** the 60 s release ceiling that would mark the upstream unhealthy (contracts §8, still [defined]). The guard waits within each request's `D` instead. Command-line flags for Q, H and K are also deferred: the defaults fit all three harnesses' 300 s idle limits.
6. **Test fake.** `tests/fake_upstream.py` answers `GET /status` statically (`status_busy`, `status_queued`), outside `requests`, like `/props`.

## D90: Harness strings as adapter data; the tool-result instruction rule deferred (Phase 4B S7)

1. **Harness-written user prefixes are adapter data.** Each adapter declares them in `integrations/<harness>/synthetic_user_prefixes.json`, each with the probe that recorded it. Core reads their union as one flat list (`palimnesis.harness_strings`), which names no harness. `test_harness_synthetic_prefixes_from_adapter_data` keeps the two equal. OpenCode's two strings moved there unchanged, so OpenCode behaviour is unchanged. Claude Code and Pi declare none: no probe has recorded one (HC2–HC9, HP1–HP7).
2. **"A user message carrying a tool result is never an instruction": deferred, for lack of a case.**
   - In the neutral form a tool result is a `tool` message, never a user message, so a Messages user turn of tool results alone is no instruction already.
   - The rule would matter only for text blocks beside a tool result. Neither harness sends them: none in 269 captured Claude Code requests (103 tool-result turns), none in Pi's 8.
   - Making it hold would need a per-occurrence flag carried through the archive and every caller of `is_instruction`, which read message text. That is not worth building for a shape no harness sends.
   - If a capture shows one, the Messages split is where to mark it.
3. **Claude Code's interrupt marker is unverified.** No capture holds Claude Code's message after a user interrupts a tool call. `test_cc_interrupt_marker_hosts_no_excerpt` waits for one. Recording it needs an interactive run, which S13's live smoke can include. If it is a harness-written user message, its prefix goes into `integrations/claude-code/`.
4. **What S7 does cover:** a late system entry starts no turn (D86), and a tool-result-only user turn adds no instruction. Both are tested on the neutral split.
