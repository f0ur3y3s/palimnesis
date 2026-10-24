"""OpenAI Chat Completions request normalization.

``parse`` turns a client body into typed messages and blocks, rejecting anything
outside the declared subset (``docs/capabilities.md``). ``render_upstream``
re-emits the client's own message objects, optionally with internal messages
spliced in (decision D10 item 9).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


class InvalidBody(ValueError):
    """The body is not a Chat Completions request at all."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class Unsupported(ValueError):
    """The request is outside the declared subset (contracts §3: 400 ``unsupported_feature``)."""

    code = "unsupported_feature"

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = f"{field}: {message}"


def _has_lone_surrogate(s: str) -> bool:
    # json.loads joins valid escaped pairs, so any surrogate left is unpaired.
    return any("\ud800" <= ch <= "\udfff" for ch in s)


@dataclass(frozen=True)
class Block:
    """One unit of message content. ``text`` is the exact decoded string;
    a tool call's ``text`` is its ``arguments`` string as sent."""

    kind: str
    text: str
    tool_call_id: str | None = None
    name: str | None = None
    encoding: str = field(init=False)

    def __post_init__(self) -> None:
        enc = "wtf-8" if _has_lone_surrogate(self.text) else "utf-8"
        object.__setattr__(self, "encoding", enc)

    def to_bytes(self) -> bytes:
        """UTF-8, or WTF-8 (decision D10 item 15) when the text has lone surrogates."""
        if self.encoding == "wtf-8":
            return self.text.encode("utf-8", "surrogatepass")
        return self.text.encode("utf-8")

    @classmethod
    def from_bytes(
        cls,
        kind: str,
        data: bytes,
        encoding: str,
        tool_call_id: str | None = None,
        name: str | None = None,
    ) -> Block:
        if encoding == "wtf-8":
            text = data.decode("utf-8", "surrogatepass")
        elif encoding == "utf-8":
            text = data.decode("utf-8")
        else:
            raise ValueError(f"unknown block encoding {encoding!r}")
        block = cls(kind, text, tool_call_id=tool_call_id, name=name)
        if block.encoding != encoding:
            raise ValueError(f"block bytes tagged {encoding} decode as {block.encoding}")
        return block


@dataclass(frozen=True)
class Envelope:
    """What re-emitting the client's message object verbatim needs.

    ``content_form`` is ``"string"``, ``"null"`` or ``"absent"``; ``object`` is the
    exact object as parsed, keys in client order."""

    key_order: tuple[str, ...]
    content_form: str
    object: dict[str, Any]


@dataclass(frozen=True)
class Message:
    role: str
    blocks: tuple[Block, ...]
    envelope: Envelope

    @property
    def raw_object(self) -> dict[str, Any]:
        return self.envelope.object


def _content_form(m: dict[str, Any]) -> str:
    if "content" not in m:
        return "absent"
    return "null" if m["content"] is None else "string"


def _blocks(m: dict[str, Any]) -> tuple[Block, ...]:
    role = m["role"]
    if role == "tool":
        return (Block("tool_result", m["content"], tool_call_id=m["tool_call_id"]),)
    out: list[Block] = []
    if "reasoning_content" in m:
        out.append(Block("reasoning", m["reasoning_content"]))
    if m.get("content") is not None:
        out.append(Block("text", m["content"]))
    for tc in m.get("tool_calls", ()):
        fn = tc["function"]
        out.append(Block("tool_call", fn["arguments"], tool_call_id=tc["id"], name=fn["name"]))
    return tuple(out)


@dataclass(frozen=True)
class ChatRequest:
    """A parsed request. ``settings`` holds the fingerprinted top-level fields that
    were present; ``stream``/``stream_options`` are transport-only (contracts §6)."""

    messages: tuple[Message, ...]
    settings: dict[str, Any]
    stream: bool
    stream_options: dict[str, Any] | None
    top_level_order: tuple[str, ...]
    raw: bytes


# Fingerprinted generation settings forwarded as sent (decision D10 item 14).
SETTINGS_FIELDS = (
    "model", "temperature", "top_p", "seed", "stop", "presence_penalty", "frequency_penalty",
    "reasoning_effort", "chat_template_kwargs", "max_completion_tokens", "max_tokens",
    "tools", "tool_choice",
)
_TOP_LEVEL = frozenset(SETTINGS_FIELDS) | {"messages", "stream", "stream_options"}
_MESSAGE_KEYS = {
    "system": frozenset({"role", "content"}),
    "user": frozenset({"role", "content"}),
    "assistant": frozenset({"role", "content", "reasoning_content", "tool_calls"}),
    "tool": frozenset({"role", "content", "tool_call_id"}),
}
_TOOL_FUNCTION_KEYS = frozenset({"name", "description", "parameters", "strict"})


