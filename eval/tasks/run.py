"""Run one Phase 3 coding task through real OpenCode 2.1.4 under one arm (plan §5, D44.5).

    uv run python eval/tasks/run.py --task ho-t1 --arm 4 --out RUN [--reason TEXT] [--ws-root DIR]
        [--expect-n-ctx 32768] [--upstream URL] [--tag T]
    uv run python eval/tasks/run.py --check-reference [--task ID]   # no model: the checks themselves

Arms (D44.1):
  4  ``a4-d43``: the default ``serve`` (q1/r1/x2/a3, transcripts), OpenCode with
     ``compaction.auto`` off and ``limit.context`` 1,000,000 (the shipped settings).
  1  native OpenCode compaction: ``serve --passthrough``, ``compaction.auto`` on and
     ``limit.context`` 32768, the true capacity at the held-out ``n_ctx``.

**Attempts** (D44.7, ``eval/attempts.py``): each invocation is a new attempt of one task
under one arm. Records go to ``RUN/records/attempt-NNN/``; the workspace, OpenCode home
and transcripts root go to ``--ws-root`` (default ``RUN-ws``), a tree with no records,
answers or hidden checks in it. A rerun needs ``--reason``.

**Refusals and aborts.** Held-out tasks refuse a dirty git tree. Every run refuses to
start, and aborts, unless Strata's ``/props`` reports ``--expect-n-ctx``; it is read
before and after the session. One task is one OpenCode session: a first turn that yields
no session id aborts. An abort is ``aborted: <reason>`` in ``result.json``, exit code 3,
and no check runs.

**The check.** After the session the workspace is copied into the records tree, the
task's hidden check is written into the copy only, and a small runner executes it with
the system Python, writing one outcome per test id as JSON. The expected test names are
read from ``HIDDEN``; a test that did not report counts as failed. Success needs every
``test_f_*``; constraint ``C<N>`` holds when every ``test_c<N>_*`` passed. A check that
outlives its timeout fails with ``check_timeout``. For a task with a ``KEY_CONSTRAINT``
(the restart task, ho-t3) the restart gate needs success and that constraint (D45.8). The
stub's own check result is recorded beside it.

**Gate inputs** (arm 4): ``--explain`` (exit 0, pairs = upstream calls − 1, 0 unexplained),
``transcripts verify``, inputs over budget by the pinned counter, excerpt leaks and echoes
(client requests and responses, the OpenCode export, transcript files), records
reachable from the workspace tree, and per call the upstream time (flagged over 600 s).
Every turn also records the proxy's own statuses (front tap).
"""

from __future__ import annotations

import argparse
import ast
import importlib
import json
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
ROOT = EVAL.parent
sys.path[:0] = [str(HERE), str(EVAL)]

import attempts as att  # noqa: E402
import gate_inputs as gi  # noqa: E402
import needle  # noqa: E402
import oc_harness as oc  # noqa: E402
import oc_stack  # noqa: E402

TASKS = ["dev-t1", "dev-t2", "dev-t3", "ho-t1", "ho-t2", "ho-t3", "ho-t4", "ho-t5"]
RUNNER_VERSION = "tasks-run v2"
TURN_TIMEOUT_S = 1800
CHECK_TIMEOUT_S = 300
CONTEXT_32K = 32_768
A4 = needle.CONFIGS["a4-d43"]

# Executes the hidden check and writes {test id: outcome}; stderr and stdout are free.
CHECK_RUNNER = r'''import json, os, sys, unittest

sys.path.insert(0, os.getcwd())
out, names = sys.argv[1], sys.argv[2:]
outcomes = {}


class Result(unittest.TextTestResult):
    def addSuccess(self, test):
        super().addSuccess(test)
        outcomes.setdefault(test.id(), "ok")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        outcomes[test.id()] = "FAIL"

    def addError(self, test, err):
        super().addError(test, err)
        outcomes[getattr(test, "id", lambda: str(test))()] = "ERROR"

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        outcomes[test.id()] = "skipped"

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        outcomes[test.id()] = "expected failure"

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        outcomes[test.id()] = "unexpected success"

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            outcomes[test.id()] = "FAIL"


suite = unittest.defaultTestLoader.loadTestsFromNames(names)
unittest.TextTestRunner(resultclass=Result, verbosity=2).run(suite)
with open(out, "w", encoding="utf-8") as f:
    json.dump(outcomes, f)
'''


