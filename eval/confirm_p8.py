"""Phase 8 confirmatory runs (plan §1.4, S13 rehearsal and S14): spec and report.

    python eval/confirm_p8.py spec --seed N --root DIR --ws-root DIR --opencode EXE --out SPEC.json
        [--tasks T,...] [--histories H,...] [--attempts 3] [--set-needles heldout7]
    python eval/confirm_p8.py report ROOT [--tasks T,...] [--histories H,...] [--attempts 3]
        [--trap-reviews FILE] [--json]

**Arms** (plan §1.4): the candidate ``a8`` (arm 4) and the baseline arm 1 (``a1``, OpenCode's
own compaction, D115.1).

**Schedule** (``schedule``): ``--attempts`` attempts (3), each a run directory
``ROOT/k1..k3``. Within an attempt the tasks are in a seeded order, and each task runs both
arms back to back in a seeded order. Then the needle histories run on ``a8``, one per step
(``ROOT/needles``), in a seeded order.

**Report** (``confirm_report``), over the declared tasks:

- **primary:** each task's outcome per arm is success in at least 2 of its attempts (a
  missing or killed attempt is a failure); the paired 2x2 of those majorities, b and c, the
  exact McNemar p and the gate "candidate majority successes >= baseline's";
- **constraints:** per arm over every attempt, with a bootstrap clustered by task;
- **traps** over the suite (U4): a task repeats when any candidate attempt repeats;
  disputed attempts are settled only by ``--trap-reviews`` (``k1:task:arm``);
- **needles:** ``report.needle_gate`` over the histories (loose exact >= 95%);
- **archive gates:** ``report.arm_inputs_ok`` on every candidate attempt;
- **sensitivity:** the primary table without ho6-t9 (U13).
It prints ``unscored`` and ``missing attempts:`` lines that ``eval/run_ready.py`` reads.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (HERE, HERE / "tasks"):
    if str(p) not in sys.path:
        sys.path.append(str(p))

CANDIDATE, BASELINE = "a8", "a1"
ARMS = {CANDIDATE: ["--arm", "4", "--config", CANDIDATE], BASELINE: ["--arm", "1"]}
TASKS = tuple([f"ho6-t{i}" for i in range(1, 11)] + [f"ho7-t{i}" for i in range(1, 21)])
HISTORIES = tuple(f"ho7-h{i}" for i in range(1, 31))
SENSITIVITY_DROP = "ho6-t9"  # partly exposed to the lead (D113.12, U13)
TAG = "p8-confirm"
GATE = 0.95


def schedule(seed: int, tasks=TASKS, histories=HISTORIES, attempts: int = 3) -> list[tuple]:
    """[("task", k, task, arm) ...] then [("needle", None, history, a8) ...], in run order."""
    rnd = random.Random(seed)
    out = []
    for k in range(1, attempts + 1):
        order = list(tasks)
        rnd.shuffle(order)
        for t in order:
            arms = [CANDIDATE, BASELINE]
            rnd.shuffle(arms)
            out += [("task", k, t, a) for a in arms]
    hs = list(histories)
    rnd.shuffle(hs)
    out += [("needle", None, h, CANDIDATE) for h in hs]
    return out


def make_spec(*, seed: int, python: str, root: str, ws_root: str, opencode: str,
              upstream: str = "http://127.0.0.1:8080", n_ctx: int = 32768, tasks=TASKS,
              histories=HISTORIES, attempts: int = 3, needle_set: str = "heldout7") -> dict:
    steps = []
    for kind, k, item, arm in schedule(seed, tasks, histories, attempts):
        if kind == "task":
            steps.append({"name": f"k{k} {item} {arm}", "argv": [
                python, "eval/tasks/run.py", "--task", item, *ARMS[arm],
                "--out", f"{root}/k{k}", "--ws-root", f"{ws_root}\\k{k}", "--upstream", upstream,
                "--expect-n-ctx", str(n_ctx), "--tag", TAG]})
        else:
            steps.append({"name": f"needles {item} {arm}", "argv": [
                python, "eval/needle.py", "run", "--driver", "opencode", "--set", needle_set,
                "--config", arm, "--histories", item, "--out", f"{root}/needles",
                "--ws-root", f"{ws_root}\\needles", "--upstream", upstream,
                "--expect-n-ctx", str(n_ctx), "--tag", TAG]})
    custom = (tuple(tasks) != TASKS or tuple(histories) != HISTORIES or attempts != 3)
    return {"config": f"p8-confirm-seed{seed}" + (f"-{len(tasks)}t{len(histories)}h{attempts}k" if custom else ""),
            "seed": seed, "steps": steps,
            "server": {"props": f"{upstream}/props", "n_ctx": n_ctx, "slots": 1,
                       "build": "Strata 0.1.58", "temperature": 1.0, "top_p": 0.95, "top_k": 20},
            "env": {"OPENCODE_EXE": opencode}}


# --- report -------------------------------------------------------------------------------

def majority(outcomes: list[bool], attempts: int = 3) -> bool:
    """Success in at least 2 of ``attempts``; a missing attempt counts as a failure."""
    return sum(bool(x) for x in outcomes) >= attempts // 2 + 1


def confirm_report(results: dict[int, dict], tasks, *, attempts: int = 3,
                   trap_reviews: dict[str, bool] | None = None,
                   needles: tuple[list[dict], dict] | None = None,
                   resamples: int | None = None, seed: int | None = None) -> dict:
    """``results``: {k: {(task, arm): result.json}} per attempt directory."""
    import report

    resamples = resamples or report.BOOT_RESAMPLES
    seed = report.BOOT_SEED if seed is None else seed
    trap_reviews = trap_reviews or {}
    ks = list(range(1, attempts + 1))

    def runs(t, arm):
        return [results.get(k, {}).get((t, arm)) for k in ks]

    succ = {(t, a): majority([report.task_success(r) for r in runs(t, a)], attempts)
            for t in tasks for a in (CANDIDATE, BASELINE)}

    def table(ts):
        out = report._paired_binary(lambda t, a: succ[(t, a)], list(ts), CANDIDATE, BASELINE)
        out["candidate"] = sum(succ[(t, CANDIDATE)] for t in ts)
        out["baseline"] = sum(succ[(t, BASELINE)] for t in ts)
        out["gate"] = out["candidate"] >= out["baseline"]
        out["power_floor"] = report.power_floor(out["b"] + out["c"])
        return out

    constraints = {}
    for arm in (CANDIDATE, BASELINE):
        by_task = {}
        for t in tasks:
            held = []
            for r in runs(t, arm):
                held += list(report._constraints_of(r, None).values()) if r else []
            by_task[t] = held
        n = sum(len(v) for v in by_task.values())
        k = sum(sum(v) for v in by_task.values())
        lo, hi = report.cluster_bootstrap(by_task, resamples, seed) if n else (None, None)
        constraints[arm] = {"held": k, "total": n, "rate": k / n if n else None, "ci95": (lo, hi)}

    traps = {}
    for arm in (CANDIDATE, BASELINE):
        rep, disputed, unscored = [], [], []
        for t in tasks:
            verdicts = []
            for k, r in zip(ks, runs(t, arm)):
                v = report.trap_verdict(r, trap_reviews.get(f"k{k}:{t}:{arm}")) if r else None
                verdicts.append(v)
                if v == "disputed":
                    disputed.append(f"k{k}:{t}")
                elif v is None:
                    unscored.append(f"k{k}:{t}")
            if "repeat" in verdicts:
                rep.append(t)
        traps[arm] = {"repeats": rep, "disputed": disputed, "unscored": unscored,
                      "gate": not rep and not disputed}

    archive_failures = [f"k{k}:{t}" for t in tasks for k, r in zip(ks, runs(t, CANDIDATE))
                        if not (r and report.arm_inputs_ok(r, 4))]
    missing = [f"k{k}:{t}:{a}" for t in tasks for a in (CANDIDATE, BASELINE)
               for k, r in zip(ks, runs(t, a)) if r is None]
    out = {"tasks": list(tasks), "attempts": attempts,
           "primary": table(tasks),
           "sensitivity_without": SENSITIVITY_DROP,
           "sensitivity": table([t for t in tasks if t != SENSITIVITY_DROP]),
           "constraints": constraints, "traps": traps,
           "archive_gates": {"failures": archive_failures, "gate": not archive_failures},
           "missing": missing}
    if needles is not None:
        out["needles"] = report.needle_gate(needles[0], needles[1], gate=GATE)
    return out


def format_report(rep: dict) -> list[str]:
    p, s = rep["primary"], rep["sensitivity"]
    c = rep["constraints"]
    out = ["Phase 8 confirmatory report (plan §1.4)", "",
           f"primary (majority of {rep['attempts']}): a8 {p['candidate']}/{p['n']}, a1 {p['baseline']}/{p['n']}; "
           f"b={p['b']} c={p['c']} McNemar p={p['mcnemar_p']:.4f} (floor {p['power_floor']:.4f}); "
           f"gate {'pass' if p['gate'] else 'FAIL'}",
           f"sensitivity without {rep['sensitivity_without']}: a8 {s['candidate']}/{s['n']}, "
           f"a1 {s['baseline']}/{s['n']}; b={s['b']} c={s['c']} p={s['mcnemar_p']:.4f}"]
    for arm in (CANDIDATE, BASELINE):
        x = c[arm]
        rate = "n/a" if x["rate"] is None else f"{x['rate']:.1%}"
        lo, hi = x["ci95"]
        ci = "" if lo is None else f" [{lo:.1%}, {hi:.1%}]"
        out.append(f"constraints {arm}: {x['held']}/{x['total']} {rate}{ci}")
    for arm in (CANDIDATE, BASELINE):
        tr = rep["traps"][arm]
        out.append(f"traps {arm}: repeats {', '.join(tr['repeats']) or 'none'}; disputed "
                   f"{', '.join(tr['disputed']) or 'none'}")
    if "needles" in rep:
        n = rep["needles"]
        out.append(f"needles: {n.get('passed', n.get('hits', '?'))} loose exact, gate "
                   f"{'pass' if n.get('gate') else 'FAIL'}")
    ag = rep["archive_gates"]
    out.append(f"archive gates: {'pass' if ag['gate'] else 'FAIL ' + ', '.join(ag['failures'])}")
    unscored = [f"{a}:{x}" for a in (CANDIDATE, BASELINE) for x in rep["traps"][a]["unscored"]]
    out.append(f"unscored {', '.join(unscored) or 'none'}")  # run_ready.py reads this form
    out.append(f"missing attempts: {', '.join(rep['missing']) or 'none'}")
    return out


def load(root: Path, tasks, attempts: int = 3) -> dict[int, dict]:
    import report

    results = {}
    for k in range(1, attempts + 1):
        run = root / f"k{k}"
        if (run / "attempts.json").exists():
            results[k], _ = report.load_phase7_results(run, [CANDIDATE, BASELINE],
                                                       scan=frozenset(tasks))
        else:
            results[k] = {}
    return results


def load_needles(root: Path, set_name: str, histories) -> tuple[list[dict], dict] | None:
    import report

    run = root / "needles"
    if not (run / "attempts.json").exists():
        return None
    rows, _meta = report.load_attempts(run, CANDIDATE)[:2]
    expected = {h: q for h, q in report.expected_needles(set_name).items() if h in set(histories)}
    rows, _missing = report.fill_missing(rows, expected)
    return rows, expected


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("spec", "report"):
        q = sub.add_parser(name)
        q.add_argument("--tasks")
        q.add_argument("--histories")
        q.add_argument("--attempts", type=int, default=3)
        q.add_argument("--set-needles", default="heldout7")
        if name == "spec":
            q.add_argument("--seed", type=int, required=True)
            q.add_argument("--root", required=True)
            q.add_argument("--ws-root", required=True)
            q.add_argument("--python", default=sys.executable)
            q.add_argument("--opencode", required=True)
            q.add_argument("--out", type=Path, required=True)
        else:
            q.add_argument("root", type=Path)
            q.add_argument("--trap-reviews", type=Path)
            q.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    tasks = tuple(a.tasks.split(",")) if a.tasks else TASKS
    hist = tuple(a.histories.split(",")) if a.histories else HISTORIES
    if a.cmd == "spec":
        spec = make_spec(seed=a.seed, python=a.python, root=a.root, ws_root=a.ws_root,
                         opencode=a.opencode, tasks=tasks, histories=hist, attempts=a.attempts,
                         needle_set=a.set_needles)
        a.out.write_text(json.dumps(spec, indent=1), encoding="utf-8")
        for i, st in enumerate(spec["steps"], 1):
            print(f"{i:3}: {st['name']}")
        print(f"{len(spec['steps'])} steps -> {a.out}")
        return 0
    import report

    reviews = ({k: bool(v["repeat"]) for k, v in json.loads(a.trap_reviews.read_text(encoding="utf-8")).items()}
               if a.trap_reviews else None)
    results = load(a.root, tasks, a.attempts)
    needles = load_needles(a.root, a.set_needles, hist) if hist else None
    rep = confirm_report(results, tasks, attempts=a.attempts, trap_reviews=reviews, needles=needles)
    print(json.dumps(rep, indent=1, default=str) if a.json else "\n".join(format_report(rep)))
    assert report  # imported for its loaders
    return 0


if __name__ == "__main__":
    sys.exit(main())
