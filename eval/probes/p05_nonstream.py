"""Probe 5 + 11: non-streaming responses on each dialect, and which generation params are honored.

Each case saves fixtures/nonstream_<case>.json with request, status, headers, body and wall time.
Usage: python p05_nonstream.py [case ...]   (default: all cases)
"""

from __future__ import annotations

import sys
import time

from strata_common import MODEL, client, save_json, status

TOOLS_OA = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    },
}]
TOOLS_AN = [{
    "name": "get_weather",
    "description": "Get the current weather for a city.",
    "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
}]
Q = "What is 17 * 23? Reply with just the number."
U = [{"role": "user", "content": Q}]

CASES: dict[str, tuple[str, dict]] = {
    # OpenAI chat completions
    "oa_default_think_low": ("/v1/chat/completions", {"model": MODEL, "messages": U, "max_tokens": 256, "reasoning_effort": "low"}),
    "oa_effort_none": ("/v1/chat/completions", {"model": MODEL, "messages": U, "max_tokens": 64, "reasoning_effort": "none"}),
    "oa_enable_thinking_false": ("/v1/chat/completions", {"model": MODEL, "messages": U, "max_tokens": 64,
                                                          "chat_template_kwargs": {"enable_thinking": False}}),
    "oa_max_tokens_8": ("/v1/chat/completions", {"model": MODEL, "messages": U, "max_tokens": 8, "reasoning_effort": "low"}),
    "oa_max_completion_tokens_8": ("/v1/chat/completions", {"model": MODEL, "messages": U, "max_completion_tokens": 8,
                                                            "reasoning_effort": "low"}),
    "oa_reasoning_format_none": ("/v1/chat/completions", {"model": MODEL, "messages": U, "max_tokens": 256,
                                                          "reasoning_effort": "low", "reasoning_format": "none"}),
    "oa_tool_call": ("/v1/chat/completions", {
        "model": MODEL, "max_tokens": 256, "reasoning_effort": "none", "tools": TOOLS_OA,
        "messages": [{"role": "user", "content": "What's the weather in Paris? Use the tool."}]}),
    "oa_tool_followup": ("/v1/chat/completions", {
        "model": MODEL, "max_tokens": 64, "reasoning_effort": "none", "tools": TOOLS_OA,
        "messages": [
            {"role": "user", "content": "What's the weather in Paris? Use the tool."},
            {"role": "assistant", "content": "", "reasoning_content": "I should call the tool.",
             "tool_calls": [{"id": "call_1", "type": "function",
                             "function": {"name": "get_weather", "arguments": "{\"city\": \"Paris\"}"}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": "Sunny, 20C"},
        ]}),
    # Reasoning carryover on the OpenAI path: compare usage.prompt_tokens with local renders (p02).
    "oa_prior_reasoning": ("/v1/chat/completions", {
        "model": MODEL, "max_tokens": 4, "reasoning_effort": "none",
        "messages": [{"role": "user", "content": "Q1"},
                     {"role": "assistant", "content": "Answer one.",
                      "reasoning_content": "Let me think about this carefully step by step with many words of reasoning here."},
                     {"role": "user", "content": "Reply with the single word OK."}]}),
    "oa_prior_reasoning_preserve_false": ("/v1/chat/completions", {
        "model": MODEL, "max_tokens": 4, "reasoning_effort": "none",
        "chat_template_kwargs": {"preserve_thinking": False},
        "messages": [{"role": "user", "content": "Q1"},
                     {"role": "assistant", "content": "Answer one.",
                      "reasoning_content": "Let me think about this carefully step by step with many words of reasoning here."},
                     {"role": "user", "content": "Reply with the single word OK."}]}),
    "oa_prior_no_reasoning": ("/v1/chat/completions", {
        "model": MODEL, "max_tokens": 4, "reasoning_effort": "none",
        "messages": [{"role": "user", "content": "Q1"},
                     {"role": "assistant", "content": "Answer one."},
                     {"role": "user", "content": "Reply with the single word OK."}]}),
    "oa_unknown_model": ("/v1/chat/completions", {"model": "no-such-model", "messages": U, "max_tokens": 16,
                                                  "reasoning_effort": "none"}),
    # Anthropic messages
    "an_thinking_disabled": ("/v1/messages", {"model": MODEL, "max_tokens": 64, "messages": U,
                                              "thinking": {"type": "disabled"}}),
    "an_effort_low": ("/v1/messages", {"model": MODEL, "max_tokens": 256, "messages": U,
                                       "output_config": {"effort": "low"}}),
    "an_tool_call": ("/v1/messages", {"model": MODEL, "max_tokens": 256, "thinking": {"type": "disabled"},
                                      "tools": TOOLS_AN,
                                      "messages": [{"role": "user", "content": "What's the weather in Paris? Use the tool."}]}),
    # Responses
    "rs_effort_low": ("/v1/responses", {"model": MODEL, "input": Q, "max_output_tokens": 256,
                                        "reasoning": {"effort": "low"}}),
}

# Same requests counted via /v1/messages/count_tokens to compare with usage.
COUNT_EQUIV = {
    "an_thinking_disabled": {"messages": U, "thinking": {"type": "disabled"}},
    "an_effort_low": {"messages": U, "output_config": {"effort": "low"}},
    "an_tool_call": {"messages": [{"role": "user", "content": "What's the weather in Paris? Use the tool."}],
                     "thinking": {"type": "disabled"}, "tools": TOOLS_AN},
}


def run(name: str) -> None:
    path, body = CASES[name]
    pre = status()
    t0 = time.monotonic()
    with client() as c:
        r = c.post(path, json=body)
    dt = time.monotonic() - t0
    try:
        payload = r.json()
    except Exception:
        payload = r.text
    rec = {"case": name, "path": path, "request": body, "status": r.status_code,
           "headers": dict(r.headers), "body": payload, "wall_s": round(dt, 3),
           "server_busy_before": pre.get("busy"), "queued_before": pre.get("queued")}
    if name in COUNT_EQUIV:
        with client(30) as c:
            ct = c.post("/v1/messages/count_tokens", json={"model": MODEL, **COUNT_EQUIV[name]})
        rec["count_tokens"] = ct.json()
    save_json(f"nonstream_{name}.json", rec)
    usage = payload.get("usage") if isinstance(payload, dict) else None
    print(f"{name}: {r.status_code} wall={dt:.1f}s usage={usage} count={rec.get('count_tokens')}")


if __name__ == "__main__":
    for n in (sys.argv[1:] or list(CASES)):
        run(n)
