# Decisions: working notes and Phase 3 acceptance (D69–D79)

[Index](README.md) · Material choices, their reasons and rejected alternatives; newest last.

## D69 — ho2 becomes development data after its gate (R32, R33)

- **Decision.** ho2 has been judged (R32), so its records and task modules may now be read for diagnosis, as development data. The next held-out gate needs a fresh set, written and committed before any run of the design it judges, as D62.3 did for ho2.
- **Why.** The development tasks no longer separate the arms: arm 1 and both a5 variants pass all five (R30). Every coding loss the project has measured is on held-out tasks (R25, R32). Diagnosing those losses needs their records.
- **Runs.** ho2's tasks also take development configurations: arm 4 variants (`--arm 4 --config a4-…`) and arm-5 matrix arms (`eval/tasks/run.py`, `RETIRED_SETS`). So do its needles (`needle.RETIRED_SETS`, added for R36), which keep the other held-out rules: real OpenCode, every question, a clean tree, no resume. ho is unchanged and runs only the frozen arms.
- **What it costs.** ho2 can no longer judge anything shaped by what R33 found.

## D70 — The current turn is collapsed last (R33-A)

`ViewPolicy.protect_turn`, `serve --protect-turn`; off by default, so the frozen arms keep their behaviour.
- **The rule.** A move masks oldest-first as before (D14), and its collapse then reaches only up to the current turn. The turn starts at the latest genuine instruction (`turns.is_instruction`), so OpenCode's synthetic follow-ups do not start one. If the view still exceeds `T`, the move stubs the turn's own largest tool results and reasoning in place (`ViewState.oversized`), never the newest group's. It collapses the turn's own groups, oldest first to `T`, only when the view still exceeds `H`. A view left between `T` and `H` is accepted.
- **Why.** In 90–91% of the mid-turn calls in arms 4 and 5, part of the turn's own work was already hidden (R33-A). A 300-line read collapsed the steps before it, and the model then invented their history and rewrote files from memory (R33-B). Assistant calls survive a stub but not a collapse.
- **Cost.** In-turn stubs change messages near the end of the prompt, so they cost little of the prefix cache. Views between `T` and `H` mean more frequent moves in long turns. Each such move is recorded as `oversized_output` or `collapse`; no new cause is needed.
- **Recorded** as `policy_version` `v2+turn` (or `v2+pinN+turn`).
- **Rejected.**
  - *Lowering `T` or raising `H` globally:* it changes every view, not the turn the model is working in.
  - *Keeping edit and write calls by tool name:* the core keys off protocol, never off a harness's tool names.

## D71 — Excerpt retrieval r2: no reasoning (R33-C)

`FtsExcerpts(retrieval="r2")`, `serve --retrieval r2`; r1 stays the default for the frozen arms.
- **The rule.** r2 is r1 with reasoning blocks left out of the candidates.
- **Why.** Excerpts returned the model's own unverified reasoning, including its inventions, under the header "historical evidence". On ho2 that included "an earlier task variant (spec A)" and a false column rule, and R30-C measured reasoning at 42% of excerpt items. D66 removed reasoning from grep for the same reason.
- **Unchanged.** Recall by address still returns reasoning.

## D72 — Working notes refreshed by the model at each collapse (R33-D, user choice B)

`ViewPolicy.notes_tokens`, `serve --notes TOKENS`; 0 (off) by default, so the frozen arms keep their behaviour.
- **The user's choice.** The options were:
  - (A) model-maintained notes through a hidden tool;
  - (B) a proxy-triggered refresh, in which the model writes the notes;
  - (C) a deterministic digest assembled by the proxy.

  The user chose B, because it is closest to the summary that made native compaction win in R33-D. This amends the plan's "deterministic compaction free of LLM calls" for this feature only: masking and collapse stay deterministic, and the notes are a fallible aid that the model writes.
