"""Probe 22 (Phase 4B, S0 M2): Messages rendering parity on Strata 0.1.54.

For each case, an Anthropic Messages body is measured four ways:

  ct     ``POST /v1/messages/count_tokens`` on the Messages body (status, ``input_tokens``);
  mr     ``POST /v1/messages`` with ``max_tokens: 1``, non-streaming: status and the prompt
         size ``input_tokens + cache_creation_input_tokens + cache_read_input_tokens``;
  local  the repo's counter (``tokens.default().count_messages``) on the neutral Chat
         Completions body that ``neutral()`` below maps the Messages body to;
  cr     ``POST /v1/chat/completions`` with ``max_tokens: 1`` on that neutral Chat body:
         status and ``usage.prompt_tokens``.

``neutral()`` is the Phase 4B adapter mapping (docs/plan/phases/phase4b.md, core position 3),
written here only for the probe: ``system`` (string or text blocks) joins with "" into one
leading system message; a user message's ``tool_result`` blocks become ``tool`` messages in
order, its text blocks one message (same role) after them; an assistant's ``thinking``
becomes ``reasoning_content``, ``text`` the content, ``tool_use`` ``tool_calls`` whose
arguments are canonical JSON (sorted keys, compact); ``cache_control``, ``is_error``,
``signature`` and ``metadata`` are dropped; any other block type is dropped (and noted).
Tools become ``{"type": "function", "function": {name, description?, parameters}}``.
``thinking.type: disabled`` -> ``reasoning_effort: "none"``; ``output_config.effort`` ->
``reasoning_effort``; ``budget_tokens`` and ``adaptive`` are not mapped (noted).
``tool_choice`` auto/any/tool/none -> "auto"/"required"/named function/"none";
``stop_sequences`` -> ``stop``; ``temperature``/``top_p``/``top_k`` pass through.

Each case may name ``ref``, the case it differs from by one field: equal ``ct`` means the
field is not rendered. ``alts`` are other candidate neutral mappings, counted locally only.

Requests are sequential, idle-gated (D39), synthetic, ``max_tokens: 1``. Writes
fixtures/strata_messages/p22_messages_render_parity.json.

    uv run python eval/probes/p22_messages_render_parity.py [--only case,case] [--no-generate]
"""

from __future__ import annotations

import argparse
import copy
import json
import time
from typing import Any

from strata_common import BASE, FIXTURES, MODEL, check_build, client, wait_idle

from palimnesis.upstreams.strata import tokens

OUT = FIXTURES / "strata_messages"
OUT.mkdir(parents=True, exist_ok=True)
BUILD = "Strata 0.1.54"

# -- the neutral Chat mapping (probe-local) ----------------------------------------------------


