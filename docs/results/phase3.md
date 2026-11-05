# Results: Phase 3, first gate (R18–R27)

[Index](README.md) · Append-only; each entry names its commit, configuration and hardware.

## R18 — Proactive-recall selection latency at 1M archived tokens (Phase 3, 2026-10-25)

`python eval/bench_recall.py --tokens 1000000 --queries 40 --json` on `f4151ac`. Hardware as R6; profile `strata-0.1.48`.

- **Session.** One synthetic OpenCode-shaped session of 1,002,646 tokens: 449 tool outputs of 300–6,000 tokens, each with one planted identifier.
- **Queries.** Each of the 40 queries is a new instruction naming one planted identifier. Every block except the newest 12 messages is absent from the view, the worst case where everything is a candidate.
- **What is timed.** `FtsExcerpts.select` through the real store and the pinned counter, at an allocation of 1,920 tokens.

| Metric | Value |
| --- | --- |
| Selection p50 / p95 / max | 10.4 / **12.0** / 14.6 ms |
| Planted identifier in the selection | 40 / 40 |
| Items per selection, median | 1 |

**Target** (p95 ≤ 50 ms at 1M tokens, contracts §13): met. A 200K-token run gave p50 2.8 ms and p95 6.8 ms, so cost grows with archive size but stays far inside the bound. The hit rate measures retrieval of an exact identifier only, not answer quality; the needle evaluation does that.

## R19 — Phase 3 development needle set and the O3 hybrid emulator (S10, 2026-10-25)

**These are EMULATOR results, not real OpenCode.** Two parts of the plan were not run in development:
- **Arm 1 (native compaction)** needs real OpenCode.
- **The ±50% cap variants (D20.2)** are not exposed as settings.

**Code and environment.**
- **Proxy code:** `d1c9589`. Its `src/` and `tests/` are identical to `954c6a4`. The eval files were uncommitted: `eval/needle.py`, `eval/needle_gen.py`, `eval/report.py` and `eval/needles/dev/`.
- **Client host:** as R6 (Windows 11 Pro 26200, Intel64 Family 6 Model 204, Python 3.12.13, tokenizers 0.23.3, SQLite 3.53.1).
- **Strata:** 0.1.48, `qwen3.8-flash-next-iq3_xxs`, `n_ctx` 65536, one slot, on an RTX 3060 12 GB with preset "IQ3_XXS 64K" (D40).
- **Emulated 32K:** `--input-budget 24320` at 64K capacity (O2), giving `Q` 2,432 and `q_msg` 972.
- **Deadline:** `deadline_s` was raised to 3,600, because the slot gate may hold a request.
- **Pin and canary:** the profile pin `strata-0.1.48@cf3b5a426570` and the canary matched at every proxy start, and again after the outage.

**Development set** (`eval/needles/dev/dev-h1..h6.json`, built by `needle_gen.py` with seeds 3100–3105).
- **Histories.** Six templated, OpenCode-shaped Python coding sessions of about 43–46K tokens each, plus OpenCode's ~5K-token head. Each history is imported as the session's first request, so its prior assistant and tool turns are `client_import`.
- **Steps.**
  - Q1 is the host of the import request.
  - The rest follow in order: P1, Q2, Q3, P2, Q4, Q5, P3, Q6, Q7, Q8, a proxy restart, Q9, Q10.
  - The P steps are 3.7–8K-token pastes answered with "reply 'noted'". They give later questions several eviction events.
- **Needles.** 10 per history, covering A1's categories:
  - identifier ×2;
  - superseded;
  - irrelevant matches;
  - vague ×2;
  - oversized read (a 420-line verbose log);
  - mid-task (the constant is named only in a scripted `pytest` output);
  - multi-fact (host:port/db, gathered from three turns);
  - restart plus multiple evictions (a value from P1).
- **Scoring.**
  - "Exact" is equality after whitespace and case normalization.
  - "Loose" additionally strips wrapping backticks, quotes and a trailing period.
  - Partials are recorded separately.
- **Needle location.** Taken from the tapped upstream body of the question's first upstream call: verbatim in the view, in the excerpt block, or absent.
- **Lookup.** A tool call aimed at the transcript directory.

**Emulator** (`eval/needle.py`, v2).
- **Request shape.**
  - It replays OpenCode 2.1.4's captured system prompt, with the `<env>` paths set to its own workspace, and the 11 captured tools.
  - Requests use the captured top-level shape and stream.
  - History is resent without `reasoning_content`, as asked; the proxy restores it.
- **Message content.**
  - Content is null only on tool-call-only turns. Otherwise it is the text, or "" when there is none, per the 2.1.4 bundle's OpenAI Chat conversion (`ze`).
  - That conversion also echoes `reasoning_content` when `compatibility.reasoningField` is set. The upstream body is the same either way.
- **Tools.**
  - `read` and `grep` follow the 2.1.4 bundle: its output formats, 2,000-line / 50 KB pages, and ripgrep with `--hidden` and 100 matches.
  - `glob` is emulated, and `edit` and `write` are confined to the workspace.
  - `shell` runs only allow-listed read-only commands under Git Bash, or the history's scripted `pytest`.
  - At most 8 tool calls run per question.
  - On a length stop, OpenCode's two synthetic continuations are sent.
- **Unverified:** the long-line suffix, the shell truncation preview, and glob and grep ordering (sorted by path).

**D39 pacing.**
- An in-process gate sat between the proxy and Strata. Before each inference request it waited for `/status` to show `busy` false and `queued` 0, and the driver did the same.
- The gate counted foreign requests from `/v1/status` `activity.requests`.
- The notice that the other application had stopped arrived at 2026-10-25 04:44Z, before every run here.
- No foreign activity was observed in any run: the activity counters agreed, and there were 0 busy-before-request events and 0 queued samples. All runs are labelled unaffected.

**Outage (10:07–10:36Z).** Strata stopped because its launcher's SSH lifeline ended, not because of these runs.
- **a4-a4.** Its first attempt, started 10:06:04Z, had completed 1 needle when the outage killed it. That attempt is discarded as an infrastructure failure and counts in no denominator.
- **Rerun.** After the pin and canary check, a4-a4 was rerun from scratch, 10:37–11:07Z, with a cold prompt cache.
- **Other configurations.** All finished before 10:06:04Z; a4-base ran 06:43–07:19Z and completed. No completed run has a connection-error request.

**Smoke run** (h1, 3 needles, arm 4): 3/3 exact. `--explain` exited 0 and `transcripts verify` passed.

## R20 — Phase 3 development matrix at emulated 32K (S10, 2026-10-25, EMULATOR)

**Setup.**
- Each configuration ran 6 histories × 10 needles. Runs were sequential, 06:43–11:07Z, at 30–59 minutes each.
- **Configurations:**
  - `a2-base`: transcripts plus a3, recall off;
  - `a3-base`: excerpts with `--no-transcripts`;
  - `a4-base`: q1/x1/a3;
  - the variants each change one factor of `a4-base`.
- **Columns:**
  - "Loose exact" counts all 60 needles; the CI is a 95% Wilson interval.
  - "Clean" excludes a needle when any earlier step of its session errored, or when one of its upstream bodies exceeded 24,320 tokens (the R21 defects).

