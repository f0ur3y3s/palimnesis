"""Drive Pi against the Pi fault server (Phase 4B S0, probes HP1-HP7).

Each probe gets a throwaway root with its own agent directory (``PI_CODING_AGENT_DIR``),
home (``HOME``/``USERPROFILE``) and working folder, a dummy API key, and
``PI_OFFLINE=1``/``PI_SKIP_VERSION_CHECK=1``/``PI_TELEMETRY=0``, so the user's ``~/.pi``
is never read or written and nothing leaves loopback. Pi talks only to
``pi_fault_server.py`` on 127.0.0.1 (or, for ``mbp_*`` probes, to a local
``palimnesis serve --passthrough`` whose upstream the caller chooses).

Usage:
    uv run python eval/probes/pi_probe.py --list
    uv run python eval/probes/pi_probe.py hp1_join_chat hp4_s500 ...
    uv run python eval/probes/pi_probe.py --summary RUNDIR

Environment: ``PI_CLI`` (path to Pi's ``dist/bundle/cli.js``; default the 1.5.0 managed
install), ``PI_PROBE_ROOT`` (where run folders go; default a temp folder).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pi_fault_server import (
    SCENARIOS,
    ServerThread,
    Status,
    Stream,
    answer,
    ok,
    tool_turn,
)

PI_CLI = Path(os.environ.get(
    "PI_CLI",
    Path.home() / ".pi/agent/install/releases/1.5.0/node_modules/@earendil-works/"
    "pi-coding-agent/dist/bundle/cli.js",
))
ROOT = Path(os.environ.get("PI_PROBE_ROOT", Path(tempfile.gettempdir()) / "pi-probe-runs"))

HEADER_EXTENSION = """\
// Palimnesis association probe: X-Palimnesis-Session from Pi's own session id.
export default function (pi) {
  pi.on("before_provider_headers", (event, ctx) => {
    event.headers["X-Palimnesis-Session"] = ctx.sessionManager.getSessionId();
  });
  pi.on("session_start", (event, ctx) => {
    console.error(`[palimnesis-probe] session_start reason=${event.reason} id=${ctx.sessionManager.getSessionId()}`);
  });
}
"""


class Probe:
    """One probe root: a fault server plus any number of Pi invocations sharing it."""

    def __init__(self, name: str, plan: list, protocol: str = "chat", *,
                 base: str | None = None, model: dict | None = None,
                 compat: dict | None = None, settings: dict | None = None,
                 extension: str | None = None, provider_headers: dict | None = None,
                 upstream_base: str | None = None, via_proxy: bool = False) -> None:
        self.name = name
        self.dir = ROOT / name
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.agent = self.dir / "agent"
        self.home = self.dir / "home"
        self.work = self.dir / "work"
        for d in (self.agent, self.home, self.work):
            d.mkdir(parents=True)
        (self.work / "notes.txt").write_text("hello from notes\n", encoding="utf-8")
        self.server = None
        self.proxy = None
        if upstream_base is None:
            self.server = ServerThread(plan, name, self.dir / "server.jsonl").start()
            port = self.server.port
            if via_proxy:
                # Phase 4B S14 (hx_*): Pi -> palimnesis serve (archive mode) -> fault server.
                # The fault server has no /props, so bounded views stay off; the archive,
                # stream, error and admission paths are what these runs exercise.
                port = self._start_proxy(port)
            if base is None:
                base = "http://127.0.0.1:{port}/s/probe-sess/v1" if protocol == "chat" \
                    else "http://127.0.0.1:{port}/s/probe-sess"
            self.base = base.format(port=port)
        else:
            self.base = upstream_base
        api = "openai-completions" if protocol == "chat" else "anthropic-messages"
        m = {"id": "m", "name": "m", "reasoning": True, "contextWindow": 32768, "maxTokens": 8192}
        m.update(model or {})
        provider = {"baseUrl": self.base, "api": api, "apiKey": "dummy-probe-key",
                    "models": [m]}
        if compat:
            provider["compat"] = compat
        if provider_headers:
            provider["headers"] = provider_headers
        (self.agent / "models.json").write_text(
            json.dumps({"providers": {"fault": provider}}, indent=2), encoding="utf-8")
        s = {"defaultProvider": "fault", "defaultModel": m["id"], "defaultProjectTrust": "never",
             "enableInstallTelemetry": False, "cacheWarming": "off", "quietStartup": True,
             "retry": {"baseDelayMs": 500}}
        for k, v in (settings or {}).items():
            if isinstance(v, dict) and isinstance(s.get(k), dict):
                s[k] = {**s[k], **v}
            else:
                s[k] = v
        (self.agent / "settings.json").write_text(json.dumps(s, indent=2), encoding="utf-8")
        self.ext_path = None
        if extension:
            self.ext_path = self.dir / "palimnesis-session.ts"
            self.ext_path.write_text(extension, encoding="utf-8")
        self.runs: list[dict] = []
        self.meta = {"name": name, "protocol": protocol, "base": self.base,
                     "settings": s, "provider": {**provider, "apiKey": "<dummy>"}}

    def env(self) -> dict:
        e = dict(os.environ)
        for k in list(e):
            if k.startswith(("PI_", "OPENAI", "ANTHROPIC")):
                del e[k]
        e.update({
            "PI_CODING_AGENT_DIR": str(self.agent),
            "HOME": str(self.home), "USERPROFILE": str(self.home),
            "PI_OFFLINE": "1", "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0",
            "NO_COLOR": "1",
        })
        e.pop("HTTP_PROXY", None)
        e.pop("HTTPS_PROXY", None)
        return e

    def argv(self, extra: list[str]) -> list[str]:
        a = ["node", str(PI_CLI)]
        if self.ext_path:
            a += ["-e", str(self.ext_path)]
        return a + extra

    def pi(self, args: list[str], timeout: float = 120.0, label: str | None = None) -> dict:
        """Run Pi once (print or json mode) with stdin at EOF."""
        label = label or f"run{len(self.runs) + 1}"
        t0 = time.time()
        try:
            p = subprocess.run(self.argv(args), cwd=self.work, env=self.env(),
                               stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
                               check=False)
            rc, out, err = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired as e:
            rc, out, err = "timeout", e.stdout or b"", e.stderr or b""
        rec = {"label": label, "args": args, "rc": rc, "seconds": round(time.time() - t0, 2)}
        (self.dir / f"{label}.stdout.txt").write_bytes(out)
        (self.dir / f"{label}.stderr.txt").write_bytes(err)
        self.runs.append(rec)
        return rec

    def rpc(self, args: list[str], script: list, timeout: float = 180.0,
            label: str | None = None) -> dict:
        """Run Pi in RPC mode. ``script`` items are command dicts, or callables taking the
        list of records so far and returning a command dict (or None to skip). After a
        ``prompt`` the driver waits for ``agent_settled``."""
        label = label or f"rpc{len(self.runs) + 1}"
        t0 = time.time()
        p = subprocess.Popen(self.argv(["--mode", "rpc"] + args), cwd=self.work, env=self.env(),
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        records: list[dict] = []
        cond = threading.Condition()

        def reader():
            for line in p.stdout:
                try:
                    r = json.loads(line.rstrip(b"\r\n"))
                except ValueError:
                    continue
                with cond:
                    records.append(r)
                    cond.notify_all()

        err_chunks: list[bytes] = []
        threading.Thread(target=reader, daemon=True).start()
        threading.Thread(target=lambda: err_chunks.extend(p.stderr), daemon=True).start()

        def wait_for(pred, start: int, limit: float) -> dict | None:
            end = time.time() + limit
            with cond:
                while True:
                    for r in records[start:]:
                        if pred(r):
                            return r
                    left = end - time.time()
                    if left <= 0:
                        return None
                    cond.wait(left)

        ok_all = True
        for i, item in enumerate(script):
            cmd = item(records) if callable(item) else dict(item)
            if cmd is None:
                continue
            cmd.setdefault("id", f"c{i}")
            start = len(records)
            p.stdin.write(json.dumps(cmd).encode() + b"\n")
            p.stdin.flush()
            cid = cmd["id"]
            resp = wait_for(lambda r, cid=cid: r.get("type") == "response" and r.get("id") == cid,
                            start, 60)
            if resp is None:
                ok_all = False
                break
            disposition = (resp.get("data") or {}).get("disposition")
            if cmd["type"] == "prompt" and disposition == "handled":
                time.sleep(1.5)  # an extension command: no run; let its async work finish
            elif (cmd["type"] == "prompt" and resp.get("success")
                  and wait_for(lambda r: r.get("type") == "agent_settled", start,
                               timeout) is None):
                ok_all = False
                break
        p.stdin.close()
        try:
            p.wait(15)
        except subprocess.TimeoutExpired:
            p.kill()
        rec = {"label": label, "args": args, "rc": p.returncode, "completed": ok_all,
               "seconds": round(time.time() - t0, 2)}
        with (self.dir / f"{label}.rpc.jsonl").open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        (self.dir / f"{label}.stderr.txt").write_bytes(b"".join(err_chunks))
        self.runs.append(rec)
        return rec

    def requests(self) -> list[dict]:
        path = self.dir / "server.jsonl"
        if not path.exists():
            return []
        return [r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())
                if r["event"] == "request"]

    def _start_proxy(self, upstream_port: int) -> int:
        import socket

        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            port = sk.getsockname()[1]
        self.proxy_log = open(self.dir / "serve.log", "wb")
        self.proxy = subprocess.Popen(
            [sys.executable, "-m", "palimnesis", "serve", "--port", str(port),
             "--upstream", f"http://127.0.0.1:{upstream_port}", "--db", str(self.dir / "archive.db"),
             "--transcripts", str(self.dir / "transcripts")],
            stdout=self.proxy_log, stderr=subprocess.STDOUT)
        end = time.time() + 60
        while time.time() < end:
            with socket.socket() as sk:
                if sk.connect_ex(("127.0.0.1", port)) == 0:
                    return port
            time.sleep(0.3)
        raise RuntimeError("palimnesis serve did not start")

    def close(self) -> None:
        if self.proxy:
            self.proxy.terminate()
            try:
                self.proxy.wait(30)
            except subprocess.TimeoutExpired:
                self.proxy.kill()
            self.proxy_log.close()
        if self.server:
            self.server.stop()
        (self.dir / "meta.json").write_text(
            json.dumps({**self.meta, "runs": self.runs}, indent=2), encoding="utf-8")


def last_records(probe: Probe, label: str) -> list[dict]:
    path = probe.dir / f"{label}.rpc.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def prompt(msg: str) -> dict:
    return {"type": "prompt", "message": msg}


# ---------------------------------------------------------------------------
# Probes. Each returns the Probe (closed). Names are the CLI arguments.

PROBES: dict[str, callable] = {}


def probe(fn):
    PROBES[fn.__name__] = fn
    return fn


def _simple(name, plan, protocol="chat", args=None, timeout=120, **kw) -> Probe:
    pr = Probe(name, plan, protocol, **kw)
    try:
        pr.pi(["--mode", "json", "-nc"] + (args or []) + ["Reply with the single word OK."],
              timeout=timeout)
    finally:
        pr.close()
    return pr


# HP1 joining -----------------------------------------------------------------

@probe
def hp1_join_chat():
    return _simple("hp1_join_chat", [ok()], "chat")


@probe
def hp1_join_chat_trailing_slash():
    return _simple("hp1_join_chat_trailing_slash", [ok()], "chat",
                   base="http://127.0.0.1:{port}/s/probe-sess/v1/")


@probe
def hp1_join_messages():
    return _simple("hp1_join_messages", [ok()], "messages")


@probe
def hp1_join_messages_v1():
    return _simple("hp1_join_messages_v1", [ok()], "messages",
                   base="http://127.0.0.1:{port}/s/probe-sess/v1")


# HP2 association ---------------------------------------------------------------

def _session_walk(name: str, protocol: str) -> Probe:
    """prompt; new_session; prompt; fork from the first user entry; prompt; clone; prompt;
    switch_session back to the first file; prompt. Then restart with --session <first id>."""
    pr = Probe(name, [answer("Answer ATTEMPT", reasoning="Reasoning ATTEMPT")], protocol,
               extension=HEADER_EXTENSION)
    try:
        state: dict = {}

        def remember(recs):
            # the last get_state response
            for r in reversed(recs):
                if r.get("type") == "response" and r.get("command") == "get_state":
                    return r["data"]
            return {}

        def fork_cmd(recs):
            for r in reversed(recs):
                if r.get("type") == "response" and r.get("command") == "get_fork_messages":
                    msgs = r["data"]["messages"]
                    return {"type": "fork", "entryId": msgs[0]["entryId"]}
            return None

        def switch_back(recs):
            first = None
            for r in recs:
                if r.get("type") == "response" and r.get("command") == "get_state":
                    first = r["data"].get("sessionFile")
                    break
            state["first_file"] = first
            return {"type": "switch_session", "sessionPath": first}

        script = [
            {"type": "get_state"},
            prompt("Turn one in session A."),
            {"type": "new_session"},
            {"type": "get_state"},
            prompt("Turn one in session B (after new_session)."),
            {"type": "get_fork_messages"},
            fork_cmd,
            {"type": "get_state"},
            prompt("Turn in the fork."),
            {"type": "clone"},
            {"type": "get_state"},
            prompt("Turn in the clone."),
            switch_back,
            {"type": "get_state"},
            prompt("Turn two in session A (after switch back)."),
        ]
        pr.rpc([], script, label="walk")
        recs = last_records(pr, "walk")
        first_state = next(r["data"] for r in recs
                           if r.get("type") == "response" and r.get("command") == "get_state")
        sid = first_state.get("sessionId")
        # Restart: resume session A by id, one more prompt.
        pr.rpc(["--session", sid], [{"type": "get_state"}, prompt("Turn three in A after restart.")],
               label="restart")
        # Restart with --continue (most recent session for the folder).
        pr.rpc(["--continue"], [{"type": "get_state"}, prompt("Turn after --continue.")],
               label="continue")
        # Driver-chosen id: --session-id makes Pi's id equal a Palimnesis id.
        pr.rpc(["--session-id", "pal-0123abcd"], [{"type": "get_state"}, prompt("Chosen id.")],
               label="chosen_id")
    finally:
        pr.close()
    return pr


@probe
def hp2_sessions_chat():
    return _session_walk("hp2_sessions_chat", "chat")


@probe
def hp2_sessions_messages():
    return _session_walk("hp2_sessions_messages", "messages")


TREE_EXTENSION = HEADER_EXTENSION.rstrip().rstrip("}") + """
  // /probe-tree <entryId> [summarize]: what /tree navigation does to the next request.
  pi.registerCommand("probe-tree", {
    description: "probe: navigate the session tree",
    handler: async (args, ctx) => {
      const [id, mode] = (args || "").trim().split(/\\s+/);
      await ctx.waitForIdle();
      const r = await ctx.navigateTree(id, { summarize: mode === "summarize" });
      console.error(`[probe-tree] ${JSON.stringify(r)} id=${ctx.sessionManager.getSessionId()}`);
    },
  });
}
"""


def _tree(name: str, summarize: bool) -> Probe:
    """Two turns, then /tree to the first user entry (edit-and-resubmit), then a prompt."""
    pr = Probe(name, [answer("Answer ATTEMPT", reasoning="Reasoning ATTEMPT")], "chat",
               extension=TREE_EXTENSION, settings={"branchSummary": {"skipPrompt": True}})
    try:
        def nav(recs):
            for r in reversed(recs):
                if r.get("type") == "response" and r.get("command") == "get_fork_messages":
                    eid = r["data"]["messages"][-1]["entryId"]
                    return prompt(f"/probe-tree {eid}" + (" summarize" if summarize else ""))
            return None

        pr.rpc([], [prompt("First prompt."), prompt("Second prompt."),
                    {"type": "get_fork_messages"}, nav, {"type": "get_state"},
                    prompt("Replacement second prompt.")], label="tree")
    finally:
        pr.close()
    return pr


@probe
def hp2_tree():
    return _tree("hp2_tree", False)


@probe
def hp2_tree_summarize():
    return _tree("hp2_tree_summarize", True)


@probe
def hp2_affinity_headers():
    """Pi's native session headers (compat.sendSessionAffinityHeaders) and $ENV headers."""
    pr = Probe("hp2_affinity_headers", [ok()], "chat",
               compat={"sendSessionAffinityHeaders": True},
               provider_headers={"X-Palimnesis-Session": "$PALIMNESIS_SESSION"})
    try:
        os.environ["PALIMNESIS_SESSION"] = "env-session-42"
        pr.pi(["--mode", "json", "-nc", "Reply OK."])
    finally:
        os.environ.pop("PALIMNESIS_SESSION", None)
        pr.close()
    return pr


