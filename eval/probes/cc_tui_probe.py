"""Drive interactive Claude Code (the TUI) through a Windows ConPTY for the HC2 inventory.

Same isolation as cc_probe.py (its ``child_env``: scratch CLAUDE_CONFIG_DIR/HOME, dummy
key, loopback base URL, sentinel proxy unless --no-sentinel). Pre-seeds the scratch
``.claude.json`` so onboarding, the API-key approval and the folder-trust dialogs do not
block, then types a script of inputs with pauses: a prompt, a tool loop, an idle wait,
``/clear``, another prompt, ``/exit``.

Usage (needs pywinpty, Windows only):
    uv run --with pywinpty python eval/probes/cc_tui_probe.py --root C:/ccprobe RUN [--env candidate|default] [--no-sentinel]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cc_probe  # noqa: E402

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[=>()][0-9A-Za-z]?")


def main() -> None:
    from winpty import PtyProcess

    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--root", required=True)
    ap.add_argument("--env", default="candidate", choices=["candidate", "default"])
    ap.add_argument("--no-sentinel", action="store_true")
    ap.add_argument("--idle", type=float, default=90.0)
    a = ap.parse_args()
    run_dir = Path(a.root) / a.run
    if run_dir.exists():
        shutil.rmtree(run_dir)
    work = run_dir / "work"
    work.mkdir(parents=True)
    (work / "hello.txt").write_text("hello from the probe work dir\n", encoding="utf-8")
    log = run_dir / "server.jsonl"
    srv = subprocess.Popen([sys.executable, str(cc_probe.SERVER), "--scenario", "ok", "--port", "0", "--log", str(log)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    url = json.loads(srv.stdout.readline())["listening"]
    sentinel_port, stop_sentinel = (None, None)
    if not a.no_sentinel:
        sentinel_port, stop_sentinel = cc_probe.start_sentinel(run_dir / "sentinel.jsonl")
    spec = {"env": cc_probe.CANDIDATE_ENV if a.env == "candidate" else {}}
    env = cc_probe.child_env(run_dir, f"{url}/s/probe-{a.run}", spec, sentinel_port)
    key = cc_probe.DUMMY_KEY
    cfg = {
        "hasCompletedOnboarding": True, "theme": "dark", "numStartups": 5,
        "customApiKeyResponses": {"approved": [key[-20:]], "rejected": []},
        "projects": {str(work).replace("\\", "/"): {"hasTrustDialogAccepted": True, "hasCompletedProjectOnboarding": True},
                     str(work): {"hasTrustDialogAccepted": True, "hasCompletedProjectOnboarding": True}},
    }
    (run_dir / "config" / ".claude.json").write_text(json.dumps(cfg), encoding="utf-8")
    cmd = [cc_probe.CLAUDE, "--model", cc_probe.MODEL, "--allowedTools", "Bash(echo:*)", "Read"]
    p = PtyProcess.spawn(cmd, cwd=str(work), env=env, dimensions=(50, 160))
    screen = run_dir / "tui.txt"
    out = screen.open("w", encoding="utf-8")
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                data = p.read(4096)
            except EOFError:
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.1)
                continue
            out.write(ANSI.sub("", data))
            out.flush()

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    marks = []

    def mark(label):
        marks.append({"wall": time.time(), "label": label})

    def send(text, pause):
        mark(f"send {text!r}")
        p.write(text)
        time.sleep(0.5)
        p.write("\r")
        time.sleep(pause)

    time.sleep(8)
    mark("started")
    send("Reply with the single word OK.", 8)
    send(cc_probe.PROMPT_TOOL.replace("WORK", str(work).replace("\\", "/")), 10)
    mark("idle start")
    time.sleep(a.idle)
    mark("idle end")
    send("/clear", 5)
    send("After clear. Reply with the single word OK.", 8)
    send("/exit", 6)
    mark("exit sent")
    if p.isalive():
        p.terminate(force=True)
    stop.set()
    srv.terminate()
    if stop_sentinel:
        stop_sentinel()
    sent = run_dir / "sentinel.jsonl"
    meta = {"run": a.run, "env": a.env, "marks": marks, "sentinel_hits": sent.read_text().splitlines() if sent.exists() else []}
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"run": a.run, "sentinel_hits": len(meta["sentinel_hits"])}))


if __name__ == "__main__":
    main()
