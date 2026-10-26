# Results

Append-only. Each entry names its commit (or "uncommitted" with the date), configuration and hardware.

## R1 — Passthrough overhead vs. fake upstream (Phase 0, 2026-10-24, pre-initial-commit)

`uv run python eval/bench_passthrough.py --n 300` · 64 KiB request body, 51-event SSE · direct and proxied requests interleaved, 20 warm-up rounds discarded · Windows 11 Pro 26200, Intel64 Family 6 Model 204 (8 logical CPUs), Python 3.12, uvicorn 0.54 / httpx 0.28.1 · loopback, fake upstream in-process.

| Metric | Direct p95 | Proxy p95 | Paired overhead p50 / p95 |
| --- | --- | --- | --- |
| Non-streaming total | 1.41 ms | 4.86 ms | 2.55 / 3.64 ms |
| SSE first byte | 1.38 ms | 4.09 ms | 2.12 / 3.11 ms |
| SSE total | 1.68 ms | 5.56 ms | 3.20 / 4.29 ms |

Target "p95 overhead under 5 ms" is met on this workload with ~0.7 ms headroom on SSE total. Not yet measured against live Strata, where network jitter dominates; rerun there before claiming the green light.

## R2 — OpenCode 2.1.4 live through passthrough; fixed overhead (Phase 0, 2026-10-24, uncommitted)

Setup and evidence: `docs/probes/opencode_live.md`, fixtures `eval/fixtures/opencode-2.1.4/live/`. Strata 0.1.48, `n_ctx` 65536 at run time. Two-turn scripted task, 10 requests, process restart between turns.

- All 10 requests were `primary`, streamed, and ended with `finish_reason` + `[DONE]`. Path prefix `/s/<opencode session id>/v1` was preserved via the `model.request` plugin hook, including across the restart.
- History was byte-level append-only across all 10 requests; `reasoning_content` was echoed byte-equal on every prior assistant turn.
- Replay direct vs. through a fresh proxy: 10/10 status and finish-reason matches each; generated text differed (diagnostic only); proxied request bodies byte-identical.
- Prompt tokens per request: 5004, 5107, 5189, 5261, 5344, 9101, 10279, 10392, 10731, 10808. Cached tokens ≈ previous prompt + completion.

Fixed overhead `F` ≈ 5.0K tokens (system + tool schemas + a one-line user message; grows with project instruction files). Headroom for history with `R = 8192`, `M = 256`:

| `n_ctx` | `input_budget` | History room ≈ budget − F |
| --- | --- | --- |
| 32,768 | 24,320 | ≈ 19.3K |
| 65,536 | 48,000 (configured cap; formula allows 57,088) | ≈ 43K |

32K is viable for OpenCode with default tools. Repositories with large instruction files or extra tools reduce history room one-for-one; the Phase 2 floor check reports this.

## R3 — Passthrough overhead after the raw-ASGI rewrite (Phase 0, 2026-10-24, uncommitted)

Same command, workload and hardware as R1, with the proxy under its production uvicorn config (`palimnesis.server`).

| Metric | Direct p95 | Proxy p95 | Paired overhead p50 / p95 |
| --- | --- | --- | --- |
| Non-streaming total | 1.05 ms | 2.62 ms | 1.38 / 1.85 ms |
| SSE first byte | 1.07 ms | 3.67 ms | 2.22 / 2.82 ms |
| SSE total | 1.35 ms | 4.91 ms | 3.12 / 3.79 ms |

The target of p95 overhead under 5 ms is met. A live smoke test of `palimnesis serve` against Strata relayed `/v1/models` with Strata's `Server` and `Date` headers once, and rejected an unsessioned request with 400 and `x-should-retry: false`.

## R4 — Phase 0 gate (2026-10-24)

| Green light | Result | Evidence |
| --- | --- | --- |
| First harness completes a scripted task through supported paths | pass, streaming only (OpenCode sends no non-streaming requests) | R2 |
| Fake-upstream fixtures preserve fields, errors, event ordering, tool deltas, cancellation | pass: 76 tests, including 15 recorded Strata streams and 10 live OpenCode exchanges relayed byte-for-byte | `tests/` |
| Live direct and proxy behavior comparable | pass: 10/10 status and finish-reason matches each | R2 |
| Passthrough p95 overhead under 5 ms | pass against the fake upstream (1.9–3.8 ms); not measured against live Strata | R3 |
| Protocol reviewer approves the declared subset | pass: approved after fixes | D9 |
| Real-SDK no-key timeout/retry fixtures; safe deadline and idle settings | pass for OpenCode 2.1.4: 48 fault runs; contracts §5 table | `docs/probes/opencode_faults.md` |
| First-harness setup lists unsupported features; linear workflow needs none of them | pass | `docs/harnesses.md` |

Carried into Phase 1:

- Rewritten streams send `x-should-retry: false`, which also stops OpenCode's resend after its own idle timeout. Until Palimnesis's keepalives land (Ph3), this relies on Strata's ~10 s keepalive comments; Phase 1 must relay or emit comments while waiting.
- Add a test that no capture is written without `--capture-dir`, and cover capture fail-open on the response-write path.
- `Proxy` assumes lifespan startup created the HTTP client; fail clearly if it runs without lifespan.
- Measured cancellation-to-slot-release through the proxy against live Strata (direct numbers: `docs/probes/strata.md` §9).

## R5 — Cancellation to slot release through the proxy, live Strata (Phase 1 carry-over, 2026-10-24)

`PALIMNESIS_PROXY=http://127.0.0.1:9078 python eval/probes/p09_cancel.py <mode> <ms> <n>` against `palimnesis serve` (post-`phase-0` working tree) and Strata 0.1.48, `n_ctx` 65536, no queue at cancel. Only the cancelled request goes through the proxy; `/status` polling and the follow-up go direct. Records are appended to `eval/probes/fixtures/cancel_trials.jsonl` with `via_proxy`.

