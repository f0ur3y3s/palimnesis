"""Phase 8 S3 pilot: choose the notes candidate (plan S3, D121.3, D125).

    python eval/pilot_s3.py spec --seed N --root DIR --ws-root DIR --opencode EXE --out SPEC.json [--tasks T,...]
    python eval/pilot_s3.py report ROOT [--tasks T,...] [--trap-reviews FILE]
        [--retention-reviews FILE] [--json]

Run the report on Zeus, in the clone that ran the pilot: ``attempts.json`` stores absolute
records paths. The rehearsal and the pilot need separate roots (an attempt of the same
task and arm in one round directory needs ``--reason``, and the step would stop).

**Arms.** ``a4-d77`` (the Phase 7 candidate, notes n2) is the control. ``a4-n3`` is
``a4-d77`` with notes format n3 (D122, D123); ``a4-n3p`` adds D65's pinned instructions.

**Schedule** (``make_spec``). Round 1 runs every task once per arm: dev-t6..t10 and the
three retired ho5 tasks whose trap ``a4-d77`` repeated in S11 (ho5-t2, t4, t13). Round 2
runs the three ho5 tasks once more per arm, so each arm has 2 attempts on each. Within a
round the tasks are in a seeded order and each task's arms run back to back in a seeded
order. A round is one ``eval/tasks/run.py`` run directory (``ROOT/r1``, ``ROOT/r2``), so
every round has one designated attempt per task and arm. The spec feeds
``eval/headless.py plan --spec``.

**Report** (``pilot_report``), per arm over every attempt:

- trap verdicts (``report.trap_verdict``: repeat, clean, disputed; a disputed attempt is
  settled only by ``--trap-reviews``, keyed ``round:task:arm``);
- task success and early constraints held;
- whether the notes in force at the trap turn hold the task's warning
  (``notes_audit.audit_run``), and the mean length of the committed notes versions in
  characters (exact; tokens would be an estimate).

**Selection** (``select``; D125 records the outcome):

- **V-n1, retention:** in every ho5-t4 and ho5-t13 attempt, the notes in force at the trap
  turn hold the warning. The detector matches the warning's backticked code exactly, so a
  paraphrase reads as lost: every state other than ``kept`` is read by hand and recorded
  in ``--retention-reviews`` (keyed ``round:task:arm``, ``{"kept": bool}``) before V-n1
  is settled. ho5-t2's detector is unreliable (R68), so its attempts are read by hand and
  reported, not counted.
- **V-n2, no repeat:** 0 trap repeats over all of the arm's attempts, none disputed or
  unscored. S14's trap gate is 0 repeats over three attempts per task, so a pilot repeat
  predicts a gate failure.
- **No regression:** successes, and early constraints held, each at least the control's
  in this pilot minus 1.
- An n3 arm meeting all three is eligible. ``a4-n3`` wins when it is eligible; ``a4-n3p``
  wins only when it alone is (its pins cost up to about 4K tokens of every view, and the
  two arms' notes mechanism is the same, so notes length cannot separate them). With none
  eligible there is no candidate: the default does not flip and the user decides.

The report prints ``unscored ...`` and ``missing attempts: ...`` lines that
``eval/run_ready.py`` reads for gate item 5.
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

CONTROL = "a4-d77"
CANDIDATES = ("a4-n3", "a4-n3p")
ARMS = (CONTROL, *CANDIDATES)
DEV = tuple(f"dev-t{i}" for i in range(6, 11))
HO5 = ("ho5-t2", "ho5-t4", "ho5-t13")
RETENTION = ("ho5-t4", "ho5-t13")  # usable warning detectors (R68)
HAND = ("ho5-t2",)
ROUNDS = {"r1": DEV + HO5, "r2": HO5}
TAG = "s3-pilot"


def schedule(seed: int) -> list[tuple[str, str, str]]:
    """[(round, task, arm)] in run order."""
    rnd = random.Random(seed)
    out = []
    for rd, tasks in ROUNDS.items():
        order = list(tasks)
        rnd.shuffle(order)
        for t in order:
            arms = list(ARMS)
            rnd.shuffle(arms)
            out += [(rd, t, a) for a in arms]
    return out


def make_spec(*, seed: int, python: str, root: str, ws_root: str, opencode: str,
              upstream: str = "http://127.0.0.1:8080", n_ctx: int = 32768,
              only: set[str] | None = None) -> dict:
    """The headless spec; ``only`` keeps the listed tasks' steps, in schedule order."""
    steps = []
    for rd, t, arm in schedule(seed):
        if only is not None and t not in only:
            continue
        steps.append({"name": f"{rd} {t} {arm}", "argv": [
            python, "eval/tasks/run.py", "--task", t, "--arm", "4", "--config", arm,
            "--out", f"{root}/{rd}", "--ws-root", f"{ws_root}\\{rd}",
            "--upstream", upstream, "--expect-n-ctx", str(n_ctx), "--tag", TAG]})
    name = f"s3-pilot-seed{seed}" + (f"-{'+'.join(sorted(only))}" if only else "")
    return {"config": name, "seed": seed, "steps": steps,
            "server": {"props": f"{upstream}/props", "n_ctx": n_ctx, "slots": 1,
                       "build": "Strata 0.1.58", "temperature": 1.0, "top_p": 0.95,
                       "top_k": 20},
            "env": {"OPENCODE_EXE": opencode}}


