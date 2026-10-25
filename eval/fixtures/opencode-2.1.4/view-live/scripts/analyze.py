"""Read-only analysis of the forced-budget live run (results R14).

Usage: python analyze.py ROOT [--json OUT]

ROOT holds archive.db, tap/ (both proxies' taps) and captures/ (the passthrough's
capture of every upstream exchange). Reports per-request statuses, the upstream body's
exact count under the Strata 0.1.48 counter against the input budget, view_versions rows
and causes, and every upstream_call event (lcp, cached, prompt_ms, estimate, reuse class,
cause). The DB is opened read-only.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from palimnesis.upstreams.strata import tokens


def taps(root: Path, label: str):
    log = root / "tap" / "tap.jsonl"
    recs = [json.loads(line) for line in log.read_text("utf-8").splitlines()]
    return [r for r in recs if r.get("label") == label and "event" not in r]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    p.add_argument("--json", type=Path)
    a = p.parse_args()
    root = a.root
    counter = tokens.default()
    out = {}
    arch = [r for r in taps(root, "arch") if r["path"].endswith("/chat/completions")]
    up = [r for r in taps(root, "up") if r["path"].endswith("/chat/completions")]
    out["client_requests"] = [{"name": r["name"], "status": r.get("status"),
                               "ttfb_ms": round((r["t_first_data"] - r["t_arrival"]) * 1000, 1)
                               if "t_first_data" in r else None,
                               "total_s": round(r["t_end"] - r["t_arrival"], 2)} for r in arch]
    bodies = []
    for r in up:
        body = json.loads((root / "tap" / r["name"] / "request.body").read_bytes())
        tools, kw = counter.render_args(body)
        n = counter.count_messages(body["messages"], tools, **kw)
        bodies.append({"name": r["name"], "status": r.get("status"), "messages": len(body["messages"]),
                       "count": n, "max_completion_tokens": body.get("max_completion_tokens")})
    out["upstream_bodies"] = bodies
    c = sqlite3.connect(f"file:{root / 'archive.db'}?mode=ro", uri=True)
    try:
        out["view_versions"] = [dict(zip([d[0] for d in cur.description], row)) for cur in
                                [c.execute("SELECT * FROM view_versions ORDER BY n")]
                                for row in cur.fetchall()]
        calls = [json.loads(p) for (p,) in c.execute(
            "SELECT payload FROM events WHERE kind = 'upstream_call' ORDER BY event_id")]
        out["upstream_calls"] = [{k: x.get(k) for k in (
            "call_id", "outcome", "view_n", "input_tokens", "prompt_tokens", "cached_tokens",
            "prompt_ms", "lcp_tokens", "expected_reuse_est", "reuse_class", "cause",
            "lcp_source", "included_excerpts")} | {"first_diff_kind": (x.get("first_diff") or {}).get("kind")}
            for x in calls]
        out["event_kinds"] = dict(c.execute("SELECT kind, count(*) FROM events GROUP BY kind"))
        out["drift"] = [json.loads(p) for (p,) in c.execute(
            "SELECT payload FROM events WHERE kind = 'count_drift'")]
        out["excerpt_blocks"] = c.execute(
            "SELECT status, count(*) FROM excerpt_blocks GROUP BY status").fetchall()
    finally:
        c.close()
    text = json.dumps(out, indent=1, default=str)
    if a.json:
        a.json.write_text(text, "utf-8")
    print(text)


if __name__ == "__main__":
    sys.exit(main())
