# Results: working notes and Phase 3 acceptance (R33–R42)

[Index](README.md) · Append-only; each entry names its commit, configuration and hardware.

## R33 — Why Palimnesis loses coding tasks: diagnosis from the ho2 records (2026-10-28, development data per D69)

**Outcome.** Every Palimnesis loss on ho2-t2, t3 and t4 traces to the same cause. The view hides the model's own work in the turn it is doing, and nothing in the view says what that work was. Native compaction fails less because its checkpoint is a working summary. No proxy defect was found.

The findings come from per-call reconstruction of four failed runs, each against the same task's passing runs: ho2-t2 arm 5, ho2-t3 arms 4 and 5, and ho2-t4 arm 4. A replay of recorded edits reproduces the final files byte for byte. Scratch: `…/scratchpad/diag/`, `…/scratchpad/diag2/`.

**R33-A. The current turn's own work leaves the view.**
- In 91% of arm 4's mid-turn calls (1,220 of 1,339), at least one of the turn's own tool calls or results was collapsed or masked. Arm 5's figure is 90% (1,908 of 2,121).
- It starts early. ho2-t3 arm 4 collapsed six messages of turn 1 at call 4, after one 18K-token read. ho2-t2 arm 5 had collapsed its turn-7 work into a 24-message span, then 60, then 120.
- A span note says only "N messages · archived exactly; not shown". At the start of turn 7 on ho2-t2, arm 4's view was:
  - that note, covering 584 messages;
  - the last turn's answer;
  - excerpts that were mostly the model's own reasoning and stray grep lines.

**R33-B. What the model does without its own work in view.** Each of these is verified at specific calls in the reconstructions:
- **It invents a history.**
  - ho2-t3: "in the previous turn I read overlap.py" (arm 4); "previous attempt I created tests/data/" (arm 5).
  - ho2-t2 arm 5: "Reads of workspace files are serving stale snapshots" and "test file on disk has been replaced with a … graded suite". No view ever contained such content.
- **It rewrites whole files from memory.**
  - ho2-t2 arm 5: a 12.5K rewrite at call 141 broke slash chords, which had passed before it.
  - ho2-t4 arm 4: the rewrite at call 317 dropped turn 5's promotion and broke mixed numbers. In that request the doc and the old `scale.py` were head/tail stubs.
- **It trusts its own text over the spec.** ho2-t3 arm 4 removed a correct `end == start` check because "the file's real docstring" allowed it. The model had written that docstring in turn 1.
- **It re-verifies instead of progressing.** Compared with arm 1 across all runs:

  | | Arm 1 | Arm 4 | Arm 5 |
  |---|---|---|---|
  | Test runs | 64 | 171 | 217 |
  | Test reruns with no edit since the last run | 36 | 118 | 131 |
  | git commands | 26 | 128 | 109 |

  The killed turns were made of this.
- **It leaves the workspace.** Across arms, including arm 1, 35 tool calls in 8 runs guessed paths under `C:\Users\Daniel\repos\mnemon`, the Palimnesis repo. None reached `eval/tasks/` or a hidden test, and the repo is unchanged. It is an eval-hygiene risk all the same.

**R33-C. The proxy's own text adds to it.**
- **Excerpts and transcript greps return the model's earlier unverified reasoning, labelled "historical evidence".** This includes its hallucinations: "an earlier task variant (spec A)" (ho2-t4), "saladkit" (ho2-t4), and a false column rule (ho2-t2). R30-C measured reasoning at 42% of excerpt items.
- **The model copies the placeholder format into its own reasoning.** This happened in 30 arm-4 responses and 22 arm-5 responses. On ho2-t4 arm 4, turn 5 ended on a self-written `[archived exactly; not shown]` with no answer, leaving a `NameError` unfixed.
- **Arm 5 only:**
  - On ho2-t3 turn 7, between alternating pins and span notes, the model took the current instruction for an old one: "current turn = Turn E". It made no edits that turn. This is the layout R31 associated with needle early stops.
  - A refused lookup ended the response with `length`, and OpenCode's synthetic "hit the output token limit" follow-up then read as a truncated turn (ho2-t2).

**R33-D. What arm 1 had instead.** OpenCode's checkpoint is a structured summary of about 9K characters, refreshed in-turn when needed. Its sections are objective, requirements, decisions, and active state with next move. In every pair it carried what the failing arm lost:
- ho2-t3: "`end == start` is an error, not a 24-hour shift".
- ho2-t4: the promotion thresholds and "1 tsp = 5 ml, 1 tbsp = 15 ml, 1 cup = 240 ml".
- ho2-t2: the column formula, and "transpose_sheet — still raise NotImplementedError".

Arm 1 then made targeted edits; it never rewrote a file from memory.

**R33-E. Where this points.**
1. **A working state in view.** This is Phase 4A's pinned state (goal, constraints, decisions, current step, dead ends). R33 is the evidence that recall without state loses to a summary.
2. **Keep the current turn's own edits and results in view** in preference to older turns. Size it so one oversized read cannot evict them.
3. **Keep reasoning out of excerpts**, as D66 did for grep.
4. **Make placeholders say what they replace**, for example the file read and its lines, so a placeholder is information rather than something to copy.
5. **Isolate task workspaces** from the user's repositories.

None of these is tested yet. ho2 can serve as the development loop for them (D69); development tasks dev-t1..t5 do not reproduce the losses.

## R34 — The R33 fixes on ho2: current turn kept, no reasoning in excerpts, working notes (2026-10-28, development data per D69)

**Outcome.** With working notes (D72), arm 4 passed ho2-t2, t3 and t4, the three tasks where R33 traced its losses. Without notes (D70 and D71 only) it passed t2 and t4 and failed t3. Each cell is one attempt on development data, so this shows a direction, not a gate result. The runs also found a reconciliation defect, fixed as D73.

Setup:
- Arm 4 dev configs `a4-tr` (`a4-d43` + `--protect-turn` + `--retrieval r2`) and `a4-trn` (`a4-tr` + `--notes 2048`).
- 32K on Zeus, `--tag dev-r33`, workspaces under `%TEMP%\pmxdev\ws` (R33-E 5).
- Commits `487c2ad`, `32c57bd` and `2b694c9`. Records: `…/scratchpad/s12dev/tasks/records/attempt-001..007`.