# --- report ---------------------------------------------------------------------------

def _load_round(run: Path, tasks: tuple[str, ...]) -> dict:
    """{(task, arm): (result, attempt_dir | None)} for the designated attempts."""
    import attempts as att
    import report

    manifest = att.load(run) if (run / "attempts.json").exists() else []
    out = {}
    for arm in ARMS:
        chosen, _ = att.designate(manifest, "task", arm)
        for t in tasks:
            a = chosen.get(t)
            if a is None:
                continue
            d = Path(a["records"]) / f"{t}-{arm}"
            f = d / "result.json"
            r = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"aborted": "no result.json"}
            if report._usable(r) and "state_eval" not in r:
                r["state_eval"] = report.trap_scan(d, t, r)
            out[(t, arm)] = (r, d)
    return out


def _audit(d: Path | None, task_id: str) -> dict | None:
    import notes_audit
    import state_eval as se

    if d is None or not (d / "archive.db").exists():
        return None
    a = notes_audit.audit_run(d / "archive.db", se.task_module(task_id))
    lens = [len(v["text"]) for v in notes_audit.read_versions(d / "archive.db")]
    return {"at_need": (a["at_need"] or {}).get("actual"), "versions": a["versions"],
            "sections": a["sections"], "notes_chars_mean": sum(lens) / len(lens) if lens else 0.0}


def collect(root: Path, reviews: dict[str, bool] | None = None,
            only: set[str] | None = None,
            retention_reviews: dict[str, bool] | None = None) -> list[dict]:
    """One row per planned (round, task, arm), loaded from ``root``. ``only`` keeps the
    listed tasks (the rehearsal runs dev-t6 alone); rounds left empty are skipped."""
    import report

    reviews = reviews or {}
    retention_reviews = retention_reviews or {}
    rows = []
    for rd, planned in ROUNDS.items():
        tasks = tuple(t for t in planned if only is None or t in only)
        if not tasks:
            continue
        got = _load_round(root / rd, tasks)
        for t in tasks:
            for arm in ARMS:
                r, d = got.get((t, arm), (None, None))
                key = f"{rd}:{t}:{arm}"
                held = report._constraints_of(r, None)
                rows.append({
                    "round": rd, "task": t, "arm": arm, "present": r is not None,
                    "usable": report._usable(r), "aborted": (r or {}).get("aborted"),
                    "verdict": report.trap_verdict(r, reviews.get(key)) if r else None,
                    "reviewed": key in reviews,
                    "success": report.task_success(r),
                    "constraints": (sum(held.values()), len(held)),
                    "notes": _audit(d, t) if report._usable(r) else None,
                    "retention_review": retention_reviews.get(key)})
    return rows


def _kept(r: dict) -> bool | None:
    """Retention at the trap turn: True when detected as kept, else the hand review's
    verdict, or None while a non-kept state awaits its hand read."""
    if r["notes"] and r["notes"]["at_need"] == "kept":
        return True
    return r.get("retention_review")


def pilot_report(rows: list[dict]) -> dict:
    arms = {}
    for arm in ARMS:
        mine = [r for r in rows if r["arm"] == arm]
        ret = [r for r in mine if r["task"] in RETENTION]
        chars = [r["notes"]["notes_chars_mean"] for r in mine if r["notes"]]
        arms[arm] = {
            "attempts": len(mine),
            "repeats": sum(r["verdict"] == "repeat" for r in mine),
            "disputed": [f"{r['round']}:{r['task']}" for r in mine if r["verdict"] == "disputed"],
            "unscored": [f"{r['round']}:{r['task']}" for r in mine if r["verdict"] is None],
            "successes": sum(r["success"] for r in mine),
            "constraints": (sum(r["constraints"][0] for r in mine),
                            sum(r["constraints"][1] for r in mine)),
            "retention": (sum(_kept(r) is True for r in ret), len(ret)),
            "retention_pending": [f"{r['round']}:{r['task']}" for r in ret if _kept(r) is None],
            "notes_chars_mean": sum(chars) / len(chars) if chars else None,
            "hand": [f"{r['round']}:{r['task']}" for r in mine if r["task"] in HAND],
        }
    missing = [f"{r['round']}:{r['task']}:{r['arm']}" for r in rows if not r["present"]]
    return {"arms": arms, "missing": missing, "rows": rows, "selection": select(arms)}


