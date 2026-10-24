"""Summarize opencode_fault_probe.py fixtures: per run, attempt arrival times, gaps,
request-body differences between attempts, header differences (ignoring traceparent,
b3 and content-length) and what `opencode run` printed.

Usage: uv run python eval/probes/opencode_fault_summary.py [RUN ...] [-v]
"""

import json
import sys
from pathlib import Path

FAULTS = (
    Path(__file__).resolve().parents[2]
    / "eval"
    / "fixtures"
    / "opencode-2.1.4"
    / "faults"
)
VOLATILE = {"traceparent", "b3", "content-length"}


def msg_summary(m):
    c = m.get("content")
    if isinstance(c, list):
        c = " | ".join(p.get("text", p.get("type", "?")) for p in c)
    s = f"{m['role']}: {str(c)[:160]!r}"
    for k in m:
        if k not in ("role", "content"):
            s += f" [{k}={str(m[k])[:120]!r}]"
    return s


def analyze(run: Path, verbose: bool):
    meta = (
        json.loads((run / "meta.json").read_text())
        if (run / "meta.json").exists()
        else {}
    )
    recs = [json.loads(l) for l in (run / "server.jsonl").open(encoding="utf-8")]
    reqs = [r for r in recs if r["event"] == "request" and r.get("attempt")]
    print(
        f"=== {run.name}  exit={meta.get('exit_code')} elapsed={meta.get('elapsed_s')} killed={meta.get('killed_after_s')} attempts={len(reqs)}"
    )
    t0 = reqs[0]["t"] if reqs else 0
    prev = None
    for r in reqs:
        gap = "" if prev is None else f" gap={r['t'] - prev['t']:.2f}s"
        ends = [
            e
            for e in recs
            if e.get("attempt") == r["attempt"]
            and e["event"] in ("stream_end", "client_gone", "hang_start", "response")
        ]
        print(
            f"  #{r['attempt']} t=+{r['t'] - t0:.2f}{gap} conn={r['conn']} end={[e['event'] + ':' + str(e.get('end', e.get('status', e.get('during', '')))) + '@+' + format(e['t'] - t0, '.2f') for e in ends]}"
        )
        body = r["body"]
        msgs = body["messages"]
        if prev is not None:
            pm = prev["body"]["messages"]
            common = 0
            while common < min(len(pm), len(msgs)) and pm[common] == msgs[common]:
                common += 1
            if common == len(pm) == len(msgs):
                print("     body messages identical to previous")
            else:
                print(
                    f"     messages: prev={len(pm)} now={len(msgs)} common_prefix={common}"
                )
                for m in msgs[common:]:
                    print("       +", msg_summary(m))
                for m in pm[common:]:
                    print("       -", msg_summary(m))
            ob = {k: v for k, v in prev["body"].items() if k != "messages"}
            nb = {k: v for k, v in body.items() if k != "messages"}
            if ob != nb:
                print(
                    "     non-message body fields differ:",
                    {
                        k: (ob.get(k), nb.get(k))
                        for k in set(ob) | set(nb)
                        if ob.get(k) != nb.get(k) and k != "tools"
                    },
                    "tools_changed=",
                    ob.get("tools") != nb.get("tools"),
                )
            ph = {k.lower(): v for k, v in prev["headers"] if k.lower() not in VOLATILE}
            nh = {k.lower(): v for k, v in r["headers"] if k.lower() not in VOLATILE}
            if ph != nh:
                print(
                    "     headers differ:",
                    {
                        k: (ph.get(k), nh.get(k))
                        for k in set(ph) | set(nh)
                        if ph.get(k) != nh.get(k)
                    },
                )
        prev = r
    if verbose and reqs:
        print("  last request messages:")
        for m in reqs[-1]["body"]["messages"][1:]:
            print("     ", msg_summary(m))
    for f in ("opencode.stdout.txt", "opencode.stderr.txt"):
        p = run / f
        if p.exists():
            t = p.read_text(encoding="utf-8", errors="replace").strip()
            if t:
                print(f"  {f}: {t[-700:]!r}")


if __name__ == "__main__":
    names = [a for a in sys.argv[1:] if not a.startswith("-")]
    v = "-v" in sys.argv
    for run in sorted(FAULTS.iterdir()):
        if (
            run.is_dir()
            and (not names or run.name in names)
            and (run / "server.jsonl").exists()
        ):
            analyze(run, v)