| Config | Exact (ws/case) | Loose exact | 95% CI | Clean loose / n | Errored (R21-B) | Upstream early stops (R21-C) | Needle in view / excerpt / absent | Fallback when absent | Lookups (questions); unnecessary | Prompt / completion tokens, all steps | TTFVC p50 / p90 s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| a4-base (q1/x1/a3) | 38 | 44 | 61–83% | 31/32 | 12 | 2 | 18 / 31 / 5 | 5/5 | 27 (9); 16 | 2,356,126 / 12,429 | 7.4 / 75.0 |
| a3-base (no transcripts) | 33 | 35 | 46–70% | 23/33 | 11 | 9 | 18 / 31 / 5 | 0/5 | 0 | 2,280,871 / 16,069 | 6.5 / 94.8 |
| a2-base (no excerpts) | 56 | **59** | 91–100% | 59/60 | 0 | 0 | 13 / 0 / 47 | 47/47 | 133 (48); 2 | 3,311,913 / 38,144 | 49.1 / 88.6 |
| a4-q2 | 45 | 46 | 65–86% | 44/50 | 5 | 5 | 9 / 40 / 8 | 8/8 | 30 (9); 8 | 2,098,389 / 13,898 | 7.3 / 83.0 |
| a4-x2 | 57 | **58** | 89–99% | 58/60 | 0 | 0 | 9 / 44 / 9 | 9/9 | 33 (15); 6 | 2,428,859 / 16,355 | 8.2 / 68.0 |
| a4-a4 | 36 | 37 | 49–73% | 25/30 | 12 | 4 | 16 / 32 / 5 | 5/5 | 23 (8); 12 | 2,133,511 / 12,401 | 8.1 / 80.0 |

**Paired against a4-base**, per needle (both / only a4-base / only the variant / neither):

| Variant | All 60 | Clean in both |
| --- | --- | --- |
| a4-x2 | 43 / 1 / 15 / 1 | 30 / 1 / 1 / 0 |
| a4-q2 | 37 / 7 / 9 / 7 | 24 / 6 / 0 / 0 |
| a4-a4 | 29 / 15 / 8 / 8 | 8 / 5 / 0 / 0 |

The configurations differ mostly through R21-B and R21-C, not through retrieval.

**Retrieval.**
- In arms 3 and 4 the needle was in an excerpt for 31–44 of 60 questions.
- Arm 2 found 46 of 47 absent needles by transcript lookup. Compared with a4-base it cost 2.2 lookups per needle, 1.4× the prompt tokens, 3× the completion tokens, and a time to first visible content (TTFVC) p50 of 49 s against 7 s.

**Lookups.** Every arm with transcripts looked a needle up whenever it was absent. Unnecessary lookups, made when the needle was already in context, numbered 2–16 per configuration.

**`--explain`** exited 0 with 0 unexplained pairs on all 6 archives.
- `append` reuse was 1.17M cached against 1.16M estimated tokens for a4-base, and 2.63M against 2.60M for a2-base, the largest.
- `collapse` reuse matched its estimate exactly.
- `view_disabled` calls reused about 0.7M tokens against an estimate of 0 in a4-base, a3-base and a4-a4.

**`transcripts verify`** passed on all 30 transcript-enabled sessions.

**Variant evidence.** Development only; nothing is frozen here.
- **x2 over x1.** Suggestive, but each configuration was run once at temperature 1.0.
  - x2 had 0 early stops and 0 errored needles.
  - The four x1 configurations had 20 early stops in 240 needles (a3-base 9, a4-q2 5, a4-a4 4, a4-base 2). Each one seeded the R21-B cascade.
  - On needles clean in both runs, x2 and x1 tie (30 / 1 / 1 / 0). The gain is in how the model answers, not in what was retrieved.
- **q2:** no measurable effect. Its 6 clean-pair losses follow the early-stop and cascade pattern. Keep q1.
- **a4:** thin evidence (13 clean pairs) and no gain. Its 5 losses follow the same pattern. Keep a3.
- **Caveats.** The set is templated and most questions name their identifier, so clean accuracy sits near the ceiling everywhere except arm 3.

Sanitized per-needle summaries are in `eval/fixtures/phase3-dev/`. They hold no bodies, and paths appear as `<RUN>` or `<HOME>`.

## R21 — Defects found by the development runs (S10, 2026-10-25; A and B fixed by D41)

**A. A failed view build forwards an unbounded body upstream.**
- **Where.** `archive.py:234` (and `:135`) logs "bounded view build failed; forwarding unbounded" and then sends the client's whole history.
- **Trigger.** Any rendering error. Live, it was a generated tool call whose arguments were not a JSON object, truncated by `finish_reason: "length"`. When the client resent that call, the pinned template raised `RenderError`.
- **Effect.**
  - The upstream body was far over the input budget, and Strata answered 400 on every later request of the session ("prompt 85,430 tokens … context 65,536").
  - The proxy should have returned a structured error consistent with GL1 instead.
- **Repro.** `uv run python eval/probes/repro_unbounded_after_bad_args.py`. With a 12,000-token budget, request 2 forwards all 64 client messages (100,398 bytes).

**B. A reasoning-only turn causes count drift, which disables views for the whole process.**
- **Drift.** For a prior assistant turn with null or "" content and no tool calls, Strata does not render its `reasoning_content`, but the pinned local counter does.
  - `eval/probes/p11_null_content_count.py`, 3 tiny idle-gated requests:

    | Content | Local | Remote |
    | --- | --- | --- |
    | null | 100 | 68 |
    | "" | 100 | 68 |
    | "ok" | 101 | 101 |

  - Live drifts were 83 and 16 tokens.
- **Cascade.**
  1. Every later request in that session drifts.
  2. After 3 in a row, "bounded views disabled: 3 consecutive count drifts" takes effect for every session in the process until a restart.
  3. Bodies are then forwarded unbounded. Strata returns 400 once a body exceeds its 64K context; smaller histories run unmasked.
  4. The restart before Q9 re-enables views, but the session drifts again within 3 requests.
- **Incidence.** Errored needles: a4-base 12, a3-base 11, a4-a4 12, a4-q2 5. Later answers were contaminated too: the model also answered the earlier questions left unanswered.
- **Real OpenCode is affected.** OpenCode sends "" for such turns (bundle `ze`), so this occurs whenever the model answers only in its reasoning.

**C. Upstream early stops.** Seen with Strata 0.1.48 and this model; cause unverified.
- **Symptom.** `finish_reason: "stop"` arrives with the answer cut mid-value (`r2026.`, `2.`, `test`), or with no content after the answer appeared in the reasoning.
- **Not the relay.** The raw upstream SSE saved by the gate shows the same text.
- **Pattern.** 20 of 240 needles under x1, against 0 of 60 under x2 and 0 of 60 without excerpts.
  - One unverified hypothesis: speculative or prompt-lookup decoding that copies the answer from the excerpt.
- **Link to B.** Every reasoning-only answer triggers B.

**Earlier attempts.** These used emulator v1, 05:14–06:41Z, and are superseded by R20.
- **Paste prompts.** The paste turns first asked for analysis. The model wrote the pastes to files, and one lint count hit `length`, which exposed A. The pastes were changed to "reply 'noted'".
- **Empty content.** v1 resent text-less, tool-less turns with null content; v2 resends "" as OpenCode does. B occurred under both.
- **v1 results.** The v1 a4-base and a3-base runs scored 54/60 and 34/60 loose exact (`eval/fixtures/phase3-dev/v1/`). A partial a2-base run was discarded.

## R22 — x1 against x2 on the fixed proxy, two runs each (S10, 2026-10-25, EMULATOR)

**Setup.**
- Code at `47e501e` (D41 fixes R21-A and R21-B), with the eval files from `8703656` and the uncommitted `eval/report.py` additions: `--drift`, `--pair`/`--pool` and early-stop examples.
- Strata, hardware, dev set (dev-h1..h6), the emulator v2 and every R20 setting are unchanged: `--input-budget 24320` at 64K capacity, `deadline_s` 3,600, the D39 idle gate.
- Strata ran in the systemd user scope `strata-64k`, restarted at 10:36Z after the R19 outage. No outage occurred during these runs.
- **Run order:** interleaved a4-base, a4-x2, a4-base, a4-x2, 11:22–13:45Z. Each took 31–40 minutes and used fresh sessions and archives.
- **Foreign traffic:** none observed (activity counters, 0 busy-before-request events, 0 queued samples). The runs are unaffected.

**Before the first run:**
- `eval/probes/p11_null_content_count.py` read local 68 / remote 68 for null, 68 / 68 for "" and 101 / 101 for "ok". This was 100 for null and "" before D41.
- The smoke run (h1, 3 needles, arm 4) scored 3/3, with `--explain` exit 0 and `transcripts verify` passing.

