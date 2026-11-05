# Results: Phase 3B, hidden recall tools (R28–R32)

[Index](README.md) · Append-only; each entry names its commit, configuration and hardware.

## R28 — Phase 3B S10 development matrix: halted after arm B (2026-10-26, development data only)

**Outcome: S10 halted at its first possible defect signal, so no arm is selected.** The smoke run passed. The needle screen completed a4-d43, a5-A and a5-B. a5-B's leak scan then reported 1 hard leak: a hidden-result window in the client stream. The run stopped during a5-C, as the halt rule requires. The review below (R28-A) finds a false positive of `gate_inputs.internal_scan`, not a proxy leak; resuming is left to the lead. Not run: a5-C (killed after 17 questions; void), a5-D, selection (steps 3 and 5) and the development tasks (step 4). No held-out data was touched.

**Setup.**
- **Code:** `8055e02`, clean tree in every run (`git_provenance` dirty false). `src/` and `eval/` were not changed. Full suite: 1483 passed, 1 skipped.
- **Strata:** Zeus (D49), 0.1.48, `qwen3.8-flash-next-iq3_xxs`, RTX 4070 Ti SUPER 16 GB, one slot. `/props` reported `n_ctx` 65536 before and after each run.
- **Client host:** Windows 11 Pro 26200 (Intel64 Family 6 Model 204), Python 3.12.13 (venv), tokenizers 0.23.3, SQLite 3.53.1. OpenCode 2.1.4 for the smoke run.
- **Emulated 32K (O2):** `--input-budget 24320` at 65536.
  - The emulator does this natively.
  - The real-OpenCode tooling cannot: `oc_stack.Stack` starts the proxy with `serve`'s default budget (48,000 at 64K), and `run.py` sets arm 1's `limit.context` to `--expect-n-ctx`.
  - Runs therefore went through a scratch wrapper (`s10run.py`, not in the repo). It does four things:
    - starts every non-passthrough proxy child with `--input-budget 24320`, confirmed in the proxy log (`input_budget=24320`);
    - counts over-budget against 24,320;
    - would give arm 1 `limit.context` 32768 (not used here);
    - adds a halt watcher, a full per-call tap dump (R25-C), and a front tap between the emulator and the proxy, so the D62.4 leak scan can read the emulator's client stream.
  - Recorded as a deviation. The tooling needs an `--input-budget` option before S10 resumes.
- **Arm settings:** a5-* are arm 4's settings (q1, r1, x2, transcripts projected) plus stub / addendum / tools: A `s2/a1/t1`, B `s3/a1/t1`, C `s2/a0/t2`, D `s0/a1/t2`. Client output limit is 24,576 (O-B3); `deadline_s` 3600.
- **D39:** Strata's activity counter rose by exactly our upstream calls in every run: 806→828 (22), →951 (123), →1082 (131), →1238 (156), →1275 (a5-C's 37). 0 gate events. All runs are labelled unaffected.
- **Cache:** the smoke run came after 1.9 h idle (cold). The screen configs ran back to back; each session is new.
- **Raw data:** `…/scratchpad/s10-3b/`. Sanitized fixtures in `eval/fixtures/phase3b-dev/`:
  - `smoke/a5-A.jsonl` and `screen/{a4-d43,a5-A,a5-B}.jsonl`, written by `report.py --fixtures` (no bodies);
  - `summary.json`, per-arm figures from the upstream tap and the halt evidence.

**(1) Smoke run: dev-h1 under a5-A through real OpenCode, 17:43Z, 95 s.**

| Check | Result |
| --- | --- |
| Loose / strict exact | 10/10 / 10 (Wilson 72–100%) |
| Hidden calls answered | 10 calls (grep 9, recall 1), 10 results, 0 error results; continuations 7 over 15 responses (max 4) |
| `max_completion_tokens` | 24,576 on all 15 client requests; each upstream call carried 8,192 (R) |
| Hidden-recall leaks (D62.4) | 0 hard (stream calls, stream results, export calls, export results), 0 mentions |
| `--explain` | exit 0, 21/21 pairs, 0 unexplained |
| `transcripts verify` | pass (1/1) |
| Other inputs | Import faithful (101 messages, all prior turns `client_import`); 0 of 22 over 24,320; drift 0 of 22; excerpt leaks 0 / echoes 0; 0 proxy non-200s; 0 reachable records |

**(2) Needle screen (partial): dev-h1..h6 through the emulator (needle-emulator v2), one run per configuration, 17:45–18:12Z.**

Figures come from the upstream tap: every call, continuations included, attributed to its step by tap order. The emulator's own `calls.jsonl` keeps only a round's last call, and its client usage reports the last call's prompt (D61). `report.py`'s token and lookup columns therefore undercount arm 5 (a5-A prompt 1.84M there, 2.55M at the tap). "Unnecessary" counts questions whose needle was in view or in an excerpt and that still made a hidden or transcript lookup.

| Config | Loose exact /60 (95% Wilson) | Strict | Early stops (R21-C) | Not run | In view / excerpt / absent | Absent answered | Hidden calls (grep / recall / catalog) | Harness lookups | Invalid ids (Wilson) | Error results | Unnecessary: questions / calls | Upstream calls | Prompt / completion tokens, all steps | TTFVC p50 / p90 s | Latency p50 / p90 s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| a4-d43 | 51 (74–92%) | 51 | 8 | 0 | 9 / 44 / 9 | 7/9 | – | 33 | – | – | 5 of 51 / 7 | 123 | 2,316,806 / 13,255 | 2.9 / 10.3 | 3.0 / 10.5 |
| a5-A | 34 (44–68%) | 34 | 18 | 5 (dev-h6 Q6–Q10) | 12 / 40 / 7 | 4/7 | 49 / 10 / 0 | 0 | 0/10 (0–28%) | 5 invalid_arguments, 6 limit_reached | 8 of 48 / 23 | 131 | 2,554,914 / 19,782 | 2.7 / 9.6 | 2.7 / 10.2 |
| a5-B | 41 (56–79%) | 31 | 19 | 0 | 13 / 45 / 7 | 4/7 | 61 / 18 / 5 | 0 | **1/18 = 5.6%** (1.0–25.8%) | 4 invalid_arguments, 7 limit_reached, 1 bad_page, 1 unknown_block | 13 of 53 / 31 | 156 | 2,940,888 / 23,755 | 3.0 / 16.3 | 3.5 / 13.0 |

