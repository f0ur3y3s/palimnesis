"""Live probe (6 small requests, idle-gated), from the S12 protocol review.

1. Does Strata still render ``tools`` when ``tool_choice`` is ``"none"`` (OpenCode's
   step-limit step)? Compares ``prompt_tokens`` for none / auto / absent against the
   local count, which ignores ``tool_choice``.
2. Which output limit wins when a request carries both ``max_completion_tokens`` and
   ``max_tokens``? Reads ``completion_tokens`` with the two set far apart, both ways.

    uv run python eval/probes/p16_tool_choice_and_output_limits.py [--upstream URL]
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import httpx

from palimnesis.upstreams.strata import tokens

TOOLS = [{"type": "function", "function": {
    "name": "read", "description": "Read a file from the workspace and return its text.",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                   "required": ["path"]}}}]
MESSAGES = [{"role": "system", "content": "You are a coding agent."},
            {"role": "user", "content": "Write a long story about a lighthouse keeper."}]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", default="http://192.168.1.19:8080")
    u = ap.parse_args().upstream.rstrip("/")
    c = tokens.default()

    def idle():
        while True:
            s = httpx.get(f"{u}/status", timeout=10).json()
            if not s.get("busy") and not s.get("queued"):
                return
            time.sleep(2)

    def call(body):
        idle()
        return httpx.post(f"{u}/v1/chat/completions", json=body, timeout=600).json()["usage"]

    out = {"upstream": u, "tool_choice": {}, "output_limits": {}}
    for choice in ("none", "auto", None):
        body = {"model": "m", "stream": False, "max_tokens": 1, "messages": MESSAGES,
                "tools": TOOLS}
        if choice is not None:
            body["tool_choice"] = choice
        local = c.count_messages(**tokens.render_args_from_openai(body))
        remote = call(body)["prompt_tokens"]
        out["tool_choice"][str(choice)] = {"local": local, "remote": remote}
    no_tools = {"model": "m", "stream": False, "max_tokens": 1, "messages": MESSAGES}
    out["tool_choice"]["no tools"] = {
        "local": c.count_messages(**tokens.render_args_from_openai(no_tools)),
        "remote": call(no_tools)["prompt_tokens"]}
    for mct, mt in ((8, 300), (300, 8)):
        body = {"model": "m", "stream": False, "messages": MESSAGES,
                "max_completion_tokens": mct, "max_tokens": mt}
        out["output_limits"][f"max_completion_tokens={mct}, max_tokens={mt}"] = \
            call(body)["completion_tokens"]
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
