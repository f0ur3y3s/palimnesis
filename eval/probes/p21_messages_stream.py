"""Probe 21 (Phase 4B, S0 M1): Anthropic Messages stream shapes on Strata 0.1.54.

Questions (docs/plan/phases/phase4b.md §1, row M1):
  a. Event order on ``POST /v1/messages`` with ``stream: true``; ``event:`` name vs ``data.type``.
  b. ``message_start`` usage, and the ``message_delta`` usage (the ``input_tokens: 1`` note).
  c. ``content_block_*`` for thinking, text and tool_use; ``input_json_delta`` granularity;
     the tool_use id format; parallel tool_use.
  d. ``stop_reason`` on a length stop (text, thinking, inside tool arguments) and on a stop sequence.
  e. Keep-alives: SSE comments or ``event: ping``, and when (a ~12K-token cold prefill case).
  e2. Non-streaming twins of a tool call and of a length stop inside tool arguments.
  f. EOF on engine death: NOT probed (it needs killing the engine; restarting Strata needs
     the user's approval). The report marks it unverified.

Every case runs once (``--reps``), strictly sequentially, each gated on /status idle (D39).
Bodies are synthetic. Writes fixtures/strata_messages/p21_<case>_<rep>.sse (exact bytes) and
fixtures/strata_messages/p21_messages_stream.json (per-run shape summaries).

    uv run python eval/probes/p21_messages_stream.py [--reps 1] [--only case,case]
"""

from __future__ import annotations

import argparse
import json
import re
import time

from strata_common import BASE, FIXTURES, MODEL, check_build, client, filler, status, stream_post, wait_idle

OUT = FIXTURES / "strata_messages"
OUT.mkdir(parents=True, exist_ok=True)
BUILD = "Strata 0.1.54"

