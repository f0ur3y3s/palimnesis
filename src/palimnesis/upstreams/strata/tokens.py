"""Exact local prompt rendering and token counting against the pinned Strata template.

``render`` reproduces what Strata 0.1.48 feeds its tokenizer (docs/probes/strata.md §2,
§4): the pinned ``chat_template.jinja`` in a jinja2 ``ImmutableSandboxedEnvironment``
with HF-style ``tojson`` (``ensure_ascii=False``, keys unsorted), after Strata's own
preprocessing of OpenAI-shaped input:

- tools are rendered bare: the OpenAI ``{type, function}`` wrapper is removed and the
  ``function`` object rendered with all its keys (``strict`` included); an Anthropic
  tool renders as ``{name, description, parameters}``;
- tool-call ``arguments`` follow Strata's ``tool_arguments`` (#510): a JSON object is
  parsed to a mapping, empty is {}, and anything else (cut-off JSON, a list) is kept as
  text under ``"arguments"``;
- completed assistant turns with no text, no image and no tool calls are dropped, except
  the final message (``ChatTemplate.render``, #843). A reasoning-only turn therefore
  renders nothing, reasoning included (R21-B, ``eval/probes/p12_strata_normalization.py``);
- reasoning travels as ``reasoning_content``; ``preserve_thinking`` is never passed
  (Strata ignores it, so every earlier turn keeps its reasoning);
- effort ``none`` means ``enable_thinking=False``;
- an added-token string written inside a message (any field but ``role``; dict keys
  excepted) or a tool definition is text, not that token (the 0.1.49 frontend's
  ``mark_think_literals``: #537, #554, #2026 and the control tokens). Marking happens
  before the #843 drop, as in Strata's ``encode_prompt``. An assistant message keeps its own tool-call markers; an assistant
  content opening with a whole ``<think>...</think>`` block and a user message wholly
  wrapped in ``<tool_response>...</tool_response>`` keep those markers. Like Strata, the
  render marks such strings with private-use characters, and the encoder emits them as
  text with the text around them (R23-A, ``eval/probes/p14_literal_tags.py``).

Consecutive ``tool`` messages are left as they are: the template itself merges them
into one user turn. ``count`` tokenizes with the pinned ``tokenizer.json`` and
``add_special_tokens=False``, without its NFC normalizer: Strata's tokenizer has none
(``eval/probes/p15_nfc_count.py``, D47).

``COUNTER_REVISION`` names this reproduction of Strata's rendering and tokenizing; cache
accounting records it in each call's identity, so a call counted by an earlier revision
is a model/template change, not an unexplained one.

Fragment cache: the tokenizer splits its input on added tokens before normalizing and
pre-tokenizing, so a render cut immediately before an added token counts as the sum of
its pieces. Renders are cut before each ``<|im_start|>`` the template wrote (one
fragment per rendered turn); fragment counts are memoized in an LRU keyed by ``sha256(fragment)`` and the pin
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

from ...profile import Layout, Segment, empty_assistant
from . import pins

SPLIT_TOKENS = ("<|im_start|>",)
COUNTER_REVISION = "c3"  # c2: literal tags as text (D46); c3: no NFC (D47)
DEFAULT_CACHE_SIZE = 65536
IDS_CACHE_SIZE = 8192  # fragments whose token ids are memoized (cache accounting)


class RenderError(ValueError):
    """The template refused the input (Strata would answer 400)."""


# Strata's marks (serve/frontend.py): the literal tags have fixed private-use characters;
# each other added token (a control token) gets one from U+F0E10 in tokenizer order.
THINK_TAGS = {"<think>": "\U000F0E01", "</think>": "\U000F0E02"}
VISION_TAGS = {"<|vision_start|>": "\U000F0E03", "<|image_pad|>": "\U000F0E04",
               "<|vision_end|>": "\U000F0E05", "<|video_pad|>": "\U000F0E06"}
TOOL_LITERAL_TAGS = {"</tool_call>": "\U000F0E07", "<tool_call>": "\U000F0E08",
                     "<tool_response>": "\U000F0E09", "</tool_response>": "\U000F0E0A"}
LITERAL_TAGS = {**THINK_TAGS, **VISION_TAGS, **TOOL_LITERAL_TAGS}
CONTROL_MARK0 = 0xF0E10


def literal_tags(added_tokens: Sequence[str]) -> dict[str, str]:
    """Tag text -> mark for every added token, longest first as the tokenizer matches them."""
    controls = [t for t in added_tokens if t not in LITERAL_TAGS]
    tags = {**LITERAL_TAGS, **{c: chr(CONTROL_MARK0 + k) for k, c in enumerate(controls)}}
    return dict(sorted(tags.items(), key=lambda t: -len(t[0])))


def _mark(text: str, tags: Mapping[str, str]) -> str:
    for tag, mark in tags.items():
        text = text.replace(tag, mark)
    return text


def _mark_deep(v: Any, tags: Mapping[str, str]) -> Any:
    if isinstance(v, str):
        return _mark(v, tags)
    if isinstance(v, Mapping):
        return {k: _mark_deep(x, tags) for k, x in v.items()}
    if isinstance(v, list):
        return [_mark_deep(x, tags) for x in v]
    return v


def _has_tag(v: Any, tags: Mapping[str, str]) -> bool:
    if isinstance(v, str):
        return any(tag in v for tag in tags)
    if isinstance(v, Mapping):
        return any(_has_tag(x, tags) for x in v.values())
    if isinstance(v, list):
        return any(_has_tag(x, tags) for x in v)
    return False


def _keep_tool_result_wrap(content: Any, tags: Mapping[str, str]) -> Any:
    """A user message whose whole text is ``<tool_response>...</tool_response>`` keeps that
    outer pair as markers; only the text inside is marked. None: not such a message."""
    o, c = "<tool_response>", "</tool_response>"

    def wrap(text: str, first: bool, last: bool) -> str:
        i = text.index(o) + len(o) if first else 0
        j = text.rindex(c) if last else len(text)
        head = _mark(text[:i - len(o)], tags) + o if first else ""
        tail = c + _mark(text[j + len(c):], tags) if last else ""
        return head + _mark(text[i:j], tags) + tail

    if isinstance(content, str):
        body = content.strip()
        if len(body) >= len(o) + len(c) and body.startswith(o) and body.endswith(c):
            return wrap(content, True, True)
        return None
    if not (isinstance(content, list) and content
            and all(isinstance(x, Mapping) and "text" in x for x in content)):
        return None
    texts = [x["text"] for x in content]
    if not all(isinstance(t, str) for t in texts):
        return None
    body = "".join(texts).strip()
    if not (len(body) >= len(o) + len(c) and body.startswith(o) and body.endswith(c)):
        return None
    if not (texts[0].lstrip().startswith(o) and texts[-1].rstrip().endswith(c)):
        return None
    if len(content) == 1:
        return [{**content[0], "text": wrap(texts[0], True, True)}]
    return ([{**content[0], "text": wrap(texts[0], True, False)}]
            + [_mark_deep(x, tags) for x in content[1:-1]]
            + [{**content[-1], "text": wrap(texts[-1], False, True)}])


def mark_literals(messages: Sequence[Mapping[str, Any]], tools: Any,
                  tags: Mapping[str, str]) -> tuple[list, Any, bool]:
    """Strata's ``mark_think_literals``: ``(messages, tools, changed)`` with every tag in
    the messages' fields (``role`` aside) and the tools swapped for its mark."""
    if not _has_tag(list(messages), tags) and not _has_tag(tools, tags):
        return list(messages), tools, False
    own = {t: v for t, v in tags.items() if t not in TOOL_LITERAL_TAGS}
    out = []
    for message in messages:
        m = dict(message)
        content = m.get("content")
        mine = own if m.get("role") == "assistant" else tags
        for k, v in m.items():
            if k != "role":
                m[k] = _mark_deep(v, mine)
        if m.get("role") == "user":
            kept = _keep_tool_result_wrap(content, tags)
            if kept is not None:
                m["content"] = kept
        if (m.get("role") == "assistant" and isinstance(content, str)
                and content.lstrip().startswith("<think>") and "</think>" in content):
            i, j = content.index("<think>") + len("<think>"), content.index("</think>")
            m["content"] = (content[:i] + _mark(content[i:j], own) + "</think>"
                            + _mark(content[j + len("</think>"):], own))
        out.append(m)
    return out, _mark_deep(tools, tags), True


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


