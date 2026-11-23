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
    # Both eligible: a4-n3 (no pins), whatever the notes lengths; a4-n3p only alone.
    assert _select(**{"a4-n3p": _arm(chars=2000.0)})["candidate"] == "a4-n3"
    assert _select()["candidate"] == "a4-n3"
    assert _select(**{"a4-n3": _arm(repeats=1)})["candidate"] == "a4-n3p"
    # A non-kept state awaiting its hand read leaves V-n1 unsettled.
    pend = {**_arm(), "retention_pending": ["r2:ho5-t13"]}
    assert _select(**{"a4-n3": pend})["checks"]["a4-n3"]["V-n1"] is False
    # V-n1: one lost warning at the trap turn.
    s = _select(**{"a4-n3": _arm(retention=(3, 4))})
    assert s["checks"]["a4-n3"]["V-n1"] is False and s["candidate"] == "a4-n3p"
    # V-n2 (D126): a repeat with the warning lost, a disputed or an unscored attempt.
    for bad in (_arm(repeats=1), _arm(disputed=["r2:ho5-t4"]), _arm(unscored=["r1:dev-t9"])):
        assert _select(**{"a4-n3": bad, "a4-n3p": bad})["candidate"] is None
    # A repeat made with the warning held in the notes does not fail V-n2; D125's rule,
    # reported beside it, does.
    held = {**_arm(repeats=1), "repeats_lost": [], "repeats_held": ["r2:ho5-t4"]}
    s = _select(**{"a4-n3": held, "a4-n3p": held})
    assert s["candidate"] == "a4-n3" and s["checks"]["a4-n3"]["V-n2 (D125)"] is False
    lost = {**_arm(repeats=1), "repeats_lost": ["r2:ho5-t4"], "repeats_held": []}
    assert _select(**{"a4-n3": lost, "a4-n3p": lost})["candidate"] is None
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


def _row(rd, t, a, at_need="kept", review=None):
    return {"round": rd, "task": t, "arm": a, "present": True, "usable": True, "aborted": None,
            "verdict": "clean", "reviewed": False, "success": True, "constraints": (3, 3),
            "notes": {"at_need": at_need, "versions": 5, "sections": [], "notes_chars_mean": 2500.0},
            "retention_review": review}


def test_a_non_kept_state_waits_for_its_hand_read_and_the_read_settles_it():
    rows = [_row(rd, t, a) for rd, t, a in pilot_s3.schedule(1)]
    i = next(k for k, r in enumerate(rows)
             if (r["round"], r["task"], r["arm"]) == ("r2", "ho5-t13", "a4-n3"))
    rows[i] = _row("r2", "ho5-t13", "a4-n3", at_need="omitted")
    rep = pilot_s3.pilot_report(rows)
    assert rep["arms"]["a4-n3"]["retention"] == (3, 4)
    assert rep["arms"]["a4-n3"]["retention_pending"] == ["r2:ho5-t13"]
    assert "retention to hand-read r2:ho5-t13" in "\n".join(pilot_s3.format_report(rep))
    assert rep["selection"]["candidate"] == "a4-n3p"
    rows[i] = _row("r2", "ho5-t13", "a4-n3", at_need="omitted", review=True)  # paraphrased, kept
    rep = pilot_s3.pilot_report(rows)
    assert rep["arms"]["a4-n3"]["retention"] == (4, 4)
    assert rep["selection"]["candidate"] == "a4-n3"
    rows[i] = _row("r2", "ho5-t13", "a4-n3", at_need="omitted", review=False)
    assert pilot_s3.pilot_report(rows)["arms"]["a4-n3"]["retention"] == (3, 4)


