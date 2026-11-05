"""Probe 23 (Phase 4B, S0 M3): error shapes on Strata 0.1.54's Anthropic Messages routes.

Cases (docs/plan/phases/phase4b.md §1, row M3): malformed JSON, a non-object body, an empty
body, empty / non-list ``messages``, an unknown role, a message without content, OpenAI-wrapped
tools, context overflow (stream and non-stream, and count_tokens on the same body), prompt +
``max_tokens`` over the context with and without ``fit_max_tokens: false``, an unknown sub-route
and a GET. Each records status, headers, raw body and time to answer.

The engine-down shape is NOT probed: it needs stopping the engine, and restarting Strata
needs the user's approval. Mid-stream ``event: error`` frames likewise need an engine failure.

Sequential, idle-gated (D39), synthetic. Writes fixtures/strata_messages/p23_messages_errors.json.

    uv run python eval/probes/p23_messages_errors.py [--only case,case]
"""

from __future__ import annotations

import argparse
import json
import time

from strata_common import BASE, FIXTURES, MODEL, check_build, client, filler, wait_idle

OUT = FIXTURES / "strata_messages"
OUT.mkdir(parents=True, exist_ok=True)
BUILD = "Strata 0.1.54"
OFF = {"type": "disabled"}


def msg(content: str = "Q1", **kw) -> dict:
    return {"model": MODEL, "max_tokens": 8, "thinking": OFF, "messages": [{"role": "user", "content": content}], **kw}


def overflow_text() -> str:
    # 16000 words is ~35K tokens with this tokenizer (p21: 9000 words -> 19932 tokens), over n_ctx 32768.
    return filler(16000, seed=2301) + "\n\nReply with one word."


def big_text() -> str:
    # ~9000 words -> ~20K tokens: prompt + max_tokens 16000 exceeds 32768.
    return f"[nonce {time.time_ns()}]\n" + filler(9000, seed=2302) + "\n\nReply with the single word: done."


# (name, path, method, payload) where payload is a dict (sent as JSON) or bytes (sent raw).
def cases() -> list[tuple[str, str, str, object]]:
    over = overflow_text()
    big = big_text()
    return [
        ("malformed_json", "/v1/messages", "POST", b'{"model": "m", "messages": ['),
        ("malformed_json_count_tokens", "/v1/messages/count_tokens", "POST", b'{"model": "m", "messages": ['),
        ("not_an_object", "/v1/messages", "POST", b"[1, 2]"),
        ("empty_object", "/v1/messages", "POST", {}),
        ("empty_messages", "/v1/messages", "POST", {"model": MODEL, "max_tokens": 8, "messages": []}),
        ("messages_not_list", "/v1/messages", "POST", {"model": MODEL, "max_tokens": 8, "messages": "hi"}),
        ("unknown_role", "/v1/messages", "POST", {"model": MODEL, "max_tokens": 8,
                                                 "messages": [{"role": "bot", "content": "Q1"}]}),
        ("unknown_role_stream", "/v1/messages", "POST", {"model": MODEL, "max_tokens": 8, "stream": True,
                                                        "messages": [{"role": "bot", "content": "Q1"}]}),
        ("missing_content", "/v1/messages", "POST", {"model": MODEL, "max_tokens": 8, "thinking": OFF,
                                                    "messages": [{"role": "user"}]}),
        ("openai_wrapped_tools", "/v1/messages", "POST", msg(tools=[{"type": "function", "function": {
            "name": "f", "parameters": {"type": "object", "properties": {}}}}])),
        ("overflow_count_tokens", "/v1/messages/count_tokens", "POST", msg(over)),
        ("overflow_nonstream", "/v1/messages", "POST", msg(over)),
        ("overflow_stream", "/v1/messages", "POST", {**msg(over), "stream": True}),
        ("prompt_plus_max_over_ctx_fit_false", "/v1/messages", "POST",
         {**msg(big), "max_tokens": 16000, "fit_max_tokens": False}),
        ("prompt_plus_max_over_ctx", "/v1/messages", "POST", {**msg(big), "max_tokens": 16000}),
        ("unknown_subroute", "/v1/messages/batches", "POST", msg()),
        ("get_messages", "/v1/messages", "GET", None),
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    props = check_build(BUILD)
    only = [x for x in a.only.split(",") if x]
    results: dict = {"base": BASE, "build": props.get("build_info"),
                     "n_ctx": props["default_generation_settings"]["n_ctx"],
                     "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "cases": []}
    with client(900) as c:
        for name, path, method, payload in cases():
            if only and name not in only:
                continue
            wait_idle(quiet=1.0)
            t0 = time.monotonic()
            if method == "GET":
                r = c.get(path)
            elif isinstance(payload, bytes):
                r = c.post(path, content=payload, headers={"content-type": "application/json"})
            else:
                r = c.post(path, json=payload)
            elapsed = round(time.monotonic() - t0, 3)
            raw = r.content
            try:
                body = r.json()
            except ValueError:
                body = None
            row = {"name": name, "path": path, "method": method, "status": r.status_code, "elapsed_s": elapsed,
                   "headers": {k: v for k, v in r.headers.items() if k.lower() != "date"},
                   "body": body if body is not None else raw[:2000].decode("utf-8", "replace")}
            if isinstance(payload, bytes):
                row["sent_raw"] = payload.decode()
            elif isinstance(payload, dict):
                row["sent_fields"] = sorted(payload)
                row["sent_max_tokens"] = payload.get("max_tokens")
                if body and isinstance(body, dict) and "usage" in body:
                    row["usage"] = body["usage"]
                    row["body"] = {k: v for k, v in body.items() if k != "content"}
                    row["content_types"] = [b.get("type") for b in body.get("content", [])]
            results["cases"].append(row)
            short = json.dumps(row["body"], ensure_ascii=False)[:220] if not isinstance(row["body"], str) \
                else row["body"][:220]
            print(f"{name:36s} {r.status_code} {elapsed:7.2f}s {r.headers.get('content-type')} {short}")
    results["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (OUT / "p23_messages_errors.json").write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n",
                                                 encoding="utf-8")


if __name__ == "__main__":
    main()
