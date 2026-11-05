"""Needle histories through real Pi 1.5.0 (``eval/needle.py run --driver pi``).

Phase 4B S14, "Development needles dev-h1..h6 via the harness driver, arm 4 only —
reported" (``docs/plan/phases/phase4b.md`` §6). The structure mirrors the OpenCode driver
(``eval/needle_opencode.py``); per history:

1. A fresh git repo holds the history's workspace files (``needle_opencode.make_workspace``).
2. The import messages up to, not including, the Q1 text become a Pi session file
   (``pi_harness.history_to_pi_session``; HP7) whose header id is the Palimnesis session,
   ``<history>-<config>-<tag>-a<N>``. The template is written, copied to the session file
   Pi will use and append to (HP7: Pi appends to an imported file), then deleted; its
   SHA-256 stays in the records.
3. Pi runs isolated with the shipped adapter (``integrations/pi/``) pointed at the front tap
   (``Stack``, as ``eval/oc_stack.py``). The adapter's extension sends
   ``X-Palimnesis-Session`` = Pi's session id = the header id, so one history is one
   Palimnesis session with no ``/s/<id>`` in the base URL.
4. Every step is one ``pi --mode json --session <file>`` turn, its text as the message. The
   proxy restarts where the history says so (``restart_before``). Pi builds and resends
   every request, executes its own tools (``read,grep,bash,ls,find``) and decides when to
   stop; there is no tool cap.

**Import fidelity.** The first step's archived client body must carry the history plus the
Q1 text exactly as Pi sends Chat (user content as text parts, HP3 §3.1; Pi's own system
message and tools allowed), and every prior assistant and tool message must be archived as
``client_import``. Anything else is an infrastructure failure that stops the history (D44.7),
as in the OpenCode driver. Each step also records whether its first request ended with the
step's text verbatim (``prompt_faithful``). ``--protocol messages`` compares the protocol-
neutral ``canonical`` sequence instead (development only; not yet run live).

**Attempts, refusals.** As the OpenCode driver: ``--out RUN`` is a run directory of attempts
(``eval/attempts.py``, kind ``needles``, so ``eval/report.py`` reads it; use a run directory
of its own for Pi), ``--ws-root`` holds workspaces and Pi homes, a rerun needs
``--reason``. Pi runs only ``a4-d77`` (arm 4, the serve defaults). Held-out sets keep the
OpenCode driver's rules (``needle_opencode.refusals``); in 4B Pi runs no held-out set
(O-4B-11), so only the retired ``heldout2`` is accepted, and never against the fake upstream.

**Fake upstream** (``--upstream fake``, development check only): the stack runs against
``tests/fake_upstream.py`` with no slot gate; each question is scripted as one ``bash``
grep of the session's transcript directory, then the gold answer; a paste gets "ok". It
proves the plumbing (import, resend, records, gate inputs), not any model behaviour.

Per-step records keep the OpenCode driver's fields (``report.py`` reads them) with
``driver: "pi"``, ``pi_exit``, ``pi_s``, ``settled``, ``stops`` and ``pi_retries``.
``ttfvc_s`` runs from the start of the ``pi`` process to the first visible delta at the
upstream tap.

``needle.py preflight --driver pi`` pushes imports through real Pi straight to the fake
upstream (no proxy) and checks fidelity, like the OpenCode preflight.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sys
import tempfile
import time
import traceback
from pathlib import Path

import httpx

import attempts as att
import gate_inputs as gi
import needle
import needle_opencode as nod
import oc_stack
import pi_harness as pi

DRIVER_VERSION = "needle-pi v1"
TURN_TIMEOUT_S = 1800
PI_CONFIGS = (needle.A4_HELDOUT3,)  # a4-d77: arm 4, equal to serve's defaults (D78)


class Stack(oc_stack.Stack):
    """``oc_stack.Stack`` with an optional slot gate (none against the fake upstream, whose
    ``/v1/status`` is not served) and the front tap's origin for Pi's ``baseUrl``."""

    def __init__(self, records: Path, upstream: str, settings: dict, *, gated: bool = True,
                 transcripts: Path | None = None, input_budget: int | None = None):
        self.records = records
        self.gate = needle.SlotGate(upstream if gated else None)
        self.tap = needle.Tap(upstream, records / "bodies", self.gate)
        self.tap_server, self.tap_thread = needle.serve_in_thread(self.tap, tap_port := needle.free_port())
        self.settings = dict(settings, deadline_s=3600.0)
        if transcripts is not None:
            self.settings["transcripts"] = str(transcripts)
        self.transcripts = transcripts
        self.proxy = needle.ProxyProcess(records, f"http://127.0.0.1:{tap_port}", self.settings,
                                         input_budget=input_budget)
        self.proxy.start()
        self.front = needle.Tap(self.proxy.url, records / "front", needle.SlotGate(None))
        self.front_port = needle.free_port()
        self.front_server, self.front_thread = needle.serve_in_thread(self.front, self.front_port)

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.front_port}"


def import_history(h: dict) -> list[dict]:
    history = h["import"][:-1]
    if h["import"][-1] != {"role": "user", "content": h["steps"][0]["text"]}:
        raise ValueError(f"{h['id']}: the import does not end with the Q1 text")
    return history


def write_session(h: dict, history: list[dict], session: str, ws: Path, home: pi.PiHome,
                  protocol: str) -> dict:
    """Write the session template, copy it to the file Pi will use, delete the template.
    Returns the session file, its hash and size, or the conversion error."""
    try:
        entries = pi.history_to_pi_session(
            history, session_id=session, cwd=str(ws), protocol=protocol,
            model=pi.model_id(protocol), t0_ms=int(time.time() * 1000) - 6 * 3600 * 1000,
            seed=h["seed"])
    except ValueError as e:
        return {"ok": False, "error": f"unrepresentable history: {e}"}
    raw = pi.session_jsonl(entries)
    template = home.root / "import.template.jsonl"
    template.write_bytes(raw)
    path = home.root / "sessions" / f"{session}.jsonl"
    try:
        path.write_bytes(template.read_bytes())
    finally:
        template.unlink(missing_ok=True)
    return {"ok": True, "path": path, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "entries": len(entries)}


FAKE_NOTES = ("Objective\nAnswer the user's questions about this session.\nCurrent step and next move\n"
              "Waiting for the next question.\nRequirements and constraints\nNone recorded.\n"
              "Decisions\nNone.\nDone so far\nNothing changed.\nDead ends\nNone.")


class FakeModel:
    """The fake upstream's model, answering by request: the proxy's own working-notes
    refresh (``[palimnesis notes request]``, a4-d77's notes) gets ``FAKE_NOTES``; every
    other request takes the next scripted reply of the current step, or "ok" when the step
    has none left. Per step, a question greps the session's transcript directory with Pi's
    ``bash`` tool (when transcripts are on), then answers with the gold value; a paste
    gets "ok". Counts come from ``FakeUpstream.respond_counted``."""

    def __init__(self, fake):
        self.fake = fake
        self.queue: list[dict] = []
        self.notes = 0

    def script(self, step: dict, sdir: Path | None) -> None:
        self.queue = []
        if step["kind"] == "question":
            if sdir is not None:
                cmd = (f"grep -rn -F -- {json.dumps(step['parts'][0])} {json.dumps(sdir.as_posix())}"
                       " | head -5")
                self.queue.append({"tool_call": (f"call_fake_{step['id']}", "bash",
                                                 pi.js_compact({"command": cmd}))})
            self.queue.append({"text": step["answer"]})
        else:
            self.queue.append({"text": "ok"})
        from tests.fake_upstream import _Scripted

        for _ in range(len(self.queue) + 4):  # spare entries serve notes refreshes and strays
            self.fake._script.append(_Scripted(status=200, headers={"content-type": "text/event-stream"},
                                               build=self._build, chunks=[]))

    def _build(self, raw: bytes) -> list[bytes]:
        if "[palimnesis notes request]" in (pi.last_user_text(json.loads(raw)) or ""):
            self.notes += 1
            reply = {"text": FAKE_NOTES}
        else:
            reply = self.queue.pop(0) if self.queue else {"text": "ok"}
        # respond_counted's builder, borrowed: queue it, take it straight back, build.
        self.fake.respond_counted(**reply)
        return self.fake._script.pop().build(raw)


def miss_row(h, step, session, config, arm, reason) -> dict:
    return dict(nod.miss_row(h, step, session, config, arm, reason), driver="pi")


# ---------------------------------------------------------------- preflight

def preflight(a) -> int:
    """Every history's import through real Pi straight to the fake upstream: the first
    request must carry the history plus Q1. No proxy, no model, no Strata."""
    sys.path.insert(0, str(needle.ROOT))
    from tests.fake_upstream import FakeUpstream
    from tests.servers import serve

    protocol = getattr(a, "protocol", "chat")
    histories = needle.select_histories(a)
    bad = 0
    fake = FakeUpstream()
    with serve(fake.app()) as base, tempfile.TemporaryDirectory(prefix="pi-preflight-") as tmp:
        for hpath in histories:
            h = json.loads(hpath.read_text(encoding="utf-8"))
            root = Path(tmp) / h["id"]
            ws = root / "ws"
            nod.make_workspace(h, ws)
            home = pi.PiHome(root / "pi", ws, base, protocol)
            history = import_history(h)
            session = f"{h['id']}-preflight"
            imp = write_session(h, history, session, ws, home, protocol)
            if not imp["ok"]:
                bad += 1
                print(f"{h['id']}: {imp['error']}", flush=True)
                continue
            n0 = len(fake.requests)
            fake.respond_counted(text="ok")
            turn = home.run(h["steps"][0]["text"], imp["path"], label="q1", timeout=300)
            reqs = [r for r in fake.requests[n0:] if r.method == "POST"]
            if not reqs:
                bad += 1
                print(f"{h['id']}: no request reached the fake upstream (exit {turn['exit']})", flush=True)
                continue
            fid = pi.chat_fidelity(json.loads(reqs[0].body), history, h["steps"][0]["text"], protocol)
            hdr = reqs[0].headers.get("x-palimnesis-session")
            bad += not (fid["faithful"] and hdr == session)
            print(f"{h['id']}: faithful={fid['faithful']} messages={fid['messages_sent']}/"
                  f"{fid['messages_expected']} first_diff={fid['first_diff']} session_header={hdr == session} "
                  f"sha256={imp['sha256'][:16]}" + (f" diff={fid.get('diff')}" if fid.get("diff") else ""),
                  flush=True)
    print(f"preflight (pi, {protocol}): {len(histories) - bad}/{len(histories)} faithful", flush=True)
    return 1 if bad else 0


# ---------------------------------------------------------------- the run

def refusals(a, histories: list[Path]) -> list[str]:
    out = []
    if a.config not in PI_CONFIGS:
        out.append(f"the Pi driver runs arm 4 only, {' or '.join(PI_CONFIGS)} (phase4b §6), not {a.config}")
    if a.set in needle.HELDOUT_SETS:
        if a.set not in needle.RETIRED_SETS:
            out.append(f"no held-out set runs through Pi in Phase 4B (O-4B-11): {a.set}")
        if a.upstream == "fake":
            out.append("held-out histories never run against the fake upstream (it answers with the gold)")
        out += [p for p in nod.refusals(a, histories)
                if not p.startswith("--resume does not apply") and not p.startswith("held-out needles run only")]
    if a.resume:
        out.append("--resume does not apply to the Pi driver; each invocation is a new attempt")
    if not histories:
        out.append("no histories selected")
    return out


def run(a) -> int:
    histories = needle.select_histories(a)
    problems = refusals(a, histories)
    cfg = None
    try:
        cfg = needle.config(a.config)
    except ValueError as e:
        problems.append(str(e))
    if problems:
        for p in problems:
            print(f"refused: {p}", file=sys.stderr)
        return 2
    protocol = a.protocol
    with contextlib.ExitStack() as es:
        fake = None
        if a.upstream == "fake":
            sys.path.insert(0, str(needle.ROOT))
            from tests.fake_upstream import FakeUpstream
            from tests.servers import serve

            fake = FakeUpstream(props_n_ctx=a.expect_n_ctx)
            upstream = es.enter_context(serve(fake.app()))
        else:
            upstream = a.upstream.rstrip("/")
        return _run(a, cfg, histories, upstream, fake, protocol)


def _run(a, cfg, histories, upstream, fake, protocol) -> int:
    props = gi.strata_props(upstream)
    why = gi.check_n_ctx(props, a.expect_n_ctx)
    if why:
        print(f"refused: {why}", file=sys.stderr)
        return 2
    ids = [json.loads(h.read_text(encoding="utf-8"))["id"] for h in histories]
    attempt = att.new_attempt(Path(a.out), kind="needles", config=a.config, ids=ids, reason=a.reason,
                              ws_root=Path(a.ws_root) if a.ws_root else None,
                              extra={"set": a.set, "tag": a.tag, "driver": "pi", "protocol": protocol})
    n_att = attempt["attempt"]
    rec_dir, ws_dir = Path(attempt["records"]), Path(attempt["ws"])
    troot = ws_dir / "transcripts" if cfg["transcripts_enabled"] else None
    settings = needle.proxy_settings(cfg)
    stack = Stack(rec_dir, upstream, settings, gated=fake is None, transcripts=troot,
                  input_budget=a.input_budget)
    from palimnesis.transcripts.projector import session_dir

    client = httpx.Client(timeout=httpx.Timeout(None, connect=15))
    fake_model = FakeModel(fake) if fake is not None else None
    meta = {"config": a.config, **cfg, "settings": stack.settings,
            "input_budget": a.input_budget if a.input_budget is not None else "default (serve)",
            "driver": "pi", "driver_version": DRIVER_VERSION, "pi": "1.5.0", "pi_cli": str(pi.PI_CLI),
            "protocol": protocol, "pi_tools": pi.TOOLS, "set": a.set, "live": fake is None,
            "upstream": a.upstream, "attempt": n_att, "provenance": gi.git_provenance(),
            "expect_n_ctx": a.expect_n_ctx, "started": time.time(), "sessions": [], "imports": {},
            "strata": [], "infra_failures": [], "not_run": [],
            "transcripts_root": str(troot) if troot else None}
    qlog = open(rec_dir / "questions.jsonl", "a", encoding="utf-8", newline="\n")
    clog = open(rec_dir / "calls.jsonl", "a", encoding="utf-8", newline="\n")
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
            home = None
            try:
                base = ws_dir / h["id"]
                ws = base / "ws"
                nod.make_workspace(h, ws)
                home = pi.PiHome(base / "pi", ws, stack.origin, protocol)
                history = import_history(h)
                imp = write_session(h, history, session, ws, home, protocol)
                meta["imports"][session] = {k: imp[k] for k in ("sha256", "bytes", "entries", "error") if k in imp}
                if not imp["ok"]:
                    reason = f"import_failed: {imp['error']}"
                    meta["infra_failures"].append({"history": h["id"], "reason": reason})
                    misses(h, steps, session, reason)
                    continue
                sdir = session_dir(troot, session) if troot else None
                tools = needle.Tools(ws, troot, sdir, [], None)
                for si, step in enumerate(steps):
                    if stack.tap.abort:
                        raise needle.SlotBusyTooLong(stack.tap.abort)
                    if step.get("restart_before"):
                        stack.restart_proxy()
                    if fake_model is not None:
                        fake_model.script(step, sdir)
                    rec = run_step(a, cfg, h, step, session, imp["path"], home, stack, tools, client,
                                   clog, rec_dir, protocol)
                    done = si + 1
                    infra = None
                    if si == 0:
                        first = nod.archive_first_request(stack.proxy.db, session)
                        fid = (pi.chat_fidelity(first["body"], history, step["text"], protocol) if first
                               else {"faithful": False, "first_diff": None, "error": "no archived request"})
                        fid["sources"] = (first or {}).get("sources")
                        fid["prior_assistant_tool"] = sum(1 for m in history if m["role"] in ("assistant", "tool"))
                        fid["client_import_ok"] = (fid["sources"] or {}).get("client_import") == fid["prior_assistant_tool"]
                        meta["imports"][session].update(fid)
                        rec["import"] = fid
                        if not (fid["faithful"] and fid["client_import_ok"]):
                            infra = (f"import_infidelity: first_diff={fid.get('first_diff')} "
                                     f"sources={fid['sources']} diff={fid.get('diff')}")
                            rec["errors"].append({"status": None, "error": infra})
                            rec["infra_failure"] = infra
                    qlog.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    qlog.flush()
                    print(f"[{a.config}/pi-{protocol} a{n_att}] {step['id']:7} {str(step.get('category')):24} "
                          f"exact={rec.get('exact_loose')!s:5} view={rec.get('in_view')!s:5} "
                          f"exc={rec.get('in_excerpt')!s:5} lookups={rec['lookups']} rounds={rec['rounds']} "
                          f"proxy={rec['proxy_statuses']} prompt_ok={rec.get('prompt_faithful')} "
                          f"{rec['total_s']:.0f}s ans={rec['answer'][:60]!r}", flush=True)
                    if infra:
                        meta["infra_failures"].append({"history": h["id"], "reason": infra})
                        misses(h, steps[done:], session, infra)
                        break
                    if any(e["status"] == 409 for e in rec["errors"]):
                        misses(h, steps[done:], session, "history_divergence (409) earlier in the session")
                        break
            except needle.SlotBusyTooLong as e:
                abort = f"slot_busy: {e}"
                status = 3
                misses(h, steps[done:], session, abort)
            except Exception:
                reason = "driver_exception: " + traceback.format_exc()[-600:]
                print(f"history {h['id']} failed: {reason}", flush=True)
                meta["infra_failures"].append({"history": h["id"], "reason": reason})
                misses(h, steps[done:], session, reason)
            finally:
                if home is not None:
                    save_session(rec_dir, home, session, meta)
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
        if fake_model is not None:
            meta["fake_notes_replies"] = fake_model.notes
        qlog.close()
        clog.close()
    nod.gate_checks(rec_dir, ws_dir, stack, cfg, meta, troot, a.expect_n_ctx, histories, a.input_budget)
    att.finish_attempt(Path(a.out), n_att, "aborted" if abort else "done", abort=abort,
                       infra_failures=meta["infra_failures"])
    return status


def save_session(rec_dir: Path, home: pi.PiHome, session: str, meta: dict) -> None:
    """Pi's session file as the history's export: the raw JSONL in ``pi-sessions/`` and an
    export-shaped copy in ``exports/`` for the gate scans (``pi_harness.as_export``)."""
    path = home.root / "sessions" / f"{session}.jsonl"
    if not path.exists():
        return
    try:
        (rec_dir / "pi-sessions").mkdir(exist_ok=True)
        (rec_dir / "pi-sessions" / path.name).write_bytes(path.read_bytes())
        (rec_dir / "exports").mkdir(exist_ok=True)
        (rec_dir / "exports" / f"{session}.json").write_text(
            json.dumps(pi.as_export(pi.read_session(path)), ensure_ascii=False), encoding="utf-8",
            newline="\n")
    except Exception as e:
        meta.setdefault("export_errors", {})[session] = f"{type(e).__name__}: {e}"


def run_step(a, cfg, h, step, session, session_file, home, stack, tools, client, clog, rec_dir,
             protocol) -> dict:
    rec = {"history": h["id"], "session": session, "config": a.config, "arm": cfg["arm"],
           "driver": "pi", "protocol": protocol, "pi_session": session, "step": step["id"],
           "kind": step["kind"], "category": step.get("category"),
           "restart_before": bool(step.get("restart_before")),
           "rounds": 0, "tool_calls": [], "lookups": 0, "workspace_tool_calls": 0,
           "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "calls": [], "errors": []}
    pre = stack.gate.wait_idle(client, f"driver:{step['id']}")
    before, fbefore = len(stack.tap.calls), len(stack.front.calls)
    q0 = time.time()
    turn = home.run(step["text"], session_file, label=step["id"], timeout=TURN_TIMEOUT_S)
    stack.settle()
    new_calls, front_calls = stack.tap.calls[before:], stack.front.calls[fbefore:]
    summ = pi.turn_summary(turn["events"])
    rec.update(oc_stack.call_summary(new_calls, front_calls))
    rec["front_n"] = [c["n"] for c in front_calls]
    rec["rounds"] = len(new_calls)
    rec["pi_exit"] = turn["exit"]
    rec["pi_s"] = turn["elapsed_s"]
    rec["settled"] = summ["settled"]
    rec["stops"] = summ["stops"]
    rec["finishes"] = summ["stops"]
    rec["pi_retries"] = summ["retries"]
    if front_calls:
        body = json.loads((rec_dir / "front" / f"{front_calls[0]['n']:04d}.json").read_bytes())
        rec["prompt_faithful"] = pi.last_user_text(body) == step["text"]
        if not rec["prompt_faithful"]:
            rec["errors"].append({"status": None, "error": "the step's text did not reach the proxy verbatim"})
    if turn.get("timeout_killed"):
        rec["errors"].append({"status": None, "error": f"pi killed at {TURN_TIMEOUT_S}s"})
    if not summ["settled"]:
        # Judged by the events, not the exit code (HP7: Windows exit 0xC0000409 after work).
        rec["errors"].append({"status": None, "error": f"pi did not settle (exit {turn['exit']}): "
                                                       f"{turn['stderr'][-300:]}"})
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
                                  "result_chars": t["output_chars"], "error": t["error"]})
        rec["lookups"] += int(lookup)
        rec["workspace_tool_calls"] += int(not lookup)
    needle.count_hidden(rec, new_calls)
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
