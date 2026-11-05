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
| Server | Strata 0.1.48 (`/props` `build_info`); 0.1.54 accepted as an equivalent build (D76: same template, same counts on all 210 cases) | `docs/probes/strata.md` §1; `PIN.json` `equivalent_builds` |
| Model | `qwen3.8-flash-next-iq3_xxs` (hybrid recurrent, MTP) | §1 |
| Chat template | sha256 `12827f24b742ea4e80cdc12dbcf9622227056b9f797252a3149263d4f9aaadce` | `eval/probes/fixtures/strata_chat_template.jinja` |
| Tokenizer | `Qwen/Qwen3.8-Flash-Next` `tokenizer.json`, loaded without its NFC normalizer, with added-token strings inside messages counted as text (D46, D47); 210 recorded counting cases exact against the server, plus `tool_choice` (p16) | §4, §11 |
| `n_ctx` | read at runtime (observed 32768, then 65536) | §0 |

Backend specifics sit behind a backend-neutral upstream profile (D15 amended, D21). v1 ships one profile, `strata-0.1.48`. A llama.cpp profile, with its own probe suite, is later work. Until then, `--passthrough` relays to any OpenAI-compatible server, but bounded views, budgets and excerpts require a pinned profile.

## Endpoints

Modes: archive mode (`palimnesis serve`, the default, with `--db`) archives and reconciles chat requests; `--passthrough` relays everything unchanged.

| Client endpoint | `--passthrough` | Archive mode | Notes |
| --- | --- | --- | --- |
| `POST /v1/chat/completions` (stream) | relayed | **supported (Ph1)** | first-harness path; live-verified with OpenCode |
| `POST /v1/chat/completions` (non-stream) | relayed | **supported (Ph1)** | no first-harness traffic; fake-upstream tests only |
| `POST /v1/messages` (+ `count_tokens`) | relayed | archived (Ph4B S4, D87): the Messages subset of contracts §16, upstream always Chat; `count_tokens` relayed unarchived; supported for Pi (R43) | Strata's own errors lack Anthropic's envelope (archive mode adds it, D88); final `usage.input_tokens` is 1 |
| `POST /v1/responses` and any other `POST` | relayed | rejected, `unsupported_feature` | upstream is stateless |
| `GET`/`HEAD`/`OPTIONS` (`/v1/models`, `/props`, `/health`) | relayed | relayed | metadata |

## Harnesses

| Harness | Version | Endpoint | Status | Setup |
| --- | --- | --- | --- | --- |
| OpenCode | 2.1.4 | Chat Completions | first harness (Ph0–3); proactive excerpts and transcript-file fallback (gate passed, D37); hidden recall tools with `--hidden-tools` (Ph3B, streaming requests) | `harnesses.md` |
| Pi | 1.5.0 | Chat Completions / Messages | **supported** (Ph4B): adapter in `integrations/pi/` (D91); recorded sessions replay on both protocols; live smoke on both protocols and the transcript gate passed through the proxy against Strata (R43, D93); transcript-file fallback | `harnesses.md`, `docs/probes/pi.md` |
| Claude Code | 2.1.318 | Messages | **backlogged: closed source** (user, 2026-11-05; D92, `backlog.md`). Probes kept in `docs/probes/claude_code.md` | — |

## Chat Completions request features (first harness)

| Feature | Status | Notes |
| --- | --- | --- |
| `system`, `user`, `assistant`, `tool` text messages | supported (Ph1) | |
| `developer` role | rejected (Ph1) | OpenCode sends `system`; Pi's adapter sets `supportsDeveloperRole: false`, so Pi sends `system` (D82, D91) |
| User content as an array of text parts | supported (Ph4B, D91) | Pi's default; parts join with `""`, as Strata joins them, so it hashes and renders like the same string |
| `reasoning_content` on assistant turns (vendor extension) | supported (Ph1) | archived separately; reconstructed for every earlier turn (contracts §9) |
| `tools` (function), `strict` | supported (Ph1) | upstream renders the bare form |
| `tool_choice: "auto"` | supported (Ph1) | |
| `tool_choice: "none"` | supported (Ph3) | OpenCode step-limit step; Strata renders no tool schemas, and the counter matches (p16, D50) |
| Other `tool_choice` forms, `parallel_tool_calls` | rejected (Ph1) | |
| `max_completion_tokens`, `max_tokens` | supported (Ph3) | request-wide allowance (contracts §7); with both, `max_completion_tokens` wins, as on Strata (p16) |
| `stream_options.include_usage` | supported (Ph1) | upstream always puts usage on the finish chunk |
| `reasoning_effort`, `chat_template_kwargs.enable_thinking` | passthrough | full-prefix invalidation cause |
| `chat_template_kwargs.preserve_thinking`, `reasoning_format` | rejected (Ph1) | ignored upstream; accepting them would misstate behavior |
| Image / audio content parts | rejected (Ph1) | multimodal not listed |
| `n > 1`, `logprobs`, `response_format` | rejected (Ph1) | |

