# Decisions: Phase 3B (D51–D68)

[Index](README.md) · Material choices, their reasons and rejected alternatives; newest last.

## D51 — Composite visible turns (Phase 3B S2)

One visible response that spans several upstream calls is stored as one generation per call, with the hidden results between them as `internal_tool` rows (`view='internal'`). `ledger.load_archived` folds an attempt's parts and results into one composite `Archived`: text and reasoning concatenated, external calls only, `parts` in seq order. `_upstream_body` expands it back into each part with its own reasoning and calls, and each result, as separate view items with their own seqs.

- **Partials.** OpenCode flattens a broken composite as all reasoning, then all text, of what it received (H1 c), so `transcript.flattened` checks the resend against that form of the stream prefix. The upstream render keeps stream order: parts fully received keep their calls and results; the part where the cut falls keeps reasoning and text up to it and no calls.
- **Superseded attempts** fold their own results, so a cancelled composite the client dropped leaves nothing behind upstream. This closes the D13 carry-over for hidden rows.
- Rejected: a separate visible occurrence plus a map to the parts. It needs to know at the first token whether a response will continue, and changes storage for every response.

## D52 — Stream assembly (Phase 3B S1)

`palimnesis.assemble.ChatAssembler` turns one or more upstream calls into one client stream. Deviation from the plan: external tool calls stream as they arrive, renumbered, rather than buffered until complete. Calls are classified at their first delta, which always carries the name (§12.1), so nothing needs holding back; a length stop inside an external call's arguments behaves as in Phases 1–3. A single call with no hidden call is relayed byte for byte.

## D53 — Mixed calls

A call with hidden and external tool calls: the hidden ones are answered and archived at once, the external ones go to the client, and the response ends with `tool_calls`. The next request renders the part, then every result in the order of the part's calls, hidden ones among the client's: the pinned template pairs results with calls by position (corrected after the 3B review). Text after a hidden call is visible text of that part (S0 delta 1). A hidden call cut off before its result is never rendered, and a failed answer the client saw nothing of (only hidden calls) blocks neither a retry nor a next turn that omits it.

## D54 — Hidden tool schemas fixed at the first mask

The schemas (`recalltools.schemas`, from the registered `t1`/`t2` descriptions) are fixed per session by a `hidden_tools_fixed` event at the first view that hides anything, together with the addendum, and appended after the client's tools. They are counted as fixed input before acceptance. Their arrival is `tool_change` (plus `view_format_change` when the addendum arrives with them); the re-render after a restart adds the fixed tools back. A client tool or history call with the `palimnesis_` prefix is refused before acceptance (§3).

## D55 — Limits, the length stop, and streaming only

- Per response: 4 continuations, 8 hidden calls, results within a quarter of the input budget (2,048 tokens per recall, 1,024 per search or catalog page). A call over a limit gets "limit reached"; another hidden call after that ends the response with `length`, as does too little allowance (contracts §7). Removing the tools or switching to `tool_choice: "none"` for a final call was rejected: the tools render before the system prompt, so either re-reads the whole prompt.
- Every hidden call has a result before the response ends, so no later render holds a dangling call.
- **Streaming only.** Hidden tools are not offered to non-streaming requests. OpenCode always streams; a non-streaming assembly path would be a second relay for no current client. Recorded as a known limit.

## D56 — Allowance cap

`A = min(client limit, 24,576)`, with R still 8,192 per call. Continuations start only with at least 1,024 tokens left (probe P2: below that Strata gives thinking no budget). The shipped OpenCode config's `limit.output` rises to 24,576 with arm 5 (O-B3).

## D57 — Recall by address (`palimnesis_recall`)

`id` resolves through `addresses.resolve` in the session's scope and must name an occurrence on the session's branch. Unknown and ambiguous ids return errors with suggestions, never content. `§A.N` returns a code-point range of block N: the header gives the range, total length, the block's SHA-256 and `next_offset`, and pages reassemble exactly; lone surrogates show as U+FFFD (D38.1). `§A` alone returns the only block, or lists the blocks without content. Every result fits its token cap; a cap smaller than the header is an error, `no_room`.