def canonical(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _text(content: Any, notes: list[str], where: str, joiner: str = "") -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for b in content:
        if b.get("type") == "text":
            parts.append(b.get("text", ""))
        else:
            notes.append(f"{where}: {b.get('type')} block dropped")
    return joiner.join(parts)


def neutral(m: dict, *, joiner: str = "", sort_args: bool = True, text_first: bool = False,
            late_system: str = "system", description_default: str | None = None) -> tuple[dict, list[str]]:
    notes: list[str] = []
    msgs: list[dict] = []
    if m.get("system"):
        msgs.append({"role": "system", "content": _text(m["system"], notes, "system", joiner)})
    for i, msg in enumerate(m.get("messages", [])):
        role, c = msg.get("role"), msg.get("content")
        if role == "system" and (msgs or i > 0) and late_system != "system":
            role = late_system
        if isinstance(c, str):
            msgs.append({"role": role, "content": c})
            continue
        if role == "assistant":
            reasoning, text, calls = [], [], []
            for b in c:
                t = b.get("type")
                if t == "thinking":
                    reasoning.append(b.get("thinking", ""))
                elif t == "text":
                    text.append(b.get("text", ""))
                elif t == "tool_use":
                    inp = b.get("input", {})
                    calls.append({"id": b.get("id"), "type": "function", "function": {
                        "name": b.get("name"),
                        "arguments": canonical(inp) if sort_args else json.dumps(inp, ensure_ascii=False)}})
                else:
                    notes.append(f"messages[{i}]: assistant {t} block dropped")
            a: dict = {"role": "assistant", "content": joiner.join(text)}
            if reasoning:
                a["reasoning_content"] = "".join(reasoning)
            if calls:
                a["tool_calls"] = calls
            msgs.append(a)
            continue
        text, results = [], []
        for b in c:
            t = b.get("type")
            if t == "tool_result":
                results.append({"role": "tool", "tool_call_id": b.get("tool_use_id"),
                                "content": _text(b.get("content"), notes, f"messages[{i}].tool_result", joiner)})
            elif t == "text":
                text.append(b.get("text", ""))
            else:
                notes.append(f"messages[{i}]: {role} {t} block dropped")
        user = [{"role": role, "content": joiner.join(text)}] if text else []
        msgs.extend(user + results if text_first else results + user)
    body: dict = {"model": MODEL, "messages": msgs}
    if m.get("tools"):
        tools = []
        for t in m["tools"]:
            fn: dict = {"name": t["name"]}
            if "description" in t:
                fn["description"] = t["description"]
            elif description_default is not None:
                fn["description"] = description_default
            fn["parameters"] = t.get("input_schema", {})
            tools.append({"type": "function", "function": fn})
        body["tools"] = tools
    tc = m.get("tool_choice")
    if isinstance(tc, dict):
        kind = tc.get("type")
        body["tool_choice"] = {"auto": "auto", "any": "required", "none": "none"}.get(kind) or \
            {"type": "function", "function": {"name": tc.get("name")}}
    th, oc = m.get("thinking"), m.get("output_config")
    if isinstance(th, dict) and th.get("type") == "disabled":
        body["reasoning_effort"] = "none"
    elif isinstance(oc, dict) and oc.get("effort"):
        body["reasoning_effort"] = oc["effort"]
    if isinstance(th, dict) and th.get("type") != "disabled":
        notes.append(f"thinking {th} not mapped")
    for k in ("temperature", "top_p", "top_k"):
        if k in m:
            body[k] = m[k]
    if "stop_sequences" in m:
        body["stop"] = m["stop_sequences"]
    for k in m:
        if k not in ("model", "system", "messages", "tools", "tool_choice", "thinking", "output_config",
                     "temperature", "top_p", "top_k", "stop_sequences", "max_tokens", "stream"):
            notes.append(f"top-level {k} dropped")
    return body, notes


# -- cases --------------------------------------------------------------------------------------

WEATHER = {"name": "get_weather", "description": "Get the current weather for a city.",
           "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}
WRITE = {"name": "write_file", "description": "Write a text file.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"},
                                                           "content": {"type": "string"}},
                          "required": ["path", "content"]}}
SYS = "You are terse."
CC = {"type": "ephemeral"}
SIG = "EuYBCkQYAiJAk3Xf0aZ1c2lnbmF0dXJlLWJsb2ItZm9yLXByb2Jl"
BILLING = "x-anthropic-billing-header: cc_version=2.1.170.bf4; cc_entrypoint=sdk-cli; cch=b145e;"


def base(**kw) -> dict:
    return {"system": SYS, "messages": [{"role": "user", "content": "Q1"}], **kw}


def two_turn(assistant_content, **kw) -> dict:
    return {"system": SYS, "messages": [{"role": "user", "content": "Q1"},
                                        {"role": "assistant", "content": assistant_content},
                                        {"role": "user", "content": "Q2"}], **kw}


def tool_conv(result_block: dict | list, *, user_extra_after=None, user_extra_before=None, think=True,
              tool_input=None, tool=WEATHER, **kw) -> dict:
    asst = []
    if think:
        asst.append({"type": "thinking", "thinking": "I need the tool.", "signature": SIG})
    asst += [{"type": "text", "text": "Checking."},
             {"type": "tool_use", "id": "toolu_01", "name": tool["name"],
              "input": tool_input if tool_input is not None else {"city": "Paris"}}]
    blocks = list(result_block) if isinstance(result_block, list) else [result_block]
    if user_extra_after:
        blocks.append(user_extra_after)
    if user_extra_before:
        blocks.insert(0, user_extra_before)
    return {"system": SYS, "tools": [tool], "messages": [
        {"role": "user", "content": "What is the weather in Paris?"},
        {"role": "assistant", "content": asst},
        {"role": "user", "content": blocks}], **kw}


