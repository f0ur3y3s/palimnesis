"""Summarize Phase 3 needle runs from ``eval/needle.py`` (emulator or real OpenCode).

    python eval/report.py RUNDIR [--configs a4-base,a3-base] [--fixtures eval/fixtures/phase3-dev]
    python eval/report.py RUN --configs a4-d43 --set heldout [--designate ho-h3=2,...]
    python eval/report.py --coding RUN [--designate ho-t3:a4=2,...]

A run directory with ``attempts.json`` (``eval/attempts.py``; the OpenCode driver and
the task runner) is read per history or task from its designated attempt, the latest by
default; superseded attempts are listed with the reason. With ``--set heldout`` the needle
gate (D44.4) is printed over all 12 histories x 10 questions: a needle with no row counts
as a miss. ``--coding`` prints the coding gate (D44.5, D45.8).

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

ORDER = ["a4-base", "a3-base", "a2-base", "a4-q2", "a4-x2", "a4-a4", "a4-d43"]
NEEDLE_GATE = 0.85  # D44.4
BOOT_RESAMPLES, BOOT_SEED = 10_000, 44


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


def load(run: Path, config: str, designate: dict | None = None):
    if (run / "attempts.json").exists():
        return load_attempts(run, config, designate)
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


def _one_n_ctx(metas: list[dict]) -> int | None:
    """The ``expect_n_ctx`` the designated attempts share; one run never mixes two."""
    seen = {m.get("expect_n_ctx") for m in metas} - {None}
    if len(seen) > 1:
        raise ValueError(f"designated attempts ran at different n_ctx: {sorted(seen)}")
    return seen.pop() if seen else None


def load_attempts(run: Path, config: str, designate: dict | None = None):
    """Rows of the designated attempt per history; meta merged over those attempts."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import attempts as att

    chosen, superseded = att.designate(att.load(run), "needles", config, designate)
    rows, metas, pairs = [], [], []
    for hid, a in sorted(chosen.items()):
        d = Path(a["records"])
        rows += [r for r in (json.loads(l) for l in (d / "questions.jsonl").read_text(encoding="utf-8").splitlines() if l)
                 if r["history"] == hid]
        if not any(m.get("_dir") == str(d) for m in metas):
            m = json.loads((d / "meta.json").read_text(encoding="utf-8")) if (d / "meta.json").exists() else {}
            m["_dir"] = str(d)
            logs = "".join(f.read_text(encoding="utf-8", errors="replace") for f in sorted(d.glob("proxy-*.log")))
            m["_log_view_disabled"] = logs.count("bounded views disabled")
            m["_log_unbounded"] = logs.count("forwarding unbounded")
            metas.append(m)
            ex = d / "explain.json"
            if ex.exists() and ex.read_text(encoding="utf-8").strip():
                pairs += json.loads(ex.read_text(encoding="utf-8")).get("pairs", [])
    meta = {"_log_view_disabled": sum(m["_log_view_disabled"] for m in metas),
            "_log_unbounded": sum(m["_log_unbounded"] for m in metas),
            "explain_exit": max((m.get("explain_exit") if m.get("explain_exit") is not None else 99 for m in metas), default=None),
            "verify": {k: v for m in metas for k, v in (m.get("verify") or {}).items()},
            "gate_events": [e for m in metas for e in m.get("gate_events") or []],
            "history_errors": [e for m in metas for e in m.get("infra_failures") or []],
            "proxy_starts": sum(m.get("proxy_starts") or 0 for m in metas),
            "started": min((m.get("started", 0) for m in metas), default=0),
            "finished": max((m.get("finished", 0) for m in metas), default=0),
            "expect_n_ctx": _one_n_ctx(metas),
            "attempts": metas, "superseded": superseded,
            "designated": {h: a["attempt"] for h, a in chosen.items()}}
    explain = {"pairs": pairs, "summary": {"pairs": len(pairs)}}
    return rows, meta, explain


