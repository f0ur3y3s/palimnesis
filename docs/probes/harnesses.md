# Harness probe: Pi, OpenCode, Claude Code

Oct 24, 2026 · Phase 0 static research

## What this is, and what it is not

This is a read-only investigation of the three installed harnesses. It supports the Phase 0 first-harness choice and the Phase 4B harness-expansion notes in `docs/v1_plan.md`. The three harnesses are evaluated on equal footing. The user's existing Pi provider entry for Strata is recorded as an environment fact only. It is not counted as an advantage, because each harness needs similar provider configuration.

Every finding comes from reading installed code, bundled strings, tagged upstream source or public docs. None of the harnesses was run against a server. The plan requires captured fixtures rather than assumed defaults ("Client timeouts and automatic retries"), so treat each timeout, retry and request-shape claim here as a hypothesis to confirm with a fake-upstream capture.

Markers:
- **INFERRED**: deduced from code paths, not directly observed.
- **UNVERIFIED**: could not be confirmed from the available sources.

Versions examined:

| Harness | Version | Source examined |
| --- | --- | --- |
| Pi | 1.4.0 (commit `4a080252f06c`) | Unbundled JS in `~/.pi/agent/install/releases/1.4.0/node_modules/@earendil-works/*/dist`, spot-checked against `pi-coding-agent/dist/bundle/cli.js`. Bundled docs in `pi-coding-agent/docs/`. |
| OpenCode | 2.1.4 (tag `v2.1.4`, commit `68bc26b7da19`) | Strings extracted from `%APPDATA%\npm\node_modules\@opencode\cli\bin\opencode.exe` (Bun single-file binary), plus the GitHub source tarball at the tag. Bundle strings match the tag source. |
| Claude Code | 2.1.310 (`GIT_SHA 0d2056ec…`, built 2026-10-23) | Strings extracted from `~/.local/bin/claude.exe` (Bun single-file binary), plus code.claude.com docs. Minified identifiers below are from this build only. |

Path shorthands used below:
- `$PI` = `~/.pi/agent/install/releases/1.4.0/node_modules/@earendil-works`
- `$OC` = `https://github.com/anomalyco/opencode/blob/v2.1.4/`
- Claude Code references are bundle identifiers or quoted strings.

---

## Pi 1.4.0

### 1. Wire protocols and custom endpoint configuration

Custom providers are configured in `~/.pi/agent/models.json`. Each provider's `api` value picks the protocol (`$PI/pi-coding-agent/docs/models-configuration.md` lines 13–57, 109–175):
- `openai-completions` (Chat Completions)
- `openai-responses` (Responses)
- `anthropic-messages`
- Others, such as Google and Bedrock, which are not relevant here.

Provider-level fields:
- `baseUrl`, `api`, `apiKey`, `headers`, `compat`, `authHeader`, `models`, `modelOverrides`.
- `apiKey` and `headers` accept `$ENV`, `${ENV}` and `!command` (`$PI/pi-coding-agent/dist/core/resolve-config-value.js` lines 21–70).
- `baseUrl` is used raw, with no interpolation (INFERRED from `provider-composer.js` lines 88, 139, 168).

Model-level fields:
- `baseUrl`, `reasoning`, `contextWindow`, `maxTokens`, `headers`, `compat`.
- `samplingParams`: fields merged into the request body.
- `thinkingLevelMap`.

The config directory can be relocated per process with `PI_CODING_AGENT_DIR` (`docs/environment-variables.md`). Extensions can also register providers at runtime with `pi.registerProvider()` (`docs/custom-provider.md`).

Environment fact: `~/.pi/agent/models.json` already has a `strata` provider (`openai-completions`, `http://192.168.1.173:8080/v1`, `reasoning: true`, `contextWindow` 32768, `maxTokens` 8192, no `compat` overrides). `settings.json` contains no behaviour settings, so every default below is in effect.

### 2. URL joining, prefix preservation, headers

**OpenAI paths.** Pi uses the official `openai` SDK with `baseURL: model.baseUrl` (`$PI/pi-ai/dist/api/openai-completions.js` lines 560–566).
- The SDK joins with `new URL(baseURL + path)` (`pi-ai/node_modules/openai/client.js` lines 471–475).
- So `http://127.0.0.1:9000/s/<session>/v1` becomes `…/s/<session>/v1/chat/completions`. **The prefix is preserved.**

**Anthropic path.** Pi uses `@anthropic-ai/sdk` through `client.beta.messages.create` (`anthropic-messages.js` line 444).
- So `http://127.0.0.1:9000/s/<session>` becomes `…/s/<session>/v1/messages?beta=true`.
- **The prefix is preserved, but Palimnesis must accept the `?beta=true` query.**

**Custom headers.**
- Provider- and model-level `headers` are merged last, so they override SDK defaults (openai-completions.js lines 556–559; anthropic-messages.js lines 823–826).
- `"X-Palimnesis-Session": "$PALIMNESIS_SESSION"` works.
- The extension hook `before_provider_headers` can rewrite headers per request.

**Native session headers.**
- Off by default.
- `compat.sendSessionAffinityHeaders: true` sends Pi's session ID as `session_id`, `x-client-request-id` and `x-session-affinity` (openai-completions.js lines 544–555).
- They are omitted when `cacheRetention` is `"none"`, and compaction and branch-summary calls force that value, so those calls never carry them.

**Per-session URL.** `baseUrl` is static per config. A per-session URL needs one of:
- a separate `PI_CODING_AGENT_DIR` (with its own models.json) per Palimnesis session, or
- an extension that computes the URL (INFERRED).

`/new`, `/fork`, `/clone` and `/resume` change Pi's internal session ID without changing the URL.

### 3. HTTP client, timeouts, retries

**Clients.**
- `openai` 7.19.0 (`pi-ai/node_modules/openai/version.js`) and `@anthropic-ai/sdk` 0.129.0.
- Transport is Node fetch, replaced with npm `undici` 8.10.2 through `setGlobalDispatcher(new EnvHttpProxyAgent(...))` (`pi-coding-agent/dist/core/http-dispatcher.js` lines 68–97).

