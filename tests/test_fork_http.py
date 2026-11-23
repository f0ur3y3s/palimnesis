"""Phase 8 S6: an explicit fork into a new session (plan §1.5, U6, D129).

``POST /palimnesis/sessions/<source>/fork`` with ``{"at_turn": N}`` (and optionally the
new ``session``) copies the source's archived history up to the end of turn N, with
provenance, into a new session; ``palimnesis session fork SOURCE --at N`` calls it. A
client then continues the fork from its base URL. The parent is unaffected, nothing is
sent upstream, and divergence inside one session is still 409."""

from __future__ import annotations

import json
import sqlite3

import httpx
import pytest

from palimnesis.archive.ledger import branch_id_for, load_archived
from palimnesis.cli import main

from .archive_helpers import answer, assistant, body, lifecycle_stack, user

SRC = "ses_src"
SYSTEM = {"role": "system", "content": "You are terse."}


@pytest.fixture
def lc(tmp_path):
    with lifecycle_stack(tmp_path) as s:
        yield s


def three_turns(lc) -> list[dict]:
    msgs = [SYSTEM, user("U1")]
    for i in (1, 2, 3):
        lc.upstream.respond_sse(answer(f"A{i}"))
        assert lc.post(SRC, body(msgs)).status_code == 200
        msgs = msgs + [assistant(f"A{i}")] + ([user(f"U{i + 1}")] if i < 3 else [])
    return msgs  # S, U1, A1, U2, A2, U3, A3


def fork(lc, source=SRC, **doc) -> httpx.Response:
    return httpx.post(f"{lc.proxy_url}/palimnesis/sessions/{source}/fork", json=doc, timeout=30)


def rows(lc, sql, *args):
    c = sqlite3.connect(f"file:{lc.db_path}?mode=ro", uri=True)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def shape(lc, session):
    c = sqlite3.connect(f"file:{lc.db_path}?mode=ro", uri=True)
    try:
        return [(a.role, a.content_sha256) for a in load_archived(c, branch_id_for(session))]
    finally:
        c.close()


def test_a_fork_copies_the_history_through_turn_n_with_provenance(lc):
    three_turns(lc)
    before = rows(lc, "SELECT count(*) FROM occurrences")
    n_up = len(lc.upstream.requests)

    r = fork(lc, at_turn=2, session="ses_fork")

    assert r.status_code == 200, r.text
    assert r.json() == {"session": "ses_fork", "source": SRC, "at_turn": 2, "copied": 5}
    src = shape(lc, SRC)
    assert shape(lc, "ses_fork") == src[:5]  # S, U1, A1, U2, A2
    assert len(lc.upstream.requests) == n_up  # nothing sent upstream
    prov = rows(lc, "SELECT f.source_occ_id, o.branch_id FROM fork_occurrences f"
                    " JOIN occurrences o ON o.occ_id = f.source_occ_id")
    assert len(prov) == 5 and {b for _, b in prov} == {branch_id_for(SRC)}
    assert rows(lc, "SELECT session_id, source_session_id, at_turn FROM forks") == [
        ("ses_fork", SRC, 2)]
    assert rows(lc, "SELECT count(*) FROM occurrences")[0][0] == before[0][0] + 5


def test_the_fork_continues_as_a_prefix_and_the_parent_is_unaffected(lc):
    msgs = three_turns(lc)
    src_before = rows(lc, "SELECT occ_id, seq FROM occurrences WHERE branch_id = ? ORDER BY seq",
                      branch_id_for(SRC))
    assert fork(lc, at_turn=2, session="ses_fork").status_code == 200

    lc.upstream.respond_sse(answer("B3"))
    branch = msgs[:5] + [user("U3 instead")]
    r = lc.post("ses_fork", body(branch))

    assert r.status_code == 200, r.content[:300]
    sent = json.loads(lc.upstream.requests[-1].body)["messages"]
    assert [m["content"] for m in sent] == [m["content"] for m in branch]
    assert rows(lc, "SELECT count(*) FROM occurrences WHERE branch_id = ? AND source ="
                    " 'client_import'", branch_id_for("ses_fork")) == [(0,)]
    assert rows(lc, "SELECT occ_id, seq FROM occurrences WHERE branch_id = ? ORDER BY seq",
                branch_id_for(SRC)) == src_before
    # The parent continues as before.
    lc.upstream.respond_sse(answer("A4"))
    assert lc.post(SRC, body(msgs + [user("U4")])).status_code == 200


def test_divergence_inside_the_source_session_is_still_409(lc):
    msgs = three_turns(lc)
    assert fork(lc, at_turn=1, session="ses_fork").status_code == 200
    r = lc.post(SRC, body(msgs[:3] + [user("edited")]))
    assert r.status_code == 409 and r.json()["error"]["code"] == "history_divergence"


