"""The Pi needle driver's pure parts (Phase 4B S14): a Chat history as a Pi 1.5.0 session file,
what Pi is expected to resend, the import-fidelity comparison, the turn summary from
``pi --mode json`` events and the driver's refusals. Shapes come from ``docs/probes/pi.md``
(HP3, HP7) and a session file Pi 1.5.0 wrote; nothing here runs Pi, a proxy or a model."""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval")]

import needle  # noqa: E402
import needle_pi  # noqa: E402
import pi_harness as pi  # noqa: E402

sys.path.remove(str(ROOT / "eval"))

T0 = 1_793_872_800_000  # 2026-11-05T10:00:00.000Z
CALL = {"id": "call_1", "type": "function",
        "function": {"name": "read", "arguments": '{"path":"src/a.py"}'}}
HISTORY = [
    {"role": "user", "content": "Read src/a.py."},
    {"role": "assistant", "content": None, "tool_calls": [CALL]},
    {"role": "tool", "tool_call_id": "call_1", "content": "1: x = 1"},
    {"role": "assistant", "content": "It sets x.", "reasoning_content": "Short file."},
]


def convert(history=HISTORY, **kw):
    kw.setdefault("model", "m")
    return pi.history_to_pi_session(history, session_id="dev-h1-a4-d77-t-a1", cwd="/w",
                                    t0_ms=T0, seed=7, **kw)


def test_session_header_is_version_3_with_id_and_cwd():
    assert convert()[0] == {"type": "session", "version": 3, "id": "dev-h1-a4-d77-t-a1",
                            "timestamp": "2026-11-05T10:00:00.000Z", "cwd": "/w"}


def test_messages_become_pi_entries():
    msgs = [e["message"] for e in convert()[1:]]
    assert msgs[0] == {"role": "user", "content": [{"type": "text", "text": "Read src/a.py."}],
                       "timestamp": T0 + 1000}
    assert msgs[1]["content"] == [{"type": "toolCall", "id": "call_1", "name": "read",
                                   "arguments": {"path": "src/a.py"}}]
    assert (msgs[1]["role"], msgs[1]["api"], msgs[1]["provider"], msgs[1]["model"],
            msgs[1]["stopReason"]) == ("assistant", "openai-completions", "palimnesis", "m", "toolUse")
    assert msgs[1]["usage"]["totalTokens"] == 0
    assert msgs[2] == {"role": "toolResult", "toolCallId": "call_1", "toolName": "read",
                       "content": [{"type": "text", "text": "1: x = 1"}], "isError": False,
                       "timestamp": T0 + 3000}
    assert msgs[3]["content"] == [
        {"type": "thinking", "thinking": "Short file.", "thinkingSignature": "reasoning_content"},
        {"type": "text", "text": "It sets x."}]
    assert msgs[3]["stopReason"] == "stop"


def test_entries_chain_by_parent_id_with_unique_ids():
    entries = convert()[1:]
    assert all(e["type"] == "message" for e in entries)
    assert entries[0]["parentId"] is None
    assert [e["parentId"] for e in entries[1:]] == [e["id"] for e in entries[:-1]]
    assert len({e["id"] for e in entries}) == len(entries)
    assert all(len(e["id"]) == 8 and int(e["id"], 16) >= 0 for e in entries)
    assert entries[-1]["timestamp"] == "2026-11-05T10:00:04.000Z"


def test_messages_protocol_uses_the_messages_provider_and_an_empty_signature():
    msgs = [e["message"] for e in convert(protocol="messages")[1:]]
    assert (msgs[1]["api"], msgs[1]["provider"]) == ("anthropic-messages", "palimnesis-messages")
    assert msgs[3]["content"][0] == {"type": "thinking", "thinking": "Short file.", "thinkingSignature": ""}


def test_session_jsonl_is_one_json_object_per_line():
    raw = pi.session_jsonl(convert())
    lines = raw.decode("utf-8").split("\n")
    assert lines[-1] == "" and len(lines) == 6
    assert [json.loads(x) for x in lines[:-1]] == convert()