- **Paired with a4-d43** (both / only a4-d43 / only the arm / neither), loose exact: a5-A 27 / 21 / 7 / 0 (exact McNemar p 0.013); a5-B 40 / 11 / 1 / 8 (p 0.006). Pairs within a history are not independent, so these p-values overstate the evidence (R22).
- **Continuations:** a5-A 36 over 95 responses (max 4); a5-B 49 over 107 (max 4, 7 responses at 4).
- **The ranking is dominated by early stops, not by recall** (R28-B). One run per arm cannot separate them.
- **Sensitivity, early-stopped questions excluded** (loose exact over the questions that ran, less early stops):

  | Config | Loose exact | 95% Wilson | Misses left |
  | --- | --- | --- | --- |
  | a4-d43 | 51/52 | 90–100% | h2q9 |
  | a5-A | 34/37 | 79–97% | h3q8, h5q8, h5q10 |
  | a5-B | 41/41 | 91–100% | none |

  On this view the order is B ≥ a4-d43 ≥ A, the reverse of the headline counts for A and B. The headline ranking hinges on R21-C noise.
- **a5-B fails selection rule 1** (invalid ids above 5%) on 1 invalid id in 18 recall calls, an interval of 1–26%. The figure is one event, and per-arm recall counts this small cannot resolve the 5% threshold.
- **dev-h6 under a5-A stopped after P3.** The upstream ended a paste step's response with `length` inside `glob`/`write` arguments the model began while saving the paste. The emulator stops a history whose calls it cannot resend (R21). The 5 needles count as misses.

**Input checks (D44.6 / D62.4), per complete configuration** (a4-d43 / a5-A / a5-B):
- `--explain`: exit 0, 117/117, 125/125 and 150/150 pairs (= upstream calls − 6), 0 unexplained. Arm 5 adds `internal_continuation` pairs (34 and 42).
- `transcripts verify`: 6/6 each.
- Over 24,320 by the pinned counter: 0 of 123 / 131 / 156. Largest input 22,537 / 22,566 / 24,263.
- Count drift: 0 of 123 / 131 / 156, checked live on every upstream call.
- Excerpt leaks: 0 / 0 / 0. Echoes: 0 / 0 / 2 client + 2 transcript.
- Hidden-recall hard leaks: – / 0 / **1** (R28-A). Mentions (reported only): model 0 / 3 / 6, harness 0.
- Proxy non-200s and stream errors: 0. "views disabled" / "forwarding unbounded": 0 / 0. Reachable records are not applicable to the emulator.
- Relay: over all 410 upstream calls, the client stream's text equals the upstream calls' text in every response (assigned by arrival time).

**R28-A. The halt: a hard-leak hit in a5-B is a false positive of the leak scan.**
- **The hit.** Front call 68, session dev-h5, is the model's `write` call on paste step P1. It saves the pasted canary deploy log to `notes/…md`, including the line `2026-10-24T21:07:44Z INFO canary: new release tag r2026.10.17-hf9 …`.
- **The matched windows** come from hidden grep results in *other* sessions: dev-h2 seq 140 and dev-h3 seq 143. The deploy-log template and timestamp are shared across development histories (D45, "not everything is disjoint").
- **Why the scan called them distinctive:**
  - The archived paste reads `INFO  canary` with two spaces.
  - Grep snippets render it with one space, so the one-space window occurs in no earlier archived text on those branches.
  - The model's copy also has one space.