# HP3 shapes ---------------------------------------------------------------------

def _tool_loop(name: str, protocol: str, *, compat=None, model=None) -> Probe:
    pr = Probe(name, SCENARIOS["tool_loop"][1], protocol, compat=compat, model=model)
    try:
        pr.rpc([], [{"type": "get_state"}, prompt("Read notes.txt and tell me what it says."),
                    prompt("Thanks. Anything else?")], label="turns")
        recs = last_records(pr, "turns")
        sid = next(r["data"]["sessionId"] for r in recs
                   if r.get("type") == "response" and r.get("command") == "get_state")
        pr.rpc(["--session", sid], [prompt("Third turn after restart.")], label="restart")
    finally:
        pr.close()
    return pr


@probe
def hp3_chat_default():
    return _tool_loop("hp3_chat_default", "chat")


@probe
def hp3_chat_compat():
    return _tool_loop("hp3_chat_compat", "chat",
                      compat={"supportsDeveloperRole": False, "supportsStore": False,
                              "supportsReasoningEffort": False, "maxTokensField": "max_tokens"})


@probe
def hp3_chat_bigwindow():
    """contextWindow 1,000,000: does max_completion_tokens still shrink with input?"""
    return _simple("hp3_chat_bigwindow", [ok()], "chat",
                   model={"contextWindow": 1_000_000, "maxTokens": 8192})


