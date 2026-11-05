"""Real Pi 1.5.0 as an evaluation client (Phase 4B S14; ``docs/probes/pi.md``).

Used by the needle driver (``eval/needle.py run --driver pi``, ``eval/needle_pi.py``).
Every Pi process runs isolated, as in ``eval/probes/pi_live_smoke.py`` and HP1-HP7:

- a throwaway agent directory (``PI_CODING_AGENT_DIR``), HOME/USERPROFILE, TEMP and XDG
  directories under one root (``oc_harness.base_env``: an environment allowlist and a PATH
  without the repo's virtual environment); the user's ``~/.pi`` is never read or written;
- ``PI_OFFLINE=1``, ``PI_SKIP_VERSION_CHECK=1``, ``PI_TELEMETRY=0``, ``-nc`` (no context
  files);
- the shipped adapter (``integrations/pi/``): its ``models.json`` with the port replaced, its
  ``settings.json`` plus the isolation keys, and its session extension loaded with ``-e``
  (``X-Palimnesis-Session`` = Pi's session id);
- the process tree killed at the timeout; stdin at EOF; success judged by the run's events
  (``agent_settled``), not the exit code (HP7: Windows exits ``0xC0000409`` after work).

**Import** (HP7, VERIFIED for user and assistant text): ``history_to_pi_session`` turns an
OpenAI Chat message list (the needle histories) into the entries of a Pi session file. The
shapes of tool calls, tool results and thinking blocks were read from a session file Pi
1.5.0 itself wrote (a scripted tool loop against ``eval/probes/pi_fault_server.py``):

- assistant ``content`` blocks ``{"type": "thinking", "thinking", "thinkingSignature"}``
  (on Chat the signature names the stream field, ``reasoning_content``),
  ``{"type": "text", "text"}``, ``{"type": "toolCall", "id", "name", "arguments": <object>}``;
  ``stopReason`` ``toolUse`` or ``stop``;
- tool results as ``{"role": "toolResult", "toolCallId", "toolName", "content": [text],
  "isError": false}``.

What Pi cannot carry back verbatim is refused (``ValueError``), never silently changed:
whitespace-only text or reasoning (Pi drops it, HP3 §3.4), an assistant turn with neither
text nor calls, tool-call arguments that are not a JSON object or are not already in
``JSON.stringify``'s compact form (Pi re-serializes them, HP3 §3.4), calls without a result
and results without a call. ``chat_fidelity`` then checks the first request Pi actually sends.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import oc_harness as oc

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "integrations" / "pi"
WINDOWS = os.name == "nt"
PI_CLI = Path(os.environ.get(
    "PI_CLI",
    Path.home() / ".pi/agent/install/releases/1.5.0/node_modules/@earendil-works/"
    "pi-coding-agent/dist/bundle/cli.js",
))
# grep, ls and find are off by default (HP6); the a3 addendum's grep needs them.
TOOLS = "read,grep,bash,ls,find"
PROVIDER = {"chat": "palimnesis", "messages": "palimnesis-messages"}
API = {"chat": "openai-completions", "messages": "anthropic-messages"}
# Windows' CreateProcess limit is 32,767 characters for the whole command line.
WINDOWS_CMDLINE_MAX = 32_000


def adapter_models() -> dict:
    return json.loads((ADAPTER / "models.json").read_text(encoding="utf-8"))


def model_id(protocol: str = "chat") -> str:
    return adapter_models()["providers"][PROVIDER[protocol]]["models"][0]["id"]


# ---------------------------------------------------------------- session file (pure)

def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def js_compact(obj) -> str:
    """``JSON.stringify(obj)`` for the JSON values tool arguments hold: no spaces,
    non-ASCII kept, integral floats without ``.0`` (JavaScript numbers)."""
    def norm(x):
        if isinstance(x, float) and x.is_integer() and abs(x) < 2 ** 53:
            return int(x)
        if isinstance(x, dict):
            return {k: norm(v) for k, v in x.items()}
        if isinstance(x, list):
            return [norm(v) for v in x]
        return x
    return json.dumps(norm(obj), separators=(",", ":"), ensure_ascii=False)


def _text_of_user(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list) and all(isinstance(p, dict) and p.get("type") == "text"
                                         and isinstance(p.get("text"), str) for p in content):
        return [p["text"] for p in content]
    raise ValueError("user content must be a string or a list of text parts")


ZERO_USAGE = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0,
              "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}}


def history_to_pi_session(messages: list[dict], *, session_id: str, cwd: str, t0_ms: int,
                          protocol: str = "chat", provider: str | None = None,
                          model: str | None = None, seed: int = 0) -> list[dict]:
    """An OpenAI Chat message list (no system message) as Pi 1.5.0 session-file entries:
    a version-3 ``session`` header, then one ``message`` entry per user, assistant and tool
    message, chained by ``parentId``. Timestamps advance 1 s per message from ``t0_ms``;
    entry ids are 8 hex digits derived from ``seed``. Raises ``ValueError`` for a history
    Pi would not resend verbatim (module docstring)."""
    if protocol not in API:
        raise ValueError(f"unknown protocol {protocol!r}")
    provider = provider or PROVIDER[protocol]
    model = model or model_id(protocol)
    calls: dict[str, str] = {}   # call id -> tool name
    answered: set[str] = set()
    for m in messages:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                if tc["id"] in calls:
                    raise ValueError(f"duplicate tool call id {tc['id']}")
                calls[tc["id"]] = tc["function"]["name"]
    out: list[dict] = [{"type": "session", "version": 3, "id": session_id,
                        "timestamp": _iso(t0_ms), "cwd": cwd}]
    parent, t = None, t0_ms
    pending: set[str] = set()

    def add(message: dict) -> None:
        nonlocal parent
        eid = f"{(seed * 1_000_003 + len(out) * 2_654_435_761) & 0xFFFF_FFFF:08x}"
        out.append({"type": "message", "id": eid, "parentId": parent, "timestamp": _iso(t),
                    "message": message})
        parent = eid

    for i, m in enumerate(messages):
        role = m.get("role")
        t += 1000
        if role == "user":
            if pending:
                raise ValueError(f"message {i}: user message before the results of {sorted(pending)}")
            add({"role": "user", "content": [{"type": "text", "text": x} for x in _text_of_user(m["content"])],
                 "timestamp": t})
        elif role == "assistant":
            if pending:
                raise ValueError(f"message {i}: assistant message before the results of {sorted(pending)}")
            blocks: list[dict] = []
            reasoning = m.get("reasoning_content")
            if reasoning is not None and reasoning != "":
                if not reasoning.strip():
                    raise ValueError(f"message {i}: whitespace-only reasoning (Pi drops it)")
                blocks.append({"type": "thinking", "thinking": reasoning,
                               "thinkingSignature": "reasoning_content" if protocol == "chat" else ""})
            content = m.get("content")
            if content is not None and not isinstance(content, str):
                raise ValueError(f"message {i}: assistant content must be a string or null")
            if content:
                if not content.strip():
                    raise ValueError(f"message {i}: whitespace-only assistant text (Pi drops it)")
                blocks.append({"type": "text", "text": content})
            for tc in m.get("tool_calls") or []:
                raw = tc["function"]["arguments"] or "{}"
                try:
                    args = json.loads(raw)
                except ValueError:
                    raise ValueError(f"message {i}: tool call {tc['id']} arguments are not JSON") from None
                if not isinstance(args, dict):
                    raise ValueError(f"message {i}: tool call {tc['id']} arguments are not an object")
                if js_compact(args) != raw:
                    raise ValueError(f"message {i}: tool call {tc['id']} arguments are not compact "
                                     "JSON (Pi re-serializes them)")
                blocks.append({"type": "toolCall", "id": tc["id"], "name": tc["function"]["name"],
                               "arguments": args})
                pending.add(tc["id"])
            if not blocks:
                raise ValueError(f"message {i}: assistant message with no text, reasoning or calls")
            add({"role": "assistant", "content": blocks, "api": API[protocol], "provider": provider,
                 "model": model, "usage": json.loads(json.dumps(ZERO_USAGE)),
                 "stopReason": "toolUse" if m.get("tool_calls") else "stop", "timestamp": t})
        elif role == "tool":
            cid = m.get("tool_call_id")
            if cid not in calls:
                raise ValueError(f"message {i}: tool result {cid} answers no call")
            if cid in answered or cid not in pending:
                raise ValueError(f"message {i}: tool result {cid} is repeated or out of place")
            if not isinstance(m.get("content"), str):
                raise ValueError(f"message {i}: tool result content must be a string")
            answered.add(cid)
            pending.discard(cid)
            add({"role": "toolResult", "toolCallId": cid, "toolName": calls[cid],
                 "content": [{"type": "text", "text": m["content"]}], "isError": False, "timestamp": t})
        else:
            raise ValueError(f"message {i}: unsupported role {role!r}")
    missing = sorted(set(calls) - answered)
    if missing:
        raise ValueError(f"tool calls without a result: {missing}")
    return out


def session_jsonl(entries: list[dict]) -> bytes:
    return "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries).encode("utf-8")


# ---------------------------------------------------------------- what Pi resends (pure)

def expected_chat(history: list[dict], question: str) -> list[dict]:
    """The non-system messages of Pi's first Chat request after import (HP3 §3.1): user
    content as text parts, everything else as the history has it, then the question."""
    out = []
    for m in history:
        if m["role"] == "user":
            out.append({"role": "user", "content": [{"type": "text", "text": x}
                                                    for x in _text_of_user(m["content"])]})
        else:
            out.append(dict(m))
    out.append({"role": "user", "content": [{"type": "text", "text": question}]})
    return out


def canonical(messages: list[dict]) -> list[tuple]:
    """A protocol-neutral sequence of a request's conversation, for either a Chat message
    list or an Anthropic Messages list: user text, thinking, assistant text, calls (with
    parsed arguments) and results, in order. ``cache_control`` and message boundaries are
    ignored. System messages are skipped."""
    out: list[tuple] = []
    for m in messages:
        role = m.get("role")
        if role in ("system", "developer"):
            continue
        content = m.get("content")
        if role == "tool":
            out.append(("result", m.get("tool_call_id"), content if isinstance(content, str)
                        else "".join(p.get("text", "") for p in content or [])))
            continue
        if role == "assistant" and m.get("reasoning_content"):
            out.append(("thinking", m["reasoning_content"]))
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])
        for b in blocks:
            kind = b.get("type")
            if kind == "text":
                if role == "user":
                    out.append(("user", b["text"]))
                elif b["text"]:
                    out.append(("text", b["text"]))
            elif kind == "thinking":
                out.append(("thinking", b.get("thinking")))
            elif kind == "tool_use":
                out.append(("call", b.get("id"), b.get("name"), b.get("input")))
            elif kind == "tool_result":
                c = b.get("content")
                out.append(("result", b.get("tool_use_id"), c if isinstance(c, str)
                            else "".join(p.get("text", "") for p in c or [])))
            else:
                out.append(("other", kind))
        for tc in m.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except ValueError:
                args = tc["function"]["arguments"]
            out.append(("call", tc.get("id"), tc["function"]["name"], args))
    return out


def chat_fidelity(client_body: dict, history: list[dict], question: str,
                  protocol: str = "chat") -> dict:
    """Compare Pi's first request after import with the history plus the question.

    Chat: the non-system messages must equal ``expected_chat`` exactly (Pi's own system
    message and tools are allowed). Messages: the ``canonical`` sequences must be equal.
    Returns counts and the first mismatching index (``None`` when equal)."""
    if protocol == "chat":
        got = [m for m in client_body.get("messages") or [] if m.get("role") not in ("system", "developer")]
        want = expected_chat(history, question)
    else:
        got = canonical(client_body.get("messages") or [])
        want = canonical(expected_chat(history, question))
    first_diff = next((i for i, (g, w) in enumerate(zip(got, want)) if g != w), None)
    if first_diff is None and len(got) != len(want):
        first_diff = min(len(got), len(want))
    out = {"protocol": protocol, "messages_sent": len(got), "messages_expected": len(want),
           "first_diff": first_diff, "faithful": first_diff is None,
           "system_sent": bool(client_body.get("system")) or any(
               m.get("role") in ("system", "developer") for m in client_body.get("messages") or []),
           "tools_sent": [t.get("name") or (t.get("function") or {}).get("name")
                          for t in client_body.get("tools") or []]}
    if first_diff is not None:
        g = got[first_diff] if first_diff < len(got) else None
        w = want[first_diff] if first_diff < len(want) else None
        out["diff"] = {"got": json.dumps(g, ensure_ascii=False)[:300],
                       "want": json.dumps(w, ensure_ascii=False)[:300]}
    return out


def last_user_text(body: dict) -> str | None:
    """The text of a request's last user message that carries text (either protocol)."""
    for m in reversed(body.get("messages") or []):
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            return c
        texts = [b.get("text", "") for b in c or [] if b.get("type") == "text"]
        if texts:
            return "".join(texts)
    return None