def load(task_id: str):
    return importlib.import_module(task_id.replace("-", "_"))


def task_seed(task_id: str) -> int:
    return sum(ord(c) * 31 ** i for i, c in enumerate(task_id)) % 1_000_003


def materialize(task, ws: Path) -> None:
    rnd = random.Random(task_seed(task.ID))
    for rel, text in task.files(rnd).items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")


def expected_tests(hidden: dict[str, str]) -> list[str]:
    """Test method names defined in the hidden check's classes."""
    names = []
    for text in hidden.values():
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ClassDef):
                names += [f.name for f in node.body
                          if isinstance(f, ast.FunctionDef) and f.name.startswith("test_")]
    return names


def by_method(outcomes: dict[str, str]) -> dict[str, str]:
    """{test id: outcome} -> {method name: outcome}."""
    return {tid.rsplit(".", 1)[-1]: v for tid, v in outcomes.items()}


def score_check(results: dict[str, str], expected: list[str], constraints: dict[str, str]) -> dict:
    """Task success: every expected ``test_f_*`` reported ``ok`` (at least one exists).
    Constraint ``C<N>``: every expected ``test_c<N>_*`` reported ``ok``. An expected test
    with no result counts as failed."""
    def ok(name):
        return results.get(name) == "ok"

    functional = [n for n in expected if n.startswith("test_f_")]
    adherence = {}
    for cid in constraints:
        mine = [n for n in expected if n.startswith(f"test_c{cid[1:]}_")]
        adherence[cid] = bool(mine) and all(ok(n) for n in mine)
    return {"success": bool(functional) and all(ok(n) for n in functional),
            "functional_passed": sum(ok(n) for n in functional), "functional_total": len(functional),
            "missing": [n for n in expected if n not in results],
            "constraints": adherence, "constraints_held": sum(adherence.values()),
            "constraints_total": len(adherence)}


def check_env(root: Path) -> dict:
    """The allowlisted environment (``oc.base_env``) with HOME and TEMP under ``root``."""
    for d in ("home", "tmp"):
        (root / d).mkdir(parents=True, exist_ok=True)
    return oc.base_env(root)


def system_python() -> str:
    """The ``python`` the model's shell finds on the cleaned PATH. Resolved here because
    Windows looks a bare name up on the parent's PATH, where ``uv run`` put the venv."""
    found = shutil.which("python", path=oc.clean_path())
    if not found:
        raise RuntimeError("no python on the cleaned PATH")
    return found


