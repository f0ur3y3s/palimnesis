# Strata probe results (Phase 0)

Probed 2026-10-24 between 19:39 and 20:12 UTC against `http://192.168.1.173:8080`. These results describe the installed server, not upstream defaults. Scripts are in `eval/probes/` and fixtures are in `eval/probes/fixtures/`. Run a probe with:

```
uv run --no-project --python 3.12 --with httpx python eval/probes/<script>.py
```

`p02_template_render.py` also needs `--with jinja2 --with tokenizers` and a path to `tokenizer.json`.

Labels: **[verified]** means measured here. **[docs]** means it comes from the upstream repo's `main` branch docs and was not measured. **[unverified]** means it is inferred or untested.

## 0. Caveats that affect every number below

- **The server configuration changed during probing.** At the start it had `n_ctx=32768`, default temperature 0.6, vision on and the conversation cache off. Fixtures from that run are in `fixtures/before_restart_ctx32k/`.
- The server went down at 19:47:49Z. My in-flight request received `503 {"error":{"type":"server_error","message":"the engine stopped unexpectedly (exit code -15); the next request restarts it"}}`, then connections were refused for about 3.5 min.
- It came back with `n_ctx=65536`, temperature 1.0, vision off and an 8192 MiB conversation cache. All other fixtures come from this configuration.
- **There was a second outage at 20:01:25Z, about 6.5 min long.** It happened about 14 s into my streaming 20K-token request with `return_progress: true`.
  - The stream ended with no error event and no `[DONE]` (`sse_oa_long_prefill_progress_TRUNCATED_server_died.sse`).
  - The configuration was unchanged on restart.
- **The cause of both outages is unknown [unverified].** Exit code −15 is SIGTERM, and the first outage brought a configuration change, which points to the operator. The request that hit the first outage succeeded when repeated. I did not repeat `return_progress`.
- **Palimnesis must read `n_ctx` from `/props` and must not hard-code 32768.**
- Other clients used the server during the probes. For the first 8 minutes a client looped requests of about 100 s each, and later clients sent requests now and then. Every probe tolerates queueing, and the cancellation numbers come from `/status` transitions and the server's own request records.
- Prefill speed varies a lot because experts are offloaded to RAM. I measured about 512 tok/s steady, about 435 tok/s for a cold 20K prompt, and as low as about 137 tok/s right after a restart.

## 1. Version, build and headers [verified]

| Source | Value |
| --- | --- |
| `/props` `build_info` | `Strata 0.1.48` |
| `/v1/status` `engine` and `/metrics` `engine.version` | `0.1.48` |
| Upstream repo | Latest tag `v0.2.4.2` (app release numbering). The `main` branch docs describe 0.1.39–0.1.45+ engine features, so they may not match 0.1.48 exactly. |

- **Model:** `qwen3.8-flash-next-iq3_xxs`, from the GGUF `Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS`. It is a hybrid model with a recurrent state and MTP drafting.
- **KV cache:** int8.
- **`prefill_cap`:** 8192.
- **Headers:**
  - `Server: BaseHTTP/0.6 Python/3.12.15`.
  - Responses are HTTP/1.0 with `Connection: close`. There is no keep-alive and no chunked encoding.
  - SSE responses add `Cache-Control: no-cache` and `X-Accel-Buffering: no`.
  - There is no version header and no request-id header.
- **Metadata endpoints** (all GET): `/health`, `/api/health`, `/props`, `/v1/models`, `/models`, `/slots`, `/status` and `/v1/status`.
  - `/v1/status` lists `dialects` and `context`.
- **Metrics endpoints** (all GET): `/metrics` (JSON, or Prometheus text with `Accept: text/plain`), `/metrics/prometheus` and `/mcp`.
  - `/metrics` JSON includes `requests[]`: per-request `reused`, `prompt_read`, `finish`, `first_engine_token_s` and more.
  - `/version` returns 404.