## Anthropic Messages request features (Pi; Phase 4B)

The subset and its mapping are contracts §16; in short:

| Feature | Status | Notes |
| --- | --- | --- |
| `system` (string or text blocks), user/assistant text, `thinking`, `tool_use`, `tool_result` (string or text blocks, `is_error`) | supported | mapped to the neutral Chat form as Strata's Messages route renders it (D84, D86); M2 parity corpus exact |
| `role: system` mid-conversation | supported | kept as `system`; rendered as `user` upstream, as Strata does; never an instruction (D86) |
| `tools` (`name`, `description`, `input_schema`, `cache_control`, `eager_input_streaming`), `tool_choice` `auto`/`none` | supported | other `tool_choice` forms rejected |
| `thinking` `enabled`/`disabled`/`adaptive`, `budget_tokens`, `display`; `output_config.effort` | supported | mapped to `reasoning_effort`; `budget_tokens` maps to a level only, not a hard cap (D84) |
| `cache_control`, `signature`, `metadata.user_id` | accepted, not rendered | `cache_control` is outside the content hash and the fingerprint |
| `?beta=true` | accepted | any other query string is rejected |
| `redacted_thinking`, images, documents, server tools, `stop_sequences`, `top_k`, `context_management`, unknown fields | rejected | `400 unsupported_feature` in Anthropic's envelope |
| Streaming output | supported | `message_start` … `message_stop`; thinking with an empty signature (O-4B-2); one `event: error` on failure; `event: ping` keepalives (D85, D89) |
| Hidden recall tools | not offered | Chat only (Phase 4B position 1) |

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

## Known limits

Phase 3 is accepted on the configuration `serve` ships since D78, `a4-d77` (R41, R42).
- **ho3 at 32K:** it passed 5 of 5 coding tasks against 4 of 5 for OpenCode's own compaction, passed the restart task, and answered 115 of 120 needles.
- **Phase 3's first configuration, `a4-d43`,** failed its coding gate at 32K: 3 of 5 against 5 of 5, and the restart task failed (R25). It is still available as `--no-protect-turn --retrieval r1 --notes 0 --notes-format n1 --notes-header h1`.
- **The evidence:** one attempt per task and arm, one model (the pinned Strata build), one harness (OpenCode 2.1.4), 32K only, on pythia (D76). Results there are not compared with Zeus runs.

Every limit below is rejected or documented, never silent. Resolved limits of earlier phases are recorded in `docs/results/`.

### Sessions and the archive

- **One serialized branch per session.**
  - Edits, undo, revert, fork and rewind get `409 history_divergence`; start a new session.
  - Concurrent requests get `409 session_busy` or `409 request_in_progress`.
- **Interrupted turns are never resumed automatically.**
  - After a crash or a failed stream, a resend that repeats an already-answered request gets `409 ambiguous_retry`.
  - OpenCode's own resend of a flattened partial is accepted (D10.3).
  - A reply interrupted from the client side may be dropped by the next request (D13.1).
- **Idempotent replay** covers completed non-streaming results only. Repeated streaming keys get `409 streaming_replay_unsupported` (Ph8).
- **Archive growth is unbounded.**
  - There is no deletion, export or disk budget yet (Ph8). Measured growth is in results R6 and R8.
  - To delete, remove `palimnesis.db*` and `transcripts` with the proxy stopped.
- **Durability.** Process crashes are tested; power-loss durability is not claimed (Ph8).
- **Per-request cost grows with history.** Accept reloads the whole branch (R8: TTFB p50 rises from 8 to 16 ms over 50 turns).

### Bounded view and its cost

