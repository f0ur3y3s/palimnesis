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

## D91: Pi through the proxy; failed partials may be omitted (Phase 4B S8, S9)

1. **Chat subset: user content as text parts** (O-4B-9). Pi sends it with no switch to turn it off. Only `{type: "text", text}` parts are accepted, and only in user messages; other part types stay rejected. The parts join with `""` into one text block, as Strata joins them, so a part list and the same string hash and render alike. The client's own object still goes upstream unchanged when nothing is spliced.
2. **Excerpts on a part list** get the string form's `\n\n` separator inside the appended part, since parts join with nothing between them.
   - **Known difference (paper-fidelity review, S15):** the proactive-recall query (`recall/proactive.py` `_message_text`, D28) joins a message's text parts with `\n`, not `""`. It only matters for a message with several parts, and Pi sends one. It is left as is, because changing the query changes which excerpts are selected for `a4-d77`.
3. **O-4B-5 in reconciliation.** Any incomplete generated turn may be left out of a resend; it stays archived, superseded (`partial_superseded`). Before, only a client-cancelled or unseen one could be. OpenCode always resent server-failed partials, so it never meets the change; Pi always omits them (HP4.3). A complete turn left out is still a divergence.
4. **The Pi adapter** (`integrations/pi/`): the two providers, settings with compaction off, and the HP2 session extension. Setup is in `harnesses.md`.
5. **Replay tests over recorded bodies** (`tests/harness_replay.py`): the fault-server captures are replayed through the proxy, with each answer rebuilt from the assistant turn the harness resent next. Pi's default-settings captures are mapped through the two compat flags (`developer` to `system`, `store` dropped), which HP3 verified change nothing else.
   - `test_pi_chat_session_round_trip` and `test_pi_messages_session_round_trip` (HP3 tool loops) archive every request with no divergence.
   - `test_pi_retry_after_partial_policy` (HP4.3): the failed partial is superseded and turn 2 is accepted.
   - S8: `test_pi_manual_compact_request_is_divergence` (HP5) and the recorded Claude Code `/compact` both answer 409 and archive nothing; summary-shaped text in an ordinary turn is accepted.

## D92: Claude Code is backlogged

The user decided on 2026-11-05: "Claude code is closed source so let's skip supporting it", then "Put in the docs to backlog it". It is in `docs/backlog.md`, with what exists and what picking it up would take.

- **Out of Phase 4B:** S10 (the Claude Code adapter and wrapper), its rows in S11–S14, and O-4B-13 (Strata at 64K for Claude Code); pythia stays at 32K. `capabilities.md` lists Claude Code as backlogged.
- **Kept, because Pi uses them:** the Messages route, emitter, errors and admission (D84–D89). The Messages mapping copies Strata's own Messages route, including the billing-stamp pinning, which is harmless for other clients.
- **Kept as evidence:** the S0 probes and fixtures (`docs/probes/claude_code.md`), and the S8 test that replays Claude Code's recorded `/compact`. They test the Messages protocol with real bodies, not a supported harness.
- **Harness-neutral core is unchanged.** Pi and OpenCode remain the peers of position 4; the AST check still forbids harness names in core.

## D93: Reasoning and cache accounting on Messages; Pi live through the proxy (Phase 4B S11–S13)

1. **S11 and S12 needed no code.** On a Messages tool loop with thinking, a breakpoint moving every turn and a proxy restart, the upstream render equals the render of what the model generated, as Chat with its reasoning. That holds whether the client resends the thinking or leaves it out, since archived reasoning is restored (contracts §9). The earlier prompt is a token prefix of the next one across the restart, and `--explain` finds nothing unexplained (`tests/test_messages_reasoning_cache.py`).
2. **A new allowed cause, from the live run.** The first Pi gate session had one unexplained pair: a main call right after its own notes refresh.
   - The session's first masked view was also its first collapse. Protect-turn kept the whole current turn in view, so the collapse hid nothing visible and no notes block rendered.
   - The main call was therefore exactly the refresh call without its notes prompt. That change is the refresh ending, so it is recorded as `state_refresh`.
   - Reproduced deterministically with plain Chat strings, so it is not Pi-specific (`test_a_call_that_is_its_own_refresh_without_the_prompt_is_state_refresh`). R41's ho3 runs never hit it: their first masked views came before their first collapses.
   - Known cost, recorded and not changed here, because `a4-d77` is frozen: such a move still spends one refresh call while hiding nothing.