def tr(content, **kw) -> dict:
    return {"type": "tool_result", "tool_use_id": "toolu_01", "content": content, **kw}


def mid_system(top: bool, content="Hook context: the user prefers metric units.") -> dict:
    msgs = [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "A1"},
            {"role": "system", "content": content}, {"role": "user", "content": "Q2"}]
    return {"system": SYS, "messages": msgs} if top else {"messages": msgs}


def with_cc() -> dict:
    return {"system": [{"type": "text", "text": SYS, "cache_control": CC}],
            "tools": [{**WEATHER, "cache_control": CC}],
            "messages": [{"role": "user", "content": [{"type": "text", "text": "Weather?", "cache_control": CC}]},
                         {"role": "assistant", "content": [
                             {"type": "tool_use", "id": "toolu_01", "name": "get_weather",
                              "input": {"city": "Paris"}, "cache_control": CC}]},
                         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_01",
                                                       "content": "18C", "cache_control": CC}]}]}


def strip_cc(v):
    if isinstance(v, dict):
        return {k: strip_cc(x) for k, x in v.items() if k != "cache_control"}
    if isinstance(v, list):
        return [strip_cc(x) for x in v]
    return v


THINK_TEXT = [{"type": "thinking", "thinking": "Short reasoning about Q1.", "signature": SIG},
              {"type": "text", "text": "A1"}]

