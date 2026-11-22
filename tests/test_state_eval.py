"""Phase 4A S8: the GL2 tooling (``eval/state_eval.py``, D105).

Trap patterns match their stated trap and never the task's reference; every development,
ho2 and ho3 task states its rules and trap in its first turn; the evaluator counts the
watermark moves after that statement, finds trap repeats in generated tool calls and final
files, and refuses heldout4."""

from __future__ import annotations

import json
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


def test_state_tools_refuse_a_locked_heldout_set():
    # heldout6 stays locked (D115.9, D117.4); heldout4 and heldout5 were unlocked by D115.
    with pytest.raises(ValueError, match="D96"):
        state_eval.task_module("ho6-t1")
    assert state_eval.main(["nowhere", "--task", "ho6-t2"]) == 2


FAKE = SimpleNamespace(ID="fake-t1", TRAP_PATTERNS=(r"int\(\s*float\(",))


RUN_WS = Path("C:/runs/attempt-001/ws")
SOURCE = str(RUN_WS / "pkg" / "parse.py")
TRAP_WRITE = ("write", {"path": SOURCE, "content": "cents = int(float(p) * 100)\n"})


def _session(tmp_path, calls: int, trap_call: bool | tuple = False):
    if trap_call is True:
        trap_call = TRAP_WRITE
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048, notes_format="n2") as (
            fake, url, s):
        for k in range(calls):
            if trap_call and k == calls - 1:
                tool, args = trap_call
                fake.respond_counted(tool_call=("call_t", tool, json.dumps(args)))
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
    [r] = state_eval.evaluate(db, FAKE, run_ws=RUN_WS)
    assert r["trap_repeated"] is True
    assert [(h["where"], h["kind"]) for h in r["trap_hits"]] == [("tool_call", "code")]
    assert r["trap_hits"][0]["tool"] == "write"
    assert r["trap_hits"][0]["path"] == "pkg/parse.py"
    assert r["trap_doubtful"] == 0


# D109: a hit counts as a repeat only when the trap is code (not a comment or a string)
# that the model put into a task source file. Everything else is doubtful, for review by
# hand (D107.7): searches, shell commands, scratch files outside the workspace, tests,
# comments and strings, and an edit's old text (the model removing the trap).
DOUBTFUL_CALLS = {
    "scratch file": ("write", {"path": "C:/runs/attempt-001/oc/tmp/opencode/probe.py",
                               "content": "print(int(float('0.29') * 100))\n"}),
    "comment only": ("write", {"path": SOURCE,
                               "content": "# never int(float(p) * 100): 0.29 -> 28\nx = 1\n"}),
    "string only": ("write", {"path": SOURCE, "content": "WHY = 'not int(float(p) * 100)'\n"}),
    "test file": ("write", {"path": str(RUN_WS / "tests" / "test_p.py"),
                            "content": "assert int(float('1') * 100) == 100\n"}),
    "edit removes it": ("edit", {"path": SOURCE, "oldString": "c = int(float(p) * 100)",
                                 "newString": "c = to_cents(p)"}),
    "search": ("grep", {"pattern": "int(float(", "path": str(RUN_WS)}),
    "shell": ("shell", {"command": "python -c \"print(int(float('0.29')*100))\""}),
    "no path": ("write", {"content": "int(float(p) * 100)"}),
}


@pytest.mark.parametrize("case", sorted(DOUBTFUL_CALLS))
def test_doubtful_trap_hits_are_reported_not_counted(tmp_path, case):
    db = _session(tmp_path, 4, trap_call=DOUBTFUL_CALLS[case])
    [r] = state_eval.evaluate(db, FAKE, run_ws=RUN_WS)
    assert r["trap_repeated"] is False
    assert [(h["where"], h["kind"]) for h in r["trap_hits"]] == [("tool_call", "doubtful")]
    assert r["trap_doubtful"] == 1


def test_an_edit_that_adds_the_trap_counts(tmp_path):
    db = _session(tmp_path, 4, trap_call=("edit", {
        "path": SOURCE, "oldString": "c = to_cents(p)", "newString": "c = int(float(p) * 100)"}))
    [r] = state_eval.evaluate(db, FAKE, run_ws=RUN_WS)
    assert r["trap_repeated"] is True and r["trap_hits"][0]["kind"] == "code"


@pytest.mark.parametrize("path", ["pkg/parse.py", "./pkg/parse.py", "pkg\\parse.py"])
def test_a_relative_path_is_in_the_run_workspace(tmp_path, path):
    """The harness resolves a relative path against the workspace it runs in."""
    db = _session(tmp_path, 4, trap_call=("write", {"path": path, "content": "c = int(float(p))\n"}))
    [r] = state_eval.evaluate(db, FAKE, run_ws=RUN_WS)
    assert r["trap_repeated"] is True and r["trap_hits"][0]["path"] == "pkg/parse.py"


def test_without_the_run_workspace_no_tool_call_counts(tmp_path):
    db = _session(tmp_path, 4, trap_call=True)
    [r] = state_eval.evaluate(db, FAKE)
    assert r["trap_repeated"] is False and r["trap_hits"][0]["kind"] == "doubtful"


