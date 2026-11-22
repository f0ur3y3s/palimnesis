"""Phase 7 unseen-set controls and the sealed dataset's hashes and shape."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval"), str(ROOT / "eval" / "tasks")]
import heldout  # noqa: E402
import needle  # noqa: E402
import needle_opencode  # noqa: E402
import needle_strata  # noqa: E402
import report  # noqa: E402
import run as task_run  # noqa: E402
import state_eval  # noqa: E402

sys.path.remove(str(ROOT / "eval"))
sys.path.remove(str(ROOT / "eval" / "tasks"))

CLEAN = {"commit": "abc", "dirty": False, "status": []}


def _unlock_root(tmp_path: Path, unlocked, heading: str | None = "## D115: the protocol") -> Path:
    (tmp_path / "eval").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "decisions").mkdir(parents=True, exist_ok=True)
    if unlocked is not None:
        text = unlocked if isinstance(unlocked, str) else json.dumps({"unlocked": unlocked})
        (tmp_path / "eval" / "heldout_unlock.json").write_text(text, encoding="utf-8")
    (tmp_path / "docs" / "decisions" / "phase7.md").write_text(
        "# Phase 7 decisions\n\n## D111: scope\n" + (f"\n{heading}\n" if heading else ""),
        encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("set_name, task_id", [("heldout4", "ho4-t1"), ("heldout5", "ho5-t7"),
                                               ("heldout6", "ho6-t10")])
def test_unseen_sets_refused_without_unlock(tmp_path, set_name, task_id):
    assert heldout.UNSEEN_SETS == ("heldout4", "heldout5", "heldout6")
    assert state_eval.REFUSED_SETS == heldout.UNSEEN_SETS
    assert heldout.set_of_task(task_id) == set_name
    assert heldout.set_of_task("ho3-t1") is None and heldout.set_of_task("dev-t1") is None
    # No unlock file: locked.
    root = _unlock_root(tmp_path, None)
    assert not heldout.is_unlocked(set_name, root=root, committed=True)
    with pytest.raises(heldout.Locked, match="D96"):
        heldout.require_unlocked(set_name, root=root, committed=True)
    assert "D96" in heldout.run_refusal(set_name, CLEAN, root=root, committed=True)
    # Seen and retired sets are not unseen sets.
    for s in ("development", "heldout", "heldout2", "heldout3"):
        assert heldout.unlock_problem(s, root=root) is None
    assert task_run.task_refusal("ho3-t1", CLEAN) is None


@pytest.mark.parametrize("set_name, task_id", [("heldout6", "ho6-t10")])
def test_sets_the_repository_still_locks_are_refused_by_every_tool(set_name, task_id):
    # The repository's own unlock file does not list the set: every analysis tool refuses,
    # before anything of the set is read.
    assert not heldout.is_unlocked(set_name)
    with pytest.raises(ValueError, match="D96"):
        state_eval.task_module(task_id)
    assert state_eval.main(["nowhere", "--task", task_id]) == 2
    with pytest.raises(heldout.Locked, match="D96"):
        report.expected_needles(set_name)
    # Run drivers refuse too.
    assert "D96" in task_run.task_refusal(task_id, CLEAN)
    a = argparse.Namespace(set=set_name, config=needle.A4_HELDOUT3, questions=None,
                           input_budget=None, resume=False)
    assert any("D96" in p for p in needle_opencode.refusals(a, [Path(f"{task_id}.json")]))


def test_repository_unlocks_heldout4_and_heldout5_by_d115_only():
    # D115.9: the frozen protocol unlocked heldout4 and heldout5; heldout6 stays sealed
    # for Phase 8 (D117.4).
    raw = json.loads((ROOT / heldout.UNLOCK_FILE).read_text(encoding="utf-8"))
    assert raw == {"unlocked": {"heldout4": "D115", "heldout5": "D115"}}
    assert heldout.is_unlocked("heldout4") and heldout.is_unlocked("heldout5")
    assert not heldout.is_unlocked("heldout6")


def test_unlock_needs_committed_protocol(tmp_path):
    ok = {"heldout5": "D115"}
    root = _unlock_root(tmp_path / "a", ok)
    assert heldout.is_unlocked("heldout5", root=root, committed=True)
    assert heldout.run_refusal("heldout5", CLEAN, root=root, committed=True) is None
    # Unlocked but a dirty tree: a run driver still refuses.
    assert "clean" in heldout.run_refusal("heldout5", {"dirty": True, "status": [" M x"]},
                                          root=root, committed=True)
    # Only the listed set unlocks.
    assert not heldout.is_unlocked("heldout4", root=root, committed=True)
    # Not committed.
    assert "not committed" in heldout.unlock_problem("heldout5", root=root, committed=False)
    assert "not committed" in heldout.unlock_problem("heldout5", root=root,
                                                     committed=lambda p: False)
    # No D115 heading in docs/decisions.
    assert "D115" in heldout.unlock_problem(
        "heldout5", root=_unlock_root(tmp_path / "b", ok, heading="D115 is planned"),
        committed=True)
    # Another decision named.
    assert heldout.unlock_problem("heldout5", root=_unlock_root(tmp_path / "c", {"heldout5": "D114"}),
                                  committed=True)
    # Not valid JSON.
    assert "JSON" in heldout.unlock_problem("heldout5", root=_unlock_root(tmp_path / "d", "{nope"),
                                            committed=True)


def test_unlock_file_commit_check_reads_git(tmp_path):
    root = _unlock_root(tmp_path, {"heldout5": "D115"})
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@localhost"]
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    assert not heldout.git_committed(heldout.UNLOCK_FILE, root)  # untracked
    assert not heldout.is_unlocked("heldout5", root=root)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "x"], cwd=root, check=True)
    assert heldout.git_committed(heldout.UNLOCK_FILE, root)
    assert heldout.is_unlocked("heldout5", root=root)
    (root / heldout.UNLOCK_FILE).write_text(json.dumps({"unlocked": {"heldout5": "D115",
                                                                     "heldout6": "D115"}}))
    assert not heldout.git_committed(heldout.UNLOCK_FILE, root)  # modified
    assert not heldout.is_unlocked("heldout6", root=root)


def test_heldout5_shape_and_hashes(tmp_path, capsys):
    # Shapes: ho5 has 18 histories x 10 questions; the ho6 reserve has tasks only.
    assert report.SET_SHAPE["heldout5"] == (18, 10)
    assert report.SET_SHAPE["heldout6"] == (0, 0)
    good = {f"ho5-h{i}": [{"id": f"q{k}"} for k in range(10)] for i in range(1, 19)}
    assert report.shape_problems("heldout5", good) == []
    assert report.shape_problems("heldout5", dict(list(good.items())[:12]))
    assert report.shape_problems("heldout6", {}) == []
    assert report.shape_problems("heldout6", {"ho6-h1": [{}]})
    assert needle.SETS["heldout5"] == ("heldout5", "ho5")
    assert needle.SETS["heldout6"] == ("heldout6", "ho6")
    assert {"heldout5", "heldout6"} <= set(needle.HELDOUT_SETS)
    assert not {"heldout4", "heldout5", "heldout6"} & set(needle.RETIRED_SETS)
    # Task registries name the ids; the modules need not exist yet.
    assert [t for t in task_run.TASKS if t.startswith("ho5-")] == [f"ho5-t{i}" for i in range(1, 21)]
    assert [t for t in task_run.TASKS if t.startswith("ho6-")] == [f"ho6-t{i}" for i in range(1, 11)]
    assert heldout.TASKS["heldout4"] == [f"ho4-t{i}" for i in range(1, 6)]
    with pytest.raises(LookupError, match="not present"):
        task_run.load("ho2-t99")
    # The SHA-256 manifest: seal, verify, detect a change and a missing file; no contents.
    (tmp_path / "eval" / "tasks").mkdir(parents=True)
    a, b = tmp_path / "eval" / "tasks" / "x_t1.py", tmp_path / "eval" / "tasks" / "x_t2.py"
    a.write_text("SECRET_A = 1\n", encoding="utf-8")
    b.write_text("SECRET_B = 2\n", encoding="utf-8")
    m = heldout.seal(["eval/tasks/x_t2.py", "eval/tasks/x_t1.py"], root=tmp_path)
    assert list(m["files"]) == ["eval/tasks/x_t1.py", "eval/tasks/x_t2.py"]
    assert all(len(h) == 64 for h in m["files"].values())
    assert heldout.verify(m, root=tmp_path) == {"ok": True, "checked": 2, "mismatched": [],
                                                "missing": []}
    a.write_text("SECRET_A = 3\n", encoding="utf-8")
    b.unlink()
    r = heldout.verify(m, root=tmp_path)
    assert (r["ok"], r["mismatched"], r["missing"]) == (False, ["eval/tasks/x_t1.py"],
                                                         ["eval/tasks/x_t2.py"])
    assert not heldout.verify({"files": {}}, root=tmp_path)["ok"]
    mf = tmp_path / "hashes.json"
    mf.write_text(json.dumps(m), encoding="utf-8")
    assert heldout.verify(mf, root=tmp_path)["ok"] is False
    assert "SECRET" not in json.dumps(r) + capsys.readouterr().out


def test_phase7_seal_covers_authored_files_and_history_shape():
    from palimnesis.upstreams.strata import tokens

    history_ids = [f"ho5-h{i}" for i in range(1, 19)]
    history_paths = [f"eval/needles/heldout5/{hid}.json" for hid in history_ids]
    task_paths = {
        f"eval/tasks/{tid.replace('-', '_')}.py"
        for name in ("heldout5", "heldout6")
        for tid in heldout.TASKS[name]
    }
    generators = {f"eval/needle_gen_ho5_{author}.py" for author in "abcd"}
    expected_paths = task_paths | generators | set(history_paths)
    manifest = json.loads((ROOT / heldout.HASHES_FILE).read_text(encoding="utf-8"))
    assert set(manifest["files"]) == expected_paths
    result = heldout.verify(manifest, root=ROOT)
    assert result["ok"], result

    histories = [json.loads((ROOT / path).read_text(encoding="utf-8")) for path in history_paths]
    for hid, history in zip(history_ids, histories, strict=True):
        assert history["id"] == hid and history["set"] == "heldout5", hid
        questions = [step for step in history["steps"] if step["kind"] == "question"]
        assert [step["qid"] for step in questions] == [f"Q{i}" for i in range(1, 11)], hid
        assert [step["qid"] for step in questions if step.get("restart_before")] == ["Q9"], hid
        assert [step["qid"] for step in questions if "mid_task" in step] == ["Q7"], hid
        assert all(tokens.count(step["text"]) < needle_strata.B_IN_32K for step in history["steps"]), hid
    assert not needle_strata.coverage_gaps(needle_strata.coverage(histories))
