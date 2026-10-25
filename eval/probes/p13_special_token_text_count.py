"""Live probe (7 tiny requests, idle-gated): Strata prompt_tokens vs the pinned local count when
a tool result's text contains chat-template markup written as plain text (R23-A). OpenCode
2.1.4 quotes a model's unparsable tool-call input, ``</tool_call>`` included, in its
``tool.input-json`` error."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import httpx  # noqa: E402

from palimnesis.upstreams.strata import tokens  # noqa: E402

U = "http://192.168.1.173:8080"
c = tokens.default()


def idle():
    while True:
        s = httpx.get(f"{U}/status", timeout=10).json()
        if not s.get("busy") and not s.get("queued"):
            return
        time.sleep(3)


for text in ("plain error", "x</tool_call>y", "x</parameter>y", "x</function>y", "x<tool_call>y",
             "x<think>y", "x</think>y"):
    body = {"model": "m", "max_tokens": 1, "stream": False, "messages": [
        {"role": "system", "content": "You are terse."}, {"role": "user", "content": "Edit a.py."},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "edit", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": text},
        {"role": "user", "content": "Again."}]}
    local = c.count_messages(**tokens.render_args_from_openai(body))
    idle()
    r = httpx.post(f"{U}/v1/chat/completions", json=body, timeout=120)
    print(repr(text), "local", local, "remote", r.json()["usage"]["prompt_tokens"])