def _require(ok: bool, field_path: str, what: str) -> None:
    if not ok:
        raise Unsupported(field_path, what)


def _check_keys(obj: dict[str, Any], allowed: frozenset[str], prefix: str) -> None:
    for key in obj:
        _require(key in allowed, f"{prefix}{key}", "field is not supported")


def _check_tool_call(tc: Any, path: str) -> None:
    _require(isinstance(tc, dict), path, "tool call must be an object")
    _require(tc.get("type") == "function", f"{path}.type", "only function tool calls are supported")
    _check_keys(tc, frozenset({"id", "type", "function"}), f"{path}.")
    _require(isinstance(tc.get("id"), str), f"{path}.id", "tool call id must be a string")
    fn = tc.get("function")
    _require(isinstance(fn, dict), f"{path}.function", "function must be an object")
    _check_keys(fn, frozenset({"name", "arguments"}), f"{path}.function.")
    _require(isinstance(fn.get("name"), str), f"{path}.function.name", "name must be a string")
    _require(
        isinstance(fn.get("arguments"), str),
        f"{path}.function.arguments",
        "arguments must be a JSON-encoded string",
    )


def _check_message(m: Any, i: int) -> None:
    path = f"messages[{i}]"
    _require(isinstance(m, dict), path, "message must be an object")
    role = m.get("role")
    _require(role in _MESSAGE_KEYS, f"{path}.role", f"role {role!r} is not supported")
    _check_keys(m, _MESSAGE_KEYS[role], f"{path}.")
    content = m.get("content")
    if role == "assistant":
        _require(content is None or isinstance(content, str), f"{path}.content",
                 "assistant content must be a string or null")
        if "reasoning_content" in m:
            _require(isinstance(m["reasoning_content"], str), f"{path}.reasoning_content",
                     "reasoning_content must be a string")
        if "tool_calls" in m:
            _require(isinstance(m["tool_calls"], list), f"{path}.tool_calls",
                     "tool_calls must be an array")
            for j, tc in enumerate(m["tool_calls"]):
                _check_tool_call(tc, f"{path}.tool_calls[{j}]")
    else:
        _require(isinstance(content, str), f"{path}.content",
                 "only string content is supported")
    if role == "tool":
        _require(isinstance(m.get("tool_call_id"), str), f"{path}.tool_call_id",
                 "tool message needs a string tool_call_id")


def _check_top_level(obj: dict[str, Any]) -> None:
    _check_keys(obj, _TOP_LEVEL, "")
    if "stream" in obj:
        _require(isinstance(obj["stream"], bool), "stream", "stream must be a boolean")
    if "stream_options" in obj:
        so = obj["stream_options"]
        _require(isinstance(so, dict), "stream_options", "stream_options must be an object")
        _check_keys(so, frozenset({"include_usage"}), "stream_options.")
        if "include_usage" in so:
            _require(isinstance(so["include_usage"], bool), "stream_options.include_usage",
                     "include_usage must be a boolean")
    if "chat_template_kwargs" in obj:
        kw = obj["chat_template_kwargs"]
        _require(isinstance(kw, dict), "chat_template_kwargs", "must be an object")
        _check_keys(kw, frozenset({"enable_thinking"}), "chat_template_kwargs.")
    if "tools" in obj:
        _require(isinstance(obj["tools"], list), "tools", "tools must be an array")
        for i, tool in enumerate(obj["tools"]):
            path = f"tools[{i}]"
            _require(isinstance(tool, dict), path, "tool must be an object")
            _require(tool.get("type") == "function", f"{path}.type", "only function tools are supported")
            _check_keys(tool, frozenset({"type", "function"}), f"{path}.")
            fn = tool.get("function")
            _require(isinstance(fn, dict), f"{path}.function", "function must be an object")
            _check_keys(fn, _TOOL_FUNCTION_KEYS, f"{path}.function.")
            _require(isinstance(fn.get("name"), str), f"{path}.function.name", "name must be a string")
    if "tool_choice" in obj:
        _require(obj["tool_choice"] in ("none", "auto"), "tool_choice",
                 'only tool_choice "none" or "auto" is supported')


class _DuplicateKeys(dict):  # type: ignore[type-arg]
    """An object that repeated ``key``; JSON leaves its meaning undefined."""

    key: str


class _NonFinite:
    """``NaN``/``Infinity``: accepted by Python's parser, not valid JSON."""

    def __init__(self, name: str) -> None:
        self.name = name


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            dup = _DuplicateKeys(out)
            dup.key = key
            return dup
        out[key] = value
    return out