- **When.** Only on a view move that advances the collapse boundary. Watermark-only moves do not trigger it.
- **The refresh call.**
  - The proxy sends one internal call, `<attempt>#notes`, before the client's call.
  - Its body is the request rendered under the state the move started from, plus `NOTES_PROMPT`. That is the previous view plus the new messages, so it extends the previous call's prompt and keeps the prefix cache.
  - If that would exceed `B_in`, the largest unmasked results are stubbed first, the newest included.
  - It uses the client's tools and settings, with the reserve as output limit and streaming on.
  - Reasoning is discarded. It runs inside the request deadline, and a client disconnect cancels it.
- **Commit.**
  - The text is cut at a line so the rendered block fits S.
  - It is stored in `notes_versions`, which is immutable and numbered per branch, and named by the view version (`ViewState.notes`).
  - A refresh fails on any of: an upstream status, a transport error, a 180 s timeout, a tool call, an error event, or no text. A failure is recorded and keeps the previous notes.
- **Rendering.**
  - The notes appear as one user-role block right after the last span note, headed: "your own working notes from earlier in this conversation; the user's messages win".
  - S is reserved out of the maskable capacity, and the block's tokens never count toward `H` or `T`, so the notes never move the watermark.
- **Accounting.**
  - The refresh call is `state_refresh`. The next call's first change is the collapse, so it is `collapse`.
  - A view whose first change is its notes is `state_commit` (contracts §10).
  - The view version's cause gains `state_commit`.
  - A restart never takes a refresh call as its base (`last_upstream_call`).
  - The rendering policy is recorded as `+notesS` in `policy_version`.
- **Cost.**
  - One upstream call per collapse move. R32 had 23–95 collapse moves per task; arm 1 made 17–90 compaction calls.
  - The prompt is mostly cached, so the cost is the generation: an estimated 15–40 s on Zeus (unmeasured until R34).
  - OpenCode waits up to 300 s for headers (harnesses.md). Other harnesses' header timeouts are unverified, which matters for 4B.
- **Rejected.**
  - *Refreshing in the background:* an agent loop rarely leaves the slot idle.
  - *Putting the notes in the system message:* every refresh would re-read the whole prompt.
  - *Putting the notes at the end of the view:* they would be re-read on every call.

**Review fixes** (protocol review and cache audit of `a3a2b8c`):
- **A fixed place.** The block sits right after the leading system message once anything is collapsed. After the last span note, a later collapse moved it past a kept message (a pin, or the current instruction), and that pair was unexplained.
- **Room for the notes.** The oversized and last-resort steps leave S free, and the block's whole message is charged, so committing notes never forces another move or a budget error.
- **Stubbing to fit.** A refresh that must stub to fit `B_in` stubs newest first, and only items whose stub changes something. Every `#notes` call is `state_refresh`.
- **More failure reasons:**
  - `incomplete`: the stream ended without `[DONE]`;
  - `upstream_error`;
  - `upstream_status:<code>`;
  - `too_long`: nothing fits the slot. Notes whose first line is longer than the slot are cut inside that line instead.
- **Outcomes.** A failure's reason is the refresh call's outcome, and a cancelled refresh is recorded `cancelled`.
- **A notes defect never fails the request.** Any error in building, storing or rebuilding returns the view without new notes. Fitting runs off the event loop and counts the header at a 6-digit version.
- **A rebuild that moves again** keeps what it evicted visible to retrieval.
- **Known limits:**
  - A collapse made by a hidden-tool continuation inside one visible response does not refresh; the next request's move will.
  - A refresh that cannot fit even fully stubbed is skipped without a row.
  - A refresh that stops on `length` is committed after the cut.
  - Refresh failures do not re-read the upstream facts; the visible call does.

Cache-audit fixes to D70 (from the audit of `487c2ad`):
- In-turn stubbing never records an item its stub leaves unchanged, and it orders by tokens saved.
- A previous call that cannot be re-rendered because the recorded view format differs is `view_format_change`, not `unexplained`. This also covers a `--stub` change across a restart. It applies only when `policy_version` or `stub_format` differ.

