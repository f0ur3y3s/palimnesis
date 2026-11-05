"""Probe 24 (Phase 4B, S0 M4, and M2 by cache): cross-dialect prefix reuse on Strata 0.1.54.

Part A, token identity (supports M2, where counts cannot see order): for a case from p22,
a fresh nonce and ~300 tokens of filler go at the start of the first user message; the
Messages body is sent to ``/v1/messages`` (``max_tokens: 1``), then its neutral Chat body
(p22's ``neutral()``) to ``/v1/chat/completions`` (``max_tokens: 1``). Strata's conversation
cache checkpoints the first prompt at its generation start (docs/probes/strata.md §7), so
the Chat call reuses nearly all of it (``cached >= prompt - 16``: the generation prompt is
re-read) only if both routes produced the same tokens up to there; otherwise reuse falls to
0 (the nonce rules out older checkpoints). Candidate fixes (``alts``) are sent after it.

Part B, M4 extension: a conversation primed through one dialect is extended by one turn
through the other (and a same-dialect control). Records cached tokens, Chat ``timings``, and
``/metrics`` ``reused``/``prompt_read``. Also a tool loop (tool_use arguments resent as
canonical sorted JSON vs insertion order) and Claude Code's billing-header stamp (two
requests differing only in ``cch``) on each dialect.

Sequential, idle-gated (D39), synthetic. Writes fixtures/strata_messages/p24_cross_dialect_cache.json.

    uv run python eval/probes/p24_cross_dialect_cache.py [--part A|B|AB]
"""

from __future__ import annotations

import argparse
import copy
import json
import time

from p22_messages_render_parity import BILLING, CASES, SYS, WRITE, neutral, pin_billing
from strata_common import BASE, FIXTURES, MODEL, check_build, client, filler, recent_requests, wait_idle

OUT = FIXTURES / "strata_messages"
OUT.mkdir(parents=True, exist_ok=True)
BUILD = "Strata 0.1.54"
HIT_SLACK = 16

# case name -> {alt name: (neutral kwargs, chat-body overrides)}
IDENTITY: dict[str, dict[str, tuple[dict, dict]]] = {
    "base": {},
    "system_blocks": {},
    "user_multi_text": {},
    "assistant_multi_text": {},
    "tool_result_text_blocks": {},
    "tool_result_is_error": {},
    "tool_result_then_text": {},
    "text_then_tool_result": {"text_first": ({"text_first": True}, {})},
    "tool_use_unsorted_input": {"insertion_order_args": ({"sort_args": False}, {})},
    "tool_no_description": {"description_empty": ({"description_default": ""}, {})},
    "mid_system_with_top": {"late_system_as_user": ({"late_system": "user"}, {})},
    "first_message_system": {},
    "cache_control": {},
    "thinking_signed": {},
    "redacted_thinking": {},
    "document_block": {},
    "billing_header_system": {"pinned_stamp": ({}, {"_pin": True})},
    "budget_4096": {"as_effort_medium": ({}, {"reasoning_effort": "medium"})},
    "effort_max": {},
    "tool_choice_none": {},
}


def with_nonce(msg: dict, tag: str) -> dict:
    m = copy.deepcopy(msg)
    pre = f"[{tag} {time.time_ns()}]\n" + filler(140, seed=2400) + "\n\n"
    for x in m["messages"]:
        if x["role"] != "user":
            continue
        if isinstance(x["content"], str):
            x["content"] = pre + x["content"]
            return m
        for b in x["content"]:
            if b.get("type") == "text":
                b["text"] = pre + b["text"]
                return m
    raise ValueError("no user text to carry the nonce")


def post(c, path: str, body: dict) -> dict:
    wait_idle(quiet=1.0)
    t0 = time.monotonic()
    r = c.post(path, json=body)
    out: dict = {"status": r.status_code, "elapsed_s": round(time.monotonic() - t0, 3)}
    j = r.json()
    if r.status_code != 200:
        return {**out, "error": j}
    u = j.get("usage") or {}
    if path.startswith("/v1/messages"):
        out["prompt"] = sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                                    "cache_read_input_tokens"))
        out["cached"] = u.get("cache_read_input_tokens")
        out["completion"] = u.get("output_tokens")
        out["content"] = j.get("content")
        out["stop_reason"] = j.get("stop_reason")
    else:
        out["prompt"] = u.get("prompt_tokens")
        out["cached"] = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
        out["completion"] = u.get("completion_tokens")
        out["timings"] = j.get("timings")
        ch = (j.get("choices") or [{}])[0]
        out["message"] = ch.get("message")
        out["finish_reason"] = ch.get("finish_reason")
    rec = recent_requests(1)
    if rec:
        out["metrics"] = {k: rec[0].get(k) for k in ("prompt_tokens", "reused", "prompt_read", "finish")}
    return out


def hit(prev_prompt: int | None, r: dict) -> bool | None:
    if r.get("cached") is None or prev_prompt is None:
        return None
    return r["cached"] >= min(prev_prompt, r["prompt"]) - HIT_SLACK


