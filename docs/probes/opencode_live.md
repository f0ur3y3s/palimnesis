# OpenCode 2.1.4 live probe through the Mnemon passthrough (Phase 0)

Oct 24, 2026, 20:19–20:30 UTC.

**Setup:**

- OpenCode `v2.1.4` (Bun single-file binary, `%APPDATA%\npm\node_modules\@opencode\cli\bin\opencode.exe`).
- The Mnemon passthrough (`mnemon serve`, uncommitted working tree on `main`), with capture on.
- Strata `0.1.48` at `http://192.168.1.173:8080`, model `qwen3.8-flash-next-iq3_xxs`, `n_ctx` 65536 from `/props`.

**Fixtures:** `eval/fixtures/opencode-2.1.4/live/`. Its README lists every exchange.

**Labels:** **[verified]** means observed in these captures or runs. **[source]** means read from the `v2.1.4` source tarball, not exercised live. **[unverified]** means inferred.

This probe confirms or corrects the static OpenCode section of `docs/probes/harnesses.md`. Fault, timeout and retry behaviour is out of scope here; see `eval/fixtures/opencode-2.1.4/faults/`.

## 1. Isolation (environment variables) [verified]

OpenCode resolves its global paths from XDG variables on every platform, including Windows (`packages/util/src/global-roots.ts`). It resolves `home` from `OPENCODE_TEST_HOME ?? os.homedir()` (`packages/util/src/global.ts`). `opencode debug paths` printed only scratch paths with the variables below.

The user's `~/.config/opencode`, `~/.local/share/opencode`, `~/.local/state/opencode` and `~/.cache/opencode` kept their mtimes from before the run. They were checked with `stat` only; their contents were not read.

| Variable | Value / purpose |
| --- | --- |
| `OPENCODE_CONFIG_DIR` | `<scratch>/config`: the global config dir. It holds `opencode.json`, `plugins/` and `service.json`. |
| `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`, `XDG_STATE_HOME` | `<scratch>/xdg/*`. The DB, logs, snapshots and the service registration go here. |
| `OPENCODE_TEST_HOME`, `HOME`, `USERPROFILE` | `<scratch>/home`. `home` roots `~/.claude` and `~/.agents` discovery, and `~` expansion. |
| `TEMP`, `TMP` | `<scratch>/tmp`. Otherwise OpenCode uses the shared `%TEMP%\opencode`. |
| `OPENCODE_DISABLE_PROJECT_CONFIG=true` | **Required.** See below. |
| `OPENCODE_DISABLE_CLAUDE_CODE=true` | Stops `.claude` skill roots from loading. |
| `OPENCODE_DISABLE_MODELS_FETCH=true`, `OPENCODE_DISABLE_AUTOUPDATE=true`, `OPENCODE_DISABLE_FILEWATCHER=true` | Remove network and background noise. |
| `OPENCODE_CONFIG`, `OPENCODE_CONFIG_CONTENT`, `OPENCODE_CLI_CONFIG_CONTENT` | Unset |

Two hazards that `harnesses.md` does not mention:

- **Config discovery walks from the working directory to the drive root, with no stop** (`packages/core/src/config/discovery.ts`, `fs.up` without `stop`) [source].
  - At each ancestor it loads `.claude`, `.agents`, `.opencode`, `opencode.json` and `opencode.jsonc`.
  - Any directory under `C:\Users\Daniel` therefore picks up `C:\Users\Daniel\.claude` (skills) and any `~/.opencode` or `~/opencode.json`, even with `OPENCODE_TEST_HOME` set.
  - `OPENCODE_DISABLE_PROJECT_CONFIG=true` disables the walk. With it set, `opencode debug config` listed only the scratch `opencode.json` and the config directory.
  - `AGENTS.md` instruction discovery stops at the git root or home (`config/plugin/instruction.ts`) [source].
