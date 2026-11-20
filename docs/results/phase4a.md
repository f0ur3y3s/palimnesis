# Phase 4A results

## R61: S10, pinned state against none on 15 development tasks at emulated 32K (2026-11-18 to 2026-11-19, reported, not gated)

**Setup** (D107, D108):
- **Host:** Zeus, Strata 0.1.57, `qwen3.8-flash-next-iq3_xxs`, `n_ctx` 131,072, one slot, emulated 32K (`--input-budget 24320`).
- **Harness:** OpenCode 2.1.4 through `eval/tasks/run.py` at `822fdf3`, on a clean tree.
- **Arms:** `a4-d77` (serve's defaults: notes on) and `a4-tr` (the same without notes).
- **Tasks:** dev-t1..t5, ho2-t1..t5 and ho3-t1..t5, one designated attempt per task and arm.
- **Records:** `captures/phase4a-s10-822fdf3/` (gitignored). Collected by `captures/collect-phase4a-s10.py` into `phase4a-s10-summary-final.json`, with GL2 under D109's rule.

**Infrastructure:**
- **Two reruns, both a4-tr ho2-t3.** Attempt 1 was aborted when Windows Update restarted Zeus. Attempt 2 was cut off when the machine running OpenCode restarted. Attempt 3 is the designated one (D108).
- **Retried before model execution:** a4-d77 dev-t1 attempt 1, because the transcript root was refused inside the Git worktree.
- **One turn killed:** a4-tr ho2-t1 turn 8, at the 30-minute limit. The task still passed.

**D44.6 inputs, all 30 runs:**
- 0 unexplained cache changes (`--explain`), and `transcripts verify` passing. The two aborted ho2-t3 attempts also explain fully: 60 and 232 pairs, 0 unexplained.
- 0 over budget, 0 leaks or echoes, 0 drift and 0 proxy rejections.

**Foreign activity** (`foreign_between`/`foreign_during`, 1 or 2 on 7 runs) is our own requests counted late (R25-B), not outside traffic:
- **After the relaunch,** Strata's request counter read 1,404. That is the 1,402 calls our runs recorded, plus the call cut off by the restart, plus the launcher's one-token start check.
- **Before the relaunch,** the pattern is the same: one between and one during a call, with no gate event and no queued sample.

### Outcomes

| | `a4-d77` (notes) | `a4-tr` (no notes) |
|---|---|---|
| Tasks passed | **14/15** [0.70, 0.99] | 10/15 [0.42, 0.85] |
| Constraints held (all eligible) | **44/45** [0.88, 1.00] | 36/45 [0.66, 0.89] |
| Trap repeats (all eligible) | 0/15 | 0/15 |
| Upstream calls: main + notes refresh | 1,288 + 139 = 1,427 | 2,511 |
| Re-read tokens: main + refresh | 3.22M + 0.49M = 3.71M | 6.91M |
| Prompt time (main calls) | 36 min + refresh time not recorded | 72 min* |

- **Intervals.** Wilson 95% intervals. The constraint intervals treat 45 constraints as independent, but they cluster in 15 tasks.
- **Refresh time.** Refresh calls carry no `prompt_ms`, so a4-d77's prompt time leaves them out.
- **\*Prompt time is not a clean comparison.** a4-tr's last 8 runs came after the relaunch, with a cold cache and an untrained expert tier (D108).
- **Re-read tokens** are counted from the bodies and are unaffected.

**Paired by task** (one attempt each, so this shows direction, not effect size):
- **Tasks.** Four tasks passed with notes and failed without: dev-t5, ho2-t3, ho3-t1 and ho3-t5. None went the other way. ho2-t2 failed in both arms, and the other 10 passed in both. Sign test p = 0.125.
- **Constraints.** 8 held with notes and broke without, and none went the other way.
  - Six of the 8 are on tasks a4-tr failed anyway. Only dev-t2 C2 and ho2-t4 C2 broke on tasks that passed.
  - Counted per task (any constraint lost), it is 7–0, p = 0.016.
- **Calls.** a4-tr used more calls on 12 of 15 tasks, up to 5.4× on ho2-t2. Counting a4-d77's refresh calls, it used 57% of a4-tr's calls and 54% of its re-read tokens.
- **Confounds.**
  - Three of the four task differences (ho2-t3, ho3-t1, ho3-t5) are among a4-tr's 8 runs after Zeus's relaunch (D108). The relaunch used the same build and arguments, but whether a cold cache can change answers, and not only speed, was not tested.
  - The runs went in a fixed order, the baseline arm first.
  - With one attempt per task, all of this shows a direction, not an effect size.

**Eligibility.** Every run had at least 5 watermark or collapse moves after the first instruction, so every constraint and trap is eligible. In all 30 runs, the instruction that states the rules and the trap was collapsed out of view by the end.

### GL2: early constraints and traps

- **Constraints** are listed above. The one constraint a4-d77 lost (ho3-t4 C2) was lost by a4-tr too.
- **Traps: 0 repeats in 30 runs.**
  - **Pattern tasks (8 per arm):** 0 `code` hits under D109. The 6 `doubtful` hits were each read by hand: a demonstration in a shell command and one in a scratch script (a4-d77 dev-t1), a grep (a4-d77 dev-t4), a comment saying the code avoids `fnmatch`, both in the write and in the final file (a4-d77 ho2-t5, 2 hits), and a scratch script comparing `statistics.quantiles` with nearest-rank (a4-tr dev-t4).
  - **Manual tasks (7 per arm, 14 runs):** reviewed by hand from the final code (D107.7). None uses its trap. Each verdict names the deciding code, for example a stack rather than counts (ho3-t3), field enumeration rather than minute stepping (ho3-t5), and an explicit table before NFKD (dev-t2).
- **Traps do not separate the arms here.** Both arms avoided every trap, so these tasks cannot say whether a pinned state helps against repeated dead ends. The arms differ on constraints and task success instead.

### GL1: what a state commit costs

| Cause (a4-d77) | Pairs | Re-read tokens | Share |
|---|---|---|---|
| `state_commit` | 130 | 1,444,546 | 44.9% |
| `append` | 987 | 1,010,614 | 31.4% |
| `watermark_move` | 91 | 571,028 | 17.7% |
| `oversized_output` | 55 | 121,373 | 3.8% |
| `collapse` | 8 | 65,431 | 2.0% |
| `excerpt_omitted` | 2 | 6,347 | 0.2% |

- **The state's own share.** Of `state_commit`'s 1.44M re-read tokens, 214K is the notes block itself (`state_marginal_tokens`, about 1,640 per commit). The other 1.23M (`with_state_tokens`) is the rest of those pairs' re-read: mostly the collapse made in the same move.
- **The refresh calls**, reported apart: 139 calls and 2.89M prompt tokens, of which 2.42M were cached. They re-read 488K tokens, counted from each refresh's common prefix with the call before it (`eval/replay.py`).
- **Without notes,** a4-tr re-read 6.91M tokens. Of that, 2.23M is labelled `collapse` (227 pairs) and 1.84M `watermark_move`.
  - With notes, most collapses are labelled `state_commit` (130 pairs), because a pair's cause names only its first change.
  - So the arms' collapse counts are not comparable label by label. The totals are.

### The state itself

- **Versions:** 131 committed and 8 failed (7 empty replies, 1 tool call instead of notes), from 139 refresh calls.
  - 12 committed versions were taken from the reasoning (n2).
  - Every committed version but one reached the model in a later main call. ho3-t5's last version never rendered (D93's known cost, measured as D105.11 asks).