TOOLS = [
    {"name": "get_weather", "description": "Get the current weather for a city.",
     "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}},
    {"name": "write_file", "description": "Write a text file to the workspace.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                      "required": ["path", "content"]}},
]
SYSTEM = "You are a helpful assistant with tools."
OFF = {"type": "disabled"}


def body(prompt: str, max_tokens: int, *, think: str | None, tools: bool = False, **kw) -> dict:
    b: dict = {"model": MODEL, "stream": True, "max_tokens": max_tokens, "system": SYSTEM,
               "messages": [{"role": "user", "content": prompt}]}
    if think is None:
        b["thinking"] = OFF
    else:
        b["output_config"] = {"effort": think}
    if tools:
        b["tools"] = TOOLS
    b.update(kw)
    return b


P_SHORT = "In one short sentence: why is the sky blue?"
P_COUNT = "Count from 1 to 200, separated by commas."
P_WEATHER = "What's the weather in Paris right now? Use the tool."
P_PARALLEL = ("Get the current weather for Paris and for Oslo. Call get_weather once per city, both calls in "
              "this one response, before any answer.")
P_POEM = "Use write_file to create poem.txt containing an original 30-line poem about rivers. Call the tool directly."


def long_prefill() -> dict:
    nonce = f"nonce-{int(time.time())}"
    text = f"[{nonce}]\n" + filler(9000, seed=2101) + "\n\nIn one word: what is the first word of this text?"
    return body(text, 16, think=None)


CASES = {
    "text_off": lambda: body(P_SHORT, 64, think=None),
    "thinking_low": lambda: body(P_SHORT, 1024, think="low"),
    "tool_off": lambda: body(P_WEATHER, 256, think=None, tools=True),
    "tool_low": lambda: body(P_WEATHER, 1024, think="low", tools=True),
    "parallel_off": lambda: body(P_PARALLEL, 256, think=None, tools=True),
    "length_text": lambda: body(P_COUNT, 12, think=None),
    "length_thinking": lambda: body(P_SHORT, 24, think="low"),
    "length_tool_args": lambda: body(P_POEM, 40, think=None, tools=True),
    "stop_sequence": lambda: body("Count from 1 to 20, separated by commas.", 128, think=None,
                                  stop_sequences=["7,"]),
    # tool_choice behaviour (p22 shows neither form changes the prompt count)
    "forced_tool_named": lambda: body("Say hello.", 128, think=None, tools=True,
                                      tool_choice={"type": "tool", "name": "get_weather"}),
    "forced_tool_any": lambda: body("Say hello.", 128, think=None, tools=True, tool_choice={"type": "any"}),
    "tool_choice_none": lambda: body(P_WEATHER, 128, think=None, tools=True, tool_choice={"type": "none"}),
    "long_prefill": long_prefill,
}

_EV = re.compile(r"^event: ?(.*)$", re.M)


def frames(raw: bytes, arrivals) -> list[dict]:
    """Split SSE bytes into frames: {"t", "kind": comment|event, "event", "data"}."""
    ends, total = [], 0
    for t, n in arrivals:
        total += n
        ends.append((total, t))
    out, pos = [], 0
    while (i := raw.find(b"\n\n", pos)) >= 0:
        block = raw[pos:i].decode("utf-8", "replace")
        end = i + 2
        pos = end
        if not block.strip():
            continue
        t = next((tt for tot, tt in ends if tot >= end), None)
        lines = block.split("\n")
        data = [ln[5:].lstrip() for ln in lines if ln.startswith("data:")]
        if not data:
            out.append({"t": t, "kind": "comment", "text": block})
            continue
        ev = _EV.search(block)
        try:
            j = json.loads("\n".join(data))
        except json.JSONDecodeError:
            j = None
        out.append({"t": t, "kind": "event", "event": ev.group(1) if ev else None, "data": j})
    tail = raw[pos:].decode("utf-8", "replace")
    if tail.strip():
        out.append({"t": None, "kind": "tail", "text": tail})
    return out


def shape(fr: list[dict]) -> dict:
    order: list[list] = []

    def push(k):
        if order and order[-1][0] == k:
            order[-1][1] += 1
        else:
            order.append([k, 1])

    blocks: dict[int, dict] = {}
    msg_start = msg_delta = None
    name_mismatch, comments, pings = [], [], 0
    last_event = None
    for f in fr:
        if f["kind"] == "comment":
            push("comment")
            comments.append({"t": f["t"], "text": f["text"], "after": last_event})
            continue
        if f["kind"] == "tail":
            push("tail")
            continue
        d = f["data"] or {}
        typ = d.get("type")
        if f["event"] != typ:
            name_mismatch.append([f["event"], typ])
        if typ == "ping":
            pings += 1
        last_event = typ
        if typ == "content_block_start":
            cb = d["content_block"]
            blocks[d["index"]] = {"start": cb, "deltas": 0, "delta_types": set(), "text": "",
                                  "json_pieces": [], "stopped": False}
            push(f"start:{cb.get('type')}")
        elif typ == "content_block_delta":
            b = blocks.setdefault(d["index"], {"start": None, "deltas": 0, "delta_types": set(), "text": "",
                                               "json_pieces": [], "stopped": False})
            dt = d["delta"]["type"]
            b["deltas"] += 1
            b["delta_types"].add(dt)
            if dt == "input_json_delta":
                b["json_pieces"].append(d["delta"]["partial_json"])
            else:
                b["text"] += d["delta"].get("text", d["delta"].get("thinking", ""))
            push(f"delta:{dt}[{d['index']}]")
        elif typ == "content_block_stop":
            if d["index"] in blocks:
                blocks[d["index"]]["stopped"] = True
            push(f"stop[{d['index']}]")
        else:
            if typ == "message_start":
                msg_start = d
            elif typ == "message_delta":
                msg_delta = d
            push(typ)
    out_blocks = []
    for i in sorted(blocks):
        b = blocks[i]
        e = {"index": i, "start": b["start"], "deltas": b["deltas"], "delta_types": sorted(b["delta_types"]),
             "stopped": b["stopped"]}
        if b["json_pieces"]:
            joined = "".join(b["json_pieces"])
            try:
                parsed, ok = json.loads(joined), True
            except ValueError:
                parsed, ok = None, False
            e.update({"json_pieces": b["json_pieces"][:40], "json_piece_count": len(b["json_pieces"]),
                      "json": joined, "json_parses": ok, "input": parsed})
        else:
            e["text"] = b["text"][:400]
        out_blocks.append(e)
    return {"order": order, "message_start": msg_start, "message_delta": msg_delta, "blocks": out_blocks,
            "comments": comments, "ping_events": pings, "event_name_mismatches": name_mismatch,
            "ends_with_message_stop": bool(order) and order[-1][0] == "message_stop",
            "timeline": [[f["t"], f.get("event") or f["kind"]] for f in fr[:5]]
            + [[f["t"], f.get("event") or f["kind"]] for f in fr[-3:]]}


# Non-streaming twins: what the collected message holds when the output ends inside tool arguments.
NONSTREAM = {
    "length_tool_args_nonstream": lambda: {**body(P_POEM, 40, think=None, tools=True), "stream": False},
    "tool_off_nonstream": lambda: {**body(P_WEATHER, 256, think=None, tools=True), "stream": False},
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    props = check_build(BUILD)
    only = [x for x in a.only.split(",") if x]
    results = {"base": BASE, "build": props.get("build_info"),
               "n_ctx": props["default_generation_settings"]["n_ctx"],
               "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "runs": []}
    for name, make in CASES.items():
        if only and name not in only:
            continue
        for rep in range(a.reps):
            waited = wait_idle(quiet=2.0)
            req = make()
            r = stream_post(req, "/v1/messages")
            (OUT / f"p21_{name}_{rep}.sse").write_bytes(r["raw"])
            fr = frames(r["raw"], r["arrivals"])
            sh = shape(fr)
            sh.update({"case": name, "rep": rep, "status": r["status"],
                       "content_type": r["headers"].get("content-type"), "elapsed_s": r["elapsed_s"],
                       "waited_idle_s": round(waited, 1), "max_tokens": req["max_tokens"],
                       "request_fields": sorted(k for k in req if k != "messages"),
                       "headers": {k: v for k, v in r["headers"].items()
                                   if k.lower() not in ("date", "set-cookie")},
                       "status_after": status()})
            results["runs"].append(sh)
            md = (sh["message_delta"] or {})
            print(f"{name}#{rep}: {r['status']} {r['elapsed_s']}s stop={md.get('delta', {}).get('stop_reason')} "
                  f"blocks={[b['start']['type'] if b['start'] else None for b in sh['blocks']]} "
                  f"comments={len(sh['comments'])} pings={sh['ping_events']}")
    for name, make in NONSTREAM.items():
        if only and name not in only:
            continue
        wait_idle(quiet=2.0)
        req = make()
        t0 = time.monotonic()
        with client(600) as c:
            r = c.post("/v1/messages", json=req)
        run = {"case": name, "status": r.status_code, "content_type": r.headers.get("content-type"),
               "elapsed_s": round(time.monotonic() - t0, 3), "body": r.json()}
        results["runs"].append(run)
        print(f"{name}: {r.status_code} stop={run['body'].get('stop_reason')} "
              f"content={[b.get('type') for b in run['body'].get('content', [])]}")
    results["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (OUT / "p21_messages_stream.json").write_text(json.dumps(results, indent=1, ensure_ascii=False, default=list)
                                                  + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
