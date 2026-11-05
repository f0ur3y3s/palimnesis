# Pi 1.5.0 probe: joining, association, request shapes, timeouts, retries, compaction

Nov 5, 2026 · Phase 4B S0, probes HP1–HP7

## What this is

This probe records how Pi behaves against a scripted upstream, so that the Phase 4B Pi adapter (S9) and the decisions O-4B-2, O-4B-4, O-4B-5 and O-4B-9 rest on captured fixtures rather than on the 2026-10-24 static reading (`docs/probes/harnesses.md`, Pi 1.4.0). It confirms, corrects and extends that reading.

Every result comes from a real Pi process (`node …/pi-coding-agent/dist/bundle/cli.js`) talking to `eval/probes/pi_fault_server.py` on 127.0.0.1, except §3.6, which used a real model (LM Studio `qwen36` on mbp) through a local `palimnesis serve --passthrough`. No Strata server and no real provider was contacted.

Markers:
- **VERIFIED**: observed in a fixture.
- **SOURCE**: read in Pi 1.5.0's installed `dist`, not exercised.
- **UNVERIFIED**: neither.

## Version

| Item | Value | Evidence |
| --- | --- | --- |
| Pi | **1.5.0** (managed install, `~/.pi/agent/install/releases/1.5.0`; the plan assumed 1.4.0) | `pi --version`; `User-Agent: pi/1.5.0 (win32; node/v24.18.0; x64)` (VERIFIED) |
| OpenAI SDK | 7.19.0 | `x-stainless-package-version` (VERIFIED) |
| Node | v24.18.0, Windows 11 x64 | headers (VERIFIED) |
| Anthropic SDK | not in headers | UNVERIFIED (1.4.0 notes: 0.129.0) |

OS-dependent facts (paths, shell tool, exit codes) are from Windows and must be re-checked on the evaluation host.

## Setup