- **`opencode run` and the TUI talk to a shared background service by default** (`ServerConnection.resolve`, `cli/src/services/server-connection.ts`) [source, plus a process listing].
  - The service is registered at `$XDG_STATE_HOME/opencode/service.json`.
  - The user already has one running (`opencode.exe serve --service`, started 2026-10-23). A client with the default state dir attaches to it, so that service's config, plugins and environment apply, not the invoking process's.
  - Use `opencode run --standalone`, or put `{"disabled": true}` in `$OPENCODE_CONFIG_DIR/service.json`. That file makes every command standalone; `opencode debug config` would otherwise also start the service.
  - The standalone server is a child process (`opencode serve --stdio --port 0`) that exits with the client. No OpenCode process from this probe outlived its run.

The exact `env.sh` is in `eval/fixtures/opencode-2.1.4/live/config/env.sh`.

## 2. Configuration [verified]

`$OPENCODE_CONFIG_DIR/opencode.json` uses the v2 shape:

```json
{
  "model": "mnemon/qwen3.8-flash-next-iq3_xxs",
  "update": "disable",
  "share": "disabled",
  "compaction": { "auto": false },
  "agents": { "title": { "disabled": true } },
  "permissions": [{ "action": "subagent", "resource": "*", "effect": "deny" }],
  "providers": {
    "mnemon": {
      "name": "Mnemon",
      "package": "@opencode/ai/providers/openai-compatible",
      "settings": {
        "baseURL": "http://127.0.0.1:9011/s/static-fallback/v1",
        "apiKey": "mnemon-local-dummy"
      },
      "compatibility": { "reasoningField": "reasoning_content" },
      "models": {
        "qwen3.8-flash-next-iq3_xxs": {
          "name": "Qwen3.8 Flash Next (Strata via Mnemon)",
          "capabilities": { "tools": true, "reasoning": { "supported": true } },
          "limit": { "context": 1000000, "output": 8192 }
        }
      }
    }
  }
}
```

`$OPENCODE_CONFIG_DIR/service.json` contains `{"disabled": true}`.

Notes on individual settings:

- **Provider fields.** In the v2 shape, `baseURL` and `apiKey` live under `providers.<id>.settings` [source: `config/plugin/provider.ts`, `aisdk-native.ts`].
- **API key.** The key is sent as `Authorization: Bearer …`, which the proxy capture redacts. Strata ignores it.
- **Fallback baseURL.** The static `baseURL` is a deliberately wrong session (`static-fallback`). If the identity hook failed, captures would land under that session. None did.
- **`max_completion_tokens` stays constant.** OpenCode computes `min(limit.output || 32000, 256000)`, then reduces it to `limit.context − measured − 1.15·estimated` (floor 1024) when `limit.context > 0` (`session/model-request.ts` `outputLimit`) [source].
  - With `limit.context` 1,000,000 and `limit.output` 8192, the reduction never binds. **Every one of the 10 requests sent `max_completion_tokens: 8192`** [verified], while the prompt grew from 5004 to 10808 tokens.
  - Setting `limit.context: 0` should also disable the fit, because `outputLimit` returns the requested value when `limit.context <= 0` [source, unverified live]. That also makes the window "unknown" to OpenCode.
  - Real capacity enforcement is Mnemon's job (plan, "Complete budgets").
- **Compaction.** `compaction.auto: false` was set. History never neared a threshold in this probe, so the setting was not exercised live. It rests on the source reading in `harnesses.md` §6.
- **Title generation.** `agents.title.disabled: true` was set, and no `title` request occurred (plugin log: 10/10 `kind: primary`).
  - From source, the title agent picks the provider's small model or a lower reasoning variant of the primary model, and gives up when neither exists (`session/context.ts` `selectTitle`). A custom model with no variants may never title even when enabled [unverified].
  - So this run does not prove that the setting is necessary, only that it is sufficient.
- **Subagent tool.** `permissions` deny on `subagent` removed the tool definition. The advertised tools were `edit, glob, grep, question, read, shell, skill, webfetch, websearch, write, execute`, with no `subagent` [verified].
- **Running the tasks.** `opencode run --standalone --auto --format json [--session <id>] "<message>"`. `--auto` approves permissions that are not explicitly denied. `--session <id>` resumes, or creates a session with that ID.

## 3. Session identity: the `model.request` plugin hook works [verified]

`$OPENCODE_CONFIG_DIR/plugins/mnemon.ts` (fixture copy: `config/plugins/mnemon.ts`):

