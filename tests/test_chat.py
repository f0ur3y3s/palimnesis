"""Chat Completions request normalization: parse, rejection list, upstream render."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from palimnesis.chat import (
    Block,
    InvalidBody,
    Unsupported,
    content_sha256,
    parse,
    render_messages,
    render_upstream,
)

ROOT = Path(__file__).resolve().parents[1]
LIVE_BODIES = sorted(
    (ROOT / "eval" / "fixtures" / "opencode-2.1.4" / "live" / "exchanges").glob("*/*/request.body")
)


def _body(*messages: str, extra: str = "") -> bytes:
    """A minimal request; message objects are given as literal JSON text."""
    return ('{"model":"m","messages":[' + ",".join(messages) + "]" + extra + "}").encode()


USER = '{"role":"user","content":"next"}'


def test_ten_live_bodies_present():
    assert len(LIVE_BODIES) == 10


@pytest.mark.parametrize("path", LIVE_BODIES, ids=lambda p: p.parent.name)
def test_live_body_parses_and_renders_byte_identical(path):
    body = path.read_bytes()
    req = parse(body)
    assert len(req.messages) == len(json.loads(body)["messages"])
    assert render_upstream(req) == body


def test_live_tool_turn_parses_into_typed_blocks():
    req = parse(LIVE_BODIES[1].read_bytes())
    assert [m.role for m in req.messages] == ["system", "user", "assistant", "tool"]

    user = req.messages[1]
    assert [(b.kind, b.text) for b in user.blocks] == [
        (
            "text",
            '"Create a file named hello.py that prints the sum of 2 and 3. Then run it'
            ' with python and tell me what it printed. Keep it short."',
        )
    ]

    reasoning, call = req.messages[2].blocks
    assert reasoning.kind == "reasoning"
    assert reasoning.text == (
        "The user is asking for a simple file hello.py that outputs the sum of 2 and 3,"
        " and then wants to run it with python. Let's do it.\n"
    )
    assert call.kind == "tool_call"
    assert call.tool_call_id == "call_371c4e088f8f4fc993bd4e34"
    assert call.name == "write"
    assert call.text == r'{"path":"hello.py","content":"print(2 + 3)\n"}'

    (result,) = req.messages[3].blocks
    assert result.kind == "tool_result"
    assert result.tool_call_id == "call_371c4e088f8f4fc993bd4e34"
    assert result.text == "Created file successfully: hello.py"


# (message JSON text, kind, decoded text, encoding, stored bytes); the block is the
# message's first.
BLOCK_CASES = {
    "empty": (r'{"role":"user","content":""}', "text", "", "utf-8", b""),
    "whitespace": (r'{"role":"user","content":"  \n "}', "text", "  \n ", "utf-8", b"  \n "),
    "multibyte": (
        r'{"role":"user","content":"hé 漢 🙂"}',
        "text", "hé 漢 \U0001f642", "utf-8", b"h\xc3\xa9 \xe6\xbc\xa2 \xf0\x9f\x99\x82",
    ),
    "crlf": (r'{"role":"user","content":"a\r\nb\r\n"}', "text", "a\r\nb\r\n", "utf-8", b"a\r\nb\r\n"),
    "tabs": (r'{"role":"user","content":"\tx\t"}', "text", "\tx\t", "utf-8", b"\tx\t"),
    "lone_surrogate": (
        r'{"role":"user","content":"a\ud800b"}', "text", "a\ud800b", "wtf-8", b"a\xed\xa0\x80b"
    ),
    "tool_args": (
        r'{"role":"assistant","content":null,"tool_calls":[{"id":"c1","type":"function",'
        r'"function":{"name":"f","arguments":"{\"a\": {\"b\":[1,\"ü\"]} }"}}]}',
        "tool_call", '{"a": {"b":[1,"ü"]} }', "utf-8", b'{"a": {"b":[1,"\xc3\xbc"]} }',
    ),
    "reasoning": (
        r'{"role":"assistant","content":"ok","reasoning_content":"think\n\n"}',
        "reasoning", "think\n\n", "utf-8", b"think\n\n",
    ),
    "tool_result": (r'{"role":"tool","tool_call_id":"c1","content":""}', "tool_result", "", "utf-8", b""),
}


@pytest.mark.parametrize(
    "body",
    [b"", b"{", b"\xff\xfe{}", b"[]", b'"x"', b"{}", b'{"model":"m","messages":{}}',
     b'{"model":"m","messages":null}'],
    ids=["empty", "truncated", "not_utf8", "array", "string", "no_messages", "messages_object",
         "messages_null"],
)
def test_malformed_body_is_invalid_body(body):
    with pytest.raises(InvalidBody):
        parse(body)


@pytest.mark.parametrize(
    "message, form, blocks, keys",
    [
        (
            r'{"role":"assistant","content":null,"reasoning_content":"r"}',
            "null", [("reasoning", "r")], ("role", "content", "reasoning_content"),
        ),
        (
            r'{"reasoning_content":"r","role":"assistant"}',
            "absent", [("reasoning", "r")], ("reasoning_content", "role"),
        ),
        (
            r'{"role":"assistant","content":"","reasoning_content":"r"}',
            "string", [("reasoning", "r"), ("text", "")], ("role", "content", "reasoning_content"),
        ),
    ],
    ids=["null", "absent", "empty_string"],
)
def test_assistant_content_null_absent_and_empty_are_distinguished(message, form, blocks, keys):
    msg = parse(_body(message, USER)).messages[0]
    assert msg.envelope.content_form == form
    assert msg.envelope.key_order == keys
    assert [(b.kind, b.text) for b in msg.blocks] == blocks


@pytest.mark.parametrize("case", BLOCK_CASES.values(), ids=BLOCK_CASES.keys())
def test_blocks_round_trip(case):
    message, kind, text, encoding, stored = case
    block = parse(_body(message, USER)).messages[0].blocks[0]
    assert (block.kind, block.text, block.encoding) == (kind, text, encoding)
    assert block.to_bytes() == stored
    assert Block.from_bytes(
        kind, stored, encoding, tool_call_id=block.tool_call_id, name=block.name
    ) == block


SYS = r'{"role":"system","content":"s"}'
CALL = (
    r'{"role":"assistant","content":null,"tool_calls":[{"id":"c1","type":"function",'
    r'"function":{"name":"f","arguments":"{}"}}]}'
)
RESULT = r'{"role":"tool","tool_call_id":"c1","content":"ok"}'
TOOL = r'{"type":"function","function":{"name":"f","parameters":{}}}'

# (body, field path) per capabilities.md "Chat Completions request features" and D10 item 14.
REJECTIONS = {
    "developer_role": (_body(r'{"role":"developer","content":"d"}', USER), "messages[0].role"),
    "unknown_role": (_body(r'{"role":"function","content":"d"}', USER), "messages[0].role"),
    "missing_role": (_body(r'{"content":"d"}', USER), "messages[0].role"),
    "message_not_object": (_body('"hi"', USER), "messages[0]"),
    "text_part_array": (
        _body(r'{"role":"user","content":[{"type":"text","text":"hi"}]}'), "messages[0].content"
    ),
    "image_part": (
        _body(r'{"role":"user","content":[{"type":"image_url","image_url":{"url":"x"}}]}'),
        "messages[0].content",
    ),
    "audio_part": (
        _body(r'{"role":"user","content":[{"type":"input_audio","input_audio":{}}]}'),
        "messages[0].content",
    ),
    "user_content_null": (_body(r'{"role":"user","content":null}'), "messages[0].content"),
    "user_content_absent": (_body(r'{"role":"user"}'), "messages[0].content"),
    "system_content_number": (_body(r'{"role":"system","content":1}', USER), "messages[0].content"),
    "tool_content_null": (
        _body(CALL, r'{"role":"tool","tool_call_id":"c1","content":null}'), "messages[1].content"
    ),
    "tool_without_call_id": (_body(CALL, r'{"role":"tool","content":"x"}'), "messages[1].tool_call_id"),
    "user_name_field": (_body(r'{"role":"user","content":"x","name":"bob"}'), "messages[0].name"),
    "reasoning_on_user": (
        _body(r'{"role":"user","content":"x","reasoning_content":"r"}'), "messages[0].reasoning_content"
    ),
    "message_function_call": (
        _body(r'{"role":"assistant","content":null,"function_call":{"name":"f","arguments":"{}"}}', USER),
        "messages[0].function_call",
    ),
    "non_function_tool_call": (
        _body(
            r'{"role":"assistant","content":null,"tool_calls":[{"id":"c1","type":"custom",'
            r'"custom":{"name":"f","input":""}}]}',
            RESULT,
        ),
        "messages[0].tool_calls[0].type",
    ),
    "tool_call_arguments_object": (
        _body(
            r'{"role":"assistant","content":null,"tool_calls":[{"id":"c1","type":"function",'
            r'"function":{"name":"f","arguments":{}}}]}',
            RESULT,
        ),
        "messages[0].tool_calls[0].function.arguments",
    ),
    "trailing_assistant_prefill": (_body(SYS, USER, r'{"role":"assistant","content":"Sure"}'), "messages[2]"),
    "n": (_body(USER, extra=',"n":2'), "n"),
    "logprobs": (_body(USER, extra=',"logprobs":true'), "logprobs"),
    "top_logprobs": (_body(USER, extra=',"top_logprobs":2'), "top_logprobs"),
    "response_format": (_body(USER, extra=r',"response_format":{"type":"json_object"}'), "response_format"),
    "parallel_tool_calls": (_body(USER, extra=',"parallel_tool_calls":false'), "parallel_tool_calls"),
    "preserve_thinking": (
        _body(USER, extra=r',"chat_template_kwargs":{"enable_thinking":true,"preserve_thinking":true}'),
        "chat_template_kwargs.preserve_thinking",
    ),
    "other_template_kwarg": (
        _body(USER, extra=r',"chat_template_kwargs":{"foo":1}'), "chat_template_kwargs.foo"
    ),
    "reasoning_format": (_body(USER, extra=r',"reasoning_format":"none"'), "reasoning_format"),
    "non_function_tool": (_body(USER, extra=r',"tools":[{"type":"custom","custom":{"name":"f"}}]'), "tools[0].type"),
    "tool_choice_required": (_body(USER, extra=r',"tools":[' + TOOL + r'],"tool_choice":"required"'), "tool_choice"),
    "tool_choice_named": (
        _body(USER, extra=r',"tools":[' + TOOL + r'],"tool_choice":{"type":"function","function":{"name":"f"}}'),
        "tool_choice",
    ),
    "legacy_functions": (_body(USER, extra=r',"functions":[{"name":"f"}]'), "functions"),
    "legacy_function_call": (_body(USER, extra=r',"function_call":"auto"'), "function_call"),
    "user_field": (_body(USER, extra=r',"user":"u1"'), "user"),
    "metadata": (_body(USER, extra=r',"metadata":{}'), "metadata"),
    "unknown_top_level": (_body(USER, extra=r',"frobnicate":1'), "frobnicate"),
    "stream_not_bool": (_body(USER, extra=r',"stream":"yes"'), "stream"),
    "stream_options_other_key": (
        _body(USER, extra=r',"stream":true,"stream_options":{"include_obfuscation":false}'),
        "stream_options.include_obfuscation",
    ),
}


def test_supported_settings_are_collected_and_order_recorded():
    body = (
        r'{"messages":[{"role":"user","content":"x"}],"model":"m","temperature":0.6,"top_p":1,'
        r'"seed":7,"stop":["\n\n"],"presence_penalty":0,"frequency_penalty":0.5,'
        r'"reasoning_effort":"low","chat_template_kwargs":{"enable_thinking":false},'
        r'"max_completion_tokens":100,"max_tokens":50,'
        r'"tools":[{"type":"function","function":{"name":"f","description":"d",'
        r'"parameters":{"type":"object"},"strict":false}}],"tool_choice":"none",'
        r'"stream":true,"stream_options":{"include_usage":true}}'
    ).encode()
    req = parse(body)
    assert req.settings == {
        "model": "m",
        "temperature": 0.6,
        "top_p": 1,
        "seed": 7,
        "stop": ["\n\n"],
        "presence_penalty": 0,
        "frequency_penalty": 0.5,
        "reasoning_effort": "low",
        "chat_template_kwargs": {"enable_thinking": False},
        "max_completion_tokens": 100,
        "max_tokens": 50,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "f", "description": "d", "parameters": {"type": "object"}, "strict": False
                },
            }
        ],
        "tool_choice": "none",
    }
    assert req.stream is True
    assert req.stream_options == {"include_usage": True}
    assert req.top_level_order == (
        "messages", "model", "temperature", "top_p", "seed", "stop", "presence_penalty",
        "frequency_penalty", "reasoning_effort", "chat_template_kwargs", "max_completion_tokens",
        "max_tokens", "tools", "tool_choice", "stream", "stream_options",
    )


def test_minimal_request_is_non_streaming_with_only_model_setting():
    req = parse(_body(USER, extra=r',"tool_choice":"auto"'))
    assert req.stream is False
    assert req.stream_options is None
    assert req.settings == {"model": "m", "tool_choice": "auto"}


@pytest.mark.parametrize(
    "body, field_path",
    [
        (rb'{"model":"m","model":"n","messages":[{"role":"user","content":"x"}]}', "model"),
        (rb'{"model":"m","messages":[{"role":"user","content":"x","content":"y"}]}',
         "messages[0].content"),
        (rb'{"model":"m","messages":[{"role":"user","content":"x"}],"tools":[{"type":"function",'
         rb'"function":{"name":"f","parameters":{"a":1,"a":2}}}]}', "tools[0].function.parameters.a"),
    ],
    ids=["top_level", "message", "nested_schema"],
)
def test_duplicate_object_keys_rejected(body, field_path):
    with pytest.raises(Unsupported) as e:
        parse(body)
    assert e.value.field == field_path


@pytest.mark.parametrize(
    "body, field_path",
    [
        (rb'{"model":"m","messages":[{"role":"user","content":"x"}],"temperature":NaN}', "temperature"),
        (rb'{"model":"m","messages":[{"role":"user","content":"x"}],"stop":[1,Infinity]}', "stop[1]"),
        (rb'{"model":"m","messages":[{"role":"user","content":"x"}],"tools":[{"type":"function",'
         rb'"function":{"name":"f","parameters":{"maximum":-Infinity}}}]}',
         "tools[0].function.parameters.maximum"),
    ],
    ids=["nan", "infinity", "negative_infinity"],
)
def test_non_finite_numbers_rejected(body, field_path):
    with pytest.raises(Unsupported) as e:
        parse(body)
    assert e.value.field == field_path


HIDDEN_CALL = {
    "role": "assistant",
    "content": None,
    "tool_calls": [
        {"id": "mn_1", "type": "function", "function": {"name": "recall", "arguments": '{"q":"ü"}'}}
    ],
}
HIDDEN_RESULT = {"role": "tool", "tool_call_id": "mn_1", "content": "recalled 漢\r\n"}


def _pairs(body: bytes):
    """Decode keeping every object's key order visible."""
    return json.loads(body, object_pairs_hook=lambda p: p)