def expected_needles(set_name: str) -> dict[str, list[dict]]:
    """{history id: [{id, category, answer}] per question} of a committed needle set."""
    folder = {"heldout": "heldout", "development": "dev"}[set_name]
    out = {}
    for f in sorted((Path(__file__).resolve().parent / "needles" / folder).glob("*.json")):
        h = json.loads(f.read_text(encoding="utf-8"))
        out[h["id"]] = [{"id": s["id"], "category": s["category"], "answer": s["answer"]}
                        for s in h["steps"] if s["kind"] == "question"]
    return out


def fill_missing(rows: list[dict], expected: dict[str, list[dict]]) -> tuple[list[dict], list[str]]:
    """Every expected needle gets a row; a missing one is a miss (``not_run: missing``)."""
    have = {(r["history"], r["step"]) for r in rows if r["kind"] == "question"}
    missing = []
    out = list(rows)
    for hid, steps in expected.items():
        for st in steps:
            sid = st["id"]
            if (hid, sid) not in have:
                missing.append(f"{hid}/{sid}")
                out.append({"history": hid, "session": None, "step": sid, "kind": "question",
                            "category": st["category"], "not_run": "missing", "rounds": 0, "tool_calls": [],
                            "lookups": 0, "prompt_tokens": 0, "completion_tokens": 0,
                            "cached_tokens": 0, "calls": [], "errors": [{"status": None, "error": "missing"}],
                            "total_s": 0.0, "answer": "", "answered": False, "gold": st["answer"],
                            "exact": False, "exact_loose": False, "contains": False, "partial": False})
    return out, missing


def cluster_bootstrap(by_history: dict[str, list[bool]], resamples: int = BOOT_RESAMPLES,
                      seed: int = BOOT_SEED) -> tuple[float, float]:
    """History-clustered percentile bootstrap (D45 amendment): resample histories with
    replacement ``resamples`` times (``random.Random(seed)``), take loose exact over all
    needles of the resampled histories, and return the 2.5% and 97.5% percentiles
    (linear interpolation between order statistics)."""
    import random

    hs = [v for _, v in sorted(by_history.items())]
    if not hs:
        return (0.0, 0.0)
    rnd = random.Random(seed)
    stats = []
    for _ in range(resamples):
        pick = [hs[rnd.randrange(len(hs))] for _ in hs]
        n = sum(len(v) for v in pick)
        stats.append(sum(sum(v) for v in pick) / n if n else 0.0)
    stats.sort()

    def q(p):
        x = p * (len(stats) - 1)
        lo = int(x)
        hi = min(lo + 1, len(stats) - 1)
        return stats[lo] + (stats[hi] - stats[lo]) * (x - lo)

    return (q(0.025), q(0.975))


def needle_gate(rows: list[dict], expected: dict[str, list[dict]]) -> dict:
    """D44.4 on loose exact over every expected needle; missing rows count as misses."""
    rows, missing = fill_missing(rows, expected)
    allq = [r for r in rows if r["kind"] == "question" and r["history"] in expected]
    seen, q = set(), []
    for r in allq:  # one row per needle counts; any second row fails the gate
        if (r["history"], r["step"]) not in seen:
            seen.add((r["history"], r["step"]))
            q.append(r)
    by_h: dict[str, list[bool]] = {}
    for r in q:
        by_h.setdefault(r["history"], []).append(bool(r["exact_loose"]))
    n = sum(len(v) for v in expected.values())
    k = sum(bool(r["exact_loose"]) for r in q)
    dupes = len(allq) - len(q)
    return {"n": n, "rows": len(q), "duplicates": dupes, "loose": k, "strict": sum(bool(r["exact"]) for r in q),
            "rate": k / n if n else 0.0, "wilson": wilson(k, n), "bootstrap": cluster_bootstrap(by_h),
            "missing": missing, "not_run": sum(1 for r in q if r.get("not_run")),
            "pass": n > 0 and dupes == 0 and k / n >= NEEDLE_GATE}


