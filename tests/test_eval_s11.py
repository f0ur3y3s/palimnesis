"""Pure functions of the S11 evaluation tooling (eval/needle_gen.py, eval/oc_harness.py,
eval/needle_opencode.py, eval/tasks/run.py). Expected values are literal fixtures or the
committed needle files; nothing here runs OpenCode or a model."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval"), str(ROOT / "eval" / "tasks")]

import needle_gen  # noqa: E402
import needle_opencode  # noqa: E402
import oc_harness  # noqa: E402

sys.path.remove(str(ROOT / "eval"))
sys.path.remove(str(ROOT / "eval" / "tasks"))


# ---------------------------------------------------------------- needle sets

@pytest.mark.parametrize("i", range(6))
def test_development_set_regenerates_byte_identically(i):
    h = needle_gen.build_history(i, 3100 + i)
    committed = (ROOT / "eval" / "needles" / "dev" / f"{h['id']}.json").read_bytes()
    assert (json.dumps(h, indent=1, ensure_ascii=False) + "\n").encode("utf-8") == committed


@pytest.mark.parametrize("i", range(12))
def test_heldout_set_regenerates_byte_identically(i):
    h = needle_gen.build_heldout(i, 5200 + i)
    committed = (ROOT / "eval" / "needles" / "heldout" / f"{h['id']}.json").read_bytes()
    assert (json.dumps(h, indent=1, ensure_ascii=False) + "\n").encode("utf-8") == committed


def _skeleton(h):
    return [(s["kind"], s.get("qid"), s.get("category"), s.get("restart_before"),
             "mid_task" in s) for s in h["steps"]]


def test_heldout_keeps_the_development_skeleton():
    dev = _skeleton(needle_gen.build_history(0, 3100))
    for i in range(12):
        h = needle_gen.build_heldout(i, 9000 + i)
        assert _skeleton(h) == dev
        assert h["import"][-1] == {"role": "user", "content": h["steps"][0]["text"]}
        roles = [m["role"] for m in h["import"]]
        assert roles.count("tool") == sum(len(m.get("tool_calls") or []) for m in h["import"])


def test_heldout_themes_and_word_banks_are_disjoint_from_development():
    def tokens(themes):
        out = set()
        for t in themes:
            out |= {t["project"], t["svc"], t["db"], t["const"], *t["helper"], *t["modules"],
                    *t["clients"]}
        return out

    assert len(needle_gen.THEMES_HO) == 12
    assert not tokens(needle_gen.THEMES) & tokens(needle_gen.THEMES_HO)
    assert not set(needle_gen.VERBS) & set(needle_gen.VERBS_HO)
    assert not set(needle_gen.NOUNS) & set(needle_gen.NOUNS_HO)
    assert not set(needle_gen.ADJS) & set(needle_gen.ADJS_HO)


def test_heldout_wording_shares_no_four_word_run_with_development():
    # User turns, assistant summaries, questions and paste wrappers (not tool output or
    # paste bodies), on seeds other than the held-out ones.
    def grams(h):
        texts = [m["content"] for m in h["import"] if m["role"] == "user"]
        texts += [m["content"] for m in h["import"] if m["role"] == "assistant" and m.get("content")]
        texts += [s["text"].split("```")[0] for s in h["steps"]]
        out = set()
        for t in texts:
            w = re.findall(r"[a-z']+", t.lower())
            out |= {tuple(w[k:k + 4]) for k in range(len(w) - 3)}
        return out

    dev = set().union(*(grams(needle_gen.build_history(i, 3100 + i)) for i in range(6)))
    ho = set().union(*(grams(needle_gen.build_heldout(i, 9000 + i)) for i in range(12)))
    assert not dev & ho


def test_heldout_evidence_is_in_the_history():
    for i in range(12):
        h = needle_gen.build_heldout(i, 9000 + i)
        text = "\n".join((m.get("content") or "") + json.dumps(m.get("tool_calls") or "")
                         for m in h["import"]) + "\n".join(s["text"] for s in h["steps"])
        for s in h["steps"]:
            if s["kind"] == "question":
                for e in s["evidence"]:
                    assert e in text, (h["id"], s["qid"], e)


# ---------------------------------------------------------------- OpenCode export format

def test_opencode_id_matches_observed_shape():
    # Observed in a 2.1.4 export: msg_1737216e2001S9Byc4shWJMkOp (counter 1).
    ms = (0x1A1 << 36) + (0x1737216E2001 >> 12)
    assert oc_harness.opencode_id("msg", ms, 1, "S9Byc4shWJMkOp") == "msg_1737216e2001S9Byc4shWJMkOp"
    # Session ids count down: the bitwise inverse of the same 48 bits.
    assert oc_harness.opencode_id("ses", ms, 1, "x" * 14, descending=True) == \
        f"ses_{0xFFFFFFFFFFFF - 0x1737216E2001:012x}" + "x" * 14


HISTORY = [
    {"role": "user", "content": "read a.txt"},
    {"role": "assistant", "content": None, "reasoning_content": "look first",
     "tool_calls": [{"id": "call_a", "type": "function",
                     "function": {"name": "read", "arguments": '{"path":"a.txt"}'}}]},
    {"role": "tool", "tool_call_id": "call_a", "content": "Read file a.txt, lines 1-1\n1: alpha"},
    {"role": "assistant", "content": "It says alpha."},
    {"role": "assistant", "content": "", "reasoning_content": "only thinking"},
]


def test_history_to_export_shape():
    doc = oc_harness.history_to_export(HISTORY, directory="C:\\w", project_id="p0",
                                       t0_ms=1_800_000_000_000, seed=3)
    assert doc["info"]["projectID"] == "p0"
    assert doc["info"]["location"] == {"directory": "C:\\w"}
    assert doc["info"]["id"].startswith("ses_")
    msgs = doc["messages"]
    assert [m["type"] for m in msgs] == ["user", "assistant", "assistant", "assistant", "idle"]
    assert msgs[0]["text"] == "read a.txt" and msgs[0]["files"] == []
    tool_step = msgs[1]
    assert [p["type"] for p in tool_step["content"]] == ["reasoning", "tool"]
    assert tool_step["content"][0]["text"] == "look first"
    assert tool_step["content"][0]["native"] == {"reasoningField": "reasoning_content"}
    tool = tool_step["content"][1]
    assert (tool["id"], tool["name"], tool["state"]["status"]) == ("call_a", "read", "completed")
    assert tool["state"]["input"] == {"path": "a.txt"}
    assert tool["state"]["content"] == [{"type": "text", "text": "Read file a.txt, lines 1-1\n1: alpha"}]
    assert (tool_step["finish"], tool_step["rawFinish"]) == ("tool-calls", "tool_calls")
    assert msgs[2]["content"] == [{"type": "text", "text": "It says alpha."}]
    assert msgs[2]["finish"] == "stop"
    assert [p["type"] for p in msgs[3]["content"]] == ["reasoning"]
    ids = [m["id"] for m in msgs]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    created = [m["time"]["created"] for m in msgs]
    assert created == sorted(created)
    assert oc_harness.history_to_export(HISTORY, directory="C:\\w", project_id="p0",
                                        t0_ms=1_800_000_000_000, seed=3) == doc


def test_history_to_export_rejects_unpaired_tool_messages():
    with pytest.raises(ValueError, match="without a call"):
        oc_harness.history_to_export(
            [{"role": "user", "content": "x"}, {"role": "tool", "tool_call_id": "c9", "content": "r"}],
            directory="d", project_id="p", t0_ms=0)
    with pytest.raises(ValueError, match="has no result"):
        oc_harness.history_to_export(HISTORY[:2], directory="d", project_id="p", t0_ms=0)


def test_import_fidelity_normalizes_only_empty_reasoning():
    sent = [{"role": "system", "content": "sys"},
            {**HISTORY[0]}, {**HISTORY[1]}, {**HISTORY[2]},
            {"role": "assistant", "content": "It says alpha.", "reasoning_content": ""},
            {**HISTORY[4]}, {"role": "user", "content": "q1"}]
    r = needle_opencode.import_fidelity({"messages": sent}, HISTORY, "q1")
    assert r["faithful"] and r["first_diff"] is None and r["empty_reasoning_added"] == 1
    changed = [dict(m) for m in sent]
    changed[4]["content"] = "It says beta."
    r = needle_opencode.import_fidelity({"messages": changed}, HISTORY, "q1")
    assert not r["faithful"] and r["first_diff"] == 3
    r = needle_opencode.import_fidelity({"messages": sent[:-1]}, HISTORY, "q1")
    assert r["first_diff"] == 5


def _ev(kind, mid, **part):
    return {"type": kind, "sessionID": "ses_x", "part": {"messageID": mid, **part}}


def test_turn_summary_takes_the_last_step_text():
    # 2.1.4 shape: a tool step ends with step_finish "tool-calls"; the last step has none.
    events = [_ev("step_start", "m1"),
              _ev("tool_use", "m1", tool="read", state={"status": "completed", "input": {"path": "a"},
                                                         "output": "Read file a"}),
              _ev("step_finish", "m1", reason="tool-calls"),
              _ev("step_start", "m2"), _ev("text", "m2", text="LED-5964-T")]
    s = needle_opencode.turn_summary(events)
    assert s["final"] == "LED-5964-T"
    assert s["tools"] == [{"name": "read", "input": {"path": "a"}, "status": "completed",
                           "output_chars": 11}]
    assert s["finishes"] == ["tool-calls"] and s["steps"] == 2


def test_turn_summary_without_a_final_text():
    events = [_ev("step_start", "m1"),
              _ev("tool_use", "m1", tool="shell", state={"status": "error", "input": {}, "error": "boom"})]
    s = needle_opencode.turn_summary(events)
    assert s["final"] is None and s["tools"][0]["status"] == "error"
    assert needle_opencode.turn_summary([])["final"] is None


# ---------------------------------------------------------------- coding tasks

def _runner():
    sys.path[:0] = [str(ROOT / "eval"), str(ROOT / "eval" / "tasks")]
    try:
        import run as task_run
    finally:
        sys.path.remove(str(ROOT / "eval"))
        sys.path.remove(str(ROOT / "eval" / "tasks"))
    return task_run


def test_score_check_counts_unreported_tests_as_failed():
    score = _runner().score_check
    c = {"C1": "a", "C2": "b", "C3": "c"}
    expected = ["test_f_a", "test_f_b", "test_c1_x", "test_c2_x", "test_c2_y", "test_c3_z"]
    r = score({"test_f_a": "ok", "test_f_b": "ok", "test_c1_x": "ok", "test_c2_x": "ok",
               "test_c2_y": "FAIL"}, expected, c)
    assert r["success"] and r["functional_passed"] == 2
    assert r["constraints"] == {"C1": True, "C2": False, "C3": False}
    assert r["constraints_held"] == 1 and r["missing"] == ["test_c3_z"]
    # Only the names the run reported: a silent test_f_b must not let success through.
    assert not score({"test_f_a": "ok"}, expected, c)["success"]
    assert not score({}, expected, c)["success"]
    assert not score({"test_f_a": "ok"}, [], c)["success"]


class _Task:
    ID = "probe"
    CONSTRAINTS = {"C1": "x"}

    def __init__(self, hidden):
        self.HIDDEN = {"_check/test_hidden.py": hidden}


STDERR_THEN_FAIL = """import sys
import unittest


