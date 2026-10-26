"""Probe 18 (Phase 3B, S0 P2): does Strata wrap up thinking under a small output limit?

docs/probes/strata.md §11 marks "max_tokens >= 1024 with thinking on: thinking is wrapped up
with 25% of the cap left" as [docs]. This probe sends a thinking-heavy synthetic prompt with
thinking on (the default effort, which is xhigh) at max_tokens 512, 1024, 2048 and 4096, and
records per run: reasoning and content tokens (delta counts and local token counts),
completion_tokens, finish_reason, the reasoning tail, and /status (phase, generated,
thinking_budget, reasoning_recoveries) polled every 0.25 s while the request runs.

Strictly sequential, idle-gated. Writes fixtures/p18_<cap>_<rep>.sse and
fixtures/p18_small_limit_thinking.json.

    uv run python eval/probes/p18_small_limit_thinking.py [--reps 3] [--caps 512,1024,2048,4096]
    uv run python eval/probes/p18_small_limit_thinking.py --budget-only --caps 600,1500,3000,8192

``--budget-only`` reads only /status ``thinking_budget`` for each cap: it disconnects after
the first few reasoning deltas (a decode-time cancel) and merges the budgets into the JSON.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from strata_common import (BASE, MODEL, check_build, oa_shape, save_bytes, save_json, status,
                           stream_post, wait_idle)

PROMPT = ("How many 7-digit positive integers have digits that sum to 30 and are divisible by 11? "
          "Work it out carefully, then give the final number in one short sentence.")


def poll_status(stop: threading.Event, out: list) -> None:
    t0 = time.monotonic()
    while not stop.is_set():
        try:
            s = status()
            out.append({"t": round(time.monotonic() - t0, 2), **{k: s.get(k) for k in (
                "busy", "phase", "generated", "max_tokens", "thinking_budget", "reasoning_recoveries")}})
        except Exception as e:  # noqa: BLE001 - a missed poll is only a gap in the trace
            out.append({"t": round(time.monotonic() - t0, 2), "error": str(e)[:80]})
        stop.wait(0.25)


def transitions(trace: list[dict]) -> list[dict]:
    """Collapse the /status trace to the points where phase changed."""
    out, last = [], object()
    for s in trace:
        key = (s.get("phase"), s.get("busy"))
        if key != last:
            out.append(s)
            last = key
    return out


def budget_only(caps: list[int]) -> None:
    import json

    from strata_common import FIXTURES
    rows, slot_s = [], 0.0
    for cap in caps:
        body = {"model": MODEL, "stream": True, "max_tokens": cap,
                "messages": [{"role": "user", "content": f"[budget {cap}] {PROMPT}"}]}
        wait_idle(quiet=1.0)
        trace: list[dict] = []
        stop = threading.Event()
        th = threading.Thread(target=poll_status, args=(stop, trace), daemon=True)
        th.start()
        run = stream_post(body, abort=lambda evs, t: sum(
            1 for e in evs if e["kind"] == "data" and "reasoning_content" in e["text"]) >= 20)
        waited = wait_idle(poll=0.05)
        stop.set()
        th.join()
        slot_s += run["elapsed_s"] + waited
        budgets = sorted({s.get("thinking_budget") for s in trace if s.get("busy")
                          and s.get("max_tokens") == cap} - {None})
        rows.append({"cap": cap, "thinking_budget": budgets, "aborted": run["aborted"],
                     "release_s": round(waited, 3)})
        print(rows[-1])
    path = FIXTURES / "p18_small_limit_thinking.json"
    out = json.loads(path.read_text(encoding="utf-8"))
    out["budget_only"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rows": rows,
                          "slot_seconds": round(slot_s, 1)}
    save_json(path.name, out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--caps", default="512,1024,2048,4096")
    ap.add_argument("--budget-only", action="store_true")
    args = ap.parse_args()
    props = check_build()
    if args.budget_only:
        budget_only([int(c) for c in args.caps.split(",")])
        return
    from palimnesis.upstreams.strata import tokens
    tok = tokens.default()
    out = {"upstream": BASE, "build_info": props["build_info"], "prompt": PROMPT,
           "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "runs": []}
    slot_s = 0.0
    for cap in [int(c) for c in args.caps.split(",")]:
        for rep in range(args.reps):
            body = {"model": MODEL, "stream": True, "max_tokens": cap,
                    "messages": [{"role": "user", "content": f"[run {cap}-{rep}] {PROMPT}"}]}
            wait_idle(quiet=1.0)
            trace: list[dict] = []
            stop = threading.Event()
            th = threading.Thread(target=poll_status, args=(stop, trace), daemon=True)
            th.start()
            run = stream_post(body)
            stop.set()
            th.join()
            slot_s += run["elapsed_s"]
            save_bytes(f"p18_{cap}_{rep}.sse", run["raw"])
            shape = oa_shape(run["events"])
            order = dict()
            for k, n in shape["order"]:
                order[k] = order.get(k, 0) + n
            r_tok = tok.count(shape["reasoning"]) if shape["reasoning"] else 0
            c_tok = tok.count(shape["content"]) if shape["content"] else 0
            completion = (shape["usage"] or {}).get("completion_tokens")
            trans = transitions(trace)
            answer_at = next((s.get("generated") for s in trace
                              if s.get("phase") not in (None, "thinking", "prefill", "queued")
                              and s.get("busy")), None)
            rec = {"cap": cap, "rep": rep, "finish_reason": shape["finish_reason"],
                   "completion_tokens": completion,
                   "reasoning_deltas": order.get("reasoning", 0), "content_deltas": order.get("content", 0),
                   "reasoning_tokens_local": r_tok, "content_tokens_local": c_tok,
                   "reasoning_share_of_cap": round(order.get("reasoning", 0) / cap, 3),
                   "left_after_reasoning": cap - order.get("reasoning", 0),
                   "reasoning_tail": shape["reasoning"][-400:], "content": shape["content"][-400:],
                   "order": shape["order"], "status_transitions": trans,
                   "generated_at_first_non_thinking_phase": answer_at,
                   "thinking_budget_seen": sorted({str(s.get("thinking_budget")) for s in trace}),
                   "reasoning_recoveries_seen": sorted({str(s.get("reasoning_recoveries")) for s in trace}),
                   "comments": sum(1 for e in run["events"] if e["kind"] == "comment"),
                   "usage": shape["usage"], "elapsed_s": run["elapsed_s"]}
            out["runs"].append(rec)
            print(cap, rep, {k: rec[k] for k in ("finish_reason", "completion_tokens", "reasoning_deltas",
                                                 "content_deltas", "left_after_reasoning",
                                                 "thinking_budget_seen")})
            if status().get("busy"):
                print("  warning: still busy after stream end")
    out["slot_seconds"] = round(slot_s, 1)
    out["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_json("p18_small_limit_thinking.json", out)
    print("slot seconds", out["slot_seconds"])


if __name__ == "__main__":
    main()
