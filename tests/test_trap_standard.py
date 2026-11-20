"""Phase 7 S7: the trap standard (plan §1.2, D112) and its temptation probe.

- The probe (``eval/tasks/trap_probe.py``) sends the trap turn's request with the workspace
  at that turn, no history and no warning, straight to the upstream (fake, on loopback).
- Every task that declares ``TRAP_TURN`` passes the lint: the trap is needed late, its
  request names neither the warning nor the trap, and the patterns separate the trap
  solution from the reference.
- dev-t6..t10 meet T2, T5 and T6 on their own files: the trap solution passes the visible
  tests and every ``test_f_*`` and constraint, and fails a ``test_t_*`` the reference passes.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from .fake_upstream import FakeUpstream
from .servers import serve

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval"), str(ROOT / "eval" / "tasks")]
import run as task_run  # noqa: E402
import state_eval  # noqa: E402
import heldout  # noqa: E402
import trap_probe  # noqa: E402

sys.path.remove(str(ROOT / "eval"))
sys.path.remove(str(ROOT / "eval" / "tasks"))

TRAP_TASKS = [f"dev-t{n}" for n in range(6, 11)]


def _reply(code: str) -> bytes:
    text = f"markbook/report.py\n```python\n{code}\n```\n"
    return json.dumps({"id": "x", "object": "chat.completion", "model": "m",
                       "choices": [{"index": 0, "finish_reason": "stop",
                                    "message": {"role": "assistant", "content": text}}]}).encode()


def test_trap_probe_strips_warning_direct_upstream():
    real = state_eval.task_module("dev-t6")
    # A workspace file that repeats the warning: the probe must strip it, not send it.
    planted = {"NOTES.md": f"Team notes.\n{real.TRAP_WARNING}\n{real.TRAP}\nEnd.\n"}
    task = SimpleNamespace(**{k: getattr(real, k) for k in dir(real) if k.isupper()},
                           files=lambda rnd: {**real.files(rnd), **planted})
    fake = FakeUpstream()
    fake.respond_json(_reply("def final_mark(s):\n    return round(weighted(s))\n"))
    fake.respond_json(_reply("def final_mark(s):\n    # not round(x): never rounded up\n"
                             "    return t // 10\n"))
    fake.respond_json(_reply("def final_mark(s):\n    return int(round(weighted(s)))\n"))
    with serve(fake.app()) as url:
        r = trap_probe.probe(task, url)
    assert (r["samples"], r["trap_samples"], r["passed"]) == (3, 2, True)
    assert [s["trap"] for s in r["results"]] == [True, False, True]
    assert fake.props_requests == 1
    assert [(q.method, q.path) for q in fake.requests] == [("POST", "/v1/chat/completions")] * 3
    for q in fake.requests:
        body = json.loads(q.body)
        assert body["model"] == "qwen3.8-flash-next-iq3_xxs" and body["stream"] is False
        assert not {"temperature", "top_p", "top_k", "seed"} & set(body)
        assert [m["role"] for m in body["messages"]] == ["system", "user"]
        sent = "\n".join(m["content"] for m in body["messages"])
        assert real.TRAP_WARNING not in sent and real.TRAP not in sent
        assert "already tried" not in sent.lower() and real.TURNS[0] not in sent
        assert sent.endswith(real.TURNS[real.TRAP_TURN])
        assert "Team notes." in sent  # the planted file was sent, without the warning
        assert "markbook/scores.py" in sent and "def _score" in sent
        assert "tenths // 10" not in sent  # the trap turn's file is still the stub
        assert "Appendix A" not in sent  # the long document is left out
    # A request that would restate the warning is refused before anything is sent.
    leaky = SimpleNamespace(**{**vars(task), "TURNS": [*real.TURNS[:6],
                                                       "Recall we already tried it.", *real.TURNS[7:]]})
    with pytest.raises(ValueError, match="already tried"):
        trap_probe.build_request(leaky, "m")


def _trap_modules():
    out = []
    for path in sorted((ROOT / "eval" / "tasks").glob("*.py")):
        if not re.fullmatch(r"(dev|ho\d?)_t\d+", path.stem):
            continue
        if heldout.set_of_task(path.stem.replace("_", "-")) is not None:
            continue  # unseen sets (ho4, ho5, ho6) stay unread until unlocked (D96, D113)
        if "TRAP_TURN" not in path.read_text(encoding="utf-8"):
            continue
        out.append(state_eval.task_module(path.stem.replace("_", "-")))
    return out


def _identifiers(trap: str) -> set[str]:
    """The code a trap names: called names, dotted names and keyword arguments."""
    found = set(re.findall(r"[A-Za-z_][\w.]*(?=\()", trap))
    found |= set(re.findall(r"\b[A-Za-z_]\w*\.[A-Za-z_][\w.]*", trap))
    found |= set(re.findall(r"\b[A-Za-z_]\w*\s*=\s*\w+", trap))
    return {f.strip(".") for f in found}


def test_trap_suite_lint():
    modules = _trap_modules()
    assert {m.ID for m in modules} >= set(TRAP_TASKS)
    for task in modules:
        assert task.TRAP_TURN >= 5 and task.TRAP_TURN < len(task.TURNS), task.ID
        assert task.TRAP_TURN >= task.RESTART_BEFORE, task.ID
        request = task.TURNS[task.TRAP_TURN]
        assert task.TRAP not in request and task.TRAP_WARNING not in request, task.ID
        assert task.TRAP_WARNING in task.TURNS[0] and "already tried" in task.TRAP_WARNING
        assert "already tried" not in request.lower(), task.ID
        for name in _identifiers(task.TRAP):
            assert not re.search(rf"(?<![\w.]){re.escape(name)}(?![\w])", request), (task.ID, name)
        assert task.TRAP_SOLUTION and task.TRAP_PATTERNS, task.ID
        assert set(task.TRAP_SOLUTION) <= set(task.REFERENCE), task.ID
        trap_code = "\n".join(state_eval.code_only(t) for t in task.TRAP_SOLUTION.values())
        ref_code = "\n".join(state_eval.code_only(t) for t in task.REFERENCE.values())
        state = trap_probe.trap_state(task)
        before = "\n".join(state_eval.code_only(state[p]) for p in task.TRAP_SOLUTION)
        assert any(re.search(p, trap_code) for p in task.TRAP_PATTERNS), task.ID
        for p in task.TRAP_PATTERNS:
            assert not re.search(p, request), (task.ID, p)
            assert not re.search(p, ref_code), (task.ID, p)
            assert not re.search(p, before), (task.ID, p)


def _visible(task, overlay: dict[str, str]) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d) / "repo"
        task_run.materialize(task, ws)
        for rel, text in overlay.items():
            (ws / rel).write_text(text, encoding="utf-8", newline="\n")
        return subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                              cwd=ws, capture_output=True, text=True, timeout=300)


@pytest.mark.parametrize("tid", TRAP_TASKS)
def test_dev_trap_tasks_meet_t2_t5_t6(tid):
    task = state_eval.task_module(tid)
    assert (task.ID, task.SET, task.RESTART_BEFORE, len(task.TURNS)) == (tid, "development", 4, 8)
    expected = task_run.expected_tests(task.HIDDEN)
    traps = [n for n in expected if n.startswith("test_t_")]
    assert traps
    trap = {**task.REFERENCE, **task.TRAP_SOLUTION}
    ref = task_run.check_one(task, task.REFERENCE, sys.executable)
    assert ref["success"] and ref["constraints_held"] == 3, ref["tail"]
    assert all(ref["results"].get(n) == "ok" for n in traps), ref["results"]
    stub = task_run.check_one(task, {}, sys.executable)
    assert not stub["success"] and stub["functional_passed"] == 0
    bad = task_run.check_one(task, trap, sys.executable)
    assert bad["success"] and bad["constraints_held"] == 3, bad["tail"]  # T2, T4, T6
    assert any(bad["results"].get(n) != "ok" for n in traps), bad["results"]  # T5
    for overlay in (task.REFERENCE, trap):
        v = _visible(task, overlay)
        assert v.returncode == 0, v.stderr[-2000:]  # T2: visible tests pass
    assert _visible(task, {}).returncode != 0  # the stub fails them


# Correct lines a pilot run wrote that an earlier pattern set matched (R64). A trap
# pattern must not fire on them, so a `code` hit stays evidence of the trap.
PILOT_FALSE_POSITIVES = {
    "dev-t10": ["word = word[len(piece):]",
                "rest = rest[len(chunk):]"],
}


@pytest.mark.parametrize("tid", sorted(PILOT_FALSE_POSITIVES))
def test_trap_patterns_skip_pilot_false_positives(tid):
    task = state_eval.task_module(tid)
    for line in PILOT_FALSE_POSITIVES[tid]:
        assert not [p for p in task.TRAP_PATTERNS if re.search(p, line)], line


def test_trap_probe_runs_on_a_locked_set_without_sample_output(monkeypatch, tmp_path):
    """Authors probe their own unseen tasks before any unlock (plan §1.1 step 3, T1): the
    probe prints only pass or fail and the count, and refuses ``--out`` for an unseen task."""
    import heldout

    monkeypatch.setattr(heldout, "unlock_problem", lambda s, **kw: "locked (D96)" if s else None)
    monkeypatch.setattr(heldout, "set_of_task", lambda t: "heldout5")
    assert trap_probe.load_task("dev-t6").ID == "dev-t6"
    monkeypatch.setattr(trap_probe, "probe", lambda *a, **k: {
        "task": "dev-t6", "passed": True, "trap_samples": 3, "samples": 3, "replies": ["x"]})
    assert trap_probe.main(["--task", "dev-t6", "--upstream", "http://u"]) == 0
    with pytest.raises(SystemExit):
        trap_probe.main(["--task", "dev-t6", "--upstream", "http://u", "--out", str(tmp_path / "o")])
    assert not (tmp_path / "o").exists()
