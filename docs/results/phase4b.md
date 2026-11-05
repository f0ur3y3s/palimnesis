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
