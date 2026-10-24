"""Commit latency (FULL vs NORMAL) and archive-relay delay vs passthrough.

Usage:
    python eval/bench_commit.py [--n 500] [--relay-n 10] [--burst-n 60] [--json]

Part 1 times ``await Store.write(fn)`` from the event loop (thread hop,
``BEGIN IMMEDIATE``, the inserts, ``COMMIT``) for a segment-like batch: the
payload split into 64-byte ``segments`` rows plus one ``events`` row, as
``ledger.commit_batch`` writes. Payloads 256 B, 4 KiB and 16 KiB; FULL and
NORMAL stores on the same filesystem, interleaved round-robin so drift hits
all configurations alike. ``fn_ms`` is time inside the transaction before
``COMMIT``; ``total - fn`` approximates the commit (WAL sync) cost.

Part 2 streams ~200 small SSE deltas from the fake upstream through a
passthrough proxy and archive proxies (FULL; NORMAL as a diagnostic),
interleaved. Each archive request uses a new session. ``paced`` sleeps
between deltas like a decoding server (Strata decodes ~25 ms/token);
``burst`` sends all deltas at once (throughput view). A ``FakeUpstream`` subclass
timestamps each chunk as it is handed to the server, so per-event relay delay
is client arrival minus upstream send for the same event (one process, one
``perf_counter``).

Delays are quantized by the Windows timer (``GetTickCount64``, 15.6 ms), which
also governs the relay's batch-age timeout; the measured upstream send gap
is reported as the effective pacing.

Judged against the former 25 ms batch-age budget (the relay now flushes when
its read queue drains, D12; commit latency is then added per paced event).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from mnemon import archive, ledger, rawarchive
from mnemon.api import create_app
from mnemon.config import Settings
from mnemon.store import Store
from tests.fake_upstream import FakeUpstream
from tests.servers import serve

SIZES = [256, 4096, 16384]
SEGMENT_BYTES = 64
MODES = ["FULL", "NORMAL"]


def pct(values: list[float], q: int) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[q - 1]


def summary(ms: list[float]) -> dict:
    return {
        "n": len(ms),
        "p50_ms": round(pct(ms, 50), 3),
        "p95_ms": round(pct(ms, 95), 3),
        "p99_ms": round(pct(ms, 99), 3),
        "max_ms": round(max(ms), 3),
    }


# --- part 1: Store.write commit latency -------------------------------------------


def _prepare(conn: sqlite3.Connection) -> str:
    """Parent rows a segment needs: session, branch, raw body, request, occurrence, block."""
    session = "bench-commit"
    branch = ledger.ensure_session(conn, session, "path")
    raw_id = rawarchive.put_raw(conn, session, branch, b'{"messages":[]}')
    conn.execute(
        "INSERT INTO requests VALUES ('req_b', ?, ?, ?, ?, 1, 'fp', 1, NULL, NULL, NULL, '{}', ?)",
        (session, branch, ledger.ENDPOINT_CHAT, raw_id, time.time()),
    )
    conn.execute("INSERT INTO attempts VALUES ('att_b', 'req_b', 1, ?)", (time.time(),))
    conn.execute(
        "INSERT INTO occurrences VALUES ('occ_b', ?, 1, NULL, 'assistant', 'both', 'generated',"
        " 'req_b', NULL, '{}', '')",
        (branch,),
    )
    conn.execute("INSERT INTO blocks VALUES ('blk_b', 'occ_b', 0, 'text', 'utf-8', '{}')")
    return "blk_b"


async def commit_latency(workdir: Path, n: int, warmup: int) -> dict:
    stores = {m: Store.open(workdir / f"commit-{m}.db", synchronous=m) for m in MODES}
    try:
        for store in stores.values():
            await store.write(_prepare)
        seq = {m: 0 for m in MODES}
        results = {(m, s): {"total": [], "fn": []} for m in MODES for s in SIZES}
        for i in range(n + warmup):
            for size in SIZES:
                for mode in MODES:
                    rows = max(1, size // SEGMENT_BYTES)
                    start = seq[mode]
                    seq[mode] += rows
                    data = [os.urandom(SEGMENT_BYTES) for _ in range(rows)]

                    def batch(c, start=start, data=data):
                        t = time.perf_counter()
                        c.executemany(
                            "INSERT INTO segments VALUES ('blk_b', ?, ?)",
                            [(start + k, d) for k, d in enumerate(data)],
                        )
                        c.execute(
                            "INSERT INTO events (request_id, attempt_id, kind, payload, at)"
                            " VALUES ('req_b', 'att_b', 'delivery_progress', ?, ?)",
                            (json.dumps({"bytes_forwarded": start}), time.time()),
                        )
                        return (time.perf_counter() - t) * 1000

                    t = time.perf_counter()
                    fn_ms = await stores[mode].write(batch)
                    total = (time.perf_counter() - t) * 1000
                    if i >= warmup:
                        results[(mode, size)]["total"].append(total)
                        results[(mode, size)]["fn"].append(fn_ms)
        diagnostics = {m: await s.diagnostics() for m, s in stores.items()}
    finally:
        for store in stores.values():
            store.close()
    out = {"segment_row_bytes": SEGMENT_BYTES, "diagnostics": diagnostics, "results": {}}
    for (mode, size), r in results.items():
        commit_only = [t - f for t, f in zip(r["total"], r["fn"])]
        out["results"][f"{mode}-{size}"] = {
            "mode": mode,
            "payload_bytes": size,
            "rows": max(1, size // SEGMENT_BYTES) + 1,
            "total": summary(r["total"]),
            "fn": summary(r["fn"]),
            "total_minus_fn": summary(commit_only),
        }
    return out


# --- part 2: relay delay vs passthrough ----------------------------------------------


def _event(text: str) -> bytes:
    obj = {"id": "chatcmpl-bench", "object": "chat.completion.chunk", "created": 1792873194,
           "model": "m", "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}
    return b"data: " + json.dumps(obj).encode() + b"\n\n"


def sse_events(count: int) -> list[bytes]:
    first = (b'data: {"id": "chatcmpl-bench", "object": "chat.completion.chunk", "created": 1792873194, '
             b'"model": "m", "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, '
             b'"finish_reason": null}]}\n\n')
    tokens = [_event(f" tok{i}") for i in range(count)]
    finish = (b'data: {"id": "chatcmpl-bench", "object": "chat.completion.chunk", "created": 1792873194, '
              b'"model": "m", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], '
              b'"usage": {"prompt_tokens": 5, "completion_tokens": 200, "total_tokens": 205}}\n\n')
    return [first, *tokens, finish, b"data: [DONE]\n\n"]


class TimedUpstream(FakeUpstream):
    """Fake upstream that records when it hands each scripted chunk to the server."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[list[float]] = []

    async def _stream(self, label, chunks):
        times: list[float] = []
        self.sent.append(times)
        async for data in super()._stream(label, [(d, c) for d, c in chunks]):
            times.append(time.perf_counter())
            yield data


