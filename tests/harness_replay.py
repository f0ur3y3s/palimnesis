"""Replay recorded harness requests through the proxy (Phase 4B S8–S10).

The fault-server captures (``eval/probes/fixtures/<harness>/<run>/server.jsonl``) hold
every request body a harness sent. Repeats are elided there; these helpers restore them.
``answer_for`` turns the assistant turn a harness resent into the upstream Chat stream
that would have produced it, so a replay archives what the harness actually saw.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .archive_helpers import DONE, chunk

FIXTURES = Path(__file__).resolve().parents[1] / "eval" / "probes" / "fixtures"


def recorded(run: str) -> list[dict]:
    """Request bodies in order, with elided repeats restored: a top-level field written as
    ``{"_elided": true, "first_seq": n}`` (Claude Code captures) or ``{"$same_as_seq": n}``
    (Pi captures), and a message written as ``{"$same_as_seq": n}`` (the same position in
    request ``n``)."""
    out: list[dict] = []
    for line in (FIXTURES / run / "server.jsonl").read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        if not isinstance(d.get("body"), dict):
            continue
        body = dict(d["body"])
        for key, value in body.items():
            if isinstance(value, dict) and value.get("_elided"):
                body[key] = out[value["first_seq"] - 1][key]
            elif isinstance(value, dict) and "$same_as_seq" in value:
                body[key] = out[value["$same_as_seq"] - 1][key]
        messages = []
        for i, m in enumerate(body.get("messages", [])):
            if isinstance(m, dict) and "$same_as_seq" in m:
                m = out[m["$same_as_seq"] - 1]["messages"][i]
            assert not (isinstance(m.get("content"), dict) and m["content"].get("_elided")), m
            messages.append(m)
        body["messages"] = messages
        out.append(body)
    return out


def pi_compat(body: dict) -> dict:
    """A body Pi sent with default settings, as the adapter's compat flags send it:
    ``supportsDeveloperRole: false`` renames ``developer`` to ``system`` and
    ``supportsStore: false`` drops ``store``; nothing else changes (HP3, VERIFIED)."""
    out = {k: v for k, v in body.items() if k != "store"}
    out["messages"] = [{**m, "role": "system"} if m.get("role") == "developer" else m
                       for m in body["messages"]]
    return out


def _chat_assistant(message: dict) -> dict:
    """A resent assistant turn, Chat-shaped, from either protocol."""
    content = message.get("content")
    if isinstance(content, list):  # Anthropic blocks
        out: dict[str, Any] = {"content": "".join(b["text"] for b in content if b["type"] == "text"),
                               "reasoning_content": "".join(
                                   b["thinking"] for b in content if b["type"] == "thinking"),
                               "tool_calls": [
                                   {"id": b["id"], "function": {"name": b["name"],
                                                                "arguments": json.dumps(b["input"])}}
                                   for b in content if b["type"] == "tool_use"]}
        return out
    return {"content": content or "", "reasoning_content": message.get("reasoning_content") or "",
            "tool_calls": message.get("tool_calls") or []}


def answer_for(message: dict, usage: dict | None = None) -> list[bytes]:
    """The upstream Chat stream whose output the harness resent as ``message``."""
    a = _chat_assistant(message)
    out = [chunk({"role": "assistant", "content": ""})]
    if a["reasoning_content"]:
        out.append(chunk({"reasoning_content": a["reasoning_content"]}))
    if a["content"]:
        out.append(chunk({"content": a["content"]}))
    for i, call in enumerate(a["tool_calls"]):
        out.append(chunk({"tool_calls": [{"index": i, "id": call["id"], "type": "function",
                                          "function": {"name": call["function"]["name"],
                                                       "arguments": call["function"]["arguments"]}}]}))
    finish = "tool_calls" if a["tool_calls"] else "stop"
    out.append(chunk({}, finish))
    return out + [DONE]


def next_answer(bodies: list[dict], i: int) -> list[bytes]:
    """The answer to request ``i``: the assistant turn request ``i + 1`` resends right after
    request ``i``'s own messages, or a plain answer for the last request."""
    if i + 1 < len(bodies):
        sent = len(bodies[i]["messages"])
        following = bodies[i + 1]["messages"]
        if len(following) > sent and following[sent].get("role") == "assistant":
            return answer_for(following[sent])
    return answer_for({"role": "assistant", "content": "Done."})
