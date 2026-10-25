"""Phase 3 development needle evaluation: the O3 hybrid OpenCode emulator (plan §5, A1).

EMULATOR, not real OpenCode. It replays OpenCode 2.1.4's captured system prompt and
11 tools (``eval/fixtures/opencode-2.1.4/live/exchanges``), posts OpenCode-shaped
streaming requests to the proxy at ``/s/<session>/v1/chat/completions`` (prior assistant
turns resent without ``reasoning_content``; the proxy restores archived reasoning), and
executes the model's tool calls itself with OpenCode 2.1.4 output formats and limits read
from the 2.1.4 bundle (read: 2,000 lines / 50 KB pages, ``Read file P, lines a-b``;
grep: ripgrep ``--hidden``, ``Found N matches`` / ``  Line n: text``, 100 matches; glob;
shell through Git Bash). Shell runs only read-only allow-listed commands (grep, rg, sed -n,
head, tail, cat, wc, ls, find, awk, sort, uniq, cut, nl) or a history's scripted
command; anything else gets a tool error. Paths outside the session workspace and the
transcripts root are reported as not found. At most 8 tool calls are executed per
question (``--max-tools``); further calls get a tool error.

Topology: emulator -> proxy child process (``needle.py proxy``, same app and uvicorn config
as ``palimnesis serve``) -> upstream gate (in-process tap) -> Strata. The gate enforces D39:
before every inference request it waits for an idle slot on ``/status`` (busy false,
queued 0) with jittered back-off, one request at a time; it records foreign requests from
the ``/v1/status`` activity counter before, during and after each call, and aborts the run
if the slot stays busy for more than 20 minutes. It also keeps each exact upstream body
(scratch only), which decides whether a needle was in the model's context and whether it
came from an excerpt block.

Subcommands:
  run        --config NAME --out RUNDIR [--histories h1,h2] [--questions N] [--upstream URL|fake]
             [--driver emulator|opencode] [--set development|heldout]
             [--reason TEXT] [--ws-root DIR] [--expect-n-ctx N]   (opencode driver)
  preflight  [--set heldout] [--histories h1,h2]: imports through real OpenCode, fake upstream
  proxy      (internal) the proxy child

``--driver opencode`` (``eval/needle_opencode.py``) runs each history through real
OpenCode 2.1.4 instead: ``opencode session import``, then one ``opencode run --session``
per step, against the default ``serve`` budget (no ``--input-budget``). Held-out
histories (``--set heldout``) run only that way (D44.2).

Configurations (A1 arms on the emulated 32K budget, --input-budget 24320 at 64K capacity):
  a4-base  excerpts + transcripts, q1/x1/a3     a3-base  excerpts, no transcripts (a0)
  a2-base  transcripts + a3, recall off          a4-q2 / a4-x2 / a4-a4  one factor changed
  a4-d43   the frozen configuration (D43): q1/x2/a3 with transcripts
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import random
import re
import shlex
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "eval" / "fixtures" / "opencode-2.1.4" / "live" / "exchanges"
NEEDLES = ROOT / "eval" / "needles" / "dev"
SETS = {"development": ("dev", "dev"), "heldout": ("heldout", "ho")}  # --set: (dir, id prefix)
INPUT_BUDGET = 24_320
MAX_TOOLS = 8
MAX_ROUNDS = 12
BUSY_ABORT_S = 20 * 60
EMULATOR_VERSION = "needle-emulator v2"

CONFIGS = {
    "a4-base": dict(arm=4, recall="fts", transcripts_enabled=True, query_policy="q1",
                    excerpt_renderer="x1", addendum="a3"),
    "a3-base": dict(arm=3, recall="fts", transcripts_enabled=False, query_policy="q1",
                    excerpt_renderer="x1", addendum="a3"),
    "a2-base": dict(arm=2, recall="off", transcripts_enabled=True, query_policy="q1",
                    excerpt_renderer="x1", addendum="a3"),
    "a4-q2": dict(arm=4, recall="fts", transcripts_enabled=True, query_policy="q2",
                  excerpt_renderer="x1", addendum="a3"),
    "a4-x2": dict(arm=4, recall="fts", transcripts_enabled=True, query_policy="q1",
                  excerpt_renderer="x2", addendum="a3"),
    "a4-a4": dict(arm=4, recall="fts", transcripts_enabled=True, query_policy="q1",
                  excerpt_renderer="x1", addendum="a4"),
    # D43: the frozen Phase 3 configuration (equal to a4-x2), for held-out runs.
    "a4-d43": dict(arm=4, recall="fts", transcripts_enabled=True, query_policy="q1",
                   excerpt_renderer="x2", addendum="a3"),
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def dumps(obj) -> bytes:
    # JSON.stringify shape: no spaces, non-ASCII kept.
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------- OpenCode head

def opencode_head(workspace: Path) -> tuple[str, list, str]:
    live = sorted(LIVE.glob("*/*"))[-1]
    body = json.loads((live / "request.body").read_text(encoding="utf-8"))
    system = body["messages"][0]["content"]
    # The <env> block names the capture's working directory; OpenCode writes the
    # current one there, so the emulator substitutes its workspace (nothing else changes).
    m = re.search(r"Working directory: (.+)", system)
    old_cwd = m.group(1).strip()
    old_base = old_cwd.rsplit("\\", 1)[0]
    system = system.replace(old_cwd, str(workspace)).replace(old_base, str(workspace.parent))
    return system, body["tools"], body["model"]


# ---------------------------------------------------------------- Strata status

class SlotGate:
    """D39 pacing on the shared slot."""

    def __init__(self, upstream: str | None):
        self.upstream = upstream
        self.events: list[dict] = []

    def _status(self, client) -> tuple[dict, dict]:
        s = client.get(f"{self.upstream}/status", timeout=10).json()
        v = client.get(f"{self.upstream}/v1/status", timeout=10).json()
        return s, v

    def wait_idle(self, client: httpx.Client, who: str) -> dict:
        if self.upstream is None:
            return {"waited_s": 0.0, "busy_polls": 0}
        t0, k, busy_polls = time.time(), 0, 0
        while True:
            try:
                s, v = self._status(client)
            except Exception as e:  # status endpoint unreachable: back off too
                s, v = {"busy": True, "queued": -1, "error": type(e).__name__}, {}
            if not s.get("busy") and not s.get("queued"):
                return {"waited_s": round(time.time() - t0, 2), "busy_polls": busy_polls,
                        "activity": (v.get("activity") or {}).get("requests")}
            busy_polls += 1
            waited = time.time() - t0
            if busy_polls == 1:
                self.events.append({"t": t0, "who": who, "event": "busy_before_request",
                                    "queued": s.get("queued"), "phase": s.get("phase")})
            if waited > BUSY_ABORT_S:
                raise SlotBusyTooLong(f"slot busy for {waited:.0f}s")
            delay = min(30.0, 2.0 * 1.5 ** k) * random.uniform(0.7, 1.3)
            k += 1
            time.sleep(delay)

    def activity(self, client) -> int | None:
        if self.upstream is None:
            return None
        try:
            return client.get(f"{self.upstream}/v1/status", timeout=10).json()["activity"]["requests"]
        except Exception:
            return None


class SlotBusyTooLong(RuntimeError):
    pass


# ---------------------------------------------------------------- upstream tap

class Tap:
    """ASGI forwarder between the proxy and Strata: gates inference on an idle slot,
    records each upstream call (body to scratch, usage, timings, foreign activity).

    With ``SlotGate(None)`` it is the front tap between a client and the proxy: no gate,
    and each record holds the proxy's own response status and stream error, so a proxy
    rejection is told apart from an upstream failure without reading logs.

    Bodies are numbered after any already in ``bodies``, so a second tap on the same
    directory never overwrites an earlier run's files."""

    def __init__(self, upstream: str, bodies: Path, gate: SlotGate):
        self.upstream, self.bodies, self.gate = upstream.rstrip("/"), bodies, gate
        self.calls: list[dict] = []
        self.client: httpx.AsyncClient | None = None
        self.last_after: int | None = None
        self.abort: str | None = None
        self.inflight = 0  # inference calls not yet recorded in ``calls``
        bodies.mkdir(parents=True, exist_ok=True)
        self.next_n = max((int(f.name[:4]) for f in bodies.glob("[0-9][0-9][0-9][0-9].json")),
                          default=0)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    self.client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=15))
                    await send({"type": "lifespan.startup.complete"})
                elif msg["type"] == "lifespan.shutdown":
                    await self.client.aclose()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        body = bytearray()
        while True:
            msg = await receive()
            if msg["type"] == "http.request":
                body.extend(msg.get("body", b""))
                if not msg.get("more_body"):
                    break
            else:
                return
        path = scope["path"]
        qs = scope.get("query_string", b"").decode()
        inference = scope["method"] == "POST" and (
            path.endswith("/chat/completions") or path.endswith("/responses")
            or (path.endswith("/messages") and "count_tokens" not in path))
        headers = [(k, v) for k, v in scope["headers"]
                   if k.lower() not in (b"host", b"content-length", b"connection")]
        rec: dict = {}
        stop = asyncio.Event()
        samples: list = []
        if inference:
            self.inflight += 1
            self.next_n += 1
            n = self.next_n
            rec = {"n": n, "t_arrival": time.time(), "req_bytes": len(body), "path": path}
            if self.gate.upstream is not None:
                try:
                    pre = await asyncio.to_thread(self._gate_sync, n)
                except SlotBusyTooLong as e:
                    self.abort = str(e)
                    self.inflight -= 1
                    await self._reply(send, 503, b'{"error":{"message":"slot busy too long"}}')
                    return
                rec.update(pre)
                if self.last_after is not None and pre.get("activity") is not None:
                    rec["foreign_between"] = pre["activity"] - self.last_after
            (self.bodies / f"{n:04d}.json").write_bytes(bytes(body))
            rec["t_dispatch"] = time.time()

            async def monitor():
                while not stop.is_set():
                    try:
                        s = (await self.client.get(f"{self.upstream}/status", timeout=10)).json()
                        samples.append((round(time.time() - rec["t_arrival"], 1), s.get("busy"),
                                        s.get("queued"), s.get("prompt_tokens"), s.get("generated")))
                    except Exception:
                        pass
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(stop.wait(), 3.0)

            mon = asyncio.create_task(monitor()) if self.gate.upstream is not None else None
        url = f"{self.upstream}{path}" + (f"?{qs}" if qs else "")
        req = self.client.build_request(scope["method"], url, headers=headers, content=bytes(body))
        try:
            resp = await self.client.send(req, stream=True)
        except Exception:
            if inference:
                stop.set()
                self.inflight -= 1
            raise
        out = bytearray()
        rec["t_upstream_headers"] = time.time()
        try:
            await send({"type": "http.response.start", "status": resp.status_code, "headers": [
                (k, v) for k, v in resp.headers.raw
                if k.lower() not in (b"content-length", b"transfer-encoding", b"connection")]})
            async for chunk in resp.aiter_raw():
                if inference:
                    if "t_first_chunk" not in rec:
                        rec["t_first_chunk"] = time.time()
                    if "t_first_content" not in rec and VISIBLE.search(chunk):
                        rec["t_first_content"] = time.time()
                    out.extend(chunk)
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        except Exception as e:
            rec["relay_error"] = type(e).__name__
        finally:
            await resp.aclose()
            if inference:
                stop.set()
                if mon is not None:
                    with contextlib.suppress(Exception):
                        await mon
                rec["t_end"] = time.time()
                rec["upstream_s"] = round(rec["t_end"] - rec["t_dispatch"], 3)
                rec["status"] = resp.status_code
                rec.update(parse_usage(bytes(out)))
                # The raw upstream stream (scratch only), to tell upstream from relay defects.
                (self.bodies / f"{rec['n']:04d}.resp.sse").write_bytes(bytes(out))
                rec["status_samples"] = samples
                after = await asyncio.to_thread(self._activity_sync)
                if after is not None and rec.get("activity") is not None:
                    rec["foreign_during"] = after - rec["activity"] - 1
                    self.last_after = after
                # A queued sample whose prompt size is not ours means foreign work overlapped.
                ours = rec.get("prompt_tokens")
                rec["foreign_overlap_samples"] = sum(
                    1 for _, busy, queued, pt, _g in samples
                    if (queued or 0) > 0 or (busy and ours and pt not in (None, ours)))
                self.calls.append(rec)
                self.inflight -= 1

    def _activity_sync(self):
        with httpx.Client() as c:
            return self.gate.activity(c)

    def _gate_sync(self, n: int) -> dict:
        with httpx.Client() as c:
            return self.gate.wait_idle(c, f"tap#{n}")

    async def _reply(self, send, status, body):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})


