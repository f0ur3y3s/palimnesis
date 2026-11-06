"""Probe 27: the wire shapes of a Strata release, to compare two releases (R51).

Sends a fixed list of requests and records, for each, the status, the content type and a
skeleton of the body: keys and value types, with values kept only where they are enums
(``object``, ``type``, ``role``, ``finish_reason``, ``stop_reason``, ``event``, error
``code``, tool names) and ids reduced to their prefix. Streams are parsed into events, and
a run of identical events is recorded once with its count, so a different chunking shows
as a count, not as a different shape.

Run it against Strata in mock mode (``serve.server --engine mock``) with the two scripts in
``--script-cycle`` order that ``~/strata-test/mock.sh`` on mbp uses: a reasoning-then-text
reply, then a reasoning-then-tool-call reply. The eight generating cases alternate text and
tool requests to match, so two releases given the same scripts see the same requests.

    uv run python eval/probes/p27_release_shapes.py --upstream URL --out A.json [--session S]
    uv run python eval/probes/p27_release_shapes.py --compare A.json B.json

``--session S`` sends ``X-Palimnesis-Session: S-<case>``, a session per case, so the same
cases can run through the proxy.
``--compare`` prints every case whose shape differs and exits 1 if any does. It also prints
error messages whose wording changed (``WORDING``), since the proxy and harnesses match some
of them, but wording alone does not fail the comparison.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

import httpx

ENUM_KEYS = {"object", "type", "role", "finish_reason", "stop_reason", "event", "code", "name",
             "stop_sequence", "param"}
ID_KEYS = {"id", "tool_call_id", "tool_use_id", "system_fingerprint"}
MODEL = "qwen3.8-flash-next-iq3_xxs"

TOOLS_OA = [{"type": "function", "function": {
    "name": "get_weather", "description": "Weather for a city.",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]
TOOLS_AN = [{"name": "get_weather", "description": "Weather for a city.",
             "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}]
USER = [{"role": "user", "content": "Say hello."}]
WEATHER = [{"role": "user", "content": "What is the weather in Paris?"}]
OVERFLOW = [{"role": "user", "content": "word " * 40_000}]


def chat(stream: bool, tools: bool, **extra) -> dict:
    body = {"model": MODEL, "messages": WEATHER if tools else USER, "max_tokens": 200, "stream": stream}
    if tools:
        body["tools"] = TOOLS_OA
    if stream:
        body["stream_options"] = {"include_usage": True}
    return {**body, **extra}


def messages(stream: bool, tools: bool, **extra) -> dict:
    body = {"model": MODEL, "messages": WEATHER if tools else USER, "max_tokens": 200, "stream": stream}
    if tools:
        body["tools"] = TOOLS_AN
    return {**body, **extra}


# (name, method, path, body). Generating cases alternate text and tool requests, in the
# order the mock's two scripts cycle.
CASES = [
    ("chat_stream_text", "POST", "/v1/chat/completions", chat(True, False)),
    ("chat_stream_tool", "POST", "/v1/chat/completions", chat(True, True)),
    ("chat_text", "POST", "/v1/chat/completions", chat(False, False)),
    ("chat_tool", "POST", "/v1/chat/completions", chat(False, True)),
    ("messages_stream_text", "POST", "/v1/messages", messages(True, False)),
    ("messages_stream_tool", "POST", "/v1/messages", messages(True, True)),
    ("messages_text", "POST", "/v1/messages", messages(False, False)),
    ("messages_tool", "POST", "/v1/messages", messages(False, True)),
    ("count_tokens", "POST", "/v1/messages/count_tokens", {"model": MODEL, "messages": USER}),
    ("chat_malformed_json", "POST", "/v1/chat/completions", b"{not json"),
    ("messages_malformed_json", "POST", "/v1/messages", b"{not json"),
    ("chat_empty_messages", "POST", "/v1/chat/completions", {"model": MODEL, "messages": []}),
    ("messages_empty_messages", "POST", "/v1/messages", {"model": MODEL, "messages": [], "max_tokens": 10}),
    ("chat_overflow_stream", "POST", "/v1/chat/completions",
     {"model": MODEL, "messages": OVERFLOW, "max_tokens": 10, "stream": True}),
    ("chat_overflow", "POST", "/v1/chat/completions", {"model": MODEL, "messages": OVERFLOW, "max_tokens": 10}),
    ("messages_overflow", "POST", "/v1/messages", {"model": MODEL, "messages": OVERFLOW, "max_tokens": 10}),
    ("unknown_route", "POST", "/v1/nonexistent", {"model": MODEL}),
    ("models", "GET", "/v1/models", None),
    ("props", "GET", "/props", None),
    ("status", "GET", "/status", None),
    ("v1_status", "GET", "/v1/status", None),
    ("slots", "GET", "/slots", None),
    ("health", "GET", "/health", None),
]


def _id(value: str) -> str:
    m = re.match(r"^([A-Za-z]+[-_])", value)
    return f"{m.group(1)}…" if m else "id…"


def skel(x, key: str | None = None):
    if isinstance(x, dict):
        return {k: skel(v, k) for k, v in sorted(x.items())}
    if isinstance(x, list):
        out = []
        for item in (skel(v) for v in x):
            if not out or out[-1] != item:
                out.append(item)
        return out
    if isinstance(x, str):
        if key in ENUM_KEYS:
            return x
        if key in ID_KEYS:
            return _id(x)
        return "str"
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, int):
        return x if key == "index" else "int"
    if isinstance(x, float):
        return "float"
    return type(x).__name__


def parse_body(text: str):
    try:
        return skel(json.loads(text))
    except ValueError:
        return {"raw": "str" if text.strip() else ""}


def parse_sse(text: str) -> list:
    events = []
    for block in re.split(r"\r?\n\r?\n", text):
        if not block.strip():
            continue
        name, data, comment = None, [], False
        for line in block.splitlines():
            if line.startswith(":"):
                comment = True
            elif line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        payload = "\n".join(data)
        if comment and not data:
            shape = {"comment": True}
        elif payload == "[DONE]":
            shape = {"event": name, "data": "[DONE]"}
        else:
            shape = {"event": name, "data": parse_body(payload)}
        if events and events[-1]["shape"] == shape:
            events[-1]["count"] += 1
        else:
            events.append({"shape": shape, "count": 1})
    return events


def _message(text: str) -> str | None:
    """An error's message, verbatim: harnesses and the proxy read some of these."""
    try:
        err = json.loads(text).get("error")
    except (ValueError, AttributeError):
        return None
    return err.get("message") if isinstance(err, dict) else None