def turn_summary(events: list[dict]) -> dict:
    """Final text, tool calls, stop reasons and errors of one ``pi --mode json`` run.

    The answer is the text of the run's last assistant message, unless that message called
    a tool or ended in ``error``/``aborted`` (a failed partial, which Pi never resends)."""
    final = None
    stops, errors, retries = [], [], 0
    started: dict[str, dict] = {}
    tools: list[dict] = []
    settled = None
    for e in events:
        kind = e.get("type")
        if kind == "message_end" and (e.get("message") or {}).get("role") == "assistant":
            m = e["message"]
            stops.append(m.get("stopReason"))
            blocks = m.get("content") or []
            text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
            called = any(isinstance(b, dict) and b.get("type") == "toolCall" for b in blocks)
            if m.get("stopReason") in ("error", "aborted"):
                errors.append(f"{m.get('stopReason')}: {str(m.get('errorMessage') or '')[:300]}")
                final = None
            else:
                final = None if called else text
        elif kind == "tool_execution_start":
            started[e.get("toolCallId")] = {"name": e.get("toolName"), "input": e.get("args") or {}}
        elif kind == "tool_execution_end":
            s = started.pop(e.get("toolCallId"), {"name": e.get("toolName"), "input": {}})
            res = e.get("result") or {}
            chars = sum(len(b.get("text", "")) for b in res.get("content") or [] if isinstance(b, dict))
            tools.append({"name": s["name"], "input": s["input"], "error": bool(e.get("isError")),
                          "output_chars": chars})
        elif kind and "retry" in kind and kind.endswith("start"):
            retries += 1
        elif kind == "agent_settled":
            settled = not e.get("aborted")
    for s in started.values():  # started, never ended (killed mid-tool)
        tools.append({"name": s["name"], "input": s["input"], "error": True, "output_chars": 0})
    return {"final": final, "tools": tools, "stops": stops, "errors": errors,
            "retries": retries, "settled": settled}