- Script: `p01_server_info.py`. Fixtures: `props.json`, `v1_status.json`, `metrics_sample.json`, `metrics_prometheus.txt`, `routes.json`.

## 2. Chat template and reasoning in history [verified]

The verbatim template is in `fixtures/strata_chat_template.jinja`. It was identical before and after the restart.

It is the Unsloth variant of `Qwen/Qwen3.8-Flash-Next`'s `chat_template.jinja`. The variant merges leading system and developer messages, maps `high` to `xhigh`, drops the "No user query found" check, and requires tool-call arguments to be a mapping.

`/props` `chat_template_caps.supports_preserve_reasoning` is `true`.

The lines that control reasoning carryover:

```jinja
115  {%- if message.reasoning_content is string %}
119  {%- if preserve_thinking is undefined or preserve_thinking is true or loop.index0 > ns.last_query_index %}
         {{- '<|im_start|>' + message.role + '\n<think>\n' + reasoning_content + '\n</think>\n\n' + content }}
     {%- else %}
         {{- '<|im_start|>' + message.role + '\n' + content }}
102  {%- set ns.last_query_index = index %}   {# last user msg that is not purely <tool_response> #}
178  {%- if enable_thinking is defined and enable_thinking is false %} {{- '<think>\n\n</think>\n\n' }} {%- else %} {{- '<think>\n' }}
```

What the installed server actually renders:

- **All earlier reasoning is kept, in every assistant turn, including completed earlier user turns.** `preserve_thinking` is undefined, so line 119 is always true.
  - Verified by token counts: a prior turn with 17 tokens of reasoning renders as 90 tokens, against 73 without it. The same 17-token difference shows on the OpenAI path (55 against 38).
  - Thinking-disabled requests also keep it (50 against 33).
- **The `last_query_index` branch is never used.** That branch would keep only the current user turn's tool steps.
- **`chat_template_kwargs: {"preserve_thinking": false}` is ignored** on both `/v1/chat/completions` and `/v1/messages`. The token count is unchanged. Rendering locally with that flag would give 69, not 90.
- **An assistant turn with no reasoning still gets an empty `<think>\n\n</think>\n\n` block.** History without reasoning is therefore not byte-identical to "content only".
- **Input reasoning sources:**
  - On `/v1/messages`, reasoning comes from Anthropic `thinking` blocks. The `signature` is ignored, and responses carry `"signature": ""`.
  - On `/v1/chat/completions`, it comes from `reasoning_content`.
  - An OpenAI-style `reasoning_content` field sent to `/v1/messages` is ignored.
- **Effort is set in the first system message:**

  | Effort | System instruction |
  | --- | --- |
  | `xhigh` (the default, which `high` maps to) | about 38-token xhigh instruction |
  | `low` | low instruction |
  | `medium` | no instruction |
  | `none` or `enable_thinking: false` | no instruction, plus a closed empty think block in the generation prompt |

  Because effort lives at the start of the prompt, **changing effort invalidates the whole prefix cache**. Upstream has an opt-in `effort_position: "end"` setting [docs].
- **Tool definitions are rendered as bare `{"name","description","parameters"}` objects, not the OpenAI-wrapped form,** on both dialects.
  - OpenAI string `arguments` are parsed to objects before rendering. The template itself raises an error on non-empty string arguments.
  - Consecutive `tool` messages are merged into one `user` turn of `<tool_response>` blocks.

Golden renders are in `fixtures/render_*.txt`.

## 3. Endpoints [verified]

| Route | Status |
| --- | --- |
| `POST /v1/chat/completions` | works, streaming and non-streaming, with tools |
| `POST /v1/messages` | works, streaming and non-streaming, with tools, thinking blocks and parallel `tool_use` |
| `POST /v1/messages/count_tokens` | works (see §4) |
| `POST /v1/responses` | works, stateless; `/v1/responses/input_tokens` returns 404 "keeps no responses" |
| `/v1/completions`, `/completion`, `/v1/embeddings`, `/infill` | 404 |
| `/tokenize`, `/detokenize`, `/apply-template`, `/v1/tokenize` | 404 |