**Timeouts.**

| Timeout | Default | Source |
| --- | --- | --- |
| Connect | 10 s (undici default, not overridden) | `undici/lib/core/connect.js:69` |
| Headers timeout and body read-idle | 300000 ms each | `httpIdleTimeoutMs`; `0` disables (`http-dispatcher.js` lines 3, 77, 81; `docs/settings.md` line 126) |
| SDK `timeout` | Same 300 s (`retry.provider.timeoutMs ?? httpIdleTimeoutMs`) | Armed only until response headers arrive (`openai/client.js` lines 991–1025) |
| Total deadline for a stream | None (INFERRED) | — |

**SDK retries.** Disabled: Pi passes `maxRetries: 0` on every call (openai-completions.js line 195; anthropic-messages.js line 429).

**Provider-level retry** (`pi-ai/dist/utils/provider-retry.js`):
- Applies only up to response headers.
- Retryable: `x-should-retry: true`, connection errors, 408, 409, 429, ≥500.
- Honours `retry-after` / `retry-after-ms`, capped at 60 s.
- Backoff is `min(0.5·2^i, 8)` s.
- **Default count is 0** (`retry.provider.maxRetries`).

**Agent-level retry** (`pi-coding-agent/dist/core/agent-session.js`; defaults in `settings-defaults.js` lines 17–25):
- **On by default:** `retry.enabled: true`, `maxRetries: 3`, `baseDelayMs: 2000`, giving delays of 2/4/8 s.
- Errors are classified by a regex over the error message (`pi-ai/dist/utils/retry.js` lines 26–106). It matches 429/5xx, overloaded, `fetch failed`, `terminated`, `socket hang up`, `timeout`, "Stream ended without finish_reason".
- Context overflow and quota errors are excluded.

**Retry after partial streaming: yes, at agent level.**
- The partial assistant message is recorded with `stopReason: "error"`.
- `_prepareRetry` (lines 3090–3125) adds `context_edit` omission entries for it.
- It then resends the **same prefix**, i.e. a replay rather than a continuation.

**Idempotency and retry headers.**
- No idempotency key.
- `X-Stainless-Retry-Count` is always `0`, because each retry is a fresh SDK call.
- `X-Stainless-Timeout: 300` is sent.

**Overrides.** settings.json keys `httpIdleTimeoutMs`, `retry.enabled`, `retry.maxRetries`, `retry.baseDelayMs`, `retry.maxAgentDelayMs`, `retry.provider.{timeoutMs,maxRetries,maxRetryDelayMs}`.

### 4. Streaming

Everything streams:
- `stream: true` is hard-coded on openai-completions (line 579), openai-responses and anthropic-messages (the anthropic path re-forces it after `onPayload`, line 441).
- Side calls (compaction, branch summary, cache warming) also stream; `completeSimple` is just `streamSimple(...).result()`.
- **No non-streaming model requests were found.**
- **There is no automatic title generation.** Sessions are named manually with `/name`.

### 5. Features that break a linear transcript

| Feature | Default | How to disable |
| --- | --- | --- |
| `/tree` (navigate, or edit and resubmit an earlier message; rewinds the same session) | Available, user-initiated | No setting. `doubleEscapeAction: "none"` removes the shortcut. An extension can cancel it via `session_before_tree`. |
| `/fork`, `/clone`, `/resume`, `/new`, `/import` | Available, user-initiated | No setting. An extension can cancel via `session_before_fork` / `session_before_switch`. Each produces a new Pi session ID. |
| `/tree` branch summarization (LLM call) | Prompted | `branchSummary.skipPrompt: true` defaults to no summary |
| Cache warming (concurrent `max_tokens: 1` replay while tools run) | `cacheWarming: "streaming"`. Inert unless the model declares `promptCache` lifetimes and the expected saving is at least $0.05 (INFERRED from the gating in `cache-warmer.js`). | `"cacheWarming": "off"` in the global settings.json |
| Subagents | None built in (extensions or SDK only) | Do not install subagent extensions |
| Parallel tool calls | Local parallel execution; results appended in call order; no `parallel_tool_calls` sent | Transcript stays linear; no change needed |
| Agent retry omission (§3) | On | `retry.enabled: false` |
| Mid-run steering and follow-up messages | Queued after tool results | Linear; no change needed |

### 6. Native compaction

**Triggers.**
- Threshold: `contextTokens > contextWindow − reserveTokens` (16384 by default), keeping 20000 recent tokens (`docs/compaction.md` lines 29–35).
- Checked between turns, before a prompt and after `agent_end`.
- Also on overflow or early-`length` recovery, where it compacts and retries. This includes llama.cpp's "exceeds the available context size" error (`pi-ai/dist/utils/overflow.js` line 20).

**Verified disable: `"compaction": { "enabled": false }` in `~/.pi/agent/settings.json`.**
- `_checkCompaction` returns false immediately when `!settings.enabled` (`agent-session.js` lines 2392–2394; spot-checked).
- `shouldCompact()` also returns false. This covers threshold, between-turn and overflow/length-recovery compaction.
- Manual `/compact` and `/tree` branch summaries remain user-triggerable.
- With compaction off, overflow surfaces as an error and is not retried.

### 7. Reasoning

**Parsing.** On openai-completions, deltas are read from `reasoning_content`, `reasoning` or `reasoning_text`, and the source field name is recorded.

**Replay.**
- Assistant history re-sends the thinking text under that same field, so **`reasoning_content` is echoed back** for same-provider/same-model messages (openai-completions.js lines 1008–1018).
- Thinking from a different model is dropped.
- There is no age-based stripping.

**Compat flags.**
- `requiresThinkingAsText`.
- `requiresReasoningContentOnAssistantMessages`, which forces `reasoning_content: ""` on every assistant message.

**Anthropic path.**
- Signed `thinking` blocks are replayed, and `redacted_thinking` is replayed with its `data`.
- Unsigned thinking becomes a text block unless `compat.allowEmptySignature: true`.