3. **S13, Pi live** (R43, `eval/probes/pi_live_smoke.py`). Pi 1.5.0 on Windows used the shipped adapter, a local proxy, and Strata 0.1.54 on pythia through an SSH tunnel, with a throwaway agent directory and home.
   - Smoke on Chat and on Messages: a tool loop, then a second turn in the same Pi session.
   - The gate: four large files read with a budget of 8,000, the first then deleted. Pi answered the code from history, then confirmed it with its own `grep` on the session's transcript directory.
   - Every archive: `--explain` 0 unexplained, `transcripts verify` passes, no failed attempts.
   - Pi is listed as supported on both protocols, with the transcript-file fallback (position 5).
4. **Driver lessons.**
   - On Windows, terminating `uv run` leaves its child server running and holding the archive lock, so the driver starts the server with `python -m palimnesis`.
   - Transcript projection is asynchronous, so the checks run while the proxy still serves, retrying `verify` until the projector has caught up.

## D94: A length-stopped turn may be left out of the resend (Phase 4B S14 finding)

- **Finding.** The S14 fault runs through the proxy (`hx_partial_length_*`, R44) showed that Pi 1.5.0 leaves an assistant reply that ended with `finish_reason: length` out of every later request, exactly as it does a failed reply. A direct run of the same scenario confirms it on both protocols. The archive held that reply as a complete turn, so Pi's next request was refused with 409 `history_divergence`, and the session could not go on.
- **Rule.** A generated turn whose attempt completed with the length stop may be omitted from a resend. It stays archived and is superseded, like an omitted failed partial (O-4B-5, D91). `Archived.truncated` carries it, read from the `turn_complete` event's finish reason. Any other complete turn left out is still a divergence.
- **OpenCode is unaffected.** It resends a length-stopped reply and adds its own follow-up (D67), so the reply still matches in place.
- **Tests:** `test_a_length_stopped_turn_may_be_omitted_and_is_superseded` (pure) and `test_pi_turn_after_a_length_stop_is_accepted` (HTTP). The four live runs pass after the fix.

## D95: Phase 4B reviews (S15): protocol review and cache audit, fixes and known limits

Two read-only reviews covered `phase-3..HEAD`: the protocol reviewer against contracts §3–§8 and §16, and the cache auditor against §10. Each fix below has a red test first. The S14 Pi needle driver's fake run found one more.

