"""Phase 7 S4: traps for any arm (``eval/state_eval.py``, ``eval/tasks/run.py``).

Trap hits come from the captured upstream request bodies as well as the archive, keyed by
protocol (Chat ``tool_calls``, Messages ``tool_use``) and classified by the same D109
rule. Eligibility is judged at the trap turn (``TRAP_TURN``). ``test_t_*`` is scored apart
from success, and ``--check-reference`` runs the trap solution. Every task here is
synthetic."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from .test_notes_http import BUDGET, _body
from .test_state_eval import FAKE, RUN_WS, SOURCE, _session
from .test_state_golden import _answer
from .test_view_http import post, view_stack

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval"), str(ROOT / "eval" / "tasks")]
import run as task_run  # noqa: E402
import state_eval  # noqa: E402

sys.path.remove(str(ROOT / "eval"))
sys.path.remove(str(ROOT / "eval" / "tasks"))

STATEMENT = "Rules: cents are integers. We already tried int(float(p) * 100); 0.29 became 28."
TRAP_ASK = "Now add parse_total(lines) to pkg/parse.py."
TASK = SimpleNamespace(ID="fake-t9", TRAP_PATTERNS=(r"int\(\s*float\(",),
                       TURNS=[STATEMENT, "turn 2", "turn 3", "turn 4", "turn 5", "turn 6",
                              TRAP_ASK, "turn 8"], TRAP_TURN=6)


def _write_bodies(d: Path, bodies: list[dict]) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for n, b in enumerate(bodies, 1):
        (d / f"{n:04d}.json").write_text(json.dumps(b), encoding="utf-8")
    (d / "0001.resp.sse").write_text("data: {}\n\n", encoding="utf-8")  # not a request
    return d


def _chat_call(cid, name, args) -> dict:
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def test_trap_hits_from_chat_bodies_passthrough_arm(tmp_path):
    trap = _chat_call("call_1", "write", {"filePath": SOURCE, "content": "c = int(float(p) * 100)\n"})
    grep = _chat_call("call_2", "grep", {"pattern": "int(float("})
    # A call with no id, repeated at the same position in a later body: one call.
    anon = {"role": "assistant", "content": None, "tool_calls": [
        {"type": "function", "function": {"name": "bash", "arguments": '{"command": "int(float(1))"}'}}]}
    h1 = [{"role": "system", "content": "s"}, {"role": "user", "content": STATEMENT}]
    h2 = h1 + [trap, {"role": "tool", "tool_call_id": "call_1", "content": "ok"}]
    h3 = h2 + [anon, {"role": "tool", "content": "1"}]
    h4 = h3 + [grep, {"role": "tool", "tool_call_id": "call_2", "content": "x"}]
    d = _write_bodies(tmp_path / "bodies", [{"messages": h} for h in (h1, h2, h3, h4)])
    calls = state_eval.body_tool_calls(state_eval.read_bodies(d))
    assert [(c["n"], c["tool"]) for c in calls] == [(2, "write"), (3, "bash"), (4, "grep")]
    r = state_eval.evaluate_bodies(d, TASK, run_ws=RUN_WS)
    assert [(h["body"], h["tool"], h["kind"]) for h in r["trap_hits"]] == [
        (2, "write", "code"), (3, "bash", "doubtful"), (4, "grep", "doubtful")]
    assert r["trap_hits"][0]["path"] == "pkg/parse.py"
    assert r["trap_doubtful"] == 2 and r["source"] == "bodies"
    # The same classifier as the archive path: without the run workspace nothing is code.
    r = state_eval.evaluate_bodies(d, TASK)
    assert {h["kind"] for h in r["trap_hits"]} == {"doubtful"}


def test_trap_hits_from_messages_bodies(tmp_path):
    def use(cid, name, inp):
        return {"type": "tool_use", "id": cid, "name": name, "input": inp}

    first = {"role": "assistant", "content": [
        {"type": "text", "text": "Writing it."},
        use("toolu_1", "Write", {"file_path": SOURCE, "content": "c = int(float(p))\n"})]}
    result = {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "int(float( done"}]}
    second = {"role": "assistant", "content": [
        use("toolu_2", "edit", {"path": SOURCE, "edits": [{"oldText": "c = int(float(p))",
                                                           "newText": "c = cents(p)"}]})]}
    h1 = [{"role": "user", "content": [{"type": "text", "text": STATEMENT}]}]
    h2 = h1 + [first, result]
    h3 = h2 + [second, {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_2", "content": "ok"}]}]
    d = _write_bodies(tmp_path / "bodies", [{"system": "s", "messages": h, "max_tokens": 10}
                                            for h in (h1, h2, h3)])
    r = state_eval.evaluate_bodies(d, TASK, run_ws=RUN_WS)
    # The tool result is not a generated call; the edit's old text is removal (doubtful).
    assert [(h["body"], h["tool"], h["kind"]) for h in r["trap_hits"]] == [
        (2, "Write", "code"), (3, "edit", "doubtful")]


def test_need_turn_eligibility_collapsed_before_trap_turn(tmp_path):
    """The candidate (archive): eligible at need when the view in force for the trap
    turn's request had collapsed the statement. In this fixture the statement is
    ``Instruction 0`` and request k carries ``Instruction {k + 2}`` as its newest turn."""
    (tmp_path / "long").mkdir()
    (tmp_path / "short").mkdir()
    db = _session(tmp_path / "long", 4, trap_call=True)
    turns = ["Instruction 0: implement part 0.", "Instruction 1", "Instruction 2",
             "Now finish the last part."] + [f"Instruction {k}: what was the code?"
                                             for k in (3, 4, 5)]
    late = SimpleNamespace(ID="fake-t1", TRAP_PATTERNS=FAKE.TRAP_PATTERNS, TURNS=turns,
                           TRAP_TURN=6)  # the fourth request
    [r] = state_eval.evaluate(db, late, run_ws=RUN_WS)
    assert r["trap_eligible_at_need"] is True and r["trap_repeat_at_need"] is True
    # The end-of-session fields are kept.
    assert r["eligible"] is True and r["trap_repeated"] is True
    # Without TRAP_TURN (older tasks), or a trap turn never sent: None.
    [r] = state_eval.evaluate(db, FAKE, run_ws=RUN_WS)
    assert r["trap_eligible_at_need"] is None and r["trap_repeat_at_need"] is None
    [r] = state_eval.evaluate(db, SimpleNamespace(**{**vars(late), "TURNS": turns[:6] + ["never"]}))
    assert r["trap_eligible_at_need"] is None
    # A short session whose view never moved: the statement is in view at the trap turn.
    short = [f"short turn {k}" for k in range(8)]
    with view_stack(tmp_path / "short", input_budget=BUDGET, notes_tokens=2048,
                    notes_format="n2") as (fake, url, s):
        messages = [{"role": "system", "content": "You are a coding agent."}]
        for k, text in enumerate(short):
            messages.append({"role": "user", "content": text})
            _answer(fake, f"answer {k}")
            assert post(url, _body(messages)).status_code == 200
            messages.append({"role": "assistant", "content": f"answer {k}"})
        db = s.db_path
    task = SimpleNamespace(ID="fake-t3", TRAP_PATTERNS=FAKE.TRAP_PATTERNS, TURNS=short, TRAP_TURN=6)
    [r] = state_eval.evaluate(db, task, run_ws=RUN_WS)
    assert r["trap_eligible_at_need"] is False and r["trap_repeat_at_need"] is None


def test_arm1_eligibility_compaction_before_trap_turn(tmp_path):
    """Arm 1 (bodies): eligible at need when the trap turn's first request no longer
    carries the turn-1 statement in full, because native compaction replaced it."""
    trap = _chat_call("call_9", "edit", {"filePath": SOURCE, "oldString": "pass",
                                        "newString": "return int(float(t) * 100)"})
    early = [{"role": "system", "content": "s"}, {"role": "user", "content": STATEMENT},
             {"role": "assistant", "content": "ok"}]
    kept = early + [{"role": "user", "content": f"<wrapped>{TRAP_ASK}</wrapped>"}]
    summary = [{"role": "system", "content": "s"},
               {"role": "user", "content": "Summary: cents are integers; parse.py done."},
               {"role": "user", "content": TRAP_ASK}]
    # Not compacted before the trap turn: the statement is still in view.
    d = _write_bodies(tmp_path / "a", [{"messages": early}, {"messages": kept},
                                       {"messages": kept + [trap]}])
    r = state_eval.evaluate_bodies(d, TASK, run_ws=RUN_WS)
    assert (r["trap_turn_body"], r["trap_eligible_at_need"], r["trap_repeat_at_need"]) == (2, False, None)
    # Compacted before the trap turn: eligible, and the repeat counts.
    d = _write_bodies(tmp_path / "b", [{"messages": early}, {"messages": early + [
        {"role": "user", "content": "You MUST summarize the conversation above"}]},
        {"messages": summary}, {"messages": summary + [trap]}])
    r = state_eval.evaluate_bodies(d, TASK, run_ws=RUN_WS)
    assert (r["trap_turn_body"], r["trap_eligible_at_need"], r["trap_repeat_at_need"]) == (3, True, True)
    assert r["eligible"] is None and r["trap_repeated"] is None
    # No TRAP_TURN, or a trap turn never sent: None.
    old = SimpleNamespace(ID="fake-t2", TRAP_PATTERNS=TASK.TRAP_PATTERNS, TURNS=TASK.TURNS)
    assert state_eval.evaluate_bodies(d, old)["trap_eligible_at_need"] is None
    d = _write_bodies(tmp_path / "c", [{"messages": early}])
    assert state_eval.evaluate_bodies(d, TASK)["trap_eligible_at_need"] is None


def test_t_scored_apart_from_success():
    c = {"C1": "x"}
    expected = ["test_f_a", "test_c1_x", "test_t_trap", "test_t_other"]
    r = task_run.score_check({"test_f_a": "ok", "test_c1_x": "ok", "test_t_trap": "FAIL",
                              "test_t_other": "ok"}, expected, c)
    assert r["success"] is True and r["functional_total"] == 1
    assert r["constraints"] == {"C1": True}
    assert r["trap_tests"] == {"passed": False, "failed": ["test_t_trap"], "total": 2}
    # A trap test that did not report counts as failed; success does not depend on it.
    r = task_run.score_check({"test_f_a": "ok", "test_t_trap": "ok"}, expected, c)
    assert r["success"] is True and r["trap_tests"]["failed"] == ["test_t_other"]
    # A failed functional test fails success whatever the trap tests say.
    r = task_run.score_check({"test_f_a": "FAIL", "test_t_trap": "ok", "test_t_other": "ok"},
                             expected, c)
    assert r["success"] is False and r["trap_tests"]["passed"] is True
    # No test_t_*: None.
    assert task_run.score_check({"test_f_a": "ok"}, ["test_f_a"], {})["trap_tests"] == {
        "passed": None, "failed": [], "total": 0}
    # The hidden-check markers include trap test definitions.
    t = SimpleNamespace(HIDDEN={"_check/test_hidden.py": "class HiddenTests:\n"
                                                        "    def test_t_trap(self):\n        pass\n"})
    assert "def test_t_trap(self):" in task_run.hidden_markers(t)


# ---------------------------------------------------------------- --check-reference

STUB = '''def cents(text):
    raise NotImplementedError
'''
VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pkg.money import cents  # noqa: E402


class VisibleTests(unittest.TestCase):
    def test_whole(self):
        self.assertEqual(cents("7"), 700)

    def test_two_places(self):
        self.assertEqual(cents("12.50"), 1250)
'''
HIDDEN = '''import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pkg.money import cents  # noqa: E402


class HiddenTests(unittest.TestCase):
    def test_f_values(self):
        self.assertEqual(cents("1.50"), 150)
        self.assertEqual(cents("2.25"), 225)

    def test_c1_signature(self):
        self.assertEqual(list(inspect.signature(cents).parameters), ["text"])

    def test_t_float_rounding(self):
        self.assertEqual(cents("0.29"), 29)
        self.assertEqual(cents("1.15"), 115)
'''
REFERENCE = '''def cents(text):
    whole, _, frac = text.partition(".")
    return int(whole) * 100 + int(frac.ljust(2, "0") or 0)
'''
TRAP = '''def cents(text):
    return int(float(text) * 100)
'''


def _check_task(**kw):
    base = dict(ID="syn-t1", SET="development", CONSTRAINTS={"C1": "keep cents(text)"},
                files=lambda rnd: {"pkg/__init__.py": "", "pkg/money.py": STUB,
                                   "tests/test_money.py": VISIBLE},
                HIDDEN={"_check/test_hidden.py": HIDDEN}, REFERENCE={"pkg/money.py": REFERENCE},
                TRAP_SOLUTION={"pkg/money.py": TRAP}, TRAP_PATTERNS=(r"int\(\s*float\(",),
                TURNS=["t"] * 8, TRAP_TURN=6)
    return SimpleNamespace(**{**base, **kw})


def test_check_reference_runs_trap_solution():
    py = sys.executable
    r = task_run.check_task_reference(_check_task(), python=py)
    assert r["checks"] == {"contract": True, "reference": True, "stub": True, "trap": True,
                           "patterns": True}
    assert r["ok"] is True
    # A trap solution the trap tests do not catch fails the trap check.
    r = task_run.check_task_reference(_check_task(TRAP_SOLUTION={"pkg/money.py": REFERENCE.replace(
        "def cents(text):", "def cents(text):  # int(float(text) * 100) avoided")}), python=py)
    assert r["checks"]["trap"] is False and r["checks"]["patterns"] is False and not r["ok"]
    # A trap solution that fails a visible test fails the trap check.
    r = task_run.check_task_reference(_check_task(TRAP_SOLUTION={"pkg/money.py": TRAP.replace(
        "return", "return 1 + ")}), python=py)
    assert r["checks"]["trap"] is False
    # A pattern that also matches the reference fails the pattern check.
    r = task_run.check_task_reference(_check_task(TRAP_PATTERNS=(r"int\(",)), python=py)
    assert r["checks"]["patterns"] is False
    # Patterns are alternative forms of the trap: one matching the trap solution is enough,
    # as long as none matches the reference (D112).
    r = task_run.check_task_reference(_check_task(
        TRAP_PATTERNS=(r"int\(\s*float\(", r"Decimal\(\s*float\(")), python=py)
    assert r["checks"]["patterns"] is True
    r = task_run.check_task_reference(_check_task(
        TRAP_PATTERNS=(r"Decimal\(\s*float\(",)), python=py)
    assert r["checks"]["patterns"] is False
    # TRAP_TURN must be at least 5.
    r = task_run.check_task_reference(_check_task(TRAP_TURN=3), python=py)
    assert r["checks"]["contract"] is False
    # A task without a trap solution keeps the old two checks.
    r = task_run.check_task_reference(_check_task(TRAP_SOLUTION=None, TRAP_TURN=None), python=py)
    assert r["checks"] == {"reference": True, "stub": True} and r["ok"]