def test_trap_repeat_found_in_final_source_files_not_tests(tmp_path):
    db = _session(tmp_path, 4, trap_call=False)
    ws = tmp_path / "ws"
    (ws / "pkg").mkdir(parents=True)
    (ws / "tests").mkdir()
    (ws / "pkg" / "parse.py").write_text("cents = int(float(text) * 100)\n", encoding="utf-8")
    (ws / "pkg" / "notes.py").write_text('"""Never int(float(x) * 100)."""\n# int(float(\n',
                                         encoding="utf-8")
    (ws / "tests" / "test_x.py").write_text("int(float('1'))\n", encoding="utf-8")
    [r] = state_eval.evaluate(db, FAKE, workspace=ws)
    assert r["trap_hits"] == [
        {"where": "file", "path": "pkg/notes.py", "pattern": FAKE.TRAP_PATTERNS[0],
         "kind": "doubtful"},
        {"where": "file", "path": "pkg/parse.py", "pattern": FAKE.TRAP_PATTERNS[0],
         "kind": "code"}]
    assert r["trap_repeated"] is True and r["trap_doubtful"] == 1


@pytest.mark.parametrize("tool, args", [
    # OpenCode: write/edit with filePath; multiedit's edits.
    ("write", {"filePath": SOURCE, "content": "c = int(float(p) * 100)\n"}),
    ("edit", {"filePath": SOURCE, "oldString": "c = 0", "newString": "c = int(float(p) * 100)"}),
    ("multiedit", {"filePath": SOURCE, "edits": [
        {"oldString": "a = 1", "newString": "a = 2"},
        {"oldString": "c = 0", "newString": "c = int(float(p) * 100)"}]}),
    # Pi 1.5.0: edit with edits[{oldText, newText}].
    ("edit", {"path": SOURCE, "edits": [{"oldText": "c = 0", "newText": "c = int(float(p))"}]}),
    # Claude Code: Write/Edit with file_path.
    ("Write", {"file_path": SOURCE, "content": "c = int(float(p))\n"}),
    ("Edit", {"file_path": SOURCE, "old_string": "c = 0", "new_string": "c = int(float(p))"}),
])
def test_every_harness_write_shape_is_read(tmp_path, tool, args):
    """Harness neutrality: the trap written through any harness's write or edit counts."""
    db = _session(tmp_path, 4, trap_call=(tool, args))
    [r] = state_eval.evaluate(db, FAKE, run_ws=RUN_WS)
    assert r["trap_repeated"] is True and r["trap_hits"][0]["kind"] == "code"


@pytest.mark.parametrize("tool, args", [
    ("edit", {"path": SOURCE, "edits": [{"oldText": "c = int(float(p))", "newText": "c = 0"}]}),
    ("multiedit", {"filePath": SOURCE, "edits": [
        {"oldString": "c = int(float(p))", "newString": "c = to_cents(p)"}]}),
])
def test_old_text_in_an_edit_list_is_removal_not_a_repeat(tmp_path, tool, args):
    db = _session(tmp_path, 4, trap_call=(tool, args))
    [r] = state_eval.evaluate(db, FAKE, run_ws=RUN_WS)
    assert r["trap_repeated"] is False and r["trap_hits"][0]["kind"] == "doubtful"


def test_a_trap_split_across_lines_is_found(tmp_path):
    """The arguments are JSON: a pattern spanning a newline is searched in the decoded
    text, not the escaped ``\\n``."""
    db = _session(tmp_path, 4, trap_call=("write", {"path": SOURCE,
                                                   "content": "c = int(\n    float(p) * 100)\n"}))
    [r] = state_eval.evaluate(db, FAKE, run_ws=RUN_WS)
    assert r["trap_repeated"] is True


@pytest.mark.parametrize("path", ["pkg/../../oc/tmp/probe.py", "../ws2/pkg/parse.py",
                                  str(RUN_WS / "pkg" / ".." / ".." / "oc" / "probe.py"),
                                  "pkg/conftest.py", "pkg/parse_test.py"])
def test_paths_outside_the_workspace_or_test_files_are_not_source(tmp_path, path):
    db = _session(tmp_path, 4, trap_call=("write", {"path": path, "content": "c = int(float(p))\n"}))
    [r] = state_eval.evaluate(db, FAKE, run_ws=RUN_WS)
    assert r["trap_repeated"] is False


def test_code_outside_comments_and_strings():
    code = state_eval.code_only
    assert "int(float(" in code("x = int(float(p) * 100)  # int(float( again\n")
    assert "int(float(" not in code("# int(float(p))\ns = 'int(float(p))'\n")
    assert "int(float(" not in code('"""\nint(float(p))\n"""\n')
    # An f-string's text is a string; the code in its replacement fields runs.
    assert "int(float(" in code("c = f'{int(float(p) * 100)}'\n")
    assert "int(float(" not in code("c = f'never int(float(p)) {x}'\n")
    # Offsets follow the tokenizer's lines, so a form feed or a lone CR in a comment
    # does not shift later spans.
    assert "int(float(" not in code("# a\x0cb\rc\ns = 'int(float(p))'\n")
    assert "int(float(" in code("# a\x0cb\rc\ns = int(float(p))\n")
    # A fragment that does not tokenize (an edit's newString) still loses its comments
    # and complete strings.
    assert "int(float(" in code("    return int(float(p) * 100\n")
    assert "int(float(" not in code("  # int(float(p)\n  s = 'int(float(p)'\n  )")


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
