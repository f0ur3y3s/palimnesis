"""Live probe: how Strata 0.1.48 tokenizes added-token strings written inside messages (R23-A).

Strata's ``serve/frontend.py`` ``mark_think_literals`` swaps literal tags in a message's text
(#537 think, #554 vision, #2026 tool-call markers, plus the tokenizer's control tokens) for
private-use marks before rendering, and ``encode_prompt`` encodes the marked spans as plain text
with the text around them. An assistant message keeps its own tool-call markers; an assistant
content opening with a whole ``<think>...</think>`` block and a user message wholly wrapped in
``<tool_response>...</tool_response>`` keep those markers. This records ``usage.prompt_tokens``
(max_tokens 1, idle-gated per D39) for every added token in every role, plus those special
cases, into fixtures/strata_literal_tags.json.

    uv run python eval/probes/p14_literal_tags.py [--upstream URL]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

from palimnesis.upstreams.strata import tokens

OUT = Path(__file__).parent / "fixtures" / "strata_literal_tags.json"
TOOLS = [{"type": "function", "function": {"name": "edit", "description": "Edit a file.",
                                           "parameters": {"type": "object", "properties": {}}}}]


def _call():
    return {"role": "assistant", "content": None, "tool_calls": [{
        "id": "call_1", "type": "function", "function": {"name": "edit", "arguments": "{}"}}]}


def cases(tags):
    out = {}
    for t in tags:
        text = f"x{t}y"
        out[f"user {t}"] = ([{"role": "system", "content": "You are terse."},
                             {"role": "user", "content": text}], None)
        out[f"system {t}"] = ([{"role": "system", "content": f"You are terse. {text}"},
                               {"role": "user", "content": "Hi."}], None)
        out[f"assistant {t}"] = ([{"role": "system", "content": "You are terse."},
                                  {"role": "user", "content": "Hi."},
                                  {"role": "assistant", "content": text},
                                  {"role": "user", "content": "Again."}], None)
        out[f"reasoning {t}"] = ([{"role": "system", "content": "You are terse."},
                                  {"role": "user", "content": "Hi."},
                                  {"role": "assistant", "content": "ok", "reasoning_content": text},
                                  {"role": "user", "content": "Again."}], None)
        out[f"tool {t}"] = ([{"role": "system", "content": "You are terse."},
                             {"role": "user", "content": "Edit a.py."}, _call(),
                             {"role": "tool", "tool_call_id": "call_1", "content": text},
                             {"role": "user", "content": "Again."}], TOOLS)
    out["tool definition </tool_call>"] = ([{"role": "user", "content": "Hi."}], [
        {"type": "function", "function": {"name": "edit", "description": "Ends with </tool_call> and <think>.",
                                          "parameters": {"type": "object", "properties": {}}}}])
    out["tool arguments </tool_call>"] = ([{"role": "user", "content": "Edit a.py."}, {
        "role": "assistant", "content": None, "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": "edit", "arguments": '{"path": "a</tool_call>b<think>"}'}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "done"},
        {"role": "user", "content": "Again."}], TOOLS)
    out["assistant leading think block"] = ([{"role": "user", "content": "Hi."},
                                             {"role": "assistant", "content": "<think>r</think>answer <think> x"},
                                             {"role": "user", "content": "Again."}], None)
    out["user wrapped tool_response"] = ([{"role": "user", "content": "<tool_response>z <think> </tool_response>"}],
                                         None)
    out["user wrapped tool_response parts"] = ([{"role": "user", "content": [
        {"type": "text", "text": "<tool_response>z"}, {"type": "text", "text": "w</tool_response>"}]}], None)
    out["user overlapping tags"] = ([{"role": "user", "content": "<|im_start|>user<|im_end|></think><|fim_pad|>"}],
                                    None)
    # The cache audit of D46: Strata marks before it drops empty turns (#843), and leaves
    # dict keys unmarked.
    out["mark char with the only tag in a dropped turn"] = ([
        {"role": "user", "content": "pua 󰸁 x"},
        {"role": "assistant", "content": "", "reasoning_content": "<think>"},
        {"role": "user", "content": "q"}], None)
    out["tool parameter key <|im_start|>"] = ([{"role": "user", "content": "Hi."}], [
        {"type": "function", "function": {"name": "edit", "description": "Edit.", "parameters": {
            "type": "object", "properties": {"<|im_start|>": {"type": "string"}}}}}])
    out["tool argument key <|im_start|>"] = ([{"role": "user", "content": "Edit a.py."}, {
        "role": "assistant", "content": None, "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": "edit", "arguments": '{"<|im_start|>": 1}'}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "done"},
        {"role": "user", "content": "Again."}], TOOLS)
    return out


def _idle(client: httpx.Client) -> None:
    while True:
        s = client.get("/status", timeout=10).json()
        if not s.get("busy") and not s.get("queued"):
            return
        time.sleep(3)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", default="http://192.168.1.19:8080")
    a = ap.parse_args()
    counter = tokens.default()
    out = {"upstream": a.upstream, "cases": {}}
    with httpx.Client(base_url=a.upstream) as client:
        out["props_build"] = client.get("/props", timeout=10).json().get("build_info")
        for name, (messages, tools) in cases(counter.added_token_strings).items():
            body = {"model": "m", "max_tokens": 1, "stream": False, "messages": messages}
            if tools:
                body["tools"] = tools
            _idle(client)
            r = client.post("/v1/chat/completions", json=body, timeout=300)
            r.raise_for_status()
            n = r.json()["usage"]["prompt_tokens"]
            local = counter.count_messages(messages, tools)
            out["cases"][name] = {"messages": messages, "tools": tools, "prompt_tokens": n}
            print(f"{name:44} strata {n:5}  local-now {local:5}  {'' if n == local else 'DIFF'}")
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