## D58 — Search (`palimnesis_grep`)

- **Text mode:** each whitespace-separated word becomes an FTS5 phrase of its unicode61 sub-tokens, joined with AND, so model text is never FTS syntax. Hits narrow to the line of the first matching phrase.
- **Regex mode:** RE2 (`google-re2` 1.1.20251105), patterns of at most 512 characters, 8 MiB of RE2 memory, 32 MiB scanned per call, cancellation checked between blocks, and no fallback dialect. `log_errors` is off, so a rejected pattern, which is model text, never reaches the logs.
- **Scope:** `hidden` (default: the blocks the current view no longer shows, `recall.candidates`) or `all`. System messages and hidden results are never searched.
- **Pages** of 10 hits with address, seq, role, kind, line range and a snippet of at most 200 characters. The cursor binds the branch, the query and the archive cutoff, so pages stay stable as the archive grows; a foreign cursor is an error.

## D59 — Catalog pages as tool results

`palimnesis_catalog` returns `catalog.first`, `next` or `page` (20 entries of at most 48 tokens). Pages are ordinary tool results, so the catalog slot P stays 0 and navigation never invalidates the prefix (D20.3 kept).

## D60 — Hidden results stay out of recall's own inputs

Hidden results are copies of archived text: they are never full-text indexed, so neither excerpts nor `palimnesis_grep` find them. They are archived as `internal_tool` rows, shown in transcripts flagged `internal`, and masked like any tool output once out of view.

## D61 — Visible usage

The client's usage reports the last call's `prompt_tokens` and cached tokens, and `completion_tokens` summed over every call of the response. Each call's own usage stays in its `upstream_call` event.

## D63 — Stable in-progress transcript path, turn 0 marked (R25-E, O-B5)

Decided by the user before the 3B baseline (O-B5), so arm 4 runs with it. Amends D34.

- The in-progress turn is published as `turn-NNNN.md` from the start and replaced as it grows; when it seals it is rewritten once under the same name. R25-E found 6 stale-path errors and about 16 recovery listings in one task from the old `turn-NNNN.pK.md` names.
- To keep D34's crash guarantee, `manifest.json` lists only write-once files and names the in-progress turn as `live`. Publication order: write-once files, the manifest, the live turn, the index. `verify` reads the live turn and checks its payloads against the archive like any other.
- Turn 0's index line reads "system prompt: already in your context". In ho-t3 the model read that file 6 times.
- The format id stays `t1`: transcripts are a derived projection, rebuilt from the archive.

## D62 — Held-out protocol for Phase 3B, fixed before any 3B run

Written on 2026-10-26, before the development matrix ran and before the fresh held-out set (`ho2`) was used. It mirrors D44, and nothing here changes after held-out results are seen.

1. **Configurations.** Arm 5 is `a5-d64`, the matrix arm frozen by D64 after development selection (docs/affordances.md rule), at the D64 commit or a later one that changes only `eval/` and docs. Arm 4 is `a4-d43` with the D63 transcript fixes (O-B5). Arm 1 is native OpenCode compaction through `--passthrough`. Strata is Zeus (D49) relaunched at `n_ctx` 32768 with the pin and canary passing.
2. **Driver.** Real OpenCode 2.1.4 for every held-out needle and task, as D44.2. Arm 5 uses OpenCode `limit.output` 24576 (O-B3); arms 1 and 4 keep the D45 config.
3. **Held-out set.** `ho2`: 12 histories × 10 questions and 5 tasks (`ho2-t3` the restart task), written by an author separate from the development work, with seeds, themes and scenarios disjoint from dev and from the Phase 3 set, and committed before its first run (O-B1).
4. **Gates, all at 32K on `ho2`** (O-B6):
   - needles: arm 5 loose exact ≥ 85% over all 120, reported as D44.4;
   - coding: arm 5's successes ≥ arm 1's over the 5 tasks, and `ho2-t3` passes under arm 5; one attempt per task and arm;
   - arm 5 recall: invalid-id rate ≤ 5% over all `palimnesis_recall` calls;
   - every arm-5 archive: 0 hidden-recall leaks, plus the D44.6 inputs (0 over budget, 0 excerpt leaks, `--explain` 0 unexplained, `transcripts verify` passing). A leak is a hidden call (`palimnesis_*` name or hidden call id) or the whole text of a hidden result in what the proxy sent the client. Tool names the model writes in its own text, and archive text that reaches the client through a harness tool such as a transcript read, are mentions: reported, not gating, as D45.9.8 separates excerpt echoes from leaks. (Amended before any 3B run, 2026-10-26.) A fragment of a hidden result that the model quotes in its own text, such as a limit or argument-error message, is an echo: reported, not gating, as D45.9.8 counts a quoted excerpt header. The proxy relays only model deltas, so a relayed result would arrive whole. (Amended after the development matrix and before any held-out run, 2026-10-26, R29.)
   Arm 4 runs the same set for comparison; its results are reported, not gated.
