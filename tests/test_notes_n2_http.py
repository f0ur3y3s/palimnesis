"""Working notes format n2 through the proxy (D74): ``serve --notes TOKENS --notes-format n2``.

The refresh call sends the n2 prompt; notes longer than the slot keep every section,
each cut to its first lines; a refresh whose reply has no text but whose reasoning holds
the notes commits them from the reasoning, recorded with reason ``from_reasoning``.
n1 keeps D72's behaviour."""

from __future__ import annotations

import json

from palimnesis.upstreams.strata import tokens
from palimnesis.view import ViewPolicy, notes_block, notes_prompt

from .archive_helpers import DONE, chunk
from .test_notes_http import BUDGET, _body, _messages, _notes_rows, _sent
from .test_view_http import post, rows, view_stack

SECTIONS = ["Objective", "Current step and next move", "Requirements and constraints",
            "Decisions", "Done so far", "Dead ends"]
N2 = dict(input_budget=BUDGET, notes_tokens=2048, notes_format="n2")


def _notes(lines_per_section):
    out = []
    for s in SECTIONS:
        out.append(s)
        out += [f"- {s.split()[0].lower()} fact {k}: " + " ".join(["word"] * 12) for k in range(lines_per_section)]
    return "\n".join(out)


def _reasoning_only(text):
    return [chunk({"role": "assistant", "content": ""}), chunk({"reasoning_content": text}),
            chunk({}, "stop"), DONE]


def test_an_n2_refresh_sends_the_n2_prompt(tmp_path):
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_counted(_notes(2))
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    expected = notes_prompt(ViewPolicy(notes_tokens=2048, notes_format="n2"))
    assert _sent(fake, 0)[-1] == {"role": "user", "content": expected}


def test_long_n2_notes_keep_every_section(tmp_path):
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_counted(_notes(60))
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    [(_, status, _, text)] = _notes_rows(s)
    assert status == "committed"
    assert [line for line in text.split("\n") if line in SECTIONS] == SECTIONS
    assert "- dead fact 0: " in text
    block = next(m["content"] for m in _sent(fake, 1) if "palimnesis notes" in str(m.get("content")))
    assert tokens.default().count_cached(block) <= 2048


def test_notes_written_only_as_reasoning_are_committed_from_it(tmp_path):
    notes = _notes(2)
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_sse(_reasoning_only("Let me write them.\n" + notes))
        fake.respond_counted("visible answer")
        r = post(url, _body(_messages()))

    assert r.status_code == 200 and notes not in r.text
    assert _notes_rows(s) == [(1, "committed", "from_reasoning", notes)]
    assert {"role": "user", "content": notes_block(1, notes)} in _sent(fake, 1)


def test_reasoning_that_is_not_notes_still_fails_empty(tmp_path):
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_sse(_reasoning_only("Objective\nBuild it.\n\nRequirements and constraints\n"))
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    [(_, status, reason, text)] = _notes_rows(s)
    assert (status, reason, text) == ("failed", "empty", "")


def test_n1_never_takes_notes_from_reasoning(tmp_path):
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048) as (fake, url, s):
        fake.respond_sse(_reasoning_only(_notes(2)))
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    [(_, status, reason, _)] = _notes_rows(s)
    assert (status, reason) == ("failed", "empty")


def test_the_policy_version_names_the_notes_format(tmp_path):
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_counted(_notes(2))
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    [(policy,)] = rows(s, "SELECT policy_version FROM view_versions ORDER BY n DESC LIMIT 1")
    assert policy.endswith("+notes2048n2")
    causes = [json.loads(p)["cause"] for (p,) in rows(
        s, "SELECT payload FROM events WHERE kind = 'upstream_call' ORDER BY event_id")]
    assert "unexplained" not in causes



# --- review of the D74 draft ------------------------------------------------------------

def test_reasoning_notes_never_rescue_an_incomplete_stream(tmp_path):
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_sse(_reasoning_only(_notes(2))[:-1])  # no [DONE]
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    [(_, status, reason, text)] = _notes_rows(s)
    assert (status, reason, text) == ("failed", "incomplete", "")


def test_reasoning_notes_never_rescue_a_tool_call(tmp_path):
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_sse([chunk({"role": "assistant", "content": ""}),
                          chunk({"reasoning_content": _notes(2)}),
                          chunk({"tool_calls": [{"index": 0, "id": "call_x", "type": "function",
                                                 "function": {"name": "read", "arguments": "{}"}}]}),
                          chunk({}, "tool_calls"), DONE])
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    [(_, status, reason, _)] = _notes_rows(s)
    assert (status, reason) == ("failed", "tool_call")


def test_a_malformed_refresh_stream_is_failed_and_recorded(tmp_path):
    """Review F4 (D72): a stream the parser rejects is a recorded failure, not 'cancelled'."""
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_sse([chunk({"content": "Objective"}), b"data: {not json\n\n", DONE])
        fake.respond_counted("visible answer")
        r = post(url, _body(_messages()))

    assert r.status_code == 200 and "visible answer" in r.text
    [(_, status, reason, _)] = _notes_rows(s)
    assert (status, reason) == ("failed", "malformed")
    [first, *_] = [json.loads(p) for (p,) in rows(
        s, "SELECT payload FROM events WHERE kind = 'upstream_call' ORDER BY event_id")]
    assert first["outcome"] == "malformed"


def test_a_slot_smaller_than_its_header_fails_too_long_without_hanging(tmp_path):
    """Review F2 (D72): fitting never loops when the header alone exceeds the slot."""
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=24) as (fake, url, s):
        fake.respond_counted("Objective\nsomething")
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    [(_, status, reason, _)] = _notes_rows(s)
    assert (status, reason) == ("failed", "too_long")
