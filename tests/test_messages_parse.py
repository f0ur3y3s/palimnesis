"""Anthropic Messages parsing into the neutral Chat form (Phase 4B S2, core positions 2-3).

Pure tests of ``palimnesis.protocols.messages.parse``. Expected values come from the
plan's mapping (``docs/plan/phases/phase4b.md`` §2.1, D82) and from the M2 parity
fixture recorded against Strata 0.1.54 (``docs/probes/strata.md`` §13.2).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from palimnesis.protocols import chat, messages
from palimnesis.upstreams.strata import tokens

FIXTURE = (Path(__file__).resolve().parents[1] / "eval" / "probes" / "fixtures"
           / "strata_messages" / "p22_messages_render_parity.json")
WEATHER = {"name": "get_weather", "description": "Get the weather.",
           "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}}}


def body(msgs, **top) -> bytes:
    return json.dumps({"model": "m", "max_tokens": 64, **top, "messages": msgs},
                      ensure_ascii=False).encode()


def neutral(raw: bytes) -> dict:
    return json.loads(messages.parse(raw).chat_body)


def rejected(raw: bytes) -> str:
    with pytest.raises(chat.Unsupported) as e:
        messages.parse(raw)
    return e.value.field


# --- allowlist ------------------------------------------------------------------------------

@pytest.mark.parametrize("raw, field", [
    (body([{"role": "user", "content": "hi"}], top_k=5), "top_k"),
    (body([{"role": "user", "content": "hi"}], stop_sequences=["x"]), "stop_sequences"),
    (body([{"role": "user", "content": "hi"}], context_management={}), "context_management"),
    (body([{"role": "user", "content": "hi", "name": "u"}]), "messages[0].name"),
    (body([{"role": "user", "content": [{"type": "text", "text": "hi", "citations": []}]}]),
     "messages[0].content[0].citations"),
    (body([{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t",
                                          "content": "x", "extra": 1}]}]),
     "messages[0].content[0].extra"),
    (body([{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t",
                                          "content": [{"type": "text", "text": "x", "y": 1}]}]}]),
     "messages[0].content[0].content[0].y"),
    (body([{"role": "user", "content": "hi"}], system=[{"type": "text", "text": "s", "z": 1}]),
     "system[0].z"),
    (body([{"role": "user", "content": "hi"}], tools=[{**WEATHER, "strict": True}]),
     "tools[0].strict"),
    (body([{"role": "user", "content": "hi"}], tool_choice={"type": "auto",
                                                            "disable_parallel_tool_use": True}),
     "tool_choice.disable_parallel_tool_use"),
    (body([{"role": "user", "content": "hi"}], thinking={"type": "enabled", "foo": 1}),
     "thinking.foo"),
    (body([{"role": "user", "content": "hi"}], output_config={"effort": "low", "format": {}}),
     "output_config.format"),
    (body([{"role": "user", "content": "hi"}], metadata={"user_id": "u", "x": 1}), "metadata.x"),
    (body([{"role": "user", "content": [{"type": "text", "text": "hi",
                                          "cache_control": {"type": "ephemeral", "q": 1}}]}]),
     "messages[0].content[0].cache_control.q"),
])
def test_messages_rejects_unknown_fields_at_every_level(raw, field):
    assert rejected(raw) == field


@pytest.mark.parametrize("block, role", [
    ({"type": "redacted_thinking", "data": "abc"}, "assistant"),
    ({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AA=="}},
     "user"),
    ({"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": "x"}},
     "user"),
    ({"type": "server_tool_use", "id": "s", "name": "web_search", "input": {}}, "assistant"),
    ({"type": "web_search_tool_result", "tool_use_id": "s", "content": []}, "user"),
    ({"type": "tool_use", "id": "t", "name": "x", "input": {}}, "user"),
    ({"type": "tool_result", "tool_use_id": "t", "content": "x"}, "assistant"),
])
def test_redacted_thinking_image_document_server_tool_rejected(block, role):
    msgs = [{"role": "user", "content": "q"}, {"role": "assistant", "content": [block]},
            {"role": "user", "content": "next"}] if role == "assistant" else [
        {"role": "user", "content": [block]}]
    index = 1 if role == "assistant" else 0
    assert rejected(body(msgs)) == f"messages[{index}].content[0].type"


def test_server_tools_and_image_tool_results_are_rejected():
    assert rejected(body([{"role": "user", "content": "hi"}],
                         tools=[{"type": "web_search_20250305", "name": "web_search"}])) == "tools[0].type"
    image = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AA=="}}
    assert rejected(body([{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t", "content": [image]}]}])) == \
        "messages[0].content[0].content[0].type"


def test_reserved_palimnesis_names_and_other_tool_choices_are_rejected():
    assert rejected(body([{"role": "user", "content": "hi"}],
                         tools=[{**WEATHER, "name": "palimnesis_recall"}])) == "tools[0].name"
    assert rejected(body([{"role": "user", "content": "q"},
                          {"role": "assistant", "content": [{"type": "tool_use", "id": "t",
                                                             "name": "palimnesis_grep", "input": {}}]},
                          {"role": "user", "content": "n"}])) == "messages[1].content[0].name"
    for tc in ({"type": "any"}, {"type": "tool", "name": "get_weather"}):
        assert rejected(body([{"role": "user", "content": "hi"}], tools=[WEATHER],
                             tool_choice=tc)) == "tool_choice.type"


def test_invalid_bodies_and_prefill():
    for raw in (b"{", b"[]", json.dumps({"max_tokens": 5, "messages": []}).encode()):
        with pytest.raises(chat.InvalidBody):
            messages.parse(raw)
    assert rejected(json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode()) == \
        "max_tokens"
    assert rejected(body([{"role": "user", "content": "q"},
                          {"role": "assistant", "content": "prefill"}])) == "messages[1]"
    assert rejected(b'{"max_tokens": 5, "max_tokens": 6, "messages": [{"role": "user", '
                    b'"content": "hi"}]}') == "max_tokens"


# --- the neutral split --------------------------------------------------------------------

def test_tool_results_and_text_split_deterministically():
    raw = body([
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "plan ", "signature": ""},
            {"type": "thinking", "thinking": "more"},
            {"type": "text", "text": "a"}, {"type": "text", "text": "b"},
            {"type": "tool_use", "id": "t1", "name": "read", "input": {"p": 1}},
            {"type": "tool_use", "id": "t2", "name": "read", "input": {"p": 2}}]},
        {"role": "user", "content": [
            {"type": "text", "text": "see "},
            {"type": "tool_result", "tool_use_id": "t1", "content": "one"},
            {"type": "text", "text": "these"},
            {"type": "tool_result", "tool_use_id": "t2", "is_error": True,
             "content": [{"type": "text", "text": "tw"}, {"type": "text", "text": "o"}]}]}])

    assert neutral(raw)["messages"] == [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "ab", "reasoning_content": "plan more",
         "tool_calls": [
             {"id": "t1", "type": "function", "function": {"name": "read", "arguments": '{"p":1}'}},
             {"id": "t2", "type": "function", "function": {"name": "read", "arguments": '{"p":2}'}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "one"},
        {"role": "tool", "tool_call_id": "t2", "content": "two"},
        {"role": "user", "content": "see these"},
    ]
    req = messages.parse(raw)
    assert [m.role for m in req.messages] == ["user", "assistant", "tool", "tool", "user"]
    assert [b.kind for b in req.messages[1].blocks] == ["reasoning", "text", "tool_call", "tool_call"]
    assert [chat.content_sha256(m) for m in messages.parse(raw).messages] == \
        [chat.content_sha256(m) for m in req.messages]
    assert req.raw == raw


def test_an_assistant_turn_without_text_has_null_content_and_no_text_block():
    req = messages.parse(body([
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "t", "signature": ""},
                                          {"type": "tool_use", "id": "c", "name": "x", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c", "content": "r"}]}]))

    assert req.messages[1].raw_object["content"] is None
    assert [b.kind for b in req.messages[1].blocks] == ["reasoning", "tool_call"]
    assert [m.role for m in req.messages] == ["user", "assistant", "tool"]


def test_cache_control_moves_keep_content_hash():
    cc = {"type": "ephemeral"}
    first = messages.parse(body([
        {"role": "user", "content": [{"type": "text", "text": "q", "cache_control": cc}]}],
        system=[{"type": "text", "text": "s", "cache_control": cc}], tools=[{**WEATHER, "cache_control": cc}]))
    later = messages.parse(body([
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": [{"type": "text", "text": "a"}]},
        {"role": "user", "content": [{"type": "text", "text": "q2", "cache_control": cc}]}],
        system=[{"type": "text", "text": "s"}], tools=[WEATHER]))

    hashes = [chat.content_sha256(m) for m in first.messages]
    assert hashes == [chat.content_sha256(m) for m in later.messages[:2]]
    assert first.settings["tools"] == later.settings["tools"]
    assert first.messages[1].raw_object == later.messages[1].raw_object == {"role": "user", "content": "q"}


def test_tool_use_input_round_trips_exact_json():
    value = {"zeta": 1, "alpha": {"y": [1, 2.5, None, True], "x": "é 👋"}, "mid": "a\"b\\c\n"}
    raw = body([{"role": "user", "content": "q"},
                {"role": "assistant", "content": [{"type": "tool_use", "id": "c", "name": "w",
                                                   "input": value}]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c", "content": ""}]}])
    [call] = neutral(raw)["messages"][1]["tool_calls"]
    args = call["function"]["arguments"]

    assert args == '{"zeta":1,"alpha":{"y":[1,2.5,null,true],"x":"é 👋"},"mid":"a\\"b\\\\c\\n"}'
    assert list(json.loads(args)) == ["zeta", "alpha", "mid"] and json.loads(args) == value
    [block] = messages.parse(raw).messages[1].blocks
    assert block.text == args and (block.tool_call_id, block.name) == ("c", "w")


def test_a_system_message_stays_system_wherever_it_is():
    """D86: Strata renders a late one as user; the neutral form keeps the role, so the
    core treats it as fixed context, never as a user instruction."""
    late = neutral(body([{"role": "user", "content": "q"},
                         {"role": "system", "content": [{"type": "text", "text": "env"}]},
                         {"role": "user", "content": "q2"}], system="top"))
    first = neutral(body([{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]))
    both = neutral(body([{"role": "system", "content": "s"}, {"role": "user", "content": "q"}],
                        system="top"))

    assert [m["role"] for m in late["messages"]] == ["system", "user", "system", "user"]
    assert late["messages"][2] == {"role": "system", "content": "env"}
    assert [m["role"] for m in first["messages"]] == ["system", "user"]
    assert [m["role"] for m in both["messages"]] == ["system", "system", "user"]


def test_settings_map_to_the_chat_route():
    out = neutral(body([{"role": "user", "content": "hi"}], stream=True, system="s",
                       tools=[{"name": "n", "input_schema": {"type": "object"},
                               "eager_input_streaming": True}],
                       tool_choice={"type": "none"}, temperature=0.5, top_p=0.9,
                       metadata={"user_id": "u"}, thinking={"type": "adaptive"},
                       output_config={"effort": "max"}))

    assert list(out) == ["model", "max_tokens", "stream", "stream_options", "tools",
                         "tool_choice", "temperature", "top_p", "reasoning_effort", "messages"]
    assert out["stream_options"] == {"include_usage": True}
    assert out["tools"] == [{"type": "function", "function": {
        "name": "n", "description": "", "parameters": {"type": "object"}}}]
    assert (out["tool_choice"], out["reasoning_effort"], out["max_tokens"]) == ("none", "xhigh", 64)
    assert messages.parse(body([{"role": "user", "content": "x"}])).stream is False


@pytest.mark.parametrize("top, effort", [
    ({"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}}, "none"),
    ({"thinking": {"type": "adaptive"}, "output_config": {"effort": "medium"}}, "medium"),
    ({"output_config": {"effort": "high"}}, "high"),
    ({"thinking": {"type": "enabled", "budget_tokens": 1024}}, "low"),
    ({"thinking": {"type": "enabled", "budget_tokens": 7168, "display": "summarized"}}, "medium"),
    ({"thinking": {"type": "enabled", "budget_tokens": 16000}}, "xhigh"),
    ({"thinking": {"type": "enabled", "budget_tokens": 16000}, "output_config": {"effort": "low"}},
     "low"),
    ({"thinking": {"type": "enabled"}}, None),
    ({"thinking": {"type": "adaptive"}}, None),
])
def test_thinking_and_effort_map_as_strata_maps_them(top, effort):
    assert neutral(body([{"role": "user", "content": "x"}], **top)).get("reasoning_effort") == effort


def test_the_billing_stamp_is_pinned_as_strata_pins_it():
    stamp = "x-anthropic-billing-header: cc_version=2.1.318.cc7; cc_entrypoint=sdk-cli; cch=b145e;"
    a = messages.parse(body([{"role": "user", "content": "q"}],
                            system=[{"type": "text", "text": stamp}, {"type": "text", "text": "\nS"}]))
    b = messages.parse(body([{"role": "user", "content": "q"}],
                            system=stamp.replace("cc7", "0eb").replace("b145e", "0a1b2") + "\nS"))

    assert a.messages[0].raw_object["content"] == (
        "x-anthropic-billing-header: cc_version=2.1.318.fff; cc_entrypoint=sdk-cli; cch=fffff;\nS")
    assert chat.content_sha256(a.messages[0]) == chat.content_sha256(b.messages[0])
    assert messages.pin_billing_stamp("no stamp cch=abc;") == "no stamp cch=abc;"


# --- parity with Strata's Messages route (M2 fixture) ---------------------------------------

REJECTED_CASES = {
    "redacted_thinking", "document_block", "unknown_role", "effort_bogus", "tool_choice_any",
    "tool_choice_tool", "tool_choice_auto_no_parallel", "top_k", "top_k_string",
    "stop_sequences", "stop_sequences_string", "unknown_top_level_field",
}


def test_parity_corpus_counts_equal_recorded_count_tokens():
    """Every M2 case the subset accepts counts, locally on its neutral Chat body, exactly
    the prompt Strata's Messages route rendered (``mr``); the rest are rejected."""
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    counter = tokens.default()
    accepted, refused, mismatched = [], set(), []
    for case in cases:
        doc = {"max_tokens": 1, **case["messages_body"]}
        try:
            req = messages.parse(json.dumps(doc, ensure_ascii=False).encode())
        except chat.Unsupported:
            refused.add(case["name"])
            continue
        accepted.append(case["name"])
        assert case["mr"]["status"] == 200, case["name"]
        count = counter.count_messages(**tokens.render_args_from_openai(json.loads(req.chat_body)))
        if count != case["mr"]["prompt"]:
            mismatched.append((case["name"], count, case["mr"]["prompt"]))

    assert refused == REJECTED_CASES
    assert len(accepted) == len(cases) - len(REJECTED_CASES)
    assert mismatched == []
