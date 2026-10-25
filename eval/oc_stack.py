"""The process stack for real-OpenCode evaluation runs, and the gate inputs read from it.

    OpenCode → front tap → proxy child (``needle.py proxy``) → upstream tap → Strata

- The **upstream tap** (``needle.Tap`` with the D39 gate) waits for an idle slot before
  every inference request and keeps each exact upstream body and stream.
- The **front tap** (``needle.Tap`` without a gate) keeps each client request, the proxy's
  own status and stream, so a proxy rejection is visible without reading logs.
- The proxy child runs the ``serve`` app with ``serve``'s defaults (no
  ``--input-budget``), ``deadline_s`` 3600 (D45.4), and an explicit transcripts root
  outside the records tree.

Records (bodies, streams, logs, archive) go to ``records``; nothing here writes into a
workspace tree.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import needle
import oc_harness as oc

SLOW_UPSTREAM_S = 600.0  # D45.13: flagged, the proxy's default deadline


class Stack:
    def __init__(self, records: Path, upstream: str, settings: dict, *, passthrough: bool = False,
                 transcripts: Path | None = None):
        self.records = records
        self.gate = needle.SlotGate(upstream)
        self.tap = needle.Tap(upstream, records / "bodies", self.gate)
        self.tap_server, self.tap_thread = needle.serve_in_thread(self.tap, tap_port := needle.free_port())
        self.settings = dict(settings, deadline_s=3600.0)
        if transcripts is not None and not passthrough:
            self.settings["transcripts"] = str(transcripts)
        self.transcripts = transcripts if not passthrough else None
        self.proxy = needle.ProxyProcess(records, f"http://127.0.0.1:{tap_port}", self.settings,
                                         input_budget=None, passthrough=passthrough)
        self.proxy.start()
        self.front = needle.Tap(self.proxy.url, records / "front", needle.SlotGate(None))
        self.front_port = needle.free_port()
        self.front_server, self.front_thread = needle.serve_in_thread(self.front, self.front_port)

    def base_url(self, session: str) -> str:
        """``palimnesis session url <session>`` on the front tap's port."""
        _, url = oc.session_base_url(self.front_port, session)
        return url

    def restart_proxy(self) -> None:
        self.proxy.stop()
        self.proxy.start()

    def settle(self, timeout: float = 30) -> None:
        deadline = time.time() + timeout
        while (self.tap.inflight or self.front.inflight) and time.time() < deadline:
            time.sleep(0.05)

    def stop(self) -> None:
        self.proxy.stop()
        for server, thread in ((self.front_server, self.front_thread), (self.tap_server, self.tap_thread)):
            server.should_exit = True
            thread.join(10)


def call_summary(upstream: list[dict], front: list[dict]) -> dict:
    """Per-turn status accounting: the proxy's answers to the client (front tap) and the
    upstream's answers to the proxy (upstream tap). A failed front call while every
    upstream call succeeded is a proxy rejection. A call the client left (OpenCode killed
    mid-stream) is a client cancel, neither."""
    proxy_bad, up_bad = failed(front), failed(upstream)
    return {"proxy_statuses": [c.get("status") for c in front],
            "proxy_stream_errors": [c.get("stream_error") for c in front if c.get("stream_error")],
            "upstream_statuses": [c.get("status") for c in upstream],
            "proxy_rejections": len(proxy_bad) if not up_bad else 0,
            "upstream_failures": len(up_bad),
            "client_cancels": sum(1 for c in front if c.get("client_disconnect")),
            "slow_upstream_calls": [c["n"] for c in upstream if (c.get("upstream_s") or 0) > SLOW_UPSTREAM_S],
            "max_upstream_s": max((c.get("upstream_s") or 0 for c in upstream), default=0)}


def failed(calls: list[dict]) -> list[dict]:
    """Calls answered with an error status or an in-stream error."""
    return [c for c in calls if c.get("status") != 200 or c.get("stream_error")]


def client_texts(records: Path, front_calls: list[dict]) -> list[str]:
    """Client-visible text: every client request body and every proxy response stream."""
    from gate_inputs import sse_texts, strings_of

    out = []
    for c in front_calls:
        req = records / "front" / f"{c['n']:04d}.json"
        resp = records / "front" / f"{c['n']:04d}.resp.sse"
        if req.exists():
            try:
                out += strings_of(json.loads(req.read_bytes()))
            except ValueError:
                out.append(req.read_text(encoding="utf-8", errors="replace"))
        if resp.exists():
            out += sse_texts(resp.read_bytes())
    return out
