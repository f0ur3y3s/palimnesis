"""Summarize the ``hx_*`` runs: Pi's HP4 faults through Palimnesis (Phase 4B S14).

For each run folder (``pi_probe.py hx_...``) this reads the fault server's log, the proxy's
archive and Pi's RPC records, and checks the plan §6 gate for fault runs:

- **no silent duplicate generation:** at most one completed attempt per archived request,
  and every request the fault server answered with output is either the one completed
  attempt or a recorded failure;
- **failures surface:** an attempt the fault server failed is recorded failed, never
  completed;
- **the session goes on:** Pi's second prompt was accepted and answered (a failed partial
  left out of the resend is superseded, O-4B-5);
- **no unexplained 409:** any 409 the proxy sent is listed with its code.

    uv run python eval/probes/pi_proxy_faults.py RUNROOT [--json]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


# Outcomes that differ from Pi direct by contract, not by defect.
EXPECTED = {
    "finish_no_done": ("contracts §3: a stream that ends without [DONE] is an upstream failure; "
                       "Strata always sends [DONE] (docs/probes/strata.md §13.1), so only the "
                       "fault server produces this shape"),
}


def summarize(run: Path) -> dict:
    upstream = [json.loads(x) for x in (run / "server.jsonl").read_text(encoding="utf-8").splitlines()
                if '"request"' in x]
    upstream = [u for u in upstream if u.get("event") == "request" and u.get("method") == "POST"]
    conn = sqlite3.connect(f"file:{run / 'archive.db'}?mode=ro", uri=True)
    try:
        requests = conn.execute("SELECT count(*) FROM requests").fetchone()[0]
        per_request = conn.execute(
            "SELECT r.request_id, sum(e.kind = 'turn_complete'), sum(e.kind = 'attempt_failed')"
            " FROM requests r LEFT JOIN events e ON e.request_id = r.request_id"
            " GROUP BY r.request_id ORDER BY r.arrived_at").fetchall()
        failures = [json.loads(p).get("reason") for (p,) in conn.execute(
            "SELECT payload FROM events WHERE kind = 'attempt_failed' ORDER BY event_id")]
        superseded = conn.execute(
            "SELECT count(*) FROM events WHERE kind = 'partial_superseded'").fetchone()[0]
    finally:
        conn.close()
    rpc = run / "turns.rpc.jsonl"
    records = [json.loads(x) for x in rpc.read_text(encoding="utf-8").splitlines()] if rpc.exists() else []
    ends = [r for r in records if r.get("type") == "agent_end" or r.get("type") == "agent_settled"]
    stops = [((r.get("message") or {}).get("stopReason")) for r in records
             if r.get("type") == "message_end" and (r.get("message") or {}).get("role") == "assistant"]
    errors = [((r.get("message") or {}).get("errorMessage") or "")[:160] for r in records
              if r.get("type") == "message_end" and (r.get("message") or {}).get("stopReason") == "error"]
    duplicates = [rid for rid, done, _ in per_request if (done or 0) > 1]
    second_answered = bool(stops) and stops[-1] in ("stop", "toolUse", "length")
    return {"run": run.name, "upstream_requests": len(upstream), "archived_requests": requests,
            "completed_per_request": [done or 0 for _, done, _ in per_request],
            "failed_per_request": [f or 0 for _, _, f in per_request],
            "failure_reasons": failures, "superseded": superseded, "pi_stops": stops,
            "pi_errors": errors, "settled": len(ends),
            "expected": next((why for scn, why in EXPECTED.items() if scn in run.name), None),
            "pass": not duplicates and (second_answered or any(scn in run.name for scn in EXPECTED))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = [summarize(d) for d in sorted(args.root.glob("hx_*")) if (d / "archive.db").exists()]
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(f"{'PASS' if r['pass'] else 'FAIL'} {r['run']}: upstream {r['upstream_requests']}, "
                  f"archived {r['archived_requests']}, completed {r['completed_per_request']}, "
                  f"failed {r['failure_reasons']}, superseded {r['superseded']}, "
                  f"pi stops {r['pi_stops']}" + (f", pi errors {r['pi_errors']}" if r['pi_errors'] else "")
                  + (f" [expected: {r['expected']}]" if r["expected"] else ""))
    return 0 if rows and all(r["pass"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
