# OpenCode 2.1.4 live through Mnemon archive mode (Phase 1)

Captured 2026-10-24, 22:43–22:45 UTC, at `98be1e0` (clean tree; `src/` identical to `845ae90`). OpenCode 2.1.4 ran through `mnemon` in archive mode to live Strata 0.1.48 (`qwen3.8-flash-next-iq3_xxs`, `n_ctx` 65536), cold cache at request 1. This is the Phase 0 live run (`../live/`, `docs/probes/opencode_live.md`) repeated with archiving on, a proxy restart between turns, and a client-side interrupt. Results entry: `docs/results.md` R9.

This folder holds only a sanitized summary. There are no request or response bodies, no headers and no credentials. The full DB, taps and captures stayed in the session scratchpad.

## Files

- `summary.json`: per-request status, event sequence, byte-equality checks, usage, timings, the visible-history comparison, the 409 details, and raw-body storage rows.
- `scripts/run_proxy.py`: runs `mnemon.api.create_app` under `mnemon.server.uvicorn_config`, which is what `mnemon serve` runs. It is wrapped in an ASGI tap that records the exact request and response bytes plus timings, and it adds a stop file for a clean uvicorn shutdown.
- `scripts/oc_turn.py`: one isolated `opencode run --standalone --auto --format json [--session]` turn. It sets the same environment as `../live/config/env.sh`, plus `PWD` set to a throwaway git repo and stdin at EOF. Optionally it kills the process tree a set delay after the proxy's first streamed `data:` chunk.
- `scripts/analyze.py`: the read-only analysis. It opens the DB with `mode=ro` while the proxy is stopped and uses `ledger.load_archived`, `ledger.message_dict` and `rawarchive.get_raw`.

The scripts hard-code this session's scratch root. Edit `ROOT` before reusing them.

## Topology and why

```
opencode ──► mnemon archive :9031 (tap) ──► mnemon --passthrough :9032 (--capture-dir, tap) ──► Strata
```

`--capture-dir` writes nothing in archive mode, because the recorder is only wired into the passthrough relay (`src/mnemon/api.py:221`). So the client side is recorded by the ASGI tap around the archive app, and the upstream side by a second Mnemon instance in passthrough mode. The archive's upstream was `http://127.0.0.1:9032/s/upstream`. TTFB overhead therefore includes one extra loopback passthrough hop of about 1–3 ms (R3).

OpenCode config: `../live/config/` with `baseURL` on port 9031. The plugin was unchanged (`model.request` → `/s/<sessionID>/v1`), with `service.json` `{"disabled": true}`, `OPENCODE_DISABLE_PROJECT_CONFIG=true`, and isolated XDG, HOME and TEMP directories.

## Sequence

| Turn | Proxy process | Requests | Result |
| --- | --- | --- | --- |
| 1: create `hello.py` printing 2+3, run it | run1 | 3 (`write`, `shell`, final text) | all 200; "printed **5**" |
| (clean stop, restart on the same `--db`) | | | `recover` abandoned 0 attempts (none were active) |
| 2: `--session`, add `print(2 * 3)`, run it | run2 | 4 (`read`, `edit`, `shell`, final text) | all 200; reports 5 and 6 |
| 3: `--session`, 150-word question, process tree killed 2.06 s after first `data:` | run2 | 1 | 200, cut during reasoning; event `cancelled` (8,840 bytes forwarded); Strata `busy:false` at the first poll, under 1 s after the kill |
| 4: `--session`, "what is 7 times 8?" | run2 | 1 | **409 `history_divergence`**, `x-should-retry: false`; OpenCode exits 1 and does not retry |

## Checks

- **Raw archive.** For all 8 accepted requests, `get_raw` equals the client body byte for byte. Storage is 1 snapshot plus 7 v2 deltas: 22,548 payload bytes for 170,802 logical bytes.
- **Upstream bodies.** For all 8, they equal the client bodies byte for byte, in both the tap and the Mnemon passthrough capture. No partial was ever accepted, so there was no split.
- **Responses.** Client-received bytes equal upstream bytes for all 8, including `: keep-alive` comments.
- **Generated turns.** Each archived generated occurrence equals the reasoning, text and tool calls the client streamed, 8 of 8, including the 143-character reasoning-only partial.
- **Visible history.** The archive has 17 visible occurrences: the final accepted request's 16 messages, which all match, plus the incomplete generated turn. There was 1 session, 0 context versions, and an `active_request_id` of NULL at the end.
- **Events.** Requests 1–7 each have `accepted_input, attempt_started, delivery_started, turn_complete, delivery_completed`. Request 8 has `accepted_input, attempt_started, delivery_started, cancelled`. There were no `attempt_abandoned` events, which is correct because the restart was clean and no stale marker existed. The rejected request 9 wrote nothing.
- **TTFB** (arrival to first `data:` at the archive tap, minus the same at the upstream tap): 1.5–8.0 ms on warm requests and 31.4 / 35.0 ms on the first request of each proxy process. Client TTFB was 62–112 ms.

