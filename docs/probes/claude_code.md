# Claude Code 2.1.318 probe: HC1–HC9

Nov 5, 2026 · Phase 4B S0, captured fixtures

## What this is

This probe records how Claude Code talks to a custom Anthropic Messages base URL: URL joining, every request it makes, body shapes, thinking replay, timeouts and retries, compaction, resume, the transcript gate and non-interactive driving. The plan (`docs/plan/phases/phase4b.md` §1, table HC1–HC9) requires these facts from fixtures, not from the 2026-10-24 static notes (`docs/probes/harnesses.md`, Claude Code 2.1.310). It confirms, corrects and extends those notes.

Every result comes from a real `claude` 2.1.318 talking to a deterministic fake Messages server on loopback. No real model or provider was involved.

Markers:
- **VERIFIED**: observed in a fixture.
- **STATIC**: read in the 2.1.318 bundle strings, not exercised.
- **UNVERIFIED**: neither.

## Version

`claude --version` → `2.1.318 (Claude Code)`, `/c/Users/<user>/.local/bin/claude.exe` (Bun single-file binary). The plan assumed 2.1.310. Headers report `User-Agent: claude-cli/2.1.318 (external, sdk-cli)` in `-p` mode and `(external, cli)` interactively, `X-Stainless-Package-Version: 0.128.0` (same SDK as 2.1.310), `X-Stainless-Runtime: node`, `X-Stainless-Runtime-Version: v26.12.1`.

## Setup