## D73 — Empty arguments match any archived arguments (R34 defect)

- **The defect.** In the R34 dev loop (ho2-t4, `a4-tr`, commit `a3a2b8c`), turn 5 was killed at 30 minutes while OpenCode ran a complete, valid `read` call (129 bytes of JSON, finish `tool_calls`). OpenCode resent the call with `arguments: "{}"` and an `aborted` tool result. D68 accepted `{}` only for arguments that never parsed, so message 715 diverged, and turns 6–8 were refused `409 history_divergence`.
- **The rule.** In a generated turn, a tool call resent with arguments `"{}"` matches whatever arguments were archived. `{}` is OpenCode's placeholder for a call it did not run, whether the arguments never parsed (D68) or the call was interrupted (here).
  - Upstream receives the client's copy, as for partials and D68.
  - The archive keeps the generated bytes.
  - Other differences still diverge, and booleans still never equal numbers.
- **Known limit.** An edit that blanks a call's arguments to `{}` is not detected. It can only remove information; it can inject none.
- **Rejected:** matching OpenCode's `aborted` result text in the core. The core keys off protocol, never off a harness's strings.
- **Affected runs.** The frozen arms carry the same rule as D68. R32 was not affected: none of its kills landed while a tool ran, and it had no 409s. The R34 ho2-t4 `a4-tr` run is void and reruns at the fix.

## D74 — Working-notes format n2: the cut keeps every section; notes taken from reasoning (R34-C)

- **The problems (R34-C).**
  - The model wrote 8–12K characters of notes against a 2,048-token slot. A line-prefix cut kept the first sections: of 36 committed versions, 8 kept *Current step and next move* and 2 kept *Dead ends*.
  - 6 of 42 refreshes ended with no text. In 5 the reasoning held complete notes with every section; the sixth had stopped after one section.
- **n2** (`--notes-format n2`, dev arm `a4-trn2`):
  - **Section order.** The prompt asks for *Current step and next move* second, after the objective.
  - **Length.** The requested length is sized to the slot: about 0.3 words per token, rounded to 100 (600 words at 2,048). n1 asked for about 1,200 words at any S.
  - **Reply, not reasoning.** The prompt asks for the notes as the reply.
  - **A cut keeps every section.** Each section keeps its heading and its first k non-blank lines, with the largest k that fits. When the text has no section headings, or the headings alone do not fit, it is cut at a line as in n1.
  - **Notes from reasoning.** A reply with no text is committed from its reasoning when at least three distinct section headings stand on lines of their own. The text starts at the first heading. It is recorded `committed` with reason `from_reasoning`; otherwise the refresh fails `empty` as before.
- **Why reasoning is acceptable here, when D71 keeps it out of excerpts.** D71 removed old reasoning that resurfaced as evidence for a later question. Here the reasoning is the requested notes, written for this purpose, and it is rendered under the same "your own working notes" header as notes written as the reply.
- **Rejected:**
  - Retrying an empty refresh. It costs another 30–60 s, and the reasoning already holds the notes in 5 of 6 cases.
  - Dropping whole trailing sections. A cut inside *Done so far* still kept useful lines in R34, and the order alone does not protect the last sections.
- **n1 stays the default**, as D70 and D71 left the frozen behaviour as the default. `a4-trn` keeps n1, so R34's runs stay reproducible. The view's `policy_version` names n2 (`+notes{S}n2`). Under n1, D72's "reasoning is discarded" still holds.

**Review fixes** (protocol review of the D74 draft):
- **No notes of bare headings.** When not even one line per section fits (one very long first line), n2 cuts at a line instead.
- **Headings.** Matching is case-insensitive and allows numbers, bold and the prompt's own long parenthetical. Bullets and sentences that start with a section's name are not headings.
- **Reasoning.** A draft needs three distinct sections with a line under them, so an echo of the prompt's section list is not notes. Of several drafts the last is taken.
- **D72 defects found in review:**
  - A slot smaller than the block's header looped forever in `fit_prefix`; fitting now returns nothing, and the refresh fails `too_long`.
  - A refresh stream with an event the parser rejects was recorded `cancelled` with no notes row; it now fails `malformed`.