# A streamed delta the client shows: text content or a tool call (not reasoning).
VISIBLE = re.compile(rb'"content": ?"[^"]|"tool_calls": ?\[')


def parse_usage(raw: bytes) -> dict:
    out: dict = {}
    for line in raw.split(b"\n"):
        if not line.startswith(b"data: ") or line.strip() == b"data: [DONE]":
            continue
        try:
            d = json.loads(line[6:])
        except ValueError:
            continue
        for ch in d.get("choices") or []:
            if ch.get("finish_reason"):
                out["finish"] = ch["finish_reason"]
        if d.get("error"):
            out["stream_error"] = json.dumps(d["error"], ensure_ascii=False)[:300]
        if d.get("usage"):
            u = d["usage"]
            out["prompt_tokens"] = u.get("prompt_tokens")
            out["completion_tokens"] = u.get("completion_tokens")
            out["cached_tokens"] = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
        if d.get("timings"):
            t = d["timings"]
            out["timings"] = {k: t.get(k) for k in ("cache_n", "prompt_n", "prompt_ms",
                                                    "predicted_n", "predicted_ms")}
    return out


def serve_in_thread(app, port: int):
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    th = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    th.start()
    deadline = time.monotonic() + 20
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("server failed to start")
        time.sleep(0.02)
    return server, th