def run(base: str, session: str | None, model: str = MODEL, skip: str = "") -> dict:
    out = {}
    with httpx.Client(base_url=base.rstrip("/"), timeout=120) as client:
        for name, method, path, body in CASES:
            if skip and re.search(skip, name):
                continue
            if isinstance(body, dict) and "model" in body:
                body = {**body, "model": model}
            content = body if isinstance(body, bytes) else (None if body is None else json.dumps(body).encode())
            headers = {"content-type": "application/json"}
            if session:  # one conversation per session, as the proxy requires
                headers["x-palimnesis-session"] = f"{session}-{name.replace('_', '-')}"
            r = client.request(method, path, content=content, headers=headers)
            ctype = r.headers.get("content-type", "").split(";")[0]
            record = {"status": r.status_code, "content_type": ctype}
            if ctype == "text/event-stream":
                events = parse_sse(r.text)
                record["events"] = [e["shape"] for e in events]
                record["counts"] = [e["count"] for e in events]
            else:
                record["body"] = parse_body(r.text)
                if r.status_code >= 400:
                    record["error_message"] = _message(r.text)
            out[name] = record
            print(f"{name:26} {r.status_code} {ctype}")
    return out


def compare(a: Path, b: Path) -> int:
    left, right = (json.loads(p.read_text(encoding="utf-8")) for p in (a, b))
    differing = 0
    for name in sorted(set(left) | set(right)):
        la, rb = left.get(name), right.get(name)
        strip = (lambda r: None if r is None else
                 {k: v for k, v in r.items() if k not in ("counts", "error_message")})
        wa, wb = (la or {}).get("error_message"), (rb or {}).get("error_message")
        if wa != wb:
            print(f"WORDING {name}")
            print(f"   {a.name}: {wa}")
            print(f"   {b.name}: {wb}")
        if strip(la) == strip(rb):
            note = "" if (la or {}).get("counts") == (rb or {}).get("counts") else "  (event counts differ)"
            print(f"same   {name}{note}")
            continue
        differing += 1
        print(f"DIFFER {name}")
        sa = json.dumps(strip(la), indent=1, sort_keys=True, ensure_ascii=False).splitlines()
        sb = json.dumps(strip(rb), indent=1, sort_keys=True, ensure_ascii=False).splitlines()
        for line in difflib.unified_diff(sa, sb, a.name, b.name, n=2, lineterm=""):
            print("   " + line)
    print(f"{differing} of {len(set(left) | set(right))} cases differ")
    return 1 if differing else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--session")
    ap.add_argument("--compare", nargs=2, type=Path)
    ap.add_argument("--model", default=MODEL, help="the model name to send (another server's own)")
    ap.add_argument("--skip", default="", help="regex of case names to leave out, e.g. overflow")
    args = ap.parse_args()
    if args.compare:
        return compare(*args.compare)
    if not (args.upstream and args.out):
        ap.error("--upstream and --out are required unless --compare is given")
    args.out.write_text(json.dumps(run(args.upstream, args.session, args.model, args.skip), indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
