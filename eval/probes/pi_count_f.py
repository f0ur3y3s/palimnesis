"""Count Pi's fixed input F (system prompt + tools) with the pinned Strata counter.

Reads the first Chat Completions request a Pi probe captured (``server.jsonl`` from
``pi_fault_server.py``) and counts it with ``palimnesis.upstreams.strata.tokens`` (the
pinned template and tokenizer, exact against Strata in 19 of 19 cases, docs/probes/strata.md
§4). Prints the whole first prompt, the prompt without tools, the user turn alone, and F
as the difference. Also checks whether a leading ``developer`` message renders exactly
like ``system`` (decision O-4B-9).

Usage:
    uv run python eval/probes/pi_count_f.py RUNDIR [RUNDIR ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from palimnesis.upstreams.strata import pins
from palimnesis.upstreams.strata.tokens import Tokens


def first_chat_body(rundir: Path) -> dict:
    for line in (rundir / "server.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["event"] == "request" and r.get("protocol") == "chat":
            return r["body"]
    raise SystemExit(f"no chat request in {rundir}")


def main() -> None:
    tok = Tokens(pins.load())
    for arg in sys.argv[1:]:
        body = first_chat_body(Path(arg))
        msgs = body["messages"]
        tools, kw = tok.render_args(body)
        as_system = [{**m, "role": "system"} if m["role"] == "developer" else m for m in msgs]
        full = tok.count(tok.render(msgs, tools, **kw))
        full_sys = tok.count(tok.render(as_system, tools, **kw))
        no_tools = tok.count(tok.render(as_system, None, **kw))
        user_only = tok.count(tok.render([m for m in msgs if m["role"] == "user"], None, **kw))
        same = tok.render(msgs, tools, **kw) == tok.render(as_system, tools, **kw)
        print(json.dumps({
            "run": Path(arg).name,
            "roles": [m["role"] for m in msgs],
            "tools": [t["function"]["name"] for t in tools or []],
            "system_chars": len(msgs[0]["content"]) if isinstance(msgs[0]["content"], str) else None,
            "first_prompt_tokens": full,
            "first_prompt_tokens_system_role": full_sys,
            "developer_renders_as_system": same,
            "without_tools": no_tools,
            "user_turn_only": user_only,
            "F_system_plus_tools": full_sys - user_only,
            "F_tools_only": full_sys - no_tools,
        }, indent=1))


if __name__ == "__main__":
    main()
