"""Client cancellation through Palimnesis, and how fast Strata frees its slot (Phase 4B S14).

A streaming request goes through a local ``palimnesis serve`` (archive mode) to Strata
(``--upstream``, e.g. an SSH tunnel to pythia). The client closes its connection at a set
point, during decode (after some text) or during prefill (a long prompt, after a delay),
and the script polls Strata's ``/status`` every 25 ms until it shows neither work nor a
queue. Release is that time minus the moment the client closed. Contracts §8 expects under
1 s during decode and at most one prefill chunk during prefill (``docs/probes/strata.md``
§9: Strata cancels only at an 8,192-token chunk boundary).

Every trial waits for Strata to be idle first (D39). Afterwards the archive must show each
attempt recorded as ``cancelled``, never completed.

    uv run python eval/probes/proxy_cancel_release.py --upstream http://127.0.0.1:18080 [--trials 3]
"""

from __future__ import annotations

import argparse
import json
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def status(upstream: str) -> dict:
    return httpx.get(f"{upstream}/status", timeout=5).json()


def wait_idle(upstream: str, limit: float = 1800) -> None:
    end = time.time() + limit
    while time.time() < end:
        s = status(upstream)
        if not s.get("busy") and not s.get("queued"):
            return
        time.sleep(1)
    raise RuntimeError("Strata never went idle")


def filler(tokens: int) -> str:
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]
    return " ".join(f"{words[i % 8]}{i % 97}" for i in range(tokens // 3))  # ~3 tokens a word


def trial(proxy: str, upstream: str, mode: str, n: int) -> dict:
    if mode == "decode":
        messages = [{"role": "user", "content": f"[{time.time_ns()}] Count from 1 to 600, one "
                                                "number per line, nothing else."}]
        body = {"model": "m", "stream": True, "max_completion_tokens": 3000,
                "reasoning_effort": "none", "messages": messages}
    else:
        messages = [{"role": "user", "content": f"[{time.time_ns()}] " + filler(12000)
                     + "\n\nSummarize the above in one line."}]
        body = {"model": "m", "stream": True, "max_completion_tokens": 64,
                "reasoning_effort": "none", "messages": messages}
    wait_idle(upstream)
    session = f"cancel-{mode}-{n}"
    pieces = 0
    t_close = None
    with httpx.Client(timeout=120) as c:
        with c.stream("POST", f"{proxy}/s/{session}/v1/chat/completions", json=body) as r:
            t_start = time.monotonic()
            for chunk in r.iter_raw():
                if mode == "decode":
                    pieces += chunk.count(b'"content":')
                    if pieces >= 40:
                        break
                elif time.monotonic() - t_start >= 3.0:
                    break
            t_close = time.monotonic()
    busy_seen = False
    while True:
        s = status(upstream)
        if s.get("busy") or s.get("queued"):
            busy_seen = True
        else:
            break
        if time.monotonic() - t_close > 120:
            break
        time.sleep(0.025)
    return {"mode": mode, "trial": n, "session": session, "release_s": round(time.monotonic() - t_close, 3),
            "busy_after_close": busy_seen, "content_pieces_before_close": pieces}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", default="http://127.0.0.1:18080")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--modes", default="decode,prefill")
    ap.add_argument("--root", type=Path, default=Path(tempfile.gettempdir()) / "proxy-cancel")
    args = ap.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    db = args.root / f"archive-{int(time.time())}.db"
    port = free_port()
    log = open(args.root / "serve.log", "wb")
    proxy = subprocess.Popen([sys.executable, "-m", "palimnesis", "serve", "--port", str(port),
                              "--upstream", args.upstream, "--db", str(db), "--no-transcripts"],
                             stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                httpx.get(f"{url}/props", timeout=2)
                break
            except httpx.HTTPError:
                time.sleep(0.5)
        results = [trial(url, args.upstream, mode, n)
                   for mode in args.modes.split(",") for n in range(args.trials)]
        time.sleep(2)
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        outcomes = dict(conn.execute(
            "SELECT r.session_id, group_concat(e.kind) FROM requests r JOIN events e"
            " ON e.request_id = r.request_id WHERE e.kind IN"
            " ('turn_complete','attempt_failed','cancelled','attempt_abandoned')"
            " GROUP BY r.session_id").fetchall())
        conn.close()
    finally:
        proxy.terminate()
        proxy.wait(30)
        log.close()
    for r in results:
        r["archive"] = outcomes.get(r["session"])
    summary = {"results": results,
               "max_release_s": {m: max(r["release_s"] for r in results if r["mode"] == m)
                                 for m in args.modes.split(",")},
               "all_cancelled": all(r["archive"] == "cancelled" for r in results)}
    print(json.dumps(summary, indent=2))
    (args.root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0 if summary["all_cancelled"] and summary["max_release_s"].get("decode", 0) < 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
