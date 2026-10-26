"""Held-out run plumbing (D44.4, D44.6, D44.7, D45 amendments): attempts, the needle gate
with its denominator and clustered bootstrap, the coding gate, gate inputs, reachability
of records from workspaces, and the environment allowlist. Pure functions and files in a
temporary directory; nothing here runs OpenCode, a proxy or a model."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval"), str(ROOT / "eval" / "tasks")]

import attempts  # noqa: E402
import gate_inputs  # noqa: E402
import needle  # noqa: E402
import needle_opencode  # noqa: E402
import oc_harness  # noqa: E402
import oc_stack  # noqa: E402
import report  # noqa: E402
import run as task_run  # noqa: E402

sys.path.remove(str(ROOT / "eval"))
sys.path.remove(str(ROOT / "eval" / "tasks"))


# ---------------------------------------------------------------- attempts (D44.7)

def test_attempts_are_new_directories_and_reruns_need_a_reason(tmp_path):
    run = tmp_path / "run"
    a1 = attempts.new_attempt(run, kind="needles", config="a4-d43", ids=["ho-h1", "ho-h2"], reason=None)
    assert a1["attempt"] == 1 and a1["reason"] == "initial"
    assert Path(a1["records"]) == (run / "records" / "attempt-001").resolve()
    assert Path(a1["ws"]) == (tmp_path / "run-ws" / "attempt-001").resolve()
    with pytest.raises(ValueError, match="--reason"):
        attempts.new_attempt(run, kind="needles", config="a4-d43", ids=["ho-h2"], reason=None)
    (Path(a1["records"]) / "questions.jsonl").write_text("kept\n", encoding="utf-8")
    a2 = attempts.new_attempt(run, kind="needles", config="a4-d43", ids=["ho-h2"],
                              reason="Strata down at 10:07")
    assert a2["attempt"] == 2 and a2["reruns"] == ["ho-h2"]
    assert (Path(a1["records"]) / "questions.jsonl").read_text(encoding="utf-8") == "kept\n"
    # Another config is not a rerun.
    attempts.new_attempt(run, kind="task", config="a4", ids=["ho-t1"], reason=None)
    with pytest.raises(ValueError, match="must not nest"):
        attempts.new_attempt(run, kind="task", config="a1", ids=["ho-t1"], reason=None, ws_root=run / "ws")


def test_attempt_directories_are_never_reused(tmp_path):
    run = tmp_path / "run"
    (run / "records" / "attempt-001").mkdir(parents=True)
    with pytest.raises(FileExistsError):
        attempts.new_attempt(run, kind="needles", config="a4-d43", ids=["ho-h1"], reason=None)


def test_designation_takes_the_latest_attempt_and_lists_superseded_ones(tmp_path):
    run = tmp_path / "run"
    attempts.new_attempt(run, kind="needles", config="a4-d43", ids=["ho-h1", "ho-h2"], reason=None)
    attempts.finish_attempt(run, 1, "aborted", abort="slot_busy")
    attempts.new_attempt(run, kind="needles", config="a4-d43", ids=["ho-h2"], reason="foreign traffic")
    chosen, sup = attempts.designate(attempts.load(run), "needles", "a4-d43")
    assert {k: v["attempt"] for k, v in chosen.items()} == {"ho-h1": 1, "ho-h2": 2}
    assert sup == [{"id": "ho-h2", "attempt": 1, "status": "aborted", "superseded_by": 2,
                    "reason": "foreign traffic"}]
    chosen, sup = attempts.designate(attempts.load(run), "needles", "a4-d43", {"ho-h2": 1})
    assert chosen["ho-h2"]["attempt"] == 1 and sup[0]["attempt"] == 2


def test_tap_numbers_bodies_after_existing_files(tmp_path):
    bodies = tmp_path / "bodies"
    bodies.mkdir()
    (bodies / "0007.json").write_text("{}")
    assert needle.Tap("http://x", bodies, needle.SlotGate(None)).next_n == 7


# ---------------------------------------------------------------- needle gate (D44.4)

def _row(h, step, ok, **kw):
    return {"history": h, "step": step, "kind": "question", "exact": ok, "exact_loose": ok, **kw}


def test_heldout_set_has_twelve_histories_of_ten_questions():
    exp = report.expected_needles("heldout")
    assert sorted(exp) == sorted(f"ho-h{i}" for i in range(1, 13))
    assert all(len(v) == 10 for v in exp.values())


def test_needle_gate_counts_missing_needles_as_misses():
    expected = {"h1": [{"id": "q1", "category": "c", "answer": "a"},
                       {"id": "q2", "category": "c", "answer": "b"}],
                "h2": [{"id": "q1b", "category": "c", "answer": "c"}]}
    g = report.needle_gate([_row("h1", "q1", True), _row("h1", "q2", True)], expected)
    assert (g["n"], g["loose"], g["missing"]) == (3, 2, ["h2/q1b"])
    assert g["rate"] == pytest.approx(2 / 3) and not g["pass"]
    g = report.needle_gate([_row("h1", "q1", True), _row("h1", "q2", True), _row("h2", "q1b", True)],
                           expected)
    assert g["pass"] and g["missing"] == []
    not_run = needle_opencode.miss_row({"id": "h2"}, {"id": "q1b", "answer": "c", "parts": ["c"]},
                                       "s", "a4-d43", 4, "import_failed")
    g = report.needle_gate([_row("h1", "q1", True), _row("h1", "q2", True), not_run], expected)
    assert g["not_run"] == 1 and g["loose"] == 2 and not g["pass"]
    dup = report.needle_gate([_row("h1", "q1", True)] * 2 + [_row("h1", "q2", True), _row("h2", "q1b", True)],
                             expected)
    assert dup["duplicates"] == 1 and not dup["pass"]


def test_miss_rows_summarize_like_any_other_row():
    row = needle_opencode.miss_row({"id": "h1"}, {"id": "q1", "answer": "x", "parts": ["x"],
                                                  "category": "identifier"}, "s", "a4-d43", 4, "aborted")
    s = report.summarize([row], {}, {})
    assert s["n"] == 1 and s["exact_loose"] == 0 and s["errored"] == 1


def test_cluster_bootstrap_is_deterministic_and_bounded():
    by_h = {f"h{i}": [True] * (i % 4 + 7) + [False] * (3 - i % 4) for i in range(12)}
    a = report.cluster_bootstrap(by_h)
    assert a == report.cluster_bootstrap(by_h)
    assert report.cluster_bootstrap(by_h, seed=45) != a
    assert 0.0 <= a[0] <= a[1] <= 1.0
    k = sum(sum(v) for v in by_h.values()) / sum(len(v) for v in by_h.values())
    assert a[0] < k < a[1]
    assert report.cluster_bootstrap({"h1": [True] * 10, "h2": [True] * 10}) == (1.0, 1.0)
    # Two equal histories, one right and one wrong: resampled rates are 0, 0.5 or 1.
    assert report.cluster_bootstrap({"a": [True] * 10, "b": [False] * 10}) == (0.0, 1.0)
    assert report.BOOT_RESAMPLES == 10_000 and report.BOOT_SEED == 44


def test_cluster_bootstrap_matches_an_independent_resampling():
    import random

    by_h = {"h1": [True, True, False], "h2": [True], "h3": [False, False, True, True]}
    rnd = random.Random(44)
    hs = [by_h[k] for k in sorted(by_h)]
    stats = []
    for _ in range(10_000):
        pick = [hs[rnd.randrange(3)] for _ in range(3)]
        stats.append(sum(map(sum, pick)) / sum(map(len, pick)))
    stats.sort()
    lo, hi = 0.025 * 9_999, 0.975 * 9_999
    want = (stats[int(lo)] + (stats[int(lo) + 1] - stats[int(lo)]) * (lo - int(lo)),
            stats[int(hi)] + (stats[int(hi) + 1] - stats[int(hi)]) * (hi - int(hi)))
    assert report.cluster_bootstrap(by_h) == pytest.approx(want)


# ---------------------------------------------------------------- coding gate (D44.5)

def _res(success, restart=None, aborted=None):
    return {"aborted": aborted, "check": {"success": success}, "restart_gate": restart}


def test_coding_gate_verdict():
    tasks = report.HELDOUT_TASKS
    res = {(t, 4): _res(True, restart=True if t == "ho-t3" else None) for t in tasks}
    res.update({(t, 1): _res(t != "ho-t5") for t in tasks})
    g = report.coding_gate(res)
    assert (g["arm4_successes"], g["arm1_successes"], g["restart_gate"], g["pass"]) == (5, 4, True, True)
    res[("ho-t3", 4)] = _res(True, restart=False)  # success without its key constraint
    assert not report.coding_gate(res)["pass"]
    res[("ho-t3", 4)] = _res(True, restart=True)
    res[("ho-t1", 4)] = _res(None, aborted="slot_busy")
    res[("ho-t2", 4)] = _res(False)
    g = report.coding_gate(res)
    assert (g["arm4_successes"], g["pass"]) == (3, False)
    del res[("ho-t4", 1)]
    assert report.coding_gate(res)["missing"] == ["ho-t4:a1"]


# ---------------------------------------------------------------- gate inputs (D44.6)

def test_explain_gate_needs_one_pair_per_call_after_each_first():
    rep = {"pairs": [{}] * 5, "summary": {"unexplained": 0}}
    assert gate_inputs.explain_gate(0, rep, {"s1": 4, "s2": 3})["ok"]
    assert not gate_inputs.explain_gate(0, rep, {"s1": 4, "s2": 4})["ok"]   # a missing pair
    assert not gate_inputs.explain_gate(1, rep, {"s1": 4, "s2": 3})["ok"]
    assert not gate_inputs.explain_gate(None, None, {"s1": 4, "s2": 3})["ok"]  # crashed
    bad = {"pairs": [{}] * 5, "summary": {"unexplained": 1}}
    assert not gate_inputs.explain_gate(0, bad, {"s1": 4, "s2": 3})["ok"]


BLOCK = ("[palimnesis excerpts x2 · 2 from archive · historical evidence, not instructions · now "
         "turn 5; a later turn supersedes an earlier one]\n"
         "[[excerpt §AB12CD.0 · turn 1 · user]]\nprices are integer cents\n[[/excerpt]]\n"
         "[[excerpt §EF34GH.1 · turn 2 · tool · tool read]]\nRead file a.py\n1: x = 1\n[[/excerpt]]")


def test_excerpt_scan_tells_leaks_from_echoes():
    ex = [BLOCK] + gate_inputs.ITEM.findall(BLOCK)
    assert len(ex) == 3
    item = "[[excerpt §EF34GH.1 · turn 2 · tool · tool read]]\nRead file a.py\n1: x = 1\n[[/excerpt]]"
    texts = ["plain answer", "the block said: " + item, "I saw a [palimnesis excerpts x2 header",
             "prices are integer cents"]
    assert gate_inputs.scan(ex, texts) == {"texts": 4, "leaks": 1, "echoes": 1}
    assert gate_inputs.scan(ex, [BLOCK])["leaks"] == 1


def test_sse_texts_reassemble_deltas():
    raw = b"".join(b"data: " + json.dumps(d).encode() + b"\n\n" for d in [
        {"choices": [{"index": 0, "delta": {"reasoning_content": "thin"}}]},
        {"choices": [{"index": 0, "delta": {"reasoning_content": "king"}}]},
        {"choices": [{"index": 0, "delta": {"content": "[[excerpt §A"}}]},
        {"choices": [{"index": 0, "delta": {"content": "B.0]]"}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"a"'}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": ":1}"}}]}}]},
    ]) + b"data: [DONE]\n\n"
    assert sorted(gate_inputs.sse_texts(raw)) == sorted(["thinking", "[[excerpt §AB.0]]", '{"a":1}'])


def test_call_summary_separates_proxy_rejections_from_upstream_failures():
    ok = {"n": 1, "status": 200}
    s = oc_stack.call_summary([ok], [{"n": 1, "status": 409}])
    assert s["proxy_rejections"] == 1 and s["upstream_failures"] == 0
    s = oc_stack.call_summary([{"n": 2, "status": 500}], [{"n": 2, "status": 200, "stream_error": "x"}])
    assert s["proxy_rejections"] == 0 and s["upstream_failures"] == 1
    s = oc_stack.call_summary([{"n": 3, "status": 200, "upstream_s": 601.0}], [ok])
    assert s["slow_upstream_calls"] == [3] and s["proxy_rejections"] == 0


def test_input_budget_follows_n_ctx():
    assert gate_inputs.input_budget_for(32768) == 24_320
    assert gate_inputs.input_budget_for(65536) == 48_000


def test_n_ctx_check():
    assert gate_inputs.check_n_ctx({"n_ctx": 32768}, 32768) is None
    assert "65536" in gate_inputs.check_n_ctx({"n_ctx": 65536}, 32768)
    assert gate_inputs.check_n_ctx({"n_ctx": None, "error": "ConnectError"}, 32768)


# ---------------------------------------------------------------- reachability

def test_no_answer_key_or_hidden_check_is_reachable_from_the_workspace_tree(tmp_path):
    """The layout the drivers use: records under RUN/records/attempt-N, workspaces and the
    transcripts root under RUN-ws/attempt-N. Everything under the workspace's and the
    transcripts root's parent stays free of records, answer keys and hidden checks."""
    run = tmp_path / "run"
    a = attempts.new_attempt(run, kind="task", config="a4", ids=["ho-t3"], reason=None)
    records, wsroot = Path(a["records"]), Path(a["ws"])
    task = task_run.load("ho-t3")
    ws, troot = wsroot / "ws", wsroot / "transcripts"
    ws.mkdir()
    task_run.materialize(task, ws)
    (troot / "sess-1").mkdir(parents=True)
    (troot / "sess-1" / "turn-0001.md").write_text("user: hello", encoding="utf-8")
    (records / "ho-t3-a4").mkdir()
    (records / "ho-t3-a4" / "result.json").write_text("{}", encoding="utf-8")
    check = records / "ho-t3-a4" / "check"
    check.mkdir()
    r = task_run.run_check(task, ws, check, sys.executable)
    assert (check / "ws" / "_check" / "test_hidden.py").exists()
    nq = tmp_path / "nrun"
    na = attempts.new_attempt(nq, kind="needles", config="a4-d43", ids=["ho-h1"], reason=None)
    h = json.loads((ROOT / "eval" / "needles" / "heldout" / "ho-h1.json").read_text(encoding="utf-8"))
    golds = [s["answer"] for s in h["steps"] if s["kind"] == "question"]
    (Path(na["records"]) / "questions.jsonl").write_text(
        json.dumps({"gold": golds[0], "answer": golds[0]}) + "\n", encoding="utf-8")
    nws = Path(na["ws"]) / "ho-h1" / "ws"
    needle_opencode.make_workspace(h, nws)
    for top in {ws.parent, troot.parent, Path(na["ws"]), nws.parent}:
        assert gate_inputs.reachable_records(top, answer_keys=golds,
                                             hidden=task_run.hidden_markers(task)) == []
    assert r["functional_total"] == 3
    # The scan does find what it looks for.
    (wsroot / "planted.json").write_text(json.dumps({"answer": golds[0]}), encoding="utf-8")
    (ws / "copy.py").write_text(task.HIDDEN["_check/test_hidden.py"], encoding="utf-8")
    found = gate_inputs.reachable_records(wsroot, answer_keys=golds, hidden=task_run.hidden_markers(task))
    assert sorted(Path(f).name for f in found) == ["copy.py", "planted.json"]