# ---------------------------------------------------------------- proxy child

def proxy_child(a) -> None:
    import uvicorn

    from palimnesis.api import create_app
    from palimnesis.config import Settings
    from palimnesis.server import uvicorn_config

    extra = json.loads(a.settings)
    if extra.get("transcripts"):
        extra["transcripts"] = Path(extra["transcripts"])
    # --passthrough: `palimnesis serve --passthrough` (no archive); otherwise archive mode.
    # No --input-budget: the default budget (48,000, never above capacity), as `serve`.
    settings = Settings(upstream_base_url=a.upstream, db_path=None if a.passthrough else Path(a.db),
                        synchronous="FULL", input_budget=a.input_budget, **extra)
    print(f"proxy child settings={settings}", flush=True)
    server = uvicorn.Server(uvicorn_config(create_app(settings), host="127.0.0.1", port=a.port,
                                           log_level="warning"))
    stop = Path(a.stop_file)

    def watch():
        while not stop.exists():
            time.sleep(0.2)
        server.should_exit = True

    threading.Thread(target=watch, daemon=True).start()
    server.run()
    print("proxy child exited cleanly", flush=True)


class ProxyProcess:
    def __init__(self, run_dir: Path, upstream: str, settings: dict,
                 input_budget: int | None = INPUT_BUDGET, passthrough: bool = False):
        self.run_dir, self.upstream, self.settings = run_dir, upstream, settings
        self.input_budget, self.passthrough = input_budget, passthrough
        self.db = run_dir / "archive.db"
        self.port = free_port()
        self.proc: subprocess.Popen | None = None
        self.starts = 0

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        self.starts += 1
        # Unique per start, and removed first: a stop file or log left by an earlier run
        # in the same directory can neither stop this child nor be overwritten.
        tag = f"{self.starts}-{os.getpid()}-{time.time_ns()}"
        stop = self.run_dir / f"STOP-{tag}"
        stop.unlink(missing_ok=True)
        log = open(self.run_dir / f"proxy-{tag}.log", "a", encoding="utf-8")
        self.stop_file = stop
        self.proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "proxy", "--port", str(self.port),
             "--db", str(self.db), "--upstream", self.upstream,
             *(["--input-budget", str(self.input_budget)] if self.input_budget else []),
             *(["--passthrough"] if self.passthrough else []),
             "--settings", json.dumps(self.settings), "--stop-file", str(stop)],
            stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT))
        deadline = time.time() + 90
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"proxy child exited: see {log.name}")
            with contextlib.suppress(OSError), socket.create_connection(("127.0.0.1", self.port), 0.5):
                return
            time.sleep(0.2)
        raise RuntimeError("proxy child did not start")

    def stop(self) -> None:
        if self.proc is None:
            return
        self.stop_file.write_text("stop")
        try:
            self.proc.wait(60)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(10)
        self.proc = None


# ---------------------------------------------------------------- tool emulation

def tool_error(message: str) -> str:
    return json.dumps({"error": {"type": "tool.execution", "message": message}, "content": []},
                      separators=(",", ":"), ensure_ascii=False)


SHELL_ALLOW = {"grep", "rg", "sed", "head", "tail", "cat", "wc", "ls", "find", "awk", "sort",
               "uniq", "cut", "nl", "echo", "pwd", "tr"}
BASH = next((p for p in (r"C:\Program Files\Git\bin\bash.exe",) if Path(p).exists()),
            shutil.which("bash"))


