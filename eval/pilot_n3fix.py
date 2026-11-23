"""D137 pilot: the n3 carry without quoted duplicates, on retired heldout5.

    python eval/pilot_n3fix.py spec --root DIR --ws-root DIR --python PY --opencode EXE --out SPEC.json
        [--tasks T,...] [--rounds r1,...]
    python eval/pilot_n3fix.py report ROOT [--retention-reviews FILE] [--tasks T,...] [--rounds r1,...]

**Steps:** ``a8`` (``a4-d77`` with notes n3, now with the D137 dedupe) on ho5-t2, ho5-t4 and
ho5-t13, in two rounds (``ROOT/r1``, ``ROOT/r2``): 6 attempts, as in S3's ho5 rounds.

**Report, against D137.3:**
- retention at the trap turn in every ho5-t4 and ho5-t13 attempt (the notes in force hold
  the warning; a non-kept state is read by hand into ``--retention-reviews``);
- the mean length of the committed notes versions, against R69's ``a4-n3`` (5,531 chars);
- duplicates: the notes in force at the trap turn holding the warning's code more than once
  (the defect D137 fixes), per attempt.
It prints ``unscored`` and ``missing attempts:`` lines for ``eval/run_ready.py``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (HERE, HERE / "tasks"):
    if str(p) not in sys.path:
        sys.path.append(str(p))

import pilot_s3  # noqa: E402

ARM = "a8"
TASKS = ("ho5-t2", "ho5-t4", "ho5-t13")
RETENTION = ("ho5-t4", "ho5-t13")
ROUNDS = ("r1", "r2")
R69_N3_CHARS = 5531.0
TAG = "n3fix-pilot"


def make_spec(*, python: str, root: str, ws_root: str, opencode: str,
              upstream: str = "http://127.0.0.1:8080", n_ctx: int = 32768,
              tasks=TASKS, rounds=ROUNDS) -> dict:
    steps = [{"name": f"{rd} {t} {ARM}", "argv": [
        python, "eval/tasks/run.py", "--task", t, "--arm", "4", "--config", ARM,
        "--out", f"{root}/{rd}", "--ws-root", f"{ws_root}\\{rd}", "--upstream", upstream,
        "--expect-n-ctx", str(n_ctx), "--tag", TAG]} for rd in rounds for t in tasks]
    name = "n3fix-pilot" + ("" if tuple(tasks) == TASKS else "-" + "+".join(tasks)) \
        + ("" if tuple(rounds) == ROUNDS else "-" + "+".join(rounds))
    return {"config": name, "steps": steps,
            "server": {"props": f"{upstream}/props", "n_ctx": n_ctx, "slots": 1,
                       "build": "Strata 0.1.58", "temperature": 1.0, "top_p": 0.95, "top_k": 20},
            "env": {"OPENCODE_EXE": opencode}}


def _load(run: Path, tasks) -> dict:
    import attempts as att
    import report

    manifest = att.load(run) if (run / "attempts.json").exists() else []
    chosen, _ = att.designate(manifest, "task", ARM)
    out = {}
    for t in tasks:
        a = chosen.get(t)
        if a is None:
            continue
        d = Path(a["records"]) / f"{t}-{ARM}"
        f = d / "result.json"
        r = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"aborted": "no result.json"}
        out[t] = (r, d if report._usable(r) else None)
    return out


def _duplicates(d: Path, task_id: str) -> int | None:
    """How many times the warning's backticked code occurs in the notes in force at the
    trap turn (1 when kept once; 0 when not held); None without notes."""
    import notes_audit
    import state_eval as se

    task = se.task_module(task_id)
    frags = re.findall(r"`([^`]+)`", getattr(task, "TRAP_WARNING", "") or "")
    vs = notes_audit.read_versions(d / "archive.db")
    at = notes_audit.need_time(d / "archive.db", task)
    inforce = [v for v in vs if at is None or v["created_at"] <= at]
    if not inforce or not frags:
        return None
    return max(inforce[-1]["text"].count(f) for f in frags)


def collect(root: Path, tasks=TASKS, rounds=ROUNDS, reviews: dict | None = None) -> list[dict]:
    reviews = reviews or {}
    rows = []
    for rd in rounds:
        got = _load(root / rd, tasks)
        for t in tasks:
            r, d = got.get(t, (None, None))
            notes = pilot_s3._audit(d, t) if d is not None else None
            rows.append({"round": rd, "task": t, "present": r is not None,
                         "usable": d is not None, "notes": notes,
                         "copies": _duplicates(d, t) if d is not None else None,
                         "retention_review": reviews.get(f"{rd}:{t}:{ARM}")})
    return rows


def evaluate(rows: list[dict]) -> dict:
    ret = [r for r in rows if r["task"] in RETENTION]
    kept = [pilot_s3._kept(r) for r in ret]
    chars = [r["notes"]["notes_chars_mean"] for r in rows if r["notes"]]
    mean = sum(chars) / len(chars) if chars else None
    dup = [f"{r['round']}:{r['task']}" for r in rows if (r["copies"] or 0) > 1]
    checks = {"retention": bool(ret) and all(k is True for k in kept),
              "shorter_than_r69": mean is not None and mean < R69_N3_CHARS,
              "no_duplicates": not dup}
    return {"retention": (sum(k is True for k in kept), len(ret)),
            "retention_pending": [f"{r['round']}:{r['task']}" for r, k in zip(ret, kept) if k is None],
            "notes_chars_mean": mean, "duplicates": dup, "checks": checks,
            "pass": all(checks.values()),
            "missing": [f"{r['round']}:{r['task']}" for r in rows if not r["present"]],
            "unscored": [f"{r['round']}:{r['task']}" for r in rows if r["present"] and not r["usable"]]}


def format_report(ev: dict, rows: list[dict]) -> list[str]:
    out = ["D137 pilot: n3 carry without quoted duplicates (a8, retired ho5)", ""]
    for r in rows:
        n = r["notes"] or {}
        out.append(f"{r['round']} {r['task']:8} at need {str(n.get('at_need')):8} "
                   f"warning copies {r['copies']} notes ch "
                   + (f"{n['notes_chars_mean']:.0f}" if n else "-"))
    out.append("")
    mean = ev["notes_chars_mean"]
    out.append(f"retention {ev['retention'][0]}/{ev['retention'][1]}; to hand-read "
               f"{', '.join(ev['retention_pending']) or 'none'}")
    out.append(f"notes chars mean {'n/a' if mean is None else f'{mean:.0f}'} (R69 a4-n3 {R69_N3_CHARS:.0f})")
    out.append(f"duplicated warnings {', '.join(ev['duplicates']) or 'none'}")
    out.append(f"unscored {', '.join(ev['unscored']) or 'none'}")
    out.append(f"missing attempts: {', '.join(ev['missing']) or 'none'}")
    out.append(", ".join(f"{k} {'pass' if v else 'FAIL'}" for k, v in ev["checks"].items()))
    out.append(f"D137 pilot: {'PASS' if ev['pass'] else 'FAIL'}")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("spec")
    s.add_argument("--root", required=True)
    s.add_argument("--ws-root", required=True)
    s.add_argument("--python", default=sys.executable)
    s.add_argument("--opencode", required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--tasks")
    s.add_argument("--rounds")
    r = sub.add_parser("report")
    r.add_argument("root", type=Path)
    r.add_argument("--retention-reviews", type=Path)
    r.add_argument("--tasks")
    r.add_argument("--rounds")
    a = p.parse_args(argv)
    tasks = tuple(a.tasks.split(",")) if a.tasks else TASKS
    rounds = tuple(a.rounds.split(",")) if a.rounds else ROUNDS
    if a.cmd == "spec":
        spec = make_spec(python=a.python, root=a.root, ws_root=a.ws_root, opencode=a.opencode,
                         tasks=tasks, rounds=rounds)
        a.out.write_text(json.dumps(spec, indent=1), encoding="utf-8")
        for i, st in enumerate(spec["steps"], 1):
            print(f"{i:3}: {st['name']}")
        print(f"{len(spec['steps'])} steps -> {a.out}")
        return 0
    reviews = ({k: bool(v["kept"]) for k, v in json.loads(a.retention_reviews.read_text(encoding="utf-8")).items()}
               if a.retention_reviews else None)
    rows = collect(a.root, tasks, rounds, reviews)
    print("\n".join(format_report(evaluate(rows), rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
