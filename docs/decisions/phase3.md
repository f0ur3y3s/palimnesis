# Decisions: Phase 3 (D26–D50)

[Index](README.md) · Material choices, their reasons and rejected alternatives; newest last.

## D26 — Recall candidates: only what the base view dropped

Candidates for a new instruction's excerpts are the blocks the base view no longer shows: every block of a collapsed message, and the replaced block of a stubbed one (a tool result, or reasoning). The base view already includes this request's moves, so spans evicted by this very request are candidates (A1).

- **Excluded:** text still verbatim anywhere in the view, system messages and replaced context versions, superseded partials (they are not view items), ranges already quoted by an included excerpt block, and anything at or after the instruction.
- **Excerpt text is never a candidate.** It is never archived as a block, so it is never indexed.
- **Unmasked sessions** have no candidates and record `nothing_absent` without searching. Their upstream bodies stay byte-identical to the client's.

## D27 — Chunk-level full-text index

Migration 5 adds `fts_chunks` (contentless FTS5) and `chunk_map`. Every archived block is indexed in contiguous chunks of at most 24 lines and 1,536 code points, cut at a line end, else whitespace, else a safe cut. Chunks are indexed where blocks are, and existing archives are backfilled during the migration, which is the first migration that runs Python.

Rejected: ranking whole blocks. BM25's length normalization buries one dense hit inside a long tool output (`test_a_dense_hit_inside_a_long_block_outranks_a_sparse_hit`).

Adapted from Eunoe, which indexes 6-line windows of tool results with the tool call's description folded into each. Palimnesis's chunks are larger, so a hit keeps more of its context before the ±4 lines are added. They cover every block kind, including user text and reasoning, because A1 retrieves any absent span. Call arguments are indexed as their own blocks rather than folded into results. These sizes are development-selectable.

## D28 — Query policy q1

The query is built from the instruction's own text and never passed through as FTS5 syntax.

