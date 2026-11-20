"""Phase 4A S2: every notes refresh's whole output and its provenance are archived (D105.4).

``notes_outputs`` keeps one immutable row per refresh that produced a stream, failed ones
included: the reply before the cut, the reasoning, which reply lines the cut left out,
the refresh call id, the archive cutoff, and the prompt format and header the version was
written under. It commits in the same write as its ``notes_versions`` row. Logs and events
carry counts only, never state text (privacy rule)."""

from __future__ import annotations

import json
import logging

import pytest

from .archive_helpers import DONE, chunk
from .test_notes_http import BUDGET, _body, _messages, _notes_rows
from .test_notes_n2_http import _notes
from .test_view_http import post, rows, view_stack

N2 = dict(input_budget=BUDGET, notes_tokens=2048, notes_format="n2", notes_header="h2")


def _outputs(s):
    """Rows with content and reasoning decoded: they are stored as WTF-8 bytes (D106)."""
    out = rows(s, "SELECT o.notes_id, v.n, v.status, o.call_id, o.archive_seq, o.prompt_format,"
                  " o.header, o.content, o.reasoning, o.source, o.dropped"
                  " FROM notes_outputs o JOIN notes_versions v USING (notes_id) ORDER BY v.n")
    return [(*r[:7], r[7].decode("utf-8", "surrogatepass"), r[8].decode("utf-8", "surrogatepass"),
             *r[9:]) for r in out]


def _with_reasoning(reasoning, content):
    return [chunk({"role": "assistant", "content": ""}), chunk({"reasoning_content": reasoning}),
            chunk({"content": content}), chunk({}, "stop"), DONE]


def test_refresh_reply_archived_whole_when_cut(tmp_path):
    reply = _notes(60)
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_counted(reply)
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    [(n, vstatus, _, cut)] = _notes_rows(s)
    [row] = _outputs(s)
    assert vstatus == "committed" and row[7] == reply  # the whole reply, before the cut
    dropped = json.loads(row[10])
    lines = reply.split("\n")
    assert dropped and [lines[i] for i in dropped] == [
        l for l in lines if l.strip() and l not in cut.split("\n")]
    assert cut != reply


def test_refresh_reasoning_archived_with_its_version(tmp_path):
    notes = _notes(2)
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_sse(_with_reasoning("Let me think about the task.", notes))
        fake.respond_counted("visible answer")
        r = post(url, _body(_messages()))

    assert r.status_code == 200 and "Let me think" not in r.text
    [row] = _outputs(s)
    assert (row[2], row[7], row[8], row[9], json.loads(row[10])) == (
        "committed", notes, "Let me think about the task.", "reply", [])


def test_notes_from_reasoning_record_their_source(tmp_path):
    notes = _notes(2)
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_sse([chunk({"role": "assistant", "content": ""}),
                          chunk({"reasoning_content": "Drafting.\n" + notes}), chunk({}, "stop"), DONE])
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    [row] = _outputs(s)
    assert (row[2], row[7], row[9]) == ("committed", "", "from_reasoning")
    assert row[8] == "Drafting.\n" + notes


@pytest.mark.parametrize("script, reason", [
    (lambda f: f.respond_counted(tool_call=("call_x", "read", "{}")), "tool_call"),
    (lambda f: f.respond_sse([chunk({"role": "assistant", "content": ""}),
                              chunk({"reasoning_content": "nothing useful"}), chunk({}, "stop"), DONE]),
     "empty"),
])
def test_failed_refresh_output_archived_with_its_reason(tmp_path, script, reason):
    with view_stack(tmp_path, **N2) as (fake, url, s):
        script(fake)
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    [(_, status, vreason, text)] = _notes_rows(s)
    assert (status, vreason, text) == ("failed", reason, "")
    [row] = _outputs(s)
    assert row[2] == "failed"


def test_a_refresh_without_a_stream_archives_no_output(tmp_path):
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_json(b'{"error": {"message": "busy"}}', status=503)
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    assert [r[1] for r in _notes_rows(s)] == ["failed"]
    assert _outputs(s) == []


def test_state_version_records_cutoff_call_id_and_formats(tmp_path):
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_counted(_notes(2))
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    [row] = _outputs(s)
    [(attempt,)] = rows(s, "SELECT attempt_id FROM attempts")
    [(max_seq,)] = rows(s, "SELECT max(seq) FROM occurrences")
    assert row[3] == f"{attempt}#notes"
    assert (row[5], row[6]) == ("n2", "h2")
    # The refresh rendered the whole request: the cutoff is its newest archived message.
    assert 0 < row[4] <= max_seq


def test_refresh_logs_and_events_carry_no_state_text(tmp_path, caplog):
    secret = "Objective\nShip the PELICAN-77 release.\nDead ends\n- tried QUOKKA mode"
    caplog.set_level(logging.DEBUG, logger="palimnesis")
    with view_stack(tmp_path, **N2) as (fake, url, s):
        fake.respond_sse(_with_reasoning("thinking about WOMBAT", secret))
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    payloads = " ".join(p for (p,) in rows(s, "SELECT payload FROM events"))
    for word in ("PELICAN", "QUOKKA", "WOMBAT"):
        assert word not in caplog.text and word not in payloads
    [(payload,)] = rows(s, "SELECT payload FROM events WHERE kind = 'notes_version'")
    event = json.loads(payload)
    assert event["call_id"].endswith("#notes") and event["archive_seq"] > 0
    assert event["cut_lines"] == 0