- **Cut (D105.6):** 12 versions were cut to fit the 2,048-token slot. 9 of the 131 (6.9%) lost a line under *Requirements and constraints* or *Dead ends*. That is under the 10% bar, so **the priority cut stays deferred**.
- **Cited addresses (F3):** only one session cited any, ho2-t5 with 4 citations, all `valid`. The model almost never writes addresses into its state unprompted. The n3 variant ("Useful addresses") stays a later decision (D105.7).

## R62: The pinned state on Pi through Messages (neutrality smoke, 2026-11-19)

- **Setup:** Pi 1.5.0 through `eval/tasks/run.py --harness pi --protocol messages`, `a4-d77`, dev-t1, on Zeus (Strata 0.1.57, `n_ctx` 131,072). Run at `c12cdf1`; no proxy code changed after `822fdf3`. Records in `captures/phase4a-pi-smoke-c12cdf1/` (gitignored).
- **Attempt 1, at emulated 32K (`--input-budget 24320`):**
  - Passed every D44.6 input, and the task passed 4/4.
  - But Pi's prompt peaked at 16,111 tokens, so the view never moved and no state was written. That does not meet the gate.
- **Attempt 2, at `--input-budget 12000`** (development data; the reason is recorded in `attempts.json`):
  - 36 calls, 8 turns, prompt peak 11,166 tokens.
  - **5 committed state versions** and 0 failed, each with its `notes_outputs` row (`reply`).
  - 0 unexplained changes, `transcripts verify` passing, 0 over budget, 0 leaks or echoes, 0 drift, 0 proxy rejections and 0 foreign requests.
  - The task passed 4/4, with constraints 3/3.