def as_export(entries: list[dict]) -> dict:
    """A Pi session file in the ``opencode session export`` shape that
    ``gate_inputs._export_parts`` and ``strings_of`` read: assistant text and reasoning
    parts, and one ``tool`` part per call with its input and result."""
    results = {}
    for e in entries:
        m = e.get("message") or {}
        if e.get("type") == "message" and m.get("role") == "toolResult":
            results[m.get("toolCallId")] = m.get("content")
    msgs = []
    for e in entries:
        m = e.get("message") or {}
        if e.get("type") != "message":
            continue
        if m.get("role") == "user":
            msgs.append({"type": "user", "text": "".join(b.get("text", "") for b in m.get("content") or []
                                                         if isinstance(b, dict))})
        elif m.get("role") == "assistant":
            parts = []
            for b in m.get("content") or []:
                if b.get("type") == "text":
                    parts.append({"type": "text", "text": b.get("text", "")})
                elif b.get("type") == "thinking":
                    parts.append({"type": "reasoning", "text": b.get("thinking", "")})
                elif b.get("type") == "toolCall":
                    parts.append({"type": "tool", "id": b.get("id"), "name": b.get("name"),
                                  "state": {"input": b.get("arguments"),
                                            "content": results.get(b.get("id"))}})
            msgs.append({"type": "assistant", "content": parts})
    return {"info": {"harness": "pi"}, "messages": msgs}