CASES: list[dict] = [
    {"name": "base", "msg": base()},
    {"name": "base_no_system", "msg": {"messages": [{"role": "user", "content": "Q1"}]}},
    # system
    {"name": "system_blocks", "msg": base(system=[{"type": "text", "text": SYS},
                                                  {"type": "text", "text": "Answer in English."}]),
     "alts": {"join_newline": {"joiner": "\n"}, "join_blank_line": {"joiner": "\n\n"}}},
    {"name": "system_string_joined", "msg": base(system=SYS + "Answer in English.")},
    {"name": "billing_header_system", "msg": base(system=BILLING + "\n" + SYS),
     "alts": {"pinned_stamp": {"pin_billing": True}}},
    # user text blocks
    {"name": "user_multi_text", "msg": {"system": SYS, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "Part one."}, {"type": "text", "text": "Part two."}]}]},
     "alts": {"join_newline": {"joiner": "\n"}, "join_blank_line": {"joiner": "\n\n"}}},
    {"name": "user_text_joined", "msg": {"system": SYS, "messages": [
        {"role": "user", "content": "Part one.Part two."}]}},
    {"name": "assistant_multi_text", "msg": two_turn([{"type": "text", "text": "A1 part one."},
                                                      {"type": "text", "text": "A1 part two."}]),
     "alts": {"join_newline": {"joiner": "\n"}}},
    # tool results
    {"name": "tool_result_string", "msg": tool_conv(tr("18C, clear"))},
    {"name": "tool_result_text_blocks", "msg": tool_conv(tr([{"type": "text", "text": "18C,"},
                                                            {"type": "text", "text": " clear"}])),
     "ref": "tool_result_string", "alts": {"join_newline": {"joiner": "\n"}}},
    {"name": "tool_result_plain_boom", "msg": tool_conv(tr("boom: city not found"))},
    {"name": "tool_result_is_error", "msg": tool_conv(tr("boom: city not found", is_error=True)),
     "ref": "tool_result_plain_boom"},
    {"name": "tool_result_then_text", "msg": tool_conv(tr("18C, clear"),
                                                       user_extra_after={"type": "text", "text": "Now summarize."})},
    {"name": "text_then_tool_result", "msg": tool_conv(tr("18C, clear"),
                                                       user_extra_before={"type": "text", "text": "Now summarize."}),
     "ref": "tool_result_then_text", "alts": {"text_first": {"text_first": True}}},
    {"name": "tool_use_unsorted_input", "msg": tool_conv(tr("ok"), tool=WRITE,
                                                         tool_input={"path": "a.txt", "content": "hi"}),
     "alts": {"insertion_order_args": {"sort_args": False}}},
    {"name": "tool_use_sorted_input", "msg": tool_conv(tr("ok"), tool=WRITE,
                                                       tool_input={"content": "hi", "path": "a.txt"}),
     "ref": "tool_use_unsorted_input"},
    {"name": "tool_no_description", "msg": base(tools=[{k: v for k, v in WEATHER.items() if k != "description"}]),
     "alts": {"description_empty": {"description_default": ""}}},
    {"name": "tools_only", "msg": base(tools=[WEATHER])},
    # mid-conversation system
    {"name": "mid_system_with_top", "msg": mid_system(True),
     "alts": {"late_system_as_user": {"late_system": "user"}}},
    {"name": "mid_system_as_user_control", "msg": {
        "system": SYS, "messages": [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "A1"},
                                    {"role": "user", "content": "Hook context: the user prefers metric units."},
                                    {"role": "user", "content": "Q2"}]}},
    {"name": "mid_system_no_top", "msg": mid_system(False),
     "alts": {"late_system_as_user": {"late_system": "user"}}},
    {"name": "mid_system_blocks", "msg": {"system": SYS, "messages": [
        {"role": "user", "content": "Q1"}, {"role": "assistant", "content": "A1"},
        {"role": "system", "content": [{"type": "text", "text": "Hook context: the user prefers metric units."}]},
        {"role": "user", "content": "Q2"}]}, "ref": "mid_system_with_top",
     "alts": {"late_system_as_user": {"late_system": "user"}}},
    {"name": "first_message_system", "msg": {"messages": [{"role": "system", "content": SYS},
                                                          {"role": "user", "content": "Q1"}]}, "ref": "base"},
    # cache_control
    {"name": "cache_control_stripped", "msg": strip_cc(with_cc())},
    {"name": "cache_control", "msg": with_cc(), "ref": "cache_control_stripped"},
    # thinking blocks
    {"name": "thinking_signed", "msg": two_turn(THINK_TEXT)},
    {"name": "thinking_no_signature", "msg": two_turn([{"type": "thinking", "thinking": "Short reasoning about Q1."},
                                                       {"type": "text", "text": "A1"}]), "ref": "thinking_signed"},
    {"name": "thinking_empty_signature", "msg": two_turn([{"type": "thinking", "thinking": "Short reasoning about Q1.",
                                                          "signature": ""}, {"type": "text", "text": "A1"}]),
     "ref": "thinking_signed"},
    {"name": "no_thinking_prior", "msg": two_turn([{"type": "text", "text": "A1"}])},
    {"name": "redacted_thinking", "msg": two_turn([{"type": "redacted_thinking", "data": "opaque-bytes"},
                                                   {"type": "text", "text": "A1"}]), "ref": "no_thinking_prior"},
    # thinking / effort request fields
    {"name": "thinking_adaptive", "msg": base(thinking={"type": "adaptive"}), "ref": "base"},
    {"name": "thinking_enabled_no_budget", "msg": base(thinking={"type": "enabled"}), "ref": "base"},
    {"name": "budget_1024", "msg": base(thinking={"type": "enabled", "budget_tokens": 1024}), "ref": "base",
     "alts": {"as_effort_low": {"effort": "low"}}},
    {"name": "budget_4096", "msg": base(thinking={"type": "enabled", "budget_tokens": 4096}), "ref": "base",
     "alts": {"as_effort_medium": {"effort": "medium"}}},
    {"name": "budget_16000", "msg": base(thinking={"type": "enabled", "budget_tokens": 16000}), "ref": "base",
     "alts": {"as_effort_xhigh": {"effort": "xhigh"}}},
    {"name": "thinking_disabled", "msg": base(thinking={"type": "disabled"}), "ref": "base"},
    {"name": "effort_low", "msg": base(output_config={"effort": "low"}), "ref": "base"},
    {"name": "effort_medium", "msg": base(output_config={"effort": "medium"}), "ref": "base"},
    {"name": "effort_high", "msg": base(output_config={"effort": "high"}), "ref": "base"},
    {"name": "effort_xhigh", "msg": base(output_config={"effort": "xhigh"}), "ref": "base"},
    {"name": "effort_max", "msg": base(output_config={"effort": "max"}), "ref": "base",
     "alts": {"as_effort_xhigh": {"effort": "xhigh"}}},
    {"name": "effort_bogus", "msg": base(output_config={"effort": "bogus"}), "ref": "base"},
    {"name": "disabled_plus_effort_low", "msg": base(thinking={"type": "disabled"}, output_config={"effort": "low"}),
     "ref": "thinking_disabled"},
    # tool_choice
    {"name": "tool_choice_auto", "msg": base(tools=[WEATHER], tool_choice={"type": "auto"}), "ref": "tools_only"},
    {"name": "tool_choice_any", "msg": base(tools=[WEATHER], tool_choice={"type": "any"}), "ref": "tools_only"},
    {"name": "tool_choice_tool", "msg": base(tools=[WEATHER], tool_choice={"type": "tool", "name": "get_weather"}),
     "ref": "tools_only"},
    {"name": "tool_choice_none", "msg": base(tools=[WEATHER], tool_choice={"type": "none"}), "ref": "tools_only"},
    {"name": "tool_choice_auto_no_parallel", "msg": base(tools=[WEATHER], tool_choice={
        "type": "auto", "disable_parallel_tool_use": True}), "ref": "tools_only"},
    # sampling and other fields
    {"name": "top_k", "msg": base(top_k=5), "ref": "base"},
    {"name": "top_k_string", "msg": base(top_k="5"), "ref": "base"},
    {"name": "temperature_top_p", "msg": base(temperature=0.2, top_p=0.9), "ref": "base"},
    {"name": "stop_sequences", "msg": base(stop_sequences=["END"]), "ref": "base"},
    {"name": "stop_sequences_string", "msg": base(stop_sequences="END"), "ref": "base"},
    {"name": "metadata", "msg": base(metadata={"user_id": "user-123"}), "ref": "base"},
    {"name": "unknown_top_level_field", "msg": base(palimnesis_probe_unknown={"x": 1}), "ref": "base"},
    {"name": "document_block", "msg": {"system": SYS, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "Q1"},
        {"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": "doc body"}}]}]},
     "ref": "base"},
    {"name": "unknown_role", "msg": {"messages": [{"role": "bot", "content": "Q1"}]}},
]


