# OpenCode 2.1.4 fault probe: timeouts, retries and continuations

Oct 24, 2026 · Phase 0 captured fixtures

## What this is

This probe records how OpenCode 2.1.4 behaves when the model endpoint fails. The plan requires these facts from fixtures, not from assumed SDK defaults ("Client timeouts and automatic retries"). It confirms, corrects and extends `docs/probes/harnesses.md` (OpenCode §3, §4 and §8, and item 3 of "Items to confirm").

Every result below comes from a real `opencode run` (`opencode.exe` v2.1.4) talking to a deterministic fake upstream. No live Strata server was involved. Source references use `$OC` = the v2.1.4 tag (`packages/...`).

Markers:
- **VERIFIED**: observed in a fixture.
- **SOURCE**: read in the tagged source, not exercised.
- **UNVERIFIED**: neither.

## Setup

**Fault server.** `eval/probes/opencode_fault_server.py` is a raw asyncio HTTP/1.1 server that speaks Chat Completions SSE:
- A role chunk, content (or `reasoning_content`) deltas, a finish chunk, a usage chunk, then `data: [DONE]`.
- Each POST to `*/chat/completions` is one attempt. The scenario says what attempt N gets; the last entry repeats.
- Every request is logged to JSONL with its arrival time, headers and full body, as are response milestones.
- It can delay the status line, end the chunked body cleanly ("eof") or reset the socket ("abort"), send nothing ("hang"), write SSE comments, and emit in-stream error events.

**Driver.** `eval/probes/opencode_fault_probe.py` runs one scenario per throwaway OpenCode home. `eval/probes/opencode_fault_summary.py` prints attempts, gaps and body diffs.

**Fixtures.** Raw logs are in `eval/fixtures/opencode-2.1.4/faults/<run>/`:
- `server.jsonl`
- `opencode.stdout.txt` and `opencode.stderr.txt`
- `opencode.json`
- `meta.json`
- `opencode.log`
- `retry-off.js` and `proxy.log` where used

`faults/summary.txt` is the summarizer output.

**Command.** `opencode run --standalone -m fault/m "Reply with the single word OK."`, with stdin at EOF. A run is killed after 150 s; no final-matrix run reached that limit.

**Config.** v1 provider shape (`opencode.json`):
- Provider `fault`, `npm: "@ai-sdk/openai-compatible"`, `options.baseURL`, `options.apiKey`, model `m` with `limit {context: 32768, output: 1024}`.
- `"compaction": {"auto": false}`
- `"agents": {"title": {"disabled": true}}`
- `"permissions": [{"action": "subagent", "resource": "*", "effect": "deny"}]`. The `subagent` tool is absent from the captured tool list.
- `"snapshot": false`

Title generation is off, so every request in the fixtures is a primary step.

**Endpoint.** OpenCode points directly at the fault server (`http://127.0.0.1:<port>/v1`) in the main matrix. Four runs go through `uv run mnemon serve --upstream <fault server>` with base `http://127.0.0.1:<port>/s/<session>/v1`: `ok_proxy`, `s500_proxy`, `partial_abort_then_ok_proxy` and `chunk_timeout5s_keepalive_proxy`. The session prefix was preserved, and each behaved the same as its direct counterpart.

### Isolation (VERIFIED)

Each run's DB, logs, cache and state were written only under `<scratchpad>/opencode-retry/runs/<run>/`. Its `opencode.log` shows `location services booted directory=<that run>/work`.