@probe
def hp3_chat_smallwindow():
    """contextWindow 12000 with maxTokens 8192: clamp visible on the first request."""
    return _simple("hp3_chat_smallwindow", [ok()], "chat",
                   model={"contextWindow": 12000, "maxTokens": 8192})


@probe
def hp3_messages_default():
    return _tool_loop("hp3_messages_default", "messages")


@probe
def hp3_messages_empty_sig_allowed():
    return _tool_loop("hp3_messages_empty_sig_allowed", "messages",
                      compat={"allowEmptySignature": True})


COMPOSITE = [("start",), ("reasoning", "R1 first thought ATTEMPT\n"), ("text", "T1 first visible."),
             ("reasoning", "\nR2 second thought\n"), ("text", " T2 second visible."),
             ("finish", "stop"), ("usage", 10, 5), ("done",)]
WS_TOOL = [("start",), ("reasoning", "  "), ("text", "\n\n"),
           ("tool_call", "call_ws_1", "read", ['{"path": ', '"notes.txt"}']),
           ("finish", "tool_calls"), ("usage", 10, 5), ("done",)]


def _replay(name: str, protocol: str, first: list, compat=None) -> Probe:
    """One response shape, then a plain answer; the resend shows how Pi replays it."""
    pr = Probe(name, [Stream(first), ok(), ok()], protocol, compat=compat)
    try:
        pr.rpc([], [prompt("First prompt."), prompt("Second prompt.")], label="turns")
    finally:
        pr.close()
    return pr


