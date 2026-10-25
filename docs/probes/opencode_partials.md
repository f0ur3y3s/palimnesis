# OpenCode 2.1.4 partials probe: what the next request carries after a partial stream

Oct 24, 2026 · Phase 1 slice 0 · fake upstream only

## What this is

This probe answers one question for D10.3, D10.4 and D10.12: when Palimnesis ends a stream after partial output, what does OpenCode 2.1.4 send on the next request in that session? "Next request" means OpenCode's own Continue resend, if any, and then the next user turn.

Every result comes from a real `opencode.exe` v2.1.4 talking to the deterministic fault server. No live Strata server was involved.

Markers:
- **VERIFIED**: observed in a fixture here.
- **UNVERIFIED**: inferred, not exercised.

## Setup

**Server.** `eval/probes/opencode_fault_server.py`, extended with:
- `("error", message, code)`: the code is now configurable. Every scenario here sends `data: {"error": {"message": "palimnesis: upstream stream failed", "type": "server_error", "code": "upstream_stream_failed"}}`.
- `("tool_call", id, name, [fragments])`: streams one tool call at index 0.
- `--raw-dir`: writes the exact bytes of each request body.
- The `pp_*` scenarios. In each, attempt 1 fails as described and every later attempt gets a normal answer, `OK from fault server`, with `finish_reason: stop`.

**Driver.** `eval/probes/opencode_partials_probe.py` gives each run a fresh isolated OpenCode home under `<scratchpad>/opencode-partials/runs/<run>/`. The isolation follows `docs/probes/opencode_faults.md`:
- XDG dirs, `OPENCODE_CONFIG_DIR`, `HOME`, `USERPROFILE`, `OPENCODE_TEST_HOME`, `TEMP` and `TMP`
- `OPENCODE_DISABLE_PROJECT_CONFIG=1`
- `PWD` set to the run's `work` dir
- stdin at EOF
- `--standalone`

Each run then does:

1. `opencode run --standalone -m <model> "First question: what is 2+2?"`
2. `opencode run --standalone -m <model> --session <id> "Next question: what is 3+3?"`, where `<id>` is the `x-opencode-session-id` of turn 1's first request.

**Config.**
- `v2`, the default: the shipped `integrations/opencode/opencode.json` (`providers.palimnesis`, `compatibility.reasoningField: reasoning_content`, `limit.output: 8192`) plus `plugins/palimnesis.ts`. `PALIMNESIS_PROXY_ORIGIN` points at the fault server, so every request goes to `/s/<sessionID>/v1/chat/completions` with `X-Palimnesis-Kind: primary`, exactly as with Palimnesis.
- `v1`: the fault probe's config, with provider `fault` and no `reasoningField`. It is used only for the `_v1` runs.

**Fixtures.** `eval/fixtures/opencode-2.1.4/partials/<run>/` holds:
- `req-NN.json`: the exact request body bytes, one file per request.
- `requests.jsonl`: headers, attempt and turn for each request.
- `events.jsonl`: the server's response milestones.
- `turn{1,2}.std{out,err}.txt`, `opencode.json` and `meta.json`.

`partials/summary.txt` is the output of `eval/probes/opencode_partials_summary.py`.

## Results common to every run (VERIFIED)

- **The failed partial assistant message is never omitted.** It appears in every later request of the session, the Continue (where one happens) and turn 2.
- **The history before the failed turn is byte-identical.** Every request in every run begins with the exact bytes of turn 1's first request up to the end of its last message, which is the failed turn's user message. Everything after the `messages` array is also byte-identical: `tools`, `stream`, `stream_options` and `max_completion_tokens`. The same day's system prompt (date, `<env>`) did not change between the two processes.
- **The original user message of the failed turn is still present**, unchanged.
- **The flattening is specific to failed messages.** In a failed assistant message, reasoning is flattened into `content`: the reasoning comes first, then the text, joined with no separator and with no trimming or normalization of whitespace (A3, D3). With `reasoningField`, `reasoning_content` is present but `""`. Without `reasoningField` (v1), the key is absent. The control runs show that a *completed* message keeps its reasoning in `reasoning_content`, byte-exact including leading and trailing newlines (Z, Z2). Completed messages without reasoning carry `reasoning_content: ""`, the same as a partial message.
- **Key order.** An assistant message is `role, content, tool_calls?, reasoning_content?`. A tool message is `role, tool_call_id, content`.
- **Turn 2 needs no rewrite.** No synthetic message and no error text appear in assistant content. The only error text that reaches history is the synthetic tool result in tool-call runs (E, E2, E3).
- **Session and trace.**
  - The `/s/<id>/` prefix and `x-opencode-session-id` are the same for turn 1, the Continue and turn 2. `X-Palimnesis-Kind` is `primary` on all of them.
  - The `traceparent` trace-id is shared by a turn and its Continue, but turn 2 gets a **new trace-id**. This closes the open question in `opencode_faults.md`.
- The user prompts arrive wrapped in literal double quotes (`"\"First question…\""`). This is how `opencode run` passes its message argument on Windows, and it matches the live fixtures. It does not affect the results.