### 8. Request-shape oddities

These defaults apply to openai-completions on an unrecognised URL (`detectCompat`, `buildParams`).

**Fields sent:**
- `stream_options.include_usage: true`.
- `store: false`.
- **`max_completion_tokens`, not `max_tokens`**. It is clamped to `min(maxTokens, contextWindow − estimatedInput − 4096)`, so it shrinks as context fills. Override with `compat.maxTokensField: "max_tokens"`.
- The system prompt is sent with **role `developer`** when `reasoning: true`. Override with `compat.supportsDeveloperRole: false`.
- `reasoning_effort: "medium"`.

**`thinkingFormat` alternatives:**
- `qwen` sends `enable_thinking`.
- `qwen-chat-template` sends `chat_template_kwargs: {enable_thinking, preserve_thinking: true}`.
- `thinkingTokenBudgetField: "thinking_budget_tokens"` sends a llama.cpp-style budget.

**Not sent by default:**
- `tool_choice`, `parallel_tool_calls`, `user`, `metadata`, `cache_control`.
- `prompt_cache_key`. It is only sent for api.openai.com, or when `PI_CACHE_RETENTION=long`.

**Other shape details:**
- `tools: []` is sent when history has tool calls but no tools are active.
- Images in tool results move to a synthetic user message.
- Headers include `User-Agent: pi/1.4.0 (…)`, `X-Stainless-*` and `Authorization: Bearer <apiKey>`.

**On the Anthropic path:**
- `cache_control: {type: "ephemeral"}` on system, last tool and last user block.
- `eager_input_streaming: true` on tools.
- `anthropic-beta` headers.

---

## OpenCode 2.1.4

**Architecture note.** 2.x no longer uses the Vercel AI SDK on the request path for mapped providers. `$OC/packages/core/src/aisdk-native.ts` remaps config `npm` values onto OpenCode's own Effect-based client `@opencode/ai`:
- `@ai-sdk/openai-compatible` → `@opencode/ai/providers/openai-compatible`
- `@ai-sdk/anthropic` → `@opencode/ai/providers/anthropic`
- `@ai-sdk/openai` → `@opencode/ai/providers/openai`

As a result, AI SDK `maxRetries` and `APICallError.isRetryable` do not apply.

**Docs lag the code.** The published docs at the tag (`packages/web/src/content/docs/*.mdx`) describe the v1 config shape, while the code accepts both v1 and a native v2 shape (`packages/schema/src/config/*.ts`). At least one documented default is wrong; see `chunkTimeout` in §3.

### 1. Wire protocols and custom endpoint configuration

Native routes:
- Chat Completions (`openai-compatible-chat`, `$OC/packages/ai/src/protocols/openai-compatible-chat.ts`).
- Responses (`providers/openai`, `providers/openai-compatible/responses`). These are stateless over HTTP; `previous_response_id` is only used on the opt-in WebSocket transport.
- Anthropic Messages (`providers/anthropic`, `providers/anthropic-compatible`).

Config is `opencode.json` / `opencode.jsonc`, in either of two shapes:
- **v1 shape:** `provider.<id>.{npm, options:{baseURL, apiKey, headers, timeout, headerTimeout, chunkTimeout, setCacheKey}, models.<id>.{limit, interleaved, headers, options}}` (`packages/core/src/v1/config/provider.ts`).
- **v2 shape:** `providers.<id>.{package, settings:{timeout, headerTimeout, chunkTimeout, compaction, transport}, headers, body, compatibility, models.<id>.{limit, capabilities, compatibility, headers, body}}`.

Unknown v1 model options on openai-compatible are sent verbatim in the body (`COMPATIBLE_KEYS`, `v1/config/provider-options.ts`).

Interpolation:
- `{env:VAR}` and `{file:path}` are substituted at load (`config/variable.ts`).
- `${VAR}` in `baseURL` is resolved at model resolution (`model-resolver.ts`).

Environment fact: `~/.config/opencode/opencode.json` exists. It was not read.

### 2. URL joining, prefix preservation, headers

**Joining.** `new URL(trimBaseUrl(baseURL) + path)`, where trailing slashes are stripped (`$OC/packages/ai/src/route/endpoint.ts`). A query string inside `baseURL` would break the join.

**OpenAI.** Path `/chat/completions`. So `http://127.0.0.1:9000/s/<session>/v1` becomes `…/s/<session>/v1/chat/completions`. **The prefix is preserved.**

**Anthropic.** Path `/messages`, default base `https://api.anthropic.com/v1`.
- **The Anthropic-style base must include `/v1`.** Use `http://127.0.0.1:9000/s/<session>/v1` to get `…/v1/messages`.
- A bare `/s/<session>` base would POST to `/s/<session>/messages`.
- `?beta=true` is added only when the provider ID is `anthropic` (INFERRED from `model-resolver.ts`).

**Custom headers.** Supported at provider, model, variant and agent level, merged case-insensitively (`Provider.mergeHeaders`). `X-Palimnesis-Session` passes through. OpenCode's own per-request headers win on a name clash.

**Headers OpenCode always sends** (`session/model-request.ts`, confirmed in the bundle):
- `x-opencode-session-id`, the true session ID.
- `x-opencode-parent-session-id` and `x-parent-session-id`, for child sessions.
- `x-session-affinity`, `X-Session-Id` and `x-opencode-session`. These carry `parentID ?? fork.sessionID ?? id`, so subagents and forks **share their parent's or source's value** (`session/affinity.ts`).
- `User-Agent: opencode/…`, `x-opencode-project`, `x-opencode-client`.

**Per-session URL.**
- Config interpolation is per process.
- The plugin `session` hook `"model.request"` receives `{sessionID, kind: "primary"|"compaction"|"title"|"generate", baseURL, headers}` and may rewrite `baseURL` and headers (`packages/plugin/src/effect/session.ts`; applied in `packages/core/src/session/model-request.ts`). This would put `/s/<sessionID>` in the path and tag side calls by `kind`.
- Plugin registration paths and syntax for v2 are INFERRED and untested.