def part_a(c) -> list[dict]:
    by_name = {x["name"]: x for x in CASES}
    rows = []
    for name, alts in IDENTITY.items():
        msg = with_nonce({"model": MODEL, **by_name[name]["msg"]}, f"A:{name}")
        chat, notes = neutral(msg)
        m = post(c, "/v1/messages", {**msg, "max_tokens": 1, "stream": False})
        ch = post(c, "/v1/chat/completions", {**chat, "max_tokens": 1, "stream": False})
        row = {"name": name, "messages": {k: m.get(k) for k in ("status", "prompt", "cached", "metrics", "error")},
               "chat_neutral": {k: ch.get(k) for k in ("status", "prompt", "cached", "metrics", "error")},
               "neutral_hit": hit(m.get("prompt"), ch), "mapping_notes": notes, "alts": {}}
        for alt, (kw, over) in alts.items():
            m2 = copy.deepcopy(msg)
            over = dict(over)
            if over.pop("_pin", False):
                m2["system"] = pin_billing(m2["system"])
            alt_chat, _ = neutral(m2, **kw)
            alt_chat.update(over)
            a = post(c, "/v1/chat/completions", {**alt_chat, "max_tokens": 1, "stream": False})
            row["alts"][alt] = {**{k: a.get(k) for k in ("status", "prompt", "cached", "metrics", "error")},
                                "hit": hit(m.get("prompt"), a)}
        rows.append(row)
        print(f"A {name:26s} msg={m.get('prompt')} chat={ch.get('prompt')} cached={ch.get('cached')} "
              f"hit={row['neutral_hit']} " + " ".join(f"{k}:{v['prompt']}/{v['cached']}/{v['hit']}"
                                                       for k, v in row["alts"].items()))
    return rows


# -- part B ----------------------------------------------------------------------------------------

def opening(tag: str) -> str:
    return f"[{tag} {time.time_ns()}]\n" + filler(700, seed=2401) + "\n\nSummarize the text above in one sentence."


def msgs_reply_blocks(r: dict) -> list[dict]:
    return [b for b in (r.get("content") or []) if b.get("type") in ("thinking", "text", "tool_use")]


def chat_reply_message(r: dict) -> dict:
    m = r.get("message") or {}
    out = {"role": "assistant", "content": m.get("content") or ""}
    if m.get("reasoning_content"):
        out["reasoning_content"] = m["reasoning_content"]
    return out


def chat_reply_as_blocks(r: dict) -> list[dict]:
    m = r.get("message") or {}
    blocks = []
    if m.get("reasoning_content"):
        blocks.append({"type": "thinking", "thinking": m["reasoning_content"], "signature": ""})
    blocks.append({"type": "text", "text": m.get("content") or ""})
    return blocks


def scenario(c, name: str, prime: str, extend: str, think: bool) -> dict:
    q1, q2 = opening(f"B:{name}"), "Now give one word from it."
    msg_think = {"output_config": {"effort": "low"}} if think else {"thinking": {"type": "disabled"}}
    chat_think = {"reasoning_effort": "low" if think else "none"}
    mt1 = 1024 if think else 48
    if prime == "messages":
        p = post(c, "/v1/messages", {"model": MODEL, "system": SYS, "max_tokens": mt1, **msg_think,
                                     "messages": [{"role": "user", "content": q1}]})
        asst_blocks = msgs_reply_blocks(p)
        asst_chat, _ = neutral({"messages": [{"role": "assistant", "content": asst_blocks}]})
        asst_chat_msg = asst_chat["messages"][0]
    else:
        p = post(c, "/v1/chat/completions", {"model": MODEL, "max_tokens": mt1, **chat_think,
                                             "messages": [{"role": "system", "content": SYS},
                                                          {"role": "user", "content": q1}]})
        asst_blocks = chat_reply_as_blocks(p)
        asst_chat_msg = chat_reply_message(p)
    if extend == "messages":
        e = post(c, "/v1/messages", {"model": MODEL, "system": SYS, "max_tokens": 8, **msg_think, "messages": [
            {"role": "user", "content": q1}, {"role": "assistant", "content": asst_blocks},
            {"role": "user", "content": q2}]})
    else:
        e = post(c, "/v1/chat/completions", {"model": MODEL, "max_tokens": 8, **chat_think, "messages": [
            {"role": "system", "content": SYS}, {"role": "user", "content": q1}, asst_chat_msg,
            {"role": "user", "content": q2}]})
    pc = (p.get("prompt") or 0) + (p.get("completion") or 0)
    row = {"name": name, "prime": prime, "extend": extend, "think": think,
           "prime_result": {k: p.get(k) for k in ("status", "prompt", "completion", "cached", "metrics",
                                                  "stop_reason", "finish_reason")},
           "extend_result": {k: e.get(k) for k in ("status", "prompt", "completion", "cached", "timings", "metrics")},
           "prime_prompt_plus_completion": pc,
           "delta_cached_minus_prime_total": None if e.get("cached") is None else e["cached"] - pc,
           "assistant_blocks": [b.get("type") for b in asst_blocks]}
    print(f"B {name:28s} prime={p.get('prompt')}+{p.get('completion')} extend={e.get('prompt')} "
          f"cached={e.get('cached')} delta={row['delta_cached_minus_prime_total']}")
    return row


