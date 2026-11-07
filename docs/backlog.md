# Backlog

Work set aside on purpose, with the reason, what already exists and what picking it up would take. An item leaves the backlog when a phase plan takes it on; its decision then says so.

## Claude Code support

- **Status:** backlogged by the user on 2026-11-05 because Claude Code is closed source (D92).
- **What exists:**
  - S0 probes HC1–HC9 with recorded fixtures: `docs/probes/claude_code.md`, `eval/probes/fixtures/claude-code-2.1.318/`, drivers `eval/probes/cc_*.py`.
  - The Messages archive route, emitter, error envelope and admission that Claude Code would use (D84–D89). Pi uses them too, so they stay supported.
  - A test that replays Claude Code's recorded `/compact` through the proxy (`tests/test_discontinuity.py`, S8): real Claude Code bodies, with 23 tools, the mid-conversation system entry and adaptive thinking, archive, and the summarizer request is refused with 409.
- **What picking it up would take** (the Phase 4B plan's S10 and the Claude Code parts of S11–S14):
  - **Context.** Strata at 64K on pythia: Claude Code's fixed input is 18,812 tokens interactively, more than 32K allows (O-4B-13, HC3). The user approved that restart for Claude Code work.
  - **Adapter.** `integrations/claude-code/`: a wrapper that runs `palimnesis session new` or `session url <id>` and sets `ANTHROPIC_BASE_URL` per process, plus the candidate environment (`CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`, `DISABLE_AUTO_COMPACT=1`, `CLAUDE_CODE_MAX_CONTEXT_TOKENS=1000000`, HC3, HC6).
  - **Tests and evidence still missing:**
    - the interrupt marker after a user stops a tool call (D90);
    - the non-streaming fallback resend policy (HC5);
    - resume fidelity through the proxy (HC7);
    - the transcript gate with `--add-dir` (HC8);
    - a live smoke.
  - **Re-probe first:** the S0 facts are for 2.1.318; the client changes with every release.

## Early stops on Pi's sessions (R45)

- **Status:** recorded, not pursued in Phase 4B. Needles are reported, not gated, there (D81.6).
- **What is known:**
  - The model cuts a short answer after a token or two (`finish_reason: stop`), and once one cut answer is in the history, later answers are cut the same way (D97.2, R45-A).
  - On Pi's development needles, this cost 14 of 60.
  - Pi's system prompt may raise the rate of the first cut (7/16 against 2/16 with OpenCode's; p ≈ 0.11).
- **What picking it up would take:**
  - an OpenCode run on the development set, to separate the harness from the set;
  - then, if Pi's sessions stay worse, a harness-side temperature or system-prompt setting in `integrations/pi/`. The proxy sets no sampling parameters and does not rewrite history (R38-D, D75).

## Pi's Messages ho2 tasks: one attempt is not enough (R52)

- **Status:** recorded, not pursued in Phase 4B. Task runs are reported, not gated, there (D81.6).
- **What is known:**
  - On Messages, `a4-d77` passed 3/5 ho2 tasks and Pi's own compaction 4/5. On Chat, both passed 5/5.
  - Both `a4-d77` failures are string-handling details the model got wrong: the spacing in ho2-t2 and ho2-t4, and plural units in ho2-t4. The recorded bodies show the proxy did not change the inputs involved.
  - Every task ran once per arm, so the difference cannot be told from run-to-run variance.
- **What picking it up would take:** three or more attempts per task and arm on Messages, about 13 hours for `a4-d77` and 30 for arm 1 at R52's pace, then a paired comparison per task.

## Single-prompt game tasks (game-t1, R52)

- **Status:** a test the user added. Two pairs run, and the rubric (`eval/tasks/game_t1_rubric.md`) needs a person to play.
- **What is known:** every failure in four runs was a name used in one write and missing from the others, from a page written in parts. None of the runs opened its page before ending its turn.
- **What picking it up would take:** blind scores for pair 2 from the user, then more pairs. The 30-minute turn limit cut arm 1 off in pair 1, so later pairs should use `--turn-timeout` (pair 2 used 3 hours).
