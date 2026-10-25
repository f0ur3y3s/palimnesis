"""Exact local prompt rendering and token counting against the pinned Strata template.

``render`` reproduces what Strata 0.1.48 feeds its tokenizer (docs/probes/strata.md §2,
§4): the pinned ``chat_template.jinja`` in a jinja2 ``ImmutableSandboxedEnvironment``
with HF-style ``tojson`` (``ensure_ascii=False``, keys unsorted), after Strata's own
preprocessing of OpenAI-shaped input:

- tools are rendered bare: the OpenAI ``{type, function}`` wrapper is removed and the
  ``function`` object rendered with all its keys (``strict`` included); an Anthropic
  tool renders as ``{name, description, parameters}``;
- string tool-call ``arguments`` are parsed to mappings;
- reasoning travels as ``reasoning_content``; ``preserve_thinking`` is never passed
  (Strata ignores it, so every earlier turn keeps its reasoning);
- effort ``none`` means ``enable_thinking=False``.

Consecutive ``tool`` messages are left as they are: the template itself merges them
into one user turn. ``count`` tokenizes with the pinned ``tokenizer.json`` and
``add_special_tokens=False``.

Fragment cache: the tokenizer splits its input on added tokens before normalizing and
pre-tokenizing, so a render cut immediately before an added token counts as the sum of
its pieces. Renders are cut before each ``<|im_start|>`` (one fragment per rendered
turn); fragment counts are memoized in an LRU keyed by ``sha256(fragment)`` and the pin
id. A startup self-test checks additivity on built-in renders; if it fails, every count
is a full tokenization.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import jinja2
from jinja2.sandbox import ImmutableSandboxedEnvironment
from tokenizers import Tokenizer

from ...profile import Layout, Segment
from . import pins

SPLIT_TOKENS = ("<|im_start|>",)
DEFAULT_CACHE_SIZE = 65536
IDS_CACHE_SIZE = 8192  # fragments whose token ids are memoized (cache accounting)


class RenderError(ValueError):
    """The template refused the input (Strata would answer 400)."""


def _tojson(x: Any, indent: int | None = None, separators: Any = None, sort_keys: bool = False) -> str:
    return json.dumps(x, ensure_ascii=False, indent=indent, separators=separators, sort_keys=sort_keys)


def _raise_exception(message: str) -> None:
    raise jinja2.exceptions.TemplateError(message)


class _Sandbox(ImmutableSandboxedEnvironment):
    """The immutable sandbox with its attribute check memoized by (type, attr).

    The check (underscore names, internal attributes, known-mutable methods)
    depends only on the object's type and the name, so this is exact. It removes
    most of the per-render overhead that the view builder's searches pay."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._safe: dict[tuple[type, str], bool] = {}

    def is_safe_attribute(self, obj: Any, attr: str, value: Any) -> bool:
        key = (type(obj), attr)
        hit = self._safe.get(key)
        if hit is None:
            hit = self._safe[key] = super().is_safe_attribute(obj, attr, value)
        return hit


def bare_tool(tool: Mapping[str, Any]) -> Mapping[str, Any]:
    """Strata's tool form.

    OpenAI ``{type, function}`` is unwrapped to the ``function`` object with every key
    it carries, in order (``strict`` included: the live OpenCode bodies count 55 tokens
    short without it). An Anthropic tool becomes ``{name, description, parameters}``
    with ``parameters = input_schema``. An already-bare tool passes unchanged.
    """
    fn = tool.get("function")
    if isinstance(fn, Mapping):
        return fn
    if "input_schema" in tool:
        out: dict[str, Any] = {"name": tool["name"]}
        if "description" in tool:
            out["description"] = tool["description"]
        out["parameters"] = tool["input_schema"]
        return out
    return tool


def _parsed_arguments(tool_call: Mapping[str, Any]) -> Mapping[str, Any]:
    fn = tool_call.get("function")
    if not isinstance(fn, Mapping):
        return tool_call
    args = fn.get("arguments")
    if not isinstance(args, str) or not args.strip():
        return tool_call
    try:
        parsed = json.loads(args)
    except ValueError:
        return tool_call  # the template rejects it, as Strata would
    if not isinstance(parsed, Mapping):
        return tool_call
    return {**tool_call, "function": {**fn, "arguments": parsed}}


