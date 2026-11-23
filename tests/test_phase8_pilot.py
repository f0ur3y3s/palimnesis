"""Phase 8 S3 pilot arms and the ho5 retirement in code (D117.4, D120.3, D125).

ho5 was retired to development data at Phase 7's close (D117.4), so its tasks take any
configuration. ho4 stays unopened and ho6 stays sealed: neither is retired. The pilot's
two candidate arms are a4-d77 with notes format n3 (D121, D122), alone and with D65's
pinned instructions."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "eval" / "tasks"))
import needle  # noqa: E402
import run as task_run  # noqa: E402

sys.path.remove(str(ROOT / "eval"))
sys.path.remove(str(ROOT / "eval" / "tasks"))


def test_ho5_is_retired_and_ho4_ho6_are_not():
    assert "heldout5" in needle.RETIRED_SETS
    assert {"heldout2", "heldout3"} <= set(needle.RETIRED_SETS)
    assert not {"heldout4", "heldout6"} & set(needle.RETIRED_SETS)
    assert task_run.RETIRED_SETS == needle.RETIRED_SETS


def test_the_pilot_arms_are_a4_d77_plus_n3_and_pins():
    base = needle.CONFIGS["a4-d77"]
    assert base.get("notes_format") == "n2"
    assert needle.CONFIGS["a4-n3"] == {**base, "notes_format": "n3"}
    assert needle.CONFIGS["a4-n3p"] == {**base, "notes_format": "n3", "pin_tokens": 4096}


def test_retired_ho5_runs_a_pilot_arm_and_sealed_ho6_refuses_it():
    for cfg in ("a4-n3", "a4-n3p"):
        arm = task_run.resolve_arm(4, cfg, "heldout5")
        assert arm["label"] == cfg and arm["cfg"] == needle.CONFIGS[cfg]
        with pytest.raises(ValueError, match="held-out tasks run arm 4 only"):
            task_run.resolve_arm(4, cfg, "heldout6")
    assert task_run.resolve_arm(4, "a4-d77", "heldout5")["label"] == "a4-d77"


# --- eval/pilot_s3.py: schedule, selection, report lines ---------------------------------

sys.path.insert(0, str(ROOT / "eval"))
import pilot_s3  # noqa: E402
import run_ready  # noqa: E402

sys.path.remove(str(ROOT / "eval"))


def test_schedule_runs_every_arm_once_per_task_per_round_in_seeded_order():
    s = pilot_s3.schedule(7)
    assert s == pilot_s3.schedule(7) and s != pilot_s3.schedule(8)
    assert len(s) == 3 * (5 + 3) + 3 * 3 == 33
    r1 = [x for x in s if x[0] == "r1"]
    r2 = [x for x in s if x[0] == "r2"]
    assert s == r1 + r2  # round 2 starts after round 1
    for rd, tasks in (("r1", pilot_s3.DEV + pilot_s3.HO5), ("r2", pilot_s3.HO5)):
        got = [(t, a) for r, t, a in s if r == rd]
        assert sorted(got) == sorted((t, a) for t in tasks for a in pilot_s3.ARMS)
    for i in range(0, len(s), 3):  # a task's three arms run back to back
        assert len({(r, t) for r, t, _ in s[i:i + 3]}) == 1


def test_spec_steps_call_run_py_per_round_directory():
    spec = pilot_s3.make_spec(seed=7, python="py", root="captures/p", ws_root=r"C:\ws",
                              opencode="oc.exe")
    first = spec["steps"][0]
    rd, task, arm = pilot_s3.schedule(7)[0]
    assert first["name"] == f"{rd} {task} {arm}"
    argv = first["argv"]
    assert argv[:2] == ["py", "eval/tasks/run.py"]
    assert argv[argv.index("--out") + 1] == f"captures/p/{rd}"
    assert argv[argv.index("--config") + 1] == arm and argv[argv.index("--task") + 1] == task
    assert argv[argv.index("--expect-n-ctx") + 1] == "32768"
    assert spec["server"]["temperature"] == 1.0 and spec["env"] == {"OPENCODE_EXE": "oc.exe"}


def _arm(repeats=0, successes=11, constraints=(30, 33), retention=(4, 4), chars=3000.0,
         disputed=(), unscored=()):
    return {"attempts": 11, "repeats": repeats, "disputed": list(disputed),
            "unscored": list(unscored), "successes": successes, "constraints": constraints,
            "retention": retention, "notes_chars_mean": chars, "hand": ["r1:ho5-t2"]}


def _select(**arms):
    base = {"a4-d77": _arm(repeats=3, retention=(1, 4)), "a4-n3": _arm(), "a4-n3p": _arm()}
    return pilot_s3.select({**base, **arms})


def test_selection_rules():
    # Both eligible: the smaller notes win; on a tie, a4-n3 (no pins).
    assert _select(**{"a4-n3p": _arm(chars=2000.0)})["candidate"] == "a4-n3p"
    assert _select()["candidate"] == "a4-n3"
    # V-n1: one lost warning at the trap turn.
    s = _select(**{"a4-n3": _arm(retention=(3, 4))})
    assert s["checks"]["a4-n3"]["V-n1"] is False and s["candidate"] == "a4-n3p"
    # V-n2: a single repeat, a disputed or an unscored attempt.
    for bad in (_arm(repeats=1), _arm(disputed=["r2:ho5-t4"]), _arm(unscored=["r1:dev-t9"])):
        assert _select(**{"a4-n3": bad, "a4-n3p": bad})["candidate"] is None
    # No regression: more than one success or constraint below the control.
    assert _select(**{"a4-n3": _arm(successes=10)})["candidate"] == "a4-n3"
    s = _select(**{"a4-n3": _arm(successes=9), "a4-n3p": _arm(constraints=(28, 33))})
    assert s["candidate"] is None
    assert s["checks"]["a4-n3"]["no_regression"] is False


def _gate_reads(text, tmp_path):
    f = tmp_path / "report.txt"
    f.write_text(text, encoding="utf-8")
    return run_ready._evidence({"report_output": str(f)})[2]


def test_an_empty_pilot_reports_every_cell_missing_and_the_gate_reads_it(tmp_path):
    rep = pilot_s3.pilot_report(pilot_s3.collect(tmp_path / "nothing"))
    assert len(rep["missing"]) == 33 and rep["selection"]["candidate"] is None
    text = "\n".join(pilot_s3.format_report(rep))
    assert "unscored a4-d77:r1:" in text
    assert not _gate_reads(text, tmp_path)["ok"]


def test_a_complete_pilot_report_passes_the_gate_reader(tmp_path):
    rows = [{"round": rd, "task": t, "arm": a, "present": True, "usable": True, "aborted": None,
             "verdict": "clean", "reviewed": False, "success": True, "constraints": (3, 3),
             "notes": {"at_need": "kept", "versions": 5, "sections": [], "notes_chars_mean": 2500.0}}
            for rd, t, a in pilot_s3.schedule(1)]
    rep = pilot_s3.pilot_report(rows)
    text = "\n".join(pilot_s3.format_report(rep))
    assert "unscored none" in text and "missing attempts: none" in text
    assert _gate_reads(text, tmp_path)["ok"]
    assert rep["arms"]["a4-n3"]["retention"] == (4, 4)
    assert rep["selection"]["candidate"] == "a4-n3"


def test_the_rehearsal_report_covers_only_its_task(tmp_path):
    rep = pilot_s3.pilot_report(pilot_s3.collect(tmp_path / "nothing", only={"dev-t6"}))
    assert rep["missing"] == ["r1:dev-t6:a4-d77", "r1:dev-t6:a4-n3", "r1:dev-t6:a4-n3p"]


def test_the_rehearsal_spec_is_the_pilot_spec_cut_to_its_task():
    full = pilot_s3.make_spec(seed=7, python="py", root="r", ws_root="w", opencode="o")
    reh = pilot_s3.make_spec(seed=7, python="py", root="r", ws_root="w", opencode="o",
                             only={"dev-t6"})
    assert reh["steps"] == [s for s in full["steps"] if " dev-t6 " in s["name"]]
    assert len(reh["steps"]) == 3 and reh["config"] != full["config"]
