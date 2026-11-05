"""Anthropic Messages request normalization (Phase 4B S2).

``parse`` turns a ``POST /v1/messages`` body into the neutral, Chat-shaped
``chat.ChatRequest`` the core already uses (Phase 4B core positions 2 and 3). The raw
Anthropic body is what the archive stores; ``ChatRequest.chat_body`` is the neutral
Chat Completions body the upstream receives. The subset is allowlist-strict, like
D11: a field is mapped, accepted with no upstream effect, or rejected before
acceptance with ``400 unsupported_feature``. Nothing is dropped silently.

The mapping copies what Strata 0.1.54's own Messages route renders, so the neutral
Chat body gives the same tokens and reuses the same cache (``docs/probes/strata.md``
§13.2, §13.4; D82):

- ``system`` (a string or text blocks, joined with ``""``) is one leading system
  message, with Claude Code's billing stamp pinned to ``f``s as Strata pins it.
- A user message's ``tool_result`` blocks become ``tool`` messages, in order, and its
  text blocks one ``user`` message after them, joined with ``""``. A tool result's
  text blocks join with ``""``.
- An assistant message's ``thinking`` blocks become ``reasoning_content``, its text
  blocks the content, and its ``tool_use`` blocks ``tool_calls`` whose arguments are
  the input serialized in the client's own key order (sorting the keys changes the
  tokens, M2/M4). With no text, the content is null.
- A ``system`` message after the first position renders as a ``user`` message in
  place (O-4B-12); a first-position one stays a system message.
- ``cache_control``, ``signature``, ``is_error``, ``metadata`` and
  ``eager_input_streaming`` have no upstream effect and are left out of the neutral
  form, so a moving cache breakpoint never changes a message's content hash, and a
  single text block equals the same string (Claude Code's resends, HC3/HC7).
- A tool without ``description`` renders with ``description: ""``.
- Thinking: ``disabled`` is ``reasoning_effort: "none"`` and wins; otherwise
  ``output_config.effort`` maps (``max`` to ``xhigh``, as Strata maps it); otherwise
  ``budget_tokens`` maps to a level (under 2,048 low, under 8,192 medium, else
  xhigh). Strata's Messages route also applies the budget as a hard reasoning cap;
  the neutral Chat body does not (D84).
"""

from __future__ import annotations

import json
from typing import Any

from palimnesis.protocols import chat
from palimnesis.protocols.chat import (
    RESERVED_PREFIX,
    ChatRequest,
    Envelope,
    InvalidBody,
    Message,
    Unsupported,
    _find_ambiguity,
    _object_pairs,
    _require,
)

ENDPOINT = "/v1/messages"

_TOP_LEVEL = frozenset({
    "model", "max_tokens", "stream", "system", "messages", "tools", "tool_choice",
    "thinking", "output_config", "metadata", "temperature", "top_p",
})
TRANSPORT_FIELDS = frozenset({"stream"})
_MESSAGE_KEYS = frozenset({"role", "content"})
_ROLES = ("user", "assistant", "system")
_BLOCK_KEYS = {
    "text": frozenset({"type", "text", "cache_control"}),
    "thinking": frozenset({"type", "thinking", "signature"}),
    "tool_use": frozenset({"type", "id", "name", "input", "cache_control"}),
    "tool_result": frozenset({"type", "tool_use_id", "content", "is_error", "cache_control"}),
}
_BLOCKS_BY_ROLE = {
    "user": ("text", "tool_result"),
    "assistant": ("text", "thinking", "tool_use"),
    "system": ("text",),
}
_TOOL_KEYS = frozenset({"name", "description", "input_schema", "cache_control",
                        "eager_input_streaming"})