### 3. HTTP client, timeouts, retries

**Client.** Effect `FetchHttpClient` over Bun `fetch` (Bun 1.4.4, Effect 4.0.1). Bun's built-in 5-minute idle cut-off is disabled with `timeout: false` (`packages/core/src/effect/app-node-platform.ts`).

**Timeouts** (`packages/ai/src/route/transport/http.ts`, `packages/core/src/provider.ts`):

| Timeout | Default | Notes |
| --- | --- | --- |
| Connect | None separately | Covered by the header timeout |
| `headerTimeout` | 300000 ms | `false` disables (v2 only) |
| `chunkTimeout` (idle between raw byte chunks) | **900000 ms** | `DEFAULT_CHUNK_TIMEOUT_MS = 900_000`, spot-checked. The tag's `config.mdx` wrongly says 300000. Measured on raw bytes, so SSE comments should count as activity (INFERRED). |
| `timeout` (whole request) | None | Unbounded unless set |

**Retryable** (`packages/ai/src/provider-error.ts`):
- `x-should-retry` overrides everything else.
- Otherwise retryable: 429 (non-quota), 408, 409, 5xx, transport errors, incomplete streams (no `finish_reason`), and unknown failures.
- Not retried: auth, quota, content policy, context overflow, other 4xx.
- `retry-after` / `retry-after-ms` are honoured.

**Session retry loop** (`packages/core/src/model-retry.ts`, spot-checked):
- Exponential from 2 s, each gap capped at 10 s, with jitter.
- **Up to 10 retries.** `retry-after` can raise a delay up to 15 min.
- Timeouts are limited to 3 retries (`MAX_TIMEOUT_RETRIES = 3`).
- The count spans retries and continuations within a step.

**After partial streaming.**
- If no output has streamed, OpenCode resends the full request.
- If output has streamed, it does a **Continue**: the partial assistant message is kept and marked failed, then a synthetic user message is appended: "The previous response was interrupted. Continue from where you left off without repeating completed content."
- `x-should-retry: false` does **not** stop the Continue path. Only the plugin `retry` hook does.
- A `length` stop appends a synthetic "hit the output token limit" message, up to 2 times.

**Idempotency and retry headers.** Neither is sent.

**Overrides.**
- There is no config key for retry count.
- Use the plugin `retry` hook (`decision = {retry: false}`) or server-side `x-should-retry`.

### 4. Streaming

- Every request streams. `stream: true` is a schema literal for Chat and Anthropic.
- `stream_options.include_usage` is sent unless `compatibility.streamUsage: false`.
- `LLM.generate` collects a stream, so **no non-streaming requests reach the wire**.
- Title generation, compaction summaries and `/btw` side questions all stream.
- There is no `small_model` in v2 (v1 `small_model` becomes `agents.title.model`). For a custom provider, the title call likely uses the same Strata model on the same session headers (INFERRED).

### 5. Features that break a linear transcript

| Feature | Default | How to disable |
| --- | --- | --- |
| Title generation, concurrent with the first primary request (forked in `session/runner/llm.ts`) | **On** | v2 `"agents": {"title": {"disabled": true}}` / v1 `"agent": {"title": {"disable": true}}`, or the plugin `title` hook |
| Subagent tool (`subagent`, formerly `task`): child sessions, optionally background/concurrent | **On** | `"permissions": [{"action": "subagent", "resource": "*", "effect": "deny"}]` or v1 `"tools": {"task": false}`. A wholesale deny removes the tool definition (`packages/core/src/tool.ts` `whollyDisabled`). |
| Background shell jobs (shell tool `background: true` injects later notices) | Available | Only by denying `shell` (INFERRED) |
| Undo, redo, revert (truncates history), `fork`, `timeline`, `/btw` | User-initiated TUI commands | No config switch found (UNVERIFIED that none exists) |
| Background compaction precompute | Off | `experimental.background_compaction` stays false |
| Warming keep-alive requests | Off (`warming: false`) | — |
| Parallel tool calls | Concurrent local execution; no `parallel_tool_calls` sent | Transcript stays linear |
| Session-retry Continue (§3) | On | Plugin `retry` hook only |
| Deterministic in-request rewrites | On | Instruction or date changes arrive as appended system-update messages; images over 25 MiB are replaced with placeholders. Not configurable (INFERRED). |

### 6. Native compaction

**v2 schema:** `compaction: {auto?, keep?: {tokens}, buffer?}` (`packages/schema/src/config/compaction.ts`).
- In 2.1.4, `prune` and `tail_turns` are reported as unsupported and ignored.
- There is no `autocompact` key and no `OPENCODE_DISABLE_AUTOCOMPACT` env var.

**Triggers:**
- Before each step, when the estimated context reaches the ceiling: window − max(15%, 16k), or window − `buffer`.
- On a provider context overflow.
- An unknown or zero window never triggers auto compaction.

**Verified disable: `"compaction": {"auto": false}`.**
- `compact()` returns `skipped` for both `auto` and `overflow` triggers (`packages/core/src/session/compaction.ts` line 288: "Only the user compacts when automatic compaction is off, overflow included", spot-checked).
- Manual `/compact` still works.
- Provider-native compaction (`settings.compaction: {type: "native"}`) is opt-in only.

### 7. Reasoning

**Parsing.** On openai-compatible, deltas are read from the configured field, then `reasoning_content`, `reasoning`, `reasoning_text`.

**Replay.**
- **Reasoning is re-sent under the same field on every prior assistant turn**, including turns that have only tool calls (`protocols/openai-chat.ts` `lowerAssistantMessage`).
- This applies only to same-provider, same-model, non-failed messages. Failed or interrupted messages have their reasoning converted to plain text (`runner/to-llm-message.ts`).

**Config.**
- v1 `"interleaved": {"field": "reasoning_content"}` or v2 `compatibility.reasoningField` fixes the field.
- It also forces the field onto every assistant message, with `""` when empty.