def test_the_rehearsal_is_round_one_of_dev_t6_and_ho5_t13_in_spec_and_report(tmp_path):
    full = pilot_s3.make_spec(seed=8125, python="py", root="r", ws_root="w", opencode="o")
    reh = pilot_s3.make_spec(seed=8125, python="py", root="r", ws_root="w", opencode="o",
                             only={"dev-t6", "ho5-t13"}, rounds={"r1"})
    assert reh["config"] == "s3-pilot-seed8125-dev-t6+ho5-t13-r1"
    assert reh["steps"] == [s for s in full["steps"] if s["name"].startswith("r1 ")
                            and s["name"].split()[1] in ("dev-t6", "ho5-t13")]
    assert len(reh["steps"]) == 6
    rep = pilot_s3.pilot_report(pilot_s3.collect(tmp_path / "nothing", only={"dev-t6", "ho5-t13"},
                                                 rounds={"r1"}))
    assert sorted(rep["missing"]) == sorted(f"r1:{t}:{a}" for t in ("dev-t6", "ho5-t13")
                                            for a in pilot_s3.ARMS)


def test_an_unknown_round_is_refused():
    with pytest.raises(SystemExit, match="unknown rounds"):
        pilot_s3.main(["report", "x", "--rounds", "r3"])


def test_repeats_split_by_whether_the_notes_held_the_warning():
    rows = [_row(rd, t, a) for rd, t, a in pilot_s3.schedule(1)]
    def put(rd, t, a, **kw):
        i = next(k for k, r in enumerate(rows) if (r["round"], r["task"], r["arm"]) == (rd, t, a))
        rows[i] = {**_row(rd, t, a, **{k: v for k, v in kw.items() if k != "verdict"}),
                   "verdict": kw.get("verdict", "clean")}
    put("r2", "ho5-t4", "a4-n3", verdict="repeat")                       # held: kept
    put("r1", "ho5-t4", "a4-d77", verdict="repeat", at_need="omitted")   # lost, unread
    put("r2", "ho5-t2", "a4-d77", verdict="repeat", review=False)        # hand read: lost
    put("r1", "ho5-t2", "a4-n3p", verdict="repeat", at_need="kept", review=False)  # hand read wins
    rep = pilot_s3.pilot_report(rows)
    assert rep["arms"]["a4-n3"]["repeats_held"] == ["r2:ho5-t4"]
    assert rep["arms"]["a4-n3"]["repeats_lost"] == []
    assert rep["arms"]["a4-d77"]["repeats_lost"] == ["r1:ho5-t4", "r2:ho5-t2"]
    assert rep["arms"]["a4-n3p"]["repeats_lost"] == ["r1:ho5-t2"]
    assert rep["selection"]["candidate"] == "a4-n3"
    text = "\n".join(pilot_s3.format_report(rep))
    assert "a4-n3: repeats with the warning lost none; with the warning held r2:ho5-t4" in text


# --- D126: the S3 candidate is named a8 and `serve` ships it ---------------------------

def test_a8_is_a4_n3_and_serve_ships_it(tmp_path):
    from palimnesis.cli import serve_settings
    from palimnesis.config import Settings

    assert needle.CONFIGS["a8"] == needle.CONFIGS["a4-n3"]
    served = serve_settings(["--upstream", "http://u:8080", "--db", str(tmp_path / "a.db")])
    base = Settings(upstream_base_url="http://u:8080")
    a8 = needle.CONFIGS["a8"]
    assert {k: getattr(served, k) for k in needle.PROXY_KEYS} == {
        k: a8.get(k, getattr(base, k)) for k in needle.PROXY_KEYS}
    # a8 is a4-d77 (D78's default) with notes format n3 and nothing else.
    d77 = needle.CONFIGS["a4-d77"]
    assert {k for k in set(a8) | set(d77) if a8.get(k) != d77.get(k)} == {"notes_format"}


# --- D137 pilot (eval/pilot_n3fix.py) ---------------------------------------------------

sys.path.insert(0, str(ROOT / "eval"))
import pilot_n3fix  # noqa: E402

sys.path.remove(str(ROOT / "eval"))


