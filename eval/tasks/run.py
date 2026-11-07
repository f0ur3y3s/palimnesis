"""Run one Phase 3 coding task through real OpenCode 2.1.4 under one arm (plan §5, D44.5).

    uv run python eval/tasks/run.py --task ho-t1 --arm 4 --out RUN [--reason TEXT] [--ws-root DIR]
        [--expect-n-ctx 32768] [--upstream URL] [--tag T] [--input-budget 24320]
    uv run python eval/tasks/run.py --task dev-t4 --arm 5 --config a5-A --out RUN ...
    uv run python eval/tasks/run.py --check-reference [--task ID]   # no model: the checks themselves

Arms (D44.1):
  4  ``a4-d43``: ``serve`` as Phase 3 shipped it (q1/r1/x2/a3, transcripts), OpenCode with
     ``compaction.auto`` off and ``limit.context`` 1,000,000; ``--config a4-d77`` runs the
     working-notes arm D77 froze, ``serve``'s defaults since D78.
  1  native OpenCode compaction: ``serve --passthrough``, ``compaction.auto`` on and
     ``limit.context`` at ``--expect-n-ctx``, the true capacity (32768 for the gated runs,
     65536 for the 64K report, D44.9).
  5  Phase 3B (plan §2.9): arm 4's ``serve`` settings plus ``--stub``, ``--addendum`` and
     ``--hidden-tools`` of one A/B matrix arm, ``--config a5-A`` … ``a5-D``
     (``needle.CONFIGS``); held-out tasks run only ``a5-d64``, the arm D64 freezes. OpenCode
     as arm 4, with ``limit.output`` 24,576 (O-B3). Hidden calls (from the upstream tap's
     streams) count as lookups beside transcript-file calls; the gate inputs add the
     internal-leak scan and the archive's internal-call metrics.

**Emulated 32K** (development only, O2): ``--input-budget 24320`` with Strata at 65536 gives
the proxy that budget, counts over-budget inputs against it, and sets arm 1's OpenCode
``limit.context`` to the emulated context, the smallest ``n_ctx`` whose default budget it
is (``gate_inputs.emulated_n_ctx``: 24,320 -> 32,768). Held-out tasks refuse it.

Tasks: dev-t1..t5 (development; dev-t4 is the development restart task, dev-t5 a long
agentic turn with mid-task information needs), ho-t1..t5 (the Phase 3 held-out set) and
ho2-t1..t5 (the fresh Phase 3B held-out set, O-B1). A registered task whose module is not
present yet is skipped by ``--check-reference``.

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

**Pi** (``--harness pi [--protocol chat|messages]``, Phase 4B S14, ``pi_task.py``): Pi 1.5.0
in place of OpenCode, development tasks only, arm 4 as ``a4-d77`` (the adapter's
``contextWindow`` 1,000,000, ``compaction.enabled: false``) and arm 1 (``--passthrough``,
``compaction.enabled: true``, ``contextWindow`` at ``--expect-n-ctx``). Each turn is one
``pi --mode json`` run on the task's one Pi session; the restart turn also restarts the
proxy. Records as above with ``harness: "pi"``; Pi's session file stands in for the export
and Pi's compaction events are the compaction calls. ``--upstream fake`` checks the
plumbing against ``tests/fake_upstream.py`` with a scripted model.

    uv run python eval/tasks/run.py --harness pi --task dev-t1 --arm 4 --out RUN-pi ...
"""

from __future__ import annotations

import argparse
import ast
import importlib
import importlib.util
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
import report  # noqa: E402

TASKS = ["dev-t1", "dev-t2", "dev-t3", "dev-t4", "dev-t5",
         "ho-t1", "ho-t2", "ho-t3", "ho-t4", "ho-t5",
         "ho2-t1", "ho2-t2", "ho2-t3", "ho2-t4", "ho2-t5",
         "ho3-t1", "ho3-t2", "ho3-t3", "ho3-t4", "ho3-t5",  # ho3: D77's fresh set
         "ho4-t1", "ho4-t2", "ho4-t3", "ho4-t4", "ho4-t5"]  # ho4: the Phase 7 held-out set