def preprocess_messages(messages: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    for message in messages:
        calls = message.get("tool_calls")
        if isinstance(calls, list) and calls:
            message = {**message, "tool_calls": [_parsed_arguments(tc) for tc in calls]}
        out.append(message)
    return out


def render_args_from_openai(body: Mapping[str, Any]) -> dict[str, Any]:
    """``render``/``count_messages`` keyword arguments for an OpenAI Chat Completions body.

    Reads ``messages``, ``tools``, ``reasoning_effort`` and
    ``chat_template_kwargs.enable_thinking``; other template kwargs are ignored, as on
    Strata 0.1.48 (``preserve_thinking`` verified ignored).
    """
    kwargs = body.get("chat_template_kwargs")
    enable_thinking = kwargs.get("enable_thinking") if isinstance(kwargs, Mapping) else None
    return {
        "messages": body.get("messages") or [],
        "tools": body.get("tools") or None,
        "effort": body.get("reasoning_effort"),
        "enable_thinking": enable_thinking if isinstance(enable_thinking, bool) else None,
    }


class Tokens:
    """Renderer and counter bound to one verified pin."""

    def __init__(
        self,
        pin: pins.Pin,
        *,
        cache_size: int = DEFAULT_CACHE_SIZE,
        split_tokens: Sequence[str] = SPLIT_TOKENS,
    ) -> None:
        self.pin = pin
        self._split_tokens = tuple(split_tokens)
        self._hits = 0
        self._misses = 0
        env = _Sandbox(
            trim_blocks=True, lstrip_blocks=True, extensions=["jinja2.ext.loopcontrols"]
        )
        env.filters["tojson"] = _tojson
        env.globals["raise_exception"] = _raise_exception
        self._template = env.from_string(pin.chat_template)
        tokenizer_json = pin.tokenizer_json.decode("utf-8")
        self._tokenizer = Tokenizer.from_str(tokenizer_json)
        self._added_token_strings = tuple(
            t["content"] for t in json.loads(tokenizer_json).get("added_tokens", ()))
        self._cache: OrderedDict[bytes, int] = OrderedDict()
        self._ids: OrderedDict[bytes, tuple[int, ...]] = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()
        self.fragments_ok = self._additivity_self_test()

    @property
    def added_token_strings(self) -> tuple[str, ...]:
        """The pinned tokenizer's added tokens (``<|im_start|>``, ``<think>``, ...).

        The tokenizer extracts these from raw text before anything else, so text that
        contains one renders as that token."""
        return self._added_token_strings

    def render_args(self, body: Mapping[str, Any]) -> tuple[list | None, dict[str, Any]]:
        """``(tools, kw)`` for ``count_messages`` from an OpenAI Chat Completions body."""
        args = render_args_from_openai(body)
        args.pop("messages")
        return args.pop("tools"), args

    # -- render -----------------------------------------------------------------

    def render(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
        *,
        effort: str | None = None,
        enable_thinking: bool | None = None,
        add_generation_prompt: bool = True,
    ) -> str:
        variables: dict[str, Any] = {
            "messages": preprocess_messages(messages),
            "tools": [bare_tool(t) for t in tools] if tools else None,
            "add_generation_prompt": add_generation_prompt,
        }
        if effort == "none":
            enable_thinking = False
        elif effort is not None:
            variables["reasoning_effort"] = effort
        if enable_thinking is not None:
            variables["enable_thinking"] = enable_thinking
        try:
            return self._template.render(**variables)
        except jinja2.exceptions.TemplateError as exc:
            raise RenderError(str(exc)) from exc

    # -- count ------------------------------------------------------------------

    def count(self, text: str) -> int:
        """Exact token count of ``text`` (no fragment cache).

        Lone surrogates (valid in JSON escapes and archived as WTF-8) cannot be
        tokenized; they count as U+FFFD. Any difference from the upstream's own
        count is caught by per-call usage reconciliation."""
        return len(self._tokenizer.encode(_tokenizable(text), add_special_tokens=False).ids)

    def encode(self, text: str) -> list[int]:
        """Token ids of ``text`` (``add_special_tokens=False``; lone surrogates as U+FFFD)."""
        return list(self._tokenizer.encode(_tokenizable(text), add_special_tokens=False).ids)

    def _fragment_ids(self, fragment: str) -> tuple[int, ...]:
        key = hashlib.sha256(fragment.encode("utf-8", "surrogatepass")).digest()
        with self._lock:
            hit = self._ids.get(key)
            if hit is not None:
                self._ids.move_to_end(key)
                return hit
        ids = tuple(self.encode(fragment))
        with self._lock:
            self._ids[key] = ids
            if len(self._ids) > IDS_CACHE_SIZE:
                self._ids.popitem(last=False)
        return ids

    def layout(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
        *,
        effort: str | None = None,
        enable_thinking: bool | None = None,
        add_generation_prompt: bool = True,
    ) -> Layout:
        """The render's token ids split into the template's turns.

        The render is cut before each ``<|im_start|>`` (as for counting). The template
        opens one turn for the head (leading system messages, tools, effort preamble),
        one per user or assistant message, one per run of tool results and one for the
        generation prompt; a message whose own text contains ``<|im_start|>`` adds a
        cut per occurrence. When the cuts do not add up, every turn is ``unmapped``."""
        text = self.render(messages, tools, effort=effort, enable_thinking=enable_thinking,
                           add_generation_prompt=add_generation_prompt)
        fragments = split_fragments(text, self._split_tokens)
        if self.fragments_ok:
            pieces = [self._fragment_ids(f) for f in fragments]
        else:  # additivity failed: exact ids for the whole, fragment counts as boundaries
            whole = tuple(self.encode(text))
            pieces, at = [], 0
            for f in fragments:
                n = self.count(f)
                pieces.append(whole[at:at + n])
                at += n
            if pieces and at < len(whole):
                pieces[-1] += whole[at:]
        units = _turn_units(messages, tools, text.startswith("<|im_start|>system"),
                            add_generation_prompt)
        ids: list[int] = []
        segments: list[Segment] = []
        if sum(n for _, _, n in units) == len(fragments):
            k = 0
            for kind, members, n in units:
                start = len(ids)
                for piece in pieces[k:k + n]:
                    ids.extend(piece)
                k += n
                segments.append(Segment(kind, members, start, len(ids)))
        else:
            for piece in pieces:
                start = len(ids)
                ids.extend(piece)
                segments.append(Segment("unmapped", (), start, len(ids)))
        return Layout(tuple(ids), tuple(segments))

    def count_cached(self, text: str) -> int:
        """Exact count of any text through the LRU (for repeated previews and sizing)."""
        return self._fragment_count(text)

    def count_rendered(self, text: str) -> int:
        """Count a render through the fragment cache (full count if additivity failed)."""
        if not self.fragments_ok:
            return self.count(text)
        return sum(self._fragment_count(f) for f in split_fragments(text, self._split_tokens))

    def count_messages(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
        *,
        effort: str | None = None,
        enable_thinking: bool | None = None,
        add_generation_prompt: bool = True,
    ) -> int:
        return self.count_rendered(
            self.render(
                messages,
                tools,
                effort=effort,
                enable_thinking=enable_thinking,
                add_generation_prompt=add_generation_prompt,
            )
        )

    def _fragment_count(self, fragment: str) -> int:
        key = hashlib.sha256(fragment.encode("utf-8", "surrogatepass")).digest() + self.pin.id.encode()
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                self._hits += 1
                return hit
        n = self.count(fragment)
        with self._lock:
            self._misses += 1
            self._cache[key] = n
            if len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return n

    def cache_stats(self) -> dict[str, int]:
        with self._lock:
            return {"hits": self._hits, "misses": self._misses, "size": len(self._cache)}

    def _additivity_self_test(self) -> bool:
        for text in self._self_test_renders():
            pieces = split_fragments(text, self._split_tokens)
            if sum(self.count(f) for f in pieces) != self.count(text):
                return False
        return True

    def _self_test_renders(self) -> Iterable[str]:
        tools = [{"name": "f", "description": "Probe tool é.", "parameters": {"type": "object",
                  "properties": {"x": {"type": "string"}}}}]
        convo = [
            {"role": "system", "content": "System  prompt\r\n with  spaces "},
            {"role": "user", "content": "naïve café 日本語 🙂 ‍ text<|im_end|>"},
            {"role": "assistant", "content": None, "reasoning_content": "think\n\n",
             "tool_calls": [{"id": "a", "type": "function",
                             "function": {"name": "f", "arguments": '{"x": "1\\n2"}'}}]},
            {"role": "tool", "tool_call_id": "a", "content": "5\r\n"},
            {"role": "tool", "tool_call_id": "b", "content": "  trailing\n"},
            {"role": "assistant", "content": "done.", "reasoning_content": "ok"},
            {"role": "user", "content": "<tool_response>x</tool_response>"},
        ]
        yield self.render(convo, tools)
        yield self.render(convo[1:], None, enable_thinking=False)
        yield self.render(convo[1:2], None, effort="low", add_generation_prompt=False)


_LONE_SURROGATE = re.compile("[\\ud800-\\udfff]")


def _tokenizable(text: str) -> str:
    return _LONE_SURROGATE.sub("�", text) if _LONE_SURROGATE.search(text) else text


def _cuts(value: Any) -> int:
    return json.dumps(value, ensure_ascii=False).count(SPLIT_TOKENS[0])


def _turn_units(messages: Sequence[Mapping[str, Any]], tools, has_head: bool,
                generation: bool) -> list[tuple[str, tuple[int, ...], int]]:
    """(kind, message indices, fragment count) per template turn, in render order."""
    num_sys = 0
    while num_sys < len(messages) and messages[num_sys].get("role") in ("system", "developer"):
        num_sys += 1
    units: list[tuple[str, tuple[int, ...], int]] = []
    if has_head:
        cuts = 1 + _cuts(list(messages[:num_sys])) + (_cuts([bare_tool(t) for t in tools])
                                                      if tools else 0)
        units.append(("head", tuple(range(num_sys)), cuts))
    i = num_sys
    while i < len(messages):
        role = messages[i].get("role")
        j = i + 1
        if role == "tool":
            while j < len(messages) and messages[j].get("role") == "tool":
                j += 1
        members = tuple(range(i, j))
        units.append((role if role in ("user", "assistant", "tool") else "unmapped", members,
                      1 + _cuts([messages[k] for k in members])))
        i = j
    if generation:
        units.append(("generation", (), 1))
    return units


def split_fragments(text: str, split_tokens: Sequence[str] = SPLIT_TOKENS) -> list[str]:
    """Cut ``text`` immediately before each occurrence of a split token."""
    cuts = [0]
    for token in split_tokens:
        start = text.find(token, 1)
        while start != -1:
            cuts.append(start)
            start = text.find(token, start + 1)
    cuts = sorted(set(cuts))
    cuts.append(len(text))
    return [text[a:b] for a, b in zip(cuts, cuts[1:]) if b > a]


_default: Tokens | None = None
_default_lock = threading.Lock()


def default() -> Tokens:
    """The process-wide ``Tokens`` for the vendored default pin (loaded once)."""
    global _default
    if _default is None:
        with _default_lock:
            if _default is None:
                _default = Tokens(pins.load())
    return _default


def render(
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]] | None = None,
    *,
    effort: str | None = None,
    enable_thinking: bool | None = None,
    add_generation_prompt: bool = True,
) -> str:
    return default().render(
        messages,
        tools,
        effort=effort,
        enable_thinking=enable_thinking,
        add_generation_prompt=add_generation_prompt,
    )


def count(text: str) -> int:
    return default().count(text)


def count_messages(
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]] | None = None,
    *,
    effort: str | None = None,
    enable_thinking: bool | None = None,
    add_generation_prompt: bool = True,
) -> int:
    return default().count_messages(
        messages,
        tools,
        effort=effort,
        enable_thinking=enable_thinking,
        add_generation_prompt=add_generation_prompt,
    )
