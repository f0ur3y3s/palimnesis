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

BASE = os.environ.get("STRATA_URL", "http://192.168.1.173:8080").rstrip("/")
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