| Task | `a4-trn` (notes) | `a4-tr` | R32 arm 4 (`a4-d43`) | R32 arm 1 (native) |
|---|---|---|---|---|
| ho2-t2 | **pass** 3/3, 3/3 · 85 calls · 20 min | pass 3/3, 3/3 · 194 · 35 min | pass 3/3, 3/3 · 473 · 94 min, kills 2 | pass 3/3, 3/3 · 132 · 29 min |
| ho2-t3 (restart) | **pass** 4/4, 3/3, restart gate True · 178 · 40 min | fail 2/4, 2/3, restart gate False · 178 · 36 min | fail 3/4, 3/3, restart gate False · 194 · 65 min | pass 4/4, 3/3, restart gate True · 172 · 31 min |
| ho2-t4 | **pass** 4/4, 3/3 · 167 · 33 min | pass 4/4, 3/3 · 204 · 43 min (attempt 4) | fail 0/4, 3/3 · 456 · 113 min, kills 2 | pass 4/4, 3/3 · 202 · 40 min |

- `a4-trn` counts include the notes refresh calls. Arm 1's counts include its compaction calls.
- No `a4-tr` or `a4-trn` run had a 30-minute kill, except the voided attempt 3 below. Every run had:
  - 0 proxy rejections, after the D73 fix;
  - every cache change explained (`--explain`), 0 over-budget calls, 0 leaks and 0 model or harness mentions;
  - Strata's activity counter rising by exactly our upstream calls (D39).
- The longest turns stayed under the limit: ho2-t3 `a4-trn` turn 7 (79 calls, 1,240 s) and ho2-t4 `a4-tr` turn 3 (99 calls, 1,235 s).

**R34-A. ho2-t4 `a4-tr` attempt 3 is void (D73).**
- The 30-minute kill of turn 5 landed while OpenCode ran a complete, valid `read` call.
- OpenCode resent that call with `arguments: "{}"` and an aborted tool result. Reconciliation took that as edited history, so turns 6–8 were refused with 409 `history_divergence`.
- D73 accepts `{}` against any archived arguments. Attempt 4 was the rerun, with its reason recorded.
- R32 is unaffected: none of its killed turns landed while a tool ran, and it had no 409s.

**R34-B. Working notes: what they cost.**

| | ho2-t2 | ho2-t3 | ho2-t4 |
|---|---|---|---|
| Refreshes (committed / failed) | 10 (8 / 2) | 19 (15 / 4) | 13 (13 / 0) |
| Refresh time, median · total | 37 s · 6.1 min | 34 s · 11.8 min | 34 s · 8.5 min |
| Share of the run's wall time | 31% | 29% | 26% |
| Refresh prompt tokens, cached | 80% | 89% | 91% |
| Share of all prompt tokens | 15% | 13% | 10% |

- Refresh time runs from the request's start to the end of its refresh call. The client waits for it before the visible call starts.
- Each refresh generated 2,000–6,000 completion tokens, and a third to a half of those were reasoning.
- Even with refreshes, every `a4-trn` run took about arm 1's wall time or less, and fewer calls than `a4-tr`.

**R34-C. Working notes: two defects in the notes themselves.**
- **Every committed version was cut.**
  - The model wrote 8–12K characters against the prompt's "about 1,200 words". Fitting to the 2,048-token slot kept the first 5–7K.
  - The sections are written in order, so the cut fell on the last ones. Of 36 committed versions:
    - all kept *Requirements* and *Decisions*;
    - 32 kept *Done so far*;
    - 8 kept *Current step and next move*;
    - 2 kept *Dead ends*.
  - The runs passed on the requirements and the record of work done. The next move and the dead ends mostly never reached the view.
- **6 of 42 refreshes failed as `empty`.** Each ended `stop` with the notes written only in reasoning (700–12,300 characters) and no content. The view kept the previous version, which D72 allows.

**R34-D. What this does not show.**
- Variance. Each cell is one attempt, while R32 had kills and failures that varied by turn.
- ho2-t5 and ho2-t1, and the needle sets, were not run under the new configs.
- Arm 5 with these changes was not run.
- ho2 is development data now (D69), so a gate needs tasks the fixes were not tuned on.

**R34-E. Next.**
1. Make the cut harmless:
   - put *Current step and next move* first in the requested order;
   - ask for a tighter length;
   - when the text is cut, keep whole sections instead of a prefix.
2. When a refresh's content is empty, use its reasoning, or retry once.
3. Cut the refresh latency, for example by limiting its reasoning.
4. Repeat the `a4-trn` runs to measure variance, and run ho2-t1 and ho2-t5 and the needle sets.
5. Then decide on a gate run on fresh held-out tasks.

## R35 — Working-notes format n2 on ho2 (2026-10-28, development data per D69)

**Outcome.** Arm 4 with notes format n2 (`a4-trn2`, D74, commit `56d29d2`) passed ho2-t2, t3 and t4. Each was one attempt, the same as R34's `a4-trn`.
- Every committed notes version kept all six sections. Under n1, 8 of 36 kept *Current step* and 2 kept *Dead ends*.
- Refreshes took about half as long.
- ho2-t4 held 2 of 3 constraints. Its notes carried the missed rule.

Records: `…/scratchpad/s12dev/tasks/records/attempt-008..010`, tag `dev-r33`.

| Task | `a4-trn2` (n2) | `a4-trn` (n1, R34) | R32 arm 1 (native) |
|---|---|---|---|
| ho2-t2 | pass 3/3, 3/3 · 114 calls · 31 min | pass 3/3, 3/3 · 85 · 20 min | pass 3/3, 3/3 · 132 · 29 min |
| ho2-t3 (restart) | pass 4/4, 3/3, restart gate True · 146 · 21 min | pass 4/4, 3/3, True · 178 · 40 min | pass 4/4, 3/3, True · 172 · 31 min |
| ho2-t4 | pass 4/4, **2/3** · 121 · 22 min | pass 4/4, 3/3 · 167 · 33 min | pass 4/4, 3/3 · 202 · 40 min |

All three runs had:
- no 30-minute kills and no proxy rejections;
- every cache change explained, no over-budget calls and no leaks;
- Strata's activity counter rising by exactly our upstream calls (D39).

The longest turn was ho2-t2 turn 7: 58 calls, 1,182 s.

**R35-A. The notes.**

| | ho2-t2 | ho2-t3 | ho2-t4 |
|---|---|---|---|
| Refreshes (committed / failed) | 11 (11 / 0) | 13 (11 / 2) | 13 (12 / 1) |
| Committed from reasoning | 1 | 2 | 0 |
| Committed length, characters | 3,893–5,570 | 3,867–6,931 | 4,063–4,893 |
| Versions with all six sections | 11/11 | 11/11 | 12/12 |
| Refresh time, median · total | 24 s · 5.1 min | 17 s · 3.6 min | 15 s · 3.5 min |
| Share of the run's wall time | 17% (n1: 31%) | 17% (n1: 29%) | 16% (n1: 26%) |
| Refresh prompt cached · share of all prompt tokens | 86% · 12% | 90% · 11% | 85% · 13% |

