"""Probe 2/4: render the installed chat template locally and compare token counts with Strata.

Renders fixtures/strata_chat_template.jinja with jinja2 (HF-style tojson) and tokenizes with the
Qwen/Qwen3.8-Flash-Next tokenizer.json (pass its path as argv[1]; download from
https://huggingface.co/Qwen/Qwen3.8-Flash-Next/resolve/main/tokenizer.json). Compares against
/v1/messages/count_tokens for equivalent Anthropic-shaped requests (no inference).
Saves fixtures/template_render_check.json and golden renders fixtures/render_<case>.txt.

Usage: uv run --no-project --python 3.12 --with httpx --with jinja2 --with tokenizers python p02_template_render.py <tokenizer.json>
"""

from __future__ import annotations

import json
import sys

import jinja2
from jinja2.sandbox import ImmutableSandboxedEnvironment
from tokenizers import Tokenizer

from p04_count_tokens import TH
from p05_nonstream import TOOLS_AN
from strata_common import FIXTURES, MODEL, client, save_json

TEMPLATE = (FIXTURES / "strata_chat_template.jinja").read_text(encoding="utf-8")


def tojson(x, indent=None, separators=None, sort_keys=False):
    return json.dumps(x, ensure_ascii=False, indent=indent, separators=separators, sort_keys=sort_keys)


def raise_exception(msg):
    raise jinja2.exceptions.TemplateError(msg)


ENV = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True, extensions=["jinja2.ext.loopcontrols"])
ENV.filters["tojson"] = tojson
ENV.globals["raise_exception"] = raise_exception
TPL = ENV.from_string(TEMPLATE)


def render(messages, tools=None, **kw) -> str:
    return TPL.render(messages=messages, tools=tools, add_generation_prompt=True, **kw)


OA_TOOLS = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": t["input_schema"]}} for t in TOOLS_AN]
# Strata's /v1/messages path renders each tool as a bare {"name", "description", "parameters"} object
# (verified: 300 tokens vs 309 for the OpenAI-wrapped form).
BARE_TOOLS = [{"name": t["name"], "description": t["description"], "parameters": t["input_schema"]} for t in TOOLS_AN]
TC = {"id": "c1", "type": "function", "function": {"name": "get_weather", "arguments": {"city": "Paris"}}}

# (case, anthropic request for count_tokens, openai-shaped messages for local render, render kwargs)
CASES = [
    ("user_default", {"messages": [{"role": "user", "content": "Q1"}]},
     [{"role": "user", "content": "Q1"}], {}, None),
    ("user_thinking_disabled", {"messages": [{"role": "user", "content": "Q1"}], "thinking": {"type": "disabled"}},
     [{"role": "user", "content": "Q1"}], {"enable_thinking": False}, None),
    ("user_effort_low", {"messages": [{"role": "user", "content": "Q1"}], "output_config": {"effort": "low"}},
     [{"role": "user", "content": "Q1"}], {"reasoning_effort": "low"}, None),
    ("user_effort_medium", {"messages": [{"role": "user", "content": "Q1"}], "output_config": {"effort": "medium"}},
     [{"role": "user", "content": "Q1"}], {"reasoning_effort": "medium"}, None),
    ("system_user", {"system": "You are terse.", "messages": [{"role": "user", "content": "Q1"}]},
     [{"role": "system", "content": "You are terse."}, {"role": "user", "content": "Q1"}], {}, None),
    ("prior_text", {"messages": [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "Answer one."},
                                 {"role": "user", "content": "Q2"}]},
     [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "Answer one."},
      {"role": "user", "content": "Q2"}], {}, None),
    ("prior_thinking", {"messages": [{"role": "user", "content": "Q1"},
                                     {"role": "assistant", "content": [{"type": "thinking", "thinking": TH, "signature": "x"},
                                                                       {"type": "text", "text": "Answer one."}]},
                                     {"role": "user", "content": "Q2"}]},
     [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "Answer one.", "reasoning_content": TH},
      {"role": "user", "content": "Q2"}], {}, None),
    ("prior_thinking_preserve_false_LOCAL_ONLY", None,
     [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "Answer one.", "reasoning_content": TH},
      {"role": "user", "content": "Q2"}], {"preserve_thinking": False}, None),
    ("tools_only", {"messages": [{"role": "user", "content": "Q1"}], "tools": TOOLS_AN},
     [{"role": "user", "content": "Q1"}], {}, BARE_TOOLS),
    ("tool_turn_think", {"tools": TOOLS_AN, "messages": [
        {"role": "user", "content": "Weather in Paris?"},
        {"role": "assistant", "content": [{"type": "thinking", "thinking": TH, "signature": "x"},
                                          {"type": "tool_use", "id": "c1", "name": "get_weather", "input": {"city": "Paris"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "Sunny 20C"}]}]},
     [{"role": "user", "content": "Weather in Paris?"},
      {"role": "assistant", "content": "", "reasoning_content": TH, "tool_calls": [TC]},
      {"role": "tool", "tool_call_id": "c1", "content": "Sunny 20C"}], {}, BARE_TOOLS),
]