| Setting | Reason |
| --- | --- |
| `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`, `XDG_STATE_HOME` | Roots of every global path (`$OC/packages/util/src/global-roots.ts`) |
| `OPENCODE_CONFIG_DIR` | Global config dir (`util/src/global.ts`) |
| `OPENCODE_TEST_HOME`, `USERPROFILE`, `HOME` | `global.home`, which is used for `~/.claude`, `~/.agents` and `~/.opencode` |
| `TEMP`, `TMP` | Otherwise the shared `%TEMP%\opencode` is used |
| `OPENCODE_DISABLE_PROJECT_CONFIG=1`, `OPENCODE_DISABLE_CLAUDE_CODE=1` | Stop the upward config walk and `.claude` skill loading (`core/src/config/discovery.ts`) |
| `OPENCODE_DISABLE_MODELS_FETCH=1`, `OPENCODE_DISABLE_AUTOUPDATE=1` | No network side traffic |
| `--standalone` | Spawns a private `opencode serve --stdio --port 0` child instead of attaching to the user's background service (`cli/src/services/server-connection.ts`) |
| **`PWD=<run>/work`** | `opencode run` takes its session directory from `process.env.PWD` before `cwd` (`cli/src/run/run.ts:74`). A PWD inherited from Git Bash pointed the session at the mnemon checkout. |
| **stdin at EOF** | `run.ts:77` reads stdin to EOF when it is not a TTY. An open pipe hangs the run after server bootstrap. |

The last two rows are pitfalls not listed in `docs/probes/opencode_live.md`.

A first pass ran before the PWD fix. Those requests carried `Working directory: C:\Users\Daniel\repos\mnemon` in the system prompt's `<env>` block. They were still standalone and used only the scratch config; no project files were loaded and nothing was written to the repo. The whole matrix was then re-run with the fix, and those fixtures replaced the first-pass ones. Attempt counts and classifications were identical.

## Scenario results

**Gaps** are the time between successive request arrivals at the server. For non-timeout failures, a gap equals the backoff delay plus well under 0.1 s of failure handling. For timeout scenarios, it includes the timeout itself. With 11 attempts, the server saw 10 retries.

**Outcome** is what `opencode run` printed and its exit code. Stderr shows one `> build · m` line per attempt, and the final error is the JSON `error.message` from the response body.

### 1. HTTP 5xx

| Run | Attempts | Gaps (s) | Body between attempts | Outcome |
| --- | --- | --- | --- | --- |
| `s500` | 11 | 2.2, 4.1, 8.9, 11.6, 8.6, 11.7, 9.7, 10.3, 11.5, 10.3 (≈90 s total) | identical | `Error: fault server error`, exit 1 |
| `s502` | 11 | 2.0, 4.3, 7.7, 10.8, … ≤ 11.9 (≈87 s) | identical | error, exit 1 |
| `s503` | 11 | 1.9, 4.2, 8.8, 9.0, … ≤ 11.2 (≈80 s) | identical | error, exit 1 |
| `s503_then_ok` | 3 | 2.0, 4.2 | identical | `OK from fault server`, no error, exit 0 |
| `s500_proxy` (through `mnemon serve`) | 11 | 1.7, 3.4, 8.6, … (≈82 s) | identical | error, exit 1 |

The schedule matches `$OC/packages/core/src/model-retry.ts` (SOURCE): exponential from 2 s, capped at 10 s per gap, `Schedule.jittered` (0.8–1.2×), and `recurs(10)`. Observed gaps fall between 1.6 s and 12.6 s.

### 2. 429, `x-should-retry`, 409, 400

| Run | Attempts | Gaps (s) | Body | Outcome |
| --- | --- | --- | --- | --- |
| `s429` (no retry-after) | 11 | 1.6, 3.3, 9.1, 10.9, … (≈90 s) | identical | `Error: rate limited`, exit 1 |
| `s429_ra2` (`retry-after: 2`) | 11 | 2.0, 3.6, 8.0, 8.6, … (≈83 s) | identical | error, exit 1. A 2 s floor is below the schedule, so no visible effect. |
| `s429_ra15_then_ok` (`retry-after: 15`) | 2 | **15.0** | identical | OK, exit 0 |
| `s429_ram9000_then_ok` (`retry-after-ms: 9000`) | 2 | **9.0** | identical | OK, exit 0 |
| `s503_ra12_then_ok` (503 + `retry-after: 12`) | 2 | **12.0** | identical | OK, exit 0 |
| `s429_noretry` (429 + `x-should-retry: false`) | **1** | — | — | `Error: rate limited`, exit 1 |
| `s500_noretry` (500 + `x-should-retry: false`) | **1** | — | — | error, exit 1 |
| `s409` | 11 | 2.2, 4.2, 9.3, … (≈87 s) | identical | `Error: request already in progress`, exit 1 |
| `s409_noretry` (409 + `x-should-retry: false`) | **1** | — | — | error, exit 1 |
| `s400` | **1** | — | — | `Error: bad request from fault server`, exit 1 |