def test_insertions_splice_hidden_events_and_keep_client_objects_verbatim():
    body = LIVE_BODIES[2].read_bytes()
    client = json.loads(body)
    assert len(client["messages"]) == 6

    out = render_upstream(parse(body), {2: [HIDDEN_CALL, HIDDEN_RESULT], 6: [HIDDEN_RESULT]})

    expected = dict(client)
    expected["messages"] = (
        client["messages"][:2] + [HIDDEN_CALL, HIDDEN_RESULT] + client["messages"][2:] + [HIDDEN_RESULT]
    )
    assert json.loads(out) == expected
    pairs = dict(_pairs(out))
    assert list(pairs) == ["model", "messages", "tools", "stream", "stream_options",
                           "max_completion_tokens"]
    original = dict(_pairs(body))["messages"]
    assert pairs["messages"][:2] == original[:2]
    assert pairs["messages"][4:8] == original[2:]
    assert pairs["tools"] == dict(_pairs(body))["tools"]
    assert "漢".encode() in out  # ensure_ascii=False
    assert b'"messages":[{' in out  # compact separators


def test_insertion_render_reescapes_lone_surrogates_as_valid_json():
    body = _body(r'{"role":"user","content":"a\ud800b"}', USER)
    out = render_upstream(parse(body), {1: [HIDDEN_RESULT]})
    out.decode("utf-8")  # strict UTF-8: the surrogate stays an escape, not raw bytes
    assert json.loads(out)["messages"] == [
        {"role": "user", "content": "a\ud800b"}, HIDDEN_RESULT, {"role": "user", "content": "next"}
    ]


