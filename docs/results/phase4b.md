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

## R49: Archive size and how it grows (2026-11-06)

**Outcome.** An archive grows roughly linearly with requests and output tokens, plus one quadratic term from periodic full snapshots of the request body. At the pace of the ho2-t2 run (about 700 output tokens and 3.7 KB of new request body per request), it reaches about 7 MB at 100 requests, 45 MB at 500 and 117 MB at 1,000.

**Method.** `eval/archive_size.py` reads an archive read-only and reports bytes per table (`dbstat`), row counts, and the raw request bodies' logical and stored sizes. It was run on the nine `a4-d77` Pi task archives from R47 and the ho2 Chat runs (28–140 requests, 1.4–10.2 MB each).

**Where the bytes go** (ho2-t2, 140 requests, 10.2 MB):

| Part | Bytes | Share | Grows with |
|---|---|---|---|
| Delivery events (`delivery_progress` and the rest) | 4.05 MB | 40% | streamed reply chunks |
| Reply text rows and their index (`segments` + autoindex) | 3.02 MB | 30% | streamed reply chunks |
| Raw request bodies (5 snapshots + 135 deltas) | 1.92 MB | 19% | requests, and history size at each snapshot |
| Full-text index (`fts_*`) | 0.48 MB | 5% | archived text |
| Everything else (occurrences, requests, notes, views, schema) | 0.75 MB | 7% | requests |

- **Replies are stored per streamed chunk.** Each chunk costs 284 bytes on average across the nine archives (272–312): its text row, its index entry and its delivery event. A chunk carries about 4 tokens (98,246 output tokens in 24,577 chunks on ho2-t2), so this is about 71 bytes per output token. The text itself is about 10 bytes of each chunk.
- **Request bodies are stored as deltas.** The agent sent 39.6 MB of request bodies over ho2-t2; the archive stored 1.9 MB, about 5%. A full snapshot is taken every 33 requests (one snapshot, then at most 32 deltas, `rawdelta.py`), and the snapshots are 1.31 MB of the 1.92 MB.
- **What the agent adds is stored once.** Tool results and user messages were 147 rows and 201 KB.

**Model.** For a session of N requests whose request body reaches L bytes, with O output tokens and T bytes of archived text:

```
size ≈ 200 KB + N · 8.3 KB + 71 B · O + 1.0 · T + N · L / 66
```

- 200 KB is the schema and fixed tables. 8.3 KB per request is 3.9 KB of bookkeeping plus about 4.4 KB of body delta. T is counted once more for the full-text index.
- N · L / 66 is the snapshots: about N/33 of them, at half the final body size on average when the body grows steadily. With L = h · N for a body that grows by h bytes per request, this is h · N² / 66, the one term that grows faster than linearly.

| Archive | N | Output tokens | Predicted | Actual | Error |
|---|---|---|---|---|---|
| dev-t1 | 34 | 29,040 | 2.81 MB | 3.09 MB | −9% |
| dev-t2 | 28 | 19,163 | 1.99 MB | 2.34 MB | −15% |
| dev-t3 | 29 | 10,754 | 1.31 MB | 1.41 MB | −7% |
| dev-t4 | 32 | 13,080 | 1.55 MB | 1.58 MB | −2% |
| dev-t5 | 29 | 12,745 | 1.50 MB | 1.69 MB | −11% |
| ho2-t1 | 39 | 37,704 | 3.50 MB | 3.42 MB | +2% |
| ho2-t2 | 140 | 98,246 | 9.88 MB | 10.22 MB | −3% |
| ho2-t3 | 79 | 72,346 | 6.81 MB | 6.63 MB | +3% |
| ho2-t4 | 51 | 55,572 | 5.14 MB | 6.08 MB | −15% |

**Projection** at ho2-t2's per-request rates (700 output tokens, 3.2 KB of archived text, body growth h = 3.65 KB per request), so about 61 KB per request plus 55 · N² bytes of snapshots:

| Requests | Agent's history | Linear part | Snapshots | Archive |
|---|---|---|---|---|
| 100 | about 90K tokens | 6.1 MB | 0.6 MB | about 7 MB |
| 500 | about 460K tokens | 30.6 MB | 13.8 MB | about 45 MB |
| 1,000 | about 910K tokens | 61.2 MB | 55.4 MB | about 117 MB |
| 2,000 | about 1.8M tokens | 122 MB | 221 MB | about 344 MB |