`retry-after` (seconds or HTTP date) and `retry-after-ms` set a **floor**: delay = max(backoff, header), capped at 15 min (`$OC/packages/ai/src/route/executor.ts:22`, `model-retry.ts`). The floor was verified for 429 and 503. Whether it also applies to 409 is not tested; the source applies it only to `RateLimit` and `ProviderInternal` reasons.

`x-should-retry: false` overrides classification for every status tried.

### 3. Stream closed after the role chunk only (no content)

| Run | Attempts | Gaps (s) | Body | Outcome |
| --- | --- | --- | --- | --- |
| `role_only_eof` (clean end of chunked body) | 11 | 2.0, 3.3, 7.7, 12.0, … (≈84 s) | identical | `Error: OpenAI Chat stream ended without finish_reason`, exit 1 |
| `role_only_eof_noretry` (+ `x-should-retry: false` on the 200) | **1** | — | — | same error, exit 1 |
| `role_only_abort` (1 s pause, then RST) | 11 | 3.0, 4.4, 10.3, … (each includes the 1 s pause) | identical | `Error: Connection lost while reading the response: ECONNRESET …`, exit 1 |
| `role_only_abort_noretry` | **1** | — | — | same error, exit 1 |

A role chunk with empty content does **not** count as output started. OpenCode resends the full request, and `x-should-retry` on the stream's 200 headers is honored.

**Fault-server pitfall.** An immediate RST after writing discards data the client has not read yet (Windows). A first `partial_abort` attempt without the pause lost its text and looked like a no-output retry. The final scenarios pause 1 s before resetting.

### 4. Stream closed after partial visible text: Continue

| Run | Attempts | Gaps (s) | Body change on attempt N+1 | Outcome |
| --- | --- | --- | --- | --- |
| `partial_eof` (text, clean EOF, every attempt) | 11 | 2.2, 3.5, 6.5, 10.9, … (≈85 s) | **+2 messages each time:** `assistant: "Partial answer attempt-N"`, then `user: "The previous response was interrupted. Continue from where you left off without repeating completed content."` | All 11 partial texts printed; 10 step errors and a final error; exit 1 |
| `partial_eof_then_ok` | 2 | 1.7 | +2 as above | `Partial answer attempt-1` / `OK from fault server`, plus `Error: … without finish_reason`; **exit 1 despite recovery** |
| `partial_abort_then_ok` (text, 1 s, RST) | 2 | 2.7 | +2 as above | partial text and OK, `Error: … ECONNRESET`, exit 1 |
| `partial_abort_then_ok_proxy` (upstream RST through `mnemon serve`) | 2 | 3.1 | +2 as above | same. The proxy turns the upstream RST into a client-side ECONNRESET. |
| `partial_eof_noretry` (+ `x-should-retry: false`) | 2 | 1.8 | +2 as above | **Continue still happens**; exit 1 |
| `partial_reasoning_then_ok` (`reasoning_content` then text) | 2 | 2.4 | +2. The assistant message is `content: "Thinking about attempt-1Partial answer attempt-1"`, with **no `reasoning_content` field**. | partial text and OK, exit 1 |
| `reasoning_only_then_ok` (reasoning only, no text) | 2 | 2.1 | +2. The assistant message is `content: "Thinking about attempt-1"`. | OK, exit 1 |
| `plugin_retry_off_partial_eof` (retry hook vetoes) | **1** | — | — | `Partial answer attempt-1`, `Error: … without finish_reason`, exit 1 |

Facts drawn from these runs:
- **Continue fires for an incomplete stream or a transport read failure once any text *or reasoning* has streamed.** `x-should-retry` cannot stop it; only the plugin `retry` hook can.
- Continue appends to the transcript; it does not resend the old request.
- **Reasoning from the failed message is converted to plain text** and concatenated directly onto the visible text with no separator. The assistant message carries no `reasoning_content` field.
- Each Continue counts against the same 10-retry budget, with the same backoff.
- The interrupted assistant message stays in every later request.