- **Gate (plan §4): met, at a smaller budget than planned (D110).** The same refresh path commits state for an Anthropic Messages client as for OpenCode's Chat. S7's HTTP test (`tests/test_state_protocols.py`) already shows the bodies are identical.

## R63: Phase 4A gate summary (2026-11-19)

| Gate or requirement | Evidence | Result |
|---|---|---|
| `a4-d77` unchanged by 4A | S0 goldens, plain and rich (`tests/test_state_golden.py`), recorded at `phase-4b` | pass |
| Provenance, retrievable originals, cited addresses | S2, S3 and S6 tests; D106 review fixes | pass |
| Conflict and isolation rules (contracts §17) | S5 tests | pass |
| Harness neutrality | S7 test; R62 live on Pi Messages at `--input-budget 12000` (D110); D109's detector reads every harness's write shapes | pass |
| **GL1:** explicit invalidations with measured prefix cost | 0 unexplained on all 32 designated archives and the 2 aborted ones (R61, R62); `--by-cause` per cause, with the state's own share (R61) | pass |
| **GL2:** early constraints and traps over at least 3 moves | Reported, not gated (D105.10): constraints 44/45 with the state against 36/45 without (7–0 by task, with the relaunch confound in R61); 0 trap repeats in 30 runs | reported |
| State aids navigation and never replaces instructions | Its header and authority rules (§17, S5 tests). The GL2 attribution of a held constraint to the state was not measured: the rule-stating turn was out of view in all 30 runs, but excerpts and transcripts could also carry it | partly |
| Independently releasable from 4B | `Settings()` keeps notes off (`notes_tokens` 0); `serve` ships `a4-d77` (D78), unchanged by 4A (S0 goldens) | pass |
| D44.6 inputs | All S10 and smoke runs (R61, R62) | pass |
| Deterministic suite | `uv run pytest -q` at the tag commit (see the tag message for the count) | pass |

- **Decided from the evidence:**
  - the priority cut stays deferred (6.9% < 10%, D105.6);
  - n3 stays a later decision. Its candidate arm (`a4-trn3h`) and the dev-state needles were not built or run (D107.10). The baseline shows the model rarely cites addresses (1 of 15 sessions);
  - the slot stays 2,048 tokens (D105.3). The optional 800-token arm was not run.
- **Still deferred:**
  - the 64K report run on pythia (D107.10);
  - skipping refreshes that never render (measured at 1 of 131, D105.11);
  - a state tool, background refresh, and model-facing access to dropped lines (plan §5).
- **Known limits carried over:** a refresh can happen twice across a crash (contracts §17); there is no refresh inside hidden continuations.