# ---------------------------------------------------------------- isolated Pi

class PiHome:
    """One isolated Pi agent directory and home, configured with the shipped adapter
    pointed at ``base_origin`` (``http://127.0.0.1:<port>``), on ``protocol``."""

    def __init__(self, root: Path, workspace: Path, base_origin: str, protocol: str = "chat",
                 max_tokens: int | None = None):
        self.root, self.ws, self.protocol = root, workspace, protocol
        self.agent = root / "agent"
        for d in ("agent", "home", "tmp", "logs", "sessions", "xdg/config", "xdg/data",
                  "xdg/cache", "xdg/state"):
            (root / d).mkdir(parents=True, exist_ok=True)
        models = adapter_models()
        for p in models["providers"].values():
            p["baseUrl"] = p["baseUrl"].replace("http://127.0.0.1:9000", base_origin.rstrip("/"))
            if max_tokens:
                for m in p["models"]:
                    m["maxTokens"] = max_tokens
        self.models = models
        (self.agent / "models.json").write_text(json.dumps(models, indent=2), encoding="utf-8", newline="\n")
        settings = json.loads((ADAPTER / "settings.json").read_text(encoding="utf-8"))
        settings.update({"defaultProvider": PROVIDER[protocol], "defaultProjectTrust": "never",
                         "enableInstallTelemetry": False, "quietStartup": True})
        self.settings = settings
        (self.agent / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8", newline="\n")
        self.extension = root / "palimnesis-session.ts"
        shutil.copy(ADAPTER / "extensions" / "palimnesis-session.ts", self.extension)
        self.n = 0

    def env(self) -> dict:
        e = oc.base_env(self.root)
        e.update({"PI_CODING_AGENT_DIR": str(self.agent), "PI_OFFLINE": "1",
                  "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0", "NO_COLOR": "1",
                  "PWD": str(self.ws)})
        return e

    def run(self, prompt: str, session_file: Path, *, label: str = "run", timeout: float = 1800) -> dict:
        """One ``pi --mode json --session <file>`` turn with ``prompt`` as its message.

        The prompt is an argument (as in ``pi_live_smoke``); the step's first request is
        checked against it (``last_user_text``), so a quoting change would show."""
        self.n += 1
        argv = ["node", str(PI_CLI), "-e", str(self.extension), "-nc", "--mode", "json",
                "--tools", TOOLS, "--session", str(session_file), prompt]
        if WINDOWS and len(subprocess.list2cmdline(argv)) > WINDOWS_CMDLINE_MAX:
            raise ValueError(f"prompt too long for a Windows command line ({len(prompt)} chars)")
        logs = self.root / "logs"
        stem = f"{self.n:03d}-{label}"
        meta = {"label": label, "started": time.time()}
        with open(logs / f"{stem}.stdout", "wb") as so, open(logs / f"{stem}.stderr", "wb") as se:
            p = subprocess.Popen(argv, cwd=self.ws, env=self.env(), stdin=subprocess.DEVNULL,
                                 stdout=so, stderr=se, start_new_session=not WINDOWS)
            deadline = time.time() + timeout
            while p.poll() is None and time.time() < deadline:
                time.sleep(0.05)
            if p.poll() is None:
                oc.kill_tree(p)
                meta["timeout_killed"] = True
            meta["exit"] = p.wait()
        meta["ended"] = time.time()
        meta["elapsed_s"] = round(meta["ended"] - meta["started"], 2)
        meta["events"] = oc.parse_events((logs / f"{stem}.stdout").read_bytes())
        meta["stderr"] = (logs / f"{stem}.stderr").read_bytes().decode("utf-8", "replace")[-3000:]
        return meta


def read_session(path: Path) -> list[dict]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out