**Anthropic path.**
- Signed thinking and `redacted_thinking` are replayed.
- Unsigned thinking is demoted to text; this is not configurable for custom providers (INFERRED).
- `anthropic-beta: interleaved-thinking-2025-05-14` is always sent.

### 8. Request-shape oddities

**Chat Completions:**
- One `system` message.
- Tools carry `strict: false`.
- **`max_completion_tokens`** for custom providers, defaulting to `min(limit.output or 32000, 256000)` reduced to the space left in the context window, with a minimum of 1024. Override with v2 `compatibility.maxTokensField: "max_tokens"`.
- `tool_choice` is sent only as `"none"` on the step-limit step.
- `tools: []` is sent when tool history exists but no tools are active.
- **The stream must end with a known `finish_reason` and `[DONE]`.** Otherwise it is an incomplete-stream error, which is retryable.

**Not sent to custom providers by default:** `store`, `prompt_cache_key`, `reasoning_effort`, `chat_template_kwargs`, `cache_control` (`packages/ai/src/cache-policy.ts`).

**Anthropic route:** automatic `cache_control` ephemeral breakpoints (at most 4), `max_tokens` 32000.

**Provider IDs to avoid:** `ollama`, `lmstudio`, `vllm`. Their built-in plugins poll local servers every 30 s (`packages/core/src/plugin/provider/local.ts`).

---

## Claude Code 2.1.310

### 1. Wire protocols and custom endpoint configuration

**Anthropic Messages only.**
- The bundle contains no `chat/completions` string (spot-checked: 0 occurrences).
- The gateway protocol docs (code.claude.com/docs/en/llm-gateway-protocol) list only Anthropic Messages, Bedrock InvokeModel and Vertex rawPredict.
- **Palimnesis would have to serve Anthropic Messages, including SSE, and translate to Strata's OpenAI-compatible API.**

**Configuration** (shell env or the settings.json `"env"` block):
- `ANTHROPIC_BASE_URL`. The provider remains `firstParty`.
- Credentials: `ANTHROPIC_AUTH_TOKEN` (sent as Bearer), `ANTHROPIC_API_KEY` (sent as `x-api-key`), or `apiKeyHelper`.
- Models: `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU,FABLE}_MODEL`, `ANTHROPIC_SMALL_FAST_MODEL` (deprecated but still read), `CLAUDE_CODE_SUBAGENT_MODEL`.
- Docs say a base URL with no gateway credential falls back to a saved claude.ai login.

**Unknown model IDs** get an assumed 200K window. Set `CLAUDE_CODE_MAX_CONTEXT_TOKENS` to the real Strata capacity.

### 2. URL joining, prefix preservation, headers

**Joining.** SDK `buildURL` concatenates base + path, de-duplicating a joining slash.
- `http://127.0.0.1:9000/s/<session>` becomes `POST …/s/<session>/v1/messages?beta=true` (path string spot-checked).
- **The prefix is preserved.** An OpenAI-style `/v1` base would double to `/v1/v1/messages`.

**Other calls on the base URL:**
- `HEAD {base}/api/hello`, a connection warm-up with a 10 s timeout. Skipped when a proxy, socket or client certificate is configured.
- `POST /v1/messages/count_tokens?beta=true`. Optional; Claude Code falls back to a character estimate.
- `GET /v1/models?limit=1000`, only with `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`.
- `cache_touch` is not sent to custom base URLs.

**Traffic that does not follow the base URL:** OAuth, GrowthBook flags, telemetry, fast-mode checks and the WebFetch preflight go to Anthropic hosts. They are cut by:
- `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`
- `DISABLE_TELEMETRY`
- `DISABLE_GROWTHBOOK`
- `skipWebFetchPreflight`

**Custom headers.** `ANTHROPIC_CUSTOM_HEADERS` takes newline-separated `Name: value` lines (parser `hAe()` splits on `\r?\n` and the first `:`). It is merged after defaults, so `X-Palimnesis-Session` passes through.

**Headers always sent:**
- `X-Claude-Code-Session-Id`
- `x-app: cli`
- `User-Agent: claude-cli/2.1.310 …`
- `anthropic-version: 2023-06-01`
- `X-Stainless-*`
- `x-claude-code-agent-id` and `x-claude-code-parent-agent-id`, on subagent requests

**Opt-in header:** `CLAUDE_CODE_GATEWAY_HINT_HEADERS=1` adds `x-claude-code-request-class` (`main|subagent|workflow|compaction|auxiliary|side_reply`) and related hints.

**Per-session URL.** `ANTHROPIC_BASE_URL` is per process. `/clear` regenerates the session ID while the URL stays fixed (INFERRED from `regenerateSessionId` and the docs).

### 3. HTTP client, timeouts, retries

**Client.** Bun `fetch` via `@anthropic-ai/sdk` **0.128.0** (`var aA="0.128.0"` feeds `X-Stainless-Package-Version`; spot-checked).

**Timeouts:**

| Timeout | Default | Notes |
| --- | --- | --- |
| `API_TIMEOUT_MS` | 600000 ms; `0` means no limit | For streaming, limits only the wait for response headers. `X-Stainless-Timeout: 600`. |
| Non-streaming requests | `API_TIMEOUT_MS`, else 300000 ms | — |
| Connect | None | `CLAUDE_CODE_CONNECT_TIMEOUT_MS` is a no-op since 2.1.186 (docs) |
| Event-level idle watchdog | On; ≥300000 ms | `CLAUDE_STREAM_IDLE_TIMEOUT_MS`; `CLAUDE_ENABLE_STREAM_WATCHDOG=0` disables. On custom URLs, bytes without parsed events reset it only for a limited time (docs). |
| Byte-level watchdog | 300 s for non-Anthropic hosts, clamped 10 s–30 min | `CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS`, `CLAUDE_ENABLE_BYTE_WATCHDOG` |
| Body idle | About 5 min | Active for custom URLs; `API_FORCE_IDLE_TIMEOUT=0` disables |

Proper SSE `ping` events, rather than comments, are the safer keepalive (INFERRED).