def test_the_n3fix_pilot_runs_a8_on_the_ho5_traps_in_two_rounds():
    spec = pilot_n3fix.make_spec(python="py", root="r", ws_root="w", opencode="o")
    assert [s["name"] for s in spec["steps"]] == [
        f"{rd} {t} a8" for rd in ("r1", "r2") for t in ("ho5-t2", "ho5-t4", "ho5-t13")]
    argv = spec["steps"][0]["argv"]
    assert argv[argv.index("--config") + 1] == "a8" and argv[argv.index("--out") + 1] == "r/r1"
    assert needle.CONFIGS["a8"]["notes_format"] == "n3"
    reh = pilot_n3fix.make_spec(python="py", root="r", ws_root="w", opencode="o",
                                tasks=("ho5-t13",), rounds=("r1",))
    assert len(reh["steps"]) == 1 and reh["config"] == "n3fix-pilot-ho5-t13-r1"


def _n3row(rd, t, at_need="kept", copies=1, chars=5000.0, review=None):
    return {"round": rd, "task": t, "present": True, "usable": True, "copies": copies,
            "notes": {"at_need": at_need, "notes_chars_mean": chars}, "retention_review": review}


def test_the_n3fix_pilot_report_checks_retention_length_and_duplicates(tmp_path):
    rows = [_n3row(rd, t) for rd in ("r1", "r2") for t in ("ho5-t2", "ho5-t4", "ho5-t13")]
    ev = pilot_n3fix.evaluate(rows)
    assert ev["pass"] and ev["retention"] == (4, 4)
    text = "\n".join(pilot_n3fix.format_report(ev, rows))
    assert "unscored none" in text and "missing attempts: none" in text
    rows[1] = _n3row("r1", "ho5-t4", copies=3)
    assert pilot_n3fix.evaluate(rows)["checks"]["no_duplicates"] is False
    rows[1] = _n3row("r1", "ho5-t4", at_need="omitted")
    ev = pilot_n3fix.evaluate(rows)
    assert ev["retention_pending"] == ["r1:ho5-t4"] and not ev["pass"]
    rows[1] = _n3row("r1", "ho5-t4", at_need="omitted", review=True)
    assert pilot_n3fix.evaluate(rows)["pass"]
    rows = [_n3row(rd, t, chars=6000.0) for rd in ("r1", "r2") for t in ("ho5-t2", "ho5-t4", "ho5-t13")]
    assert pilot_n3fix.evaluate(rows)["checks"]["shorter_than_r69"] is False
    empty = pilot_n3fix.collect(tmp_path / "none")
    assert len(pilot_n3fix.evaluate(empty)["missing"]) == 6


# --- Phase 8 confirmatory spec and report (eval/confirm_p8.py) ---------------------------

sys.path.insert(0, str(ROOT / "eval"))
import confirm_p8  # noqa: E402

sys.path.remove(str(ROOT / "eval"))


def test_the_confirmatory_schedule_pairs_arms_per_task_per_attempt_then_needles():
    s = confirm_p8.schedule(5)
    tasks = [x for x in s if x[0] == "task"]
    needles = [x for x in s if x[0] == "needle"]
    assert len(tasks) == 30 * 2 * 3 and len(needles) == 30
    assert s[-30:] == needles  # needles after every task attempt
    for i in range(0, len(tasks), 2):  # both arms back to back, same task and attempt
        (_, k1, t1, a1), (_, k2, t2, a2) = tasks[i], tasks[i + 1]
        assert (k1, t1) == (k2, t2) and {a1, a2} == {"a8", "a1"}
    assert [k for _, k, _, _ in tasks] == sorted(k for _, k, _, _ in tasks)
    assert {t for _, _, t, _ in tasks} == set(confirm_p8.TASKS)
    assert confirm_p8.schedule(5) == s and confirm_p8.schedule(6) != s


def test_the_confirmatory_spec_argv():
    spec = confirm_p8.make_spec(seed=5, python="py", root="r", ws_root="w", opencode="o")
    assert spec["config"] == "p8-confirm-seed5" and len(spec["steps"]) == 210
    t = next(st["argv"] for st in spec["steps"] if st["name"].endswith(" a8"))
    assert t[t.index("--config") + 1] == "a8" and t[t.index("--arm") + 1] == "4"
    b = next(st["argv"] for st in spec["steps"] if st["name"].endswith(" a1") and st["name"].startswith("k"))
    assert b[b.index("--arm") + 1] == "1" and "--config" not in b
    n = spec["steps"][-1]["argv"]
    assert n[1:3] == ["eval/needle.py", "run"] and n[n.index("--set") + 1] == "heldout7"
    reh = confirm_p8.make_spec(seed=5, python="py", root="r", ws_root="w", opencode="o",
                               tasks=("ho5-t4", "ho5-t13"), histories=("ho5-h1",), needle_set="heldout5")
    assert len(reh["steps"]) == 2 * 2 * 3 + 1 and reh["config"].endswith("-2t1h3k")