def _timed_stream(client: httpx.Client, url: str, body: bytes) -> tuple[float, list[float], float]:
    """Request start, absolute arrival time of each complete SSE event, and end."""
    arrivals: list[float] = []
    t0 = time.perf_counter()
    buffer = b""
    with client.stream("POST", url, content=body) as r:
        if r.status_code != 200:
            raise RuntimeError(f"{url}: status {r.status_code}: {r.read()[:300]!r}")
        for chunk in r.iter_raw():
            now = time.perf_counter()
            buffer += chunk
            complete = buffer.count(b"\n\n")
            arrivals += [now] * (complete - len(arrivals))
    return t0, arrivals, time.perf_counter()


def relay_delay(workdir: Path, deltas: int, paced_n: int, burst_n: int, gap_s: float) -> dict:
    """Per-event relay delay = client arrival - upstream send of the same event."""
    events = sse_events(deltas)
    fake = TimedUpstream()
    body = json.dumps({"model": "m", "stream": True,
                       "messages": [{"role": "user", "content": "hi"}]}).encode()
    out = {"deltas": deltas, "events_per_stream": len(events), "gap_s": gap_s}
    with serve(fake.app()) as upstream_url:
        apps = {
            "passthrough": create_app(Settings(upstream_base_url=upstream_url)),
            "archive_FULL": create_app(Settings(upstream_base_url=upstream_url,
                                                db_path=workdir / "relay-full.db")),
            "archive_NORMAL": create_app(Settings(upstream_base_url=upstream_url,
                                                  db_path=workdir / "relay-normal.db",
                                                  synchronous="NORMAL")),
        }
        with (
            serve(apps["passthrough"], mnemon=True) as pt,
            serve(apps["archive_FULL"], mnemon=True) as af,
            serve(apps["archive_NORMAL"], mnemon=True) as an,
        ):
            urls = {"passthrough": pt, "archive_FULL": af, "archive_NORMAL": an}
            with httpx.Client(timeout=120) as client:
                for label, rounds, gap in (("paced", paced_n, gap_s), ("burst", burst_n, 0.0)):
                    chunks = [(gap if gap and 0 < k < len(events) - 1 else 0.0, e)
                              for k, e in enumerate(events)]
                    data = {name: {"ttfb": [], "first": [], "delay": [], "batches": [],
                                   "gap": [], "total": []} for name in urls}
                    for i in range(rounds + 3):  # 3 warm-up rounds
                        for name, base in urls.items():
                            fake.respond_sse(chunks)
                            url = f"{base}/s/bench-{label}-{name}-{i}/v1/chat/completions"
                            t0, arrivals, t_end = _timed_stream(client, url, body)
                            sent = fake.sent[-1]
                            if len(arrivals) != len(events) or len(sent) != len(events):
                                raise RuntimeError(f"{name}: {len(arrivals)}/{len(sent)} events")
                            if i < 3:
                                continue
                            d = data[name]
                            d["ttfb"].append((arrivals[0] - t0) * 1000)
                            d["first"].append((arrivals[0] - sent[0]) * 1000)
                            d["delay"] += [(a - s) * 1000 for a, s in zip(arrivals, sent)]
                            d["batches"].append(len(set(arrivals)))
                            d["gap"] += [(b - a) * 1000 for a, b in zip(sent[1:], sent[2:-1])]
                            d["total"].append((t_end - t0) * 1000)
                    result = {}
                    for name, d in data.items():
                        result[name] = {
                            "ttfb_first_event": summary(d["ttfb"]),
                            "first_event_relay_delay": summary(d["first"]),
                            "per_event_relay_delay": summary(d["delay"]),
                            "upstream_send_gap": summary(d["gap"]) if d["gap"] else None,
                            "client_batches_per_stream": statistics.median(d["batches"]),
                            "total": summary(d["total"]),
                        }
                    base_ = result["passthrough"]
                    for name in ("archive_FULL", "archive_NORMAL"):
                        r = result[name]
                        r["added_vs_passthrough_p50_ms"] = {
                            k: round(r[k]["p50_ms"] - base_[k]["p50_ms"], 3)
                            for k in ("ttfb_first_event", "per_event_relay_delay", "total")}
                        r["added_vs_passthrough_p95_ms"] = {
                            k: round(r[k]["p95_ms"] - base_[k]["p95_ms"], 3)
                            for k in ("ttfb_first_event", "per_event_relay_delay", "total")}
                    out[label] = result
    return out