| Run | Config | Loose exact | 95% CI | Exact (ws/case) | Early stops (R21-C) | Count drift | "views disabled" / "forwarding unbounded" lines | `--explain` | verify | Lookups (questions) | TTFVC p50 s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | a4-base (x1) | 51/60 | 74–92% | 51 | 7 | 0 of 132 calls | 0 / 0 | exit 0, 0 unexplained | 6/6 pass | 19 (8) | 6.8 |
| 1 | a4-x2 | 58/60 | 89–99% | 56 | 1 | 0 of 130 calls | 0 / 0 | exit 0, 0 unexplained | 6/6 pass | 37 (18) | 10.2 |
| 2 | a4-base (x1) | 53/60 | 78–94% | 53 | 7 | 0 of 129 calls | 0 / 0 | exit 0, 0 unexplained | 6/6 pass | 32 (14) | 7.2 |
| 2 | a4-x2 | 58/60 | 89–99% | 58 | 0 | 0 of 141 calls | 0 / 0 | exit 0, 0 unexplained | 6/6 pass | 39 (16) | 10.4 |

- **Count drift.** For every upstream body the gate recorded, `usage.prompt_tokens` equalled the pinned local count. That holds for all 532 calls in 24 sessions, including those after reasoning-only answers, so D41 holds live.
- **Errors.** No errored needles, no upstream errors, and no stopped histories.
- **Early stops** (gold → answer):
  - Run 1 x1: `h2q2` fix/stockroom-double-76323 → ""; `h6q4` 6.0s → `6`; `h6q5` 15s → `1`; `h6q6` test_validate_legacy_event → `test_validate`; `h6q7` 768 → `7`; `h6q9` → ""; `h6q10` → "".
  - Run 2 x1: `h6q4` → `6`, `h6q5` → "", `h6q6` → `test`, `h6q7` → `76`, `h6q8` → `pg-st`, `h6q9` → `r20`, `h6q10` → `plan`.
  - Run 1 x2: `h3q6` test_store_fast_token → "".
  - **Where they come from.** The raw upstream SSE has the same cut. For example, run 1 `h6q4` streamed the content `6` and then `finish_reason: "stop"`, after reasoning that ended `read_timeout = "6.0s". Reply with only the value.`; under x2 the same needle streamed `6`, `.`, `0`, `s`.

**Pooled x1 against x2.** 120 needle pairs, with run 1 paired with run 1 and run 2 with run 2:

| | x2 right | x2 wrong |
| --- | --- | --- |
| **x1 right** | 102 | 2 |
| **x1 wrong** | 14 | 2 |

- **Discordant pairs:** x1 only 2, x2 only 14. The exact McNemar two-sided p is 0.0042.
- **Early stops** still concentrate under x1: 14 of 120, against 1 of 120 under x2. 14 of x1's 16 misses are early stops.
- **Caveat: the effect is one history.**
  - 12 of the 14 x2-only pairs are dev-h6 Q4–Q10, and they recur in both runs. The first early stop is at h6q4 in each run, and every later answer in that session is cut short.
  - With dev-h6 excluded, the pooled table is 96 / 2 / 2 / 0 (p = 1.0).
  - Pairs within a session are not independent, so the McNemar p overstates the evidence. It supports "x1 triggers a reproducible early-stop cascade in dev-h6, and x2 does not". It does not establish a general retrieval or answer-quality difference.
- **Cost of x2.** More lookups (37–39 against 19–32) and a time to first visible content p50 of 10.2–10.4 s against 6.8–7.2 s.

Sanitized per-needle summaries are in `eval/fixtures/phase3-dev/r22/run1/` and `run2/`.

## R23 — S11 tooling smoke runs through real OpenCode (development data only, 2026-10-25)

**Setup.**
- **Code:** `3554fbe` with the uncommitted S11 tooling (D45): `eval/oc_harness.py`, `eval/needle_opencode.py`, `eval/tasks/`, and the `eval/needle.py` and `eval/needle_gen.py` changes. `src/` is unchanged.
- **Client:** OpenCode 2.1.4, isolated as in R9/R10, with messages on stdin.
- **Strata:** 0.1.48 at `n_ctx` 32768 (D40), one slot. `/v1/status` reported context 32768 before the runs. Strata was not restarted or reconfigured here.
- **Arm 4** is `a4-d43`, the default `serve` with `deadline_s` 3600 (D45.4). **Arm 1** is `serve --passthrough` with `compaction.auto` on and `limit.context` 32768.
- **D39 gate:** the driver waits for an idle slot before each turn, and the tap waits before each upstream call. There were 0 busy-before-request events, and foreign activity between and during calls was 0 in every run, so all runs are labelled unaffected.
- Raw run data (bodies, archives, OpenCode homes) stayed in the session scratchpad.

**(a) dev-h1, all 10 questions, real-OpenCode driver, arm 4.**

| Loose exact | In view / excerpt / absent | Lookups | Upstream calls | `--explain` | `transcripts verify` | Count drift | "views disabled" / "forwarding unbounded" | Client excerpt markers | Wall |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 9/10 | 1 / 8 / 1 | 4 (Q8, the absent needle, answered correctly) | 18 | exit 0, 0 unexplained (14 append, 3 collapse) | pass | 0 of 18 | 0 / 0 | 0 in 18 client requests | 2.4 min |

- **Import.** The first client body equalled the history plus Q1: 101 messages, with `reasoning_content: ""` added to 50 assistant turns. Its 73 prior assistant and tool turns were archived as `client_import`.
- **The miss is Q7.** The development histories' mid-task command is `pytest`, which the system Python lacks, and the model answered that pytest is not installed. Held-out histories use `unittest` (D45.6).
- **Timing.** TTFVC p50 3.5 s, latency p50 3.7 s and p90 24.5 s. The cold first question took 24.5 s.

**(b) dev-t1, one session of 8 turns, under each arm.**

| Arm | Success | Constraints | Upstream calls | Prompt / completion tokens | Max input | Lookups | Latency | Compaction | `--explain` | verify | Count drift | Over 24,320 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 4 (`a4-d43`) | yes (4/4) | 3/3 | 52 | 882,154 / 44,087 | 23,729 | 8 (turn 5) | 1,247 s | none (collapse ×6, watermark ×3) | exit 0, 0 of 51 unexplained | pass | 0 of 52 | 0 |
| 1 (native) | yes (4/4) | 3/3 | 40 | 451,853 / 21,743 | 21,266 | 0 | 579 s | 5 requests, 4 checkpoints | n/a (passthrough) | n/a | **10 of 40** | 0 |

- **Arm 4.** "views disabled" and "forwarding unbounded" each appeared 0 times, and no client request carried excerpt markers (0 in 52).
- **Arm 4, turn 5.** Turn 5 is the first after the restart, and it took 566 s and 20 calls. By then the view had collapsed the turn-1 user message (the constraints) into a span note. The model searched the transcripts (8 lookups, 4 tool errors on paths it made up) before it implemented `parse_price` correctly.

**R23-A. Proxy defect: special-token text in message content is miscounted** (fixed by D46).
- **What happens.** The pinned counter tokenizes message text with the HF tokenizer, which turns `<tool_call>`, `</tool_call>`, `<think>` and `</think>` written as plain text into single special tokens. Strata tokenizes them as text.
- **Probe.** `eval/probes/p13_special_token_text_count.py` sent 7 tiny idle-gated requests. Each put the string in a tool result:

  | Tool-result text | Local | Remote |
  | --- | --- | --- |
  | `plain error` | 101 | 101 |
  | `x</tool_call>y` | 102 | 104 |
  | `x<tool_call>y` | 102 | 104 |
  | `x<think>y` | 102 | 103 |
  | `x</think>y` | 102 | 103 |
  | `x</parameter>y` | 103 | 103 |
  | `x</function>y` | 103 | 103 |

  Empty tool arguments (`"{}"`, `""`, `"{ }"`) count correctly.
