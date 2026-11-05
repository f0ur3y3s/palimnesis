"""Summarize cc_probe.py runs: one line per request, plus body facts and attempt gaps.

Usage:
    uv run python eval/probes/cc_probe_summary.py RUN_DIR [RUN_DIR ...] [--bodies] [--diff]

Per request: arrival time, method, path?query, kind, stream flag, model, tool count,
body bytes, max_tokens, thinking, message roles, betas header. ``--bodies`` adds system
block lengths/prefixes, cache_control positions, metadata keys, other top-level fields.
``--diff`` prints, for each main request, how its messages differ from the previous main
request (common prefix length, removed, added).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def cc_positions(body: dict) -> list[str]:
    out = []
    sys_ = body.get("system")
    if isinstance(sys_, list):
        for i, b in enumerate(sys_):
            if isinstance(b, dict) and b.get("cache_control"):
                out.append(f"system[{i}]:{json.dumps(b['cache_control'])}")
    for i, t in enumerate(body.get("tools") or []):
        if isinstance(t, dict) and t.get("cache_control"):
            out.append(f"tools[{i}]")
    for i, m in enumerate(body.get("messages") or []):
        c = m.get("content")
        if isinstance(c, list):
            for j, b in enumerate(c):
                if isinstance(b, dict) and b.get("cache_control"):
                    out.append(f"messages[{i}].content[{j}]")
    return out


def norm_msg(m: dict) -> str:
    """Message without cache_control, for prefix comparisons."""
    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k != "cache_control"}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x
    return json.dumps(strip(m), sort_keys=True, ensure_ascii=False)


def summarize(run: Path, bodies: bool, diff: bool) -> None:
    print(f"== {run.name}")
    meta = run / "meta.json"
    if meta.exists():
        m = json.loads(meta.read_text(encoding="utf-8"))
        print("   invocations:", [(i["exit"], i["killed"], i["seconds"]) for i in m.get("invocations", [])],
              "sentinel_hits:", len(m.get("sentinel_hits", [])))
    prev_main = None
    last_t = None
    for line in (run / "server.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        ev = r["event"]
        if ev != "request":
            if ev in ("client_gone", "stream_end", "hang_start", "header_delay") or (ev == "response" and r.get("status") != 200):
                print(f"   {r['t']:8.2f}   .. {ev} seq={r.get('seq')} {r.get('during', '') or r.get('end', '') or r.get('status', '')} {r.get('since_headers', '')} {r.get('rejected', '')}")
            continue
        b = r["body"] if isinstance(r["body"], dict) else {}
        h = {k.lower(): v for k, v in r["headers"]}
        gap = "" if last_t is None else f"+{r['t'] - last_t:.2f}"
        last_t = r["t"]
        roles = "".join((m.get("role") or "?")[0] for m in b.get("messages", []))
        th = b.get("thinking")
        print(f"   {r['t']:8.2f} {gap:>7} #{r['seq']} {r['method']} {r['path']}{'?' + r['query'] if r['query'] else ''} "
              f"[{r['kind']}{' main' if r['main'] else ''}{' stream' if r['stream'] else ' nonstream' if r['kind'] == 'messages' else ''}] "
              f"model={b.get('model')} tools={len(b.get('tools') or [])} bytes={r['body_bytes']} max_tokens={b.get('max_tokens')} "
              f"thinking={json.dumps(th) if th else None} roles={roles}")
        if bodies and b:
            print(f"        beta={h.get('anthropic-beta')}")
            print(f"        keys={sorted(b.keys())}")
            sys_ = b.get("system")
            if isinstance(sys_, list):
                for i, s in enumerate(sys_):
                    t = s.get("text", "")
                    print(f"        system[{i}] len={len(t)} cc={s.get('cache_control')} {t[:110]!r}")
            elif isinstance(sys_, str):
                print(f"        system(str) len={len(sys_)} {sys_[:110]!r}")
            print(f"        cache_control={cc_positions(b)}")
            for k in sorted(b):
                if k not in ("messages", "system", "tools", "model", "max_tokens", "stream", "thinking"):
                    print(f"        {k}={json.dumps(b[k])[:300]}")
        if diff and r["main"] and b:
            cur = [norm_msg(m) for m in b.get("messages", [])]
            if prev_main is not None:
                n = 0
                while n < min(len(cur), len(prev_main)) and cur[n] == prev_main[n]:
                    n += 1
                print(f"        diff vs previous main: common={n} prev={len(prev_main)} cur={len(cur)}")
                for m in b["messages"][n:]:
                    print(f"          + {norm_msg(m)[:260]}")
                for m in prev_main[n:]:
                    print(f"          - {m[:260]}")
            prev_main = cur


def matrix_row(run: Path) -> str:
    """One line: main attempts (stream/nonstream), gaps, body changes, outcome."""
    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    reqs, gone = [], []
    for line in (run / "server.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["event"] == "request" and r["kind"] == "messages":
            reqs.append(r)
        elif r["event"] == "client_gone":
            gone.append(f"gone@{r.get('since_headers')}s/{r.get('during', 'stream')}")
    kinds = "".join("S" if r["stream"] else "N" for r in reqs)
    gaps = [round(b["t"] - a["t"], 2) for a, b in zip(reqs, reqs[1:])]
    same = []
    for a, b in zip(reqs, reqs[1:]):
        ma = [norm_msg(m) for m in a["body"].get("messages", [])]
        mb = [norm_msg(m) for m in b["body"].get("messages", [])]
        same.append("=" if ma == mb else f"~{len(mb) - len(ma):+d}")
    outcome = ""
    for f in sorted(run.glob("claude.*.stdout.jsonl")):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("type") == "result":
                outcome = f"{o.get('subtype')} is_error={o.get('is_error')} {str(o.get('result'))[:90]!r}"
    inv = meta["invocations"][-1]
    return (f"{run.name:42} n={len(reqs)} kinds={kinds} gaps={gaps} bodies={''.join(same)} {' '.join(gone)} "
            f"exit={inv['exit']} t={inv['seconds']} | {outcome}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--bodies", action="store_true")
    ap.add_argument("--diff", action="store_true")
    ap.add_argument("--matrix", action="store_true", help="one line per run")
    a = ap.parse_args()
    for r in a.runs:
        if a.matrix:
            print(matrix_row(Path(r)))
        else:
            summarize(Path(r), a.bodies, a.diff)


if __name__ == "__main__":
    main()
