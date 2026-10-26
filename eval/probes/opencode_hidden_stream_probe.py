"""H1 (Phase 3B, S0): what OpenCode 2.1.4 does with the streams a hidden-recall assembler emits.

Palimnesis's assembler (docs/plans/phase3b.md §2.2) can show the client ONE visible response made
of several upstream generations: reasoning, text, then reasoning again, then text, under one
chunk id. It can also end a response with ``finish_reason: "length"`` (caps, §2.4) or with an
in-stream error event mid-continuation. This probe drives real OpenCode 2.1.4 against the
scripted fault server (``opencode_fault_server.py``, ``hs_*`` scenarios; never a model server)
and records, per scenario:

  turn 1   ``opencode run`` with the first question (attempt 1 gets the scenario's stream,
           every later attempt a normal answer);
  turn 2   ``opencode run --session <id>`` with a second question;
  export   ``opencode session export <id>``: what OpenCode stored.

Isolation is ``eval/oc_harness.Home`` (allowlisted environment, ``--standalone``, message on
stdin, private HOME/XDG/config, a fresh git workspace, process tree killed at the timeout).
No plugin is loaded; the provider's baseURL is the fault server's ``/v1``.

Usage:
    uv run python eval/probes/opencode_hidden_stream_probe.py --root SCRATCH/opencode-hidden RUN [RUN ...]
    uv run python eval/probes/opencode_hidden_stream_probe.py --root SCRATCH/opencode-hidden all
    uv run python eval/probes/opencode_hidden_stream_probe.py --list

Output: eval/fixtures/opencode-2.1.4/hidden_stream/<RUN>/ (req-NN.json exact request bodies,
requests.jsonl, events.jsonl, turn{1,2}.json, export.json, meta.json) and
hidden_stream/summary.json (each request's messages after the system prompt).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "eval"))
sys.path.insert(0, str(REPO / "eval" / "probes"))
import oc_harness  # noqa: E402
from opencode_fault_probe import _kill_tree, _wait_http  # noqa: E402

SERVER = REPO / "eval" / "probes" / "opencode_fault_server.py"
FIXTURES = REPO / "eval" / "fixtures" / "opencode-2.1.4" / "hidden_stream"
TURN1 = "First question: what is 2+2?"
TURN2 = "Next question: what is 3+3?"
TIMEOUT_S = 150

RUNS: dict[str, str] = {
    "a_composite_stop": "hs_composite_stop",
    "a2_composite_tool": "hs_composite_tool",
    "a3_text_after_tool": "hs_text_after_tool",
    "b_length_text": "hs_length_text",
    "b2_length_text_noretry": "hs_length_text_noretry",
    "b3_composite_length": "hs_composite_length",
    "c_text_err_noretry": "hs_text_err_noretry",
    "c2_composite_err_noretry": "hs_composite_err_noretry",
}


def _brief(m: dict) -> dict:
    out = {"role": m.get("role")}
    for k in ("content", "reasoning_content", "tool_call_id"):
        if k in m:
            v = m[k]
            if isinstance(v, str) and len(v) > 300:
                v = v[:300] + f"...[{len(v)} chars]"
            out[k] = v
    if m.get("tool_calls"):
        out["tool_calls"] = [{"id": c.get("id"), "name": (c.get("function") or {}).get("name"),
                              "arguments": (c.get("function") or {}).get("arguments")}
                             for c in m["tool_calls"]]
    out["keys"] = list(m.keys())
    return out


def _export_brief(export: dict) -> list[dict]:
    rows = []
    for msg in export.get("messages", []):
        row = {"type": msg.get("type"), "finish": msg.get("finish"), "rawFinish": msg.get("rawFinish")}
        if msg.get("type") == "user":
            row["text"] = msg.get("text")
        parts = []
        for p in msg.get("content") or []:
            t = p.get("type")
            if t in ("reasoning", "text"):
                parts.append({"type": t, "text": p.get("text")})
            elif t == "tool":
                st = p.get("state") or {}
                parts.append({"type": t, "name": p.get("name"), "id": p.get("id"),
                              "status": st.get("status"), "input": st.get("input")})
            else:
                parts.append({"type": t})
        if parts:
            row["parts"] = parts
        if msg.get("error"):
            row["error"] = msg.get("error")
        rows.append(row)
    return rows


def _rmtree(path: Path) -> None:
    """rmtree that also removes read-only files (git objects on Windows)."""
    def onexc(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onexc=onexc)


def run_one(name: str, root: Path, port: int) -> dict:
    scenario = RUNS[name]
    run_root = root / name
    if run_root.exists():
        _rmtree(run_root)
    home = oc_harness.Home(run_root, run_root / "work")
    (run_root / "work" / "notes.txt").write_text("notes: the probe file\n", encoding="utf-8")
    out = FIXTURES / name
    if out.exists():
        _rmtree(out)
    out.mkdir(parents=True)
    origin = f"http://127.0.0.1:{port}"
    log = run_root / "server.jsonl"
    server = subprocess.Popen([sys.executable, str(SERVER), "--scenario", scenario, "--port", str(port),
                               "--log", str(log), "--raw-dir", str(out)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    cfg = oc_harness.config(f"{origin}/v1")
    home.write_config(cfg)
    (out / "opencode.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    turns, session, export, n_turn1 = [], None, None, 0
    try:
        _wait_http(origin + "/health")
        t1 = home.run(TURN1, label="turn1", timeout=TIMEOUT_S)
        turns.append(t1)
        time.sleep(1)
        reqs = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
        reqs = [r for r in reqs if r.get("event") == "request" and r.get("attempt") is not None]
        n_turn1 = len(reqs)
        if reqs:
            session = {k.lower(): v for k, v in reqs[0]["headers"]}.get("x-opencode-session-id")
        if session:
            turns.append(home.run(TURN2, session=session, label="turn2", timeout=TIMEOUT_S))
            time.sleep(1)
            try:
                export = home.export(session)
            except Exception as e:  # noqa: BLE001 - recorded, not fatal
                export = {"export_error": repr(e)}
    finally:
        _kill_tree(server)
    for i, t in enumerate(turns, 1):
        (out / f"turn{i}.json").write_text(json.dumps(t, indent=2, ensure_ascii=False, default=str),
                                           encoding="utf-8")
    if export is not None:
        (out / "export.json").write_text(json.dumps(export, indent=2, ensure_ascii=False),
                                         encoding="utf-8")
    requests = []
    with (out / "requests.jsonl").open("w", encoding="utf-8") as rf, \
            (out / "events.jsonl").open("w", encoding="utf-8") as ef:
        for line in log.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("event") == "request":
                body = r.pop("body", None)
                r["turn"] = 1 if (r.get("attempt") or 0) <= n_turn1 else 2
                rf.write(json.dumps(r, ensure_ascii=False) + "\n")
                if r.get("attempt") is not None and isinstance(body, dict):
                    msgs = body.get("messages") or []
                    requests.append({"attempt": r["attempt"], "turn": r["turn"],
                                     "raw_body_file": r.get("raw_body_file"),
                                     "max_completion_tokens": body.get("max_completion_tokens"),
                                     "messages_after_system": [_brief(m) for m in msgs
                                                               if m.get("role") != "system"]})
            else:
                ef.write(line + "\n")
    meta = {"run": name, "scenario": scenario, "session_id": session, "turn1_requests": n_turn1,
            "turns": [{k: t.get(k) for k in ("label", "exit", "elapsed_s", "timeout_killed")} |
                      {"events": [e.get("type") for e in t.get("events") or []]} for t in turns],
            "prompts": [TURN1, TURN2], "isolated_root": str(run_root)}
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"meta": meta, "requests": requests,
            "export": _export_brief(export) if isinstance(export, dict) and "messages" in export else export}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("runs", nargs="*")
    p.add_argument("--root")
    p.add_argument("--port", type=int, default=18800)
    p.add_argument("--list", action="store_true")
    args = p.parse_args()
    if args.list:
        for k, v in RUNS.items():
            print(k, v)
        return
    names = list(RUNS) if args.runs == ["all"] else args.runs
    root = Path(args.root)
    summary_path = FIXTURES / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    for i, name in enumerate(names):
        res = run_one(name, root, args.port + i)
        summary[name] = res
        print(json.dumps({"run": name, "turn1_requests": res["meta"]["turn1_requests"],
                          "turns": [(t["exit"], t["elapsed_s"]) for t in res["meta"]["turns"]]}), flush=True)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
