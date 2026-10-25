# Capability matrix

What Palimnesis claims, per endpoint and harness. Anything absent is unsupported and, once rewriting exists, rejected with `unsupported_feature`. Status values:

- **passthrough**: relayed unchanged.
- **supported (Ph N)**: rewritten and archived from that phase.
- **planned (Ph N)**: on the roadmap.
- **rejected**: refused with a documented error.
- **untested**.

## Pinned upstream

| Item | Value | Source |
| --- | --- | --- |
| Server | Strata 0.1.48 (`/props` `build_info`) | `docs/probes/strata.md` §1 |
| Model | `qwen3.8-flash-next-iq3_xxs` (hybrid recurrent, MTP) | §1 |
| Chat template | sha256 `12827f24b742ea4e80cdc12dbcf9622227056b9f797252a3149263d4f9aaadce` | `eval/probes/fixtures/strata_chat_template.jinja` |
| Tokenizer | `Qwen/Qwen3.8-Flash-Next` `tokenizer.json`; 19/19 exact against server | §4 |
| `n_ctx` | read at runtime (observed 32768, then 65536) | §0 |

Backend specifics sit behind a backend-neutral upstream profile (D15 amended, D21). v1 ships one profile, `strata-0.1.48`. A llama.cpp profile, with its own probe suite, is later work. Until then, `--passthrough` relays to any OpenAI-compatible server, but bounded views, budgets and excerpts require a pinned profile.

## Endpoints

Modes: archive mode (`palimnesis serve`, the default, with `--db`) archives and reconciles chat requests; `--passthrough` relays everything unchanged.

| Client endpoint | `--passthrough` | Archive mode | Notes |
| --- | --- | --- | --- |
| `POST /v1/chat/completions` (stream) | relayed | **supported (Ph1)** | first-harness path; live-verified with OpenCode |
| `POST /v1/chat/completions` (non-stream) | relayed | **supported (Ph1)** | no first-harness traffic; fake-upstream tests only |
| `POST /v1/messages` (+ `count_tokens`) | relayed | rejected, `unsupported_feature` (planned Ph4B) | upstream errors lack Anthropic's envelope; final `usage.input_tokens` is 1 |
| `POST /v1/responses` and any other `POST` | relayed | rejected, `unsupported_feature` | upstream is stateless |
| `GET`/`HEAD`/`OPTIONS` (`/v1/models`, `/props`, `/health`) | relayed | relayed | metadata |

## Harnesses

| Harness | Version | Endpoint | Status | Setup |
| --- | --- | --- | --- | --- |
| OpenCode | 2.1.4 | Chat Completions | first harness (Ph0–3) | `harnesses.md` |
| Pi | 1.4.0 | Chat Completions / Messages | planned (Ph4B) | `docs/probes/harnesses.md` |
| Claude Code | 2.1.310 | Messages | planned (Ph4B) | `docs/probes/harnesses.md` |

## Chat Completions request features (first harness)

| Feature | Status | Notes |
| --- | --- | --- |
| `system`, `user`, `assistant`, `tool` text messages | supported (Ph1) | |
| `developer` role | untested | OpenCode sends `system`; Pi sends `developer` |
| `reasoning_content` on assistant turns (vendor extension) | supported (Ph1) | archived separately; reconstructed for every earlier turn (contracts §9) |
| `tools` (function), `strict` | supported (Ph1) | upstream renders the bare form |
| `tool_choice: "none"` | supported (Ph3) | OpenCode step-limit step |
| Other `tool_choice` forms, `parallel_tool_calls` | untested | |
| `max_completion_tokens`, `max_tokens` | supported (Ph3) | request-wide allowance (contracts §7) |
| `stream_options.include_usage` | supported (Ph1) | upstream always puts usage on the finish chunk |
| `reasoning_effort`, `chat_template_kwargs.enable_thinking` | passthrough | full-prefix invalidation cause |
| `chat_template_kwargs.preserve_thinking`, `reasoning_format` | rejected (Ph1) | ignored upstream; accepting them would misstate behavior |
| Image / audio content parts | rejected (Ph1) | multimodal not listed |
| `n > 1`, `logprobs`, `response_format` | rejected (Ph1) | |

## Lifecycle features (first harness)

| Feature | Status | Requirement |
| --- | --- | --- |
| Linear session, one branch | supported (Ph1) | |
| Title generation | must be disabled | `harnesses.md` |
| `subagent` tool | must be denied | `harnesses.md` |
| Native compaction | must be disabled | `compaction.auto: false` |
| Undo, revert, fork, `/btw` | rejected (Ph1) | divergence error; no config switch exists |
| Continue-after-partial resend | supported (Ph1) | rewritten streams end failures with an in-stream error event plus `x-should-retry: false`; when OpenCode still resends a flattened partial plus "Continue…", it is reconciled against the archived partial (D10.3) |
| Streaming idempotent replay | planned (Ph8) | 409 recovery response until then |

## Known limits of the Phase 1 archive

These are the limits of the first usable release. They are rejected or documented, never silent.

- **One serialized branch per session.**
  - Edits, undo, revert, fork and rewind get `409 history_divergence`; start a new session.
  - Concurrent requests get `409 session_busy` or `409 request_in_progress`.
- **Interrupted turns are never resumed automatically.**
  - After a crash or a failed stream, a resend that repeats an already-answered request gets `409 ambiguous_retry`.
  - OpenCode's own resend of a flattened partial is accepted (D10.3).
  - A reply interrupted from the client side may be dropped by the next request (D13.1).
- **Idempotent replay** covers completed non-streaming results only. Repeated streaming keys get `409 streaming_replay_unsupported` (Ph8).
- **No bounded view yet** (Ph2). The upstream receives the client's full history, and `n_ctx` limits are the harness's and upstream's own.
- **Archive growth is unbounded.** There is no deletion, export or disk budget yet (Ph8). Measured growth is in results R6 and R8.
- **Durability.** Process crashes are tested; power-loss durability is not claimed (Ph8).
- **Per-request cost grows with history.** Accept reloads the whole branch (R8: TTFB p50 rises from 8 to 16 ms over 50 turns).

## Known limits of Phase 2

- **No excerpt retrieval yet.** Excerpt blocks are budgeted, stored, rendered and included, but the Phase 2 source selects nothing, so every recorded selection is empty. Proactive retrieval arrives in Phase 3 (A1).
- **Masked detail is not recallable by the model.** Beyond stub previews it stays out of reach until Phase 3's excerpts and transcript files. The archive keeps everything exactly.
- **No transcript-file fallback yet** (Phase 3, harness capability gate).
- **Masking only on overflow.** Bounded views mask only when the history would cross the high watermark; below it the client's body is forwarded byte-identical. `--view off` keeps budgets and rejects over-budget history instead of masking.
- **Watermark moves cost a deep re-read.** Strata keeps 6 checkpoints, so a move typically re-reads the post-move target (about T tokens). Measured: a move every 7–11K ingress tokens at a 24K budget and every 15–24K at 48K (R12). Live at a 12K budget, each move re-read 4.6–5.0K tokens in about 14.5 s, against a 762 ms median for append turns (R14); at 48K that scales to about 60 s (estimate). At small budgets with large outputs, moves can come almost every turn (D24.2).
