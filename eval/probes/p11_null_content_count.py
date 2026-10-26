"""Live probe (2 tiny requests, idle-gated): Strata prompt_tokens vs the pinned local count for a
prior assistant turn with reasoning_content and content null vs "" (no tool calls)."""
import json, sys, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
import httpx
from palimnesis.upstreams.strata import tokens
U = "http://192.168.1.19:8080"
c = tokens.default()
def idle():
    while True:
        s = httpx.get(f"{U}/status", timeout=10).json()
        if not s.get("busy") and not s.get("queued"):
            return
        time.sleep(3)
for content in (None, "", "ok"):
    body = {"model": "m", "max_tokens": 1, "stream": False, "messages": [
        {"role": "system", "content": "You are terse."}, {"role": "user", "content": "Say a number."},
        {"role": "assistant", "content": content, "reasoning_content": "The user wants a number. I will think about which number to pick, maybe seven or eight or nine."},
        {"role": "user", "content": "Again."}]}
    local = c.count_messages(**tokens.render_args_from_openai(body))
    idle()
    r = httpx.post(f"{U}/v1/chat/completions", json=body, timeout=120).json()
    print(repr(content), "local", local, "remote", r["usage"]["prompt_tokens"])
