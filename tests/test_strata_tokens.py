"""Pinned template + tokenizer (contracts §1.3): local render and count equal Strata's.

Expected values are literal fixtures recorded from the live server (Phase 0 probes and
the OpenCode 2.1.4 live capture), never recomputed the way the code computes them.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from palimnesis.upstreams.strata import pins, tokens

ROOT = Path(__file__).resolve().parents[1]
PROBES = ROOT / "eval" / "probes" / "fixtures"
LIVE = ROOT / "eval" / "fixtures" / "opencode-2.1.4" / "live" / "exchanges"

TEMPLATE_SHA = "12827f24b742ea4e80cdc12dbcf9622227056b9f797252a3149263d4f9aaadce"
TOKENIZER_SHA = "0997f410c57a1f4e53b09e4be8f4a172d90edd9564368fb0847030937229b9f3"


def test_default_pin_loads_verified():
    pin = pins.load()
    assert pin.id.startswith("strata-0.1.48@")
    assert pin.build_info == "Strata 0.1.48"
    assert pin.template_sha256 == TEMPLATE_SHA
    assert pin.tokenizer_sha256 == TOKENIZER_SHA
    assert pin.chat_template == (PROBES / "strata_chat_template.jinja").read_text(encoding="utf-8")


@pytest.mark.parametrize("victim", ["chat_template.jinja", "tokenizer.json", "PIN.json"])
def test_tampered_pin_file_raises(tmp_path, victim):
    src = pins.pin_dir()
    dst = tmp_path / src.name
    shutil.copytree(src, dst)
    data = (dst / victim).read_bytes()
    (dst / victim).write_bytes(data[:-2] + b" " + data[-1:])
    with pytest.raises(pins.PinError, match=victim):
        pins.load(dst)


def test_missing_pin_file_raises(tmp_path):
    dst = tmp_path / "strata-0.1.48"
    shutil.copytree(pins.pin_dir(), dst)
    (dst / "tokenizer.json").unlink()
    with pytest.raises(pins.PinError, match="tokenizer.json"):
        pins.load(dst)


# --- render: p02's cases, inputs copied literally from eval/probes/p02_template_render.py ---

TH = "Let me think about this carefully step by step with many words of reasoning here."
BARE_TOOLS = [{"name": "get_weather", "description": "Get the current weather for a city.",
               "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}]
OA_TOOLS = [{"type": "function", "function": BARE_TOOLS[0]}]
Q1 = [{"role": "user", "content": "Q1"}]
PRIOR = Q1 + [{"role": "assistant", "content": "Answer one."}, {"role": "user", "content": "Q2"}]
PRIOR_TH = Q1 + [{"role": "assistant", "content": "Answer one.", "reasoning_content": TH},
                 {"role": "user", "content": "Q2"}]
TOOL_TURN = [
    {"role": "user", "content": "Weather in Paris?"},
    {"role": "assistant", "content": "", "reasoning_content": TH,
     "tool_calls": [{"id": "c1", "type": "function",
                     "function": {"name": "get_weather", "arguments": {"city": "Paris"}}}]},
    {"role": "tool", "tool_call_id": "c1", "content": "Sunny 20C"},
]

# (golden render file, messages, tools, render kwargs)
RENDER_CASES = [
    ("user_default", Q1, None, {}),
    ("user_thinking_disabled", Q1, None, {"enable_thinking": False}),
    ("user_effort_low", Q1, None, {"effort": "low"}),
    ("user_effort_medium", Q1, None, {"effort": "medium"}),
    ("system_user", [{"role": "system", "content": "You are terse."}] + Q1, None, {}),
    ("prior_text", PRIOR, None, {}),
    ("prior_thinking", PRIOR_TH, None, {}),
    ("tools_only", Q1, BARE_TOOLS, {}),
    ("tool_turn_think", TOOL_TURN, BARE_TOOLS, {}),
]


def _golden(name: str) -> str:
    return (PROBES / f"render_{name}.txt").read_bytes().decode("utf-8")


@pytest.mark.parametrize("name,messages,tools,kw", RENDER_CASES, ids=[c[0] for c in RENDER_CASES])
def test_local_render_equals_render_fixtures_text(name, messages, tools, kw):
    from palimnesis.upstreams.strata import tokens

    assert tokens.render(messages, tools, **kw) == _golden(name)


def test_render_applies_strata_preprocessing_wrapped_tools_and_string_arguments():
    """OpenAI-wrapped tools render bare; string arguments render as parsed mappings."""
    from palimnesis.upstreams.strata import tokens

    as_openai = [TOOL_TURN[0],
                 {**TOOL_TURN[1], "tool_calls": [{"id": "c1", "type": "function",
                                                  "function": {"name": "get_weather",
                                                               "arguments": '{"city": "Paris"}'}}]},
                 TOOL_TURN[2]]
    assert tokens.render(as_openai, OA_TOOLS) == _golden("tool_turn_think")


# --- count: server counts recorded in count_tokens.json / template_render_check*.json ---

TOOL_TURN_NO_THINK = [TOOL_TURN[0], {k: v for k, v in TOOL_TURN[1].items() if k != "reasoning_content"},
                      TOOL_TURN[2]]

# (count_tokens.json case, messages, tools, render kwargs) -- Anthropic requests there,
# the same conversations in OpenAI shape here.
COUNT_CASES = [
    ("user_only_default", Q1, None, {}),
    ("user_only_thinking_disabled", Q1, None, {"enable_thinking": False}),
    ("user_only_effort_low", Q1, None, {"effort": "low"}),
    ("user_only_effort_medium", Q1, None, {"effort": "medium"}),
    ("user_only_effort_high", Q1, None, {"effort": "high"}),
    ("system_plus_user", [{"role": "system", "content": "You are terse."}] + Q1, None, {}),
    ("prior_turn_text", PRIOR, None, {}),
    ("prior_turn_thinking", PRIOR_TH, None, {}),
    ("prior_turn_text_thinking_disabled", PRIOR, None, {"enable_thinking": False}),
    ("prior_turn_thinking_thinking_disabled", PRIOR_TH, None, {"enable_thinking": False}),
    ("tools_only", Q1, BARE_TOOLS, {}),
    ("tool_turn_no_think", TOOL_TURN_NO_THINK, BARE_TOOLS, {}),
    ("tool_turn_think", TOOL_TURN, BARE_TOOLS, {}),
    ("trailing_assistant_prefill", Q1 + [{"role": "assistant", "content": "Partial"}], None, {}),
]
SERVER_COUNTS = {k: v["body"]["input_tokens"]
                 for k, v in json.loads((PROBES / "count_tokens.json").read_text(encoding="utf-8")).items()
                 if v["status"] == 200}


@pytest.mark.parametrize("case,messages,tools,kw", COUNT_CASES, ids=[c[0] for c in COUNT_CASES])
def test_local_count_equals_count_tokens_fixture(case, messages, tools, kw):
    from palimnesis.upstreams.strata import tokens

    assert tokens.count_messages(messages, tools, **kw) == SERVER_COUNTS[case]


def test_local_count_equals_check_json():
    from palimnesis.upstreams.strata import tokens

    check = json.loads((PROBES / "template_render_check.json").read_text(encoding="utf-8"))
    for name, _, _, _ in RENDER_CASES:
        assert tokens.count(_golden(name)) == check[name]["server_count_tokens"], name


OA_FIXTURES = ["oa_prior_reasoning", "oa_prior_reasoning_preserve_false", "oa_prior_no_reasoning",
               "oa_effort_none", "oa_enable_thinking_false", "oa_default_think_low", "oa_tool_call",
               "oa_tool_followup"]


@pytest.mark.parametrize("case", OA_FIXTURES)
def test_local_count_of_openai_request_equals_usage_prompt_tokens(case):
    """Whole recorded request bodies: wrapped tools, string arguments, effort none, kwargs."""
    from palimnesis.upstreams.strata import tokens

    rec = json.loads((PROBES / f"nonstream_{case}.json").read_text(encoding="utf-8"))
    args = tokens.render_args_from_openai(rec["request"])
    assert tokens.count_messages(**args) == rec["body"]["usage"]["prompt_tokens"]


def _live_exchanges():
    out = []
    for d in sorted(p for p in LIVE.glob("*/*") if p.is_dir()):
        usage = re.findall(rb'"usage": \{"prompt_tokens": (\d+)', (d / "response.body").read_bytes())
        out.append(pytest.param(d, int(usage[-1]), id=d.name))
    return out


LIVE_EXCHANGES = _live_exchanges()


def test_live_fixture_set_is_complete():
    assert len(LIVE_EXCHANGES) == 10


@pytest.mark.parametrize("exchange,prompt_tokens", LIVE_EXCHANGES)
def test_local_count_equals_live_usage_prompt_tokens(exchange, prompt_tokens):
    from palimnesis.upstreams.strata import tokens

    body = json.loads((exchange / "request.body").read_bytes())
    assert tokens.count_messages(**tokens.render_args_from_openai(body)) == prompt_tokens


# --- fragment cache: additivity and fallback ---


def _all_golden_texts():
    texts = [_golden(name) for name, _, _, _ in RENDER_CASES]
    expected = [json.loads((PROBES / "template_render_check.json").read_text(encoding="utf-8"))[name]
                ["server_count_tokens"] for name, _, _, _ in RENDER_CASES]
    return list(zip(texts, expected))


def test_startup_self_test_finds_fragments_additive():
    from palimnesis.upstreams.strata import tokens

    assert tokens.default().fragments_ok is True


def test_fragment_sum_equals_full_count():
    from palimnesis.upstreams.strata import tokens

    t = tokens.default()
    for text, expected in _all_golden_texts():
        fragments = tokens.split_fragments(text)
        assert "".join(fragments) == text
        assert sum(t.count(f) for f in fragments) == expected
    for exchange, prompt_tokens in (p.values for p in LIVE_EXCHANGES):
        text = t.render(**tokens.render_args_from_openai(json.loads((exchange / "request.body").read_bytes())))
        fragments = tokens.split_fragments(text)
        assert len(fragments) >= 3
        assert sum(t.count(f) for f in fragments) == prompt_tokens


def test_warm_count_is_served_from_fragment_cache():
    from palimnesis.upstreams.strata import pins, tokens

    t = tokens.Tokens(pins.load())
    body = json.loads((LIVE_EXCHANGES[-1].values[0] / "request.body").read_bytes())
    args = tokens.render_args_from_openai(body)
    first = t.count_messages(**args)
    misses = t.cache_stats()["misses"]
    assert t.count_messages(**args) == first == LIVE_EXCHANGES[-1].values[1]
    stats = t.cache_stats()
    assert stats["misses"] == misses and stats["hits"] >= len(tokens.split_fragments(t.render(**args)))


def test_non_additive_split_falls_back_to_full_counting():
    """A split that cuts inside words is not additive: the self-test must catch it."""
    from palimnesis.upstreams.strata import pins, tokens

    t = tokens.Tokens(pins.load(), split_tokens=("e",))
    assert t.fragments_ok is False
    exchange, prompt_tokens = LIVE_EXCHANGES[0].values
    args = tokens.render_args_from_openai(json.loads((exchange / "request.body").read_bytes()))
    assert t.count_messages(**args) == prompt_tokens


def test_lone_surrogates_are_counted_as_replacement_characters_not_an_error():
    t = tokens.default()

    assert t.count("a\ud83d") == t.count("a�")
    assert t.count_cached("b\udc00") == t.count("b�")
    rendered = t.render([{"role": "user", "content": "x\ud83d"}])
    assert t.count_rendered(rendered) == t.count(rendered.replace("\ud83d", "�"))


# --- Strata's message normalization (R21-A, R21-B; eval/probes/p12_strata_normalization.py) ---

NORMALIZATION = json.loads((PROBES / "strata_normalization.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", sorted(NORMALIZATION["cases"]))
def test_local_count_equals_strata_after_its_normalization(case):
    """Empty completed assistant turns are dropped (#843); malformed tool-call
    arguments render as text under "arguments", empty ones as {} (#510)."""
    rec = NORMALIZATION["cases"][case]
    body = {"messages": rec["messages"], "tools": NORMALIZATION["tools"]}

    assert tokens.count_messages(**tokens.render_args_from_openai(body)) == rec["prompt_tokens"]


def test_a_final_empty_assistant_message_is_kept():
    t = tokens.default()
    head = [{"role": "user", "content": "Say a number."}]

    assert t.render(head + [{"role": "assistant", "content": ""}], add_generation_prompt=False) \
        != t.render(head, add_generation_prompt=False)


def test_a_dropped_empty_turn_keeps_the_layout_mapped():
    t = tokens.default()
    messages = NORMALIZATION["cases"]["empty_turn_empty_string"]["messages"]

    layout = t.layout(messages, NORMALIZATION["tools"])

    assert len(layout.ids) == NORMALIZATION["cases"]["empty_turn_empty_string"]["prompt_tokens"]
    assert all(s.kind != "unmapped" for s in layout.segments)
    [empty] = [s for s in layout.segments if s.messages == (2,)]
    assert empty.start == empty.end
