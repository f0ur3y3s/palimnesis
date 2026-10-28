"""Working notes through the proxy (D72): ``serve --notes TOKENS``.

When a request's view move advances the collapse boundary, the proxy first sends one
internal refresh call upstream: the request as it rendered before the move plus
``NOTES_PROMPT``. Its text becomes the next notes version, stored immutably and rendered
right after the last span note of the view the client's request then gets. The client
sees only its own response. A failed refresh keeps the notes it had."""

from __future__ import annotations

import json

from palimnesis.view import NOTES_PROMPT, notes_block

from .test_view_http import TOOLS, post, rows, upstream_tokens, view_stack

NOTES = "Objective\nFinish part 2.\nRequirements and constraints\nend == start is an error."
BUDGET = 24_320


def _messages(extra=()):
    messages = [{"role": "system", "content": "You are a coding agent."}]
    for t in range(3):
        messages.append({"role": "user", "content": f"Instruction {t}: implement part {t}."})
        for i in range(6):
            call_id = f"call_{t}_{i}"
            messages.append({"role": "assistant", "content": None, "tool_calls": [
                {"id": call_id, "type": "function", "function": {"name": "read", "arguments": "{}"}}]})
            messages.append({"role": "tool", "tool_call_id": call_id, "content": "ok"})
            messages.append({"role": "assistant",
                             "content": " ".join(f"w{t}_{i}_{k}" for k in range(150))})
    messages.append({"role": "user", "content": "Now finish the last part."})
    return [*messages, *extra]


def _body(messages):
    return json.dumps({"model": "m", "messages": messages, "tools": TOOLS, "stream": True,
                       "max_completion_tokens": 8192}).encode()


def _sent(fake, k):
    return json.loads(fake.requests[k].body)["messages"]


def _spans(messages):
    return [i for i, m in enumerate(messages)
            if m["role"] == "user" and str(m.get("content")).startswith("[palimnesis s1 span")]


def _notes_rows(s):
    return rows(s, "SELECT n, status, reason, text FROM notes_versions ORDER BY n")


def test_a_collapse_move_refreshes_the_notes_before_the_clients_call(tmp_path):
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048) as (fake, url, s):
        fake.respond_counted(NOTES)
        fake.respond_counted("visible answer")
        r = post(url, _body(_messages()))

    assert r.status_code == 200 and "visible answer" in r.text and NOTES not in r.text
    assert len(fake.requests) == 2
    refresh, visible = _sent(fake, 0), _sent(fake, 1)
    assert refresh[-1] == {"role": "user", "content": NOTES_PROMPT}
    assert refresh[-2] == {"role": "user", "content": "Now finish the last part."}
    assert not _spans(refresh)  # the request as it was before the move
    assert upstream_tokens(fake.requests[0].body) <= BUDGET
    [k] = _spans(visible)[-1:]
    assert visible[k + 1] == {"role": "user", "content": notes_block(1, NOTES)}
    assert upstream_tokens(fake.requests[1].body) <= BUDGET
    assert _notes_rows(s) == [(1, "committed", None, NOTES)]


def test_the_notes_stay_until_the_next_collapse(tmp_path):
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048) as (fake, url, s):
        fake.respond_counted(NOTES)
        fake.respond_counted("first")
        assert post(url, _body(_messages())).status_code == 200
        fake.respond_counted("second")
        more = [{"role": "assistant", "content": "first"}, {"role": "user", "content": "go on"}]
        assert post(url, _body(_messages(more))).status_code == 200

    assert len(fake.requests) == 3
    assert {"role": "user", "content": notes_block(1, NOTES)} in _sent(fake, 2)
    assert len(_notes_rows(s)) == 1


def test_a_failed_refresh_keeps_the_notes_it_had_and_still_answers(tmp_path):
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048) as (fake, url, s):
        fake.respond_json(b'{"error": {"message": "busy"}}', status=503)
        fake.respond_counted("visible answer")
        r = post(url, _body(_messages()))

    assert r.status_code == 200 and "visible answer" in r.text
    assert len(fake.requests) == 2
    assert not any("palimnesis notes" in str(m.get("content")) for m in _sent(fake, 1))
    [(n, status, reason, text)] = _notes_rows(s)
    assert (status, text) == ("failed", "") and reason == "upstream_status"


def test_a_refresh_that_calls_a_tool_is_failed(tmp_path):
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048) as (fake, url, s):
        fake.respond_counted(tool_call=("call_x", "read", "{}"))
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    [(_, status, reason, _)] = _notes_rows(s)
    assert (status, reason) == ("failed", "tool_call")


def test_notes_longer_than_the_slot_are_cut_at_a_line_to_fit(tmp_path):
    long_notes = "\n".join(f"line {k}: " + "word " * 40 for k in range(200))
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=1024) as (fake, url, s):
        fake.respond_counted(long_notes)
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    [(_, status, _, text)] = _notes_rows(s)
    assert status == "committed" and long_notes.startswith(text) and text.endswith("word ")
    block = next(m["content"] for m in _sent(fake, 1) if "palimnesis notes" in str(m.get("content")))
    from palimnesis.upstreams.strata import tokens

    assert tokens.default().count_cached(block) <= 1024


def test_without_notes_there_is_one_upstream_call(tmp_path):
    with view_stack(tmp_path, input_budget=BUDGET) as (fake, url, s):
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    assert len(fake.requests) == 1


def test_the_refresh_and_the_next_call_are_explained(tmp_path):
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048) as (fake, url, s):
        fake.respond_counted(NOTES)
        fake.respond_counted("first")
        assert post(url, _body(_messages())).status_code == 200
        fake.respond_counted("second")
        more = [{"role": "assistant", "content": "first"}, {"role": "user", "content": "go on"}]
        assert post(url, _body(_messages(more))).status_code == 200

    causes = [json.loads(p)["cause"] for (p,) in rows(
        s, "SELECT payload FROM events WHERE kind = 'upstream_call' ORDER BY event_id")]
    assert causes[0] in ("first_call", "state_refresh")
    assert causes[1].split(",")[0] == "collapse"
    assert causes[2] == "append"
    assert "unexplained" not in causes
    ids = [json.loads(p)["call_id"] for (p,) in rows(
        s, "SELECT payload FROM events WHERE kind = 'upstream_call' ORDER BY event_id")]
    assert ids[0].endswith("#notes") and "#" not in ids[1]


def test_the_view_version_records_the_notes_and_the_policy(tmp_path):
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048) as (fake, url, s):
        fake.respond_counted(NOTES)
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    policy, masks = rows(s, "SELECT policy_version, oversized FROM view_versions"
                            " ORDER BY n DESC LIMIT 1")[0]
    assert policy.endswith("+notes2048")
    [(notes_id,)] = rows(s, "SELECT notes_id FROM notes_versions")
    assert json.loads(masks)["notes"] == notes_id