@probe
def hp3_chat_composite():
    """Reasoning/text/reasoning/text in one response (Palimnesis hidden-stream shape)."""
    return _replay("hp3_chat_composite", "chat", COMPOSITE)


@probe
def hp3_messages_composite():
    return _replay("hp3_messages_composite", "messages", COMPOSITE,
                   compat={"allowEmptySignature": True})


@probe
def hp3_chat_whitespace_tool():
    """Whitespace-only reasoning and text before a tool call."""
    return _replay("hp3_chat_whitespace_tool", "chat", WS_TOOL)


@probe
def hp3_messages_signed():
    """Thinking blocks with a non-empty signature (control for replay)."""
    plan = [
        Stream([("start",), ("reasoning", "I should read notes ATTEMPT"), ("sig", "c2lnLTE="),
                ("tool_call", "call_pi_1", "read", ['{"path": "no', 'tes.txt"}']),
                ("finish", "tool_calls"), ("usage", 10, 5), ("done",)]),
        Stream([("start",), ("reasoning", "Got the note ATTEMPT"), ("sig", "c2lnLTI="),
                ("text", "The note says hello ATTEMPT"), ("finish", "stop"), ("usage", 10, 5),
                ("done",)]),
        answer("Second turn ATTEMPT"),
    ]
    pr = Probe("hp3_messages_signed", plan, "messages")
    try:
        pr.rpc([], [prompt("Read notes.txt and tell me what it says."), prompt("Thanks.")],
               label="turns")
    finally:
        pr.close()
    return pr


