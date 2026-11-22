"""Phase 8 S2h: headless runs that need no Claude Code session and resume by themselves.

    python eval/headless.py plan RUN_DIR --spec SPEC.json --commit SHA   # once
    python eval/headless.py run RUN_DIR        # what the scheduled task runs
    python eval/headless.py status RUN_DIR     # progress, from the state file
    python eval/headless.py install RUN_DIR    # register the Windows scheduled task (Zeus)
    python eval/headless.py uninstall RUN_DIR
    python eval/headless.py rerun RUN_DIR --step N --reason TEXT   # after a stop (D44.7)
    python eval/headless.py skip RUN_DIR --step N --reason TEXT

A run directory holds:

- ``plan.json``: the numbered steps, each an argv run from the repository root, with the
  commit and the config it was written for, and its own SHA-256. It is written once
  (``write_plan``) and never changed.
- ``state.jsonl``: append-only events, each flushed and fsynced: ``started`` and
  ``finished`` (with ``exit``) per step.
- ``READY.json``: written by ``eval/run_ready.py`` (the run-readiness gate, Phase 8 plan).
  The runner refuses to start unless it says PASS for the plan's commit, SHA and config.
- ``STOPPED``: written when a step exits nonzero. The runner then refuses to continue until
  a person has decided (a rerun for an infrastructure failure, D44.7, or a resume at the
  next step) and removed the file, and the decision is recorded.
- ``runner.log``: the steps' output.

Resolution (``next_step``) uses the state alone:

- a step with a ``finished`` event of exit 0 is done;
- a step ``started`` and never ``finished`` was cut off by the host (a reboot, a crash, a
  killed process). It reruns with ``--reason host-restart``, the D44.7 infrastructure case.
  The reason goes to that rerun only;
- a nonzero ``finished`` stops the run.

``install`` registers a task that starts at boot and now, under the current user with S4U
logon (it runs whether or not anyone is logged on, and stores no password). It allows one
instance at a time and has no time limit. A lock file keeps a second runner out.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
TASK_PREFIX = "Palimnesis run"


class Stopped(RuntimeError):
    """The run stopped at a failed step and waits for a person."""


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def write_plan(d: Path, steps: list[dict], *, commit: str, config: str,
               server: dict | None = None, env: dict | None = None) -> dict:
    """Write ``plan.json`` once; a plan already there is never replaced. ``server`` is the
    upstream every step needs (``server_problem``), checked before each step. ``env`` is
    added to every step's environment (for example ``OPENCODE_EXE`` on a host whose
    OpenCode is not where ``eval/oc_harness.py`` looks)."""
    d.mkdir(parents=True, exist_ok=True)
    path = d / "plan.json"
    body = {"commit": commit, "config": config, "steps": steps, "server": server}
    if env:
        body["env"] = env
    plan = {**body, "sha": _sha(body)}
    with open(path, "x", encoding="utf-8") as f:  # FileExistsError if a plan exists
        json.dump(plan, f, indent=1)
    return plan


def read_plan(d: Path) -> dict:
    plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
    body = {k: plan.get(k) for k in ("commit", "config", "steps", "server")}
    if plan.get("env"):
        body["env"] = plan["env"]
    if plan.get("sha") != _sha(body):
        raise ValueError("plan.json does not match its own SHA-256")
    return plan


def append_state(d: Path, event: dict) -> None:
    with open(d / "state.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({**event, "at": time.time()}) + "\n")
        f.flush()
        os.fsync(f.fileno())


def read_state(d: Path) -> list[dict]:
    path = d / "state.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass  # a line torn by a power cut: its step never counted as finished
    return out


def next_step(plan: dict, events: list[dict]) -> tuple[int | None, str | None]:
    """(index of the next step, rerun reason or None); (None, None) when all are done.
    A person's ``decision`` after a stop either reruns the step with its reason or skips
    it (``decide``)."""
    started, finished, rerun, skipped = set(), {}, {}, set()
    for e in events:
        kind, i = e.get("event"), e.get("step")
        if kind == "started":
            started.add(i)
            rerun.pop(i, None)
        elif kind == "finished":
            finished[i] = e.get("exit")
        elif kind == "decision" and e.get("action") == "rerun":
            finished.pop(i, None)
            started.discard(i)
            rerun[i] = e["reason"]
        elif kind == "decision" and e.get("action") == "skip":
            skipped.add(i)
    for i in range(len(plan["steps"])):
        if i in skipped:
            continue
        if i in finished:
            if finished[i] != 0:
                raise Stopped(f"step {i + 1} ({plan['steps'][i]['name']}) exited {finished[i]}")
            continue
        if i in rerun:
            return i, rerun[i]
        return i, ("host-restart" if i in started else None)
    return None, None


def decide(d: Path, *, step: int, action: str, reason: str) -> None:
    """Record a person's decision on the stopped ``step`` (1-based): ``rerun`` it with
    ``reason`` (an infrastructure failure, D44.7) or ``skip`` to the next step; then the
    STOPPED marker is removed. Record the same decision in a decision entry."""
    if action not in ("rerun", "skip") or not reason.strip():
        raise ValueError("a decision is rerun or skip, with a reason")
    plan = read_plan(d)
    try:
        i, _ = next_step(plan, read_state(d))
    except Stopped as e:
        if not str(e).startswith(f"step {step} "):
            raise ValueError(f"step {step} is not the stopped step: {e}") from None
    else:
        # A stop before a step ran (the server check): only a retry of that step.
        if not (d / "STOPPED").exists() or i is None or i != step - 1 or action != "rerun":
            raise ValueError("the run is not stopped at that step")
        append_state(d, {"step": step - 1, "event": "decision", "action": "retry",
                         "reason": reason.strip()})
        (d / "STOPPED").unlink()
        return
    append_state(d, {"step": step - 1, "event": "decision", "action": action,
                     "reason": reason.strip()})
    (d / "STOPPED").unlink(missing_ok=True)


def _ready_problem(d: Path, plan: dict) -> str | None:
    path = d / "READY.json"
    if not path.exists():
        return "no READY.json: run eval/run_ready.py first"
    ready = json.loads(path.read_text(encoding="utf-8"))
    for key, want in (("result", "PASS"), ("commit", plan["commit"]),
                      ("plan_sha", plan["sha"]), ("config", plan["config"])):
        if ready.get(key) != want:
            return f"READY.json {key} is {ready.get(key)!r}, expected {want!r}"
    return None


def server_problem(props: dict, want: dict) -> str | None:
    """Why the upstream's ``/props`` is not the server the plan needs, or None: real
    ``n_ctx``, slots, build and the sampling defaults (OpenCode sends none, D115.12)."""
    gen = props.get("default_generation_settings") or {}
    params = gen.get("params") or {}
    have = {"n_ctx": gen.get("n_ctx"), "slots": props.get("total_slots"),
            "build": props.get("build_info"), "temperature": params.get("temperature"),
            "top_p": params.get("top_p"), "top_k": params.get("top_k")}
    bad = [f"{k} is {have[k]!r}, expected {want[k]!r}" for k in have
           if k in want and have[k] != want[k]]
    return "; ".join(bad) or None


def _probe_props(url: str) -> dict | None:
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())
    except (OSError, ValueError):
        return None


def wait_for_server(want: dict, probe, *, poll_s: float = 30, wait_s: float = 3600) -> str | None:
    """Wait until the upstream answers (Strata loads for about 16 minutes after a boot),
    then check it. None when it is the right server, else why not."""
    deadline = time.monotonic() + wait_s
    while True:
        props = probe(want["props"])
        if props is not None:
            return server_problem(props, want)
        if time.monotonic() >= deadline:
            return f"server not up at {want['props']} after {wait_s:.0f} s"
        time.sleep(poll_s)


def _default_runner(log: Path, extra_env: dict | None = None) -> Callable[[list[str]], int]:
    def run(argv: list[str]) -> int:
        with open(log, "a", encoding="utf-8") as out:
            out.write(f"\n=== {time.strftime('%Y-%m-%dT%H:%M:%S')} {' '.join(argv)}\n")
            out.flush()
            return subprocess.call(argv, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT,
                                    env={**os.environ, "PYTHONUNBUFFERED": "1",
                                         **(extra_env or {})})
    return run


class _Lock:
    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pid = self.path.read_text(encoding="utf-8").strip()
            if pid and _alive(int(pid)):
                raise RuntimeError(f"another runner (pid {pid}) holds {self.path}")
            self.path.unlink()  # left by a runner the host killed
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return self

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True,
                             text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def run(d: Path, runner: Callable[[list[str]], int] | None = None, *,
        probe=_probe_props, poll_s: float = 30, wait_s: float = 3600) -> int:
    """Run the plan's remaining steps in order. 0 when all are done; nonzero on a stop or a
    refusal (a missing or stale readiness PASS, an existing STOPPED)."""
    plan = read_plan(d)
    if (d / "STOPPED").exists():
        print(f"refused: {d / 'STOPPED'} exists; decide, record it, then remove the file",
              file=sys.stderr)
        return 2
    if problem := _ready_problem(d, plan):
        print(f"refused: {problem}", file=sys.stderr)
        return 2
    runner = runner or _default_runner(d / "runner.log", plan.get("env"))
    with _Lock(d / "runner.lock"):
        while True:
            try:
                i, reason = next_step(plan, read_state(d))
            except Stopped as e:
                (d / "STOPPED").write_text(f"{e}\n", encoding="utf-8")
                return 2
            if i is None:
                return 0
            if plan.get("server"):
                if problem := wait_for_server(plan["server"], probe, poll_s=poll_s,
                                              wait_s=wait_s):
                    (d / "STOPPED").write_text(f"before step {i + 1}: {problem}\n",
                                               encoding="utf-8")
                    return 2
            argv = list(plan["steps"][i]["argv"])
            if reason:
                argv += ["--reason", reason]
            append_state(d, {"step": i, "event": "started", "reason": reason})
            code = runner(argv)
            append_state(d, {"step": i, "event": "finished", "exit": code})
            if code != 0:
                (d / "STOPPED").write_text(
                    f"step {i + 1} ({plan['steps'][i]['name']}) exit {code}\n", encoding="utf-8")
                return code


def status(d: Path) -> dict:
    plan = read_plan(d)
    events = read_state(d)
    done: set[int] = set()
    for e in events:  # in order: a later rerun decision undoes nothing already done
        if e.get("event") == "finished" and e.get("exit") == 0:
            done.add(e["step"])
    started = [e for e in events if e.get("event") == "started"]
    finished = {e["step"] for e in events if e.get("event") == "finished"}
    current = next((e for e in reversed(started) if e["step"] not in finished), None)
    stopped = d / "STOPPED"
    return {"total": len(plan["steps"]), "done": len(done),
            "current": None if current is None else {
                "step": current["step"] + 1, "name": plan["steps"][current["step"]]["name"],
                "since": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(current["at"])),
                "reason": current.get("reason")},
            "stopped": stopped.read_text(encoding="utf-8").strip() if stopped.exists() else None,
            "reruns": sum(1 for e in started if e.get("reason"))}


def _task_name(d: Path) -> str:
    return f"{TASK_PREFIX} {d.resolve().parent.name} {d.resolve().name}"


def install_script(d: Path, python: str) -> str:
    """PowerShell that registers the run's scheduled task (S4U: runs logged on or not)."""
    d = d.resolve()
    args = f'"{ROOT / "eval" / "headless.py"}" run "{d}"'
    return "\n".join([
        f'$a = New-ScheduledTaskAction -Execute "{python}" -Argument \'{args}\' '
        f'-WorkingDirectory "{ROOT}"',
        "$t = @((New-ScheduledTaskTrigger -AtStartup), "
        "(New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(30)))",
        "$p = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited",
        "$s = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit 0 "
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable",
        f'Register-ScheduledTask -TaskName "{_task_name(d)}" -Action $a -Trigger $t '
        "-Principal $p -Settings $s -Force | Out-Null",
        f'"registered {_task_name(d)}"'])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command",
                   choices=["plan", "run", "status", "install", "uninstall", "rerun", "skip"])
    p.add_argument("run_dir", type=Path)
    p.add_argument("--step", type=int, help="rerun/skip: the stopped step (1-based)")
    p.add_argument("--reason", default="", help="rerun/skip: why (recorded)")
    p.add_argument("--spec", type=Path,
                   help="plan: JSON with config, server and steps [{name, argv}]")
    p.add_argument("--commit", help="plan: the commit the plan runs at")
    a = p.parse_args(argv)
    if a.command == "plan":
        spec = json.loads(a.spec.read_text(encoding="utf-8-sig"))
        plan = write_plan(a.run_dir, spec["steps"], commit=a.commit, config=spec["config"],
                          server=spec.get("server"), env=spec.get("env"))
        print(f"wrote {a.run_dir / 'plan.json'}: {len(plan['steps'])} steps, sha {plan['sha'][:12]}")
        for i, s in enumerate(plan["steps"], 1):
            print(f"  {i}: {s['name']}")
        return 0
    if a.command in ("rerun", "skip"):
        decide(a.run_dir, step=a.step, action=a.command, reason=a.reason)
        print(f"recorded {a.command} of step {a.step}; record it in a decision entry too")
        return 0
    if a.command == "run":
        return run(a.run_dir)
    if a.command == "status":
        print(json.dumps(status(a.run_dir), indent=1))
        return 0
    if a.command == "install":
        script = install_script(a.run_dir, sys.executable)
    else:
        script = (f'Unregister-ScheduledTask -TaskName "{_task_name(a.run_dir)}" '
                  "-Confirm:$false; 'removed'")
    return subprocess.call(["powershell", "-NoProfile", "-Command", script])


if __name__ == "__main__":
    sys.exit(main())
