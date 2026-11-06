# Phase 4B results

## R43: Pi 1.5.0 live through Palimnesis (S13, 2026-11-05)

- **Setup:** Pi 1.5.0 on Windows with the shipped adapter (`integrations/pi/`) and a throwaway agent directory, talking to `palimnesis serve` (serve defaults, `a4-d77`) on the same machine. Its upstream was Strata 0.1.54 on pythia (32K, one slot) through an SSH tunnel.
- **Commit:** after `62e554a`, with the D93 accounting rule.
- **Driver:** `eval/probes/pi_live_smoke.py smoke gate`. Summary in `eval/probes/fixtures/pi-1.5.0/live/summary.json` (paths replaced).

| Scenario | Turns | Requests | Answer | `--explain` unexplained | `transcripts verify` | Failed attempts | View moves |
|---|---|---|---|---|---|---|---|
| smoke, Chat | read `notes.txt`, then a follow-up | 3 | "Thursday" both turns | 0 | pass | 0 | 0 |
| smoke, Messages | the same | 4 | "Thursday" both turns | 0 | pass | 0 | 0 |
| gate, Chat, budget 8,000 | read 4 logs (about 5K tokens each), delete `log1.txt`, ask for its code, then confirm from the transcript | 14 | `ZX-4471-QUAIL`; confirmed by Pi's `grep` on the session directory (`turn-0001.md:114`) | 0 | pass | 0 | 5 |

- **How the code was answered.** In the gate, the code came from a proactive excerpt (one selected block held it). The confirming turn then reached the transcript files with Pi's own `grep`, which is the capability the gate checks (D37's criterion).
- **The first gate run** found one unexplained pair, a main call right after its own notes refresh. D93 explains it and adds the rule; both runs above are after the fix.
- Turn times were 4–85 s; the longest were the 5K-token file reads with thinking.

## R44: Pi's faults, cancellation and restarts through Palimnesis (S14, 2026-11-05)

The plan §6 gates for fault runs, restart and cancellation. All runs are after D94, at `d573f54` plus this slice.

**Fault runs** (`eval/probes/pi_probe.py hx_*`, summarized by `eval/probes/pi_proxy_faults.py`; `eval/probes/fixtures/pi-1.5.0/live/proxy_faults.json`):
- Setup: Pi 1.5.0 with the adapter's compat flags and its own default timers, then `palimnesis serve` in archive mode, then the Pi fault server. The fault server has no `/props`, so bounded views stay off; the archive, stream, error and admission paths are what these runs exercise.
- Scenarios: the twelve HP4 scenarios on both protocols, and the partial ones also with Pi's retry off. That is 34 runs, all passing.
- **No silent duplicate generation:** at most one completed attempt per archived request in every run.
- **Statuses** (500, 429, 503 with `x-should-retry: false`). Pi retries anyway (HP4.2). The proxy records the failed attempt and then completes the same request: one request, two attempts, one generation.
- **Partial streams** (EOF, reset, upstream error, tool-call error). The proxy ends the stream with its in-stream error, and Pi does not retry. Pi's next turn leaves the partial out, and the archive supersedes it (O-4B-5).
- **Length stop:** see D94. All four runs pass after the fix.
- **Header delay 8 s and 12 s of comments** with Pi's default 300 s timers: one request each, success.
- **`finish_no_done`** (a finish chunk, then EOF with no `[DONE]`): both turns fail through the proxy, by contract §3. Strata always sends `[DONE]` (`docs/probes/strata.md` §13.1), so this is a fault-server shape; it is listed as expected, not a defect.

**Cancellation** (`eval/probes/proxy_cancel_release.py`; `proxy_cancel_release.json`): a client disconnect through the proxy against Strata 0.1.54 on pythia, three trials each.

| Close point | Release (Strata `/status` free) | Archive |
|---|---|---|
| Decode, after about 40 content pieces | 0.17–0.27 s | `cancelled` ×3 |
| Prefill, 3 s into a prompt of about 12K tokens | 6.95–7.00 s | `cancelled` ×3 |

Decode is under contracts §8's 1 s. Prefill releases at the end of the current 8,192-token chunk, as Strata cancels only at chunk boundaries (`docs/probes/strata.md` §9).