| Mode | Cancel after | Release via proxy (s) | Direct, `strata.md` §9 (s) |
| --- | --- | --- | --- |
| Decode, stream | 2 s | 0.156, 0.094 | 0.047–0.079 |
| Decode, non-stream (client leaves before response headers) | 2 s | 0.469, 0.281 | 0.23–0.50 |
| Prefill, stream (~19.9K tokens) | 3 s | 14.27 | 5.9–15.0 |
| Prefill, non-stream (~20.0K tokens) | 3 s | 12.72 | 10.6–10.8 |

The proxy adds at most about 0.1 s to slot release. Non-streaming cancellation, the Phase 0 review's finding #1, frees the slot live. Prefill release is still bounded by Strata's 8192-token chunk boundary, not by the proxy. n = 1–2 per mode: indicative, not a distribution.

## R6 — Raw archive growth, v1 vs v2 deltas, and archive-mode metadata (Phase 1 slice 16, 2026-10-24)

`python eval/bench_archive.py` (default turns 10/50/100/200, e2e 50 turns, 5 timing repeats), run from a `git archive` export of `611432b` (clean) plus the then-uncommitted `eval/bench_archive.py`. Windows 11 Pro 26200, Intel64 Family 6 Model 204 (8 logical CPUs), SanDisk SN5100S NVMe, NTFS, Python 3.12.13, SQLite 3.53.1, `synchronous=FULL`, WAL, snapshot depth 32. DB sizes after `wal_checkpoint(TRUNCATE)`; per-table bytes from `dbstat`. An empty schema is 176,128 bytes (43 pages).

Workloads: the 10 live OpenCode 2.1.4 bodies, and synthetic OpenCode-shaped tool loops built from live body 0 (its system prompt, first user message and real tools array after `messages`). Each request adds one assistant tool call (~0.6 KB with reasoning) and a 1 KiB tool result: `repetitive` (templated text) or `random` (seeded base64). Every body reconstructed byte-exact.

| Workload | Logical | v1 payload | v2 payload | v2 saves (payload / `raw_bodies` table) | Snapshots / deltas, max depth |
| --- | --- | --- | --- | --- | --- |
| Live, 10 | 317,977 | 143,379 | 44,982 | **68.6% / 65.8%** | 1 / 9, 9 |
| Repetitive, 50 | 3,073,965 | 701,872 | 177,088 | 74.8% / 72.0% | 2 / 48, 32 |
| Repetitive, 100 | 10,377,120 | 1,627,064 | 577,496 | 64.5% / 62.5% | 4 / 96, 32 |
| Repetitive, 200 | 37,691,460 | 3,750,350 | 1,640,281 | **56.3% / 54.6%** | 7 / 193, 32 |
| Random, 200 | 35,228,020 | 3,640,649 | 1,530,580 | **58.0% / 56.0%** | 7 / 193, 32 |

- **D10.7: v2 meets the ≥ 25% bar on both the live replay (68.6%) and the 200-request synthetic replay (56.3% repetitive, 58.0% random).** v2 saves about the tools array (~11 KB) per delta. Snapshots are identical in both variants and dominate v2 at 200 requests (1.31 MB of 1.64 MB), so the saving shrinks as sessions lengthen or turns grow. Adoption is a decision, not made here.
- The two content regimes differ by < 2%: neither format compresses, so regime affects only body size.
- DB file at 200 requests: v1 3.96 MB, v2 1.89 MB. `raw_bodies` is ~99% of non-schema pages.
- `get_raw` (plain read connection, median of 5) at 200 repetitive requests, v1 p50 / p95 by depth: 0: 0.10 / 0.17 ms; 1–8: 0.27 / 0.79; 9–16: 0.80 / 1.55; 17–24: 1.35 / 2.44; 25–32: 1.87 / 3.40 ms. v1 and v2 are equal within noise.
- `put_raw` rebuilds the parent chain on every insert, inside the accept transaction. At 200 requests of up to 357 KB, p50 / p95 is 6.0 / 12.5 ms (v1) and 6.6 / 12.7 ms (v2). On the live bodies it is 0.5 / 1.1 ms (v1) and 0.9 / 1.8 ms (v2).

End to end through the proxy in archive mode (shipped defaults: v1, FULL) against the fake upstream. 50 requests of the repetitive session; each response is a recorded-shape Strata stream with ~97 deltas (5-character reasoning pieces and a chunked tool call). 1.15 MB of SSE relayed, all byte-identical, every request reconciled as an extension.

| After N requests | DB pages | `raw_bodies` | Metadata excl. raw | `segments` + PK index | `events` | `occurrences` | `blocks` | `aliases` + index | FTS |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 471,040 | 143,360 | 327,680 | 73,728 + 57,344 | 12,288 | 12,288 | 4,096 | 4,096 + 4,096 | 32,768 |
| 25 | 876,544 | 331,776 | 544,768 | 167,936 + 131,072 | 24,576 | 16,384 | 16,384 | 4,096 + 4,096 | 40,960 |
| 50 | 1,662,976 | 716,800 | 946,176 | 319,488 + 270,336 | 45,056 | 28,672 | 24,576 | 12,288 + 12,288 | 53,248 |

- Rows at 50: 101 occurrences, 151 blocks, 4,841 segments, 250 events, 101 aliases, 50 attempts and generations.
- Metadata outgrows raw bodies: about 16.1 KB per request from 25 to 50, of which `segments` and its autoindex are 11.6 KB. One segment row per SSE delta stores 1.4 KB of text per request at ~8× overhead (the 36-byte `block_id` is repeated in the table and its PK index). Reasoning dominates the segment count.
- Time to first byte rose from 10.9 ms (median of the first 10 requests) to 19.4 ms (last 10) as `accept` reloads the whole branch and `put_raw` rebuilds deeper chains.

## R7 — FULL vs NORMAL commit latency and archive relay delay (Phase 1 slice 16, 2026-10-24)

`python eval/bench_commit.py` (n = 500 per configuration after 20 warm-up rounds; relay: 200 deltas, 10 paced rounds at a 25 ms requested gap, 60 burst rounds, 3 warm-up rounds each). Run from the same `611432b` export, hardware and SQLite as R6. DBs are in `%TEMP%` on the same NTFS NVMe volume; read back as WAL plus the stated `synchronous` on writer and reader.