- **Why it cannot be a leak:**
  - The flagged response is a single upstream call (#92, `finish: tool_calls`) with no hidden call.
  - Session dev-h5's first hidden result comes later (seq 126), after the paste (seq 104) and these writes (105–111).
  - Its text is the model's copy of a paste in its own input.
- **Scan defects (eval/):** `internal_scan` matches windows of every session's results against every session's client stream, and grep snippets that normalize whitespace defeat the distinctiveness test. The same false positive could fail the D62.4 gate on ho2, because the needle driver also keeps all histories in one archive. Suggested fix: pair a session's results with that session's client stream only, and test distinctiveness on whitespace-normalized text. Not changed here.

**R28-B. Upstream early stops (R21-C) recur on Zeus under x2, and more often under arm 5.**
- **Rates:** 8, 18 and 19 per configuration (Wilson 7–24%, 20–43%, 21–44%). R22 saw 0–1 per 60 under x2 on bazzite.
- **Pattern:** they cascade within a history (a4-d43 and a5-B dev-h2, a5-A dev-h1, a5-B dev-h6), and the answer stops after its first characters (`9` for `9282`, `test` for `test_emit_empty_manifest`).
- **The same dev-h1 under a5-A through real OpenCode** had 0 early stops and scored 10/10.
- **Not the arm-5 assembler.** Arm 5 rewrites the client stream (`palimnesis.assemble`), so R21-C was re-checked against the raw upstream SSE.
  - **Three a5-A early stops, last call of each question:**

    | Step | Gold | Client got | Strata's own stream |
    | --- | --- | --- | --- |
    | h1q2 | `fix/ledger-rounding-37570` | `fix/ledger-rounding-37` | upstream #3 streamed the same, then `finish: stop` |
    | h1q3 | `9282` | `9` | upstream #4 streamed `9`, then `stop` |
    | h5q4 | `4.25s` | `4` | upstream #106 streamed `4`, then `stop` |

  - In each case the reasoning had just stated the full value ("…`fix/ledger-rounding-37570`. Reply with only the branch name.").
  - **Every call, all three arms:** no upstream text was longer than what the client received, across all 410 upstream calls (see Input checks).
- **Cause:** unknown. The text is in Strata's own stream; Zeus runs MTP with `--spec-min-p` 0.5 (D48.4). Until that is understood, or repeats per arm are run, needle retention on this server mostly measures early stops, and selection rule 2 (rank by retention) would rank noise.

**R28-C. Tooling notes for S10's resumption** (eval only; nothing changed):
1. Add `--input-budget` to `oc_stack.Stack` / `needle_opencode` / `run.py`, and a matching arm-1 `limit.context`, for O2 emulation through real OpenCode.
2. The emulator's `calls.jsonl` and per-question hidden counts miss continuation calls that the tap records after the client's `[DONE]`.
3. The emulator has no front tap or `internal_scan` of its own.
4. The halt watcher checked hidden tool names live but result text only after each run. That is why a5-C had started when the hit was found.

## R29 — Phase 3B S10: matrix resumed, development tasks, and why arm 5 lost to native compaction (2026-10-26/27, development data only)

**Outcome: no arm is frozen.** The needle screen ranks a5-D first and a5-C third. On the 5 development tasks, both a5-D and a5-C fall short of arm 1:
- tasks passed: 4/5 for each arm-5 variant, against arm 1's 5/5;
- constraints held: 14/15 for each, against 15/15;
- prompt tokens: 9.0M (a5-D) and 7.5M (a5-C), against 5.3M.

Every arm-5 miss traces to a rule or note the user typed that left the view and was never retrieved (R29-E). The user chose to fix that before D64 (plan delta "R29 fixes", D65–D67). No held-out data was touched.

**Setup** (as R28 except as noted):
- **Code:**
  - screen r1–r2 at `c060ad1`; r3 at `ab77f9a`;
  - dev tasks at `ab77f9a` (dev-t1 and the dev-t2 a5-D run), then `fbd9fd0`.
  - `src/` is identical across these commits; only `eval/` and docs changed.
  - Clean tree in every run.
- **Strata:** Zeus 0.1.48, relaunched with spec 6 / `mtp_max` 4 (the Phase 3 64K profile). `n_ctx` 65536, emulated 32K with `--input-budget 24320`. Arm 1 is OpenCode `limit.context` 32768 through `--passthrough`.
- **Wrapper:** the scratch wrapper `s10run.py` (R28-C), whose leak-scan call was fixed and whose runs were recomputed from the tap dumps.
- **D39:** activity rose by exactly our calls in every run, with 0 gate events.
- **Raw data:** `…/scratchpad/s10-3b/` (`screen3/`, `tasks/`, `replay/`).

**R29-A. Early stops are an engine behaviour, not a proxy one.** Replaying R28-B's three a5-A early stops directly against Strata, with the identical prompt, gives:
- the same mix at spec 2, 4 and 6, and at temperature 0;
- at spec 6: h1q2 4 full / 1 empty, h1q3 2 cut / 3 empty, h5q4 5/5 full;
- 1,101 draft tokens offered, 690 accepted (`replay/a5-A-spec6.json`).

They therefore stay in the screen as noise. The screen was repeated three times per arm so that selection does not rank one run's early stops.

**R29-B. Leak-scan false positives (eval only, test-first).**
1. **Session pairing.** R28-A's hit is fixed by pairing each session's results with its own client stream, on whitespace-normalized text (`c060ad1`).
2. **Content joined with newlines (`15bd024`).** Earlier archived content was joined with newlines, so a window starting after a block's "L1:" framing looked new. This caused 9 more hits: grep results that quoted the model's own reasoning.
3. **Quoted messages.** The last 4 hits were the model quoting a limit or argument-error message in its own text. D62.4 was amended before any held-out run (user decision): a hidden result's *whole* text in the client stream is a leak; a fragment the model quotes is an echo, reported (`ab77f9a`).

**R29-C. Needle screen: dev-h1..h6 through the emulator, 3 repeats per arm.**

| Config | Loose exact /60 per repeat | Mean | Early stops | Excluding early stops | Invalid ids | Unnecessary calls (mean) | Prompt tokens (mean) | Hidden calls (mean) | Latency p50 s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| a5-D | 57, 54, 50 | 53.7 | 3, 6, 8 | 57/57, 54/54, 50/52 (98.7%) | 0/68 | 52.3 | 3.08M | 97.7 | 6.3, 5.0, 5.2 |
| a4-d43 | 56, 48, 54 | 52.7 | 2, 10, 4 | 56/58, 48/50, 54/56 (96.3%) | – | 11.7 | 2.58M | – | 3.1, 3.9, 3.2 |
| a5-C | 51, 56, 48 | 51.7 | 8, 3, 12 | 51/52, 56/57, 48/48 (98.8%) | 1/44 | 34.0 | 2.79M | 76.7 | 3.7, 3.8, 4.8 |
| a5-A | 54, 47, 49 | 50.0 | 5, 11, 10 | 54/55, 47/49, 49/50 (97.4%) | 0/46 | 25.7 | 2.97M | 84.0 | 4.1, 2.9, 2.7 |
| a5-B | 51, 39, 34 | 41.3 | 9, 19, 26 | 51/51, 39/41, 34/34 (98.4%) | 1/51 | 28.7 | 2.82M | 70.0 | 3.3, 3.7, 3.4 |

- **Ranking** by `docs/affordances.md`: a5-D, a4-d43, a5-C, a5-A, a5-B.
  - Every arm passes rule 1 (invalid ids ≤ 5%) on the pooled calls.
  - The top two matrix arms, a5-D and a5-C, went to the tasks (O-B8).
- **Retention.** Once early stops are excluded, every arm retains 96–99%. The arm-5 lead over arm 4 is about one question in 60, inside the repeat-to-repeat spread.
- **Input checks, all 15 runs:**
  - 0 hidden-recall leaks (amended D62.4) and 0 unexplained `--explain` pairs;
  - `transcripts verify` passing;
  - 0 inputs over 24,320 and 0 count drift.

**R29-D. Development tasks dev-t1..t5 through real OpenCode, one attempt per task and arm.**

| Task | Arm | Tests | Constraints | Upstream calls | Prompt / completion tokens | Hidden calls | Compactions | Minutes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev-t1 | 1 | 4/4 | 3/3 | 91 | 1.13M / 58K | – | 13 | 12.3 |
| dev-t1 | a5-D | 4/4 | 3/3 | 78 | 1.31M / 42K | 2 | – | 10.4 |
| dev-t1 | a5-C | 4/4 | 3/3 | 50 | 0.79M / 45K | 3 | – | 10.3 |
| dev-t2 | 1 | 4/4 | 3/3 | 70 | 0.81M / 59K | – | 8 | 12.3 |
| dev-t2 | a5-D | 4/4 | **2/3 (C2)** | 266 | 4.28M / 170K | 41 | – | 39.5, turn 5 timed out |
| dev-t2 | a5-C | 4/4 | 3/3 | 33 | 0.55M / 20K | 0 | – | 5.0 |
| dev-t3 | 1 | 3/3 | 3/3 | 47 | 0.56M / 29K | – | 6 | 6.4 |
| dev-t3 | a5-D | 3/3 | 3/3 | 52 | 0.85M / 66K | 1 | – | 15.0 |
| dev-t3 | a5-C | 3/3 | **2/3 (C1)** | 76 | 1.23M / 47K | 12 | – | 11.5 |
| dev-t4 | 1 | 4/4 | 3/3 | 51 | 0.62M / 25K | – | 5 | 6.4 |
| dev-t4 | a5-D | 4/4 | 3/3 | 80 | 1.30M / 38K | 4 | – | 9.6 |
| dev-t4 | a5-C | 4/4 | 3/3 | 87 | 1.45M / 52K | 21 | – | 13.1 |
| dev-t5 | 1 | 3/3 | 3/3 | 161 | 2.14M / 124K | – | 17 | 25.0 |
| dev-t5 | a5-D | **1/3** | 3/3 | 79 | 1.21M / 108K | 9 | – | 23.6 |
| dev-t5 | a5-C | **1/3** | 3/3 | 217 | 3.50M / 183K | 62 | – | 43.5, turn 5 timed out |

- **Totals:**

  | Arm | Tasks passed | Constraints held | Prompt tokens |
  | --- | --- | --- | --- |
  | 1 | 5/5 | 15/15 | 5.26M |
  | a5-D | 4/5 | 14/15 | 8.95M |
  | a5-C | 4/5 | 14/15 | 7.52M |

- **Restart task:** dev-t4 passes its restart gate under all three arms.
- **Every arm-5 run passed every input check:** 0 leaks, 0 unexplained pairs, `transcripts verify` exit 0, 0 over budget, 0 drift.
- **Recovered attempts.** A post-run crash in `eval/tasks/run.py` hit dev-t1 under a5-D and a5-C, and dev-t2 under a5-D: a local named `report` shadowed the module after the last turn (fixed in `fbd9fd0`). For each, every turn had completed. A scratch `salvage.py` recomputed the post-run fields from the saved records and ran the same check. The attempts are marked `salvaged`; only `proxy_starts` and `gate_events` could not be recovered.

**R29-E. Diagnosis from the saved records.**

1. **User-typed rules and notes leave the view, and nothing says what left.** Span collapse absorbs user messages like any other. With s0 stubs, a5-D's turn-7 view of dev-t5 held one note: "202 messages · archived exactly; not shown".

   | Miss | What was lost | When it left the view | Retrieved? |
   | --- | --- | --- | --- |
   | dev-t2 a5-D, C2 (whole words) | turn-1 rule | by call 11 | never; `slugify` cut words in turn 7 (call 262) |
   | dev-t3 a5-C, C1 (never sleeps by itself) | turn-1 rule | absent from call 52 on | never; `time.sleep` added at call 52 |
   | dev-t5 a5-D, vendor codes | turn-3 note | within 7 calls | never; no hidden call after turn 1 |
   | dev-t5 a5-C, vendor codes | turn-3 note | — | recalled twice in turn 5; in turn 7 the model took its own masked edits for seed files and left Q71/Q72/Q75 unhandled |

   - In dev-t5, a5-D credited invented labels to `docs/telemetry.md` ("sensor self-test", "calibration drift", "maintenance due").
   - Arm 1's compaction summary carried each of these rules and notes to the end (dev-t5: "seal leak" from the note's arrival to call 161).
   - This is the needle/task gap. A needle question asks for earlier content, which prompts recall: arm 5 retains 98–99%. A task's need is implicit, and the model fills the gap instead of searching.

