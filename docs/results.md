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

Same command, workload and hardware as R1, with the proxy under its production uvicorn config (`mnemon.server`).

| Metric | Direct p95 | Proxy p95 | Paired overhead p50 / p95 |
| --- | --- | --- | --- |
| Non-streaming total | 1.05 ms | 2.62 ms | 1.38 / 1.85 ms |
| SSE first byte | 1.07 ms | 3.67 ms | 2.22 / 2.82 ms |
| SSE total | 1.35 ms | 4.91 ms | 3.12 / 3.79 ms |

The target of p95 overhead under 5 ms is met. A live smoke test of `mnemon serve` against Strata relayed `/v1/models` with Strata's `Server` and `Date` headers once, and rejected an unsessioned request with 400 and `x-should-retry: false`.

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

- Rewritten streams send `x-should-retry: false`, which also stops OpenCode's resend after its own idle timeout. Until Mnemon's keepalives land (Ph3), this relies on Strata's ~10 s keepalive comments; Phase 1 must relay or emit comments while waiting.
- Add a test that no capture is written without `--capture-dir`, and cover capture fail-open on the response-write path.
- `Proxy` assumes lifespan startup created the HTTP client; fail clearly if it runs without lifespan.
- Measured cancellation-to-slot-release through the proxy against live Strata (direct numbers: `docs/probes/strata.md` §9).

## R5 — Cancellation to slot release through the proxy, live Strata (Phase 1 carry-over, 2026-10-24)

`MNEMON_PROXY=http://127.0.0.1:9078 python eval/probes/p09_cancel.py <mode> <ms> <n>` against `mnemon serve` (post-`phase-0` working tree) and Strata 0.1.48, `n_ctx` 65536, no queue at cancel. Only the cancelled request goes through the proxy; `/status` polling and the follow-up go direct. Records are appended to `eval/probes/fixtures/cancel_trials.jsonl` with `via_proxy`.

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
- Topology: OpenCode → Mnemon archive (an ASGI tap around `create_app`, under the CLI's uvicorn config) → a Mnemon `--passthrough` instance with `--capture-dir` → Strata. A second instance was needed because `--capture-dir` writes nothing in archive mode.

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
- Mnemon archived the 143-character partial. `reconcile` (`src/mnemon/transcript.py:180`) rejects the omission per D10.4, and every later request in the session gets the same 409.
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

**Observations (not Mnemon defects).**

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