- **Failures.** Three refreshes still failed `empty`: their reasoning held no draft with three sections that had content. Under n1, 6 of 42 failed `empty`; under n2, 3 of 37 did, and 3 more were recovered from reasoning.
- **Refresh time.** Refreshes are shorter because the notes are shorter. n1 asked for about 1,200 words; n2 asks for about 600 at S = 2,048.

**R35-B. ho2-t4's missed constraint (C2).**
- The hidden check expects `scale_line("1/2 tsp  sea salt, flaky ", 2)` to keep the double space after the unit. The model's parser collapsed it.
- 11 of the 12 notes versions quoted the rule "kept exactly as written". So the rule was in view, and the model did not apply it to whitespace. This is not lost state.
- The task still passes: its success is the visible tests, 4/4.
- R32's arm 1 and R34's `a4-trn` both held C2 on this task.

**R35-C. Reading.**
- Over R34 and R35, notes n1 and n2 each passed all three tasks that native compaction passed, and that arm 4 failed in R32.
- n2 fixes R34-C's truncation and halves the refresh cost.
- On wall time the two formats split: n2 was faster on t3 and t4, slower on t2.
- These are single attempts on development data, which supports adopting n2. It is not a gate result.
- Next (R34-E 4–5):
  - repeat attempts for variance;
  - run ho2-t1 and ho2-t5 and the needle sets under `a4-trn2`;
  - then fresh held-out tasks for a gate.

## R36 — `a4-trn2` on all of ho2: second attempts, ho2-t1, ho2-t5 and the needles (2026-10-28/29, development data per D69)

**Outcome.** Commit `5f0e5bf`, clean tree, one batch, 22:22–01:43Z.
- **Tasks.** The second attempts at t2, t3 and t4 passed with every constraint held. ho2-t1 passed and ho2-t5 failed. Over R35 and R36, `a4-trn2` passed 6 of 6 attempts on t2–t4 and 7 of 8 task runs in all.
- **Needles.** 107/120 loose exact (Wilson 82.3–93.6%), against arm 4's 119/120 in R32. 10 of the 13 misses are upstream early stops (R21-C); arm 4 had 1.

Records: `…/scratchpad/s12dev/tasks/records/attempt-011..015` and `…/s12dev/needles-a4-trn2/`, tags `dev-r33` (tasks) and `dev-r36` (needles).

**R36-A. Tasks.**

| Task | `a4-trn2` R36 | `a4-trn2` R35 | R32 arm 1 (native) | R32 arm 4 (`a4-d43`) |
|---|---|---|---|---|
| ho2-t1 | pass 4/4, 3/3 · 257 calls · 59 min | – | pass 4/4, 2/3, kills 3 | pass 4/4, 3/3, kills 0 |
| ho2-t2 | pass 3/3, 3/3 · 95 · 16 min | pass 3/3, 3/3 · 114 · 31 min | pass 3/3, 3/3 | pass 3/3, 3/3, kills 2 |
| ho2-t3 (restart) | pass 4/4, 3/3, restart gate True · 121 · 19 min | pass 4/4, 3/3, True · 146 · 21 min | pass 4/4, 3/3, True | fail 3/4, 3/3, False |
| ho2-t4 | pass 4/4, 3/3 · 258 · 39 min | pass 4/4, **2/3** · 121 · 22 min | pass 4/4, 3/3 | fail 0/4, 3/3, kills 2 |
| ho2-t5 | **fail 2/3**, 3/3 · 86 · 20 min | – | fail 0/3, 1/3, kills 3 | fail 1/3, 3/3, kills 1 |

- **All five runs:**
  - no 30-minute kills and no proxy rejections;
  - every cache change explained, and payload verification passed;
  - Strata's activity counter rising by exactly our upstream calls (D39).
