"""OMP 18.16.0 through Palimnesis against live Strata (Phase 4B close): the plan §6 gates.

OMP runs headless (``omp -p --mode json``) with the shipped adapter, installed by
``palimnesis setup omp`` into a throwaway agent directory (``PI_CODING_AGENT_DIR``), with
its own session directory and working folder. The user's ``~/.omp`` is never read or
written. The proxy is a local ``palimnesis serve`` whose upstream is Strata
(``--upstream``, e.g. ``http://192.168.1.173:8080``). OMP's JSON events have Pi's shape.

Scenarios (each in ``<root>/<scenario>/``; pass/fail and checks in ``summary.json``):
- ``smoke_chat``: a tool loop (read a file, answer), then the session
  resumed with ``--resume <id>`` for a second turn. Checks: every request archived on the
  Chat endpoint under one session (OMP's own id, routed by the extension), both
  answers right, ``--explain`` 0 unexplained, ``transcripts verify``.
- ``gate`` (Chat, small input budget): as ``pi_live_smoke.py gate``. Four large files leave
  the view, the first is deleted, the code it held is asked for, and a last turn greps the
  transcript directory (D37's capability criterion: a tool call names a path under it).
- ``restart`` (Chat, small input budget): the proxy restarts after each of three reads;
  the last turn asks for log1's code.
- ``cancel`` (Chat): OMP is killed while Strata decodes its answer. Checks: Strata's
  ``/status`` shows the slot free within 1 s of the kill (contracts §8), the archive
  records the attempt ``cancelled`` and none completed, and the session then resumes.

    uv run python eval/probes/omp_live_smoke.py --upstream http://192.168.1.173:8080 [smoke gate restart cancel]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
OMP = shutil.which("omp") or "omp"
MODEL = os.environ.get("OMP_MODEL", "qwen3.8-flash-next-iq3_xxs")
CODE = "ZX-4471-QUAIL"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def strata_status(upstream: str) -> dict:
    return httpx.get(f"{upstream}/status", timeout=5).json()


def wait_idle(upstream: str, limit: float = 1800) -> None:
    end = time.time() + limit
    while time.time() < end:
        s = strata_status(upstream)
        if not s.get("busy") and not s.get("queued"):
            return
        time.sleep(1)
    raise RuntimeError("Strata never went idle")


class Run:
    def __init__(self, root: Path, name: str, upstream: str, protocol: str,
                 input_budget: int | None) -> None:
        self.dir = root / name
        shutil.rmtree(self.dir, ignore_errors=True)
        self.agent, self.sessions, self.work = (self.dir / "agent", self.dir / "sessions",
                                                self.dir / "work")
        for d in (self.agent, self.sessions, self.work):
            d.mkdir(parents=True)
        self.upstream = upstream
        self.protocol = protocol
        self.port = free_port()
        self.db = self.dir / "archive.db"
        self.transcripts = self.dir / "transcripts"
        # The server itself, not a ``uv run`` wrapper (see pi_live_smoke.py).
        argv = [sys.executable, "-m", "palimnesis", "serve", "--port", str(self.port),
                "--upstream", upstream, "--db", str(self.db), "--transcripts", str(self.transcripts)]
        if input_budget:
            argv += ["--input-budget", str(input_budget)]
        self.argv = argv
        self.log = open(self.dir / "serve.log", "ab")
        self.proxy = subprocess.Popen(argv, cwd=REPO, stdout=self.log, stderr=subprocess.STDOUT)
        self._wait_port()
        setup = subprocess.run([sys.executable, "-m", "palimnesis", "setup", "omp", "--model", MODEL,
                                "--agent-dir", str(self.agent), "--port", str(self.port)],
                               cwd=REPO, capture_output=True, text=True)
        if setup.returncode:
            raise RuntimeError(setup.stdout + setup.stderr)
        self.turns: list[dict] = []
        self.session: str | None = None

    def restart(self) -> None:
        self.proxy.terminate()
        self.proxy.wait(30)
        self.proxy = subprocess.Popen(self.argv, cwd=REPO, stdout=self.log, stderr=subprocess.STDOUT)
        self._wait_port()

    def _wait_port(self) -> None:
        end = time.time() + 120
        while time.time() < end:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", self.port)) == 0:
                    return
            time.sleep(0.5)
        raise RuntimeError("palimnesis serve did not start")

    def env(self) -> dict:
        e = {k: v for k, v in os.environ.items()
             if not k.startswith(("PI_", "OPENAI", "ANTHROPIC")) and k not in ("HTTP_PROXY", "HTTPS_PROXY")}
        e.update({"PI_CODING_AGENT_DIR": str(self.agent), "NO_COLOR": "1"})
        return e

    def argv_for(self, prompt: str) -> list[str]:
        # The shipped configuration as is: titles, skills and background roles included.
        argv = [OMP, "-p", "--mode", "json", "--auto-approve", "--no-lsp",
                "--session-dir", str(self.sessions), "--model", f"palimnesis/{MODEL}"]
        if self.session:
            argv += ["--resume", self.session]
        return argv + [prompt]

    def omp(self, prompt: str, timeout: float = 1200) -> dict:
        t0 = time.time()
        p = subprocess.run(self.argv_for(prompt), cwd=self.work, env=self.env(),
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
        return self._record(prompt, p.returncode, p.stdout, p.stderr, t0)

    def _record(self, prompt: str, rc: int, stdout: bytes, stderr: bytes, t0: float) -> dict:
        n = len(self.turns) + 1
        (self.dir / f"turn{n}.stdout.jsonl").write_bytes(stdout)
        (self.dir / f"turn{n}.stderr.txt").write_bytes(stderr)
        events = []
        for line in stdout.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        for e in events:
            if e.get("type") == "session" and not self.session:
                self.session = e.get("id")
        turn = {"prompt": prompt, "rc": rc, "seconds": round(time.time() - t0, 1),
                "session_event": next((e.get("id") for e in events if e.get("type") == "session"), None),
                "answer": final_text(events), "tool_calls": tool_calls(events)}
        self.turns.append(turn)
        return turn

    def close(self) -> dict:
        try:
            checks = self.checks()
            end = time.time() + 30
            while checks["verify_rc"] != [0] * len(checks["sessions"]) and time.time() < end:
                time.sleep(2)
                checks = self.checks()
        finally:
            self.proxy.terminate()
            try:
                self.proxy.wait(30)
            except subprocess.TimeoutExpired:
                self.proxy.kill()
            self.log.close()
        return checks

    def checks(self) -> dict:
        conn = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        try:
            endpoints = [e for (e,) in conn.execute("SELECT endpoint FROM requests")]
            sessions = [s for (s,) in conn.execute("SELECT session_id FROM sessions")]
            failed = [json.loads(p).get("reason") for (p,) in conn.execute(
                "SELECT payload FROM events WHERE kind = 'attempt_failed'")]
            cancelled = conn.execute("SELECT count(*) FROM events WHERE kind = 'cancelled'").fetchone()[0]
            views = conn.execute("SELECT count(*) FROM view_versions").fetchone()[0]
            excerpts = conn.execute("SELECT rendered FROM excerpt_blocks WHERE status = 'selected'"
                                    ).fetchall()
            over = [json.loads(p).get("input_tokens") for (p,) in conn.execute(
                "SELECT payload FROM events WHERE kind = 'upstream_call'")]
        finally:
            conn.close()
        explain = subprocess.run([sys.executable, "eval/replay.py", "--explain", str(self.db), "--json"],
                                 cwd=REPO, capture_output=True, text=True)
        (self.dir / "explain.json").write_text(explain.stdout, encoding="utf-8")
        verify = [subprocess.run([sys.executable, "-m", "palimnesis", "transcripts", "verify", s,
                                  "--db", str(self.db), "--root", str(self.transcripts)],
                                 cwd=REPO, capture_output=True, text=True) for s in sessions]
        log = (self.dir / "serve.log").read_text(encoding="utf-8", errors="replace")
        return {"requests": len(endpoints), "refused_400": log.count('" 400 '),
                "refused_409": log.count('" 409 '), "endpoints": sorted(set(endpoints)),
                "sessions": sessions, "attempts_failed": failed, "cancelled": cancelled,
                "view_versions": views, "max_input_tokens": max([t for t in over if t] or [0]),
                "excerpts_with_code": sum(CODE in r for (r,) in excerpts),
                "explain_rc": explain.returncode,
                "verify_rc": [v.returncode for v in verify],
                "verify_out": [v.stdout[-300:] + v.stderr[-300:] for v in verify if v.returncode]}


def final_text(events: list[dict]) -> str:
    text = ""
    for e in events:
        if e.get("type") == "message_end" and (e.get("message") or {}).get("role") == "assistant":
            parts = (e["message"].get("content") or [])
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)
                           and p.get("type") == "text") or text
    return text


def tool_calls(events: list[dict]) -> list[dict]:
    return [{"tool": e.get("toolName"), "args": e.get("args")} for e in events
            if e.get("type") == "tool_execution_start"]


def smoke(root: Path, upstream: str, protocol: str) -> dict:
    run = Run(root, f"smoke_{protocol}", upstream, protocol, None)
    (run.work / "notes.txt").write_text("The release train leaves on Thursday.\n", encoding="utf-8")
    try:
        first = run.omp("Read notes.txt and tell me in one sentence what it says.")
        second = run.omp("Which day was that? Answer with one word.")
    finally:
        checks = run.close()
    endpoint = "/v1/chat/completions" if protocol == "chat" else "/v1/messages"
    ok = (first["rc"] == 0 and second["rc"] == 0 and "thursday" in first["answer"].lower()
          and "thursday" in second["answer"].lower() and checks["endpoints"] == [endpoint]
          and checks["sessions"] == [run.session] and second["session_event"] == run.session
          and checks["explain_rc"] == 0 and checks["verify_rc"] == [0]
          and any(c["tool"] == "read" for c in first["tool_calls"]))
    return {"scenario": f"smoke_{protocol}", "pass": ok, "turns": run.turns, "checks": checks}


def filler(i: int, lines: int = 220) -> str:
    return "\n".join(f"record {i}-{n}: sensor {n % 17} reading {(n * 37 + i) % 1000} units, "
                     f"status nominal, batch {i * 1000 + n}" for n in range(lines))


def write_logs(run: Run, count: int) -> None:
    for i in range(1, count + 1):
        body = filler(i)
        if i == 1:
            lines = body.split("\n")
            lines.insert(97, f"NOTE: the deploy code for this release is {CODE}.")
            body = "\n".join(lines)
        (run.work / f"log{i}.txt").write_text(body + "\n", encoding="utf-8")


ASK = ("What is the deploy code that log1.txt mentioned? log1.txt has been deleted; find it "
       "in this conversation's history. Reply with the code only.")


def gate(root: Path, upstream: str, budget: int) -> dict:
    run = Run(root, "gate_chat", upstream, "chat", budget)
    write_logs(run, 4)
    try:
        for i in range(1, 5):
            run.omp(f"Read log{i}.txt in full and reply with its line count only.")
        (run.work / "log1.txt").unlink()
        last = run.omp(ASK)
        confirm = run.omp("Confirm that code from the exact transcript of this conversation: grep "
                          "the transcript directory named in your instructions for ZX- and quote "
                          "the matching line.")
    finally:
        checks = run.close()
    root_str = str(run.transcripts).replace("\\", "/").lower()
    used = [c for c in confirm["tool_calls"]
            if root_str in json.dumps(c["args"]).replace("\\\\", "/").lower()]
    return {"scenario": "gate_chat",
            "pass": (CODE in last["answer"] and CODE in confirm["answer"] and bool(used)
                     and checks["view_versions"] > 0 and checks["sessions"] == [run.session]
                     and checks["explain_rc"] == 0 and checks["verify_rc"] == [0]),
            "answer_via_excerpt": checks["excerpts_with_code"] > 0,
            "transcript_calls": used, "turns": run.turns, "checks": checks}


def restart(root: Path, upstream: str, budget: int) -> dict:
    run = Run(root, "restart_chat", upstream, "chat", budget)
    write_logs(run, 3)
    try:
        for i in range(1, 4):
            run.omp(f"Read log{i}.txt in full and reply with its line count only.")
            run.restart()
        (run.work / "log1.txt").unlink()
        last = run.omp(ASK)
    finally:
        checks = run.close()
    ok = (CODE in last["answer"] and all(t["rc"] == 0 for t in run.turns)
          and checks["explain_rc"] == 0 and checks["verify_rc"] == [0]
          and checks["sessions"] == [run.session])
    return {"scenario": "restart_chat", "pass": ok, "turns": run.turns, "checks": checks}


def cancel(root: Path, upstream: str, trials: int) -> dict:
    run = Run(root, "cancel_chat", upstream, "chat", None)
    results = []
    try:
        first = run.omp("Reply with the single word ready.")
        for n in range(trials):
            wait_idle(upstream)
            t0 = time.time()
            p = subprocess.Popen(run.argv_for(
                "Without using any tools, write a 3,000-word story about a lighthouse keeper."),
                cwd=run.work, env=run.env(), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            generated = 0
            deadline = time.time() + 600
            while time.time() < deadline:
                s = strata_status(upstream)
                generated = s.get("generated") or 0
                if s.get("busy") and s.get("phase") == "answering" and generated >= 40:
                    break
                time.sleep(0.05)
            p.kill()
            t_kill = time.monotonic()
            while True:
                s = strata_status(upstream)
                if not s.get("busy") and not s.get("queued"):
                    break
                if time.monotonic() - t_kill > 120:
                    break
                time.sleep(0.025)
            release = round(time.monotonic() - t_kill, 3)
            out, err = p.communicate(timeout=30)
            run._record("(killed) story", p.returncode, out, err, t0)
            results.append({"trial": n + 1, "generated_before_kill": generated, "release_s": release})
        after = run.omp("Reply with the single word done.")
    finally:
        checks = run.close()
    conn = sqlite3.connect(f"file:{run.db}?mode=ro", uri=True)
    try:
        done_after_cancel = conn.execute(
            "SELECT count(*) FROM events c JOIN events d ON c.attempt_id = d.attempt_id"
            " WHERE c.kind = 'cancelled' AND d.kind = 'turn_complete'").fetchone()[0]
    finally:
        conn.close()
    ok = (first["rc"] == 0 and after["rc"] == 0 and "done" in after["answer"].lower()
          and all(r["release_s"] < 1.0 for r in results) and checks["cancelled"] >= trials
          and done_after_cancel == 0 and checks["sessions"] == [run.session]
          and checks["explain_rc"] == 0 and checks["verify_rc"] == [0])
    return {"scenario": "cancel_chat", "pass": ok, "trials": results,
            "completed_after_cancel": done_after_cancel, "turns": run.turns, "checks": checks}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", nargs="*", default=["smoke", "gate", "restart", "cancel"])
    ap.add_argument("--upstream", default="http://192.168.1.173:8080")
    ap.add_argument("--root", type=Path, default=Path(tempfile.gettempdir()) / "omp-live-smoke")
    ap.add_argument("--gate-budget", type=int, default=16000)
    ap.add_argument("--trials", type=int, default=3)
    args = ap.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    results = []
    for s in args.scenarios:
        wait_idle(args.upstream)
        if s == "smoke":
            results.append(smoke(args.root, args.upstream, "chat"))
        elif s == "gate":
            results.append(gate(args.root, args.upstream, args.gate_budget))
        elif s == "restart":
            results.append(restart(args.root, args.upstream, args.gate_budget))
        elif s == "cancel":
            results.append(cancel(args.root, args.upstream, args.trials))
        (args.root / "summary.json").write_text(json.dumps(results, indent=2, ensure_ascii=False),
                                                encoding="utf-8")
    print(json.dumps([{k: r[k] for k in ("scenario", "pass")} for r in results]))
    return 0 if all(r["pass"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