Other observed behavior:

- **`model` is ignored.** An unknown model returns 200.
- **`/v1/messages` does not require `max_tokens`.** A request without it returns 200.

## 4. Token counting [verified]

There is no tokenize or apply-template endpoint.

**`POST /v1/messages/count_tokens` returns `{"input_tokens": N}`, the exact rendered prompt including the generation prompt.**

- It equals the prompt token count of the same request on `/v1/messages`, where that count is `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`. It also equals `usage.prompt_tokens` on the OpenAI path.
- It takes 15–80 ms, does not queue behind generation, and works while the engine is busy.
- It applies no context check: a 70,515-token request returns 200.
- It accepts only Anthropic-shaped requests. OpenAI-wrapped tools return 400 `tools[0] has no name`.
- It honors `system`, `tools`, `thinking` and `output_config.effort`. It ignores a top-level `reasoning_effort`.

**Exact local counting works.** Rendering the pinned template with jinja2 (HF-style `tojson`, `ensure_ascii=False`, no key sorting) and tokenizing with `Qwen/Qwen3.8-Flash-Next` `tokenizer.json` matched the server in **19 of 19** cases:

- 10 `count_tokens` cases, including tools, a tool turn with reasoning, effort levels and system;
- 9 `usage.prompt_tokens` cases, including tool calls with string arguments and prior reasoning.

The one requirement is that tools are passed in the bare form. Scripts: `p04_count_tokens.py` and `p02_template_render.py`. Fixtures: `count_tokens.json`, `template_render_check*.json`.

