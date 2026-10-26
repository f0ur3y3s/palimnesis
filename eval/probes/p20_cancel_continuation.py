"""Probe 20 (Phase 3B, S0 P4): cancel during a continuation call, and slot release time.

Per repetition: call 1 (p19's request with the task "do exactly what the
file asks", thinking on, effort low) runs to completion with a
read_file tool call. Call 2 is the continuation (call 1's messages + the assistant tool call as
generated + a tool result that asks for a long answer), streaming with max_tokens 3000. One
second after call 2's first reasoning or content delta, the client disconnects. Measured as in
p09: release_s = time from close until /status no longer shows call 2 (polled every 25 ms), the
server's request record (finish, reused, output_tokens), and the TTFB of a tiny follow-up request.

Strictly sequential, idle-gated, synthetic bodies. Writes fixtures/p20_cancel_<rep>_call2.sse and
fixtures/p20_cancel_continuation.json. Compare with docs/probes/strata.md §9 (decode, stream:
0.047-0.079 s).

    uv run python eval/probes/p20_cancel_continuation.py [--reps 3] [--after-ms 1000]
"""

from __future__ import annotations

import argparse
import json
import random
import time

from p09_cancel import tiny_ttfb
from p19_continuation_cache import assistant_message, call1
from strata_common import (BASE, check_build, recent_requests, save_bytes, save_json, status,
                           stream_post, wait_idle)

LONG_ASK = ("Writing brief stored in this file: write an original story of at least 1,500 words "
            "about a lighthouse keeper. Start writing immediately.")
TASK = "then do exactly what the file asks."
CAP = 3000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--after-ms", type=int, default=1000)
    args = ap.parse_args()
    props = check_build()
    out = {"upstream": BASE, "build_info": props["build_info"], "after_ms": args.after_ms,
           "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "trials": []}
    slot_s = 0.0
    rng = random.Random()
    for rep in range(args.reps):
        for _ in range(3):
            nonce = f"p20-{rng.randrange(16**6):06x}"
            b1, r1, s1 = call1(nonce, "low", task=TASK)
            slot_s += r1["elapsed_s"]
            if s1["calls"] and s1["finish_reason"] == "tool_calls":
                break
        asst = assistant_message(s1)
        msgs2 = b1["messages"] + [asst] + [
            {"role": "tool", "tool_call_id": c["id"], "content": LONG_ASK} for c in asst["tool_calls"]]
        b2 = {**b1, "messages": msgs2, "max_tokens": CAP}
        wait_idle(quiet=1.0)
        first = {}

        def abort(events, t):
            if "t" not in first:
                for e in events:
                    if e["kind"] == "data" and ('"reasoning_content"' in e["text"] or (
                            '"content"' in e["text"] and '"role"' not in e["text"])):
                        first["t"] = e["t"] if e["t"] is not None else t
                        break
            return "t" in first and t - first["t"] >= args.after_ms / 1000

        st_before = None
        r2 = stream_post(b2, abort=abort)
        t_close = r2["t_closed_mono"]
        try:
            st_before = status()
        except Exception:  # noqa: BLE001
            pass
        # Release: call 2 no longer shown active (it is the only request with max_tokens 3000).
        t_rel = None
        polls = 0
        while time.monotonic() - t_close < 120:
            s = status()
            polls += 1
            if not (s.get("busy") and s.get("max_tokens") == CAP):
                t_rel = time.monotonic()
                break
            time.sleep(0.025)
        release_s = None if t_rel is None else round(t_rel - t_close, 3)
        ttfb, total, timings = tiny_ttfb()
        slot_s += r2["elapsed_s"] + (release_s or 0) + total
        time.sleep(0.5)
        recs = [{k: r.get(k) for k in ("id", "finish", "prompt_tokens", "reused", "prompt_read",
                                       "output_tokens", "engine_generated", "duration_s",
                                       "first_engine_token_s")} for r in recent_requests(3)]
        save_bytes(f"p20_cancel_{rep}_call2.sse", r2["raw"])
        n_deltas = sum(1 for e in r2["events"] if e["kind"] == "data") - 1
        trial = {"rep": rep, "call1_usage": s1["usage"], "aborted": r2["aborted"],
                 "first_delta_t": first.get("t"), "stream_elapsed_s": r2["elapsed_s"],
                 "deltas_received": n_deltas, "status_right_after_close": st_before and {
                     k: st_before.get(k) for k in ("busy", "phase", "generated", "max_tokens", "queued")},
                 "release_s": release_s, "release_polls": polls,
                 "tiny_ttfb_after_release_s": round(ttfb, 3), "tiny_timings": timings,
                 "server_records": recs}
        out["trials"].append(trial)
        print(rep, json.dumps({k: trial[k] for k in ("aborted", "first_delta_t", "deltas_received",
                                                     "status_right_after_close", "release_s",
                                                     "tiny_ttfb_after_release_s")}),
              json.dumps(recs[1] if len(recs) > 1 else recs))
    out["slot_seconds"] = round(slot_s, 1)
    out["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_json("p20_cancel_continuation.json", out)
    print("slot seconds", out["slot_seconds"])


if __name__ == "__main__":
    main()