## Per-scenario results

Abbreviations:
- `R` = `Thinking about attempt-1`, the streamed reasoning.
- `T` = `Partial answer attempt-1`, the streamed text.
- `INT` = `The previous response was interrupted. Continue from where you left off without repeating completed content.`
- `U1` and `U2` are the turn 1 and turn 2 user messages.
- `S` is the system message.
- `OKA` = `{"role":"assistant","content":"OK from fault server","reasoning_content":""}`.

### A. Reasoning and text, then an error event, with `x-should-retry: false` (`A_reason_text_err_noretry`; v1 in `A_reason_text_err_noretry_v1`)

| | |
| --- | --- |
| Turn 1 requests | 1 (no retry, no Continue). Prints `T` and `Error: palimnesis: upstream stream failed`; exit 1. |
| Turn 2 messages | `S, U1, {"role":"assistant","content":"Thinking about attempt-1Partial answer attempt-1","reasoning_content":""}, U2` |
| Partial present? | Yes. `content` = `R + T`, no separator. `reasoning_content` is `""` (v2) or absent (v1). |
| Synthetic or error text? | None. |
| Prior history bytes | Identical. |

**A2. Reasoning only, then an error event** (`A2_reason_err_noretry`). Turn 1 printed only the error. Turn 2 carries `{"role":"assistant","content":"Thinking about attempt-1","reasoning_content":""}`: the reasoning alone becomes `content`.

**A3. Whitespace-padded reasoning and text** (`A3_ws_reason_text_err_noretry`). The reasoning was `\nThinking about attempt-1\n\n` and the text `\n\nPartial answer attempt-1 \n`. `content` is exactly `"\nThinking about attempt-1\n\n\n\nPartial answer attempt-1 \n"`.

### B. Text only, then an error event, with `x-should-retry: false` (`B_text_err_noretry`)

| | |
| --- | --- |
| Turn 1 requests | 1. Prints `T` and the error; exit 1. |
| Turn 2 messages | `S, U1, {"role":"assistant","content":"Partial answer attempt-1","reasoning_content":""}, U2` |
| Partial present? | Yes, `content` = `T`. It is indistinguishable on the wire from a completed message with that text. |
| Synthetic or error text? | None. |
| Prior history bytes | Identical. |

### C. Text, then a bare close, with `x-should-retry: false` (`C_text_eof_noretry`)

| | |
| --- | --- |
| Turn 1 requests | 2. Attempt 2 is a **Continue**: `S, U1, {"role":"assistant","content":"Partial answer attempt-1","reasoning_content":""}, {"role":"user","content":INT}`. It uses the same connection and trace-id. Output: `T`, `OK from fault server`, `Error: OpenAI Chat stream ended without finish_reason`; exit 1. |
| Turn 2 messages | `S, U1, partial(T), user INT, OKA, U2` |
| Partial present? | Yes, in both the Continue and turn 2. Same shape as B. |
| Synthetic or error text? | The `INT` user message, which stays in history. No error text. |
| Prior history bytes | Identical. |

The header has no effect on this path: C is identical to D.

### D. Text, then a bare close, no header: the default Continue (`D_text_eof`; `D2_reason_text_eof`, `D2_reason_text_eof_v1`, `D3_ws_reason_text_eof`)

| | |
| --- | --- |
| Turn 1 requests | 2. Same as C. |
| Continue body | `S, U1, partial, user INT`. The partial is `content` = `T` (D), `R + T` (D2 and D2_v1), or the whitespace-exact `R + T` (D3). `reasoning_content` is `""` (v2) or absent (v1). |
| Turn 2 messages | The Continue's messages, then the continuation's completed answer (`OKA`), then `U2`. |
| Partial present? | Yes. The partial is byte-identical in the Continue and in turn 2. |
| Synthetic or error text? | `INT` only, and it persists into turn 2. |
| Prior history bytes | Identical. |

### E. Partial tool call (name plus partial arguments), then an error event, with `x-should-retry: false` (`E_tool_err_noretry`; with reasoning and text in `E2_reason_text_tool_err_noretry`; bare close in `E3_tool_eof`)

The streamed arguments were `{"filePath": "notes.tx`: invalid, unterminated JSON.

| | E (tool only, error event) | E2 (`R` + `Let me look attempt-1` + tool, error event) | E3 (tool only, bare close, no header) |
| --- | --- | --- | --- |
| Turn 1 requests | 1. Output: `Error`, `✗ Read failed`, `Error`; exit 1. | 1. Output adds the text. | **2: a Continue.** The tool-call delta alone counts as output; the faults doc only showed this for text and reasoning. |
| Assistant message | `{"role":"assistant","content":null,"tool_calls":[{"id":"call_fault_1","type":"function","function":{"name":"read","arguments":"{}"}}],"reasoning_content":""}` | Same, with `content` = `"Thinking about attempt-1Let me look attempt-1"` | Same as E |
| Then | `{"role":"tool","tool_call_id":"call_fault_1","content":"{\"error\":{\"type\":\"provider.internal\",\"message\":\"palimnesis: upstream stream failed\",\"status\":200,\"response\":{\"body\":\"<the SSE error data payload, verbatim>\"}},\"content\":[]}"}` | Same | Tool message whose content is `{"error":{"type":"provider.invalid-output","message":"OpenAI Chat stream ended without finish_reason","status":200},"content":[]}`, then `user INT` |
| Turn 2 messages | `S, U1, assistant(tool_calls), tool(error), U2` | Same | `S, U1, assistant(tool_calls), tool(error), user INT, OKA, U2` |
| Prior history bytes | Identical | Identical | Identical |