# HP4 timeouts and retries ---------------------------------------------------------

def _retry(name, plan, protocol="chat", settings=None, timeout=150, **kw):
    return _simple(name, plan, protocol, settings=settings, timeout=timeout, **kw)


SHORT_IDLE = {"httpIdleTimeoutMs": 5000}
RETRY_OFF = {"retry": {"enabled": False}}

for _scn in ["s500", "s500_then_ok", "s409_then_ok", "s429_then_ok", "s429_ra7_then_ok",
             "s503_noretry_then_ok", "s409_shouldretry_then_ok", "s400_then_ok",
             "s409_divergence_then_ok", "role_only_eof_then_ok", "finish_no_done",
             "partial_length"]:
    def _mk(scn=_scn):
        def f():
            return _retry(f"hp4_{scn}", SCENARIOS[scn][1])
        f.__name__ = f"hp4_{scn}"
        return f
    probe(_mk())

for _scn in ["partial_eof_then_ok", "partial_abort_then_ok", "partial_error_then_ok",
             "partial_error_noretry_then_ok", "partial_error_plain_then_ok",
             "partial_tool_error_then_ok"]:
    for _proto in ["chat", "messages"]:
        for _off in [False, True]:
            def _mk(scn=_scn, proto=_proto, off=_off):
                nm = f"hp4_{scn}_{proto}" + ("_retryoff" if off else "")

                def f():
                    # Two turns so the resend after the failure shows what Pi kept.
                    pr = Probe(nm, SCENARIOS[scn][1], proto,
                               settings=RETRY_OFF if off else None)
                    try:
                        pr.rpc([], [prompt("First prompt."), prompt("Second prompt.")],
                               label="turns")
                    finally:
                        pr.close()
                    return pr
                f.__name__ = nm
                return f
            probe(_mk())

for _scn in ["header_delay8_then_ok", "idle_after_start_then_ok", "idle_after_text_then_ok",
             "comments_12s", "comments_after_start_12s"]:
    for _proto in ["chat", "messages"]:
        def _mk(scn=_scn, proto=_proto):
            nm = f"hp4_{scn}_{proto}"

            def f():
                return _retry(nm, SCENARIOS[scn][1], proto, settings=SHORT_IDLE)
            f.__name__ = nm
            return f
        probe(_mk())

for _scn in ["pings_after_start_12s", "pings_before_start_12s"]:
    def _mk(scn=_scn):
        nm = f"hp4_{scn}_messages"

        def f():
            return _retry(nm, SCENARIOS[scn][1], "messages", settings=SHORT_IDLE)
        f.__name__ = nm
        return f
    probe(_mk())


@probe
def hp4_s500_default_delay():
    """Default retry settings (baseDelayMs 2000): the real agent backoff schedule."""
    return _retry("hp4_s500_default_delay", SCENARIOS["s500"][1],
                  settings={"retry": {"baseDelayMs": 2000}})


@probe
def hp4_provider_retry_429():
    """retry.provider.maxRetries 2 with the agent retry off: who honours retry-after."""
    return _retry("hp4_provider_retry_429", SCENARIOS["s429_ra7_then_ok"][1],
                  settings={"retry": {"enabled": False, "provider": {"maxRetries": 2}}})


@probe
def hp4_provider_retry_409_noretry():
    return _retry("hp4_provider_retry_409_noretry", SCENARIOS["s409_divergence_then_ok"][1],
                  settings={"retry": {"enabled": False, "provider": {"maxRetries": 2}}})


# HX: the HP4 faults through Palimnesis (Phase 4B S14) ----------------------------
# Pi with the adapter's compat flags and its own default timers -> palimnesis serve ->
# the fault server. ``eval/probes/pi_proxy_faults.py`` summarizes the archives.

HX_COMPAT = {"chat": {"supportsDeveloperRole": False, "supportsStore": False},
             "messages": {"allowEmptySignature": True}}