- Runs of `[\w.\-/:#@]` become terms of `unicode61` sub-tokens. A run that splits becomes a phrase.
- Code-like terms come first: runs that split, or contain digits, internal capitals or backticks (narrowed by D38.4). Plain words follow in order of first occurrence.
- Dropped: one-character words and a frozen stopword and filler list. "fix" and similar verbs stay, because IDF discounts common words.
- At most 32 terms. Long messages contribute their first 12,000 and last 4,000 code points.
- Each term is emitted as an FTS5 string joined by `OR`, so operators, prefixes, column filters and quotes in the text are only ever searched as words. A 2,000-case fuzz test against FTS5 confirms that.
- An empty query records `empty_query`. This covers "continue", "ok" and punctuation only.
- q2 (adding the previous instruction's terms for very short messages) is a development variant. It was built behind a setting, run in R20 and not chosen (D43).

## D29 — Retrieval r1

1. **Hits.** The top 64 chunks by BM25 among the candidate blocks. Ties break by newest source, then block index, start offset and chunk rowid, so the order is total.
2. **Relevance floor.** A chunk must contain one code-like term or two distinct terms (`below_floor`).
3. **Focus and context.** An item is the hit chunk plus up to 4 context lines a side, within its block. Overlapping or touching ranges in one block merge, keeping the best rank. Only an item over the cap is narrowed: to the chunk's matching lines, or its best line when those still exceed it, then regrown a line at a time, alternately after and before, within the chunk plus its context. (Text corrected in S12 to match the code; the code is unchanged since D38.)
4. **Item cap.** `min(512, allocation − block overhead)`. The overhead is the rendered block header, item header and footer, plus a fixed 40 tokens per item for provenance (`_HEADER_SLACK`). A long tool name can cost more than that; packing counts the real rendering, so the charge stays exact and only the cap is approximate (D38.5). Below 32 tokens the reason is `zero_allocation`.
5. **Packing.** Greedy in rank order: at most 8 items, 2 per source occurrence, at most 16 exact renders. An item that overshoots shrinks once by the measured excess and keeps at least 32 tokens; otherwise it is skipped. The charge never exceeds the allocation. If nothing fits, the reason is `no_fit`.
6. **Rendering.** Chronological by source seq (D30). `source_sha256` is the SHA-256 of the excerpt's exact text, so an item can be checked against the archive range `[start, end)`.

## D30 — Excerpt order within a block

Items render in the order (source seq, source block, start). Phase 2 sorted by turn, then occurrence id; ids are random, so items within one turn were unordered. No stored rendering changes, since Phase 2 never stored a block with more than one item.

## D31 — Retries select when no excerpt row exists

A retried or keyed request hosts excerpts when its last new client message is a genuine instruction with no `excerpt_blocks` row. This happens when a crash fell between acceptance and the excerpt commit, or when the source failed. Either no upstream call was made for it, or the call failed without output, so nothing the model saw depended on a selection and selecting then is safe. An existing row is always reused (`test_a_retry_after_a_crash_before_the_excerpt_commit_selects_once`).

## D37 — Transcript capability gate for OpenCode 2.1.4: passed

`docs/probes/opencode_transcripts.md` records the result.

- **What passed.** With the shipped config and no extra rule, OpenCode's read, grep, glob and shell tools reached a transcript directory outside the working tree and outside any repository, without prompts or denials, with and without `--auto`. The exact needle was returned in 15 of 15 lookups.
- **Why.** Every OpenCode agent starts from allow-all rules, including `external_directory`.
- **Fallback (O5) not needed.**

Consequences for the design:

1. **Bounded lookups only.** The model addendum must require a search followed by a bounded read. Unbounded `read` pages up to 2,000 lines or 50 KB, and it overflowed a 64K context in the probe.
2. **Point at the session directory.** The addendum names the session's own directory, never the transcripts root. OpenCode's grep searches hidden folders such as `.staging`.
3. **LF only.** Projection files use LF line endings. CRLF leaks `\r` into grep previews.
4. **Filesystem permissions are the only confinement.** OpenCode's shell tool bypasses `external_directory`, so permission rules confine nothing. Transcript privacy rests on filesystem permissions alone.
5. **The allow rule is optional.** Adding one (`external_directory` and `read` on `<root>/*`, placed last) changes nothing under the default agents. It matters only for agents configured with ask or deny.

## D32 — Transcript location and directory names

The root is `<db dir>/transcripts` by default, overridden with `--transcripts DIR`; `--no-transcripts` disables projection.

- **Git work trees.** A default root inside a git work tree disables projection with a warning. An explicit root inside one refuses startup.
- **Session directory names.** Each session's directory is `safe(id[:40]).lower() + "-" + sha256(id)[:12]`. Here `safe` maps anything outside `[A-Za-z0-9_-]`, dots included, to `_`, since Windows is case-insensitive and D4 allows device names.
- **What the model is pointed at.** `projector.session_dir(root, id)` is the only path the addendum names. Staging lives at `<root>/.staging`, outside every session directory (D37.2).

## D33 — Transcript format t1

**Turn files.** `turn-NNNN.md` holds one turn:
- a header line with turn, status, seq range and format;
- then each archived block once, between `[[§ALIAS.N · seq S · role · tool NAME (call_id) · kind]]` and `[[/§ALIAS.N]]`, escaped with the x1 payload escaping (reversible).

**Linked payloads.** A payload goes to `payloads/ALIAS.N.txt` when it is over 64 KiB or contains NUL, and to `.bin` when it is not valid UTF-8. The file holds its exact bytes. The turn file then shows a head/tail preview, the line count and the SHA-256.

**Index and manifest.**
- `index.md` has one line per turn (at most about 60 tokens, with a 100-character preview) and a header saying "search; do not read whole".
- `manifest.json` lists every published file with its SHA-256.
- Files are written as bytes, LF only (D37.3).

**Adaptations from the plan:**
- **`incomplete: failed`.** This status is added, since `attempt_failed` is neither complete nor cancelled.
- **Context versions.** A context version renders in the turn of its seq, flagged `replaces §X`, rather than linked from `turn-0000.md`. The link would have rewritten a write-once file.
- **When a turn is sealed.** A turn becomes write-once only once a later turn exists. Until then it is `turn-NNNN.pK.md`, and its unfinished linked payloads are `.pK` too. K counts the archive rows it renders, so it only grows and is deterministic.
- **Branch revision.** The generation is the cutoff seq. The index and manifest also carry a branch revision, because content can change at the same seq, for example when an attempt ends.

## D34 — Publication protocol

1. **Write each file safely.** Write to `.staging`, fsync, then `os.replace`.
2. **Order.** Write-once files first (sealed turns, sealed payloads), then the newest `.pK` files, then `manifest.json`, then `index.md`. Superseded `.p` files are removed best-effort afterwards.
3. **What a reader sees.** `index.md` names only complete files, so a reader always sees one consistent generation. After a crash, or a refused index replace, the manifest may lead the index by one generation. The manifest does not list `index.md`.
4. **Windows locking.** A `PermissionError`, as when a reader holds the index open, is retried 3 times at 50 ms. If it persists, the previous generation stays published and the next trigger retries.
5. **Rebuild.** `palimnesis transcripts rebuild SESSION` reproduces the projection byte for byte from the archive without inference, and repairs any write-once file whose bytes are wrong. It is unsupported while the proxy is writing the same session.
6. **Verify.** `palimnesis transcripts verify SESSION` checks every payload against the archive.

## D35 — Projector scheduling

- **One worker.** A single background thread on a read-only store connection. It coalesces per session, with the newest trigger winning.
- **Triggers.** It is triggered after acceptance and after each attempt ends, from the request's `finally`. It never blocks a response and holds no write lock.
- **Startup and shutdown.** At startup it re-projects the sessions that recovery touched. At shutdown it drains.
- **Logs.** Only counts and directory hashes.
- **Not built yet:** `eval/bench_projection.py` (publication latency and bytes per request) and the Phase 8 deletion cascade.

## D36 — The transcript-search addendum (a3)

- **Where it goes.** The proxy appends `a3`, which names the session's transcript directory, to the upstream copy of the first system message. When there is no system message, it prepends one. (Since D95.5, only a *leading* system message takes it; a later one renders as a user turn.) The archive and the client never see it, and it counts in F.
- **When it is fixed.** At the session's first view that hides anything (a watermark, collapse or oversized stub), stored as an immutable `addendum_fixed` event, and reused unchanged from then on, even if the transcript root moves. Cache-accounting rebuilds after a restart apply the stored text.
- **Before acceptance.** The budget check counts the addendum's tokens, so it cannot turn into a budget error after acceptance.
- **Deviation from the plan.** The plan fixed the addendum at the first bounded request; it is fixed at the first masked one instead.
  - Unmasked sessions stay byte-identical to the client, as Phase 2 promises. The addendum's claim that content may be hidden is only made once it is true.
  - The cost is one extra re-read of the whole head, system prompt and tool schemas (about 5K tokens for OpenCode), once per session. The pinned template renders the tools before the system text, so the addendum lands just before the system-root checkpoint and that checkpoint is lost. A watermark move already falls back to that checkpoint (R14), so this is the only extra cost. Measured by the Phase 3 cache audit: LCP 4,958 versus 4,976 for the move alone; estimated reuse 0 versus about 4,975 tokens.
- **Cache accounting.** A change of the addendum, including its first appearance or a later removal, is recorded as `view_format_change`. On the first masked request that is the first token difference, ahead of the move itself.
- **Disabling it.** `--no-transcripts` drops the addendum, recorded as `view_format_change`. Rejected: injecting it through harness configuration, which is harness-specific and would be archived as client content.

## D38 — Phase 3 review fixes

1. **Excerpts of text with lone surrogates.** JSON allows lone surrogates, and the archive keeps them as WTF-8. An excerpt now quotes each one as U+FFFD, which keeps offsets because it is one code point each. `source_sha256` still covers the exact archived range.
   - **Bug fixed:** the rendering could not be stored, and the request failed with a 500 on every retry.
   - **Fallback:** if an excerpt row still cannot be stored, the view move is committed alone and the request proceeds without excerpts (§13).
2. **Counted before acceptance:**
   - the addendum the session actually uses, i.e. the stored text when one is fixed, not the current root's;
   - the residue of any older history, as one worst-case span note.

   A request that cannot fit is refused before acceptance rather than failing after it, with the in-build check as the safety net. A sweep test drives requests near the budget edge and confirms it.
3. **A move made by the rebuild with a new excerpt block** (an R3 omission) is recorded and becomes the view the upstream call is attributed to.
   - **Bug fixed:** calls kept the base view number and were recorded `unexplained`, so `--explain` failed. The auditor's `long12b` scenario is now a regression test.
4. **Code-like terms narrowed (D28 amended).** A term is code-like when it has digits, `_`, `/`, `::`, internal capitals, a dot between two parts of 2+ characters, or backticks. Hyphenated and abbreviated prose (`follow-up`, `e.g.`) is plain, and a phrase of only one-character parts is dropped. A single code-like term can therefore clear the r1 floor alone only for a real identifier. Eunoe requires `min(2, wanted)` matched terms. r1 also admits one code-like term, because an error code or identifier is the strongest single signal in a coding session (papers.md).
5. **Packing counts the real rendering (D29.5 amended).** The block is counted with real provenance (alias, turn, role, tool name), so the charge is exact. A placeholder had let a long tool name throw away a whole selection. `over_allocation` remains as the defensive reason when a source returns more than its allocation.
6. **Never re-quote included text (D26).** Already-quoted ranges are compared with each item's span after context is added, not with the hit chunk.
7. **One decode per block.** `search_chunks` decodes each block once, however many of its chunks hit. A 4 MB tool output had cost 1.2 s.
8. **Warm-up sees the addendum.** Warm-up runs on the items the build used, addendum included.
9. **Carriage returns in transcripts (D33 amended).** File structure is LF only. A CR inside a payload is payload text and is kept, so lines of CRLF tool output end in CR inside their block, and `extract` splits on LF only. Linked payload files hold exact bytes, special tokens included; only inline payloads are escaped.
10. **"Byte-identical" means "except restored reasoning" (§9).** Unmasked sessions forward the client's body unchanged unless archived reasoning is restored for a client that omits it, as OpenCode does.

## D39 — The upstream is shared with another application

The user advised on 2026-10-25 that the Strata server on bazzite also serves another application.

- **Pacing.** Evaluation and live runs never saturate the slot. Each request waits for an idle slot (`/slots` or `/status`) and backs off rather than queueing behind foreign work. Runs are sequential and small.
- **Labelling.** Foreign traffic during a run is recorded. Latency, prefill and prompt-cache figures from such runs are labelled as possibly affected by it, not reported as clean. Foreign requests can evict cached prefixes, so measured reuse is a lower bound.
- **No restarts without asking.** The held-out step's restart with `n_ctx` 32768 (O2) would disrupt the other application, so it needs the user's go-ahead first. The fallback is emulating 32K with `--input-budget 24320` at 64K capacity, with native compaction (arm 1) given a matching `limit.context`, labelled as emulated.
- **Update (2026-10-25).** The user reports the other application has been stopped. Runs after this notice are labelled unaffected unless foreign activity is actually observed. The idle-slot check stays in place, and so does the rule against restarting Strata without asking.

## D40 — Restarting Strata at 32K for held-out runs

The user granted SSH access to bazzite (alias `bazzite`) on 2026-10-25 and asked for the server to be restarted at 32K for the held-out runs (O2).

- **How Strata runs.** Its own launcher (`~/.local/share/strata/terminal/0.1.49/strata.py launch`) serves the saved preset "IQ3_XXS 64K" (`~/.local/state/strata/launch/iq3_xxs-64k.json`): engine 0.1.48, `--max-context 65536`, `--kv int8`, MTP, `--expert-cache auto`, vision off, parallel 1, port 8080.
- **Restart command:** `strata.py launch --preset "IQ3_XXS 64K" --context 32k --parallel 1 --restart --no-tui --yes`. Its `--plan` dry run shows the running configuration in every respect except the context.
  - The override applies to that start only; the saved preset stays 64K.
  - `--parallel 1` is pinned because the launcher's default, "fit to card", could fit a second slot at the smaller context.
- **Rejected: the old `iq3_xxs-32k` profile** from 2026-10-23. It has vision on (CPU reader), no expert cache and, per `docs/probes/strata.md` §0, different defaults with the conversation cache off. Those differences would confound held-out latency and cache reuse with more than the context size.
- **Sequence.**
  1. Wait for the development evaluation, which runs on the 64K server, to finish. Nothing is restarted mid-run.
  2. Restart with the command above.
  3. Check that `/props` and `/v1/status` report `n_ctx` 32768, and that the build, template hash and canary still match the pinned profile. Bounded views turn off otherwise.
  4. Run the held-out evaluation.
  5. Restore with `strata.py launch --preset "IQ3_XXS 64K" --restart --no-tui --yes` and check that `n_ctx` is 65536.
- **Launch outside the SSH login.** bazzite sets logind `KillUserProcesses=true`, so anything started from an SSH login is killed when the login closes, even under `setsid nohup`. That is what stopped the 64K server at 06:07 EDT on 2026-10-25, during the development evaluation. Every launch is therefore wrapped in its own systemd user scope, so it outlives the login: `systemd-run --user --scope --unit=strata-<ctx> python/bin/python3 strata.py launch ...`. Stop with `strata.py launch --stop --preset "IQ3_XXS 64K"` before starting the next unit.
- **Observed and not changed:** the launcher warns that the server runs on the LAN with no API key ("anyone who can reach this port can use the model and its tools"). This is the user's existing configuration.

## D41 — The counter follows Strata's message normalization (R21-A, R21-B)

The development evaluation (R21) found two places where the pinned counter rendered something other than what Strata renders. Strata's `serve/frontend.py` is the evidence; `eval/probes/p12_strata_normalization.py` recorded live counts for both.

1. **Reasoning-only assistant turns.** Strata drops a completed assistant turn that has no text, no image and no tool calls, reasoning included (#843); the final message is kept. The counter now drops the same turns.
   - **Effect before the fix:** whenever the model answered only in its reasoning, every later request in the session drifted, by 83 and 16 tokens live. Three drifts in a row disabled bounded views for the whole process (D22.4).
   - OpenCode 2.1.4 sends "" for such turns, so this hits real sessions, not only the emulator.
   - In `layout` a dropped turn is a zero-length segment. The kept messages around it group as Strata renders them, so a tool run continues across it.
2. **Malformed tool-call arguments.** Strata keeps arguments that are not a JSON object as text under `"arguments"`, and maps empty arguments to `{}` (#510). The counter used to leave them as strings, which the pinned template refuses.
   - **Effect before the fix:** a call cut off by `finish_reason: "length"`, resent by the client, made every view build fail. The proxy then forwarded the whole history (D14.9), and Strata answered 400 on every later request in the session.
3. **D14.9 is unchanged.** A view defect still forwards unbounded. With the counter matching Strata, these two inputs no longer reach that path. Making the fallback refuse rather than forward would turn a counter defect into a hard failure for the user, so it is not done here.
4. **R21-C (upstream early stops) is not a proxy defect.** Answers that end mid-value or arrive empty match the raw upstream stream. With item 1 fixed they no longer cascade, so they now count as ordinary model misses. Their cause in Strata 0.1.48 is unknown.

## D42 — Turns the upstream renders as nothing, in the core (cache audit of D41)

D41 made the counter drop empty assistant turns. The cache audit of that change found that the core still treated those turns as rendered.

1. **A template rule, not a Strata branch.** `TemplateRules.drops_empty_assistant` declares that the upstream renders nothing for a completed assistant turn matching `profile.empty_assistant`: no text, no image, no tool calls; reasoning does not count. The core implements both values, and Strata declares `True`. The Strata counter uses the same predicate, so there is one definition.
2. **The view's recent window counts rendered tokens.** `min_recent` used to count a dropped turn's reasoning. A long reasoning-only answer could therefore fill the window by itself and leave the newest tool result stubbed, even though the window then rendered almost nothing. Dropped turns now count zero, so the view equals the one built without the turn.
3. **Dropped turns are never masked.** Stubbing their reasoning changed no tokens, yet it marked them `stub` or oversized and reported them in `evicted_now`. Their manifest form is now `verbatim`.
4. **Checkpoints.** The Strata cache model took every assistant segment start as a resume point, including zero-length ones, and they crowded the 6 slots. It now takes only segments that render tokens. Two message lists that render identical ids get identical checkpoints.
5. **`--explain` alignment.** When a collapse absorbs a dropped turn at the start of its run, the first differing token lies in the next segment, and the pair was compared at the wrong turn (`unexplained`). `_changed_segment` steps back to a zero-length segment just before that one only when its turn changed, so an edit of the next turn is still attributed there.
6. **Canary.** `prior_turn_thinking_only` (Strata: 61 tokens, recorded 2026-10-25) makes a server that renders empty turns (for example `STRATA_KEEP_EMPTY_TURNS=1`) fail the pin check at startup, instead of drifting per call.
7. **Accepted: a dropped turn's reasoning is not a recall candidate.** Recall covers what the view removed (D26), and the view never removes these turns. The model never sees them either, but that is the upstream's rendering, not the proxy's. A reasoning-only answer is still archived and projected into transcripts.

## D43 — Phase 3 variants frozen: q1, r1, x2, a3 (S10)

Selected on development data only (R20, R22); the held-out set has not been run.

1. **x2 replaces x1 as the excerpt renderer.** In R22, on the fixed proxy, x2 scored 58/60 in both runs and x1 scored 51 and 53. Pooled, x2 alone was right on 14 needle pairs and x1 alone on 2.
   - **The evidence is narrow.** 12 of the 14 are one history (dev-h6), where x1 sets off a cascade of early stops (R21-C) in both runs. Without dev-h6 the two are level (96 / 2 / 2 / 0). What R22 shows is that x2 avoids a reproducible failure; it does not show better retrieval or answers in general.
   - **Why choose x2 anyway.** The early stops are upstream behavior with an unknown cause, and x2 is the renderer under which they stayed rare (1 in 120, against 14 in 120). A1 also asks that retrieval scores not be read as currency, and x2's header says so: the current turn, and that a later turn supersedes an earlier one.
   - **Cost:** more lookups (37–39 against 19–32 per run) and a higher time to first visible content (p50 10.2–10.4 s against 6.8–7.2 s). The held-out report includes both.
   - x1 stays registered and selectable with `--excerpt-renderer x1`. Stored blocks keep their own rendering and `renderer_version`, so archives written under x1 replay unchanged.
2. **q1 stays.** In R20, q2 scored 46/60 against q1's 44, with bugs A and B still present. That is no evidence for the change, so the simpler policy stays.
3. **a3 stays.** a4 scored 37/60 in R20, against 44 for a3.
4. **q2 and a4 were not re-run after D41.** Their R20 results include bugs A and B. They stay selectable for later phases but are not part of the held-out configuration.
5. **The held-out configuration** is the default `serve`: q1, r1, x2, a3, transcripts t1, s1 stubs. The emulated 32K (`--input-budget 24320`) is development-only; held-out runs use Strata restarted at 32K (O2, D40).

## D44 — Held-out protocol for S11, fixed before any held-out run

Written on 2026-10-25, after D43 froze the variants and before any held-out history was generated or run. Nothing here changes after held-out results are seen (plan §7: "Freeze criteria before held-out results; do not waive a failed gate after seeing them").

1. **Configuration.** Arm 4 is `a4-d43`: the default `serve` at commit `ac87c8f` or a later commit that changes only `eval/` and docs. Strata runs at `n_ctx` 32768 (D40), and the pin and canary passed at 32K (4/4 cases, 2026-10-25). Arm 1 is native OpenCode compaction through `--passthrough`, with `limit.context` 32768.
2. **Driver.** Held-out needles and coding tasks run through real OpenCode 2.1.4 (O3), never the emulator. A generated history enters OpenCode through `opencode session import`; each question is then a real `opencode run --session` turn. OpenCode therefore builds and resends every request itself.
3. **Held-out set.** 12 histories × 10 questions (120 needles). Themes, seeds and question wording are disjoint from dev-h1..h6. The category skeleton is the same, so A1's coverage holds. The set is generated once and committed before its first run.
4. **Needle gate (O1).** Loose exact match (R19's definition) on arm 4 at 32K is at least 85%, observed over all 120 needles.
   - **What is reported:** the count, a 95% Wilson interval, strict exact, and a history-clustered bootstrap interval. Questions in one history are not independent.
   - **What counts as a miss:** every needle with no correct answer, including errors, early stops and timeouts.
5. **Coding gate (O1).** 5 held-out tasks (plus 3 development tasks, used only to check the harness), run once per arm.
   - **The gate:** arm 4's successes are at least arm 1's, and the restart task passes under arm 4.
   - **Task success** is the task's executable check, run after the session.
6. **Other gates for the tag:** on every held-out archive, 0 over-budget inputs, 0 excerpt text visible to the client, `--explain` with 0 unexplained pairs, and `transcripts verify` passing.
7. **Reruns.** A history or task is rerun from scratch only for an infrastructure failure outside the proxy: Strata down, foreign traffic seen by the D39 gate, or an OpenCode or driver crash not caused by a proxy response. Each rerun and its reason is recorded, and the first attempt's data is kept. A failure caused by the proxy counts.
8. **A defect found during held-out runs.** The run stops. After the fix, the whole held-out needle set and every coding task rerun on the fixed commit. Both results are reported, and the gate is judged on the rerun.
9. **64K (reported only).** After the 32K runs, Strata goes back to 65536. Arm 4 runs 60 needles (held-out histories h1..h6) and the same 5 tasks under both arms.

## D45 — S11 tooling: real OpenCode for needles and coding tasks

Written on 2026-10-25 while building the S11 tools, on development data only. No held-out history or task has run. D44 is unchanged; this entry records how the tools implement it.

1. **Needle driver** (`eval/needle.py run --driver opencode`, `eval/needle_opencode.py`).
   - Each history's import, up to but not including the Q1 text, becomes an `opencode session export` document. It enters an isolated OpenCode home through `opencode session import`. Every step is then one `opencode run --session` turn.
   - Records keep the emulator's per-needle fields, so `eval/report.py` reads both. They are labelled `driver: "opencode"`.
   - There is no tool cap; the emulator's 8 calls per question do not apply. A turn is killed after 30 minutes and counts as an error.
   - Each run also checks that the first client body equals the history and that its prior turns are archived as `client_import`.
2. **Messages go to `opencode run` on stdin.** As one argument, 2.1.4 on Windows keeps the quotes `CreateProcess` adds (`docs/harnesses.md`, OpenCode). Rejected: one argument per word. It works for short text, but pastes exceed the command-line limit.
3. **Session identity without the plugin.** The provider's `baseURL` is `palimnesis session url <history|task>-<config>-<tag>`. One OpenCode session therefore maps to one named Palimnesis session, which `transcripts verify` and `--explain` can address. Requests carry no `X-Palimnesis-Kind`; the proxy does not read it.
4. **Proxy settings.** The child runs the `serve` app with `serve`'s defaults (no `--input-budget`), except `deadline_s` 3600, as in the development runs. The reason: the D39 gate between the proxy and Strata holds a request while the slot is busy, and that wait counts against the deadline. This is the only difference from the `serve` defaults, and it is open for confirmation before the held-out run.
5. **The model's environment.** The model's shell gets PATH without the project's virtual environment, so it runs the system Python. The hidden checks use the same interpreter.
6. **Held-out histories** (`needle_gen.py --set heldout`, `build_heldout`). A separate builder with its own themes, word banks, file names, value formats and phrasing bank, on `build_history`'s skeleton.

**Not everything is disjoint**:
- The P1 deploy-log body comes from the shared `log_lines` templates, including the `2026-10-2x` timestamps and the probe, rollout, queue, reload, HTTP and GC lines.
- Some values are shared or drawn from overlapping ranges: the default pooler port 5432 named in the pooler turn, the 420-test size of the verbose integration run, the fixture read timeouts (`<1–9>.0s`) and write timeouts (60–90 s), and the fallback range for the target read timeout. Four held-out answer values (`15s`, `22s`, `28s`, `2.5s`) also occur as values in the development set, which the model never sees during a held-out run.

None of these is an answer, or the evidence for one. No four-word run of user, assistant, question or paste-wrapper text is shared (tested). `build_history` is untouched, so the dev files regenerate byte-identically (tested).
   - The held-out project tests use stdlib `unittest`, and Q7's command (`python -m unittest tests.test_<module>`) runs for real: it fails naming the constant and the requirement id, but not the required value.
   - The development histories' Q7 command is `pytest`, which the system Python lacks. Under real OpenCode, dev-h1 Q7 therefore failed in the smoke run. That affects development data only.
7. **Coding tasks** (`eval/tasks/`, `run.py`).
   - Each task is one OpenCode session of 8 turns in a fresh git repository. Constraints and an "already tried X, it failed because Y" note come in turn 1. Turn 2 is a full read of a 7–14K-token document; turns 4 and 6 are verbose runs of a ~10–12K-token passing suite. The proxy restarts before turn 5.
   - **Restart task:** ho-t3. Its key constraint C2 (how the command line writes its output) is stated only in turn 1, and is needed only in turn 5, which does not repeat it (tested).
   - **Arms:** arm 4 is `a4-d43` with OpenCode's shipped settings (`compaction.auto` false, `limit.context` 1,000,000). Arm 1 is `serve --passthrough` with `compaction.auto` true and `limit.context` 32768. Both go through the same tap and gate.
   - **Success** means every `test_f_*` method of the hidden check passes. The check is copied in only after the session and run with the system Python. **Constraint `C<N>` holds** when every `test_c<N>_*` method passes. Each check passes on the task's reference solution and fails on the stub (tested).
8. **Gate inputs recorded per run.**
   - `--explain` exit and unexplained pairs, `transcripts verify`, and count drift against the pinned counter.
   - Upstream inputs over 24,320 tokens.
   - Client-visible excerpt text: excerpt markers in any archived client request.
   - The proxy log's "views disabled" and "forwarding unbounded" lines.

9. **Amendments after the independent review (2026-10-25, before any held-out run).**
   1. **Check scoring.**
      - The hidden check runs under a small runner that writes one outcome per test id as JSON, so stderr output cannot break the result.
      - The expected `test_f_*` and `test_c<N>_*` names are read from `HIDDEN`. A test with no outcome counts as failed.
      - A check that outlives 300 s fails with `check_timeout`; `--explain` and `transcripts verify` still run.
   2. **The needle gate's denominator.**
      - Every question that never ran gets a miss row with `not_run` and the reason: an import failure, an unfaithful import, a driver exception, an abort, or a failed Strata check.
      - With `--set heldout`, `report.py` asserts 12 histories × 10 questions, counts any missing needle as a miss, and fails the gate on a duplicate row.
   3. **Attempts** (`eval/attempts.py`).
      - Each driver or runner invocation is a new attempt: `RUN/records/attempt-NNN/` for its records, and `RUN-ws/attempt-NNN/` for its workspaces, OpenCode homes and transcripts root.
      - An attempt directory is never reused or removed. A rerun of an id under the same configuration needs `--reason`. `--resume` is refused by the OpenCode driver.
      - `RUN/attempts.json` records each attempt's number, ids, reason, timestamps, status, and its aborts and infrastructure failures.
      - The report designates the latest attempt per history or task (`--designate` overrides) and lists each superseded attempt with its reason.
      - In the shared proxy and tap code:
        - stop files and proxy logs are unique per start (logs are appended, never truncated);
        - tap bodies are numbered after any already in the directory;
        - an existing `meta.json` is kept under `earlier`.
   4. **History-clustered bootstrap.** 10,000 resamples of histories with replacement, `random.Random(44)`, loose exact over all needles of each resample. The interval is the 2.5th and 97.5th percentiles, with linear interpolation between order statistics. It is reported with the count, the 95% Wilson interval and strict exact.
   5. **Nothing to read the answers from.**
      - Records (`questions.jsonl` with gold, `calls.jsonl`, bodies, streams, `meta.json`, `result.json`, the archive) live only under `RUN/records/`. The transcripts root is given to the proxy explicitly, under `RUN-ws/attempt-NNN/`.
      - A task's workspace is copied into the records tree after the session, and its hidden check is written into the copy only.
      - `import.json` is deleted once imported; its SHA-256 is recorded.
      - Each run lists any record, answer key or hidden-check text found under its workspace tree. A test asserts there is none.
   6. **One task, one session.** A first turn with no session id, or a later turn that reports another session, aborts the task as an infrastructure failure.
   7. **Restart gate.** ho-t3 under arm 4 passes only when every `test_f_*` and every `test_c2_*` passes.
   8. **Gate inputs.**
      - **Over budget:** every arm-4 upstream body is counted with the pinned counter (`tokens.default().count_messages`) against the input budget for the expected `n_ctx` (24,320 at 32K).
      - **`--explain`:** it must exit 0, report 0 unexplained pairs, and report as many pairs as there are upstream calls after each session's first. A crash or a mismatch fails the input.
      - **Excerpt leaks:** scanned in every client request and every proxy response (front tap), the OpenCode export, and the transcript files. A leak is the exact text of a stored block (`excerpt_blocks.rendered`), or of one of its items from `[[excerpt …]]` to `[[/excerpt]]`. Text that only quotes an excerpt marker is counted as an echo, which is reported and is not a gate failure.
   9. **Provenance.**
      - Every run records the git commit and whether the tree is dirty; held-out needles and tasks refuse a dirty tree.
      - Strata's `/props` `n_ctx` and build are read before and after each history and task. A run refuses to start, or aborts, unless `n_ctx` equals `--expect-n-ctx` (default 32768; 65536 for the later 64K runs).
      - Held-out needles refuse any configuration other than `a4-d43`, and refuse `--questions`.
   10. **Import fidelity is enforced.** A first client body that differs from the history (beyond the `reasoning_content: ""` OpenCode adds), or prior turns not all archived as `client_import`, is an infrastructure failure under D44.7, and the history stops there. `needle.py preflight --set heldout` pushes every import through real OpenCode against the fake upstream (no proxy, no model, no Strata) and checks fidelity.
   11. **Aborts** in the task runner are `aborted: <reason>` in `result.json`, with exit code 3, and no check runs.
   12. **`deadline_s` 3600 is confirmed** (D45.4). Each upstream call records its upstream time, from dispatch after the gate to the end of the stream. Calls over 600 s are listed.
   13. **Proxy rejections are visible.** A front tap between OpenCode and the proxy records the proxy's own status and any in-stream error per request. A failed front call while every upstream call succeeded counts as a proxy rejection.
   14. **Reporting.**
      - `a4-d43` is in `report.py`'s `ORDER`.
      - `report.py --coding RUN` prints each run's constraint adherence next to the stub's own check result, followed by the D44.5 verdict: arm 4's successes against arm 1's over ho-t1..t5, plus the restart gate. A missing or aborted run counts as a failure.
   15. **Environment allowlist** (`oc_harness.ENV_ALLOW`, details in `docs/harnesses.md`). `APPDATA` and `LOCALAPPDATA` stay real, because the system `python` (Python install manager) keeps its installs there. The hidden check's interpreter is resolved on the cleaned PATH, because Windows resolves a bare `python` on the parent's PATH.
   16. **The taps pass a client's disconnect along (R24-A, 2026-10-25, before any held-out run).**
       - `needle.Tap` watches `receive()` for `http.disconnect` while it relays. When the client leaves first, it stops relaying and closes the stream it was reading, and records `client_disconnect`. The server does not fail a send to a client that left, so without this the tap read the stream to the end.
       - In the front tap, OpenCode killed at the turn timeout reaches the proxy as a client cancel, so D13.1 lets the next request omit the cut-off turn. In the upstream tap, the proxy's cancel reaches Strata, which releases the slot on disconnect (`docs/probes/strata.md` §9).
       - A disconnected call is a client cancel (`client_cancels` per turn), neither a proxy rejection nor an upstream failure. A non-200 status or an in-stream error still counts.
       - Test: `tests/test_eval_taps.py` (client → front tap → proxy → upstream tap → fake upstream; the cut-off stream closes, the resend gets 200).
       - D44.1: the held-out configuration is `a4-d43` at the commit that carries this fix. It changes `eval/` only.

## D46 — Added-token strings inside messages count as text (R23-A)

The S11 smoke runs found that the counter tokenized `</tool_call>`, `<think>` and the other added-token strings as single tokens when a message quoted them. Strata encodes them as text. OpenCode's `tool.input-json` error quotes the model's unparsable call, `</tool_call>` included, so ordinary sessions hit this. Each request then drifted, and the local count ran low, the unsafe direction for the budget.

1. **The counter mirrors `mark_think_literals`.** `tokens.mark_literals` marks the same strings, fields and exceptions as Strata (`docs/probes/strata.md` §4). It runs after `preprocess_messages`, as Strata marks after `openai_to_messages`. The encoder emits each added token the template wrote as that token, and everything between them as plain text: the marks turn back into the tag text, and that text is encoded with a copy of the pinned tokenizer that has no added tokens.
2. **Evidence.** `eval/probes/p14_literal_tags.py` covers all 33 added tokens in every role, plus the three exceptions, against live Strata. That is 171 cases, and the local count now matches each one (`tests/test_strata_tokens.py`).
   - Rejected: marking only Strata's named literal tags. The probe shows the FIM, audio and TTS tokens are text too, so this GGUF's control tokens are every added token outside those tags.
3. **Layout.** `<|im_start|>` inside a message is text, so it no longer cuts the render. Each template turn is one fragment, and the per-message cut count (`_cuts`) is gone.
4. **Unchanged.**
   - `count`, `count_cached` and `encode` still tokenize the text they are given with the added tokens live. They size previews, the recent window and excerpt charges, and count the probes' golden renders.
   - A message that quotes a tag is therefore estimated a few tokens low there. The assembled request is still counted exactly, so the budget holds.
   - Excerpt payloads are still escaped (contract §11, Delimiters). Strata now makes such text inert anyway; the escaping still keeps a payload from closing its block.
5. **Cost.** On a 150 KB history (dev-h1's import), the marking scan adds about 1.5 ms per count. With a tag present the whole count takes about 6.5 ms cold, against 2.7 ms without.
6. **D44.1 amended before any held-out run.** The held-out configuration is `a4-d43` at the commit that carries this fix and D47. No held-out history or task has run, and the fixes change counting, not anything model-facing.
7. **Fixes from the cache audit of this change.**
   - **Mark before the drop.** Strata marks the whole message list before #843 drops empty turns. A tag that sits only in a dropped turn still switches marking on, and then any private-use mark character elsewhere is turned back into tag text. The counter now does the same (live: 64 tokens, where marking after the drop gave 66).
   - **Dict keys cut.** Strata does not mark keys, so `<|im_start|>` in a tool parameter name or a parsed argument key is a real token and cuts the render. `_key_cuts` counts those, so the layout stays mapped. The counts were already right.
   - **Counter revision.** `tokens.COUNTER_REVISION` ("c3") is part of every call's identity. After a restart, a call recorded by an older revision can fail to re-render to its recorded count; `explain` now classifies such a pair as `model_template_change` instead of `unexplained` (contract §10).
   - **Test oracle.** `test_cacheacct_http.encoded` encodes the marked render, so a future tag case gets the right expected LCP.

## D47 — No Unicode normalization before counting

The cache audit of D46 noticed that Strata's tokenizer (`tools/strata_tokenizer.py`, built from the model pack's vocab and merges) has no normalizer, while the pinned `tokenizer.json` declares NFC. `eval/probes/p15_nfc_count.py` confirmed it live: text whose NFC form differs counted low locally, by 1 for a combining accent and by 8 for decomposed Hangul. That is the unsafe direction for the budget.

1. **The counter loads the pinned tokenizer with its normalizer removed.** The pinned bytes and their hash are unchanged; only the in-memory copy differs. The pre-tokenizer and the model are unchanged, and the counts now match on every probe case.
2. **Canary.** `decomposed_text` (Strata: 69 tokens, recorded 2026-10-25) makes a server that does normalize fail the pin check at startup.
3. **Found before any held-out run.** It is part of the counter revision `c3`.

## D48 — Held-out ho-t3..t5 and 64K run on a second Strata host

Decided on 2026-10-26, after ho-t1 and ho-t2 had run under both arms on bazzite. This is a deviation from D44's "nothing here changes after held-out results are seen", and is recorded as one.

1. **What moves.** The 120 held-out needles and the ho-t1 and ho-t2 pairs stay as run on bazzite (192.168.1.173). ho-t3..t5, both arms, and the 64K report runs (D44.9) run against a second Strata, Zeus (192.168.1.19).
   - Each task's two arms run on the same machine.
   - The driver, OpenCode 2.1.4 and the proxy stay on the same Windows host. Only `--upstream` changes.
2. **Why.** Wall time. On the same recorded ho-t1 requests, Zeus decodes at 91 tok/s against bazzite's 52 and reads prompts at 1,226–1,411 tok/s against 708–770. Arm 1's compaction loop had made its runs take 2–4 h each on bazzite.
3. **Equivalence shown before any run on Zeus.**
   - **Pin:** `build_info` "Strata 0.1.48", template sha `12827f24…`, `n_ctx` 32768.
   - **Counting:** all 210 recorded counting cases give the same `prompt_tokens`, with 0 differences: 174 literal-tag, 6 NFC, 10 normalization and 20 `count_tokens`.
   - **Generation defaults:** sampling 1.0 / 0.95 / 20, the model card's thinking defaults that both servers apply because OpenCode sends none. Thinking is capped at 6,144 of OpenCode's 8,192 by the same answer-room rule.
   - **Release:** the slot is idle 0.13 s after a client disconnects mid-stream.
   - **D39:** `/v1/status` exposes the activity counter the D39 gate reads, and it counts inference requests only.
4. **What differs, and isn't verified.**
   - Zeus runs Control layer 0.2.3.1, against bazzite's 0.1.49. `serve/server.py`, `serve/frontend.py` and `tools/strata_tokenizer.py` differ, though the counts above match.
   - The engine's memory-placement and tuning flags are per-machine: Zeus has `--kv-resident`, `--pcie-frac` and `--adapt-*`; bazzite has `--resident-experts`. `--spec-min-p` is 0.5 on both. Zeus's config had a sampling block, which was removed to match bazzite. Whether the placement flags change outputs is unverified.
   - Zeus's server log is not readable from the driver host, so a D39 halt there is judged on the activity counter alone.
5. **What this changes for the gate.** No arm, proxy setting, gate or criterion changes. The 30-minute turn limit is wall-clock time, so on a faster machine more work fits in each turn. On bazzite the limit cut arm 1's turns 10 times and arm 4's once. The coding gate (D44.5) therefore adds up 2 tasks run on bazzite and 3 on Zeus.
   - It was chosen knowing ho-t1 and ho-t2's results: arm 4 1 of 2, arm 1 2 of 2.
   - R25 reports each task with the machine it ran on, along with each machine's kill counts.
6. **64K settings follow `n_ctx` (found before any 64K run).** `eval/tasks/run.py` had fixed arm 1's OpenCode `limit.context` at 32768, so at 64K native compaction would still have fired as if the context were 32K. It now equals `--expect-n-ctx`; arm 4 keeps the shipped 1,000,000. `eval/report.py` judged the "clean" needle subset against a fixed 24,320; it now uses arm 4's budget at the run's recorded `n_ctx` (48,000 at 65536). The 32K runs are unchanged by both: their `n_ctx` was 32768. The change touches `eval/` only (D44.1).

## D49 — Zeus is the only Strata host

Decided by the user on 2026-10-26, after the 64K report runs (R26). bazzite (192.168.1.173) is no longer used for this project; all live work runs against Zeus (192.168.1.19:8080).

- **What changes.** The default `--upstream` of the eval drivers and probes, the serve command in `CLAUDE.md` and the eval-runner's host note now name Zeus.
- **What stays.** Results, probe write-ups and probe fixtures keep the host they ran against. R25's per-machine split (D48) is unchanged.
- **Zeus's context.** Zeus was last launched at `n_ctx` 65536 (D48.6). A run that needs 32K relaunches it with the 32K config and checks `/props` first, as every driver already does through `--expect-n-ctx`.

## D50 — Phase 3 final review fixes (S12)

The final protocol, cache and paper-fidelity reviews of Phase 3 ran on 2026-10-26 at `4b024b8`, over the code changed since the D38 review. Each code change landed as a red test first.

1. **`tool_choice: "none"` renders no tool schemas.** Probe p16 on Zeus: the probe prompt counted 69 tokens with `tool_choice: "none"`, the same as with no `tools`, against 317 with `"auto"` or none (`eval/probes/fixtures/strata_tool_choice_output_limits.json`). The counter rendered the tools anyway. With OpenCode's tool schemas the drift would be thousands of tokens, over the 1,024 that turns bounded views off for the process (D22.4), on OpenCode's step-limit step. The held-out runs never reached that step (drift 0 everywhere).
   - `render_args_from_openai` now drops the tools when `tool_choice` is `"none"`. The counter revision becomes `c4`.
   - Cache accounting sees the tools change, so such a call is a `tool_change`.
   - Tests: `test_tool_choice_none_renders_no_tool_schemas` (literal probe values) and `test_tool_choice_none_drops_the_tools_from_the_render_as_a_tool_change`.
2. **The re-render after a restart knows dropped turns.** `cacheacct._rerender` built the previous call without `drops_empty_assistant`, unlike the live build (D42). With reasoning-only answers in the session, the re-render counted 2,543 tokens against 5,236 recorded, and the next call was `unexplained`. None of the 25 re-renders in the held-out archives hit it. Test: `test_a_turn_the_upstream_drops_rerenders_as_it_was_sent_after_restart`.
3. **`restart_or_eviction` names a shortfall, not a cause.** The cache audit found 36 such pairs in R25's 32K tasks, all with explained causes and no restart. In each, cached equalled the head end, below a checkpoint the model expected; in 32 of them the previous call had itself reused that region from cache. The model (D22.2) assumes the previous render's checkpoints are held, and Strata evidently drops some. The class keeps its name and means "below the estimate". The model is unchanged: it is an estimate, and no gate reads it.
4. **Both output limits.** p16: with both set, Strata uses `max_completion_tokens` (8 against 300 gave 8; 300 against 8 gave 300), which is the precedence the proxy already applies. No change.
5. **Documentation brought to the code.**
   - Contracts §1, §2 (the unbounded fallback after a non-budget build failure, D14.9), §3, §5, §7, §8 (deferrals to Ph4B and 3B), §9 (transcript-search steps), §10 and §11.
   - capabilities.md: `developer`, other `tool_choice` forms and `parallel_tool_calls` are rejected, not untested; `tool_choice: "auto"` is listed; the tokenizer row; known limits of Phase 3.
   - The paper-fidelity fixes: docstrings of `excerpts.py` (x2, U+FFFD), `affordances.py` (a3 cites Eunoe) and `projector.py` (git work trees); D28 and D29.3/.4 corrected to the code; papers.md lists the Complexity Trap and further Eunoe adaptations.
