# Palimnesis

A local, lossless context proxy between an agent harness and a [Strata](#requirements) server.

- **Archives** every accepted message exactly, in a local SQLite database.
- **Bounds** what the model sees: when a chat outgrows the context, older turns are masked in the upstream copy only. The harness's own history is never rewritten.
- **Recalls** what the view removed: each new instruction gets a short block of matching archived excerpts, and the full history is published as transcript files the model can grep and read.

Nothing is summarized and nothing is deleted. The model works in a bounded view while the archive keeps the full history.

## Results

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/results-dark.svg">
  <img alt="Held-out results at a 32K context: Palimnesis passed 5 of 5 coding tasks against 4 of 5 for OpenCode's native compaction, with 53% of the prompt tokens and 42% of the upstream calls, and recalled 115 of 120 needles exactly. Per task it took 33 to 61 minutes against 42 to 156, and 53 to 103 upstream calls against 67 to 249." src="docs/images/results-light.svg">
</picture>

On a fresh held-out set (`ho3`), with real OpenCode 2.1.4 and a local model at a 32K context, Palimnesis passed every coding task, while native compaction failed one. It also used about half the prompt tokens. Recall of facts from earlier in a session cleared the 85% bar. These are one attempt per task and arm on one host, so they show the direction of the effect, not its exact size. Full tables, method and caveats: [results R41](docs/results/phase3-acceptance.md#r41--d77-held-out-run-a4-d77-on-ho3-2026-11-0405-pythia-held-out-per-d77). The figure is drawn by `eval/readme_figures.py` from those tables.

## In plain terms

A local model has a small desk. It can only look at so many pages of your conversation at once, and a long coding session soon has more pages than fit.

Most tools handle this by **rewriting old pages into a short summary** and throwing the originals away. The summary is lossy: the exact error message, the file path, the number you mentioned an hour ago are often gone, and the model can't get them back.

Palimnesis does it differently:

- **It keeps every page,** exactly as written, in a filing cabinet on your computer (the archive).
- **It keeps the desk tidy.** When the desk gets full, it takes the oldest pages off the desk, never out of the cabinet. Your tool still has its full copy of the conversation; only what the model is shown changes.
- **It hands back what matters.** Each time you ask something new, it looks through the cabinet and puts the most relevant old snippets on the desk. And it tells the model where the cabinet is, so the model can search it and read any old page word for word.
## The research behind it, and what held up

Five sources shaped the design. Each was a starting point, not a spec: [`docs/contracts.md`](docs/contracts.md) decides behaviour, and [`docs/papers.md`](docs/papers.md) lists every adaptation. R numbers below are entries in [`docs/results/`](docs/results/README.md), and D numbers are entries in [`docs/decisions/`](docs/decisions/README.md).

| Source | What it was for | What we built from it | Status |
|---|---|---|---|
| [The Complexity Trap](https://arxiv.org/abs/2508.21433) | Evidence that plain, deterministic masking of old tool output competes with LLM summarization | The bounded view: old results become stubs, old turns collapse into spans | Shipped, with changes |
| [ARC](https://arxiv.org/html/2607.25066v1) | Masking is safe only if every hidden item stays exactly addressable | Exact archive addresses; hidden recall tools the model could call by address | Addresses shipped; the tools failed their gates |
| [Eunoe](https://github.com/chroxify/eunoe) (software, not a paper) | Proactive recall: quote matching history back before each new message, plus transcript files to search | Excerpt blocks on each new user message; per-session transcript files and a search recipe | Shipped |
| [LCM](https://arxiv.org/html/2605.04050v1) | Immutable history; an optional hierarchical summary DAG | The append-only SQLite archive | Archive shipped; the DAG is not built (optional Phase 5) |
| [RaMem](https://arxiv.org/abs/2606.22844) | Retrieval validity: evidence with its context and provenance | Nothing yet | Planned for the optional Phase 6 |

### The Complexity Trap: deterministic masking

- **Built:** a view that stays under the context budget without asking a model to summarize anything. Old tool results become stubs with a head and tail preview, and whole old turns collapse into one line that says they are archived. The view moves at hysteresis watermarks rather than every turn, so the prompt cache survives between moves.
- **Worked:**
  - It never overflowed: 0 over-budget inputs across every live run (R17, R27, R41).
  - Every prompt-cache change is accounted for, with 0 unexplained over thousands of call pairs (R17, R27, R42).
- **Didn't, at first:** masking alone lost coding tasks to native compaction, 3/5 against 5/5 (R25), and again 2/5 against 4/5 (R32).
  - The diagnosis (R33): the view hid the model's own work in the turn it was doing, and a stub says only "archived; not shown". Without that work the model invented history, rewrote files from memory, and re-ran tests that had not changed.
  - The paper keeps recent turns verbatim, and we had departed from that.
- **The fix:**
  - The current turn is now collapsed last (D70).
  - Excerpts no longer quote the model's own earlier reasoning, which had carried its mistakes forward as "evidence" (D71).
  - A small block of **working notes**, refreshed by the model at each collapse (D72), carries forward the goal, constraints and next step. The notes adapt native compaction's checkpoint, not a paper (R33-D).
  - With these, the shipped configuration passed 5/5 held-out tasks against native compaction's 4/5 (R41).

### ARC: exact, addressable recall

- **Built:** every archived item has a stable address, and the view's stubs and spans point at what they hide. In Phase 3B we added hidden recall tools: the model could fetch an item by its address inside one response, and the harness never saw the calls.
- **Worked:** the addressing itself. Excerpts, transcripts and accounting all rest on it.
- **Didn't:** the hidden tools failed both gates on held-out data: needles 97/120 against an 85% bar, and coding 2/5 against native compaction's 4/5 (R32).
  - 21 of the 23 needle misses were answers the model cut short.
  - On the coding tasks the tool arm used 1.6 times the prompt tokens of the masking-only arm (35.3M against 22.1M).
  - That masking-only arm passed only 2/5 there itself, which led to R33's diagnosis above.
  - The tools stay in the code, off by default, and are never offered on Anthropic Messages (D64, D87).
- **Not yet:** ARC's paired-outcome (McNemar) analysis is planned for the Phase 7 evaluation.

### Eunoe: proactive recall and transcript files

- **Built:**
  - Before each new user message is answered, a lexical search over archived content the view no longer shows quotes the best matches, exactly, in a delimited block appended to that message.
  - The block is fixed once chosen, so it doesn't break the prompt cache (R15).
  - The full history is also published as per-session transcript files, with a short recipe telling the model how to grep them and read only the lines it needs.
  - We adapted the search to 32–64K budgets and to code (D27–D29).
- **Worked:**
  - On the first held-out set, recall scored 120/120. The model answered all 31 needles that were absent from both the view and the excerpts by searching the transcript files (R25).
  - A header that names the current turn and says a later turn overrides an earlier one cut early-stop answers sharply: 1 against 14 in 120 (R22).
  - Pi found and used the transcript files with its own tools before it was listed as supported (R43).
- **Didn't, at first:**
  - Transcript lookups had real overhead. In one task only about half of 68 lookups found what the model was after. Some of the rest chased a file name that changed as the turn grew; that name is now stable (D63).
  - Quoting the model's own earlier reasoning hurt coding, as above (D71).
- **Not taken:** cross-session recall, and Eunoe's own context folding.

### LCM: immutable history

- **Built:** an append-only archive. Nothing the client sends or the model generates is rewritten or deleted. Even turns a client drops from its resend stay archived and are marked superseded. Transcripts can be rebuilt from the archive byte for byte.
- **Not built:** LCM's hierarchical summary DAG. The working notes now carry a short model-written summary of the current work; the DAG stays an optional phase.

### Open problems the research didn't predict

- **Answers cut short.** The local model sometimes stops after a token or two, giving "1" for "1.25s". Once one cut answer is in a session's history, later answers copy the pattern. It is the model's own sampling behaviour, reproduced directly against Strata without Palimnesis (R38, R45), and it hit Pi's sessions hardest. It is backlogged in [`docs/backlog.md`](docs/backlog.md).
- **Small samples.** Each held-out task ran once per arm on one host. The results show direction, not effect size.

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/).
- A **Strata 0.1.48** server, or 0.1.54, which D76 verified as an equivalent build, reachable over HTTP. Palimnesis counts tokens exactly as that build does, using a pinned template and tokenizer that ship with it. At startup it checks the server's build, template and a `count_tokens` canary against the pin. On a mismatch it still archives and forwards, but turns bounded views off.
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
| `--notes TOKENS` | `2048` | Working notes: before older messages leave the view, one extra upstream call has the model rewrite a notes block that stays in view. `0` turns them off; do so when the input budget is under about 8,000 tokens, where the slot takes too much of the view. |
| `--protect-turn` / `--no-protect-turn` | on | Collapse the current turn's own work last, so the model keeps sight of the steps it just took. |
| `--capture-dir DIR` | off | Store raw request and response bodies, for debugging and replay. **This writes conversation content to disk.** |

`--query-policy`, `--excerpt-renderer`, `--addendum`, `--retrieval`, `--notes-format` and `--notes-header` select variants for evaluation. Their defaults are the configuration the held-out run R41 passed (D43, D78); leave them alone.

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

Version 0.1.0, under active development. The plan is [`docs/plan/v1_plan.md`](docs/plan/v1_plan.md), amended by [`docs/plan/amendments/`](docs/plan/amendments/). Each phase's measured results are in [`docs/results/`](docs/results/), and its design decisions in [`docs/decisions/`](docs/decisions/). What the proxy guarantees is stated in [`docs/contracts.md`](docs/contracts.md). Labels such as `a4-d77`, `ho3` or `r2` are explained in [`docs/glossary.md`](docs/glossary.md).

**Known limits.** In the held-out evaluation that accepted Phase 3 (R41, 32K context), the shipped configuration answered 115 of 120 recall questions exactly and succeeded on 5 of 5 long coding tasks, against 4 of 5 for OpenCode's own compaction. Phase 3's first configuration had succeeded on 3 of 5 (R25). That is one attempt per task, one model and one harness; every known limit is listed in [`docs/capabilities.md`](docs/capabilities.md#known-limits-of-phase-3).

**Development tools** are in [`eval/`](eval/):
- `eval/replay.py CAPTURE_DIR --target URL` replays captures against Strata or the proxy.
- `eval/replay.py --explain DB` explains every prompt-cache change between upstream calls.
- `eval/bench_passthrough.py` measures passthrough overhead.

Run each with `uv run python`.

## License

MIT. See [`LICENSE`](LICENSE) and [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
