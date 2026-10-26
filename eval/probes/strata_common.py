"""Shared helpers for Strata Phase 0 probes.

Run probes with:
    uv run --no-project --python 3.12 --with httpx python eval/probes/<probe>.py

Probes are deliberately sequential and small: Strata is a shared single-slot server.
Set STRATA_URL to override the base URL.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

BASE = os.environ.get("STRATA_URL", "http://192.168.1.19:8080").rstrip("/")
MODEL = os.environ.get("STRATA_MODEL", "qwen3.8-flash-next-iq3_xxs")
HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
FIXTURES.mkdir(exist_ok=True)


def client(timeout: float = 600.0) -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=httpx.Timeout(timeout, connect=10.0))


def status() -> dict:
    with client(10) as c:
        return c.get("/status").json()


def server_time() -> float:
    """Server wall clock (from /metrics 'time'), used to align server-side request records."""
    with client(10) as c:
        return c.get("/metrics").json()["time"]


def recent_requests(n: int = 10) -> list[dict]:
    with client(10) as c:
        return c.get("/metrics").json()["requests"][:n]


def wait_idle(max_wait: float = 1800.0, poll: float = 1.0, quiet: float = 0.0, log=print) -> float:
    """Block until /status reports not busy and nothing queued. Returns seconds waited.

    quiet: additionally require the server to stay idle this long (avoids racing a looping client).
    """
    t0 = time.monotonic()
    idle_since = None
    last_log = 0.0
    while True:
        s = status()
        idle = (not s.get("busy")) and not s.get("queued")
        now = time.monotonic()
        if idle:
            idle_since = idle_since or now
            if now - idle_since >= quiet:
                return now - t0
        else:
            idle_since = None
        if now - t0 > max_wait:
            raise TimeoutError(f"server still busy after {max_wait}s: {s}")
        if now - last_log > 30:
            log(f"  [wait_idle] busy={s.get('busy')} queued={s.get('queued')} phase={s.get('phase')} "
                f"gen={s.get('generated')}/{s.get('max_tokens')} waited={now - t0:.0f}s")
            last_log = now
        time.sleep(poll)


def save_json(name: str, obj) -> Path:
    p = FIXTURES / name
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def save_bytes(name: str, data: bytes) -> Path:
    p = FIXTURES / name
    p.write_bytes(data)
    return p


def chat_body(content: str, **kw) -> dict:
    body = {"model": MODEL, "messages": [{"role": "user", "content": content}], "max_tokens": 64}
    body.update(kw)
    return body


def filler(n_words: int, seed: int = 0) -> str:
    """Deterministic, low-repetition filler text (~1.3 tokens/word for this tokenizer, verify via usage)."""
    import random

    rng = random.Random(seed)
    vocab = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar "
             "papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu river mountain lantern "
             "copper meadow harbor violet thunder pebble orchard canyon glacier falcon ember willow summit "
             "quartz saffron tundra beacon cobalt marble prairie").split()
    words = [rng.choice(vocab) + (str(rng.randint(0, 99)) if rng.random() < 0.3 else "") for _ in range(n_words)]
    lines = [" ".join(words[i:i + 16]) + "." for i in range(0, len(words), 16)]
    return "\n".join(lines)


# -- streaming capture (Phase 3B probes p17-p20) ---------------------------------------------


def check_build(expected: str = "Strata 0.1.48") -> dict:
    """Refuse to probe a different engine build; returns /props without the template."""
    with client(10) as c:
        props = c.get("/props").json()
    if props.get("build_info") != expected:
        raise SystemExit(f"build_info is {props.get('build_info')!r}, expected {expected!r}")
    return {k: v for k, v in props.items() if k != "chat_template"}


def parse_sse(raw: bytes, arrivals: list[tuple[float, int]] | None = None) -> list[dict]:
    """Split raw SSE bytes into events: {"t", "kind": comment|data|done, "text", "json"}.

    ``t`` is the arrival time (s from send) of the chunk that completed the event, when
    ``arrivals`` (cumulative (t, n_bytes) pairs) is given."""
    ends = []
    if arrivals:
        total = 0
        for t, n in arrivals:
            total += n
            ends.append((total, t))
    out, pos = [], 0
    while True:
        i = raw.find(b"\n\n", pos)
        if i < 0:
            break
        block = raw[pos:i].decode("utf-8", "replace")
        end = i + 2
        t = next((tt for tot, tt in ends if tot >= end), None) if ends else None
        pos = end
        if not block.strip():
            continue
        data = [ln[5:].lstrip() for ln in block.split("\n") if ln.startswith("data:")]
        if not data:
            out.append({"t": t, "kind": "comment", "text": block})
            continue
        d = "\n".join(data)
        if d == "[DONE]":
            out.append({"t": t, "kind": "done", "text": d})
            continue
        try:
            j = json.loads(d)
        except json.JSONDecodeError:
            j = None
        out.append({"t": t, "kind": "data", "text": d, "json": j})
    if pos < len(raw) and raw[pos:].strip():
        out.append({"t": None, "kind": "tail", "text": raw[pos:].decode("utf-8", "replace")})
    return out


def stream_post(body: dict, path: str = "/v1/chat/completions", abort=None,
                timeout: float = 600.0) -> dict:
    """POST a streaming request; capture exact bytes with arrival times.

    ``abort(events, t_since_send)`` is checked after every received chunk; returning True
    closes the connection (a client disconnect). Returns raw, arrivals, events, timing."""
    t0 = time.monotonic()
    raw = bytearray()
    arrivals: list[tuple[float, int]] = []
    aborted_at = None
    with client(timeout) as c:
        with c.stream("POST", path, json=body) as r:
            status_code, headers = r.status_code, dict(r.headers)
            for chunk in r.iter_raw():
                t = time.monotonic() - t0
                raw.extend(chunk)
                arrivals.append((round(t, 4), len(chunk)))
                if abort is not None and abort(parse_sse(bytes(raw)), t):
                    aborted_at = time.monotonic()
                    break
    t_closed = time.monotonic()
    return {"status": status_code, "headers": headers, "raw": bytes(raw), "arrivals": arrivals,
            "events": parse_sse(bytes(raw), arrivals), "elapsed_s": round(t_closed - t0, 3),
            "aborted": aborted_at is not None, "t_closed_mono": t_closed}


def oa_shape(events: list[dict]) -> dict:
    """Assemble an OpenAI Chat stream and describe its shape.

    ``order`` is the run-length sequence of delta kinds (role, reasoning, content,
    tool[i], finish, comment, done); ``calls`` the assembled tool calls; plus the
    finish chunk's finish_reason and usage."""
    order: list[list] = []
    calls: dict[int, dict] = {}
    reasoning, content = [], []
    finish = usage = None
    first_tool_deltas: dict[int, dict] = {}

    def push(kind):
        if order and order[-1][0] == kind:
            order[-1][1] += 1
        else:
            order.append([kind, 1])

    for ev in events:
        if ev["kind"] in ("comment", "done", "tail"):
            push(ev["kind"])
            continue
        j = ev.get("json") or {}
        for ch in j.get("choices") or []:
            d = ch.get("delta") or {}
            if "role" in d:
                push("role")
            if d.get("reasoning_content"):
                reasoning.append(d["reasoning_content"])
                push("reasoning")
            if d.get("content"):
                content.append(d["content"])
                push("content")
            for tc in d.get("tool_calls") or []:
                i = tc.get("index")
                push(f"tool[{i}]")
                if i not in calls:
                    first_tool_deltas[i] = tc
                    calls[i] = {"id": tc.get("id"), "type": tc.get("type"),
                                "name": (tc.get("function") or {}).get("name"), "arguments": ""}
                fn = tc.get("function") or {}
                calls[i]["arguments"] += fn.get("arguments") or ""
                for k in ("id", "type"):
                    if tc.get(k) and calls[i][k] is None:
                        calls[i][k] = tc[k]
                if fn.get("name") and calls[i]["name"] is None:
                    calls[i]["name"] = fn["name"]
            if ch.get("finish_reason"):
                finish = ch["finish_reason"]
                push("finish")
        if j.get("usage"):
            usage = j["usage"]
    return {"order": order, "reasoning": "".join(reasoning), "content": "".join(content),
            "calls": [calls[k] for k in sorted(calls, key=lambda x: (x is None, x))],
            "first_tool_deltas": first_tool_deltas, "finish_reason": finish, "usage": usage}
