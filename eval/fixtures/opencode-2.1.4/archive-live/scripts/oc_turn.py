"""Run one isolated `opencode run --standalone` turn (env mirrors Phase 0 env.sh).

--kill-after-first-data TAPLOG DELAY: kill the opencode process tree DELAY seconds
after a new `first_data` event appears in the proxy tap log (client-side interrupt).
"""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(r"C:\Users\Daniel\AppData\Local\Temp\claude\C--Users-Daniel-repos-mnemon"
            r"\fac1bd63-de12-4fc2-8f3c-959c6d0d6c76\scratchpad\opencode-archive")
EXE = Path(os.environ["APPDATA"]) / "npm/node_modules/@opencode/cli/bin/opencode.exe"


def env():
    e = {k: v for k, v in os.environ.items()
         if not k.startswith("OPENCODE") and not k.startswith("XDG_")}
    e.update({
        "HOME": str(ROOT / "home"), "USERPROFILE": str(ROOT / "home"),
        "OPENCODE_TEST_HOME": str(ROOT / "home"),
        "OPENCODE_CONFIG_DIR": str(ROOT / "config"),
        "XDG_CONFIG_HOME": str(ROOT / "xdg/config"), "XDG_DATA_HOME": str(ROOT / "xdg/data"),
        "XDG_CACHE_HOME": str(ROOT / "xdg/cache"), "XDG_STATE_HOME": str(ROOT / "xdg/state"),
        "OPENCODE_DISABLE_PROJECT_CONFIG": "true", "OPENCODE_DISABLE_CLAUDE_CODE": "true",
        "OPENCODE_DISABLE_MODELS_FETCH": "true", "OPENCODE_DISABLE_AUTOUPDATE": "true",
        "OPENCODE_DISABLE_FILEWATCHER": "true",
        "MNEMON_PROXY_ORIGIN": "http://127.0.0.1:9031",
        "MNEMON_PLUGIN_LOG": str(ROOT / "logs/plugin.jsonl"),
        "TEMP": str(ROOT / "tmp"), "TMP": str(ROOT / "tmp"),
        "PWD": str(ROOT / "work"),
    })
    return e


def first_data_events(log: Path):
    if not log.exists():
        return []
    return [r for r in map(json.loads, log.read_text("utf-8").splitlines())
            if r.get("event") == "first_data"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--label", required=True)
    p.add_argument("--session")
    p.add_argument("--kill-after-first-data", nargs=2, metavar=("TAPLOG", "DELAY"))
    p.add_argument("--timeout", type=float, default=900)
    p.add_argument("message")
    a = p.parse_args()
    cmd = [str(EXE), "run", "--standalone", "--auto", "--format", "json"]
    if a.session:
        cmd += ["--session", a.session]
    cmd.append(a.message)
    out = ROOT / "logs"
    meta = {"label": a.label, "command": ["opencode.exe", *cmd[1:]], "started": time.time()}
    seen = len(first_data_events(Path(a.kill_after_first_data[0]))) if a.kill_after_first_data else 0
    oc = subprocess.Popen(cmd, cwd=ROOT / "work", env=env(), stdin=subprocess.DEVNULL,
                          stdout=(out / f"{a.label}.stdout.jsonl").open("wb"),
                          stderr=(out / f"{a.label}.stderr.txt").open("wb"))
    killed = False
    deadline = time.time() + a.timeout
    while oc.poll() is None and time.time() < deadline:
        if a.kill_after_first_data and not killed:
            evs = first_data_events(Path(a.kill_after_first_data[0]))
            if len(evs) > seen:
                meta["first_data_seen"] = evs[seen]["t"]
                time.sleep(float(a.kill_after_first_data[1]))
                meta["kill_at"] = time.time()
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(oc.pid)],
                               capture_output=True, check=False)
                killed = True
        time.sleep(0.05)
    if oc.poll() is None:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(oc.pid)], capture_output=True)
        meta["timeout_killed"] = True
    meta.update(exit_code=oc.wait(), killed=killed, ended=time.time())
    meta["elapsed_s"] = round(meta["ended"] - meta["started"], 2)
    (out / f"{a.label}.meta.json").write_text(json.dumps(meta, indent=2), "utf-8")
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