Facts drawn from these runs:
- The tool call keeps its streamed `id` and `name`.
- Its `arguments` become `"{}"`: the partial fragments are dropped. Whether arguments that were complete, valid JSON before the failure would be kept is UNVERIFIED.
- The tool was never executed.
- OpenCode writes a synthetic tool result that embeds the failure. For an error event, that includes Palimnesis's exact error-event data payload as `response.body`.

### Control: completed reasoning answer (`Z_control_reason_text_ok`, `Z2_control_ws_reason_text_ok`)

Turn 2 carries `{"role":"assistant","content":"Complete answer attempt-1","reasoning_content":"Thinking about attempt-1"}`. Z2 keeps the whitespace in both fields exactly.

## Reconciliation rules implied

Definitions:
- `D` is the concatenation, in emission order, of the reasoning deltas and then the content deltas that Palimnesis wrote to the client for the archived partial generation.
- `|R|` is the length of the reasoning part of `D`.
- An *error-event ending* is an SSE error event followed by a clean end, sent with `x-should-retry: false`.

1. **Failed partial without tool calls (A, A2, A3, B, C, D, D2, D3).**
   - The client message matches when `role == "assistant"`, `content` is a string, `content == D[:k]` for some `0 < k ≤ len(D)`, and `tool_calls` is absent.
   - `reasoning_content` must be `""` when present, and may be absent (v1 configs).
   - The split is `reasoning = D[:min(k, |R|)]` and `text = D[min(k, |R|):k]`. There is no separator between them, and no trimming.
   - After an error-event ending, the stream ended cleanly, so expect `k == len(D)`. After an RST or crash (D10.12), `k` may be shorter, because unread bytes are lost. Record `k` as the acknowledged extent (D10.3).
   - A non-empty `reasoning_content` never occurs on a failed partial. If it occurs, the message is a completed answer.
   - A text-only partial (B) is identical on the wire to a completed message with the same text. Classify it from the archive outcome of the bound occurrence, never from the message alone.
2. **Failed partial with a tool call (E, E2, E3).**
   - The assistant message has `content == D[:k]`, or `null` when `k == 0`.
   - It has `tool_calls == [{"id": <streamed id>, "type": "function", "function": {"name": <streamed name>, "arguments": "{}"}}]`. Match on id and name; the arguments are always the literal `"{}"`, not the streamed prefix.
   - `reasoning_content` is `""` or absent.
   - It is followed by a client-authored `role: "tool"` message for that `tool_call_id` whose content is OpenCode's error JSON. Accept that message as ordinary appended client content. Do not require particular bytes: they embed Palimnesis's error payload, or OpenCode's own message for a bare close.
3. **Next turn after an error-event ending (A, B, E).** The request is an **extension**, not a resend:
   - `visible parent (byte-identical) + U_failed (unchanged) + partial (rules 1–2) [+ tool result] + new user message`.
   - There is no synthetic user message.
   - Attach the partial as acknowledged and append the new turn.
4. **Continue (any bare close, missing `finish_reason`, RST or read timeout once any text, reasoning or tool-call delta has streamed; `x-should-retry` is irrelevant) (C, D, E3).**
   - The Continue request is `visible parent + U_failed + partial (rules 1–2) [+ tool result] + {"role":"user","content":"The previous response was interrupted. Continue from where you left off without repeating completed content."}`. Match the string exactly.
   - The next user turn is that sequence, plus the continuation's completed assistant message, plus the new user message. It is an ordinary append on top of the Continue.
5. **"Message omitted → superseded partial" (D10.4) was never observed.** In no scenario did OpenCode 2.1.4 drop the failed partial or resend `parent + U_failed` alone after output had streamed. An identical resend happens only when no output streamed: a pre-output failure, per `opencode_faults.md`. Keep D10.4 only as a defensive rule for other harnesses or user edits. For OpenCode, a request whose history lacks a partial that the client acknowledged is divergence, unless `k == 0` was possible: a crash before any byte was read.
6. **Byte-level prefix.** For every shape above, everything before the failed turn's assistant position is byte-identical to the failed request's `messages` bytes. Everything after the `messages` array is byte-identical too. A prefix-based raw delta (D10.7) therefore applies unchanged.

## Not covered

- Interleaved reasoning after text: emission order is assumed for `D`.
- Arguments that were complete, valid JSON before the failure.
- Several tool calls in one partial.
- A Continue that itself fails.
- An RST after partial output with an error-event ending already written.
- The interactive TUI.