def _res(ok=True, held=(True, True), repeat=False, inputs=True):
    return {"check": {"success": ok, "constraints": {f"C{i}": h for i, h in enumerate(held)},
                      "trap_tests": {"passed": not repeat}},
            "state_eval": {"trap_hits": [{"kind": "code"}] if repeat else []},
            "explain_gate": {"ok": inputs}, "verify": {"exit": 0}, "over_budget": {"ok": True},
            "excerpt_scan": {"client": {"leaks": 0}, "transcripts": {"leaks": 0}}}


def test_majority_of_three_and_the_report():
    assert confirm_p8.majority([True, True, False]) and not confirm_p8.majority([True, None, False])
    tasks = ("ho6-t1", "ho6-t9", "ho7-t1")
    results = {k: {} for k in (1, 2, 3)}
    for k in (1, 2, 3):
        results[k][("ho6-t1", "a8")] = _res(ok=k != 3)          # 2/3: success
        results[k][("ho6-t1", "a1")] = _res(ok=k == 1)          # 1/3: failure
        results[k][("ho6-t9", "a8")] = _res()
        results[k][("ho6-t9", "a1")] = _res(ok=False)
        results[k][("ho7-t1", "a8")] = _res(repeat=k == 2)      # one attempt repeats the trap
        if k != 3:
            results[k][("ho7-t1", "a1")] = _res()               # k3 missing: still 2/3
    rep = confirm_p8.confirm_report(results, tasks, resamples=200, seed=1)
    p = rep["primary"]
    assert (p["candidate"], p["baseline"], p["b"], p["c"]) == (3, 1, 2, 0) and p["gate"]
    s = rep["sensitivity"]
    assert (s["n"], s["b"]) == (2, 1)  # without ho6-t9
    assert rep["traps"]["a8"]["repeats"] == ["ho7-t1"] and not rep["traps"]["a8"]["gate"]
    assert rep["missing"] == ["k3:ho7-t1:a1"]
    assert rep["constraints"]["a8"]["total"] == 18
    text = "\n".join(confirm_p8.format_report(rep))
    assert "missing attempts: k3:ho7-t1:a1" in text and "unscored a1:k3:ho7-t1" in text


def test_a8_is_a_held_out_configuration_and_ho6_ho7_unlock_under_d138(tmp_path):
    import heldout

    assert "a8" in needle.HELDOUT_CONFIGS
    assert task_run.resolve_arm(4, "a8", "heldout7")["label"] == "a8"
    with pytest.raises(ValueError, match="a8"):
        task_run.resolve_arm(4, "a4-n3", "heldout6")
    assert heldout.PROTOCOL_DECISIONS == {"heldout4": "D115", "heldout5": "D115",
                                          "heldout6": "D138", "heldout7": "D138"}
    (tmp_path / "eval").mkdir()
    (tmp_path / "docs" / "decisions").mkdir(parents=True)
    (tmp_path / "eval" / "heldout_unlock.json").write_text(
        '{"unlocked": {"heldout7": "D115"}}', encoding="utf-8")
    (tmp_path / "docs" / "decisions" / "x.md").write_text("## D115: p7\n## D138: p8\n", encoding="utf-8")
    assert "D138" in heldout.unlock_problem("heldout7", root=tmp_path, committed=True)
    (tmp_path / "eval" / "heldout_unlock.json").write_text(
        '{"unlocked": {"heldout7": "D138"}}', encoding="utf-8")
    assert heldout.unlock_problem("heldout7", root=tmp_path, committed=True) is None