**Fault server** (`eval/probes/pi_fault_server.py`). A raw asyncio HTTP/1.1 server, derived from `opencode_fault_server.py`, that serves both protocols from one protocol-neutral step list:
- `*/chat/completions`: Chat chunks (`role`, `content`, `reasoning_content`, streamed `tool_calls`, `finish_reason`, a usage chunk, `[DONE]`).
- `*/messages`: Anthropic events (`message_start`, `content_block_*` for `thinking`/`text`/`tool_use`, `signature_delta` when scripted, `message_delta`, `message_stop`).
- Faults: delayed status line, clean EOF, reset (after a 1 s pause, see the OpenCode probe's Windows pitfall), hang, SSE comments, `event: ping`, in-stream errors (`data: {"error":…}` on Chat, `event: error` on Messages), error statuses with any headers.
- Each POST is one attempt; the scenario says what attempt N gets and the last entry repeats. Every request (time, target, headers, full body) is logged as JSONL.

**Driver** (`eval/probes/pi_probe.py`). One probe = one throwaway root with its own fault server and any number of Pi runs. Pi runs in `--mode json` (one prompt, stdin at EOF) or `--mode rpc` (scripted JSONL commands: `prompt`, `new_session`, `fork`, `clone`, `switch_session`, `compact`, `get_state`, …). `--summary RUNDIR` prints attempts, gaps, the kept prefix and the new messages of each resend, and Pi's retry/compaction/end events. `--export DIR` writes sanitized fixtures. `eval/probes/pi_count_f.py` counts F with the pinned Strata counter.

```sh
uv run python eval/probes/pi_probe.py --list
PI_PROBE_ROOT=<scratch> uv run python eval/probes/pi_probe.py 'hp1_*' 'hp2_*' 'hp3_*' 'hp4_*' 'hp5_*' 'hp6_*' 'hp7_*'
uv run python eval/probes/pi_probe.py --summary <scratch>/hp4_partial_error_then_ok_chat
uv run python eval/probes/pi_count_f.py <scratch>/hp6_default_tools
```

**Fixtures** (`eval/probes/fixtures/pi-1.5.0/`): `<run>/server.jsonl` (every request; a `tools`, `system` or leading system/developer message identical to the run's first request is written as `{"$same_as_seq": N}`), `<run>/*.rpc.jsonl` (command responses, retry and compaction events, each run's final message), `<run>/meta.json` (provider and settings used), `summary.txt` (the summarizer over all 79 fault-server runs), and `mbp/` (real-model passthrough captures). Paths are replaced by `<PROBE_ROOT>`/`<HOME>`/`<TMP>`; the API key was a dummy.

**Base config.** `models.json`: provider `fault`, `api` `openai-completions` or `anthropic-messages`, `apiKey` dummy, model `m` with `reasoning: true`, `contextWindow: 32768`, `maxTokens: 8192`. `settings.json`: `defaultProjectTrust: "never"`, `enableInstallTelemetry: false`, `cacheWarming: "off"`, `quietStartup: true`, `retry.baseDelayMs: 500` (except `hp4_s500_default_delay`). Runs pass `-nc` (no `AGENTS.md`/`CLAUDE.md`) unless noted.

### Isolation (VERIFIED)

| Setting | Reason |
| --- | --- |
| `PI_CODING_AGENT_DIR=<run>/agent` | Agent dir: `models.json`, `settings.json`, `sessions/`. The user's `~/.pi` was never read or written. |
| `HOME`, `USERPROFILE=<run>/home` | Anything Pi resolves from `~` |
| `PI_OFFLINE=1`, `PI_SKIP_VERSION_CHECK=1`, `PI_TELEMETRY=0`, `enableInstallTelemetry: false` | No catalog refresh, version check or install telemetry. The fault-server logs contain only model POSTs: no `GET /models` or other side traffic. |
| `cwd=<run>/work` | Session grouping and the `<cwd>` in the system prompt |
| Unset `PI_*`, `OPENAI*`, `ANTHROPIC*`, `HTTP(S)_PROXY` | No inherited credentials or proxies |

Built-in extensions (`builtin:mcp`, `builtin:llama.cpp`, `builtin:codemode`, `builtin:tool-search`) load by default; with no MCP config they added no tools and no traffic (VERIFIED: four tools in every default request, no non-model requests).

## HP1 URL joining (VERIFIED)

| Protocol | `baseUrl` | Request target |
| --- | --- | --- |
| Chat | `http://127.0.0.1:P/s/probe-sess/v1` | `POST /s/probe-sess/v1/chat/completions` |
| Chat | `…/s/probe-sess/v1/` (trailing slash) | `POST /s/probe-sess/v1/chat/completions` |
| Messages | `http://127.0.0.1:P/s/probe-sess` | `POST /s/probe-sess/v1/messages?beta=true` |
| Messages | `…/s/probe-sess/v1` | `POST /s/probe-sess/v1/v1/messages?beta=true` (**doubled**; do not put `/v1` in a Pi Messages base) |

The session prefix is preserved on both protocols. Messages always carries `?beta=true`. Runs: `hp1_*`.

## HP2 Association

### Header extension (VERIFIED)

The extension below (written by the driver as `palimnesis-session.ts`, loaded with `-e`) set `X-Palimnesis-Session` on every model request, on both protocols, to the id of the session that made the request:

```ts
export default function (pi) {
  pi.on("before_provider_headers", (event, ctx) => {
    event.headers["X-Palimnesis-Session"] = ctx.sessionManager.getSessionId();
  });
}
```

Pi's docs say the hook runs once per provider request and retries reuse its headers (SOURCE).

### Session operations (VERIFIED, RPC-driven; runs `hp2_sessions_chat`, `hp2_sessions_messages`, `hp2_tree*`)

| Operation | Pi session id after it | Next request's history |
| --- | --- | --- |
| Start | new UUIDv7, e.g. `01a1abec-4181-…` | — |
| `/new` (`new_session`) | new id | empty (system + new prompt) |
| `/fork` from a user message (`fork`) | new id; header `parentSession` | history **before** that message (fork from the first message = empty); the forked text is returned for editing |
| `/clone` (`clone`) | new id | the whole current branch, so the **first request under the new id already carries history** (4 messages) |
| `/resume` (`switch_session`) back to session A | A's id | A's history, exact prefix of A's last request |
| Restart with `--session <id>` | same id | exact prefix (Chat byte-equal; Messages equal except the moving `cache_control`) |
| Restart with `--continue` | most recent session's id | exact prefix |
| Restart with `--session-id pal-0123abcd` | **the chosen id** | new or existing session with that id |
| `/tree` to an earlier user entry (`ctx.navigateTree`, no summary) | **same id** | truncated: the earlier prefix plus the new prompt. Palimnesis sees a divergence. |
| `/tree` with summary | same id | first a **branch-summary side call on the same session** (summarizer system prompt, 2 messages), then the truncated prefix plus a user message `The following is a summary of a branch…` plus the prompt |

`/tree` was driven through an extension command calling `ctx.navigateTree` (the API behind the `/tree` UI); the interactive selector itself was not exercised (UNVERIFIED that the UI path is identical). The `/resume` picker UI was replaced by RPC `switch_session` (same session-replacement path per the docs, SOURCE).

Pi session ids (UUIDv7 with hyphens) are valid Palimnesis ids, and Palimnesis's `session new` ids (`YYYYMMDD-HHMMSS-hex8`) are valid Pi `--session-id` values (Pi: letters, digits, `.`, `_`, `-`, alphanumeric at both ends).

### Other identity sources (VERIFIED, `hp2_affinity_headers`)

- Off by default: no `session_id`/`x-session-affinity` headers and no `prompt_cache_key`.
- `compat.sendSessionAffinityHeaders: true` adds `session_id`, `x-client-request-id`, `x-session-affinity`, all equal to Pi's session id.
- Provider `headers` with `"X-Palimnesis-Session": "$PALIMNESIS_SESSION"` sends the environment value (per-process association, like the Claude Code wrapper).

## HP3 Request shapes

### 3.1 Chat defaults (VERIFIED, `hp1_join_chat`, `hp3_chat_default`)

| Field | Value |
| --- | --- |
| Top level | `model`, `messages`, `stream: true`, `stream_options: {include_usage: true}`, **`store: false`**, **`max_completion_tokens`**, `tools`, **`reasoning_effort: "medium"`** |
| Not sent | `tool_choice`, `parallel_tool_calls`, `temperature`, `user`, `metadata`, `prompt_cache_key`, `cache_control` |
| Leading message | **`role: "developer"`**, a string (2,475 characters on Windows, includes `<cwd>`) |
| User messages | **always an array of text parts**: `[{"type":"text","text":…}]`, even for one part. There is no compat flag for string content (SOURCE: `openai-completions.js` keeps the stored form; prompts are stored as arrays). |
| Assistant | `content` a string (all text blocks joined with `""`), or **`null`** when there is no non-whitespace text (tool-call-only turns); `reasoning_content` (the field the stream used); `tool_calls` |
| Tool results | `{"role":"tool","content":<string>,"tool_call_id":…}` (no `name`) |
| Tools | exactly `{type:"function", function:{name, description, parameters}}`; `read`, `bash`, `edit`, `write` by default. (Pi's internal `constrainedSampling` tool key appears in its JSON event echo but is **not** sent.) |
| Headers | `authorization: Bearer <key>`, `user-agent: pi/1.5.0 (…)`, `x-stainless-*` (`retry-count: 0`, `timeout: 300`), no idempotency key |

### 3.2 Chat compat flags (VERIFIED, `hp3_chat_compat`)

`compat: {supportsDeveloperRole: false, supportsStore: false, supportsReasoningEffort: false, maxTokensField: "max_tokens"}` gives `role: "system"`, no `store`, no `reasoning_effort`, and `max_tokens` instead of `max_completion_tokens`. Each flag only removes or renames its field; messages and tools are unchanged. **`supportsStore` exists in 1.5.0** (O-4B-9's "existence unverified" is settled).

### 3.3 Output limit (VERIFIED)

| `contextWindow` / `maxTokens` | First request |
| --- | --- |
| 32768 / 8192 | `max_completion_tokens: 8192` |
| 1,000,000 / 8192 | 8192 |
| 12000 / 8192 | **6336** |

The limit is clamped to the room the window leaves (`contextWindow − estimated input − 4096` in the static notes; 12000 − 6336 − 4096 = 1568 estimated tokens here). It therefore changes from request to request once the conversation nears `contextWindow`. A `contextWindow` far above any real conversation keeps it constant at `maxTokens`.

### 3.4 Resend fidelity, Chat (VERIFIED)

- Across turns, a tool loop, and a restart with `--session <id>`: every request's `messages` is a **byte-equal prefix** of the next one, and `tools`, the developer message and the limit are unchanged (`hp3_chat_default`, `hp3_chat_compat`, `mbp/mbp_chat_tool_loop`).
- The system prompt and tool loadout are persisted in the session file as a `system` message entry (new in 1.5.0) and replayed after a restart.
- What Pi changes between the stream it received and the history it resends:
  - **Tool-call `arguments` are re-serialized compactly** (`{"path": "notes.txt"}` streamed → `{"path":"notes.txt"}` resent). LM Studio's arguments were already compact, so they matched.
  - **Whitespace-only text and reasoning are dropped**: `reasoning "  "` + text `"\n\n"` + a tool call is resent as `content: null` with no `reasoning_content` (`hp3_chat_whitespace_tool`; real model: `qwen36` streamed `"\n\n"` before its call and Pi resent `null`).
  - Leading/trailing whitespace inside non-empty text and reasoning is kept exactly (real model: `"\n\nThe exact content…"`).
  - A composite stream (reasoning, text, reasoning, text) is resent as `reasoning_content` = the reasoning deltas concatenated and `content` = the text deltas concatenated, with no separator added (`hp3_chat_composite`).

### 3.5 Messages (VERIFIED, `hp3_messages_*`, `hp1_join_messages`)

| Item | Value |
| --- | --- |
| Headers | `x-api-key: <key>`, `anthropic-version: 2023-06-01`, **`anthropic-beta: interleaved-thinking-2025-05-14`**, `anthropic-dangerous-direct-browser-access: true` |
| Body | `model`, `max_tokens` (= `maxTokens`, 8192), `stream: true`, **`thinking: {type: "enabled", budget_tokens: 7168, display: "summarized"}`** (`budget_tokens` = `maxTokens − 1024` in both runs: 7168, and 3072 at `maxTokens` 4096), `system`, `messages`, `tools` |
| Not sent | `temperature`, `metadata`, `tool_choice`, `output_config`, `stop_sequences`, `top_k` |
| `system` | one text block with `cache_control: {type: "ephemeral"}` |
| `tools` | `{name, description, input_schema, eager_input_streaming: true}` on every tool; `cache_control` on the **last** tool |
| `cache_control` on messages | on the **last block of the last user message** only. It moves every turn, so the previous user message loses it on the resend. Ignoring `cache_control`, every resend is an exact prefix, including after a restart. |
| Tool results | `{"type":"tool_result","tool_use_id","content":<string>,"is_error":false}` |

**Thinking replay** (O-4B-2):

| Stream | `compat.allowEmptySignature` | Resent assistant content |
| --- | --- | --- |
| `thinking` with `signature: ""` (no `signature_delta`) | unset (default `false`) | **`{"type":"text","text":<thinking>}`** then the text block: thinking **demoted to text** |
| same | `true` | `{"type":"thinking","thinking":…,"signature":""}`: replayed as thinking |
| `thinking` + `signature_delta` `"c2lnLTE="` | unset | `{"type":"thinking",…,"signature":"c2lnLTE="}`: replayed verbatim |
| LM Studio `qwen36` (`thinking` block with no signature field) | unset | demoted to text (`mbp/mbp_messages_tool_loop`) |
| Composite (thinking, text, thinking, text) | `true` | four blocks in stream order, exact (`hp3_messages_composite`) |

### 3.6 Real model through the passthrough (VERIFIED, `mbp/`)

`palimnesis serve --passthrough --upstream http://192.168.1.8:8080` relayed both protocols to LM Studio (`qwen36`; `qwen3.8-27b` could not load: "insufficient system resources"). **LM Studio serves `/v1/messages?beta=true`** with Anthropic events (`message_start`, `content_block_*`, `message_delta`, `message_stop`; no `ping`). Both tool loops completed (read `notes.txt`, answer, second turn), and each Chat resend was a byte-equal prefix of the next. Captures are exact request and response bodies (authorization redacted by the proxy).

## HP4 Timeouts and retries

### 4.1 Timers (VERIFIED with `httpIdleTimeoutMs: 5000`)

| Run | Behaviour |
| --- | --- |
| `hp4_header_delay8_then_ok_{chat,messages}` | Client gave up at **5.3 s** waiting for the status line; error `Request timed out.`; agent retry after 0.5 s; success |
| `hp4_idle_after_start_then_ok_*`, `hp4_idle_after_text_then_ok_*` | Client closed ~5 s after the last byte; error `terminated`; agent retry; success |
| `hp4_comments_12s_*` (`: keep-alive` every 2 s for 12 s **before** the first event) | One request, success |
| `hp4_comments_after_start_12s_*` (comments after the first event) | One request, success |
| `hp4_pings_after_start_12s_messages`, `hp4_pings_before_start_12s_messages` (`event: ping` every 2 s) | One request, success |
| `hp4_finish_no_done` | `[DONE]` not required (stop with `finish_reason` + usage, then EOF) |

- One setting, `httpIdleTimeoutMs` (default **300 000 ms**, `0`/`"disabled"` disables), is both the header wait and the body read-idle timer (SOURCE: undici `headersTimeout` and `bodyTimeout` in `core/http-dispatcher.js`).
- **SSE comments and `event: ping` both reset the read-idle timer, on both protocols, before or after the first event.** The timer is byte-level.
- Response headers must arrive within `httpIdleTimeoutMs`; nothing sent before headers can extend it.
- No whole-request deadline was observed over 12 s of keepalives; its absence over longer spans is UNVERIFIED.

### 4.2 Agent retry triggers (VERIFIED; `retry.baseDelayMs` 500 unless noted)

The agent retry (on by default, `maxRetries: 3`) classifies by regex over the error message (`pi-ai/dist/utils/retry.js`, SOURCE). Pi's message for an HTTP error is `<status>: <body>`.

| Run | Attempts | Retried? |
| --- | --- | --- |
| `hp4_s500` | 4 (gaps 0.5, 1.0, 2.0 s) | yes, then `stop=error` |
| `hp4_s500_default_delay` (default `baseDelayMs` 2000) | 4 (gaps **2.0, 4.0, 8.0 s**) | yes |
| `hp4_s429_then_ok` | 2 | yes |
| `hp4_s429_ra7_then_ok` (`retry-after: 7`) | 2, gap **0.5 s** | yes; **`retry-after` ignored** by the agent retry |
| `hp4_s503_noretry_then_ok` (503 + `x-should-retry: false`) | 2 | **yes: `x-should-retry` ignored** by the agent retry |
| `hp4_s409_then_ok`, `hp4_s409_shouldretry_then_ok` (+ `x-should-retry: true`), `hp4_s409_divergence_then_ok` | 1 | no |
| `hp4_s400_then_ok` | 1 | no |
| `hp4_role_only_eof_then_ok` (role chunk, EOF) | 2 | yes (`Stream ended without finish_reason`) |
| `hp4_partial_length` (`finish_reason: length`) | 1 | no; `stop=length`, no continuation |

**Provider retry** (`retry.provider.maxRetries`, default 0, only before response headers):
- `hp4_provider_retry_429` (agent retry off, provider retries 2): second attempt after **7.02 s**, so the provider retry honours `retry-after` (VERIFIED).
- `hp4_provider_retry_409_noretry` (409 + `x-should-retry: false`): 1 attempt (VERIFIED). Whether the provider retry retries a 409 with `x-should-retry: true` is UNVERIFIED (the 1.4.0 notes say yes).

### 4.3 What follows a partial stream (O-4B-5; VERIFIED, both protocols, retry on and off)

Each run: turn 1's first attempt streams reasoning and text, then fails; every later attempt is a normal answer; then a second prompt.

| Failure (runs `hp4_partial_*`) | `retry.enabled: true` | `retry.enabled: false` |
| --- | --- | --- |
| Clean EOF (`…_eof_…`) | retry resends **the same prefix**, partial omitted; then turn 2 | no retry; turn 2 = prefix + **new user message**, partial omitted |
| Reset (`…_abort_…`) | same, error `terminated` | same as left, without retry |
| In-stream error `palimnesis: upstream stream failed` (`…_error_…`) | **no retry** (wording matches no retry pattern); turn 2 = prefix + new user message | same |
| Same + `x-should-retry: false` (`…_error_noretry_…`) | same as previous row | same |
| Text + half a tool call + in-stream error (`…_tool_error_…`) | no retry; partial text and call omitted | same |

- **Pi never resends a failed partial.** An assistant message that ended with `stopReason: "error"` is left out of every later request, with retries on or off, on Chat and Messages. Turn 2 then has two consecutive user messages (the failed turn's prompt and the new one).
- With retries on, a retryable failure (EOF, reset, timeout, 5xx, 429) is retried by resending the prefix the failed attempt was sent with.
- On Messages the error message Pi classifies is the whole `event: error` payload (`{"type": "error", "error": {"type": "api_error", …}}`), so an error `type` such as `overloaded_error` would match `overloaded` and be retried (SOURCE inference; `api_error` was not retried, VERIFIED).
- Wording matters: a proxy in-stream error containing any retryable phrase (`timeout`, `terminated`, `overloaded`, `server error`, `internal error`, `connection lost`, `ended without`, `rate limit`, `500`/`502`/`503`/`504`, …) **will** be agent-retried; `x-should-retry` cannot prevent it.

## HP5 Compaction (VERIFIED, `hp5_*`, `keepRecentTokens: 10` so a compaction has something to summarize)

| Run | `compaction.enabled` | Trigger | Result |
| --- | --- | --- | --- |
| `hp5_threshold_on` | true | turn 2 reports 30 000 prompt tokens (> 32768 − 16384) | `compaction_start reason=threshold`; a summarizer request (2 messages); turn 3 resent on the compacted context |
| `hp5_threshold_off` | **false** | same | no compaction; every resend is an exact prefix |
| `hp5_overflow_on` | true | turn 3 gets 400 `the request exceeds the available context size…` | `compaction_start reason=overflow`, summarizer request, then the turn is retried on the compacted context |
| `hp5_overflow_off` | **false** | same | the 400 surfaces once (`stop=error`), **not retried**, no compaction; turn 4 = prefix + the failed prompt + the new prompt |

With the default `keepRecentTokens` (20000) a short session reports `Nothing to compact (session too small)`, which hides whether compaction is enabled; a disable check needs a session longer than `keepRecentTokens`.

**Manual `/compact`** (`hp5_manual_compact`, RPC `compact`, works with `compaction.enabled: false`). Request shape: same URL, same headers, same body fields (`store`, `max_completion_tokens`, `reasoning_effort`), `messages` = `[{developer: "You are a context summarization assistant…"}, {user: [{text: "<conversation>\n[User]: …\n</conversation>\n\n…structured summary…"}]}]`, **no `tools`**. The next request starts over: developer prompt, then a user message carrying the summary, then the kept messages and the new prompt. For Palimnesis this is a divergence on the same session (S8).

**Branch summary** (`hp2_tree_summarize`): same pattern with "Create a structured summary of this conversation branch…"; disabled from the UI by `branchSummary.skipPrompt: true` (SOURCE).

## HP6 Fixed input F and the transcript gate

### F (VERIFIED, `eval/probes/pi_count_f.py` over `hp6_default_tools`)

Counted with the pinned Strata template and tokenizer (`palimnesis.upstreams.strata.tokens`, exact against Strata 19/19, `docs/probes/strata.md` §4), default tools, no context files, Windows cwd:

| Part | Tokens |
| --- | --- |
| Whole first request (`Reply with the single word OK.`) | 1,554 |
| User turn alone | 17 |
| **F = system prompt + tools** | **1,537** |
| of which tools (`read`, `bash`, `edit`, `write`) | 880 |
| of which system prompt (2,475 chars) | 657 |

- A leading `developer` message renders **identically** to `system` under the pinned template (`developer_renders_as_system: true`).
- F grows with the cwd path, `AGENTS.md`/`CLAUDE.md` context files, skills and extra tools; a Linux host gets a different prompt (UNVERIFIED by how much). At 32K, F ≈ 1.5K is far under the D79 floor limit (18,176).
- Cross-check: LM Studio `qwen36` reported `prompt_tokens: 1603` for the same first request (different template).

### Gate (VERIFIED on Windows, `hp6_gate`)

In `--mode json` with `--tools read,grep,bash,ls,find`, scripted calls to `read`, `grep`, `bash` (`grep -rn`), `ls` and `find` on a folder **outside** the working folder all returned the file's content, with **no prompt** and no permission error. Pi has no permission system (its `docs/security.md`). The default tool set is `read`, `bash`, `edit`, `write`; `grep`, `find` and `ls` must be enabled (`--tools` or `defaultTools`) if the a3 addendum names them.

## HP7 Non-interactive driving and import (VERIFIED)

- `pi -p "…"` (final text on stdout), `pi --mode json "…"` (JSONL events, then exit) and `pi --mode rpc` (JSONL commands on stdin) all run with no TTY. RPC covers `prompt`, `new_session`, `switch_session`, `fork`, `clone`, `compact`, `get_state`, `get_messages`, `get_entries`, `set_auto_retry`, `set_auto_compaction`. An extension command sent as `prompt` returns `disposition: "handled"` and starts no run.
- `--no-session`: no session file written (`hp7_print_mode`).
- **Import** (`hp7_import`): a hand-written JSONL with only a `session` header (version 3, `id`, `cwd`) and two `message` entries (user content as text parts; assistant with `api`, `provider`, `model`, `usage`, `stopReason`) opened with `--session <path>` resent that history verbatim (`user`, `assistant` string) after a fresh developer prompt. Pi **appends to the imported file** (a `system` entry and the new turn), so drivers should import a copy. `--session-id <id>` chooses the id of a new session.
- Sessions are stored at `<agent dir>/sessions/--<cwd slug>--/<timestamp>_<id>.jsonl`; `PI_CODING_AGENT_SESSION_DIR` or `--session-dir` relocate them.
- On Windows, RPC processes that ran a tool often exited with status `0xC0000409` after stdin closed, after all work had finished and been logged. Drivers should judge success by `agent_settled` and the server log, not the exit code.

## Changes from the Pi 1.4.0 static notes

- Version 1.5.0. `User-Agent: pi/1.5.0`.
- **`compat.supportsStore` exists**; `supportsDeveloperRole`, `supportsReasoningEffort` and `maxTokensField` work as documented.
- User content is always an array of text parts on Chat (not noted before).
- Assistant `content` is `null` for tool-call-only turns, and whitespace-only text/reasoning is dropped on resend; tool-call arguments are re-serialized compactly.
- The system prompt and tools are persisted as a `system` session entry and replayed after restart.
- Messages adds `thinking.display: "summarized"` and `anthropic-beta: interleaved-thinking-2025-05-14`; `budget_tokens` = `maxTokens − 1024` in both runs.
- The agent retry **ignores `x-should-retry` and `retry-after`**, and does not retry 409; the 1.4.0 list of 409/`x-should-retry`/`retry-after` applies to the provider retry only (default off).
- **A failed partial is omitted from later requests even with `retry.enabled: false`.** The notes described the omission only as part of the retry.
- `--session-id` lets a driver choose Pi's session id.
- Telemetry: `enableInstallTelemetry` (default true) and `PI_TELEMETRY`; built-in extensions `mcp`, `llama.cpp`, `codemode`, `tool-search` load by default.
- A Messages `baseUrl` ending in `/v1` doubles it (`/v1/v1/messages`).

## Evidence for the decisions

- **O-4B-4 (association).** The header extension works on both protocols and follows Pi's own session id through `/new`, `/fork`, `/clone`, `/resume` and restarts (VERIFIED). Consequences for the archive: `/clone` opens a new session whose first request already carries history; `/tree` keeps the id and truncates history (divergence, 409); branch summaries and `/compact` are side calls on the same session id and diverge too. No fallback (`PI_CODING_AGENT_DIR` per session) is needed; `--session-id <palimnesis id>` additionally lets a driver make the two ids equal.
- **O-4B-5 (partial omitted from the resend).** Pi omits a failed partial from every later request **even with retries off**, on both protocols, whatever ended the stream (EOF, reset, in-stream error, with or without `x-should-retry: false`). By the plan's own rule this selects **(b)**: with (a), one upstream failure would make every later turn in the session diverge. The proxy's current wording `palimnesis: upstream stream failed` is not agent-retried, so with (b) a retry occurs only for transport failures and timeouts.
- **O-4B-9 (developer, store).** Both flags exist and work: `compat: {supportsDeveloperRole: false, supportsStore: false}` gives `system` and no `store` (VERIFIED). The fallback is not needed. Still needed in the Chat subset regardless of flags: **user content as an array of text parts** (no flag), `content: null` on tool-call-only assistant turns, `reasoning_effort` (or `supportsReasoningEffort: false`), `max_completion_tokens` (or `maxTokensField: "max_tokens"`), and `stream_options.include_usage`. A `developer` message renders exactly like `system` under the pinned template, should the fallback ever be wanted.
- **O-4B-2 (empty signatures).** Pi replays `""` as thinking **only with `compat.allowEmptySignature: true`**; by default it demotes the thinking to a text block, which would diverge from an archived thinking block. Non-empty signatures are replayed verbatim. So (a) is viable for Pi only with that flag in the adapter config; (b) works with Pi's defaults.
- **O-4B-7 (keepalive).** Pi's only read timer is `httpIdleTimeoutMs` (300 s default), reset by comments and by `ping`; response headers must arrive within the same 300 s. K = 15 s and H = 10 s are well inside it.

## Recommended Pi settings for Palimnesis

`models.json` (adapter config; Chat shown, the Strata model id and the token sizes are the deployment's):

```json
{
  "providers": {
    "palimnesis": {
      "baseUrl": "http://127.0.0.1:9000/v1",
      "api": "openai-completions",
      "apiKey": "unused",
      "compat": { "supportsDeveloperRole": false, "supportsStore": false },
      "models": [
        { "id": "<strata model id>", "reasoning": true,
          "contextWindow": 1000000, "maxTokens": 8192 }
      ]
    }
  }
}
```

- With the header extension the base URL needs no `/s/<id>`. Without it, use `…/s/<id>/v1` (Chat) or `…/s/<id>` (Messages, `api: "anthropic-messages"`, never ending in `/v1`).
- For Messages add `"compat": {"allowEmptySignature": true}` if O-4B-2 chooses (a).
- `contextWindow` far above any conversation keeps `max_completion_tokens` constant and keeps Pi's own context accounting from mattering; the proxy enforces the real budget.

`settings.json`:

```json
{
  "compaction": { "enabled": false },
  "branchSummary": { "skipPrompt": true },
  "cacheWarming": "off",
  "enableInstallTelemetry": false,
  "retry": { "enabled": true, "provider": { "maxRetries": 0 } }
}
```

- `retry.enabled: true` is safe under O-4B-5 (b); under (a), set it to `false` (Pi still omits the partial, so the session diverges either way). Evaluation drivers may set it `false` so that every failure is visible.
- Keep `httpIdleTimeoutMs` at its default (300 000) or above 4 × K.
- Keep Palimnesis's in-stream error wording free of Pi's retryable phrases (§4.3).
- Extension `integrations/pi/`: the `before_provider_headers` hook above. Pi's docs say `session_before_compact` and `session_before_tree` handlers can cancel `/compact` and `/tree` summaries (SOURCE; cancelling was not exercised).

## Not verified

- The interactive `/tree` selector and `/resume` picker (driven here through `ctx.navigateTree` and RPC `switch_session`).
- Cancelling `/compact` or `/tree` from an extension.
- Any behaviour on Linux or on the evaluation host; Strata itself (pythia was not used).
- A whole-request deadline over long keepalive spans; provider retry of a 409 with `x-should-retry: true`.
- Cache warming with `cacheWarming` left on (it needs a model with `promptCache` lifetimes and cost data; left off in every run).
