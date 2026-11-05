"""Drive Claude Code against cc_fault_server.py in an isolated profile and save fixtures.

Isolation (every run): the child gets an environment built from a short allowlist of OS
variables, never the caller's (so no CLAUDECODE / CLAUDE_CODE_* / messaging-socket
variables leak in). It sets:

- ``CLAUDE_CONFIG_DIR``, ``HOME``, ``USERPROFILE``, ``APPDATA``, ``LOCALAPPDATA``,
  ``TEMP``/``TMP`` to folders under the run directory, so the user's ``~/.claude``,
  ``~/.claude.json`` and credentials are never read or written;
- ``ANTHROPIC_API_KEY`` to a dummy value and ``ANTHROPIC_BASE_URL`` to the loopback fault
  server (path prefix ``/s/<session>``);
- the non-essential-traffic switches (``CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC``,
  ``DISABLE_TELEMETRY``, ``DISABLE_ERROR_REPORTING``, ``DISABLE_AUTOUPDATER``,
  ``DISABLE_GROWTHBOOK``);
- unless a run sets ``"no_sentinel": True``, ``HTTP(S)_PROXY`` to a local sentinel that
  logs and refuses every proxied request (``NO_PROXY`` covers loopback), so any attempt
  to reach a non-loopback host is recorded in ``sentinel.jsonl`` and fails.

The working directory is ``<run>/work`` (outside the repo). stdin is closed unless the
run feeds stream-json input.

Usage:
    uv run python eval/probes/cc_probe.py --root SCRATCH RUN [RUN ...]
    uv run python eval/probes/cc_probe.py --list

Output: ``<root>/<run>/`` (server.jsonl, sentinel.jsonl, claude.<i>.stdout.jsonl,
claude.<i>.stderr.txt, meta.json, config/ including transcripts). ``--fixtures`` also
copies a sanitized ``server.jsonl`` and ``meta.json`` to
``eval/probes/fixtures/claude-code-2.1.318/<run>/`` (credentials already redacted by the
server; user paths and ``metadata.user_id`` device/account ids redacted; with
``--slim``, system and tools replaced by their sha256 and size after the first request).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "eval" / "probes" / "cc_fault_server.py"
FIXTURES = REPO / "eval" / "probes" / "fixtures" / "claude-code-2.1.318"
CLAUDE = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude.exe")
MODEL = "qwen3.8-27b"
DUMMY_KEY = "sk-ant-dummy-palimnesis-probe-0000"

OS_KEEP = ["SystemRoot", "SYSTEMROOT", "SystemDrive", "windir", "COMSPEC", "PATHEXT", "PATH",
           "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS", "ProgramFiles",
           "ProgramFiles(x86)", "ProgramW6432", "CommonProgramFiles", "ProgramData", "LANG"]

SAFE_ENV = {
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "DISABLE_AUTOUPDATER": "1",
    "DISABLE_GROWTHBOOK": "1",
    # Added after the 2026-11-05 runs: interactive startup tried CONNECT downloads.claude.ai
    # and github.com (refused by the sentinel). Name from the 2.1.318 bundle; effect unverified.
    "CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL": "1",
}

# The candidate Palimnesis env from phase4b / harnesses.md (side calls and betas off).
CANDIDATE_ENV = {
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
    "CLAUDE_CODE_ATTRIBUTION_HEADER": "0",
    "CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK": "1",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "32768",
    "DISABLE_AUTO_COMPACT": "1",
    "CLAUDE_CODE_DISABLE_TERMINAL_TITLE": "1",
    "CLAUDE_CODE_ENABLE_AWAY_SUMMARY": "0",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    "CLAUDE_CODE_FORK_SUBAGENT": "0",
    "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
    "CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION": "false",
}

PROMPT_OK = "Reply with the single word OK."
PROMPT_TOOL = 'List the files. @@tool Bash {"command": "echo probe-bash-ok", "description": "echo"} @@tool Read {"file_path": "WORK/hello.txt"}'
ALLOW_TOOL = ["--allowedTools", "Bash(echo:*)", "Read"]
# Tools Palimnesis does not need (subagents, scheduling, worktrees, web, notebooks).
TRIM_TOOLS = ["Agent", "ListAgents", "SendMessage", "Workflow", "Monitor", "CronCreate", "CronDelete",
              "CronList", "ScheduleWakeup", "EnterWorktree", "ExitWorktree", "ReportFindings",
              "NotebookEdit", "TaskStop", "WebFetch", "WebSearch", "Skill"]

# name -> spec. Keys: scenario, server (extra server args), env, invocations
# [{prompt, args, stdin: [(delay_s, text), ...], idle_after: s}], timeout, settings, no_sentinel
RUNS: dict[str, dict] = {
    # HC1/HC2/HC3: default env (only the safety switches), one turn and a tool loop
    "default_ok": {"invocations": [{"prompt": PROMPT_OK}]},
    "default_tool": {"invocations": [{"prompt": PROMPT_TOOL, "args": ALLOW_TOOL}]},
    "default_ok_nosentinel": {"no_sentinel": True, "invocations": [{"prompt": PROMPT_OK}]},
    "default_ok_hello200_ct200_models": {"server": ["--hello-status", "200", "--count-tokens", "200", "--models", "200"],
                                         "env": {"CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1"}, "no_sentinel": True,
                                         "invocations": [{"prompt": PROMPT_OK}]},
    "candidate_ok": {"env": CANDIDATE_ENV, "invocations": [{"prompt": PROMPT_OK}]},
    "candidate_tool": {"env": CANDIDATE_ENV, "invocations": [{"prompt": PROMPT_TOOL, "args": ALLOW_TOOL}]},
    "candidate_attr_on": {"env": {**CANDIDATE_ENV, "CLAUDE_CODE_ATTRIBUTION_HEADER": "1"}, "invocations": [{"prompt": PROMPT_OK}, {"prompt": PROMPT_OK, "args": ["--continue"]}]},
    "candidate_betas_on": {"env": {k: v for k, v in CANDIDATE_ENV.items() if k != "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"}, "invocations": [{"prompt": PROMPT_TOOL, "args": ALLOW_TOOL}]},
    "candidate_hints": {"env": {**CANDIDATE_ENV, "CLAUDE_CODE_GATEWAY_HINT_HEADERS": "1"}, "invocations": [{"prompt": PROMPT_TOOL, "args": ALLOW_TOOL}]},
    # Long-lived session over stream-json stdin: idle traffic and multi-turn movement
    "default_stdin_idle": {"timeout": 260, "invocations": [{"prompt": None, "args": ["--input-format", "stream-json"] + ALLOW_TOOL,
                            "stdin": [(0, PROMPT_TOOL), (25, "Second turn. " + PROMPT_OK), (25, "Third turn, after idle."), (150, None)]}]},
    "candidate_stdin_idle": {"env": CANDIDATE_ENV, "timeout": 260, "invocations": [{"prompt": None, "args": ["--input-format", "stream-json"] + ALLOW_TOOL,
                              "stdin": [(0, PROMPT_TOOL), (25, "Second turn. " + PROMPT_OK), (25, "Third turn, after idle."), (150, None)]}]},
}


def add_runs() -> None:
    c = CANDIDATE_ENV
    # HC4 thinking and signatures (two turns via --continue)
    for sig in ("none", "empty", "opaque"):
        RUNS[f"think_sig_{sig}"] = {"env": c, "server": ["--think", "--sig", sig],
                                    "invocations": [{"prompt": PROMPT_TOOL, "args": ALLOW_TOOL},
                                                    {"prompt": "Next turn. " + PROMPT_OK, "args": ["--continue"]}]}
    RUNS["think_only_tail"] = {"env": c, "server": ["--sig", "none"],
                               "invocations": [{"prompt": "@@thinkonly " + PROMPT_OK},
                                               {"prompt": "Next turn. " + PROMPT_OK, "args": ["--continue"]}]}
    RUNS["think_sig_none_reject"] = {"env": c, "server": ["--think", "--sig", "none", "--reject-empty-signature"],
                                     "invocations": [{"prompt": PROMPT_TOOL, "args": ALLOW_TOOL},
                                                     {"prompt": "Next turn. " + PROMPT_OK, "args": ["--continue"]}]}
    # HC3 / O-4B-12 mid-conversation system: reject, see strip-and-retry
    for name, wording in {
        "sysrole_reject_anthropic": None,
        "sysrole_reject_palimnesis": "palimnesis: unsupported_feature: role 'system' in messages is not supported",
    }.items():
        extra = ["--reject-system-role"] + (["--system-role-wording", wording] if wording else [])
        RUNS[name] = {"env": c, "server": extra,
                      "invocations": [{"prompt": PROMPT_TOOL, "args": ALLOW_TOOL},
                                      {"prompt": "Next turn. " + PROMPT_OK, "args": ["--continue"]}]}
    # HC5 retries and stream failures (candidate env: fallback disabled)
    for scen in ("s500_then_ok", "s500_noretry", "s400_retry_true", "s409", "s409_noretry", "s429_ra5_then_ok",
                 "s429_noretry", "s529", "start_eof_then_ok", "start_eof_noretry_then_ok", "start_abort_then_ok",
                 "partial_eof_then_ok", "partial_abort_then_ok", "partial_eof_noretry_then_ok", "error_event_then_ok",
                 "error_event_overloaded_then_ok", "error_event_noretry_then_ok", "partial_error_event_then_ok",
                 "partial_error_event_noretry_then_ok", "complete_then_eof_then_ok", "max_tokens_stop", "ok_ping_first",
                 "complete_then_eof_noretry_then_ok", "complete_then_error_event_then_ok",
                 "complete_then_error_event_noretry_then_ok", "complete_then_abort_then_ok"):
        RUNS[f"f_{scen}"] = {"env": {**c, "CLAUDE_CODE_MAX_RETRIES": "3"}, "scenario": scen, "timeout": 200,
                             "invocations": [{"prompt": PROMPT_OK}]}
        RUNS[f"fb_{scen}"] = {"env": {**{k: v for k, v in c.items() if k != "CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK"}, "CLAUDE_CODE_MAX_RETRIES": "3"},
                              "scenario": scen, "timeout": 200, "invocations": [{"prompt": PROMPT_OK}]}
    RUNS["f_s500_default_retries"] = {"env": c, "scenario": "s500", "timeout": 400, "invocations": [{"prompt": PROMPT_OK}]}
    RUNS["f_s429_ra90"] = {"env": c, "scenario": "s429_ra90", "timeout": 300, "invocations": [{"prompt": PROMPT_OK}]}
    # Header wait
    RUNS["f_header_timeout5s"] = {"env": {**c, "API_TIMEOUT_MS": "5000", "CLAUDE_CODE_MAX_RETRIES": "2"}, "scenario": "header_delay8", "timeout": 120,
                                  "invocations": [{"prompt": PROMPT_OK}]}
    RUNS["f_header_delay8_default"] = {"env": c, "scenario": "header_delay8", "invocations": [{"prompt": PROMPT_OK}]}
    # Watchdogs: shortened via the documented env, then once at the default
    short = {**c, "CLAUDE_STREAM_IDLE_TIMEOUT_MS": "15000", "CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS": "15000", "CLAUDE_CODE_MAX_RETRIES": "1"}
    for scen in ("idle_after_start_then_ok", "headers_only_idle_then_ok", "comments_40_then_ok", "start_comments_40_then_ok",
                 "pings_40_then_ok", "start_pings_40_then_ok"):
        RUNS[f"wd15_{scen}"] = {"env": short, "scenario": scen, "timeout": 200, "invocations": [{"prompt": PROMPT_OK}]}
    ev_only = {**c, "CLAUDE_STREAM_IDLE_TIMEOUT_MS": "15000", "CLAUDE_CODE_MAX_RETRIES": "1"}
    byte_only = {**c, "CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS": "15000", "CLAUDE_CODE_MAX_RETRIES": "1"}
    for scen in ("comments_40_then_ok", "start_comments_40_then_ok", "idle_after_start_then_ok"):
        RUNS[f"wdev15_{scen}"] = {"env": ev_only, "scenario": scen, "timeout": 200, "invocations": [{"prompt": PROMPT_OK}]}
        RUNS[f"wdby15_{scen}"] = {"env": byte_only, "scenario": scen, "timeout": 200, "invocations": [{"prompt": PROMPT_OK}]}
    RUNS["wdfb15_idle_after_start_then_ok"] = {"env": {**short, "CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK": "0"},
                                               "scenario": "idle_after_start_then_ok", "timeout": 200,
                                               "invocations": [{"prompt": PROMPT_OK}]}
    for scen in ("start_comments_660", "start_pings_660"):
        RUNS[f"wd_default_{scen}"] = {"env": {**c, "CLAUDE_CODE_MAX_RETRIES": "1"}, "scenario": scen, "timeout": 900,
                                      "invocations": [{"prompt": PROMPT_OK}]}
    for scen in ("start_comments_330", "start_pings_330", "comments_330", "pings_330", "idle_after_start_then_ok"):
        RUNS[f"wd_default_{scen}"] = {"env": {**c, "CLAUDE_CODE_MAX_RETRIES": "1"}, "scenario": scen, "timeout": 900,
                                      "invocations": [{"prompt": PROMPT_OK}]}
    # HC6 compaction and the blocking limit
    # The fake reports a fixed input_tokens; turn 2 shows whether the client blocks.
    two = [{"prompt": PROMPT_OK}, {"prompt": "Turn 2. " + PROMPT_OK, "args": ["--continue"]}]
    for n in (9000, 10500, 13000, 20000, 30000):
        RUNS[f"blk32k_u{n}"] = {"env": c, "server": ["--usage-input", str(n)], "invocations": two}
    for n in (20000, 26000, 30000):
        RUNS[f"blk32k_out4k_u{n}"] = {"env": {**c, "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "4096"},
                                      "server": ["--usage-input", str(n)], "invocations": two}
    for n in (30000, 250000):
        RUNS[f"blk1m_u{n}"] = {"env": {**c, "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "1000000"},
                               "server": ["--usage-input", str(n)], "invocations": two}
    no_auto = {k: v for k, v in c.items() if k != "DISABLE_AUTO_COMPACT"}
    # Auto-compaction threshold ~ (32768 - 4096) - 13000 = 15672 < 20000 < blocking 25672
    for name, env in {"acmp_default_u20000": no_auto, "acmp_auto_off_u20000": c,
                      "acmp_compact_off_u20000": {**no_auto, "DISABLE_COMPACT": "1"}}.items():
        RUNS[name] = {"env": {**env, "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "4096"}, "server": ["--usage-input", "20000"],
                      "invocations": [{"prompt": PROMPT_OK}, {"prompt": "Turn 2. " + PROMPT_OK, "args": ["--continue"]}]}
    for name, env in {
        "compact_auto_off": {**c},
        "compact_off": {**no_auto, "DISABLE_COMPACT": "1"},
        "compact_default": no_auto,
    }.items():
        RUNS[name] = {"env": {**env, "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "1000000", "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "32768",
                              "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "4096"},
                      "server": ["--usage-input", "24000"], "timeout": 240,
                      "invocations": [{"prompt": "Turn 1. " + PROMPT_OK},
                                      {"prompt": "Turn 2. " + PROMPT_OK, "args": ["--continue"]},
                                      {"prompt": "/compact", "args": ["--continue"]},
                                      {"prompt": "After compact. " + PROMPT_OK, "args": ["--continue"]}]}
    # HC7 resume fidelity
    RUNS["resume"] = {"env": c, "server": ["--think", "--sig", "none"],
                      "invocations": [{"prompt": PROMPT_TOOL, "args": ALLOW_TOOL},
                                      {"prompt": "Turn two via continue. " + PROMPT_OK, "args": ["--continue"]},
                                      {"prompt": "Turn three via resume. " + PROMPT_OK, "args": ["--resume", "{session_id}"]},
                                      {"prompt": "Turn four via fork. " + PROMPT_OK, "args": ["--resume", "{session_id}", "--fork-session"]}]}
    # HC8 transcript gate: read and grep a directory outside the cwd, no prompt
    gate = 'Look it up. @@tool Read {"file_path": "TRANSCRIPTS/t-0001.md"} @@tool Grep {"pattern": "needle-4242", "path": "TRANSCRIPTS"} @@tool Bash {"command": "grep -rn needle-4242 TRANSCRIPTS_POSIX", "description": "grep"}'
    RUNS["gate_none"] = {"env": c, "gate": True, "invocations": [{"prompt": gate}]}
    RUNS["gate_add_dir"] = {"env": c, "gate": True, "invocations": [{"prompt": gate, "args": ["--add-dir", "TRANSCRIPTS"]}]}
    RUNS["gate_settings"] = {"env": c, "gate": True, "settings": {"permissions": {"additionalDirectories": ["TRANSCRIPTS"]}},
                             "invocations": [{"prompt": gate}]}
    RUNS["gate_settings_allow"] = {"env": c, "gate": True,
                                   "settings": {"permissions": {"additionalDirectories": ["TRANSCRIPTS"],
                                                                "allow": ["Read(TRANSCRIPTS_GLOB)", "Grep(TRANSCRIPTS_GLOB)", "Bash(grep:*)"]}},
                                   "invocations": [{"prompt": gate}]}
    # O-4B-13: F with tools trimmed by --disallowedTools (a harness setting)
    RUNS["candidate_trim"] = {"env": c, "invocations": [{"prompt": PROMPT_TOOL, "args": ALLOW_TOOL + ["--disallowedTools"] + TRIM_TOOLS}]}
    RUNS["candidate_trim_settings"] = {"env": c, "settings": {"permissions": {"deny": TRIM_TOOLS}},
                                       "invocations": [{"prompt": PROMPT_TOOL, "args": ALLOW_TOOL}]}
    # HC9 history import: hand-built session file, then --resume
    RUNS["import_history_sysrole_reject"] = {"env": c, "import": True, "server": ["--reject-system-role"],
                                             "invocations": [{"prompt": "Imported continue. " + PROMPT_OK, "args": ["--resume", "IMPORT_SID"]},
                                                             {"prompt": "Next. " + PROMPT_OK, "args": ["--continue"]}]}
    RUNS["import_history"] = {"env": c, "import": True,
                              "invocations": [{"prompt": "Imported continue. " + PROMPT_OK, "args": ["--resume", "IMPORT_SID"]}]}


add_runs()


# ---------------------------------------------------------------------------
# Sentinel proxy: logs and refuses anything routed through HTTP(S)_PROXY.


def start_sentinel(log_path: Path) -> tuple[int, callable]:
    loop = asyncio.new_event_loop()
    f = log_path.open("a", encoding="utf-8")

    async def handle(reader, writer):
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            first = head.split(b"\r\n", 1)[0].decode("latin-1")
            f.write(json.dumps({"wall": time.time(), "request_line": first}) + "\n")
            f.flush()
            writer.write(b"HTTP/1.1 403 Forbidden\r\ncontent-length: 0\r\nconnection: close\r\n\r\n")
            await writer.drain()
        except Exception as e:  # noqa: BLE001
            f.write(json.dumps({"wall": time.time(), "error": repr(e)}) + "\n")
            f.flush()
        finally:
            writer.close()

    ready = threading.Event()
    holder = {}

    def run():
        asyncio.set_event_loop(loop)
        srv = loop.run_until_complete(asyncio.start_server(handle, "127.0.0.1", 0))
        holder["port"] = srv.sockets[0].getsockname()[1]
        holder["srv"] = srv
        ready.set()
        loop.run_forever()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    ready.wait(10)

    def stop():
        loop.call_soon_threadsafe(loop.stop)
    return holder["port"], stop


# ---------------------------------------------------------------------------


def child_env(run_dir: Path, base_url: str, spec: dict, sentinel_port: int | None) -> dict:
    env = {k: os.environ[k] for k in OS_KEEP if k in os.environ}
    home = run_dir / "home"
    for d in ("home", "home/AppData/Roaming", "home/AppData/Local", "tmp", "config"):
        (run_dir / d).mkdir(parents=True, exist_ok=True)
    env.update({
        "CLAUDE_CONFIG_DIR": str(run_dir / "config"),
        "HOME": str(home), "USERPROFILE": str(home),
        "APPDATA": str(home / "AppData" / "Roaming"), "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "TEMP": str(run_dir / "tmp"), "TMP": str(run_dir / "tmp"),
        "ANTHROPIC_BASE_URL": base_url, "ANTHROPIC_API_KEY": DUMMY_KEY, "ANTHROPIC_MODEL": MODEL,
        **SAFE_ENV,
    })
    gb = Path(r"C:\Program Files\Git\bin\bash.exe")
    if gb.exists():
        env["CLAUDE_CODE_GIT_BASH_PATH"] = str(gb)
    if sentinel_port:
        proxy = f"http://127.0.0.1:{sentinel_port}"
        env.update({"HTTPS_PROXY": proxy, "HTTP_PROXY": proxy, "https_proxy": proxy, "http_proxy": proxy,
                    "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
    env.update(spec.get("env", {}))
    return env


def subst(s: str, ctx: dict) -> str:
    for k, v in ctx.items():
        s = s.replace(k, v)
    return s


def write_import_session(cfg: Path, work: Path) -> str:
    """Hand-build a Claude Code session JSONL (2 user/assistant pairs) under projects/."""
    import uuid
    sid = str(uuid.uuid4())
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(work))
    proj = cfg / "projects" / slug
    proj.mkdir(parents=True, exist_ok=True)
    lines = []
    parent = None
    ts = "2026-11-05T10:00:00.000Z"
    turns = [("user", "Imported turn one: remember the code word heron-77."),
             ("assistant", "Noted: heron-77."),
             ("user", "Imported turn two: what is 2+2?"),
             ("assistant", "4.")]
    for role, text in turns:
        u = str(uuid.uuid4())
        rec = {"parentUuid": parent, "isSidechain": False, "userType": "external", "cwd": str(work),
               "sessionId": sid, "version": "2.1.318", "type": role, "uuid": u, "timestamp": ts}
        if role == "user":
            rec["message"] = {"role": "user", "content": text}
        else:
            rec["message"] = {"id": f"msg_import_{u[:8]}", "type": "message", "role": "assistant", "model": MODEL,
                              "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
                              "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}
        lines.append(json.dumps(rec))
        parent = u
    (proj / f"{sid}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sid


def run_one(name: str, root: Path, fixtures: bool, slim: bool) -> dict:
    spec = RUNS[name]
    run_dir = root / name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    work = run_dir / "work"
    work.mkdir(parents=True)
    (work / "hello.txt").write_text("hello from the probe work dir\n", encoding="utf-8")
    ctx = {"WORK": str(work).replace("\\", "/")}
    if spec.get("gate"):
        tdir = run_dir / "transcripts"
        tdir.mkdir()
        (tdir / "t-0001.md").write_text("# transcript\nuser: the needle-4242 is here\n", encoding="utf-8")
        ctx["TRANSCRIPTS_POSIX"] = "/" + str(tdir).replace("\\", "/").replace(":", "", 1)
        ctx["TRANSCRIPTS_GLOB"] = "//" + str(tdir).replace("\\", "/").replace(":", "", 1) + "/**"
        ctx["TRANSCRIPTS"] = str(tdir).replace("\\", "/")
    log = run_dir / "server.jsonl"
    sargs = [sys.executable, str(SERVER), "--scenario", spec.get("scenario", "ok"), "--port", "0",
             "--log", str(log)] + spec.get("server", [])
    srv = subprocess.Popen(sargs, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    url = json.loads(srv.stdout.readline())["listening"]
    sentinel_port, stop_sentinel = (None, None)
    if not spec.get("no_sentinel"):
        sentinel_port, stop_sentinel = start_sentinel(run_dir / "sentinel.jsonl")
    base_url = f"{url}/s/probe-{name}"
    env = child_env(run_dir, base_url, spec, sentinel_port)
    if spec.get("settings"):
        (run_dir / "config" / "settings.json").write_text(subst(json.dumps(spec["settings"]), ctx), encoding="utf-8")
    if spec.get("import"):
        ctx["IMPORT_SID"] = write_import_session(run_dir / "config", work)
    meta = {"run": name, "claude_version": subprocess.run([CLAUDE, "--version"], capture_output=True, text=True, env=env).stdout.strip(),
            "scenario": spec.get("scenario", "ok"), "server_args": spec.get("server", []),
            "env_overrides": spec.get("env", {}), "sentinel": bool(sentinel_port), "invocations": []}
    session_id = None
    for i, inv in enumerate(spec["invocations"]):
        if session_id:
            ctx["{session_id}"] = session_id
        cmd = [CLAUDE, "-p"]
        if inv.get("prompt") is not None:
            cmd.append(subst(inv["prompt"], ctx))
        cmd += ["--output-format", "stream-json", "--verbose", "--model", MODEL]
        cmd += [subst(a, ctx) for a in inv.get("args", [])]
        t0 = time.time()
        out_f = (run_dir / f"claude.{i}.stdout.jsonl").open("w", encoding="utf-8")
        err_f = (run_dir / f"claude.{i}.stderr.txt").open("w", encoding="utf-8")
        stdin_plan = inv.get("stdin")
        p = subprocess.Popen(cmd, cwd=work, env=env, stdout=out_f, stderr=err_f,
                             stdin=subprocess.PIPE if stdin_plan else subprocess.DEVNULL, text=True, encoding="utf-8")
        killed = False
        try:
            if stdin_plan:
                for delay, text in stdin_plan:
                    time.sleep(delay)
                    if text is None:
                        break
                    p.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": subst(text, ctx)}}) + "\n")
                    p.stdin.flush()
                p.stdin.close()
            p.wait(timeout=spec.get("timeout", 150))
        except subprocess.TimeoutExpired:
            p.kill()
            killed = True
            p.wait()
        out_f.close()
        err_f.close()
        for line in (run_dir / f"claude.{i}.stdout.jsonl").read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("session_id"):
                session_id = o["session_id"]
        meta["invocations"].append({"cmd": [c if c != DUMMY_KEY else "<dummy>" for c in cmd[1:]], "exit": p.returncode,
                                    "killed": killed, "seconds": round(time.time() - t0, 2), "session_id": session_id})
        time.sleep(1.0)
    srv.terminate()
    srv.wait()
    if stop_sentinel:
        stop_sentinel()
    sent = run_dir / "sentinel.jsonl"
    meta["sentinel_hits"] = sent.read_text().splitlines() if sent.exists() else []
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    if fixtures:
        save_fixture(run_dir, name, slim)
    return meta


USER_RE = re.compile(r"(?i)C:[\\/]+Users[\\/]+[^\\/\"]+")


def sanitize_text(s: str) -> str:
    s = USER_RE.sub("C:/Users/<user>", s)
    s = re.sub(r"(?i)/c/Users/[^/\"]+", "/c/Users/<user>", s)
    return s


def sanitize_record(rec: dict, seen: dict, slim: bool) -> dict:
    body = rec.get("body")
    if isinstance(body, dict):
        md = body.get("metadata")
        if isinstance(md, dict) and isinstance(md.get("user_id"), str):
            try:
                uid = json.loads(md["user_id"])
                for k in ("device_id", "account_uuid"):
                    if uid.get(k):
                        uid[k] = "<redacted>"
                md["user_id"] = json.dumps(uid)
            except ValueError:
                md["user_id"] = "<redacted>"
        if slim:
            # Keep the first full system/tools of a run only when keep_first; elide the rest
            # (and every mid-conversation system entry's text) as sha256 + size.
            for key in ("system", "tools"):
                if key in body:
                    raw = json.dumps(body[key], ensure_ascii=False)
                    h = hashlib.sha256(raw.encode()).hexdigest()[:16]
                    if h in seen or not seen.get("_keep_first", False):
                        body[key] = {"_elided": True, "sha256_16": h, "bytes": len(raw), "first_seq": seen.get(h)}
                    seen.setdefault(h, rec.get("seq"))
            if not seen.get("_keep_first", False):
                for m in body.get("messages", []):
                    if m.get("role") == "system":
                        raw = json.dumps(m.get("content"), ensure_ascii=False)
                        m["content"] = {"_elided": True, "sha256_16": hashlib.sha256(raw.encode()).hexdigest()[:16], "bytes": len(raw)}
    return json.loads(sanitize_text(json.dumps(rec, ensure_ascii=False)))


# Runs whose fixtures keep one full request body (system, tools, mid-conversation system).
SHAPE_RUNS = {"default_tool", "candidate_tool", "candidate_trim", "tui_candidate", "compact_auto_off", "sysrole_reject_anthropic"}


def save_fixture(run_dir: Path, name: str, slim: bool) -> None:
    dest = FIXTURES / name
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    seen: dict = {"_keep_first": name in SHAPE_RUNS}
    out = []
    for line in (run_dir / "server.jsonl").read_text(encoding="utf-8").splitlines():
        out.append(json.dumps(sanitize_record(json.loads(line), seen, slim), ensure_ascii=False))
    (dest / "server.jsonl").write_text("\n".join(out) + "\n", encoding="utf-8")
    (dest / "meta.json").write_text(sanitize_text((run_dir / "meta.json").read_text(encoding="utf-8")), encoding="utf-8")
    if (run_dir / "sentinel.jsonl").exists():
        shutil.copy(run_dir / "sentinel.jsonl", dest / "sentinel.jsonl")
    for f in sorted(run_dir.glob("claude.*.stdout.jsonl")):
        lines = []
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                o = json.loads(line)
            except ValueError:
                lines.append(line)
                continue
            # The init line lists tools, slash commands, skills, agents: kept whole in shape
            # runs (the harness's own inventory), reduced to counts elsewhere.
            if slim and name not in SHAPE_RUNS and o.get("type") == "system" and o.get("subtype") == "init":
                o = {k: (f"<{len(v)} items>" if isinstance(v, list) and len(v) > 3 else v) for k, v in o.items()}
            lines.append(json.dumps(o, ensure_ascii=False))
        (dest / f.name).write_text(sanitize_text("\n".join(lines) + "\n"), encoding="utf-8")
    for f in sorted(run_dir.glob("claude.*.stderr.txt")):
        (dest / f.name).write_text(sanitize_text(f.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="*")
    ap.add_argument("--root", default=None)
    ap.add_argument("--fixtures", action="store_true")
    ap.add_argument("--slim", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--save-only", action="store_true", help="only (re)write fixtures from existing run dirs")
    a = ap.parse_args()
    if a.save_only:
        for name in a.runs:
            save_fixture(Path(a.root) / name, name, a.slim)
        return
    if a.list:
        for k in RUNS:
            print(k)
        return
    root = Path(a.root or (Path(os.environ.get("TEMP", ".")) / "cc-probe"))
    for name in a.runs:
        if name not in RUNS:
            sys.exit(f"unknown run {name}")
        m = run_one(name, root, a.fixtures, a.slim)
        print(json.dumps({"run": name, "invocations": [(i["exit"], i["killed"], i["seconds"]) for i in m["invocations"]],
                          "sentinel_hits": len(m["sentinel_hits"])}), flush=True)


if __name__ == "__main__":
    main()