**Restart** (`eval/probes/pi_live_smoke.py restart`; `restart.json`): Pi on Chat with a budget of 8,000. The proxy restarted after each of three 5K-token file reads, and a last turn asked for the code from the first file, which had been deleted.
- Pi answered `ZX-4471-QUAIL`.
- 11 requests and 3 view moves; no failed attempts.
- `--explain` 0 unexplained: each call after a restart is explained by re-rendering the previous call (D14.8).
- `transcripts verify` passes.

## R45: Pi's development needles through Palimnesis (S14, 2026-11-05, development data, reported, not gated, per D81.6)

**Outcome: 42/60 loose exact (70%).** 14 of the 18 misses are answers the model cut short. Every archive and accounting check is clean.

- **Setup:** `eval/needle.py run --driver pi --protocol chat --config a4-d77 --set development`, one attempt. Real Pi 1.5.0 ran on Windows with the shipped adapter. Strata 0.1.54 ran on pythia (32K, one slot) through the tunnel. The code was that of `bbcf570`, which includes the D97 fix. The first attempt stopped at dev-h1 Q4 with the 409 D97 fixes; this is the rerun.
- **Records:** `C:/Users/Daniel/palimnesis-runs/pi-dev-needles-chat2/` (records, 107 upstream bodies) and its `.log`. Wall time was 83.7 min.

| Loose exact | 95% Wilson | History-clustered bootstrap | Strict exact | Needle in view / excerpt / absent | Exact when absent | Lookups | Early stops | Prompt / completion tokens |
|---|---|---|---|---|---|---|---|---|
| 42/60 (70%) | 57.5–80.1% | 45.0–91.7% | 34 | 47 / 46 / 2 | 0/2 | 0 | 14 | 1.95M / 27K |

- **Per history:** dev-h2 and dev-h4 scored 10/10 and dev-h3 9/10 (h3 q7 was the right value with extra text, as in R41). dev-h1 scored 6/10, dev-h5 3/10 and dev-h6 6/10. The early stops all fall in these three histories.
- **The other misses:** h5 q8 and h6 q8 (`multi_fact`) gave wrong values with the needle out of both the view and the excerpts. Pi did not search its transcript directory for either, although it did in R43's gate. OpenCode answered all 22 of its absent needles in R41, with 41 lookups.
- **Gate inputs, all clean:**
  - `--explain`: 101/101 pairs explained, 0 unexplained;
  - `transcripts verify`: 6/6;
  - over-budget inputs, view-disabled events, unbounded forwards and errored questions: 0 each;
  - leak scans: 0 leaks and 0 echoes over 40,697 client and 258 transcript texts; 0 internal hard leaks;
  - 0 hidden calls and 0 foreign requests.
- **D97's empty-reply rule held live.** dev-h1 P2 again got a reasoning-only reply, and Pi's next request left it out without a 409.

**R45-A. The early stops: a cascade from one cut answer.** Each of the three histories starts with one cut answer, `1` for `1.25s` (h1 q4), `fix/quillctl-config-` (h5 q2) or `6` for `6.0s` (h6 q4). Most answers after it in the same session are cut the same way, all finishing `stop`: `2` for `22s`, `9` for `9299`, `r` for `r2026.10.19-hf5`. This is D97.2's finding, now seen across a whole run. Exact upstream bodies were replayed directly to Strata, with no proxy, and sent unchanged except where a form says otherwise. Scripts and data are in the session scratchpad, `r45/` (`ablate.py`, `ablate-r45*.json`).

| Prompt | Pi's request | No `reasoning_effort` | OpenCode 2.1.4's system prompt | Pi's prompt without "Be concise in your responses" |
|---|---|---|---|---|
| h1 q4, the first cut | 3/14 cut | 2/6 | 1/6 | not run |
| h1 q5, after `1` in history | 6/6 | 4/6 | 5/6 | not run |
| h5 q2, the first cut | 2/8 | not run | 0/8 | 0/8 |
| h6 q4, the first cut | 5/8 | not run | 2/8 | 4/8 |

