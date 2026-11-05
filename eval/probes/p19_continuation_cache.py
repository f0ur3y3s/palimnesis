"""Probe 19 (Phase 3B, S0 P3): prompt-cache reuse for a hidden continuation on Strata.

A hidden continuation (docs/plan/phases/phase3b.md §2.7) is call 2 = call 1's messages + the assistant
tool call exactly as generated (reasoning included) + a tool result. Question: does Strata reuse
the tokens it generated in call 1, beyond the generation-start checkpoint that
``palimnesis.upstreams.strata.cache.StrataCacheModel`` assumes?

Per repetition (a fresh nonce in the user message, so call 1 starts cold past the shared head):
  call 1  streaming, thinking on (effort low), answer must be a read_file tool call;
  call 2  same messages + {"role": "assistant", content, reasoning_content, tool_calls} built from
          call 1's stream + {"role": "tool", ...}; streaming, small max_tokens.
Recorded: usage of both calls; /metrics reused and prompt_read; local layouts of both prompts
(tokens.default(), checked against usage.prompt_tokens); StrataCacheModel.expected(layout1,
layout2); the token LCP of the two prompts; the call-2 position where call 1's generated tokens
end (assistant segment end); and cached_tokens of call 2 against all of these.

Variants: short tool result (about 20 tokens), long tool result (about 2,000 tokens), and a
thinking-off short control. Synthetic bodies only. Writes fixtures/p19_<variant>_<rep>_call{1,2}.sse
and fixtures/p19_continuation_cache.json.

    uv run python eval/probes/p19_continuation_cache.py [--reps 3]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from strata_common import (BASE, MODEL, check_build, filler, oa_shape, recent_requests, save_bytes,
                           save_json, status, stream_post, wait_idle)

TOOLS = [{"type": "function", "function": {
    "name": "read_file", "description": "Read a text file from the workspace and return its text.",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                   "required": ["path"]}}}]
SYS = {"role": "system", "content": "You are a careful assistant. Use tools when asked."}
SHORT_RESULT = "The meeting moved to Thursday at 10:00 in room B."


TASK = "then tell me in one sentence what it says."


def first_messages(nonce: str, task: str = TASK) -> list[dict]:
    return [SYS, {"role": "user", "content": f"[{nonce}] Read notes/{nonce}.txt with read_file, {task}"}]


def call1(nonce: str, effort: str, max_tokens: int = 1024, task: str = TASK) -> tuple[dict, dict, dict]:
    """Run call 1; returns (request body, stream run, assembled shape)."""
    body = {"model": MODEL, "stream": True, "max_tokens": max_tokens, "tools": TOOLS,
            "reasoning_effort": effort, "messages": first_messages(nonce, task)}
    wait_idle(quiet=1.0)
    run = stream_post(body)
    return body, run, oa_shape(run["events"])


def assistant_message(shape: dict) -> dict:
    """The assistant turn exactly as generated: content, reasoning and the tool calls."""
    msg = {"role": "assistant", "content": shape["content"],
           "tool_calls": [{"id": c["id"], "type": "function",
                           "function": {"name": c["name"], "arguments": c["arguments"]}}
                          for c in shape["calls"]]}
    if shape["reasoning"]:
        msg["reasoning_content"] = shape["reasoning"]
    return msg


def server_record(usage: dict | None) -> dict | None:
    """The newest /metrics request record with this prompt length (sequential, idle-gated)."""
    for r in recent_requests(4):
        if usage and r.get("prompt_tokens") == usage.get("prompt_tokens"):
            return {k: r.get(k) for k in ("id", "time", "finish", "prompt_tokens", "reused",
                                          "prompt_read", "output_tokens", "engine_generated",
                                          "prompt_ms")}
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    args = ap.parse_args()
    props = check_build()
    from palimnesis.profile import common_prefix
    from palimnesis.upstreams.strata import tokens
    from palimnesis.upstreams.strata.cache import StrataCacheModel
    tok, model = tokens.default(), StrataCacheModel()
    long_result = filler(900, seed=1919)  # about 2,000 tokens
    variants = [("short_on", "low", SHORT_RESULT, args.reps), ("long_on", "low", long_result, args.reps),
                ("short_off", "none", SHORT_RESULT, 2)]
    out = {"upstream": BASE, "build_info": props["build_info"], "tools": TOOLS,
           "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "long_result_tokens": tok.count(long_result), "runs": []}
    slot_s = 0.0
    rng = random.Random()
    for name, effort, result, reps in variants:
        for rep in range(reps):
            for attempt in range(3):
                nonce = f"p19-{rng.randrange(16**6):06x}"
                b1, r1, s1 = call1(nonce, effort)
                slot_s += r1["elapsed_s"]
                if s1["calls"] and s1["finish_reason"] == "tool_calls":
                    break
                print("  call 1 gave no tool call, retrying", s1["finish_reason"])
            rec1 = server_record(s1["usage"])
            save_bytes(f"p19_{name}_{rep}_call1.sse", r1["raw"])
            asst = assistant_message(s1)
            msgs2 = b1["messages"] + [asst] + [
                {"role": "tool", "tool_call_id": c["id"], "content": result} for c in asst["tool_calls"]]
            b2 = {**b1, "messages": msgs2, "max_tokens": 160}
            wait_idle(quiet=1.0)
            r2 = stream_post(b2)
            slot_s += r2["elapsed_s"]
            s2 = oa_shape(r2["events"])
            rec2 = server_record(s2["usage"])
            save_bytes(f"p19_{name}_{rep}_call2.sse", r2["raw"])

            kw = {"effort": effort}
            l1 = tok.layout(b1["messages"], TOOLS, **kw)
            l2 = tok.layout(msgs2, TOOLS, **kw)
            u1, u2 = s1["usage"] or {}, s2["usage"] or {}
            asst_seg = [s for s in l2.segments if s.kind == "assistant"][-1]
            gen_prompt_1 = len(l1.ids) - l1.generation_start
            # Call 1 generated after its full prompt (which ends with the generation prompt);
            # in call 2 those generated tokens are rendered up to the assistant turn's end.
            rendered_generated = asst_seg.end - len(l1.ids)
            cached2 = (u2.get("prompt_tokens_details") or {}).get("cached_tokens")
            run = {
                "variant": name, "rep": rep, "nonce": nonce, "effort": effort,
                "call1": {"usage": u1, "server": rec1, "finish_reason": s1["finish_reason"],
                          "reasoning_chars": len(s1["reasoning"]), "content": s1["content"],
                          "calls": s1["calls"]},
                "call2": {"usage": u2, "server": rec2, "finish_reason": s2["finish_reason"]},
                "local": {
                    "prompt1": len(l1.ids), "prompt2": len(l2.ids),
                    "prompt1_matches_usage": len(l1.ids) == u1.get("prompt_tokens"),
                    "prompt2_matches_usage": len(l2.ids) == u2.get("prompt_tokens"),
                    "generation_start_1": l1.generation_start, "generation_prompt_1_tokens": gen_prompt_1,
                    "lcp_prompt1_prompt2": common_prefix(l1.ids, l2.ids),
                    "assistant_segment_2": [asst_seg.start, asst_seg.end],
                    "rendered_generated_tokens": rendered_generated,
                    "completion_tokens_1": u1.get("completion_tokens"),
                    "generation_start_2": l2.generation_start,
                    "checkpoints_1": list(model.checkpoints(l1)),
                },
                "expected_model": model.expected(l1, l2),
                "cached2": cached2,
                "cached2_minus_expected": None if cached2 is None else cached2 - model.expected(l1, l2),
                "cached2_minus_prompt1": None if cached2 is None else cached2 - len(l1.ids),
                "cached2_vs_assistant_end": None if cached2 is None else cached2 - asst_seg.end,
            }
            out["runs"].append(run)
            print(name, rep, json.dumps({k: run[k] for k in ("expected_model", "cached2",
                                                              "cached2_minus_prompt1",
                                                              "cached2_vs_assistant_end")}),
                  json.dumps({k: run["local"][k] for k in ("prompt1", "prompt2", "prompt1_matches_usage",
                                                           "prompt2_matches_usage",
                                                           "rendered_generated_tokens",
                                                           "completion_tokens_1")}))
            if status().get("busy"):
                print("  warning: still busy after stream end")
    out["slot_seconds"] = round(slot_s, 1)
    out["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_json("p19_continuation_cache.json", out)
    print("slot seconds", out["slot_seconds"])


if __name__ == "__main__":
    main()