### 5. Terminal-marker variants

| Run | Attempts | Body | Outcome |
| --- | --- | --- | --- |
| `finish_no_done` (`finish_reason: stop` + usage, no `[DONE]`) | 1 | — | `Complete answer attempt-1`, exit 0. **`[DONE]` is not required.** |
| `done_no_finish` (text + `[DONE]`, no `finish_reason`) | 11 | +2 each attempt, as in §4 | Ten Continues, ≈84 s, exit 1. A missing `finish_reason` is an incomplete stream (`openai-chat.ts` `finishEvents`; overridable by `compatibility.requireFinishReason: false`, SOURCE). |

This corrects `harnesses.md` §8, which says the stream must end with a known `finish_reason` *and* `[DONE]`. Only `finish_reason` is required.

### 6. Header wait

| Run | Config | Attempts | Timeline | Outcome |
| --- | --- | --- | --- | --- |
| `header_timeout5s` (status line delayed 8 s) | `options.headerTimeout: 5000` | **4** | Client closed the socket at **5.00 s** after each request; arrivals at 0, 7.4, 17.1, 31.1 s | `Error: Timed out waiting for response headers`, exit 1 |
| `header_delay8_default` | none | 1 | Headers at 8 s, success | OK, exit 0 |

- The v1 key `provider.<id>.options.headerTimeout` (ms) works.
- Timeout failures are capped at 3 retries (`MAX_TIMEOUT_RETRIES = 3`, `model-retry.ts:40`), so 4 attempts. The usual backoff is added after each timeout.
- The default is 300 000 ms (`$OC/packages/core/src/provider.ts:201` `DEFAULT_TIMEOUT_MS`, SOURCE). It also covers connect time; there is no separate connect timeout.

### 7. Read idle (`chunkTimeout`) and SSE comments

| Run | Config | Attempts | Timeline / body | Outcome |
| --- | --- | --- | --- | --- |
| `chunk_timeout5s_idle_role` (role chunk, then silence) | `chunkTimeout: 5000` | **4** | Client closed at **5.0 s** after the last byte each time; body identical | `Error: Timed out waiting for response data`, exit 1 |
| `chunk_timeout5s_idle_role_then_ok` | 5000 | 2 | Gap 6.7 s; identical | OK, exit 0 |
| `chunk_timeout5s_idle_text_then_ok` (text, then silence) | 5000 | 2 | Gap 7.3 s; **Continue** (+2 messages) | Partial text and OK, error line, exit 1 |
| `chunk_timeout5s_idle_role_noretry` (+ `x-should-retry: false` on the 200) | 5000 | **1** | — | timeout error, exit 1. The client-side timeout is not retried either. |
| `chunk_timeout5s_keepalive` (`: keep-alive` every 2 s for 15 s, before any data event) | 5000 | **1** | 8 comments, then the full answer at 16 s | OK, exit 0 |
| `chunk_timeout5s_keepalive_after_role` (comments after the role chunk) | 5000 | 1 | Same | OK, exit 0 |
| `chunk_timeout5s_keepalive_proxy` (comments relayed by `mnemon serve`) | 5000 | 1 | Same | OK, exit 0 |
| `total_timeout10s_keepalive` (comments for 15 s) | `options.timeout: 10000` | **4** | Client closed at **10.03 s** each time despite the comments | `Error: Timed out waiting for the response to complete`, exit 1 |

**SSE comment lines count as read activity.** The idle timer runs on raw response bytes before SSE framing (`$OC/packages/ai/src/route/transport/http.ts:119-124`).

Three timers apply; all three config keys work:

| Timer | Config key | Default | Notes |
| --- | --- | --- | --- |
| Read-idle | `chunkTimeout` | **900 000 ms** (`provider.ts:208` `DEFAULT_CHUNK_TIMEOUT_MS`, SOURCE) | Comments reset it |
| Whole-request | `timeout` | None | Keepalives do not extend it. Counted as a timeout retry (max 3). |
| Header wait | `headerTimeout` | 300 000 ms | See §6 |