5. **Reruns and defects:** as D44.7 and D44.8. No waivers.
6. **After the verdict (report only):** arm 5 at 64K on `ho2` h1–h6 and the 5 tasks; then arm 5 on the Phase 3 set (`heldout`, `ho-t1..t5`), labelled "seen set, not evidence".

## D64 — Arm 5 frozen as a5-Dp (S10, R30)

Selected on development data only (R28–R30). No `ho2` or `ho` data has been run or read.

1. **The arm.** `a5-d64` is `a5-Dp`: a5-D (`s0` header-only stubs, addendum `a1`, hidden tools `t2`) plus 4,096 tokens of pinned instructions (D65). It also carries D66's grep and D67's lookup budget, which have no switch. `needle.A5_FROZEN = "a5-Dp"`.
2. **The rule (affordances.md).**
   - No arm is rejected: every arm's invalid-id rate is at most 5%.
   - Ranked by retention over three repeats, a5-Dp and a5-D tie at 53.7/60, ahead of a5-Cp's 52.3.
   - The tie breaks on unnecessary calls: 5.0 for a5-Dp, against 52.3 for a5-D.
   - a5-D without pins is not a candidate: R29 showed it loses a typed rule that leaves the view (dev-t2 C2), and the user chose the fixes before D64.
3. **The tasks agree.**
   - a5-Dp passed 5/5 development tasks and held 15/15 constraints, as arm 1 did.
   - It used 4.95M prompt tokens against arm 1's 5.26M, and 46 min of wall time against 63 (R30-A).
   - a5-Cp also passed 5/5, at 2.3× arm 1's tokens.
   - The tasks are a check on the rule, not part of it: one attempt each, development data.
4. **Held-out runs** use the D64 commit or a later one that changes only `eval/` and docs (D62.1). Arm 4 stays `a4-d43`, with no pins. It takes the `serve` defaults for stubs, tools and pins, so when S12 changes those defaults, `a4-d43` must name `s1`, no hidden tools and pins 0 itself. `test_arm_4_proxy_settings_are_unchanged` guards this.
5. **Shipped defaults wait for the gate.** `serve` keeps Phase 3's defaults:
   - `s1` stubs;
   - no hidden tools;
   - `--pin-instructions 0`.

   The shipped `integrations/opencode/opencode.json` keeps `limit.output` 8192. These defaults change together at the phase-3b tag (S12), and only if D62's gates pass:
   - `serve` defaults to a5-Dp as a whole;
   - `limit.output` rises to 24576.

   The output limit is safe only with the hidden loop, which caps each upstream call at R = 8,192 (D56). The user chose this order on 2026-10-27.
6. **Known limit carried into the gate.** Excerpts still rank the model's reasoning: 42% of excerpt items in R30's task archives, and first in 31 of 67 selected blocks (R30-C). Changing that would change the arm under test, so it stays as frozen and is reported with the held-out results.