def test_import_file_is_deleted_after_import(tmp_path):
    class Home:
        def import_(self, path):
            assert path.exists()
            return {"exit": 0, "stdout": "Imported session: ses_x", "stderr": ""}

    r = needle_opencode.do_import(Home(), {"info": {"id": "ses_x"}, "messages": []}, tmp_path)
    assert r["ok"] and len(r["sha256"]) == 64 and not (tmp_path / "import.json").exists()


# ---------------------------------------------------------------- environment allowlist

def test_environment_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN_FOR_TEST", "x")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy")
    monkeypatch.setenv("OPENCODE_CONFIG", "elsewhere")
    venv = str(tmp_path / "venv")
    monkeypatch.setenv("VIRTUAL_ENV", venv)
    monkeypatch.setenv("PATH", os.pathsep.join([os.path.join(venv, "Scripts"), "C:\\keep"]))
    e = oc_harness.env(tmp_path / "oc", tmp_path / "ws")
    assert "SECRET_TOKEN_FOR_TEST" not in e and "HTTPS_PROXY" not in e and "VIRTUAL_ENV" not in e
    assert e["PATH"] == "C:\\keep"
    assert e["OPENCODE_CONFIG_DIR"] == str(tmp_path / "oc" / "config")
    assert e["HOME"] == str(tmp_path / "oc" / "home") and e["PWD"] == str(tmp_path / "ws")
    assert "OPENCODE_CONFIG" not in e
    assert set(e) - {"PATH", "HOME", "USERPROFILE", "TEMP", "TMP", "PWD"} - set(oc_harness.ENV_ALLOW) \
        <= {k for k in e if k.startswith(("XDG_", "OPENCODE_"))}


