"""Probe what OpenCode 2.1.4 sends on the turn AFTER a stream that ended with partial output.

Each run: one throwaway OpenCode home, one fault server scenario whose first attempt
fails after partial output (every later attempt gets a normal answer), then

    turn 1: opencode run --standalone -m <model> "<TURN1>"
    turn 2: opencode run --standalone -m <model> --session <id> "<TURN2>"

The session id is read from the ``x-opencode-session-id`` header of turn 1's first request.
The fault server writes each request body's exact bytes to ``req-NN.json``.

Configs:
    v2  the shipped integrations/opencode/opencode.json (providers.mnemon, reasoningField
        reasoning_content) plus plugins/mnemon.ts, with MNEMON_PROXY_ORIGIN pointed at the
        fault server, so requests go to /s/<sessionID>/v1 exactly as with Mnemon.
    v1  the opencode_fault_probe.py config (provider "fault", no reasoningField).

Usage:
    uv run python eval/probes/opencode_partials_probe.py --root SCRATCH/opencode-partials RUN [RUN ...]
    uv run python eval/probes/opencode_partials_probe.py --list

Output: eval/fixtures/opencode-2.1.4/partials/<RUN>/ (req-NN.json, requests.jsonl,
events.jsonl, turnN.stdout.txt, turnN.stderr.txt, opencode.json, meta.json).
Never point this at a real model server.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from opencode_fault_probe import _config as v1_config
from opencode_fault_probe import _kill_tree, _wait_http, isolated_env

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "eval" / "probes" / "opencode_fault_server.py"
FIXTURES = REPO / "eval" / "fixtures" / "opencode-2.1.4" / "partials"
INTEGRATION = REPO / "integrations" / "opencode"
OPENCODE_EXE = (
    Path.home() / "AppData/Roaming/npm/node_modules/@opencode/cli/bin/opencode.exe"
)
TURN1 = "First question: what is 2+2?"
TURN2 = "Next question: what is 3+3?"
KILL_AFTER_S = 150

RUNS: dict[str, dict] = {
    "A_reason_text_err_noretry": {"scenario": "pp_reason_text_err_noretry"},
    "A_reason_text_err_noretry_v1": {
        "scenario": "pp_reason_text_err_noretry",
        "config": "v1",
    },
    "A2_reason_err_noretry": {"scenario": "pp_reason_err_noretry"},
    "A3_ws_reason_text_err_noretry": {"scenario": "pp_ws_reason_text_err_noretry"},
    "B_text_err_noretry": {"scenario": "pp_text_err_noretry"},
    "Z2_control_ws_reason_text_ok": {"scenario": "pp_ws_reason_text_ok"},
    "D3_ws_reason_text_eof": {"scenario": "pp_ws_reason_text_eof"},
    "Z_control_reason_text_ok": {"scenario": "pp_reason_text_ok"},
    "C_text_eof_noretry": {"scenario": "pp_text_eof_noretry"},
    "D_text_eof": {"scenario": "pp_text_eof"},
    "D2_reason_text_eof": {"scenario": "pp_reason_text_eof"},
    "D2_reason_text_eof_v1": {"scenario": "pp_reason_text_eof", "config": "v1"},
    "E_tool_err_noretry": {"scenario": "pp_tool_err_noretry"},
    "E2_reason_text_tool_err_noretry": {"scenario": "pp_reason_text_tool_err_noretry"},
    "E3_tool_eof": {"scenario": "pp_tool_eof"},
}


def _run_opencode(cmd: list[str], home: Path, env: dict, out: Path, tag: str) -> dict:
    started = time.time()
    oc = subprocess.Popen(
        cmd,
        cwd=home / "work",
        env=env,
        # `opencode run` reads stdin to EOF when it is not a TTY (cli/src/run/run.ts).
        stdin=subprocess.DEVNULL,
        stdout=(out / f"{tag}.stdout.txt").open("wb"),
        stderr=(out / f"{tag}.stderr.txt").open("wb"),
    )
    killed = False
    try:
        rc = oc.wait(timeout=KILL_AFTER_S)
    except subprocess.TimeoutExpired:
        _kill_tree(oc)
        killed = True
        rc = oc.wait()
    return {
        "command": [Path(cmd[0]).name, *cmd[1:]],
        "exit_code": rc,
        "killed": killed,
        "elapsed_s": round(time.time() - started, 2),
    }


def _requests(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [
        r
        for r in map(json.loads, log.read_text(encoding="utf-8").splitlines())
        if r.get("event") == "request"
    ]


def run_one(name: str, root: Path, port: int) -> dict:
    spec = RUNS[name]
    cfg_kind = spec.get("config", "v2")
    home = root / "runs" / name
    if home.exists():
        shutil.rmtree(home)
    for sub in (
        "xdg-config/opencode",
        "xdg-data",
        "xdg-cache",
        "xdg-state",
        "home",
        "work",
        "tmp",
    ):
        (home / sub).mkdir(parents=True, exist_ok=True)
    out = FIXTURES / name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    server_log = home / "server.jsonl"
    origin = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [
            sys.executable,
            str(SERVER),
            "--scenario",
            spec["scenario"],
            "--port",
            str(port),
            "--log",
            str(server_log),
            "--raw-dir",
            str(out),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    cfg_dir = home / "xdg-config" / "opencode"
    env = isolated_env(home)
    if cfg_kind == "v2":
        config = json.loads((INTEGRATION / "opencode.json").read_text(encoding="utf-8"))
        config["providers"]["mnemon"]["settings"]["baseURL"] = f"{origin}/v1"
        config.update({"share": "disabled", "update": "disable"})
        (cfg_dir / "plugins").mkdir()
        shutil.copy(INTEGRATION / "plugins" / "mnemon.ts", cfg_dir / "plugins")
        env["MNEMON_PROXY_ORIGIN"] = origin
        model = config["model"]
    else:
        config = v1_config(f"{origin}/v1", {})
        model = "fault/m"
    (cfg_dir / "opencode.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )
    shutil.copy(cfg_dir / "opencode.json", out / "opencode.json")

    turns = []
    try:
        _wait_http(origin + "/health")
        exe = str(OPENCODE_EXE)
        turns.append(
            _run_opencode(
                [exe, "run", "--standalone", "-m", model, TURN1],
                home,
                env,
                out,
                "turn1",
            )
        )
        time.sleep(1)
        reqs = _requests(server_log)
        n_turn1 = len(reqs)
        session = None
        chat = [r for r in reqs if r.get("attempt") is not None]
        if chat:
            hdrs = {k.lower(): v for k, v in chat[0]["headers"]}
            session = hdrs.get("x-opencode-session-id")
        if session:
            turns.append(
                _run_opencode(
                    [
                        exe,
                        "run",
                        "--standalone",
                        "-m",
                        model,
                        "--session",
                        session,
                        TURN2,
                    ],
                    home,
                    env,
                    out,
                    "turn2",
                )
            )
            time.sleep(1)
    finally:
        _kill_tree(server)

    # Split the server log: request index (headers, no body; body bytes are in req-NN.json)
    # and response/connection events.
    with (
        (out / "requests.jsonl").open("w", encoding="utf-8") as rf,
        (out / "events.jsonl").open("w", encoding="utf-8") as ef,
    ):
        for line in server_log.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("event") == "request":
                r["turn"] = 1 if r["seq"] <= n_turn1 else 2
                r.pop("body", None)
                rf.write(json.dumps(r, ensure_ascii=False) + "\n")
            else:
                ef.write(line + "\n")
    meta = {
        "run": name,
        "scenario": spec["scenario"],
        "config": cfg_kind,
        "model": model,
        "session_id": session,
        "turn1_requests": n_turn1,
        "turns": turns,
        "prompts": [TURN1, TURN2],
        "isolated_home": str(home),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("runs", nargs="*")
    p.add_argument("--root")
    p.add_argument("--port", type=int, default=18700)
    p.add_argument("--list", action="store_true")
    args = p.parse_args()
    if args.list:
        for k, v in RUNS.items():
            print(k, v)
        return
    root = Path(args.root)
    for i, name in enumerate(args.runs):
        meta = run_one(name, root, args.port + i)
        print(
            json.dumps(
                {
                    "run": name,
                    "turn1_requests": meta["turn1_requests"],
                    "turns": [
                        (t["exit_code"], t["elapsed_s"], t["killed"])
                        for t in meta["turns"]
                    ],
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