class Tools:
    """OpenCode 2.1.4 read/grep/glob/shell/edit/write semantics against real files."""

    def __init__(self, workspace: Path, transcripts_root: Path | None, session_dir: Path | None,
                 scripted: list[dict], tmp: Path | None = None):
        self.ws, self.troot, self.sdir, self.scripted = workspace, transcripts_root, session_dir, scripted
        # OpenCode's approved temp directory, named in the system prompt's <env> block.
        self.tmp = tmp

    def _resolve(self, p: str | None) -> Path:
        if not p or p in ("undefined", "null"):
            return self.ws
        q = Path(os.path.expanduser(p.replace("/", os.sep)))
        if not q.is_absolute():
            q = self.ws / q
        return Path(os.path.normpath(q))

    def _allowed(self, q: Path) -> bool:
        s = str(q).lower()
        roots = [self.ws] + ([self.troot] if self.troot else []) + ([self.tmp] if self.tmp else [])
        return any(s == str(r).lower() or s.startswith(str(r).lower() + os.sep) for r in roots)

    def _writable(self, q: Path) -> bool:
        s = str(q).lower()
        return any(s.startswith(str(r).lower() + os.sep) for r in (self.ws, self.tmp) if r)

    def is_lookup(self, name: str, args: dict) -> bool:
        if self.troot is None:
            return False
        texts = [str(v) for v in args.values() if isinstance(v, str)]
        root = str(self.troot).lower().replace("\\", "/")
        for t in texts:
            tt = t.lower().replace("\\", "/")
            if root in tt or "/transcripts/" in tt:
                return True
        if name in ("read", "grep", "glob") and self._allowed(self._resolve(args.get("path"))) and \
                str(self._resolve(args.get("path"))).lower().startswith(str(self.troot).lower()):
            return True
        return False

    def run(self, name: str, raw_args: str) -> str:
        try:
            args = json.loads(raw_args or "{}")
            if not isinstance(args, dict):
                raise ValueError
        except ValueError:
            return tool_error(f"Invalid arguments for {name}")
        try:
            fn = getattr(self, f"t_{name}", None)
            if fn is None:
                if name == "question":
                    return tool_error("This non-interactive run cannot ask the user questions, so the "
                                      "question was cancelled. Continue without an answer; make "
                                      "reasonable assumptions and state them.")
                return tool_error(f"The {name} tool is not available in this environment.")
            return fn(args)
        except Exception as e:  # emulator bug guard: model-visible as a tool error
            return tool_error(f"Unable to run {name}: {type(e).__name__}")

    def t_read(self, a: dict) -> str:
        path = a.get("path")
        if not isinstance(path, str) or not path:
            return tool_error("Invalid arguments for read")
        q = self._resolve(path)
        if not self._allowed(q) or not q.exists():
            return tool_error(f"File not found: {path}")
        offset = int(a.get("offset") or 1) or 1
        limit = min(int(a.get("limit") or 2000), 2000) or 2000
        if q.is_dir():
            entries = sorted(e.name + ("/" if e.is_dir() else "") for e in q.iterdir())
            page = entries[offset - 1: offset - 1 + limit]
            head = (f"Read directory {path}, 0 entries" if not page else
                    f"Read directory {path}, entries {offset}-{offset + len(page) - 1}")
            out = [head, *page]
            if offset - 1 + len(page) < len(entries):
                out.append(f"[Output truncated. Continue reading with offset: {offset + len(page)}]")
            return "\n".join(out)
        text = q.read_bytes().decode("utf-8", "replace")
        lines = [] if text == "" else re.sub(r"\n$", "", text).split("\n")
        page, size = [], 0
        for line in lines[offset - 1: offset - 1 + limit]:
            if len(line) > 2000:
                line = line[:2000] + "..."  # per-line cap (2,000 chars); suffix unverified
            size += len(line.encode("utf-8")) + 1
            if size > 50 * 1024 and page:
                break
            page.append(line)
        out = [f"Read file {path}, 0 lines" if not page else
               f"Read file {path}, lines {offset}-{offset + len(page) - 1}"]
        out += [f"{offset + i}: {t}" for i, t in enumerate(page)]
        if offset - 1 + len(page) < len(lines):
            out.append(f"[Output truncated. Continue reading with offset: {offset + len(page)}]")
        return "\n".join(out)

    def t_grep(self, a: dict) -> str:
        pattern = a.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return tool_error("Pattern must not be empty")
        q = self._resolve(a.get("path"))
        if not self._allowed(q) or not q.exists():
            return tool_error(f"Search path does not exist: {a.get('path') or '.'}")
        cwd = q if q.is_dir() else q.parent
        limit = int(a.get("limit") or 100)
        cmd = ["rg", "--json", "--hidden", "--no-config", "--glob=!**/.git/**", "--sort", "path"]
        if a.get("literal"):
            cmd.append("-F")
        if a.get("caseSensitive") is False:
            cmd.append("-i")
        if a.get("include"):
            cmd += ["--glob", str(a["include"])]
        cmd += ["-e", pattern, q.name if q.is_file() else "."]
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=30)
        if p.returncode == 2 and not p.stdout:
            return tool_error(f"Invalid regex pattern: {p.stderr.decode('utf-8', 'replace').strip()[:300]}")
        matches = []
        for line in p.stdout.splitlines():
            d = json.loads(line)
            if d["type"] != "match":
                continue
            rel = d["data"]["path"].get("text", "")
            txt = d["data"]["lines"].get("text", "").rstrip("\n")
            matches.append((os.path.normpath(os.path.join(cwd, rel)), d["data"]["line_number"], txt))
            if len(matches) > limit:
                break
        truncated = len(matches) > limit
        matches = matches[:limit]
        if not matches:
            return "No matches found"
        out, last = [f"Found {len(matches)} matches"], ""
        for path, n, txt in matches:
            if path != last:
                if last:
                    out.append("")
                last = path
                out.append(f"{path}:")
            out.append(f"  Line {n}: {txt}")
        if truncated:
            out += ["", f"(Results are truncated: showing first {len(matches)} results. Consider "
                        "using a more specific path or pattern.)"]
        return "\n".join(out)

    def t_glob(self, a: dict) -> str:
        pattern = a.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return tool_error("Invalid arguments for glob")
        q = self._resolve(a.get("path"))
        if not self._allowed(q) or not q.exists():
            return tool_error(f"Search path does not exist: {a.get('path') or '.'}")
        if not q.is_dir():
            return tool_error(f"Search path is not a directory: {a.get('path') or '.'}")
        limit = int(a.get("limit") or 100)
        cmd = ["rg", "--files", "--no-config", "--sort", "path", "--glob", pattern]
        if a.get("hidden"):
            cmd.append("--hidden")
        p = subprocess.run(cmd, cwd=q, capture_output=True, timeout=30)
        files = [os.path.normpath(os.path.join(q, f)) for f in p.stdout.decode("utf-8", "replace").splitlines() if f]
        truncated = len(files) > limit
        files = files[:limit]
        out = files or ["No files found"]
        if truncated:
            out += ["", f"(Results are truncated: showing first {len(files)} results. Consider "
                        "using a more specific path or pattern.)"]
        return "\n".join(out)

    def t_shell(self, a: dict) -> str:
        command = a.get("command")
        if not isinstance(command, str) or not command.strip():
            return tool_error("Invalid arguments for shell")
        for s in self.scripted:
            if s["match"] in command.replace("\\", "/"):
                return s["output"]
        if re.search(r"[<>;`]|\$\(|\bsed\s+-i|-delete\b|-exec\b|\|\|", command):
            return tool_error("This command is not available in this environment.")
        segments = re.split(r"\||&&", command)
        for seg in segments:
            try:
                words = shlex.split(seg)
            except ValueError:
                return tool_error("This command is not available in this environment.")
            if not words or words[0] not in SHELL_ALLOW:
                return tool_error("This command is not available in this environment.")
            for w in words[1:]:
                if (w.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", w)) and \
                        not self._allowed(Path(os.path.normpath(w.replace("/", os.sep) if not w.startswith("/c/") else "C:" + w[2:].replace("/", os.sep)))):
                    return tool_error("This command is not available in this environment.")
        cwd = self._resolve(a.get("workdir")) if a.get("workdir") else self.ws
        if not self._allowed(cwd) or not cwd.is_dir():
            return tool_error(f"Working directory does not exist: {a.get('workdir')}")
        p = subprocess.run([BASH, "-c", command], cwd=cwd, capture_output=True, timeout=60)
        out = (p.stdout + p.stderr).decode("utf-8", "replace")
        if len(out) > 50 * 1024:  # OpenCode saves large output to a file; preview shape unverified
            out = out[:50 * 1024] + "\n...[output truncated]"
        return out

    def t_write(self, a: dict) -> str:
        q = self._resolve(a.get("path"))
        if not self._writable(q):
            return tool_error(f"Unable to write {a.get('path')}")
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_text(str(a.get("content", "")), encoding="utf-8", newline="\n")
        return f"Created file successfully: {a.get('path')}"

    def t_edit(self, a: dict) -> str:
        path = a.get("path")
        q = self._resolve(path)
        old, new = a.get("oldString", ""), a.get("newString", "")
        if old == new:
            return tool_error("No changes to apply: oldString and newString are identical.")
        if not self._writable(q) or not q.is_file():
            return tool_error(f"File not found: {path}")
        text = q.read_text(encoding="utf-8")
        n = text.count(old)
        if n == 0:
            return tool_error(f"Could not find oldString in {path}. It must match exactly, including "
                              "whitespace and indentation.")
        if n > 1 and not a.get("replaceAll"):
            return tool_error(f"Found {n} matches for oldString, but expected exactly one. Add more "
                              "surrounding context to make oldString unique, or set replaceAll to "
                              "true to replace every occurrence.")
        text = text.replace(old, new) if a.get("replaceAll") else text.replace(old, new, 1)
        q.write_text(text, encoding="utf-8", newline="\n")
        k = n if a.get("replaceAll") else 1
        return f"Edited {path} ({k} replacement{'' if k == 1 else 's'})"


# ---------------------------------------------------------------- the emulator client

@dataclass
class CallResult:
    status: int
    content: str = ""
    reasoning: str = ""
    tool_calls: list = field(default_factory=list)
    finish: str | None = None
    usage: dict = field(default_factory=dict)
    t_post: float = 0.0
    t_headers: float | None = None
    t_first_delta: float | None = None
    t_first_content: float | None = None
    t_end: float = 0.0
    error: str | None = None


def stream_call(client: httpx.Client, url: str, body: bytes) -> CallResult:
    res = CallResult(status=0, t_post=time.time())
    calls: dict[int, dict] = {}
    try:
        with client.stream("POST", url, content=body, headers={
                "content-type": "application/json", "x-palimnesis-kind": "primary",
                "user-agent": "opencode/2.1.4 (palimnesis needle emulator)"}) as r:
            res.status = r.status_code
            res.t_headers = time.time()
            if r.status_code != 200:
                res.error = r.read().decode("utf-8", "replace")[:500]
                return res
            for line in r.iter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                d = json.loads(line[6:])
                if "error" in d:
                    res.error = json.dumps(d["error"])[:500]
                    continue
                if d.get("usage"):
                    res.usage = d["usage"]
                for ch in d.get("choices") or []:
                    delta = ch.get("delta") or {}
                    now = time.time()
                    if delta.get("reasoning_content"):
                        res.reasoning += delta["reasoning_content"]
                        res.t_first_delta = res.t_first_delta or now
                    if delta.get("content"):
                        res.content += delta["content"]
                        res.t_first_delta = res.t_first_delta or now
                        res.t_first_content = res.t_first_content or now
                    for tc in delta.get("tool_calls") or []:
                        res.t_first_delta = res.t_first_delta or now
                        res.t_first_content = res.t_first_content or now
                        slot = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
                        slot["id"] = tc.get("id") or slot["id"]
                        fn = tc.get("function") or {}
                        slot["name"] += fn.get("name") or ""
                        slot["arguments"] += fn.get("arguments") or ""
                    if ch.get("finish_reason"):
                        res.finish = ch["finish_reason"]
    except httpx.HTTPError as e:
        res.error = f"{type(e).__name__}: {e}"
    res.tool_calls = [calls[k] for k in sorted(calls)]
    res.t_end = time.time()
    return res


LENGTH_NOTE = ("Your last response hit the output token limit (stop reason: length). Do not "
               "apologize, recap, or repeat yourself. Break the remaining work into smaller pieces.")


def args_object(raw: str) -> bool:
    try:
        return isinstance(json.loads(raw or "{}"), dict)
    except ValueError:
        return False


def assistant_message(res: CallResult) -> dict:
    # As OpenCode 2.1.4's OpenAI Chat conversion builds it ("ze" in the bundle): content is
    # null only for a tool-call-only turn, else the joined text ("" when there is none).
    # reasoning_content is left out here (the proxy restores archived reasoning).
    msg = {"role": "assistant", "content": res.content if (res.content or not res.tool_calls) else None}
    if res.tool_calls:
        msg["tool_calls"] = [{"id": c["id"], "type": "function",
                              "function": {"name": c["name"], "arguments": c["arguments"]}}
                             for c in res.tool_calls]
    return msg


def normalize(s: str) -> str:
    return " ".join((s or "").split()).casefold()


def normalize_loose(s: str) -> str:
    s = normalize(s)
    s = s.strip().strip("`*\"' ").rstrip(".").strip("`*\"' ")
    return s


def score(answer_text: str | None, step: dict) -> dict:
    gold = step["answer"]
    got = answer_text or ""
    exact = normalize(got) == normalize(gold)
    loose = normalize_loose(got) == normalize_loose(gold)
    contains = normalize(gold) in normalize(got)
    parts = [p for p in step["parts"] if normalize(p) in normalize(got)]
    return {"exact": exact, "exact_loose": loose, "contains": contains,
            "parts_found": len(parts), "parts_total": len(step["parts"]),
            "partial": (not loose) and (contains or 0 < len(parts))}


def context_check(body: bytes, step: dict) -> dict:
    """Was the answer in the model's context on the question's first upstream call, and
    did it come from the excerpt block?"""
    d = json.loads(body)
    msgs = d["messages"]
    last_user = max(i for i, m in enumerate(msgs) if m["role"] == "user")
    excerpt = ""
    texts = []
    for i, m in enumerate(msgs):
        c = m.get("content")
        c = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False) if c else ""
        if i == last_user and "[palimnesis excerpts" in c:
            k = c.index("[palimnesis excerpts")
            excerpt, c = c[k:], c[:k]
        texts.append(c)
        for tc in m.get("tool_calls") or []:
            texts.append(tc["function"]["arguments"])
        if m.get("reasoning_content"):
            texts.append(m["reasoning_content"])
    visible = "\n".join(texts)
    parts = step["parts"]
    return {
        "in_view": all(p in visible for p in parts),
        "in_excerpt": all(p in excerpt or p in visible for p in parts) and any(p in excerpt for p in parts),
        "parts_in_context": sum(1 for p in parts if p in visible or p in excerpt),
        "excerpt_items": excerpt.count("[[excerpt "),
        "excerpt_present": bool(excerpt),
        "addendum_present": "An exact transcript is in" in msgs[0].get("content", "")
        or "look it up in the exact transcript" in msgs[0].get("content", ""),
        "stub_count": visible.count("[palimnesis s1"),
    }