- **The cascade does not depend on the prompt.** Once a cut answer is in the history, the next answer is cut in 4–6 of 6 calls under every form. When the earlier cut answer was corrected in the history, the next answer came back whole (D97.2).
- **Pi's system prompt may raise the first cut, but the evidence is weak.** On h5 q2 and h6 q4 together it cut 7 of 16 calls, against 2 of 16 with OpenCode's system prompt (Fisher p ≈ 0.11). Removing only Pi's "Be concise in your responses" rule gave 4/16. h1 q4 cut at about the same rate under every form. Effort is not the cause: Pi sends `reasoning_effort: medium` and OpenCode sends none, and neither form changes the rate.
- **Why R41 saw none of this:** R41 ran OpenCode on ho3, a different set, so the two runs cannot be compared. An OpenCode run on the development set would separate the harness from the set; it was not run.
- **What Palimnesis can and cannot do here:** the proxy sets no sampling parameters and does not rewrite the client's history (R38-D, D75). The cut answer is the model's own reply, which Pi resends verbatim. This is recorded as a model behaviour on Pi's sessions, as D97.2 decided. Two follow-ups are backlogged, neither tried here: a harness-side temperature, and an OpenCode development-set run.

## R46: Where the wall-clock gain over native compaction comes from (2026-11-05)

**Outcome.** Palimnesis's tasks finish sooner because native compaction makes the model do extra work, not because any call runs faster:
- **On both harnesses, most of the gap is the model writing summaries:** 57% for OpenCode and 55% for Pi.
- **The second cause differs by harness:**
  - **OpenCode** (31% of the gap): more task work, with more than twice as many task calls.
  - **Pi** (35% of the gap): re-reading prompts whose cached start each compaction rewrote.

**Method.** `eval/wall_split.py` reads Strata's per-call `timings` from each run's recorded responses:
- `prompt_ms` covers the uncached tokens prefilled, and `predicted_ms` covers decoding.
- It splits them between task calls and compaction calls. Compaction calls are OpenCode's compaction requests, Pi's summarizer, and Palimnesis's working-notes refresh (D72).
- Per run, the four parts add up to the run's upstream time, which matches its recorded latency to within a few percent (tool execution is the rest).
- The data are in `eval/fixtures/wall-split/`.

**R46-A. OpenCode 2.1.4, held-out `ho3` (the R41 runs, pythia, 32K).** Totals over the five tasks, in seconds of upstream time:

| | `a4-d77` | Arm 1 (native) | Extra on arm 1 | Share of the gap |
|---|---|---|---|---|
| Compaction or notes calls, decode | 2,326 | 11,951 | 9,625 | 57% |
| Task calls, decode | 8,740 | 13,906 | 5,166 | 31% |
| Task calls, prefill | 2,379 | 3,733 | 1,354 | 8% |
| Compaction or notes calls, prefill | 343 | 1,038 | 695 | 4% |
| **Upstream total** | **13,788** | **30,628** | **16,840** | |

- **Summaries:** arm 1 made 148 compaction calls that wrote 541,523 tokens. `a4-d77` made 42 notes refreshes that wrote 96,884 tokens. Decoding them took 3.3 hours against 0.6.
- **More task work:** arm 1 made 700 task calls that generated 577,670 tokens, against 318 calls and 361,370 tokens. Arm 1 also had 11 turns killed at the 30-minute limit, against none. Which calls re-did earlier work was not measured.
- **Prompt cache:** this is not where OpenCode's gain comes from. The cache hit rate was 86% on arm 1 and 80% on `a4-d77`, and prefill is 12% of the gap.

**R46-B. Pi 1.5.0, development tasks dev-t1 and dev-t2 (Chat).** These are the two tasks with both arms complete at the time. Arm 1 keeps 8,192 recent tokens (D99).

