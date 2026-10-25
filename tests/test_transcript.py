"""Reconciling a client resend against the archived visible history (pure seam).

Outcomes (docs/plans/phase1.md; D10.3-D10.6):
- Extend(k, ...): client messages [0, k) match the archive; the rest are new.
- Prefix(k): the client resent only the first k archived messages (a retry).
- Divergence(index, reason): history was edited, truncated or forged.
"""

from __future__ import annotations

import json

import pytest

from palimnesis.chat import parse
from palimnesis.transcript import Archived, Divergence, Extend, Prefix, reconcile


def client(*messages) -> tuple:
    body = {"model": "m", "messages": list(messages)}
    if messages[-1]["role"] == "assistant":  # parse() forbids a trailing assistant
        body["messages"].append({"role": "user", "content": "__tail__"})
        return parse(json.dumps(body).encode()).messages[:-1]
    return parse(json.dumps(body).encode()).messages


def archived_client(message) -> Archived:
    return Archived.from_client(f"occ-{id(message)}", message)


def generated(text="", reasoning="", tool_calls=(), complete=True) -> Archived:
    return Archived.generated("occ-gen", text=text, reasoning=reasoning,
                              tool_calls=tuple(tool_calls), complete=complete)


SYS = {"role": "system", "content": "You are helpful. Today is 2026-10-24."}
U1 = {"role": "user", "content": "write hello.py"}
U2 = {"role": "user", "content": "now run it"}
CALL = {"id": "call_1", "name": "write", "arguments": '{"path":"hello.py"}'}
A1 = {"role": "assistant", "content": None, "reasoning_content": "I will write it.",
      "tool_calls": [{"id": "call_1", "type": "function",
                      "function": {"name": "write", "arguments": '{"path":"hello.py"}'}}]}
T1 = {"role": "tool", "tool_call_id": "call_1", "content": "ok"}


def _archive(*parts):
    return [p if isinstance(p, Archived) else archived_client(client(p)[0]) for p in parts]


def test_first_request_extends_an_empty_archive_from_zero():
    msgs = client(SYS, U1)

    assert reconcile(msgs, []) == Extend(0)


def test_appended_turns_extend_the_archive():
    archive = _archive(SYS, U1, generated(reasoning="I will write it.", tool_calls=[CALL]))
    msgs = client(SYS, U1, A1, T1)

    assert reconcile(msgs, archive) == Extend(3)


def test_generated_assistant_matches_when_client_omits_reasoning():
    archive = _archive(SYS, U1, generated(reasoning="I will write it.", tool_calls=[CALL]))
    without_reasoning = {k: v for k, v in A1.items() if k != "reasoning_content"}

    assert reconcile(client(SYS, U1, without_reasoning, T1), archive) == Extend(3)


@pytest.mark.parametrize("content", [None, "", "absent"])
def test_generated_empty_text_matches_null_empty_or_absent_content(content):
    archive = _archive(SYS, U1, generated(tool_calls=[CALL]))
    a = {k: v for k, v in A1.items() if k not in ("content", "reasoning_content")}
    if content != "absent":
        a["content"] = content

    assert reconcile(client(SYS, U1, a, T1), archive) == Extend(3)


def test_resend_of_only_the_archived_prefix_is_a_retry_not_an_extension():
    archive = _archive(SYS, U1, generated(text="done"))

    assert reconcile(client(SYS, U1), archive) == Prefix(2)


def test_edited_earlier_user_message_diverges_at_its_index():
    archive = _archive(SYS, U1, generated(text="done"))
    edited = {"role": "user", "content": "write hello2.py"}

    result = reconcile(client(SYS, edited, {"role": "assistant", "content": "done"}, U2), archive)

    assert isinstance(result, Divergence) and result.index == 1


def test_changed_generated_text_diverges():
    archive = _archive(SYS, U1, generated(text="done"))
    forged = {"role": "assistant", "content": "done!"}

    result = reconcile(client(SYS, U1, forged, U2), archive)

    assert isinstance(result, Divergence) and result.index == 2


