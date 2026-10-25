# Palimnesis

Local proxy between agent harnesses and a Strata server: archives accepted conversation content, presents a bounded view upstream, and gives exact addressable recall of what the view removed. `docs/v1_plan.md` is the plan; read the section for the phase you're working in.

## Commands

- `uv run pytest -q`: the full deterministic suite (fake upstream on real loopback sockets; no network).
- `uv run palimnesis serve --upstream http://192.168.1.173:8080 [--capture-dir DIR]`: run the proxy on 127.0.0.1:9000.
- `uv run palimnesis session new` / `uv run palimnesis session url <id>`: base URLs for a new or resumed chat.
- `uv run python eval/replay.py CAPTURE_DIR --target URL`: replay captures against direct Strata or the proxy.
- `uv run python eval/bench_passthrough.py`: passthrough overhead report.

## Rules

- **Contracts are the spec.** `docs/contracts.md` states proxy behavior; papers motivate mechanisms but never override a contract or protocol correctness. A behavior change touching a contract lands as a red fake-upstream test first, then the code, then the contract text.
- **Harness-neutral core.** Pi, OpenCode and Claude Code are peers. Harness-specific behavior lives in adapters and `docs/harnesses.md`; core modules key off protocol (OpenAI Chat Completions, Anthropic Messages), never off a harness name.
- **Evidence over defaults.** SDK timeouts/retries, Strata template/cancellation/cache behavior and harness URL joining are recorded from captured fixtures or probes (`eval/probes/`, `docs/probes/`), never from assumed SDK defaults. Mark unverified facts as unverified.
- **Decisions.** A material choice (format, default, rejected alternative, deviation from the plan) gets an entry in `docs/decisions.md` with its reason.
- **Citations.** A module implementing a research mechanism names its paper and any justified adaptation in the module docstring (`docs/papers.md` holds the list). Protocol plumbing needs none.
- **Tests** sit at the agreed seams: HTTP end-to-end through `tests/fake_upstream.py`, plus pure functions with their own contracts (e.g. `palimnesis.sessions`). Expected values come from the spec or literal fixtures.
- **Privacy.** Operational logs never contain request/response bodies or credentials; body capture exists only behind `--capture-dir`.
- **Blocking I/O** (SQLite, file writes) runs off the event-loop thread.

## Phase workflow

plan → failing tests → implement → independent review → applicable checks → `docs/results.md` → commit and tag `phase-N`. Roles live in `.claude/agents/`: `planner`, `test-writer`, `protocol-reviewer`, `cache-auditor`, `paper-fidelity-reviewer`, `eval-runner`. Reviewers report; they never edit.
