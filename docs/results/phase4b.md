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

## R45: Pi's development needles through Palimnesis (S14, 2026-11-05, development data, reported, not gated, per D81.6)

**Outcome: 42/60 loose exact (70%).** 14 of the 18 misses are answers the model cut short. Every archive and accounting check is clean.

- **Setup:** `eval/needle.py run --driver pi --protocol chat --config a4-d77 --set development`, one attempt. Real Pi 1.5.0 ran on Windows with the shipped adapter. Strata 0.1.54 ran on pythia (32K, one slot) through the tunnel. The code was that of `bbcf570`, which includes the D97 fix. The first attempt stopped at dev-h1 Q4 with the 409 D97 fixes; this is the rerun.
- **Records:** `C:/Users/Daniel/palimnesis-runs/pi-dev-needles-chat2/` (records, 107 upstream bodies) and its `.log`. Wall time was 83.7 min.

| Loose exact | 95% Wilson | History-clustered bootstrap | Strict exact | Needle in view / excerpt / absent | Exact when absent | Lookups | Early stops | Prompt / completion tokens |
|---|---|---|---|---|---|---|---|---|
| 42/60 (70%) | 57.5–80.1% | 45.0–91.7% | 34 | 47 / 46 / 2 | 0/2 | 0 | 14 | 1.95M / 27K |

- **Per history:** dev-h2 and dev-h4 scored 10/10 and dev-h3 9/10 (h3 q7 was the right value with extra text, as in R41). dev-h1 scored 6/10, dev-h5 3/10 and dev-h6 6/10. The early stops all fall in these three histories.
- **The other misses:** h5 q8 and h6 q8 (`multi_fact`) gave wrong values with the needle out of both the view and the excerpts. Pi did not search its transcript directory for either, although it did in R43's gate. OpenCode answered all 22 of its absent needles in R41, with 41 lookups.
- **Gate inputs, all clean:**
  - `--explain`: 101/101 pairs explained, 0 unexplained;
  - `transcripts verify`: 6/6;
  - over-budget inputs, view-disabled events, unbounded forwards and errored questions: 0 each;
  - leak scans: 0 leaks and 0 echoes over 40,697 client and 258 transcript texts; 0 internal hard leaks;
  - 0 hidden calls and 0 foreign requests.
- **D97's empty-reply rule held live.** dev-h1 P2 again got a reasoning-only reply, and Pi's next request left it out without a 409.

**R45-A. The early stops: a cascade from one cut answer.** Each of the three histories starts with one cut answer, `1` for `1.25s` (h1 q4), `fix/quillctl-config-` (h5 q2) or `6` for `6.0s` (h6 q4). Most answers after it in the same session are cut the same way, all finishing `stop`: `2` for `22s`, `9` for `9299`, `r` for `r2026.10.19-hf5`. This is D97.2's finding, now seen across a whole run. Exact upstream bodies were replayed directly to Strata, with no proxy, and sent unchanged except where a form says otherwise. Scripts and data are in the session scratchpad, `r45/` (`ablate.py`, `ablate-r45*.json`).

| Prompt | Pi's request | No `reasoning_effort` | OpenCode 2.1.4's system prompt | Pi's prompt without "Be concise in your responses" |
|---|---|---|---|---|
| h1 q4, the first cut | 3/14 cut | 2/6 | 1/6 | not run |
| h1 q5, after `1` in history | 6/6 | 4/6 | 5/6 | not run |
| h5 q2, the first cut | 2/8 | not run | 0/8 | 0/8 |
| h6 q4, the first cut | 5/8 | not run | 2/8 | 4/8 |

- **The cascade does not depend on the prompt.** Once a cut answer is in the history, the next answer is cut in 4–6 of 6 calls under every form. When the earlier cut answer was corrected in the history, the next answer came back whole (D97.2).
- **Pi's system prompt may raise the first cut, but the evidence is weak.** On h5 q2 and h6 q4 together it cut 7 of 16 calls, against 2 of 16 with OpenCode's system prompt (Fisher p ≈ 0.11). Removing only Pi's "Be concise in your responses" rule gave 4/16. h1 q4 cut at about the same rate under every form. Effort is not the cause: Pi sends `reasoning_effort: medium` and OpenCode sends none, and neither form changes the rate.
- **Why R41 saw none of this:** R41 ran OpenCode on ho3, a different set, so the two runs cannot be compared. An OpenCode run on the development set would separate the harness from the set; it was not run.
- **What Palimnesis can and cannot do here:** the proxy sets no sampling parameters and does not rewrite the client's history (R38-D, D75). The cut answer is the model's own reply, which Pi resends verbatim. This is recorded as a model behaviour on Pi's sessions, as D97.2 decided. Two follow-ups are backlogged, neither tried here: a harness-side temperature, and an OpenCode development-set run.
