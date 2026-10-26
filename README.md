# Palimnesis

A local, lossless context proxy between an agent harness and a [Strata](#requirements) server.

- **Archives** every accepted message exactly, in a local SQLite database.
- **Bounds** what the model sees: when a chat outgrows the context, older turns are masked in the upstream copy only. The harness's own history is never rewritten.
- **Recalls** what the view removed: each new instruction gets a short block of matching archived excerpts, and the full history is published as transcript files the model can grep and read.

Nothing is summarized and nothing is deleted. The model works in a bounded view while the archive keeps the full history.

## In plain terms

A local model has a small desk. It can only look at so many pages of your conversation at once, and a long coding session soon has more pages than fit.

Most tools handle this by **rewriting old pages into a short summary** and throwing the originals away. The summary is lossy: the exact error message, the file path, the number you mentioned an hour ago are often gone, and the model can't get them back.

Palimnesis does it differently:

- **It keeps every page,** exactly as written, in a filing cabinet on your computer (the archive).
- **It keeps the desk tidy.** When the desk gets full, it takes the oldest pages off the desk, never out of the cabinet. Your tool still has its full copy of the conversation; only what the model is shown changes.
- **It hands back what matters.** Each time you ask something new, it looks through the cabinet and puts the most relevant old snippets on the desk. And it tells the model where the cabinet is, so the model can search it and read any old page word for word.
## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/).
- A **Strata 0.1.48** server, reachable over HTTP. Palimnesis counts tokens exactly as that build does, using a pinned template and tokenizer that ship with it. At startup it checks the server's build, template and a `count_tokens` canary against the pin. On a mismatch it still archives and forwards, but turns bounded views off.
- One harness that speaks OpenAI Chat Completions. **OpenCode 2.1.4** is the supported harness today; see [`docs/harnesses.md`](docs/harnesses.md). Pi and Claude Code are planned.

## Install

```sh
git clone git@github.com:f0ur3y3s/palimnesis.git
cd palimnesis
uv sync
uv run pytest -q   # optional: the full offline suite, no network needed
```

## Quick start (OpenCode)

1. **Run the proxy** against your Strata server:
   ```sh
   uv run palimnesis serve --upstream http://<strata-host>:8080
   ```
   It listens on `127.0.0.1:9000`.
2. **Install the OpenCode integration.** Copy `integrations/opencode/opencode.json` and `integrations/opencode/plugins/palimnesis.ts` into your OpenCode config directory, keeping the `plugins/` folder. Merge the JSON into an existing config rather than replacing it.
3. **Chat normally:** `opencode`, `opencode run …`, `opencode run --session <id> …`.

The plugin routes each OpenCode session to its own Palimnesis session, so new chats and resumed chats need no extra steps. The shipped config also turns off the OpenCode features that would conflict with the proxy. [`docs/harnesses.md`](docs/harnesses.md) explains each setting and what to avoid while using Palimnesis.

## Other OpenAI-compatible clients

Palimnesis needs to know which chat a request belongs to. Get a session base URL and point the client at it:

```sh
uv run palimnesis session new          # prints a base URL for a new chat
uv run palimnesis session url <id>     # the base URL to resume a chat
```

The URL has the form `http://127.0.0.1:9000/s/<session>/v1`. A client that can't change its base URL per chat can send an `X-Palimnesis-Session: <session>` header instead. A request with neither is refused with `session_required`; Palimnesis never merges two chats.

Only `POST /v1/chat/completions` is supported (streaming and non-streaming). `/v1/messages` and `/v1/responses` are refused with `unsupported_feature`.

## Commands

| Command | What it does |
| --- | --- |
| `palimnesis serve --upstream URL` | Run the proxy. |
| `palimnesis session new` / `session url ID` | Base URL for a new or resumed chat. |
| `palimnesis catalog SESSION [--page N]` | Print a session's catalog: what is archived and its addresses. |
| `palimnesis excerpts SESSION` | List the recall excerpt blocks a session has received. |
| `palimnesis transcripts verify SESSION` | Check a session's transcript files against the archive (SHA-256). |
| `palimnesis transcripts rebuild SESSION` | Rebuild them from the archive, byte for byte. |

Prefix each with `uv run`. The inspection commands are read-only and take `--db PATH` for a non-default archive.

### `serve` options

| Option | Default | Meaning |
| --- | --- | --- |
| `--host`, `--port` | `127.0.0.1`, `9000` | Where the proxy listens. |
| `--upstream URL` | (required) | The Strata server's origin. |
| `--db PATH` | see [Where data lives](#where-data-lives) | Archive database. One proxy process owns an archive at a time. |
| `--passthrough` | off | Relay only: no archive, no views, no recall. |
| `--input-budget TOKENS` | 48000 | Cap on the input sent upstream; never above what the server's context allows. |
| `--view on\|off` | `on` | `off` keeps archiving and budget checks but never masks. |
| `--synchronous FULL\|NORMAL` | `FULL` | SQLite durability. `NORMAL` survives process crashes but not power loss. |
| `--transcripts DIR` / `--no-transcripts` | beside the archive | Where transcript files go, or turn them off. |
| `--capture-dir DIR` | off | Store raw request and response bodies, for debugging and replay. **This writes conversation content to disk.** |

`--query-policy`, `--excerpt-renderer` and `--addendum` select recall variants for evaluation. Their defaults are the frozen choices (D43); leave them alone.

## Where data lives

| | Windows | Linux / macOS |
| --- | --- | --- |
| Archive | `%LOCALAPPDATA%\palimnesis\palimnesis.db` | `$XDG_DATA_HOME/palimnesis/palimnesis.db` (default `~/.local/share/…`) |
| Transcript files | `…\palimnesis\transcripts\<session>\` | `…/palimnesis/transcripts/<session>/` |

- **Privacy.** Operational logs never contain message content or credentials. Conversation content is stored only in the archive, the transcript files and, if you turn it on, `--capture-dir`.
- **Transcript files are protected only by filesystem permissions,** which are per-user by default. The model reads them through the harness's own file tools.
- **Deleting.** There is no delete command yet. To discard everything, stop the proxy and delete `palimnesis.db*` and the `transcripts` directory.

## Errors you may see

Errors come back in the client's own error format, with `x-should-retry: false` unless a retry can help.

| Status, code | Meaning | What to do |
| --- | --- | --- |
| 400 `session_required` | The request reached `/v1` without a session. | Use a session base URL, or check that the OpenCode plugin loaded. |
| 400 `session_mismatch` | The URL path and the `X-Palimnesis-Session` header name different sessions. | Fix the client configuration. |
| 400 `invalid_session_id` | A session id outside `[A-Za-z0-9._-]`, or one that doesn't start alphanumeric. | Use an id from `palimnesis session new`. |
| 400 `unsupported_feature` | An endpoint or request feature Palimnesis doesn't support. | See [`docs/capabilities.md`](docs/capabilities.md). |
| 400 `context_budget_exceeded` | The part that can't be masked (system prompt, tool schemas, the current message) doesn't fit. Nothing was archived. | Shorten the input or raise the server's context. |
| 409 `history_divergence` | The client's history no longer matches the archive, after undo, revert, fork or a manual `/compact`. | Start a new chat. |
| 502 `upstream_unreachable` / `upstream_failed` | Strata is down or returned an error. | Check the Strata server. |
| 503 `archive_unavailable` | The archive couldn't commit the request. | Check disk space and that no other proxy owns the database. |
| 504 `deadline_exceeded` | The request ran past its overall time limit. | Retry. Long generations on slow hardware can hit it. |

## Project status

Version 0.1.0, under active development. The plan is [`docs/v1_plan.md`](docs/v1_plan.md), amended by [`docs/amendments/`](docs/amendments/). Each phase's measured results are in [`docs/results.md`](docs/results.md), and its design decisions in [`docs/decisions.md`](docs/decisions.md). What the proxy guarantees is stated in [`docs/contracts.md`](docs/contracts.md).

**Development tools** are in [`eval/`](eval/):
- `eval/replay.py CAPTURE_DIR --target URL` replays captures against Strata or the proxy.
- `eval/replay.py --explain DB` explains every prompt-cache change between upstream calls.
- `eval/bench_passthrough.py` measures passthrough overhead.

Run each with `uv run python`.

## License

MIT. See [`LICENSE`](LICENSE) and [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