HELDOUT_TASKS = ["ho-t1", "ho-t2", "ho-t3", "ho-t4", "ho-t5"]
RESTART_TASK = "ho-t3"


def load_task_results(run: Path, designate: dict | None = None) -> tuple[dict, list[dict]]:
    """{(task, arm): result.json of the designated attempt}, superseded attempts."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import attempts as att

    manifest = att.load(run)
    out, sup = {}, []
    for arm in (4, 1):
        override = {k.split(":")[0]: v for k, v in (designate or {}).items() if k.endswith(f":a{arm}")}
        chosen, superseded = att.designate(manifest, "task", f"a{arm}", override)
        sup += [{**x, "arm": arm} for x in superseded]
        for tid, a in chosen.items():
            f = Path(a["records"]) / f"{tid}-a{arm}" / "result.json"
            out[(tid, arm)] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"aborted": "no result.json"}
    return out, sup


def task_success(r: dict | None) -> bool:
    return bool(r and not r.get("aborted") and (r.get("check") or {}).get("success"))


def arm4_inputs_ok(r: dict) -> bool:
    """D44.6 inputs of one arm-4 task run."""
    scan = r.get("excerpt_scan") or {}
    return bool((r.get("explain_gate") or {}).get("ok") and (r.get("verify") or {}).get("exit") == 0
                and (r.get("over_budget") or {}).get("ok")
                and all((v or {}).get("leaks", 1) == 0 for v in (scan.get("client"), scan.get("transcripts"))))


def coding_gate(results: dict, tasks: list[str] = HELDOUT_TASKS) -> dict:
    """D44.5: arm 4's successes are at least arm 1's over the held-out tasks, and the
    restart task passes under arm 4 with its key constraint (D45.8). A missing or aborted
    run is a failure until it is rerun."""
    a4 = sum(task_success(results.get((t, 4))) for t in tasks)
    a1 = sum(task_success(results.get((t, 1))) for t in tasks)
    rt = results.get((RESTART_TASK, 4)) or {}
    restart = bool(task_success(rt) and rt.get("restart_gate"))
    inputs = all(arm4_inputs_ok(results.get((t, 4)) or {}) for t in tasks)
    missing = [f"{t}:a{arm}" for t in tasks for arm in (4, 1) if (t, arm) not in results]
    return {"arm4_successes": a4, "arm1_successes": a1, "restart_gate": restart,
            "arm4_inputs_ok": inputs, "missing": missing, "pass": a4 >= a1 and restart}


def print_coding(run: Path, designate: dict | None) -> None:
    results, sup = load_task_results(run, designate)
    print("| Task | Arm | Attempt | Success | Constraints (stub) | Restart gate | Turns | Tokens in/out | "
          "Lookups | Latency s | Compaction calls | Proxy rejections | --explain | verify | Over budget | "
          "Leaks:echoes client/transcripts | Aborted |")
    print("|" + "---|" * 17)
    for (tid, arm), r in sorted(results.items()):
        c, st = r.get("check") or {}, r.get("stub_check") or {}
        scan = r.get("excerpt_scan") or {}
        leaks = "/".join(f"{(scan.get(k) or {}).get('leaks')}:{(scan.get(k) or {}).get('echoes')}"
                         for k in ("client", "transcripts")) if scan else "n/a"
        over = len((r.get("over_budget") or {}).get("over", [])) if r.get("over_budget") else "n/a"
        print(f"| {tid} | {arm} | {r.get('attempt')} | {c.get('success')} | {c.get('constraints_held')}/"
              f"{c.get('constraints_total')} ({st.get('constraints_held')}/{st.get('constraints_total')}) | "
              f"{r.get('restart_gate')} | {len(r.get('turns') or [])} | {r.get('prompt_tokens', 0):,}/"
              f"{r.get('completion_tokens', 0):,} | {r.get('lookups')} | {r.get('latency_s')} | "
              f"{len(r.get('compaction_calls') or [])} | {r.get('proxy_rejections')} | "
              f"{(r.get('explain_gate') or {}).get('ok', 'n/a')} | {(r.get('verify') or {}).get('exit', 'n/a')} | "
              f"{over} | {leaks} | {r.get('aborted')} |")
    g = coding_gate(results)
    verdict = "PASS" if g["pass"] else "FAIL"
    print(f"\nCoding gate (D44.5): arm 4 {g['arm4_successes']}/5 vs arm 1 {g['arm1_successes']}/5; "
          f"restart task {RESTART_TASK} under arm 4 (success and its key constraint): {g['restart_gate']}; "
          f"arm-4 gate inputs ok: {g['arm4_inputs_ok']}; missing runs: {g['missing'] or 'none'} -> {verdict}")
    for x in sup:
        print(f"superseded: {x['id']} arm {x['arm']} attempt {x['attempt']} ({x['status']}) by attempt "
              f"{x['superseded_by']}: {x['reason']}")


def budget_for(meta: dict) -> int:
    """Arm 4's input budget at the run's ``n_ctx`` (32768 for runs that record none)."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gate_inputs as gi

    return gi.input_budget_for(meta.get("expect_n_ctx") or 32768)