- **Longest turns:** ho2-t4 turn 1 took 1,159 s (105 calls), and ho2-t1 turn 7 took 1,072 s.
- **ho2-t3:** the tap counted 1 foreign request between calls and 1 during a call. Strata's total matched our calls, so this is R25-B's late-counted request, not foreign traffic.
- **ho2-t4:** one client cancel without a kill (OpenCode's interrupted call, D73).
- **ho2-t5** fails the hidden match test (`test_f_match`), with every constraint held. It is the best result on this task so far; every R32 arm failed it, native included.
- **Variance:** the same task under the same arm took 16–31 min (t2) and 22–39 min (t4) across two attempts. ho2-t4 missed C2 once and held it once.

**R36-B. The notes.** Same measures as R35-A.

| | ho2-t1 | ho2-t2 | ho2-t3 | ho2-t4 | ho2-t5 |
|---|---|---|---|---|---|
| Refreshes (committed / failed) | 26 (25 / 1) | 9 (9 / 0) | 12 (12 / 0) | 20 (18 / 2) | 10 (10 / 0) |
| Committed from reasoning | 4 | 0 | 0 | 4 | 0 |
| Versions with all six sections | 25/25 | 9/9 | 12/12 | 17/18 | 10/10 |
| Refresh time, median · share of wall time | 21 s · 17% | 19 s · 19% | 18 s · 20% | 19 s · 17% | 25 s · 20% |

- Every failure was `empty`.
- The one ho2-t4 version without *Dead ends* was written that way; it was not cut.

**R36-C. Needles.**

| Arm | Loose exact | Early stops | Needle in view | Lookups | Prompt tokens | Wall |
|---|---|---|---|---|---|---|
| `a4-trn2` (R36) | 107/120 | 10 | 101 | 19 | 3.92M | 44.7 min |
| `a4-d43` (R32, 2 attempts) | 119/120, 119/120 | 1 | 27–29 | 133–146 | 4.75M–4.97M | 25–27 min |

- **The misses:**
  - **10 early stops** (finish `stop`): 4 empty answers and 6 cut short, such as `180` for `18000ms`, `4` for `4450ms`, and `test_reckon_nimble` for `test_reckon_nimble_lattice`.
  - **2 follow-on misses** in ho2-h1. After the empty answer at q2, q3 and q4 also answered the previous step; the correct value follows the earlier one.
  - **1 right value with commentary** (h8q4), which loose exact does not accept.
  - So when the model answered, it answered correctly in 107 of 108 questions, as in R32.
- **Where the misses fall:** identifier 23/24, superseded 11/12, irrelevant matches 8/12, vague 19/24, oversized read 10/12. Every other category is 12/12.
- **The needle is now usually in view.** 101 of 120 facts were in the view (R32: 27–29), so the model looked things up 19 times. The gold value was in that history's notes for 98 of 120 questions.
- **Not R31's layout.** R31 tied arm 5's early stops to long runs of user messages. Here every prompt has runs of at most 3, for hits and misses alike.
- **A weak association with refreshes.** 46 questions had a notes refresh in their turn, and 7 of them missed (15%); 6 of the other 74 missed (8%). This is not significant on its own.
- **Not run:** no ablation separates the three changes from arm 4 (current turn kept, retrieval r2, notes). The early stops are an engine behaviour (R29-A), and something in this arm's prompts brings them on more often.
- **Checks:** every cache change explained (263/263), payload verification 12/12, no leaks, no hidden calls.

**R36-D. Reading.**
- **Tasks:** `a4-trn2` matched or beat native compaction on all five ho2 tasks, on development data. Both attempts on t2–t4 passed.
- **Needles:** 107/120 would clear the 85% bar, but it is 12 below arm 4. The cause is early stops, not recall, and this run cannot say which change brings them on.
- **Next:**
  1. needles under `a4-tr` (no notes) and `a4-trn` (n1), to find which change brings the early stops on;
  2. then fresh held-out tasks for a gate.

## R37 — Which change brings R36's early stops on: ho2 needles without notes, and with notes n1 (2026-10-29, development data per D69)

**Outcome.** The notes bring them on. Without notes (`a4-tr`) the needles score 119/120, as arm 4 did in R32. With notes they score 105/120 (n1) and 107/120 (n2, R36), and almost every miss is an answer that stops early.

Commit `f4d898b`, clean tree, 02:55–04:13Z, tag `dev-r37`. Records: `…/scratchpad/s12dev/needles-a4-tr/` and `…/needles-a4-trn/`.

| Arm | Adds to `a4-d43` | Loose exact | Misses: empty / cut short / right value with extra text | Needle in view | Misses with the needle in view | Lookups | Prompt tokens | Upstream calls | Wall |
|---|---|---|---|---|---|---|---|---|---|
| `a4-d43` (R32, 2 attempts) | – | 119/120, 119/120 | 1 / 0 / 0 each | 27–29 | 0 | 133–146 | 4.75M–4.97M | 306–317 | 25–27 min |
| `a4-tr` | current turn kept (D70), no reasoning in excerpts (D71), retrieval r2 | **119/120** | 1 / 0 / 0 | 29 | 0 of 29 | 131 | 4.95M | 328 | 29 min |
| `a4-trn` | + notes n1 | **105/120** | 1 / 13 / 1 | 103 | 15 of 103 | 15 | 3.85M | 260 | 49 min |
| `a4-trn2` (R36) | + notes n2 | **107/120** | 4 / 6 / 3 | 101 | 9 of 101 | 19 | 3.92M | 275 | 45 min |

- **"Cut short"** means the answer is a prefix of the gold: `bug` for `bugfix/loomline/thread-876769`, `47` for `4739`, `4150` for `4150ms`. "Right value with extra text" includes R36's two follow-on answers in ho2-h1.
- **D70, D71 and retrieval r2 cost nothing on needles.** `a4-tr` matches `a4-d43` on score, misses, the needle in view, lookups and tokens.
- **What the notes change.** The notes carry the facts, so the needle is in view for 101–103 questions instead of 29, and the model looks things up 15–19 times instead of about 130. Its answers then stop early: 15 times under n1 and 10 under n2.
- **Not just "in view."** Without notes, the 29 questions whose needle was in view had 0 misses. With notes, the misses fall on questions whose needle was in view: 15 of 15 under n1, 9 of 13 under n2.
- **Not tied to the refresh turn.** Under n1, 7 of 45 questions whose turn held a refresh missed, against 8 of 75 without one.
- **Mechanism unverified.** R21-C first suggested a hypothesis for these early stops: Strata's speculative decoding (MTP) copying an answer from text in the prompt. R29-A showed they reproduce directly against Strata. Neither run tests whether the notes block, or the fact being in it, causes the cut.
- **Checks:** both runs explained every cache change (316/316 and 248/248), passed verification 12/12, had no leaks and no hidden calls, and Strata's activity rose by exactly the tap's call count (328 and 260).

**R37-B. Reading.**
- **On ho2 the notes trade recall for coding.**
  - Recall: they cost 12–14 needles, through early stops.
  - Coding: they won tasks. R34's `a4-trn` passed ho2-t3, which `a4-tr` failed, and `a4-trn2` passed t2–t4 twice (R35, R36).
- **n2 vs n1:** n2 stops early less often than n1 (10 against 15), but one run each cannot separate them.
- **Next:** take a few early-stop prompts from these bodies and replay them directly against Strata, as R29-A did. Vary one thing at a time:
  - the notes block present or removed;
  - the value inside the notes kept or masked;
  - speculative decoding on or off, if Strata allows it per request.
  
  That shows whether the cut follows the notes' content, their placement, or the decoder, before any change to the notes.

## R38 — Replaying the early stops directly against Strata, with the notes varied (2026-10-29, development data per D69)

**Outcome.** The early stop is a per-call event, not a fixed property of a prompt. Varying the notes block changed its rate at most modestly, and not significantly. Removing the notes did not stop it.

**Method** (R29-A's). 9 needle answer calls from R36/R37 bodies were sent straight to Strata, 4 times each in four forms (144 calls). Strata was otherwise idle.
- **The prompts:** 7 that stopped early in the run (4 `a4-trn`, 3 `a4-trn2`, at most one per history per arm) and 2 `a4-trn` controls that were answered correctly. In each, the gold value is in the notes block and also elsewhere in the view.
- **The four forms:**
  - `orig`: as sent;
  - `no_notes`: the notes message removed;
  - `masked`: the gold value inside the notes replaced by `[elided]`;
  - `in_system`: the notes text appended to the system message instead.
- Only the short answer, finish reason, counts and timings were recorded. Script and data: `…/scratchpad/r37/replay_notes.py`, `replay_notes.json`.

| Form | Early-stopped prompts: exact | … early stops (empty or cut short) | Controls: exact |
|---|---|---|---|
| `orig` | 19/28 | 9/28 | 8/8 |
| `no_notes` | 20/28 | 4/28 | 7/8 |
| `masked` | 20/28 | 6/28 | 7/8 |
| `in_system` | 19/28 | 9/28 | 8/8 |

- **The run's early stop reproduces about one call in three.** The same prompt, sent again, mostly answers in full. Every prompt that stopped early in the run answered exactly in at least one of its four `orig` replays.
- **The notes matter little within a prompt.** Removing them gives 4 early stops against 9, which is not significant (Fisher, p ≈ 0.2). Masking the value gives 6. Moving the notes into the system message changes nothing (9).
- **Shape of the stops (all 144 calls):**
  - 29 early stops: 7 empty and 22 cut short, at a token boundary (`4300` for `4300ms`, `bug` for `bugfix/…`).
  - In 17 of the 29, the reasoning had just stated the full value.
  - Every one finished `stop`, with 18–40 completion tokens.
  - Drafts were accepted at 0.66–0.71 on early stops, against 0.75 on full answers.
- **R29-A's replays, read again.**
  - At temperature 0 they still varied between full, cut and empty answers. Greedy decoding without drafting would give one answer.
  - Its "spec 2, no MTP" replay still offered 603 draft tokens, so drafting was never off in any replay so far.

**R38-B. Reading.**
- **Why the arm's rate rises with notes.** It cannot be the notes block itself, which the replay shows at most weakly. The more likely cause is what the notes do to the turn.
  - **With notes**, the facts are in view, so the model answers directly in a short completion. In the replay, about one such call in five to three stops early.
  - **Without notes** (`a4-tr`, `a4-d43`), the same categories answer after a lookup (about 130 lookups against 15–19).
  - This is consistent with R37: with notes the misses are in identifier, superseded, irrelevant matches and vague, which are the categories `a4-tr` answers by lookup.
- **Engine hypothesis (unverified).** Zeus runs MTP drafting with `--spec-min-p` 0.5. If that accepts drafted tokens other than the model's own choice, a drafted end-of-turn token right after the first token of a value would give exactly these cuts at temperature 0. Strata has no per-request switch for drafting: six candidate fields left `timings.draft_n` unchanged.
- **Next:** relaunch Strata on Zeus with drafting off, or with `--spec-min-p` that only accepts the model's own token. Then replay `orig` for these 9 prompts, 8 times each.
  - If the stops disappear, the cause is the engine. The fix is server configuration, and earlier needle results under drafting need that caveat.
  - If they remain, the fix belongs in how the notes shape the answer turn.

**R38-C. Drafting off, then temperature 0** (same 9 prompts, `orig` only). Strata on Zeus was relaunched at 32K with no drafter: `--spec 2`, no `--mtp`, `--suffix-draft 0`. `/metrics` showed drafting `off`, `mtp_max` 0 and `lookup` 0, and 0 drafts were offered over all 108 calls.

| Condition | Early-stopped prompts: exact | … early stops | Controls: exact |
|---|---|---|---|
| Drafting on, temperature default (R38) | 19/28 | 9/28 | 8/8 |
| **Drafting off**, temperature default, 8 each | 35/56 | **21/56** | 14/16 |
| **Drafting off, temperature 0**, 4 each | 20/28 | **8/28** | 8/8 |

- **Drafting is not the cause.** With no drafter at all, the stops stay (38% of calls), with the same shape: 8 empty and 15 cut short, all finishing `stop`. R38's engine hypothesis is refuted.
- **Sampling causes most of them.** OpenCode sends no temperature, so Strata samples at its defaults (1.0 / 0.95 / top-k 20, D48.3). At temperature 0, 5 of the 7 prompts answer exactly in 4 of 4 calls.
- **ho2-h1 q2 stops under greedy decoding.**
  - Under both notes formats it answers `bug` (6 times) or nothing (once), and the full branch name only twice. So the model's most likely next token after `bug` is the end of the turn.
  - That is a model-level failure on this prompt, and on R36's ho2-h1 cascade, not sampling luck.
- **The engine is not exactly deterministic at temperature 0** even without drafting.
  - Identical requests produced different completion lengths, for example 29, 57 and 66 tokens for one control.
  - The first, uncached call often differs from the cached repeats. Prefill against cache reuse, or `--adapt-*` expert swapping, are plausible sources, both unverified.
  - R29-A's temperature-0 variation fits this.

**R38-D. Reading.**
- **The early stops come from the model,** sampled at temperature 1.0, ending its turn right after the first token of a value. In one prompt the model ends there even when greedy.
- **The proxy sets no sampling parameters of its own;** the harness's request decides them, and OpenCode sends none. So the remaining question is why turns with notes make the model end early more often.
  - The leading explanation is R38-B's: with the facts in its notes, the model answers directly after very short reasoning (median 47–113 characters in these replays), instead of after a lookup.
  - That is untested.
- **For evaluation:** needle scores on this server include a sampling-driven early-stop rate. Every arm runs under the same defaults, so comparisons between arms stay fair, but single runs are noisy (R29's lesson).

**R38-E. One sentence in the notes header.** Same 9 prompts, 6 calls per form, drafting still off (R38-C showed drafting does not change the rate). Each prompt's unchanged form ran in the same session as the control. The sentence is added inside the header's brackets:
- `hint_check`: "Notes can abbreviate or go stale: before you quote an exact value from them, confirm it against the conversation or the archived transcript".
- `hint_full`: "When you quote a value from these notes, write it out in full, exactly as recorded".

| Form | Early-stopped prompts: exact | … early stops | Controls: exact | Tool calls | Reasoning, median characters |
|---|---|---|---|---|---|
| `orig` | 23/42 | 19/42 | 11/12 | 0 | 91 |
| `hint_check` | 29/42 | 13/42 | 12/12 | 0 | 103 |
| `hint_full` | **36/42** | **6/42** | 11/12 | 0 | 88 |

- **`hint_full` cuts the early stops by about two thirds.**
  - Fisher's exact test gives p = 0.004 over the 7 prompts, but calls on one prompt are not independent.
  - By prompt: fewer stops in 5, the same in 1, more in 1 (ho2-h6 q4, 0 → 1).
  - ho2-h1 q2, which stops even when greedy, fell from 3/6 to 1/6 under n1 and from 6/6 to 3/6 under n2.
- **`hint_check` does not help significantly** (p = 0.26), and it never made the model look anything up.
- **Short reasoning is not the mechanism.** `hint_full` did not lengthen the reasoning (88 against 91 characters). The sentence acts on the answer itself.
- **Not tested here:**
  - whether the sentence changes anything else the model does with its notes, in coding tasks;
  - whether a header change costs cache reuse (it does not: the header is part of the notes block, which is already re-rendered at each `state_commit`).

## R39 — Notes header h2 (D75) on the ho2 needles, ho2-t3 and ho2-t4 (2026-10-29, development data per D69)

**Outcome.** With h2, the needles score 111/120, against 107 for `a4-trn2` and 119 without notes (`a4-tr`). Early stops fall from 10 to 7, in the direction R38-E predicted. One run cannot separate the two arms, though (Fisher p = 0.62). Both tasks passed, and ho2-t4 missed constraint C2, which it has missed before under three arms.

Commit `e8d6181`, clean tree, 05:17–06:58Z, tag `dev-r39`, Strata on Zeus in its normal 32K configuration (drafting on). Records: `…/scratchpad/s12dev/needles-a4-trn2h/` and `…/s12dev/tasks/records/attempt-016/`, `attempt-017/`.

| Arm | Loose exact | Misses: empty / cut short / right value with extra text | Needle in view | Misses with the needle in view | Lookups | Prompt tokens | Upstream calls | Wall |
|---|---|---|---|---|---|---|---|---|
| `a4-tr` (R37) | 119/120 | 1 / 0 / 0 | 29 | 0 of 29 | 131 | 4.95M | 328 | 29 min |
| `a4-trn` (R37) | 105/120 | 1 / 13 / 1 | 103 | 15 of 103 | 15 | 3.85M | 260 | 49 min |
| `a4-trn2` (R36) | 107/120 | 4 / 6 / 3 | 101 | 9 of 101 | 19 | 3.92M | 275 | 45 min |
| `a4-trn2h` | **111/120** | 4 / 3 / 2 | 99 | 8 of 99 | 22 | 4.30M | 292 | 49 min |

- **Early stops: 7, against 10 (n2) and 14 (n1).** Under h2 they are 4 empty answers and 3 cut short (`47000` for `47000ms`, `bug` for a branch name, `4` for a four-digit value).
- **The misses fall on different questions in each run.** Across the three notes arms, only ho2-h1 q2 missed every time. It is R38-C's prompt that stops even under greedy decoding.
- **A run of misses in one history.** Four consecutive questions in ho2-h11 (q2–q5) stopped early. None of them missed under `a4-trn2`, and two missed under `a4-trn`. R36's ho2-h1 had a similar run.
- **A new kind of miss in ho2-h6.**
  - On q6 (oversized read), the model went back to the coding task first: it made 24 rounds and 19 workspace tool calls and reported a committed fix. Only then did it answer, with the right value inside 300 characters of report.
  - q7 was answered with a run report that contains the gold.
  - No earlier arm did this on these questions (q6 took 1–4 rounds and no workspace calls). It is one occurrence; whether the header or the notes' "Current step" prompted it is unverified.
- **Checks:** every cache change was explained (280/280), verification passed 12/12, there were no leaks or hidden calls, and Strata's activity rose by exactly the tap's call count (292).

| Task | Arm (attempt) | Result | Constraints | Calls | Lookups | Wall | Notes refreshes: committed / failed |
|---|---|---|---|---|---|---|---|
| ho2-t3 | `a4-trn2` (a9, a14) | pass, pass | 3/3, 3/3 | 146, 121 | 0, 0 | 21, 19 min | 12 / 0 (a14) |
| ho2-t3 | `a4-trn2h` (a16) | **pass** | **3/3**, restart gate held | 61 | 0 | 13 min | 7 / 0 |
| ho2-t4 | `a4-trn2` (a10, a15) | pass, pass | 2/3 (C2), 3/3 | 121, 258 | 0, 1 | 22, 39 min | 18 / 2 empty (a15) |
| ho2-t4 | `a4-trn2h` (a17) | **pass** | **2/3 (C2)** | 216 | 6 | 40 min | 17 / 2 empty |

- **C2 on ho2-t4 is a coin flip across arms.** It held in 1 of 2 `a4-tr` attempts (the other missed C3), in 1 of 1 `a4-trn`, in 1 of 2 `a4-trn2` and in 0 of 1 `a4-trn2h`. Nothing here ties the miss to the header.
- **Strata's activity matched the upstream calls** (61 and 216). There were no kills; ho2-t4 had one client cancel.
- **The notes behaved as under n2.** Every committed version had all six sections, refreshes took 15–19% of wall time, and the two failed refreshes were empty, as in `a4-trn2` a15.

**R39-B. Reading.**
- **h2 is no worse than n2's header on this data, and probably better on recall.** The needles rose 107 → 111, early stops fell 10 → 7, and both tasks passed as before. Neither difference is significant from one run.
- **The notes still cost recall.** `a4-trn2h` is 8 below `a4-tr` (111 against 119, p = 0.02 on misses), mostly through early stops on questions whose needle is in view. The header narrows the gap; it does not close it.
- **The ho2-h6 miss is the one to watch.** A needle question that sends the model back into the coding task changes the workspace, not just the score. If it recurs, look at whether the notes' "Current step" reads to the model as an instruction.
- **Next:**
  - a second ho2 needle attempt under `a4-trn2h`, to separate it from `a4-trn2`;
  - `a4-trn2h` on ho2-t1, t2 and t5, to see the whole development set under one arm before choosing the held-out configuration.

## R40 — `a4-trn2h` again: a second ho2 needle attempt, and ho2-t1, t2 and t5 (2026-10-29, development data per D69)

**Outcome.**
- **Needles: the second attempt scores 102/120.** Over both attempts, `a4-trn2h` stops early as often as `a4-trn2`: 20 of 240 answers against 10 of 120. R38-E's two-thirds cut in replay does not carry over to live runs, so R39's 111 was run-to-run variation.
- **Tasks: all three passed with every constraint held.** That includes ho2-t5, which every earlier arm failed, native compaction included. With R39, `a4-trn2h` has passed all five ho2 tasks, one attempt each.

Commit `5048e8f`, clean tree, 14:02–16:23Z, tag `dev-r40`, Strata on Zeus in its normal 32K configuration (drafting on). Records: `…/scratchpad/s12dev/needles-a4-trn2h/records/attempt-002/` and `…/s12dev/tasks/records/attempt-018..020/`.

**R40-A. Needles.**

| Arm (attempt) | Loose exact | Misses: empty / cut short / right value with extra text / other | Needle in view | Lookups | Prompt tokens | Upstream calls | Wall |
|---|---|---|---|---|---|---|---|
| `a4-tr` (R37) | 119/120 | 1 / 0 / 0 / 0 | 29 | 131 | 4.95M | 328 | 29 min |
| `a4-trn2` (R36) | 107/120 | 4 / 6 / 3 / 0 | 101 | 19 | 3.92M | 275 | 45 min |
| `a4-trn2h` a1 (R39) | 111/120 | 4 / 3 / 2 / 0 | 99 | 22 | 4.30M | 292 | 49 min |
| `a4-trn2h` a2 | **102/120** | 8 / 5 / 4 / 1 | 100 | 18 | 4.34M | 291 | 45 min |

- **Early stops (empty or cut short):**
  - `a4-trn2h`: 7 and 13 in its two attempts, 20/240 (8.3%);
  - `a4-trn2`: 10/120 (8.3%);
  - `a4-trn`: 14/120.
- **7 of the 18 misses come from the restart questions.**
  - In four histories (ho2-h1, h3, h8, h12), the question right after the proxy restart (q9, restart with multiple evictions) got an empty answer. Each finished `stop` after 29–119 completion tokens.
  - In three of those histories, the next question (q10) was answered with q9's value followed by its own, which counts as extra text.
  - In R36, R37 and R39, none of the 36 restart questions under notes arms missed.
- **The restart is not the cause; the per-call early stop is.** R38's method was used on the q9 answer calls from both attempts: each was sent to Strata 6 times, unchanged. Script and data: `…/scratchpad/r40/replay_restart.py`, `replay_restart.json`.

  | Bodies from | ho2-h1 q9 | ho2-h3 q9 | ho2-h8 q9 | ho2-h12 q9 |
  |---|---|---|---|---|
  | a1 (answered in the run) | 6/6 exact | 5/6 exact, 1 tool call | 6/6 exact | 6/6 exact |
  | a2 (empty in the run) | 6/6 tool call | 5/6 exact, 1 empty | 3/6 exact, 3 empty | 6/6 exact |

  - Three of the four empty prompts mostly answer exactly when sent again. ho2-h8 q9 stops early in half its calls, which is the per-call event R38 described.
  - In the a2 body for ho2-h1 q9, the value is not in the notes, and the replay always asks for a lookup. In the run, that call ended with no text and no tool call.
  - Four such stops landing on one question number in one attempt is chance, on top of a rate that is the same across the two attempts.
- **ho2-h6 q6 did not recur.** The question was answered in 4 rounds with no workspace tool calls. R39's return to the coding task happened once in two attempts.
- **The run of misses in one history moved to ho2-h1** (q6–q10, five in a row: `test_steep_nim` for `test_steep_nimble_parcel`, `4` for `425`, `r` for a host string, empty, `debounce` for `debounce_adaptive`).
- **Checks:** every cache change was explained (279/279), verification passed 12/12, there were no leaks or hidden calls, and Strata's activity rose by exactly the tap's call count (291).

**R40-B. Tasks.**

| Task | `a4-trn2h` (R39/R40) | `a4-trn2` (R35/R36) | R32 arm 1 (native) | R32 arm 4 (`a4-d43`) |
|---|---|---|---|---|
| ho2-t1 | **pass 4/4, 3/3** · 177 calls · 43 min | pass 4/4, 3/3 · 257 · 59 min | pass 4/4, 2/3, kills 3 | pass 4/4, 3/3, kills 0 |
| ho2-t2 | **pass 3/3, 3/3** · 77 · 16 min | pass 3/3, 3/3 (×2) · 95–114 · 16–31 min | pass 3/3, 3/3 | pass 3/3, 3/3, kills 2 |
| ho2-t3 (restart) | pass 4/4, 3/3, restart gate True · 61 · 13 min | pass 4/4, 3/3, True (×2) | pass 4/4, 3/3, True | fail 3/4, 3/3, False |
| ho2-t4 | pass 4/4, 2/3 (C2) · 216 · 40 min | pass 4/4, 2/3 and 3/3 | pass 4/4, 3/3 | fail 0/4, 3/3, kills 2 |
| ho2-t5 | **pass 3/3, 3/3** · 147 · 35 min | fail 2/3, 3/3 | fail 0/3, 1/3, kills 3 | fail 1/3, 3/3, kills 1 |

- **ho2-t5 passes for the first time.** The hidden match test (`test_f_match`), which `a4-trn2` failed, now passes. One attempt cannot tell whether the header or chance did it.
- **All three runs:**
  - no 30-minute kills, no proxy rejections and no client cancels; the longest turn was ho2-t1 turn 6, 1,182 s;
  - every cache change explained and verification passed;
  - Strata's activity rising by exactly our upstream calls (177, 77 and 147).
  - On t1 and t2, the tap counted 1 foreign request between calls and none during a call, with Strata's total matching ours. This is R25-B's late-counted request.
- **The notes behaved as under n2.**

  | | ho2-t1 | ho2-t2 | ho2-t5 |
  |---|---|---|---|
  | Refreshes (committed / failed) | 20 (19 / 1 empty) | 7 (6 / 1 tool call) | 14 (14 / 0) |
  | Share of wall time | 18% | 16% | 15% |

  Every committed version had all six sections, except one t1 version without "Dead ends".

**R40-C. Reading.**
- **Header h2 does not reduce live early stops.** Two attempts give the same rate as n2's single one. R38-E measured the sentence on 7 prompts chosen because they had stopped, against the unchanged form of the same prompts. The live runs cover all 120 questions, and there the effect does not show. h1 stays the default (D75); h2 has no recall case.
- **On ho2 the notes arm now passes every task, and costs 8–17 needles.**
  - Tasks: `a4-trn2h` passed 5 of 5 tasks, with 14 of 15 constraints held. R32's arm 4 passed 2 of 5, and native compaction 4 of 5 with 12 of 15 constraints.
  - Recall: needles are 102–111 against 119 without notes. The loss is the sampling-driven early stop of R38-C, on answers the notes put in view.
- **Next decision (the user's):** what goes to a fresh held-out set.
  - `a4-trn2` or `a4-trn2h` as is, accepting the needle cost.
  - Or a change aimed at the early stop first. The proxy sets no sampling parameters (R38-D), so the options are a harness-side temperature or a change in how the notes shape the answer turn, and either is a new decision.

## R41 — D77 held-out run: `a4-d77` on ho3 (2026-11-04/05, pythia, held-out per D77)

**Outcome: every D77 gate passes.**
- **Needles: 115/120 loose exact (95.8%)**, against the 85% bar.
- **Coding: `a4-d77` 5/5, arm 1 (native compaction) 4/5.** `ho3-t3` passed under `a4-d77` with its key constraint held.
- **Archives:** every `a4-d77` archive has clean D44.6 inputs.
- **Comparability:** nothing was waived or rerun. Per D77.7 this judges `a4-d77` on fresh data at 32K on pythia (Strata 0.1.54, D76), and no number here is evidence against a Zeus run.

Commit `f2bd688`, clean tree on pythia, real OpenCode 2.1.4. Needles ran first (one attempt, 113.6 min wall), then the tasks in D77.8's order from 14:16Z on 11-04 to 02:54Z on 11-05. Records on pythia: `~/runs/d77/needles/records/attempt-001/` and `~/runs/d77/tasks/records/attempt-001..010/`, with logs `~/runs/d77/needles.log` and `tasks.log`.

**R41-A. Needle gate (D44.4).**

| Arm | Loose exact | 95% Wilson | History-clustered bootstrap | Strict exact | Needle in view / excerpt / absent | Exact when absent | Lookups (questions) | Prompt / completion tokens | Upstream calls |
|---|---|---|---|---|---|---|---|---|---|
| `a4-d77` | **115/120 (95.8%)** | 90.6–98.2% | 93.3–98.3% (10,000 resamples, seed 44) | 113 | 91 / 29 / 22 | 22/22 | 41 (22) | 5.56M / 162K | 298 |

- **Categories:** identifier 23/24, vague 23/24, mid_task 9/12. irrelevant_matches, multi_fact, oversized_read, restart_multi_eviction and superseded were all 12/12.
- **All 5 loose misses gave the right value with extra text.** There were no empty answers, nothing cut short and no wrong values. The upstream early stops of R36–R40 did not occur: 0 here, against 20/240 for `a4-trn2h` on ho2 (R40). Host, Strata build and set all differ from R40, so the drop is not attributable to any one of them.
  - In each miss, the model first did workspace work and then explained:
    - three `mid_task` questions (ho3-h2, h7 and h12, q7) answered `38`, `950` and `125`, each followed by a note about the failing test;
    - ho3-h1 q2 wrote the branch name to a file before quoting it;
    - ho3-h3 q10 made 5 workspace tool calls and appended the old name.
  - This is R39's return to the coding task, seen 5 times in 120 questions.
- **The 2 strict-only misses** (ho3-h3 q2 and h11 q2) were the branch name in backticks.
- **Gate inputs:**
  - `--explain` exit 0 with 286/286 pairs explained, `transcripts verify` 12/12, and 0 over-budget inputs;
  - leak scans: 0 leaks and 0 echoes over 144,312 client texts and 516 transcript texts; the internal scan found 0 hard leaks and 0 model or harness mentions;
  - 0 hidden calls, 0 errored questions, 0 foreign requests during or between calls, and 0 view-disabled or unbounded forwards.

**R41-B. Coding gate (D44.5).** One attempt per task and arm. Constraints are given as held/3.

| Task | `a4-d77` | Arm 1 (native, `limit.context` 32768) |
|---|---|---|
| ho3-t1 | **pass**, 3/3 · 64 calls · 42 min · kills 0 | **fail**, 1/3 (C1, C2) · 207 · 150 min · kills 4, 1 `compaction.failed` |
| ho3-t2 | **pass**, 3/3 · 56 · 36 min · kills 0 | pass, 2/3 (C2) · 67 · 42 min · kills 0 |
| ho3-t3 (restart) | **pass**, 3/3, restart gate True · 103 · 61 min · kills 0 | pass, 3/3, restart gate True · 161 · 79 min · kills 1, 1 `compaction.failed` |
| ho3-t4 | **pass**, 3/3 · 53 · 33 min · kills 0 | pass, 3/3 · 175 · 98 min · kills 2 |
| ho3-t5 | **pass**, 3/3 · 84 · 60 min · kills 0 | pass, 3/3 · 249 · 156 min · kills 4, 1 `compaction.failed` |
| Total | **5/5, 15/15 constraints** · 360 calls · 6.0M prompt tokens · 0 kills | 4/5, 12/15 · 859 calls · 11.4M prompt tokens · 11 kills |

- **Arm 1's failures on t1, t3 and t5:**
  - each ended an OpenCode turn with exit 1 and `compaction.failed`, "Compaction summary reached the output token limit" on t1 and "Compaction produced no summary" on t3 and t5;
  - every upstream call in those turns returned 200 with no proxy errors, so each is a task outcome, not an infrastructure failure (D44.7), and the session went on, as on ho-t1 (R25);
  - arm 1 made 154 compaction calls in all.
- **`a4-d77`:**
  - its largest input was 24,228 tokens, under the 24,320 budget, with 0 over-budget inputs;
  - `--explain`, verification and the leak scans were clean on all five archives;
  - its longest turn was 1,796 s on ho3-t3, inside the 30-minute limit.
- **Neither arm:** had proxy rejections. The tap counted 2 foreign requests between calls on ho3-t1 arm 1, which is not a gate input for arm 1.

**R41-C. Reading.**
- **The working-notes arm generalizes to a fresh set.** On ho3, `a4-d77` passed every task with every constraint, using 42% of arm 1's upstream calls and 53% of its prompt tokens, with no 30-minute kills against arm 1's 11.
- **The needle cost from ho2 did not show here.** That cost was 102–111/120 with 7–13 early stops. Recall stayed at 115/120, and the misses that remain are the arm returning to the coding task.
- **What one run cannot say:** one attempt per task and arm, and one needle attempt. pythia's slower decode (D76) puts more pressure on arm 1's turns than Zeus did.
- **Next:**
  - Making `a4-d77`'s settings the shipped default is a separate decision.
  - The extra-text misses are the one recall failure left to look at, on development data.

## R42 — Phase 3 gate summary, second: accepted on the shipped configuration (2026-11-05)

**Outcome: Phase 3 is accepted.**
- R27 left one A1 green light unmet, held-out recall and coding. R41 met it on the fresh set ho3 with `a4-d77`, which `serve` has shipped since D78.
- The acceptance reviews of everything changed since S12 found no blocker, and their should-fix findings are fixed (D79).
- The `phase-3` tag is applied to the commit that lands D79 and this entry.

Code: the D79 commit. Full suite on pythia: 1694 passed, 1 skipped (a Windows-only transcript test, `test_transcripts.py`).

| A1 green light | Evidence | Status |
| --- | --- | --- |
| Excerpt sets and renderings survive requests and restarts; inclusion follows the view policy; excerpts never visible to the harness; allocations fit the budget; retrieval covers spans evicted now; lossless payloads and rebuild; consistent generations across crashes; the first harness reads transcripts; oversized reads narrowed; tool-step reasoning correct; selection latency | As R27; their tests still pass. On R41's archives: 0 over-budget inputs, 0 leaks, `transcripts verify` 12/12 needle histories and all five tasks | Met |
| Held-out recall and coding meet O1 | R41 (D77, ho3, 32K, pythia): needles 115/120 loose exact (95.8%, Wilson 90.6–98.2%) against ≥ 85%; coding `a4-d77` 5/5 against arm 1's 4/5 (gate: ≥ arm 1); restart task ho3-t3 passed with its key constraint | **Met** (R27: not met) |
| Every cache change explained | R41: `--explain` 0 unexplained on all six `a4-d77` archives. The corrected `state_refresh` rule (D79.2) re-labels 14 refresh pairs; each was checked against the exact bodies and is an allowed cause | Met |
| Reviews | Protocol, cache and paper-fidelity reviews of `9482265..455be60`: no blocker. Should-fix: notes slot missing from admission and the floor; `state_refresh` given without the extension check; wrong-shape refresh events recorded `cancelled`; a refresh that could not fit left no record; refresh failures did not mark the facts stale; papers.md out of date for D70, D71 and D72. All fixed test-first (D79) | Met |

**What acceptance covers:**
- Evidence: one attempt per task and arm and one needle attempt, on one host (pythia, D76), one model (the pinned Strata build) and one harness (OpenCode 2.1.4), at 32K.
- `capabilities.md` "Known limits of Phase 3" lists what stays open: the per-collapse refresh cost, the fixed notes slot at small budgets, extra-text recall answers, lexical retrieval and transcript lookup overhead.

**Carried forward from R27:**
- The evaluation-tooling items.
- Deferred by design: Ph4B admission and harnesses, 3B continuation accounting and RE2 search.

**Next:** Phase 4B (harness expansion: Anthropic Messages archive mode, Pi, Claude Code), and a decision on how working notes relate to Phase 4A's pinned state.