```ts
export default {
  id: "mnemon-session-url",
  setup: async (ctx: any) => {
    await ctx.session.hook("model.request", (event: any) => {
      event.baseURL = `${BASE}/s/${event.sessionID}/v1`
      event.headers["X-Mnemon-Kind"] = event.kind
      // (plus an appendFileSync log line)
    }, { providerID: "mnemon" })
  },
}
```

How the plugin loads:

- **Registration.** Files in `<global config dir>/plugin/` or `<global config dir>/plugins/` (`*.ts` / `*.js`) are auto-discovered (`plugin/source-directory.ts`).
  - The module needs a default export `{id, setup}` (Promise API) or `{id, effect}` (Effect API). No `@opencode/plugin` import is needed, and Bun transpiles TypeScript directly.
  - A `plugins: ["./x.ts"]` config entry pointing at a **file** is rejected with a warning ("configured plugin path must be a directory") [source]. Auto-discovery is the simple path.
- **What the hook sees.** It receives `{sessionID, agent, model, kind, baseURL, headers}`. Changes to `baseURL` and `headers` replace the route endpoint and the request headers (`session/model-request.ts`).

What the captures show:

- Every request arrived as `POST /s/ses_e906e5405ffeVfiX2TzyrOhErb/v1/chat/completions` with an empty query.
  - The proxy stripped the prefix and forwarded `/v1/chat/completions`.
  - The base `…/s/<id>/v1` joined with `/chat/completions` exactly as `harnesses.md` §2 predicted.
- **OpenCode session IDs fit the proxy's validator.** The form is `ses_` plus 26 characters of `[0-9A-Za-z]` (30 characters in total), so no mapping was needed.
  - Note: `model-request.ts` tests `/^ses_[0-9a-f]{64}$/` for the prompt cache key, and this ID does not match. The cache key goes unused for custom providers anyway (§4).
- **Resume works.** Turn 2 was a new `opencode run` process with `--session ses_e906…`. It routed to the same `/s/<id>/` path with no Mnemon-side session command.
  - So `mnemon session new` is not needed for OpenCode: each new OpenCode session yields a fresh path ID, and a resumed one reuses it.
  - Forks and child sessions get their own `sessionID` and therefore a separate path [source; forks and subagents not exercised].
- **Side calls are tagged.** `X-Mnemon-Kind` carried `primary` on all 10 requests. The proxy captured it and stripped it before forwarding (`x-mnemon-*`). Title, compaction and generate calls would carry their own `kind`.

## 4. Request shape [verified]

### Headers

Request headers as received by the proxy, identical on all 10 requests apart from the tracing IDs and `content-length`:

| Header | Value |
| --- | --- |
| `authorization` | `Bearer <apiKey>` (redacted in capture) |
| `content-type` | `application/json` |
| `user-agent` | `opencode/latest/2.1.4/cli` |
| `b3` | `<trace>-<span>-1-<parent>`: **Zipkin tracing, not in harnesses.md** |
| `traceparent` | `00-<trace>-<span>-01`: **W3C tracing, not in harnesses.md**. One trace ID spans a whole `opencode run`; the span changes per request. |
| `x-mnemon-kind` | from the plugin |
| `x-opencode-client` | `cli` |
| `x-opencode-project` | the project ID, which is the throwaway repo's root commit hash |
| `x-opencode-session`, `x-opencode-session-id`, `x-session-affinity`, `x-session-id` | the session ID (all equal for a root session) |
| `connection` | `keep-alive` |
| `accept` | `*/*` |
| `accept-encoding` | `gzip, deflate, br, zstd` |
| `host`, `content-length` | — |

- **Not sent:** `x-stainless-*`, `Idempotency-Key`, any retry-count header, `x-opencode-parent-session-id` / `x-parent-session-id` (no child sessions here).
- **`accept-encoding` passthrough.** The proxy forwards `accept-encoding` upstream. Strata 0.1.48 answered uncompressed. A compressing upstream would flow through `aiter_raw` with its `content-encoding` header [unverified].

### Body

- **Top-level key order:** `model`, `messages`, `tools`, `stream`, `stream_options`, `max_completion_tokens`.
  - `stream` is `true`.
  - `stream_options` is `{"include_usage": true}`.
  - `max_completion_tokens` is 8192 on every request.
