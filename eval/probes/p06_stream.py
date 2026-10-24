"""Probe 6: capture raw SSE bytes verbatim for each dialect.

Writes fixtures/sse_<case>.sse (exact bytes as received) and fixtures/sse_<case>.meta.json
(request, status, headers, per-chunk arrival offsets, and a parsed event summary).
Usage: python p06_stream.py [case ...]
"""

from __future__ import annotations

import json
import sys
import time

from p05_nonstream import TOOLS_AN, TOOLS_OA
from strata_common import MODEL, client, filler, save_bytes, save_json

Q = "What is 17 * 23? Reply with just the number."
U = [{"role": "user", "content": Q}]
PAR = ("In a single response, emit two get_weather tool calls in parallel: one for Paris and one for Oslo. "
       "Do not write any text.")
WX = [{"role": "user", "content": "What's the weather in Paris and in Oslo? Use the tool for each city."}]

CASES: dict[str, tuple[str, dict]] = {
    "oa_plain": ("/v1/chat/completions", {"model": MODEL, "messages": U, "max_tokens": 64, "stream": True,
                                          "reasoning_effort": "none"}),
    "oa_reasoning": ("/v1/chat/completions", {"model": MODEL, "messages": U, "max_tokens": 256, "stream": True,
                                              "reasoning_effort": "low"}),
    "oa_tool": ("/v1/chat/completions", {"model": MODEL, "messages": WX, "max_tokens": 256, "stream": True,
                                         "reasoning_effort": "none", "tools": TOOLS_OA}),
    "oa_tool_parallel": ("/v1/chat/completions", {"model": MODEL, "max_tokens": 256, "stream": True,
                                                  "reasoning_effort": "none", "tools": TOOLS_OA,
                                                  "messages": [{"role": "user", "content": PAR}]}),
    "an_tool_parallel": ("/v1/messages", {"model": MODEL, "max_tokens": 256, "stream": True,
                                          "thinking": {"type": "disabled"}, "tools": TOOLS_AN,
                                          "messages": [{"role": "user", "content": PAR}]}),
    # ~20K-token prefills (two 8192-token chunks + tail) to observe keep-alive cadence and prompt_progress.
    "oa_long_prefill": ("/v1/chat/completions", {
        "model": MODEL, "max_tokens": 4, "stream": True, "reasoning_effort": "none",
        "messages": [{"role": "user", "content": filler(9000, seed=4242) + "\n\nReply with the single word OK."}]}),
    "oa_long_prefill_progress": ("/v1/chat/completions", {
        "model": MODEL, "max_tokens": 4, "stream": True, "reasoning_effort": "none", "return_progress": True,
        "messages": [{"role": "user", "content": filler(9000, seed=4343) + "\n\nReply with the single word OK."}]}),
    "oa_include_usage": ("/v1/chat/completions", {"model": MODEL, "messages": U, "max_tokens": 64, "stream": True,
                                                  "reasoning_effort": "none",
                                                  "stream_options": {"include_usage": True}}),
    "oa_length": ("/v1/chat/completions", {"model": MODEL, "messages": U, "max_tokens": 8, "stream": True,
                                           "reasoning_effort": "low"}),
    "an_plain": ("/v1/messages", {"model": MODEL, "messages": U, "max_tokens": 64, "stream": True,
                                  "thinking": {"type": "disabled"}}),
    "an_thinking": ("/v1/messages", {"model": MODEL, "messages": U, "max_tokens": 256, "stream": True,
                                     "output_config": {"effort": "low"}}),
    "an_tool": ("/v1/messages", {"model": MODEL, "messages": WX, "max_tokens": 256, "stream": True,
                                 "thinking": {"type": "disabled"}, "tools": TOOLS_AN}),
    "rs_reasoning": ("/v1/responses", {"model": MODEL, "input": Q, "max_output_tokens": 256, "stream": True,
                                       "reasoning": {"effort": "low"}}),
}


def summarize(raw: bytes) -> list[str]:
    """One line per SSE event: 'event-name | short data' (comments shown as ': ...')."""
    out = []
    for block in raw.decode("utf-8", "replace").replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        ev, data, comments = None, [], []
        for line in block.split("\n"):
            if line.startswith(":"):
                comments.append(line)
            elif line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if comments and not data:
            out.append(" / ".join(comments)[:120])
            continue
        d = "\n".join(data)
        try:
            j = json.loads(d)
            if "choices" in j:
                ch = j["choices"][0] if j["choices"] else {}
                short = json.dumps({"delta": ch.get("delta"), "finish_reason": ch.get("finish_reason"),
                                    **({"usage": j["usage"]} if j.get("usage") else {}),
                                    **({"timings": "..."} if j.get("timings") else {})}, ensure_ascii=False)
            else:
                short = json.dumps(j, ensure_ascii=False)
        except Exception:
            short = d
        out.append(f"{ev or '-'} | {short[:300]}")
    return out


def run(name: str) -> None:
    path, body = CASES[name]
    chunks: list[tuple[float, int]] = []
    buf = bytearray()
    t0 = time.monotonic()
    with client() as c, c.stream("POST", path, json=body) as r:
        hdrs = dict(r.headers)
        code = r.status_code
        for b in r.iter_raw():
            chunks.append((round(time.monotonic() - t0, 4), len(b)))
            buf.extend(b)
    save_bytes(f"sse_{name}.sse", bytes(buf))
    events = summarize(bytes(buf))
    save_json(f"sse_{name}.meta.json", {"case": name, "path": path, "request": body, "status": code,
                                         "headers": hdrs, "chunk_arrivals_s_bytes": chunks,
                                         "events_summary": events})
    print(f"== {name}: {code} {len(buf)} bytes, {len(chunks)} chunks, {time.monotonic() - t0:.1f}s")
    for e in events:
        print("   ", e[:220])


if __name__ == "__main__":
    for n in (sys.argv[1:] or list(CASES)):
        run(n)