- **How it arose live.** In the arm 1 run (passthrough, so no view was affected), the model emitted unparsable tool arguments. OpenCode's `tool.input-json` error quoted them, `</tool_call>` included, and every later request in the session drifted by +3 (calls 31–40).
- **Effect under arm 4.** Every request drifts while that text stays in view, so 3 in a row disable bounded views for the whole process (D22.4), after which bodies are forwarded unbounded. The local count is also low, the unsafe direction for the budget.
- **Status.** Fixed by D46 before any held-out run. The smoke runs under arm 4 did not hit it.
- **After the fix.** `p13` reads local equal to remote on all 7 cases (for example `x</tool_call>y` 104 / 104). The wider probe `p14_literal_tags.py` matches on all 171 cases: every added token in user, system, assistant, reasoning and tool text, plus tool definitions, tool arguments and the three exceptions.

**Corrections after the review (2026-10-25).**
- **The checks ran under the wrong Python.** The R23 hidden checks ran under the project venv's Python 3.12, not the system 3.14 the model used: Windows looked up the bare `python` on the runner's PATH. The checks use only the standard library, so the dev-t1 outcomes (4/4 and 3/3 under both arms) stand, but the interpreter differed. Fixed in D45.9.15.
- **The arm 1 compaction count.** R23 reported "compactions=0" for arm 1 at first. That came from the runner's original detector, which looked for requests without tools. The corrected count, from the observed prompts, is 5 compaction requests (calls 6, 9, 10, 19, 34) and 4 checkpoints, as R23's table states.
- **The R23 excerpt check was narrower than D44.6.** It looked only for excerpt markers in archived client requests. The amended scan (D45.9.8) also covers proxy responses, the OpenCode export and the transcripts. It has not been rerun on the R23 data.
- **Other runner changes.** The runner now writes records and workspaces into separate trees, and writes the hidden check only into a copy (D45.9.5). The R23 runs used the earlier layout, which wrote `_check/` into the workspace after the session.

**Plumbing check against the fake upstream (no Strata, no model; 2026-10-25).**
- **The fake e2e run.** dev-t1 ran under both arms, and dev-h1 with 2 questions ran as two attempts, through real OpenCode, the front tap, the proxy and the fake upstream. The fake upstream answers "ok", and the slot gate was patched out.
- **What it confirmed:**
  - attempts, designation and the reason for the rerun;
  - the explicit transcripts root;
  - the `--explain` gate (2/2 pairs);
  - verify;
  - local budget counts;
  - leak scans (0 leaks, 0 echoes);
  - reachability (0 records found under the workspace trees);
  - both reports (`--set development` and `--coding`).
- **Preflight.** `needle.py preflight --set heldout --histories h1,h2` reported both imports faithful: 101/101 messages, 50 empty reasoning fields added. The questions were sent only to the fake upstream and were not read.

## R24 — S11 development smoke on the final commit; held-out runs not started (2026-10-25)

**Outcome: Step 1 failed one gate input, so no held-out history or task was run.** The failure is in the evaluation tooling, not the proxy (R24-A). Fixing it needs a decision first.