| | `a4-d77` | Arm 1 (Pi's compaction) | Extra on arm 1 | Share of the gap |
|---|---|---|---|---|
| Compaction or notes calls, decode | 246 | 2,375 | 2,129 | 55% |
| Task calls, prefill | 586 | 1,917 | 1,331 | 35% |
| Task calls, decode | 964 | 1,179 | 214 | 6% |
| Compaction or notes calls, prefill | 104 | 286 | 182 | 5% |
| **Upstream total** | **1,899** | **5,756** | **3,857** | |

- **Summaries:** Pi made 38 summarizer calls that wrote 110,434 tokens. `a4-d77` made 6 notes refreshes that wrote 10,138 tokens.
- **Re-reading:** each Pi compaction rewrites the start of the prompt, so the next call prefills it again. The cache hit rate was 61–63% on arm 1 against 83–84%. Palimnesis changes the prompt's start only at its watermark moves; between them, each request extends the cached prefix.
- **Caveat:** the compaction count follows D99's setting. A larger `keepRecentTokens` would compact less often but leave less room per turn at 32K.

**Reading.**
- The model's speed is the same on both arms; the difference is how much it is asked to write and re-read.
- Masking with exact recall needs no summary of what it hides. Palimnesis's one summary-like cost, the working notes, is written only when old turns actually leave the view, and is short.

## R47: Pi's development coding tasks on Chat, arm 4 against Pi's own compaction (S14, 2026-11-05/06, development data, reported, not gated, per D81.6)

**Outcome: `a4-d77` passed 5/5 with every constraint held, in 162 upstream calls and 62 minutes. Pi's own compaction (arm 1) passed 4/5, held 13/15 constraints, and took 322 calls and 4.9 hours.** This repeats R41's OpenCode result on a second harness, on development data with one attempt per task and arm.

- **Setup:**
  - Real Pi 1.5.0 on Windows with the shipped adapter, through `eval/tasks/run.py --harness pi --protocol chat`.
  - Strata 0.1.54 on pythia at 32K, one slot, through an SSH tunnel.
  - Arm 4 is `a4-d77` through `serve`. Arm 1 is `--passthrough` with Pi's compaction on, `contextWindow` 32,768 and `keepRecentTokens` 8,192 (D99).
  - Tasks ran in order, arm 4 first, from 18:36 on 11-05 to 01:37 on 11-06. Records: `C:/Users/Daniel/palimnesis-runs/pi-dev-tasks-chat2/records/attempt-001..011`, tag `pi-r46b`.
- **Code:**
  - dev-t1 arm 4 ran at `446a308` (D98, D99).
  - Every later run ran `f3786fb`'s `src/` (D100). dev-t1 arm 1 started from the working tree minutes before that commit, with the same `src/`. D100 changes only rare paths (a retry inside a failed handler's tail, empty replies a client resent, transcript labels), and none of them occurred in these runs: 0 proxy rejections.
- **Excluded:**
  - The first arm 1 attempt at dev-t1 ran with Pi's default `keepRecentTokens` and never compacted (D99). It is attempt 2 of the earlier directory `pi-dev-tasks-chat`.
  - dev-t3 arm 1's attempt 6 stopped at turn 6 when the client laptop slept and the tunnel dropped. Its rerun, attempt 7, records the reason. The rerun's reason text says "memory cleanup"; the client misreported the sleep as a memory shortage.