@pytest.mark.parametrize("history, why", [
    ([{"role": "user", "content": "q"}, {"role": "assistant", "content": "  \n"}], "whitespace-only assistant text"),
    ([{"role": "user", "content": "q"}, {"role": "assistant", "content": "a", "reasoning_content": " "}],
     "whitespace-only reasoning"),
    ([{"role": "user", "content": "q"}, {"role": "assistant", "content": None}], "no text, reasoning or calls"),
    ([{"role": "user", "content": "q"},
      {"role": "assistant", "content": None, "tool_calls": [dict(CALL, function={"name": "read", "arguments": '{"path": "a"}'})]},
      {"role": "tool", "tool_call_id": "call_1", "content": "r"}], "not compact"),
    ([{"role": "user", "content": "q"},
      {"role": "assistant", "content": None, "tool_calls": [dict(CALL, function={"name": "read", "arguments": "[1]"})]},
      {"role": "tool", "tool_call_id": "call_1", "content": "r"}], "not an object"),
    ([{"role": "user", "content": "q"}, {"role": "assistant", "content": None, "tool_calls": [CALL]}],
     "without a result"),
    ([{"role": "user", "content": "q"}, {"role": "tool", "tool_call_id": "call_9", "content": "r"}], "answers no call"),
    ([{"role": "user", "content": "q"}, {"role": "assistant", "content": None, "tool_calls": [CALL]},
      {"role": "user", "content": "again"}, {"role": "tool", "tool_call_id": "call_1", "content": "r"}],
     "before the results"),
    ([{"role": "system", "content": "s"}], "unsupported role"),
    ([{"role": "user", "content": [{"type": "image_url", "image_url": {}}]}], "text parts"),
])
def test_histories_pi_would_not_resend_verbatim_are_refused(history, why):
    with pytest.raises(ValueError, match=why):
        convert(history)


def test_js_compact_matches_json_stringify():
    assert pi.js_compact({"a": 1.0, "b": [2.5, "é"], "c": {"d": None}}) == '{"a":1,"b":[2.5,"é"],"c":{"d":null}}'


def test_every_development_history_converts():
    for path in sorted((ROOT / "eval" / "needles" / "dev").glob("dev-h*.json")):
        h = json.loads(path.read_text(encoding="utf-8"))
        history = needle_pi.import_history(h)
        entries = convert(history)
        assert len(entries) == 1 + len(history), path.name


# ---------------------------------------------------------------- fidelity

def pi_chat_body(messages):
    return {"model": "m", "stream": True, "tools": [{"type": "function", "function": {"name": "read"}}],
            "messages": [{"role": "system", "content": "You are a coding assistant running inside pi"}] + messages}


def test_expected_chat_sends_user_content_as_text_parts_and_ends_with_the_question():
    want = pi.expected_chat(HISTORY, "Q1?")
    assert want[0] == {"role": "user", "content": [{"type": "text", "text": "Read src/a.py."}]}
    assert want[1:4] == HISTORY[1:]
    assert want[-1] == {"role": "user", "content": [{"type": "text", "text": "Q1?"}]}


def test_chat_fidelity_allows_pis_system_message_and_tools():
    fid = pi.chat_fidelity(pi_chat_body(pi.expected_chat(HISTORY, "Q1?")), HISTORY, "Q1?")
    assert fid["faithful"] and fid["first_diff"] is None
    assert (fid["messages_sent"], fid["messages_expected"]) == (5, 5)
    assert fid["system_sent"] and fid["tools_sent"] == ["read"]


def test_chat_fidelity_finds_the_first_difference():
    sent = pi.expected_chat(HISTORY, "Q1?")
    sent[1] = dict(sent[1], tool_calls=[dict(CALL, function={"name": "read", "arguments": '{"path": "src/a.py"}'})])
    fid = pi.chat_fidelity(pi_chat_body(sent), HISTORY, "Q1?")
    assert not fid["faithful"] and fid["first_diff"] == 1 and "diff" in fid
    short = pi.chat_fidelity(pi_chat_body(pi.expected_chat(HISTORY, "Q1?")[:-1]), HISTORY, "Q1?")
    assert short["first_diff"] == 4
    plain = pi.chat_fidelity(pi_chat_body([{"role": "user", "content": "Read src/a.py."}]), HISTORY, "Q1?")
    assert plain["first_diff"] == 0  # a string where Pi sends text parts


def test_messages_fidelity_compares_the_canonical_sequence():
    body = {"system": [{"type": "text", "text": "pi", "cache_control": {"type": "ephemeral"}}],
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "Read src/a.py."}]},
                {"role": "assistant", "content": [{"type": "tool_use", "id": "call_1", "name": "read",
                                                   "input": {"path": "src/a.py"}}]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1",
                                              "content": "1: x = 1", "is_error": False}]},
                {"role": "assistant", "content": [{"type": "thinking", "thinking": "Short file.", "signature": ""},
                                                  {"type": "text", "text": "It sets x."}]},
                {"role": "user", "content": [{"type": "text", "text": "Q1?",
                                              "cache_control": {"type": "ephemeral"}}]}]}
    fid = pi.chat_fidelity(body, HISTORY, "Q1?", protocol="messages")
    assert fid["faithful"], fid
    assert pi.canonical(body["messages"])[1] == ("call", "call_1", "read", {"path": "src/a.py"})
    body["messages"][2]["content"][0]["content"] = "changed"
    assert pi.chat_fidelity(body, HISTORY, "Q1?", protocol="messages")["first_diff"] == 2


