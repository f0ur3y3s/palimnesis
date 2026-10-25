"""Summarize Phase 3 needle runs from ``eval/needle.py`` (EMULATOR results).

    python eval/report.py RUNDIR [--configs a4-base,a3-base] [--fixtures eval/fixtures/phase3-dev]

Per configuration: exact match with a 95% Wilson interval, partials, by-category counts,
where the needle was on the question's first upstream call (verbatim in the view, in the
excerpt block, or absent), appropriate fallback use (a transcript lookup when the needle was
absent), unnecessary lookups (lookups when it was present), round trips, tokens, time to
first visible content, total latency, cache reuse by cause from ``replay.py --explain``,
``transcripts verify`` and foreign traffic seen by the slot gate. With ``--fixtures`` it
writes sanitized per-question summaries (no bodies; run paths replaced by ``<RUN>``).
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ORDER = ["a4-base", "a3-base", "a2-base", "a4-q2", "a4-x2", "a4-a4"]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def load(run: Path, config: str):
    d = run / config
    rows = [json.loads(l) for l in (d / "questions.jsonl").read_text(encoding="utf-8").splitlines() if l]
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8")) if (d / "meta.json").exists() else {}
    explain = {}
    if (d / "explain.json").exists() and (d / "explain.json").read_text(encoding="utf-8").strip():
        explain = json.loads((d / "explain.json").read_text(encoding="utf-8"))
    logs = "".join(f.read_text(encoding="utf-8", errors="replace") for f in sorted(d.glob("proxy-*.log")))
    meta["_log_view_disabled"] = logs.count("bounded views disabled")
    meta["_log_unbounded"] = logs.count("forwarding unbounded")
    return rows, meta, explain


BUDGET = 24_320


def mark_clean(rows) -> None:
    """``clean``: no error in this or any earlier step of the session, and every upstream call
    of the question within the input budget (a larger body means bounded views were off)."""
    bad = set()
    for r in rows:
        if r["errors"]:
            bad.add(r["session"])
        over = any((c.get("prompt_tokens") or 0) > BUDGET for c in r["calls"])
        r["clean"] = r["session"] not in bad and not over and not r["errors"]


def summarize(rows, meta, explain) -> dict:
    mark_clean(rows)
    q = [r for r in rows if r["kind"] == "question"]
    clean = [r for r in q if r["clean"]]
    n = len(q)
    errored = [r for r in q if r["errors"]]
    valid = [r for r in q if not r["errors"]]
    ex = sum(r["exact"] for r in q)
    exl = sum(r["exact_loose"] for r in q)
    part = sum(r["partial"] for r in q)
    absent = [r for r in q if r.get("fact_absent")]
    present = [r for r in q if r.get("fact_absent") is False]
    cats = defaultdict(lambda: [0, 0])
    for r in q:
        cats[r["category"]][0] += r["exact_loose"]
        cats[r["category"]][1] += 1
    allsteps = rows
    pairs = explain.get("pairs", [])
    by_cause = defaultdict(lambda: {"pairs": 0, "cached": 0, "est": 0, "lcp": 0})
    unexplained = 0
    for p in pairs:
        c = by_cause[p.get("cause")]
        c["pairs"] += 1
        c["cached"] += p.get("cached_tokens") or 0
        c["est"] += p.get("expected_reuse_est") or 0
        c["lcp"] += p.get("lcp_tokens") or 0
        unexplained += p.get("cause") in (None, "unexplained")
    calls = [c for r in allsteps for c in r["calls"]]
    return {
        "n": n, "exact": ex, "exact_loose": exl, "wilson_loose": wilson(exl, n), "wilson": wilson(ex, n),
        "n_clean": len(clean), "exact_clean": sum(r["exact_loose"] for r in clean),
        "wilson_clean": wilson(sum(r["exact_loose"] for r in clean), len(clean)),
        "lookups_clean": sum(r["lookups"] for r in clean),
        "absent_clean": sum(1 for r in clean if r.get("fact_absent")),
        "fallback_clean": sum(1 for r in clean if r.get("appropriate_fallback")),
        "excerpt_clean": sum(1 for r in clean if r.get("in_excerpt")),
        "errored": len(errored), "n_valid": len(valid),
        # Upstream early stops: a final answer that is empty or a strict prefix of the gold
        # value (the raw upstream stream shows the same text, so the relay is not the cause).
        "early_stop": sum(1 for r in valid if r["answered"] and not r["exact_loose"] and (
            not r["answer"].strip() or r["gold"].casefold().startswith(r["answer"].strip().strip("`").casefold()))),
        "exact_loose_valid": sum(r["exact_loose"] for r in valid),
        "wilson_loose_valid": wilson(sum(r["exact_loose"] for r in valid), len(valid)),
        "view_disabled_events": meta.get("_log_view_disabled"),
        "unbounded_forward_events": meta.get("_log_unbounded"),
        "stopped_histories": meta.get("stopped_histories") or [],
        "partial": part, "contains": sum(r["contains"] for r in q),
        "unanswered": sum(not r["answered"] for r in q),
        "in_view": sum(bool(r.get("in_view")) for r in q),
        "in_excerpt": sum(bool(r.get("in_excerpt")) for r in q),
        "absent": len(absent),
        "exact_when_absent": sum(r["exact_loose"] for r in absent),
        "exact_when_excerpt": sum(r["exact_loose"] for r in q if r.get("in_excerpt")),
        "n_excerpt": sum(bool(r.get("in_excerpt")) for r in q),
        "fallback_used": sum(r.get("appropriate_fallback", False) for r in absent),
        "unnecessary_lookups": sum(r.get("unnecessary_lookups", 0) for r in present),
        "questions_with_unnecessary": sum(1 for r in present if r.get("unnecessary_lookups")),
        "n_present": len(present),
        "lookups": sum(r["lookups"] for r in q),
        "questions_with_lookup": sum(1 for r in q if r["lookups"]),
        "tool_calls": sum(len(r["tool_calls"]) for r in q),
        "rounds": sum(r["rounds"] for r in q),
        "max_rounds": max((r["rounds"] for r in q), default=0),
        "prompt_tokens": sum(r["prompt_tokens"] for r in allsteps),
        "completion_tokens": sum(r["completion_tokens"] for r in allsteps),
        "cached_tokens": sum(r["cached_tokens"] for r in allsteps),
        "q_prompt_tokens": sum(r["prompt_tokens"] for r in q),
        "q_completion_tokens": sum(r["completion_tokens"] for r in q),
        "ttfvc_p50": pct([r.get("ttfvc_s") for r in q], 0.5),
        "ttfvc_p90": pct([r.get("ttfvc_s") for r in q], 0.9),
        "latency_p50": pct([r["total_s"] for r in q], 0.5),
        "latency_p90": pct([r["total_s"] for r in q], 0.9),
        "wall_s": (meta.get("finished", 0) - meta.get("started", 0)) if meta else None,
        "by_category": {k: tuple(v) for k, v in sorted(cats.items())},
        "explain_exit": meta.get("explain_exit"), "explain_summary": explain.get("summary"),
        "unexplained": unexplained, "by_cause": dict(by_cause),
        "verify": {k: v["exit"] for k, v in (meta.get("verify") or {}).items()},
        "foreign_between": sum(c.get("foreign_between") or 0 for c in calls),
        "foreign_during": sum(max(0, c.get("foreign_during") or 0) for c in calls),
        "foreign_overlap_samples": sum(c.get("foreign_overlap_samples") or 0 for c in calls),
        "gate_waits": sum(1 for c in calls if (c.get("driver_wait_s") or 0) > 0.5 or (c.get("tap_wait_s") or 0) > 0.5),
        "gate_events": len(meta.get("gate_events") or []),
        "upstream_calls": len(calls), "errors": sum(len(r["errors"]) for r in allsteps),
        "history_errors": len(meta.get("history_errors") or []),
        "proxy_starts": meta.get("proxy_starts"),
    }


def sanitize(r: dict, run: Path) -> dict:
    keep = ["history", "config", "arm", "step", "category", "restart_before", "gold", "answer",
            "exact", "exact_loose", "contains", "partial", "parts_found", "parts_total",
            "in_view", "in_excerpt", "evidence_in_context", "evidence_total", "excerpt_items",
            "addendum_present", "stub_count", "fact_absent", "appropriate_fallback",
            "unnecessary_lookups", "lookups", "workspace_tool_calls", "rounds", "prompt_tokens",
            "completion_tokens", "cached_tokens", "ttfvc_s", "total_s", "answered"]
    out = {k: r.get(k) for k in keep if k in r}
    out["errors"] = [{"status": e.get("status")} for e in r.get("errors", [])]
    tools = []
    for t in r.get("tool_calls", []):
        args = json.dumps(t.get("args", {}), ensure_ascii=False)
        for prefix in (str(run), str(run).replace("\\", "/"), str(run).replace("\\", "\\\\")):
            args = args.replace(prefix, "<RUN>")
        home = str(Path.home())
        for prefix in (home, home.replace("\\", "/"), home.replace("\\", "\\\\")):
            args = args.replace(prefix, "<HOME>")
        tools.append({"name": t["name"], "lookup": t["lookup"], "error": t.get("error"),
                      "result_chars": t.get("result_chars"), "args": json.loads(args)})
    out["tool_calls"] = tools
    out["calls"] = [{k: c.get(k) for k in ("prompt_tokens", "cached_tokens", "completion_tokens",
                                             "first_content_s", "total_s", "prompt_ms", "finish",
                                             "foreign_between", "foreign_during")}
                    for c in r.get("calls", [])]
    out["answer"] = (out.get("answer") or "")[:160]
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("run", type=Path)
    p.add_argument("--configs")
    p.add_argument("--fixtures", type=Path)
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    configs = a.configs.split(",") if a.configs else [c for c in ORDER if (a.run / c / "questions.jsonl").exists()]
    res, rows_by = {}, {}
    for c in configs:
        rows, meta, explain = load(a.run, c)
        res[c] = summarize(rows, meta, explain)
        rows_by[c] = {r["step"]: r for r in rows if r["kind"] == "question"}
        if a.fixtures:
            a.fixtures.mkdir(parents=True, exist_ok=True)
            with open(a.fixtures / f"{c}.jsonl", "w", encoding="utf-8", newline="\n") as f:
                for r in rows:
                    f.write(json.dumps(sanitize(r, a.run), ensure_ascii=False) + "\n")
    if a.json:
        print(json.dumps(res, indent=1))
        return
    print("| Config | n | Exact (ws/case) | 95% CI | Exact (loose) | 95% CI | Partial | In view / excerpt / absent | Exact when absent | Fallback used when absent | Unnecessary lookups (questions) | Lookups (questions) | Round trips (max) | Prompt / completion tok, all steps | TTFVC p50/p90 s | Latency p50/p90 s |")
    print("|" + "---|" * 16)
    for c, s in res.items():
        lo, hi = s["wilson"]
        lo2, hi2 = s["wilson_loose"]
        print(f"| {c} | {s['n']} | {s['exact']} ({s['exact'] / max(1, s['n']):.0%}) | {lo:.0%}–{hi:.0%} | "
              f"{s['exact_loose']} ({s['exact_loose'] / max(1, s['n']):.0%}) | {lo2:.0%}–{hi2:.0%} | {s['partial']} | "
              f"{s['in_view']} / {s['in_excerpt']} / {s['absent']} | {s['exact_when_absent']}/{s['absent']} | "
              f"{s['fallback_used']}/{s['absent']} | {s['unnecessary_lookups']} ({s['questions_with_unnecessary']}/{s['n_present']}) | "
              f"{s['lookups']} ({s['questions_with_lookup']}) | {s['rounds']} ({s['max_rounds']}) | "
              f"{s['prompt_tokens']:,} / {s['completion_tokens']:,} | {s['ttfvc_p50']}/{s['ttfvc_p90']} | "
              f"{s['latency_p50']}/{s['latency_p90']} |")
    print()
    cats = sorted({k for s in res.values() for k in s["by_category"]})
    print("| Category | " + " | ".join(res) + " |")
    print("|---|" + "---|" * len(res))
    for k in cats:
        print(f"| {k} | " + " | ".join(f"{s['by_category'].get(k, (0, 0))[0]}/{s['by_category'].get(k, (0, 0))[1]}" for s in res.values()) + " |")
    print()
    base = rows_by.get("a4-base")
    if base:
        print("Paired vs a4-base (loose exact): config: both / only base / only config / neither")
        for c, rb in rows_by.items():
            if c == "a4-base":
                continue
            k, kc = Counter(), Counter()
            for sid, r in rb.items():
                if sid in base:
                    k[(base[sid]["exact_loose"], r["exact_loose"])] += 1
                    if base[sid].get("clean") and r.get("clean"):
                        kc[(base[sid]["exact_loose"], r["exact_loose"])] += 1
            print(f"  {c}: {k[(True, True)]} / {k[(True, False)]} / {k[(False, True)]} / {k[(False, False)]}"
                  f"   (clean in both: {kc[(True, True)]} / {kc[(True, False)]} / {kc[(False, True)]} / {kc[(False, False)]})")
    print()
    for c, s in res.items():
        causes = ", ".join(f"{k}: {v['pairs']} pairs, cached {v['cached']:,} vs est {v['est']:,}"
                           for k, v in sorted(s["by_cause"].items(), key=lambda kv: str(kv[0])))
        print(f"{c}: explain exit {s['explain_exit']}, unexplained {s['unexplained']}; {causes}")
        lo3, hi3 = s["wilson_loose_valid"]
        lo4, hi4 = s["wilson_clean"]
        print(f"   CLEAN subset: {s['exact_clean']}/{s['n_clean']} loose exact ({lo4:.0%}–{hi4:.0%}); "
              f"needle in excerpt {s['excerpt_clean']}, absent {s['absent_clean']} (fallback used "
              f"{s['fallback_clean']}); lookups {s['lookups_clean']}")
        print(f"   upstream early stops (empty or prefix answers) {s['early_stop']}")
        print(f"   errored questions {s['errored']}; loose exact on the {s['n_valid']} without an error "
              f"{s['exact_loose_valid']} ({lo3:.0%}–{hi3:.0%}); view-disabled events "
              f"{s['view_disabled_events']}, unbounded forwards {s['unbounded_forward_events']}; "
              f"stopped histories {s['stopped_histories']}")
        print(f"   verify {s['verify']}; upstream calls {s['upstream_calls']}, errors {s['errors']}, "
              f"history errors {s['history_errors']}, proxy starts {s['proxy_starts']}; foreign between "
              f"{s['foreign_between']}, during {s['foreign_during']}, overlap samples "
              f"{s['foreign_overlap_samples']}, gate waits {s['gate_waits']}, gate events {s['gate_events']}; "
              f"wall {s['wall_s'] and round(s['wall_s'] / 60, 1)} min; question tokens "
              f"{s['q_prompt_tokens']:,}/{s['q_completion_tokens']:,}; cached all steps {s['cached_tokens']:,}")


if __name__ == "__main__":
    main()