- An unknown notes format is refused when the engine starts.
- **Known limits:**
  - Meta-text after a draft in the reasoning stays in the last section.
  - A reasoning-only refresh that stops on `length` commits what it has, as a cut reply does under D72.
  - A draft that fails `too_long` is not marked as taken from reasoning.

## D75 — Working-notes header h2: values quoted from the notes in full (R36–R38)

- **The problem.** With working notes, ho2's needles scored 105–107/120, against 119/120 without them (R37). Almost every miss is an answer cut short or empty.
  - Those stops are the model's own. They persist with drafting off, and at temperature 0 most of them go away (R38-C).
  - The notes make them more frequent: the facts are in view, so the model answers straight from its notes.
- **h2** (`--notes-header h2`, dev arm `a4-trn2h` = `a4-trn2` + h2) adds one sentence inside the notes header: "When you quote a value from these notes, write it out in full, exactly as recorded".
  - Replayed against Strata, it cut the early stops on the stopping prompts from 19/42 to 6/42, with the controls unchanged (R38-E).
- **Why a header sentence.**
  - The proxy sets no sampling parameters, and changing the harness's sampling would not be harness-neutral.
  - The header is already part of every notes block, so a fixed sentence adds no new cache invalidation; the block still changes only at `state_commit`.
- **Rejected:**
  - "Confirm before quoting" (`hint_check`). It did not help significantly (13/42), and it never led to a lookup.
  - Removing the notes from the answer turn. That loses the task gains the notes bring (R34–R36).
- **h1 stays the default**, as with D70–D74, so earlier runs stay reproducible. The header is counted when the notes are fitted to S, so h2 leaves slightly less room for the notes text.
- **Unverified:** whether h2 changes how the model uses its notes in coding tasks. R39 checks the needles and ho2-t3 and ho2-t4.
- **Review** (cache audit of the D75 draft): no unexplained prefix change.
  - Both callers of `notes_block`, the view and the fit, use the policy's header, and so does the refresh call.
  - h1 stays byte-identical to before.
  - `policy_version` is only stored and compared.
- **Known limit:** changing the header across a restart within one session is unsupported.
  - Notes are fitted once, under the header in use when they are saved. Rendered later under the longer h2 header, notes saved under h1 near the full slot can exceed S by the sentence's ~20 tokens.
  - A view filled to its limit can then fail its budget check.
  - The cache explanation stays correct: the pair is a `view_format_change`.
  - Runs fix the header for their whole length.

## D76 — pythia is the Strata host; Strata 0.1.54 is an equivalent build of the 0.1.48 pin

Decided by the user on 2026-11-03: Zeus is busy and cannot be used (D49 suspended), and tests and live runs move to pythia (`ssh pythia`). pythia's other services are stopped for the duration.

- **The host.** pythia: Linux, RTX 3060 12 GB, 46 GB RAM, at 192.168.1.173. It is bazzite (D48) reinstalled, confirmed by the user: same hardware, new OS, Strata and engine. Strata Terminal 0.2.8 with engine **0.1.54** (CUDA 13), the same `qwen3.8-flash-next-iq3_xxs` model, launched from a copy of its saved preset with `--max-context 32768` (`~/.local/state/strata/launch/iq3_xxs-32k.json`: `--kv int8`, `--mmap-experts`, `--expert-cache auto`, `--spec 4`, `--spec-min-p 0.5`, MTP), `--host 0.0.0.0 --port 8080 --parallel 1 --no-api-key`. The driver, proxy and harness run on pythia too, so live defaults name `http://127.0.0.1:8080`.
- **Equivalence shown before any run, as D48 did for Zeus.**
  - **Template:** `/props` `chat_template` sha `12827f24…`, equal to the pin.
  - **Counting:** all 210 recorded counting cases give the same counts, 0 differences: 174 literal-tag (p14), 10 normalization (p12), 6 NFC (p15), 20 `count_tokens` (p04).
  - **Generation defaults:** temperature 1.0, top_p 0.95, top_k 20, as recorded.
  - **Release:** the slot is idle 0.13 s after a client disconnects mid-stream.
  - **D39:** `/v1/status` `activity.requests` counts inference requests only (190 after the 190 probe completions; the 20 `count_tokens` calls are not counted).