class HiddenTests(unittest.TestCase):
    def test_f_noisy(self):
        print("line one\\nline two ... ok", file=sys.stderr)
        sys.stderr.write("partial line without newline ... ")
        self.fail("after stderr output")

    def test_c1_fine(self):
        self.assertTrue(True)
"""


def test_a_failing_test_that_writes_to_stderr_scores_as_a_failure(tmp_path):
    task_run = _runner()
    ws = tmp_path / "repo"
    ws.mkdir()
    (tmp_path / "check").mkdir()
    r = task_run.run_check(_Task(STDERR_THEN_FAIL), ws, tmp_path / "check", sys.executable)
    assert r["results"] == {"test_f_noisy": "FAIL", "test_c1_fine": "ok"}
    assert r["success"] is False and r["constraints"] == {"C1": True}
    assert not (ws / "_check").exists()  # the hidden check is written only into the copy


def test_a_hidden_check_that_does_not_import_fails_every_test(tmp_path):
    task_run = _runner()
    ws = tmp_path / "repo"
    ws.mkdir()
    (tmp_path / "check").mkdir()
    hidden = "import not_a_module_anywhere\n" + STDERR_THEN_FAIL
    r = task_run.run_check(_Task(hidden), ws, tmp_path / "check", sys.executable)
    assert r["success"] is False and r["constraints"] == {"C1": False}
    assert set(r["missing"]) == {"test_f_noisy", "test_c1_fine"}


def test_a_hidden_check_that_times_out_fails_with_a_reason(tmp_path):
    task_run = _runner()
    ws = tmp_path / "repo"
    ws.mkdir()
    (tmp_path / "check").mkdir()
    hidden = ("import time\nimport unittest\n\n\nclass HiddenTests(unittest.TestCase):\n"
              "    def test_f_slow(self):\n        time.sleep(60)\n")
    r = task_run.run_check(_Task(hidden), ws, tmp_path / "check", sys.executable, timeout=2)
    assert r["success"] is False and r["reason"] == "check_timeout"


def test_restart_gate_needs_success_and_the_key_constraint():
    task_run = _runner()
    t = task_run.load("ho-t3")
    assert task_run.restart_gate(t, {"success": True, "constraints": {"C1": True, "C2": True}})
    assert not task_run.restart_gate(t, {"success": True, "constraints": {"C2": False}})
    assert not task_run.restart_gate(t, {"success": False, "constraints": {"C2": True}})
    assert task_run.restart_gate(task_run.load("ho-t1"), {"success": True}) is None


def test_task_definitions():
    task_run = _runner()
    restart_tasks = []
    for tid in task_run.TASKS:
        t = task_run.load(tid)
        assert t.ID == tid
        assert t.SET == ("development" if tid.startswith("dev-") else "heldout")
        assert 0 < t.RESTART_BEFORE < len(t.TURNS)
        assert set(t.CONSTRAINTS) == {"C1", "C2", "C3"} and t.TRAP
        hidden = "\n".join(t.HIDDEN.values())
        for cid in t.CONSTRAINTS:
            assert f"def test_c{cid[1:]}_" in hidden, (tid, cid)
        assert "def test_f_" in hidden
        files = t.files(__import__("random").Random(1))
        assert not set(files) & set(t.HIDDEN)
        if t.KEY_CONSTRAINT:
            restart_tasks.append(tid)
    assert [t for t in restart_tasks if t.startswith("ho-")] == ["ho-t3"]
    assert sum(t.startswith("dev-") for t in task_run.TASKS) == 3
    assert sum(t.startswith("ho-") for t in task_run.TASKS) == 5


def test_restart_task_states_its_key_constraint_only_before_the_restart():
    t = _runner().load("ho-t3")
    assert "<input>.redacted" in t.TURNS[0] and "exit code 3" in t.TURNS[0]
    for turn in t.TURNS[1:]:
        assert ".redacted" not in turn and "exit code 3" not in turn
    before = " ".join(t.TURNS[1:t.RESTART_BEFORE]).lower()
    assert "command-line" not in before and "main(" not in before
    assert "main(argv)" in t.TURNS[t.RESTART_BEFORE]


@pytest.mark.parametrize("tid", ["dev-t1", "dev-t2", "dev-t3", "ho-t1", "ho-t2", "ho-t3", "ho-t4",
                                 "ho-t5"])
def test_hidden_check_passes_the_reference_and_fails_the_stub(tid):
    task_run = _runner()
    t = task_run.load(tid)
    ref = task_run.check_one(t, t.REFERENCE, sys.executable)
    assert ref["success"] and ref["constraints_held"] == ref["constraints_total"] == 3, ref["tail"]
    stub = task_run.check_one(t, {}, sys.executable)
    assert not stub["success"] and stub["functional_passed"] == 0


def test_is_compaction_recognizes_the_observed_prompts():
    is_compaction = _runner().is_compaction
    for text in ("You MUST summarize the conversation above into a structured summary ...",
                 "Update the existing checkpoint in the conversation above into one ...",
                 "The previous response did not fill in the required summary template. ..."):
        assert is_compaction({"messages": [{"role": "system", "content": "s"},
                                           {"role": "user", "content": text}], "tools": [{}]})
    assert not is_compaction({"messages": [{"role": "user", "content": "Summarize the file."}]})
    assert not is_compaction({"messages": [{"role": "tool", "content": "You MUST summarize"}]})
    assert not is_compaction({"messages": []})
