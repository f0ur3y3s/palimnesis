"""Regressions for the Phase 3 acceptance reviews of the shipped configuration (D78, R42):
working notes on the protocol, cache-accounting and recording paths."""

from __future__ import annotations

import json

from .test_notes_http import BUDGET, NOTES, _body
from .test_view_http import post, rows, view_stack


def _calls(s):
    return [json.loads(p) for (p,) in rows(
        s, "SELECT payload FROM events WHERE kind = 'upstream_call' ORDER BY event_id")]


def _work(t, groups=6, words=150):
    out = [{"role": "user", "content": f"Instruction {t}: implement part {t}."}]
    for i in range(groups):
        call_id = f"call_{t}_{i}"
        out.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": "read", "arguments": "{}"}}]})
        out.append({"role": "tool", "tool_call_id": call_id, "content": "ok"})
        out.append({"role": "assistant", "content": " ".join(f"w{t}_{i}_{k}" for k in range(words))})
    return out


# Cache audit 1: a refresh call is `state_refresh` only when it extends the call before it.
# A session's first masking move fixes the transcript addendum (D36), so the refresh of a
# first move that is also a collapse is the first call carrying it: a head change.
def test_a_refresh_that_changes_the_head_is_not_recorded_as_extending(tmp_path):
    from .test_view_http import _code

    first = [{"role": "system", "content": "You are a coding agent."}, *_work(0), *_work(1),
             {"role": "user", "content": "Read the big module next."}]
    call = {"role": "assistant", "content": None, "tool_calls": [
        {"id": "big", "type": "function", "function": {"name": "read", "arguments": "{}"}}]}
    second = [*first, call, {"role": "tool", "tool_call_id": "big", "content": _code(9, 400)}]
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048) as (fake, url, s):
        fake.respond_counted(tool_call=("big", "read", "{}"))
        assert post(url, _body(first)).status_code == 200
        assert len(fake.requests) == 1  # under H: no move, no refresh
        fake.respond_counted(NOTES)
        fake.respond_counted("done")
        r = post(url, _body(second))
        assert r.status_code == 200, r.text[:300]

    calls = _calls(s)
    assert [c["call_id"].endswith("#notes") for c in calls] == [False, True, False]
    refresh = calls[1]
    assert b"[palimnesis" in fake.requests[1].body  # the first masked view carries the addendum
    assert refresh["lcp_tokens"] < 1000  # the change starts in the head
    assert refresh["cause"] != "state_refresh"
    assert "view_format_change" in refresh["cause"]
    assert not [c for c in calls if "unexplained" in c["cause"]]


# Protocol review 3: a refresh that meets a 5xx, a transport error or a context-window 400
# marks the upstream facts stale as the client's own call would (contracts §1), so the
# next request re-reads them.
def test_a_refresh_upstream_failure_makes_the_next_request_reread_the_facts(tmp_path):
    from .test_notes_http import _messages

    more = [{"role": "assistant", "content": "visible answer"},
            {"role": "user", "content": "go on"}]
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048) as (fake, url, s):
        fake.respond_json(b'{"error":{"message":"restarting"}}', status=503)
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200
        reads = fake.props_requests
        fake.respond_counted("second")
        assert post(url, _body(_messages(more))).status_code == 200
        assert fake.props_requests > reads


def test_without_a_failure_the_next_request_does_not_reread_the_facts(tmp_path):
    from .test_notes_http import _messages

    more = [{"role": "assistant", "content": "visible answer"},
            {"role": "user", "content": "go on"}]
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048) as (fake, url, s):
        fake.respond_counted(NOTES)
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200
        reads = fake.props_requests
        fake.respond_counted("second")
        assert post(url, _body(_messages(more))).status_code == 200
        assert fake.props_requests == reads


# Protocol review 5 / cache audit 2: a collapse whose refresh cannot fit B_in, even with
# every unmasked result stubbed, sends no call, and that failure is recorded too (§2).
def test_a_refresh_that_cannot_fit_is_recorded_without_a_call(tmp_path):
    from .test_view_http import DONE, body, history

    messages = history(30) + [{"role": "assistant", "content": "ok"},
                              {"role": "user", "content": "first"}]
    with view_stack(tmp_path, input_budget=8000, transcripts_enabled=False,
                    notes_tokens=2048) as (fake, url, s):
        fake.respond_sse([DONE])
        assert post(url, body(messages, max_completion_tokens=8192)).status_code == 200

    assert len(fake.requests) == 1  # no refresh call
    collapsed = rows(s, "SELECT collapse_seq FROM view_versions ORDER BY n DESC LIMIT 1")[0][0]
    assert collapsed  # the move collapsed
    assert rows(s, "SELECT n, status, reason, text FROM notes_versions") == [
        (1, "failed", "over_budget", "")]


# Protocol review 4: a rebuild with the new notes that raises sends the view the move
# built, so the notes the plan holds stay that view's (none here), never the new version.
def test_a_failed_rebuild_with_new_notes_keeps_the_plan_on_the_sent_view(tmp_path, monkeypatch):
    from palimnesis.view.builder import notes_block
    from palimnesis.view.engine import ViewEngine

    from .test_notes_http import _messages

    real = ViewEngine.build
    seen = {}

    async def build(self, prepared, plan):
        if plan.view_state.notes:  # the rebuild naming the committed notes
            raise RuntimeError("rebuild failed")
        return await real(self, prepared, plan)

    real_body = ViewEngine.body

    def body(req, plan, prepared, view):
        seen["notes"] = dict(plan.notes)
        return real_body(req, plan, prepared, view)

    monkeypatch.setattr(ViewEngine, "build", build)
    monkeypatch.setattr(ViewEngine, "body", staticmethod(body))
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048) as (fake, url, s):
        fake.respond_counted(NOTES)
        fake.respond_counted("visible answer")
        r = post(url, _body(_messages()))

    assert r.status_code == 200 and "visible answer" in r.text
    assert notes_block(1, NOTES).encode() not in fake.requests[1].body
    assert seen["notes"] == {}


# Protocol review 7: the startup floor counts the notes slot, as admission now does.
def test_the_startup_floor_counts_the_notes_slot():
    import pytest

    from palimnesis.view.budget import BudgetError, BudgetPolicy, check_floor

    check_floor(13_000, fixed_min=5, client_limit=None, policy=BudgetPolicy())
    with pytest.raises(BudgetError) as e:
        check_floor(13_000, fixed_min=5, client_limit=None, policy=BudgetPolicy(), notes=2048)
    assert e.value.terms["notes"] == 2048


def test_with_notes_bounded_views_are_refused_below_the_raised_floor(tmp_path, caplog):
    import logging

    from palimnesis.api import create_app
    from palimnesis.config import Settings

    from .fake_upstream import FakeUpstream
    from .test_view_http import DONE, body, history
    from .test_view_http import serve as serve_app

    fake = FakeUpstream()
    fake.props_n_ctx = 13_000
    caplog.set_level(logging.WARNING, logger="palimnesis")
    with serve_app(fake.app()) as upstream_url:
        s = Settings(upstream_base_url=upstream_url, db_path=tmp_path / "a.db", notes_tokens=2048)
        with serve_app(create_app(s), palimnesis=True) as url:
            data = body(history(30), max_completion_tokens=4096)
            fake.respond_sse([DONE])
            assert post(url, data).status_code == 200

    assert fake.requests[-1].body == data  # forwarded unbounded, still archived
    text = " ".join(r.getMessage() for r in caplog.records if "floor" in r.getMessage())
    assert "notes=2048" in text
