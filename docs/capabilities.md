# Capability matrix

What Mnemon claims, per endpoint and harness. Anything absent is unsupported and, once rewriting exists, rejected with `unsupported_feature`. Status values:

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

## Endpoints

| Client endpoint | Phase 0 | First rewritten | Notes |
| --- | --- | --- | --- |
| `POST /v1/chat/completions` (stream) | passthrough | supported (Ph1) | first-harness path |
| `POST /v1/chat/completions` (non-stream) | passthrough | supported (Ph1) | no first-harness traffic; fake-upstream fixtures only |
| `POST /v1/messages` (+ `count_tokens`) | passthrough | planned (Ph4B) | upstream errors lack Anthropic's envelope; final `usage.input_tokens` is 1 |
| `POST /v1/responses` | passthrough | rejected (until listed) | upstream is stateless |
| `GET /v1/models`, `/props`, `/health` | passthrough | passthrough | metadata |

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
| Continue-after-partial retry | suppressed once streams are rewritten (Ph1) | in-stream error event plus `x-should-retry: false` (contracts §5, Ph1); a resend carrying a flattened partial is a divergence |
| Streaming idempotent replay | planned (Ph8) | 409 recovery response until then |