# Runnable but outside the evaluation's task shape (no restart turn, one constraint).
EXTRA_TASKS = ["game-t1"]  # the user's single-prompt game test (2026-11-06)
RUNNER_VERSION = "tasks-run v2"
TURN_TIMEOUT_S = 1800
CHECK_TIMEOUT_S = 300

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


def load_optional(task_id: str):
    """The task's module, or None while it is not present (the ho2 set is written apart)."""
    name = task_id.replace("-", "_")
    if importlib.util.find_spec(name) is None:
        return None
    return importlib.import_module(name)


def available(task_ids: list[str]) -> list[str]:
    return [t for t in task_ids if load_optional(t) is not None]


def task_seed(task_id: str) -> int:
    return sum(ord(c) * 31 ** i for i, c in enumerate(task_id)) % 1_000_003


def materialize(task, ws: Path) -> None:
    rnd = random.Random(task_seed(task.ID))
    ws.mkdir(parents=True, exist_ok=True)  # game-t1 starts from an empty workspace
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


def opencode_context_limit(arm: int, n_ctx: int) -> int:
    """Arms 4 and 5 keep the shipped 1,000,000 (Palimnesis owns the budget); arm 1 compacts
    at the server's real capacity."""
    return n_ctx if arm == 1 else 1_000_000


def opencode_output_limit(arm: int) -> int:
    """OpenCode's ``limit.output``: 24,576 for arm 5 (O-B3), 8,192 otherwise."""
    return needle.output_limit(arm)


RETIRED_SETS = needle.RETIRED_SETS  # judged held-out sets, now development data (D69)


def resolve_arm(arm: int, config: str | None, task_set: str) -> dict:
    """{arm, label, config, cfg} for ``--arm`` and ``--config``. ``label`` names the attempt
    config and the records directory: ``a4`` and ``a1`` as in Phase 3, the configuration
    name for arm 5 and for an arm-4 development variant. Held-out tasks run only the
    frozen arms; a retired set's tasks run any configuration (D69)."""
    held = task_set.startswith("heldout") and task_set not in RETIRED_SETS
    if arm == 1:
        if config is not None:
            raise ValueError("--config applies to arms 4 and 5; arm 1 is native compaction")
        return {"arm": 1, "label": "a1", "config": "a1-native", "cfg": None}
    if arm == 4:
        if config is None or config == "a4-d43":
            return {"arm": 4, "label": "a4", "config": "a4-d43", "cfg": needle.CONFIGS["a4-d43"]}
        if held and config != needle.A4_HELDOUT3:
            raise ValueError(f"held-out tasks run arm 4 only as a4-d43 or "
                             f"{needle.A4_HELDOUT3} (D77), not {config}")
        cfg = needle.config(config)
        if cfg.get("arm") != 4:
            raise ValueError(f"{config} is not a configuration of arm 4")
        return {"arm": 4, "label": config, "config": config, "cfg": cfg}
    if arm != 5:
        raise ValueError(f"no arm {arm}")
    if config is None:
        raise ValueError("arm 5 needs --config: a matrix arm (a5-A ... a5-D, a5-Cp, a5-Dp), "
                         "or a5-d64, the arm D64 froze")
    if held and config != needle.A5_HELDOUT:
        raise ValueError(f"held-out tasks run arm 5 only as {needle.A5_HELDOUT}, not {config}")
    cfg = needle.config(config)
    if cfg.get("arm") != 5:
        raise ValueError(f"{config} is not an arm-5 configuration")
    return {"arm": 5, "label": config, "config": config, "cfg": cfg}


def arm_fields(arm: dict, n_ctx: int, input_budget: int | None = None) -> dict:
    """The arm's configuration as ``result.json`` records it. With an emulated
    ``input_budget`` (O2), arm 1 compacts at the emulated context."""
    emulated = gi.emulated_n_ctx(input_budget, n_ctx) if input_budget is not None else None
    return {"arm": arm["arm"], "config": arm["config"],
            "frozen_as": needle.A5_FROZEN if arm["config"] == needle.A5_HELDOUT else None,
            "config_settings": arm["cfg"], "passthrough": arm["arm"] == 1,
            "input_budget": input_budget, "emulated_n_ctx": emulated,
            "opencode_limit_context": opencode_context_limit(arm["arm"], emulated or n_ctx),
            "opencode_limit_output": opencode_output_limit(arm["arm"]),
            "compaction_auto": arm["arm"] == 1}