### 8. `finish_reason: "length"`

| Run | Attempts | Gaps (s) | Body | Outcome |
| --- | --- | --- | --- | --- |
| `length` | **3** | 0.0, 0.0 (no backoff) | +2 each time: `assistant: "Truncated answer attempt-N"`, then `user: "Your last response hit the output token limit (stop reason: length). Do not apologize, recap, or repeat yourself. Break the remaining work into smaller pieces."` | All three texts printed, then `Error: Response still truncated after two output token limit continuations`, exit 1 |

The synthetic message is sent twice, then the run fails (`$OC/packages/core/src/session/runner/llm.ts:38` and `:315`).

### Mid-stream error signalling

| Run | Attempts | Body | Outcome |
| --- | --- | --- | --- |
| `error_event_then_ok` (role + `data: {"error":{…}}`, no text) | 2 (gap 2.2 s) | identical (full retry) | OK, exit 0 |
| `error_event_noretry` (same, + `x-should-retry: false`) | **1** | — | `Error: upstream failed`, exit 1 |
| `partial_error_event_then_ok` (text + error event) | 2 | +2 (Continue) | partial text and OK, error line, exit 1 |
| **`partial_error_event_noretry`** (text + error event + `x-should-retry: false`) | **1** | — | `Partial answer attempt-1`, then `Error: upstream failed`, exit 1. **No Continue.** |
| `partial_finish_error_then_ok` (text + `finish_reason: "error"` + `[DONE]`) | 2 | +2 (Continue) | partial text and OK, `Error: Provider reported an error (finish_reason: error)`, exit 1 |

**An SSE error event with `x-should-retry: false` on the response is the only server-side way found to end a partially delivered stream without triggering Continue.** It works because the failure is not an incomplete stream or read failure (`isInterruptedStream`, `$OC/packages/core/src/session/runner/step.ts`). Instead it is classified as a provider error, whose retryability the header controls.

### 9. Idempotency key and retry-count headers (VERIFIED: none)

Header names on every attempt in every run:

```
accept, accept-encoding, authorization, b3, connection, content-length, content-type, host,
traceparent, user-agent, x-opencode-client, x-opencode-project, x-opencode-session,
x-opencode-session-id, x-session-affinity, x-session-id
```

- There is **no idempotency key, attempt number or retry-count header**.
- Header values are identical across attempts except for `content-length` (Continue bodies grow), `traceparent` and `b3`.
- `traceparent` keeps **one trace-id across all attempts and continuations of a prompt**, with a new span-id per attempt. All 48 runs show this.
- Whether a later user turn in the same session gets a new trace-id is UNVERIFIED, because each run sends one prompt. Treat trace context as a diagnostic hint only, never as identity.
- Retries after a clean failure reuse the keep-alive connection. After an RST or a client timeout, OpenCode opens a new connection.

## Verified config keys

v1 shape, under `provider.<id>.options`. All are VERIFIED unless marked.

| Key | Default | Verified effect |
| --- | --- | --- |
| `headerTimeout` (ms; `false` disables, SOURCE) | 300 000 (SOURCE) | 5000 → client closes at 5.00 s and retries; 4 attempts |
| `chunkTimeout` (ms) | 900 000 (SOURCE) | 5000 → client closes 5.0 s after the last byte; SSE comments reset it |
| `timeout` (ms, whole request) | none | 10000 → closes at 10.03 s despite keepalives; 4 attempts |

Other configuration facts:
- **v2 shape** `providers.<id>.settings.{headerTimeout, chunkTimeout, timeout}` uses the same fields (`$OC/packages/schema/src/config/provider.ts`). SOURCE, not run.
- **Retry count.** No config key exists. The session schedule is fixed: 10 retries, plus at most 3 retries for timeouts.
- **Retry hook (VERIFIED).** It disables both automatic retries and Continue. The file `$OPENCODE_CONFIG_DIR/plugins/retry-off.js` is auto-discovered (`core/src/plugin/source-directory.ts`):

  ```js
  export default {
    id: "mnemon-retry-off",
    setup: async (ctx) => {
      await ctx.session.hook("retry", (event) => { event.decision = { retry: false } })
    },
  }
  ```

  `plugin_retry_off_s500` made 1 attempt (vs 11 without the hook). `plugin_retry_off_partial_eof` made 1 attempt and no Continue. The `length` continuation is a separate path and is not a retry decision (SOURCE). The hook was not run against `length`.
