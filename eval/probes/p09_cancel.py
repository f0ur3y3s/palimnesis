"""Probe 9: cancellation-to-slot-release latency.

For each trial a request is sent over a raw socket; once the server shows it active (via /status) we
wait N ms and close the socket. We then measure:
  release_s   time from close until /status no longer shows our request (polled every ~25 ms);
  tiny_ttfb_s time from close until the first byte of a tiny follow-up request (non-streaming, 1 token);
and compare tiny_ttfb_s with an idle baseline. If another client's request is queued ahead of ours,
tiny_ttfb_s includes that request and only release_s is meaningful (queued_at_cancel records this).

Modes: prefill-stream, decode-stream, prefill-nonstream, decode-nonstream.
Usage: python p09_cancel.py <mode> <cancel_after_ms> [trials]   or   python p09_cancel.py baseline [n]
Appends results to fixtures/cancel_trials.jsonl.

Set MNEMON_PROXY=http://127.0.0.1:<port> to send the cancelled request through a Mnemon proxy
(session "cancel-probe"); /status polling and the tiny follow-up still go to Strata directly.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from urllib.parse import urlparse

import httpx

from strata_common import BASE, FIXTURES, MODEL, filler, recent_requests, save_bytes, status

U = urlparse(BASE)
HOST, PORT = U.hostname, U.port or 80
LOG = FIXTURES / "cancel_trials.jsonl"
PROXY = os.environ.get("MNEMON_PROXY")
PREFILL_WORDS = 9000  # ~20K tokens per count_tokens


def body_for(mode: str, seed: int) -> dict:
    stream = mode.endswith("-stream")
    if mode.startswith("prefill"):
        return {"model": MODEL, "max_tokens": 16, "reasoning_effort": "none", "stream": stream,
                "messages": [{"role": "user", "content": filler(PREFILL_WORDS, seed=1000 + seed) +
                              "\n\nReply with the single word OK."}]}
    return {"model": MODEL, "max_tokens": 3000, "reasoning_effort": "none", "stream": stream,
            "messages": [{"role": "user", "content": f"Trial {seed}. Count from 1 to 1500, numbers separated "
                                                     "by single spaces, no other text."}]}


def raw_post(path: str, body: dict, via_proxy: bool = False) -> socket.socket:
    data = json.dumps(body).encode()
    host, port = HOST, PORT
    if via_proxy and PROXY:
        p = urlparse(PROXY)
        host, port, path = p.hostname, p.port or 80, "/s/cancel-probe" + path
    s = socket.create_connection((host, port), timeout=600)
    s.sendall((f"POST {path} HTTP/1.1\r\nHost: {host}:{port}\r\nContent-Type: application/json\r\n"
               f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n").encode() + data)
    return s


def tiny_ttfb() -> tuple[float, float, dict]:
    """Non-streaming 1-token request; returns (ttfb_s, total_s, timings)."""
    body = {"model": MODEL, "max_tokens": 1, "reasoning_effort": "none",
            "messages": [{"role": "user", "content": "Say hi."}]}
    s = raw_post("/v1/chat/completions", body)
    t0 = time.monotonic()
    first = s.recv(1)
    ttfb = time.monotonic() - t0
    buf = bytearray(first)
    while True:
        b = s.recv(65536)
        if not b:
            break
        buf.extend(b)
    total = time.monotonic() - t0
    s.close()
    try:
        timings = json.loads(bytes(buf).split(b"\r\n\r\n", 1)[1]).get("timings", {})
    except Exception:
        timings = {"_raw": bytes(buf)[:300].decode("utf-8", "replace")}
    return ttfb, total, timings


def mine(st: dict, mode: str) -> bool:
    if not st.get("busy"):
        return False
    if mode.startswith("prefill"):
        return (st.get("prompt_tokens") or 0) > 15000
    return st.get("max_tokens") == 3000


def wait_until(pred, timeout: float, poll: float = 0.025):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        st = status()
        if pred(st):
            return st, time.monotonic()
        time.sleep(poll)
    return None, time.monotonic()


def trial(mode: str, cancel_ms: int, seed: int) -> dict:
    body = body_for(mode, seed)
    s = raw_post("/v1/chat/completions", body, via_proxy=True)
    s.settimeout(0.2)
    t_send = time.monotonic()
    received = bytearray()
    arrivals: list[tuple[float, int]] = []
    first_byte_s = None

    # Wait until our request is the active one (it may queue behind another client's request).
    def active(st):
        return mine(st, mode) and (mode.startswith("prefill") or st.get("generated", 0) > 0)

    st, t_active = None, None
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        try:
            b = s.recv(65536)
            if b:
                first_byte_s = first_byte_s or (time.monotonic() - t_send)
                arrivals.append((round(time.monotonic() - t_send, 3), len(b)))
                received.extend(b)
        except socket.timeout:
            pass
        st = status()
        if active(st):
            t_active = time.monotonic()
            break
    if t_active is None:
        s.close()
        return {"mode": mode, "error": "never became active"}
    # Keep draining while waiting cancel_ms so the server is not blocked writing.
    while (time.monotonic() - t_active) * 1000 < cancel_ms:
        try:
            b = s.recv(65536)
            if b:
                first_byte_s = first_byte_s or (time.monotonic() - t_send)
                arrivals.append((round(time.monotonic() - t_send, 3), len(b)))
                received.extend(b)
        except socket.timeout:
            pass
    st_before = status()
    if mode.endswith("-stream"):
        save_bytes(f"cancel_{mode}_{cancel_ms}ms_seed{seed}.raw", bytes(received))
    try:
        s.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    s.close()
    t_close = time.monotonic()
    # Release: our request no longer shown as active.
    st_after, t_rel = wait_until(lambda x: not mine(x, mode), timeout=300)
    release_s = t_rel - t_close
    queued = st_before.get("queued", 0)
    ttfb, total, timings = tiny_ttfb()
    ttfb_from_close = time.monotonic() - t_close - (total - ttfb)
    rec = {"mode": mode, "via_proxy": PROXY, "cancel_after_ms": cancel_ms, "seed": seed, "queue_wait_s": round(t_active - t_send, 2),
           "state_at_cancel": {k: st_before.get(k) for k in ("phase", "prompt_tokens", "generated", "queued")},
           "bytes_received": len(received), "arrivals_s_bytes": arrivals, "first_byte_s": first_byte_s and round(first_byte_s, 3),
           "received_head": bytes(received[:600]).decode("utf-8", "replace"),
           "release_s": round(release_s, 3),
           "status_after_release": {k: (st_after or {}).get(k) for k in ("busy", "phase", "prompt_tokens", "queued")},
           "queued_at_cancel": queued, "tiny_ttfb_from_close_s": round(ttfb_from_close, 3),
           "tiny_ttfb_s": round(ttfb, 3), "tiny_timings": timings, "at": time.time()}
    time.sleep(0.5)
    rec["server_records"] = [{k: r.get(k) for k in ("id", "time", "duration_s", "finish", "prompt_tokens", "reused",
                                                    "prompt_read", "prompt_ms", "output_tokens", "first_engine_token_s")}
                             for r in recent_requests(2)]
    return rec


def baseline(n: int) -> list[dict]:
    out = []
    for i in range(n):
        st = status()
        ttfb, total, timings = tiny_ttfb()
        out.append({"mode": "baseline", "busy_before": st.get("busy"), "queued_before": st.get("queued"),
                    "tiny_ttfb_s": round(ttfb, 3), "tiny_total_s": round(total, 3), "tiny_timings": timings,
                    "at": time.time()})
        time.sleep(0.5)
    return out


def main() -> None:
    mode = sys.argv[1]
    if mode == "baseline":
        recs = baseline(int(sys.argv[2]) if len(sys.argv) > 2 else 3)
    else:
        cancel_ms = int(sys.argv[2])
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        recs = []
        for i in range(n):
            seed = int(time.time()) % 100000 + i
            recs.append(trial(mode, cancel_ms, seed))
    with LOG.open("a", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(json.dumps({k: v for k, v in r.items() if k not in ("received_head", "tiny_timings")}))


if __name__ == "__main__":
    main()