def test_changed_reasoning_diverges_but_omitted_reasoning_does_not():
    archive = _archive(SYS, U1, generated(text="done", reasoning="think"))
    changed = {"role": "assistant", "content": "done", "reasoning_content": "thought"}

    result = reconcile(client(SYS, U1, changed, U2), archive)

    assert isinstance(result, Divergence) and result.index == 2


def test_changed_tool_call_arguments_diverge():
    archive = _archive(SYS, U1, generated(tool_calls=[CALL]))
    a = json.loads(json.dumps(A1))
    a["tool_calls"][0]["function"]["arguments"] = '{"path":"hello2.py"}'

    result = reconcile(client(SYS, U1, a, T1), archive)

    assert isinstance(result, Divergence) and result.index == 2


def test_tool_arguments_reserialized_by_the_client_still_match():
    # OpenCode parses streamed arguments and resends JSON.stringify output
    # (eval/fixtures/opencode-2.1.4/live exchange 4 → request 5).
    streamed = {"id": "call_1", "name": "write", "arguments": '{"path": "hello.py", "n": [1, 2]}'}
    archive = _archive(SYS, U1, generated(reasoning="I will write it.", tool_calls=[streamed]))
    a = json.loads(json.dumps(A1))
    a["tool_calls"][0]["function"]["arguments"] = '{"path":"hello.py","n":[1,2]}'

    assert reconcile(client(SYS, U1, a, T1), archive) == Extend(3)


def test_non_json_tool_arguments_must_match_exactly():
    archive = _archive(SYS, U1, generated(tool_calls=[dict(CALL, arguments="not json")]))
    a = json.loads(json.dumps(A1))
    a["tool_calls"][0]["function"]["arguments"] = "not  json"

    result = reconcile(client(SYS, U1, a, T1), archive)

    assert isinstance(result, Divergence) and result.index == 2


def test_assistant_message_palimnesis_never_generated_diverges():
    archive = _archive(SYS, U1, U2)  # archived as client-sent users only
    result = reconcile(client(SYS, U1, {"role": "assistant", "content": "hi"}, U2), archive)

    assert isinstance(result, Divergence) and result.index == 2


def test_truncated_history_with_a_new_user_message_diverges():
    archive = _archive(SYS, U1, generated(text="done"), U2, generated(text="ran"))

    result = reconcile(client(SYS, U1, {"role": "assistant", "content": "done"},
                              {"role": "user", "content": "different"}), archive)

    assert isinstance(result, Divergence) and result.index == 3


def test_changed_leading_system_message_is_a_context_version_not_divergence():
    archive = _archive(SYS, U1, generated(text="done"))
    tomorrow = {"role": "system", "content": "You are helpful. Today is 2026-10-25."}

    assert reconcile(client(tomorrow, U1, {"role": "assistant", "content": "done"}, U2), archive) == Extend(
        3, context_changed=(0,)
    )


def test_changed_system_message_after_the_first_user_turn_diverges():
    archive = _archive(SYS, U1, generated(text="done"), {"role": "system", "content": "note A"})

    result = reconcile(client(SYS, U1, {"role": "assistant", "content": "done"},
                              {"role": "system", "content": "note B"}, U2), archive)

    assert isinstance(result, Divergence) and result.index == 3


def test_identical_user_text_twice_is_two_positions_not_a_match_shortcut():
    archive = _archive(SYS, U1, generated(text="done"))
    msgs = client(SYS, U1, {"role": "assistant", "content": "done"}, U1)

    assert reconcile(msgs, archive) == Extend(3)


def test_hidden_internal_occurrences_are_not_part_of_the_visible_history():
    hidden_call = Archived.generated("occ-h", text="", reasoning="", tool_calls=(
        {"id": "m1", "name": "palimnesis_recall", "arguments": "{}"},), complete=True, view="internal")
    hidden_result = Archived("occ-r", role="tool", source="internal_tool", view="internal",
                             content_sha256="x")
    archive = _archive(SYS, U1, hidden_call, hidden_result, generated(text="done"))

    assert reconcile(client(SYS, U1, {"role": "assistant", "content": "done"}, U2), archive) == Extend(3)