- **What differs, and isn't verified.**
  - `build_info` is "Strata 0.1.54". The serve and engine code changed between builds; outputs are not compared, only counts.
  - Speed: prefill 690 tok/s and decode 37 tok/s on a 29K-token prompt with drafting on, against Zeus's 1,226–1,411 and 91 (D48) and the same machine's 708–770 and 52 as bazzite. The prompts differ, so the decode gap to bazzite is not attributed (engine, `--kv int8` and `--mmap-experts` are candidates). Live runs take about twice Zeus's wall time, and the 30-minute turn limit cuts more work.
  - The thinking cap's answer-room rule (D48.3) is not re-measured.
- **The pin.** The pin's `build_info` would refuse 0.1.54 and disable bounded views (contracts §1). `PIN.json` gains `equivalent_builds`, each build with its evidence; `Pin.accepted_builds` is the pin's own build followed by those, and the build check accepts any of them. Template hash and the `count_tokens` canary are still checked against the live server at every start.
  - Rejected: a separate `strata-0.1.54` pin and profile. The template and tokenizer are byte-identical, so it would duplicate the 12.8 MB tokenizer and fork the profile id that archives record, for no difference in rendering or counting.
  - Rejected: dropping the build check. A future build that changes rendering without changing the template text would then pass on the canary alone.
  - The manifest's sha changes, so `Pin.id` becomes `strata-0.1.48@79a81d4791cf`. It keys only the in-memory counting cache and the facts diagnostics.
- **Comparability.** Results stay per machine and per build (D48, D49). The R32 baselines and the R33–R40 development runs ran on Zeus; R25's bazzite runs used engine 0.1.48 on the old install. A held-out comparison on pythia needs its arms run on pythia.
- **Also fixed while bringing the suite up on Linux** (1,668 passed, 2 failed before; both pass now):
  - `test_fingerprint` took the "first live request" with `next(glob())`, whose order is filesystem-dependent; it now takes `min()`.
  - Capture wrote `request.json` and `response.json` in place, so a reader could load half a file; each is now written under a temporary name and renamed (contracts §12). `test_capture`'s wait now also waits for the response half.

## D77 — Held-out protocol for the working-notes arm on ho3, fixed before any run

Written on 2026-11-03, after R40 and before the fresh set `ho3` was run or read by the lead. The user left the choice between R40-C's two options to the lead: the arm goes to a fresh held-out set as it is, accepting the needle cost R36–R40 measured on development data, instead of first changing it for the sampling-driven early stop. Nothing here changes after held-out results are seen (plan §7). It mirrors D44 and D62.

1. **Configurations.**
   - **Arm 4 is `a4-d77`**: `a4-trn2h` (R39/R40) frozen under its held-out name. That is `a4-d43` plus D70 (current turn collapsed last), D71 (retrieval r2), D72/D74 working notes (2,048 tokens, format n2) and D75's header h2. It runs at the D77 commit or a later one that changes only `eval/` and docs.
   - h2, not h1: `a4-trn2h` is the configuration with all five ho2 tasks passing and 240 needles measured; R40 found h2 neither helps nor hurts recall live.
   - **Arm 1** is native OpenCode compaction through `--passthrough`, `limit.context` 32768, as D44.1.
   - `a4-d43` and arm 5 are not run: pythia's speed (D76) makes each arm-task pair cost hours, and neither is gated.