- **Absent fields:** `tool_choice`, `parallel_tool_calls`, `prompt_cache_key`, `reasoning_effort`, `store`, `temperature`, `chat_template_kwargs`, `user`, `metadata`.
  - `reasoning_effort` is absent even with `capabilities.reasoning.supported: true`, because no `effort` list was configured.
- **`model`** is the config model key.
- **Messages:**
  - A single `system` message (8656 characters). It holds the harness instructions, model name and IDs, a "Code Mode" catalog for the `execute` tool, the `opencode` and `report` skills, today's date and an `<env>` block with the working directory and scratch tmp path.
  - No user `AGENTS.md` and no `.claude` content was injected.
- **Tools:** 11, each `{"type":"function","function":{name, description, parameters, strict:false}}`. The array is byte-identical across all requests (10,839 bytes compact).
  - **`execute`** (JavaScript Code Mode runtime with `fetch`), **`websearch`**, **`webfetch`**, **`skill`** and **`question`** are on by default. `harnesses.md` does not list them.
  - `question` cannot be answered in `opencode run`. The tool returns an error result; exchange 4 shows the model calling it.
- **Assistant turns:**
  - Tool-call-only assistants have keys `role, content, tool_calls, reasoning_content`, with **`content: null`**.
  - Text-bearing assistants carry `content` as a string.
- **Tool results** are `{"role":"tool","tool_call_id","content": <string>}`.
  - Tool errors are serialised as a JSON string: `{"error":{"type":"tool.execution","message":…},"content":[]}`.
  - Shell output keeps `\r\n` on Windows.
- **User text quirk.** The user text arrived wrapped in literal double quotes (`"\"Create a file…\""`). The cause is likely the npm `opencode` shell shim under Git Bash passing argv to the Bun exe [unverified]. It is harmless here, but it is a harness/OS input quirk, not proxy behaviour.

### `max_completion_tokens`

8192 on all 10 requests. Prompt tokens per request: 5004, 5107, 5189, 5261, 5344, 9101, 10279, 10392, 10731, 10808.

## 5. Streaming, side calls and linearity [verified]

- **All 10 requests streamed** and ended with a known `finish_reason` (`tool_calls` ×8, `stop` ×2) and `data: [DONE]`. All were HTTP 200 with complete captures.
  - Strata sent 2–4 `: keep-alive` comments per response; OpenCode accepted them.
  - No non-streaming request occurred.
- **No side calls.** The plugin log, proxy log and captures each show exactly 10 `primary` requests: no title, compaction, generate or subagent calls.
- **History is append-only.** It was checked at the byte level: the previous request's `messages` serialisation, up to its closing `]`, is a byte prefix of the next request in all 9 transitions.
  - Each step appends `,{assistant},{tool}`; turn 2 starts by appending `,{user}` after turn 1's final assistant message.
  - This held across the process restart between turns, so OpenCode rebuilt the history from its SQLite store byte-faithfully.
  - No synthetic messages (Continue, length or system-update notices) appeared.
- **Reasoning echo.** `reasoning_content` was echoed on **every** prior assistant turn, including tool-call-only turns and final text turns. It was byte-equal to the concatenated streamed `reasoning_content` deltas, and the echoed `content` equalled the streamed content.
  - Every assistant turn here had non-empty reasoning, so the `""` forcing for empty reasoning was not exercised.
- **Strata cache reuse.** Each request's `cached_tokens` was within a few tokens of the previous request's `prompt + completion`, e.g. 5088 against 5004 + 82, and 10791 against 10731 + 59.
  - The echoed reasoning keeps the template prefix stable, consistent with `strata.md` §2.
  - The first request was cold (0 cached).
- **Usage reporting.** OpenCode reported `reasoning: 0` tokens in its step events. Strata's usage has no reasoning breakdown, so OpenCode cannot split it out.
- **Raw-delta implication** (plan, "Archival exactness").
  - Because `tools` (10.8 KB) follows `messages`, the longest common byte prefix ends at the previous `messages` array. A prefix-only delta re-stores the whole tools array on every request.
  - The common suffix after the prefix was 10,933 bytes on every transition. The optional prefix+suffix delta variant would remove that duplication for OpenCode.

