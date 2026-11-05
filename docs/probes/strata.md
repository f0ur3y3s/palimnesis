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

I did not test cancellation during an internal continuation; that requires the Palimnesis loop. A simulated continuation (call 2 after a tool call, no proxy) released in 0.062–0.093 s during decode (§12.4).

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
| both `max_completion_tokens` and `max_tokens` | `max_completion_tokens` wins: 8 against 300 gave 8 tokens, 300 against 8 gave 300 (p16, Zeus, 2026-10-26) |
| `tool_choice: "none"` | the tool schemas are **not rendered**: the probe prompt counted 69 tokens, the same as with no `tools`, against 317 for `"auto"` or no `tool_choice` (p16, Zeus, 2026-10-26) |
| `max_tokens` ≥ 1024 with thinking on | thinking is wrapped up when cap − max(512, cap/4) is reached; below 1024 there is no wrap-up (§12.2, Zeus, 2026-10-26; the docs' "25% of the cap" holds only from 2048) |
| `reasoning_effort` `none` / `low` / `medium` / `high` (OpenAI); `output_config.effort` and `thinking.type: disabled` (Anthropic); `reasoning.effort` (Responses) | honored; prompt token counts change as in §2 |
| `chat_template_kwargs.enable_thinking: false` | honored, same as `none` |
| `chat_template_kwargs.preserve_thinking` | **ignored** |
| `reasoning_format: "none"` | accepted, no effect; reasoning stays separated |
| `stream_options.include_usage` | no effect; usage is always in the final chunk |
| `fit_max_tokens: false` | **not honored** |
| `return_progress: true` | outcome unknown; the server died during the only attempt (see §0) |
| `reasoning_budget_tokens`, `strata_checkpoint` | not tested [docs] |

I also saw one unexplained result before the restart: `max_tokens: 8` produced `completion_tokens: 4`. After the restart it produced 8.

## 12. Tool streams, small limits and continuations (Phase 3B) [verified on Zeus, 2026-10-26]

Probed 2026-10-26 between 15:38 and 15:52 UTC against `http://192.168.1.19:8080` (Zeus): `build_info` `Strata 0.1.48`, one slot, `n_ctx` 65536. Every request ran alone, gated on `/status` showing neither busy nor queued, and every body is synthetic. Slot time was about 6 minutes in total. Scripts: `p17_tool_stream_shapes.py` to `p20_cancel_continuation.py`. Fixtures: `p17_*` to `p20_*` in `eval/probes/fixtures/`, each probe with one results JSON and its raw `.sse` streams. Run them with `uv run python eval/probes/<script>.py`.

### 12.1 Tool-call streams (P1, `p17_tool_stream_shapes.py`)

15 cases, 3 runs each: 45 OpenAI Chat streams carrying 58 tool calls. Thinking was off (`reasoning_effort: "none"`) or on (`"low"`). Fixtures: `p17_tool_stream_shapes.json` and `p17_<case>_<rep>.sse`.

- **The first delta of a call carries `index`, `id` (`call_<hex>`), `type: "function"`, `function.name` and `arguments: ""`.** This held for all 58 calls. The arguments follow in later deltas, token-sized: `{`, `"city":`, `"`, `Paris`, `"`, `}`.
- **Arguments stream as they are generated.** They are not buffered: one argument string of about 300 deltas arrived over 3.4–4.0 s.
- **Parallel calls take indices 0, 1, 2 in order.** Each call's deltas are contiguous. No index reappeared after the next one started (0 of 45 streams).
- **Text after a call: yes, with thinking on.**
  - Asked to write a sentence after the call (`after_a_on`), 3 of 3 streams were reasoning, call 0, 8 content deltas, then `finish_reason: "tool_calls"`.
  - Asked for call, text, call (`between_on`), 2 of 3 streams were reasoning, call 0, content (`and now Oslo:`), then call 1. The third made one call only.
  - With thinking off, the same prompts never gave text after a call (0 of 6). The model stopped after the call or wrote the text before it.
  - Text asked for before a call (`sandwich_*`) came before it in 6 of 6. The text asked for after that call never appeared.
  - Reasoning after a call was never seen (0 of 45). That it cannot happen is **[unverified]**.
  - Every case of text after a call was explicitly requested. How often it happens unprompted in agent work is **[unverified]**.
- **`length` inside the arguments.**
  - Thinking off, `max_tokens` 40, 3 of 3: `finish_reason: "length"`, `completion_tokens` 40, and the arguments are an unterminated JSON prefix, for example `{"path":"poem.txt","content":"A river wakes in mountain snow,\na silver thread through`. They do not parse as JSON.
  - Thinking on, `max_tokens` 160: 2 of 3 stopped inside the arguments in the same way. The third spent all 160 tokens on reasoning, with no call and no content; caps below 1024 get no thinking budget (§12.2).
  - Nothing marks the cut: the call's last delta is an ordinary token, followed by the finish chunk with `usage`.
- **Keep-alive comments.** Each stream had 1 or 2 `: keep-alive` comments between the role chunk and the first delta (2 when the prompt was not cached), and none between deltas in any of the 45 streams. The only comment seen between deltas is at the forced thinking wrap-up (§12.2).
- After a tool-call response, `/status` `phase` reads `tool call complete`.

### 12.2 Thinking under a small output limit (P2, `p18_small_limit_thinking.py`)

Each run used the default effort (xhigh), thinking on, and a counting problem that needs long reasoning. There were 3 runs per cap. `/status` was polled every 0.25 s during each request. Fixtures: `p18_small_limit_thinking.json` (every run) and `p18_<cap>_0.sse` (the first run per cap; the others were dropped for size).

| `max_tokens` | `/status` `thinking_budget` | Reasoning deltas | Content deltas | `completion_tokens` | `finish_reason` |
| --- | --- | --- | --- | --- | --- |
| 512 | none | 512 | 0 | 512 | `length` ×3 |
| 1024 | 512 | 528 | 10–17 | 541–548 | `stop` ×3 |
| 2048 | 1536 | 1551–1552 | 4–14 | 1559–1569 | `stop` ×3 |
| 4096 | 3072 | 3077–3088 | 13–15 | 3104–3106 | `stop` ×3 |

- **The rule: for caps of 1024 and up, the thinking budget is cap − max(512, cap/4). Below 1024 there is no budget.**
  - Extra caps were read from `/status` with requests cut off after 20 reasoning deltas: 1500 gave 988, 2047 gave 1535, 3000 gave 2250, 5000 gave 3750 and 8192 gave 6144. There was no budget at 600, 700 or 1023.
  - The "25% of the cap" in the upstream docs therefore holds only from 2048 up. Between 1024 and 2047 the answer keeps 512 tokens.
  - Palimnesis's per-call reserve R = 8192 gets a thinking budget of 6144.
- **How the wrap-up works.**
  - At the budget, Strata injects `\n\nI have thought about this long enough; time to give my answer.\n` into the reasoning, then closes thinking.
  - The injected sentence streams as 16 ordinary `reasoning_content` deltas. A client therefore archives and resends it as model reasoning.
  - Reasoning ended 5–16 deltas past the budget.
- **The forced answers were short.** Content used 4–17 tokens, at most 3.3% of the room kept for it.
- **Below 1024 the cap ends the response mid-reasoning.** All three 512 runs reasoned for all 512 tokens and ended with `finish_reason: "length"` and empty `content`.
- **A keep-alive comment comes between the last reasoning delta and the first content delta** in all 9 wrap-up runs.
- `reasoning_recoveries` stayed 0.

### 12.3 Cache reuse for a continuation (P3, `p19_continuation_cache.py`)

The probe simulates one hidden continuation without the proxy:

1. **Call 1** is streamed with thinking on (`low`) and answers with a `read_file` tool call.
2. **Call 2** sends call 1's messages, plus `{"role": "assistant", "content": "", "reasoning_content": <streamed reasoning>, "tool_calls": [<the call as streamed>]}`, plus a tool result.

The tool result was about 20 tokens (short) or 2,009 tokens (long). A thinking-off pair was the control. A fresh nonce in each user message kept call 1 cold past the shared head. Expected reuse comes from `StrataCacheModel.expected(layout1, layout2)`, with the layouts built by `tokens.default()`. Fixtures: `p19_continuation_cache.json` and `p19_<variant>_<rep>_call{1,2}.sse`.

| Variant | prompt1 + completion1 | Model expected | Call 2 `cached_tokens` | δ = cached − (prompt1 + completion1) |
| --- | --- | --- | --- | --- |
| short, on | 338+54, 340+55, 336+65 | 333, 335, 331 | 391, 397, 401 | −1, +2, 0 |
| long, on | 340+61, 338+54, 340+61 | 335, 333, 335 | 403, 391, 400 | +2, −1, −1 |
| short, off | 312+34, 314+35 | 305, 307 | 346, 348 | 0, −1 |

- **Strata reuses the tokens it generated in call 1, not only the generation-start checkpoint.** Call 2's `cached_tokens` was prompt1 + completion1 + δ, with δ between −1 and +2, in 8 of 8 pairs. An earlier run of the same script with a 3,330-token result also gave δ between −1 and +2 over 8 pairs; its fixtures were overwritten by the rerun.
- **`StrataCacheModel.expected` under-predicts.** It returns call 1's generation start (prompt1 − 5 with thinking on, − 7 off). Measured reuse exceeded it by 58–70 tokens with thinking on and by 41 off, which is the whole generated turn.
- **`/metrics` agrees.** `reused` equals `cached_tokens`. Call 2 read 29–34 tokens with the short result, and 2,022–2,025 tokens in 1.7–1.8 s with the long one.
- **The local render matched exactly.** prompt1 and prompt2 matched `usage.prompt_tokens` in 8 of 8 pairs. The generated turn re-rendered as completion1 + 1 tokens: the extra token is the `\n` after `<|im_end|>`. That the re-rendered tokens are also identical in content is inferred from the reuse.
- **Why δ can be +1 or +2** (reuse 1–2 tokens past what was generated) is **[unverified]**.
- **Untested** (each **[unverified]**):
  - another request between call 1 and call 2 (here they were about 1 s apart on an idle server);
  - any change to the resent reasoning or arguments text;
  - text after the call;
  - a call 1 that ends in `length`.

### 12.4 Cancel during a continuation (P4, `p20_cancel_continuation.py`)

The probe runs P3's call 1 with the task "do exactly what the file asks", then call 2 streaming with a tool result that asks for a 1,500-word story and `max_tokens` 3000. The client disconnects 1 s after call 2's first reasoning or content delta. Release is measured as in §9. Fixtures: `p20_cancel_continuation.json` and `p20_cancel_<rep>_call2.sse`.

- **Release took 0.078, 0.093 and 0.062 s**, 3 of 3 with server records `finish: "disconnect"`. Each took two `/status` polls, so the resolution is about 30 ms.
- **A tiny follow-up request then had a TTFB of 0.141–0.156 s.**
- **This matches §9's decode-time stream cancel** (0.047–0.079 s): a continuation's decode cancels like any other.
- The cancels landed about 1 s into decode, after 79–87 deltas. Call 2 reused 393–401 tokens and read 44–47, consistent with §12.3.
- **Cancel during a continuation's prefill was not measured.** A 2,000-token result prefills in 1.7–1.8 s (§12.3), within one 8192-token chunk. By §9, a cancel then would release when that prefill ends **[inferred, unverified]**.

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

## 13. Anthropic Messages on 0.1.54 (Phase 4B, M1–M5)

Probed 2026-11-05 between 13:35 and 13:52 UTC against `http://127.0.0.1:8080` on pythia (D76): `build_info` `Strata 0.1.54`, one slot, `n_ctx` 32768. Every request ran alone, gated on `/status` showing neither busy nor queued (D39), and every body is synthetic. Strata was not restarted or reconfigured. Scripts: `p21_messages_stream.py` to `p25_messages_beta_headers.py`; run them on pythia with `uv run python eval/probes/<script>.py`. Fixtures are in `eval/probes/fixtures/strata_messages/`. The 0.1.54 frontend source on pythia (`serve/frontend.py`, `serve/server.py`) was read to design the cases; a fact below is **[verified]** only when a capture shows it, and **[source]** marks what only the source says.

### 13.1 Stream shapes (M1, `p21_messages_stream.py`) [verified]

13 streamed cases and 2 non-streamed twins, one run each. Fixtures: `p21_messages_stream.json` and `p21_<case>_0.sse`.

- **Framing.** Every frame is `event: <name>\ndata: <json>\n\n`, and the event name always equals `data.type` (0 mismatches). Headers are the same as §1: `text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `Connection: close`.
- **Event order:** `message_start`, keep-alive comments, then per block `content_block_start`, its deltas and `content_block_stop`, then `message_delta` and `message_stop`. Blocks are never interleaved; indices count up from 0. Every stream, including all three length stops, ended with `message_stop`.
- **`message_start` is sent on acceptance, before prefill.** It arrived at 0.009–0.022 s in every case, including the 19,932-token prefill whose first block came at 29 s.
- **Usage.**
  - `message_start` `usage` is `{input_tokens: <whole prompt>, output_tokens: 0}`, with no cache fields.
  - `message_delta` `usage` is `{input_tokens: 1, cache_creation_input_tokens, cache_read_input_tokens, output_tokens}`. The three input fields sum to the whole prompt in every run (for example `tool_off`: 1 + 344 + 0 = 345; `length_thinking`: 1 + 4 + 55 = 60). **The `input_tokens: 1` of §5 still holds on 0.1.54.** The frontend keeps one token there because 0 made Claude Code count the prompt twice [source, #1013].
  - `/v1/messages` responses carry no `timings` object (p24 extension calls).
- **Blocks.**
  - `thinking`: `content_block_start` carries `{"type":"thinking","thinking":"","signature":""}`, deltas are `thinking_delta`, and there is no `signature_delta`.
  - `text`: `{"type":"text","text":""}`, then `text_delta`.
  - `tool_use`: `{"type":"tool_use","id":"call_<24 hex>","name":...,"input":{}}`, then `input_json_delta`. **The id is `call_` plus 24 hex digits, not Anthropic's `toolu_` form.** Message ids are `msg_` plus 24 hex digits.
  - Seen: thinking then text, thinking then tool_use, two parallel tool_use blocks, and text then two tool_use blocks (`parallel_off`).
- **`input_json_delta` is token-sized, as on Chat (§12.1):** `{`, `"city":`, `"`, `Paris`, `"`, `}` (6 pieces; Oslo took 7: `Os`, `lo`). One emoji argument arrived as the JSON escape text `👋` inside `partial_json` (`forced_tool_any`); the joined JSON still parses.
- **Stop reasons.** `end_turn`, `tool_use`, `stop_sequence` (with `stop_sequence: "7,"` in `message_delta`), and **`max_tokens` on a length stop**:
  - in text (`length_text`, cap 12);
  - in thinking (`length_thinking`, cap 24): the thinking block is closed with `content_block_stop`, and no text block follows;
  - inside tool arguments (`length_tool_args`, cap 40): the `tool_use` block is closed with `content_block_stop` after 20–21 pieces whose concatenation does not parse (`{"path":"poem.txt","content":"The River's Long Memory\n\nA river is a sentence written`). Nothing marks the cut.
  - **Non-streaming drops that cut-off call**: `content: []`, `stop_reason: "max_tokens"` (`length_tool_args_nonstream`).
- **Forced `tool_choice`.** `{"type":"tool","name":...}` and `{"type":"any"}` each produced a `tool_use` block even for "Say hello.", with `stop_reason: "tool_use"`.
  - For the named form, `content_block_start` and the first `{` delta came at 0.014 s, before the keep-alives and the prefill: the server writes the call's opening itself [source: `forced_call`].
  - `{"type":"none"}` gave a text answer to a weather question with tools present.
- **Keep-alives are SSE comments, `: keep-alive\n\n`. No `ping` event was sent in any of the 13 streams.**
  - Short prompts: 1 or 2 comments between `message_start` and the first block, none between deltas.
  - The 19,932-token cold prefill (`long_prefill`): 6 comments, at 10.1, 10.5, 20.5, 21.1, 28.9 and 29.3 s. That is the 10 s cadence plus one per prefill chunk, as in §6.
  - For the forced named call, the 2 comments came after the first `input_json_delta`, inside the open block.
- **EOF on engine death: not probed [unverified].** Observing it needs stopping the engine, and restarting Strata needs the user's approval.
  - When the engine dies mid-stream, the 0.1.54 source writes `event: error` with `{"type":"error","error":{"type":"api_error","message":"...; the next request restarts it"}}` [source].
  - For an expired queue wait it writes `rate_limit_error` with `code: queue_wait_timeout` [source].
  - On 0.1.48 a dying server process closed the stream with no event (§0, §6).

### 13.2 Rendering parity (M2, `p22_messages_render_parity.py`; `p24_cross_dialect_cache.py` part A) [verified]

Each case was measured four ways:
- **ct:** `count_tokens` on the Messages body;
- **mr:** the prompt of `/v1/messages` with `max_tokens: 1`, the sum of the three input fields;
- **local:** the repo counter's count of the neutral Chat body;
- **cr:** `usage.prompt_tokens` of that Chat body on `/v1/chat/completions`.

The neutral mapping is `neutral()` in `p22`, written from core position 3 of the Phase 4B plan; the script docstring lists its choices. Fixture: `p22_messages_render_parity.json` (57 cases, with bodies, counts and errors).

Counts cannot see order, so part A of `p24` also tests token identity:
1. A fresh nonce and about 300 tokens of filler open the first user message.
2. The Messages body is sent, then its neutral Chat body.
3. The Chat call reuses the first prompt up to its generation start (prompt − 5 here) only if both routes produced the same tokens. Otherwise reuse is 0.

Fixture: `p24_cross_dialect_cache.json` (`identity`, 20 cases).

**Cases where the neutral Chat body is token-identical to the Messages route** (ct = mr = local = cr, and a cache hit):

| Case | ct | Identity (cached / prompt) |
| --- | --- | --- |
| `base` (system string + user) | 59 | 390 / 395 |
| multi-block `system`, joined with `""` | 63 (= the joined string; `\n` would be 64) | 395 / 400 |
| several text blocks in one user message, joined with `""` | 62 (= the joined string; `\n` 64) | 394 / 399 |
| several text blocks in one assistant message, joined with `""` | 84 (`\n` 86) | 417 / 422 |
| `tool_result` with a text-block array, joined with `""` | 367 (= the string form; `\n` 368) | 701 / 706 |
| `tool_result` with `is_error: true` | 367 (= without it) | 701 / 706 |
| `tool_result` then text in one user message | 375 | 709 / 714 |
| text then `tool_result` in one user message | 375 | 708 / 713; the text-first Chat order gets 0 |
| `cache_control` on system, tools, text, `tool_use` and `tool_result` | 351 (= without it) | 683 / 688 |
| `thinking` with a signature, with `""`, or with none | 84 each | 416 / 421 |
| `redacted_thinking` | 77 (= no thinking block) | 410 / 415 |
| `document` block | 59 (= without it) | 391 / 396 |
| `role: system` as the first message, no top-level `system` | 59 (= top-level `system`) | 391 / 396 |
| mid-conversation `role: system` (string or blocks) | 91 (= the same text as a `user` message) | 425 / 430; the local counter errors (below) |
| `output_config.effort: "max"` | 59 (= `high` = `xhigh` = default) | 392 / 397; the local counter errors (below) |
| `tool_choice: {"type":"none"}` | mr 59 (tools not rendered); **ct 305** | 392 / 397 |

- **The Messages route always puts a user message's `tool_result`s first, then its text, whatever the block order.** This matches core position 3.
- **A mid-conversation `system` message is rendered, not refused.**
  - Both routes turn a `system` message after the first position into a `user` message, in place: ct 91 equals the as-user control, and mr 91 = cr 91.
  - Without a top-level `system` the count is 86, which matches the as-user mapping.
  - The frontend comment names Claude Code's hook context as the reason [source: `_late_system_to_user`].
- **`count_tokens` does not apply `tool_choice: none`.** It counts the tool schemas (305), while the request renders none (mr 59, cr 59). The `/v1/messages` handler drops the tools for `none`; `_count_tokens` does not [source].

**Cases where the neutral body as written in `p22` diverges, and the change that restores identity:**

| Case | Messages route | Neutral Chat | Fix that matched (identity) |
| --- | --- | --- | --- |
| `tool_use` input sent as canonical sorted JSON | 385 (insertion order) | 385, but **cache 0 / 725** | arguments in the input's own key order: 720 / 725 |
| tool without `description` | 297: the route renders `"description": ""` | 293 (key absent) | `description: ""` when absent: 630 / 635 |
| `system` starting with `x-anthropic-billing-header: ...cch=b145e;` | 94: `cch` and the 4th `cc_version` part pinned to `f`s | 97 (raw) | pinning the stamp the same way: 427 / 432 |
| `thinking: {"type":"enabled","budget_tokens":N}` | 1024 → 47 (= `low`), 4096 → 21 (= `medium`), 16000 → 59 (= `xhigh`) | 59 (not mapped) | `reasoning_effort` from the budget (under 2048 low, under 8192 medium, else xhigh): 357 / 362 |

- **Key order.** The Messages route renders `input` in the order the client sent it, and the Chat route parses `arguments` keeping the string's order. Sorted keys give the same count but different tokens when the input is not already sorted (`render_equals_neutral: false` locally).
- **`budget_tokens`** also becomes a real reasoning budget: `reasoning_budget_tokens`, which closes thinking after N tokens [source; behaviour not probed].

**The repo's local counter (c4) fails on two shapes the 0.1.54 Chat route accepts:**
- a mid-conversation `system` message: `RenderError: System message must be at the beginning`. The counter does not apply Strata's late-system-to-user step.
- `reasoning_effort: "max"`: `RenderError: Unexpected reasoning effort max`. Strata maps `max` and `maximum` to `xhigh` before the template.

**Field classification on `/v1/messages` (0.1.54).** "Not rendered" means the prompt count equals the case without the field. Sampling fields still act on sampling.

| Field | Class | Evidence (ct / mr against the reference) |
| --- | --- | --- |
| `system` (string or text blocks) | rendered, blocks joined `""` | 63 = 63 |
| user / assistant text blocks | rendered, joined `""` | 62, 84 |
| `tool_result` (string or text blocks) | rendered as `tool`, joined `""`, before the message's text | 367, 375 |
| `tool_result.is_error` | not rendered | 367 = 367 |
| `cache_control` (anywhere) | not rendered | 351 = 351 |
| `thinking` block | rendered as reasoning | 84 against 77 |
| `thinking.signature` (present, `""`, absent) | not rendered | 84 = 84 = 84 |
| `redacted_thinking` block | dropped, no error | 77 = 77 |
| `document` block (any unknown block type) | dropped, no error | 59 = 59 |
| `role: system`, first position | rendered as system | 59 = 59 |
| `role: system`, later | rendered as `user`, in place | 91 = 91 |
| unknown role (`bot`) | 400 `Unexpected message role.` | ct, mr and cr all 400 |
| `thinking.type: disabled` | rendered (closed think block, no effort line) | 23 against 59 |
| `thinking.type: adaptive` | not rendered (default effort) | 59 = 59 |
| `thinking.type: enabled`, no budget | not rendered (default effort) | 59 = 59 |
| `thinking.budget_tokens` | rendered as an effort level | 47 / 21 / 59 |
| `output_config.effort` `low` / `medium` | rendered | 47 / 21 |
| `output_config.effort` `high` / `xhigh` / `max` | rendered as the default `xhigh` | 59 |
| `output_config.effort` unknown (`bogus`) | 400 `unknown reasoning effort 'bogus': use none, low, medium or high` | ct, mr, cr 400 |
| `disabled` plus `effort: low` | `disabled` wins | 23 = 23 |
| `tool_choice` `auto`, `any`, `tool`, `disable_parallel_tool_use` | not rendered (the forced forms change the output, §13.1) | 305 = 305 |
| `tool_choice: none` | tools not rendered on `/v1/messages`; **still counted by `count_tokens`** | mr 59, ct 305 |
| `top_k`, `temperature`, `top_p` | not rendered; `top_k: "5"` (a string) also accepted | 59 = 59 |
| `stop_sequences` (list) | not rendered | 59 = 59 |
| `stop_sequences` (string) | 400 `stop_sequences must be a list of strings`; Chat's `stop: "END"` is valid | ct, mr 400 |
| `metadata` | not rendered | 59 = 59 |
| unknown top-level field | ignored | 59 = 59 |
| `tools[].description` absent | rendered as `""` | 297 against 293 |
| `tools[].cache_control` | not rendered | 351 = 351 |

### 13.3 Errors (M3, `p23_messages_errors.py`) [verified unless marked]

Fixture: `p23_messages_errors.json`. Every error is `application/json` with `Connection: close`. **The body is `{"error":{"type":"invalid_request_error","message":...}}`, not Anthropic's `{"type":"error","error":{...}}`**, unchanged from §8.

| Case | Status | Message / note |
| --- | --- | --- |
| Malformed JSON (`/v1/messages` and `count_tokens`) | 400 | `Expecting value: line 1 column 29 (char 28)` |
| Body not an object | 400 | `send a JSON object` |
| `{}`; `messages: []`; one message without `content` | 400 | `No messages provided.` |
| `messages: "hi"` | 400 | `messages must be a list of objects (a string was sent that is not JSON)` |
| Unknown role, stream or not | 400 | `Unexpected message role.` A streaming request gets plain JSON, not SSE |
| OpenAI-wrapped tools | 400 | `tools[0] has no name: each tool must be {"name": ..., "input_schema": {...}}` |
| Prompt over context (35,480 tokens, ctx 32,768), stream or not | 400 in 0.02–0.03 s | `request exceeds the context window: prompt (35480 tokens) leaves no room to answer in the context (32768); requests are never truncated`; plain JSON for the stream too |
| `count_tokens` on that body | 200 | `{"input_tokens": 35480}`: no context check |
| Prompt 19,944 + `max_tokens` 16,000 > ctx, with or without `fit_max_tokens: false` | 200 | not refused; the answer was 2 tokens, so a clamp would not show |
| `POST /v1/messages/batches`; `GET /v1/messages` | 404 | `{"error":{"message":"not found"}}` (no `type`) |
| Engine down | — | **not probed [unverified]**; 0.1.48 gave 503 `server_error` (§8). For mid-stream errors see §13.1 |

The 0.1.54 source also returns two codes not observed here [source]:
- 429 `rate_limit_error` (`code: admission_full`, `Retry-After: 1`) when its admission limit is full;
- 503 `server_draining`.

### 13.4 Cross-dialect cache reuse (M4, `p24_cross_dialect_cache.py` part B) [verified]

Each scenario primes a conversation of about 1,600 tokens (fresh nonce) through one route. It then sends the conversation, extended by the reply and one user turn, through the other route. Fixture: `p24_cross_dialect_cache.json` (`extension`).

| Prime → extend | Thinking | Prime prompt + completion | Extend prompt | Cached | δ |
| --- | --- | --- | --- | --- | --- |
| Messages → Chat | off | 1585 + 25 | 1630 | 1611 | +1 |
| Messages → Chat | low | 1609 + 253 | 1880 | 1863 | +1 |
| Chat → Messages | off | 1585 + 36 | 1641 | 1622 | +1 |
| Chat → Messages | low | 1609 + 154 | 1781 | 1764 | +1 |
| Messages → Messages (control) | off | 1585 + 27 | 1632 | 1612 | 0 |
| Chat → Chat (control) | off | 1585 + 32 | 1637 | 1617 | 0 |

δ = cached − (prime prompt + completion).

- **A conversation primed through one dialect and extended through the other reuses the whole generated turn**, as within one dialect (§12.3). δ is +1 against 0 for the controls.
  - `/metrics` agrees: `reused` equals cached, with 17–19 tokens read.
  - Thinking blocks resent as `reasoning_content`, and the reverse, keep the reuse.
- **Tool loop, Messages → Chat.** The model's call was `{"path": "a.txt", "content": "hi"}`.
  - Resent with sorted keys (`{"content":"hi","path":"a.txt"}`): cached 1,869, which is the prime prompt − 7. Only the generation-start checkpoint was reused. The 39-token generated turn was read again: δ −46, 64 tokens read.
  - Resent in the model's key order: cached 1,915, δ −1.
- **Claude Code's billing stamp.** Two requests differ only in `cch=`:
  - on `/v1/messages`: 766 / 0, then 766 / 759. The stamp is pinned, so the second request reuses everything.
  - on Chat: 769 / 0, then 770 / 0. The system prompt changed at its start, so nothing is reused.

### 13.5 `?beta=true` and Anthropic headers (M5, `p25_messages_beta_headers.py`) [verified]

Fixtures: `p25_messages_beta_headers.json` and `p25_beta_headers_stream.sse`.

- **Every variant returned 200 with the same prompt (24 tokens)**, non-streaming, streaming and on `count_tokens`. The variants:
  - the `?beta=true` query;
  - `anthropic-version: 2023-06-01`;
  - `anthropic-beta` with Claude Code's betas, or with an unknown beta name;
  - `x-api-key` and `Authorization: Bearer` with dummy values (this server runs without an API key);
  - the `/v1/v1/messages` and `/v1/v1/messages/count_tokens` aliases.
- The query string is stripped before routing [source: `_post`]. `anthropic-version` and `anthropic-beta` appear only in the CORS allow-list, so the beta headers have no effect on the prompt [source].
- Responses carry no Anthropic headers: no `request-id` and no rate-limit headers. They have only `Server`, `Content-Type`, `Content-Length` or the SSE headers, and `Connection: close`.

### 13.6 What this changes for Phase 4B

- **Core position 2 (one upstream dialect) is supported.**
  - Messages and Chat give the same tokens and reuse each other's cache when the neutral mapping matches the Messages route.
  - The `input_tokens: 1` note still holds.
  - The Messages route does four things Chat does not. The adapter must reproduce them to keep parity with the direct-Messages arm and to keep Claude Code's prefix stable:
    - pin the billing stamp;
    - render `description: ""` for tools without a description;
    - map `budget_tokens` to an effort level;
    - map `max` to `xhigh`.
- **Core position 3.**
  - **"Canonical JSON" for `tool_use.input` must keep the input's key order, not sort the keys.** Sorting changes the rendered tokens and loses the generated-turn reuse after every tool call. The content hash can still use sorted keys; only the resent Chat arguments must keep the order.
  - The rest of the mapping matches Strata: the block split (`tool_result`s first, then text), the `""` joins, and dropping `cache_control`, `is_error`, `signature`, `redacted_thinking` and unknown blocks.
- **Keep-alives.** Strata's Messages stream sends comments, never `ping`. A proxy that emits `event: ping` (core position 6) is therefore not copying upstream behaviour. Whether Claude Code needs `ping` is still HC5.
- **O-4B-12 (mid-conversation system messages).**
  - Strata 0.1.54 neither refuses nor merges them: it renders them as `user` messages in place, on both routes.
  - The repo counter (c4) refuses that shape, and refuses `effort: "max"`. It needs a late-system-to-user step and the effort aliases before such requests can be counted locally.
- **`count_tokens` is not exact for `tool_choice: none`**: it includes the tool schemas.
- **Cut-off tool calls.** A length stop inside tool arguments streams a closed `tool_use` block with unparseable JSON and `stop_reason: "max_tokens"`. The non-streaming route drops that block instead. The Messages emitter must choose which behaviour to copy.