def _find_ambiguity(value: Any, path: str) -> tuple[str, str] | None:
    """First duplicate key or non-finite number in document order, as (path, what)."""
    if isinstance(value, _NonFinite):
        return path, f"non-finite number {value.name} is not valid JSON"
    if isinstance(value, _DuplicateKeys):
        return f"{path}.{value.key}" if path else value.key, "duplicate object key"
    if isinstance(value, dict):
        for k, v in value.items():
            found = _find_ambiguity(v, f"{path}.{k}" if path else k)
            if found:
                return found
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found = _find_ambiguity(v, f"{path}[{i}]")
            if found:
                return found
    return None


def parse(body: bytes) -> ChatRequest:
    ambiguous = False

    def pairs(p: list[tuple[str, Any]]) -> dict[str, Any]:
        nonlocal ambiguous
        out = _object_pairs(p)
        ambiguous |= isinstance(out, _DuplicateKeys)
        return out

    def constant(name: str) -> _NonFinite:
        nonlocal ambiguous
        ambiguous = True
        return _NonFinite(name)

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
    for i, m in enumerate(obj["messages"]):
        _check_message(m, i)
    last = len(obj["messages"]) - 1
    _require(obj["messages"][last]["role"] != "assistant", f"messages[{last}]",
             "a trailing assistant message (prefill) is not supported")
    messages = tuple(
        Message(
            role=m["role"],
            blocks=_blocks(m),
            envelope=Envelope(tuple(m), _content_form(m), m),
        )
        for m in obj["messages"]
    )
    return ChatRequest(
        messages=messages,
        settings={k: obj[k] for k in SETTINGS_FIELDS if k in obj},
        stream=obj.get("stream", False),
        stream_options=obj.get("stream_options"),
        top_level_order=tuple(obj),
        raw=body,
    )


def _field(value: bytes | None) -> bytes:
    # Length-prefixed, with a distinct marker for "absent", so no two block lists
    # serialize to the same bytes.
    if value is None:
        return b"-"
    return str(len(value)).encode() + b":" + value


def content_sha256(message: Message) -> str:
    """SHA-256 over role and blocks (kind, ids, name, exact bytes); envelope details
    such as key order or null-vs-absent content do not contribute."""
    h = hashlib.sha256(b"mnemon.content.v1\n")
    h.update(_field(message.role.encode()))
    h.update(_field(str(len(message.blocks)).encode()))
    for b in message.blocks:
        for part in (
            b.kind.encode(),
            None if b.tool_call_id is None else b.tool_call_id.encode("utf-8", "surrogatepass"),
            None if b.name is None else b.name.encode("utf-8", "surrogatepass"),
            b.to_bytes(),
        ):
            h.update(_field(part))
    return h.hexdigest()


_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def _escape_surrogate(m: re.Match[str]) -> str:
    return f"\\u{ord(m.group()):04x}"


def render_upstream(
    req: ChatRequest,
    insertions: Mapping[int, Sequence[dict[str, Any]]] | None = None,
    replacements: Mapping[int, dict[str, Any]] | None = None,
) -> bytes:
    """The upstream body: ``req.raw`` unchanged when nothing is spliced.

    ``insertions[i]`` are message objects placed before client message ``i``
    (``i == len(req.messages)`` appends); ``replacements[i]`` substitutes client
    message ``i``. The re-serialized body keeps the client's top-level key order
    and every other client message object as parsed; it is JSON-equal to the
    client's body with the splices applied, not byte-equal."""
    insertions = insertions or {}
    replacements = replacements or {}
    if not any(insertions.values()) and not replacements:
        return req.raw
    n = len(req.messages)
    for i in insertions:
        if not 0 <= i <= n:
            raise ValueError(f"insertion index {i} outside 0..{n}")
    for i in replacements:
        if not 0 <= i < n:
            raise ValueError(f"replacement index {i} outside 0..{n - 1}")
    messages: list[dict[str, Any]] = []
    for i in range(n + 1):
        messages.extend(insertions.get(i, ()))
        if i < n:
            messages.append(replacements.get(i, req.messages[i].raw_object))
    doc: dict[str, Any] = {}
    for key in req.top_level_order:
        if key == "messages":
            doc[key] = messages
        elif key == "stream":
            doc[key] = req.stream
        elif key == "stream_options":
            doc[key] = req.stream_options
        else:
            doc[key] = req.settings[key]
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    # Lone surrogates (valid pairs were joined by the decoder) go back to \u escapes
    # so the body is strict UTF-8 that decodes to the same strings.
    return _LONE_SURROGATE.sub(_escape_surrogate, text).encode("utf-8")