## D65 — Short user instructions stay in view (R29, before D64)

Decided by the user after the development tasks (R29-E). Every arm-5 miss lost a rule or note the user had typed, while arm 1's compaction summary kept them all.

- `ViewPolicy.pin_tokens` is set with `serve --pin-instructions TOKENS`.
  - Default 0, which is off: arm 4 and the Phase 2–3 views are unchanged.
  - The arm-5 development configurations set 4,096.
- **What pins.** A user message that is an instruction (`turns.is_instruction`) and whose own content is at most `PIN_MESSAGE_TOKENS` (1,024) is pinned. Synthetic prompts never pin, and an attached excerpt block never counts.
- **Where pins go.** At each collapse move, pinned messages behind the new boundary stay verbatim in place, newest first, while their total fits `min(pin_tokens, input_budget // 6)`. They split span notes as kept messages already do. The rest are absorbed, oldest first.
- **Cache stability.** The kept set changes only with a collapse move, so the cause is recorded as `collapse`. A message absorbed once stays collapsed, and a rebuild from the persisted state is identical.
- **Last resort.** If the view still exceeds the input budget, the collapse absorbs pins as well. Pins never cause a budget error.
- **Cause.** A move that only absorbs kept messages, pins included, is recorded as `collapse` (cache audit).
- **Known limit: the collapse search can overshoot.** The search assumes the view shrinks as the collapse grows, and pins break that: each pin splits a span, so the total can rise along the candidates.
  - In the audit's 1,822 pinned collapse events, the binary search always chose the same boundary as a linear scan.
  - At worst it collapses deeper than needed; the result is persisted, so it cannot unsettle the cache.
- **Cache cost.** Measured over random sessions in the audit, pins at 4,096 against none: the prefix lost per call was −8% at 24,320 and +5.6% at 8K. Pins split the collapsed region, so most later collapses rewrite only the last span note.
- **Rejected:**
  - *Pinning every user message*: unbounded, and a pasted log is not a rule.
  - *Listing opening words in the stub*: the model would still have to recall, and R29 shows it does not when the need is implicit.
  - *Waiting for Phase 4A*: its pinned state is model-maintained and arrives after the 3B gate.
- **Relation to Phase 4A.** This is the deterministic floor of Phase 4A's "constraints"; 4A's state remains planned. Needle facts that sit in a short user message are now in view, so needle reports separate answers found in view from answers found by recall.

## D66 — Grep never searches reasoning (R29)

`palimnesis_grep` skips `reasoning` blocks in both scopes; `palimnesis_recall` still returns them by address.
- **Why:** the model's unverified reasoning, returned as a search hit, reads as evidence. In R29 grep returned the model's own inventions:
  - "golden", "legacy_slugs" and "zero-width" in dev-t2;
  - the code `B7` in dev-t5.
- **Precedent:** this follows D60, which keeps hidden results out of recall's own inputs.
- **Scope:** excerpts (A1) still rank reasoning. That is unchanged here and reported in R30.

## D67 — Lookup budget per instruction; OpenCode's length follow-up is synthetic (R29)

- **The follow-up is synthetic.** `turns.SYNTHETIC_USER_PREFIXES` gains OpenCode 2.1.4's length follow-up, "Your last response hit the output token limit (stop reason: length).", recorded in `harnesses.md` beside the interrupted-response prompt.
  - It starts no turn, hosts no excerpt, and does not reset the lookup budget.
  - Each response still gets a fresh output allowance.
  - This amends 3B's S0 delta 3.
- **The budget.** `MAX_TURN_HIDDEN_CALLS` = 16 answered hidden calls per turn, from the latest instruction in the branch. It counts archived internal results after that instruction, less those a limit refused, plus the calls this response has already answered.
  - Sixteen covers every clean turn in R29: needle questions used at most 14 and clean task turns at most 8. It stops both runaway turns (29 and 59).
