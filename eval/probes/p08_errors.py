"""Probe 8: error shapes (status code + body) for each dialect.

Saves fixtures/errors.json. Context-overflow cases send filler sized from /props n_ctx (~1.08x the
context, measured at ~2.21 tokens/word with count_tokens) and are expected to be refused before generation; oversize max_tokens cases use reasoning off and a one-word answer.
Usage: python p08_errors.py [case ...]
"""

from __future__ import annotations

import json
import sys
import time

from strata_common import FIXTURES, MODEL, client, filler

with client(10) as _c:
    N_CTX = _c.get("/props").json()["default_generation_settings"]["n_ctx"]
BIG = filler(int(N_CTX * 1.08 / 2.21), seed=1)  # ~8% over the context
NEAR = filler(9000, seed=2)  # ~20K tokens: fits, but not with max_tokens = N_CTX - 15000
NEAR_MAX = N_CTX - 15000
OK = [{"role": "user", "content": "Reply with the single word OK."}]

CASES: dict[str, tuple[str, object]] = {
    "bad_json_chat": ("/v1/chat/completions", b'{"model": "x", "messages": [ {"role": '),
    "bad_json_messages": ("/v1/messages", b'{"model": "x", "messages": [ {"role": '),
    "bad_json_responses": ("/v1/responses", b'{"model": "x", "input": '),
    "not_object_chat": ("/v1/chat/completions", b'[1,2,3]'),
    "bad_role_chat": ("/v1/chat/completions", {"model": MODEL, "max_tokens": 8, "messages": [{"role": "wizard", "content": "hi"}]}),
    "messages_missing_max_tokens": ("/v1/messages", {"model": MODEL, "messages": OK, "thinking": {"type": "disabled"}}),
    "overflow_chat": ("/v1/chat/completions", {"model": MODEL, "max_tokens": 16, "reasoning_effort": "none",
                                               "messages": [{"role": "user", "content": BIG}]}),
    "overflow_chat_stream": ("/v1/chat/completions", {"model": MODEL, "max_tokens": 16, "reasoning_effort": "none",
                                                      "stream": True, "messages": [{"role": "user", "content": BIG}]}),
    "overflow_messages": ("/v1/messages", {"model": MODEL, "max_tokens": 16, "thinking": {"type": "disabled"},
                                           "messages": [{"role": "user", "content": BIG}]}),
    "overflow_responses": ("/v1/responses", {"model": MODEL, "max_output_tokens": 16, "reasoning": {"effort": "none"},
                                             "input": BIG}),
    "overflow_count_tokens": ("/v1/messages/count_tokens", {"model": MODEL, "messages": [{"role": "user", "content": BIG}]}),
    "near_fit_false": ("/v1/chat/completions", {"model": MODEL, "max_tokens": NEAR_MAX, "reasoning_effort": "none",
                                                "fit_max_tokens": False,
                                                "messages": [{"role": "user", "content": NEAR + "\n\nReply with the single word OK."}]}),
    "near_fit_default": ("/v1/chat/completions", {"model": MODEL, "max_tokens": NEAR_MAX, "reasoning_effort": "none",
                                                  "messages": [{"role": "user", "content": NEAR + "\n\nReply with the single word OK."}]}),
    "oversize_max_tokens_small_prompt": ("/v1/chat/completions", {"model": MODEL, "max_tokens": 1000000,
                                                                  "reasoning_effort": "none", "messages": OK}),
    "oversize_max_tokens_fit_false": ("/v1/chat/completions", {"model": MODEL, "max_tokens": 1000000,
                                                               "reasoning_effort": "none", "fit_max_tokens": False,
                                                               "messages": OK}),
    "oversize_max_tokens_messages": ("/v1/messages", {"model": MODEL, "max_tokens": 1000000,
                                                      "thinking": {"type": "disabled"}, "messages": OK}),
    "negative_max_tokens": ("/v1/chat/completions", {"model": MODEL, "max_tokens": -5, "reasoning_effort": "none",
                                                     "messages": OK}),
    "string_tool_args_not_json": ("/v1/chat/completions", {
        "model": MODEL, "max_tokens": 8, "reasoning_effort": "none",
        "messages": [OK[0], {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "f", "arguments": "not json"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "x"}]}),
    "unknown_route": ("/v1/nonexistent", {"x": 1}),
}


def run(name: str, results: dict) -> None:
    path, body = CASES[name]
    t0 = time.monotonic()
    with client() as c:
        if isinstance(body, bytes):
            r = c.post(path, content=body, headers={"Content-Type": "application/json"})
        else:
            r = c.post(path, json=body)
    dt = time.monotonic() - t0
    text = r.text
    try:
        parsed = r.json()
        if isinstance(parsed, dict):
            # keep echoed fields short
            parsed = json.loads(json.dumps(parsed)[:4000]) if len(json.dumps(parsed)) < 4000 else {"_truncated": text[:2000]}
    except Exception:
        parsed = {"_raw": text[:2000]}
    req_desc = body.decode() if isinstance(body, bytes) else {
        k: (f"<{len(v[0]['content'])} chars>" if k == "messages" and len(json.dumps(v)) > 2000 else
            (f"<{len(v)} chars>" if isinstance(v, str) and len(v) > 2000 else v)) for k, v in body.items()}
    results[name] = {"n_ctx": N_CTX, "path": path, "request": req_desc, "status": r.status_code,
                     "content_type": r.headers.get("content-type"), "body": parsed, "wall_s": round(dt, 2)}
    print(f"{name}: {r.status_code} {dt:.1f}s {text[:300]!r}")


if __name__ == "__main__":
    out = FIXTURES / "errors.json"
    results = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    for n in (sys.argv[1:] or list(CASES)):
        run(n, results)
        out.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
