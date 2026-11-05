"""Pi through Palimnesis against live Strata (Phase 4B S13): live smoke and transcript gate.

Pi 1.5.0 runs with the shipped adapter (``integrations/pi/``: providers, settings and the
session extension), pointed at a local ``palimnesis serve`` whose upstream is Strata on
pythia (through an SSH tunnel, e.g. ``ssh -N -L 18080:127.0.0.1:8080 pythia``). Isolation as
in ``pi_probe.py``: a throwaway agent directory, home and working folder, ``PI_OFFLINE=1``;
the user's ``~/.pi`` is never read or written.

Scenarios:
- ``smoke`` (per protocol): a tool loop (read a file, answer), then a second turn in the same
  Pi session. Checks: every request archived on the protocol's endpoint, the answer names
  the file's content, ``replay.py --explain`` finds nothing unexplained, and
  ``palimnesis transcripts verify`` passes.
- ``gate`` (Chat, small input budget): four large files are read in turn so the first one
  leaves the view; the first file is then deleted, and a turn asks for a code that only it
  held (answered from history: a proactive excerpt or the transcript, recorded). A last
  turn asks Pi to confirm the code by grepping the transcript directory the a3 addendum
  names. Pass: both answers hold the code, the confirming turn's tool calls name a path
  under the transcript root (D37's capability criterion), ``--explain`` finds nothing
  unexplained and ``transcripts verify`` passes.

    uv run python eval/probes/pi_live_smoke.py --upstream http://127.0.0.1:18080 [smoke|gate ...]

Writes ``<root>/<scenario>/`` (proxy log, archive, transcripts, Pi output) and prints a
JSON summary; fixtures are copied by hand into ``eval/probes/fixtures/pi-1.5.0/live/``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PI_CLI = Path(os.environ.get(
    "PI_CLI",
    Path.home() / ".pi/agent/install/releases/1.5.0/node_modules/@earendil-works/"
    "pi-coding-agent/dist/bundle/cli.js",
))
TOOLS = "read,grep,bash,ls,find"
CODE = "ZX-4471-QUAIL"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Run:
    def __init__(self, root: Path, name: str, upstream: str, protocol: str,
                 input_budget: int | None) -> None:
        self.dir = root / name
        shutil.rmtree(self.dir, ignore_errors=True)
        self.agent, self.home, self.work = (self.dir / "agent", self.dir / "home", self.dir / "work")
        for d in (self.agent, self.home, self.work):
            d.mkdir(parents=True)
        self.protocol = protocol
        self.port = free_port()
        self.db = self.dir / "archive.db"
        self.transcripts = self.dir / "transcripts"
        # The server itself, not a ``uv run`` wrapper: on Windows terminating a wrapper
        # leaves its child serving and holding the archive lock.
        argv = [sys.executable, "-m", "palimnesis", "serve", "--port", str(self.port),
                "--upstream", upstream, "--db", str(self.db), "--transcripts", str(self.transcripts)]
        if input_budget:
            argv += ["--input-budget", str(input_budget)]
        self.log = open(self.dir / "serve.log", "wb")
        self.proxy = subprocess.Popen(argv, cwd=REPO, stdout=self.log, stderr=subprocess.STDOUT)
        self._wait_port()
        self._configure()
        self.turns: list[dict] = []

    def _wait_port(self) -> None:
        end = time.time() + 120
        while time.time() < end:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", self.port)) == 0:
                    return
            time.sleep(0.5)
        raise RuntimeError("palimnesis serve did not start")

    def _configure(self) -> None:
        pi = REPO / "integrations" / "pi"
        models = json.loads((pi / "models.json").read_text(encoding="utf-8"))
        for provider in models["providers"].values():
            provider["baseUrl"] = provider["baseUrl"].replace("127.0.0.1:9000",
                                                              f"127.0.0.1:{self.port}")
        (self.agent / "models.json").write_text(json.dumps(models, indent=2), encoding="utf-8")
        settings = json.loads((pi / "settings.json").read_text(encoding="utf-8"))
        settings.update({"defaultProvider": "palimnesis" if self.protocol == "chat"
                         else "palimnesis-messages", "defaultProjectTrust": "never",
                         "enableInstallTelemetry": False, "quietStartup": True})
        (self.agent / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
        self.extension = self.dir / "palimnesis-session.ts"
        shutil.copy(pi / "extensions" / "palimnesis-session.ts", self.extension)

    def env(self) -> dict:
        e = {k: v for k, v in os.environ.items()
             if not k.startswith(("PI_", "OPENAI", "ANTHROPIC")) and k not in ("HTTP_PROXY", "HTTPS_PROXY")}
        e.update({"PI_CODING_AGENT_DIR": str(self.agent), "HOME": str(self.home),
                  "USERPROFILE": str(self.home), "PI_OFFLINE": "1", "PI_SKIP_VERSION_CHECK": "1",
                  "PI_TELEMETRY": "0", "NO_COLOR": "1"})
        return e

    def pi(self, session: str, prompt: str, timeout: float = 900) -> dict:
        argv = ["node", str(PI_CLI), "-e", str(self.extension), "-nc", "--mode", "json",
                "--tools", TOOLS, "--session-id", session, prompt]
        t0 = time.time()
        p = subprocess.run(argv, cwd=self.work, env=self.env(), stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=timeout)
        n = len(self.turns) + 1
        (self.dir / f"turn{n}.stdout.jsonl").write_bytes(p.stdout)
        (self.dir / f"turn{n}.stderr.txt").write_bytes(p.stderr)
        events = []
        for line in p.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        turn = {"prompt": prompt, "rc": p.returncode, "seconds": round(time.time() - t0, 1),
                "answer": final_text(events), "tool_calls": tool_calls(events)}
        self.turns.append(turn)
        return turn

    def close(self) -> dict:
        """Checks run while the proxy still serves: transcript projection is asynchronous,
        so ``verify`` is retried until the projector has caught up (30 s at most)."""
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
        import sqlite3

        conn = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        try:
            endpoints = [e for (e,) in conn.execute("SELECT endpoint FROM requests")]
            sessions = [s for (s,) in conn.execute("SELECT session_id FROM sessions")]
            failed = [json.loads(p).get("reason") for (p,) in conn.execute(
                "SELECT payload FROM events WHERE kind = 'attempt_failed'")]
            views = conn.execute("SELECT count(*) FROM view_versions").fetchone()[0]
            excerpts = conn.execute("SELECT rendered FROM excerpt_blocks WHERE status = 'selected'"
                                    ).fetchall()
        finally:
            conn.close()
        explain = subprocess.run(["uv", "run", "python", "eval/replay.py", "--explain",
                                  str(self.db), "--json"], cwd=REPO, capture_output=True, text=True)
        (self.dir / "explain.json").write_text(explain.stdout, encoding="utf-8")
        verify = [subprocess.run(["uv", "run", "palimnesis", "transcripts", "verify", s,
                                  "--db", str(self.db), "--root", str(self.transcripts)],
                                 cwd=REPO, capture_output=True, text=True) for s in sessions]
        return {"requests": len(endpoints), "endpoints": sorted(set(endpoints)),
                "sessions": sessions, "attempts_failed": failed, "view_versions": views,
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
    out = []
    for e in events:
        if e.get("type") == "tool_execution_start":
            out.append({"tool": e.get("toolName"), "args": e.get("args")})
    return out


def smoke(root: Path, upstream: str, protocol: str) -> dict:
    run = Run(root, f"smoke_{protocol}", upstream, protocol, None)
    (run.work / "notes.txt").write_text("The release train leaves on Thursday.\n", encoding="utf-8")
    session = f"pal-smoke-{protocol}"
    try:
        first = run.pi(session, "Read notes.txt and tell me in one sentence what it says.")
        second = run.pi(session, "Which day was that? Answer with one word.")
    finally:
        checks = run.close()
    ok = (first["rc"] == 0 and second["rc"] == 0 and "thursday" in first["answer"].lower()
          and "thursday" in second["answer"].lower()
          and checks["endpoints"] == [("/v1/chat/completions" if protocol == "chat" else "/v1/messages")]
          and checks["sessions"] == [session] and checks["explain_rc"] == 0
          and checks["verify_rc"] == [0] and any(c["tool"] == "read" for c in first["tool_calls"]))
    return {"scenario": f"smoke_{protocol}", "pass": ok, "turns": run.turns, "checks": checks}


def filler(i: int, lines: int = 220) -> str:
    return "\n".join(f"record {i}-{n}: sensor {n % 17} reading {(n * 37 + i) % 1000} units, "
                     f"status nominal, batch {i * 1000 + n}" for n in range(lines))


def gate(root: Path, upstream: str, budget: int) -> dict:
    run = Run(root, "gate_chat", upstream, "chat", budget)
    for i in range(1, 5):
        body = filler(i)
        if i == 1:
            lines = body.split("\n")
            lines.insert(97, f"NOTE: the deploy code for this release is {CODE}.")
            body = "\n".join(lines)
        (run.work / f"log{i}.txt").write_text(body + "\n", encoding="utf-8")
    session = "pal-gate-chat"
    try:
        for i in range(1, 5):
            run.pi(session, f"Read log{i}.txt in full and reply with its line count only.")
        (run.work / "log1.txt").unlink()  # the code now exists only in the archive
        last = run.pi(session, "What is the deploy code that log1.txt mentioned? log1.txt has "
                               "been deleted; find it in this conversation's history. "
                               "Reply with the code only.")
        # The capability gate (D37's criterion): Pi's own tools reach the transcript
        # directory the a3 addendum names, through the proxy, with no prompt.
        confirm = run.pi(session, "Confirm that code from the exact transcript of this "
                                  "conversation: grep the transcript directory named in your "
                                  "instructions for ZX- and quote the matching line.")
    finally:
        checks = run.close()
    root_str = str(run.transcripts).replace("\\", "/").lower()
    used = [c for c in confirm["tool_calls"]
            if root_str in json.dumps(c["args"]).replace("\\\\", "/").lower()]
    return {"scenario": "gate_chat",
            "pass": (CODE in last["answer"] and CODE in confirm["answer"] and bool(used)
                     and checks["explain_rc"] == 0 and checks["verify_rc"] == [0]),
            "answer_via_excerpt": checks["excerpts_with_code"] > 0,
            "transcript_calls": used, "turns": run.turns, "checks": checks}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", nargs="*", default=["smoke", "gate"])
    ap.add_argument("--upstream", default="http://127.0.0.1:18080")
    ap.add_argument("--root", type=Path, default=Path(tempfile.gettempdir()) / "pi-live-smoke")
    ap.add_argument("--gate-budget", type=int, default=8000)
    args = ap.parse_args()
    results = []
    for s in args.scenarios:
        if s == "smoke":
            results += [smoke(args.root, args.upstream, p) for p in ("chat", "messages")]
        elif s == "gate":
            results.append(gate(args.root, args.upstream, args.gate_budget))
    print(json.dumps(results, indent=2, ensure_ascii=False))
    (args.root / "summary.json").write_text(json.dumps(results, indent=2, ensure_ascii=False),
                                            encoding="utf-8")
    return 0 if all(r["pass"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
