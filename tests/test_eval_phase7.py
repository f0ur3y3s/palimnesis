"""Phase 7 S5: the candidate report (``report.phase7_report``) and the run schedule
(``eval/phase7_schedule.py``). Pure functions over literal fixtures; nothing here runs
OpenCode, a proxy or a model, and no held-out data is read (task ids are synthetic)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval")]

import phase7_schedule  # noqa: E402
import report  # noqa: E402

sys.path.remove(str(ROOT / "eval"))

CAND, BASE = "a4-d77", "a1"


def _ok(success: bool, constraints: dict | None = None, **extra) -> dict:
    return {"check": {"success": success, "constraints": constraints or {}}, **extra}


# ---------------------------------------------------------------- McNemar and Newcombe

@pytest.mark.parametrize("b, c, p", [(6, 0, 0.03125), (5, 0, 0.0625), (8, 1, 0.0390625),
                                     (0, 6, 0.03125), (1, 8, 0.0390625)])
def test_mcnemar_literal(b, c, p):
    """Plan §1.1 and v1_plan Phase 7: two-sided exact McNemar on the discordant pairs."""
    assert report.mcnemar_exact(b, c) == p


def test_power_floor_is_two_to_one_minus_d():
    assert report.power_floor(6) == 0.03125
    assert report.power_floor(5) == 0.0625
    assert report.power_floor(0) == 1.0


@pytest.mark.parametrize("cells, lo, hi", [
    # Armitage and Berry (1994, p. 138): 50 sputum specimens on two media; both 20, first
    # only 12, second only 2, neither 16. Newcombe (1998) method 10, as printed by
    # StatsDirect's paired-proportions help ("Newcombe's refinement of Wilson's score",
    # citing Newcombe 1998a): 0.056156 to 0.329207. Here ad - bc > n/2, so phi is corrected.
    ((20, 12, 2, 16), 0.056156, 0.329207),
    # PSI AIMS CAMIS "Confidence intervals for paired proportions in SAS": r=20, s=15,
    # t=6, u=5, N=46; 0 <= ad - bc <= N/2 so phi = 0; Newcombe 0.002602 to 0.369943.
    ((20, 15, 6, 5), 0.002602, 0.369943),
])
def test_newcombe_paired_published_examples(cells, lo, hi):
    # Both published values use z = 1.959964 (the 97.5% normal quantile), not 1.96.
    a, b, c, d = cells
    diff, got_lo, got_hi = report.newcombe_paired(a, b, c, d)
    assert diff == pytest.approx((b - c) / (a + b + c + d))
    assert got_lo == pytest.approx(lo, abs=5e-7)
    assert got_hi == pytest.approx(hi, abs=5e-7)


# ---------------------------------------------------------------- primary comparison

def test_missing_or_aborted_counts_as_failure():
    """Plan: a missing or aborted designated attempt is a failure for that arm."""
    tasks = ["x-t1", "x-t2", "x-t3", "x-t4"]
    results = {
        # x-t1: candidate missing entirely, baseline succeeds -> c
        ("x-t1", BASE): _ok(True),
        # x-t2: candidate aborted (even with a passing check), baseline succeeds -> c
        ("x-t2", CAND): {**_ok(True), "aborted": "turn killed"},
        ("x-t2", BASE): _ok(True),
        # x-t3: both succeed -> a
        ("x-t3", CAND): _ok(True), ("x-t3", BASE): _ok(True),
        # x-t4: candidate succeeds, baseline missing -> b
        ("x-t4", CAND): _ok(True),
    }
    t = report.paired_table(results, tasks, CAND, BASE)
    assert (t["a"], t["b"], t["c"], t["d"]) == (1, 1, 2, 0)
    assert t["missing"] == ["x-t1:a4-d77", "x-t4:a1"]
    assert t["aborted"] == ["x-t2:a4-d77"]
    r = report.phase7_report(results, tasks, candidate=CAND, baseline=BASE)
    p = r["primary"]
    assert (p["candidate_successes"], p["baseline_successes"]) == (2, 3)
    assert (p["b"], p["c"], p["d_discordant"]) == (1, 2, 3)
    assert p["mcnemar_p"] == 1.0
    assert p["power_floor"] == 0.25
    assert p["gate"] is False
    assert p["diff"] == pytest.approx(-0.25)


def test_primary_gate_is_the_observed_rate_never_equivalence():
    tasks = [f"x-t{i}" for i in range(1, 7)]
    results = {(t, arm): _ok(True) for t in tasks for arm in (CAND, BASE)}
    r = report.phase7_report(results, tasks, candidate=CAND, baseline=BASE)
    assert r["primary"]["gate"] is True and r["primary"]["mcnemar_p"] == 1.0
    text = "\n".join(report.format_phase7(r)).lower()
    assert "equivalen" not in text.replace("does not establish equivalence", "")
    assert "noninferior" not in text.replace("or noninferiority", "")


def test_per_host_and_pooled_tables():
    tasks = ["x-t1", "x-t2", "x-t3"]
    results = {("x-t1", CAND): _ok(True), ("x-t1", BASE): _ok(False),
               ("x-t2", CAND): _ok(True), ("x-t2", BASE): _ok(True),
               ("x-t3", CAND): _ok(False), ("x-t3", BASE): _ok(True)}
    r = report.phase7_report(results, tasks, candidate=CAND, baseline=BASE,
                             hosts={"x-t1": "pythia", "x-t2": "zeus", "x-t3": "zeus"})
    assert (r["primary"]["b"], r["primary"]["c"]) == (1, 1)
    assert (r["by_host"]["pythia"]["b"], r["by_host"]["pythia"]["c"]) == (1, 0)
    assert (r["by_host"]["zeus"]["a"], r["by_host"]["zeus"]["c"]) == (1, 1)


def test_phase7_cli_pools_disjoint_task_runs(tmp_path, monkeypatch, capsys):
    for name, task in (("pythia", "x-t1"), ("zeus", "x-t2")):
        root = tmp_path / name
        attempts = []
        for number, label in enumerate((CAND, BASE), start=1):
            records = root / f"attempt-{number}"
            result = records / f"{task}-{label}" / "result.json"
            result.parent.mkdir(parents=True)
            result.write_text(json.dumps(_ok(True)), encoding="utf-8")
            attempts.append({"attempt": number, "kind": "task", "config": label,
                             "ids": [task], "records": str(records)})
        (root / "attempts.json").write_text(json.dumps({"attempts": attempts}), encoding="utf-8")

    command = ["report.py", "--phase7", str(tmp_path / "pythia"), "--tasks", "x-t1,x-t2", "--json"]
    monkeypatch.setattr(sys, "argv", [*command, "--pool", str(tmp_path / "zeus")])
    with pytest.raises(SystemExit) as exc:
        report.main()
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out)["primary"]["a"] == 2

    monkeypatch.setattr(sys, "argv", [*command, "--pool", str(tmp_path / "pythia")])
    with pytest.raises(SystemExit) as exc:
        report.main()
    assert exc.value.code == 2
    assert "multiple task run directories" in capsys.readouterr().err


@pytest.mark.parametrize("extra", [
    ["--tasks", "ho4-t1"],
    ["--tasks", "x-t1", "--needle-run", "unused", "--needle-dirs", "eval/needles/heldout5"],
])
def test_phase7_cli_refuses_locked_sets_before_loading_data(extra, monkeypatch, capsys):
    monkeypatch.setattr(report.heldout, "unlock_problem",
                        lambda name: f"locked: {name}" if name in report.heldout.UNSEEN_SETS else None)
    monkeypatch.setattr(report, "load_phase7_results", lambda *args: pytest.fail("loaded task results"))
    monkeypatch.setattr(sys, "argv", ["report.py", "--phase7", "unused", *extra])
    with pytest.raises(SystemExit) as exc:
        report.main()
    assert exc.value.code == 2
    assert "locked: heldout" in capsys.readouterr().err


# ---------------------------------------------------------------- constraints

def test_constraint_task_cluster_bootstrap_literal():
    """Resample tasks, not constraints: 10,000 draws of 4 tasks with ``random.Random(7)``
    over a tiny literal table; percentiles pinned once from this implementation."""
    by_task = {"t1": [True, True, True], "t2": [True, False, True],
               "t3": [True, True], "t4": [False, True, True]}
    lo, hi = report.cluster_bootstrap(by_task, resamples=10_000, seed=7)
    assert (round(lo, 6), round(hi, 6)) == (0.666667, 1.0)
    tasks = list(by_task)
    results = {(t, CAND): _ok(True, {f"C{i + 1}": v for i, v in enumerate(vs)})
               for t, vs in by_task.items()}
    r = report.phase7_report(results, tasks, candidate=CAND, baseline=BASE, seed=7)
    c = r["constraints"][CAND]
    assert (c["held"], c["total"]) == (9, 11)
    assert c["bootstrap"] == (lo, hi)
    assert c["gate"] is False  # 9/11 < 0.90
    assert c["per_task"]["t2"] == (2, 3)
    assert c["per_constraint"]["C2"] == (3, 4)


def test_constraints_of_a_missing_run_count_as_lost_when_declared():
    results = {("x-t1", CAND): _ok(True, {"C1": True, "C2": True})}
    r = report.phase7_report(results, ["x-t1", "x-t2"], candidate=CAND, baseline=BASE,
                             constraints_declared={"x-t2": ["C1", "C2", "C3"]})
    c = r["constraints"][CAND]
    assert (c["held"], c["total"]) == (2, 5)
    assert c["per_task"]["x-t2"] == (0, 3)


# ---------------------------------------------------------------- traps

def _hits(*kinds):
    return {"state_eval": [{"trap_hits": [{"kind": k} for k in kinds]}]}


def test_trap_gate_counts_code_repeats_and_lists_doubtful():
    suite = ["x-t1", "x-t2", "x-t3"]
    results = {("x-t1", CAND): _ok(True, **_hits("doubtful", "doubtful")),
               ("x-t2", CAND): _ok(True, **_hits()),
               ("x-t3", CAND): _ok(True, **_hits()),
               ("x-t1", BASE): _ok(True, **_hits("code")),
               ("x-t2", BASE): _ok(True, **_hits("code", "doubtful"))}
    r = report.phase7_report(results, suite, candidate=CAND, baseline=BASE, trap_suite=suite)
    t = r["traps"]
    assert (t[CAND]["repeats"], t[CAND]["n"], t[CAND]["doubtful"]) == (0, 3, 2)
    assert t[CAND]["gate"] is True
    assert (t[BASE]["repeats"], t[BASE]["doubtful"], t[BASE]["unscored"]) == (2, 1, ["x-t3"])


def _trap(passed, *kinds) -> dict:
    """A run whose check carries ``trap_tests.passed`` and the given D109 hit kinds."""
    return {"check": {"success": True, "constraints": {},
                      "trap_tests": {"passed": passed, "failed": [] if passed else ["test_t_x"],
                                     "total": 1}},
            **_hits(*kinds)}


def test_trap_repeat_needs_code_hit_and_failed_trap_test():
    """D112.9: a code hit with a failed test_t is a repeat; a code hit on a passing
    test_t, or a failed test_t with no code hit, is disputed until a review settles it."""
    suite = ["x-t1", "x-t2", "x-t3", "x-t4"]
    results = {("x-t1", CAND): _trap(False, "code"),
               ("x-t2", CAND): _trap(True, "code"),
               ("x-t3", CAND): _trap(False, "doubtful"),
               ("x-t4", CAND): _trap(True, "doubtful")}
    t = report.phase7_report(results, suite, candidate=CAND, baseline=BASE,
                             trap_suite=suite)["traps"][CAND]
    assert (t["repeats"], t["disputed"]) == (1, ["x-t2", "x-t3"])
    assert t["gate"] is False
    reviews = {f"x-t2:{CAND}": False, f"x-t3:{CAND}": True}
    t = report.phase7_report(results, suite, candidate=CAND, baseline=BASE, trap_suite=suite,
                             trap_reviews=reviews)["traps"][CAND]
    assert (t["repeats"], t["disputed"], t["reviewed"]) == (2, [], ["x-t2", "x-t3"])


def test_trap_gate_passes_only_with_no_repeat_and_nothing_disputed():
    suite = ["x-t1", "x-t2"]
    clean = {("x-t1", CAND): _trap(True), ("x-t2", CAND): _trap(True, "doubtful")}
    r = report.phase7_report(clean, suite, candidate=CAND, baseline=BASE, trap_suite=suite)
    assert r["traps"][CAND]["gate"] is True
    disputed = {**clean, ("x-t2", CAND): _trap(True, "code")}
    r = report.phase7_report(disputed, suite, candidate=CAND, baseline=BASE, trap_suite=suite)
    assert (r["traps"][CAND]["repeats"], r["traps"][CAND]["gate"]) == (0, False)
    text = "\n".join(report.format_phase7(r))
    assert "disputed" in text and "x-t2" in text
    r = report.phase7_report(disputed, suite, candidate=CAND, baseline=BASE, trap_suite=suite,
                             trap_reviews={f"x-t2:{CAND}": False})
    assert r["traps"][CAND]["gate"] is True


def test_trap_reviews_cli_file(tmp_path):
    p = tmp_path / "reviews.json"
    p.write_text('{"x-t2:a4-d77": {"repeat": false, "note": "slice, correct code"}}',
                 encoding="utf-8")
    assert report.load_trap_reviews(p) == {"x-t2:a4-d77": False}


def test_trap_gate_fails_when_a_candidate_run_is_unscored():
    r = report.phase7_report({("x-t1", CAND): _ok(True)}, ["x-t1"], candidate=CAND,
                             baseline=BASE, trap_suite=["x-t1"])
    assert r["traps"][CAND]["unscored"] == ["x-t1"] and r["traps"][CAND]["gate"] is False


# ---------------------------------------------------------------- needles

def _needles(right: int):
    expected = {f"h{i}": [{"id": f"h{i}q{j}", "category": "identifier", "answer": "x"}
                          for j in range(10)] for i in range(30)}
    rows, k = [], 0
    for h, steps in expected.items():
        for st in steps:
            ok = k < right
            rows.append({"history": h, "step": st["id"], "kind": "question", "exact_loose": ok,
                         "exact": ok})
            k += 1
    return rows, expected


@pytest.mark.parametrize("right, passes", [(285, True), (284, False), (300, True)])
def test_needle_gate_095_over_300(right, passes):
    assert report.PHASE7_NEEDLE_GATE == 0.95
    assert report.NEEDLE_GATE == 0.85  # earlier phases keep theirs
    rows, expected = _needles(right)
    g = report.needle_gate(rows, expected, gate=report.PHASE7_NEEDLE_GATE)
    assert (g["n"], g["loose"], g["pass"]) == (300, right, passes)
    assert g["wilson"] == report.wilson(right, 300)
    r = report.phase7_report({}, [], candidate=CAND, baseline=BASE, needles=(rows, expected))
    assert r["needles"]["pass"] is passes and r["needles"]["gate"] == 0.95


def test_needle_gate_counts_a_missing_needle_as_a_miss():
    rows, expected = _needles(300)
    g = report.needle_gate(rows[:-15], expected, gate=0.95)
    assert (g["loose"], g["n"], g["pass"]) == (285, 300, True)
    g = report.needle_gate(rows[:-16], expected, gate=0.95)
    assert (g["loose"], g["pass"]) == (284, False)


def test_phase7_cli_pools_needle_runs(tmp_path, monkeypatch, capsys):
    rows, expected = _needles(285)
    paths = [tmp_path / "needles1", tmp_path / "needles2"]
    by_run = dict(zip(paths, (rows[:120], rows[120:]), strict=True))
    monkeypatch.setattr(report, "expected_needles_in", lambda folder: expected)
    monkeypatch.setattr(report, "load", lambda run, *args: (by_run[run], {}, {}))
    monkeypatch.setattr(sys, "argv", ["report.py", "--phase7", str(tmp_path / "tasks"),
                                     "--tasks", "x-t1", "--json", "--needle-dirs", str(tmp_path),
                                     "--needle-run", str(paths[0]), "--needle-run", str(paths[1])])
    with pytest.raises(SystemExit) as exc:
        report.main()
    assert exc.value.code == 0
    needles = json.loads(capsys.readouterr().out)["needles"]
    assert (needles["loose"], needles["n"], needles["pass"]) == (285, 300, True)


# ---------------------------------------------------------------- exploratory

def test_secondaries_are_exploratory_and_split_by_set():
    tasks = ["s4-t1", "s4-t2", "s5-t1", "s5-t2"]
    results = {("s4-t1", CAND): _ok(True, {"C1": True}), ("s4-t1", BASE): _ok(True, {"C1": False}),
               ("s4-t2", CAND): _ok(True, {"C1": True}), ("s4-t2", BASE): _ok(False, {"C1": True}),
               ("s5-t1", CAND): _ok(False, {"C1": True}), ("s5-t1", BASE): _ok(False, {"C1": True}),
               ("s5-t2", CAND): _ok(True, {"C1": True}), ("s5-t2", BASE): _ok(True, {"C1": True})}
    r = report.phase7_report(results, tasks, candidate=CAND, baseline=BASE,
                             sets={t: t.split("-")[0] for t in tasks})
    ex = r["exploratory"]
    assert ex["label"] == "exploratory"
    assert (ex["constraint_kept"]["b"], ex["constraint_kept"]["c"]) == (1, 0)
    assert (ex["by_set"]["s4"]["b"], ex["by_set"]["s5"]["b"]) == (1, 0)
    assert all("exploratory" in line for line in report.format_phase7(r)
               if "constraint lost" in line or "by set" in line)


# ---------------------------------------------------------------- schedule

TASKS = [f"sa-t{i}" for i in range(1, 6)] + [f"sb-t{i}" for i in range(1, 21)]


def test_schedule_seeded_reproducible_and_balanced():
    one = phase7_schedule.make_schedule(TASKS, seed=115)
    assert one == phase7_schedule.make_schedule(TASKS, seed=115)
    assert one != phase7_schedule.make_schedule(TASKS, seed=116)
    hosts = one["hosts"]
    assert set(hosts) == {"pythia", "zeus"}
    counts = {h: len(v) for h, v in hosts.items()}
    assert abs(counts["pythia"] - counts["zeus"]) <= 1
    for s in ("sa", "sb"):
        per = [sum(1 for x in v if x["set"] == s) for v in hosts.values()]
        assert abs(per[0] - per[1]) <= 1
    seen = [x["task"] for v in hosts.values() for x in v]
    assert sorted(seen) == sorted(TASKS)
    for v in hosts.values():
        for x in v:
            assert sorted(x["arms"]) == sorted(["a1", "a4-d77"])
            assert one["task_host"][x["task"]] in hosts
    rep = one["repeats"]
    assert len(rep) == 5 and len({x["task"] for x in rep}) == 5
    assert all(x["host"] == one["task_host"][x["task"]] for x in rep)


def test_schedule_orders_vary_with_the_seed():
    plans = [phase7_schedule.make_schedule(TASKS, seed=s) for s in range(20)]
    firsts = {tuple(p["hosts"]["pythia"][0]["arms"]) for p in plans}
    assert firsts == {("a4-d77", "a1"), ("a1", "a4-d77")}
    assert len({tuple(x["task"] for x in p["hosts"]["pythia"]) for p in plans}) == 20


def test_schedule_cli_writes_json(tmp_path):
    out = tmp_path / "plan.json"
    assert phase7_schedule.main(["--seed", "3", "--tasks", ",".join(TASKS), "--out", str(out)]) == 0
    import json
    assert json.loads(out.read_text(encoding="utf-8")) == phase7_schedule.make_schedule(TASKS, seed=3)


# ---------------------------------------------------------------- S10 rehearsal gaps (D115)

def test_phase7_cli_scans_traps_of_suite_runs(tmp_path, monkeypatch, capsys):
    """run.py does not carry the state_eval trap scan; the report runs it (archive, or
    bodies for arm 1) on each designated suite attempt that has none, and keeps one it has."""
    root = tmp_path / "pythia"
    attempts = []
    for number, (task, label) in enumerate((("x-t1", CAND), ("x-t1", BASE),
                                            ("x-t2", CAND), ("x-t2", BASE)), start=1):
        records = root / f"attempt-{number}"
        r = _trap(passed=(task, label) != ("x-t1", CAND))  # carries an empty state_eval
        if (task, label) != ("x-t2", BASE):
            del r["state_eval"]  # as run.py writes it: no trap scan
        result = records / f"{task}-{label}" / "result.json"
        result.parent.mkdir(parents=True)
        result.write_text(json.dumps(r), encoding="utf-8")
        attempts.append({"attempt": number, "kind": "task", "config": label,
                         "ids": [task], "records": str(records)})
    (root / "attempts.json").write_text(json.dumps({"attempts": attempts}), encoding="utf-8")
    scanned = []

    def fake_scan(attempt, tid, result):
        scanned.append((Path(attempt).name, tid))
        return [{"trap_hits": [{"kind": "code"}]}] if attempt.name == f"x-t1-{CAND}" else []

    monkeypatch.setattr(report, "trap_scan", fake_scan)
    monkeypatch.setattr(sys, "argv", ["report.py", "--phase7", str(root), "--tasks", "x-t1,x-t2",
                                      "--trap-suite", "x-t1,x-t2", "--json"])
    with pytest.raises(SystemExit) as exc:
        report.main()
    assert exc.value.code == 0
    t = json.loads(capsys.readouterr().out)["traps"]
    assert sorted(scanned) == [(f"x-t1-{BASE}", "x-t1"), (f"x-t1-{CAND}", "x-t1"),
                               (f"x-t2-{CAND}", "x-t2")]
    assert (t[CAND]["repeats"], t[CAND]["unscored"]) == (1, [])
    assert (t[BASE]["repeats"], t[BASE]["unscored"]) == (0, [])


def _gates(ok=True, **over) -> dict:
    """The D44.6 per-archive inputs of one candidate run, all passing unless overridden."""
    r = {"explain_gate": {"ok": ok}, "verify": {"exit": 0}, "over_budget": {"ok": True},
         "excerpt_scan": {"client": {"leaks": 0}, "transcripts": {"leaks": 0}}}
    return {**r, **over}


def test_phase7_per_archive_gates_on_every_candidate_run():
    """D115.5: 0 over budget, 0 leaks, --explain clean and transcripts verify, per archive."""
    tasks = ["x-t1", "x-t2", "x-t3"]
    results = {("x-t1", CAND): _ok(True, **_gates()),
               ("x-t2", CAND): _ok(True, **_gates(excerpt_scan={"client": {"leaks": 1},
                                                                "transcripts": {"leaks": 0}})),
               ("x-t1", BASE): _ok(True), ("x-t2", BASE): _ok(True)}
    g = report.phase7_report(results, tasks, candidate=CAND, baseline=BASE)["archive_gates"]
    assert (g["passed"], g["n"], g["failures"], g["gate"]) == (1, 3, ["x-t2", "x-t3"], False)
    ok = {**results, ("x-t2", CAND): _ok(True, **_gates()), ("x-t3", CAND): _ok(False, **_gates())}
    g = report.phase7_report(ok, tasks, candidate=CAND, baseline=BASE)["archive_gates"]
    assert (g["passed"], g["failures"], g["gate"]) == (3, [], True)
    text = "\n".join(report.format_phase7(report.phase7_report(results, tasks, candidate=CAND,
                                                               baseline=BASE)))
    assert "Per-archive gates" in text and "x-t2" in text


def _epoch(before, after=None, flagged=False) -> dict:
    return {"host_epoch": {"before": {"epoch": before}, "after": {"epoch": after or before},
                           "flagged": flagged}}


def test_phase7_flags_pairs_split_across_host_epochs_and_reports_without_them():
    """D115.6: a pair whose arms ran under different host epochs (or a flagged epoch) is
    flagged, never rerun; the primary table is also reported without split pairs."""
    tasks = ["x-t1", "x-t2", "x-t3", "x-t4"]
    results = {("x-t1", CAND): _ok(True, **_epoch("e1")), ("x-t1", BASE): _ok(False, **_epoch("e1")),
               ("x-t2", CAND): _ok(True, **_epoch("e1")), ("x-t2", BASE): _ok(False, **_epoch("e1", "e2")),
               ("x-t3", CAND): _ok(False, **_epoch("e2", flagged=True)), ("x-t3", BASE): _ok(True, **_epoch("e2")),
               ("x-t4", CAND): _ok(True), ("x-t4", BASE): _ok(True, **_epoch("e3"))}
    r = report.phase7_report(results, tasks, candidate=CAND, baseline=BASE)
    e = r["epochs"]
    assert (e["split"], e["unknown"]) == (["x-t2", "x-t3"], ["x-t4"])
    s = e["without_split"]
    assert (s["n"], s["b"], s["c"]) == (2, 1, 0)
    assert r["primary"]["n"] == 4
    text = "\n".join(report.format_phase7(r))
    assert "split across host epochs" in text and "x-t2" in text
