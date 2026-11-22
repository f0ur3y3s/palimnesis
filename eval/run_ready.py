"""Phase 8 run-readiness gate: ``READY.json`` for a headless run directory.

    python eval/run_ready.py RUN_DIR --est-hours H [--short | --evidence FILE] [--no-suite]

Run on the host that will run the plan (Zeus), from its clone, at the plan's commit. It
reads the facts, checks each item of the gate in ``docs/plan/phases/phase8.md``, prints
every check and writes ``RUN_DIR/READY.json``. ``eval/headless.py`` refuses to start
unless that file says PASS for the plan's commit, SHA and config.

Checks (each fails when its fact cannot be read; nothing passes by default):

1. ``suite``: the full suite at this commit on this host passes (no "failed", no "error").
2. ``git``, ``git_commit``, ``git_pushed``: the tree is clean, HEAD is the plan's commit, and
   HEAD is ``origin/main``.
3. ``server``: ``/props`` is the plan's server (``headless.server_problem``);
   ``template``: the chat template's SHA-256 is the pinned one (docs/capabilities.md);
   ``strata_task``: the Strata startup task is registered.
4. ``update_pause``: Windows Update is paused past the run's estimated end, with 50% plus a
   day of margin; ``reboot``: no reboot is pending; ``disk``: every listed drive has at
   least ``--min-free-gb``; ``clock``: within 5 s of a time server.
5–9. Long runs only (not ``--short``): ``--evidence`` names the rehearsal run directory
   (all steps done, no STOPPED), the survival run directory (done, with a
   ``host-restart`` rerun), the report output (no unscored or missing parts, no traceback),
   and the hand check, plan check and independent review files (present, not empty).

``--short`` is for runs under an hour, such as the rehearsal and survival runs that
produce the evidence for a long run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "eval") not in sys.path:
    sys.path.append(str(ROOT / "eval"))
import headless  # noqa: E402

PINNED_TEMPLATE = "12827f24b742ea4e80cdc12dbcf9622227056b9f797252a3149263d4f9aaadce"
STRATA_TASK = "Palimnesis Strata"
EVIDENCE = ("rehearsal_run", "survival_run", "report_output", "hand_check", "plan_check",
            "review")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


def _suite(summary: str | None) -> dict:
    if not summary:
        return _check("suite", False, "no suite result")
    bad = re.search(r"\b(failed|error|errors)\b", summary)
    return _check("suite", not bad and "passed" in summary, summary)


def _run_dir_done(path: str | None, *, needs_restart: bool) -> tuple[bool, str]:
    if not path or not Path(path).is_dir():
        return False, f"no run directory {path!r}"
    d = Path(path)
    try:
        st = headless.status(d)
    except (OSError, ValueError) as e:
        return False, f"unreadable: {e}"
    if st["stopped"]:
        return False, f"STOPPED: {st['stopped']}"
    if st["done"] != st["total"]:
        return False, f"{st['done']}/{st['total']} steps done"
    if needs_restart:
        reasons = [e.get("reason") for e in headless.read_state(d) if e.get("event") == "started"]
        if "host-restart" not in reasons:
            return False, "no host-restart rerun recorded"
    return True, f"{st['done']}/{st['total']} steps done"


def _file(path: str | None) -> tuple[bool, str, str]:
    if not path or not Path(path).is_file():
        return False, f"no file {path!r}", ""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return bool(text.strip()), path if text.strip() else f"{path} is empty", text


def _evidence(evidence: dict | None) -> list[dict]:
    if evidence is None:
        return [_check("evidence", False, "a long run needs --evidence (items 5-9)")]
    out = []
    for key, restart in (("rehearsal_run", False), ("survival_run", True)):
        ok, detail = _run_dir_done(evidence.get(key), needs_restart=restart)
        out.append(_check(key, ok, detail))
    ok, detail, text = _file(evidence.get("report_output"))
    if ok and (m := re.search(r"unscored (?!none)|missing attempts: (?!none)|Traceback", text)):
        ok, detail = False, f"report shows {m.group(0)!r}"
    out.append(_check("report_output", ok, detail))
    for key in ("hand_check", "plan_check", "review"):
        ok, detail, _ = _file(evidence.get(key))
        out.append(_check(key, ok, detail))
    return out


def evaluate(plan: dict, facts: dict, *, est_hours: float, short: bool, evidence: dict | None,
             pinned_template: str = PINNED_TEMPLATE, min_free_gb: float = 50) -> list[dict]:
    """Every check of the gate from the facts read on the host."""
    checks = [_suite(facts.get("suite"))]
    dirty = facts.get("dirty")
    checks.append(_check("git", dirty == [], "clean" if dirty == [] else f"dirty: {dirty}"))
    checks.append(_check("git_commit", facts.get("head") == plan["commit"],
                         f"HEAD {facts.get('head')}, plan {plan['commit']}"))
    checks.append(_check("git_pushed", bool(facts.get("head"))
                         and facts.get("head") == facts.get("origin"),
                         f"HEAD {facts.get('head')}, origin/main {facts.get('origin')}"))
    props = facts.get("props")
    if props is None:
        checks.append(_check("server", False, "no /props"))
        checks.append(_check("template", False, "no /props"))
    else:
        problem = headless.server_problem(props, plan.get("server") or {})
        checks.append(_check("server", problem is None, problem or "as planned"))
        sha = facts.get("template_sha")
        checks.append(_check("template", sha == pinned_template, f"sha256 {sha}"))
    checks.append(_check("strata_task", facts.get("strata_task") is True,
                         f"{STRATA_TASK!r} registered: {facts.get('strata_task')}"))
    now, until = facts.get("now", time.time()), facts.get("update_pause_until")
    need = now + est_hours * 1.5 * 3600 + 86400
    checks.append(_check("update_pause", until is not None and until >= need,
                         f"paused until {_iso(until)}, needed {_iso(need)}"))
    checks.append(_check("reboot", facts.get("reboot_pending") is False,
                         f"reboot pending: {facts.get('reboot_pending')}"))
    free = facts.get("free_gb") or {}
    low = {k: v for k, v in free.items() if v < min_free_gb}
    checks.append(_check("disk", bool(free) and not low,
                         f"free GB {free}, minimum {min_free_gb}"))
    off = facts.get("clock_offset_s")
    checks.append(_check("clock", off is not None and abs(off) <= 5, f"offset {off} s"))
    if not short:
        checks += _evidence(evidence)
    return checks


def _iso(t: float | None) -> str:
    return "unknown" if t is None else time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


def write_ready(d: Path, plan: dict, checks: list[dict]) -> dict:
    ready = {"result": "PASS" if all(c["ok"] for c in checks) else "FAIL",
             "commit": plan["commit"], "plan_sha": plan["sha"], "config": plan["config"],
             "at": time.time(), "checks": checks}
    (d / "READY.json").write_text(json.dumps(ready, indent=1), encoding="utf-8")
    return ready


# --- host facts (Windows; Zeus) -----------------------------------------------------------

def _out(argv: list[str], **kw) -> str | None:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT, **kw)
    except OSError:
        return None
    return r.stdout if r.returncode == 0 else None


def _ps(script: str) -> str | None:
    return _out(["powershell", "-NoProfile", "-Command", script])


def gather_facts(plan: dict, *, run_suite: bool) -> dict:
    facts: dict = {"now": time.time()}
    if run_suite:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                           capture_output=True, text=True, cwd=ROOT)
        lines = [x for x in r.stdout.splitlines() if x.strip()]
        facts["suite"] = lines[-1] if lines and r.returncode == 0 else (
            f"exit {r.returncode}: {lines[-1] if lines else ''}")
    status = _out(["git", "status", "--porcelain"])
    facts["dirty"] = None if status is None else [x for x in status.splitlines() if x.strip()]
    facts["head"] = (_out(["git", "rev-parse", "--short", "HEAD"]) or "").strip() or None
    _out(["git", "fetch", "-q", "origin"])
    facts["origin"] = (_out(["git", "rev-parse", "--short", "origin/main"]) or "").strip() or None
    server = plan.get("server") or {}
    props = headless._probe_props(server["props"]) if server.get("props") else None
    facts["props"] = props
    if props is not None and isinstance(props.get("chat_template"), str):
        facts["template_sha"] = sha256_text(props["chat_template"])
    task = _ps(f"if (Get-ScheduledTask -TaskName '{STRATA_TASK}' -ErrorAction SilentlyContinue)"
               " { 'yes' } else { 'no' }")
    facts["strata_task"] = None if task is None else task.strip() == "yes"
    pause = _ps("(Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\WindowsUpdate\\UX\\Settings'"
                ").PauseUpdatesExpiryTime")
    try:
        facts["update_pause_until"] = time.mktime(time.strptime(
            pause.strip()[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone if pause else None
    except ValueError:
        facts["update_pause_until"] = None
    reboot = _ps("(Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Component "
                 "Based Servicing\\RebootPending') -or (Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\"
                 "Windows\\CurrentVersion\\WindowsUpdate\\Auto Update\\RebootRequired')")
    facts["reboot_pending"] = None if reboot is None else reboot.strip() == "True"
    disks = _ps("Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -gt 0 } | "
                "ForEach-Object { '{0}={1}' -f $_.Name, ($_.Free/1GB) }")
    facts["free_gb"] = {k: float(v) for k, v in (x.split("=") for x in (disks or "").split())}
    chart = _out(["w32tm", "/stripchart", "/computer:time.windows.com", "/samples:1",
                  "/dataonly"])
    m = re.search(r"([+-]\d+\.\d+)s", chart or "")
    facts["clock_offset_s"] = float(m.group(1)) if m else None
    return facts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run_dir", type=Path)
    p.add_argument("--est-hours", type=float, required=True,
                   help="estimated duration from measured per-arm times (the upper end)")
    p.add_argument("--short", action="store_true", help="a run under an hour: items 1-4 only")
    p.add_argument("--evidence", type=Path, help="JSON naming the items 5-9 evidence")
    p.add_argument("--min-free-gb", type=float, default=50)
    p.add_argument("--no-suite", action="store_true",
                   help="skip running the suite (the check then fails); for dry runs")
    a = p.parse_args(argv)
    if a.short and a.est_hours >= 1:
        p.error("--short is for runs under an hour")
    plan = headless.read_plan(a.run_dir)
    evidence = json.loads(a.evidence.read_text(encoding="utf-8")) if a.evidence else None
    facts = gather_facts(plan, run_suite=not a.no_suite)
    checks = evaluate(plan, facts, est_hours=a.est_hours, short=a.short, evidence=evidence,
                      min_free_gb=a.min_free_gb)
    ready = write_ready(a.run_dir, plan, checks)
    for c in checks:
        print(f"{'PASS' if c['ok'] else 'FAIL'}  {c['name']:14} {c['detail']}")
    print(f"READY.json: {ready['result']}")
    return 0 if ready["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
