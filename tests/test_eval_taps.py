"""The eval taps pass a client's disconnect along (D45.9.16): OpenCode killed mid-stream
must look, to the proxy and to the upstream, like a client that went away, not like a
turn read to the end. Real loopback sockets: client → front tap → proxy → upstream tap
→ fake upstream."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

from palimnesis.api import create_app
from palimnesis.config import Settings

from .fake_upstream import FakeUpstream
from .servers import serve

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
import needle  # noqa: E402
import oc_stack  # noqa: E402

sys.path.remove(str(ROOT / "eval"))


def chunk(text: str) -> bytes:
    return b"data: " + json.dumps({"choices": [{"index": 0, "delta": {"content": text}}]}).encode() + b"\n\n"


def wait_for(cond, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


def test_a_client_that_leaves_mid_stream_reaches_the_proxy_and_the_upstream(tmp_path):
    fake = FakeUpstream()
    fake.respond_sse([chunk("a"), (30.0, chunk("b")), b"data: [DONE]\n\n"])
    fake.respond_sse([chunk("c"), b"data: [DONE]\n\n"])
    with serve(fake.app()) as upstream_url:
        back = needle.Tap(upstream_url, tmp_path / "bodies", needle.SlotGate(None))
        back_server, back_thread = needle.serve_in_thread(back, back_port := needle.free_port())
        settings = Settings(upstream_base_url=f"http://127.0.0.1:{back_port}",
                            db_path=tmp_path / "archive.db")
        with serve(create_app(settings), palimnesis=True) as proxy_url:
            front = needle.Tap(proxy_url, tmp_path / "front", needle.SlotGate(None))
            front_server, front_thread = needle.serve_in_thread(front, front_port := needle.free_port())
            try:
                body = {"model": "m", "stream": True, "messages": [{"role": "user", "content": "hi"}]}
                t0 = time.monotonic()
                url = f"http://127.0.0.1:{front_port}/s/sess-1/v1/chat/completions"
                with httpx.Client(timeout=10) as c, c.stream("POST", url, json=body) as r:
                    assert r.status_code == 200
                    next(r.iter_raw())
                # The upstream saw its reader leave long before its 30 s chunk.
                assert wait_for(lambda: fake.closed_streams), "upstream stream was read to the end"
                assert time.monotonic() - t0 < 15
                assert not fake.completed_streams
                assert wait_for(lambda: front.calls and back.calls)
                assert front.calls[-1]["client_disconnect"] is True
                assert back.calls[-1]["client_disconnect"] is True
                # A cancel is neither a proxy rejection nor an upstream failure.
                summ = oc_stack.call_summary(back.calls, front.calls)
                assert summ["proxy_rejections"] == 0 and summ["client_cancels"] == 1
                assert oc_stack.failed(front.calls) == [] and oc_stack.failed(back.calls) == []
                # The client never stored the cut-off turn; its next request omits it, and
                # the proxy accepts that (D13.1) instead of answering 409.
                body["messages"].append({"role": "user", "content": "again"})
                r = httpx.post(url, json=body, timeout=10)
                assert r.status_code == 200, r.text
            finally:
                for server, thread in ((front_server, front_thread), (back_server, back_thread)):
                    server.should_exit = True
                    thread.join(timeout=10)


def test_a_stream_read_to_the_end_is_not_a_disconnect(tmp_path):
    fake = FakeUpstream()
    fake.respond_sse([chunk("a"), b"data: [DONE]\n\n"])
    with serve(fake.app()) as upstream_url:
        tap = needle.Tap(upstream_url, tmp_path / "bodies", needle.SlotGate(None))
        server, thread = needle.serve_in_thread(tap, port := needle.free_port())
        try:
            body = {"model": "m", "stream": True, "messages": [{"role": "user", "content": "hi"}]}
            r = httpx.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=body, timeout=10)
            assert r.status_code == 200 and r.content.endswith(b"data: [DONE]\n\n")
            assert wait_for(lambda: tap.calls)
            assert "client_disconnect" not in tap.calls[-1]
            assert fake.completed_streams and not fake.closed_streams
        finally:
            server.should_exit = True
            thread.join(timeout=10)