_CACHE_CONTROL_KEYS = frozenset({"type", "ttl"})
_THINKING_KEYS = frozenset({"type", "budget_tokens", "display"})
# Client effort words -> the Chat route's reasoning_effort (Strata maps max to xhigh).
EFFORTS = {"low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "xhigh"}
BILLING_HEADER = "x-anthropic-billing-header:"


def _check_keys(obj: dict[str, Any], allowed: frozenset[str], prefix: str) -> None:
    for key in obj:
        _require(key in allowed, f"{prefix}{key}", "field is not supported")


def _check_cache_control(block: dict[str, Any], path: str) -> None:
    if "cache_control" in block:
        cc = block["cache_control"]
        _require(isinstance(cc, dict), f"{path}.cache_control", "cache_control must be an object")
        _check_keys(cc, _CACHE_CONTROL_KEYS, f"{path}.cache_control.")
        _require(cc.get("type") == "ephemeral", f"{path}.cache_control.type",
                 'only "ephemeral" cache_control is supported')


def _text_blocks(content: Any, path: str) -> str:
    """A string, or a list of text blocks joined with "" as Strata joins them."""
    if isinstance(content, str):
        return content
    _require(isinstance(content, list), path, "content must be a string or an array of text blocks")
    out = []
    for j, block in enumerate(content):
        bpath = f"{path}[{j}]"
        _require(isinstance(block, dict), bpath, "content block must be an object")
        _require(block.get("type") == "text", f"{bpath}.type",
                 f"block type {block.get('type')!r} is not supported here")
        _check_keys(block, _BLOCK_KEYS["text"], f"{bpath}.")
        _require(isinstance(block.get("text"), str), f"{bpath}.text", "text must be a string")
        _check_cache_control(block, bpath)
        out.append(block["text"])
    return "".join(out)


def pin_billing_stamp(system: str) -> str:
    """Strata 0.1.54's ``pin_billing_stamp``: Claude Code's per-request ``cch=`` and
    per-session ``cc_version`` fourth part, at the very start of the system text and
    inside its first 160 characters, become ``f``s, so the system prefix is stable."""
    if not system.startswith(BILLING_HEADER):
        return system
    s = list(system)
    cch = system.find("cch=", len(BILLING_HEADER))
    if 0 <= cch <= 160:
        v, end = cch + 4, system.find(";", cch + 4)
        if end > v and end - v <= 16:
            s[v:end] = "f" * (end - v)
    cv = system.find("cc_version=")
    if 0 <= cv <= 160:
        v, end = cv + len("cc_version="), system.find(";", cv)
        if v < end and end - v <= 64:
            parts = system[v:end].split(".")
            if len(parts) > 3:
                tail = v + len(".".join(parts[:3])) + 1
                s[tail:end] = "f" * (end - tail)
    return "".join(s)


def arguments(value: Any) -> str:
    """A ``tool_use`` input as Chat arguments: compact JSON in the client's key order."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _message(obj: dict[str, Any]) -> Message:
    """A neutral message built from a Chat-shaped object, exactly as ``chat.parse``
    would build it, so the archive treats both protocols' messages alike."""
    form = "null" if obj.get("content", "") is None else "string"
    return Message(role=obj["role"], blocks=chat._blocks(obj),
                   envelope=Envelope(tuple(obj), form, obj))


def _split_user(content: list, path: str, role: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    texts: list[str] = []
    for j, block in enumerate(content):
        bpath = f"{path}[{j}]"
        kind = _block_kind(block, bpath, role)
        if kind == "tool_result":
            _require(isinstance(block.get("tool_use_id"), str), f"{bpath}.tool_use_id",
                     "tool_use_id must be a string")
            if "is_error" in block:
                _require(isinstance(block["is_error"], bool), f"{bpath}.is_error",
                         "is_error must be a boolean")
            text = _text_blocks(block.get("content", ""), f"{bpath}.content")
            results.append({"role": "tool", "tool_call_id": block["tool_use_id"],
                            "content": text})
        else:
            texts.append(block["text"])
    # Strata renders a message's tool results first, then its text (M2).
    return results + ([{"role": role, "content": "".join(texts)}] if texts else [])


def _split_assistant(content: list, path: str) -> dict[str, Any]:
    reasoning: list[str] = []
    texts: list[str] = []
    calls: list[dict[str, Any]] = []
    for j, block in enumerate(content):
        bpath = f"{path}[{j}]"
        kind = _block_kind(block, bpath, "assistant")
        if kind == "thinking":
            _require(isinstance(block.get("thinking"), str), f"{bpath}.thinking",
                     "thinking must be a string")
            if "signature" in block:
                _require(isinstance(block["signature"], str), f"{bpath}.signature",
                         "signature must be a string")
            reasoning.append(block["thinking"])
        elif kind == "text":
            texts.append(block["text"])
        else:
            _require(isinstance(block.get("id"), str), f"{bpath}.id", "id must be a string")
            _require(isinstance(block.get("name"), str), f"{bpath}.name", "name must be a string")
            _require(not block["name"].startswith(RESERVED_PREFIX), f"{bpath}.name",
                     f"the {RESERVED_PREFIX} prefix is reserved for Palimnesis's own tools")
            _require(isinstance(block.get("input"), dict), f"{bpath}.input",
                     "input must be an object")
            calls.append({"id": block["id"], "type": "function",
                          "function": {"name": block["name"], "arguments": arguments(block["input"])}})
    out: dict[str, Any] = {"role": "assistant", "content": "".join(texts) if texts else None}
    if reasoning:
        out["reasoning_content"] = "".join(reasoning)
    if calls:
        out["tool_calls"] = calls
    return out


def _block_kind(block: Any, path: str, role: str) -> str:
    _require(isinstance(block, dict), path, "content block must be an object")
    kind = block.get("type")
    _require(kind in _BLOCKS_BY_ROLE[role], f"{path}.type",
             f"block type {kind!r} is not supported in a {role} message")
    _check_keys(block, _BLOCK_KEYS[kind], f"{path}.")
    if kind == "text":
        _require(isinstance(block.get("text"), str), f"{path}.text", "text must be a string")
    _check_cache_control(block, path)
    return kind


def _neutral_messages(obj: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if "system" in obj:
        system = _text_blocks(obj["system"], "system")
        if system:
            out.append({"role": "system", "content": pin_billing_stamp(system)})
    for i, m in enumerate(obj["messages"]):
        path = f"messages[{i}]"
        _require(isinstance(m, dict), path, "message must be an object")
        role = m.get("role")
        _require(role in _ROLES, f"{path}.role", f"role {role!r} is not supported")
        _check_keys(m, _MESSAGE_KEYS, f"{path}.")
        content = m.get("content")
        _require(isinstance(content, (str, list)), f"{path}.content",
                 "content must be a string or an array of content blocks")
        _require(content != [], f"{path}.content", "content must not be empty")
        if role == "system":
            # Strata renders a system message after the first position as a user message,
            # in place (M2, O-4B-12).
            role = "system" if not out and i == 0 else "user"
            out.append({"role": role, "content": _text_blocks(content, f"{path}.content")})
        elif isinstance(content, str):
            out.append({"role": role, "content": content})
        elif role == "assistant":
            out.append(_split_assistant(content, f"{path}.content"))
        else:
            out.extend(_split_user(content, f"{path}.content", role))
    return out


def _tools(tools: Any) -> list[dict[str, Any]]:
    _require(isinstance(tools, list), "tools", "tools must be an array")
    out = []
    for i, tool in enumerate(tools):
        path = f"tools[{i}]"
        _require(isinstance(tool, dict), path, "tool must be an object")
        _check_keys(tool, _TOOL_KEYS, f"{path}.")
        _require(isinstance(tool.get("name"), str), f"{path}.name", "name must be a string")
        _require(not tool["name"].startswith(RESERVED_PREFIX), f"{path}.name",
                 f"the {RESERVED_PREFIX} prefix is reserved for Palimnesis's own tools")
        if "description" in tool:
            _require(isinstance(tool["description"], str), f"{path}.description",
                     "description must be a string")
        _require(isinstance(tool.get("input_schema"), dict), f"{path}.input_schema",
                 "input_schema must be an object")
        if "eager_input_streaming" in tool:
            _require(isinstance(tool["eager_input_streaming"], bool),
                     f"{path}.eager_input_streaming", "must be a boolean")
        _check_cache_control(tool, path)
        out.append({"type": "function", "function": {
            "name": tool["name"], "description": tool.get("description", ""),
            "parameters": tool["input_schema"]}})
    return out


def _tool_choice(value: Any) -> str:
    _require(isinstance(value, dict), "tool_choice", "tool_choice must be an object")
    _require(value.get("type") in ("auto", "none"), "tool_choice.type",
             'only tool_choice "auto" or "none" is supported')
    _check_keys(value, frozenset({"type"}), "tool_choice.")
    return value["type"]


def _effort(obj: dict[str, Any]) -> str | None:
    thinking = obj.get("thinking")
    if thinking is not None:
        _require(isinstance(thinking, dict), "thinking", "thinking must be an object")
        _check_keys(thinking, _THINKING_KEYS, "thinking.")
        _require(thinking.get("type") in ("enabled", "disabled", "adaptive"), "thinking.type",
                 'thinking type must be "enabled", "disabled" or "adaptive"')
        if "budget_tokens" in thinking:
            bt = thinking["budget_tokens"]
            _require(thinking["type"] == "enabled", "thinking.budget_tokens",
                     'budget_tokens needs thinking type "enabled"')
            _require(isinstance(bt, int) and not isinstance(bt, bool) and bt > 0,
                     "thinking.budget_tokens", "budget_tokens must be a positive integer")
        if "display" in thinking:
            _require(thinking["display"] in ("summarized", "omitted"), "thinking.display",
                     'display must be "summarized" or "omitted"')
    effort = None
    if "output_config" in obj:
        oc = obj["output_config"]
        _require(isinstance(oc, dict), "output_config", "output_config must be an object")
        _check_keys(oc, frozenset({"effort"}), "output_config.")
        if "effort" in oc:
            _require(oc["effort"] in EFFORTS, "output_config.effort",
                     f"effort must be one of {', '.join(EFFORTS)}")
            effort = EFFORTS[oc["effort"]]
    if thinking is not None and thinking["type"] == "disabled":
        return "none"
    if effort is not None:
        return effort
    if thinking is not None and "budget_tokens" in thinking:
        bt = thinking["budget_tokens"]
        return "low" if bt < 2048 else "medium" if bt < 8192 else "xhigh"
    return None


def _check_top_level(obj: dict[str, Any]) -> None:
    _check_keys(obj, _TOP_LEVEL, "")
    if "model" in obj:
        _require(isinstance(obj["model"], str), "model", "model must be a string")
    mt = obj.get("max_tokens")
    _require(isinstance(mt, int) and not isinstance(mt, bool) and mt > 0, "max_tokens",
             "max_tokens must be a positive integer")
    if "stream" in obj:
        _require(isinstance(obj["stream"], bool), "stream", "stream must be a boolean")
    for k in ("temperature", "top_p"):
        if k in obj:
            _require(isinstance(obj[k], (int, float)) and not isinstance(obj[k], bool), k,
                     f"{k} must be a number")
    if "metadata" in obj:
        md = obj["metadata"]
        _require(isinstance(md, dict), "metadata", "metadata must be an object")
        _check_keys(md, frozenset({"user_id"}), "metadata.")
        if "user_id" in md:
            _require(isinstance(md["user_id"], str), "metadata.user_id", "user_id must be a string")


def parse(body: bytes) -> ChatRequest:
    ambiguous = False

    def pairs(p: list[tuple[str, Any]]) -> dict[str, Any]:
        nonlocal ambiguous
        out = _object_pairs(p)
        ambiguous |= isinstance(out, chat._DuplicateKeys)
        return out

    def constant(name: str) -> chat._NonFinite:
        nonlocal ambiguous
        ambiguous = True
        return chat._NonFinite(name)

    try:
        obj = json.loads(body.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise InvalidBody(f"request body is not valid JSON: {e}") from None
    if ambiguous:
        found = _find_ambiguity(obj, "")
        assert found is not None
        raise Unsupported(*found)
    if not isinstance(obj, dict):
        raise InvalidBody("request body must be a JSON object")
    if not isinstance(obj.get("messages"), list):
        raise InvalidBody("'messages' must be an array")
    if not obj["messages"]:
        raise InvalidBody("'messages' must not be empty")
    _check_top_level(obj)
    messages = _neutral_messages(obj)
    _require(bool(messages) and messages[-1]["role"] != "assistant",
             f"messages[{len(obj['messages']) - 1}]",
             "a trailing assistant message (prefill) is not supported")
    tools = _tools(obj["tools"]) if "tools" in obj else None
    tool_choice = _tool_choice(obj["tool_choice"]) if "tool_choice" in obj else None
    effort = _effort(obj)
    stream = obj.get("stream", False)

    # The neutral Chat body's top-level fields, in the client's order.
    settings: dict[str, Any] = {}
    order: list[str] = []
    for key in obj:
        if key in ("system", "metadata"):
            continue
        if key in ("thinking", "output_config"):
            if effort is not None and "reasoning_effort" not in settings:
                settings["reasoning_effort"] = effort
                order.append("reasoning_effort")
            continue
        if key == "messages":
            order.append("messages")
        elif key == "stream":
            order.append("stream")
            if stream:
                order.append("stream_options")
        elif key == "tools":
            settings["tools"] = tools
            order.append("tools")
        elif key == "tool_choice":
            settings["tool_choice"] = tool_choice
            order.append("tool_choice")
        else:
            settings[key] = obj[key]
            order.append(key)
    stream_options = {"include_usage": True} if stream else None
    doc: dict[str, Any] = {}
    for key in order:
        doc[key] = (messages if key == "messages" else stream if key == "stream"
                    else stream_options if key == "stream_options" else settings[key])
    neutral = chat._LONE_SURROGATE.sub(chat._escape_surrogate, json.dumps(
        doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False)).encode("utf-8")
    return ChatRequest(
        messages=tuple(_message(m) for m in messages),
        settings=settings,
        stream=stream,
        stream_options=stream_options,
        top_level_order=tuple(order),
        raw=body,
        neutral=neutral,
    )