# --- Partial turns (D10.3, docs/probes/opencode_partials.md) ----------------

PARTIAL = generated(reasoning="Let me think. ", text="Hello wor", complete=False)


def _partial_msg(content, **extra):
    return {"role": "assistant", "content": content, **extra}


@pytest.mark.parametrize("reasoning_field", [{"reasoning_content": ""}, {}])
def test_flattened_partial_matches_and_records_the_acknowledged_extent(reasoning_field):
    archive = _archive(SYS, U1, PARTIAL)
    msgs = client(SYS, U1, _partial_msg("Let me think. Hello wor", **reasoning_field), U2)

    assert reconcile(msgs, archive) == Extend(3, partials=((2, 23),))


def test_partial_cut_short_by_a_reset_matches_a_shorter_prefix():
    archive = _archive(SYS, U1, PARTIAL)
    msgs = client(SYS, U1, _partial_msg("Let me th"), U2)

    assert reconcile(msgs, archive) == Extend(3, partials=((2, 9),))


def test_continue_message_after_a_partial_is_ordinary_new_client_content():
    archive = _archive(SYS, U1, PARTIAL)
    cont = {"role": "user", "content": "The previous response was interrupted. Continue from "
            "where you left off without repeating completed content."}

    assert reconcile(client(SYS, U1, _partial_msg("Let me think. Hello wor"), cont), archive) == Extend(
        3, partials=((2, 23),)
    )


def test_flattened_text_that_is_not_a_prefix_of_what_was_sent_diverges():
    archive = _archive(SYS, U1, PARTIAL)

    result = reconcile(client(SYS, U1, _partial_msg("Let me think. Hello world!"), U2), archive)

    assert isinstance(result, Divergence) and result.index == 2


def test_partial_resent_with_nonempty_reasoning_diverges():
    archive = _archive(SYS, U1, PARTIAL)
    msg = _partial_msg("Hello wor", reasoning_content="Let me think. ")

    result = reconcile(client(SYS, U1, msg, U2), archive)

    assert isinstance(result, Divergence) and result.index == 2


def _tool_partial_msg(content, call_id="call_9", name="write"):
    return {"role": "assistant", "content": content, "reasoning_content": "", "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": "{}"}}]}


TOOL_PARTIAL = generated(reasoning="Plan.", tool_calls=[
    {"id": "call_9", "name": "write", "arguments": '{"pa'}], complete=False)
TOOL_ERROR = {"role": "tool", "tool_call_id": "call_9", "content": '{"error":"interrupted"}'}


@pytest.mark.parametrize("content", ["Plan.", None])
def test_partial_tool_call_matches_on_id_and_name_with_placeholder_arguments(content):
    archive = _archive(SYS, U1, TOOL_PARTIAL)
    msgs = client(SYS, U1, _tool_partial_msg(content), TOOL_ERROR, U2)

    assert reconcile(msgs, archive) == Extend(3, partials=((2, len(content or "")),))


@pytest.mark.parametrize("call", [{"call_id": "call_8"}, {"name": "read"}])
def test_partial_tool_call_with_another_id_or_name_diverges(call):
    archive = _archive(SYS, U1, TOOL_PARTIAL)

    result = reconcile(client(SYS, U1, _tool_partial_msg("Plan.", **call), TOOL_ERROR, U2), archive)

    assert isinstance(result, Divergence) and result.index == 2


def test_a_resend_that_omits_an_archived_partial_diverges():
    # Never observed from OpenCode (probe rule 5); treated strictly.
    archive = _archive(SYS, U1, PARTIAL)

    result = reconcile(client(SYS, U1, U2), archive)

    assert isinstance(result, Divergence) and result.index == 2


def test_resend_up_to_the_failed_user_message_is_a_retry_of_that_request():
    archive = _archive(SYS, U1, PARTIAL)

    assert reconcile(client(SYS, U1), archive) == Prefix(2)


def test_completed_turn_still_requires_exact_text():
    archive = _archive(SYS, U1, generated(text="Hello world", complete=True))

    result = reconcile(client(SYS, U1, _partial_msg("Hello wor"), U2), archive)

    assert isinstance(result, Divergence) and result.index == 2