**Fixed**
1. **No bare close after a failed terminal commit** (protocol review). The relay encoded a batch's client bytes before committing it. On Messages that encoding already produced `message_stop`, and a failed commit then suppressed the error event. Bytes are now encoded only after the commit. The emitter's one error event is no longer suppressed by an encoded but unsent `message_stop`; the relay asks for one only when the response was not delivered. (`test_a_failed_terminal_commit_ends_with_an_error_event_not_a_bare_close`)
2. **Omitting a failed or length-stopped turn is narrowed to where Pi omits it** (protocol review). O-4B-5 and D94 had let any such turn be left out of any later request, so an edit deleting one a later request had resent was accepted. Now the turn may be left out only while it is the newest archived turn, or once an earlier request has already superseded it (`ledger.superseded_ids`). A client-cancelled or unseen partial may still be left out anywhere, as before. (`test_a_failed_partial_the_client_resent_may_not_be_deleted_later`, `..._length_stopped_...`)
3. **`message_start` names the requested model** (protocol review). A comment before the first chunk, which Strata sends during any prefill over 10 s, gave `"model": null`.
4. **Messages fingerprints are version 2** (protocol review): v1 with `cache_control` dropped at any depth. Chat fingerprints stay v1, unchanged.
5. **The addendum joins only a leading system message** (cache audit). It could join a mid-conversation system message, which renders as a user turn. That moved the prefix with no recorded cause and put addendum text in a user turn.
6. **A composite turn keeps its last part's length stop** (cache audit), so D94 holds for hidden-loop responses too.
7. **D93 is tightened** (cache audit). The refresh's notes prompt must start exactly where the main call's generation prompt does, so a main call that also lost later turns is not hidden as `state_refresh`.
8. **Two canary cases for counter c5** (cache audit): `mid_system_with_top` and `effort_high`, with counts recorded on 0.1.54 by the M2 probe. A Strata build that changes either mapping now fails the startup cross-check.
9. **`--explain --json` keeps the estimate label** (cache audit).
10. **A refresh that stubs an earlier result to fit B_in is `state_refresh`** (found by the Pi needle driver's fake dev-h1 run). The refresh renders before its move is recorded, so the stub had no cause. It predates 4B: `a4-d77` refreshes could meet it on OpenCode too.

**Known limits, recorded rather than built**
- **Supersede after hidden continuations** (cache audit 2). When a turn that ran hidden calls fails or hits the length stop and Pi leaves it out, the next call loses parts the previous call rendered, and `--explain` reports it as unexplained. Hidden tools are off by default, offered on Chat only, and failed their gates (R32). The case is reported loudly, never silently miscounted.
- **Headers within H before acceptance** (protocol review 4). The stream gate starts after acceptance, so a request whose view preparation and acceptance take longer than H sends headers late. Pi's header timer is 300 s.
- **A tool name split across stream pieces** would reach a Messages client only in part (protocol review 6). Strata sends names whole (§12.1).
- **The canary's own Messages mapping** (`facts.anthropic_to_render_args`) is a second mapping beside `protocols.messages`. It differs in `""` against `null` for empty assistant text; both render the same tokens.

## D96: Held-out set `ho4` written, unseen for Phase 7 (O-4B-11)

- **Written before any Pi evaluation run**, as O-4B-11 requires, by an author separate from the development work. The author did not read results from R33 on, decisions from D69 on, or the view, recall, transcript and notes code. The lead commits it by path and has not read its content.
- **Shape**, as `ho3`: 12 needle histories × 10 questions (`eval/needles/heldout4/`, generated by `eval/needle_gen_ho4.py`, seeds 7500–7511, `restart_before` placed as in ho3), and 5 coding tasks `ho4-t1..t5` with `ho4-t3` the restart task (key constraint C2).
- **Checks the author ran:** every task's reference solution passes `--check-reference` and every stub fails; the generator's `--check` reproduces the files byte for byte and confirms independence from dev, `ho`, `ho2` and `ho3`; all 12 histories load through `needle.py`.
- **Registered** as `heldout4` in `eval/needle.py` (held-out protections apply) and `eval/report.py`. The Pi needle driver refuses held-out sets. Phase 7 sets the protocol before any run, as D77 did for `ho3`.
- **Harnesses:** OpenCode and Pi. Claude Code is backlogged (D92).

## D97: Pi's empty replies; the first Pi needle run stopped (S14)

The first live development needle run through Pi (Chat, `a4-d77`) stopped at dev-h1 Q4. There were two findings.

1. **Pi drops an assistant reply with empty or whitespace text from its resend.** pi.md (HP3) records that Pi drops whitespace-only text and reasoning when it resends.
   - dev-h1's P2 got a reasoning-only reply, so Pi's next request left the whole message out. The archive held it as a complete generated turn, and the proxy answered 409 `history_divergence`, ending the history.
   - **Rule:** a generated reply with no text (or whitespace only) and no tool calls may be left out of a resend anywhere. It is superseded. Strata renders such a turn as nothing (#843, D41), so what the model sees does not change.
   - A reply whose whitespace-only text comes back as `content: null` beside its tool calls still matches.
   - OpenCode resends these turns and is unaffected. (`test_a_turn_that_renders_nothing_may_be_left_out`, `test_whitespace_only_text_resent_as_null_still_matches`)
2. **Answers cut after a token or two: the model, not Palimnesis.** dev-h1 Q2 and Q3 answered `fix/ledger-rounding-` and `9` with `finish_reason: stop` after 14 tokens, while the reasoning held the whole value.
   - Replaying the exact upstream body directly to Strata reproduced it: every effort level cut the answer, and so did user content flattened to strings.
   - The same body with the earlier cut answer corrected in history answered `9282` both times.
   - So once one answer in a conversation is cut, the model repeats the pattern in context.
   - The needle results record it as a model behaviour on Pi's sessions. It is not a proxy defect, and arm 4 is the only needle arm, so no comparison depends on it.
3. **The Pi coding-task driver** (`eval/tasks/run.py --harness pi`, `eval/tasks/pi_task.py`). Arm 4 is the shipped adapter through `serve` (`a4-d77`). Arm 1 is `--passthrough` with Pi's compaction on and `contextWindow` set to the true capacity. Real Pi ran dev-t1 on both arms and dev-t4 on Messages against the fake upstream; the hidden checks passed, and arm 1's compaction was recorded.


## D98: Two pre-existing races in the request lifecycle (S15 findings)

Two full-suite runs on pythia each failed one test that passes most of the time. Both are real races in the proxy, not test faults, and both predate Phase 4B's review fixes.

1. **A finished response no longer holds its session.**
   - **Finding.** `test_session_usable_after_mid_stream_commit_failure` failed 2 runs in 4 when run alone. With storage down mid-stream, the relay could not record its terminal event, so the session's active marker stayed set. The request stayed in `live` (the requests this process is relaying) until its handler returned, which is after the final body and the `delivery_completed` write. A client that resent at once arrived inside that window and got 409 `request_in_progress`, although its response had ended.
   - **Fix.** The handler drops the request from `live` just before the response's final body is sent. A marker outside `live` is abandoned as stale at the next request (contracts §11: "on the next request when its terminal event could not be written"). `attempt_abandoned` is terminal, so a later `interrupt` for the old request records only `delivery_failed`, never a second terminal event. In the normal path the terminal commit has already cleared the marker, so nothing changes there.
   - **Test:** the existing one, now 8 of 8 alone.
2. **Past the deadline, the record is the deadline's.**
   - **Finding.** `test_a_client_that_stops_reading_cannot_hold_the_upstream_past_the_deadline` failed 2 runs in 20 without item 1, and as often with it. When the deadline cancels a send that is blocked on a client that stopped reading, the send can fail with an error rather than the window's cancellation. That skipped `_expired`, so the generic path recorded `cancelled`, or else `delivery_failed` with no reason. The upstream was closed on time in every run; only the archived reason was wrong.
   - **Fix.** The generic path records through `ledger.expire` once the request's deadline has passed, and through `ledger.interrupt` otherwise. Both run after any terminal write already queued, so neither adds a second terminal event.
   - **Test:** the existing one, now 25 of 25 alone.

## D99: Pi's arm 1 keeps a quarter of a small window (S14 finding)

- **Finding.** The first live dev-t1 run on arm 1 (Pi's own compaction, `contextWindow` 32,768) never compacted, and failed 0/4.
  - Pi 1.5.0 compacts when the context passes `contextWindow − reserveTokens`, 16,384 here. It then keeps the newest `keepRecentTokens` (default 20,000) and summarizes what came before.
  - Below a window of 16,384 + 20,000 = 36,384, the threshold fires, but `prepareCompaction` finds no cut point and returns nothing. Pi emits no event and does not compact.
  - The session ran on toward the window. Pi then shrank `max_completion_tokens` to fit what was left, down to 1, and every turn from 4 on ended after one token with `length`.
- **Rule.** Pi's defaults stay wherever they can work. Below 36,384, arm 1 sets `keepRecentTokens` to a quarter of the window: 8,192 at 32K. After a compaction the context is then about the fixed input, plus the summary, plus 8K, under the 16,384 threshold. `--pi-keep-recent-tokens` still overrides it, and `result.json` records the settings used (`pi_compaction`).
- **Why not Pi's defaults as shipped:** at 32K they cannot compact at all, so arm 1 would measure a harness that runs out of context, not native compaction. D44.1 sets OpenCode's `limit.context` to the true window for the same reason: to measure compaction working.
- **Rejected:** lowering `reserveTokens`. Compaction would then start later, closer to the window.
- **The first dev-t1 arm 1 run** is kept in the records as attempt 2 and is not reported as arm 1's result. (`test_arm_1_keeps_few_enough_recent_tokens_for_compaction_to_run`)

## D100: Protocol review of D97–D98 (S15): three fixes and known limits

A read-only protocol review covered everything changed since D95's review: D97's omission rule and D98's lifecycle fixes. Each fix has a red test first.

**Fixed**
1. **A retry accepted in the old handler's tail stays live** (introduced by D98.1).
   - `live` is keyed by request id, and a retry of the same request runs under the same id. D98.1 released the id before the final body, so an identical resend could be accepted while the failed handler was still finishing. Then that handler's `finally` discarded the id under the running retry.
   - The retry's marker then looked stale. A second request on the session abandoned the running attempt and got past the busy check: two terminal events for the retry, and a broken per-session serialization (contracts §4, §5 `session_busy`).
   - Now `finally` discards only if the final-body send did not already release the id. (`test_a_retry_accepted_in_the_old_handlers_tail_keeps_the_session_serialized`; it failed 3 of 3 before.)
2. **D97 is narrowed as D95.**
   - An empty reply may be left out only while it is the newest archived turn, or once an earlier request superseded it. Pi leaves it out from the very next request, so Pi is unaffected.
   - Before, "anywhere" let a later request supersede a turn that an earlier request had resent. The turn's transcript file was already sealed and write-once, and would be rewritten after a restart.
   - A composite turn (D51) never counts as empty: its hidden calls and results render upstream even when its visible text is empty, so leaving it out would drop what the model saw. (`test_an_empty_reply_the_client_resent_may_not_be_deleted_later`, `test_a_composite_turn_with_hidden_calls_is_never_left_out_as_empty`)
3. **A complete reply the client left out is labelled complete** in transcripts, not `incomplete: superseded`. Its message keeps the `superseded` flag. (`test_a_complete_reply_the_client_left_out_is_not_labelled_incomplete`)

**Known limits, recorded rather than built**
- **A complete but undelivered empty reply** (a disconnect after its terminal commit) that the client then leaves out is still a 409 `history_divergence`. The unfinished-turn path handles it first. It is reported loudly, never accepted silently.
- **Whitespace text resent as `null` beside tool calls** is accepted (D97). The upstream gets the client's `null`, not the archived text. Whether the pinned template renders the two alike is unverified. If not, it is a prefix change at that turn, which `--explain` would report.
- **A deadline between the terminal batch and the final empty body** (the client stopped reading) can follow `[DONE]` or `message_stop` with a `deadline_exceeded` error event. This predates 4B. It needs a client that stops reading after the end of the answer and resumes within 2 s.
- **D98.2 judges the deadline when the exception is handled.** A disconnect just before D, whose cancellation a shielded write holds past D, is recorded as `deadline_exceeded`, not `cancelled`.
- **`_expired` sends through the raw `send`**, so an expired request with storage down stays in `live` until its handler ends. In that window a retry still gets 409 `request_in_progress`.
- **The hidden loop's error path after a final body.** If `_delivered` fails after `_hidden_terminal` sent the final body, the except path tries a second final body. The server refuses it; it logs and records a second `delivery_failed`. Hidden tools are off by default.
