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
