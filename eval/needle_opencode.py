"""Needle histories through real OpenCode 2.1.4 (``eval/needle.py run --driver opencode``).

D44.2: held-out needles run through real OpenCode, never the emulator. Per history:

1. A fresh git repo holds the history's workspace files (committed, so OpenCode sees a
   project with a root commit).
2. The import messages up to, not including, the Q1 text become an
   ``opencode session export`` document (``oc_harness.history_to_export``) and enter an
   isolated OpenCode home through ``opencode session import``. The file is deleted once
   imported; its SHA-256 stays in the records.
3. The provider's ``baseURL`` is ``palimnesis session url <history>-<config>-<tag>-a<N>``
   on the front tap (``eval/oc_stack.py``).
4. Every step is one ``opencode run --session <id> --format json`` turn, its text on stdin.
   The proxy restarts where the history says so (``restart_before``, Q8 → Q9). OpenCode
   builds and resends every request itself, executes its own tools and decides when to
   stop; there is no tool cap.

**Attempts** (D44.7, ``eval/attempts.py``): ``--out RUN`` is a run directory. Each
invocation is a new attempt with its records in ``RUN/records/attempt-NNN/`` and its
workspaces, OpenCode homes and transcripts root in ``--ws-root`` (default ``RUN-ws``),
which holds no records. A rerun of a history needs ``--reason``.

**Held-out runs** (``--set heldout``) refuse a dirty git tree, any configuration other
than ``a4-d43``, ``--questions`` and ``--resume``, and Strata unless ``/props`` reports
``n_ctx`` ``--expect-n-ctx`` (32768) before and after every history.

**Every question gets a row.** A step that never ran (import failure, an unfaithful import,
an exception, an abort, a Strata check) gets a miss row with ``not_run`` and the reason,
so the gate's denominator stays 10 per history. An import whose first client body
differs from the history (beyond the ``reasoning_content: ""`` OpenCode adds), or whose
prior turns are not all archived as ``client_import``, is an infrastructure failure
(D44.7) and stops that history.

Per-step records keep the emulator's fields (``eval/report.py`` reads both), plus
``driver: "opencode"``, the proxy's own statuses (front tap) and slow upstream calls.
``ttfvc_s`` runs from the start of the ``opencode run`` process (OpenCode start-up
included) to the first visible content or tool-call delta at the upstream tap.

``needle.py preflight --set heldout`` pushes every import through real OpenCode against
the fake upstream (no proxy, no model, no Strata) and checks fidelity.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

import httpx

import attempts as att
import gate_inputs as gi
import needle
import oc_harness as oc
import oc_stack

DRIVER_VERSION = "needle-opencode v2"
TURN_TIMEOUT_S = 1800


def import_fidelity(client_body: dict, history: list[dict], question: str) -> dict:
    """Compare the first client request with the imported history plus the Q1 text.

    OpenCode 2.1.4 (with ``compatibility.reasoningField``) sends ``reasoning_content``
    on every assistant turn, ``""`` when the turn has none; that difference alone is
    normalized. Returns counts and the first mismatching index (``None`` when equal)."""
    got = [m for m in client_body["messages"] if m.get("role") != "system"]
    want = [dict(m) for m in history] + [{"role": "user", "content": question}]
    for m in want:
        if m["role"] == "assistant" and "reasoning_content" not in m:
            m["reasoning_content"] = ""
    first_diff = next((i for i, (g, w) in enumerate(zip(got, want)) if g != w), None)
    if first_diff is None and len(got) != len(want):
        first_diff = min(len(got), len(want))
    return {"messages_sent": len(got), "messages_expected": len(want), "first_diff": first_diff,
            "faithful": first_diff is None,
            "empty_reasoning_added": sum(1 for m in got if m.get("role") == "assistant"
                                         and m.get("reasoning_content") == "")}


def archive_first_request(db: Path, session: str) -> dict:
    """The session's first archived client body and its occurrences by source (read-only)."""
    from palimnesis.rawarchive import get_raw

    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT request_id, raw_id FROM requests WHERE session_id = ? "
                           "ORDER BY arrived_at LIMIT 1", (session,)).fetchone()
        if row is None:
            return {}
        sources = dict(conn.execute(
            "SELECT source, count(*) FROM occurrences WHERE request_id = ? GROUP BY source",
            (row[0],)).fetchall())
        return {"body": json.loads(get_raw(conn, row[1])), "sources": sources}
    finally:
        conn.close()


