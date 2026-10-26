"""Live probe: Strata's message normalization before rendering (R21-A, R21-B).

Strata 0.1.48 (`serve/frontend.py`) drops completed assistant turns with no text, no
image and no tool calls, except the final message (`ChatTemplate.render`, #843). It keeps
tool-call arguments that are not a JSON object as text under "arguments" and maps empty
arguments to {} (`tool_arguments`, #510). This records `usage.prompt_tokens` for each case
(max_tokens 1, idle-gated per D39) into fixtures/strata_normalization.json.

    uv run python eval/probes/p12_strata_normalization.py [--upstream URL]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

OUT = Path(__file__).parent / "fixtures" / "strata_normalization.json"
TOOLS = [{"type": "function", "function": {
    "name": "write", "description": "Write a file.",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"},
                                                     "content": {"type": "string"}}}}}]
REASONING = ("The user wants a number. I will think about which number to pick, "
             "maybe seven or eight or nine.")


def _turn(content, **extra):
    return {"role": "assistant", "content": content, **extra}


def _chat(assistant, *, final=None):
    msgs = [{"role": "system", "content": "You are terse."},
            {"role": "user", "content": "Say a number."}, assistant]
    if final is not False:
        msgs.append(final or {"role": "user", "content": "Again."})
    return msgs


def _call(arguments):
    return _turn(None, tool_calls=[{"id": "call_1", "type": "function",
                                    "function": {"name": "write", "arguments": arguments}}])


def _with_result(arguments):
    return [{"role": "system", "content": "You are terse."},
            {"role": "user", "content": "Save the notes."}, _call(arguments),
            {"role": "tool", "tool_call_id": "call_1", "content": "error: invalid arguments"},
            {"role": "user", "content": "Again."}]


CASES = {
    "empty_turn_null": _chat(_turn(None, reasoning_content=REASONING)),
    "empty_turn_empty_string": _chat(_turn("", reasoning_content=REASONING)),
    "empty_turn_whitespace": _chat(_turn("  \n", reasoning_content=REASONING)),
    "empty_turn_text_parts": _chat(_turn([{"type": "text", "text": ""}],
                                         reasoning_content=REASONING)),
    "nonempty_turn": _chat(_turn("ok", reasoning_content=REASONING)),
    "turn_removed": _chat({"role": "user", "content": "Again."}, final=False),
    "args_truncated": _with_result('{"path":"notes.txt","content":"abc'),
    "args_list": _with_result('[1, 2]'),
    "args_empty": _with_result(""),
    "args_object": _with_result('{"path":"notes.txt"}'),
}


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
    out = {"upstream": a.upstream, "tools": TOOLS, "cases": {}}
    with httpx.Client(base_url=a.upstream) as client:
        out["props_build"] = client.get("/props", timeout=10).json().get("build_info")
        for name, messages in CASES.items():
            body = {"model": "m", "max_tokens": 1, "stream": False, "messages": messages,
                    "tools": TOOLS}
            _idle(client)
            r = client.post("/v1/chat/completions", json=body, timeout=300)
            r.raise_for_status()
            n = r.json()["usage"]["prompt_tokens"]
            out["cases"][name] = {"messages": messages, "prompt_tokens": n}
            print(f"{name:28} {n}")
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
