"""D77's held-out gate on the fresh set heldout3: a4-trn2h frozen as a4-d77, the ho3 tasks
registered, and the report judging arm 4 under the a4-d77 label. Pure functions; nothing
here runs OpenCode, a proxy or a model."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval"), str(ROOT / "eval" / "tasks")]

import needle  # noqa: E402
import oc_harness  # noqa: E402
import report  # noqa: E402
import run as task_run  # noqa: E402

sys.path.remove(str(ROOT / "eval"))
sys.path.remove(str(ROOT / "eval" / "tasks"))


def test_a4_d77_is_a4_trn2h_under_its_held_out_name():
    assert needle.A4_HELDOUT3 == "a4-d77"
    assert needle.CONFIGS["a4-d77"] == needle.CONFIGS["a4-trn2h"]
    assert "a4-d77" in needle.HELDOUT_CONFIGS


def test_heldout3_is_a_held_out_set_not_retired():
    assert needle.SETS["heldout3"] == ("heldout3", "ho3")
    assert "heldout3" in needle.HELDOUT_SETS
    assert "heldout3" not in needle.RETIRED_SETS
    assert report.SET_SHAPE["heldout3"] == (12, 10)


def test_ho3_tasks_run_arm_4_only_as_a4_d77_or_a4_d43():
    info = task_run.resolve_arm(4, "a4-d77", "heldout3")
    assert (info["arm"], info["label"], info["config"]) == (4, "a4-d77", "a4-d77")
    assert task_run.resolve_arm(4, None, "heldout3")["label"] == "a4"
    with pytest.raises(ValueError, match="a4-d77"):
        task_run.resolve_arm(4, "a4-trn2h", "heldout3")
    assert task_run.resolve_arm(1, None, "heldout3")["label"] == "a1"
    assert [t for t in task_run.TASKS if t.startswith("ho3-")] == [
        "ho3-t1", "ho3-t2", "ho3-t3", "ho3-t4", "ho3-t5"]


def _ok(success: bool, restart_gate=None) -> dict:
    return {"check": {"success": success}, "restart_gate": restart_gate}


def test_heldout3_coding_gate_compares_a4_d77_with_arm_1_and_needs_ho3_t3():
    results = {(t, 4): _ok(True) for t in report.HELDOUT3_TASKS}
    results.update({(t, 1): _ok(True) for t in report.HELDOUT3_TASKS})
    results[("ho3-t3", 4)] = _ok(True, restart_gate=True)
    g = report.coding_gate(results, report.HELDOUT3_TASKS, arm=4, restart_task=report.RESTART_TASK3)
    assert g["pass"] and g["arm4_successes"] == g["arm1_successes"] == 5
    results[("ho3-t3", 4)] = _ok(True, restart_gate=False)
    assert not report.coding_gate(results, report.HELDOUT3_TASKS, arm=4,
                                  restart_task=report.RESTART_TASK3)["pass"]


def test_heldout3_results_load_arm_4_under_the_a4_d77_label(tmp_path, monkeypatch):
    seen = []

    def designate(manifest, kind, label, override):
        seen.append(label)
        return {}, []

    import attempts

    monkeypatch.setattr(attempts, "load", lambda run: {})
    monkeypatch.setattr(attempts, "designate", designate)
    report.load_task_results(tmp_path, arm4=report.A4_LABEL3)
    assert seen == ["a4-d77", "a1"]


def test_opencode_kill_reaches_the_whole_process_group_on_posix():
    if oc_harness.WINDOWS:
        pytest.skip("POSIX process groups")
    import subprocess
    import time

    p = subprocess.Popen(["sh", "-c", "sleep 60 & echo $! ; wait"], stdout=subprocess.PIPE,
                         start_new_session=True, text=True)
    child = int(p.stdout.readline())
    oc_harness.kill_tree(p)
    p.wait(timeout=10)
    for _ in range(100):
        try:
            import os

            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("the shell's child survived the kill")