| Task | `a4-d77` | Arm 1 (Pi's compaction) |
|---|---|---|
| dev-t1 | **pass** 4/4, constraints 3/3 · 38 calls · 20 min | pass 4/4, 2/3 · 63 calls · 46 min · 13 compactions |
| dev-t2 | **pass** 4/4, 3/3 · 30 · 12 min | pass 4/4, 3/3 · 59 · 52 min · 15 compactions |
| dev-t3 | **pass** 3/3, 3/3 · 30 · 10 min | **fail** 2/3, 3/3 · 97 · 114 min · 25 compactions · 1 turn killed at 30 min |
| dev-t4 (restart) | **pass** 4/4, 3/3, restart gate True · 34 · 11 min | pass 4/4, 3/3, restart gate True · 34 · 13 min · 4 compactions |
| dev-t5 | **pass** 3/3, 3/3 · 30 · 9 min | pass 3/3, 2/3 · 69 · 68 min · 17 compactions |
| **Total** | **5/5, 15/15 · 162 calls · 62 min · 0 kills** | 4/5, 13/15 · 322 calls · 4.9 h · 1 kill |

- **Gate inputs on every `a4-d77` archive:**
  - `--explain` with 0 unexplained;
  - `transcripts verify` passing;
  - 0 over-budget inputs and 0 view-disabled events;
  - 0 leaks and 0 echoes in the client and transcript scans.
  - The largest input was 23,839 tokens, under the 24,320 budget.
- **Arm 1:** 0 proxy rejections; every turn's calls returned 200.

**R47-A. Where arm 1's extra time went** (`eval/wall_split.py`, all five pairs; this extends R46-B). Seconds of upstream time:

| | `a4-d77` | Arm 1 | Extra on arm 1 | Share of the gap |
|---|---|---|---|---|
| Compaction or notes calls, decode | 383 | 7,082 | 6,699 | 49% |
| Task calls, prefill | 1,247 | 5,300 | 4,053 | 30% |
| Task calls, decode | 1,751 | 3,843 | 2,092 | 15% |
| Compaction or notes calls, prefill | 279 | 974 | 695 | 5% |
| **Upstream total** | **3,661** | **17,199** | **13,538** | |

- **Summaries:** Pi made 89 summarizer calls that wrote 335,270 tokens. `a4-d77` made 10 notes refreshes that wrote 15,553.
- **Prompt cache:** the hit rate was 63% on arm 1 against 85%.
- **Task work:** arm 1 made 230 task calls against 152.

**Reading.**
- On Pi, as on OpenCode, the archive and bounded view finished every task without the summary cost. Arm 4 had no task failures and no killed turns.
- Arm 1's one failure, dev-t3, ran 25 compactions and hit the 30-minute turn limit once.
- One attempt per task on development data shows direction, not effect size. The Messages cells and the ho2 tasks follow in later entries.

## R48: Pi's development needles on Messages (S14, 2026-11-06, development data, reported, not gated, per D81.6)

**Outcome: 51/60 loose exact (85.0%)**, against 42/60 on Chat (R45). Every archive and accounting check is clean.

- **Setup:** as R45, with the `palimnesis-messages` provider (`--protocol messages`), from 01:37 to 02:38 on 11-06 (61 min). The proxy ran `f3786fb`'s `src/`. Records are in `C:/Users/Daniel/palimnesis-runs/pi-dev-needles-msg/`, tag `pi-msg-r45`.

| Loose exact | 95% Wilson | History-clustered bootstrap | Strict exact | Needle in view / excerpt / absent | Exact when absent | Lookups | Early stops | Prompt / completion tokens |
|---|---|---|---|---|---|---|---|---|
| 51/60 (85.0%) | 73.9–91.9% | 73.3–95.0% | 36 | 50 / 35 / 1 | 1/1 | 1 | 3 | 2.01M / 27K |

- **Categories:**
  - 6/6: multi_fact, oversized_read, restart_multi_eviction and superseded.
  - identifier 11/12, irrelevant_matches 5/6, vague 9/12, mid_task 2/6.
- **Misses:**
  - 3 early stops, each a value without its unit: `1.25` for `1.25s` and `22` for `22s` (h1), and `30` for `30s` (h4).
  - The `mid_task` misses are the right value followed by a note about the failing test, as in R41.
- **Strict against loose:** strict exact is 36 because Pi on Messages wrapped most answers in backticks, such as `` `"4.25s"` ``.
- **Gate inputs, all clean:**
  - `--explain`: 106/106 pairs explained, 0 unexplained;
  - `transcripts verify`: 6/6;
  - over-budget inputs, view-disabled events, unbounded forwards and errored questions: 0 each;
  - leak scans: 0 leaks and 0 echoes over 50,650 client and 258 transcript texts; 0 internal hard leaks;
  - 0 hidden calls and 0 foreign requests.
- **Why Chat stopped early more often (14 against 3) is not established.**
  - Both protocols reach Strata as the same Chat request: the same system prompt apart from the workspace path, the same tools, and the same `reasoning_effort`. User text arrives as a string from Messages and as text parts from Chat, which render the same tokens (D91.1).
  - The two runs are separate sessions, though, and their views diverge. At h1 q4, for example, Chat still showed two file reads in full where Messages showed stubs, and the working notes differ.
  - Early stops cascade within a session (R45-A), so a single first cut changes a history's count by several.
  - This is consistent with run-to-run variation. It is no evidence that the protocol matters.
