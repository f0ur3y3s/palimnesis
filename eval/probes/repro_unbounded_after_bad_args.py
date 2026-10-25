"""Repro: a generated tool call with non-object JSON arguments makes later view builds fail,
and the proxy then forwards the client's unbounded body upstream (over the input budget)."""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
import httpx
from tests.fake_upstream import FakeUpstream
from tests.servers import serve
from palimnesis.api import create_app
from palimnesis.config import Settings
from palimnesis.upstreams.strata import tokens

def sse(*chunks):
    return b"".join(b"data: " + json.dumps({"choices": [c]}).encode() + b"\n\n" for c in chunks) + b"data: [DONE]\n\n"

count = lambda raw: tokens.default().count_messages(**tokens.render_args_from_openai(json.loads(raw)))
tools = [{"type": "function", "function": {"name": "write", "description": "w", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}}}]
hist = [{"role": "system", "content": "You are a coding agent."}]
for i in range(30):
    hist += [{"role": "user", "content": f"step {i}: " + ("lorem ipsum dolor sit amet " * 120)},
             {"role": "assistant", "content": f"done {i}"}]
hist.append({"role": "user", "content": "save the notes"})
with tempfile.TemporaryDirectory() as d:
    fake = FakeUpstream()
    with serve(fake.app()) as up:
        s = Settings(upstream_base_url=up, db_path=Path(d) / "a.db", input_budget=12000, transcripts_enabled=False)
        with serve(create_app(s), palimnesis=True) as px:
            url = f"{px}/s/repro1/v1/chat/completions"
            bad_args = '{"path":"notes.txt","content":"abc'  # truncated by finish_reason length
            fake.respond_sse([sse({"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "write", "arguments": bad_args}}]}},
                                  {"index": 0, "delta": {}, "finish_reason": "length"})])
            r = httpx.post(url, content=json.dumps({"model": "m", "messages": hist, "tools": tools, "stream": True}), timeout=60)
            print("request 1", r.status_code, "upstream tokens", count(fake.requests[-1].body))
            hist2 = hist + [{"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "write", "arguments": bad_args}}]},
                            {"role": "tool", "tool_call_id": "call_1", "content": "error: invalid arguments"}]
            fake.respond_sse([sse({"index": 0, "delta": {"content": "ok"}}, {"index": 0, "delta": {}, "finish_reason": "stop"})])
            r = httpx.post(url, content=json.dumps({"model": "m", "messages": hist2, "tools": tools, "stream": True}), timeout=60)
            body = fake.requests[-1].body
            try:
                n = count(body)
            except Exception as e:
                n = f"uncountable ({type(e).__name__}); messages={len(json.loads(body)['messages'])}, bytes={len(body)}"
            print("request 2", r.status_code, "upstream body:", n, "(input budget 12000; client messages", len(hist2), ")")