@pytest.mark.parametrize("path", LIVE_BODIES, ids=lambda p: p.parent.name)
def test_live_messages_round_trip_json_equal(path):
    body = path.read_bytes()
    req = parse(body)
    out = render_upstream(req, {len(req.messages): [HIDDEN_RESULT]})
    original = _pairs(body)
    original[1][1].append(list(HIDDEN_RESULT.items()))
    assert _pairs(out) == original


def test_empty_insertions_return_raw_body():
    body = LIVE_BODIES[0].read_bytes()
    assert render_upstream(parse(body), {}) == body


def _hashes(*messages: str) -> list[str]:
    return [content_sha256(m) for m in parse(_body(*messages, USER)).messages]


def test_identical_content_in_two_messages_hashes_equal():
    a, b, _ = _hashes(r'{"role":"user","content":"same"}', r'{"content":"same","role":"user"}')
    assert a == b
    assert len(a) == 64 and int(a, 16) >= 0


@pytest.mark.parametrize(
    "first, second",
    [
        (r'{"role":"user","content":"x"}', r'{"role":"system","content":"x"}'),
        (r'{"role":"user","content":"x"}', r'{"role":"user","content":"x "}'),
        (r'{"role":"user","content":"\ud800"}', r'{"role":"user","content":"�"}'),
        (r'{"role":"assistant","content":"x","reasoning_content":""}',
         r'{"role":"assistant","content":"","reasoning_content":"x"}'),
        (r'{"role":"assistant","content":null,"tool_calls":[{"id":"c1","type":"function",'
         r'"function":{"name":"f","arguments":"{}"}}]}',
         r'{"role":"assistant","content":null,"tool_calls":[{"id":"c2","type":"function",'
         r'"function":{"name":"f","arguments":"{}"}}]}'),
        (r'{"role":"assistant","content":null,"tool_calls":[{"id":"c1","type":"function",'
         r'"function":{"name":"f","arguments":"{}"}}]}',
         r'{"role":"assistant","content":null,"tool_calls":[{"id":"c1","type":"function",'
         r'"function":{"name":"g","arguments":"{}"}}]}'),
        (r'{"role":"tool","tool_call_id":"c1","content":"ok"}',
         r'{"role":"tool","tool_call_id":"c2","content":"ok"}'),
        (r'{"role":"user","content":"ab"}', r'{"role":"assistant","content":"a","reasoning_content":"b"}'),
    ],
    ids=["role", "trailing_space", "surrogate_vs_replacement", "block_kind", "tool_call_id",
         "tool_name", "tool_result_id", "block_boundary"],
)
def test_different_content_hashes_differ(first, second):
    a, b, _ = _hashes(first, second)
    assert a != b