**Retries.**
- SDK `maxRetries: 0` for the main loop. Claude Code's own wrapper retries instead.
- **Default 10 retries.** `CLAUDE_CODE_MAX_RETRIES` overrides it, capped at 15.
- Backoff is `min(32 s, 0.5 s·2^(n−1))` plus 25% jitter.
- An integer-seconds `retry-after` header raises a delay. If a delay exceeds about 60 s, Claude Code stops retrying and surfaces the error.
- Retryable: `x-should-retry` (wins either way), connection errors, 408, 409, 401 after auth refresh, ≥500, and most 429.
- A body with `overloaded_error` is treated as 529. Background query sources get no 529 retries. After 3 consecutive 529s, Claude Code switches to the fallback model if one is configured.
- A 400 context-limit error is retried with a reduced `max_tokens`.

**After a stream failure.** A decision table (`keepPartial`, `retryWithoutStreaming`, `retry`, `useFallbackModel`, `fail`) depends on how far the stream got.
- **If nothing complete was received, Claude Code re-sends the turn non-streaming** ("Retrying without streaming", spot-checked).
- A 404 on a stream also tries non-streaming once.
- If output had completed, the partial output is kept.
- `CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK=1` disables the non-streaming resend. The docs warn it can duplicate tool execution behind proxies.

**Idempotency and identity headers.**
- No `Idempotency-Key`.
- `x-client-request-id` is only sent to Anthropic hosts.
- `X-Stainless-Retry-Count` is effectively always 0 (INFERRED from `maxRetries: 0`).

**Session identity in the body.** `metadata.user_id` is a JSON string containing `session_id`, `device_id` and `account_uuid`.

### 4. Streaming

- The main loop and subagents stream.
- **Non-streaming is used for:**
  - the fallback resend (§3)
  - every "side query" (built without `stream`)
  - the `quota_check` probe (`max_tokens: 1`)
  - `verify_api_key`
  - token counting
- Query sources found in the bundle include:
  - Session and conversation: `generate_session_title`, `away_summary`, `prompt_suggestion`, `agent_summary`, `tool_use_summary_generation`.
  - Memory: `extract_memories`, `auto_dream`.
  - Tools: `web_fetch_apply`.
  - Other: `compact`, `side_question` (/btw), and classifier sources.
- Which of these sources stream is UNVERIFIED.

### 5. Features that break a linear transcript