# -- measurement --------------------------------------------------------------------------------


def pin_billing(system: str) -> str:
    """The stamp pinning Strata's Messages path applies (0.1.54 frontend ``pin_billing_stamp``), for the alt."""
    import re
    s = re.sub(r"cch=([0-9a-zA-Z]+);", lambda m: "cch=" + "f" * len(m.group(1)) + ";", system, count=1)
    return re.sub(r"(cc_version=\d+\.\d+\.\d+\.)([^;]+);", lambda m: m.group(1) + "f" * len(m.group(2)) + ";", s,
                  count=1)


def local_count(chat: dict, effort: str | None = None) -> dict:
    try:
        args = tokens.render_args_from_openai(chat)
        if effort is not None:
            args["effort"] = effort
        return {"count": tokens.default().count_messages(**args)}
    except Exception as exc:  # the counter may refuse a shape Strata accepts
        return {"error": f"{type(exc).__name__}: {exc}"}


def local_render(chat: dict) -> str | None:
    try:
        return tokens.default().render(**tokens.render_args_from_openai(chat))
    except Exception:
        return None


def post(c, path: str, body: dict) -> dict:
    t0 = time.monotonic()
    r = c.post(path, json=body)
    out: dict = {"status": r.status_code, "elapsed_s": round(time.monotonic() - t0, 3)}
    try:
        j = r.json()
    except ValueError:
        return {**out, "text": r.text[:500]}
    if r.status_code != 200:
        return {**out, "error": j}
    if path == "/v1/messages/count_tokens":
        out["input_tokens"] = j.get("input_tokens")
    elif path == "/v1/messages":
        u = j.get("usage") or {}
        out["usage"] = u
        out["prompt"] = sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                                    "cache_read_input_tokens"))
        out["stop_reason"] = j.get("stop_reason")
        out["content_types"] = [b.get("type") for b in j.get("content", [])]
    else:
        u = j.get("usage") or {}
        out["prompt"] = u.get("prompt_tokens")
        out["cached"] = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
        out["finish_reason"] = (j.get("choices") or [{}])[0].get("finish_reason")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--no-generate", action="store_true", help="count_tokens and local only")
    a = ap.parse_args()
    props = check_build(BUILD)
    only = [x for x in a.only.split(",") if x]
    results: dict = {"base": BASE, "build": props.get("build_info"),
                     "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "cases": []}
    by_name: dict[str, dict] = {}
    with client(600) as c:
        for case in CASES:
            if only and case["name"] not in only:
                continue
            msg = {"model": MODEL, **copy.deepcopy(case["msg"])}
            chat, notes = neutral(msg)
            row: dict = {"name": case["name"], "ref": case.get("ref"), "messages_body": msg, "chat_body": chat,
                         "mapping_notes": notes}
            row["ct"] = post(c, "/v1/messages/count_tokens", msg)
            row["local"] = local_count(chat)
            if not a.no_generate:
                wait_idle(quiet=1.0)
                row["mr"] = post(c, "/v1/messages", {**msg, "max_tokens": 1, "stream": False})
                wait_idle(quiet=1.0)
                row["cr"] = post(c, "/v1/chat/completions", {**chat, "max_tokens": 1, "stream": False})
            alts = {}
            for alt, kw in (case.get("alts") or {}).items():
                kw = dict(kw)
                effort = kw.pop("effort", None)
                pin = kw.pop("pin_billing", False)
                m2 = copy.deepcopy(msg)
                if pin:
                    m2["system"] = pin_billing(m2["system"])
                alt_chat, _ = neutral(m2, **kw)
                alts[alt] = {"local": local_count(alt_chat, effort),
                             "render_equals_neutral": local_render(alt_chat) == local_render(chat)}
            if alts:
                row["alts"] = alts
            ct = row["ct"].get("input_tokens")
            row["ct_equals_local"] = ct is not None and ct == row["local"].get("count")
            if "mr" in row:
                row["ct_equals_mr"] = ct is not None and ct == row["mr"].get("prompt")
                row["mr_equals_cr"] = row["mr"].get("prompt") is not None and \
                    row["mr"].get("prompt") == row["cr"].get("prompt")
            ref = by_name.get(case.get("ref") or "")
            if ref is not None:
                rct = ref["ct"].get("input_tokens")
                if row["ct"]["status"] != 200 or row.get("mr", {}).get("status", 200) != 200:
                    row["field_class"] = "400"
                elif ct == rct and row.get("mr", {}).get("prompt") == ref.get("mr", {}).get("prompt"):
                    row["field_class"] = "not rendered (count equals ref)"
                else:
                    row["field_class"] = f"rendered (ct {ct} vs ref {rct})"
            by_name[case["name"]] = row
            results["cases"].append(row)
            print(f"{case['name']:32s} ct={row['ct'].get('input_tokens', row['ct']['status'])!s:>5} "
                  f"mr={row.get('mr', {}).get('prompt', row.get('mr', {}).get('status'))!s:>5} "
                  f"local={row['local'].get('count', 'ERR')!s:>5} "
                  f"cr={row.get('cr', {}).get('prompt', row.get('cr', {}).get('status'))!s:>5} "
                  f"{row.get('field_class', '')} {('alts=' + json.dumps({k: v['local'].get('count') for k, v in alts.items()})) if alts else ''}")
    results["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (OUT / "p22_messages_render_parity.json").write_text(
        json.dumps(results, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