**Setup.**
- **Code:** `64f21c8`, clean tree (`provenance.dirty` false in every run). Drivers: `needle-opencode v2` and `tasks-run v2`. OpenCode 2.1.4.
- **Deterministic suite:** `uv run pytest -q` gave 1269 passed and 1 skipped. An earlier `-x` run failed once in `test_archive_lifecycle.py::test_session_usable_after_mid_stream_commit_failure` (`sqlite3.OperationalError: database is locked`). That file then passed 58/58 on its own, and the full suite passed. The test looks timing-flaky; this is unverified.
- **`run.py --check-reference`:** all 8 tasks pass on their reference and fail on their stub.
- **Strata:** 0.1.48, `qwen3.8-flash-next-iq3_xxs`, `/props` `n_ctx` 32768 before and after every run, one slot, RTX 3060 12 GB. It was not restarted or reconfigured. The proxy's pin and canary passed at each start: 0 "views disabled" lines.
- **Client host:** Windows 11 Pro 26200, Intel Core Ultra 7 355, 31.5 GB RAM, Python 3.12.13 (venv) and 3.14.6 (system, the model's shell and the checks), tokenizers 0.23.3, SQLite 3.53.1.
- **Settings:** arm 4 is `a4-d43` (`serve` defaults, `deadline_s` 3600, D45.4). Arm 1 is `serve --passthrough` with `compaction.auto` true and `limit.context` 32768.
- **D39:** foreign activity was 0 between and during calls in every run, with 0 gate events. All runs are labelled unaffected.
- **Cache:** warm from the preflight and earlier traffic on the same server. The first dev-h1 question took 25 s.
- Raw data stayed in the session scratchpad (`…/scratchpad/s11-final/`).

**(a) dev-h1, arm 4, 16:32–16:37Z.**

| Loose exact | Strict | In view / excerpt / absent | Lookups (questions) | Upstream calls | `--explain` | verify | Count drift | Over 24,320 | Leaks : echoes, client / transcripts | Views disabled / unbounded | Proxy rejections | Reachable records | TTFVC p50 / p90 s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 9/10 (Wilson 60–98%) | 9 | 1 / 8 / 1 | 9 (3) | 28 | exit 0, 27/27 pairs, 0 unexplained | pass | 0 of 28 | 0 of 28 | 0:0 / 0:0 | 0 / 0 | 0 | 0 | 3.8 / 6.5 |

- The import was faithful: 101 messages, 50 empty reasoning fields added, and all prior turns archived as `client_import`.
- The miss is Q7 again: `pytest` is absent, as in R23(a).
- There were 0 early stops and 0 upstream calls over 600 s.

**(b) dev-t1, 16:37–17:50Z.** Arm 4 ran first, then arm 1.

| Arm | Success | Constraints (stub) | Upstream calls | Prompt / completion tokens | Max input | Lookups | Latency | Compaction | Proxy rejections | `--explain` | verify | Count drift | Over 24,320 | Leaks | Views disabled / unbounded |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 4 | no (check could not import) | 0/3 (1/3) | 97 | 1,531,556 / 66,544 | 20,706 | 7 (turn 1) | 1,808 s | none | **7** | exit 0, 96/96, 0 unexplained | pass | 0 of 97 | 0 | 0:0 / 0:0 | 0 / 0 |
| 1 | yes (4/4) | 3/3 (1/3) | 129 | 1,656,084 / 98,348 | 25,016 | 0 | 2,474 s | 15 compaction calls | 0 | n/a | n/a | 0 of 129 | n/a | n/a | 0 / 0 |

- **Arm 4, turn 1, ran into the driver's 30-minute kill** (96 calls, all 200). The session passed the budget inside turn 1, and the view collapsed 180 earlier messages into an s1 span. The model then kept re-checking its own edits with scratch scripts.
  - It also renamed `Item` to `InventoryRecord`, so the hidden check fails on import.
  - This is model behavior under the bounded view, and every view gate input holds. It is still a cost signal: in R23 the whole arm-4 session took 1,247 s.
- **Arm 1 succeeded.** It made 15 compaction calls, and its largest input was 25,016 tokens, above 24,320. Arm 1 has no input budget, so this is not a gate input.
- No call took over 600 s (max 88.7 s for arm 4, 108.3 s for arm 1).

**R24-A. Evaluation-tooling defect: the front tap hides client disconnects from the proxy.**
- **Gate input failed:** proxy rejections in the front tap, 7 of 8 arm-4 turns (`409 history_divergence`, "Message 200 … a generated assistant turn was replaced by another role").
- **Sequence** (dev-t1 arm 4, records `attempt-001/dev-t1-a4/front/0097–0104`):
  1. Turn 1 started at 16:37:17.6Z.
  2. Call 97 was dispatched at 17:07:06.5Z.
  3. The driver killed `opencode run` at about 17:07:17.8Z, 11 s into the stream.
  4. The front tap (`needle.Tap` with `SlotGate(None)`, `eval/oc_stack.py`) never reads `receive()` for `http.disconnect`. It kept draining the proxy's stream until 17:08:12.1Z, so the stream completed: `finish_reason: "tool_calls"`, `[DONE]`.
  5. The proxy therefore saw a complete, delivered turn and archived it.
  6. OpenCode had not stored that turn. Turn 2 resent history without it, and the proxy applied D10.1 (divergence) to it and to every later turn.
- **Not a proxy defect.**
  - Without the front tap, the kill would have reached the proxy as a client disconnect. The attempt would then be `cancelled`, and D13.1 lets the resend omit it.
  - D13.1 is covered by `test_transcript.py::test_partial_the_client_cancelled_may_be_omitted_and_is_superseded` and `test_review_fixes.py::test_a_cancelled_partial_is_superseded_once_across_later_turns`, both passing at `64f21c8`.
  - This was not re-verified live on this path.
- **The same blind spot sits between proxy and Strata.** The upstream tap is the same class, so after a proxy cancel Strata would keep generating until the stream ends. This is inferred from the code, not observed.
- **Effect on held-out runs.** Any turn that reaches the 30-minute kill would end its session in 409s.
  - D45.9.13 would count those as proxy rejections.
  - For needles, the driver marks the rest of the history as misses ("history_divergence (409) earlier in the session").
  - D44.7 allows a rerun only for a failure outside the proxy. That case is arguable here, and a rerun would hit the same tooling.
- **Not changed here.** The fix is in `eval/`: propagate the client disconnect in `Tap`. D44.1 allows a later commit that changes only `eval/` and docs, but that needs a new commit. No held-out data has been seen.

**Resolution (2026-10-25).** Fixed in `eval/` by D45.9.16 before any held-out run: both taps now watch for the client's disconnect and close the stream they relay. `tests/test_eval_taps.py` fails without the fix (the upstream stream runs its full 30 s) and passes with it, including the resend that omits the cut-off turn. The held-out runs use the commit that carries this fix.

## R25 — S11 held-out at 32K (2026-10-25/26)

**Outcome.** The needle gate passes: 120/120. The coding gate fails: arm 4 succeeded on 3 of 5 tasks against 5 of 5 for arm 1, and the restart task ho-t3 failed under arm 4. Every D44.6 input holds on every held-out archive. No proxy defect was found (D44.8), and nothing was rerun (D44.7).

**Setup.**
- **Code:**
  - The needles, ho-t1 and ho-t2 ran at `bc610b9`.
  - ho-t3..t5 ran at `9889b37`, which adds only D48 and the README; `src/`, `eval/` and `tests/` are unchanged.
  - `provenance.dirty` is false in every run. Drivers: `needle-opencode v2` and `tasks-run v2`. OpenCode 2.1.4.
- **Configuration (D44.1, D45.4):** arm 4 is `a4-d43`, the `serve` defaults (q1, r1, x2, a3, t1, s1) with `deadline_s` 3600. Arm 1 is `serve --passthrough` with `compaction.auto` true and `limit.context` 32768.
- **Deterministic suite at `bc610b9`:** 1270 passed, 1 failed, 1 skipped (R25-A).
- **Before any held-out run:**
  - `run.py --check-reference` passed for all 8 tasks: each passes on its reference and fails on its stub.
  - `needle.py preflight --set heldout` found 12/12 imports faithful: 101/101 messages, 50 empty reasoning fields added.
- **Strata.** 0.1.48, `qwen3.8-flash-next-iq3_xxs` IQ3_XXS, one slot. `/props` reported `n_ctx` 32768 before and after every history and task. Neither server was restarted or reconfigured by these runs. The proxy's pin and canary passed at every start (0 "views disabled" lines).
  - **bazzite** (192.168.1.173; RTX 3060 12 GB; Control 0.1.49; systemd scope `strata-32k`) served the needles, ho-t1 and ho-t2.
  - **Zeus** (192.168.1.19; RTX 4070 Ti SUPER 16 GB; Control 0.2.3.1) served ho-t3..t5. The move came after ho-t1 and ho-t2 had run, and it is a deviation from D44 (D48). Each task's two arms ran on the same machine.
- **Client host:** Windows 11 Pro 26200, Intel Core Ultra 7 355, 31.5 GB RAM. Python 3.12.13 (venv) and 3.14.6 (system: the model's shell and the checks), tokenizers 0.23.3, SQLite 3.53.1.
- **D39.** Each server's `/v1/status` activity counter rose by exactly our upstream calls:
  - bazzite: 917 → 2110 = 2 (cancel check) + 356 (needles) + 835 (ho-t1, ho-t2).
  - Zeus: 193 → 1636 = 1443 (ho-t3..t5). The 193 earlier requests were the pre-switch checks behind D48.

  All runs are labelled unaffected. The 4 gate events, and the tap's nonzero `foreign_between` sums on arm 1 (24 in total), are our own requests: cut-off calls still releasing, and late-counted disconnects (R25-B).
- **Cache.** bazzite was warm from R24's traffic; the first needle (ho1q1) took 26 s. Zeus was warm from the D48 checks.
- **Raw data** (bodies, archives, OpenCode homes, logs) stayed in the session scratchpad (`…/scratchpad/s11-heldout/`). Sanitized fixtures are in `eval/fixtures/phase3-heldout/32k/`:
  - `a4-d43.jsonl`: per-step needle summaries, from `report.py --fixtures`.
  - `tasks.jsonl`: one row per task and arm.
  - `task_turns.jsonl`: one row per turn.
  - `summary.json`: the gates.

**(0) Live cancel check (D45.9.16), 18:03Z, bazzite.**
- **Path:** a client went through the front tap, the proxy (`a4-d43`) and the upstream tap to Strata. It read 40 chunks of a streaming count-to-600 and closed.
- **Result:**
  - Both tap records carry `client_disconnect`.
  - Strata reported `busy: false` 0.134 s after the close (decode phase).
  - The archive recorded `cancelled`, then `partial_superseded`.
  - The resend without the cut-off turn got 200 (`finish: stop`).
- No held-out data was used.

**(a) Held-out needles, arm 4, one attempt, bazzite, 18:10–19:12Z (61 min).**

| Loose exact | 95% Wilson | History-clustered bootstrap | Strict | In view / excerpt / absent | Exact when absent (fallback used) | Lookups (questions) | Unnecessary lookups (questions) | Upstream calls | TTFVC p50 / p90 s | Latency p50 / p90 s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **120/120** | 96.9–100% | 100–100% | 117 | 32 / 65 / 31 | 31/31 (31/31) | 188 (74) | 77 (43 of 89) | 356 | 5.4 / 17.8 | 23.5 / 46.1 |

- **Bootstrap settings:** 10,000 resamples, seed 44.
- **Strict misses:** all 3 are the right value in backticks (ho8q1, ho8q2, ho9q6).
- **By category:** every category scored full marks, including the 12 restart questions (Q9).
- **Rows:** 0 not run, 0 missing, 0 duplicates.
- **Errors and stops:** 0 errors, 0 early stops, 0 turn kills.
- **Imports:** all 12 were faithful, with every prior turn archived as `client_import`.
- **Tokens:** 6,247,113 prompt and 73,337 completion, all steps; 5,068,844 cached.
- **`--explain` causes:** 275 append pairs and 69 collapse pairs.

**(b) Held-out coding tasks, one attempt per task and arm.** ho-t1 ran arm 4 first, ho-t2 arm 1 first, and so on.

| Task | Machine | Arm | Success (functional) | Constraints (stub) | Restart gate | Turns killed at 30 min | Upstream calls | Prompt / completion tokens | Max input | Lookups | Compaction calls | Latency s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ho-t1 | bazzite | 4 | **no** (2/3) | 3/3 (1/3) | – | none | 145 | 2,327,409 / 108,072 | 22,078 | 8 | 0 | 2,977 |
| ho-t1 | bazzite | 1 | yes (3/3) | 3/3 (1/3) | – | 1, 2, 4, 5, 6, 7 | 273 | 3,952,587 / 609,820 | 26,085 | 0 | 76 | 13,296 |
| ho-t2 | bazzite | 4 | yes (3/3) | 3/3 (1/3) | – | 7 | 196 | 3,077,953 / 136,807 | 22,137 | 16 | 0 | 3,811 |
| ho-t2 | bazzite | 1 | yes (3/3) | 3/3 (1/3) | – | 5, 6, 7, 8 | 221 | 3,058,845 / 329,833 | 21,443 | 0 | 45 | 7,667 |
| ho-t3 | Zeus | 4 | **no** (1/3) | 2/3 (0/3) | **fail** | 5, 7, 8 | 539 | 8,668,229 / 508,875 | 24,016 | 70 | 0 | 9,082 |
| ho-t3 | Zeus | 1 | yes (3/3) | 3/3 (0/3) | (pass) | 1, 3, 4 | 425 | 5,878,394 / 516,564 | 26,264 | 0 | 69 | 7,960 |
| ho-t4 | Zeus | 4 | yes (3/3) | 3/3 (0/3) | – | none | 99 | 1,616,311 / 104,342 | 24,255 | 14 | 0 | 1,857 |
| ho-t4 | Zeus | 1 | yes (3/3) | 3/3 (0/3) | – | none | 90 | 1,207,650 / 70,694 | 20,205 | 0 | 11 | 1,140 |
| ho-t5 | Zeus | 4 | yes (3/3) | 3/3 (0/3) | – | 7 | 230 | 3,831,569 / 161,396 | 23,637 | 13 | 0 | 3,000 |
| ho-t5 | Zeus | 1 | yes (3/3) | 3/3 (0/3) | – | none | 60 | 693,664 / 26,161 | 25,641 | 0 | 7 | 488 |

- **Paired outcomes:** both arms succeeded on 3 tasks, arm 1 alone on 2 (ho-t1, ho-t3), arm 4 alone on 0. The paired success difference is −2/5. The exact two-sided McNemar p is 0.5, and two discordant pairs cannot reach p < 0.05 in any split (plan §7).
- **Constraints held:** arm 4 14/15 (ho-t3 C1 failed), arm 1 15/15.
- **ho-t1, arm 4:** `test_f_parse_strict` failed, because the parser accepts `1h 30m`. Model output.
- **ho-t3, arm 4 (the restart task):**
  - C2, the key constraint stated only in turn 1, **held** after the restart.
  - The run still fails, because success also needs every `test_f_*`. `test_f_token_ipv4` and `test_f_cli` failed (IPv4 values were not redacted), and so did C1 (format).
  - Turn 5, the first after the restart, ran into the 30-minute kill after 97 calls and 14 transcript lookups.
- **Turn kills by machine:**

  | Machine | Arm 4 | Arm 1 |
  | --- | --- | --- |
  | bazzite (2 tasks) | 1 | 10 |
  | Zeus (3 tasks) | 4 | 3 |

  - Kills are counted as they happened: the killed turn ends, and the session goes on.
  - D48 records that a faster decode fits more work into each 30-minute turn.
- **After each kill, the next turn was accepted.** The next turn resent history without the cut-off turn, and the proxy took it, with 0 proxy rejections in any run (D45.9.16, D13.1). The 5 arm-4 kills are the first live coverage of that path on arm 4.
- **Compaction calls by machine (arm 1):** 121 on bazzite (2 tasks) and 87 on Zeus (3 tasks).
  - Arm 1's largest input was 26,264 tokens. Arm 1 has no input budget, so that is not a gate input.
  - On ho-t1 arm 1, two turns ended in OpenCode's `compaction.failed` ("Compaction summary reached the output token limit").

**Gate verdicts (D44; nothing waived or reinterpreted).**

| Gate | Inputs | Verdict |
| --- | --- | --- |
| Needle gate (D44.4): loose exact ≥ 85% over all 120 | 120/120 (100%) | **pass** |
| Coding gate (D44.5): arm 4 successes ≥ arm 1's, over ho-t1..t5 | 3 against 5 | **fail** |
| Restart task ho-t3 under arm 4 (success plus C2, D45.9.7) | C2 held; success no (1/3) | **fail** |
| 0 over-budget inputs (D44.6) | 0 of 356 needle calls and 0 of 1,209 arm-4 task calls over 24,320, by the pinned counter | pass |
| 0 excerpt text visible to the client (D44.6, D45.9.8) | 0 leaks in client requests, proxy responses, OpenCode exports and transcripts, over 6 archives (the needle run and the 5 arm-4 tasks; 668 and 146 stored excerpt texts). Echoes: 131 client and 1 transcript, all in ho-t1 arm 4, where the model's reasoning quoted the x2 header | pass |
| `--explain` with 0 unexplained pairs (D44.6, D45.9.8) | needles 344/344; tasks 144, 195, 538, 98 and 229 of the same counts; all exit 0, 0 unexplained | pass |
| `transcripts verify` (D44.6) | 12/12 needle sessions and 5/5 arm-4 task sessions | pass |

**Other D45.9.8 inputs.**
- **Count drift:** 0 differences in all counted calls of both arms (356 needle calls, 2,260 task calls). Killed calls carry no usage, so they are not counted.
- **"bounded views disabled" / "forwarding unbounded":** 0 / 0 in every proxy log.
- **Proxy rejections:** 0.
- **Calls over 600 s:** 0. The longest was 186.5 s.
- **Reachable records:** 0, apart from one detector false positive (R25-D).
- **Client cancels:**
  - Needles: 0.
  - Arm-4 tasks: 9. Of these, 5 are the turn kills and 4 are disconnects that arrived after a complete stream.
  - Arm-1 tasks: 623, an upper bound (R25-B).

**Halts during the run.** The task runner stopped after any run that showed a possible defect signal. It stopped twice; both stops were reviewed, and neither is a D44.7 or D44.8 case.
1. **After ho-t1 arm 1.**
   - The runner's first D39 test used the tap's `foreign_between` sum (9) and gate events (3). That was stricter than D39.
   - bazzite's activity counter equalled our calls.
   - Strata's server log shows exactly 6 `(disconnect, cancel=True)` completions, one per kill.
   - The 3 gate events came 1.8–2.4 s after killed turns.
   - The test was changed to compare the server's activity delta with our upstream calls.
2. **After ho-t4 arm 4:** a `reachable_records` false positive (R25-D).

**R25-A. Flaky deterministic test.**
- **The test:** `tests/test_deadline_http.py::test_a_client_that_stops_reading_cannot_hold_the_upstream_past_the_deadline`. It failed once in the full suite, and once in 5 runs of its file alone.
- **What fails:** a scratch copy of the test failed in 2 of 12 runs. In those runs, a stalled client whose socket closes right after the deadline has its attempt recorded as `cancelled`, not `attempt_failed: deadline_exceeded`.
- **What holds:** the upstream was closed at the deadline (1.00–1.06 s) in every run. Only the event's classification races.
- **Effect here:** none. It is not a D44.6 input, and the held-out runs cannot reach it (`deadline_s` 3600). It is unresolved.

**R25-B. The arm-1 client-cancel counts are an upper bound.**
- **The numbers:** in ho-t1 arm 1, turn 1, 69 of 70 streams were complete at both taps, `[DONE]` included and byte-identical, yet 44 calls were flagged `client_disconnect`. Strata logged only the real cut-offs as cancelled.
- **Likely cause** [inferred, unverified]: OpenCode closes the connection after `[DONE]`, before the relayed upstream connection ends. The front tap then sees a disconnect after the whole stream was delivered.
- **Where it shows:** mostly in passthrough (arm 1), and 4 times in arm 4 (ho-t3).
- **Effect:**
  - No content was lost, and no proxy rejection or `--explain` problem followed.
  - Late-counted disconnects plausibly also explain the tap's nonzero `foreign_between` on arm 1.
  - The `client_cancels` counts, especially arm 1's, should be read as an upper bound.

**R25-C. Per-call tap records are not kept for task runs.**
- `eval/tasks/run.py` writes per-turn totals only. The tap's per-call records (`client_disconnect`, `t_disconnect`, `foreign_between`, upstream timings) stay in memory and are lost when the run ends.
- R25-B and the halt reviews were therefore reconstructed from the stream files, the server's activity counter and, on bazzite, Strata's server log. Zeus's server log is not readable from the driver host (D48.4).
- The needle driver writes `calls.jsonl` and is not affected.

**R25-D. A `reachable_records` false positive (ho-t4 arm 4).**
- **The hit:** the transcript `turn-0002.md` was flagged.
- **What matched:** the generic rule that flags any file containing the literal `"gold"`. The model's own reasoning reads "…hidden tests define the "gold" behavior…". None of the task's hidden-check markers occurs in the file, and coding tasks have no answer keys.
- **Why it misfired:** the `"gold"` test is meant for needle-record JSON, and it also matches model prose.
- **Decision:** the lead reviewed it, and the run counts as valid. Nothing was rerun or changed.

**R25-E. Transcript lookup overhead (ho-t3 arm 4).** These counts come from the client's requests: 68 tool calls touched the transcript directory, the driver's 70 lookups less 2 helper-script writes. About half returned what the model was after:
- **Useful calls:**
  - It re-read the task's requirements three times after they left the view.
  - It re-read spec details, test expectations and earlier test results.
  - It re-read its own reasoning from earlier in its longest turns.
- **Overhead calls:**
  - **Stale paths:** 6 "Cannot find path" or "Search path does not exist" errors. The in-progress turn's file name carries a revision that changes as the archive grows (`turn-0002.p1601.md`, then `.p1730.md`, then `.p2165.md`; `projection.py`, D34), so a name the model had just seen was gone by its next call.
  - **Listings:** about 16 directory listings and index reads, partly to recover from those errors.
  - **System prompt:** 6 reads of `turn-0000.md`, which holds OpenCode's system prompt; that prompt is always in view.
  - **The model's own scripting errors:** a few.
- **Effect:** the overhead costs calls and time; this run had turns 5, 7 and 8 killed. It costs no correctness or gate input, so it is not a proxy defect under D44.8.
- **Two changes for after Phase 3:**
  - Give the in-progress turn a stable path.
  - Mark turn 0 in `index.md` as the system prompt, which is already in view.

  Recall by address (optional Phase 3B, A1) would avoid most of these calls.

**Not run here:** the 64K report runs (D44.9) wait for Zeus to be relaunched at 65536 (D48).

## R26 — S11 held-out at 64K, reported only (D44.9; 2026-10-26)

**Outcome.** No gate applies at 64K (D44.9). Arm 4 answered 60/60 needles from ho-h1..h6. Both arms succeeded on all 5 held-out tasks, and the restart task ho-t3 passed under arm 4. No turn was killed, nothing was rerun, and the runner never halted.

At 64K, arm 4's budget is 48,000 tokens, and these sessions barely reach it. The largest arm-4 task input was 43,830. The view moved only 5 times across the five arm-4 tasks, and the model made no transcript lookups. The 64K tasks therefore test very little of the bounded view or of recall.

**Setup.**
- **Code:** `e0a7632`, clean tree in every run. It derives arm 1's OpenCode `limit.context` from `--expect-n-ctx`, and `report.py`'s clean-subset budget from the run's recorded `n_ctx` (D48.6). `src/` is unchanged since `bc610b9`.
- **Strata:** Zeus (D48), relaunched at `n_ctx` 65536 with the same configuration as at 32K apart from `--max-context`. Strata 0.1.48, pin passing, one slot. `/props` reported `n_ctx` 65536 before and after every history and task.
- **Settings checked in the first run of each arm:**
  - Arm 4's over-budget check counted against 48,000 (`input_budget_for(65536)`), and its OpenCode `limit.context` stayed 1,000,000.
  - Arm 1's `result.json` records `opencode_limit_context` 65536, and its OpenCode config file reads `"context": 65536`.
- **Everything else is as in R25:** drivers, OpenCode 2.1.4, client host, arm settings, the 30-minute turn limit, and the order (arm 4 first on ho-t1, ho-t3 and ho-t5).
- **D39.** Zeus's activity counter started at 0 after the relaunch and ended at 674, exactly our 127 needle calls and 547 task calls. There were 0 gate events and 0 foreign activity.
- **Run times (2026-10-26):** needles 12:32–12:42Z (9.4 min), tasks 12:42–14:14Z.
- **Cache:** cold after the relaunch; the needle run was the first traffic.
- **Raw data** stayed in the session scratchpad (`…/scratchpad/s11-heldout/heldout-needles-64k/`, `heldout-tasks-64k/`). Sanitized fixtures, in the same layout as R25, are in `eval/fixtures/phase3-heldout/64k/`: `a4-d43.jsonl`, `tasks.jsonl`, `task_turns.jsonl` and `summary.json`.

**(a) Needles: arm 4, ho-h1..h6 (60 questions), against the same 60 at 32K (R25).**

| Run | Machine | Loose exact | 95% Wilson | History-clustered bootstrap | Strict | In view / excerpt / absent | Fallback used when absent | Lookups (questions) | Unnecessary lookups (questions) | Upstream calls | Max input | TTFVC p50 / p90 s | Latency p50 / p90 s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 64K | Zeus | 60/60 | 94–100% | 100–100% | 55 | 40 / 17 / 12 | 12/12 | 29 (12) | 0 (0 of 48) | 127 | 41,721 | 2.9 / 4.8 | 3.3 / 14.4 |
| 32K | bazzite | 60/60 | 94–100% | 100–100% | 60 | 16 / 30 / 17 | 17/17 | 92 (34) | 33 (17 of 43) | 178 | 22,668 | 5.3 / 17.8 | 23.9 / 48.6 |

- **What the categories mean:**
  - "In view" and "in excerpt" can both hold for one question, so the three counts don't sum to 60.
  - At 64K, more needles stayed in view and fewer were absent, so the model needed fewer lookups.
- **Strict misses at 64K:** all 5 are the right value in backticks or quotes (ho4q2, ho4q6, ho4q10, ho5q4, ho5q5).
- **Timings compare machines as well as contexts.** Zeus decodes about 1.8× faster than bazzite (D48.2), so the latency columns are not a 32K/64K comparison.
- **64K inputs:** none over budget (0 of 127 above 48,000), drift 0 of 127, `--explain` exit 0 with 121/121 pairs and 0 unexplained, verify 6/6, 0 leaks and 0 echoes, 0 reachable records, 0 proxy rejections, 0 client cancels, 0 kills, longest call 15.9 s.
- **Clean subset (R26-A):** 60/60 at a budget of 48,000.

**(b) Coding tasks, one attempt per task and arm, Zeus.**

| Task | Arm | Success (functional) | Constraints (stub) | Restart gate | Turns killed | Upstream calls | Prompt / completion tokens | Max input | Lookups | Compaction calls | View moves (collapse / watermark) | Latency s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ho-t1 | 4 | yes (3/3) | 3/3 (1/3) | – | none | 29 | 818,029 / 21,528 | 37,145 | 0 | 0 | 1 / 0 | 307 |
| ho-t1 | 1 | yes (3/3) | 3/3 (1/3) | – | none | 71 | 2,014,312 / 41,262 | 52,523 | 0 | 2 | – | 563 |
| ho-t2 | 4 | yes (3/3) | 3/3 (1/3) | – | none | 26 | 665,339 / 24,012 | 37,876 | 0 | 0 | 0 / 0 | 324 |
| ho-t2 | 1 | yes (3/3) | 3/3 (1/3) | – | none | 75 | 2,274,533 / 65,096 | 53,036 | 0 | 4 | – | 790 |
| ho-t3 | 4 | yes (3/3) | 3/3 (0/3) | **pass** | none | 42 | 1,225,960 / 35,409 | 43,830 | 0 | 0 | 1 / 1 | 495 |
| ho-t3 | 1 | yes (3/3) | 3/3 (0/3) | (pass) | none | 69 | 2,174,134 / 56,134 | 51,512 | 0 | 3 | – | 707 |
| ho-t4 | 4 | yes (3/3) | 3/3 (0/3) | – | none | 58 | 1,785,833 / 51,485 | 41,683 | 0 | 0 | 2 / 0 | 690 |
| ho-t4 | 1 | yes (3/3) | 3/3 (0/3) | – | none | 73 | 2,138,251 / 45,723 | 50,449 | 0 | 3 | – | 596 |
| ho-t5 | 4 | yes (3/3) | 3/3 (0/3) | – | none | 30 | 806,691 / 20,465 | 40,075 | 0 | 0 | 0 / 0 | 281 |
| ho-t5 | 1 | yes (3/3) | 3/3 (0/3) | – | none | 74 | 2,454,443 / 45,964 | 54,769 | 0 | 2 | – | 597 |

- **Per arm:**

  | Arm | Successes | Constraints held | Turns killed | Compaction calls | Upstream calls | Prompt / completion tokens | Latency, all tasks |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | 4 | 5/5 | 15/15 | 0 | 0 | 185 | 5,301,852 / 152,899 | 2,099 s |
  | 1 | 5/5 | 15/15 | 0 | 14 | 362 | 11,055,673 / 254,179 | 3,252 s |

  There are no discordant pairs.
- **Against 32K (R25), on the same tasks:**
  - Arm 4: 3/5 successes at 32K against 5/5 here.
  - Turn kills: 18 at 32K against 0 here.
  - Arm 1 compaction calls: 208 at 32K against 14 here.

  Most of the 32K difficulty went away at 64K. A 64K session holds about twice as much before arm 4 views or arm 1 compacts, and Zeus fits more work into each 30-minute turn. These runs do not separate the two causes, and they are one attempt per task.
- **Arm-4 inputs per task:**
  - Over budget: 0 of 185 calls above 48,000.
  - `--explain`: exit 0, with 28, 25, 41, 57 and 29 pairs, 0 unexplained. The causes were 170 append, 4 collapse, 1 watermark move and 5 `view_format_change` (one per task).
  - Verify passed 5/5.
  - 0 leaks and 0 echoes in client data and transcripts; 0 reachable records.
  - "views disabled" / "unbounded": 0/0.
  - Drift 0 of 185; longest call 89.6 s.
- **Arm-1 checks:** drift 0 of 362, longest call 87.7 s.
- **Client cancels:** 0 on arm 4. 160 on arm 1, with no turn killed, so these are all after-`[DONE]` disconnects (R25-B).

**R26-A. The clean-subset budget fix does not reach runs with an `attempts.json`.**
- `report.py`'s `budget_for(meta)` reads `meta["expect_n_ctx"]`. For a run directory with `attempts.json`, `load_attempts` builds a merged meta that leaves that key out.
- `budget_for` therefore falls back to 32768 (a budget of 24,320) for every OpenCode-driver run, and `report.py` printed "CLEAN subset: 1/1" for the 64K needles.
- Recomputed in the scratchpad with `mark_clean(rows, 48000)`, the clean subset is 60/60.
- The headline count, the Wilson interval, the bootstrap and every gate input are unaffected. 32K reports are unaffected too, because 24,320 is right there.
- **Fixed with this result:** `load_attempts` now carries `expect_n_ctx` into the merged meta, and refuses designated attempts that ran at different `n_ctx`. The new test `test_a_run_with_attempts_keeps_its_n_ctx_for_the_clean_budget` failed before the fix. After it, `report.py` prints "CLEAN subset: 60/60" for the 64K needles. The 32K held-out report is unchanged at 120/120. Full suite: 1274 passed, 1 skipped.

## R27 — Phase 3 gate summary (2026-10-26)

**Outcome: Phase 3 is not accepted.** The held-out coding gate failed at 32K (R25), and so did the restart task. Everything else Phase 3 promised is met. The `phase-3` tag is not applied. The code is usable as the first usable milestone describes, with the limits in `capabilities.md` "Known limits of Phase 3".

Code at the S12 commit. Full suite: 1277 passed, 1 skipped.

| A1 green light | Evidence | Status |
| --- | --- | --- |
| Excerpt sets and renderings survive requests and restarts | `test_retries_and_restarts_reuse_the_stored_selection`, `test_crash_after_the_excerpt_commit_reuses_the_stored_selection`, `test_a_retry_after_a_crash_before_the_excerpt_commit_selects_once` | Met |
| Inclusion follows the view policy with recorded causes | `test_view_excerpts`; `--explain` with 0 unexplained over all 1,849 held-out arm-4 pairs (S12 cache audit) | Met |
| Excerpts never visible to the harness | `test_the_upstream_sees_the_block_but_the_archive_and_client_do_not`; 0 leaks in R25 and R26 | Met |
| Allocations fit the budget | `test_excerpt_charges_never_trigger_a_watermark_move`, `test_a_token_dense_tool_name_does_not_lose_the_selection`; 0 of 1,565 (R25) and 0 of 312 (R26) arm-4 inputs over budget | Met |
| Retrieval covers spans evicted now | `test_newly_evicted_occurrences_are_reported_for_retrieval`, `test_a_needle_masked_by_this_request_is_quoted_back_to_the_upstream_only` | Met |
| Lossless payloads, rebuild after deletion | `test_turn_payloads_roundtrip_property`, `test_rebuild_after_delete_byte_identical`; `transcripts verify` 17/17 (R25) and 11/11 (R26) | Met |
| Consistent generations across crashes | `test_crash_at_each_publish_step_leaves_consistent_generation` | Met |
| The first harness searches and reads transcripts | D37 gate probe; R25: 31/31 needles absent from view answered through the files | Met |
| Oversized reads narrowed | `test_an_oversized_transcript_read_is_stubbed_and_a_narrowed_read_passes_verbatim` | Met |
| Tool-step reasoning correct | `test_a_grep_then_bounded_read_loop_keeps_excerpts_reasoning_and_prefix_across_a_restart` | Met |
| Held-out recall and coding meet O1 | Needles 120/120 at 32K (gate ≥ 85%). Coding: arm 4 3/5 against arm 1 5/5 (gate: ≥ arm 1). Restart task failed. | **Not met** |
| Selection latency p95 ≤ 50 ms at 1M tokens | R18 | Met |
| Reviews | Protocol, cache and paper-fidelity reviews at S12: no blocker. Two code defects fixed test-first (D50.1 `tool_choice: "none"` counting, D50.2 re-render of dropped turns); documentation brought to the code (D50.5) | Met |

**Why the coding gate failed, as far as the evidence goes** (R25; one attempt per task, so these are observations, not measured causes):
- **ho-t1:** a functional miss in the model's own parser (`1h 30m` accepted), with 8 transcript lookups. Not attributable to recall.
- **ho-t3 (restart):** the key constraint stated only in turn 1 held after the restart. The run failed on IPv4 redaction and formatting. Turn 5 hit the 30-minute limit after 97 calls and 14 lookups, and about half of that task's 68 lookups were overhead (R25-E).
- **At 64K** both arms passed all five tasks with no kills, but the budget barely bound (R26), so that is no evidence that recall fixes the 32K failures.

**Carried forward:**
- **Phase 3B (hidden recall by address) is an open decision for the user.** R25-E suggests it would remove most lookup overhead. A1 makes it optional.
- **Transcript paths** (R25-E): a stable name for the in-progress turn, and `index.md` marking turn 0 as the system prompt.
- **Evaluation tooling:** the flaky deadline test (R25-A); per-call tap records for task runs (R25-C); the `"gold"` detector matching prose (R25-D).
- **Deferred by design:** proxy admission, `429` and keepalives (Ph4B, O4); Anthropic error re-envelope and other harnesses (Ph4B); continuation accounting and RE2 search (3B).
- **Cache model:** `restart_or_eviction` also counts checkpoints Strata dropped without a restart (D50.3).
