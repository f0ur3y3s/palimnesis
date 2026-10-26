# OpenCode 2.1.4 hidden-stream probe (Phase 3B H1)

Oct 26, 2026 · Phase 3B slice S0 · fake upstream only

## What this is

Phase 3B's assembler (`docs/plans/phase3b.md` §2.2–§2.4) can show OpenCode stream shapes it has never received from Strata directly:
- one visible response built from several upstream generations, where reasoning resumes after text;
- a `finish_reason: "length"` stop when a hidden-tool cap or the allowance runs out;
- an in-stream error raised during a continuation.

This probe records what OpenCode 2.1.4 stores for each shape and what it sends on the next request.

Every result comes from a real `opencode.exe` 2.1.4 talking to the scripted fault server. No model server was involved.

Markers:
- **VERIFIED**: observed in a fixture here.
- **UNVERIFIED**: inferred, not exercised.

## Setup

**Server.** The probe uses `eval/probes/opencode_fault_server.py` with new `hs_*` scenarios.
- Attempt 1 gets the scenario's stream. Every later attempt gets `OK from fault server` with `finish_reason: "stop"`.
- One chunk id, `chatcmpl-fault-1`, is used for the whole of attempt 1. There is a single role chunk and word-sized deltas. This is the consistent-id form the assembler emits.
- The composite (`HS_COMPOSITE`) is these four parts, in stream order:
  - R1 = `R1 first thought attempt-1\n` (reasoning)
  - T1 = `T1 first visible attempt-1.` (text)
  - R2 = `\nR2 second thought attempt-1\n` (reasoning)
  - T2 = ` T2 second visible attempt-1.` (text)

  The whitespace at each join makes any trimming or added separator visible.
- The error event has the proxy's shape: `data: {"error": {"message": "palimnesis: upstream stream failed", "type": "server_error", "code": "upstream_stream_failed"}}`, followed by EOF, with `x-should-retry: false` (`archive._error_event`).

**Driver.** `eval/probes/opencode_hidden_stream_probe.py`.
- It uses `eval/oc_harness.Home` for isolation:
  - an allowlisted environment;
  - HOME, XDG, TEMP and `OPENCODE_CONFIG_DIR` under the run's root;
  - `OPENCODE_DISABLE_PROJECT_CONFIG`;
  - a fresh git workspace with a `notes.txt`;
  - `--standalone`;
  - the message on stdin;
  - the process tree killed at 150 s.
- The config is `oc_harness.config` with `baseURL` set to the fault server's `/v1`. It sets `reasoningField: reasoning_content` and `limit.output: 8192`. No plugin is loaded.
- Each run does three steps:
  1. `opencode run` with "First question: what is 2+2?";
  2. `opencode run --session <id>` with "Next question: what is 3+3?";
  3. `opencode session export <id>`.

**Fixtures.** Each run writes to `eval/fixtures/opencode-2.1.4/hidden_stream/<run>/`:
- `req-NN.json`: the exact request body bytes;
- `requests.jsonl` and `events.jsonl`;
- `turn{1,2}.json`, `export.json`, `opencode.json` and `meta.json`.

`hidden_stream/summary.json` lists each request's messages after the system prompt, plus the export's parts.

## Results (VERIFIED unless marked)

Abbreviations:
- `R` = R1 + R2 = `R1 first thought attempt-1\n\nR2 second thought attempt-1\n`
- `T` = T1 + T2 = `T1 first visible attempt-1. T2 second visible attempt-1.`
- `LEN` = `Your last response hit the output token limit (stop reason: length). Do not apologize, recap, or repeat yourself. Break the remaining work into smaller pieces.`