`await Store.write(fn)` from the event loop for a segment-like batch: payload split into 64-byte `segments` rows plus one `events` row; FULL and NORMAL stores interleaved round-robin.

| Mode, payload | p50 | p95 | p99 | max | Commit-only p95 (total − in-transaction work) |
| --- | --- | --- | --- | --- | --- |
| FULL, 256 B | 0.39 | 0.57 | 0.68 | 3.13 | 0.51 |
| FULL, 4 KiB | 0.53 | 0.67 | 0.90 | 3.52 | 0.49 |
| FULL, 16 KiB | 0.95 | 1.21 | 3.64 | 4.53 | 0.65 |
| NORMAL, 256 B | 0.13 | 0.20 | 0.39 | 4.36 | 0.16 |
| NORMAL, 4 KiB | 0.28 | 0.37 | 0.79 | 5.91 | 0.19 |
| NORMAL, 16 KiB | 0.73 | 0.93 | 5.33 | 5.95 | 0.37 |

All values are ms. **FULL p95 is at most 1.21 ms, 4.8% of `BATCH_MAX_AGE_S` (25 ms).** FULL costs about 0.3–0.35 ms more per commit than NORMAL. Whether this drive's flush is power-loss safe is not verified.

Relay delay is measured as client arrival minus upstream send for the same event. A `FakeUpstream` subclass timestamps each chunk, and everything shares one process and one `perf_counter`. Archive requests use a fresh session each.

| Scenario | Proxy | TTFB p50 / p95 | Per-event delay p50 / p95 / max | Client-visible batches per stream |
| --- | --- | --- | --- | --- |
| Paced (effective send gap 32.2 ms) | passthrough | 5.5 / 17.1 | 1.1 / 1.6 / 3.4 | 203 |
| | archive FULL | 46.0 / 48.8 | 35.1 / 37.8 / 42.8 | 202 |
| | archive NORMAL (diagnostic) | 34.3 / 45.5 | 33.9 / 36.6 / 49.4 | 201.5 |
| Burst (all 203 events at once) | passthrough | 4.5 / 5.3 | 3.7 / 4.5 / 5.2 | 203 |
| | archive FULL | 8.4 / 9.3 | 6.8 / 8.7 / 12.0 | 3 |
| | archive NORMAL (diagnostic) | 7.4 / 8.9 | 6.2 / 7.8 / 13.5 | 3 |

- In archive mode, paced decoding adds about 34 ms per event. That is the batch-age timer, not the commit (~1 ms). The 25 ms age fires at ~31–34 ms because Windows `time.monotonic` and asyncio timers tick at 15.6 ms, and the requested 25 ms upstream gap likewise became 32 ms. At Strata's ~25 ms/token, each batch therefore holds one event.
- FULL vs NORMAL changes the relay delay by about 1 ms. A weaker durability mode buys nothing visible here; the age timer is the lever.
- TTFB in archive mode adds the input commit and the first batch's age wait: +40.5 ms p50 (FULL) over passthrough.
- Burst streams flush in 3 batches (16 KiB cap and terminal), adding ~3 ms per event.

## R8 — After D12 tuning (Phase 1, 2026-10-24, working tree after `fd1e34c`)

Same hardware and SQLite as R6/R7. `python eval/bench_commit.py --n 100 --relay-n 10 --burst-n 30` and `python eval/bench_archive.py --turns 200 --e2e-turns 50 --repeats 1`. These are smaller samples than R6/R7.

Relay delay is client arrival minus upstream send, in ms:

| Scenario | Proxy | TTFB p50 / p95 | Per-event delay p50 / p95 / max | Batches |
| --- | --- | --- | --- | --- |
| Paced (~32 ms gap) | passthrough | 5.1 / 23.3 | 1.1 / 1.5 / 2.9 | 203 |
| | archive FULL | **8.8 / 21.6** | **3.4 / 4.1 / 9.6** (R7: 35.1 / 37.8 / 42.8) | 202 |
| Burst | archive FULL | 7.2 / 7.9 | 5.1 / 6.5 / 8.4 | 4 |

FULL commit p95 ranges from 0.53 ms (256 B batches) to 1.21 ms (16 KiB batches), matching R7.

End to end, 50 turns in archive mode (now v2):

| | R6 | R8 |
| --- | --- | --- |
| `segments` rows | 4,841 | 301 |
| Metadata excluding raw bodies | 946 KB | 512 KB |
| `raw_bodies` | 717 KB | 201 KB |
| `events` | 250 | 400 (`delivery_progress` is now recorded) |

TTFB (p50) is 8.2 ms over the first 10 turns and 16.0 ms over the last 10, against R6's 10.9 and 19.4 ms. It still grows because `accept` reloads the whole branch on every request. That is a Phase 2 scaling item (bounded view and catalog), not addressed here.

The raw-delta comparison reproduces R6 exactly. v2 meets D10.7 and is the default (D12).

## R9 — OpenCode 2.1.4 live through archive mode, with restart and client interrupt (Phase 1 live check, 2026-10-24)

**Setup.**