- **Server-side `x-should-retry: false`.** It disables full resends for every pre-output failure tried: 4xx/5xx, an in-stream error event, an incomplete stream, an RST and a client idle timeout. It does not disable Continue after an incomplete stream or a read failure once output has started.

## Corrections to `docs/probes/harnesses.md` (OpenCode)

1. §8: `[DONE]` is **not** required; only `finish_reason` is.
2. §3: "Up to 10 retries" is confirmed: 11 attempts, ≈80–100 s with every attempt failing. Continues share that budget. The `length` continuation is separate: at most 2, with no delay.
3. §3: 409 is retryable (confirmed). `retry-after-ms` works. `retry-after` is a floor (max with the backoff), not a replacement.
4. §3: `x-should-retry` sent on a **200 stream response** also governs failures inside that stream (error event, missing `finish_reason`, RST, client chunk timeout) before output. It does not govern Continue, except when the failure is an in-stream error event, which the header does control.
5. §4: The read-idle timer counts SSE comments. Previously INFERRED, now VERIFIED, direct and through `mnemon serve`.
6. §7: Reasoning from interrupted messages is flattened into `content`, concatenated with the visible text without a separator. Previously source-only, now VERIFIED.
7. New: `opencode run` uses `PWD` for its directory and reads non-TTY stdin to EOF. Both matter for scripted harness runs.
8. New, about user visibility: `opencode run` exits 1 whenever any step failed, even when a Continue later succeeded. A pre-output retry that later succeeds exits 0 with no error shown.

## Implications for Mnemon

**OpenCode behavior Mnemon has to design around:**
- OpenCode sends no idempotency key.
- It resends **identical bodies** after any pre-output failure, up to 10 times over about 80–100 s; timeouts retry at most 3 times.
- After **any** streamed text or reasoning, a bare close, RST, missing `finish_reason` or read timeout produces a **Continue**. That is a different request: it extends the visible parent with the failed assistant message, its reasoning flattened into the text, plus a fixed synthetic user message. `x-should-retry` cannot stop this.
- The client closes its socket at each timeout, so Mnemon's disconnect handling sees every abandoned attempt.

### Status codes and headers to use

| Situation | Response | Why (fixture) |
| --- | --- | --- |
| **Overload (queue full)** | `429` with `retry-after: <seconds>` (or `retry-after-ms`) set to a realistic queue-drain estimate of at least 2 s. Do **not** send `x-should-retry: false`. Use an error message such as `"mnemon: queue full"`. | OpenCode waits max(backoff, header) and resends the identical body, up to 10 times (`s429_ra15_then_ok`: 15.0 s gap). Nothing was accepted, so the resend is a fresh admission, not a duplicate. Add `x-should-retry: false` only when the overload is not expected to clear within roughly 90 s (`s429_noretry`: 1 attempt). |
| **In-progress duplicate** (same session, visible parent and fingerprint as an outstanding attempt) | `409` with `x-should-retry: false` and a clear `error.message`. Cancel the old attempt when its connection drops. | OpenCode only resends after giving up on its previous connection, so the original attempt is orphaned. Without the header, 409 is retried 10 times (`s409`); with it, there is one attempt (`s409_noretry`). If Mnemon instead wants OpenCode to retry once cancellation cleanup finishes, use `503` with `retry-after: <cleanup seconds>` (a verified floor, `s503_ra12_then_ok`). The `retry-after` floor for 409 is untested. |
| **Ambiguous completed retry** (identical body arrives after Mnemon committed a completed response that never reached the client) | `409` with `x-should-retry: false` and a documented error code in the body, for example `mnemon_ambiguous_completion`. | Never regenerate silently. The header makes this one visible failure (`s409_noretry`), and the user re-prompts. A Continue request (synthetic interrupted message plus a failed partial assistant message) is **not** a duplicate. It extends the visible parent and must be reconciled as an append, with the flattened reasoning text mapped back to the archived partial generation. |
| **Upstream failure before Mnemon sends response headers** | `502` or `503` with `x-should-retry: false` when Mnemon has already retried internally or the failure is permanent. Use `503` with `retry-after` when an OpenCode-driven resend is wanted. | 5xx is otherwise retried 10 times (`s500`, `s502`, `s503`). |
| **Upstream failure after a 200 stream started** | Always end with an SSE error event, `data: {"error":{"message":…,"type":"server_error"}}`, followed by a clean end of the chunked body. Never a bare close, an RST, or a missing `finish_reason`. Put `x-should-retry: false` on **every** streaming 200 response. | With the header, a pre-output failure is not resent (`error_event_noretry`). After visible output, the message fails with its partial text kept and no Continue (`partial_error_event_noretry`). This leaves internal retry to Mnemon, which can dedupe and cancel, and keeps the harness transcript linear. Without the header, OpenCode resends or Continues. |
| **Token allowance exhausted** | `finish_reason: "length"` as planned. | OpenCode automatically sends up to 2 continuation requests with the synthetic output-limit message (`length`). Mnemon will see these as ordinary appended turns. The per-request allowance therefore covers each of up to 3 consecutive OpenCode requests, not the logical answer. |