def run_check(task, ws: Path, check_dir: Path, python: str | None = None,
              timeout: float = CHECK_TIMEOUT_S) -> dict:
    """Copy ``ws`` to ``check_dir/ws``, write the hidden check there only, and run it with
    ``python`` (default: ``system_python()``)."""
    python = python or system_python()
    copy = check_dir / "ws"
    if copy.exists():
        raise FileExistsError(copy)
    shutil.copytree(ws, copy, ignore=shutil.ignore_patterns(".git"))
    for rel, text in task.HIDDEN.items():
        p = copy / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    (check_dir / "run_check.py").write_text(CHECK_RUNNER, encoding="utf-8", newline="\n")
    out = check_dir / "outcomes.json"
    mods = [rel[:-3].replace("/", ".") for rel in task.HIDDEN]
    expected = expected_tests(task.HIDDEN)
    try:
        p = subprocess.run([python, str(check_dir / "run_check.py"), str(out), *mods], cwd=copy,
                           capture_output=True, text=True, env=check_env(check_dir / "env"), timeout=timeout)
    except subprocess.TimeoutExpired:
        r = score_check({}, expected, task.CONSTRAINTS)
        return {**r, "success": False, "reason": "check_timeout", "exit": None, "results": {}}
    try:
        results = by_method(json.loads(out.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        results = {}
    r = score_check(results, expected, task.CONSTRAINTS)
    return {"exit": p.returncode, "results": results, **r,
            "reason": None if results else "no_outcomes", "tail": (p.stdout + p.stderr)[-1500:]}


def check_one(task, overlay: dict[str, str], python: str | None = None) -> dict:
    """The hidden check on a fresh task repo with ``overlay`` files written over it."""
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d) / "repo"
        materialize(task, ws)
        for rel, text in overlay.items():
            (ws / rel).write_text(text, encoding="utf-8", newline="\n")
        cd = Path(d) / "check"
        cd.mkdir()
        return run_check(task, ws, cd, python)


def restart_gate(task, check: dict) -> bool | None:
    """D45.8: the restart task passes under arm 4 only with success and its key constraint."""
    if not task.KEY_CONSTRAINT:
        return None
    return bool(check.get("success") and check.get("constraints", {}).get(task.KEY_CONSTRAINT))


def check_reference(task_ids: list[str]) -> int:
    """No model: the hidden check passes on ``REFERENCE`` and fails on the stub."""
    bad = 0
    for tid in task_ids:
        task = load(tid)
        for label, overlay in (("stub", {}), ("reference", task.REFERENCE)):
            r = check_one(task, overlay)
            ok = r["success"] and r["constraints_held"] == r["constraints_total"]
            want = label == "reference"
            bad += ok != want
            print(f"{tid} {label}: success={r['success']} functional={r['functional_passed']}/"
                  f"{r['functional_total']} constraints={r['constraints_held']}/{r['constraints_total']}"
                  f"{'' if ok == want else '  <-- UNEXPECTED'}")
    return 1 if bad else 0


def drift(bodies: Path, calls: list[dict]) -> dict:
    """Upstream ``usage.prompt_tokens`` against the pinned local count of each exact body."""
    from palimnesis.upstreams.strata import tokens

    counter = tokens.default()
    nonzero, n = [], 0
    for c in calls:
        if c.get("prompt_tokens") is None:
            continue
        body = json.loads((bodies / f"{c['n']:04d}.json").read_bytes())
        local = counter.count_messages(**tokens.render_args_from_openai(body))
        n += 1
        if local != c["prompt_tokens"]:
            nonzero.append({"n": c["n"], "local": local, "remote": c["prompt_tokens"]})
    return {"calls": n, "nonzero": nonzero}


# The last user message of an OpenCode 2.1.4 compaction request (observed, dev-t1 arm 1):
# a first summary, an update of an existing checkpoint, or the retry after a reply that
# did not fill the template. The request still offers the tools.
COMPACTION_PROMPTS = ("You MUST summarize the conversation above",
                      "Update the existing checkpoint in the conversation above",
                      "The previous response did not fill in the required summary template")


def is_compaction(body: dict) -> bool:
    msgs = body.get("messages") or []
    last = msgs[-1] if msgs else {}
    text = last.get("content") if isinstance(last.get("content"), str) else ""
    return last.get("role") == "user" and text.startswith(COMPACTION_PROMPTS)


def compaction_calls(bodies: Path, calls: list[dict]) -> list[int]:
    """Upstream calls that are OpenCode compaction requests (``is_compaction``)."""
    return [c["n"] for c in calls
            if is_compaction(json.loads((bodies / f"{c['n']:04d}.json").read_bytes()))]


def hidden_markers(task) -> list[str]:
    """Strings that only the hidden check contains: its class and test definitions."""
    out = ["class HiddenTests"] + list(task.HIDDEN)
    for text in task.HIDDEN.values():
        out += [l.strip() for l in text.splitlines() if l.strip().startswith(("def test_f_", "def test_c"))]
    return out


class Abort(RuntimeError):
    pass


def run(a) -> int:
    task = load(a.task)
    arm = a.arm
    name = f"{task.ID}-a{arm}"
    if task.SET == "heldout":
        prov = gi.git_provenance()
        if prov["dirty"]:
            print("refused: held-out tasks need a clean git tree: " + "; ".join(prov["status"][:5]),
                  file=sys.stderr)
            return 2
    upstream = a.upstream.rstrip("/")
    props = gi.strata_props(upstream)
    why = gi.check_n_ctx(props, a.expect_n_ctx)
    if why:
        print(f"refused: {why}", file=sys.stderr)
        return 2
    attempt = att.new_attempt(Path(a.out), kind="task", config=f"a{arm}", ids=[task.ID], reason=a.reason,
                              ws_root=Path(a.ws_root) if a.ws_root else None, extra={"tag": a.tag})
    n_att = attempt["attempt"]
    out, wsroot = Path(attempt["records"]) / name, Path(attempt["ws"])
    out.mkdir()
    ws = wsroot / "ws"
    ws.mkdir()
    materialize(task, ws)
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    subprocess.run(["git", "add", "-A"], cwd=ws, check=True)
    subprocess.run(["git", "-c", "user.name=eval", "-c", "user.email=eval@localhost", "commit", "-q",
                    "-m", "task start"], cwd=ws, check=True)
    troot = wsroot / "transcripts" if arm == 4 else None
    settings = ({k: A4[k] for k in ("recall", "transcripts_enabled", "query_policy", "excerpt_renderer",
                                    "addendum")} if arm == 4 else {})
    stack = oc_stack.Stack(out, upstream, settings, passthrough=arm == 1, transcripts=troot)
    session = f"{task.ID}-a{arm}-{a.tag}-a{n_att}"
    home = oc.Home(wsroot / "oc", ws)
    home.write_config(oc.config(stack.base_url(session),
                                context_limit=1_000_000 if arm == 4 else CONTEXT_32K, compaction=arm == 1))
    sdir = None
    if troot is not None:
        from palimnesis.projector import session_dir

        sdir = session_dir(troot, session)
    tools = needle.Tools(ws, troot, sdir, [], None)
    import httpx

    client = httpx.Client(timeout=httpx.Timeout(None, connect=15))
    import needle_opencode as nod

    res = {"task": task.ID, "set": task.SET, "arm": arm, "config": "a4-d43" if arm == 4 else "a1-native",
           "attempt": n_att, "session": session, "runner": RUNNER_VERSION, "opencode": "2.1.4",
           "provenance": gi.git_provenance(), "settings": stack.settings, "passthrough": arm == 1,
           "opencode_limit_context": 1_000_000 if arm == 4 else CONTEXT_32K, "compaction_auto": arm == 1,
           "restart_before": task.RESTART_BEFORE, "key_constraint": task.KEY_CONSTRAINT,
           "upstream": a.upstream, "expect_n_ctx": a.expect_n_ctx, "strata": [{"when": "before", **props}],
           "started": time.time(), "turns": [], "aborted": None}
    ses = None
    try:
        for i, text in enumerate(task.TURNS):
            if stack.tap.abort:
                raise Abort(f"slot_busy: {stack.tap.abort}")
            if i == task.RESTART_BEFORE:
                stack.restart_proxy()
            pre = stack.gate.wait_idle(client, f"task:{task.ID}:{i}")
            before, fbefore = len(stack.tap.calls), len(stack.front.calls)
            t0 = time.time()
            turn = home.run(text, session=ses, label=f"turn{i + 1}", timeout=TURN_TIMEOUT_S)
            stack.settle()
            calls, front = stack.tap.calls[before:], stack.front.calls[fbefore:]
            summ = nod.turn_summary(turn["events"])
            ids = {e.get("sessionID") for e in turn["events"] if e.get("sessionID")}
            if ses is None:
                if not ids:
                    raise Abort(f"no_session: turn 1 produced no session id (exit {turn['exit']}): "
                                f"{turn['stderr'][-300:]}")
                ses = sorted(ids)[0]
            if ids - {ses}:
                raise Abort(f"second_session: turn {i + 1} reported {sorted(ids - {ses})}")
            lookups = sum(int(tools.is_lookup(t["name"] or "", t["input"] if isinstance(t["input"], dict) else {}))
                          for t in summ["tools"])
            firsts = [c for c in calls if c.get("t_first_content")]
            rec = {"turn": i + 1, "restart_before": i == task.RESTART_BEFORE, "exit": turn["exit"],
                   "timeout_killed": bool(turn.get("timeout_killed")), "elapsed_s": turn["elapsed_s"],
                   "driver_wait_s": pre["waited_s"], "upstream_calls": len(calls),
                   "upstream_n": [c["n"] for c in calls], "front_n": [c["n"] for c in front],
                   **oc_stack.call_summary(calls, front),
                   "finishes": [c.get("finish") for c in calls],
                   "prompt_tokens": sum(c.get("prompt_tokens") or 0 for c in calls),
                   "max_prompt_tokens": max((c.get("prompt_tokens") or 0 for c in calls), default=0),
                   "completion_tokens": sum(c.get("completion_tokens") or 0 for c in calls),
                   "cached_tokens": sum(c.get("cached_tokens") or 0 for c in calls),
                   "prompt_ms": sum((c.get("timings") or {}).get("prompt_ms") or 0 for c in calls),
                   "ttfvc_s": round(firsts[0]["t_first_content"] - t0, 3) if firsts else None,
                   "tools": [{"name": t["name"], "status": t["status"], "output_chars": t["output_chars"]}
                             for t in summ["tools"]],
                   "lookups": lookups, "errors": summ["errors"],
                   "answer": (summ["final"] or "")[:400], "stderr": turn["stderr"][-400:] if turn["exit"] else ""}
            res["turns"].append(rec)
            print(f"[{name} a{n_att}] turn {i + 1}: exit={turn['exit']} calls={len(calls)} "
                  f"proxy={rec['proxy_statuses']} max_prompt={rec['max_prompt_tokens']} "
                  f"tools={len(summ['tools'])} lookups={lookups} {turn['elapsed_s']:.0f}s", flush=True)
            (out / "result.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        after = gi.strata_props(upstream)
        res["strata"].append({"when": "after", **after})
        why = gi.check_n_ctx(after, a.expect_n_ctx)
        if why:
            raise Abort(f"strata_check: {why}")
    except (Abort, needle.SlotBusyTooLong) as e:
        res["aborted"] = str(e) if isinstance(e, Abort) else f"slot_busy: {e}"
    finally:
        stack.stop()
    res["finished"] = time.time()
    res["opencode_session"] = ses
    res["proxy_starts"] = stack.proxy.starts
    res["gate_events"] = stack.gate.events
    calls = stack.tap.calls
    res["upstream_calls"] = len(calls)
    res["upstream_errors"] = sum(1 for c in calls if c.get("status") != 200 or c.get("stream_error"))
    res["proxy_rejections"] = sum(t["proxy_rejections"] for t in res["turns"])
    res["prompt_tokens"] = sum(c.get("prompt_tokens") or 0 for c in calls)
    res["completion_tokens"] = sum(c.get("completion_tokens") or 0 for c in calls)
    res["cached_tokens"] = sum(c.get("cached_tokens") or 0 for c in calls)
    res["max_prompt_tokens"] = max((c.get("prompt_tokens") or 0 for c in calls), default=0)
    res["slow_upstream_calls"] = [c["n"] for c in calls if (c.get("upstream_s") or 0) > oc_stack.SLOW_UPSTREAM_S]
    res["lookups"] = sum(t["lookups"] for t in res["turns"])
    res["latency_s"] = round(sum(t["elapsed_s"] for t in res["turns"]), 1)
    res["foreign_between"] = sum(c.get("foreign_between") or 0 for c in calls)
    res["foreign_during"] = sum(max(0, c.get("foreign_during") or 0) for c in calls)
    res["compaction_calls"] = compaction_calls(out / "bodies", calls)
    res["drift"] = drift(out / "bodies", calls)
    logs = "".join(f.read_text(encoding="utf-8", errors="replace") for f in sorted(out.glob("proxy-*.log")))
    res["log_view_disabled"] = logs.count("bounded views disabled")
    res["log_unbounded"] = logs.count("forwarding unbounded")
    export_texts = []
    if ses:
        try:
            exp = home.export(ses)
            (out / "export.json").write_text(json.dumps(exp, ensure_ascii=False), encoding="utf-8")
            export_texts = gi.strings_of(exp)
            kinds: dict[str, int] = {}
            for m in exp.get("messages", []):
                kinds[m.get("type")] = kinds.get(m.get("type"), 0) + 1
            res["opencode_message_types"] = kinds
        except Exception as e:  # recorded, not fatal
            res["opencode_export_error"] = f"{type(e).__name__}: {e}"
    res["reachable_records"] = gi.reachable_records(wsroot, hidden=hidden_markers(task))
    if arm == 4:
        res["over_budget"] = gi.local_over_budget(out / "bodies", calls, gi.input_budget_for(a.expect_n_ctx))
        db = stack.proxy.db
        excerpts = gi.excerpt_texts(db) if db.exists() else []
        res["excerpts_stored"] = len(excerpts)
        res["excerpt_scan"] = {
            "client": gi.scan(excerpts, oc_stack.client_texts(out, stack.front.calls) + export_texts),
            "transcripts": gi.scan(excerpts, gi.transcript_texts(troot))}
        code, report, err = gi.run_explain(db)
        (out / "explain.json").write_text(json.dumps(report) if report else "", encoding="utf-8")
        res["explain_gate"] = gi.explain_gate(code, report, {session: len(calls)} if calls else {})
        res["explain_stderr"] = err
        res["verify"] = needle.verify_sessions(db, [session], troot)[session]
    if res["aborted"]:
        res["check"] = None
        status = 3
    else:
        check_dir = out / "check"
        check_dir.mkdir()
        res["check"] = run_check(task, ws, check_dir)
        res["restart_gate"] = restart_gate(task, res["check"])
        status = 0
    stub_dir = Path(tempfile.mkdtemp(prefix="stub-check-", dir=out))
    stub_ws = stub_dir / "repo"
    materialize(task, stub_ws)
    (stub_dir / "check").mkdir()
    stub = run_check(task, stub_ws, stub_dir / "check")
    res["stub_check"] = {k: stub[k] for k in ("success", "functional_passed", "functional_total",
                                              "constraints", "constraints_held", "constraints_total")}
    (out / "result.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    att.finish_attempt(Path(a.out), n_att, "aborted" if res["aborted"] else "done", aborted=res["aborted"])
    c = res["check"] or {}
    eg = res.get("explain_gate") or {}
    print(f"[{name} a{n_att}] aborted={res['aborted']} success={c.get('success')} "
          f"({c.get('functional_passed')}/{c.get('functional_total')}) "
          f"constraints={c.get('constraints_held')}/{c.get('constraints_total')} "
          f"(stub {res['stub_check']['constraints_held']}/{res['stub_check']['constraints_total']}) "
          f"restart_gate={res.get('restart_gate')} turns={len(res['turns'])} calls={res['upstream_calls']} "
          f"proxy_rejections={res['proxy_rejections']} prompt={res['prompt_tokens']:,} "
          f"max_prompt={res['max_prompt_tokens']} lookups={res['lookups']} latency={res['latency_s']}s "
          f"compaction_calls={len(res['compaction_calls'])} drift={len(res['drift']['nonzero'])} "
          f"explain={eg.get('ok')} verify={(res.get('verify') or {}).get('exit')} "
          f"over_budget={len((res.get('over_budget') or {}).get('over', []))} "
          f"leaks={res.get('excerpt_scan')} slow={len(res['slow_upstream_calls'])} "
          f"reachable={len(res['reachable_records'])} views_disabled={res['log_view_disabled']} "
          f"unbounded={res['log_unbounded']}", flush=True)
    return status


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--task", choices=TASKS)
    p.add_argument("--arm", type=int, choices=[1, 4])
    p.add_argument("--out", help="run directory (attempts.json, records/)")
    p.add_argument("--ws-root", help="workspace tree (default: <out>-ws, beside --out)")
    p.add_argument("--reason", help="why this attempt reruns the task (D44.7)")
    p.add_argument("--expect-n-ctx", type=int, default=32768)
    p.add_argument("--upstream", default="http://192.168.1.173:8080")
    p.add_argument("--tag", default=time.strftime("%m%d%H%M"))
    p.add_argument("--check-reference", action="store_true")
    a = p.parse_args()
    if a.check_reference:
        return check_reference([a.task] if a.task else TASKS)
    if not (a.task and a.arm and a.out):
        p.error("--task, --arm and --out are required")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
