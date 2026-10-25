# Phase 2 live runs: forced-budget OpenCode and excerpt replay

Captured 2026-10-25, 01:58–02:10 UTC, from a `git archive` export of `1929c5c` (its `src/` differs from `ae71004` only in docstrings) plus the then-uncommitted eval files. Strata 0.1.48, `qwen3.8-flash-next-iq3_xxs`, `n_ctx` 65536, one slot, shared. Results entries: `docs/results.md` R14 and R15.

This folder holds sanitized summaries only: counts, ids, usage and accounting fields. There are no request or response bodies, headers or credentials; the archives, taps and captures stayed in the session scratchpad.

## Files

- `summary.json` (R14): from `scripts/analyze.py`. Per-request client status and timing, the exact Strata-counter count of every upstream body, `view_versions` rows, and each `upstream_call` event's accounting fields.
- `excerpt-replay.json` (R15): from `eval/live_excerpt_replay.py --report-only`. The `upstream_call` events, `view_versions` and `excerpt_blocks` rows (without the rendered text). The per-request stream log was printed during the run but not saved, because the first report step failed on a column name. That was fixed, and the report was rebuilt from the archive.
- `scripts/run_proxy.py`: `palimnesis serve` under the CLI's uvicorn config, wrapped in the R9 ASGI tap. It adds `--input-budget`.
- `scripts/oc_turn.py`: one isolated `opencode run --standalone --auto --format json [--session]` turn. The isolation is the same as R9/R10. `OC_ROOT` is required.
- `scripts/analyze.py`: read-only analysis. The DB is opened with `mode=ro`.

## Topology (R14)

```
opencode ──► palimnesis archive :9041 (--input-budget 12000, tap) ──► palimnesis --passthrough :9042 (--capture-dir, tap) ──► Strata
```

- **OpenCode config.** It is `../live/config/` with `baseURL` on port 9041. The plugin is renamed for Palimnesis: `PALIMNESIS_PROXY_ORIGIN` and an `X-Palimnesis-Kind` header, which the proxy strips.
- **Isolation.** HOME, XDG, TEMP and config directories were isolated. `OPENCODE_DISABLE_PROJECT_CONFIG` was set. `PWD` was a fresh git repo and stdin was at EOF.

Task, in one OpenCode session:

1. Create `stats.py` (mean, median, mode) and `test_stats.py`, then run the tests.
2. Add variance and stdev, test, and run.
3. Add percentile, test, run, read the file back and list its functions.
4. Add zscore, test, and run.