def turn_summary(events: list[dict]) -> dict:
    """Final text, tool calls and step finishes from ``opencode run --format json``.

    2.1.4 emits ``step_finish`` for a step that ends in tool calls but none for the
    turn's last step (observed), so the answer is the text of the last step that
    started, unless that step called a tool."""
    texts: dict[str, list[str]] = {}
    tooled: set[str] = set()
    steps: list[str] = []
    finishes: list[str] = []
    tools, errors = [], []
    for e in events:
        part = e.get("part") or {}
        mid = part.get("messageID")
        kind = e.get("type")
        if kind == "step_start":
            steps.append(mid)
        elif kind == "text":
            texts.setdefault(mid, []).append(part.get("text") or "")
        elif kind == "tool_use":
            tooled.add(mid)
            st = part.get("state") or {}
            tools.append({"name": part.get("tool"), "input": st.get("input") or {},
                          "status": st.get("status"),
                          "output_chars": len(st.get("output") or st.get("error") or "")})
        elif kind == "step_finish":
            finishes.append(part.get("reason"))
        elif kind == "error" or "error" in e:
            errors.append(json.dumps(e.get("error") or e, ensure_ascii=False)[:500])
    final = None
    last = steps[-1] if steps else next(reversed(texts), None)
    if last is not None and last not in tooled:
        final = "".join(texts.get(last, []))
    return {"final": final, "tools": tools, "finishes": finishes, "errors": errors,
            "steps": len(steps)}


def miss_row(h: dict, step: dict, session: str, config: str, arm: int, reason: str) -> dict:
    """A question that never ran: a miss with the reason (D44.4 counts it)."""
    return {"history": h["id"], "session": session, "config": config, "arm": arm,
            "driver": "opencode", "step": step["id"], "kind": "question",
            "category": step.get("category"), "restart_before": bool(step.get("restart_before")),
            "not_run": reason, "rounds": 0, "tool_calls": [], "lookups": 0,
            "workspace_tool_calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "cached_tokens": 0, "calls": [], "errors": [{"status": None, "error": f"not run: {reason}"}],
            "total_s": 0.0, "answer": "", "answered": False, "gold": step["answer"],
            "exact": False, "exact_loose": False, "contains": False, "parts_found": 0,
            "parts_total": len(step["parts"]), "partial": False}


def import_doc(h: dict, ws: Path) -> tuple[dict, list[dict]]:
    history = h["import"][:-1]
    if h["import"][-1] != {"role": "user", "content": h["steps"][0]["text"]}:
        raise ValueError(f"{h['id']}: the import does not end with the Q1 text")
    doc = oc.history_to_export(history, directory=str(ws), project_id=oc.git_root_commit(ws),
                               t0_ms=int(time.time() * 1000) - 6 * 3600 * 1000, seed=h["seed"])
    return doc, history


def make_workspace(h: dict, ws: Path) -> None:
    ws.mkdir(parents=True)
    for rel, text in h["workspace"].items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    subprocess.run(["git", "add", "-A"], cwd=ws, check=True)
    subprocess.run(["git", "-c", "user.name=eval", "-c", "user.email=eval@localhost",
                    "commit", "-q", "-m", "workspace"], cwd=ws, check=True)


def do_import(home: oc.Home, doc: dict, where: Path) -> dict:
    """Write the import file, import it, delete it; returns its hash and the outcome."""
    raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    path = where / "import.json"
    path.write_bytes(raw)
    try:
        imp = home.import_(path)
    finally:
        path.unlink(missing_ok=True)
    ok = imp["exit"] == 0 and doc["info"]["id"] in imp["stdout"]
    return {"ok": ok, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "error": None if ok else f"{imp['stdout'][-300:]} {imp['stderr'][-300:]}"}


# ---------------------------------------------------------------- preflight

