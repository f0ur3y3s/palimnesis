"""Phase 4A S5: the pinned state's conflict and isolation rules (contracts §17, D105.8).

The state is the model's own fallible text: the newest committed version replaces older
ones, a retry after a failed answer reuses it, and state text is never a recall source. It is not indexed for search, not quoted in excerpts, not projected into
transcript files and not sent to the client."""

from __future__ import annotations

import json

from palimnesis.view.builder import notes_block

from .test_notes_http import BUDGET, _body, _messages, _notes_rows, _sent
from .test_state_golden import _answer, _turns
from .test_view_http import post, rows, view_stack

MARK = "QUETZAL-5512"  # in the state, and asked for later
ONLY = "PANGOLIN"  # a word only the state holds, never asked for
NOTES = (f"Objective\nShip it.\nRequirements and constraints\n- release code {MARK}\n"
         f"Dead ends\n- the {ONLY} parser failed")


def _session(tmp_path, calls, **extra):
    settings = dict(input_budget=BUDGET, notes_tokens=2048, notes_format="n2",
                    transcripts=tmp_path / "transcripts", **extra)
    with view_stack(tmp_path, **settings) as (fake, url, s):
        responses = []
        for k in range(calls):
            _answer(fake, f"answer {k}")
            _answer(fake, f"answer {k}")
            responses.append(post(url, _body(_messages(_turns(k)))))
            fake._script.clear()
    return fake, s, responses


def test_newest_committed_version_replaces_older(tmp_path):
    fake, s, _ = _session(tmp_path, 3)
    committed = [n for n, status, _, _ in _notes_rows(s) if status == "committed"]
    assert len(committed) >= 2
    last = json.loads(fake.requests[-1].body)["messages"]
    blocks = [m for m in last if "[palimnesis notes" in str(m.get("content"))[:20]]
    assert len(blocks) == 1 and f"v{committed[-1]}" in blocks[0]["content"]


def test_retry_after_a_failed_answer_reuses_the_state_without_a_second_refresh(tmp_path):
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048, notes_format="n2") as (
            fake, url, s):
        fake.respond_counted(NOTES)
        fake.respond_json(b'{"error": {"message": "busy"}}', status=503)
        first = post(url, _body(_messages()))
        fake.respond_counted("visible answer")
        retry = post(url, _body(_messages()))

    assert first.status_code != 200 and retry.status_code == 200
    assert len(fake.requests) == 3  # refresh, failed answer, retried answer: no 2nd refresh
    assert [r[1] for r in _notes_rows(s)] == ["committed"]
    assert {"role": "user", "content": notes_block(1, NOTES, "h1")} in _sent(fake, 2)


def test_state_text_is_never_indexed_nor_excerpted(tmp_path):
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048, notes_format="n2") as (
            fake, url, s):
        fake.respond_counted(NOTES)
        fake.respond_counted("answer 0")
        assert post(url, _body(_messages())).status_code == 200
        # The next instruction asks for exactly the state's words: no excerpt may quote them.
        fake.respond_counted("answer 1")
        ask = [{"role": "assistant", "content": "answer 0"},
               {"role": "user", "content": f"What is the release code? {MARK} QUETZAL. "
                                           "And what did w0_1_7 and w1_2_9 say?"}]
        assert post(url, _body(_messages(ask))).status_code == 200

    excerpts = rows(s, "SELECT rendered FROM excerpt_blocks WHERE status = 'selected'")
    assert excerpts, "recall ran and quoted the collapsed tool output it was asked about"
    assert all(MARK not in r and ONLY not in r for (r,) in excerpts)
    for index in ("fts_blocks", "fts_chunks"):
        assert rows(s, f"SELECT count(*) FROM {index} WHERE {index} MATCH '{ONLY}'") == [(0,)]


def test_state_is_absent_from_the_client_stream_and_transcripts(tmp_path):
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048, notes_format="n2",
                    transcripts=tmp_path / "transcripts") as (fake, url, s):
        fake.respond_counted(NOTES)
        fake.respond_counted("visible answer")
        r = post(url, _body(_messages()))

    assert r.status_code == 200 and MARK not in r.text
    files = [p for p in (tmp_path / "transcripts").rglob("*") if p.is_file()]
    assert files and all(MARK not in p.read_text(encoding="utf-8", errors="replace") for p in files)
