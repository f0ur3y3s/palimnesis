"""Hidden recall tool schemas in the upstream request (Phase 3B S3; plan §2.3, D54).

The schemas are fixed per session at the first view that hides anything, like the
addendum (D36), counted as fixed input before acceptance, appended after the client's
tools in the upstream copy only, and never sent with ``tool_choice: "none"``."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from palimnesis import recalltools

from .test_view_http import DONE, TOOLS, body, history, post, rows, upstream_tokens, view_stack

REPLAY = Path(__file__).resolve().parents[1] / "eval" / "replay.py"
NAMES = ["palimnesis_recall", "palimnesis_catalog", "palimnesis_grep"]


def _turn(messages, user):
    return messages + [{"role": "assistant", "content": "ok"}, {"role": "user", "content": user}]


def _tool_names(raw: bytes) -> list[str]:
    return [t["function"]["name"] for t in json.loads(raw).get("tools") or []]


def test_schemas_are_function_tools_with_the_reserved_names():
    for version in recalltools.TOOLS_VERSIONS:
        schemas = recalltools.schemas(version)
        assert [s["function"]["name"] for s in schemas] == NAMES
        assert all(s["type"] == "function" and s["function"]["description"]
                   and s["function"]["parameters"]["type"] == "object" for s in schemas)


def test_an_unmasked_session_gets_no_hidden_tools_and_stays_byte_identical(tmp_path):
    data = body(_turn(history(2), "go on"), max_completion_tokens=8192)
    with view_stack(tmp_path, hidden_tools="t2") as (fake, url, settings):
        fake.respond_sse([DONE])
        post(url, data)

    assert fake.requests[-1].body == data
    assert rows(settings, "SELECT count(*) FROM events WHERE kind = 'hidden_tools_fixed'") == [(0,)]


def test_the_first_masked_view_fixes_the_tools_after_the_clients_and_counts_them(tmp_path):
    messages = _turn(history(30), "go on")
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, settings):
        fake.respond_sse([DONE])
        r = post(url, body(messages, max_completion_tokens=8192))
        messages = _turn(messages, "next")
        fake.respond_sse([DONE])
        post(url, body(messages, max_completion_tokens=8192))

    first, second = fake.requests[-2].body, fake.requests[-1].body
    client = [t["function"]["name"] for t in TOOLS]
    assert _tool_names(first) == client + NAMES == _tool_names(second)
    assert json.loads(first)["tools"] == json.loads(second)["tools"]  # byte-stable schemas
    assert upstream_tokens(first) <= 8000 and upstream_tokens(second) <= 8000
    assert "palimnesis_" not in r.text
    assert rows(settings, "SELECT count(*) FROM events WHERE kind = 'hidden_tools_fixed'") == [(1,)]


def test_tool_choice_none_gets_no_hidden_tools(tmp_path):
    messages = _turn(history(30), "go on")
    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, _):
        fake.respond_sse([DONE])
        post(url, body(messages, max_completion_tokens=8192))
        fake.respond_sse([DONE])
        post(url, body(_turn(messages, "stop now"), max_completion_tokens=8192,
                       tool_choice="none"))

    assert "palimnesis_recall" in _tool_names(fake.requests[-2].body)
    assert "palimnesis_recall" not in _tool_names(fake.requests[-1].body)


def test_without_the_setting_no_tools_are_injected(tmp_path):
    with view_stack(tmp_path, input_budget=8000) as (fake, url, _):
        fake.respond_sse([DONE])
        post(url, body(_turn(history(30), "go on"), max_completion_tokens=8192))

    assert _tool_names(fake.requests[-1].body) == [t["function"]["name"] for t in TOOLS]


def test_injection_is_an_explained_tool_change_across_a_restart(tmp_path):
    first = history(2) + [{"role": "user", "content": "start"}]
    spec = "\n".join(f"spec line {i}: keep value {i * 7} for key k{i}" for i in range(260))
    second = _turn(first, spec)  # a long new instruction pushes the history over the mark
    third = _turn(second, "next")
    for messages in (first, second, third):  # a new process for every call
        with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, settings):
            fake.respond_counted()
            assert post(url, body(messages, max_completion_tokens=8192)).status_code == 200

    calls = [json.loads(p) for (p,) in rows(
        settings, "SELECT payload FROM events WHERE kind = 'upstream_call' ORDER BY event_id")]
    assert [c["view_n"] for c in calls][0] == 0 and calls[1]["view_n"] >= 1
    assert "tool_change" in calls[1]["cause"].split(",")
    assert calls[2]["lcp_source"] == "rerender" and "unexplained" not in calls[2]["cause"]
    report = subprocess.run([sys.executable, str(REPLAY), "--explain", str(settings.db_path)],
                            capture_output=True, text=True)
    assert report.returncode == 0, report.stdout