- **When spent,** each further call gets "limit reached: no more archive lookups until the next user message. Continue from what you have." It is refused under the existing rule, so a further hidden call in a later continuation ends with `length` (contracts §7).
- **Unchanged:** the per-response limits (D55, D56). Their 8-call count now also counts answered calls only, so a call refused for lack of result room no longer uses up either budget (protocol review).
- **Known limits:**
  - **Over-counting.** The count includes the archived results of a failed or abandoned attempt of the same instruction, which a retry never renders. That errs toward refusing early, never toward a runaway.
  - **Older archives.** Archives written before this decision number turns from OpenCode's length follow-up on, so their transcripts renumber on the next publication, and new excerpt headers ("now turn N") can number below older ones still in view. Rebuild them with `transcripts rebuild`. A rebuild leaves turn files that the new numbering no longer uses in place; they are not in the index or the manifest. New sessions are unaffected.
- **Grep cursors** carry version `grep2`, because the hit list changed (D66). A `grep1` cursor gets `bad_cursor`.
- **Rejected:**
  - *Ending the response with `stop` at the cap*: it would end an agentic turn mid-task.
  - *Counting per client request*: the dev-t2 spiral spread 29 calls over 175 responses.

## D68 — Unparsable tool arguments resent as `{}` reconcile (S11 defect, R31)

A defect found during the first S11 held-out run (D44.8, D62.5).
- **What happened.** On ho2-t1 under arm 5, the model emitted a `write` call whose arguments were not JSON (an unterminated string). OpenCode did not run it: it answered with its `tool.input-json` error and resent the complete turn with `arguments: "{}"`, as `docs/harnesses.md` records. Reconciliation accepted `{}` only for an incomplete turn, so the resend was `409 history_divergence`, and so was every later request in that session. Turns 6–8 never reached the model.
- **The fix.** Tool-call arguments that do not parse as JSON also match the client's `"{}"`. Arguments that parse, including a JSON string or array, must still be JSON-equal (contracts §2, `palimnesis.transcript`).
  - "Parse" means as JavaScript's `JSON.parse` does: `NaN` and `Infinity`, which Python's `json.loads` accepts, count as unparsable, and so does empty text.
  - **What upstream gets:**
    - A single-call turn: the client's copy, `{}` included, as for a partial tool call and as passthrough would.
    - A composite turn (D51): every part as the model saw it, the raw arguments included, with the hidden results in place.

    Both are protocol-safe: Strata keeps non-JSON arguments as text (#510).
  - The archive keeps what the model generated either way.
  - Tests, red first: `tests/test_transcript.py` (pure), `tests/test_composite.py` (composite) and `tests/test_unparsable_args_http.py` (fake upstream).
- **Tightened in the same review: booleans never equal numbers.** JSON equality used Python's `==`, under which `true == 1`, so an edited resend of `{"replaceAll": 1}` matched an archived `{"replaceAll": true}` and went upstream as history. That breaks contracts §2 ("edited or forged history → 409"). An integral float still equals its integer, because `JSON.stringify(1.0)` is `"1"`.
- **Unverified:** what OpenCode resends for arguments that parse but fail the tool's schema (an array, a string, a wrongly typed object). This rule does not cover them. If OpenCode also sends `{}` for those, the same lockout remains through that path. Probe before widening.
- **Not narrowed to OpenCode.** The rule keys off the protocol shape: a call the client could not parse comes back with empty arguments. A client that resends the raw text still matches exactly.
- **Eval fix with it (test-first).** `gate_inputs.reachable_records` treated any quoted `"gold"` as a needle answer key. In the same run the model wrote one in its own code, so the task's transcript looked like a leaked record. A file now counts only when its `"gold"` or `"answer"` field holds one of the run's answer keys, as the `"answer"` check already did.
- **Consequence (D44.8).** The whole ho2 needle set and every task rerun on the fixed commit, and the gates are judged on the rerun. The first attempt's data is kept and reported (R31).
- **The needle early stops are not part of this fix.** They come with the pinned layout (R31), which D65 specifies; changing it after seeing held-out results is what D62 forbids. a5-d64 stays as D64 froze it.