def mark_clean(rows, budget: int) -> None:
    """``clean``: no error in this or any earlier step of the session, and every upstream call
    of the question within the input budget (a larger body means bounded views were off)."""
    bad = set()
    for r in rows:
        if r["errors"]:
            bad.add(r["session"])
        over = any((c.get("prompt_tokens") or 0) > budget for c in r["calls"])
        r["clean"] = r["session"] not in bad and not over and not r["errors"]


def summarize(rows, meta, explain) -> dict:
    mark_clean(rows, budget_for(meta))
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
        "early_stop": len(early_stops(valid)),
        "early_stop_examples": [(r["step"], r["gold"], r["answer"][:40]) for r in early_stops(valid)],
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


def early_stops(rows) -> list[dict]:
    return [r for r in rows if r["answered"] and not r["exact_loose"] and (
        not r["answer"].strip()
        or r["gold"].casefold().startswith(r["answer"].strip().strip("`").casefold()))]


def drift(run: Path, config: str) -> dict:
    """Per session: upstream ``usage.prompt_tokens`` against the pinned local count of the
    exact upstream body the gate recorded; nonzero differences are listed."""
    from palimnesis.upstreams.strata import tokens

    counter = tokens.default()
    d = run / config
    out: dict = {}
    for line in (d / "calls.jsonl").read_text(encoding="utf-8").splitlines():
        c = json.loads(line)
        if not c.get("n") or c.get("prompt_tokens") is None:
            continue
        body = json.loads((d / "bodies" / f"{c['n']:04d}.json").read_bytes())
        local = counter.count_messages(**tokens.render_args_from_openai(body))
        s = out.setdefault(c["session"], {"calls": 0, "nonzero": []})
        s["calls"] += 1
        if local != c["prompt_tokens"]:
            s["nonzero"].append({"n": c["n"], "step": c["step"], "local": local,
                                 "remote": c["prompt_tokens"]})
    return out


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value: binomial(b + c, 0.5) on the discordant pairs."""
    n, k = b + c, min(b, c)
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


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
    p.add_argument("--drift", action="store_true", help="recount every upstream body locally")
    p.add_argument("--pool", help="RUN2[,RUN3...]: pool these run dirs with RUN for --pair")
    p.add_argument("--pair", help="A,B: paired per-needle table and exact McNemar, pooled")
    p.add_argument("--set", choices=["development", "heldout"],
                   help="print the needle gate over the whole committed set (missing = miss)")
    p.add_argument("--designate", help="ID=ATTEMPT[,...] (tasks: ID:aARM=ATTEMPT) instead of the latest")
    p.add_argument("--coding", action="store_true", help="RUN is a task run directory: the coding gate")
    a = p.parse_args()
    designate = {k: int(v) for k, v in (x.split("=") for x in a.designate.split(","))} if a.designate else None
    if a.coding:
        print_coding(a.run, designate)
        return
    if a.pair:
        ca, cb = a.pair.split(",")
        runs = [a.run] + [Path(x) for x in (a.pool or "").split(",") if x]
        k = Counter()
        es = Counter()
        for run in runs:
            ra, _, _ = load(run, ca)
            rb, _, _ = load(run, cb)
            qa = {r["step"]: r for r in ra if r["kind"] == "question"}
            qb = {r["step"]: r for r in rb if r["kind"] == "question"}
            es[ca] += len(early_stops([r for r in qa.values() if not r["errors"]]))
            es[cb] += len(early_stops([r for r in qb.values() if not r["errors"]]))
            for sid in qa:
                if sid in qb:
                    k[(qa[sid]["exact_loose"], qb[sid]["exact_loose"])] += 1
        n = sum(k.values())
        print(f"Pooled over {len(runs)} run(s), {n} needle pairs ({ca} rows, {cb} columns):")
        print(f"| | {cb} right | {cb} wrong |")
        print("|---|---|---|")
        print(f"| {ca} right | {k[(True, True)]} | {k[(True, False)]} |")
        print(f"| {ca} wrong | {k[(False, True)]} | {k[(False, False)]} |")
        b, c = k[(True, False)], k[(False, True)]
        print(f"discordant: {ca} only {b}, {cb} only {c}; exact McNemar two-sided p = {mcnemar_exact(b, c):.4g}")
        print(f"early stops pooled: {dict(es)} of {n} needles each")
        return
    if a.drift:
        configs = a.configs.split(",") if a.configs else [c for c in ORDER if (a.run / c / "calls.jsonl").exists()]
        for c in configs:
            dr = drift(a.run, c)
            total = sum(v["calls"] for v in dr.values())
            bad = {s: v["nonzero"] for s, v in dr.items() if v["nonzero"]}
            print(f"{c}: {total} calls in {len(dr)} sessions; sessions with nonzero drift: {len(bad)}")
            for s, cases in bad.items():
                print(f"   {s}: {cases}")
        return
    configs = a.configs.split(",") if a.configs else [c for c in ORDER if (a.run / c / "questions.jsonl").exists()]
    res, rows_by = {}, {}
    for c in configs:
        rows, meta, explain = load(a.run, c, designate)
        if a.set:
            expected = expected_needles(a.set)
            if a.set == "heldout":  # D44.3: 12 histories x 10 questions
                shape = {k: len(v) for k, v in expected.items()}
                assert len(expected) == 12 and set(shape.values()) == {10}, shape
            gate = needle_gate(rows, expected)
            rows, _ = fill_missing(rows, expected)
            lo, hi = gate["wilson"]
            blo, bhi = gate["bootstrap"]
            verdict = "PASS" if gate["pass"] else "FAIL"
            print(f"{c} needle gate (D44.4, {a.set}): loose exact {gate['loose']}/{gate['n']} "
                  f"({gate['rate']:.1%}), 95% Wilson {lo:.1%}-{hi:.1%}, history-clustered bootstrap "
                  f"{blo:.1%}-{bhi:.1%} ({BOOT_RESAMPLES} resamples, seed {BOOT_SEED}); strict exact "
                  f"{gate['strict']}; not run {gate['not_run']}, missing {len(gate['missing'])}, "
                  f"duplicates {gate['duplicates']} -> {verdict} (>= {NEEDLE_GATE:.0%})")
            for x in meta.get("superseded", []):
                print(f"   superseded: {x['id']} attempt {x['attempt']} ({x['status']}) by attempt "
                      f"{x['superseded_by']}: {x['reason']}")
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
        print(f"   upstream early stops (empty or prefix answers) {s['early_stop']}: {s['early_stop_examples']}")
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