def restart_gate(task, check: dict) -> bool | None:
    """D45.8: the restart task passes under arm 4 only with success and its key constraint."""
    if not task.KEY_CONSTRAINT:
        return None
    return bool(check.get("success") and check.get("constraints", {}).get(task.KEY_CONSTRAINT))


def check_reference(task_ids: list[str]) -> int:
    """No model: the hidden check passes on ``REFERENCE`` and fails on the stub."""
    bad = 0
    for tid in task_ids:
        task = load_optional(tid)
        if task is None:
            print(f"{tid}: not present, skipped")
            continue
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
    try:
        info = resolve_arm(a.arm, a.config, task.SET)
    except ValueError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    arm, label = info["arm"], info["label"]
    name = f"{task.ID}-{label}"
    if task.SET.startswith("heldout") and a.input_budget is not None:
        print("refused: held-out tasks run at the real context, never an emulated --input-budget (O2)",
              file=sys.stderr)
        return 2
    try:
        fields = arm_fields(info, a.expect_n_ctx, a.input_budget)
    except ValueError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    if task.SET.startswith("heldout"):
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
    attempt = att.new_attempt(Path(a.out), kind="task", config=label, ids=[task.ID], reason=a.reason,
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
    troot = wsroot / "transcripts" if arm != 1 else None
    settings = needle.proxy_settings(info["cfg"]) if arm != 1 else {}
    stack = oc_stack.Stack(out, upstream, settings, passthrough=arm == 1, transcripts=troot,
                           input_budget=a.input_budget)
    session = f"{task.ID}-{label}-{a.tag}-a{n_att}"
    home = oc.Home(wsroot / "oc", ws)
    home.write_config(oc.config(stack.base_url(session),
                                context_limit=fields["opencode_limit_context"], compaction=arm == 1,
                                output_limit=opencode_output_limit(arm)))
    sdir = None
    if troot is not None:
        from palimnesis.transcripts.projector import session_dir

        sdir = session_dir(troot, session)
    tools = needle.Tools(ws, troot, sdir, [], None)
    import httpx

    client = httpx.Client(timeout=httpx.Timeout(None, connect=15))
    import needle_opencode as nod

    res = {"task": task.ID, "set": task.SET, **fields,
           "attempt": n_att, "session": session, "runner": RUNNER_VERSION, "opencode": "2.1.4",
           "provenance": gi.git_provenance(), "settings": stack.settings,
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
            hidden = needle.hidden_by_tool(calls)
            lookups = sum(int(tools.is_lookup(t["name"] or "", t["input"] if isinstance(t["input"], dict) else {}))
                          for t in summ["tools"]) + sum(hidden.values())
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
                   "lookups": lookups, "hidden_calls": hidden, "errors": summ["errors"],
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
    res["upstream_errors"] = len(oc_stack.failed(calls))
    res["proxy_rejections"] = sum(t["proxy_rejections"] for t in res["turns"])
    res["prompt_tokens"] = sum(c.get("prompt_tokens") or 0 for c in calls)
    res["completion_tokens"] = sum(c.get("completion_tokens") or 0 for c in calls)
    res["cached_tokens"] = sum(c.get("cached_tokens") or 0 for c in calls)
    res["max_prompt_tokens"] = max((c.get("prompt_tokens") or 0 for c in calls), default=0)
    res["slow_upstream_calls"] = [c["n"] for c in calls if (c.get("upstream_s") or 0) > oc_stack.SLOW_UPSTREAM_S]
    res["lookups"] = sum(t["lookups"] for t in res["turns"])
    res["hidden_calls"] = needle.hidden_by_tool(calls)
    res["latency_s"] = round(sum(t["elapsed_s"] for t in res["turns"]), 1)
    res["foreign_between"] = sum(c.get("foreign_between") or 0 for c in calls)
    res["foreign_during"] = sum(max(0, c.get("foreign_during") or 0) for c in calls)
    res["compaction_calls"] = compaction_calls(out / "bodies", calls)
    res["drift"] = drift(out / "bodies", calls)
    logs = "".join(f.read_text(encoding="utf-8", errors="replace") for f in sorted(out.glob("proxy-*.log")))
    res["log_view_disabled"] = logs.count("bounded views disabled")
    res["log_unbounded"] = logs.count("forwarding unbounded")
    export_texts, exports = [], {}
    if ses:
        try:
            exp = home.export(ses)
            (out / "export.json").write_text(json.dumps(exp, ensure_ascii=False), encoding="utf-8")
            export_texts = gi.strings_of(exp)
            exports = {session: exp}
            kinds: dict[str, int] = {}
            for m in exp.get("messages", []):
                kinds[m.get("type")] = kinds.get(m.get("type"), 0) + 1
            res["opencode_message_types"] = kinds
        except Exception as e:  # recorded, not fatal
            res["opencode_export_error"] = f"{type(e).__name__}: {e}"
    res["reachable_records"] = gi.reachable_records(wsroot, hidden=hidden_markers(task))
    if arm != 1:
        res["over_budget"] = gi.local_over_budget(out / "bodies", calls,
                                                  gi.run_budget(a.expect_n_ctx, a.input_budget))
        db = stack.proxy.db
        excerpts = gi.excerpt_texts(db) if db.exists() else []
        res["excerpts_stored"] = len(excerpts)
        client = oc_stack.client_texts(out, stack.front.calls) + export_texts
        res["excerpt_scan"] = {"client": gi.scan(excerpts, client),
                               "transcripts": gi.scan(excerpts, gi.transcript_texts(troot))}
        if db.exists():
            res["internal_scan"] = gi.internal_scan(db, out, stack.front.calls, exports, sessions=[session])
            res["internal"] = report.internal_metrics(db, sessions=[session])
        code, explained, err = gi.run_explain(db)
        (out / "explain.json").write_text(json.dumps(explained) if explained else "", encoding="utf-8")
        res["explain_gate"] = gi.explain_gate(code, explained, {session: len(calls)} if calls else {})
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
          f"unbounded={res['log_unbounded']} internal_leaks={(res.get('internal_scan') or {}).get('hard')} "
          f"mentions={(res.get('internal_scan') or {}).get('mentions')} "
          f"hidden_calls={res['hidden_calls']}", flush=True)
    return status


def run_pi(a) -> int:
    """``--harness pi``: one task under arm 4 or arm 1 through real Pi (``pi_task``)."""
    import contextlib

    import pi_task

    task = load(a.task)
    problems = pi_task.refusals(task.SET, a.arm, a.config, a.protocol, a.upstream)
    if a.pi_keep_recent_tokens is not None and a.arm != 1:
        problems.append("--pi-keep-recent-tokens applies to arm 1 (Pi's own compaction)")
    info = fields = None
    if not problems:
        info = pi_task.resolve_arm(a.arm)
        try:
            fields = pi_task.arm_fields(info, a.expect_n_ctx, a.input_budget, a.pi_keep_recent_tokens)
        except ValueError as e:
            problems.append(str(e))
    if problems:
        for why in problems:
            print(f"refused: {why}", file=sys.stderr)
        return 2
    with contextlib.ExitStack() as es:
        fake = None
        if a.upstream == "fake":
            sys.path.insert(0, str(ROOT))
            from tests.fake_upstream import FakeUpstream
            from tests.servers import serve

            fake = FakeUpstream(props_n_ctx=a.expect_n_ctx)
            upstream = es.enter_context(serve(fake.app()))
        else:
            upstream = a.upstream.rstrip("/")
        return _run_pi(a, task, info, fields, upstream, fake)


def _run_pi(a, task, info, fields, upstream, fake) -> int:
    import httpx
    import pi_harness as pih
    import pi_task

    arm, label = info["arm"], info["label"]
    name = f"{task.ID}-{label}"
    props = gi.strata_props(upstream)
    why = gi.check_n_ctx(props, a.expect_n_ctx)
    if why:
        print(f"refused: {why}", file=sys.stderr)
        return 2
    attempt = att.new_attempt(Path(a.out), kind="task", config=label, ids=[task.ID], reason=a.reason,
                              ws_root=Path(a.ws_root) if a.ws_root else None,
                              extra={"tag": a.tag, "harness": "pi", "protocol": a.protocol})
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
    troot = wsroot / "transcripts" if arm != 1 else None
    settings = needle.proxy_settings(info["cfg"]) if arm != 1 else {}
    stack = pi_task.Stack(out, upstream, settings, passthrough=arm == 1, gated=fake is None,
                          transcripts=troot, input_budget=a.input_budget)
    session = pi_task.session_name(task.ID, label, a.tag, n_att)
    home = pih.PiHome(wsroot / "pi", ws, stack.origin, a.protocol, tools=pi_task.TOOLS,
                      context_window=fields["pi_context_window"], compaction=fields["pi_compaction"])
    sfile = pih.new_session_file(home.root / "sessions" / f"{session}.jsonl", session, str(ws))
    sdir = None
    if troot is not None:
        from palimnesis.transcripts.projector import session_dir

        sdir = session_dir(troot, session)
    tools = needle.Tools(ws, troot, sdir, [], None)
    client = httpx.Client(timeout=httpx.Timeout(None, connect=15))
    fake_model = pi_task.FakeTaskModel(fake) if fake is not None else None
    res = {"task": task.ID, "set": task.SET, **fields, "harness": "pi", "protocol": a.protocol,
           "attempt": n_att, "session": session, "runner": RUNNER_VERSION, "pi": pi_task.PI_VERSION,
           "pi_cli": str(pih.PI_CLI), "pi_tools": pi_task.TOOLS, "pi_models": home.models,
           "pi_settings": home.settings, "live": fake is None,
           "provenance": gi.git_provenance(), "settings": stack.settings,
           "restart_before": task.RESTART_BEFORE, "key_constraint": task.KEY_CONSTRAINT,
           "upstream": a.upstream, "expect_n_ctx": a.expect_n_ctx, "strata": [{"when": "before", **props}],
           "started": time.time(), "turns": [], "aborted": None}
    try:
        for i, text in enumerate(task.TURNS):
            if stack.tap.abort:
                raise Abort(f"slot_busy: {stack.tap.abort}")
            if i == task.RESTART_BEFORE:
                stack.restart_proxy()
            if fake_model is not None:
                fake_model.script_turn(pi_task.fake_replies(task, i, sdir))
            pre = stack.gate.wait_idle(client, f"task:{task.ID}:{i}")
            before, fbefore = len(stack.tap.calls), len(stack.front.calls)
            t0 = time.time()
            turn = home.run(text, sfile, label=f"turn{i + 1}", timeout=TURN_TIMEOUT_S)
            stack.settle()
            calls, front = stack.tap.calls[before:], stack.front.calls[fbefore:]
            summ = pih.turn_summary(turn["events"])
            comps = pih.compaction_events(turn["events"])
            entries = pih.read_session(sfile)
            if (entries[0].get("id") if entries else None) != session:
                raise Abort(f"second_session: turn {i + 1} left the session file without its header id")
            if i == 0 and (not front or len(entries) < 2):
                raise Abort(f"no_session: turn 1 reached the proxy {len(front)} times and left "
                            f"{len(entries)} session entries (exit {turn['exit']}): {turn['stderr'][-300:]}")
            hidden = needle.hidden_by_tool(calls)
            lookups = sum(int(tools.is_lookup(t["name"] or "", t["input"] if isinstance(t["input"], dict) else {}))
                          for t in summ["tools"]) + sum(hidden.values())
            firsts = [c for c in calls if c.get("t_first_content")]
            faithful = None
            if front:
                body = json.loads((out / "front" / f"{front[0]['n']:04d}.json").read_bytes())
                faithful = pih.last_user_text(body) == text
            errors = list(summ["errors"])
            if turn.get("timeout_killed"):
                errors.append(f"pi killed at {TURN_TIMEOUT_S}s")
            if not summ["settled"]:
                # Judged by the events, not the exit code (HP7: Windows exit 0xC0000409 after work).
                errors.append(f"pi did not settle (exit {turn['exit']}): {turn['stderr'][-300:]}")
            rec = {"turn": i + 1, "restart_before": i == task.RESTART_BEFORE, "exit": turn["exit"],
                   "settled": summ["settled"], "stops": summ["stops"], "pi_retries": summ["retries"],
                   "prompt_faithful": faithful, "compactions": comps,
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
                   "tools": pi_task.tool_rows(summ["tools"]),
                   "lookups": lookups, "hidden_calls": hidden, "errors": errors,
                   "answer": (summ["final"] or "")[:400],
                   "stderr": turn["stderr"][-400:] if not summ["settled"] else ""}
            res["turns"].append(rec)
            print(f"[{name} pi-{a.protocol} a{n_att}] turn {i + 1}: settled={summ['settled']} exit={turn['exit']} "
                  f"calls={len(calls)} proxy={rec['proxy_statuses']} max_prompt={rec['max_prompt_tokens']} "
                  f"tools={len(summ['tools'])} lookups={lookups} compactions={len(comps)} "
                  f"{turn['elapsed_s']:.0f}s", flush=True)
            (out / "result.json").write_text(json.dumps(res, indent=1), encoding="utf-8", newline="\n")
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
    res["pi_session"] = session
    res["proxy_starts"] = stack.proxy.starts
    res["gate_events"] = stack.gate.events
    if fake_model is not None:
        res["fake_notes_replies"] = fake_model.notes
    calls = stack.tap.calls
    res["upstream_calls"] = len(calls)
    res["upstream_errors"] = len(oc_stack.failed(calls))
    res["proxy_rejections"] = sum(t["proxy_rejections"] for t in res["turns"])
    res["prompt_tokens"] = sum(c.get("prompt_tokens") or 0 for c in calls)
    res["completion_tokens"] = sum(c.get("completion_tokens") or 0 for c in calls)
    res["cached_tokens"] = sum(c.get("cached_tokens") or 0 for c in calls)
    res["max_prompt_tokens"] = max((c.get("prompt_tokens") or 0 for c in calls), default=0)
    res["slow_upstream_calls"] = [c["n"] for c in calls if (c.get("upstream_s") or 0) > oc_stack.SLOW_UPSTREAM_S]
    res["lookups"] = sum(t["lookups"] for t in res["turns"])
    res["hidden_calls"] = needle.hidden_by_tool(calls)
    res["latency_s"] = round(sum(t["elapsed_s"] for t in res["turns"]), 1)
    res["foreign_between"] = sum(c.get("foreign_between") or 0 for c in calls)
    res["foreign_during"] = sum(max(0, c.get("foreign_during") or 0) for c in calls)
    # Pi's own compactions (its events), one entry each; the summarizer requests beside them.
    res["compaction_calls"] = [{"turn": t["turn"], **c} for t in res["turns"] for c in t["compactions"]]
    res["compaction_upstream_calls"] = pi_task.upstream_compactions(out / "bodies", calls)
    chat = pi_task.chat_calls(calls)
    try:
        res["drift"] = drift(out / "bodies", chat)
    except Exception as e:  # recorded, not fatal
        res["drift"] = {"calls": 0, "nonzero": [], "error": f"{type(e).__name__}: {e}"}
    res["drift"]["skipped_not_chat"] = len(calls) - len(chat)
    logs = "".join(f.read_text(encoding="utf-8", errors="replace") for f in sorted(out.glob("proxy-*.log")))
    res["log_view_disabled"] = logs.count("bounded views disabled")
    res["log_unbounded"] = logs.count("forwarding unbounded")
    export_texts, exports = [], {}
    try:
        entries = pih.read_session(sfile)
        (out / "pi-session.jsonl").write_bytes(sfile.read_bytes())
        exp = pih.as_export(entries)
        (out / "export.json").write_text(json.dumps(exp, ensure_ascii=False), encoding="utf-8", newline="\n")
        export_texts = gi.strings_of(exp)
        exports = {session: exp}
        kinds: dict[str, int] = {}
        for e in entries:
            k = (e.get("message") or {}).get("role") if e.get("type") == "message" else e.get("type")
            kinds[k] = kinds.get(k, 0) + 1
        res["pi_entry_types"] = kinds
    except Exception as e:  # recorded, not fatal
        res["pi_export_error"] = f"{type(e).__name__}: {e}"
    res["reachable_records"] = gi.reachable_records(wsroot, hidden=hidden_markers(task))
    if arm != 1:
        res["over_budget"] = gi.local_over_budget(out / "bodies", calls,
                                                  gi.run_budget(a.expect_n_ctx, a.input_budget))
        db = stack.proxy.db
        excerpts = gi.excerpt_texts(db) if db.exists() else []
        res["excerpts_stored"] = len(excerpts)
        client_t = oc_stack.client_texts(out, stack.front.calls) + export_texts
        res["excerpt_scan"] = {"client": gi.scan(excerpts, client_t),
                               "transcripts": gi.scan(excerpts, gi.transcript_texts(troot))}
        if db.exists():
            res["internal_scan"] = gi.internal_scan(db, out, stack.front.calls, exports, sessions=[session])
            res["internal"] = report.internal_metrics(db, sessions=[session])
        code, explained, err = gi.run_explain(db)
        (out / "explain.json").write_text(json.dumps(explained) if explained else "", encoding="utf-8")
        res["explain_gate"] = gi.explain_gate(code, explained, {session: len(calls)} if calls else {})
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
    (out / "result.json").write_text(json.dumps(res, indent=1), encoding="utf-8", newline="\n")
    att.finish_attempt(Path(a.out), n_att, "aborted" if res["aborted"] else "done", aborted=res["aborted"])
    c = res["check"] or {}
    eg = res.get("explain_gate") or {}
    print(f"[{name} pi-{a.protocol} a{n_att}] aborted={res['aborted']} success={c.get('success')} "
          f"({c.get('functional_passed')}/{c.get('functional_total')}) "
          f"constraints={c.get('constraints_held')}/{c.get('constraints_total')} "
          f"(stub {res['stub_check']['constraints_held']}/{res['stub_check']['constraints_total']}) "
          f"restart_gate={res.get('restart_gate')} turns={len(res['turns'])} calls={res['upstream_calls']} "
          f"proxy_rejections={res['proxy_rejections']} prompt={res['prompt_tokens']:,} "
          f"max_prompt={res['max_prompt_tokens']} lookups={res['lookups']} latency={res['latency_s']}s "
          f"compactions={len(res['compaction_calls'])} (summarizer calls {res['compaction_upstream_calls']}) "
          f"drift={len(res['drift']['nonzero'])} explain={eg.get('ok')} "
          f"verify={(res.get('verify') or {}).get('exit')} "
          f"over_budget={len((res.get('over_budget') or {}).get('over', []))} "
          f"leaks={res.get('excerpt_scan')} slow={len(res['slow_upstream_calls'])} "
          f"reachable={len(res['reachable_records'])} views_disabled={res['log_view_disabled']} "
          f"unbounded={res['log_unbounded']}", flush=True)
    return status


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--harness", choices=["opencode", "pi"], default="opencode")
    p.add_argument("--protocol", choices=["chat", "messages"], default="chat",
                   help="Pi only: the adapter's provider (OpenCode runs Chat)")
    p.add_argument("--pi-keep-recent-tokens", type=int,
                   help="Pi arm 1 only: compaction.keepRecentTokens (default: Pi's own, or a quarter of a window too small for it, D99)")
    p.add_argument("--task", choices=TASKS + EXTRA_TASKS)
    p.add_argument("--arm", type=int, choices=[1, 4, 5])
    p.add_argument("--config", choices=[c for c in needle.config_names() if c.startswith(("a4-", "a5-"))],
                   help="arm 5 only: a matrix arm, or a5-d64 (a5-Dp, frozen by D64)")
    p.add_argument("--out", help="run directory (attempts.json, records/)")
    p.add_argument("--ws-root", help="workspace tree (default: <out>-ws, beside --out)")
    p.add_argument("--reason", help="why this attempt reruns the task (D44.7)")
    p.add_argument("--expect-n-ctx", type=int, default=32768)
    p.add_argument("--input-budget", type=int,
                   help="development only (O2): emulate a smaller context, e.g. 24320 at 65536")
    p.add_argument("--upstream", default="http://127.0.0.1:8080")
    p.add_argument("--tag", default=time.strftime("%m%d%H%M"))
    p.add_argument("--check-reference", action="store_true")
    a = p.parse_args()
    if a.check_reference:
        return check_reference([a.task] if a.task else TASKS)
    if not (a.task and a.arm and a.out):
        p.error("--task, --arm and --out are required")
    if a.harness == "pi":
        return run_pi(a)
    if a.protocol != "chat" or a.pi_keep_recent_tokens is not None or a.upstream == "fake":
        p.error("--protocol messages, --pi-keep-recent-tokens and --upstream fake apply to --harness pi")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
