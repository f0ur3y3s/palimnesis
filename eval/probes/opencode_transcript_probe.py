"""Probe whether OpenCode 2.1.4 can search and read a transcript directory outside its
working directory and outside any git repo (A1 "Harness capability gate").

Isolation is the R9/R10 one (`eval/fixtures/opencode-2.1.4/view-live/scripts/oc_turn.py`):
isolated HOME, XDG, TEMP and OpenCode config dirs, OPENCODE_DISABLE_PROJECT_CONFIG,
`opencode run --standalone`, a throwaway git repo as cwd/PWD, stdin at EOF, and the process
tree killed at the timeout. Model requests go through the shipped plugin
(integrations/opencode/plugins/palimnesis.ts) to a Palimnesis passthrough at --proxy.

A probe-only observer plugin (opencode_transcript_observer.ts) logs every permission
evaluation (action, resources, rule-derived effect) BEFORE the run command answers an
"ask", so asks are visible even under --auto, where they are approved silently.

Layout under ROOT:
    work/                         git repo, the session cwd
    localappdata/palimnesis/transcripts/ses_probe0001/
                                  index.md, turn-0001..0020.md (turn-0013.md: 3,000 lines)
    config/ home/ xdg/ tmp/ logs/ isolated OpenCode state

Variants (opencode.json `permissions`, appended after the shipped subagent deny):
    a  none (shipped config)
    b  allow external_directory + read on <transcripts>/* (forward slashes)
    c  control: external_directory * -> ask (proves the ask detector)
    d  c + allow rule written with backslashes and upper case
    e  c + allow rule written with ~ (expanded against OPENCODE_TEST_HOME)

Usage:
    uv run python -I eval/probes/opencode_transcript_probe.py --root ROOT setup
    uv run python -I eval/probes/opencode_transcript_probe.py --root ROOT run LABEL \
        --variant a [--auto] --task index|oversize|paginate [--backslash]
    uv run python -I eval/probes/opencode_transcript_probe.py --root ROOT summary [--json OUT]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EXE = Path(os.environ["APPDATA"]) / "npm/node_modules/@opencode/cli/bin/opencode.exe"
SESSION = "ses_probe0001"
TERM = "HELIOTROPE"
NEEDLE = "NEEDLE: vault combination 7-31-4-19, token QX-5521-VIOLET"
NEEDLE_LINE = 42
ANCHOR = "ANCHOR-OSPREY: the next line holds the answer"
ANCHOR_LINE = 2417
ANSWER = "ANSWER: copper-kestrel-8812"
BIG_TURN = 13
BIG_LINES = 3000
TOPICS = ["lighthouse", "quarry", "saffron", "tundra", "marimba", "obsidian", TERM.lower(),
          "pelican", "juniper", "cobalt", "meridian", "lantern", "sextant", "willow",
          "basalt", "harbor", "fennel", "zephyr", "glacier", "orchard"]


def transcripts(root: Path) -> Path:
    return root / "localappdata" / "palimnesis" / "transcripts"


def session_dir(root: Path) -> Path:
    return transcripts(root) / SESSION


def fwd(p: Path) -> str:
    return str(p).replace("\\", "/")


def turn_lines(n: int) -> list[str]:
    if n == BIG_TURN:
        lines = [f"L{i:04d} tool output row {i}: status=ok bytes={i * 37 % 9973} "
                 f"checksum={i * 2654435761 % 2**32:08x}" for i in range(1, BIG_LINES + 1)]
        lines[ANCHOR_LINE - 1] = ANCHOR
        lines[ANCHOR_LINE] = ANSWER
        return lines
    lines = [f"# Turn {n:04d}", "", f"<!-- palimnesis turn {n} session {SESSION} -->", ""]
    while len(lines) < 80:
        i = len(lines) + 1
        lines.append(f"line {i}: assistant discussed the {TOPICS[n - 1]} plan, step {i}.")
    if n == 7:
        lines[NEEDLE_LINE - 1] = NEEDLE
    return lines


def setup(root: Path) -> None:
    for d in ("config/plugins", "home", "xdg/config", "xdg/data", "xdg/cache", "xdg/state",
              "tmp", "logs", "work"):
        (root / d).mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "integrations/opencode/plugins/palimnesis.ts", root / "config/plugins")
    shutil.copy(Path(__file__).with_name("opencode_transcript_observer.ts"), root / "config/plugins")
    (root / "config/service.json").write_text('{"disabled": true}\n', "utf-8")
    work = root / "work"
    if not (work / ".git").exists():
        (work / "README.md").write_text("probe repo\n", "utf-8")
        g = ["git", "-C", str(work), "-c", "user.name=probe", "-c", "user.email=probe@localhost"]
        subprocess.run([*g, "init", "-q"], check=True)
        subprocess.run([*g, "add", "."], check=True)
        subprocess.run([*g, "commit", "-qm", "init"], check=True)
    sd = session_dir(root)
    sd.mkdir(parents=True, exist_ok=True)
    index = [f"# Transcript index: session {SESSION}", "",
             "One entry per turn: turn, file, line count, topic.", ""]
    for n in range(1, 21):
        lines = turn_lines(n)
        (sd / f"turn-{n:04d}.md").write_bytes(("\n".join(lines) + "\n").encode())  # LF
        topic = TERM if n == 7 else TOPICS[n - 1]
        index.append(f"- turn {n:04d} | turn-{n:04d}.md | {len(lines)} lines | topic: {topic}")
    (sd / "index.md").write_bytes(("\n".join(index) + "\n").encode())
    probe = subprocess.run(["git", "-C", str(sd), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True)
    print(json.dumps({"session_dir": str(sd), "in_git_repo": probe.returncode == 0,
                      "files": len(list(sd.iterdir()))}))


def config(root: Path, variant: str, proxy: str) -> dict:
    cfg = json.loads((REPO / "integrations/opencode/opencode.json").read_text("utf-8"))
    cfg["update"] = "disable"
    cfg["share"] = "disabled"
    cfg["providers"]["palimnesis"]["settings"]["baseURL"] = f"{proxy}/s/static-fallback/v1"
    t = fwd(transcripts(root))
    ask_all = {"action": "external_directory", "resource": "*", "effect": "ask"}
    extra = {
        "a": [],
        "b": [{"action": "external_directory", "resource": f"{t}/*", "effect": "allow"},
              {"action": "read", "resource": f"{t}/*", "effect": "allow"}],
        "c": [ask_all],
        "d": [ask_all, {"action": "external_directory",
                        "resource": str(transcripts(root)).upper() + "\\*", "effect": "allow"}],
        "e": [ask_all, {"action": "external_directory",
                        "resource": "~/../localappdata/palimnesis/transcripts/*", "effect": "allow"}],
    }[variant]
    cfg["permissions"] = cfg["permissions"] + extra
    return cfg


def prompt(root: Path, task: str, backslash: bool) -> str:
    sd = str(session_dir(root)) if backslash else fwd(session_dir(root))
    sep = "\\" if backslash else "/"
    if task == "index":
        return (f"Search {sd}{sep}index.md for {TERM}, then read only lines "
                f"{NEEDLE_LINE - 2}-{NEEDLE_LINE + 2} of the matching turn file (in the same "
                f"directory) and quote the line that starts with NEEDLE exactly.")
    if task == "paginate":
        return (f"Using only the read tool (no grep, glob or shell), read {sd}{sep}turn-{BIG_TURN:04d}.md "
                f"and quote exactly the line that follows the line starting with ANCHOR-OSPREY.")
    return (f"The file {sd}{sep}turn-{BIG_TURN:04d}.md has about {BIG_LINES} lines. Use the grep "
            f"tool to find the line number of ANCHOR-OSPREY in it, then use the read tool with "
            f"offset and limit to read at most 5 lines starting at that line, and quote the line "
            f"that follows the anchor exactly.")


def env(root: Path, proxy: str, label: str) -> dict:
    e = {k: v for k, v in os.environ.items()
         if not k.startswith(("OPENCODE", "XDG_", "MNEMON", "PALIMNESIS", "PROBE_"))}
    e.update({
        "HOME": str(root / "home"), "USERPROFILE": str(root / "home"),
        "OPENCODE_TEST_HOME": str(root / "home"),
        "OPENCODE_CONFIG_DIR": str(root / "config"),
        "XDG_CONFIG_HOME": str(root / "xdg/config"), "XDG_DATA_HOME": str(root / "xdg/data"),
        "XDG_CACHE_HOME": str(root / "xdg/cache"), "XDG_STATE_HOME": str(root / "xdg/state"),
        "OPENCODE_DISABLE_PROJECT_CONFIG": "true", "OPENCODE_DISABLE_CLAUDE_CODE": "true",
        "OPENCODE_DISABLE_MODELS_FETCH": "true", "OPENCODE_DISABLE_AUTOUPDATE": "true",
        "OPENCODE_DISABLE_FILEWATCHER": "true",
        "PALIMNESIS_PROXY_ORIGIN": proxy,
        "PROBE_PERMISSION_LOG": str(root / "logs/permissions.jsonl"), "PROBE_LABEL": label,
        "TEMP": str(root / "tmp"), "TMP": str(root / "tmp"),
        "PWD": str(root / "work"),
    })
    return e


def run(root: Path, label: str, variant: str, auto: bool, task: str, backslash: bool,
        proxy: str, timeout: float) -> None:
    cfg = config(root, variant, proxy)
    (root / "config/opencode.json").write_text(json.dumps(cfg, indent=2), "utf-8")
    (root / "logs" / f"{label}.opencode.json").write_text(json.dumps(cfg, indent=2), "utf-8")
    message = prompt(root, task, backslash)
    cmd = [str(EXE), "run", "--standalone", *(["--auto"] if auto else []), "--format", "json", message]
    out = root / "logs"
    meta = {"label": label, "variant": variant, "auto": auto, "task": task, "backslash": backslash,
            "command": ["opencode.exe", *cmd[1:]], "started": time.time()}
    oc = subprocess.Popen(cmd, cwd=root / "work", env=env(root, proxy, label), stdin=subprocess.DEVNULL,
                          stdout=(out / f"{label}.stdout.jsonl").open("wb"),
                          stderr=(out / f"{label}.stderr.txt").open("wb"))
    deadline = time.time() + timeout
    while oc.poll() is None and time.time() < deadline:
        time.sleep(0.05)
    if oc.poll() is None:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(oc.pid)], capture_output=True)
        meta["timeout_killed"] = True
    meta.update(exit_code=oc.wait(), ended=time.time())
    meta["elapsed_s"] = round(meta["ended"] - meta["started"], 2)
    (out / f"{label}.meta.json").write_text(json.dumps(meta, indent=2), "utf-8")
    print(json.dumps(summarize(root, label), indent=1))


def summarize(root: Path, label: str) -> dict:
    out = root / "logs"
    meta = json.loads((out / f"{label}.meta.json").read_text("utf-8"))
    events = [json.loads(line) for line in
              (out / f"{label}.stdout.jsonl").read_text("utf-8", "replace").splitlines() if line.strip()]
    tools, texts, steps, errors = [], [], 0, []
    session = next((ev.get("sessionID") for ev in events if ev.get("sessionID")), None)
    for ev in events:
        part = ev.get("part") or {}
        if ev.get("type") == "tool_use":
            st = part.get("state") or {}
            output = st.get("output") if isinstance(st.get("output"), str) else json.dumps(st.get("output"))
            tools.append({"tool": part.get("tool"), "input": st.get("input"), "status": st.get("status"),
                          "error": st.get("error"),
                          "output_head": (output or "")[:300],
                          "output_has_needle": NEEDLE in (output or "") or ANSWER in (output or "")})
        elif ev.get("type") == "text":
            texts.append(part.get("text", ""))
        elif ev.get("type") == "step_start":
            steps += 1
        elif ev.get("type") == "error":
            errors.append(json.dumps(ev)[:400])
    perm_log = out / "permissions.jsonl"
    perms = [r for r in (json.loads(x) for x in perm_log.read_text("utf-8").splitlines() if x.strip())
             if r.get("label") == label] if perm_log.exists() else []
    stderr = (out / f"{label}.stderr.txt").read_text("utf-8", "replace")
    final = "\n".join(texts)
    target = NEEDLE if meta["task"] == "index" else ANSWER
    return {
        "label": label, "variant": meta["variant"], "auto": meta["auto"], "task": meta["task"],
        "backslash": meta.get("backslash"), "exit_code": meta["exit_code"],
        "elapsed_s": meta["elapsed_s"], "timeout_killed": meta.get("timeout_killed", False),
        "session": session, "model_round_trips": steps,
        "proxy_captures": len(list((root / "captures" / session).iterdir()))
        if session and (root / "captures" / session).exists() else 0,
        "tools": tools,
        "permission_evaluations": [{k: r.get(k) for k in ("action", "resources", "effect")} for r in perms],
        "asks": [r for r in perms if r.get("effect") == "ask"],
        "denies_in_tools": [t for t in tools if t["status"] == "error"],
        "stderr_permission_lines": [x for x in stderr.splitlines() if "permission requested" in x],
        "needle_in_final_text": target in final,
        "final_text": final[-600:], "errors": errors,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--proxy", default="http://127.0.0.1:9051")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    r = sub.add_parser("run")
    r.add_argument("label")
    r.add_argument("--variant", choices="abcde", required=True)
    r.add_argument("--auto", action="store_true")
    r.add_argument("--task", choices=["index", "oversize", "paginate"], required=True)
    r.add_argument("--backslash", action="store_true")
    r.add_argument("--timeout", type=float, default=600)
    s = sub.add_parser("summary")
    s.add_argument("--json", type=Path)
    a = p.parse_args()
    root = a.root.resolve()
    if a.cmd == "setup":
        setup(root)
    elif a.cmd == "run":
        run(root, a.label, a.variant, a.auto, a.task, a.backslash, a.proxy, a.timeout)
    else:
        labels = sorted(f.name[: -len(".meta.json")] for f in (root / "logs").glob("*.meta.json"))
        rows = [summarize(root, x) for x in labels]
        text = json.dumps(rows, indent=1)
        if a.json:
            a.json.write_text(text, "utf-8")
        print(text)


if __name__ == "__main__":
    main()
