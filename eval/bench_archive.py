"""Archive growth: raw-body delta storage (v1 vs v2) and end-to-end metadata.

Usage:
    python eval/bench_archive.py [--turns 10,50,100,200] [--e2e-turns 50] [--json]

Part 1 replays request bodies straight through ``palimnesis.rawarchive.put_raw``
into a fresh store per run, for delta variant 1 (prefix + suffix) and
variant 2 (prefix + middle + suffix length):

- the 10 live OpenCode 2.1.4 bodies in ``eval/fixtures/opencode-2.1.4/live``;
- synthetic OpenCode-shaped sessions of 10/50/100/200 requests built from
  the first live body (its system prompt, first user message and the real
  ~11 KB ``tools`` array, which follows ``messages``). Each request appends
  one assistant tool call (with reasoning) and its tool result. Two content
  regimes: ``repetitive`` (templated text) and ``random`` (incompressible
  base64 tool outputs from a seeded RNG).

It reports logical bytes (sum of bodies), physical ``raw_bodies`` payload
bytes, DB file bytes, per-table bytes from SQLite ``dbstat``, snapshot/delta
counts, max chain depth, ``put_raw`` time, and ``get_raw`` reconstruction time
by depth (plain read connection, median of repeats per body).

Part 2 replays a synthetic session through the proxy in archive mode against
the fake upstream with recorded-shape SSE responses, then reports per-table
growth (occurrences, blocks, segments, events, aliases, FTS) separately from
raw bodies. It runs with the shipped defaults (delta variant, FULL).

D10.7 bar: adopt v2 only if it saves >= 25% raw bytes on the live replay and
on a synthetic 200-request replay.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import platform
import random
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

from palimnesis import ledger, rawarchive
from palimnesis.api import create_app
from palimnesis.capture import load_exchanges
from palimnesis.config import Settings
from palimnesis.store import Store
from tests.fake_upstream import FakeUpstream
from tests.servers import serve

LIVE_DIR = ROOT / "eval/fixtures/opencode-2.1.4/live/exchanges"
SESSION = "bench-archive"
DEPTH_BUCKETS = [(0, 0), (1, 8), (9, 16), (17, 24), (25, 32)]


def dumps(obj) -> bytes:
    # OpenCode's serialization (verified byte-equal on the live bodies).
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def pct(values: list[float], q: int) -> float:
    if not values:
        return float("nan")
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[q - 1]


# --- workload ----------------------------------------------------------------


class Synthetic:
    """Deterministic OpenCode-shaped tool-loop session."""

    def __init__(self, regime: str, seed: int = 7, tool_bytes: int = 1024) -> None:
        live = load_exchanges(LIVE_DIR)
        base = json.loads(live[0].request_body)
        self.base = base
        self.head = base["messages"][:2]  # system + first user message
        self.regime = regime
        self.rng = random.Random(seed)
        self.tool_bytes = tool_bytes
        self.turns: list[tuple[dict, dict, str, str]] = []  # (assistant, tool, reasoning, args)

    def _turn(self, i: int) -> tuple[dict, dict, str, str]:
        call_id = f"call_{self.rng.getrandbits(96):024x}"
        if self.regime == "repetitive":
            reasoning = (
                f"Step {i}: the previous command finished. I should inspect the next file "
                "and check whether the change compiles before moving on. Let me run it.\n"
            ) * 3
            output = "".join(
                f"src/module_{(i + k) % 17}.py:{k + 1}: def handler_{k}(request): return render(request)\n"
                for k in range(self.tool_bytes // 72)
            )
        else:
            reasoning = (
                f"Step {i}: decoding the next blob and checking its checksum before continuing.\n"
            ) * 3
            raw = self.rng.randbytes(self.tool_bytes * 3 // 4)
            output = base64.b64encode(raw).decode("ascii")
        args = json.dumps({"command": f"python tools/check.py --step {i} --verbose"})
        assistant = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": call_id, "type": "function", "function": {"name": "shell", "arguments": args}}
            ],
            "reasoning_content": reasoning,
        }
        tool = {"role": "tool", "tool_call_id": call_id, "content": output}
        return assistant, tool, reasoning, args

    def turn(self, i: int) -> tuple[dict, dict, str, str]:
        while len(self.turns) <= i:
            self.turns.append(self._turn(len(self.turns)))
        return self.turns[i]

    def body(self, n: int) -> bytes:
        """Request number ``n`` (0-based): head plus ``n`` completed tool turns."""
        messages = list(self.head)
        for i in range(n):
            assistant, tool, _, _ = self.turn(i)
            messages += [assistant, tool]
        obj = {k: v for k, v in self.base.items()}
        obj["messages"] = messages
        return dumps(obj)


def live_bodies() -> list[bytes]:
    return [ex.request_body for ex in load_exchanges(LIVE_DIR)]


def schema_key(body: bytes) -> str:
    obj = json.loads(body)
    system = [m for m in obj["messages"] if m["role"] == "system"][:1]
    return json.dumps([system, obj.get("tools")], sort_keys=True, ensure_ascii=False)


# --- measurement helpers -------------------------------------------------------


def dbstat(path: Path) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT name, count(*), sum(pgsize), sum(payload), sum(unused) FROM dbstat GROUP BY name"
        ).fetchall()
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    finally:
        conn.close()
    tables = {
        name: {"pages": pages, "bytes": size, "payload": payload, "unused": unused}
        for name, pages, size, payload, unused in sorted(rows, key=lambda r: -r[2])
    }
    return {"page_size": page_size, "page_count": page_count, "tables": tables}


def file_bytes(path: Path) -> dict:
    out = {}
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(path) + suffix)
        out["db" + suffix.replace("-", "_")] = p.stat().st_size if p.exists() else 0
    return out


def checkpoint(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def reconstruction_times(path: Path, repeats: int) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        ids = conn.execute("SELECT raw_id, depth FROM raw_bodies ORDER BY raw_id").fetchall()
        by_depth: dict[int, list[float]] = {}
        for raw_id, depth in ids:
            samples = []
            for _ in range(repeats):
                t = time.perf_counter()
                rawarchive.get_raw(conn, raw_id)
                samples.append((time.perf_counter() - t) * 1000)
            by_depth.setdefault(depth, []).append(statistics.median(samples))
    finally:
        conn.close()
    buckets = {}
    for lo, hi in DEPTH_BUCKETS:
        values = [v for d, vs in by_depth.items() if lo <= d <= hi for v in vs]
        if values:
            buckets[f"{lo}-{hi}" if lo != hi else str(lo)] = {
                "n": len(values),
                "p50_ms": round(pct(values, 50), 3),
                "p95_ms": round(pct(values, 95), 3),
            }
    return buckets


# --- part 1: raw archive replay ---------------------------------------------------


async def _replay_raw(path: Path, bodies: list[bytes], variant: int) -> list[float]:
    store = Store.open(path)  # shipped default synchronous (FULL)
    put_ms: list[float] = []
    try:
        await store.write(lambda c: ledger.ensure_session(c, SESSION, "path"))
        branch = ledger.branch_id_for(SESSION)
        previous = None
        for body in bodies:
            key = schema_key(body)
            changed = previous is not None and key != previous
            previous = key

            def put(c, body=body, changed=changed):
                t = time.perf_counter()
                rawarchive.put_raw(c, SESSION, branch, body, schema_changed=changed, variant=variant)
                return (time.perf_counter() - t) * 1000

            put_ms.append(await store.write(put))
    finally:
        store.close()
    return put_ms


def run_raw(workdir: Path, label: str, bodies: list[bytes], variant: int, repeats: int) -> dict:
    path = workdir / f"raw-{label}-v{variant}.db"
    put_ms = asyncio.run(_replay_raw(path, bodies, variant))
    checkpoint(path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        payload, snapshots, deltas, max_depth = conn.execute(
            "SELECT sum(length(payload)), sum(format = 0), sum(format != 0), max(depth) FROM raw_bodies"
        ).fetchone()
        snapshot_bytes = conn.execute(
            "SELECT coalesce(sum(length(payload)), 0) FROM raw_bodies WHERE format = 0"
        ).fetchone()[0]
        for raw_id, body in zip(
            [r[0] for r in conn.execute("SELECT raw_id FROM raw_bodies ORDER BY raw_id")], bodies
        ):
            assert rawarchive.get_raw(conn, raw_id) == body, "reconstruction mismatch"
    finally:
        conn.close()
    stat = dbstat(path)
    logical = sum(len(b) for b in bodies)
    return {
        "requests": len(bodies),
        "variant": variant,
        "logical_bytes": logical,
        "largest_body": max(len(b) for b in bodies),
        "payload_bytes": payload,
        "snapshot_payload_bytes": snapshot_bytes,
        "delta_payload_bytes": payload - snapshot_bytes,
        "payload_ratio": round(payload / logical, 4),
        "raw_bodies_table_bytes": stat["tables"].get("raw_bodies", {}).get("bytes"),
        "snapshots": snapshots,
        "deltas": deltas,
        "max_depth": max_depth,
        "files": file_bytes(path),
        "dbstat": stat,
        "put_raw_ms": {"p50": round(pct(put_ms, 50), 3), "p95": round(pct(put_ms, 95), 3)},
        "get_raw_by_depth": reconstruction_times(path, repeats),
    }


# --- part 2: end-to-end metadata growth -----------------------------------------------


def _chunk(cid: str, delta: dict, finish=None, usage=None) -> bytes:
    obj = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": 1792873194,
        "model": "qwen3.8-flash-next-iq3_xxs",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    if usage:
        obj["usage"] = usage
    return b"data: " + json.dumps(obj, ensure_ascii=False).encode() + b"\n\n"


def _pieces(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def sse_for(turn: tuple[dict, dict, str, str], i: int) -> bytes:
    """Recorded-shape Strata stream for one assistant tool call (live chunk layout)."""
    assistant, _, reasoning, args = turn
    call = assistant["tool_calls"][0]
    cid = f"chatcmpl-bench{i:08d}"
    out = [_chunk(cid, {"role": "assistant", "content": ""}), b": keep-alive\n\n"]
    out += [_chunk(cid, {"reasoning_content": p}) for p in _pieces(reasoning, 5)]
    out.append(_chunk(cid, {"tool_calls": [{"index": 0, "id": call["id"], "type": "function",
                                            "function": {"name": "shell", "arguments": ""}}]}))
    out += [_chunk(cid, {"tool_calls": [{"index": 0, "function": {"arguments": p}}]})
            for p in _pieces(args, 6)]
    out.append(_chunk(cid, {}, "tool_calls", {"prompt_tokens": 5000 + i, "completion_tokens": 80,
                                              "total_tokens": 5080 + i}))
    out.append(b"data: [DONE]\n\n")
    return b"".join(out)


def run_e2e(workdir: Path, turns: int, checkpoints: list[int]) -> dict:
    synth = Synthetic("repetitive")
    path = workdir / "e2e.db"
    fake = FakeUpstream()
    growth = {}
    ttfb_ms: list[float] = []
    sse_bytes = 0
    with serve(fake.app()) as upstream_url:
        app = create_app(Settings(upstream_base_url=upstream_url, db_path=path))
        with serve(app, palimnesis=True) as proxy_url:
            url = f"{proxy_url}/s/{SESSION}/v1/chat/completions"
            with httpx.Client(timeout=60) as client:
                for n in range(turns):
                    body = synth.body(n)
                    sse = sse_for(synth.turn(n), n)
                    sse_bytes += len(sse)
                    fake.respond_sse([sse[i : i + 97] for i in range(0, len(sse), 97)])
                    t = time.perf_counter()
                    with client.stream("POST", url, content=body) as r:
                        chunks = r.iter_raw()
                        first = next(chunks)
                        ttfb_ms.append((time.perf_counter() - t) * 1000)
                        got = first + b"".join(chunks)
                    if r.status_code != 200 or got != sse:
                        raise RuntimeError(f"turn {n}: status {r.status_code}: {got[:300]!r}")
                    if n + 1 in checkpoints:
                        growth[n + 1] = _e2e_snapshot(path)
    checkpoint(path)
    final = _e2e_snapshot(path)
    final["files"] = file_bytes(path)
    final["sse_bytes_relayed"] = sse_bytes
    final["ttfb_ms"] = {
        "first10_p50": round(statistics.median(ttfb_ms[:10]), 2),
        "last10_p50": round(statistics.median(ttfb_ms[-10:]), 2),
    }
    return {"turns": turns, "checkpoints": growth, "final": final}


_COUNTED = ("raw_bodies", "requests", "occurrences", "blocks", "segments", "events", "aliases",
            "attempts", "generations")


def _e2e_snapshot(path: Path) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in _COUNTED}
        payload = conn.execute("SELECT sum(length(payload)) FROM raw_bodies").fetchone()[0]
        logical = conn.execute("SELECT sum(total_len) FROM raw_bodies").fetchone()[0]
        seg_bytes = conn.execute("SELECT sum(length(bytes)) FROM segments").fetchone()[0]
        stat = conn.execute(
            "SELECT name, sum(pgsize) FROM dbstat GROUP BY name ORDER BY 2 DESC"
        ).fetchall()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    tables = dict(stat)
    raw = tables.get("raw_bodies", 0)
    fts = sum(v for k, v in tables.items() if k.startswith("fts_"))
    index_bytes = sum(v for k, v in tables.items() if k.startswith("sqlite_autoindex"))
    total = sum(tables.values())
    return {
        "rows": rows,
        "raw_logical_bytes": logical,
        "raw_payload_bytes": payload,
        "segment_text_bytes": seg_bytes,
        "bytes": {
            "total_pages": total,
            "raw_bodies": raw,
            "metadata_excl_raw": total - raw,
            "fts": fts,
            "autoindexes": index_bytes,
            "per_table": tables,
        },
        "schema_version": version,
    }


# --- report --------------------------------------------------------------------------


def environment(synchronous: str = "FULL") -> dict:
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
        "synchronous": synchronous,
        "delta_default_variant": rawarchive.DEFAULT_VARIANT,
        "max_depth": rawarchive.DEFAULT_MAX_DEPTH,
    }


def run(turn_counts: list[int], e2e_turns: int, repeats: int, workdir: Path) -> dict:
    report = {"environment": environment(), "raw": {}, "e2e": None}
    empty = workdir / "empty.db"
    Store.open(empty).close()
    checkpoint(empty)
    report["empty_db"] = {"files": file_bytes(empty), "page_count": dbstat(empty)["page_count"]}
    live = live_bodies()
    report["raw"]["live"] = {f"v{v}": run_raw(workdir, "live", live, v, repeats) for v in (1, 2)}
    for regime in ("repetitive", "random"):
        synth = Synthetic(regime)
        for n in turn_counts:
            bodies = [synth.body(i) for i in range(n)]
            report["raw"][f"{regime}-{n}"] = {
                f"v{v}": run_raw(workdir, f"{regime}-{n}", bodies, v, repeats) for v in (1, 2)
            }
    for entry in report["raw"].values():
        v1, v2 = entry["v1"]["payload_bytes"], entry["v2"]["payload_bytes"]
        t1, t2 = entry["v1"]["raw_bodies_table_bytes"], entry["v2"]["raw_bodies_table_bytes"]
        entry["v2_savings_payload"] = round(1 - v2 / v1, 4)
        entry["v2_savings_table"] = round(1 - t2 / t1, 4)
    if e2e_turns:
        checkpoints = sorted({10, 25, e2e_turns} & set(range(1, e2e_turns + 1)))
        report["e2e"] = run_e2e(workdir, e2e_turns, checkpoints)
    biggest = max(turn_counts)
    keys = ["live"] + [f"{r}-{biggest}" for r in ("repetitive", "random")]
    report["d10_7"] = {
        "bar": 0.25,
        "savings": {k: report["raw"][k]["v2_savings_payload"] for k in keys},
        "meets_bar": all(report["raw"][k]["v2_savings_payload"] >= 0.25 for k in keys),
    }
    return report


def print_table(report: dict) -> None:
    print(f"{'workload':18} {'var':>3} {'reqs':>4} {'logical':>10} {'payload':>10} {'ratio':>6} "
          f"{'table':>10} {'snap':>4} {'delta':>5} {'depth':>5} {'file':>10} {'get p95@max':>11}")
    for name, entry in report["raw"].items():
        for v in ("v1", "v2"):
            r = entry[v]
            deepest = list(r["get_raw_by_depth"].values())[-1]["p95_ms"]
            print(f"{name:18} {v:>3} {r['requests']:>4} {r['logical_bytes']:>10} "
                  f"{r['payload_bytes']:>10} {r['payload_ratio']:>6.3f} "
                  f"{r['raw_bodies_table_bytes']:>10} {r['snapshots']:>4} {r['deltas']:>5} "
                  f"{r['max_depth']:>5} {r['files']['db']:>10} {deepest:>9.2f}ms")
        print(f"{'':18} v2 saves {entry['v2_savings_payload']:.1%} payload, "
              f"{entry['v2_savings_table']:.1%} raw_bodies table bytes")
    print(f"empty schema DB file: {report['empty_db']['files']['db']} bytes")
    print("D10.7:", json.dumps(report["d10_7"]))
    if report["e2e"]:
        f = report["e2e"]["final"]
        print(f"e2e {report['e2e']['turns']} turns: rows {f['rows']}")
        b = f["bytes"]
        print(f"  pages total {b['total_pages']}  raw_bodies {b['raw_bodies']}  "
              f"metadata (excl raw) {b['metadata_excl_raw']}  fts {b['fts']}  "
              f"autoindexes {b['autoindexes']}  ttfb {f['ttfb_ms']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--turns", default="10,50,100,200")
    parser.add_argument("--e2e-turns", type=int, default=50)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="print only the JSON report")
    parser.add_argument("--out", type=Path, help="also write the JSON report here")
    args = parser.parse_args(argv)
    turn_counts = [int(x) for x in args.turns.split(",")]
    with tempfile.TemporaryDirectory(prefix="palimnesis-bench-archive-") as tmp:
        report = run(turn_counts, args.e2e_turns, args.repeats, Path(tmp))
    if args.out:
        args.out.write_text(json.dumps(report, indent=2))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_table(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