- **Masking only on overflow.** Bounded views mask only when the history would cross the high watermark; below it the client's body is forwarded byte-identical. `--view off` keeps budgets and rejects over-budget history instead of masking.
- **Watermark moves cost a deep re-read.**
  - Strata keeps 6 checkpoints, so a move typically re-reads the post-move target, about T tokens.
  - Frequency: a move every 7–11K ingress tokens at a 24K budget, and every 15–24K at 48K (R12).
  - Live at a 12K budget, each move re-read 4.6–5.0K tokens in about 14.5 s, against a 762 ms median for append turns (R14). At 48K that scales to about 60 s (estimate).
  - At small budgets with large outputs, moves can come almost every turn (D24.2).
  - The addendum adds one re-read of the head per session when it is fixed (D36).
- **Working notes cost one upstream call per collapse** (D72). The client's request waits for it: 15–18% of task wall time on ho2 (R40-B). A failed refresh keeps the notes the view had, and is recorded.
- **The notes slot is a fixed 2,048 tokens** (D78.5).
  - It was measured only at a 24,320-token input budget.
  - Admission and the startup floor reserve it (D79), so below about 8,000 input tokens it takes too much of the view; use `--notes 0` there.
- **A second collapse inside one request sends no refresh.** A rebuild with the new notes or an excerpt block can, rarely, advance the collapse again; that move keeps the notes just written without another refresh call (R42).
- **Some internal size estimates run a few tokens low.** Previews, the recent window and excerpt charges are sized on text with tags live (D46.4). The assembled request is counted exactly, so the budget holds.

### Recall

- **No recall by address by default.** The model reaches hidden content through proactive excerpts, and through the transcript files with its harness's own grep and read tools. Hidden recall tools exist behind `--hidden-tools` (below).
- **Transcript lookups cost calls.** Each search or read is a harness tool call and a model round trip. D63 removed the two overheads R25-E found: in-progress turn files now keep a stable name, and turn 0 is marked as the system prompt already in view.
- **Excerpts are chosen once per instruction** (§13). Tool-result steps never select, so in a long agentic turn, content that leaves the view mid-turn is reachable only through the transcript files.
- **Retrieval is lexical.** q1 ranks with BM25 over FTS5 chunks, and r2, the default, leaves the model's reasoning out of the candidates (D71). There are no embeddings, so an instruction that shares too few words with the evidence gets no excerpt.
- **Sessions started before D78 keep their stored excerpts.** An excerpt block is chosen once and reused (§11), so a block selected under r1 can still quote reasoning after an upgrade; new selections use r2.
- **Recall answers can carry extra text** (R41-A). In 5 of 120 held-out needle answers, the model first went back to the coding task and then gave the right value with commentary.
- **Transcript files rely on filesystem permissions.** OpenCode's shell tool bypasses its `external_directory` rule (`harnesses.md`).

### Hidden recall tools (Phase 3B, off by default)

`--hidden-tools t1|t2` (contracts §15) failed both Phase 3B held-out gates (R32): 97 of 120 needles against the 85% bar, and 2 of 5 coding tasks against native compaction's 4. They stay off by default and there is no `phase-3b` tag (D64).

- **Streaming requests only** (D55). A non-streaming request gets no hidden tools.
- **One visible message per response, but its text order can change upstream.** Text the model writes after a tool call, hidden or external, is re-rendered before the call in later requests (one content field per message), so from that point the prompt differs from what the model generated.
- **Dropping the tools costs re-reads.** A `tool_choice: "none"` request in a session with hidden tools renders no tools, which re-reads the whole prompt, and so does the next request that restores them.
- **Other clients of the same Strata** can still run between two requests: admission holds the slot for a whole response and its `/status` guard waits for other clients' work before dispatch, but cannot stop a client that bypasses the proxy (D89).
- **Continuation reuse estimates are low** by the generated turn (41–70 tokens in probe P3). They are labelled estimates; no gate reads them.
- **A `length` stop** (allowance or §15 limits) makes OpenCode send its own follow-up turn at once (`docs/probes/opencode_hidden_stream.md`).

### Deferred

- **Phase 4B:** Pi's fault, restart and cancellation runs through the proxy, development needles and tasks (plan §6, S14).
- **Backlog:** Claude Code (`backlog.md`, D92).
- **Phase 3B, not built:** continuation accounting across internal calls, and RE2 regex search.
- **Phase 8:** streaming replay, deletion and export, and power-loss durability.