for _scn in ["partial_eof_then_ok", "partial_abort_then_ok", "partial_error_then_ok",
             "partial_tool_error_then_ok", "s500_then_ok", "s429_then_ok",
             "s503_noretry_then_ok", "role_only_eof_then_ok", "finish_no_done",
             "partial_length", "header_delay8_then_ok", "comments_after_start_12s"]:
    for _proto in ["chat", "messages"]:
        for _off in ([False, True] if _scn.startswith("partial_") else [False]):
            def _mk(scn=_scn, proto=_proto, off=_off):
                nm = f"hx_{scn}_{proto}" + ("_retryoff" if off else "")

                def f():
                    pr = Probe(nm, SCENARIOS[scn][1], proto, via_proxy=True,
                               compat=HX_COMPAT[proto], settings=RETRY_OFF if off else None)
                    try:
                        pr.rpc([], [prompt("First prompt."), prompt("Second prompt.")],
                               label="turns", timeout=240)
                    finally:
                        pr.close()
                    return pr
                f.__name__ = nm
                return f
            probe(_mk())


# HP5 compaction -------------------------------------------------------------------

def _compaction(name, enabled: bool, plan) -> Probe:
    pr = Probe(name, plan, "chat",
               settings={"compaction": {"enabled": enabled, "keepRecentTokens": 10},
                         "retry": {"enabled": True}})
    try:
        pr.rpc([], [prompt("First prompt."), prompt("Second prompt."),
                    prompt("Third prompt."), prompt("Fourth prompt.")], label="turns")
    finally:
        pr.close()
    return pr


# Two ordinary turns first, so a compaction has something to summarize (keepRecentTokens 10).
THRESHOLD_PLAN = [ok(), answer("Big ATTEMPT", prompt_tokens=30000), ok()]
OVERFLOW_PLAN = [ok(), ok(), Status(400, {}, "the request exceeds the available context size, "
                                             "try increasing it"), ok()]


@probe
def hp5_threshold_off():
    return _compaction("hp5_threshold_off", False, THRESHOLD_PLAN)


@probe
def hp5_threshold_on():
    return _compaction("hp5_threshold_on", True, THRESHOLD_PLAN)


@probe
def hp5_overflow_off():
    return _compaction("hp5_overflow_off", False, OVERFLOW_PLAN)


@probe
def hp5_overflow_on():
    return _compaction("hp5_overflow_on", True, OVERFLOW_PLAN)


@probe
def hp5_manual_compact():
    pr = Probe("hp5_manual_compact", [answer("Answer ATTEMPT", reasoning="Reasoning ATTEMPT")],
               "chat", settings={"compaction": {"enabled": False, "keepRecentTokens": 10}})
    try:
        pr.rpc([], [prompt("First prompt."), prompt("Second prompt."), {"type": "compact"},
                    prompt("After compaction.")], label="turns")
    finally:
        pr.close()
    return pr


# HP6 gate: read/grep/bash outside the working folder ---------------------------------

@probe
def hp6_gate():
    outside = ROOT / "hp6_outside"
    outside.mkdir(parents=True, exist_ok=True)
    (outside / "transcript.md").write_text("NEEDLE-7731 lives here\n", encoding="utf-8")
    tpath = str(outside / "transcript.md").replace("\\", "/")
    tdir = str(outside).replace("\\", "/")
    plan = [
        tool_turn("call_r", "read", {"path": tpath}),
        tool_turn("call_g", "grep", {"pattern": "NEEDLE", "path": tdir}),
        tool_turn("call_b", "bash", {"command": f"grep -rn NEEDLE '{tdir}'"}),
        tool_turn("call_l", "ls", {"path": tdir}),
        tool_turn("call_f", "find", {"pattern": "*.md", "path": tdir}),
        answer("done"),
    ]
    pr = Probe("hp6_gate", plan, "chat")
    try:
        pr.pi(["--mode", "json", "-nc", "--tools", "read,grep,bash,ls,find",
               "Search the transcripts."], timeout=120)
    finally:
        pr.close()
    return pr


@probe
def hp6_default_tools():
    """First request with default tools and no context files: F is system + tools."""
    return _simple("hp6_default_tools", [ok()], "chat")


# HP7 driving ------------------------------------------------------------------------

@probe
def hp7_print_mode():
    pr = Probe("hp7_print_mode", [ok()], "chat")
    try:
        pr.pi(["-p", "-nc", "Reply with the single word OK."], label="print")
        pr.pi(["-p", "-nc", "--no-session", "Reply OK (no session)."], label="nosession")
    finally:
        pr.close()
    return pr


@probe
def hp7_import():
    """A hand-built session file (no system entry), opened with --session <path>."""
    pr = Probe("hp7_import", [ok()], "chat")
    try:
        sid = "import-0001"
        cwd = str(pr.work)
        lines = [
            {"type": "session", "version": 3, "id": sid, "timestamp": "2026-11-05T10:00:00.000Z",
             "cwd": cwd},
            {"type": "message", "id": "a0000001", "parentId": None,
             "timestamp": "2026-11-05T10:00:01.000Z",
             "message": {"role": "user", "content": [{"type": "text", "text": "Imported user turn 1"}],
                         "timestamp": 1793872801000}},
            {"type": "message", "id": "a0000002", "parentId": "a0000001",
             "timestamp": "2026-11-05T10:00:02.000Z",
             "message": {"role": "assistant",
                         "content": [{"type": "text", "text": "Imported assistant turn 1"}],
                         "api": "openai-completions", "provider": "fault", "model": "m",
                         "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0,
                                   "totalTokens": 0,
                                   "cost": {"input": 0, "output": 0, "cacheRead": 0,
                                            "cacheWrite": 0, "total": 0}},
                         "stopReason": "stop", "timestamp": 1793872802000}},
        ]
        f = pr.dir / "imported.jsonl"
        f.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
        pr.pi(["--mode", "json", "-nc", "--session", str(f), "Next turn after import."],
              label="import")
    finally:
        pr.close()
    return pr