P_TOOL = "Use write_file to create a.txt containing the single word hi. Call the tool directly."


def tool_scenario(c, name: str, sort_args: bool) -> dict:
    q1 = f"[B:{name} {time.time_ns()}]\n" + filler(700, seed=2402) + "\n\n" + P_TOOL
    base = {"model": MODEL, "system": SYS, "tools": [WRITE], "thinking": {"type": "disabled"}}
    p = post(c, "/v1/messages", {**base, "max_tokens": 96, "messages": [{"role": "user", "content": q1}]})
    blocks = msgs_reply_blocks(p)
    uses = [b for b in blocks if b.get("type") == "tool_use"]
    results = [{"type": "tool_result", "tool_use_id": u["id"], "content": "ok"} for u in uses]
    convo = {**base, "messages": [{"role": "user", "content": q1}, {"role": "assistant", "content": blocks},
                                  {"role": "user", "content": results or "continue"}]}
    chat, _ = neutral(convo, sort_args=sort_args)
    e = post(c, "/v1/chat/completions", {**chat, "max_tokens": 8, "stream": False})
    pc = (p.get("prompt") or 0) + (p.get("completion") or 0)
    row = {"name": name, "sort_args": sort_args, "tool_inputs": [u.get("input") for u in uses],
           "resent_arguments": [tc["function"]["arguments"] for m in chat["messages"] for tc in m.get("tool_calls", [])],
           "prime_result": {k: p.get(k) for k in ("status", "prompt", "completion", "cached", "metrics", "stop_reason")},
           "extend_result": {k: e.get(k) for k in ("status", "prompt", "completion", "cached", "timings", "metrics")},
           "prime_prompt_plus_completion": pc,
           "delta_cached_minus_prime_total": None if e.get("cached") is None else e["cached"] - pc}
    print(f"B {name:28s} inputs={row['tool_inputs']} prime={p.get('prompt')}+{p.get('completion')} "
          f"extend={e.get('prompt')} cached={e.get('cached')} delta={row['delta_cached_minus_prime_total']}")
    return row


def billing_scenario(c, dialect: str) -> dict:
    q = f"[B:billing:{dialect} {time.time_ns()}]\n" + filler(300, seed=2403) + "\n\nReply with one word."
    out = {"dialect": dialect, "calls": []}
    for cch in ("b145e", "0a1b2"):
        system = BILLING.replace("b145e", cch) + "\n" + SYS
        if dialect == "messages":
            r = post(c, "/v1/messages", {"model": MODEL, "system": system, "max_tokens": 1,
                                         "thinking": {"type": "disabled"},
                                         "messages": [{"role": "user", "content": q}]})
        else:
            r = post(c, "/v1/chat/completions", {"model": MODEL, "max_tokens": 1, "reasoning_effort": "none",
                                                 "messages": [{"role": "system", "content": system},
                                                              {"role": "user", "content": q}]})
        out["calls"].append({"cch": cch, **{k: r.get(k) for k in ("status", "prompt", "cached", "metrics")}})
    print(f"B billing {dialect:9s} " + " ".join(f"{x['cch']}:{x['prompt']}/{x['cached']}" for x in out["calls"]))
    return out


def part_b(c) -> dict:
    return {
        "scenarios": [
            scenario(c, "messages_to_chat_off", "messages", "chat", False),
            scenario(c, "messages_to_chat_low", "messages", "chat", True),
            scenario(c, "chat_to_messages_off", "chat", "messages", False),
            scenario(c, "chat_to_messages_low", "chat", "messages", True),
            scenario(c, "messages_to_messages_off", "messages", "messages", False),
            scenario(c, "chat_to_chat_off", "chat", "chat", False),
        ],
        "tool_loop": [tool_scenario(c, "tool_messages_to_chat_sorted", True),
                      tool_scenario(c, "tool_messages_to_chat_insertion", False)],
        "billing_header": [billing_scenario(c, "messages"), billing_scenario(c, "chat")],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="AB")
    a = ap.parse_args()
    props = check_build(BUILD)
    results: dict = {"base": BASE, "build": props.get("build_info"), "hit_slack": HIT_SLACK,
                     "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with client(900) as c:
        if "A" in a.part:
            results["identity"] = part_a(c)
        if "B" in a.part:
            results["extension"] = part_b(c)
    results["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (OUT / "p24_cross_dialect_cache.json").write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n",
                                                     encoding="utf-8")


if __name__ == "__main__":
    main()
