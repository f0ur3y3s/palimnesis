"""Passthrough overhead: direct vs. proxied latency against the fake upstream.

Usage:
    python eval/bench_passthrough.py [--n 500] [--body-kb 64] [--json]

Measures full-response latency for non-streaming JSON and time-to-first-byte
plus full latency for SSE, interleaving direct and proxied requests so drift
affects both equally. Phase 0 target: proxied-minus-direct p95 under 5 ms.
Report the hardware alongside the numbers.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from palimnesis.api import create_app  # noqa: E402
from palimnesis.config import Settings  # noqa: E402
from tests.fake_upstream import FakeUpstream  # noqa: E402
from tests.servers import serve  # noqa: E402

SSE_EVENTS = [b'data: {"choices":[{"delta":{"content":"tok"}}]}\n\n'] * 50 + [
    b"data: [DONE]\n\n"
]


def _pct(values: list[float], q: float) -> float:
    return statistics.quantiles(values, n=100, method="inclusive")[q - 1] if len(values) > 1 else values[0]


def _summary(ms: list[float]) -> dict:
    return {"p50_ms": round(_pct(ms, 50), 3), "p95_ms": round(_pct(ms, 95), 3), "n": len(ms)}


def _timed_json(client: httpx.Client, url: str, body: bytes) -> float:
    t = time.perf_counter()
    client.post(url, content=body).read()
    return (time.perf_counter() - t) * 1000


def _timed_sse(client: httpx.Client, url: str) -> tuple[float, float]:
    t = time.perf_counter()
    with client.stream("POST", url, content=b'{"stream":true}') as r:
        chunks = r.iter_raw()
        next(chunks)
        first = (time.perf_counter() - t) * 1000
        for _ in chunks:
            pass
    return first, (time.perf_counter() - t) * 1000


def run(n: int, body_kb: int) -> dict:
    fake = FakeUpstream()
    body = b'{"messages":[{"role":"user","content":"' + b"x" * (body_kb * 1024) + b'"}]}'
    reply = b'{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'
    results: dict[str, dict[str, list[float]]] = {
        k: {"direct": [], "proxy": []} for k in ("json_total", "sse_first_byte", "sse_total")
    }
    with serve(fake.app()) as upstream_url:
        with serve(create_app(Settings(upstream_base_url=upstream_url)), palimnesis=True) as proxy_url:
            targets = {
                "direct": f"{upstream_url}/v1/chat/completions",
                "proxy": f"{proxy_url}/s/bench/v1/chat/completions",
            }
            with httpx.Client(timeout=30) as client:
                for i in range(n + 20):  # first 20 rounds are warm-up
                    for name, url in targets.items():
                        fake.respond_json(reply)
                        j = _timed_json(client, url, body)
                        fake.respond_sse(SSE_EVENTS)
                        first, total = _timed_sse(client, url)
                        if i >= 20:
                            results["json_total"][name].append(j)
                            results["sse_first_byte"][name].append(first)
                            results["sse_total"][name].append(total)
    report = {
        "hardware": {"machine": platform.machine(), "processor": platform.processor(), "platform": platform.platform()},
        "python": platform.python_version(),
        "workload": {"rounds": n, "request_body_kb": body_kb, "sse_events": len(SSE_EVENTS)},
    }
    for metric, by_target in results.items():
        overhead = [p - d for p, d in zip(by_target["proxy"], by_target["direct"])]
        report[metric] = {
            "direct": _summary(by_target["direct"]),
            "proxy": _summary(by_target["proxy"]),
            "paired_overhead": _summary(overhead),
        }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=500)
    parser.add_argument("--body-kb", type=int, default=64)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run(args.n, args.body_kb)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for metric in ("json_total", "sse_first_byte", "sse_total"):
            r = report[metric]
            print(
                f"{metric:15} direct p95 {r['direct']['p95_ms']:7.3f} ms  "
                f"proxy p95 {r['proxy']['p95_ms']:7.3f} ms  "
                f"paired overhead p50 {r['paired_overhead']['p50_ms']:6.3f} / p95 {r['paired_overhead']['p95_ms']:6.3f} ms"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