2. **Grep fed the model's own inventions back to it.** `palimnesis_grep` searches archived reasoning, so the model's earlier unverified claims came back as hits.
   - **dev-t2 a5-D:** it searched for "golden", "legacy_slugs" and "zero-width" (calls 36–91). Each term first appears in a model response, and none exists in the workspace or the conversation.
   - **dev-t5 a5-C:** 10 lookups chased a code `B7` the model had written into a test.

3. **The per-response cap reset at OpenCode's length follow-up.** In dev-t5 a5-C turn 5 (154 calls), all 5 length stops came from the 4-continuation cap. Output was 1.8K–10.4K of 24,576. Each follow-up message started fresh counts. That message also counted as a new turn (the excerpts said "now turn 9" during task turn 7) and hosted excerpts.

4. **The 202-call dev-t2 a5-D turn 5 never hit a per-response limit.** It made 29 hidden calls across 175 responses. Only a per-turn budget bounds that.

5. **Turn-1 confusion.** In dev-t5 a5-D, masking started inside turn 1, during the long document reads. The model's reasoning then cited a "previous summary" that never existed, and that reasoning stayed in the view.

**Clean-turn lookup counts** (the basis for D67's budget):
- needle questions, all arm-5 repeats: at most 14 hidden calls per user turn;
- clean task turns: at most 8;
- the two runaway turns: 29 and 59.

**Flaky test (housekeeping).** `tests/test_archive_lifecycle.py::test_session_usable_after_mid_stream_commit_failure` fails intermittently with sqlite "database is locked": 1 in 6 runs on a clean `fbd9fd0` worktree, and as often with the R29 fixes applied. It holds a write lock past the writer's busy timeout, and the follow-up request can race the lock's release. It is timing-dependent; no fix yet.

## R30 — Phase 3B S10b: the R29 fixes re-run on development data (2026-10-27, development data only)

**Outcome: a5-Dp matches arm 1 on correctness and costs less.** a5-Dp is a5-D (s0/a1/t2) with the R29 fixes and 4,096 tokens of pinned instructions (D65–D67). On the 5 development tasks:
- tasks passed: 5/5, the same as arm 1;
- constraints held: 15/15, the same as arm 1;
- prompt tokens: 4.95M, against arm 1's 5.26M (−6%);
- upstream calls: 304, against 420;
- wall time: 46 min, against 63.

a5-Cp also passes 5/5 and holds 15/15, but spends 12.0M prompt tokens (+127%). On the needle screen, a5-Dp ranks first by the affordances rule, as a5-D did, now with a tenth of a5-D's unnecessary calls. Nothing is frozen yet: D64 waits for the user. No held-out data was touched.

**Setup** (as R29 except as noted):
- **Code:** `8fafb3f`, clean tree in every run.
- **Arms:** a5-Dp and a5-Cp, from `eval/needle.py` (a5-D / a5-C plus `pin_tokens=4096`). Arm 1 is R29's run, not repeated.
- **Strata:** Zeus 0.1.48, unchanged since R29. `n_ctx` 65536, emulated 32K with `--input-budget 24320`.
- **Batch:** `s10b.sh` ran tasks first, then the screen, 03:11–06:41Z.
- **D39:** activity rose by exactly our calls in every run (3,683 → 5,485), with 0 halts.
- **Raw data:** `…/scratchpad/s10b/` (`tasks/`, `screen/`, `batch.log`).

**R30-A. Development tasks dev-t1..t5 through real OpenCode, one attempt per task and arm.**

| Task | Arm | Passed | Constraints | Calls | Prompt tokens | Lookups | Wall |
|---|---|---|---|---|---|---|---|
| dev-t1 | arm 1 | ✅ | 3/3 | 91 | 1,131,366 | – | 739 s |
| | a5-Dp | ✅ 4/4 | 3/3 | 41 | 672,264 | 0 | 331 s |
| | a5-Cp | ✅ 4/4 | 3/3 | 92 | 1,535,460 | 23 | 723 s |
| dev-t2 | arm 1 | ✅ | 3/3 | 70 | 811,170 | – | 741 s |
| | a5-Dp | ✅ 4/4 | 3/3 | 74 | 1,233,845 | 9 | 780 s |
| | a5-Cp | ✅ 4/4 | 3/3 | 72 | 1,202,495 | 2 | 801 s |
| dev-t3 | arm 1 | ✅ | 3/3 | 47 | 559,980 | – | 386 s |
| | a5-Dp | ✅ 3/3 | 3/3 | 71 | 1,123,770 | 2 | 772 s |
| | a5-Cp | ✅ 3/3 | 3/3 | 72 | 1,160,843 | 5 | 831 s |
| dev-t4 | arm 1 | ✅ | 3/3 | 51 | 619,403 | – | 387 s |
| | a5-Dp | ✅ 4/4, restart gate ✅ | 3/3 | 27 | 407,391 | 0 | 287 s |
| | a5-Cp | ✅ 4/4, restart gate ✅ | 3/3 | 345 | 5,619,893 | 38 | 3,051 s |
| dev-t5 | arm 1 | ✅ | 3/3 | 161 | 2,135,056 | – | 1,498 s |
| | a5-Dp | ✅ 3/3 | 3/3 | 91 | 1,513,009 | 9 | 619 s |
| | a5-Cp | ✅ 3/3 | 3/3 | 145 | 2,438,885 | 17 | 1,483 s |
| **Total** | arm 1 | 5/5 | 15/15 | 420 | 5,256,975 | – | 3,751 s |
| | a5-Dp | 5/5 | 15/15 | 304 | 4,950,279 | 20 | 2,789 s |
| | a5-Cp | 5/5 | 15/15 | 726 | 11,957,576 | 85 | 6,889 s |

- **Every run is clean:**
  - explain exits 0;
  - transcripts verify with 0 errors;
  - nothing is over budget (largest prompt 24,278);
  - 0 leaks and 0 drift;
  - 0 proxy rejections;
  - no compaction calls.
- **The R29 misses all hold now:**
  - dev-t2 C2 under a5-D;
  - dev-t3 C1 under a5-C;
  - dev-t5's vendor note under both arms.
- **The lookup budget (D67) refused 10 calls in four runs:**
  - a5-Cp dev-t1: 3;
  - a5-Cp dev-t4: 3;
  - a5-Cp dev-t5: 2;
  - a5-Dp dev-t2: 2.

  No turn ran away. The largest per-turn count is 17 lookups (16 answered, then refusals), in a5-Cp dev-t4 turn 8. R29's runaway turns used 29 and 59.
- **The task logs' tracebacks are harmless.** They are Windows proactor `ConnectionResetError`s logged as OpenCode exits, as in R29's arm-5 logs.

**a5-Cp's dev-t4 cost is client tool churn, not lookups.**
- Of its 345 calls, the model made 122 `read` calls on 65 distinct files: 57 re-reads, for example `docs/rollup.md` 7 times.
- Turn 1 alone ran 120 calls, against arm 1's 7.
- a5-Dp made 13 reads (5 re-reads) on the same task.
- The cause is not established. a5-C's head/tail stub (`s2`) shows more of a masked read than a5-D's header-only `s0`, so the stub alone does not explain it. a5-C also lacks a5-D's addendum (`a0` against `a1`).
- It is one sample, but R29's a5-C dev-t4 also ran long (13 min, against 6 for arm 1).

**R30-B. Needle screen: dev-h1..h6 through the emulator, 3 repeats per arm, arms interleaved.**

| Arm | Loose (r1, r2, r3) | Mean | Early stops | Excluding stops | Invalid ids | Unnecessary calls | Tokens per repeat | Hidden calls | Latency p50 |
|---|---|---|---|---|---|---|---|---|---|
| a5-Dp | 50, 57, 54 | **53.7**/60 | 9, 3, 5 | 98.7% | 1/47 (2.1%) | 5.0 | 2.41M | 35.0 | 2.5–3.1 s |
| a5-Cp | 56, 47, 54 | 52.3/60 | 4, 11, 6 | 98.6% | 0/47 | 9.0 | 2.48M | 34.3 | 2.8–3.0 s |
| *R29 a5-D* | 57, 54, 50 | 53.7/60 | 3, 6, 8 | 98.7% | 0/68 | 52.3 | 3.08M | 97.7 | 5.0–6.3 s |
| *R29 a5-C* | 51, 56, 48 | 51.7/60 | 8, 3, 12 | 98.8% | 1/44 | 34.0 | 2.79M | 76.7 | 3.7–4.8 s |
| *R29 a4-d43* | 56, 48, 54 | 52.7/60 | 2, 10, 4 | 96.3% | 0/0 | 11.7 | 2.58M | 0 | 3.1–3.9 s |

- **Rule (affordances.md):** no arm is rejected (invalid ids ≤ 5%), and the ranking is a5-Dp, then a5-Cp.
- **Retention is unchanged; cost fell.**
  - a5-Dp's retention equals a5-D's. Its unnecessary calls fell from 52.3 to 5.0, hidden calls from 97.7 to 35.0, and tokens by 22%.
  - The misses that remain are early stops (R29-A), as before.
- **Pins put more answers in view under a5-C:**
  - a5-C, per repeat (in view / excerpt / absent): 17/44/5, 15/43/6, 17/42/7.
  - a5-Cp: 28/33/9, 28/33/8, 25/32/9.
  - a5-Dp: 26/24/10, 27/23/11, 26/25/9, against a5-D's 29/33/7, 23/37/8, 27/35/5.
  - The categories overlap, so rows do not sum to 60.
- **Every repeat is clean:**
  - explain exits 0 with 0 unexplained changes;
  - transcripts verify 6/6;
  - 0 over budget, 0 drift, 0 leaks;
  - `max_completion_tokens` 24,576 throughout.

**R30-C. Excerpts still favour the model's reasoning (the D66 follow-up).** Excerpt items in the ten task archives, by source block:

| Source block | Items |
|---|---|
| Reasoning | 101 |
| Tool results | 65 |
| Tool calls | 56 |
| Text | 18 |

- Reasoning is 42% of all items, and it ranks first in 31 of the 67 selected excerpt blocks.
- This is the hazard D66 removed from grep: unverified reasoning presented beside evidence.
- No task or constraint failed on it here.
- It is open; changing excerpt retrieval would change the arm under test.

## R31 — S11 held-out at 32K, attempt 1: stopped on a proxy defect (2026-10-27)

**Outcome: superseded by the D44.8 rerun.** The first ho2 pass ran both needle sets and one task, then stopped on a proxy defect (D68). Under D44.8 the gates are judged on the rerun at the fixed commit; this attempt is reported, not judged.
- **Arm 5 needles:** 97/120 loose exact (80.8%). That would fail the 85% gate.
- **Arm 4 needles:** 119/120 (99.2%).
- **ho2-t1 under arm 5:** failed (1/4 functional, 1/3 constraints). The cause was the defect: every request from turn 5's last call on was refused `409 history_divergence`, so turns 6–8 never reached the model.

**Setup.**
- **Code:** `b086098` (D64), clean tree. Drivers: `needle-opencode v2` and `tasks-run v2`. OpenCode 2.1.4.
- **Deterministic suite:** 1527 passed, 1 skipped at `b086098`. At the D68 fix: 1545 passed and 1 skipped, with 1 failure, the known R29 flake (`test_session_usable_after_mid_stream_commit_failure`). In a clean worktree it failed 2 of 4 runs at `b086098` and 2 of 3 with the fix, so it is timing, not the fix.
- **Strata:** Zeus 0.1.48, relaunched by the user at `n_ctx` 32768. `/props` reported 32768 before and after every run.
- **Before any held-out run:**
  - `run.py --check-reference`: every task, ho2-t1..t5 included, fails on its stub and passes on its reference.
  - `needle.py preflight --set heldout2`: 12/12 imports faithful (101/101 messages, 50 empty reasoning fields added).
  - Live cancel check (D45.9.16), under both `a4-d43` and `a5-d64`: both taps recorded the disconnect, Strata released the slot in 0.128 s and 0.132 s, and the resend got 200.
- **D39.** Strata's activity counter rose by exactly our upstream calls in every run:
  - needles arm 5: 4 → 306 (302 calls);
  - needles arm 4: 306 → 612 (306 calls);
  - ho2-t1 arm 5: 612 → 884 (272 calls).

  Foreign traffic 0 and gate events 0 throughout.
- **Raw data:** `…/scratchpad/s11b/` (`needles-a5-d64/`, `needles-a4-d43/`, `tasks/`, `heldout.log`).

**R31-A. Needles, one attempt per arm.**

| Arm | Loose exact | 95% Wilson | History-clustered bootstrap | Strict | In view / excerpt / absent | Early stops | Lookups (questions) | Unnecessary (questions) | Invalid ids | Prompt / completion tokens | Latency p50 / p90 s | Wall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| a5-d64 | 97/120 (80.8%) | 72.9–86.9% | 71.7–90.0% | 87 | 54 / 55 / 23 | 22 | 112 hidden (36) | 24 (13) | 0/67 | 5.73M / 31K | 6.5 / 12.6 | 19.9 min |
| a4-d43 | 119/120 (99.2%) | 95.4–99.9% | 97.5–100% | 103 | 29 / 70 / 25 | 1 | 133 transcript (61) | 50 (36) | – | 5.51M / 54K | 10.1 / 19.9 | 25.3 min |

- **Both arms are otherwise clean:**
  - `--explain` exits 0 with 0 unexplained pairs;
  - transcripts verify 12/12;
  - 0 over budget, 0 excerpt leaks, 0 hidden-recall leaks;
  - 0 views disabled.
- **Arm 5's misses are early stops.** 22 of its 23 misses end with finish `stop` after 19–131 completion tokens, with an empty or prefix answer, such as the first word of a branch name. The 23rd (ho2h8q2) is a full answer that does not match. No hidden call, limit or budget was involved: each call asked for 8,192 tokens and stopped on its own.
- **The misses cluster by position.**
  - Q2–Q5 of ho2-h2, h4, h9 and h10;
  - h6q5, h7q2, h8q1, h8q2, h11q2, h12q4 and h12q5.
  - By category: identifier 16/24, superseded 8/12, irrelevant matches 7/12, vague 18/24. Every other category is 12/12.
- **The early stops come with the pinned layout (D65).**
  - Pins split each collapsed region into alternating pinned user messages and user-role span notes.
  - Every arm-5 question's first call had more than 30 consecutive user messages in 110 of 120 cases. All 23 misses are among those 110.
  - None of the 10 questions with shorter runs missed.
  - Arm 4's prompts never have more than 2 user messages in a row, and it had 1 early stop.
  - This is an association, not a proof: no held-out prompt was replayed. A development-only test, pins on against off with the same views, is the next step.
- **Not a defect.** The proxy rendered what D65 specifies. Changing it after these results would be selection on held-out data (D62), so `a5-d64` stays as D64 froze it for the rerun.

**R31-B. ho2-t1 under arm 5, and the defect (D68).**
- **The run:**
  - 272 upstream calls, 4.37M prompt tokens, 16 hidden calls, 3,786 s.
  - Turn 3 was killed at 30 minutes (one client cancel).
  - `--explain` passed 271/271 pairs; verify, over-budget and hidden-leak checks were clean.
- **The defect.** The model emitted a `write` call whose arguments were an unterminated JSON string (6,991 bytes). OpenCode did not run it: it replied with its `tool.input-json` error and resent the complete turn with `arguments: "{}"`. Reconciliation accepted that rewrite only for incomplete turns, so message 541 diverged, and the proxy answered 409 to that request and every later one.
- **A second stop was an eval false positive.** `reachable_records` flagged the session's turn-1 transcript because the model had written a quoted `"gold"` in its own code. The workspace and the task module contain no such string. Fixed test-first: a file now counts only when its `"gold"` or `"answer"` field holds one of the run's answer keys (D68).
- **Review.** The protocol review of the fix found three more cases, all fixed test-first in D68:
  - `NaN` and `Infinity` parse in Python but not in `JSON.parse`, so they would have caused the same lockout;
  - booleans equalled numbers under JSON equality, so an edited `true` → `1` resend passed reconciliation;
  - composite turns render the raw arguments upstream.
- **Per D44.8,** the batch stopped there. ho2-t1 under arms 4 and 1 and ho2-t2..t5 did not run in this attempt. The fix is D68. The whole needle set and all 15 task runs rerun at the fixed commit, and the gates are judged on that rerun.

## R32 — S11 held-out at 32K, the D44.8 rerun: both Phase 3B gates fail (2026-10-27/28)

**Outcome: FAIL on both gates.** This is the judged run (D44.8; R31 is superseded).
- **Needle gate (D44.4):** arm 5 got 97/120 loose exact (80.8%) against the 85% bar. Arm 4 got 119/120 for comparison.
- **Coding gate (D44.5, D62.4):** arm 5 had 2/5 successes against arm 1's 4/5. It failed the restart task ho2-t3. Its gate inputs also failed on the invalid-id rate (below).

Per D64, `serve`'s defaults stay as they are and there is no `phase-3b` tag.

**Setup.**
- **Code:** `af94a2b` (D68), clean tree. Drivers: `needle-opencode v2` and `tasks-run v2`. OpenCode 2.1.4.
- **Strata:** Zeus 0.1.48, `n_ctx` 32768 before and after every run.
- **Schedule:** needles ran 17:50–18:38Z; the 15 task runs ran 18:38Z–13:14Z the next day, one attempt each, with the first arm rotated per task.
- **Supersession:** every needle history and ho2-t1 under arm 5 carry the D44.8 reason. Each is superseded by its rerun attempt.
- **D39.** Strata's activity counter rose by exactly our upstream calls in every run: needles 280 and 317, then each task run.
- **Foreign traffic and gate events:**
  - Foreign traffic during runs was 0.
  - Arm 1's nonzero `foreign_between` (1–8 per task) is R25-B's late-counted disconnect.
  - Three runs logged one `busy_before_request` gate event each, all with nothing queued. These were ho2-t2 arm 5, ho2-t4 arm 4 and ho2-t5 arm 1, each in a session where a turn had just been killed.
- **No proxy rejections** in any run. The D68 path (a complete turn resent with `{}`) did not recur visibly, and no session was refused.
- **Raw data:** `…/scratchpad/s11b/` (`needles-*`, `tasks/records/attempt-002..016`, `heldout.log`, `report-*.txt`).

**R32-A. Needles.**

| Arm | Loose exact | 95% Wilson | History-clustered bootstrap | Strict | In view / excerpt / absent | Early stops | Lookups (questions) | Unnecessary (questions) | Invalid ids | Prompt / completion tokens | Latency p50 / p90 s | Wall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| a5-d64 | 97/120 (80.8%) | 72.9–86.9% | 69.2–91.7% | 89 | 53 / 59 / 22 | 21 | 87 hidden (30) | 16 (8) | 0/61 | 5.37M / 29K | 6.4 / 11.3 | 19.8 min |
| a4-d43 | 119/120 (99.2%) | 95.4–99.9% | 97.5–100% | 108 | 27 / 74 / 22 | 1 | 146 transcript (73) | 76 (51) | – | 5.72M / 57K | 11.1 / 18.1 | 26.9 min |

- **Both arms otherwise clean:**
  - `--explain` exit 0, 0 unexplained;
  - verify 12/12;
  - 0 over budget, 0 leaks, 0 hidden-recall leaks;
  - 0 views disabled.
- **Arm 5's score repeated attempt 1's exactly** (97/120). 21 of its 23 misses are again early stops: finish `stop` with an empty or prefix answer.
  - The set of missed questions moved. ho2-h1 and h5 now miss, while h2, h4, h6, h7 and h8 now pass.
  - By category: identifier 20/24, irrelevant matches 8/12, superseded 8/12, vague 18/24. The other categories are 10–11/12.
  - R31-A's association between misses and runs of more than 30 consecutive user messages (D65 pins) was not re-measured here.
- **Arm 4** missed one question (ho2h5q9, an early stop). It made more lookups, 51 of 98 unnecessary.

**R32-B. Coding tasks.**

| Task | Arm 1 | Arm 4 | Arm 5 |
|---|---|---|---|
| ho2-t1 | pass 4/4, constraints 2/3, kills 3 | pass 4/4, 3/3, kills 0 | pass 4/4, 3/3, kills 1 |
| ho2-t2 | pass 3/3, 3/3, kills 0 | pass 3/3, 3/3, kills 2 | fail 0/3, 1/3, kills 2 |
| ho2-t3 (restart) | pass 4/4, 3/3, restart gate True, kills 0 | fail 3/4, 3/3, restart gate False, kills 0 | fail 2/4, 1/3, restart gate False, kills 1 |
| ho2-t4 | pass 4/4, 3/3, kills 0 | fail 0/4, 3/3, kills 2 | pass 4/4, 3/3, kills 2 |
| ho2-t5 | fail 0/3, 1/3, kills 3 | fail 1/3, 3/3, kills 1 | fail 2/3, 3/3, kills 1 |
| **Successes** | **4/5** | **2/5** | **2/5** |
| Constraints held | 12/15 | 15/15 | 11/15 |
| Turns killed at 30 min (tasks) | 6 (2) | 5 (3) | 7 (5) |
| Upstream calls | 1,192 | 1,379 | 2,175 |
| Prompt tokens | 15.96M | 22.07M | 35.28M |
| Wall time | 5.75 h | 6.00 h | 6.73 h |

- **Gate inputs (D44.6):**
  - Arms 4 and 5: `--explain` passed with 0 unexplained pairs, verify 0, 0 over budget and 0 hard leaks in every run. 0 answer keys were reachable from any workspace.
  - Arm 4's excerpt scan reported echoes on ho2-t4 (177 client, 1 transcript) and ho2-t5 (229, 2). Echoes are reported, never gating.
- **Arm 5's invalid-id rate fails D62.4's 5% limit in every task:** 4/22, 2/14, 1/10, 4/18 and 5/18 recall calls named an address that does not exist. In the needles it was 0/61. The lookup limit (D67) was reached 1–8 times per task.
- **Arm 4 held every constraint but passed 2 of 5 tasks.**
  - On ho2-t4 its code raised in a parser function, giving 3 test errors and 1 wrong unit conversion. The constraint checks pass.
  - Its losses are wrong or unfinished code, not lost instructions.
- **The 30-minute turn limit (D45) cut every arm.**
  - Generation ran at about 100 tokens/s on Zeus (measured on ho2-t1 arm 1). A killed turn is one that wrote about 130–170K completion tokens, mostly reasoning, in edit-test-fix loops with failed tool calls.
  - Prompt processing was 100–300 s of each killed turn. No upstream call was slow (`slow_upstream_calls` 0).
- **Cost:** arm 5 used 2.2× arm 1's prompt tokens and arm 4 used 1.4×. On ho2-t1, though, arm 4 was the cheapest arm at a third of arm 1's tokens.

**R32-C. What this says.**
- **Recall:** on held-out data, arm 4 recalls facts that left the view (99%). Arm 5 does not reach the bar, and its misses are early stops, not failed lookups.
- **Coding:** neither Palimnesis arm matched native compaction on coding tasks. Arm 4 kept every user constraint where arm 1 lost 3, but it finished fewer tasks.
- **Sample size:** five tasks, one attempt each, so a one-task difference is within noise. Still, this is the second held-out set on which Palimnesis trails native compaction on coding: R25 had arm 4 at 3/5 against arm 1's 5/5, and here arm 4 and arm 5 are both 2/5 against 4/5.
