"""Real OpenCode 2.1.4 as an evaluation client (plan §5, D44.2, O3).

Shared by the needle driver (``eval/needle.py --driver opencode``) and the coding-task
runner (``eval/tasks/run.py``). Every OpenCode process runs isolated as in R9/R10/R14:

- ``opencode … --standalone`` (a private server, never the background service);
- an environment allowlist (``ENV_ALLOW``); HOME, USERPROFILE, XDG_*, TEMP/TMP and
  ``OPENCODE_CONFIG_DIR`` under one root;
- ``OPENCODE_DISABLE_PROJECT_CONFIG`` and the other disable switches;
- ``PWD`` and the process cwd set to a fresh git repo; stdin at EOF;
- the process tree killed at the timeout, so no request stays running upstream.

The provider's ``baseURL`` is the Palimnesis session URL that
``palimnesis session new|url`` prints, so one OpenCode session maps to one named
Palimnesis session without the session plugin. No plugin is loaded, so requests carry
no ``X-Palimnesis-Kind``; the proxy does not use it.

``history_to_export`` turns an OpenAI Chat message list (the needle histories) into the
JSON ``opencode session export`` writes, for ``opencode session import``. Its shape was
learned from real 2.1.4 exports (``docs/harnesses.md``, OpenCode, "Session import").
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = Path(os.environ.get("APPDATA", "")) / "npm/node_modules/@opencode/cli/bin/opencode.exe"
MODEL_ID = "qwen3.8-flash-next-iq3_xxs"
PROVIDER = "palimnesis"


# ---------------------------------------------------------------- isolation

def clean_path() -> str:
    """PATH without the repo's virtual environment, so the model's shell sees the
    system Python (no pytest, no palimnesis), not the one ``uv run`` put first."""
    venv = os.environ.get("VIRTUAL_ENV") or str(ROOT / ".venv")
    keep = [p for p in os.environ.get("PATH", "").split(os.pathsep)
            if p and not os.path.normcase(p).startswith(os.path.normcase(venv))]
    return os.pathsep.join(keep)


# Variables inherited from the driver's environment; everything else is dropped, so no
# credential, proxy setting, virtual environment or harness variable reaches OpenCode,
# the model's shell or the hidden check.
ENV_ALLOW = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "OS",
             "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER",
             "PROCESSOR_LEVEL", "PROCESSOR_REVISION", "USERNAME", "USERDOMAIN", "COMPUTERNAME",
             "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432",
             "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "COMMONPROGRAMW6432", "PUBLIC",
             "ALLUSERSPROFILE", "TZ", "LANG", "LC_ALL",
             # Kept real: the system ``python`` is a Python install manager alias that keeps
             # its installs under LOCALAPPDATA. Isolated, it updated itself and downloaded a
             # new Python into the isolated tree (observed 2026-10-25).
             "APPDATA", "LOCALAPPDATA")


def base_env(root: Path) -> dict:
    """The allowlisted variables, the cleaned PATH, and HOME, TEMP and the XDG
    directories under ``root``."""
    e = {k: v for k, v in os.environ.items() if k.upper() in ENV_ALLOW}
    e["PATH"] = clean_path()
    home = str(root / "home")
    e.update({
        "HOME": home, "USERPROFILE": home,
        "XDG_CONFIG_HOME": str(root / "xdg" / "config"), "XDG_DATA_HOME": str(root / "xdg" / "data"),
        "XDG_CACHE_HOME": str(root / "xdg" / "cache"), "XDG_STATE_HOME": str(root / "xdg" / "state"),
        "TEMP": str(root / "tmp"), "TMP": str(root / "tmp"),
    })
    return e


def env(root: Path, workspace: Path) -> dict:
    e = base_env(root)
    e.update({
        "OPENCODE_TEST_HOME": e["HOME"],
        "OPENCODE_CONFIG_DIR": str(root / "config"),
        "OPENCODE_DISABLE_PROJECT_CONFIG": "true", "OPENCODE_DISABLE_CLAUDE_CODE": "true",
        "OPENCODE_DISABLE_MODELS_FETCH": "true", "OPENCODE_DISABLE_AUTOUPDATE": "true",
        "OPENCODE_DISABLE_FILEWATCHER": "true",
        "PWD": str(workspace),
    })
    return e


def config(base_url: str, *, context_limit: int = 1_000_000, compaction: bool = False) -> dict:
    """The isolated OpenCode config. Arm 4: ``compaction`` off and a large
    ``limit.context`` (harnesses.md, "Required settings"). Arm 1: native compaction on,
    with ``limit.context`` at the true capacity."""
    return {
        "model": f"{PROVIDER}/{MODEL_ID}",
        "update": "disable",
        "share": "disabled",
        "compaction": {"auto": compaction},
        "agents": {"title": {"disabled": True}},
        "permissions": [{"action": "subagent", "resource": "*", "effect": "deny"}],
        "providers": {PROVIDER: {
            "name": "Palimnesis",
            "package": "@opencode/ai/providers/openai-compatible",
            "settings": {"baseURL": base_url, "apiKey": "palimnesis-local"},
            "compatibility": {"reasoningField": "reasoning_content"},
            "models": {MODEL_ID: {
                "name": "Qwen3.8 Flash Next (Strata via Palimnesis)",
                "capabilities": {"tools": True, "reasoning": {"supported": True}},
                "limit": {"context": context_limit, "output": 8192},
            }},
        }},
    }


def session_base_url(port: int, session: str | None = None) -> tuple[str, str]:
    """(session id, OpenAI base URL) from ``palimnesis session new|url``."""
    cmd = ["uv", "run", "palimnesis", "session"] + (["url", session] if session else ["new"])
    p = subprocess.run(cmd + ["--port", str(port)], capture_output=True, text=True, cwd=str(ROOT),
                       check=True)
    sid = re.search(r"^session: (\S+)", p.stdout, re.M).group(1)
    url = re.search(r"^openai_base_url: (\S+)", p.stdout, re.M).group(1)
    return sid, url


class Home:
    """One isolated OpenCode home plus its workspace (a fresh git repo)."""

    def __init__(self, root: Path, workspace: Path):
        self.root, self.ws = root, workspace
        for d in ("home", "config", "tmp", "logs", "xdg/config", "xdg/data", "xdg/cache", "xdg/state"):
            (root / d).mkdir(parents=True, exist_ok=True)
        (root / "config" / "service.json").write_text('{"disabled": true}', encoding="utf-8")
        workspace.mkdir(parents=True, exist_ok=True)
        if not (workspace / ".git").exists():
            subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
            subprocess.run(["git", "-c", "user.name=eval", "-c", "user.email=eval@localhost",
                            "commit", "-q", "--allow-empty", "-m", "init"], cwd=workspace, check=True)
        self.n = 0

    def write_config(self, cfg: dict) -> None:
        (self.root / "config" / "opencode.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    def _run(self, args: list[str], label: str, timeout: float, stdin: bytes | None = None) -> dict:
        self.n += 1
        logs = self.root / "logs"
        stem = f"{self.n:03d}-{label}"
        meta = {"label": label, "args": args, "started": time.time()}
        with open(logs / f"{stem}.stdout", "wb") as so, open(logs / f"{stem}.stderr", "wb") as se:
            p = subprocess.Popen([str(EXE), *args], cwd=self.ws, env=env(self.root, self.ws),
                                 stdin=subprocess.DEVNULL if stdin is None else subprocess.PIPE,
                                 stdout=so, stderr=se)
            if stdin is not None:
                p.stdin.write(stdin)
                p.stdin.close()
            deadline = time.time() + timeout
            while p.poll() is None and time.time() < deadline:
                time.sleep(0.05)
            if p.poll() is None:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
                meta["timeout_killed"] = True
            meta["exit"] = p.wait()
        meta["ended"] = time.time()
        meta["elapsed_s"] = round(meta["ended"] - meta["started"], 2)
        meta["stdout"] = (logs / f"{stem}.stdout").read_bytes()
        meta["stderr"] = (logs / f"{stem}.stderr").read_bytes().decode("utf-8", "replace")[-3000:]
        return meta

    def run(self, message: str, *, session: str | None = None, label: str = "run",
            timeout: float = 1800) -> dict:
        """One ``opencode run`` turn. The message goes on stdin, which then reaches EOF:
        on Windows, 2.1.4 keeps the quotes ``CreateProcess`` puts around an argument
        with spaces (``"…"`` reaches the model), and long pastes exceed the command line."""
        args = ["run", "--standalone", "--auto", "--format", "json"]
        if session:
            args += ["--session", session]
        meta = self._run(args, label, timeout, stdin=message.encode("utf-8"))
        meta["events"] = parse_events(meta.pop("stdout"))
        return meta

    def export(self, session: str, label: str = "export") -> dict:
        meta = self._run(["session", "export", "--standalone", session], label, 120)
        out = meta.pop("stdout").decode("utf-8")
        return json.loads(out[out.index("{"):])

    def import_(self, path: Path, label: str = "import") -> dict:
        meta = self._run(["session", "import", "--standalone", "--directory", str(self.ws),
                          str(path)], label, 120)
        meta["stdout"] = meta["stdout"].decode("utf-8", "replace")
        return meta

    def list_sessions(self) -> str:
        meta = self._run(["session", "list", "--standalone"], "list", 120)
        return meta["stdout"].decode("utf-8", "replace")


# ---------------------------------------------------------------- session export format

_B62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def opencode_id(prefix: str, ms: int, counter: int, tail: str, *, descending: bool = False) -> str:
    """OpenCode's identifier shape: the low 48 bits of ``ms * 4096 + counter`` as 12 hex
    digits (bitwise inverted for descending ids, as session ids are), then 14 base-62
    characters. Observed in 2.1.4 exports; ``tail`` makes it deterministic here."""
    n = (ms * 0x1000 + counter) & 0xFFFF_FFFF_FFFF
    if descending:
        n = 0xFFFF_FFFF_FFFF - n
    return f"{prefix}_{n:012x}{tail[:14]}"


def _tail(seed: int, k: int) -> str:
    x, out = (seed * 1_000_003 + k * 7_919) & 0xFFFF_FFFF_FFFF, []
    for _ in range(14):
        x = (x * 6_364_136_223_846_793_005 + 1_442_695_040_888_963_407) & 0xFFFF_FFFF_FFFF_FFFF
        out.append(_B62[(x >> 33) % 62])
    return "".join(out)


def history_to_export(messages: list[dict], *, directory: str, project_id: str, t0_ms: int,
                      seed: int = 0, model_id: str = MODEL_ID, provider: str = PROVIDER,
                      agent: str = "build") -> dict:
    """An OpenAI Chat message list (no system message) as an ``opencode session export``
    document, for ``opencode session import``.

    - A ``user`` message becomes ``{"type": "user", "text", "files": []}``.
    - Each ``assistant`` message becomes one assistant message (one model step): a
      ``reasoning`` part when ``reasoning_content`` is set, a ``text`` part when the
      content is non-empty, and one completed ``tool`` part per tool call, whose result
      is the content of the ``tool`` message answering that call id.
    - ``tool`` messages are folded into those parts; one that answers no earlier call is
      an error. Every assistant message ends ``stop`` or ``tool-calls``.
    - Timestamps advance 1 s per message from ``t0_ms``; ids follow OpenCode's shape.
    """
    results: dict[str, str] = {}
    for m in messages:
        if m["role"] == "tool":
            results[m["tool_call_id"]] = m["content"]
    called = {tc["id"] for m in messages if m["role"] == "assistant" for tc in m.get("tool_calls") or []}
    stray = set(results) - called
    if stray:
        raise ValueError(f"tool results without a call: {sorted(stray)}")
    out, t, k = [], t0_ms, 0

    def nid(prefix: str) -> str:
        nonlocal k
        k += 1
        return opencode_id(prefix, t, k, _tail(seed, k))

    for m in messages:
        role = m["role"]
        if role == "tool":
            continue
        t += 1000
        if role == "user":
            if not isinstance(m["content"], str):
                raise ValueError("only string user content is supported")
            out.append({"id": nid("msg"), "time": {"created": t}, "text": m["content"],
                        "files": [], "type": "user"})
            continue
        if role != "assistant":
            raise ValueError(f"unsupported role {role!r}")
        parts: list[dict] = []
        if m.get("reasoning_content"):
            parts.append({"type": "reasoning", "text": m["reasoning_content"],
                          "native": {"reasoningField": "reasoning_content"},
                          "time": {"created": t + 100, "completed": t + 200}})
        if m.get("content"):
            parts.append({"type": "text", "text": m["content"]})
        for tc in m.get("tool_calls") or []:
            fn = tc["function"]
            args = json.loads(fn["arguments"] or "{}")
            if tc["id"] not in results:
                raise ValueError(f"tool call {tc['id']} has no result")
            parts.append({"type": "tool", "id": tc["id"], "name": fn["name"], "executed": False,
                          "state": {"status": "completed", "input": args,
                                    "content": [{"type": "text", "text": results[tc["id"]]}],
                                    "metadata": {"truncated": False}},
                          "time": {"created": t + 300, "ran": t + 400, "completed": t + 500}})
        finish = "tool-calls" if m.get("tool_calls") else "stop"
        out.append({"id": nid("msg"), "time": {"created": t, "streamed": t + 600, "completed": t + 700},
                    "type": "assistant", "agent": agent,
                    "model": {"id": model_id, "providerID": provider}, "content": parts,
                    "finish": finish, "rawFinish": "tool_calls" if m.get("tool_calls") else "stop",
                    "cost": 0, "tokens": {"input": 0, "output": 0, "reasoning": 0,
                                          "cache": {"read": 0, "write": 0}}})
    t += 1000
    out.append({"id": nid("msg"), "time": {"created": t}, "type": "idle", "outcome": "succeeded"})
    sid = opencode_id("ses", t0_ms, 1, _tail(seed, 0), descending=True)
    return {"info": {"id": sid, "projectID": project_id, "cost": 0,
                     "tokens": {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}},
                     "outcome": "succeeded", "time": {"created": t0_ms, "updated": t, "idle": t},
                     "location": {"directory": directory}},
            "messages": out}


def git_root_commit(workspace: Path) -> str:
    """OpenCode's project id for a git workspace is its root commit (observed in 2.1.4)."""
    p = subprocess.run(["git", "rev-list", "--max-parents=0", "HEAD"], cwd=workspace,
                       capture_output=True, text=True, check=True)
    return p.stdout.split()[0]


# ---------------------------------------------------------------- run output

def parse_events(raw: bytes) -> list[dict]:
    """``opencode run --format json`` writes one JSON event per line."""
    out = []
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out