**Strata normalizes messages before rendering** (`serve/frontend.py`; found by the Phase 3 development runs, R21; probe `p12_strata_normalization.py`, fixture `strata_normalization.json`, 2026-10-25). The 19 cases above did not exercise either rule.
- **Empty assistant turns are dropped** (`ChatTemplate.render`, #843). A completed assistant turn with no text (null, "", whitespace, or text parts that join to nothing), no image and no tool calls is left out, reasoning included. The final message is always kept. `STRATA_KEEP_EMPTY_TURNS=1` restores the old rendering. All four empty forms counted 311, the same as removing the turn; with content "ok" the count was 344.
- **Tool-call arguments** (`tool_arguments`, #510). A JSON object, whether text or parsed, is used as it is; empty is `{}`; anything else (cut-off JSON, a list, a number) is kept as text under `"arguments"` instead of refusing the request.
- **Added-token strings inside messages are text** (the 0.1.49 frontend's `mark_think_literals` and `encode_prompt`; the engine reports build 0.1.48; #537, #554, #2026; found by the S11 smoke runs, R23-A; probe `p14_literal_tags.py`, fixture `strata_literal_tags.json`, 171 cases, 2026-10-25).
  - **What is marked:** every value of every message field except `role`, and the tool definitions. Dict keys are not marked, so `<|im_start|>` in a parameter name or argument key is a token. Tool-call arguments are parsed first (`openai_to_messages`); marking runs on the full list before the #843 drop, so a tag only in a dropped turn still turns private-use mark characters elsewhere into tag text.
  - **Which strings:** all 33 added tokens of the pinned tokenizer, the 19 `special` ones and the 14 others, `<|fim_*|>` included. The live counts match marking all of them.
  - **How:** each string is swapped for a private-use mark before rendering. After rendering the marks become the text again, and the encoder treats those spans as plain text, tokenized with the text around them.
  - **Exceptions:**
    - An assistant message keeps its own `<tool_call>`, `</tool_call>`, `<tool_response>` and `</tool_response>` as tokens, in content, reasoning and arguments alike.
    - An assistant content that opens with a whole `<think>...</think>` block keeps that block's two markers.
    - A user message whose whole text is `<tool_response>...</tool_response>` keeps that outer pair.
- **No Unicode normalization** (`tools/strata_tokenizer.py` has no normalizer; probe `p15_nfc_count.py`, fixture `strata_nfc.json`, 2026-10-25). The pinned `tokenizer.json` declares NFC, but Strata encodes text as sent: `cafe\u0301 au lait` counts 57 against NFC's 56, and decomposed Hangul 62 against 54.
  - **Example:** as a tool result, `x</tool_call>y` counts 330 where reading it as one token gives 328, and `x<|im_end|>y` counts 333 against 328.

## 5. Non-streaming responses [verified]

Fixtures are `fixtures/nonstream_*.json`; each holds the request, headers, body and wall time. Script: `p05_nonstream.py`.

**OpenAI path:**

- `choices[0].message` has `content` and, as a separate field, `reasoning_content`.
- `finish_reason` is one of `stop`, `length` or `tool_calls`. When the length cap is hit during thinking, `content` is `null`.
- `tool_calls[].function.arguments` is a compact JSON string, and ids look like `call_<hex>`.
- `usage` has `{prompt_tokens, completion_tokens, total_tokens, prompt_tokens_details.cached_tokens}`. `completion_tokens` includes reasoning; there is no `reasoning_tokens` field.
- There is an extra `timings` object, in llama.cpp style: `cache_n`, `prompt_n`, `prompt_ms`, `predicted_n`, `predicted_ms`, `draft_n`, `draft_n_accepted`. `cache_n` equals `cached_tokens`.

**`/v1/messages`:**

- `content` holds `thinking` blocks (with `"signature": ""`), then `text` and `tool_use` blocks.
- `stop_reason` is `end_turn` or `tool_use`.
- `usage` is `{input_tokens: 1, output_tokens, cache_creation_input_tokens, cache_read_input_tokens}`.
  - **`input_tokens` is always 1 in final usage.** The total prompt is the sum of the three input fields.
  - In streaming, `message_start` instead reports the full prompt as `input_tokens` (see §6).

**`/v1/responses`:**

- Output contains a `reasoning` item with `reasoning_text` content and an empty `summary`.
- `usage` has `input_tokens_details.cached_tokens` and `output_tokens_details.reasoning_tokens`.

## 6. Streaming [verified]

Raw bytes are in `fixtures/sse_<case>.sse`; arrival times and an event summary are in `.meta.json`. Script: `p06_stream.py`.

**Common framing:**

- Responses are `text/event-stream`, HTTP/1.0 with `Connection: close`; the stream ends when the socket closes.
- JSON is raw UTF-8 with `ensure_ascii` off, so decode only at event boundaries.
- Deltas carry about one token each.
- **Keep-alives are SSE comments, `: keep-alive\n\n`.**
  - One is sent right after the first chunk.
  - During a long prefill, more arrive about every 10 s, plus one at each completed 8192-token prefill chunk. Observed arrivals: 10.2, 15.7, 25.7, 31.0, 41.0, 43.6, 44.1 s.
  - The same 10 s cadence applies while a request waits in the queue.
  - The `/v1/messages` stream sends no `ping` events; it uses these comments.

**OpenAI stream sequence:**

1. A role chunk, `{"role":"assistant","content":""}`, sent as soon as the request is accepted (before prefill, even when queued).
2. `reasoning_content` deltas.
3. `content` deltas.
4. A final chunk with an empty delta, `finish_reason`, **`usage` and `timings`**.
5. `data: [DONE]`.

More on the OpenAI stream:

- **Usage is always attached to the finish chunk, whether or not `stream_options.include_usage` is set.** The server never sends the OpenAI-spec usage chunk with `choices: []`.
- **Tool calls:**
  - The first delta carries `index`, `id`, `type`, `name` and `arguments: ""`.
  - Argument fragments then arrive token-sized: `{`, `"city":`, `"`, `Paris`, `"`, `}`.
  - Parallel calls use `index` 0 and 1, in sequence.
  - The stream ends with `finish_reason: "tool_calls"`.

**`/v1/messages` stream sequence:**

1. `message_start`, with `usage.input_tokens` = the full prompt.
2. Comment keep-alive.
3. Per block: `content_block_start` (`thinking` with `signature:""`, `text`, or `tool_use` with `input: {}`), then `thinking_delta` / `text_delta` / `input_json_delta` events, then `content_block_stop`.
4. `message_delta`, with `stop_reason` and `usage: {input_tokens: 1, cache_creation_input_tokens, cache_read_input_tokens, output_tokens}`.
5. `message_stop`.

There is no `signature_delta`.

**`/v1/responses` stream:** it uses the standard event order, with `response.reasoning_text.delta` for reasoning (fixture `sse_rs_reasoning.sse`).

**Errors in streams:**

- Errors raised before acceptance, such as overflow, return a plain 400 JSON body, not SSE.
- When the server process died mid-stream, the stream just closed with no error event.

## 7. Cache reuse [verified]

Script: `p07_cache.py` (with `--multiturn` for the second scenario). Fixtures: `cache_reuse.json`, `cache_multiturn_edit.json`.

| Step | Prompt tokens | Cached | Prefill time |
| --- | --- | --- | --- |
| 3,143-token prompt, first | 3143 | 0 | 12.3 s (cold) |
| Same prompt again | 3143 | 3136 | 0.22 s |
| Extended by one assistant and one user turn | 3165 | 3136 | 0.61 s |
| Same extended prompt via `/v1/messages` | 3165 | `cache_read` 3158 | — |

**Reuse depends on checkpoints, not on the full longest common prefix.**

- The engine has a recurrent state, so it can only resume from saved checkpoints.
- Checkpoints are taken at the start of each new assistant turn and every 16K prompt tokens. A system-prompt root is kept when the system prompt is 2048 tokens or more. Up to 6 checkpoints are kept, rotating by least recent use [docs, consistent with measurements].
- The generation prompt is always re-read: about 7 tokens with reasoning off, 5 with it on.

**Multi-turn edit test:** a conversation grown to 4 turns of about 800 tokens each.

| Step | Tokens re-read |
| --- | --- |
| Appending a turn | 12 |
| Masking turn 2's user message | 1,620 (resumed at 1,043, the checkpoint before the edit) |
| Masking turn 4 | 51 (resumed at 2,656) |
| Returning to the unedited history | 7 |

Since the restart, parked conversations (the conversation cache) also survive interleaving with other clients. Before the restart, with the cache off, the single slot was simply overwritten by whichever request ran last.

**Metric sources:**

| Path | Field |
| --- | --- |
| OpenAI | `usage.prompt_tokens_details.cached_tokens` (equals `timings.cache_n`) |
| `/v1/messages` | `usage.cache_read_input_tokens` |
| `/v1/responses` | `usage.input_tokens_details.cached_tokens` |
| Server-side | `/metrics` `requests[].reused` and `prompt_read`; Prometheus `vllm:prefix_cache_hits_total` |

## 8. Error shapes [verified]

Fixture: `errors.json`. Script: `p08_errors.py`.

Chat and messages errors use `{"error":{"type":"invalid_request_error","message":...}}`, **not Anthropic's `{"type":"error","error":{...}}` envelope**. Responses errors add `param` and `code`.

| Case | Status | Body / note |
| --- | --- | --- |
| Malformed JSON (all dialects) | 400 | `Expecting value: line 1 column 39 (char 38)` |
| JSON that is not an object | 400 | `send a JSON object` |
| Empty `{}` | 400 | `No messages provided.` (Responses: `code: missing_required_parameter`) |
| Unknown role | 400 | `Unexpected message role.` |
| Prompt ≥ context (70,475 tokens with ctx 65536), chat or messages, stream or not | 400 | `request exceeds the context window: prompt (70475 tokens) leaves no room to answer in the context (65536); requests are never truncated` — returned in 0.1–0.2 s, before queueing |
| Same, Responses | 400 | same message, `param: "input"`, `code: "context_length_exceeded"` |
| `max_tokens` 1,000,000 with a small prompt | 200 | silently clamped |
| prompt + `max_tokens` > ctx (19,865 + 50,536 > 65,536), with or without `"fit_max_tokens": false` | 200 | **clamped; `fit_max_tokens:false` is not honored in 0.1.48**, although the upstream docs say it returns 400 |
| Negative `max_tokens` | 200 | treated as no cap |
| Unknown model | 200 | `model` ignored |
| Unknown route | 404 | `{"error":{"message":"not found"}}` |
| Engine died | 503 | `{"error":{"type":"server_error","message":"the engine stopped unexpectedly (exit code -15); the next request restarts it"}}` |

## 9. Cancellation to slot release [verified]

Script: `p09_cancel.py`. Fixtures: `cancel_trials.jsonl` and `cancel_*.raw`.

Method:

- Requests go over raw sockets.
- After the server shows the request as active plus N ms, the socket is closed.
- Release is the time until `/status` stops showing that request, polled every 25 ms.
- A tiny follow-up request is sent after release. Its TTFB after release (0.11–0.33 s) matches the idle baseline (0.23–0.28 s warm), which confirms the engine was actually free.
- Server records show `finish: "cancel"` or `"disconnect"`.

| Mode | Cancel after | Release (s) | Server record |
| --- | --- | --- | --- |
| Prefill, stream (about 20K tokens) | 1 s | 14.95 | `prompt_read` 8192, 16.0 s |
| | 3 s | 13.16 | `prompt_read` 8192, 16.3 s |
| | 10 s | 5.94 | `prompt_read` 8192, 16.0 s |
| | 25 s | 7.09 | finished the second chunk |
| Prefill, non-stream | 5 s | 10.64, 10.81 | `prompt_read` 8192, 16.0–16.2 s |
| Decode, stream | 2 s | 0.079, 0.047, 0.062 | `cancel` / `disconnect` |
| Decode, non-stream | 2 s | 0.50, 0.23 | `cancel` |

**Cancellation is honored only at an 8192-token prefill-chunk boundary** (`prefill_cap`). Release takes the remaining time of the current chunk: up to about 16 s at about 512 tok/s, and up to about 60 s at the cold rate of about 137 tok/s [extrapolated, unverified].

During decode, release takes under 0.1 s for streaming. For non-streaming the disconnect is still detected without any write, and release takes under 0.5 s.

I did not test cancellation during an internal continuation; that requires the Palimnesis loop.

## 10. Concurrency on one slot [verified]

Script: `p10_concurrency.py`. Fixture: `concurrency.json`.

- **Requests are queued FIFO, never rejected.** I saw no 429 or 503 for queueing.
- **A queued streaming request immediately gets `200` plus the role chunk, then keep-alives every 10 s until it runs.** A client cannot tell queueing from prefill except through `/status` (`queued`).
- In my run, B was sent 0.3 s after A and started after A and two other clients' requests: `first_engine_token_s` was 39 s.
- **A queued request whose client disconnects is dropped and never executed.** It does not appear in `/metrics` request records. The `/status` `queued` count did not drop within 0.5 s, so removal appears to be lazy.

## 11. Parameters [verified unless marked]

| Parameter | Result |
| --- | --- |
| `max_tokens`, `max_completion_tokens` | honored; the cap includes reasoning tokens; `finish_reason: "length"` |
| `max_tokens` ≥ 1024 with thinking on | thinking is wrapped up with 25% of the cap left [docs] |
| `reasoning_effort` `none` / `low` / `medium` / `high` (OpenAI); `output_config.effort` and `thinking.type: disabled` (Anthropic); `reasoning.effort` (Responses) | honored; prompt token counts change as in §2 |
| `chat_template_kwargs.enable_thinking: false` | honored, same as `none` |
| `chat_template_kwargs.preserve_thinking` | **ignored** |
| `reasoning_format: "none"` | accepted, no effect; reasoning stays separated |
| `stream_options.include_usage` | no effect; usage is always in the final chunk |
| `fit_max_tokens: false` | **not honored** |
| `return_progress: true` | outcome unknown; the server died during the only attempt (see §0) |
| `reasoning_budget_tokens`, `strata_checkpoint` | not tested [docs] |

I also saw one unexplained result before the restart: `max_tokens: 8` produced `completion_tokens: 4`. After the restart it produced 8.

## Implications for Palimnesis

- **Counting strategy.**
  - Count locally with the pinned template (`fixtures/strata_chat_template.jinja`) and the `Qwen/Qwen3.8-Flash-Next` tokenizer, passing tools in the bare form. This matched exactly in 19 of 19 cases.
  - Cross-check with `POST /v1/messages/count_tokens`, which is exact, fast and does not queue. It needs Anthropic-shaped input, so OpenAI requests must be converted first.
  - Reconcile against `usage` after each call.
  - At startup, hash `/props.chat_template` and `build_info`. On drift, refuse rewriting or fall back to the endpoint.
  - Effort level and `enable_thinking` change the count and the first system message, so they are part of the render key.
- **Safe input budget.**
  - The server refuses prompts at or above `n_ctx`, but silently clamps `max_tokens`. Palimnesis must enforce `input + reserved_output + margin ≤ n_ctx` itself.
  - At 32K capacity, the recommendation is: input budget = 32768 − R − M. R is the generation reserve, which must cover reasoning because the cap includes thinking; for example 8192. M is a margin of 256, which can be small because counting is exact. That gives a 24,320-token input budget.
  - The server currently runs at 65,536. Read `/props` `n_ctx` per process and revalidate it after any upstream error or reconnect.
- **Cancellation release threshold.**
  - Treat the slot as released only when `/status` reports `busy: false` (or another request active) and our request has a `cancel` or `disconnect` record. Poll every 50–100 ms.
  - Set the expected release time to under 1 s during decode and up to one prefill chunk during prefill: 8192 divided by the observed prefill rate, which is about 16 s warm.
  - Use a hard ceiling of 60 s. Past that, mark the upstream unhealthy and do not dispatch.
  - Avoid scheduling cancellable work mid-prefill when possible.
- **Cache metric source.**
  - Per call, use `usage.prompt_tokens_details.cached_tokens` (OpenAI) or `cache_read_input_tokens` (Anthropic). On the server side, `/metrics` `requests[].reused` and `prompt_read` are available.
  - Expected reuse is the last checkpoint at or before the first changed token, not the token LCP. An edit at a watermark re-reads from the nearest checkpoint, which is often a whole recent turn, and a deep edit falls back to the system root or zero.
  - Because effort changes rewrite the system preamble, they invalidate everything. Record "checkpoint-limited" as an explicit invalidation cause next to LCP.
- **Client endpoints Palimnesis can serve.**
  - OpenAI Chat Completions.
  - Anthropic Messages, plus `count_tokens`. Palimnesis must translate the error envelope to Anthropic's `{"type":"error",...}`. In final usage `input_tokens` is 1, so recompute it as the sum of the three input fields.
  - OpenAI Responses, stateless only.
  - Not servable: legacy `/v1/completions`, embeddings and tokenize.
  - **Reasoning carryover:** the installed template keeps all earlier reasoning. Palimnesis must reinsert archived `reasoning_content` for every earlier assistant turn, not only for current-turn tool steps, to match what the model saw and keep cache prefixes stable.
- **Liveness, queueing and recovery.**
  - The server sends a keep-alive comment at least every about 10 s, both while queued and during prefill.
  - Upstream queueing is invisible to clients, so Palimnesis's own single-dispatch FIFO should be the only queue, with `/status` used as a guard because other clients share the server.
  - A server death mid-stream closes the socket with no terminal event. Treat EOF without `[DONE]` or `message_stop` as an upstream failure.
