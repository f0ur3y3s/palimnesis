"""Probe 17 (Phase 3B, S0 P1): OpenAI Chat tool-call stream shapes on Strata.

Questions (docs/plan/phases/phase3b.md §2.8):
  a. Does the first delta of each tool call carry ``id``, ``type`` and ``function.name``, with
     the arguments arriving after it?
  b. Parallel calls: which indices, and do their deltas ever interleave?
  c. Can content or reasoning arrive AFTER a tool call in the same response (thinking on/off)?
  d. ``max_tokens`` small enough to stop inside the arguments: finish_reason and partial args.
  e. Are keep-alive comments sent between deltas?

Every case runs ``--reps`` times (default 3), strictly sequentially, each gated on /status idle.
Request bodies are synthetic. Writes fixtures/p17_<case>_<rep>.sse (exact bytes) and
fixtures/p17_tool_stream_shapes.json (per-run shape summaries and the aggregate answers).

    uv run python eval/probes/p17_tool_stream_shapes.py [--reps 3] [--only case,case]
"""

from __future__ import annotations

import argparse
import json
import time

from strata_common import (BASE, FIXTURES, MODEL, check_build, oa_shape, save_bytes, save_json, status,
                           stream_post, wait_idle)

TOOLS = [
    {"type": "function", "function": {
        "name": "get_weather", "description": "Get the current weather for a city.",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                       "required": ["city"]}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "Read a text file from the workspace.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                       "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file", "description": "Write a text file to the workspace.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"},
                                                        "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
]
SYS = {"role": "system", "content": "You are a helpful assistant with tools."}

P_SINGLE = "What's the weather in Paris right now? Use the tool."
P_PARALLEL = ("Get the current weather for Paris, Oslo and Lima. Call get_weather once per city, "
              "all three calls in this one response, before any answer.")
P_AFTER_A = ("Call get_weather for Paris. In the same response, AFTER the tool call, write the "
             "sentence 'Request sent, waiting for the result.'")
P_AFTER_B = ("Do these three steps in this exact order within one response: 1) call read_file on "
             "notes/a.txt; 2) write one sentence saying what you expect a.txt to contain; 3) call "
             "read_file on notes/b.txt.")
P_SANDWICH = ("Reply in exactly this order: first the text 'Checking now.', then a get_weather tool "
              "call for Paris, then the text 'Done.' after the call.")
P_BETWEEN = ("In one response: call get_weather for Paris, then write the text 'and now Oslo:', then "
             "call get_weather for Oslo.")
P_LENGTH = ("Use write_file to create poem.txt containing an original 30-line poem about rivers. "
            "Call the tool directly.")


def body(prompt: str, think: bool, max_tokens: int) -> dict:
    return {"model": MODEL, "stream": True, "max_tokens": max_tokens, "tools": TOOLS,
            "reasoning_effort": "low" if think else "none",
            "messages": [SYS, {"role": "user", "content": prompt}]}


CASES: dict[str, dict] = {
    "single_off": body(P_SINGLE, False, 512),
    "single_on": body(P_SINGLE, True, 1024),
    "parallel_off": body(P_PARALLEL, False, 512),
    "parallel_on": body(P_PARALLEL, True, 1024),
    "after_a_off": body(P_AFTER_A, False, 512),
    "after_a_on": body(P_AFTER_A, True, 1024),
    "after_b_off": body(P_AFTER_B, False, 512),
    "after_b_on": body(P_AFTER_B, True, 1024),
    "sandwich_off": body(P_SANDWICH, False, 512),
    "sandwich_on": body(P_SANDWICH, True, 1024),
    "between_off": body(P_BETWEEN, False, 512),
    "between_on": body(P_BETWEEN, True, 1024),
    "length_args_off": body(P_LENGTH, False, 40),
    "length_args_on": body(P_LENGTH, True, 512),
    "length_args_on_160": body(P_LENGTH, True, 160),
}


def describe(run: dict) -> dict:
    events = run["events"]
    shape = oa_shape(events)
    order = shape["order"]
    kinds = [k for k, _ in order]
    tool_pos = [i for i, k in enumerate(kinds) if k.startswith("tool[")]
    first_tool = tool_pos[0] if tool_pos else None
    after_tool = sorted({k for k in kinds[first_tool:] if k in ("content", "reasoning")}) \
        if first_tool is not None else []
    # interleave: a call index reappears after a different index started
    seen, interleaved = [], False
    for k in kinds:
        if k.startswith("tool["):
            if seen and k != seen[-1] and k in seen:
                interleaved = True
            if not seen or seen[-1] != k:
                seen.append(k)
    first_deltas = {}
    for i, tc in shape["first_tool_deltas"].items():
        fn = tc.get("function") or {}
        first_deltas[str(i)] = {"has_id": bool(tc.get("id")), "type": tc.get("type"),
                                "has_name": bool(fn.get("name")),
                                "arguments_in_first": fn.get("arguments")}
    # keep-alive comments: positions relative to data deltas
    data_idx = [i for i, e in enumerate(events) if e["kind"] == "data"]
    comments = [i for i, e in enumerate(events) if e["kind"] == "comment"]
    first_d = data_idx[1] if len(data_idx) > 1 else None  # first delta after the role chunk
    last_d = data_idx[-1] if data_idx else None
    between = [i for i in comments if first_d is not None and first_d < i < last_d]
    calls = []
    for c in shape["calls"]:
        try:
            json.loads(c["arguments"])
            ok = True
        except (json.JSONDecodeError, TypeError):
            ok = False
        calls.append({**c, "arguments_json_ok": ok})
    tool_ts = [e["t"] for e in events if e["kind"] == "data" and any(
        (ch.get("delta") or {}).get("tool_calls") for ch in (e.get("json") or {}).get("choices") or [])]
    data_ts = [e["t"] for e in events if e["kind"] == "data"]
    return {
        "order": order, "finish_reason": shape["finish_reason"], "usage": shape["usage"],
        "content": shape["content"], "reasoning_chars": len(shape["reasoning"]),
        "reasoning_tail": shape["reasoning"][-160:], "calls": calls, "first_tool_deltas": first_deltas,
        "content_or_reasoning_after_first_tool": after_tool, "tool_deltas_interleaved": interleaved,
        "comments_total": len(comments), "comment_event_indices": comments,
        "comments_between_deltas": len(between),
        "tool_delta_time_span_s": (round(tool_ts[-1] - tool_ts[0], 3) if tool_ts else None),
        "n_tool_deltas": len(tool_ts),
        "first_data_after_role_t": data_ts[1] if len(data_ts) > 1 else None,
        "last_data_t": data_ts[-1] if data_ts else None, "elapsed_s": run["elapsed_s"],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    props = check_build()
    only = [c for c in args.only.split(",") if c]
    out = {"upstream": BASE, "build_info": props["build_info"],
           "n_ctx": props["default_generation_settings"].get("n_ctx"),
           "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "tools": TOOLS, "cases": {}}
    slot_s = 0.0
    for name, b in CASES.items():
        if only and name not in only:
            continue
        runs = []
        for rep in range(args.reps):
            wait_idle(quiet=1.0)
            run = stream_post(b)
            slot_s += run["elapsed_s"]
            save_bytes(f"p17_{name}_{rep}.sse", run["raw"])
            d = describe(run)
            runs.append(d)
            print(name, rep, json.dumps({k: d[k] for k in ("order", "finish_reason",
                                                            "content_or_reasoning_after_first_tool",
                                                            "tool_deltas_interleaved",
                                                            "comments_between_deltas")}))
            st = status()
            if st.get("busy"):
                print("  warning: still busy after stream end", st)
        out["cases"][name] = {"request": b, "runs": runs}
    out["slot_seconds"] = round(slot_s, 1)
    out["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path = FIXTURES / "p17_tool_stream_shapes.json"
    if only and path.exists():  # merge a partial re-run into the saved results
        prev = json.loads(path.read_text(encoding="utf-8"))
        prev["cases"].update(out["cases"])
        prev.setdefault("supplementary_runs", []).append(
            {"cases": only, "started": out["started"], "finished": out["finished"],
             "slot_seconds": out["slot_seconds"]})
        out = prev
    save_json(path.name, out)
    print("slot seconds", out["slot_seconds"])


if __name__ == "__main__":
    main()