2. **Upstream and driver.** Strata on pythia (D76), engine 0.1.54 at `n_ctx` 32768 with the pin and canary passing, checked before every run (`--expect-n-ctx 32768`). Real OpenCode 2.1.4 runs the needles and tasks (D44.2), on pythia, with the D45 config; the driver, proxy and OpenCode run on the same host. Each task's two arms run on the same machine.
3. **Held-out set.** `ho3`: 12 histories × 10 questions (`eval/needles/heldout3/`, seeds 7400–7411) and 5 tasks `ho3-t1..t5`, `ho3-t3` the restart task. It was written by an author separate from the development work, who did not read R33–R40, D69 onward or the notes, view and recall code, with themes, seeds, wording and scenarios disjoint from dev, `ho` and `ho2`. It is committed before its first run.
4. **Gates, all at 32K on `ho3`:**
   - needles: `a4-d77` loose exact ≥ 85% over all 120, reported as D44.4 (count, Wilson and history-clustered bootstrap intervals, strict exact; every non-answer, early stop and timeout is a miss);
   - coding: `a4-d77`'s successes ≥ arm 1's over the 5 tasks, and `ho3-t3` passes under `a4-d77` with its key constraint (D45.8); one attempt per task and arm;
   - every `a4-d77` archive: the D44.6 inputs (0 over-budget inputs, 0 excerpt text visible to the client, `--explain` 0 unexplained, `transcripts verify` passing).
5. **The turn limit** stays 30 minutes of wall time per turn (D44, D45) for both arms. pythia decodes at about 40% of Zeus's speed, so more turns may be cut than in R25 or R32; kills are reported per arm.
6. **Reruns and defects:** as D44.7 and D44.8. No waivers.
7. **What a verdict means.** It judges `a4-d77` on fresh data at 32K on pythia. It does not revise R32's Phase 3B verdict on arm 5, and results stay per machine and build (D48, D76): no number here is compared with a Zeus run as evidence.
8. **Order.** Needles first (one `a4-d77` attempt), then the tasks, `a4-d77` then arm 1 for each task, t1 to t5.

## D78 — `serve` ships `a4-d77`

Written on 2026-11-05, after R41, at the user's go-ahead.

1. **The change.** `palimnesis serve` with no variant flags now runs `a4-d77`'s settings: `--protect-turn` (D70), `--retrieval r2` (D71), `--notes 2048` (D72) with `--notes-format n2` (D74) and `--notes-header h2` (D75). Everything else is unchanged from D43: fts recall, q1, x2, a3, transcripts on, stub s1, no hidden tools and no pinned instructions.
2. **Why.** On the fresh held-out set ho3 (R41), `a4-d77` passed every D77 gate.
   - Tasks: it solved 5/5 with all 15 constraints held, against native compaction's 4/5. It used 42% of arm 1's upstream calls and 53% of its prompt tokens, with no 30-minute kills.
   - Needles: 115/120.
   - On ho2 development data the arm also passed all five tasks (R39, R40), where `a4-d43`, the previous default, passed 2 (R32).
3. **Only `serve`'s defaults move; `Settings`' stay at the Phase 3 values.**
   - The eval proxy child builds `Settings` from a configuration's named fields. `a4-d43` and every arm-5 configuration name none of these five, so changing `Settings`' defaults would silently change what those frozen configurations run, after their held-out results.
   - Rejected: moving `Settings`' defaults and writing every field into every eval configuration. That rewrites configurations frozen before their held-out runs, and turns notes on in every fake-upstream test that builds `Settings` directly.
   - `tests/test_eval_d77.py` checks that `serve`'s defaults equal `a4-d77`.
   - `eval/tasks/run.py --arm 4` without `--config` still means `a4-d43`.
4. **Opting out.**
   - `--no-protect-turn` is new: the flag is now a boolean pair.
   - `--notes 0`, `--retrieval r1`, `--notes-format n1` and `--notes-header h1` restore the Phase 3 behaviour.