- Commit `98be1e0`, clean tree. Its `src/` is identical to `845ae90`.
- Strata 0.1.48, `qwen3.8-flash-next-iq3_xxs`, `n_ctx` 65536, cold cache at request 1.
- OpenCode 2.1.4 with the isolated `live/config` setup, `--standalone`, `PWD` set to a throwaway repo, stdin at EOF.
- Hardware as R6. Archive `synchronous=FULL`, v2 deltas.
- Topology: OpenCode → Palimnesis archive (an ASGI tap around `create_app`, under the CLI's uvicorn config) → a Palimnesis `--passthrough` instance with `--capture-dir` → Strata. A second instance was needed because `--capture-dir` writes nothing in archive mode.

Evidence is in `eval/fixtures/opencode-2.1.4/archive-live/`: its README, `summary.json` and the scripts.

| Turn | Requests | Status |
| --- | --- | --- |
| 1: create and run `hello.py` (2+3) | 3 | 200 ×3 |
| clean proxy stop, restart on the same `--db` | — | 0 attempts abandoned |
| 2: `--session`, add `print(2 * 3)`, run | 4 | 200 ×4 |
| 3: `--session`, client process tree killed 2.06 s after the first `data:` | 1 | 200, `cancelled` with 8,840 bytes forwarded; Strata idle at the first poll |
| 4: `--session`, short question | 1 | **409 `history_divergence`** ("archived partial assistant turn was omitted"), no retry, `opencode run` exit 1 |

**Byte-level and archive checks.**

- `get_raw` equals the client body for 8 of 8 accepted requests. Storage is 1 snapshot plus 7 v2 deltas: 22.5 KB stored for 170.8 KB logical.
- Upstream request bodies equal client bodies for 8 of 8. No partial was accepted, so there was no split.
- Upstream response bytes equal client-received bytes for 8 of 8.
- Archived generated turns equal the streamed reasoning, text and tool calls for 8 of 8, including the 143-character reasoning-only partial.
- The visible history is 17 occurrences: the final accepted request's 16 messages, all matching, plus the incomplete turn. There was 1 session and 0 context versions.

**Events.**

- Requests 1–7 each recorded `accepted_input, attempt_started, delivery_started, turn_complete, delivery_completed`.
- Request 8 recorded `…, delivery_started, cancelled`.
- There was no `attempt_abandoned`, and none was expected after a clean stop.
- Restart reloading worked: the first turn-2 request reconciled as an extension.
- Strata cache: `cached_tokens` = 5178 of 5230 after the restart.

**TTFB.** Proxy overhead is measured to the first `data:` chunk, archive tap minus upstream tap, and includes one passthrough hop.

- Warm requests: 1.5–8.0 ms (n = 6).
- First request in each proxy process: 31.4 and 35.0 ms. This is time spent before the upstream request arrives, so it is acceptance plus a new upstream connection.
- Client TTFB: 62–112 ms.

**Finding (lifecycle gap).** A client-side kill makes the session permanently unusable.

- OpenCode persisted the interrupted assistant as a single empty reasoning part. On the next run it omitted the message entirely, so the request had two consecutive `user` messages.
- Palimnesis archived the 143-character partial. `reconcile` (`src/palimnesis/transcript.py:180`) rejects the omission per D10.4, and every later request in the session gets the same 409.
- D10.4's premise ("OpenCode never omits a partial once output has streamed") was measured only for server-side stream failures. D10.3 and D10.12 do not cover this case: the client sent no flattened Continue, and the attempt is `cancelled`, not abandoned.

The Phase 1 green light for this harness therefore holds for linear use with server-side failures, but not for user interrupts.

## R10 — Client-interrupt fix (D13.1) checked live (Phase 1, 2026-10-24)

**Setup.**

- Commit `a41809a`, clean tree.
- A fresh archive DB and a fresh isolated OpenCode 2.1.4 home.
- Strata 0.1.48 and the same model as R9. The same two-proxy topology as R9: archive with an ASGI tap, then `--passthrough --capture-dir`. `--capture-dir` now requires `--passthrough`.

Evidence is in `eval/fixtures/opencode-2.1.4/archive-live/` (README §R10, `summary-r10.json`, `scripts/`).

| Session | Sequence | Statuses |
| --- | --- | --- |
| A | Task (3 requests); client kill 2.06 s after the first `data:` (92 reasoning + 60 text characters archived); 2 follow-ups | 200 ×6. Both follow-ups record `partial_superseded`. |
| B (variant) | Client kill 1.0 s after the first visible `content` (176 + 153 characters archived); 2 follow-ups | 200 ×3, with `partial_superseded` |

**What OpenCode does after a client kill.** OpenCode never persists streamed reasoning or text after a client-side kill. It stored only empty parts, then omitted the message entirely (`…, user, user`), even when visible text had streamed. It sent no flattened partial and no Continue.

**Checks.**

- For 9 of 9 requests:
  - `get_raw` equals the client body.
  - The upstream body equals the client body. No splits were needed.
  - Upstream response bytes equal the client's.
  - Archived generated turns equal what was streamed.
- Per session, the visible history minus the superseded partial equals the last request plus the final turn. The partial stays archived as cancelled and incomplete.
- Events: `cancelled` on each interrupted request; the normal five-event sequence on every other request.
- TTFB overhead was 0–15 ms on warm requests and 32.9 ms on the first request of the process.

**Observations (not Palimnesis defects).**

- **The orphaned question gets answered.** With the partial gone, the model sees two consecutive user turns and answers the interrupted question too. In B this took 4,345 completion tokens and 99.9 s on the shared slot.
- **Cache reuse after that long turn was low.** The next request reported `cached_tokens` 5026 of a 9406-token prompt, roughly the earlier prompt only. The likely cause is checkpoint-limited reuse after a long generation (contracts §10). This is a cache-auditor item.
- **`partial_superseded` repeats.** It is re-recorded on every later request in the session (4 events for 2 partials). Each request re-derives the alignment.

No remaining bug was found in this flow.

## R11 — Phase 1 gate (2026-10-24)

| Green light | Result | Evidence |
| --- | --- | --- |
| Explicit retries don't duplicate logical events; repeated identical occurrences stay distinct; key conflicts; concurrent keys; non-streaming replay without inference; streaming keys get 409 | pass | `tests/test_archive_lifecycle.py`, `tests/test_review_fixes.py` |
| Raw requests reconstruct byte-for-byte; growth reported | pass. 10/10 live, 8/8 and 9/9 live archive runs; growth in R6 and R8 (v2 adopted, D12) | `tests/test_rawarchive.py`, R6, R8–R10 |
| Distinct sessions never merge; mismatched identity, divergence and concurrent conflicts get defined errors | pass | lifecycle tests, contracts §5 table |
| Every supported block round-trips exactly; aliases survive forced collisions | pass, including lone surrogates (D13.9) | `tests/test_chat.py`, `tests/test_addresses.py`, `tests/test_review_fixes.py` |
| Database rejects unauthorized archive mutation | pass, including plain connections and `INSERT OR REPLACE` | `tests/test_store.py` (mutation-checked) |
| Crashes around input commit and response preparation preserve data and mappings | pass at 4 crash points | `tests/test_crash_recovery.py` |
| Follow-ups reconstruct fixtures with hidden internal events without duplication | pass | `test_followup_upstream_body_contains_hidden_events_once_in_order` |
| Independent review | REJECT → fixed (D13) → APPROVE WITH CONDITIONS; conditions fixed in `6085692` | D13 |
| Live OpenCode against Strata in archive mode | pass: linear workflow and restart (R9); client interrupt fixed and verified (R10) | R9, R10 |

The suite has 515 tests. Phase 1 limits are listed in `capabilities.md` "Known limits of the Phase 1 archive". Carried forward: D13's Phase 3 note on internal occurrences of superseded attempts, and the R8 per-request cost growth, which Phase 2 addresses.

## R12 — Bounded-view watermark frequency, re-read and builder latency (Phase 2 GL7, 2026-10-25)

`python eval/bench_view.py` (defaults: 300K ingress tokens per session, seed 11). Pure, using `palimnesis.view.build` and the Strata 0.1.48 profile counter. It ran from the working tree at `1929c5c` with `src/` clean. `1929c5c`'s `src/` differs from `ae71004` only in docstrings, and only `eval/bench_view.py` was uncommitted. A rerun from a `git archive` export of `fb9b263` (D23, D24) gave identical move, re-read and excerpt counts in all 18 sessions, with latencies within ±10%. Hardware as R6; Python 3.12.13, tokenizers 0.23.3. Each session uses a fresh counter, warmed by a throwaway session with another seed. Policy: D14.6 (H 0.90, T 0.50, `min_recent` 4,096); excerpt caps D20.2. `q_msg`/`Q` were 972/2,432 at 24,320 and 1,920/4,096 at 48,000.

**Workloads.** Sessions are OpenCode-shaped: live body 0's system prompt and real tools array, so F is ~5.0K. A request is built after every user message and every tool result, carrying the persisted view state.

- `tool_heavy`: 4–12 tool groups per user message, with log-uniform outputs of 200–6,000 tokens.
- `chatty`: user 10–150 tokens and answer 30–400 tokens, with reasoning.
- `big_single`: one output of 3,000–15,000 tokens per user message.

**Measures.**

- *Ingress* is new content tokens, counted per message.
- *Re-read* is the moved view's tokens after its token LCP with the previous request (`counter.layout` ids). "est" is `len − StrataCacheModel.expected`, an estimate.

Arm `none`:

| Workload | Budget | Requests / ingress | Moves per 100K (watermark, collapse) | Ingress between moves, median | Re-read per move, median: LCP / est | Amortized re-read per ingress token | Append re-read, median |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tool_heavy | 24,320 | 209 / 317,778 | 11.96 (38, 36) | 7,699 | 8,170 / 8,216 | 0.98 | 838 |
| tool_heavy | 48,000 | 209 / 317,778 | 5.35 (17, 16) | 16,567 | 19,343 / 19,367 | 1.03 | 925 |
| chatty | 24,320 | 758 / 300,012 | 14.00 (42, 42) | 6,914 | 8,280 / 8,304 | 1.16 | 405 |
| chatty | 48,000 | 758 / 300,012 | 6.00 (18, 18) | 15,356 | 19,386 / 19,400 | 1.16 | 408 |
| big_single | 24,320 | 60 / 301,187 | 8.63 (26, 21) | 11,014 | 10,419 / 10,444 | 0.91 | 391 |
| big_single | 48,000 | 60 / 301,187 | 3.98 (12, 7) | 23,564 | 19,122 / 19,135 | 0.63 | 451 |

- **Move frequency.** A move comes every ~7K ingress tokens at 32K capacity and every ~15–24K at 64K, so frequency scales with 1/budget, not with turn count.
- **Re-read per move.** Each move re-reads about T minus the ~5K head: ~8.2K at 24,320 and ~19.3K at 48,000. That is ~1 re-read token per ingress token, amortized.
- **Checkpoint model.** The model's estimate is within 0.3% of the LCP figure, because the system root (≥ 2,048 tokens) is always a checkpoint.
- **Collapse.** Most watermark moves also collapse a span: 16 of 17 tool_heavy moves at 48K. Collapse reached the watermark itself only in big_single at 24,320 (17 of 26 moves). Elsewhere a band of s1 stubs stays visible: 1–36 in the final views.
- **Budget.** 0 of 6,162 views (all 18 sessions) exceeded the budget, and every layout length equalled `view.tokens`.

Excerpt arms. A block on every new user message (`every`) or on every third (`third`) is sized `min(q_msg, allocation)` from a real earlier span. *Starved* means the allocation was below `q_msg`.

| Workload | Budget | `every`: starved, omissions per 100K | `third`: starved, omissions per 100K | Amortized re-read `every` / `third` |
| --- | --- | --- | --- | --- |
| tool_heavy | 24,320 | 0/23 (0%), 6.9 | 0/8 (0%), 2.2 | 1.00 / 0.98 |
| tool_heavy | 48,000 | 0/23 (0%), 6.9 | 0/8 (0%), 2.2 | 1.04 / 1.04 |
| chatty | 24,320 | 414/758 (55%), 236.0 | 0/253 (0%), 82.3 | 1.29 / 1.21 |
| chatty | 48,000 | 437/758 (58%), 219.7 | 5/253 (2%), 81.3 | 1.21 / 1.18 |
| big_single | 24,320 | 0/30 (0%), 9.3 | 0/10 (0%), 3.0 | 0.93 / 0.91 |
| big_single | 48,000 | 7/30 (23%), 8.6 | 0/10 (0%), 3.0 | 0.67 / 0.65 |

- Starvation is a chatty-workload effect. `Q` holds about 2.1–2.5 full blocks, and omissions wait for a threshold event (D20.1).
- No move was ever caused by excerpts. The rebuild after attaching a block never moved the view (0 of 2,046 rebuilds). That is the case `ArchiveHandler._bound` would not persist.
- Excerpts add 0–11% to amortized re-read.

Build latency (`build`, including the exact count) at 48,000, in ms. "Plain" is a build that did not move; "identical" is a rebuild of the final state with every fragment cached.

| Workload | Arm | Moves / requests | All p50 / p95 | Plain p50 / p95 | Move p50 / p95 | Identical rebuild p95 |
| --- | --- | --- | --- | --- | --- | --- |
| tool_heavy | none | 17/209 | 9.9 / 117.0 | 9.8 / 13.5 | 123.7 / 151.2 | 8.7 |
| tool_heavy | every | 17/209 | 9.5 / 112.9 | 9.4 / 13.8 | 117.6 / 150.2 | 8.8 |
| chatty | none | 18/758 | 8.5 / 10.8 | 8.4 / 10.5 | 116.9 / 131.3 | 8.9 |
| chatty | every | 18/758 | 8.5 / 11.5 | 8.4 / 10.9 | 115.9 / 149.7 | 9.1 |
| big_single | none | 12/60 | 9.6 / 91.4 | 6.6 / 20.8 | 79.8 / 94.8 | 3.7 |
| big_single | every | 12/60 | 11.8 / 98.2 | 7.3 / 22.6 | 82.5 / 115.7 | 3.9 |

**The latency target (p95 ≤ 30 ms at 48K, warm) is met for builds that do not move, and missed for moves.**

- Plain builds run at p95 10.5–22.6 ms.
- A move build has p50 80–124 ms and p95 95–175 ms, with a maximum of 192 ms. Each probe of the watermark and collapse binary searches renders and counts the whole view.
- The overall p95 therefore fails wherever moves exceed 5% of requests: tool_heavy at 110–117 ms, big_single at 86–98 ms.
- The cost is small next to the move's own re-read prefill: ~19K tokens, ~47–62 s at R14's measured 2.4–3.2 ms per token, an estimate.

GL7 (report watermark frequency against ingress, with no universal gate) is met.

## R13 — `bench_archive` rerun: TTFB growth with BranchCache, metadata with excerpt rows (Phase 2, 2026-10-25)

`python eval/bench_archive.py --turns 200 --e2e-turns 50 --repeats 1`, run from a `git archive` export of `1929c5c` plus the uncommitted eval changes. Hardware and SQLite 3.53.1 as R6; FULL, v2 deltas.

**Script changes.**

- The fake upstream's usage now reports the exact local count of each body. R8's made-up `5000 + i` would make the Phase 2 drift monitor disable views after three requests.
- The snapshot adds `view_versions`, `excerpt_blocks`, `excerpt_items` and per-kind event counts.

Part 1 reproduces R6/R8 exactly: v2 saves 68.6% / 56.3% / 58.0%.

End to end, 50 turns at shipped defaults (views on, 48K budget). The 26.1K-token final view never masks, so there are no view versions.

| | R8 | R13 |
| --- | --- | --- |
| TTFB p50, first 10 / last 10 | 8.2 / 16.0 ms | **16.7 / 30.3 ms** |
| Metadata excluding raw bodies | 512 KB | 627 KB (`events` 143 KB) |
| `raw_bodies` | 201 KB | 201 KB |
| `events` | 400 | 451 (+50 `upstream_call`, +1 `excerpts_selected`) |
| `excerpt_blocks` / `excerpt_items` / `view_versions` | — | 1 (status `empty`) / 0 / 0 |

- **Growth.** Metadata grows 8.8 KB per request from 25 to 50 turns. The `events` table accounts for ~2.8 KB of that, mostly `upstream_call` payloads.
- **Excerpt rows.** They add one row per genuine new user instruction; the synthetic session has one.

**The target (last-10 p50 within 2 ms of first-10) is not met.** TTFB still grows. Five interleaved repeats, using per-turn medians, show where.

| Mode | First 10 → last 10 p50 | Slope |
| --- | --- | --- |
| Views on (default) | 23.2 → 43.5 ms | 0.51 ms/turn |
| View-disabled (pin mismatch) | 17.5 → 25.8 ms | 0.21 ms/turn |
| `--view off` (single runs) | — | 0.56–0.69 ms/turn |

Run-to-run noise is about ±5 ms. Component timings, first 10 → last 10 p50, in ms:

| Component | First 10 | Last 10 |
| --- | --- | --- |
| `chat.parse` | 0.7 | 3.7 |
| `ledger.accept` | 2.0 | 5.2 |
| `view.build` | 1.3 | 5.4 |
| Accounting `layout`, in a worker thread | 1.5 | 3.7 |

- **Archive side.** BranchCache keeps the statement count constant (R8's reload is gone). Per-request parse and accept CPU still grows with body size: +6–8 ms over 50 turns, comparable to R8's +7.8 ms.
- **View side.** It adds ~12 ms more by turn 50: a full render and count of the view each request, plus the accounting layout. `--view off` adds a third whole-history count in `_prepare`.
- **Bound.** View-side growth is bounded by the input budget, not by history length. R12 measures ~9 ms p50 at 48K.

## R14 — Live forced-budget OpenCode run through bounded views (Phase 2 GL8, 2026-10-25)

**Setup.**

- Code: a `git archive` export of `1929c5c`. `fb9b263` (D23, D24) landed during the run and was not exercised live.
- Strata 0.1.48, `qwen3.8-flash-next-iq3_xxs`, `n_ctx` 65536, one shared slot, cold at request 1.
- OpenCode 2.1.4 with R9/R10 isolation (`--standalone`, isolated HOME, XDG, TEMP and config, `PWD` a fresh git repo, stdin at EOF).
- Topology as R9: archive with `--input-budget 12000` (`Q` 1,200, `q_msg` 480) and an ASGI tap, then `--passthrough --capture-dir` with a tap, then Strata.
- Evidence: `eval/fixtures/opencode-2.1.4/view-live/` (README, `summary.json`, scripts).

**Task.** Four turns in one session: build `stats.py` with tests, then add variance/stdev, percentile and zscore, running the tests each time.

**Results.**

- **Statuses.** All 18 requests returned 200, and OpenCode exited 0 on all four turns. The final files pass (`python test_stats.py` prints `OK`, re-run independently). After moves 1 and 2, the turn-3 answer read the file back and listed all six functions correctly. **The task succeeded.**
- **Budget.** Every upstream body counted ≤ 12,000 with the Strata counter (max 10,352). `input_tokens` equalled `usage.prompt_tokens` on 18 of 18, with no `count_drift` events.
- **Fast path.** Requests 1–11 forwarded the client body byte-identical. Requests 12–18 were rendered views.
- **View versions.** There were 3 rows, each with cause `watermark_move,collapse`. Each collapsed the whole masked region into one span note of 11, 18 and 24 messages; watermark seq equalled collapse seq (13, 20, 26). At this budget T (~7.9K) lies below F plus `min_recent`, so no s1 stub ever reached the model.

**Upstream calls.** There were 17 pairs: 14 `append` (13 `full`, 1 `checkpoint_limited`) and 3 moves. The move rows, with the estimate labeled as such:

| Call | I | lcp | cached | est | prompt_ms | Class | Cause |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 12 (move 1) | 9,552 | 4,969 | 4,966 | 4,966 | 14,645 | `checkpoint_limited` | `collapse` |
| 14 (move 2) | 9,972 | 4,984 | 4,966 | 4,966 | 14,500 | `checkpoint_limited` | `collapse` |
| 16 (move 3) | 9,636 | 4,984 | 4,966 | 4,966 | 14,171 | `checkpoint_limited` | `collapse` |

- **Deep re-read.** A move re-read 4,586–5,006 tokens in 14.2–14.6 s, about 3.1 ms per token. Reuse fell back to the system-root checkpoint, exactly as estimated.
- **Append turns.** Over n = 14, `prompt_ms` had a median of 762 (291–2,798) for a median of 34 uncached tokens. So a move costs about 19× an append turn here; scaled to 48K (~19.3K re-read, R12), that is ~60 s (estimate).
- **First call.** Cold: 16,436 ms for 5,021 tokens.
- **The one `checkpoint_limited` append.** It is call 4, the first request of turn 2: lcp 5,923, cached 5,918, est 5,918. Strata re-read the previous generation prompt, the 5 tokens at the end of the LCP.

**`eval/replay.py --explain`** on the archive exited 0: 18 calls, 17 pairs, 0 unexplained.

**Proxy pre-dispatch time** (archive tap arrival to upstream tap arrival): 2.6–29.8 ms on non-move requests, 55.1, 39.8 and 48.0 ms on moves, and 32.7 ms on the first request of the process.

GL8 (measured reuse and prefill by cause, estimates labeled) is met for the `append` and `watermark_move`/`collapse` causes. Other causes did not occur.

## R15 — Live excerpt replay: prefix reuse with blocks included vs omitted (Phase 2 GL8, 2026-10-25)

**Setup.**

- Run: `python eval/live_excerpt_replay.py --upstream http://192.168.1.173:8080 --turns 6`, defaults `--input-budget 16000` and `--max-tokens 2048`.
- Code, Strata and hardware as R14.
- In-process proxy: `create_app(Settings(excerpt_source=SpanExcerpts()))` under the production uvicorn config. `SpanExcerpts` is `SeededExcerpts`-like: it selects a prefix of the newest earlier archived tool result, cut to the allocation it is given, with exact boundaries and sha256.
- Bodies are OpenCode-shaped (live body 0's model and tools, streamed). Each turn asks the model to `read` `notes/partK.txt`, and the proxy-side driver answers with a 1,842-token file.
- Budget: `Q` 1,600 and `q_msg` 640.
- Requests were sequential, each waiting for an idle `/status`. Cached tokens show unbroken continuity, so no foreign request evicted this session.
- Evidence: `eval/fixtures/opencode-2.1.4/view-live/excerpt-replay.json`.

| Call | Request | Block on this request (allocation → charge) | I | lcp | cached | prompt_ms | Class, cause |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | t1 user | `empty` (nothing earlier to select) | 5,000 | — | 0 | 14,596 | first call |
| 2 | t1 tool | — | 6,905 | 5,000 | 5,047 | 10,801 | `full`, `append` |
| 3 | t2 user | **new, 640 → 640** | 7,621 | 6,905 | 6,900 | 4,206 | `checkpoint_limited`, `append` |
| 4 | t2 tool | block 1 kept in prefix | 9,578 | 7,621 | 7,723 | 10,753 | `full`, `append` |
| 5 | t3 user | **new, 640 → 640** | 10,368 | 9,578 | 9,685 | 3,961 | `full`, `append` |
| 6 | t3 tool | | 12,299 | 10,368 | 10,440 | 10,717 | `full`, `append` |
| 7 | t4 user | **new, starved, 320 → 320** | 12,696 | 12,299 | 12,335 | 3,182 | `full`, `append` |
| 8 | t4 tool | | 14,608 | 12,696 | 12,748 | 10,808 | `full`, `append` |
| 9 | t5 user | `empty`, allocation 0 (starved) | 14,695 | 14,608 | 14,654 | 750 | `full`, `append` |
| 10 | t5 tool | **threshold event**: view 1, `watermark_move,collapse,excerpt_omitted`; blocks 1–2 omitted, block 3 kept | 11,255 | 4,963 | 4,960 | 15,180 | `checkpoint_limited`, `collapse` |
| 11 | t6 user | **new, 640 → 640** (room freed by the omission) | 11,977 | 11,255 | 11,295 | 3,919 | `full`, `append` |
| 12 | t6 tool | | 13,921 | 11,977 | 12,061 | 10,747 | `full`, `append` |

- **Inclusion.** Including a block never broke the prefix: on every call after an inclusion, the LCP covered the previous request whole. The block itself is prefilled once. A user turn carrying a 320–640-token block took 3.2–4.2 s, against 0.75 s for a user turn without one; that is ~5.8 ms per token on incremental prefill.
- **Omission.** Blocks were omitted only at the threshold event, together with the watermark move and collapse, and reuse fell to the system root as estimated. The first difference is the collapse, so the omission added no invalidation of its own: 6,295 tokens were re-read in 15.2 s (2.4 ms per token).
- **Starvation.** It appeared as D20.1 allows: turns 4 and 5 got 320 and 0 tokens, and the next threshold event restored a full allocation.
- **Explain.** `replay.py --explain` exited 0: 12 calls, 11 pairs, 0 unexplained. `input_tokens` equalled `prompt_tokens` on 12 of 12, with no drift.

## R16 — Builder latency after the off-path stub warm-up (Phase 2, D25, 2026-10-25)

`python eval/bench_view.py` (all workloads, budgets and arms) and `--no-warm --budgets 64K`. Run on `fb9b263` plus the D25 changes in the working tree. The benches ran sequentially on an idle machine. Hardware as R6; Python 3.12.13, tokenizers 0.23.3, profile `strata-0.1.48`.

**Counts.** Every count is identical to R12: moves per 100K, collapse counts, re-read per move (LCP and estimate), starvation and omissions. View tokens and states are unchanged, as `test_warming_stubs_never_changes_a_view` checks.

**Latency at 48K, in ms.** "Plain" means builds that do not move the view. The `--no-warm` columns reproduce R12's cold-stub numbers.

| Workload | Arm | All p50 / p95 | Plain p50 / p95 | Move p50 / p95 | `--no-warm` all p95 / move p95 |
| --- | --- | --- | --- | --- | --- |
| tool_heavy | none | 3.5 / **26.5** | 3.3 / 6.3 | 27.3 / 33.1 | 88.3 / 125.2 |
| tool_heavy | every | 3.4 / **26.6** | 3.3 / 6.6 | 28.1 / 32.7 | 88.5 / 124.4 |
| chatty | none | 2.9 / **3.9** | 2.9 / 3.7 | 37.9 / 42.4 | 3.7 / 104.3 |
| chatty | every | 3.1 / **4.5** | 3.0 / 3.9 | 41.3 / 66.5 | 3.9 / 111.2 |
| big_single | none | 6.7 / **37.4** | 2.4 / 16.4 | 28.5 / 44.6 | 76.8 / 80.4 |
| big_single | every | 6.1 / **37.8** | 2.4 / 16.5 | 29.4 / 44.5 | 76.2 / 83.9 |

The `third` arm sits between `none` and `every`. At 24,320 every overall p95 is ≤ 18.3 ms except `big_single` at 35.4 ms.

**Target** (build + count p95 ≤ 30 ms at 48K, warm). Met on `tool_heavy` and `chatty`. Missed on `big_single` by 7–9 ms, which D25 accepts with its reason.

**bench_archive e2e, 50 turns** (`--turns 200 --e2e-turns 50 --repeats 1`, three runs). TTFB p50 rose from 24.1, 25.3 and 24.4 ms over the first 10 turns to 43.1, 42.6 and 43.3 ms over the last 10. This matches R13's five-repeat views-on figure (23.2 → 43.5 ms).

- **The warm-up does not help here.** This session never masks, so per-request cost is the body-linear parse, accept and count, plus a warm-up that overlaps the next request because the fake upstream answers instantly. A real upstream generates for seconds.
- **Metadata** is 627 KB, unchanged.
- **The R8 row** is disposed of in D25.

## R17 — Phase 2 gate summary (2026-10-25)

Code at the `phase-2` tag. Full suite: 882 passed.

| Gate | Evidence | Status |
| --- | --- | --- |
| GL1: fits or a structured error | View property and HTTP tests. 0 over-budget views in R12 (6,162 views) and R14 (max 10,352 of 12,000). D23 escalation before a budget error. | Met |
| GL2: oversized newest output, user/system/schemas, Unicode, many small messages | `test_view*`, `test_stubs`, `test_phase2_review_fixes` | Met. D24.3 logs over-collapse on an oversized newest output for follow-up. |
| GL3: versions and A/B matrix | `docs/affordances.md`, registry tests | Met. Phase 3B matrix defined (A1). |
| GL4: catalog reach | catalog tests | Met. Internal only after A1 (D19, D20.3, D16.6). |
| GL5: zero upstream calls from the builder | socket-deny and one-POST tests | Met |
| GL6: every invalidation explained | `--explain` exit 0 on 10 live bodies, R14 (17 pairs), R15 (12 calls), and the cache audit's 17 archives (789 pairs, none unexplained or misattributed). D24.1 churn fixed. | Met |
| GL7: watermark frequency vs ingress | R12: moves every 7–11K ingress tokens at 24,320 and every 15–24K at 48,000. Re-read per move about T. Amortized 0.63–1.16 re-read tokens per ingress token. | Met. D24.2 logs near-per-turn moves at small budgets with large outputs. |
| GL8: reuse and prefill by cause | R14: 3 moves, each re-reading 4.6–5.0K tokens in 14.2–14.6 s, matching the estimate; appends had a median prefill of 762 ms. R15: excerpt blocks never broke the prefix. | Met |
| §1–§6, §9 (ordinary turns), §10–§12 | contract tests. Protocol review: approved with conditions, all fixed (D23). | Met |
| R8 | constant SQL statements over 200 turns; R13, R16 | Met as reinterpreted (D25) |
| Builder latency | R16 | Met on 2 of 3 workloads. `big_single` 37–39 ms, accepted (D25). |
| Paper fidelity | review: no unexplained divergence. Doc corrections committed. | Met |

**Carried to Phase 3:**

- Proactive retrieval and transcript files (A1).
- The view-policy items in D24.2 and D24.3, with bench_view data.
- Incremental accept (D25).

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
