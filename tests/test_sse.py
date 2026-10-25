"""Incremental SSE parsing and OpenAI chat-stream assembly (pure seam).

The relay forwards each event's original bytes, so parsing must account for
every input byte at any chunking. Expected assembled values are literals read
from the recorded Strata streams.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from palimnesis.sse import ChatStream, SSEParser

FIXTURES = Path(__file__).resolve().parents[1] / "eval" / "probes" / "fixtures"
OPENAI_STREAMS = sorted(FIXTURES.glob("sse_oa_*.sse"))


def _parse(data: bytes, size: int):
    parser = SSEParser()
    events = []
    for i in range(0, len(data), size):
        events += parser.feed(data[i : i + size])
    return events, parser.close()


@pytest.mark.parametrize("size", [1, 3, 7, 64, 1 << 20])
@pytest.mark.parametrize("fixture", OPENAI_STREAMS, ids=lambda p: p.stem)
def test_events_account_for_every_byte_at_any_chunking(fixture, size):
    data = fixture.read_bytes()

    events, leftover = _parse(data, size)

    assert b"".join(e.raw for e in events) + leftover == data
    assert leftover == b""


def test_lf_crlf_and_cr_line_endings_all_delimit_events():
    data = b"data: a\r\n\r\ndata: b\r\rdata: c\n\n"

    events, leftover = _parse(data, 1)

    assert [e.data for e in events] == ["a", "b", "c"]
    assert [e.raw for e in events] == [b"data: a\r\n\r\n", b"data: b\r\r", b"data: c\n\n"]
    assert leftover == b""


def test_cr_at_a_chunk_boundary_waits_for_a_possible_lf():
    parser = SSEParser()

    assert parser.feed(b"data: a\r") == []
    [event] = parser.feed(b"\n\r\n")

    assert event.raw == b"data: a\r\n\r\n"


def test_multiline_data_is_joined_with_newlines_and_space_after_colon_is_optional():
    [event], _ = _parse(b"data:x\ndata: y\nevent: delta\nid: 7\n\n", 4)

    assert (event.data, event.event, event.comment) == ("x\ny", "delta", False)


def test_comment_only_block_is_an_event_without_data():
    [event], _ = _parse(b": keep-alive\n\n", 2)

    assert (event.comment, event.data, event.raw) == (True, None, b": keep-alive\n\n")


def test_unterminated_trailing_event_is_returned_by_close_not_dispatched():
    events, leftover = _parse(b"data: whole\n\ndata: half", 5)

    assert [e.data for e in events] == ["whole"]
    assert leftover == b"data: half"


def _assemble(fixture: str) -> ChatStream:
    stream = ChatStream()
    events, _ = _parse((FIXTURES / fixture).read_bytes(), 9)
    for event in events:
        stream.apply(event)
    return stream


def test_tool_call_deltas_assemble_into_complete_calls():
    s = _assemble("sse_oa_tool.sse")

    assert s.tool_calls == [
        {"id": "call_29b8193924b440caa2580967", "name": "get_weather", "arguments": '{"city":"Paris"}'}
    ]
    assert (s.finish_reason, s.done, s.usage["completion_tokens"]) == ("tool_calls", True, 26)


def test_parallel_tool_calls_keep_their_indices():
    s = _assemble("sse_oa_tool_parallel.sse")

    assert [(c["id"], c["arguments"]) for c in s.tool_calls] == [
        ("call_a0a5506f08504237bf0b596d", '{"city":"Paris"}'),
        ("call_622871e974a14a048eb68b82", '{"city":"Oslo"}'),
    ]


def test_reasoning_and_content_accumulate_separately():
    s = _assemble("sse_oa_reasoning.sse")

    assert s.content == "391"
    assert s.reasoning.startswith("The user wants me to calculate 17 ")
    assert len(s.reasoning) == 116
    assert (s.finish_reason, s.done) == ("stop", True)


def test_length_stop_is_reported():
    s = _assemble("sse_oa_length.sse")

    assert (s.content, s.finish_reason, s.usage["completion_tokens"]) == ("", "length", 8)


def test_truncated_stream_is_not_done_and_has_no_finish():
    s = _assemble("sse_oa_long_prefill_progress_TRUNCATED_server_died.sse")

    assert (s.done, s.finish_reason) == (False, None)


def test_error_payload_is_recorded_as_a_stream_error():
    stream = ChatStream()
    [event], _ = _parse(b'data: {"error":{"message":"boom","type":"server_error"}}\n\n', 64)

    stream.apply(event)

    assert stream.error == {"message": "boom", "type": "server_error"}
    assert stream.done is False


def test_malformed_json_data_is_a_protocol_error_not_silently_skipped():
    stream = ChatStream()
    [event], _ = _parse(b"data: {not json\n\n", 64)

    with pytest.raises(ValueError):
        stream.apply(event)