# Real-model shapes through a local passthrough ---------------------------------------
# Start first:  uv run palimnesis serve --passthrough --port 9311 \
#                   --upstream http://192.168.1.8:8080 --capture-dir <dir>
# then set PI_PROBE_PASSTHROUGH=http://127.0.0.1:9311 and PI_PROBE_MODEL (e.g. qwen36).

def _mbp(name: str, protocol: str) -> Probe:
    origin = os.environ["PI_PROBE_PASSTHROUGH"].rstrip("/")
    base = f"{origin}/s/{name}/v1" if protocol == "chat" else f"{origin}/s/{name}"
    pr = Probe(name, [], protocol, upstream_base=base,
               model={"id": os.environ.get("PI_PROBE_MODEL", "qwen36"), "maxTokens": 4096})
    try:
        pr.rpc([], [{"type": "get_state"},
                    prompt("Use the read tool to read notes.txt, then tell me its exact content."),
                    prompt("Now reply with the single word DONE.")], label="turns", timeout=600)
    finally:
        pr.close()
    return pr


@probe
def mbp_chat_tool_loop():
    return _mbp("mbp_chat_tool_loop", "chat")


@probe
def mbp_messages_tool_loop():
    return _mbp("mbp_messages_tool_loop", "messages")


# ---------------------------------------------------------------------------
# Summary


def summarize(rundir: Path) -> str:
    reqs = [r for r in map(json.loads, (rundir / "server.jsonl").read_text(
        encoding="utf-8").splitlines()) if r["event"] == "request"]
    out = [f"== {rundir.name}: {len(reqs)} requests"]
    prev = None
    for r in reqs:
        hdr = {k.lower(): v for k, v in r["headers"]}
        body = r["body"] if isinstance(r["body"], dict) else {}
        msgs = body.get("messages", [])
        gap = "" if prev is None else f" gap={r['t'] - prev['t']:.2f}s"
        out.append(f"  #{r['seq']} {r['method']} {r['target']} attempt={r['attempt']}{gap} "
                   f"msgs={len(msgs)} sess={hdr.get('x-palimnesis-session')} "
                   f"step={r['step']}")
        if prev is not None and isinstance(prev["body"], dict) and msgs:
            pm = _strip_cc(prev["body"].get("messages", []))
            cm = _strip_cc(msgs)
            k = 0
            while k < min(len(pm), len(cm)) and pm[k] == cm[k]:
                k += 1
            note = f"     prefix kept {k}/{len(pm)}"
            if len(cm) > k:
                note += "; new: " + " | ".join(_short(m) for m in cm[k:])
            out.append(note)
        prev = r
    for line in (rundir / "server.jsonl").read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e["event"] in ("client_gone", "conn_error"):
            out.append(f"  server: t={e['t']} {e['event']} attempt={e.get('attempt')} "
                       f"during={e.get('during')}")
    out += ["  pi: " + x for x in outcomes(rundir)]
    return "\n".join(out)


def _strip_cc(x):
    if isinstance(x, dict):
        return {k: _strip_cc(v) for k, v in x.items() if k != "cache_control"}
    if isinstance(x, list):
        return [_strip_cc(v) for v in x]
    return x


def _short(m: dict) -> str:
    c = m.get("content")
    if isinstance(c, list):
        c = "+".join(f"{b.get('type')}:{(b.get('text') or b.get('thinking') or b.get('name') or '')!s}"[:60]
                     for b in c)
    extra = ""
    if m.get("reasoning_content"):
        extra += f" reasoning={m['reasoning_content'][:40]!r}"
    if m.get("tool_calls"):
        extra += f" tool_calls={[t['function']['name'] for t in m['tool_calls']]}"
    return f"{m.get('role')}:{str(c)[:70]!r}{extra}"


def outcomes(rundir: Path) -> list[str]:
    """Retry, compaction and end-of-run events from json-mode stdout or RPC records."""
    out = []
    for f in sorted(rundir.glob("*.stdout.txt")) + sorted(rundir.glob("*.rpc.jsonl")):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            t = r.get("type")
            if t == "auto_retry_start":
                out.append(f"{f.name}: retry attempt={r.get('attempt')}/{r.get('maxAttempts')} "
                           f"delayMs={r.get('delayMs')} err={str(r.get('errorMessage'))[:110]!r}")
            elif t == "auto_retry_end":
                out.append(f"{f.name}: retry_end success={r.get('success')} attempt={r.get('attempt')}")
            elif t in ("compaction_start", "compaction_end"):
                out.append(f"{f.name}: {t} reason={r.get('reason')} "
                           f"err={r.get('errorMessage')}")
            elif t == "agent_end":
                m = (r.get("messages") or [{}])[-1]
                out.append(f"{f.name}: agent_end stop={m.get('stopReason')} "
                           f"willRetry={r.get('willRetry')} "
                           f"err={str(m.get('errorMessage'))[:110]!r}")
    return out


