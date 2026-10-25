# Harnesses

Setup and verified behavior per supported harness. Evidence lives in `docs/probes/`; this file holds what a user needs and what Palimnesis relies on. Other harnesses are compared in `docs/probes/harnesses.md` and arrive in Phase 4B.

## OpenCode 2.1.4 (first harness; Chat Completions)

### Setup

1. Run the proxy: `uv run palimnesis serve --upstream http://<strata-host>:8080`. It archives to `%LOCALAPPDATA%\palimnesis\palimnesis.db` by default (`--db PATH` to choose, `--passthrough` to relay without archiving). One proxy process owns an archive at a time.
2. Copy `integrations/opencode/opencode.json` and `integrations/opencode/plugins/palimnesis.ts` into your OpenCode config directory (`$OPENCODE_CONFIG_DIR`, or the global config dir), keeping the `plugins/` subfolder. Merge with an existing config rather than replacing it.
3. If the proxy is not on `127.0.0.1:9000`, set `PALIMNESIS_PROXY_ORIGIN` and change `providers.palimnesis.settings.baseURL` to match. The variable must be in the environment of the process that calls the model. A shared `opencode serve --service` instance does not see a later shell's environment, so restart it, or run with `--standalone`.
4. Start or resume chats normally: `opencode`, `opencode run …`, `opencode run --session <id> …`.

### Recall and transcript files (Phase 3)