class FakeModel:
    """Dry-run model behind tests.fake_upstream: looks a needle up through the transcript
    files (grep, then a bounded read) when they exist, then answers with the gold value."""

    def __init__(self, fake, tools: Tools):
        self.fake, self.tools = fake, tools

    def queue(self, step: dict, rnd: int, messages: list) -> None:
        if step["kind"] == "question" and self.tools.sdir is not None and rnd == 0:
            self.fake.respond_counted(tool_call=("call_dry_g", "grep", json.dumps(
                {"pattern": step["parts"][0], "path": str(self.tools.sdir), "literal": True})))
            return
        if step["kind"] == "question" and self.tools.sdir is not None and rnd == 1:
            last = messages[-1]["content"]
            m = re.search(r"^(.+turn-\d+\S*\.md):\n  Line (\d+):", last, re.M)
            if m:
                self.fake.respond_counted(tool_call=("call_dry_r", "read", json.dumps(
                    {"path": m.group(1), "offset": max(1, int(m.group(2)) - 2), "limit": 5})))
                return
        if step.get("mid_task") and rnd == 0:
            self.fake.respond_counted(tool_call=("call_dry_s", "shell", json.dumps(
                {"command": step["mid_task"]["command"]})))
            return
        self.fake.respond_counted(text=step["answer"] if step["kind"] == "question" else "ok")