def _sanitize(text: str, root: Path) -> str:
    """Replace the probe root and the user's home in any spelling with placeholders."""
    reps = []
    for base, tag in ((root, "<PROBE_ROOT>"), (Path.home(), "<HOME>")):
        s = str(base)
        for v in {s, s.replace("\\", "/"), s.replace("\\", "\\\\"), s.replace("/", "\\\\")}:
            reps.append((v, tag))
    # Pi's session folder name: the cwd with separators and ':' turned into '-'.
    reps.append((str(root).replace("\\", "-").replace("/", "-").replace(":", "-"), "<PROBE_ROOT_SLUG>"))
    for old, new in sorted(reps, key=lambda x: -len(x[0])):
        text = text.replace(old, new)
    # Truncated paths in summaries escape the exact replacements above.
    text = re.sub(r"AppData[/\\]+Local[/\\]+Temp[/\\]+claude[/\\]+[0-9a-zA-Z/\\._-]*", "<TMP>", text)
    return text.replace("dummy-probe-key", "<dummy>")


def _dedup_server_log(text: str) -> str:
    """Keep every request body exactly, except that ``tools``, ``system`` and a leading
    system/developer message identical to the first request's are written as
    ``{"$same_as_seq": 1}``. Response-milestone records are kept."""
    out, first = [], None
    for line in text.splitlines():
        r = json.loads(line)
        b = r.get("body")
        if r.get("event") == "request" and isinstance(b, dict):
            if first is None:
                first = (r["seq"], b)
            else:
                seq, fb = first
                for key in ("tools", "system"):
                    if key in b and b[key] == fb.get(key):
                        b[key] = {"$same_as_seq": seq}
                msgs, fmsgs = b.get("messages") or [], fb.get("messages") or []
                if (msgs and fmsgs and isinstance(msgs[0], dict) and msgs[0] == fmsgs[0]
                        and msgs[0].get("role") in ("system", "developer")):
                    msgs[0] = {"$same_as_seq": seq}
        out.append(json.dumps(r, ensure_ascii=False))
    return "\n".join(out) + "\n"


def _filter_rpc(text: str) -> str:
    """Keep command responses, retry/compaction events and each run's final assistant
    message (``agent_end`` trimmed to its last message); drop streaming and echo events."""
    keep = []
    for line in text.splitlines():
        r = json.loads(line)
        t = r.get("type", "")
        if t == "agent_end":
            r["messages"] = (r.get("messages") or [])[-1:]
        elif not (t == "response" or t == "agent_settled" or t.startswith(("auto_retry",
                                                                            "compaction"))):
            continue
        keep.append(json.dumps(r, ensure_ascii=False))
    return "\n".join(keep) + "\n"


def export_fixtures(dest: Path, runs: list[str], capture: Path | None) -> None:
    """Copy server logs (requests, sanitized) and RPC/JSON event streams of ``runs`` into
    ``dest``, plus ``summary.txt`` for every run under ROOT."""
    dest.mkdir(parents=True, exist_ok=True)
    for name in runs:
        d = ROOT / name
        out = dest / name
        out.mkdir(exist_ok=True)
        for f in [d / "server.jsonl", d / "meta.json", *d.glob("*.rpc.jsonl")]:
            if f.exists():
                text = f.read_text(encoding="utf-8")
                if f.name == "server.jsonl":
                    text = _dedup_server_log(text)
                elif f.name.endswith(".rpc.jsonl"):
                    text = _filter_rpc(text)
                (out / f.name).write_text(_sanitize(text, ROOT), encoding="utf-8")
    summaries = [summarize(d) for d in sorted(ROOT.iterdir())
                 if (d / "server.jsonl").exists()]
    (dest / "summary.txt").write_text(_sanitize("\n".join(summaries), ROOT) + "\n",
                                      encoding="utf-8")
    if capture:
        for sess in capture.iterdir():
            for ex in sess.iterdir():
                o = dest / "mbp" / sess.name / ex.name
                o.mkdir(parents=True, exist_ok=True)
                for f in ex.iterdir():
                    o.joinpath(f.name).write_text(
                        _sanitize(f.read_text(encoding="utf-8", errors="replace"), ROOT),
                        encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("probes", nargs="*")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--summary", type=Path)
    ap.add_argument("--export", type=Path, help="write fixtures for the named runs here")
    ap.add_argument("--capture", type=Path, help="with --export: a passthrough capture dir")
    args = ap.parse_args()
    if args.list:
        print("\n".join(PROBES))
        return
    if args.summary:
        print(summarize(args.summary))
        return
    if args.export:
        export_fixtures(args.export, args.probes, args.capture)
        return
    for name in args.probes:
        matches = [n for n in PROBES if n == name or (name.endswith("*") and
                                                     n.startswith(name[:-1]))]
        for n in matches:
            t0 = time.time()
            pr = PROBES[n]()
            print(summarize(pr.dir), f"\n  runs={pr.runs} ({time.time() - t0:.1f}s)", flush=True)


if __name__ == "__main__":
    main()