- **Proactive excerpts** need no harness setup. Each new instruction gets a block of archived evidence in the upstream copy of the message only.
- **Transcript files** are written to `%LOCALAPPDATA%\palimnesis\transcripts\<session>\` (`--transcripts DIR` to move them, `--no-transcripts` to turn them off). Once a session first hides anything, the model is told that directory and to grep, then read with an offset and limit (addendum a3).
- **OpenCode reaches the directory with the shipped config.** No rule is needed: its default agents allow `external_directory`, `read`, `grep`, `glob` and `shell` outside the project (verified live, D37). If you run an agent configured with ask or deny rules, add these last in `permissions`:
  ```json
  {"action": "external_directory", "resource": "C:/Users/<you>/AppData/Local/palimnesis/transcripts/*", "effect": "allow"},
  {"action": "read", "resource": "C:/Users/<you>/AppData/Local/palimnesis/transcripts/*", "effect": "allow"}
  ```
- **Permission rules do not confine the files.** OpenCode's shell tool bypasses `external_directory`, so the transcripts' privacy rests on filesystem permissions: the per-user ACL of `%LOCALAPPDATA%`.
- **Do not point the model at the root.** OpenCode's grep searches hidden folders, including the root's `.staging`. The addendum names the session directory only.

### Session identity

The plugin's `model.request` hook rewrites each request's base URL to `/s/<OpenCode sessionID>/v1`. A new OpenCode session is a new Palimnesis session, and resuming an OpenCode session resumes its Palimnesis session, across processes [verified, `docs/probes/opencode_live.md`]. `palimnesis session new` is not needed for OpenCode.

`X-Palimnesis-Kind` carries the request kind (`primary`, `title`, `compaction`, `generate`) for the proxy; it is never forwarded upstream.

If the plugin fails to load, requests reach the unprefixed `…/v1` base URL. The proxy then rejects them with `session_required`; it never merges chats.

### Required settings and why

| Setting | Why |
| --- | --- |
| `compaction.auto: false` | Native compaction would rewrite history; this also disables compaction on overflow. Manual `/compact` still works and creates a discontinuity. |
| `agents.title.disabled: true` | Title generation runs concurrently with the first request. |
| deny `subagent` | Child sessions share their parent's affinity headers and run concurrently. |
| `limit.context: 1000000`, `limit.output: 8192` | OpenCode shrinks `max_completion_tokens` as its own history estimate approaches `limit.context`. A large context keeps it constant (8192 on every request, verified), so Palimnesis's allowance is the true limit. |
| `compatibility.reasoningField: reasoning_content` | Matches Strata's reasoning field; OpenCode echoes it on every prior assistant turn. |

### Interrupted streams

A failed or cut-short stream ends with an in-stream error event and `x-should-retry: false`, so OpenCode does not loop on retries. Its next request in that session resends the partial answer flattened into `content`. Palimnesis accepts this as acknowledging the partial and sends the upstream the reasoning and text split apart again (`docs/probes/opencode_partials.md`, D10.3).

### Unsupported while using Palimnesis (no config switch exists)

- **Undo, redo, revert, `fork`, `timeline`, `/btw`:** each changes visible history. Phase 1 rejects the divergent request with a defined error.
- **Manual `/compact`:** avoid it.
- **Background shell jobs (`background: true`):** they inject later notices; avoid them.
- **The `question` tool:** it errors in non-interactive `opencode run`, but is harmless.

### Isolation gotchas (testing and CI)

- `opencode run` attaches by default to a running `opencode serve --service` instance, which ignores your process's environment and plugins. Use `--standalone`, or put `{"disabled": true}` in `$OPENCODE_CONFIG_DIR/service.json`.
- Config discovery walks up to the drive root and loads `~/.claude` and `~/.opencode`. Set `OPENCODE_DISABLE_PROJECT_CONFIG=true` for isolated runs.
- `eval/fixtures/opencode-2.1.4/live/config/env.sh` is a complete isolated environment.

### Scripted runs and session import (evaluation, S11)

Recorded 2026-10-25 while building the real-OpenCode drivers (`eval/oc_harness.py`, `eval/needle_opencode.py`, `eval/tasks/run.py`). Raw probe data stayed in the session scratchpad.

- **Pass the message on stdin, not as an argument** [verified, Windows]. Given one argument that contains spaces, `opencode run` keeps the quotes that `CreateProcess` quoting adds: `Say "hi"` reached the upstream as `"Say \"hi\""`, quotes and escapes included. Splitting the message into one argument per word avoided it. A message written to stdin, with no message argument, arrived byte-exact: 54,916 characters with newlines, tabs and non-ASCII. stdin then reaches EOF, as scripted runs require. The R9/R10/R14 scripts passed the message as one argument, so their messages most likely reached the model quoted [inferred, unverified].
- **`--format json` events** [verified, 3 sessions]: `step_start`, `text`, `tool_use` (with `state.input`, `state.output` and `state.status`) and `step_finish`, one JSON object per line. A step that ends in tool calls gets `step_finish` with reason `tool-calls`; the turn's last step gets no `step_finish`. Its answer is therefore the text of the last step that started.
- **Export format** (`opencode session export <id>`) [verified]. It is `{"info": …, "messages": […]}`.
  - `info` holds `id`, `projectID`, `tokens`, `outcome`, `time`, and `location.directory`.
  - Each message has a `type`:
    - `user`: `text` and `files`.
    - `assistant`, one per model step: `agent`, `model` (`id`, `providerID`), `finish` and `rawFinish`, `tokens`, and `content` parts. A part is `reasoning` (`text`, plus `native.reasoningField`), `text`, or `tool` (`id`, `name`, and `state` with `status`, `input`, a `content` list of text items and `metadata`).
    - `idle`: closes a turn.
  - Ids are 12 hex digits, the low 48 bits of `ms * 4096 + counter` (inverted for session ids, so they sort newest first), then 14 base-62 characters.
  - For a git workspace, `projectID` is the repository's root commit [observed].
- **Import** [verified]. `opencode session import --standalone --directory <workspace> <file>` accepts a hand-built document of that shape, keeps its session id (`Imported session: ses_…`), and `opencode run --session <id>` continues it. `eval/oc_harness.history_to_export` builds the document from Chat Completions messages.
- **Resend fidelity** [verified against the fake upstream, 13 messages].
  - Imported history goes upstream exactly as the source messages, including:
    - tool calls (ids, names, compact argument JSON) and their results;
    - two tool calls plus text in one step;
    - reasoning, as `reasoning_content`;
    - a reasoning-only assistant turn with `content: ""`;
    - `content: null` on tool-call-only turns.
  - The one difference: an assistant turn without reasoning is sent with `reasoning_content: ""`. Key order is `role`, `content`, `tool_calls`, `reasoning_content`.
- **Through the proxy** [verified live, dev-h1, 2026-10-25]:
  - The first request of the imported session is the whole history plus the first question: 101 messages, with `reasoning_content: ""` added to 50 assistant turns.
  - Its 73 prior assistant and tool turns are archived as `client_import`.
  - The Strata count matched `usage.prompt_tokens` on all 18 upstream calls, so the empty reasoning fields render as nothing.
  - No request was rejected: OpenCode's resends of generated turns reconciled with the archive.
- **Native compaction** (`compaction.auto` true, `limit.context` 32768, through `--passthrough`) [verified live, dev-t1, 2026-10-25].
  - Compaction is an ordinary model request with the tools still offered. Its last user message is "You MUST summarize the conversation above…" the first time and "Update the existing checkpoint in the conversation above…" after that.
  - When the reply did not fill the template, OpenCode sent one retry: "The previous response did not fill in the required summary template…".
  - The next request replaces the history with one user message, `<conversation-checkpoint>…<summary>…</summary><recent-context>…</recent-context></conversation-checkpoint>`, followed by the turns since.
  - The export records each one as a message of type `compaction`. In 8 turns there were 4 compactions and 5 compaction requests; the largest upstream input was 21,266 tokens.
- **Unparsable tool arguments** [verified live, same run]. When the model emitted tool-call arguments that were not JSON, OpenCode did not run the call. It answered with a `tool.input-json` error that quotes the raw input, including any `</tool_call>` markup, and resent the call with `arguments: "{}"`.
- **The model's shell sees the system Python.** Under `uv run`, the project's virtual environment comes first on PATH. The drivers remove it, along with `VIRTUAL_ENV`, so the model runs the same `python` as the hidden checks (3.14, no pytest) [verified with a scripted shell call, fake upstream].
  - **Resolve the interpreter explicitly.** On Windows, `subprocess` looks up a bare `python` on the parent's PATH, not on the PATH passed in `env`. A check started as `["python", …]` from under `uv run` therefore ran the venv's Python 3.12 [observed]. The task runner resolves the path with `shutil.which` on the cleaned PATH. The R23 smoke checks ran under the venv interpreter; their tests use only the standard library.
- **Environment allowlist** (`oc_harness.ENV_ALLOW`). OpenCode, the model's shell and the hidden checks inherit only system variables (`SYSTEMROOT`, `COMSPEC`, `PATHEXT`, processor and user names, program directories, `TZ`/`LANG`), the cleaned PATH, and `APPDATA`/`LOCALAPPDATA`. HOME, USERPROFILE, TEMP/TMP, XDG and the OpenCode variables point into the run's own tree.
  - **Keep `LOCALAPPDATA` real.** The system `python` is a Python install manager alias, and it keeps its installs under `LOCALAPPDATA`. With `LOCALAPPDATA` isolated, one `python -c` in the model's shell made the install manager update itself (to 26.4) and download Python 3.15.1 into the isolated directory [observed 2026-10-25, fake upstream; no model involved].

### Request shape [verified]

- Every request streams, with `stream_options.include_usage`. There are no non-streaming requests on the wire.
- Top-level key order is `model`, `messages`, `tools`, `stream`, `stream_options`, `max_completion_tokens`.
- `tools` (about 10.8 KB) follows `messages`, so a prefix-only raw delta re-stores the tools array on every request (see plan, "optional measured optimization").
- Tool-call-only assistant turns have `content: null`.
- Headers include `x-opencode-session-id`, the affinity headers, `b3` and `traceparent`, `accept-encoding`, and `User-Agent: opencode/…`.
- There is no idempotency key and no retry-count header.
- The stream must carry a known `finish_reason`. `[DONE]` is not required (verified; this corrects `docs/probes/harnesses.md` §8). Without a `finish_reason`, OpenCode treats the stream as incomplete and retries it.

### Timeouts and retries

Verified against a fault-injecting fake upstream in 48 runs (`docs/probes/opencode_faults.md`, fixtures in `eval/fixtures/opencode-2.1.4/faults/`), except where marked as coming from source.

| Item | Behavior |
| --- | --- |
| Header wait (`headerTimeout`) | 300 s default (source); the setting works |
| Read-idle (`chunkTimeout`) | 900 s default (source); the setting works; SSE comments reset it |
| Total deadline (`timeout`) | none by default; the setting works |
| Retried | 5xx, 408, 409, 429, and streams that end before any output: 11 attempts in total (about 80–100 s), each with an identical body |
| Timeouts | at most 3 retries (4 attempts) |
| Not retried | 400 (1 attempt) |
| `retry-after`, `retry-after-ms` | honored as a minimum delay |
| `x-should-retry: false` | stops every resend tested, including failures inside a 200 stream and client idle timeouts |
| After partial text or reasoning | appends the partial assistant message, with reasoning flattened into its text with no separator, plus the user message "The previous response was interrupted. Continue…", then resends. `x-should-retry` does not stop this; an in-stream error event with `x-should-retry: false` does, and so does the plugin `retry` hook. |
| `finish_reason: "length"` | two immediate synthetic follow-ups, then failure |
| Idempotency or retry-count header | none; `traceparent` keeps one trace ID per prompt with a new span ID per attempt |
| `opencode run` exit code | 1 if any step failed, even when a later follow-up succeeded |

Scripted runs need `--standalone`, stdin at EOF (non-TTY stdin is read to EOF), and `PWD` set to the intended directory. `opencode run` takes its directory from `PWD` before the process cwd.