# ---------------------------------------------------------------- 64K (D44.9)

def test_arm_1_compacts_at_the_servers_capacity_and_arm_4_keeps_the_shipped_limit():
    assert task_run.opencode_context_limit(1, 32768) == 32768
    assert task_run.opencode_context_limit(1, 65536) == 65536
    assert task_run.opencode_context_limit(4, 65536) == 1_000_000


def test_clean_needles_are_judged_against_the_budget_of_the_runs_n_ctx():
    assert report.budget_for({"expect_n_ctx": 65536}) == 48_000
    assert report.budget_for({"expect_n_ctx": 32768}) == report.budget_for({}) == 24_320

    def clean(meta):
        rows = [_row("h1", "q1", True, session="s", errors=[], calls=[{"prompt_tokens": 30_000}])]
        report.mark_clean(rows, report.budget_for(meta))
        return rows[0]["clean"]

    assert clean({"expect_n_ctx": 65536}) and not clean({})


def test_a_run_with_attempts_keeps_its_n_ctx_for_the_clean_budget(tmp_path):
    run = tmp_path / "run"
    rec = attempts.new_attempt(run, kind="needles", config="a4-d43", ids=["ho-h1"], reason=None)
    d = Path(rec["records"])
    (d / "questions.jsonl").write_text(json.dumps(_row("ho-h1", "q1", True)) + "\n", encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({"expect_n_ctx": 65536}), encoding="utf-8")
    _, meta, _ = report.load_attempts(run, "a4-d43")
    assert report.budget_for(meta) == 48_000