- History tokens assume about 4 bytes per token. ho2-t2 ran 140 requests in 72 minutes, so 1,000 requests is about 8.5 hours of agent work in one session.
- Separate sessions are independent and add up.
- Not counted: the transcript files, which are written beside the database.
- **The levers, not acted on here:**
  - Storing replies per batch instead of per chunk would remove most of the 70% that events and text rows take.
  - Snapshotting by bytes instead of every 33 requests would bound the quadratic term.

## R50: Strata 0.1.57 counts exactly as the pin (2026-11-06)

**Outcome.** Strata 0.1.57, the latest stable release, renders and counts every recorded case exactly as the pin does, and Palimnesis accepts it with bounded views on (D102). The first run found one gap: Strata's `/props` leaves out `build_info` when its engine reports no version, and Palimnesis refused such a server as unreadable. `build_info` is now optional.

**Setup.** pythia's Strata 0.1.54 stayed untouched because the Pi evaluation and other work use it. Strata Control 0.1.57 for macOS arm64 (`strata-control-0.1.57-macos-arm64.tar.gz` from the v0.2.11 release, SHA-256 `e61f9906…` matching the release's `SHA256SUMS.txt`) ran on mbp in mock mode (`serve.server --engine mock`) with the model's tokenizer copied from pythia's pack (`packs/iq3_xxs/tokenizer`, 9.5 MB). Strata's `count_tokens` renders and tokenizes in Control without running the model, and the mock's `usage.prompt_tokens` comes from the same prompt encoding, so this tests what Palimnesis depends on: the template, the message preprocessing and the token counts. The engine and generation were not tested.

**Results.**

| Check | Result |
|---|---|
| `/props` template | sha `12827f24…`, equal to the pin. `n_ctx` 32,768. No `build_info` (mock engine). |
| `palimnesis check` before the fix | FAIL: `GET /props malformed: KeyError('build_info')`, so bounded views would be off |
| `palimnesis check` after the fix | PASS upstream, PASS bounded views (`canary`: 7 of 7 cases match) |
| Counting probes against recorded counts | 209 of 209 equal: 19 `count_tokens` (p04), 10 normalization (p12), 174 literal-tag (p14), 6 NFC (p15). p04's error case gives the same 400. The other two recorded `count_tokens` cases are canary cases, which also matched |
| Through the proxy | streamed Chat Completions and Anthropic Messages requests return 200 and are archived (`palimnesis catalog`) |

**What this does not show.** The real 0.1.57 engine was not run, so speed, generation, cancellation and the slot release time (D76) are not measured. The real engine reports a version, so its `/props` would carry `build_info: "Strata 0.1.57"`.

## R51: Wire shapes of Strata 0.1.57, and LM Studio behind the proxy (2026-11-06)

**Outcome.** Strata 0.1.57 sends the same responses as 0.1.54 in all 23 cases of a new shape probe, directly and through the proxy, and one error message has new wording. LM Studio, the first server other than Strata tried behind Palimnesis, works with bounded views off: Pi completed a small task through the proxy on Chat Completions and on Anthropic Messages, and the exchanges were archived. `palimnesis check` called LM Studio unreachable, and now says it answers but is not Strata.

**Shape probe.** `eval/probes/p27_release_shapes.py` sends 23 fixed requests: streamed and non-streamed text and tool calls on both protocols, `count_tokens`, malformed and empty bodies, context overflow, an unknown route, and the status endpoints. It records the status, the content type and a skeleton of each body or event stream: keys and types, with enum values kept and ids reduced to their prefix. Error messages are recorded verbatim. `--compare` diffs two runs.

