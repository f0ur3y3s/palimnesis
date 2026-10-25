"""Drive OpenCode 2.1.4 against opencode_fault_server.py and save fixtures.

Each run gets its own throwaway OpenCode home (XDG config/data/cache/state, USERPROFILE,
OPENCODE_TEST_HOME, OPENCODE_CONFIG_DIR) under --root, so the user's ~/.config/opencode
and existing OpenCode state are never read or written. ``opencode run --standalone``
starts a private server child instead of attaching to a managed background service.

Usage:
    uv run python eval/probes/opencode_fault_probe.py --root SCRATCH/opencode-retry RUN [RUN ...]
    uv run python eval/probes/opencode_fault_probe.py --list

A RUN is a name from RUNS below (scenario + config overrides + optional plugin/proxy).
Output: eval/fixtures/opencode-2.1.4/faults/<RUN>/ (server.jsonl, opencode.stdout.txt,
opencode.stderr.txt, opencode.json, meta.json, opencode.log when present).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "eval" / "probes" / "opencode_fault_server.py"
FIXTURES = REPO / "eval" / "fixtures" / "opencode-2.1.4" / "faults"
PROMPT = "Reply with the single word OK."
KILL_AFTER_S = 150

RETRY_OFF_PLUGIN = """\
// Session retry hook: veto every automatic retry/continuation decision.
export default {
  id: "palimnesis-retry-off",
  setup: async (ctx) => {
    await ctx.session.hook("retry", (event) => {
      console.error(`[palimnesis-retry-off] attempt=${event.attempt} decision=${JSON.stringify(event.decision)} error=${JSON.stringify(event.error)}`)
      event.decision = { retry: false }
    })
  },
}
"""

# name -> scenario, provider option overrides, extras
RUNS: dict[str, dict] = {
    "ok": {"scenario": "ok"},
    "ok_proxy": {"scenario": "ok", "proxy": True},
    "s500": {"scenario": "s500"},
    "s502": {"scenario": "s502"},
    "s503": {"scenario": "s503"},
    "s503_then_ok": {"scenario": "s503_then_ok"},
    "s429_ra2": {"scenario": "s429_ra2"},
    "s429": {"scenario": "s429"},
    "s429_noretry": {"scenario": "s429_noretry"},
    "s500_noretry": {"scenario": "s500_noretry"},
    "s400": {"scenario": "s400"},
    "role_only_eof": {"scenario": "role_only_eof"},
    "role_only_eof_noretry": {"scenario": "role_only_eof_noretry"},
    "role_only_abort": {"scenario": "role_only_abort"},
    "role_only_abort_noretry": {"scenario": "role_only_abort_noretry"},
    "partial_eof": {"scenario": "partial_eof"},
    "partial_eof_then_ok": {"scenario": "partial_eof_then_ok"},
    "partial_abort_then_ok": {"scenario": "partial_abort_then_ok"},
    "partial_eof_noretry": {"scenario": "partial_eof_noretry"},
    "partial_reasoning_then_ok": {"scenario": "partial_reasoning_then_ok"},
    "reasoning_only_then_ok": {"scenario": "reasoning_only_then_ok"},
    "finish_no_done": {"scenario": "finish_no_done"},
    "done_no_finish": {"scenario": "done_no_finish"},
    "header_timeout5s": {
        "scenario": "header_delay8",
        "options": {"headerTimeout": 5000},
    },
    "header_delay8_default": {"scenario": "header_delay8"},
    "chunk_timeout5s_idle_role": {
        "scenario": "idle_after_role",
        "options": {"chunkTimeout": 5000},
    },
    "chunk_timeout5s_idle_role_then_ok": {
        "scenario": "idle_after_role_then_ok",
        "options": {"chunkTimeout": 5000},
    },
    "chunk_timeout5s_idle_text_then_ok": {
        "scenario": "idle_after_text_then_ok",
        "options": {"chunkTimeout": 5000},
    },
    "chunk_timeout5s_keepalive": {
        "scenario": "keepalive_comments",
        "options": {"chunkTimeout": 5000},
    },
    "chunk_timeout5s_keepalive_after_role": {
        "scenario": "keepalive_after_role",
        "options": {"chunkTimeout": 5000},
    },
    "chunk_timeout5s_keepalive_proxy": {
        "scenario": "keepalive_comments",
        "options": {"chunkTimeout": 5000},
        "proxy": True,
    },
    "total_timeout10s_keepalive": {
        "scenario": "keepalive_comments",
        "options": {"timeout": 10000},
    },
    "length": {"scenario": "length"},
    "plugin_retry_off_s500": {"scenario": "s500", "plugin": True},
    "plugin_retry_off_partial_eof": {"scenario": "partial_eof_then_ok", "plugin": True},
    "s500_proxy": {"scenario": "s500", "proxy": True},
    "partial_abort_then_ok_proxy": {"scenario": "partial_abort_then_ok", "proxy": True},
    "s409": {"scenario": "s409"},
    "s409_noretry": {"scenario": "s409_noretry"},
    "s429_ra15_then_ok": {"scenario": "s429_ra15_then_ok"},
    "s503_ra12_then_ok": {"scenario": "s503_ra12_then_ok"},
    "s429_ram9000_then_ok": {"scenario": "s429_ram9000_then_ok"},
    "error_event_then_ok": {"scenario": "error_event_then_ok"},
    "error_event_noretry": {"scenario": "error_event_noretry"},
    "partial_error_event_then_ok": {"scenario": "partial_error_event_then_ok"},
    "partial_finish_error_then_ok": {"scenario": "partial_finish_error_then_ok"},
    "partial_error_event_noretry": {"scenario": "partial_error_event_noretry"},
    "chunk_timeout5s_idle_role_noretry": {
        "scenario": "idle_after_role_noretry_then_ok",
        "options": {"chunkTimeout": 5000},
    },
}


def _config(base_url: str, options: dict) -> dict:
    return {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "fault": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Fault server",
                "options": {"baseURL": base_url, "apiKey": "fault-no-key", **options},
                "models": {
                    "m": {
                        "name": "fault-model",
                        "limit": {"context": 32768, "output": 1024},
                    }
                },
            }
        },
        "model": "fault/m",
        "compaction": {"auto": False},
        "agents": {"title": {"disabled": True}},
        "permissions": [{"action": "subagent", "resource": "*", "effect": "deny"}],
        "snapshot": False,
        "autoupdate": False,
        "share": "disabled",
    }


def isolated_env(home: Path) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("OPENCODE") and not k.startswith("XDG_")
    }
    env.update(
        {
            # `opencode run` takes its session directory from PWD before cwd (cli/src/run/run.ts);
            # a PWD inherited from a POSIX shell would point the session at the caller's checkout.
            "PWD": str(home / "work"),
            "XDG_CONFIG_HOME": str(home / "xdg-config"),
            "XDG_DATA_HOME": str(home / "xdg-data"),
            "XDG_CACHE_HOME": str(home / "xdg-cache"),
            "XDG_STATE_HOME": str(home / "xdg-state"),
            "OPENCODE_CONFIG_DIR": str(home / "xdg-config" / "opencode"),
            "OPENCODE_TEST_HOME": str(home / "home"),
            "USERPROFILE": str(home / "home"),
            "HOME": str(home / "home"),
            "TEMP": str(home / "tmp"),
            "TMP": str(home / "tmp"),
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
            "OPENCODE_DISABLE_AUTOUPDATE": "1",
            "OPENCODE_DISABLE_CLAUDE_CODE": "1",
            "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
            "OPENCODE_DISABLE_FREE_MODELS": "1",
            "OPENCODE_DISABLE_FILEWATCHER": "1",
            "OPENCODE_LOG_LEVEL": "DEBUG",
        }
    )
    return env


def _wait_http(url: str, deadline_s: float = 20) -> None:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except urllib.error.HTTPError:
            return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"{url} did not come up")


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )


def run_one(name: str, root: Path, port: int) -> dict:
    spec = RUNS[name]
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

    server_log = out / "server.jsonl"
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
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    proxy = None
    upstream = f"http://127.0.0.1:{port}"
    base_url = f"{upstream}/v1"
    procs = [server]
    try:
        _wait_http(upstream + "/health")
        if spec.get("proxy"):
            pport = port + 1000
            proxy = subprocess.Popen(
                [
                    "uv",
                    "run",
                    "palimnesis",
                    "serve",
                    "--upstream",
                    upstream,
                    "--port",
                    str(pport),
                ],
                cwd=REPO,
                stdout=(out / "proxy.log").open("w"),
                stderr=subprocess.STDOUT,
            )
            procs.append(proxy)
            _wait_http(f"http://127.0.0.1:{pport}/s/probe/health")
            base_url = f"http://127.0.0.1:{pport}/s/fault-{name.replace('_', '-')}/v1"

        config = _config(base_url, spec.get("options", {}))
        cfg_dir = home / "xdg-config" / "opencode"
        (cfg_dir / "opencode.json").write_text(
            json.dumps(config, indent=2), encoding="utf-8"
        )
        shutil.copy(cfg_dir / "opencode.json", out / "opencode.json")
        if spec.get("plugin"):
            (cfg_dir / "plugins").mkdir()
            (cfg_dir / "plugins" / "retry-off.js").write_text(
                RETRY_OFF_PLUGIN, encoding="utf-8"
            )
            shutil.copy(cfg_dir / "plugins" / "retry-off.js", out / "retry-off.js")

        env = isolated_env(home)
        cmd = ["opencode", "run", "--standalone", "-m", "fault/m", PROMPT]
        started = time.time()
        oc = subprocess.Popen(
            subprocess.list2cmdline(cmd),
            shell=True,
            cwd=home / "work",
            env=env,
            # `opencode run` reads stdin to EOF when it is not a TTY (cli/src/run/run.ts).
            stdin=subprocess.DEVNULL,
            stdout=(out / "opencode.stdout.txt").open("wb"),
            stderr=(out / "opencode.stderr.txt").open("wb"),
        )
        killed = False
        try:
            rc = oc.wait(timeout=KILL_AFTER_S)
        except subprocess.TimeoutExpired:
            _kill_tree(oc)
            killed = True
            rc = oc.wait()
        elapsed = round(time.time() - started, 2)
        time.sleep(1)
    finally:
        for p in procs:
            _kill_tree(p)

    logs = sorted((home / "xdg-data" / "opencode" / "log").glob("*.log"))
    if logs:
        text = b"".join(p.read_bytes() for p in logs)
        (out / "opencode.log").write_bytes(text[-2_000_000:])
    meta = {
        "run": name,
        "scenario": spec["scenario"],
        "options": spec.get("options", {}),
        "plugin_retry_off": bool(spec.get("plugin")),
        "via_proxy": bool(spec.get("proxy")),
        "base_url": base_url,
        "command": cmd,
        "exit_code": rc,
        "killed_after_s": KILL_AFTER_S if killed else None,
        "elapsed_s": elapsed,
        "started_wall": started,
        "isolated_home": str(home),
        "written_paths": sorted(
            str(p.relative_to(home))
            for p in home.rglob("*")
            if p.is_dir()
            and p.parent.name
            in ("xdg-config", "xdg-data", "xdg-cache", "xdg-state", "home")
        ),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("runs", nargs="*")
    p.add_argument("--root", required=False)
    p.add_argument("--port", type=int, default=18500)
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
                    k: meta[k]
                    for k in ("run", "exit_code", "elapsed_s", "killed_after_s")
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