def preflight(a) -> int:
    """Every history's import through real OpenCode against the fake upstream: the first
    request must equal the history plus Q1. No proxy, no model, no Strata."""
    sys.path.insert(0, str(needle.ROOT))
    from tests.fake_upstream import FakeUpstream
    from tests.servers import serve

    histories = needle.select_histories(a)
    bad = 0
    fake = FakeUpstream()
    with serve(fake.app()) as base, tempfile.TemporaryDirectory(prefix="preflight-") as tmp:
        for hpath in histories:
            h = json.loads(hpath.read_text(encoding="utf-8"))
            root = Path(tmp) / h["id"]
            ws = root / "ws"
            make_workspace(h, ws)
            home = oc.Home(root / "oc", ws)
            home.write_config(oc.config(base + "/v1"))
            doc, history = import_doc(h, ws)
            imp = do_import(home, doc, root)
            if not imp["ok"]:
                bad += 1
                print(f"{h['id']}: import failed: {imp['error']}", flush=True)
                continue
            n0 = len(fake.requests)
            fake.respond_counted(text="ok")
            turn = home.run(h["steps"][0]["text"], session=doc["info"]["id"], label="q1", timeout=300)
            reqs = [r for r in fake.requests[n0:] if r.path.endswith("/chat/completions")]
            if not reqs:
                bad += 1
                print(f"{h['id']}: no request reached the fake upstream (exit {turn['exit']})", flush=True)
                continue
            fid = import_fidelity(json.loads(reqs[0].body), history, h["steps"][0]["text"])
            bad += not fid["faithful"]
            print(f"{h['id']}: faithful={fid['faithful']} messages={fid['messages_sent']}/"
                  f"{fid['messages_expected']} first_diff={fid['first_diff']} "
                  f"empty_reasoning_added={fid['empty_reasoning_added']} import_sha256={imp['sha256'][:16]}",
                  flush=True)
    print(f"preflight: {len(histories) - bad}/{len(histories)} faithful", flush=True)
    return 1 if bad else 0


# ---------------------------------------------------------------- the run

def refusals(a, histories: list[Path]) -> list[str]:
    out = []
    if a.set == "heldout":
        if a.config != "a4-d43":
            out.append(f"held-out needles run only a4-d43 (D44.1), not {a.config}")
        if a.questions:
            out.append("held-out runs ask every question; drop --questions")
        if a.resume:
            out.append("held-out attempts are never resumed; start a new attempt with --reason")
        prov = gi.git_provenance()
        if prov["dirty"]:
            out.append("held-out runs need a clean git tree: " + "; ".join(prov["status"][:5]))
    if a.resume:
        out.append("--resume does not apply to the OpenCode driver; each invocation is a new attempt")
    if not histories:
        out.append("no histories selected")
    return out


