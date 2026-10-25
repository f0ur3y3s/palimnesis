"""Proactive-recall selection latency against a large archive (Phase 3, plan §2).

Usage:
    python eval/bench_recall.py [--tokens 1000000] [--queries 60] [--seed 5] [--json]

Archives one synthetic OpenCode-shaped session of about ``--tokens`` tokens (tool
outputs of 300-6000 tokens with planted identifiers) in a fresh store, then times
``FtsExcerpts.select`` for new user instructions naming planted identifiers, with
everything but the newest groups absent from the view (the worst case: every
archived block is a candidate). Reports p50/p95/max selection latency, hit rate,
items and charge. Target: p95 <= 50 ms at 1M tokens.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from palimnesis import ledger  # noqa: E402
from palimnesis.chat import parse  # noqa: E402
from palimnesis.fingerprint import fingerprint_v1  # noqa: E402
from palimnesis.recall import FtsExcerpts  # noqa: E402
from palimnesis.store import Store  # noqa: E402
from palimnesis.upstreams.strata import tokens  # noqa: E402

WORDS = ("def class return self value result request handler render module config import "
         "from if else for while try except raise async await parse token stream buffer "
         "cache index offset length error path file line column status header body").split()


@dataclass
class BaseView:
    manifest: list
    included_excerpts: tuple = ()


def session(rng: random.Random, target_tokens: int, counter):
    messages = [{"role": "system", "content": "You are a coding agent."},
                {"role": "user", "content": "work through the backlog"}]
    planted, total, i = [], 0, 0
    while total < target_tokens:
        n_tokens = int(rng.uniform(300, 6000))
        lines = []
        while sum(len(line) for line in lines) < n_tokens * 4:
            lines.append(" ".join(rng.choice(WORDS) for _ in range(rng.randint(6, 14))))
        ident = f"ERR_{rng.randint(1000, 9999)}_{i}"
        lines[rng.randrange(len(lines))] = f"{ident} raised in module_{i}.handler()"
        planted.append(ident)
        text = "\n".join(lines)
        total += counter.count(text)
        messages.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": f"call_{i}", "type": "function",
             "function": {"name": "shell", "arguments": json.dumps({"cmd": f"run {i}"})}}]})
        messages.append({"role": "tool", "tool_call_id": f"call_{i}", "content": text})
        i += 1
    return messages, planted, total


async def main_async(a) -> dict:
    rng = random.Random(a.seed)
    counter = tokens.default()
    messages, planted, total = session(rng, a.tokens, counter)
    tmp = Path(tempfile.mkdtemp(prefix="bench_recall_"))
    store = Store.open(tmp / "archive.db")
    try:
        results = []
        source = FtsExcerpts(store, counter)
        t_accept = time.perf_counter()
        history = messages
        for q in range(a.queries):
            ident = planted[rng.randrange(len(planted) - 4)]
            history = history + [{"role": "assistant", "content": "done"},
                                 {"role": "user", "content": f"why did {ident} happen again?"}]
            req = parse(json.dumps({"model": "m", "stream": True, "messages": history}).encode())
            fp = fingerprint_v1(ledger.ENDPOINT_CHAT, "bench", ledger.branch_id_for("bench"),
                                json.loads(req.raw))
            plan = await store.write(lambda c: ledger.accept(
                c, session_id="bench", association="path", req=req, fingerprint=fp,
                retry_hint=None))
            if q == 0:
                t_accept = time.perf_counter() - t_accept
            gen = ledger.Generation(plan)
            await store.write(lambda c: ledger.commit_batch(
                c, gen, [("text", "text", "done", {})], 0))
            await store.write(lambda c: ledger.finish_attempt(
                c, gen, "turn_complete", finish_reason="stop"))
            manifest = [(i.occ_id, "stub" if i.message.get("role") == "tool" else "verbatim")
                        for i in plan.items[:-12]] + [(i.occ_id, "verbatim") for i in plan.items[-12:]]
            t = time.perf_counter()
            selection = await source.select(plan, BaseView(manifest), 1920)
            dt = (time.perf_counter() - t) * 1000
            hit = any(ident in it.text for it in selection.items)
            results.append({"ms": dt, "hit": hit, "items": len(selection.items),
                            "reason": selection.reason})
            history = [m for m in history]  # next instruction extends this one
        lat = sorted(r["ms"] for r in results[1:])  # first query warms caches
        q = lambda p: lat[min(len(lat) - 1, int(p * len(lat)))]
        return {"archived_tokens": total, "tool_outputs": len(planted), "queries": a.queries,
                "first_accept_s": round(t_accept, 1),
                "select_ms": {"p50": round(statistics.median(lat), 1), "p95": round(q(0.95), 1),
                              "max": round(lat[-1], 1)},
                "hit_rate": round(sum(r["hit"] for r in results) / len(results), 3),
                "items_median": statistics.median(r["items"] for r in results),
                "reasons": sorted({str(r["reason"]) for r in results})}
    finally:
        store.close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--tokens", type=int, default=1_000_000)
    p.add_argument("--queries", type=int, default=60)
    p.add_argument("--seed", type=int, default=5)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    report = asyncio.run(main_async(a))
    print(json.dumps(report, indent=None if a.json else 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