def select(arms: dict) -> dict:
    ctl = arms[CONTROL]
    checks, eligible = {}, []
    for arm in CANDIDATES:
        a = arms[arm]
        v1 = (a["retention"][1] > 0 and a["retention"][0] == a["retention"][1]
              and not a.get("retention_pending"))
        v2 = a["repeats"] == 0 and not a["disputed"] and not a["unscored"]
        nr = (a["successes"] >= ctl["successes"] - 1
              and a["constraints"][0] >= ctl["constraints"][0] - 1)
        checks[arm] = {"V-n1": v1, "V-n2": v2, "no_regression": nr}
        if v1 and v2 and nr:
            eligible.append(arm)
    eligible.sort(key=CANDIDATES.index)  # a4-n3 first: no pins (D125.5)
    return {"checks": checks, "eligible": eligible,
            "candidate": eligible[0] if eligible else None}


def format_report(rep: dict) -> list[str]:
    out = ["S3 pilot (plan S3, D125)", ""]
    out.append(f"{'arm':8} {'repeats':>8} {'success':>8} {'constr':>8} {'retain':>7} {'notes ch':>9}")
    for arm, a in rep["arms"].items():
        nc = "n/a" if a["notes_chars_mean"] is None else f"{a['notes_chars_mean']:.0f}"
        out.append(f"{arm:8} {a['repeats']:>4}/{a['attempts']:<3} {a['successes']:>4}/{a['attempts']:<3} "
                   f"{a['constraints'][0]:>4}/{a['constraints'][1]:<3} "
                   f"{a['retention'][0]:>3}/{a['retention'][1]:<3} {nc:>9}")
    out.append("")
    for arm, a in rep["arms"].items():
        out.append(f"{arm}: disputed {', '.join(a['disputed']) or 'none'}; "
                   f"retention to hand-read {', '.join(a.get('retention_pending') or []) or 'none'}; "
                   f"ho5-t2 read by hand {', '.join(a['hand']) or 'none'}")
    unscored = [f"{arm}:{x}" for arm, a in rep["arms"].items() for x in a["unscored"]]
    out.append(f"unscored {', '.join(unscored) or 'none'}")  # run_ready.py reads this form
    out.append(f"missing attempts: {', '.join(rep['missing']) or 'none'}")
    out.append("")
    out.append(f"{'round':5} {'task':8} {'arm':7} {'verdict':9} {'success':7} {'constr':6} {'at need':8} {'notes ch':>8}")
    for r in rep["rows"]:
        n = r["notes"] or {}
        nc = "" if not n else f"{n['notes_chars_mean']:.0f}"
        out.append(f"{r['round']:5} {r['task']:8} {r['arm']:7} {str(r['verdict']):9} "
                   f"{str(r['success']):7} {r['constraints'][0]}/{r['constraints'][1]:<4} "
                   f"{str(n.get('at_need')):8} {nc:>8}"
                   + (f"  aborted: {r['aborted']}" if r["aborted"] else ""))
    out.append("")
    s = rep["selection"]
    for arm, c in s["checks"].items():
        out.append(f"{arm}: " + ", ".join(f"{k} {'pass' if v else 'FAIL'}" for k, v in c.items()))
    out.append(f"candidate: {s['candidate'] or 'none (the default does not flip; the user decides)'}")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("spec")
    s.add_argument("--seed", type=int, required=True)
    s.add_argument("--root", required=True, help="pilot run root, relative to the repo")
    s.add_argument("--ws-root", required=True)
    s.add_argument("--python", default=sys.executable)
    s.add_argument("--opencode", required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--tasks", help="T1,T2: these tasks' steps only (the rehearsal)")
    r = sub.add_parser("report")
    r.add_argument("root", type=Path)
    r.add_argument("--trap-reviews", type=Path, help='{"r1:ho5-t2:a4-n3": {"repeat": bool}}')
    r.add_argument("--json", action="store_true")
    r.add_argument("--tasks", help="T1,T2: report these tasks only (the rehearsal)")
    r.add_argument("--retention-reviews", type=Path,
                   help='{"r1:ho5-t4:a4-n3": {"kept": bool, "note": ...}}: hand reads of non-kept states')
    a = p.parse_args(argv)
    if a.cmd == "spec":
        spec = make_spec(seed=a.seed, python=a.python, root=a.root, ws_root=a.ws_root,
                         opencode=a.opencode,
                         only=set(a.tasks.split(",")) if a.tasks else None)
        a.out.write_text(json.dumps(spec, indent=1), encoding="utf-8")
        for i, st in enumerate(spec["steps"], 1):
            print(f"{i:3}: {st['name']}")
        print(f"{len(spec['steps'])} steps -> {a.out}")
        return 0
    import report

    reviews = report.load_trap_reviews(a.trap_reviews) if a.trap_reviews else None
    only = set(a.tasks.split(",")) if a.tasks else None
    ret = ({k: bool(v["kept"]) for k, v in json.loads(a.retention_reviews.read_text(encoding="utf-8")).items()}
           if a.retention_reviews else None)
    rep = pilot_report(collect(a.root, reviews, only, ret))
    print(json.dumps(rep, indent=1, default=str) if a.json else "\n".join(format_report(rep)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
