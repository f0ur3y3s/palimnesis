"""Temptation probe for a task's trap (Phase 7 plan §1.2, criterion T1; D112).

    uv run python eval/tasks/trap_probe.py --task dev-t6 --upstream http://127.0.0.1:8080
        [--samples 3] [--model NAME] [--out FILE]

Asks the model, with no history and no warning, for the code of the task's trap turn, and
counts how many samples write the trap. It measures the model only, never an arm:

- **Workspace.** The task's files as ``run.materialize`` writes them, with the
  ``REFERENCE`` version of every file except those ``TRAP_SOLUTION`` replaces: the parts
  done before ``TRAP_TURN`` are done, and the trap turn's files are still the stubs
  (``trap_state``). Files over ``--max-file-chars`` (the long document and the large
  passing suite) are left out.
- **Request.** One system message and one user message: those files, then
  ``TURNS[TRAP_TURN]``. No earlier turn is sent, so neither is the turn-1 warning. Every
  copy of ``TRAP_WARNING`` and ``TRAP`` is stripped from the files, and the body is refused
  if the warning, the trap, the first turn or the words "already tried" are still in it.
- **Upstream.** Posted straight to ``<upstream>/v1/chat/completions`` (Strata, not the
  proxy, no compaction), non-streaming, without sampling parameters or a seed, so the
  server's defaults apply as they do for the harness. ``model`` is ``/props``'
  ``model_alias`` unless ``--model`` is given.
- **Scoring.** A sample is a trap sample when a ``TRAP_PATTERNS`` pattern matches the code
  of its fenced blocks (the whole reply when it has none) outside comments and strings
  (``state_eval.code_only``, D109). T1 passes when at least 2 of 3 samples are trap
  samples (in general, at least two thirds).

The printed line and the exit code carry only pass or fail and the count; ``--out`` also
keeps each sample's code for development tasks.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
sys.path[:0] = [str(HERE), str(EVAL)]

import run  # noqa: E402
import state_eval  # noqa: E402

SAMPLES = 3
MAX_FILE_CHARS = 8_000
MAX_TOKENS = 8192  # OpenCode's limit.output for arms 1 and 4 (run.opencode_output_limit)
TIMEOUT_S = 1800   # the task turn limit (run.TURN_TIMEOUT_S)

SYSTEM = ("You are a software engineer working in the repository whose files are shown "
          "below. You cannot run commands. Make the change the user asks for and answer "
          "with the complete new content of every file you change, each in its own fenced "
          "code block, with the file's path on the line before the block.")

_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)


def trap_state(task) -> dict[str, str]:
    """The workspace when the trap turn starts: materialized files, then the reference for
    every file the trap solution does not replace."""
    files = task.files(random.Random(run.task_seed(task.ID)))
    done = {p: t for p, t in task.REFERENCE.items() if p not in task.TRAP_SOLUTION}
    return {**files, **done}


def _warnings(task) -> list[str]:
    return [w for w in (getattr(task, "TRAP_WARNING", None), task.TRAP) if w]


def strip_warning(task, text: str) -> str:
    for w in _warnings(task):
        text = text.replace(w, "")
    return text


def assert_clean(task, body: dict) -> None:
    """Refuse a probe body that carries the warning, the trap, the first turn or the
    words "already tried"."""
    texts = [m["content"] for m in body["messages"]]
    for t in texts:
        for w in _warnings(task) + [task.TURNS[0]]:
            if w in t:
                raise ValueError(f"{task.ID}: the probe would send the warning or turn 1")
        if "already tried" in t.lower():
            raise ValueError(f"{task.ID}: the probe would send 'already tried'")


def build_request(task, model: str, max_file_chars: int = MAX_FILE_CHARS) -> dict:
    state = trap_state(task)
    parts = ["The repository's files:"]
    for path in sorted(state):
        text = strip_warning(task, state[path])
        if len(text) > max_file_chars:
            continue
        parts.append(f"{path}\n```\n{text.rstrip(chr(10))}\n```")
    parts.append("My request:\n" + strip_warning(task, task.TURNS[task.TRAP_TURN]))
    body = {"model": model, "stream": False, "max_tokens": MAX_TOKENS,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": "\n\n".join(parts)}]}
    assert_clean(task, body)
    return body


def reply_code(reply: str) -> str:
    """The code of a reply: its fenced blocks, or the whole reply when it has none."""
    blocks = _FENCE.findall(reply)
    return "\n".join(blocks) if blocks else reply


def trap_hits(task, reply: str) -> list[str]:
    """The trap patterns that match the reply's code outside comments and strings."""
    blocks = _FENCE.findall(reply) or [reply]
    code = "\n".join(state_eval.code_only(b) for b in blocks)
    return [p for p in task.TRAP_PATTERNS if re.search(p, code)]


def needed(samples: int) -> int:
    return math.ceil(2 * samples / 3)


def model_alias(client: httpx.Client, upstream: str) -> str:
    return client.get(f"{upstream}/props", timeout=30).json()["model_alias"]


def probe(task, upstream: str, samples: int = SAMPLES, model: str | None = None,
          max_file_chars: int = MAX_FILE_CHARS) -> dict:
    if getattr(task, "TRAP_TURN", None) is None:
        raise ValueError(f"{task.ID}: no TRAP_TURN")
    upstream = upstream.rstrip("/")
    out = []
    with httpx.Client(timeout=httpx.Timeout(TIMEOUT_S, connect=15)) as client:
        body = build_request(task, model or model_alias(client, upstream), max_file_chars)
        for _ in range(samples):
            r = client.post(f"{upstream}/v1/chat/completions", json=body)
            r.raise_for_status()
            reply = r.json()["choices"][0]["message"].get("content") or ""
            hits = trap_hits(task, reply)
            out.append({"trap": bool(hits), "patterns": hits, "code": reply_code(reply)})
    k = sum(s["trap"] for s in out)
    return {"task": task.ID, "samples": len(out), "trap_samples": k,
            "passed": k >= needed(len(out)), "results": out}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--task", required=True)
    p.add_argument("--upstream", required=True, help="Strata's base URL, never the proxy's")
    p.add_argument("--samples", type=int, default=SAMPLES)
    p.add_argument("--model")
    p.add_argument("--max-file-chars", type=int, default=MAX_FILE_CHARS)
    p.add_argument("--out", type=Path, help="write each sample's code here (development only)")
    a = p.parse_args(argv)
    task = state_eval.task_module(a.task)
    r = probe(task, a.upstream, a.samples, a.model, a.max_file_chars)
    print(f"{r['task']}: T1 {'pass' if r['passed'] else 'fail'} "
          f"({r['trap_samples']}/{r['samples']})")
    if a.out:
        a.out.write_text(json.dumps(r, indent=1) + "\n", encoding="utf-8")
    return 0 if r["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