# ---------------------------------------------------------------- run one configuration

def run_config(a) -> int:
    cfg = CONFIGS[a.config]
    out = Path(a.out) / a.config
    if out.exists() and not a.resume:
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    histories = select_histories(a)
    live = a.upstream != "fake"
    stack = contextlib.ExitStack()
    fake = None
    if live:
        upstream = a.upstream.rstrip("/")
    else:
        sys.path.insert(0, str(ROOT))
        from tests.fake_upstream import FakeUpstream
        from tests.servers import serve
        fake = FakeUpstream()
        upstream = stack.enter_context(serve(fake.app()))
    gate = SlotGate(upstream if live else None)
    tap = Tap(upstream, out / "bodies", gate)
    tap_port = free_port()
    tap_server, tap_thread = serve_in_thread(tap, tap_port)
    settings = {k: cfg[k] for k in ("recall", "transcripts_enabled", "query_policy",
                                    "excerpt_renderer", "addendum")}
    settings["deadline_s"] = 3600.0  # the gate may hold a request while the slot is busy
    proxy = ProxyProcess(out, f"http://127.0.0.1:{tap_port}", settings)
    proxy.start()
    from palimnesis.projector import default_root, session_dir

    troot = default_root(proxy.db) if cfg["transcripts_enabled"] else None
    client = httpx.Client(timeout=httpx.Timeout(None, connect=15))
    meta = {"config": a.config, **cfg, "settings": settings, "input_budget": INPUT_BUDGET,
            "emulator": EMULATOR_VERSION, "live": live, "upstream": a.upstream,
            "started": time.time(), "max_tools": MAX_TOOLS, "sessions": []}
    qlog = open(out / "questions.jsonl", "a", encoding="utf-8")
    clog = open(out / "calls.jsonl", "a", encoding="utf-8")
    status = 0
    try:
        for hpath in histories:
            h = json.loads(hpath.read_text(encoding="utf-8"))
            session = f"{h['id']}-{a.config}-{a.tag}"
            meta["sessions"].append(session)
            ws = out / "work" / h["id"]
            if ws.exists():
                shutil.rmtree(ws)
            ws.mkdir(parents=True)
            for rel, text in h["workspace"].items():
                p = ws / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8", newline="\n")
            subprocess.run(["git", "init", "-q"], cwd=ws)
            system, tools_schema, model = opencode_head(ws)
            sdir = session_dir(troot, session) if troot else None
            tmp = out / "work" / "tmp" / "opencode"
            tmp.mkdir(parents=True, exist_ok=True)
            tools = Tools(ws, troot, sdir, h["shell"], tmp)
            fm = FakeModel(fake, tools) if fake else None
            messages = [{"role": "system", "content": system}] + h["import"]
            steps = h["steps"]
            if a.questions:
                qs = [s for s in steps if s["kind"] == "question"][:a.questions]
                steps = [s for s in steps if s["kind"] != "question" or s in qs]
                last_q = steps.index(qs[-1])
                steps = steps[:last_q + 1]
            url = f"{proxy.url}/s/{session}/v1/chat/completions"
            try:
                for si, step in enumerate(steps):
                    if tap.abort:
                        raise SlotBusyTooLong(tap.abort)
                    if step.get("restart_before"):
                        proxy.stop()
                        proxy.start()
                    if si > 0:
                        messages.append({"role": "user", "content": step["text"]})
                    q0 = time.time()
                    rec = {"history": h["id"], "session": session, "config": a.config, "arm": cfg["arm"],
                           "step": step["id"], "kind": step["kind"], "category": step.get("category"),
                           "restart_before": bool(step.get("restart_before")), "rounds": 0,
                           "tool_calls": [], "lookups": 0, "workspace_tool_calls": 0,
                           "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0,
                           "calls": [], "errors": []}
                    executed = 0
                    length_follow = 0
                    final = None
                    first_call_n = None
                    for rnd in range(MAX_ROUNDS):
                        pre = gate.wait_idle(client, f"driver:{step['id']}:{rnd}")
                        if fm:
                            fm.queue(step, rnd, messages)
                        before = len(tap.calls)
                        res = stream_call(client, url, dumps({
                            "model": model, "messages": messages, "tools": tools_schema, "stream": True,
                            "stream_options": {"include_usage": True}, "max_completion_tokens": 8192}))
                        rec["rounds"] += 1
                        deadline = time.time() + 15  # the tap records a call after relaying its end
                        while len(tap.calls) == before and time.time() < deadline and res.status == 200:
                            time.sleep(0.05)
                        new_calls = tap.calls[before:]
                        tc = new_calls[-1] if new_calls else {}
                        if first_call_n is None and tc:
                            first_call_n = tc["n"]
                        u = res.usage or {}
                        rec["prompt_tokens"] += u.get("prompt_tokens") or 0
                        rec["completion_tokens"] += u.get("completion_tokens") or 0
                        rec["cached_tokens"] += (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
                        rec["calls"].append({
                            "status": res.status, "finish": res.finish, "upstream_calls": len(new_calls),
                            "tap_n": tc.get("n"), "prompt_tokens": u.get("prompt_tokens"),
                            "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
                            "completion_tokens": u.get("completion_tokens"),
                            "ttfb_s": round((res.t_headers or res.t_end) - res.t_post, 3),
                            "first_delta_s": round(res.t_first_delta - res.t_post, 3) if res.t_first_delta else None,
                            "first_content_s": round(res.t_first_content - res.t_post, 3) if res.t_first_content else None,
                            "total_s": round(res.t_end - res.t_post, 3), "driver_wait_s": pre["waited_s"],
                            "prompt_ms": (tc.get("timings") or {}).get("prompt_ms"),
                            "tap_wait_s": tc.get("waited_s"), "foreign_between": tc.get("foreign_between"),
                            "foreign_during": tc.get("foreign_during"),
                            "foreign_overlap_samples": tc.get("foreign_overlap_samples")})
                        clog.write(json.dumps({"session": session, "step": step["id"], "round": rnd,
                                               **{k: v for k, v in tc.items()}}) + "\n")
                        clog.flush()
                        if res.t_first_content and "ttfvc_s" not in rec and res.content:
                            rec["ttfvc_s"] = round(res.t_first_content - q0, 3)
                        if res.status != 200 or (res.error and not res.content and not res.tool_calls):
                            rec["errors"].append({"status": res.status, "error": res.error})
                            break
                        if res.error:
                            rec["errors"].append({"status": res.status, "error": res.error})
                        messages.append(assistant_message(res))
                        if any(not args_object(c["arguments"]) for c in res.tool_calls):
                            # A generated call whose arguments are not a JSON object (seen after
                            # finish_reason "length") cannot be resent faithfully: stop the history.
                            rec["errors"].append({"status": res.status, "error":
                                                  f"unparsable tool-call arguments, finish={res.finish}"})
                            rec["poisoned"] = True
                            break
                        if res.finish == "length" and not res.tool_calls and length_follow < 2:
                            # OpenCode 2.1.4: up to two synthetic continuations (opencode_faults §8).
                            length_follow += 1
                            messages.append({"role": "user", "content": LENGTH_NOTE})
                            continue
                        if not res.tool_calls:
                            final = res.content
                            break
                        for c in res.tool_calls:
                            try:
                                args = json.loads(c["arguments"] or "{}")
                            except ValueError:
                                args = {}
                            args = args if isinstance(args, dict) else {}
                            lookup = tools.is_lookup(c["name"], args)
                            if executed < a.max_tools:
                                executed += 1
                                result = tools.run(c["name"], c["arguments"])
                            else:
                                result = tool_error("Tool call limit for this question reached; answer "
                                                    "with what you have.")
                            rec["tool_calls"].append({"name": c["name"], "lookup": lookup,
                                                      "args": {k: (v if len(str(v)) < 200 else str(v)[:200])
                                                               for k, v in args.items()},
                                                      "result_chars": len(result),
                                                      "error": result.startswith('{"error"')})
                            rec["lookups"] += int(lookup)
                            rec["workspace_tool_calls"] += int(not lookup)
                            messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})
                    rec["total_s"] = round(time.time() - q0, 3)
                    rec["answer"] = (final or "")[:300]
                    rec["answered"] = final is not None
                    if step["kind"] == "question":
                        rec["gold"] = step["answer"]
                        rec.update(score(final, step))
                        if first_call_n is not None:
                            body = (out / "bodies" / f"{first_call_n:04d}.json").read_bytes()
                            rec.update(context_check(body, step))
                            rec["fact_absent"] = not rec["in_view"] and not rec["in_excerpt"]
                            rec["appropriate_fallback"] = rec["fact_absent"] and rec["lookups"] > 0
                            rec["unnecessary_lookups"] = 0 if rec["fact_absent"] else rec["lookups"]
                    qlog.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    qlog.flush()
                    if step["kind"] == "question":
                        print(f"[{a.config}] {step['id']:7} {step['category']:24} exact={rec['exact_loose']!s:5} "
                              f"view={rec.get('in_view')!s:5} exc={rec.get('in_excerpt')!s:5} "
                              f"lookups={rec['lookups']} rounds={rec['rounds']} {rec['total_s']:.0f}s "
                              f"ans={rec['answer'][:60]!r}", flush=True)
                    if rec.get("poisoned"):
                        print(f"history {h['id']} stopped after {step['id']}: {rec['errors'][-1]}", flush=True)
                        meta.setdefault("stopped_histories", []).append(
                            {"history": h["id"], "after": step["id"], "error": rec["errors"][-1]})
                        break
                    if any(e["status"] == 409 for e in rec["errors"]):
                        print(f"history {h['id']} aborted: {rec['errors']}", flush=True)
                        break
            except SlotBusyTooLong:
                raise
            except Exception:  # an emulator or driver bug: record it, go on to the next history
                import traceback
                print(f"history {h['id']} failed: {traceback.format_exc()}", flush=True)
                meta.setdefault("history_errors", []).append({"history": h["id"], "error": traceback.format_exc()[-1500:]})
    except SlotBusyTooLong as e:
        print(f"ABORT: {e}", flush=True)
        meta["abort"] = str(e)
        status = 3
    finally:
        proxy.stop()
        tap_server.should_exit = True
        tap_thread.join(10)
        stack.close()
        meta["finished"] = time.time()
        meta["gate_events"] = gate.events
        meta["proxy_starts"] = proxy.starts
        qlog.close()
        clog.close()
    post_checks(out, proxy.db, cfg, meta)
    return status


