"""Transcript-search addendum a3 (A1 bounded search recipe; D36)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from palimnesis.projector import session_dir

from .test_view_http import DONE, SID, body, history, post, rows, upstream_tokens, view_stack

REPLAY = Path(__file__).resolve().parents[1] / "eval" / "replay.py"


def _system(raw: bytes) -> str:
    return json.loads(raw)["messages"][0]["content"]


def _turn(messages, user):
    return messages + [{"role": "assistant", "content": "ok"}, {"role": "user", "content": user}]


def test_the_addendum_names_the_session_directory_in_the_upstream_system_message_only(tmp_path):
    messages = _turn(history(30), "go on")
    with view_stack(tmp_path, input_budget=8000) as (fake, url, settings):
        fake.respond_sse([DONE])
        r = post(url, body(messages, max_completion_tokens=8192))

    system = _system(fake.requests[-1].body)
    where = str(session_dir(tmp_path / "transcripts", SID))
    assert system.startswith("You are a coding agent.\n\n")
    assert f"An exact transcript is in {where}" in system
    assert "grep" in system and "offset and limit" in system
    assert "transcript" not in r.text
    # the archive keeps the client's system message unchanged
    assert rows(settings, "SELECT count(*) FROM fts_blocks WHERE fts_blocks MATCH"
                          " '\"exact transcript\"'") == [(0,)]
    [(kind,)] = rows(settings, "SELECT kind FROM events WHERE kind = 'addendum_fixed'")


def test_the_addendum_is_counted_within_the_budget(tmp_path):
    with view_stack(tmp_path, input_budget=8000) as (fake, url, _):
        fake.respond_sse([DONE])
        post(url, body(_turn(history(30), "go on"), max_completion_tokens=8192))

    assert upstream_tokens(fake.requests[-1].body) <= 8000
    assert "An exact transcript is in" in _system(fake.requests[-1].body)


def test_the_addendum_is_fixed_for_the_session_even_if_the_root_changes(tmp_path):
    messages = _turn(history(30), "first")
    with view_stack(tmp_path, input_budget=8000) as (fake, url, _):
        fake.respond_sse([DONE])
        post(url, body(messages, max_completion_tokens=8192))
        first = _system(fake.requests[-1].body)
    messages = _turn(messages, "second")
    with view_stack(tmp_path, input_budget=8000, transcripts=tmp_path / "elsewhere") as (fake, url, _):
        fake.respond_sse([DONE])
        post(url, body(messages, max_completion_tokens=8192))
        second = _system(fake.requests[-1].body)

    assert second == first


def test_an_unmasked_session_gets_no_addendum_and_stays_byte_identical(tmp_path):
    data = body(_turn(history(2), "go on"), max_completion_tokens=8192)
    with view_stack(tmp_path) as (fake, url, settings):
        fake.respond_sse([DONE])
        post(url, data)

    assert fake.requests[-1].body == data
    assert rows(settings, "SELECT count(*) FROM events WHERE kind = 'addendum_fixed'") == [(0,)]


def test_without_transcripts_a_masked_session_gets_no_addendum(tmp_path):
    with view_stack(tmp_path, input_budget=8000, transcripts_enabled=False) as (fake, url, settings):
        fake.respond_sse([DONE])
        post(url, body(_turn(history(30), "go on"), max_completion_tokens=8192))

    assert "An exact transcript" not in _system(fake.requests[-1].body)
    assert rows(settings, "SELECT count(*) FROM events WHERE kind = 'addendum_fixed'") == [(0,)]


def test_cache_accounting_explains_every_call_with_the_addendum_across_a_restart(tmp_path):
    messages = _turn(history(30), "first")
    with view_stack(tmp_path, input_budget=8000) as (fake, url, _):
        for user in ("second", "third"):
            fake.respond_sse([DONE])
            post(url, body(messages, max_completion_tokens=8192))
            messages = _turn(messages, user)
    with view_stack(tmp_path, input_budget=8000) as (fake, url, settings):
        fake.respond_sse([DONE])
        post(url, body(messages, max_completion_tokens=8192))

    out = subprocess.run([sys.executable, str(REPLAY), "--explain", str(settings.db_path), "--json"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr


def test_dropping_the_addendum_is_explained_as_a_format_change(tmp_path):
    messages = _turn(history(30), "first")
    with view_stack(tmp_path, input_budget=8000) as (fake, url, _):
        fake.respond_sse([DONE])
        post(url, body(messages, max_completion_tokens=8192))
    with view_stack(tmp_path, input_budget=8000, transcripts_enabled=False) as (fake, url, settings):
        fake.respond_sse([DONE])
        post(url, body(_turn(messages, "second"), max_completion_tokens=8192))

    causes = [json.loads(p)["cause"] for (p,) in rows(
        settings, "SELECT payload FROM events WHERE kind = 'upstream_call' ORDER BY event_id")]
    assert causes[-1] == "view_format_change"
