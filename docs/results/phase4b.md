# Phase 4B results

## R43: Pi 1.5.0 live through Palimnesis (S13, 2026-11-05)

- **Setup:** Pi 1.5.0 on Windows with the shipped adapter (`integrations/pi/`) and a throwaway agent directory, talking to `palimnesis serve` (serve defaults, `a4-d77`) on the same machine. Its upstream was Strata 0.1.54 on pythia (32K, one slot) through an SSH tunnel.
- **Commit:** after `62e554a`, with the D93 accounting rule.
- **Driver:** `eval/probes/pi_live_smoke.py smoke gate`. Summary in `eval/probes/fixtures/pi-1.5.0/live/summary.json` (paths replaced).

| Scenario | Turns | Requests | Answer | `--explain` unexplained | `transcripts verify` | Failed attempts | View moves |
|---|---|---|---|---|---|---|---|
| smoke, Chat | read `notes.txt`, then a follow-up | 3 | "Thursday" both turns | 0 | pass | 0 | 0 |
| smoke, Messages | the same | 4 | "Thursday" both turns | 0 | pass | 0 | 0 |
| gate, Chat, budget 8,000 | read 4 logs (about 5K tokens each), delete `log1.txt`, ask for its code, then confirm from the transcript | 14 | `ZX-4471-QUAIL`; confirmed by Pi's `grep` on the session directory (`turn-0001.md:114`) | 0 | pass | 0 | 5 |

- **How the code was answered.** In the gate, the code came from a proactive excerpt (one selected block held it). The confirming turn then reached the transcript files with Pi's own `grep`, which is the capability the gate checks (D37's criterion).
- **The first gate run** found one unexplained pair, a main call right after its own notes refresh. D93 explains it and adds the rule; both runs above are after the fix.
- Turn times were 4–85 s; the longest were the 5K-token file reads with thinking.

## R44: Pi's faults, cancellation and restarts through Palimnesis (S14, 2026-11-05)

The plan §6 gates for fault runs, restart and cancellation. All runs are after D94, at `d573f54` plus this slice.

**Fault runs** (`eval/probes/pi_probe.py hx_*`, summarized by `eval/probes/pi_proxy_faults.py`; `eval/probes/fixtures/pi-1.5.0/live/proxy_faults.json`):
- Setup: Pi 1.5.0 with the adapter's compat flags and its own default timers, then `palimnesis serve` in archive mode, then the Pi fault server. The fault server has no `/props`, so bounded views stay off; the archive, stream, error and admission paths are what these runs exercise.
- Scenarios: the twelve HP4 scenarios on both protocols, and the partial ones also with Pi's retry off. That is 34 runs, all passing.
- **No silent duplicate generation:** at most one completed attempt per archived request in every run.
- **Statuses** (500, 429, 503 with `x-should-retry: false`). Pi retries anyway (HP4.2). The proxy records the failed attempt and then completes the same request: one request, two attempts, one generation.
- **Partial streams** (EOF, reset, upstream error, tool-call error). The proxy ends the stream with its in-stream error, and Pi does not retry. Pi's next turn leaves the partial out, and the archive supersedes it (O-4B-5).
- **Length stop:** see D94. All four runs pass after the fix.
- **Header delay 8 s and 12 s of comments** with Pi's default 300 s timers: one request each, success.
- **`finish_no_done`** (a finish chunk, then EOF with no `[DONE]`): both turns fail through the proxy, by contract §3. Strata always sends `[DONE]` (`docs/probes/strata.md` §13.1), so this is a fault-server shape; it is listed as expected, not a defect.

**Cancellation** (`eval/probes/proxy_cancel_release.py`; `proxy_cancel_release.json`): a client disconnect through the proxy against Strata 0.1.54 on pythia, three trials each.

| Close point | Release (Strata `/status` free) | Archive |
|---|---|---|
| Decode, after about 40 content pieces | 0.17–0.27 s | `cancelled` ×3 |
| Prefill, 3 s into a prompt of about 12K tokens | 6.95–7.00 s | `cancelled` ×3 |

Decode is under contracts §8's 1 s. Prefill releases at the end of the current 8,192-token chunk, as Strata cancels only at chunk boundaries (`docs/probes/strata.md` §9).

**Restart** (`eval/probes/pi_live_smoke.py restart`; `restart.json`): Pi on Chat with a budget of 8,000. The proxy restarted after each of three 5K-token file reads, and a last turn asked for the code from the first file, which had been deleted.
- Pi answered `ZX-4471-QUAIL`.
- 11 requests and 3 view moves; no failed attempts.
- `--explain` 0 unexplained: each call after a restart is explained by re-rendering the previous call (D14.8).
- `transcripts verify` passes.