- Strata Control 0.1.54 and 0.1.57 for macOS (both SHA-256 checked against their releases) ran side by side on mbp in mock mode, with the model's tokenizer and the same two scripts in turn: reasoning then text, and reasoning then a tool call. Mock mode replays the script through Strata's real tokenizer, reasoning and tool-call parsers and stream writers.
- **Direct:** 0 of 23 cases differ in shape or event counts. One message changed: a Messages context overflow now starts `prompt is too long: 40052 tokens > 32759 maximum;` before the old text. Palimnesis matches `exceeds the context window`, which is still there. The new prefix is Anthropic's own wording, which agents may treat as an overflow; through the proxy the agent never sees it, because the proxy refuses an over-budget request itself.
- **Through the proxy,** one session per case: 0 of 23 differ between the two versions. Against direct, the 8 generating cases are identical. The other differences are the proxy's own error bodies (it adds `code` and `param`, and Anthropic's top-level `"type": "error"`) and a 400 instead of a 404 for an unsupported route.

**LM Studio** (mbp, Qwen3.6 35B-A3B as `qwen36`, untouched by the test):

- It answers every route it does not know with 200 and `{"error": ...}`, including `/props` and `/v1/messages/count_tokens`. Palimnesis reads that as facts it cannot use, so bounded views stay off and the upstream gets each request's exact bytes (`test_pin_mismatch_disables_the_view_but_still_archives`).
- `palimnesis setup pi --model qwen36` into a scratch agent directory, then Pi 1.5.0 through the proxy: on Chat it read a file and wrote the answer in 23 s (3 requests). On Messages the same task passed in 3 requests, and a second session answered from its own tool calls. Every exchange was archived (`delivery_completed` on each).
- One Pi run on Messages stalled for 10 minutes before sending any request, so it never reached the proxy. Rerun with stdin closed, it passed. That Pi waited on an open stdin is likely but unconfirmed.
- The probe against LM Studio directly and through the proxy cannot be compared case by case, because a real model answers differently each time (one direct call spent all 200 tokens reasoning). Event kinds match where both runs ended the same way.

**Not shown.** The real 0.1.57 engine (generation, speed, cancellation). Bounded views on any server other than Strata. OpenCode against LM Studio.

## R52: Pi's ho2 tasks on Chat and Messages, its development tasks on Messages, and TINY TANK WAR (S14, 2026-11-06/07, reported, not gated, per D81.6)

**Outcome.**
- On Chat, `a4-d77` and Pi's own compaction (arm 1) both passed all five ho2 tasks with every constraint held. `a4-d77` took 439 calls and 3.9 hours against 466 calls and 9.3 hours.
- On Messages, both passed all five development tasks with every constraint held, in 1.4 hours against 5.0.
- On the Messages ho2 tasks, `a4-d77` passed 3/5 and arm 1 passed 4/5. The `a4-d77` failures were two coding mistakes the run records show the proxy did not cause, and one arm 1 pass broke two of three constraints. With one attempt per task, the difference is not separable from run-to-run variance.
- **Gate inputs on all 17 `a4-d77` task archives:** no count drift; `--explain` explained every cache change; `transcripts verify` passed; no over-budget input; no view disabled; 0 leaks and 0 echoes in the client and transcript scans.

**Setup.** As R47: real Pi 1.5.0 on Windows, Strata 0.1.54 on pythia at 32K with one slot through an SSH tunnel, one attempt per task and arm, `a4-d77` first. The ho2 set is retired held-out data (D96), run here as development data. Records are under `C:/Users/Daniel/palimnesis-runs/`:

| Set | Records | Tag | When |
|---|---|---|---|
| Chat ho2 | `pi-ho2-tasks-chat`, attempts 1–9 and 11 | `pi-r46-chat` | 11-06 02:38 to 15:15, and 11-07 13:01 |
| Messages development | `pi-dev-tasks-msg`, attempts 1–10 | `pi-r46-messages` | 11-06 15:29 to 21:54 |
| Messages ho2 | `pi-ho2-tasks-msg`, attempts 1–10 | `pi-r46-messages` | 11-06 21:54 to 11-07 11:50 |