def select_histories(a) -> list[Path]:
    folder, prefix = SETS[getattr(a, "set", "development")]
    histories = sorted((ROOT / "eval" / "needles" / folder).glob(f"{prefix}-h*.json"),
                       key=lambda p: int(p.stem.rsplit("h", 1)[1]))
    if a.histories:
        want = {f"{prefix}-{h}" for h in a.histories.split(",")}
        histories = [h for h in histories if h.stem in want]
    return histories


def verify_sessions(db: Path, sessions: list[str], root: Path | None = None) -> dict:
    out = {}
    for s in sessions:
        cmd = [sys.executable, "-m", "palimnesis", "transcripts", "verify", s, "--db", str(db)]
        if root is not None:
            cmd += ["--root", str(root)]
        v = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
        out[s] = {"exit": v.returncode, "out": (v.stdout + v.stderr)[-600:]}
    return out


def post_checks(out: Path, db: Path, cfg: dict, meta: dict) -> None:
    """``replay.py --explain`` on the archive and ``transcripts verify`` per session.
    An existing ``meta.json`` (a ``--resume`` of the same directory) is kept under
    ``earlier`` rather than overwritten."""
    ex = subprocess.run([sys.executable, str(ROOT / "eval" / "replay.py"), "--explain", str(db),
                         "--json"], capture_output=True, text=True, cwd=str(ROOT))
    (out / "explain.json").write_text(ex.stdout, encoding="utf-8")
    meta["explain_exit"] = ex.returncode
    meta["explain_stderr"] = ex.stderr[-2000:]
    meta["verify"] = verify_sessions(db, meta["sessions"]) if cfg["transcripts_enabled"] else {}
    mp = out / "meta.json"
    if mp.exists():
        prev = json.loads(mp.read_text(encoding="utf-8"))
        meta["earlier"] = prev.pop("earlier", []) + [prev]
    mp.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"explain exit {ex.returncode}; verify " +
          ", ".join(f"{k[-30:]}={v['exit']}" for k, v in meta["verify"].items()), flush=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--config", choices=sorted(CONFIGS), required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--histories")
    r.add_argument("--questions", type=int)
    r.add_argument("--upstream", default="http://192.168.1.173:8080")
    r.add_argument("--tag", default=time.strftime("%m%d%H%M"))
    r.add_argument("--max-tools", type=int, default=MAX_TOOLS)
    r.add_argument("--resume", action="store_true")
    r.add_argument("--driver", choices=["emulator", "opencode"], default="emulator",
                   help="emulator (development default) or real OpenCode 2.1.4 (held-out, D44.2)")
    r.add_argument("--set", choices=sorted(SETS), default="development")
    r.add_argument("--reason", help="opencode driver: why this attempt reruns histories (D44.7)")
    r.add_argument("--ws-root", help="opencode driver: workspace tree (default: <out>-ws, beside --out)")
    r.add_argument("--expect-n-ctx", type=int, default=32768,
                   help="opencode driver: refuse unless Strata /props reports this n_ctx")
    f = sub.add_parser("preflight", help="every import through real OpenCode against the fake upstream")
    f.add_argument("--set", choices=sorted(SETS), default="heldout")
    f.add_argument("--histories")
    c = sub.add_parser("proxy")
    c.add_argument("--port", type=int, required=True)
    c.add_argument("--db", required=True)
    c.add_argument("--upstream", required=True)
    c.add_argument("--input-budget", type=int)
    c.add_argument("--passthrough", action="store_true")
    c.add_argument("--settings", required=True)
    c.add_argument("--stop-file", required=True)
    a = p.parse_args()
    if a.cmd == "proxy":
        proxy_child(a)
        return 0
    if a.cmd == "preflight":
        import needle_opencode

        return needle_opencode.preflight(a)
    if a.driver == "opencode":
        if a.upstream == "fake":
            p.error("--driver opencode needs a live upstream")
        import needle_opencode

        return needle_opencode.run(a)
    if a.set == "heldout":
        p.error("held-out needles run through real OpenCode only (D44.2): add --driver opencode")
    return run_config(a)


if __name__ == "__main__":
    sys.exit(main())