# --- Client-cancelled partials (live R9) and undelivered complete turns (review #5) ---

CANCELLED = Archived.generated("occ-cancelled", text="", reasoning="Let me", tool_calls=(),
                               complete=False, cancelled=True)


def test_partial_the_client_cancelled_may_be_omitted_and_is_superseded():
    archive = _archive(SYS, U1, CANCELLED)

    result = reconcile(client(SYS, U1, U2), archive)

    assert isinstance(result, Extend) and result.matched == 2
    assert result.superseded == ("occ-cancelled",)
    assert result.aligned == tuple(a.occ_id for a in archive[:2])


def test_a_cancelled_partial_resent_flattened_still_matches_as_a_partial():
    archive = _archive(SYS, U1, CANCELLED)

    result = reconcile(client(SYS, U1, _partial_msg("Let me"), U2), archive)

    assert result == Extend(3, partials=((2, 6),))
    assert result.aligned == tuple(a.occ_id for a in archive)
    assert result.superseded == ()


def test_history_continues_after_a_superseded_partial():
    archive = _archive(SYS, U1, CANCELLED, U2, generated(text="answer"))
    msgs = client(SYS, U1, U2, {"role": "assistant", "content": "answer"}, U1)

    result = reconcile(msgs, archive)

    assert isinstance(result, Extend) and result.matched == 4
    assert result.aligned == (archive[0].occ_id, archive[1].occ_id, archive[3].occ_id, "occ-gen")


def test_a_server_failed_partial_still_may_not_be_omitted():
    archive = _archive(SYS, U1, PARTIAL)  # failed upstream, not cancelled by the client

    assert isinstance(reconcile(client(SYS, U1, U2), archive), Divergence)


def test_complete_turn_never_fully_delivered_accepts_the_flattened_continue():
    undelivered = Archived.generated("occ-u", text="answer", reasoning="think ", tool_calls=(),
                                     complete=True, delivered=False)
    archive = _archive(SYS, U1, undelivered)

    result = reconcile(client(SYS, U1, _partial_msg("think answer", reasoning_content=""), U2), archive)

    assert isinstance(result, Extend) and result.partials == ((2, 12),)


def test_complete_undelivered_turn_resent_whole_still_matches_exactly():
    undelivered = Archived.generated("occ-u", text="answer", reasoning="think ", tool_calls=(),
                                     complete=True, delivered=False)
    archive = _archive(SYS, U1, undelivered)
    whole = {"role": "assistant", "content": "answer", "reasoning_content": "think "}

    result = reconcile(client(SYS, U1, whole, U2), archive)

    assert isinstance(result, Extend) and result.partials == ()


def test_answer_from_a_retry_after_a_cancelled_partial_aligns_past_the_partial():
    archive = _archive(SYS, U1, CANCELLED, generated(text="full answer"))
    msgs = client(SYS, U1, {"role": "assistant", "content": "full answer"}, U2)

    result = reconcile(msgs, archive)

    assert isinstance(result, Extend) and result.matched == 3
    assert result.superseded == ("occ-cancelled",)
    assert result.aligned[-1] == "occ-gen"


def test_retry_answer_that_prefixes_the_cancelled_text_binds_to_the_answer_not_the_partial():
    # Review re-check: greedy alignment matched "OK" as a flattened partial of
    # the cancelled "OK, so the answer" and then diverged on the next turn.
    cancelled = Archived.generated("occ-p", text="OK, so the answer", reasoning="",
                                   tool_calls=(), complete=False, cancelled=True)
    answer = Archived.generated("occ-a", text="OK", reasoning="", tool_calls=(), complete=True)
    archive = _archive(U1, cancelled, answer)

    result = reconcile(client(U1, {"role": "assistant", "content": "OK"}, U2), archive)

    assert isinstance(result, Extend) and result.matched == 2
    assert result.aligned[1:] == ("occ-a",)
    assert result.superseded == ("occ-p",) and result.partials == ()