5. **Costs and limits.**
   - Every move that advances the collapse boundary sends one internal upstream call to refresh the notes; on ho2 these took 15–18% of task wall time (R40-B).
   - The arm was measured only at a 24,320-token input budget (32K `n_ctx`, 8,192 client output) on Strata. The 2,048-token slot is a fixed reservation, so at smaller budgets it takes a larger share of the view.
     - A pure-view probe at `n_ctx` 12,288 with an 8,192 client limit (input budget 3,840) collapsed a 34-message view to 15 messages and sent no refresh.
     - At 16,384 (budget 7,936) it collapsed to 48 of 59 messages and refreshed.
     - Neither was run live. The README advises `--notes 0` under about 8,000 input tokens; scaling the slot to the budget would be a new mechanism, not part of the measured arm.
6. **Harness neutrality.** Archive mode serves only OpenAI Chat Completions today; Anthropic Messages is rejected until Phase 4B. When Phase 4B adds Messages archiving, these defaults apply to it too, subject to that phase's own checks.
7. **Known residual.** R41's five needle misses were the right value with extra text, after the model returned to the coding task. That is development work for later and does not hold this default back.

## D79 — Phase 3 acceptance review fixes to the shipped configuration (R42)

Written on 2026-11-05. The protocol review, cache audit and paper-fidelity review of everything changed since S12 (`9482265`), run on the D78 configuration, found no blocker. Every should-fix is fixed test-first (`tests/test_phase3_acceptance_fixes.py` and the tests named below), and the contracts and docstrings are updated.

1. **Admission and the startup floor reserve the notes slot.**
   - The finding: admission counted the fixed input and the history's span residue but not S. Once a notes version exists, every view with anything collapsed renders it. So a request could pass admission and then fail the builder's final check, a `400` after acceptance (§2 "Per request").
   - The fix: admission adds S whenever there is older history; the floor is `F + min_recent + S + R + M`.
   - This refuses, before acceptance, a band of requests that `--notes 0` would admit. That is the reservation the builder already makes, now applied where the contract needs it.
   - Rejected: adding the committed block's actual size instead of S. That ties admission to the notes text, which changes with every refresh, so a request that fits now could stop fitting after the next refresh.
2. **Refresh-call accounting.** A `#notes` call is `state_refresh` only when its LCP reaches the previous call's generation start; otherwise it is analysed like any other call.
   - Re-checked on R41's archives from the tap's exact bodies (scratch `refresh_pairs.py`): 14 refresh pairs were labelled `state_refresh` without extending.
     - On each of the five `a4-d77` tasks, the first refresh is the first call carrying the transcript addendum, appended to the system message (`view_format_change`).
     - On the needles, 9 of 48 had stubbed earlier content to fit `B_in`: 8 tool results and 1 reasoning block.
   - All 14 are allowed causes, so R41's D44.6 inputs stand.
3. **Refresh failures are recorded completely.**
   - Valid JSON of the wrong shape is `malformed`, not `cancelled`: `test_a_refresh_event_of_the_wrong_shape_is_malformed_too`.
   - A refresh that cannot fit `B_in` even with everything stubbed sends no call and is recorded `over_budget`.
   - A refresh's 5xx, context-window 400 or transport error marks the upstream facts stale, as the client's own call does (§1).
4. **Smaller fixes.**
   - The plan's notes change only after the view naming them is built, so a rebuild that raises leaves the plan on the view actually sent.
   - `--notes` refuses negative values.
5. **Documented, not changed.**
   - The refresh stubs newest first, the newest group included, for its own call (§2).
   - Excerpts selected under r1 before an upgrade are reused (§11).
   - A second collapse inside one request's rebuild keeps the new notes without another refresh (`capabilities.md`).
   - `docs/papers.md` now records the Complexity Trap hybrid as related work, not the notes' source, and that reasoning is searched only under r1.