- **Code.** The runs span commits `c82f6bc` to `17014cf`. Changes to `src/` in that window are D101 (`setup` and `check`), D102 (accepting Strata by its counts) and R50's optional `build_info`. Four runs started from a working tree with uncommitted edits (Chat ho2-t4 arm 1, Chat ho2-t5 `a4-d77`, Messages dev-t1 arm 1, Messages dev-t2 `a4-d77`), each listed in its `provenance`. Of those edits, only D102's touch the proxy, and D102 changes only how the upstream is accepted at start. Every run's records name Strata 0.1.54 with the pinned template, which D102 accepts as before. No change in the window touches views, recall or the archive.
- **Excluded.** Chat ho2-t5 arm 1, attempt 10, lost turn 4 when stopping the queue's wrapper task closed the driver's console, so Pi could not start (exit `0xC0000142`). Its rerun is attempt 11, run last, and it records the reason.
- **Turn limit.** 30 minutes, as in R47. "Kills" counts turns stopped there.

**Chat, ho2 tasks**

| Task | `a4-d77` | Arm 1 (Pi's compaction) |
|---|---|---|
| ho2-t1 | pass 4/4, 3/3 · 44 calls · 25 min | pass 4/4, 3/3 · 60 · 56 min · 17 compactions |
| ho2-t2 | pass 3/3, 3/3 · 153 · 72 min · 3 lookups | pass 3/3, 3/3 · 88 · 103 min · 25 compactions · 2 kills |
| ho2-t3 (restart) | pass 4/4, 3/3, gate True · 87 · 49 min | pass 4/4, 3/3, gate True · 136 · 178 min · 47 compactions · 4 kills |
| ho2-t4 | pass 4/4, 3/3 · 56 · 35 min | pass 4/4, 3/3 · 123 · 182 min · 47 compactions · 5 kills |
| ho2-t5 | pass 3/3, 3/3 · 99 · 53 min | pass 3/3, 3/3 · 59 · 41 min · 11 compactions (attempt 11) |
| **Total** | **5/5, 15/15 · 439 calls · 3.9 h · 0 kills** | 5/5, 15/15 · 466 calls · 9.3 h · 147 compactions · 11 kills |

**Messages, development tasks**

| Task | `a4-d77` | Arm 1 (Pi's compaction) |
|---|---|---|
| dev-t1 | pass 4/4, 3/3 · 37 · 15 min | pass 4/4, 3/3 · 31 · 12 min · 4 compactions |
| dev-t2 | pass 4/4, 3/3 · 41 · 20 min | pass 4/4, 3/3 · 105 · 133 min · 32 compactions · 4 kills |
| dev-t3 | pass 3/3, 3/3 · 44 · 17 min | pass 3/3, 3/3 · 41 · 22 min · 7 compactions |
| dev-t4 (restart) | pass 4/4, 3/3, gate True · 30 · 12 min | pass 4/4, 3/3, gate True · 59 · 34 min · 11 compactions |
| dev-t5 | pass 3/3, 3/3 · 52 · 20 min · 4 lookups | pass 3/3, 3/3 · 98 · 100 min · 28 compactions · 1 kill |
| **Total** | **5/5, 15/15 · 204 calls · 1.4 h · 0 kills** | 5/5, 15/15 · 334 calls · 5.0 h · 82 compactions · 5 kills |

On Chat, arm 1 failed dev-t3 (R47). On Messages it passed it.

**Messages, ho2 tasks**

| Task | `a4-d77` | Arm 1 (Pi's compaction) |
|---|---|---|
| ho2-t1 | pass 4/4, 3/3 · 143 · 97 min · 1 kill | pass 4/4, **1/3** · 131 · 166 min · 38 compactions · 4 kills |
| ho2-t2 | **fail** 2/3, 3/3 · 41 · 18 min | pass 3/3, 3/3 · 88 · 104 min · 22 compactions · 2 kills |
| ho2-t3 (restart) | pass 4/4, 3/3, gate True · 38 · 13 min | pass 4/4, 3/3, gate True · 76 · 67 min · 17 compactions |
| ho2-t4 | **fail** 3/4, 2/3 · 51 · 31 min | pass 4/4, 3/3 · 126 · 155 min · 36 compactions · 4 kills |
| ho2-t5 | pass 3/3, 3/3 · 40 · 24 min | **fail** 1/3, 3/3 · 102 · 103 min · 24 compactions · 3 kills |
| **Total** | **3/5, 14/15 · 313 calls · 3.1 h · 1 kill** | 4/5, 13/15 · 523 calls · 9.9 h · 137 compactions · 13 kills |

- **ho2-t2, `a4-d77`.** `transpose_sheet("C D  E\n", 1)` returned `'DbEb F\n'` for `'Db Eb F\n'`. A chord that grows must use up a following space only when more than one follows. The model's own 310 tests passed, and every turn ended normally.
- **ho2-t4, `a4-d77`.** Two coding mistakes:
  - Constraint C2 ("the text after the unit is kept exactly as written") broke on `"1/2 tsp  sea salt, flaky "`, whose double space was collapsed.
  - `test_f_scale` raised `UnitError` on the plural `cups`.
  - The run's recorded bodies show the proxy did not cause the whitespace miss: no request Pi sent, and none the proxy sent upstream, contained a unit followed by two spaces. The model never saw the case, only the constraint's wording.
- **ho2-t5, arm 1.** `test_f_match` and `test_f_rules` failed: `*.py` matched `src/a.py`, and the pattern `x.log` was read as negated.
- **ho2-t1, arm 1** passed with only C1 of three constraints held.
- **Chat against Messages.** On Chat, `a4-d77` passed all five of these tasks with the same model. Both Messages failures are string-handling details the model got wrong in one attempt. No measure here separates a protocol effect from variance. Repeat attempts per task would.

**Totals over the 15 task pairs** (Chat ho2, Messages development, Messages ho2):
- `a4-d77`: 13/15 passed, 44/45 constraints, 956 calls, 8.4 hours, 0 compactions.
- Arm 1: 14/15 passed, 43/45 constraints, 1,323 calls, 24.2 hours, 366 compactions, 29 turns killed at 30 minutes.
- On the 20 Pi tasks of R47 and R52 together, `a4-d77` passed 18/20 and arm 1 passed 18/20. `a4-d77` took 9.4 hours against 29.1.

**TINY TANK WAR (`game-t1`).** One turn, the user's prompt verbatim, in an empty workspace, on Chat (`pi-game`, tags `pi-game-t1` and `pi-game-t1-3h`). The hidden check reads the page for the required features, runs `node --check`, and plays 900 frames in Node against stubs. `eval/tasks/game_t1_rubric.md` scores what a player gets.
- Attempts 1–2 stopped at the empty start commit before Pi started (fixed in `2cf93f6`). Attempts 3–4 are pair 1, and 5–6 are pair 2.

| | Turn limit | Calls · time · compactions | Turn | Hidden check | As written |
|---|---|---|---|---|---|
| Pair 1, `a4-d77` | 30 min | 18 · 21.5 min · 0 | ended | 7/8, C1 held | blank page: `updateHi` and three other names undefined |
| Pair 1, arm 1 | 30 min | 28 · 30 min · 8 | killed | 7/8, C1 broken | blank page: `lastTime` and `audio` undefined, and two test files left beside the page |
| Pair 2, `a4-d77` | 3 h | 49 · 31 min · 0 | ended | **8/8, C1 held** | **runs** |
| Pair 2, arm 1 | 3 h | 34 · 39 min · 8 | ended | 0/8 | no `index.html`: the game is nine unjoined parts in `.tmp_build/`, four of the last edits failed, and the reply is empty |

- **Pair 2, `a4-d77`, is the only page of the four that runs as written.**
- **Pair 1, played on minimally patched copies by the user:**
  - In the `a4-d77` game, enemies fire but their shells never appear or hit. `fire()` reads the aim spread from `t.err`, while enemies keep it in `t.type.err`, so every enemy shell's direction is NaN. An instrumented run had 76 enemy shots and 0 hits. Reinforcements spawn through each level by design.
  - The arm 1 game uses tank controls (W/S drive, A/D turn), as its title screen states, and the user found them unnatural.
  - Neither game was scored with numbers.
- **Pair 2** is ready for blind scoring in `C:/Users/Daniel/palimnesis-runs/tank-rubric/pair2/`. The arm 1 page there was joined from its parts in order, with three marked patches: `audioResume`, `updateMuteLabel`, and arrays started empty.
- Every failure in both pairs is a name used in one write and missing from the others, from a model writing a page of 800–1,300 lines in parts. None of the four runs opened its page before ending its turn.