def test_last_user_text_reads_either_protocol():
    assert pi.last_user_text({"messages": [{"role": "user", "content": [{"type": "text", "text": "a"}]},
                                           {"role": "assistant", "content": "b"}]}) == "a"
    assert pi.last_user_text({"messages": [{"role": "user", "content": "s"}]}) == "s"
    assert pi.last_user_text({"messages": [
        {"role": "user", "content": [{"type": "text", "text": "q"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "r"}]}]}) == "q"


# ---------------------------------------------------------------- turn summary

def assistant(content, stop, **extra):
    return {"type": "message_end", "message": {"role": "assistant", "content": content, "stopReason": stop, **extra}}


def test_turn_summary_reads_the_final_answer_and_tool_calls():
    events = [
        {"type": "session", "id": "s"}, {"type": "agent_start"},
        assistant([{"type": "thinking", "thinking": "t"}, {"type": "text", "text": "Reading."},
                   {"type": "toolCall", "id": "c1", "name": "grep", "arguments": {"pattern": "X"}}], "toolUse"),
        {"type": "tool_execution_start", "toolCallId": "c1", "toolName": "grep", "args": {"pattern": "X"}},
        {"type": "tool_execution_end", "toolCallId": "c1", "toolName": "grep",
         "result": {"content": [{"type": "text", "text": "a.md:3: X"}]}, "isError": False},
        assistant([{"type": "text", "text": "HAR-6715-L"}], "stop"),
        {"type": "agent_end"}, {"type": "agent_settled", "aborted": False}]
    s = pi.turn_summary(events)
    assert s["final"] == "HAR-6715-L"
    assert s["tools"] == [{"name": "grep", "input": {"pattern": "X"}, "error": False, "output_chars": 9}]
    assert s["stops"] == ["toolUse", "stop"] and s["errors"] == [] and s["settled"] is True


def test_turn_summary_has_no_answer_after_a_failed_partial_or_a_kill():
    failed = pi.turn_summary([assistant([{"type": "text", "text": "Partial"}], "error", errorMessage="terminated"),
                              {"type": "agent_settled", "aborted": False}])
    assert failed["final"] is None and failed["errors"] == ["error: terminated"]
    killed = pi.turn_summary([assistant([{"type": "toolCall", "id": "c", "name": "bash", "arguments": {}}], "toolUse"),
                              {"type": "tool_execution_start", "toolCallId": "c", "toolName": "bash", "args": {}}])
    assert killed["final"] is None and killed["settled"] is None
    assert killed["tools"] == [{"name": "bash", "input": {}, "error": True, "output_chars": 0}]


def test_as_export_has_the_shape_the_gate_scans_read():
    entries = convert() + [{"type": "message", "message": {
        "role": "assistant", "content": [{"type": "text", "text": "done"}], "stopReason": "stop"}}]
    ex = pi.as_export(entries)
    assistants = [m for m in ex["messages"] if m["type"] == "assistant"]
    assert assistants[0]["content"] == [{"type": "tool", "id": "call_1", "name": "read", "state": {
        "input": {"path": "src/a.py"}, "content": [{"type": "text", "text": "1: x = 1"}]}}]
    assert assistants[1]["content"] == [{"type": "reasoning", "text": "Short file."},
                                        {"type": "text", "text": "It sets x."}]
    assert assistants[2]["content"] == [{"type": "text", "text": "done"}]


# ---------------------------------------------------------------- refusals

def args(**kw):
    base = dict(config=needle.A4_HELDOUT3, set="development", upstream="http://127.0.0.1:18080",
                questions=None, input_budget=None, resume=False)
    return Namespace(**{**base, **kw})


def test_pi_driver_runs_a4_d77_only():
    h = [Path("dev-h1.json")]
    assert needle_pi.refusals(args(), h) == []
    assert any("arm 4 only" in p for p in needle_pi.refusals(args(config="a4-d43"), h))
    assert any("--resume" in p for p in needle_pi.refusals(args(resume=True), h))
    assert needle_pi.refusals(args(), []) == ["no histories selected"]


def test_held_out_sets_keep_their_protections(monkeypatch):
    monkeypatch.setattr(needle_pi.nod.gi, "git_provenance", lambda: {"dirty": False, "status": []})
    h = [Path("ho3-h1.json")]
    assert any("O-4B-11" in p for p in needle_pi.refusals(args(set="heldout3"), h))
    retired = needle_pi.refusals(args(set="heldout2", upstream="fake", questions=1, input_budget=24320), h)
    assert any("fake upstream" in p for p in retired)
    assert any("--questions" in p for p in retired)
    assert any("--input-budget" in p for p in retired)
