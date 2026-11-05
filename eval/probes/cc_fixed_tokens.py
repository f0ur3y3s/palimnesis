"""Count Claude Code's fixed input (F) with Palimnesis's pinned Strata counter.

Reads a cc_probe.py ``server.jsonl`` (or a fixture), takes the first main request
(``tools`` present), and renders it in the neutral Chat form the Messages adapter would
send upstream (system blocks joined as ``facts.anthropic_to_render_args`` joins them;
Anthropic tools in Strata's bare form):

- ``F_system_tools``: the leading system message plus tool definitions, no turns
  (``add_generation_prompt=False``);
- ``mid_system``: the extra tokens if the mid-conversation ``role: system`` entries were
  appended to the leading system message (one of O-4B-12's mappings), measured as the
  render difference;
- ``first_user``: the extra tokens of the first user message (reminders + prompt);
- per-tool token sizes (render difference with and without each tool).

Usage:
    uv run python eval/probes/cc_fixed_tokens.py SERVER_JSONL [--per-tool]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from palimnesis.upstreams.strata import pins, tokens
from palimnesis.upstreams.strata.facts import _text


def first_main(path: Path) -> dict:
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("event") == "request" and r.get("main") and isinstance(r.get("body"), dict):
            if isinstance(r["body"].get("tools"), list):
                return r["body"]
    raise SystemExit("no main request with tools")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--per-tool", action="store_true")
    a = ap.parse_args()
    body = first_main(Path(a.log))
    tk = tokens.Tokens(pins.load())
    system = _text(body.get("system") or "")
    tools = body["tools"]
    mids = [_text(m["content"]) for m in body["messages"] if m["role"] == "system"]
    first_user = next(m for m in body["messages"] if m["role"] == "user")
    fu_text = _text([b for b in first_user["content"] if b.get("type") == "text"]) if isinstance(first_user["content"], list) else first_user["content"]

    def n(msgs, tl):
        return tk.count(tk.render(msgs, tl, add_generation_prompt=False))

    sys_only = n([{"role": "system", "content": system}], None)
    f = n([{"role": "system", "content": system}], tools)
    with_mid = n([{"role": "system", "content": system + "".join("\n\n" + x for x in mids)}], tools)
    with_user = n([{"role": "system", "content": system}, {"role": "user", "content": fu_text}], tools)
    out = {
        "model": body.get("model"), "tool_count": len(tools),
        "system_chars": len(system), "tools_json_bytes": len(json.dumps(tools, ensure_ascii=False)),
        "mid_system_entries": len(mids), "mid_system_chars": sum(len(x) for x in mids),
        "first_user_chars": len(fu_text),
        "system_only_tokens": sys_only, "F_system_tools": f,
        "mid_system_extra_tokens": with_mid - f, "first_user_extra_tokens": with_user - f,
        "F_plus_mid_plus_first_user": f + (with_mid - f) + (with_user - f),
        "d79_floor_32k_remaining": 32768 - (f + 14592),
        "d79_floor_32k_remaining_with_mid": 32768 - (with_mid + 14592),
        "counter_revision": tk.revision,
    }
    if a.per_tool:
        per = {}
        for i, t in enumerate(tools):
            rest = tools[:i] + tools[i + 1:]
            per[t["name"]] = f - n([{"role": "system", "content": system}], rest or None)
        out["per_tool_tokens"] = dict(sorted(per.items(), key=lambda kv: -kv[1]))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