# --- report ------------------------------------------------------------------------------


def environment() -> dict:
    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                                  check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    return {
        "commit": os.environ.get("BENCH_COMMIT") or git("rev-parse", "HEAD"),
        "dirty": os.environ.get("BENCH_DIRTY") or bool(git("status", "--porcelain")),
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpus": os.cpu_count(),
        "batch_flush": "queue-drain (D12)",
        "batch_max_bytes": archive.BATCH_MAX_BYTES,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=500)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--deltas", type=int, default=200)
    parser.add_argument("--gap-ms", type=float, default=25.0)
    parser.add_argument("--relay-n", type=int, default=10)
    parser.add_argument("--burst-n", type=int, default=60)
    parser.add_argument("--json", action="store_true", help="print only the JSON report")
    parser.add_argument("--out", type=Path, help="also write the JSON report here")
    parser.add_argument("--dir", type=Path, help="directory for the databases (default: temp)")
    args = parser.parse_args(argv)
    report = {"environment": environment()}
    with tempfile.TemporaryDirectory(prefix="mnemon-bench-commit-", dir=args.dir) as tmp:
        report["environment"]["db_dir"] = tmp
        report["commit"] = asyncio.run(commit_latency(Path(tmp), args.n, args.warmup))
        report["relay"] = relay_delay(Path(tmp), args.deltas, args.relay_n, args.burst_n,
                                      args.gap_ms / 1000)
    limit = 25.0  # the former batch-age budget, ms
    full_p95 = {k: v["total"]["p95_ms"] for k, v in report["commit"]["results"].items()
                if v["mode"] == "FULL"}
    report["verdict"] = {"batch_max_age_ms": limit, "full_p95_ms": full_p95,
                         "full_p95_under_age": all(v < limit for v in full_p95.values()),
                         "full_p95_max_fraction_of_age": round(max(full_p95.values()) / limit, 3)}
    if args.out:
        args.out.write_text(json.dumps(report, indent=2))
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print(f"{'config':14} {'p50':>8} {'p95':>8} {'p99':>8} {'max':>8}  (Store.write total, ms)  commit-only p95")
    for name, r in report["commit"]["results"].items():
        t = r["total"]
        print(f"{name:14} {t['p50_ms']:8.3f} {t['p95_ms']:8.3f} {t['p99_ms']:8.3f} {t['max_ms']:8.3f}"
              f"  {r['total_minus_fn']['p95_ms']:8.3f}")
    for label in ("paced", "burst"):
        print(f"relay {label} (ms; relay delay = client arrival - upstream send):")
        for name, r in report["relay"][label].items():
            gap = r["upstream_send_gap"]
            print(f"  {name:15} ttfb p50/p95 {r['ttfb_first_event']['p50_ms']:7.2f}/"
                  f"{r['ttfb_first_event']['p95_ms']:7.2f}  per-event delay p50/p95/max "
                  f"{r['per_event_relay_delay']['p50_ms']:6.2f}/{r['per_event_relay_delay']['p95_ms']:6.2f}/"
                  f"{r['per_event_relay_delay']['max_ms']:6.2f}  batches {r['client_batches_per_stream']}"
                  f"  total p50 {r['total']['p50_ms']:8.2f}"
                  + (f"  send gap p50 {gap['p50_ms']:.2f}" if gap else ""))
    print("verdict:", json.dumps(report["verdict"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