def run(a) -> int:
    cfg = needle.CONFIGS[a.config]
    histories = needle.select_histories(a)
    problems = refusals(a, histories)
    if problems:
        for p in problems:
            print(f"refused: {p}", file=sys.stderr)
        return 2
    upstream = a.upstream.rstrip("/")
    props = gi.strata_props(upstream)
    why = gi.check_n_ctx(props, a.expect_n_ctx)
    if why:
        print(f"refused: {why}", file=sys.stderr)
        return 2
    ids = [json.loads(h.read_text(encoding="utf-8"))["id"] for h in histories]
    attempt = att.new_attempt(Path(a.out), kind="needles", config=a.config, ids=ids, reason=a.reason,
                              ws_root=Path(a.ws_root) if a.ws_root else None,
                              extra={"set": a.set, "tag": a.tag})
    n_att = attempt["attempt"]
    rec_dir, ws_dir = Path(attempt["records"]), Path(attempt["ws"])
    troot = ws_dir / "transcripts" if cfg["transcripts_enabled"] else None
    settings = {k: cfg[k] for k in ("recall", "transcripts_enabled", "query_policy",
                                    "excerpt_renderer", "addendum")}
    stack = oc_stack.Stack(rec_dir, upstream, settings, transcripts=troot)
    from palimnesis.projector import session_dir

    client = httpx.Client(timeout=httpx.Timeout(None, connect=15))
    meta = {"config": a.config, **cfg, "settings": stack.settings, "input_budget": "default (serve)",
            "driver": "opencode", "driver_version": DRIVER_VERSION, "opencode": "2.1.4",
            "set": a.set, "live": True, "upstream": a.upstream, "attempt": n_att,
            "provenance": gi.git_provenance(), "expect_n_ctx": a.expect_n_ctx,
            "started": time.time(), "sessions": [], "imports": {}, "strata": [],
            "infra_failures": [], "not_run": [], "transcripts_root": str(troot) if troot else None}
    qlog = open(rec_dir / "questions.jsonl", "a", encoding="utf-8")
    clog = open(rec_dir / "calls.jsonl", "a", encoding="utf-8")
    abort: str | None = None
    status = 0

    def misses(h, steps, session, reason):
        for st in steps:
            if st["kind"] == "question":
                qlog.write(json.dumps(miss_row(h, st, session, a.config, cfg["arm"], reason),
                                      ensure_ascii=False) + "\n")
                meta["not_run"].append({"history": h["id"], "step": st["id"], "reason": reason})
        qlog.flush()

    try:
        for hpath in histories:
            h = json.loads(hpath.read_text(encoding="utf-8"))
            session = f"{h['id']}-{a.config}-{a.tag}-a{n_att}"
            steps = h["steps"]
            if a.questions:
                qs = [s for s in steps if s["kind"] == "question"][:a.questions]
                steps = [s for s in steps if s["kind"] != "question" or s in qs]
                steps = steps[:steps.index(qs[-1]) + 1]
            if abort:
                misses(h, steps, session, abort)
                continue
            before_props = gi.strata_props(upstream)
            meta["strata"].append({"history": h["id"], "when": "before", **before_props})
            why = gi.check_n_ctx(before_props, a.expect_n_ctx)
            if why:
                abort = f"strata_check: {why}"
                misses(h, steps, session, abort)
                continue
            meta["sessions"].append(session)
            done = 0
            try:
                base = ws_dir / h["id"]
                ws = base / "ws"
                make_workspace(h, ws)
                home = oc.Home(base / "oc", ws)
                home.write_config(oc.config(stack.base_url(session)))
                doc, history = import_doc(h, ws)
                imp = do_import(home, doc, base)
                meta["imports"][session] = {"sha256": imp["sha256"], "bytes": imp["bytes"]}
                if not imp["ok"]:
                    reason = f"import_failed: {imp['error']}"
                    meta["infra_failures"].append({"history": h["id"], "reason": reason})
                    misses(h, steps, session, reason)
                    continue
                ses = doc["info"]["id"]
                sdir = session_dir(troot, session) if troot else None
                tools = needle.Tools(ws, troot, sdir, [], None)
                for si, step in enumerate(steps):
                    if stack.tap.abort:
                        raise needle.SlotBusyTooLong(stack.tap.abort)
                    if step.get("restart_before"):
                        stack.restart_proxy()
                    rec = run_step(a, cfg, h, step, session, ses, home, stack, tools, client, clog, rec_dir)
                    done = si + 1
                    infra = None
                    if si == 0:
                        first = archive_first_request(stack.proxy.db, session)
                        fid = (import_fidelity(first["body"], history, step["text"]) if first
                               else {"faithful": False, "first_diff": None, "error": "no archived request"})
                        fid["sources"] = (first or {}).get("sources")
                        fid["prior_assistant_tool"] = sum(1 for m in history if m["role"] in ("assistant", "tool"))
                        fid["client_import_ok"] = (fid["sources"] or {}).get("client_import") == fid["prior_assistant_tool"]
                        meta["imports"][session].update(fid)
                        rec["import"] = fid
                        if not (fid["faithful"] and fid["client_import_ok"]):
                            infra = f"import_infidelity: first_diff={fid.get('first_diff')} sources={fid['sources']}"
                            rec["errors"].append({"status": None, "error": infra})
                            rec["infra_failure"] = infra
                    qlog.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    qlog.flush()
                    print(f"[{a.config}/opencode a{n_att}] {step['id']:7} {str(step.get('category')):24} "
                          f"exact={rec.get('exact_loose')!s:5} view={rec.get('in_view')!s:5} "
                          f"exc={rec.get('in_excerpt')!s:5} lookups={rec['lookups']} rounds={rec['rounds']} "
                          f"proxy={rec['proxy_statuses']} {rec['total_s']:.0f}s ans={rec['answer'][:60]!r}",
                          flush=True)
                    if infra:
                        meta["infra_failures"].append({"history": h["id"], "reason": infra})
                        misses(h, steps[done:], session, infra)
                        break
                    if any(e["status"] == 409 for e in rec["errors"]):
                        misses(h, steps[done:], session, "history_divergence (409) earlier in the session")
                        break
                try:
                    (rec_dir / "exports").mkdir(exist_ok=True)
                    (rec_dir / "exports" / f"{session}.json").write_text(
                        json.dumps(home.export(ses), ensure_ascii=False), encoding="utf-8")
                except Exception as e:
                    meta.setdefault("export_errors", {})[session] = f"{type(e).__name__}: {e}"
            except needle.SlotBusyTooLong as e:
                abort = f"slot_busy: {e}"
                status = 3
                misses(h, steps[done:], session, abort)
            except Exception:
                reason = "driver_exception: " + traceback.format_exc()[-600:]
                print(f"history {h['id']} failed: {reason}", flush=True)
                meta["infra_failures"].append({"history": h["id"], "reason": reason})
                misses(h, steps[done:], session, reason)
            after_props = gi.strata_props(upstream)
            meta["strata"].append({"history": h["id"], "when": "after", **after_props})
            why = gi.check_n_ctx(after_props, a.expect_n_ctx)
            if why and not abort:
                abort = f"strata_check: {why}"
                status = 3
    finally:
        stack.stop()
        meta["finished"] = time.time()
        meta["gate_events"] = stack.gate.events
        meta["proxy_starts"] = stack.proxy.starts
        meta["abort"] = abort
        qlog.close()
        clog.close()
    gate_checks(rec_dir, ws_dir, stack, cfg, meta, troot, a.expect_n_ctx, histories)
    att.finish_attempt(Path(a.out), n_att, "aborted" if abort else "done", abort=abort,
                       infra_failures=meta["infra_failures"])
    return status