| Run | Attempt 1 stream | Turn 1 | Stored (export parts of that message) | Resent on the next request |
| --- | --- | --- | --- | --- |
| `a_composite_stop` | R1 T1 R2 T2, `stop` | 1 request, exit 0 | `reasoning` = R, `text` = T; finish `stop` | `{"role":"assistant","content":T,"reasoning_content":R}` |
| `a2_composite_tool` | R1 T1 R2 T2, `read` call, `tool_calls` | 2 requests (tool step, answer), exit 0 | `reasoning` = R, `text` = T, `tool` (completed) | `content` T, `tool_calls` [`call_hs_1` `read` `{"path":"notes.txt"}`], `reasoning_content` R, then the tool result |
| `a3_text_after_tool` | T1, `read` call, T2, `tool_calls` | 2 requests, exit 0 | `text` = T1 + T2, then `tool` | `content` = `T1 before the call attempt-1. T2 after the call attempt-1.` with the call, `reasoning_content` `""` |
| `b_length_text` | text, `length` | 2 requests, exit 0 | `text`; finish `length`; then a `synthetic` message | partial `{"content":"Truncated answer attempt-1","reasoning_content":""}` plus user `LEN`, sent at once as attempt 2 |
| `b2_length_text_noretry` | same, with `x-should-retry: false` | 2 requests, exit 0 | same as b | same as b; the header changes nothing |
| `b3_composite_length` | R1 T1 R2 T2, `length` | 2 requests, exit 0 | `reasoning` = R, `text` = T; finish `length`; `synthetic` | `{"content":T,"reasoning_content":R}` plus user `LEN` |
| `c_text_err_noretry` | text, error event | 1 request, exit 1 | `text`; finish `error`, `provider.internal` | turn 2: `{"content":"Partial answer attempt-1","reasoning_content":""}` |
| `c2_composite_err_noretry` | R1 T1 R2 T2, error event | 1 request, exit 1 | `reasoning` = R, `text` = T; finish `error` | turn 2: `{"content": R + T, "reasoning_content": ""}`, that is `R1 first thought attempt-1\n\nR2 second thought attempt-1\nT1 first visible attempt-1. T2 second visible attempt-1.` |

### (a) Composite response with reasoning resuming after text

- **OpenCode merges each kind into one part.** All reasoning deltas of the message go into one `reasoning` part and all text deltas into one `text` part. The reasoning part comes first, whatever the stream order.
- **The joins are byte-exact.** Each part is a plain concatenation in arrival order, with no separator and no trimming: `R` keeps the `\n` that ends R1 and the `\n` that starts R2.
- **The resend carries `reasoning_content` = R1 + R2 and `content` = T1 + T2.** The interleaving R1 T1 R2 T2 cannot be recovered from the client's copy.
- **With a tool call (a2),** key order is `role, content, tool_calls, reasoning_content`, as in `docs/harnesses.md`. The external call keeps its id, name and compact arguments.
- **Text after a tool call (a3)** is accepted. It is stored in the same `text` part as the text before the call, and resent as `content` next to `tool_calls`. Through the template, that text renders before `<tool_call>`, not after it as the model generated it **[inferred from the template, not rendered here]**.
- **A consistent chunk id caused no visible issue.** Streams whose chunk ids change between generations were not tested **[UNVERIFIED]**.

### (b) Text-only `finish_reason: "length"`

- **The turn is not over.** OpenCode immediately sends a second request in the same turn: the partial assistant message, then a synthetic user message `LEN`.
- **The partial is kept as it was streamed, not flattened.** Reasoning stays in `reasoning_content` (b3); this differs from the error case.
- **`x-should-retry: false` does not stop the follow-up** (b2).
- In the export, the follow-up appears as a message of type `synthetic`. Turn 2 resends the length message and `LEN` unchanged.
- Here attempt 2 succeeded, so there was one follow-up. `docs/harnesses.md` (Timeouts and retries) records two follow-ups and then failure when every attempt ends in `length`.

### (c) Text, then an in-stream error event

- **c, text only, repeats the Phase 1 result** (`opencode_partials.md`, run B). There is no retry and no Continue; turn 1 exits 1. Turn 2 resends the text as `content` with `reasoning_content: ""`.
- **c2, the composite, is flattened as merged reasoning, then merged text** (R1 R2 T1 T2), joined with no separator. It is not flattened in stream order (R1 T1 R2 T2).
- In both, the export keeps the parts unflattened (`reasoning` R, `text` T) with `finish: "error"`. The flattening happens only when the history is resent.

## Implications for Phase 3B

These are for `docs/harnesses.md` and the S2/S5 design. No core module should key on them.

- **Completed composite.** The client copy is `content` = all text joined in stream order, and `reasoning_content` = all reasoning joined in stream order. Reconciliation must match the resend against those joins, and upstream rendering must split it back into per-generation parts. This is §2.1's composite with text and reasoning "concatenated in ordinal order".
- **Partial match after an error.** The flattened `content` is all reasoning joined, then all text joined. Plan Finding 6 says a composite response must use stream order, and §2.1 gives the composite a `sent` field in stream order. Matching in stream order would **not** match OpenCode's resend. Today's `reasoning + text` rule, applied to the whole composite, does.
- **`length` stops.** A cap-driven `length` stop (§2.4) makes OpenCode send a new request at once, with `LEN` as a new user message. The hidden loop then starts a new visible response with a new allowance. Up to two such follow-ups per turn are expected.
- **Text after an external call** is accepted by OpenCode, but moved before the call in its copy. If the assembler forwards it, the next request's render will not match the generated token order from that assistant turn on **[inferred]**.
