"""Phase 4A S8: the GL2 tooling (``eval/state_eval.py``, D105).

Trap patterns match their stated trap and never the task's reference; every development,
ho2 and ho3 task states its rules and trap in its first turn; the evaluator counts the
watermark moves after that statement, finds trap repeats in generated tool calls and final
files, and refuses heldout4."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from .test_notes_http import BUDGET, _body, _messages
from .test_state_golden import _answer, _turns
from .test_view_http import post, view_stack

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval"), str(ROOT / "eval" / "tasks")]
import state_eval  # noqa: E402

sys.path.remove(str(ROOT / "eval"))
sys.path.remove(str(ROOT / "eval" / "tasks"))

TASKS = [f"{p}-t{n}" for p in ("dev", "ho2", "ho3") for n in range(1, 6)]
DETECTABLE = {"dev-t1", "dev-t3", "dev-t4", "ho2-t1", "ho2-t4", "ho2-t5", "ho3-t1", "ho3-t4"}


def _reference(task) -> str:
    ref = task.REFERENCE
    return "\n".join(ref.values()) if isinstance(ref, dict) else str(ref)


@pytest.mark.parametrize("task_id", TASKS)
def test_trap_patterns_match_the_trap_not_the_reference(task_id):
    task = state_eval.task_module(task_id)
    patterns = task.TRAP_PATTERNS
    assert bool(patterns) == (task_id in DETECTABLE)
    for p in patterns:
        assert re.search(p, task.TRAP), p
        assert not re.search(p, _reference(task)), p


@pytest.mark.parametrize("task_id", TASKS)
def test_rules_and_trap_are_stated_in_the_first_turn(task_id):
    task = state_eval.task_module(task_id)
    assert "already tried" in task.TURNS[0]
    assert not any("already tried" in t for t in task.TURNS[1:])


def test_state_tools_refuse_heldout4():
    with pytest.raises(ValueError, match="D96"):
        state_eval.task_module("ho4-t1")
    assert state_eval.main(["nowhere", "--task", "ho4-t2"]) == 2


FAKE = SimpleNamespace(ID="fake-t1", TRAP_PATTERNS=(r"int\(\s*float\(",))


def _session(tmp_path, calls: int, trap_call: bool):
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048, notes_format="n2") as (
            fake, url, s):
        for k in range(calls):
            if trap_call and k == calls - 1:
                fake.respond_counted(tool_call=("call_t", "write", '{"content": "int(float(p) * 100)"}'))
            else:
                _answer(fake, f"answer {k}")
                _answer(fake, f"answer {k}")
            assert post(url, _body(_messages(_turns(k)))).status_code == 200
            fake._script.clear()
    return s.db_path


def test_state_eval_counts_moves_after_the_statement(tmp_path):
    db = _session(tmp_path, 4, trap_call=False)
    [r] = state_eval.evaluate(db, FAKE, check={"constraints": {"C1": True, "C2": False}})
    assert r["moves_after"] >= 3 and r["eligible"]
    assert (r["constraints_held"], r["constraints_eligible"]) == (1, 2)
    assert r["state_versions_after"] >= 2
    assert r["trap"] == "pattern" and r["trap_repeated"] is False


def test_too_few_moves_are_not_eligible(tmp_path):
    db = _session(tmp_path, 1, trap_call=False)
    [r] = state_eval.evaluate(db, FAKE, check={"constraints": {"C1": True}})
    assert r["moves_after"] < 3 and not r["eligible"]
    assert r["constraints_eligible"] == 0 and r["trap_repeated"] is None


def test_trap_repeat_found_in_a_generated_tool_call(tmp_path):
    db = _session(tmp_path, 4, trap_call=True)
    [r] = state_eval.evaluate(db, FAKE)
    assert r["trap_repeated"] is True
    assert [h["where"] for h in r["trap_hits"]] == ["tool_call"]
    assert r["trap_hits"][0]["tool"] == "write"


def test_trap_repeat_found_in_final_source_files_not_tests(tmp_path):
    db = _session(tmp_path, 4, trap_call=False)
    ws = tmp_path / "ws"
    (ws / "pkg").mkdir(parents=True)
    (ws / "tests").mkdir()
    (ws / "pkg" / "parse.py").write_text("cents = int(float(text) * 100)\n", encoding="utf-8")
    (ws / "tests" / "test_x.py").write_text("int(float('1'))\n", encoding="utf-8")
    [r] = state_eval.evaluate(db, FAKE, workspace=ws)
    assert r["trap_hits"] == [{"where": "file", "path": "pkg/parse.py",
                               "pattern": FAKE.TRAP_PATTERNS[0]}]


def test_a_task_without_patterns_is_reviewed_by_hand(tmp_path):
    db = _session(tmp_path, 4, trap_call=True)
    [r] = state_eval.evaluate(db, SimpleNamespace(ID="fake-t2", TRAP_PATTERNS=()))
    assert r["trap"] == "manual" and r["trap_repeated"] is None and r["trap_hits"] == []


def test_retired_sets_take_an_emulated_budget_and_heldout4_never_does():
    """D107: ho2 and ho3 are development data (D69, D105.10) and may run at an emulated
    32K; an unretired held-out set runs only at the real context (O2)."""
    sys.path.insert(0, str(ROOT / "eval" / "tasks"))
    sys.path.insert(0, str(ROOT / "eval"))
    try:
        import run as task_run
    finally:
        sys.path.remove(str(ROOT / "eval"))
        sys.path.remove(str(ROOT / "eval" / "tasks"))
    assert task_run.budget_refusal("development", 24320) is None
    assert task_run.budget_refusal("heldout2", 24320) is None
    assert task_run.budget_refusal("heldout3", 24320) is None
    assert "O2" in task_run.budget_refusal("heldout4", 24320)
    assert "O2" in task_run.budget_refusal("heldout", 24320)
    assert task_run.budget_refusal("heldout4", None) is None