def run_step(a, cfg, h, step, session, ses, home, stack, tools, client, clog, rec_dir) -> dict:
    rec = {"history": h["id"], "session": session, "config": a.config, "arm": cfg["arm"],
           "driver": "opencode", "opencode_session": ses, "step": step["id"], "kind": step["kind"],
           "category": step.get("category"), "restart_before": bool(step.get("restart_before")),
           "rounds": 0, "tool_calls": [], "lookups": 0, "workspace_tool_calls": 0,
           "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "calls": [], "errors": []}
    pre = stack.gate.wait_idle(client, f"driver:{step['id']}")
    before, fbefore = len(stack.tap.calls), len(stack.front.calls)
    q0 = time.time()
    turn = home.run(step["text"], session=ses, label=step["id"], timeout=TURN_TIMEOUT_S)
    stack.settle()
    new_calls, front_calls = stack.tap.calls[before:], stack.front.calls[fbefore:]
    summ = turn_summary(turn["events"])
    rec.update(oc_stack.call_summary(new_calls, front_calls))
    rec["front_n"] = [c["n"] for c in front_calls]
    rec["rounds"] = len(new_calls)
    rec["opencode_exit"] = turn["exit"]
    rec["opencode_s"] = turn["elapsed_s"]
    rec["finishes"] = summ["finishes"]
    if turn.get("timeout_killed"):
        rec["errors"].append({"status": None, "error": f"opencode run killed at {TURN_TIMEOUT_S}s"})
    if turn["exit"] != 0:
        rec["errors"].append({"status": None, "error": f"opencode exit {turn['exit']}: {turn['stderr'][-300:]}"})
    for e in summ["errors"]:
        rec["errors"].append({"status": None, "error": e})
    for c in oc_stack.failed(front_calls):
        rec["errors"].append({"status": c.get("status"), "error": f"proxy: {c.get('stream_error') or 'status'}"})
    for tc in new_calls:
        rec["prompt_tokens"] += tc.get("prompt_tokens") or 0
        rec["completion_tokens"] += tc.get("completion_tokens") or 0
        rec["cached_tokens"] += tc.get("cached_tokens") or 0
        t_arr = tc.get("t_arrival") or q0
        rec["calls"].append({
            "status": tc.get("status"), "finish": tc.get("finish"), "upstream_calls": 1,
            "tap_n": tc.get("n"), "prompt_tokens": tc.get("prompt_tokens"),
            "cached_tokens": tc.get("cached_tokens"), "completion_tokens": tc.get("completion_tokens"),
            "first_content_s": round(tc["t_first_content"] - t_arr, 3) if tc.get("t_first_content") else None,
            "total_s": round((tc.get("t_end") or t_arr) - t_arr, 3), "upstream_s": tc.get("upstream_s"),
            "driver_wait_s": pre["waited_s"], "prompt_ms": (tc.get("timings") or {}).get("prompt_ms"),
            "tap_wait_s": tc.get("waited_s"), "foreign_between": tc.get("foreign_between"),
            "foreign_during": tc.get("foreign_during"),
            "foreign_overlap_samples": tc.get("foreign_overlap_samples")})
        clog.write(json.dumps({"session": session, "step": step["id"], **tc}) + "\n")
    clog.flush()
    firsts = [tc for tc in new_calls if tc.get("t_first_content")]
    if firsts:
        rec["ttfvc_s"] = round(firsts[0]["t_first_content"] - q0, 3)
        rec["ttfvc_upstream_s"] = round(firsts[0]["t_first_content"] - firsts[0]["t_arrival"], 3)
    for t in summ["tools"]:
        args = t["input"] if isinstance(t["input"], dict) else {}
        lookup = tools.is_lookup(t["name"] or "", args)
        rec["tool_calls"].append({"name": t["name"], "lookup": lookup,
                                  "args": {k: (v if len(str(v)) < 200 else str(v)[:200]) for k, v in args.items()},
                                  "result_chars": t["output_chars"], "error": t["status"] == "error"})
        rec["lookups"] += int(lookup)
        rec["workspace_tool_calls"] += int(not lookup)
    rec["total_s"] = round(time.time() - q0, 3)
    final = summ["final"]
    rec["answer"] = (final or "")[:300]
    rec["answered"] = final is not None
    if step["kind"] == "question":
        rec["gold"] = step["answer"]
        rec.update(needle.score(final, step))
        if new_calls:
            body = (rec_dir / "bodies" / f"{new_calls[0]['n']:04d}.json").read_bytes()
            rec.update(needle.context_check(body, step))
            rec["fact_absent"] = not rec["in_view"] and not rec["in_excerpt"]
            rec["appropriate_fallback"] = rec["fact_absent"] and rec["lookups"] > 0
            rec["unnecessary_lookups"] = 0 if rec["fact_absent"] else rec["lookups"]
    return rec


def gate_checks(rec_dir: Path, ws_dir: Path, stack, cfg: dict, meta: dict, troot: Path | None,
                n_ctx: int, histories: list[Path]) -> None:
    """D44.6 inputs: ``--explain`` (exit 0, pairs = calls minus each session's first, 0
    unexplained), ``transcripts verify``, inputs over budget by the pinned counter, excerpt
    leaks and echoes, slow upstream calls, and records reachable from the workspaces."""
    db = stack.proxy.db
    calls = [json.loads(l) for l in (rec_dir / "calls.jsonl").read_text(encoding="utf-8").splitlines() if l]
    by_session: dict[str, int] = {}
    for c in calls:
        by_session[c["session"]] = by_session.get(c["session"], 0) + 1
    code, report, err = gi.run_explain(db)
    (rec_dir / "explain.json").write_text(json.dumps(report) if report else "", encoding="utf-8")
    meta["explain_exit"], meta["explain_stderr"] = code, err
    meta["explain_gate"] = gi.explain_gate(code, report, by_session)
    meta["verify"] = (needle.verify_sessions(db, meta["sessions"], troot)
                      if cfg["transcripts_enabled"] else {})
    meta["over_budget"] = gi.local_over_budget(rec_dir / "bodies", calls, gi.input_budget_for(n_ctx))
    meta["slow_upstream_calls"] = [c["n"] for c in calls if (c.get("upstream_s") or 0) > oc_stack.SLOW_UPSTREAM_S]
    excerpts = gi.excerpt_texts(db) if db.exists() else []
    texts = oc_stack.client_texts(rec_dir, stack.front.calls)
    for f in sorted((rec_dir / "exports").glob("*.json")) if (rec_dir / "exports").exists() else []:
        texts += gi.strings_of(json.loads(f.read_text(encoding="utf-8")))
    meta["excerpts_stored"] = len(excerpts)
    meta["excerpt_scan"] = {"client": gi.scan(excerpts, texts),
                            "transcripts": gi.scan(excerpts, gi.transcript_texts(troot))}
    golds = []
    for hp in histories:
        golds += [s["answer"] for s in json.loads(hp.read_text(encoding="utf-8"))["steps"] if s["kind"] == "question"]
    meta["reachable_records"] = gi.reachable_records(ws_dir, answer_keys=golds)
    (rec_dir / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    eg = meta["explain_gate"]
    print(f"explain exit {code} pairs {eg['pairs']}/{eg['expected_pairs']} unexplained {eg['unexplained']}; "
          f"verify {sum(v['exit'] == 0 for v in meta['verify'].values())}/{len(meta['verify'])}; "
          f"over budget {len(meta['over_budget']['over'])}; leaks {meta['excerpt_scan']}; "
          f"slow {len(meta['slow_upstream_calls'])}; reachable records {len(meta['reachable_records'])}",
          flush=True)