## 6. Replay baseline [verified]

`eval/replay.py` ran on the 10 baseline exchanges, sequentially, with Strata idle at start (`/status` `busy: false, queued: 0`):

| Target | Wall time | Status match | Finish reasons match | Byte-identical | Notes |
| --- | --- | --- | --- | --- | --- |
| Direct `http://192.168.1.173:8080` | 45 s | 10/10 | 10/10 | 0/10 | Event counts differ, e.g. exchange 4: captured 3499 vs replayed 55. |
| Proxy `http://127.0.0.1:9012/s/replay-via-proxy` | 61 s | 10/10 | 10/10 | 0/10 | The proxy's own capture shows every replayed request body **byte-identical** to the baseline. All 10 replayed responses were complete and ended with `[DONE]`. |

Generated text differs on every run (Strata default temperature 1.0; `strata.md` §0). As the plan says, that is diagnostic only. Status, finish-reason sequence and stream framing are comparable.

- `replay.py` drops the redacted `authorization` header and `x-mnemon-*` headers. It replays the rest, including `traceparent` and `b3`.
- Reports: `eval/fixtures/opencode-2.1.4/live/reports/replay_{direct,proxy}.json`.

## 7. Contradictions and additions to `docs/probes/harnesses.md` (OpenCode section)

1. **Additional headers (§2):** `b3` and `traceparent` (tracing), plus `accept-encoding: gzip, deflate, br, zstd`. The User-Agent is exactly `opencode/latest/2.1.4/cli`.
2. **The plugin path is now verified (§2 "Per-session URL").**
   - Auto-discovery is from `<config dir>/plugins/*.ts`, with a default export of `{id, setup}`.
   - A configured file path in `plugins` is rejected; it must be a directory.
3. **Background service (not in harnesses.md).** Without `--standalone` or `service.json` `{"disabled": true}`, a client attaches to a long-lived shared `opencode serve --service`.
   - Per-process environment (for example a per-process base URL or plugin env) may then never reach the process that makes model requests.
   - This undercuts the "per process" identity fallback unless the service is disabled.
4. **Config discovery reaches the drive root (not in harnesses.md).** Disable it with `OPENCODE_DISABLE_PROJECT_CONFIG`, or the user's home `.claude` / `.opencode` content leaks into any session under the home directory.
5. **Default tools (§5/§8).** `execute` (Code Mode JS with `fetch`), `websearch`, `webfetch`, `skill` and `question` are advertised by default.
   - `websearch` and `execute` can make network requests.
   - `question` returns an error under `opencode run`.
   - Consider denying them for evaluation runs.
6. **Title generation (§5)** may not fire at all for a custom single-variant model [source; unverified live]. "On by default" is not guaranteed for this setup.
7. **`content: null`** on tool-call-only assistant turns, a shape detail §8 did not state.
8. **Not contradicted (confirmed live):**
   - `/s/<id>/v1` prefix preservation and joining.
   - Always-streaming requests.
   - `stream_options.include_usage`.
   - `strict: false` on tools.
   - `max_completion_tokens` field name and fitting formula.
   - No `prompt_cache_key`, `reasoning_effort` or `tool_choice` by default.
   - `reasoning_content` echo on every prior assistant turn.
   - A deny on `subagent` removes the tool.
   - Required `finish_reason` + `[DONE]`, which Strata always supplies.

## 8. Proxy behaviour

No proxy bug blocked this probe.

- Path routing, prefix stripping, header forwarding (minus hop-by-hop and `x-mnemon-*`), streaming relay and capture all behaved as documented.
- Through the proxy, request bodies reached Strata byte-identical.

Observations for later phases (not bugs):

- The proxy forwards `accept-encoding`, `traceparent`, `b3` and the `x-opencode-*` headers to Strata.
- A request to `/s/<id>/health` (any path) is proxied and captured like any other.

## 9. Not covered here

- Cancellation and interruption, and retry/Continue behaviour: see the fault fixtures.
- `compaction.auto: false` under real context pressure.
- `limit.context: 0`.
- Forks, child sessions, `/undo` / revert.
- Anthropic-route OpenCode.
- The TUI path, which uses the same background-service resolution as `run`.