def _strata_arguments(raw: Any) -> Mapping[str, Any]:
    """Strata's ``tool_arguments`` (#510): a JSON object is used as it is, empty is {},
    anything else (cut-off JSON, a list, a number) is kept as text under "arguments"."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {}
    if isinstance(raw, Mapping):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except ValueError:
            return {"arguments": raw}
        return value if isinstance(value, Mapping) else {"arguments": raw}
    return {"arguments": json.dumps(raw, ensure_ascii=False)}


def _parsed_arguments(tool_call: Mapping[str, Any]) -> Mapping[str, Any]:
    fn = tool_call.get("function")
    if not isinstance(fn, Mapping):
        return tool_call
    return {**tool_call, "function": {**fn, "arguments": _strata_arguments(fn.get("arguments"))}}


def dropped_turns(messages: Sequence[Mapping[str, Any]]) -> frozenset[int]:
    """Indices Strata leaves out of the render (#843): completed assistant turns with no
    text, no image and no tool calls. The final message is always kept."""
    return frozenset(i for i, m in enumerate(messages[:-1]) if empty_assistant(m))


def _parsed_calls(message: Mapping[str, Any]) -> Mapping[str, Any]:
    calls = message.get("tool_calls")
    if isinstance(calls, list) and calls:
        return {**message, "tool_calls": [_parsed_arguments(tc) for tc in calls]}
    return message


def preprocess_messages(messages: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    drop = dropped_turns(messages)
    return [_parsed_calls(m) for i, m in enumerate(messages) if i not in drop]


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
        self.revision = COUNTER_REVISION
        self._split_tokens = tuple(split_tokens)
        self._hits = 0
        self._misses = 0
        env = _Sandbox(
            trim_blocks=True, lstrip_blocks=True, extensions=["jinja2.ext.loopcontrols"]
        )
        env.filters["tojson"] = _tojson
        env.globals["raise_exception"] = _raise_exception
        self._template = env.from_string(pin.chat_template)
        spec = json.loads(pin.tokenizer_json.decode("utf-8"))
        spec["normalizer"] = None  # Strata's tokenizer does not normalize (D47)
        self._tokenizer = Tokenizer.from_str(json.dumps(spec))
        self._added_token_strings = tuple(t["content"] for t in spec.get("added_tokens", ()))
        self._added_ids = {t["content"]: t["id"] for t in spec.get("added_tokens", ())}
        self._plain = Tokenizer.from_str(json.dumps({**spec, "added_tokens": []}))
        self._tags = literal_tags(self._added_token_strings)
        self._unmarks = {mark: tag for tag, mark in self._tags.items()}
        self._mark_re = re.compile("|".join(map(re.escape, self._unmarks)))
        self._added_re = re.compile("|".join(map(re.escape, sorted(
            self._added_token_strings, key=len, reverse=True))))
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
        """The prompt text Strata encodes (added-token strings inside messages as text)."""
        text, marked = self._render_marked(messages, tools, effort=effort,
                                           enable_thinking=enable_thinking,
                                           add_generation_prompt=add_generation_prompt)
        return self._unmark(text) if marked else text

    def _render_marked(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
        *,
        effort: str | None = None,
        enable_thinking: bool | None = None,
        add_generation_prompt: bool = True,
    ) -> tuple[str, bool]:
        """The render with tags written inside messages still marked, and whether any were."""
        drop = dropped_turns(messages)
        marked, bare, changed = mark_literals([_parsed_calls(m) for m in messages],
                                              [bare_tool(t) for t in tools] if tools else None,
                                              self._tags)
        variables: dict[str, Any] = {
            "messages": [m for i, m in enumerate(marked) if i not in drop],
            "tools": bare,
            "add_generation_prompt": add_generation_prompt,
        }
        if effort == "none":
            enable_thinking = False
        elif effort is not None:
            variables["reasoning_effort"] = effort
        if enable_thinking is not None:
            variables["enable_thinking"] = enable_thinking
        try:
            return self._template.render(**variables), changed
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

    def _unmark(self, text: str) -> str:
        return self._mark_re.sub(lambda m: self._unmarks[m.group(0)], text)

    def _encode_marked(self, text: str) -> list[int]:
        """Ids of a marked render: added tokens the template wrote are tokens; each run
        between them is encoded, its marks back as tag text, as plain text (Strata's
        ``encode_prompt`` with ``plain`` spans)."""
        if not self._mark_re.search(text):
            return self.encode(text)
        out: list[int] = []
        pos = 0
        for m in self._added_re.finditer(text):
            if m.start() > pos:
                out.extend(self._plain_ids(text[pos:m.start()]))
            out.append(self._added_ids[m.group(0)])
            pos = m.end()
        if pos < len(text):
            out.extend(self._plain_ids(text[pos:]))
        return out

    def _plain_ids(self, text: str) -> list[int]:
        return list(self._plain.encode(_tokenizable(self._unmark(text)),
                                       add_special_tokens=False).ids)

    def _fragment_ids(self, fragment: str, marked: bool = False) -> tuple[int, ...]:
        key = hashlib.sha256(fragment.encode("utf-8", "surrogatepass")).digest() + (
            b"m" if marked else b"")
        with self._lock:
            hit = self._ids.get(key)
            if hit is not None:
                self._ids.move_to_end(key)
                return hit
        ids = tuple(self._encode_marked(fragment) if marked else self.encode(fragment))
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

        The render is cut before each ``<|im_start|>`` the template wrote (as for
        counting). The template opens one turn for the head (leading system messages,
        tools, effort preamble), one per user or assistant message, one per run of tool
        results and one for the generation prompt; ``<|im_start|>`` inside a message is
        text and cuts nothing, except in a dict key (tool parameters, parsed arguments),
        which Strata does not mark. When the cuts do not add up, every turn is ``unmapped``."""
        text, marked = self._render_marked(messages, tools, effort=effort,
                                           enable_thinking=enable_thinking,
                                           add_generation_prompt=add_generation_prompt)
        fragments = split_fragments(text, self._split_tokens)
        if self.fragments_ok or marked:  # a marked render is cut only at template tokens
            pieces = [self._fragment_ids(f, marked) for f in fragments]
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
        text, marked = self._render_marked(messages, tools, effort=effort,
                                           enable_thinking=enable_thinking,
                                           add_generation_prompt=add_generation_prompt)
        if not marked:
            return self.count_rendered(text)
        return sum(len(self._fragment_ids(f, True))
                   for f in split_fragments(text, self._split_tokens))

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


def _key_cuts(value: Any) -> int:
    """``<|im_start|>`` written in dict keys: Strata marks values only, so these stay tokens."""
    if isinstance(value, Mapping):
        return sum(str(k).count(SPLIT_TOKENS[0]) + _key_cuts(v) for k, v in value.items())
    if isinstance(value, list):
        return sum(_key_cuts(v) for v in value)
    return 0


def _turn_units(messages: Sequence[Mapping[str, Any]], tools, has_head: bool,
                generation: bool) -> list[tuple[str, tuple[int, ...], int]]:
    """(kind, message indices, fragment count) per template turn, in render order."""
    num_sys = 0
    while num_sys < len(messages) and messages[num_sys].get("role") in ("system", "developer"):
        num_sys += 1
    units: list[tuple[str, tuple[int, ...], int]] = []
    if has_head:
        cuts = 1 + _key_cuts(list(messages[:num_sys])) + (
            _key_cuts([bare_tool(t) for t in tools]) if tools else 0)
        units.append(("head", tuple(range(num_sys)), cuts))
    # A turn Strata drops renders nothing: a zero-fragment unit in its place. The kept
    # messages around it render as if adjacent, so tool runs group across it.
    drop = dropped_turns(messages)
    i = num_sys
    while i < len(messages):
        if i in drop:
            units.append((messages[i].get("role"), (i,), 0))
            i += 1
            continue
        role = messages[i].get("role")
        members = [i]
        j = i + 1
        if role == "tool":
            while j < len(messages) and (j in drop or messages[j].get("role") == "tool"):
                if j not in drop:
                    members.append(j)
                j += 1
            while j - 1 > i and j - 1 in drop:  # trailing dropped turns get their own units
                j -= 1
        units.append((role if role in ("user", "assistant", "tool") else "unmapped",
                      tuple(members), 1 + _key_cuts([_parsed_calls(messages[k]) for k in members])))
        units.extend((messages[k].get("role"), (k,), 0) for k in range(i, j) if k in drop)
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
