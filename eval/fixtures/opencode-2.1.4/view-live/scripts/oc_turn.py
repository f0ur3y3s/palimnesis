"""Run one isolated `opencode run --standalone` turn (environment as Phase 0 env.sh).

Same isolation as the R9/R10 runs (`../archive-live/scripts/oc_turn.py`): isolated
HOME, XDG, TEMP and OpenCode config directories, `OPENCODE_DISABLE_PROJECT_CONFIG`,
`PWD` set to a throwaway git repo under OC_ROOT/work and stdin at EOF. The process
tree is killed at the timeout so no request is left running upstream.

Environment: OC_ROOT (required), OC_PROXY_ORIGIN (default http://127.0.0.1:9041).
"""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(os.environ["OC_ROOT"])
PROXY_ORIGIN = os.environ.get("OC_PROXY_ORIGIN", "http://127.0.0.1:9041")
EXE = Path(os.environ["APPDATA"]) / "npm/node_modules/@opencode/cli/bin/opencode.exe"


def env():
    e = {k: v for k, v in os.environ.items()
         if not k.startswith(("OPENCODE", "XDG_", "MNEMON", "PALIMNESIS"))}
    e.update({
        "HOME": str(ROOT / "home"), "USERPROFILE": str(ROOT / "home"),
        "OPENCODE_TEST_HOME": str(ROOT / "home"),
        "OPENCODE_CONFIG_DIR": str(ROOT / "config"),
        "XDG_CONFIG_HOME": str(ROOT / "xdg/config"), "XDG_DATA_HOME": str(ROOT / "xdg/data"),
        "XDG_CACHE_HOME": str(ROOT / "xdg/cache"), "XDG_STATE_HOME": str(ROOT / "xdg/state"),
        "OPENCODE_DISABLE_PROJECT_CONFIG": "true", "OPENCODE_DISABLE_CLAUDE_CODE": "true",
        "OPENCODE_DISABLE_MODELS_FETCH": "true", "OPENCODE_DISABLE_AUTOUPDATE": "true",
        "OPENCODE_DISABLE_FILEWATCHER": "true",
        "PALIMNESIS_PROXY_ORIGIN": PROXY_ORIGIN,
        "PALIMNESIS_PLUGIN_LOG": str(ROOT / "logs/plugin.jsonl"),
        "TEMP": str(ROOT / "tmp"), "TMP": str(ROOT / "tmp"),
        "PWD": str(ROOT / "work"),
    })
    return e


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--label", required=True)
    p.add_argument("--session")
    p.add_argument("--timeout", type=float, default=900)
    p.add_argument("message")
    a = p.parse_args()
    cmd = [str(EXE), "run", "--standalone", "--auto", "--format", "json"]
    if a.session:
        cmd += ["--session", a.session]
    cmd.append(a.message)
    out = ROOT / "logs"
    meta = {"label": a.label, "command": ["opencode.exe", *cmd[1:]], "started": time.time()}
    oc = subprocess.Popen(cmd, cwd=ROOT / "work", env=env(), stdin=subprocess.DEVNULL,
                          stdout=(out / f"{a.label}.stdout.jsonl").open("wb"),
                          stderr=(out / f"{a.label}.stderr.txt").open("wb"))
    deadline = time.time() + a.timeout
    while oc.poll() is None and time.time() < deadline:
        time.sleep(0.05)
    if oc.poll() is None:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(oc.pid)], capture_output=True)
        meta["timeout_killed"] = True
    meta.update(exit_code=oc.wait(), ended=time.time())
    meta["elapsed_s"] = round(meta["ended"] - meta["started"], 2)
    (out / f"{a.label}.meta.json").write_text(json.dumps(meta, indent=2), "utf-8")
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
