# OpenCode 2.1.4 live baseline (Phase 0)

Captured 2026-10-24 (20:19–20:23 UTC). OpenCode 2.1.4 ran through the Mnemon passthrough proxy (`mnemon serve --capture-dir`, port 9011) to the live Strata server (`http://192.168.1.173:8080`, Strata 0.1.48, `qwen3.8-flash-next-iq3_xxs`, n_ctx 65536). OpenCode ran in an isolated config/data/home under the session scratchpad. Findings are in `docs/probes/opencode_live.md`.

## Layout

- `exchanges/<session>/<started_ns>-<nonce>/`: raw proxy captures (`request.json`, `request.body`, `response.json`, `response.body`), as written by `mnemon.capture`. The folder is named `exchanges/` because the repo `.gitignore` excludes `captures/`.
- `config/`: the exact isolated setup. It holds `opencode.json`, `plugins/mnemon.ts` (the `model.request` identity hook), `service.json` (disables the shared background service, so every command is standalone) and `env.sh` (the environment variables used).
- `reports/replay_direct.json`, `reports/replay_proxy.json`: `eval/replay.py --json` output against Strata directly and through a fresh proxy.
- `run/turn1.jsonl`, `run/turn2.jsonl`: `opencode run --format json` event output for each turn. `run/plugin.jsonl` is the plugin hook log, one line per model request.

## Sanitization

- `authorization` is `<redacted>` in every `request.json`, done by the proxy at capture time. The configured key was a dummy (`mnemon-local-dummy`); it appears nowhere in the bodies.
- Bodies are synthetic task content and are kept unmodified, so replay is exact.
- They include the scratch working-directory path in the system prompt's `<env>` block, and the `x-opencode-project` header (the throwaway repo's root commit hash).

## Exchanges

All are `POST /v1/chat/completions` on session `ses_e906e5405ffeVfiX2TzyrOhErb` (the OpenCode session ID, placed in the path by the plugin). All are `kind: primary` and stream with HTTP 200. Each ends with a `finish_reason` and `data: [DONE]`. `max_completion_tokens` is 8192 on every request.

| # | Folder | Turn | Msgs in | Model action | finish | prompt / cached / completion tokens |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | `…180634574900-117cabfb` | 1 | 2 | `write` hello.py (`print(2 + 3)`) | tool_calls | 5004 / 0 / 82 |
| 1 | `…198800272300-05c758f4` | 1 | 4 | `shell` `python hello.py` | tool_calls | 5107 / 5088 / 66 |
| 2 | `…201060849300-dac57381` | 1 | 6 | Final text "It printed `5`." | stop | 5189 / 5172 / 20 |
| 3 | `…245854825300-23ac3414` | 2 | 8 | `read` hello.py | tool_calls | 5261 / 5211 / 48 |
| 4 | `…248171004500-babd4ba7` | 2 | 10 | Text plus `question` tool (misreads the file; long reasoning) | tool_calls | 5344 / 5311 / 3699 |
| 5 | `…340150354000-ea85a829` | 2 | 12 | Text plus `edit` (wrong `oldString`; tool returns an error) | tool_calls | 9101 / 9043 / 1130 |
| 6 | `…371608488900-866853cd` | 2 | 14 | `read` hello.py again | tool_calls | 10279 / 10231 / 78 |
| 7 | `…374692646800-2d0c171a` | 2 | 16 | `edit` (adds `print(2 * 3)`) | tool_calls | 10392 / 10361 / 317 |
| 8 | `…383176744200-9e28161e` | 2 | 18 | `shell` `python hello.py` | tool_calls | 10731 / 10708 / 59 |
| 9 | `…385451151700-77a863e6` | 2 | 20 | Final text reporting `5` and `6` | stop | 10808 / 10791 / 221 |

- Exchange 4's `question` call got the tool error "This non-interactive run cannot ask the user questions…", which is visible in exchange 5's request.
- Exchange 5's failed edit produced a JSON error tool result.

Both are useful as fixtures for error-shaped tool results.

## Replay

```
uv run python eval/replay.py eval/fixtures/opencode-2.1.4/live/exchanges --target http://192.168.1.173:8080
uv run python eval/replay.py eval/fixtures/opencode-2.1.4/live/exchanges --target http://127.0.0.1:9000/s/<session>
```

Strata is a shared single slot, so run one replay at a time. Generated text differs on every run; compare status, finish reasons and stream structure.