@pytest.mark.parametrize("source, doc, status, code", [
    ("ses_none", {"at_turn": 1}, 400, "unknown_session"),
    (SRC, {"at_turn": 0}, 400, "unknown_turn"),
    (SRC, {"at_turn": 4}, 400, "unknown_turn"),
    (SRC, {"at_turn": "2"}, 400, "invalid_body"),
    (SRC, {"at_turn": 1, "session": "bad..id"}, 400, "invalid_session_id"),
    (SRC, {"at_turn": 1, "session": SRC}, 409, "session_exists"),
    (SRC, {"at_turn": 1, "session": ""}, 400, "invalid_body"),
    (SRC, {"at_turn": 1, "session": 0}, 400, "invalid_body"),
])
def test_bad_forks_are_refused_and_write_nothing(lc, source, doc, status, code):
    three_turns(lc)
    before = rows(lc, "SELECT count(*) FROM occurrences")
    r = fork(lc, source, **doc)
    assert r.status_code == status and r.json()["error"]["code"] == code, r.text
    assert r.headers["x-should-retry"] == "false"
    assert rows(lc, "SELECT count(*) FROM occurrences") == before
    assert rows(lc, "SELECT count(*) FROM forks") == [(0,)]


def test_a_fork_without_a_name_gets_a_new_session_id(lc):
    three_turns(lc)
    r = fork(lc, at_turn=3)
    assert r.status_code == 200
    new = r.json()["session"]
    assert new != SRC and shape(lc, new) == shape(lc, SRC)


def test_the_cli_forks_through_the_running_proxy(lc, capsys):
    three_turns(lc)
    port = httpx.URL(lc.proxy_url).port
    rc = main(["session", "fork", SRC, "--at", "2", "--session", "ses_cli", "--port", str(port)])
    out = capsys.readouterr().out
    assert rc == 0 and "ses_cli" in out and f"/s/ses_cli/" in out
    assert shape(lc, "ses_cli") == shape(lc, SRC)[:5]


def test_a_hidden_loop_turn_still_folds_into_one_message_in_the_fork(tmp_path):
    from .test_hidden_loop_http import GREP, _masked, _post, view_stack
    from .test_view_http import SID as VIEW_SID

    with view_stack(tmp_path, input_budget=8000, hidden_tools="t2") as (fake, url, settings):
        fake.respond_turn("Checking. ", calls=[GREP])
        fake.respond_turn("It is in read 3.")
        assert _post(url, _masked()).status_code == 200
        n = len(fake.requests)
        r = httpx.post(f"{url}/palimnesis/sessions/{VIEW_SID}/fork",
                       json={"at_turn": 2, "session": "ses_hfork"}, timeout=30)
        assert r.status_code == 200, r.text
        assert len(fake.requests) == n
    c = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    try:
        src = load_archived(c, branch_id_for(VIEW_SID))
        new = load_archived(c, branch_id_for("ses_hfork"))
    finally:
        c.close()
    turns = [i for i, a in enumerate(src) if a.role == "user" and a.source in ("client", "client_import")]
    assert len(turns) == 2  # the imported history's first message, then the question
    assert [(a.role, a.content_sha256, a.text, a.tool_calls) for a in new] ==         [(a.role, a.content_sha256, a.text, a.tool_calls) for a in src]
    assert new[-1].text == "Checking. It is in read 3." and not new[-1].tool_calls


def test_accounting_replay_and_fork_add_no_unexplained_calls(tmp_path):
    """S11 cache audit: a keyed replay records no upstream call; a fork's first call is
    ``first_call`` on its own branch; refusals before acceptance record nothing."""
    from .test_view_http import SID as VIEW_SID, body as vbody, history, post, view_stack

    with view_stack(tmp_path, input_budget=8000) as (fake, url, settings):
        msgs = history(3) + [{"role": "user", "content": "go on"}]
        fake.respond_counted("done")
        payload = vbody(msgs, max_completion_tokens=8192)
        r1 = httpx.post(f"{url}/s/{VIEW_SID}/v1/chat/completions", content=payload,
                        headers={"Idempotency-Key": "kk"}, timeout=60)
        r2 = httpx.post(f"{url}/s/{VIEW_SID}/v1/chat/completions", content=payload,
                        headers={"Idempotency-Key": "kk"}, timeout=60)
        assert r1.status_code == r2.status_code == 200
        before = rows_db(settings.db_path, "SELECT count(*) FROM events WHERE kind = 'upstream_call'")
        assert before == [(1,)]  # the replay made no call and recorded none
        assert httpx.post(f"{url}/palimnesis/sessions/{VIEW_SID}/fork",
                          json={"at_turn": 1, "session": "ses_acct"}, timeout=30).status_code == 200
        fork_msgs = msgs[:-1] + [{"role": "assistant", "content": "done"}]
        users = [i for i, m in enumerate(msgs) if m["role"] == "user"]
        fake.respond_counted("forked")
        branch = msgs[:users[1]] if len(users) > 1 else msgs
        r3 = httpx.post(f"{url}/s/ses_acct/v1/chat/completions",
                        content=vbody(branch + [{"role": "user", "content": "branch"}],
                                      max_completion_tokens=8192), timeout=60)
        assert r3.status_code == 200, r3.text[:300]
        assert fork_msgs
    calls = rows_db(settings.db_path,
                    "SELECT json_extract(payload, '$.branch_id'), json_extract(payload, '$.cause')"
                    " FROM events WHERE kind = 'upstream_call' ORDER BY event_id")
    assert calls[-1] == (branch_id_for("ses_acct"), "first_call")
    assert all(c[1] != "unexplained" for c in calls)


def rows_db(db, sql):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()