| Feature | Default | How to disable |
| --- | --- | --- |
| `/rewind`, Esc Esc (truncate conversation) | Available, user-initiated | **No switch found.** `CLAUDE_CODE_DISABLE_FILE_CHECKPOINTING` only affects file restore. Whether `--disable-slash-commands` blocks it is UNVERIFIED. |
| `--resume`, `--continue`, `--fork-session`, `/clear` | User-initiated | No switch. `/clear` and forks get new session IDs on the same base URL (INFERRED). |
| Agent tool subagents. **Fork mode on by default**; can run in the background. | On | `permissions.deny: ["Agent"]` or `--disallowedTools Agent`; `CLAUDE_CODE_FORK_SUBAGENT=0`; `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` |
| Prompt suggestions | Flag-gated, default off | `CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION=false` / `promptSuggestionEnabled: false` |
| Away summary | Can fire | `CLAUDE_CODE_ENABLE_AWAY_SUMMARY=0` / `awaySummaryEnabled: false` |
| Session title (background small/fast-model call) | On | `CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1` (docs) |
| Memory extraction and auto-dream | Can fire | `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, `autoDreamEnabled: false` (gating INFERRED) |
| WebFetch summarizer, server-side `web_search` | Available | Deny `WebFetch` / `WebSearch`. Strata cannot run `web_search`. |
| Error-recovery history rewrites (strip media or thinking, then retry) | On | Not configurable |
| Parallel tool calls | Up to 10 concurrent; results returned in one user turn | Transcript stays linear |

**Not a model-call switch:** `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` does not stop model side calls, and `DISABLE_NON_ESSENTIAL_MODEL_CALLS` does not exist in this build.

**Feature flags:** many behaviours depend on GrowthBook flags. `DISABLE_GROWTHBOOK=1` pins them to their code defaults.

### 6. Native compaction

**Gate** (spot-checked): `Boolean(Fe(process.env.DISABLE_COMPACT)||i.DISABLE_AUTO_COMPACT)`. Every automatic path checks `Lf()`, which returns false under that gate or `autoCompactEnabled: false`. The paths are threshold, reactive (after prompt-too-long), idle/sleep and precompute.

**Verified disables:**
- `DISABLE_AUTO_COMPACT=1` or `"autoCompactEnabled": false` disables all automatic compaction. Manual `/compact` still works.
- **`DISABLE_COMPACT=1` additionally disables manual `/compact`.**

**Trigger:** effectiveWindow (window − min(maxOutput, 20000)) − 13000. `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` can only lower it; `CLAUDE_CODE_AUTO_COMPACT_WINDOW` sets the window.

**Client blocking limit, even with compaction off:** Claude Code refuses to send ("Prompt is too long") at about window − min(maxOutput, 20000) − 3000 estimated tokens. Set `CLAUDE_CODE_MAX_CONTEXT_TOKENS`.

**Separate from compaction:** by default the request carries `context_management` (`clear_thinking_20251015`, `clear_tool_uses_20250919`) with beta `context-management-2025-06-27`, even for unknown models. These are server-side edit instructions. Palimnesis can ignore them, or the client can drop them with `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`.

### 7. Reasoning

**Thinking parameter sent:**
- Unknown models get adaptive thinking: `thinking: {type: "adaptive"}` plus `output_config.effort`.
- Otherwise `{type: "enabled", budget_tokens}`.
- `{type: "disabled"}` when thinking is off.

**Settings:**
- `MAX_THINKING_TOKENS` sets the budget.
- `CLAUDE_CODE_DISABLE_THINKING=1` omits the parameter.
- A 400 naming an unsupported thinking type triggers one retry with the other type.

**Replay:**
- **Thinking and `redacted_thinking` blocks are re-sent with signatures.**
- Without a `signature_delta`, the signature stays `""` (replayed with an empty signature: INFERRED).
- Thinking-only unsigned tail messages are dropped.

**Signature rejection.** A 400 matching signature-error wording (e.g. "signature in thinking block") makes Claude Code strip all thinking blocks for the rest of the session.

**Implication for Palimnesis:**
- Emit an opaque, verifiable signature,
- omit thinking blocks, or
- deliberately trigger the strip path.

### 8. Request-shape oddities

**Betas, expected for a custom URL with an unknown model (INFERRED from the gating):**
- `claude-code-20250219`
- `interleaved-thinking-2025-05-14`
- `context-management-2025-06-27`
- `thinking-token-count-2026-05-13`
- `redact-thinking-2026-02-12`
- `effort-2025-11-24`
- Possibly `mid-conversation-system-2026-04-07`, `per-turn-control-2026-07-01`, `timing-2026-09-09`.

**Body fields:**
- `metadata.user_id` as a JSON string.
- `cache_control` ephemeral breakpoints on system and last message blocks. `DISABLE_PROMPT_CACHING=1` removes them.
- **Mid-conversation `role: "system"` entries inside `messages`** for unknown models. These are not removed by `DISABLE_EXPERIMENTAL_BETAS`. Claude Code retries without them after a 400 "Unexpected role system".
- The first system block is an `x-anthropic-billing-header: cc_version=…` text line. `CLAUDE_CODE_ATTRIBUTION_HEADER=0` removes it.
- Tool `defer_loading` and `tool_reference` blocks for MCP tool search. `ENABLE_TOOL_SEARCH=false` disables them.

**`CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1` removes:** `context_management`, beta tool fields (`strict`, `defer_loading`, `eager_input_streaming`), `output_config.format`, tool search, and the thinking-token-count and redact-thinking betas.

**Extra overrides:** `CLAUDE_CODE_EXTRA_BODY` (JSON merged into every body), `ANTHROPIC_BETAS`.

---

## Side-by-side

### Key facts

| | Pi 1.4.0 | OpenCode 2.1.4 | Claude Code 2.1.310 |
| --- | --- | --- | --- |
| Protocols to a custom endpoint | Chat Completions, Responses, Anthropic Messages | Chat Completions, Responses, Anthropic Messages | Anthropic Messages only |
| HTTP stack | openai 7.19.0 / @anthropic-ai/sdk 0.129.0 on undici 8.10.2 | Own `@opencode/ai` (Effect 4.0.1) on Bun 1.4.4 fetch | @anthropic-ai/sdk 0.128.0 on Bun fetch |
| Base for the OpenAI style | `…/s/<id>/v1` → `/v1/chat/completions` | `…/s/<id>/v1` → `/v1/chat/completions` | n/a |
| Base for the Anthropic style | `…/s/<id>` → `/v1/messages?beta=true` | `…/s/<id>/v1` → `/v1/messages` (must include `/v1`) | `…/s/<id>` → `/v1/messages?beta=true` |
| Custom header mechanism | `headers` in models.json (`$ENV`, `!cmd`) | `headers` in config (`{env:}`); plugin hook | `ANTHROPIC_CUSTOM_HEADERS` |
| Built-in session ID header | Opt-in (`compat.sendSessionAffinityHeaders`) | Always `x-opencode-session-id`; affinity headers carry the parent's ID | Always `X-Claude-Code-Session-Id`, plus `metadata.user_id.session_id` |
| Per-session base URL | Per process (`PI_CODING_AGENT_DIR` or an extension) | Per process, or per session via the `model.request` plugin hook | Per process (env) |
| Read-idle timeout | 300 s (`httpIdleTimeoutMs`) | 900 s (`chunkTimeout`) | About 300 s (several watchdogs plus body idle) |
| Total deadline | None | None | None for streaming (600 s is a header-wait limit) |
| Default automatic retries | Agent level: 3 (2/4/8 s); SDK and provider level: 0 | Session level: up to 10 (2–10 s), 3 for timeouts | 10 (0.5–32 s), cap 15 |
| Behaviour after partial stream | Replays the same prefix with the failed attempt omitted | Continue: keeps the failed partial and appends a synthetic user message | Keeps the partial if output completed; non-streaming resend if nothing completed |
| Idempotency key or useful retry count | None (`X-Stainless-Retry-Count` always 0) | None | None (`X-Stainless-Retry-Count` always 0) |
| Non-streaming requests | None found | None on the wire | Side queries, fallback resend, probes, count_tokens |
| Background model calls by default | None effective (cache warming inert for zero-cost models) | Concurrent title generation | Title, away summary, memory extraction, forked subagents |
| Subagents | None built in | Built in, on (deny `subagent`) | Built in, fork mode on (deny `Agent`) |
| User-initiated rewind/fork | `/tree`, `/fork`, `/clone`; extension can cancel | undo/redo/revert, fork, `/btw`; no switch found | `/rewind`, `--fork-session`, `/clear`; no switch found |
| Compaction disable (verified) | `compaction.enabled: false` (covers overflow) | `compaction.auto: false` (covers overflow) | `DISABLE_COMPACT=1` (covers manual too) or `DISABLE_AUTO_COMPACT=1` / `autoCompactEnabled: false` |
| Reasoning replay | `reasoning_content` echoed (same model) | `reasoning_content` echoed on every prior assistant turn (same model, non-failed) | Thinking blocks with signatures; empty signatures are a problem |
| Notable request oddities | `developer` role, `max_completion_tokens`, `store: false`, `reasoning_effort` | `max_completion_tokens`, `strict: false`, required `finish_reason` and `[DONE]` | Betas, `context_management`, mid-conversation system messages, billing-header system text, `metadata.user_id` |

### Scoring against the four criteria

Ratings are qualitative (Good / Fair / Poor) and reflect static findings only.

| Criterion | Pi 1.4.0 | OpenCode 2.1.4 | Claude Code 2.1.310 |
| --- | --- | --- | --- |
| **Normal supported workflow is linear** (plan Phase 0) | **Good.** There are no built-in subagents, no title or summary side calls, and cache warming is inert or switchable. Non-linear features are explicit user commands (`/tree`, `/fork`). Residual: the default agent retry replays after a partial stream (switchable via `retry.enabled: false`), and `/tree` cannot be turned off without an extension. | **Fair.** Linear once title generation is disabled and the `subagent` tool is denied, both by config. Residual: the Continue-after-partial retry adds a synthetic user turn after a failed partial and can only be stopped with a plugin; background shell jobs inject later notices; undo/revert and fork have no switch. | **Fair to Poor.** Linear only after roughly ten env and settings switches (subagents, fork mode, background tasks, title, away summary, memory, WebFetch/WebSearch). Residual: non-streaming fallback resends (switchable), error-recovery history rewrites (not switchable), `/rewind` (no switch), and behaviour that depends on feature flags. |
| **Path-prefix preservation** | **Good** for both styles, matching the plan's URLs exactly. Palimnesis must accept `?beta=true` on the Anthropic path. | **Good** for OpenAI style. **Fair** for Anthropic style: the base must be `…/s/<id>/v1`, not the plan's `…/s/<id>`. | **Good** for the Anthropic style in the plan; the OpenAI style is not applicable. Also sends `HEAD /s/<id>/api/hello`, and optionally `count_tokens` and `models`. |
| **Protocol fit with OpenAI-compatible Strata** | **Good.** Native Chat Completions with configurable `reasoning_content` handling, Qwen chat-template knobs and a `max_tokens` field override. Several defaults (`developer` role, `store`, `reasoning_effort`, `max_completion_tokens`) need compat settings or Strata tolerance. | **Good.** Native Chat Completions with configurable reasoning field and `max_tokens` field. Strict `finish_reason`/`[DONE]` expectations need to be met. Fewer extra fields than Pi by default. | **Poor.** Anthropic Messages only, so Palimnesis must translate Anthropic↔OpenAI, including SSE event lifecycles, thinking signatures, mid-conversation system messages, `context_management` and beta fields. The plan lists Anthropic Messages as a goal, so this work is eventually needed for 4B anyway, but it is a large Phase 0 dependency. |
| **Setup effort** | **Low to moderate.** One models.json provider plus `compaction.enabled: false`, `retry.enabled: false` (or a decision on retries), `cacheWarming: "off"`, and compat flags. A per-session URL needs a config dir per session or a small extension. Cancelling `/tree` and `/fork` needs an extension if enforcement is wanted. | **Moderate.** Provider config plus `compaction.auto: false`, title disable and subagent deny. A plugin is needed for a per-session URL path and to stop the Continue retry. The v1/v2 config split and stale docs add verification cost. | **High.** Anthropic-protocol translation in Palimnesis, plus a long env list: base URL, auth token, model, `CLAUDE_CODE_MAX_CONTEXT_TOKENS`, compaction, side-call and subagent switches, `DISABLE_EXPERIMENTAL_BETAS`, `DISABLE_NONSTREAMING_FALLBACK`, traffic and GrowthBook switches. Also guarding against falling back to a claude.ai login. |

### Neutral trade-off notes

**Pi**
- Has the fewest default side calls and the smallest gap between "installed" and "linear".
- Its retry model (replay the same prefix and omit the failed attempt) is the easiest of the three for Palimnesis's keyless-duplicate policy to recognise: it looks like a resend of the same visible parent.
- The costs:
  - user-facing tree and fork commands that cannot be disabled without an extension;
  - no native per-session URL;
  - a request body with several OpenAI-specific defaults that must be normalised for a local server.

**OpenCode**
- Matches the OpenAI path well. It always sends a precise session ID header (`x-opencode-session-id`), and its plugin hook can route each session and each call `kind` to distinct URLs, which suits the plan's identity model directly.
- The costs:
  - a concurrent title call and a subagent tool on by default;
  - a Continue-style recovery that adds synthetic turns after failed partial output, and that only a plugin can stop;
  - a 2.x codebase whose docs describe an older config shape;
  - an Anthropic base convention that differs from the plan's (`/v1` included).

**Claude Code**
- Is the most feature-rich and the most explicit about request classes: hint headers and agent IDs let Palimnesis tag side calls rather than only suppress them.
- Its Anthropic-only protocol would make the Anthropic adapter and the translation layer a Phase 0 prerequisite rather than a Phase 4B expansion.
- Its default behaviour includes the largest number of non-linear and non-streaming paths, several of which are flag-dependent and some of which (rewind, error-recovery rewrites) have no switch.

**Common to all three**
- No idempotency keys.
- No meaningful retry-count header.
- No total stream deadline.
- Retries driven by `x-should-retry` and 5xx/429.

So Palimnesis's error responses for duplicate or in-progress requests should carry `x-should-retry: false` and avoid 5xx/429 where a retry is unwanted. This is honoured by all three, except for OpenCode's Continue path. The plan's 429 overload response will be retried by all three under their default policies.

## Items to confirm with captured fixtures in Phase 0

1. Exact request bodies and headers for one turn, one tool loop and one streamed failure per harness. These confirm the INFERRED fields above (Pi `prompt_cache_key` gating, OpenCode `?beta=true` gating, Claude Code beta list and empty-signature replay).
2. Whether SSE comments, as opposed to `ping` events, reset each harness's idle timer, measured against the 300 s / 900 s / ~300 s limits.
3. Retry behaviour after a mid-stream disconnect with the default and the "linear" configurations:
   - Pi `retry.enabled: false`
   - OpenCode `retry` hook
   - Claude Code `CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK=1`
4. Whether `/tree` (Pi), revert (OpenCode) and `/rewind` (Claude Code) produce requests that Palimnesis's Phase 1 divergence detection rejects cleanly.
5. Whether the per-session URL mechanism works end to end:
   - Pi: a separate `PI_CODING_AGENT_DIR` or an extension.
   - OpenCode: the `model.request` hook.
   - Claude Code: per-process `ANTHROPIC_BASE_URL`.