@pytest.mark.parametrize("case", REJECTIONS.values(), ids=REJECTIONS.keys())
def test_unsupported_feature_rejected_with_field_path(case):
    body, field_path = case
    with pytest.raises(Unsupported) as e:
        parse(body)
    assert e.value.code == "unsupported_feature"
    assert e.value.field == field_path




def test_replacements_substitute_client_messages_in_place():
    body = LIVE_BODIES[2].read_bytes()
    client = json.loads(body)
    split = {"role": "assistant", "content": "text part", "reasoning_content": "reasoning "}

    out = render_upstream(parse(body), {6: [HIDDEN_RESULT]}, replacements={2: split})

    expected = dict(client)
    expected["messages"] = client["messages"][:2] + [split] + client["messages"][3:] + [HIDDEN_RESULT]
    assert json.loads(out) == expected


def test_replacement_index_outside_the_client_messages_is_rejected():
    req = parse(LIVE_BODIES[0].read_bytes())

    with pytest.raises(ValueError):
        render_upstream(req, replacements={len(req.messages): {"role": "user", "content": "x"}})


def test_render_messages_replaces_the_message_list_and_overrides_settings_in_place():
    body = LIVE_BODIES[2].read_bytes()
    req = parse(body)
    shorter = [m.raw_object for m in req.messages[:3]]

    out = render_messages(req, shorter, overrides={"max_completion_tokens": 4096})

    expected = json.loads(body)
    expected["messages"] = shorter
    expected["max_completion_tokens"] = 4096
    assert json.loads(out) == expected
    assert list(dict(_pairs(out))) == list(dict(_pairs(body)))  # key order kept


def test_render_messages_appends_an_absent_override_at_the_end():
    req = parse(b'{"model":"m","messages":[{"role":"user","content":"hi"}],"stream":true}')

    out = render_messages(req, [{"role": "user", "content": "hi"}], overrides={"max_tokens": 8192})

    assert out == b'{"model":"m","messages":[{"role":"user","content":"hi"}],"stream":true,"max_tokens":8192}'