## Turn 4: why 409 (D10.3, D10.4, D10.12)

- **What OpenCode stored.** Killed from outside, OpenCode had persisted turn 3's assistant message with only one reasoning part, `""`. It never saved the streamed reasoning. On the next run it marked that message completed and **left it out of the request**. The turn-4 request was turn 3's 16 messages, byte-identical as a prefix, plus the new user message at index 16. So there were two consecutive `user` messages.
- **What Mnemon had.** Mnemon had archived the partial (143 reasoning characters, incomplete) at visible position 16.
- **How reconcile treats it.** `reconcile` (`src/mnemon/transcript.py:180`) treats an omitted incomplete partial as divergence, per D10.4 as amended.
  - D10.3 (flattened Continue) does not apply, because OpenCode sent no flattened partial and no Continue resend. The process was dead.
  - D10.12 (abandoned after crash) does not apply either. The attempt ended `cancelled`, not abandoned, and the request is not an identical resend.
- **Effect.** Every later request in this OpenCode session gets the same 409, so the session is permanently unusable through Mnemon.
- **Evidence gap.** D10.4's evidence, "OpenCode never omits a partial once output has streamed", came from server-side stream failures only. It does not hold for a client-side process kill.

# R10: the fix for client interrupts (D13.1) checked live

**When and where.** 2026-10-24, 22:59–23:02 UTC, at `a41809a` (clean tree). The archive DB, the OpenCode home and the scratch root were all fresh, with the same Strata as R9. Results entry: `docs/results.md` R10.

**Files.** The summary is `summary-r10.json`; the R9 `summary.json` is unchanged.

**Scripts.**
- `scripts/run_proxy.py` now also emits a `first_content` tap event, on the first non-empty `content` delta.
- `scripts/oc_turn.py` gained `--kill-on first_content` and an `OC_ROOT` override.
- `scripts/analyze_r10.py` handles several sessions and superseded partials.
- `--capture-dir` now requires `--passthrough`, so this run keeps the two-proxy topology. The archive instance had no capture directory.

**Session A (`…9YNdus`)**

| Turn | Requests | Result |
| --- | --- | --- |
| t1: create and run `hello.py` | 3 | 200 ×3 |
| t2: 150-word question, process tree killed 2.06 s after the first `data:` | 1 | 200, then `cancelled`. Mnemon had archived 92 reasoning and 60 text characters. |
| t3: "7 times 8?" | 1 | **200**. A `partial_superseded` event names the cancelled occurrence. Answer: "56". |
| t4: "9 minus 4?" | 1 | 200, with `partial_superseded` again. Answer: "5". |

**Session B (`…VYgSgz`, variant): interrupt after visible text**

| Turn | Requests | Result |
| --- | --- | --- |
| b1: 200-word paragraph, killed 1.0 s after the first non-empty `content` delta | 1 | 200, then `cancelled`. Mnemon had archived 176 reasoning and 153 text characters. |
| b2: "7 times 8?" | 1 | 200 with `partial_superseded`. The model answered the orphaned b1 question first: 4,345 completion tokens, 99.9 s, 1.03 MB of SSE. |
| b3: "9 minus 4?" | 1 | 200 with `partial_superseded` |

**What OpenCode sends after a client kill.** In both sessions OpenCode stored the interrupted message with empty parts only: `reasoning: ""`, plus `text: ""` in B. It then **omitted** that message, so the requests read `…, user, user`. No flattened partial and no Continue were ever sent, even after visible text had streamed.

**Checks** (9 of 9 requests, no rejections)
- `get_raw` equals the client body.
- The upstream body equals the client body in both the tap and the capture. No split was needed, because no partial was resent.
- Upstream response bytes equal the bytes the client received.
- Each archived generated turn equals what was streamed.

**Visible history.** In each session, history minus the superseded partial equals the final request's messages plus the final completed turn. The cancelled partial stays archived as `complete: false, cancelled: true`, at position 8 in A and position 2 in B.

**Events**
- Completed requests: `accepted_input, attempt_started, delivery_started, turn_complete, delivery_completed`.
- Interrupted requests: `…, cancelled`.
- Every request after an interrupt also has `partial_superseded`, written before `accepted_input`. There were 4 in total for 2 partials, because it is re-recorded on each later request.
- No `active_request_id` was left set.

**TTFB overhead.** 0–15 ms on warm requests, and 32.9 ms on the first request of the process.