Cautions:
- `x-should-retry: false` on every stream also disables OpenCode's own resend after a client-side idle timeout before output (`chunk_timeout5s_idle_role_noretry`). That is acceptable only if Mnemon's keepalives make such timeouts impossible, which the next section requires.
- A Mnemon process crash mid-stream still produces an RST, which triggers a Continue whenever output had started. Only the plugin `retry` hook prevents that. The Phase 1 reconciliation must accept the Continue shape regardless.
- Keep proxy error messages clear of OpenCode's classifier patterns (`$OC/packages/ai/src/provider-error.ts`):
  - Context-overflow phrases such as "too many tokens" or "exceeds the context window" trigger overflow handling.
  - Quota phrases such as "usage limit" or "quota exceeded" on a 429 make it non-retryable.
  - These classifier effects are SOURCE, not exercised.

### Keepalive interval

**Recommendation: one SSE comment every 15 s from the moment the 200 headers are sent**, through queue wait, prefill and internal recall, until the first visible delta.
- Comments are verified to reset OpenCode's read-idle timer, both direct and through `mnemon serve`.
- 15 s is 60× under the 900 s default `chunkTimeout`, and still 2× under a 30 s value a user might set.
- Send the 200 status line promptly at admission, well inside the 300 s header timeout. A header timeout causes up to 3 identical resends of a request Mnemon may still be working on.

### Request-wide deadline

OpenCode has **no total deadline** by default: `timeout` is unset, and keepalives keep the idle timer alive indefinitely. Mnemon's deadline is therefore the only bound on a logical request.

**Recommendation: a request-wide deadline of 600 s by default, measured from arrival and including queue wait**, configurable.
- On expiry, cancel the upstream attempt and finish the stream with an SSE error event. With `x-should-retry: false` on the response, OpenCode makes no resend or Continue.
- 600 s ends a stuck request well before the ≈15 min a silent upstream would take to hit OpenCode's 900 s idle limit. Because Mnemon's keepalives hide upstream silence from the client, Mnemon is the only component that can stop a stuck request.
- If a user sets the provider's `timeout`, document that Mnemon's deadline must be no more than `timeout` minus a 10 s cleanup and error-delivery margin.
- The value is a policy choice, not a measured client limit. Revisit it once Strata generation rates for the longest allowed `max_completion_tokens` are measured.

## Not covered

- Native v2 config shape (`providers.<id>.settings`): SOURCE only.
- `compatibility.requireFinishReason: false`: SOURCE only.
- The retry hook's effect on the `length` path.
- Trace-id behavior across user turns.
- Interactive TUI presentation; only `opencode run` output was captured.
- Tool-call streams interrupted mid-arguments.
- Anthropic and Responses routes.
- The default 300 s header timeout and 900 s idle timeout are SOURCE plus the 8 s-delay control. They were not waited out.