def main() -> None:
    tok = Tokenizer.from_file(sys.argv[1])
    out = {}
    with client(30) as c:
        for name, an_req, oa_msgs, kw, tools in CASES:
            text = render(oa_msgs, tools=tools, **kw)
            n_local = len(tok.encode(text, add_special_tokens=False).ids)
            n_srv = None
            if an_req is not None:
                n_srv = c.post("/v1/messages/count_tokens", json={"model": MODEL, **an_req}).json().get("input_tokens")
            (FIXTURES / f"render_{name}.txt").write_text(text, encoding="utf-8", newline="")
            out[name] = {"local_tokens": n_local, "server_count_tokens": n_srv,
                         "match": (n_srv == n_local) if n_srv is not None else None}
            print(f"{name:42s} local={n_local:5d} server={n_srv} {'OK' if n_srv == n_local else ''}")
    save_json("template_render_check.json", out)


if __name__ == "__main__" and "--openai-fixtures" not in sys.argv:
    main()


def check_openai_fixtures(tok) -> dict:
    """Compare local renders of the OpenAI-path fixtures (p05) with their usage.prompt_tokens."""
    import json as _json
    res = {}
    for case, kw in [("oa_prior_reasoning", {"enable_thinking": False}),
                     ("oa_prior_reasoning_preserve_false", {"enable_thinking": False}),
                     ("oa_prior_no_reasoning", {"enable_thinking": False}),
                     ("oa_effort_none", {"enable_thinking": False}),
                     ("oa_default_think_low", {"reasoning_effort": "low"}),
                     ("oa_tool_call", {"enable_thinking": False}),
                     ("oa_tool_followup", {"enable_thinking": False})]:
        f = FIXTURES / f"nonstream_{case}.json"
        if not f.exists():
            continue
        d = _json.loads(f.read_text(encoding="utf-8"))
        req = d["request"]
        msgs = []
        for m in req["messages"]:
            m = dict(m)
            if m.get("tool_calls"):
                m["tool_calls"] = [{**tc, "function": {**tc["function"],
                                                       "arguments": _json.loads(tc["function"]["arguments"])}}
                                   for tc in m["tool_calls"]]
            msgs.append(m)
        tools = req.get("tools")
        variants = {"wrapped": tools, "bare": [t["function"] for t in tools]} if tools else {"-": None}
        for vname, tl in variants.items():
            n = len(tok.encode(render(msgs, tools=tl, **kw), add_special_tokens=False).ids)
            used = d["body"]["usage"]["prompt_tokens"]
            res[f"{case}[{vname}]"] = {"local_tokens": n, "usage_prompt_tokens": used, "match": n == used}
            print(f"{case + '[' + vname + ']':42s} local={n:5d} usage={used} {'OK' if n == used else ''}")
    return res


if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[2] == "--openai-fixtures":
    save_json("template_render_check_openai.json", check_openai_fixtures(Tokenizer.from_file(sys.argv[1])))