**Fault server.** `eval/probes/cc_fault_server.py` is a raw asyncio HTTP/1.1 server that speaks Messages SSE (`message_start`, `content_block_start/delta/stop`, `message_delta`, `message_stop`, `ping`, `error`) and logs every request (method, path, query, headers with `x-api-key`/`authorization` redacted, full body) to JSONL.
- Each `POST */v1/messages` carrying `tools` is a main attempt, answered by the scenario's step N (the last step repeats). Requests without tools always get a well-formed answer and consume no step, so a side call could not shift a fault scenario. None occurred.
- A responder reads the request: `@@tool NAME {json}` directives in the user text drive a tool loop, one call per response; `--think`/`--sig none|empty|opaque` add a thinking block and choose how it is signed; `--reject-system-role` and `--reject-empty-signature` reproduce upstream 400s.
- `--usage-input N` sets the reported `input_tokens` (Claude Code's context estimate comes from it; see HC6).

**Driver.** `eval/probes/cc_probe.py RUN…` runs named runs: each gets a fresh fault server, a sentinel proxy and an isolated profile, then one or more `claude -p … --output-format stream-json --verbose --model qwen3.8-27b` invocations (`--continue`, `--resume <id>` and stream-json stdin supported). `eval/probes/cc_probe_summary.py` prints requests, body facts, message diffs between consecutive main requests (`--diff`) and one-line fault rows (`--matrix`). `eval/probes/cc_fixed_tokens.py` counts F with the pinned Strata counter. `eval/probes/cc_tui_probe.py` drives the interactive TUI through ConPTY (`uv run --with pywinpty`).

**Fixtures.** `eval/probes/fixtures/claude-code-2.1.318/<run>/`: `server.jsonl`, `meta.json`, `claude.<i>.stdout.jsonl`, `claude.<i>.stderr.txt`, `sentinel.jsonl`. Credentials were redacted at capture; `metadata.user_id` device ids and user paths are redacted. In most runs `system`, `tools` and mid-conversation system text are replaced by `{sha256_16, bytes}`. Full bodies are kept once in the shape runs `default_tool`, `candidate_tool`, `candidate_trim`, `tui_candidate`, `compact_auto_off` and `sysrole_reject_anthropic`.

### Isolation (VERIFIED)

The child's environment is built from an OS allowlist, never inherited. The caller's own `CLAUDECODE`, `CLAUDE_CODE_*` and messaging-socket variables never reach it.

| Setting | Reason |
| --- | --- |
| `CLAUDE_CONFIG_DIR=<run>/config` | Settings, `.claude.json`, credentials and session transcripts (`projects/<cwd-slug>/<session>.jsonl`) |
| `HOME`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `TEMP`, `TMP` under the run | No profile paths |
| `ANTHROPIC_API_KEY=<dummy>`, `ANTHROPIC_BASE_URL=http://127.0.0.1:<port>/s/probe-<run>`, `ANTHROPIC_MODEL=qwen3.8-27b` | Loopback only |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `DISABLE_TELEMETRY=1`, `DISABLE_ERROR_REPORTING=1`, `DISABLE_AUTOUPDATER=1`, `DISABLE_GROWTHBOOK=1` | No side traffic |
| `HTTP(S)_PROXY` → a local sentinel that logs and refuses (`NO_PROXY=127.0.0.1,localhost`) | Any attempt to reach another host is recorded and fails |
| Working directory `C:\ccprobe\<run>\work` | **Outside the user profile** (see the incident below) |

**Isolation incident (first run, fixed).** The first scratch root was under `C:\Users\<user>\AppData\Local\Temp\…`. Claude Code walks up from the cwd for project `CLAUDE.md` files and `.claude/skills`, and reached `C:\Users\<user>\.claude\`. The user's global `CLAUDE.md` and skill names went into that one request body as "project instructions", on loopback only. Nothing was written to `~/.claude` (no project folder for the run was created there). The log was deleted and every later run used `C:\ccprobe`. **Consequence for Palimnesis evaluation drivers:** a Claude Code work dir must not sit under a folder whose ancestors contain `.claude/`, or project-memory and skill loading must be switched off (`CLAUDE_CODE_DISABLE_CLAUDE_MDS`, STATIC).

**Egress.**
- `-p` mode: 0 sentinel hits in all 117 `-p` runs. `Get-NetTCPConnection` polling of two long-lived `-p` processes for 90 s showed loopback connections only (4 per process).
- **Interactive mode (one run, `tui_candidate`):** at startup the TUI sent `CONNECT downloads.claude.ai:443` and `CONNECT github.com:443`, despite the switches above. The sentinel refused both, so nothing left the machine.
  - The bundle references `downloads.claude.ai/claude-code-releases/plugins/claude-plugins-official…` and `downloads.claude.ai/model-catalog/v1/catalog.json`, plus the switches `CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL` and `CLAUDE_CODE_MODEL_CATALOG_URL` (STATIC).
  - Interactive probing was stopped there, per the S0 brief.
  - `cc_probe.py`'s safety env now also sets `CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL=1`. It was added after the recorded runs, and its effect is UNVERIFIED.

**Real model.** mbp's LM Studio serves `/v1/messages` with an Anthropic envelope. `qwen3.8-27b` fails to load there ("insufficient system resources"); `qwen36` (loaded) answered a minimal Messages request. It was not used. Every HC question is about the shapes Claude Code sends and how it reacts, which the fake server covers.

### Envs used

- **default**: only the isolation/traffic switches above.
- **candidate** (`CANDIDATE_ENV` in `cc_probe.py`): default plus
  - `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`
  - `CLAUDE_CODE_ATTRIBUTION_HEADER=0`
  - `CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK=1`
  - `CLAUDE_CODE_MAX_CONTEXT_TOKENS=32768`
  - `DISABLE_AUTO_COMPACT=1`
  - `CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1`
  - `CLAUDE_CODE_ENABLE_AWAY_SUMMARY=0`
  - `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`
  - `CLAUDE_CODE_FORK_SUBAGENT=0`
  - `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`
  - `CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION=false`
- **fb_\***: candidate without `DISABLE_NONSTREAMING_FALLBACK`.

## HC1 URL joining (VERIFIED)

| Call | Observed |
| --- | --- |
| Messages | Base `http://127.0.0.1:P/s/probe-x` → `POST /s/probe-x/v1/messages?beta=true` in every run, both modes. The prefix is preserved. |
| `HEAD /api/hello` | **Never sent** in any run, with or without the sentinel proxy, `-p` or interactive. STATIC gate: skipped when `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` (the "essential-traffic" mode), any `HTTP(S)_PROXY`, a Unix socket or a client cert is set, or the provider is not first-party. The call is `.catch(()=>{})` with a 10 s abort, so a 404 is ignored. |
| `count_tokens` | **Never sent** (`-p`, interactive, compaction, /compact). STATIC: `POST /v1/messages/count_tokens?beta=true`, adding beta `token-counting-2024-11-01`, `maxRetries: 1`; the caller returns `null` on error and falls back to an estimate. |
| `/v1/models` | `GET /s/<id>/v1/models?limit=1000` once at start, before the first message, only with `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` (`default_ok_hello200_ct200_models`). Absent otherwise. |

## HC2 Traffic inventory

| Phase | `-p`, default env | `-p`, candidate env | Interactive TUI, candidate env (`tui_candidate`) |
| --- | --- | --- | --- |
| Start | nothing before the first message | nothing | nothing on the base URL; 2 refused `CONNECT`s (Egress above) |
| One turn | 1 streaming `/v1/messages` | same | same |
| Tool loop (Bash then Read) | 3 streaming, each with the full tool list | same | same |
| Idle | 150 s after turn 3 (`*_stdin_idle`): **none** | none | 20 s: none |
| `/clear` | n/a in `-p` | n/a | none at `/clear`; the next prompt is a fresh conversation (`common=0`) with a **new** `X-Claude-Code-Session-Id` and `metadata.user_id.session_id`, same base URL |
| Exit | none | none | `/exit`: none |

- **No title, `quota_check`, away summary, memory, prompt-suggestion or other side query was seen in any run.** Every `/v1/messages` carried `tools` and `stream: true`.
- **Non-streaming requests:** only the non-streaming fallback (HC5), and only when `CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK` is unset.
- **UNVERIFIED:** the interactive default env, the away summary after a long unfocused idle, and `/rewind`. All are interactive-only and were not run after the egress stop.

**Headers** (every request): `x-api-key`, `anthropic-version: 2023-06-01`, `anthropic-beta`, `anthropic-dangerous-direct-browser-access: true`, `x-app: cli`, `X-Claude-Code-Session-Id`, `User-Agent`, `X-Stainless-{Arch,Lang,OS,Package-Version,Retry-Count,Runtime,Runtime-Version,Timeout}`.
- No idempotency key.
- `X-Stainless-Retry-Count` is `0` on every attempt, including 11 attempts of `f_s500_default_retries`.
- `X-Stainless-Timeout` is `600` for streaming and `300` for the non-streaming fallback.
- With `CLAUDE_CODE_GATEWAY_HINT_HEADERS=1`: `x-claude-code-request-class: main`, `x-claude-code-prompt-id` (constant across a tool loop) and `x-claude-code-prev-tool-durations` (`Bash=548`; varies) (`candidate_hints`).

## HC3 Shapes (VERIFIED)

| Field | default env | candidate env |
| --- | --- | --- |
| `anthropic-beta` | `claude-code-20250219, interleaved-thinking-2025-05-14, context-management-2025-06-27, mid-conversation-tool-changes-2026-07-01, thinking-token-count-2026-05-13, advanced-tool-use-2025-11-20, effort-2025-11-24, thinking-display-updates-2026-08-18` | `claude-code-20250219, interleaved-thinking-2025-05-14, effort-2025-11-24` |
| top-level keys | `model, max_tokens, stream, system, messages, tools, thinking, output_config, metadata, context_management` | same without `context_management` |
| `thinking` | `{"type":"adaptive","display":"updates"}` | `{"type":"adaptive"}` |
| `output_config` | `{"effort":"high"}` | same |
| `context_management` | `{"edits":[{"type":"clear_thinking_20251015","keep":"all"}]}` | absent |
| `max_tokens` | 32000 | 32000; `CLAUDE_CODE_MAX_OUTPUT_TOKENS=4096` → 4096 |
| tools (`-p`) | 14: deferred loading (`ToolSearch`, a `DeferredToolPlaceholder` with `defer_loading`) | **23**, all loaded; tool keys `name, description, input_schema` only |
| tools (interactive) | not run | **26** (adds `AskUserQuestion`, `EnterPlanMode`, `ExitPlanMode`) |
| `system` | `[billing line, "You are a Claude agent, built on Anthropic's Claude Agent SDK." (cc), 5.5 KB prompt (cc)]` | `[SDK line (cc), 3.4 KB prompt (cc)]`. Interactive: `"You are Claude Code, Anthropic's official CLI for Claude."` + 3.7 KB |
| `metadata.user_id` | JSON string `{"device_id": <64 hex, per config dir>, "account_uuid": "", "session_id": <= X-Claude-Code-Session-Id>}` | same |

- **Billing line.** `system[0]` = `x-anthropic-billing-header: cc_version=2.1.318.<3 hex>; cc_entrypoint=sdk-cli;`.
  - The 3-hex suffix depends on the session's first prompt: `cc7` for "Reply with the single word OK." in three separate sessions, `0eb` for the tool prompt.
  - It is constant across a session's turns and across `--continue` (`candidate_attr_on`).
  - It does not vary per request, but it does vary per session, so it splits the system prefix between sessions.
  - `CLAUDE_CODE_ATTRIBUTION_HEADER=0` removes the block.
- **Mid-conversation `role: "system"` entries** appear in every env and both modes. `DISABLE_EXPERIMENTAL_BETAS` does not remove them, and no `mid-conversation-system` beta is sent.
  - There is one entry, right after the user message whose turn computed it. Normally that is index 1, giving roles `u s a u …`.
  - Its content is a string of about 8.4 KB (candidate `-p`; 9.5 KB interactive). It holds `# Environment` (cwd, platform, shell, OS), "You are powered by the model …", the deferred-tool list, the agent types, the skills list and "Today's date is …".
  - No further entries appear in later turns of a session (3-turn runs).
  - After `/compact` a new one sits at the tail, after the newest user message. After a `--resume` of a history that never had one (HC9), it is attached after the new user message.
- **`cache_control`.**
  - The system blocks carry ephemeral breakpoints.
  - **One message breakpoint sits on the last block of the last message and moves every request.**
  - A single-text user message is sent as `[{"type":"text","text":…,"cache_control":…}]` while it is last, and as a **plain string** in every later request (`*_stdin_idle`, `resume`: `common=7`, with only that form changed).
  - In the default env, the system entry is a block list with `cache_control` while it is the last message, and a string afterwards.
  - The adapter must therefore treat `"x"` and `[{"type":"text","text":"x"}]` as the same content, and ignore `cache_control` (phase4b position 3).
- **F** (`cc_fixed_tokens.py`, pinned counter `c4`; leading system + tools in Strata's bare tool form, no turns):

| Configuration | tools | F (system+tools) | mid-system entry (if merged) | F + 14,592 vs 32,768 |
| --- | --- | --- | --- | --- |
| candidate, `-p` (`candidate_ok`) | 23 | **16,024** | +1,971 | fits, 2,152 spare (181 with the entry) |
| candidate, interactive (`tui_candidate`) | 26 | **18,812** | +2,221 | **does not fit, −636** |
| candidate + 17 tools denied, `-p` (`candidate_trim`, `candidate_trim_settings`) | 6 (Bash, Edit, Glob, Grep, Read, Write) | **3,784** | +204 | fits, 14,392 spare |
| default, `-p` (deferred tools; needs tool search) | 14 | 9,905 | +2,058 | n/a (betas Palimnesis rejects) |

The largest tools (tokens) are Monitor 1,937, SendMessage 1,368, Workflow 1,300, CronCreate 1,233, ScheduleWakeup 1,201, Agent 964, EnterWorktree 952, Grep 848, Bash 824 and Read 541. `--disallowedTools` and `permissions.deny` in settings both remove the tools from the request and shrink the system entry from 8.4 KB to 0.8 KB.

## HC4 Thinking (VERIFIED, `think_sig_*`, `think_only_tail`, `resume`)

| Stream | Replay in later requests (tool loop, `--continue`, `--resume`) |
| --- | --- |
| No `signature_delta`; `content_block_start` carries `signature: ""` (Strata's shape) | `{"type":"thinking","thinking":…,"signature":""}`, kept in place before the `tool_use`/text |
| `signature_delta` with `""` | same |
| `signature_delta` with an opaque base64 string | replayed byte-exact |

- **Unsigned thinking is replayed as thinking, not demoted or dropped,** including after a process restart, from the session file.
- **Signature-error strip path** (`think_sig_none_reject`).
  - A 400 `messages.N.content.0: Invalid \`signature\` in \`thinking\` block` is followed at once (under 0.02 s) by the same request with **every** thinking block removed.
  - Stripped blocks stay stripped, also in the session file.
  - New thinking blocks are replayed again, so each later turn costs one 400 and one immediate retry.
- **Thinking-only response** (`think_only_tail`).
  - Claude Code at once re-sent the request with the last user message changed: `"\n"` is appended to its text and a block `[Your previous response had no visible output. Please continue and produce a user-visible response.]` is added. The thinking-only turn is dropped.
  - If the retry is also thinking-only, the next process (`--continue`) replays that turn as assistant text `"No response requested."`, without the nudge.
  - For the archive this is a tail rewrite, not an append.

## HC5 Timeouts and retries (VERIFIED; `f_*` = candidate, `fb_*` = fallback enabled; `CLAUDE_CODE_MAX_RETRIES=3` unless noted)

**Timers.**

| Run | Result |
| --- | --- |
| `f_header_timeout5s` (`API_TIMEOUT_MS=5000`, status line delayed 8 s) | Client closed at **5.0 s**, retried after 0.53 s; attempt 2 OK |
| `f_header_delay8_default` | 8 s header wait accepted |
| `wd_default_idle_after_start_then_ok` (`message_start`, then silence) | **Killed at 300.0 s**: `API Error: Stream idle timeout - no chunks received`, no retry with fallback off |
| `wd_default_start_comments_330` / `wd_default_comments_330` (`: keep-alive` every 15 s for 330 s, after / before `message_start`) | **Survived**; answer at 331 s, exit 0 |
| `wd_default_start_pings_330` / `wd_default_pings_330` (`event: ping` every 15 s for 330 s) | **Survived**, exit 0 |
| `wd_default_start_comments_660` / `wd_default_start_pings_660` (every 15 s for **660 s** after `message_start`) | **Both survived**; answer at 660.9 s, exit 0. So comments alone keep a stream alive past Palimnesis's 600 s D. |
| `wd15_*` (`CLAUDE_STREAM_IDLE_TIMEOUT_MS` and `CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS` = 15000) | Silence after `message_start`: killed at 15.0 s, no retry (`fb`: then a non-streaming resend). Silence after headers only: killed at 15.0 s and **retried as a stream**. Comments or pings every 5 s for 40 s: survived. |
| `wdby15_*` (byte watchdog 15 s only) | Same as `wd15_*`: the 15 s kill is the byte watchdog, and comments reset it |
| `wdev15_*` (event watchdog 15 s only) | Silence after `message_start` was **not** killed at 15 s; the event setting appears clamped (≥300 s in the static notes) |
| `ping` before `message_start` (`f_ok_ping_first`) | Accepted |

**Status codes** (identical in `f_` and `fb_`):

| Response | Attempts | Gaps (s) | Outcome |
| --- | --- | --- | --- |
| 500 then OK | 2 | 0.56 | OK |
| 500 every attempt, default retries (`f_s500_default_retries`) | **11** | 0.53, 1.06, 2.03, 4.34, 9.06, 19.03, 35.6, 36.6, 35.9, 39.3 (≈184 s) | `API Error: 500 …`, exit 1 |
| 500 + `x-should-retry: false` | **1** | — | error |
| 400 + `x-should-retry: true` | 2 | 0.53 | OK (the header wins) |
| 409 | 4 | 0.56, 1.03, 2.23 | error |
| 409 + `x-should-retry: false` | 1 | — | error |
| 429 + `retry-after: 5` | 2 | **5.01** | OK |
| 429 + `retry-after: 90` | **1** | — | `API Error: Request rejected (429) · queue full` at once |
| 429 + `x-should-retry: false` | 1 | — | error |
| 529 `overloaded_error` | 4 | 0.62, 1.05, 2.34 | error |
| `event: error` `overloaded_error` after `message_start` | 2 (stream) | 0.61 | OK |

**Stream failures.** "Fallback off" = `CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK=1`.

| Failure | Fallback off (`f_`) | Fallback on (`fb_`) |
| --- | --- | --- |
| `message_start`, clean EOF (± `x-should-retry: false`) | **1 attempt**, `API Error: Stream ended without receiving any events` | **non-streaming resend** after 0.02 s, identical body except `stream: false` |
| `message_start`, RST | streaming retry, identical | same |
| `message_start` + `event: error` `api_error` (± `x-should-retry: false`) | **1 attempt**, `API Error: upstream failed`, exit 1 | **non-streaming resend**; `x-should-retry: false` does not stop it |
| Open text block (no `content_block_stop`) + EOF or RST, **even with `x-should-retry: false`** | streaming retry, identical body; the partial is discarded | same |
| Open text block + `event: error` (± header) | **1 attempt**, error, exit 1 | non-streaming resend |
| **A completed content block**, then EOF, RST or `event: error`, with or without `x-should-retry: false` | **Continue**: after 0.02 s (1.0 s after RST) the next request carries the partial assistant message plus a user message `Your response above was cut off mid-stream. Resume directly from where it stops — no apology, no recap. If none of it survived, answer the request from the start.` | same |
| `stop_reason: max_tokens` | Up to 3 continuations: assistant text plus user `Output token limit hit. Resume directly — no apology, no recap of what you were doing. Pick up mid-thought if that is where the cut happened. Break remaining work into smaller pieces.`; then `API Error: Claude's response exceeded the 32000 output token maximum…`, exit 1 | same |

Retries reuse the connection after HTTP errors and open a new one after an RST or a client timeout.

## HC6 Compaction and the blocking limit (VERIFIED)

**Client blocking limit.** Before sending, Claude Code compares the last reported usage, plus new content, with `window − min(max_tokens, 20000) − 3000`. Above it, the turn is refused locally with `Prompt is too long` and nothing is sent.

| Window | `max_tokens` | Reported `input_tokens` | Turn 2 |
| --- | --- | --- | --- |
| 32768 | 32000 | 9,000 | sent |
| 32768 | 32000 | 10,500 / 13,000 / 20,000 / 30,000 | **refused** (limit ≈ 9,768) |
| 32768 | 4096 (`CLAUDE_CODE_MAX_OUTPUT_TOKENS`) | 20,000 | sent |
| 32768 | 4096 | 26,000 / 30,000 | **refused** (limit ≈ 25,672) |
| 1,000,000 | 32000 | 30,000 / 250,000 | sent |

A Palimnesis bounded view reports up to ~32K of usage. With `CLAUDE_CODE_MAX_CONTEXT_TOKENS=32768` and the default `max_tokens`, turn 2 of any real session would be refused client-side. **Set it to 1,000,000.**

**Compaction.**
- `DISABLE_COMPACT=1` (`compact_off`): `/compact` prints `/compact isn't available in this environment.` and sends nothing.
- `DISABLE_AUTO_COMPACT=1` (`compact_auto_off`): manual `/compact` works in `-p` (`claude -p "/compact" --continue`).
- **The `/compact` shape (for S8).**
  - It is a **streaming** request with the same `system`, `tools`, `thinking` and `max_tokens`.
  - Its messages are the history up to the last user message, with **the last assistant reply dropped**.
  - That user message gets `"\n"` appended and a second text block `CRITICAL: Respond with TEXT ONLY. Do NOT call any tools. …` (full text in the fixture).
  - With the fake's non-summary answer it was sent twice (0.02 s apart). The probe did not establish why.
  - The next turn starts a new history:
    - user string `This session is being continued from a previous conversation that ran out of context. The summary below covers the earlier portion …`;
    - the kept assistant reply;
    - a user message with reminders, `<local-command-caveat>`, `<command-name>/compact</command-name>`, `<local-command-stdout>Compacted </local-command-stdout>` and the new prompt;
    - a new tail `role: system` entry.
  - To the archive, both requests are divergences.
- **Auto-compaction never fired in `-p`.** With window 32768, `max_tokens` 4096 and reported usage 20,000, which is above the static threshold of about 15,672 and below the blocking limit, the default env sent turn 2 normally, as did `DISABLE_AUTO_COMPACT=1` (`acmp_*`). So `-p` could not tell the two settings apart. Interactive auto-compaction is UNVERIFIED.
- `context_management` is absent under `DISABLE_EXPERIMENTAL_BETAS=1` (HC3).

## HC7 Resume (VERIFIED, `resume`, `candidate_attr_on`)

- **`--continue` and `--resume <id>` resend the prior conversation exactly**, apart from two changes:
  - the formerly last user message changes from a block list to a string;
  - `cache_control` moves.
- That includes the mid-conversation system entry at index 1, `""`-signed thinking blocks, tool calls and results.
- The session id is unchanged.
- **`--resume <id> --fork-session`** resends the same prefix under a **new** session id (`X-Claude-Code-Session-Id` and `metadata.user_id`). It writes a new transcript file.
- With the per-process base URL it arrives at the same Palimnesis session as an extension. Per-process wrappers should start a new Palimnesis session for forks.
- `/rewind`: not driven (interactive only; UNVERIFIED).

## HC8 Transcript gate in `-p` (VERIFIED, `gate_*`)

The prompt made the model Read a file, Grep, and run `grep -rn` through Bash in a directory outside the cwd. There was no permission prompt in any case (`-p` cannot prompt).

| Grant | Read | Grep | Bash `grep -rn` |
| --- | --- | --- | --- |
| none (`gate_none`) | denied (`Claude requested permissions to read from …, but you haven't granted it yet.`) | denied | denied (`may only search … allowed working directories`) |
| `--add-dir <dir>` (`gate_add_dir`) | **ok** | **ok** | **ok** (no `Bash(grep:*)` allow needed) |
| `permissions.additionalDirectories: [<dir>]` in `$CLAUDE_CONFIG_DIR/settings.json` (`gate_settings`) | **ok** | **ok** | **ok** |

Denials come back as `tool_result` with `is_error: true`, and are listed in the result's `permission_denials`.

## HC9 Driving and import (VERIFIED)

**Driving.**
- `claude -p "<prompt>" --output-format stream-json --verbose --model <id>` runs one turn, plus its tool loop, and exits. Close stdin when no input is fed.
- The first line is `{"type":"system","subtype":"init", "session_id", "tools", …}`; the last is `{"type":"result", "is_error", "result", "api_error", "usage", "permission_denials", …}`.
- `--continue` / `--resume <id>` add turns across processes.
- `--input-format stream-json` with `{"type":"user","message":{"role":"user","content":"…"}}` lines on stdin keeps one process for several turns, and exits at stdin EOF (`*_stdin_idle`).
- Tool permission comes from `--allowedTools "Bash(echo:*)" Read`, or settings.
- Every `-p` run logs `[claude-code:unrecognized_model] {"model":"qwen3.8-27b",…}` to stderr. It is harmless.

**History import** (`import_history`).
1. Write `$CLAUDE_CONFIG_DIR/projects/<slug>/<uuid>.jsonl`, where `<slug>` is the cwd with every non-alphanumeric character replaced by `-` (`C:\ccprobe\x\work` → `C--ccprobe-x-work`).
2. Write one JSON line per message: `{parentUuid, isSidechain:false, userType:"external", cwd, sessionId, version, type:"user"|"assistant", uuid, timestamp, message}`. User `message` is `{role, content}`; assistant `message` is a full Messages response object.
3. Run `claude -p "<next>" --resume <uuid>`.

It sent the four imported messages verbatim, then the new user turn and a tail system entry, and appended to the same file.

## Changes from the 2.1.310 static notes (`docs/probes/harnesses.md`)

1. **Side calls:** none observed in `-p` (both envs) or interactively (candidate env): no title, `quota_check`, summaries or memory calls. The only non-streaming request is the fallback resend.
2. **`HEAD /api/hello`** is also skipped under `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` (essential-traffic mode), not only behind a proxy.
3. **Betas** (candidate env) are only `claude-code-20250219, interleaved-thinking-2025-05-14, effort-2025-11-24`. The default env adds `mid-conversation-tool-changes-2026-07-01`, `advanced-tool-use-2025-11-20` and `thinking-display-updates-2026-08-18`. `redact-thinking` and `mid-conversation-system` are not sent.
4. **`context_management`** in the default env is only `clear_thinking_20251015` (`keep: all`), not `clear_tool_uses`.
5. **`thinking`** is `{"type":"adaptive","display":"updates"}` by default. `display` and `context_management` are dropped by `DISABLE_EXPERIMENTAL_BETAS`.
6. **`DISABLE_EXPERIMENTAL_BETAS` also turns off tool deferral,** so all tools load: 14 → 23 in `-p`, raising F.
7. **Billing line:** per session (it follows the first prompt), not per request.
8. **Mid-conversation system entries:** confirmed. The strip path folds them into the **preceding user message** as `<system-reminder>` blocks, triggered by either wording below, and it persists across `--continue`.
9. **Comments reset the watchdog**: a comments-only wait survives 330 s before or after `message_start`, and 660 s after it. The notes inferred that `ping` was needed. Silence is killed at exactly 300 s.
10. **Signature strip** removes thinking only from blocks present at the time. New blocks are replayed and cost another 400 ("for the rest of the session" was wrong).
11. **New behaviour:**
    - Continue after a completed block, which `x-should-retry` cannot stop;
    - the thinking-only nudge;
    - the `max_tokens` continuation, ×3;
    - `retry-after: 90` fails at once;
    - `x-should-retry: true` makes a 400 retryable.
12. **Interactive startup** contacts `downloads.claude.ai` and `github.com` with the documented switches set.

## Evidence for the decisions

- **O-4B-2 (signatures).**
  - Claude Code replays `""`-signed thinking as thinking: no `signature_delta`, or an empty one. That holds in tool loops and after `--continue`/`--resume` (`think_sig_none`, `think_sig_empty`, `resume`).
  - Opaque signatures are replayed byte-exact (`think_sig_opaque`).
  - For Claude Code, (a) is sufficient.
  - Caveat for the emitter: never end a response with only a thinking block (`think_only_tail`).
- **O-4B-8 (side calls).** None found in any captured mode, so (a) `--side-model` is not needed on this evidence. Interactive default-env and long-idle inventories are UNVERIFIED.
- **O-4B-10 (`count_tokens`).**
  - Never sent; relaying it unarchived stays harmless and is low priority.
  - The important half is the blocking limit. It is computed from **reported usage**, so `CLAUDE_CODE_MAX_CONTEXT_TOKENS=1000000` is required (verified at 250,000).
  - 32768 would refuse turn 2 of a real session.
- **O-4B-12 (mid-conversation system).**
  - The entries always appear, after the first user message.
  - A 400 whose text contains `Unexpected role` + `input message role`, or `not supported` + `role 'system'` (the tested Palimnesis wording: `palimnesis: unsupported_feature: role 'system' in messages is not supported`), makes Claude Code resend at once (under 0.02 s), folded into the preceding user message.
  - The fold persists for the session.
  - The rejected request is never accepted, so the archive starts from the folded form and stays linear.
  - The cost is one extra round trip per session, plus one each time a new entry would appear (after compaction or the resume of an imported history: `import_history_sysrole_reject`).
  - "Reject" is therefore viable without any Strata rendering of the role.
- **O-4B-13 (F at 32K).**
  - `-p` candidate: F = 16,024. 16,024 + 14,592 = 30,616 ≤ 32,768 (fits, 2,152 spare).
  - Interactive candidate: F = 18,812. 18,812 + 14,592 = 33,404 > 32,768 (**does not fit, by 636**).
  - Trimming 17 tools with `permissions.deny` gives F = 3,784 (`-p`), which fits with 14,392 spare.
  - If the system entry were merged into F, add about 2.0–2.2K untrimmed, or 0.2K trimmed.

## Recommended Claude Code settings for Palimnesis

Env (per process, through the wrapper):

```
ANTHROPIC_BASE_URL=http://127.0.0.1:9000/s/<session>
ANTHROPIC_API_KEY=<any non-empty string>        # sent as x-api-key; avoids claude.ai login fallback
ANTHROPIC_MODEL=<Strata model id>
CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1      # also suppresses HEAD /api/hello
DISABLE_TELEMETRY=1  DISABLE_ERROR_REPORTING=1  DISABLE_AUTOUPDATER=1  DISABLE_GROWTHBOOK=1
CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL=1   # STATIC, unverified (interactive egress)
CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1        # no context_management, tool deferral, display, extra betas
CLAUDE_CODE_ATTRIBUTION_HEADER=0                # no per-session billing line in system[0]
CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK=1     # event: error before any completed block is final
CLAUDE_CODE_MAX_CONTEXT_TOKENS=1000000          # client blocking limit never fires on bounded-view usage
CLAUDE_CODE_MAX_OUTPUT_TOKENS=<client limit>    # sets max_tokens (default 32000)
DISABLE_COMPACT=1                               # or DISABLE_AUTO_COMPACT=1 to keep manual /compact (a divergence)
```

Settings (`$CLAUDE_CONFIG_DIR/settings.json` or the project's):

```json
{"permissions": {
  "additionalDirectories": ["<transcript root>"],
  "deny": ["Agent", "ListAgents", "SendMessage", "Workflow", "Monitor", "CronCreate", "CronDelete", "CronList",
           "ScheduleWakeup", "EnterWorktree", "ExitWorktree", "ReportFindings", "NotebookEdit", "TaskStop",
           "WebFetch", "WebSearch", "Skill"]}}
```

The side-call switches in the candidate env (title, away summary, auto memory, fork subagent, background tasks, prompt suggestion) had no observable effect, because no side call occurred even without them. They are harmless to keep. `Agent` denial is what stops subagents.

**Proxy responses** (from HC5; Messages envelope `{"type":"error","error":{…}}`):

| Situation | Response | Evidence |
| --- | --- | --- |
| Queue full | `429` + `retry-after` ≤ 30 s (5 s was honored; 90 s fails at once) | `f_s429_ra5_then_ok`, `f_s429_ra90` |
| Duplicate, ambiguous or permanent failure before headers | 4xx/5xx + `x-should-retry: false` (1 attempt) | `f_s409_noretry`, `f_s500_noretry` |
| Upstream failure after `message_start`, **before any `content_block_stop`** | `event: error`, then clean EOF. Claude Code fails the turn with no resend, given `DISABLE_NONSTREAMING_FALLBACK=1`. Leave an open block **open**: closing it first triggers a Continue. | `f_error_event_then_ok`, `f_partial_error_event_then_ok` |
| Upstream failure after a completed block | Any ending gives a Continue with the synthetic `cut off mid-stream` user message; `x-should-retry` cannot stop it. The archive must accept that shape as an append (as for OpenCode's Continue). | `f_complete_then_*` |
| Never | A bare EOF or RST while a block is open: the identical body is resent even with `x-should-retry: false` (keyless duplicate) | `f_partial_eof_noretry_then_ok` |
| Keepalive | `event: ping` or SSE comments; both verified to 660 s. `ping` before `message_start` is tolerated. | `wd_default_*`, `f_ok_ping_first` |

## Not covered or blocked

- **Interactive follow-ups, stopped after the egress attempt.** Not run: the default-env TUI inventory, the away summary after a long idle, `/rewind`, interactive auto-compaction, and `HEAD /api/hello` with nonessential traffic allowed. To continue, a human should first confirm that the switch stops the CONNECTs: the sentinel in `C:\ccprobe\tui_candidate2\sentinel.jsonl` must stay empty. Command (from the repo, with `CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL=1` now in `SAFE_ENV`):
  `uv run --with pywinpty python eval/probes/cc_tui_probe.py --root C:/ccprobe tui_candidate2 --idle 300`
- `count_tokens` triggers (never observed). Interactive `/context` is a candidate; UNVERIFIED.
- Why `/compact` was sent twice, and whether a `<summary>`-shaped answer avoids it.
- The `retry-after` cutoff between 5 s and 90 s (static: about 60 s).
- A real model's request shapes (mbp `qwen36` serves Messages, unused).
- The event-level watchdog's actual clamp (`CLAUDE_STREAM_IDLE_TIMEOUT_MS=15000` had no effect).
