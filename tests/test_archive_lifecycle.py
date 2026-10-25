"""Archive-mode request lifecycle at the HTTP seam (Phase 1).

Divergence, busy and duplicate classification, terminal handling of upstream
streams, idempotency keys, Continue-after-partial and hidden internal events.
Requests go through the proxy to a scripted fake upstream; the archive DB is
inspected read-only. Expected values come from contracts §3, §5, §6, §11,
decisions D10/D11 and the OpenCode partials probe fixtures.
"""

from __future__ import annotations

import json
import re
import socket
import sqlite3
import threading
import time
from pathlib import Path

import httpx
import pytest

from palimnesis.api import create_app
from palimnesis.config import Settings
from palimnesis.ledger import branch_id_for, load_archived

from .archive_helpers import (
    CHAT,
    CONTINUE_TEXT,
    DONE,
    RESET,
    answer,
    assistant,
    body,
    chunk,
    eventually,
    in_thread,
    lifecycle_stack,
    sse_data,
    user,
)
from .servers import serve

ROOT = Path(__file__).resolve().parents[1]
PARTIALS = ROOT / "eval/fixtures/opencode-2.1.4/partials"
SID = "ses_lifecycle"
SYSTEM = {"role": "system", "content": "You are terse."}


@pytest.fixture
def lc(tmp_path):
    with lifecycle_stack(tmp_path) as s:
        yield s


def history(lc, session: str = SID):
    with lc.db() as c:
        return load_archived(c, branch_id_for(session))


def error_of(r: httpx.Response) -> dict:
    return r.json()["error"]


def assert_rejected(r: httpx.Response, status: int, code: str) -> None:
    assert r.status_code == status, r.content[:300]
    assert error_of(r)["code"] == code
    assert r.headers["x-should-retry"] == "false"


def two_turns(lc) -> list[dict]:
    """Archive S,U1 → A1 and S,U1,A1,U2 → A2; return the last client history."""
    lc.upstream.respond_sse(answer("A1"))
    assert lc.post(SID, body([SYSTEM, user("U1")])).status_code == 200
    lc.upstream.respond_sse(answer("A2"))
    msgs = [SYSTEM, user("U1"), assistant("A1"), user("U2")]
    assert lc.post(SID, body(msgs)).status_code == 200
    return msgs + [assistant("A2")]


# --- GL3: divergence (D10.1) -------------------------------------------------


@pytest.mark.parametrize(
    "resend, index",
    [
        pytest.param([SYSTEM, user("U1 edited"), assistant("A1"), user("U2"), assistant("A2"),
                      user("U3")], 1, id="edited_earlier_user_message"),
        pytest.param([SYSTEM, user("U1"), assistant("A1"), user("U3 replaces U2")], 3,
                     id="truncated_history_resend_with_new_user"),
        pytest.param([SYSTEM, user("U1"), assistant("A1 rewritten"), user("U2"),
                      assistant("A2"), user("U3")], 2, id="assistant_text_differs"),
        pytest.param([SYSTEM, user("U1"), assistant("A1"), user("U2"), assistant("A2"),
                      user("U3"), assistant("injected by client"), user("U4")], 6,
                     id="assistant_not_generated_by_palimnesis"),
    ],
)
def test_divergent_history_409_history_divergence_nothing_sent(lc, resend, index):
    two_turns(lc)
    requests_before = lc.count("requests")

    r = lc.post(SID, body(resend))

    assert_rejected(r, 409, "history_divergence")
    message = error_of(r)["message"]
    assert re.search(rf"\b{index}\b", message), message  # names the message index
    for m in resend:  # no content echoed (D10.1)
        if m["content"] not in ("U1", "U2", "A1", "A2"):
            assert m["content"] not in message
    assert len(lc.upstream.requests) == 2
    assert lc.count("requests") == requests_before


# --- GL3 / §5: concurrent requests -------------------------------------------


def _slow_first_request(lc, msgs):
    lc.upstream.respond_sse([(1.5, chunk({"role": "assistant", "content": ""})),
                             chunk({"content": "A1"}), chunk({}, "stop"), DONE])
    t, result = in_thread(lambda: lc.post(SID, body(msgs)))
    assert eventually(lambda: len(lc.upstream.requests) == 1)
    return t, result


def test_second_different_request_while_active_409_session_busy(lc):
    t, first = _slow_first_request(lc, [SYSTEM, user("U1")])

    r = lc.post(SID, body([SYSTEM, user("something else")]))

    assert_rejected(r, 409, "session_busy")
    t.join(10)
    assert first["value"].status_code == 200
    assert len(lc.upstream.requests) == 1


def test_identical_request_while_active_409_request_in_progress(lc):
    t, first = _slow_first_request(lc, [SYSTEM, user("U1")])

    r = lc.post(SID, body([SYSTEM, user("U1")]))

    assert_rejected(r, 409, "request_in_progress")
    t.join(10)
    assert first["value"].status_code == 200
    assert len(lc.upstream.requests) == 1
    assert lc.count("requests") == 1


def test_concurrent_same_key_gets_409_in_progress_single_upstream_call(lc):
    lc.upstream.respond_json(b'{"choices":[]}', delay=1.5)
    payload = body([user("q")], stream=False)
    t, _ = in_thread(lambda: lc.post(SID, payload, headers={"Idempotency-Key": "k1"}))
    assert eventually(lambda: len(lc.upstream.requests) == 1)

    r = lc.post(SID, payload, headers={"Idempotency-Key": "k1"})

    assert_rejected(r, 409, "request_in_progress")
    t.join(10)
    assert len(lc.upstream.requests) == 1


# --- GL1 / §6: keyless duplicates --------------------------------------------


def test_failed_no_output_resend_adds_attempt_not_occurrences(lc):
    error_body = b'{"error":{"code":503,"message":"Loading model","type":"unavailable_error"}}'
    lc.upstream.respond_json(error_body, status=503)
    payload = body([SYSTEM, user("U1")])

    first = lc.post(SID, payload)

    assert first.status_code == 503
    assert first.content == error_body
    assert first.headers["x-should-retry"] == "false"

    # The retry carries a retry-count hint, which is not identity (contracts §5).
    lc.upstream.respond_sse(answer("A1"))
    second = lc.post(SID, payload, headers={"x-stainless-retry-count": "1"})

    assert second.status_code == 200, second.content[:300]
    assert len(lc.upstream.requests) == 2
    with lc.db() as c:
        attempts = c.execute("SELECT request_id, n FROM attempts ORDER BY n").fetchall()
        assert c.execute("SELECT count(*) FROM requests").fetchone()[0] == 1
    assert [n for _, n in attempts] == [1, 2]
    assert len({rid for rid, _ in attempts}) == 1
    assert [(a.role, a.source) for a in history(lc)] == [
        ("system", "client"), ("user", "client"), ("assistant", "generated")]
    assert [p.get("status") for _, p in lc.events("attempt_failed")] == [503]


def test_keyless_completed_absent_409_ambiguous_retry(lc):
    lc.upstream.respond_sse(answer("A1"))
    payload = body([SYSTEM, user("U1")])
    assert lc.post(SID, payload).status_code == 200

    r = lc.post(SID, payload)

    assert_rejected(r, 409, "ambiguous_retry")
    assert len(lc.upstream.requests) == 1
    assert lc.count("attempts") == 1


def test_identical_user_text_in_two_turns_gets_two_addresses(lc):
    lc.upstream.respond_sse(answer("ok"))
    assert lc.post(SID, body([user("same")])).status_code == 200
    lc.upstream.respond_sse(answer("ok again"))
    r = lc.post(SID, body([user("same"), assistant("ok"), user("same")]))

    assert r.status_code == 200, r.content[:300]
    archived = history(lc)
    assert [a.role for a in archived] == ["user", "assistant", "user", "assistant"]
    users = [a.occ_id for a in archived if a.role == "user"]
    assert len(set(users)) == 2
    with lc.db() as c:
        aliases = c.execute(
            f"SELECT target_id, alias FROM aliases WHERE target_id IN ({','.join('?' * 2)})",
            users).fetchall()
    assert len(aliases) == 2
    assert len({alias for _, alias in aliases}) == 2


def test_identical_first_requests_in_two_sessions_stay_separate(lc):
    payload = body([SYSTEM, user("U1")])
    for session in ("ses_one", "ses_two"):
        lc.upstream.respond_sse(answer("A1"))
        assert lc.post(session, payload).status_code == 200

    one, two = history(lc, "ses_one"), history(lc, "ses_two")
    assert [a.role for a in one] == [a.role for a in two] == ["system", "user", "assistant"]
    assert not {a.occ_id for a in one} & {a.occ_id for a in two}
    with lc.db() as c:
        per_session = dict(c.execute(
            "SELECT session_id, count(*) FROM requests GROUP BY session_id").fetchall())
    assert per_session == {"ses_one": 1, "ses_two": 1}
    assert len(lc.upstream.requests) == 2


# --- §3: unsupported features (D10.10, D11) ----------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(body([user("q")], n=1), id="n"),
        pytest.param(body([{"role": "developer", "content": "x"}, user("q")]), id="developer"),
        pytest.param(body([{"role": "user", "content": [{"type": "text", "text": "q"}]}]),
                     id="text_parts"),
        pytest.param(body([user("q")], logprobs=True), id="unknown_top_level"),
        pytest.param(body([{"role": "user", "content": "q", "name": "dan"}]), id="user_name"),
    ],
)
def test_unsupported_feature_rejected_nothing_archived(lc, payload):
    r = lc.post(SID, payload)

    assert_rejected(r, 400, "unsupported_feature")
    assert lc.upstream.requests == []
    assert lc.count("requests") == 0
    assert lc.count("occurrences") == 0
    assert lc.count("raw_bodies") == 0


@pytest.mark.parametrize("path", ["/v1/messages", "/v1/responses"])
def test_other_post_endpoints_unsupported_in_archive_mode(lc, path):
    r = httpx.post(f"{lc.proxy_url}/s/{SID}{path}", content=body([user("q")]))

    assert r.status_code == 400
    assert r.headers["x-should-retry"] == "false"
    assert "unsupported_feature" in r.text
    assert lc.upstream.requests == []
    assert lc.count("requests") == 0


# --- §3 / §5: terminal handling of streams (D10.13) --------------------------


def _assert_failed_stream(lc, r, forwarded: bytes) -> None:
    assert r.status_code == 200
    assert r.headers["x-should-retry"] == "false"
    assert r.content.startswith(forwarded)
    last = json.loads(sse_data(r.content)[-1])
    assert last["error"]["code"] == "upstream_stream_failed"
    assert "[DONE]" not in sse_data(r.content)
    generated = history(lc)[-1]
    assert generated.source == "generated"
    assert generated.complete is False
    assert len(lc.events("attempt_failed")) == 1
    assert lc.events("turn_complete") == []


def test_archive_eof_without_done_ends_with_error_event_turn_incomplete(lc):
    sent = [chunk({"role": "assistant", "content": ""}), chunk({"content": "Hel"}),
            chunk({"content": "lo"})]
    lc.upstream.respond_sse(sent)

    r = lc.post(SID, body([user("q")]))

    _assert_failed_stream(lc, r, b"".join(sent))
    assert history(lc)[-1].text == "Hello"


def test_finish_then_eof_without_done_is_failure(lc):
    sent = [chunk({"role": "assistant", "content": ""}), chunk({"content": "Hi"})]
    finish = chunk({}, "stop")
    lc.upstream.respond_sse(sent + [finish])

    r = lc.post(SID, body([user("q")]))

    _assert_failed_stream(lc, r, b"".join(sent))
    assert finish not in r.content
    assert b'"finish_reason": "stop"' not in r.content


def test_upstream_reset_mid_stream_yields_error_event(lc):
    sent = [chunk({"role": "assistant", "content": ""}), chunk({"content": "Hi"})]
    lc.upstream.respond_sse(sent + [(0.1, RESET)])

    r = lc.post(SID, body([user("q")]))

    _assert_failed_stream(lc, r, b"".join(sent))


def test_upstream_non_200_is_relayed_with_should_retry_false(lc):
    error_body = b'{"error":{"code":500,"message":"boom","type":"server_error"}}'
    lc.upstream.respond_json(error_body, status=500)

    r = lc.post(SID, body([user("q")]))

    assert r.status_code == 500
    assert r.content == error_body
    assert r.headers["x-should-retry"] == "false"
    assert len(lc.events("attempt_failed")) == 1
    assert lc.events("turn_complete") == []


def test_client_receives_upstream_bytes_unchanged_for_complete_streams(lc):
    sent = [chunk({"role": "assistant", "content": ""}), chunk({"reasoning_content": "hm"}),
            chunk({"content": "é😀"}), chunk({}, "stop"), DONE]
    lc.upstream.respond_sse(sent)

    r = lc.post(SID, body([user("q")]))

    assert r.status_code == 200
    assert r.headers["x-should-retry"] == "false"
    assert r.content == b"".join(sent)
    generated = history(lc)[-1]
    assert (generated.reasoning, generated.text, generated.complete) == ("hm", "é😀", True)


# --- Delivery ledger ----------------------------------------------------------


def test_client_disconnect_records_cancelled_and_closes_upstream(lc):
    lc.upstream.respond_sse([chunk({"role": "assistant", "content": ""}),
                             chunk({"content": "a"})]
                            + [(0.05, chunk({"content": "n"}))] * 200)

    with httpx.stream("POST", lc.url(SID), content=body([user("q")]), timeout=30) as r:
        next(r.iter_raw())

    assert eventually(lambda: lc.upstream.closed_streams == [CHAT])
    assert lc.upstream.completed_streams == []
    assert eventually(lambda: len(lc.events("cancelled")) == 1)
    assert lc.events("turn_complete") == []
    assert history(lc)[-1].complete is False


def test_delivery_events_sequence_stream(lc):
    sent = [chunk({"role": "assistant", "content": ""}), (0.1, chunk({"content": "a"})),
            (0.1, chunk({"content": "b"})), chunk({}, "stop"), DONE]
    lc.upstream.respond_sse(sent)

    r = lc.post(SID, body([user("q")]))

    assert r.status_code == 200
    milestones = {"accepted_input", "attempt_started", "delivery_started", "turn_complete",
                  "delivery_completed", "delivery_failed", "cancelled", "attempt_failed"}
    kinds = [k for k, _ in lc.events() if k in milestones]
    assert kinds == ["accepted_input", "attempt_started", "delivery_started", "turn_complete",
                     "delivery_completed"]
    [(_, completed)] = lc.events("delivery_completed")
    assert completed["bytes_forwarded"] == len(r.content)


def test_delivery_progress_recorded_for_later_batches(lc):
    # Three batches separated by more than the batch age: the ledger should
    # show delivery advancing past the first batch, not only its start.
    sent = [chunk({"role": "assistant", "content": ""}), (0.2, chunk({"content": "a"})),
            (0.2, chunk({"content": "b"})), chunk({}, "stop"), DONE]
    lc.upstream.respond_sse(sent)

    r = lc.post(SID, body([user("q")]))

    assert r.status_code == 200
    progress = [p["bytes_forwarded"] for _, p in lc.events("delivery_progress")]
    assert progress, "no delivery_progress events"
    assert progress == sorted(set(progress)) and 0 < progress[0] < len(r.content)


def test_client_disconnect_before_upstream_headers_cancels_and_abandons(lc):
    lc.upstream.respond_json(NONSTREAM, delay=5.0)

    with pytest.raises(httpx.ReadTimeout):
        httpx.post(lc.url(SID), content=body([user("q")], stream=False), timeout=0.5)

    assert eventually(lambda: lc.upstream.abandoned == [CHAT])
    assert eventually(lambda: len(lc.events("cancelled")) == 1)
    assert lc.count("prepared_responses") == 0


def test_nonstream_upstream_reset_mid_body_is_shaped_no_retry_failure(lc):
    lc.upstream.respond_sse([b'{"id":"chatcmpl-1","choices":[', (0.1, RESET)],
                            headers={"content-type": "application/json"})

    r = httpx.post(lc.url(SID), content=body([user("q")], stream=False), timeout=30)

    assert r.status_code in (502, 503), (r.status_code, r.content[:200])
    assert r.headers.get("x-should-retry") == "false"
    assert "error" in r.json()
    assert len(lc.events("attempt_failed")) == 1


def test_nonstream_malformed_upstream_body_is_shaped_no_retry_failure(lc):
    lc.upstream.respond_json(b'{"id":"chatcmpl-1","choices":[')

    r = httpx.post(lc.url(SID), content=body([user("q")], stream=False), timeout=30)

    assert r.status_code in (502, 503), (r.status_code, r.content[:200])
    assert r.headers.get("x-should-retry") == "false"
    assert "error" in r.json()
    assert len(lc.events("attempt_failed")) == 1


def test_unreachable_upstream_after_acceptance_502_should_retry_false(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    db_path = tmp_path / "archive.db"
    settings = Settings(upstream_base_url=f"http://127.0.0.1:{port}", db_path=db_path)
    with serve(create_app(settings), palimnesis=True) as proxy_url:
        r = httpx.post(f"{proxy_url}/s/{SID}{CHAT}", content=body([user("q")]), timeout=30)

    assert r.status_code == 502
    assert r.json()["error"]["code"] == "upstream_unreachable"
    assert r.headers["x-should-retry"] == "false"  # input is archived (contracts §5)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        kinds = [k for (k,) in conn.execute("SELECT kind FROM events")]
    finally:
        conn.close()
    assert "accepted_input" in kinds and "attempt_failed" in kinds


# --- Non-streaming and idempotency keys (§6, GL1) ----------------------------

NONSTREAM = (b'{"id":"chatcmpl-1","object":"chat.completion","created":1,"model":"m",'
             b'"choices":[{"index":0,"message":{"role":"assistant","content":"391",'
             b'"reasoning_content":"17*23"},"finish_reason":"stop"}],'
             b'"usage":{"prompt_tokens":5,"completion_tokens":3,"total_tokens":8}}')


def test_nonstream_response_delivered_and_prepared(lc):
    lc.upstream.respond_json(NONSTREAM)

    r = lc.post(SID, body([user("q")], stream=False))

    assert r.status_code == 200
    assert r.content == NONSTREAM
    assert r.headers["x-should-retry"] == "false"
    with lc.db() as c:
        [(status, prepared)] = c.execute("SELECT status, body FROM prepared_responses").fetchall()
    assert (status, prepared) == (200, NONSTREAM)
    generated = history(lc)[-1]
    assert (generated.text, generated.reasoning, generated.complete) == ("391", "17*23", True)
    kinds = [k for k, _ in lc.events()]
    assert kinds.index("response_prepared") < kinds.index("delivery_completed")


def test_completed_nonstream_key_replays_exact_bytes_without_upstream(lc):
    lc.upstream.respond_json(NONSTREAM)
    payload = body([user("q")], stream=False)
    first = lc.post(SID, payload, headers={"Idempotency-Key": "k1"})
    assert first.status_code == 200

    again = lc.post(SID, payload, headers={"Idempotency-Key": "k1"})

    assert again.status_code == 200
    assert again.content == first.content == NONSTREAM
    assert len(lc.upstream.requests) == 1
    assert lc.count("requests") == 1
    assert lc.count("attempts") == 1


@pytest.mark.parametrize(
    "second",
    [
        pytest.param(body([user("q"), assistant("391"), user("other")], stream=False),
                     id="different_messages"),
        pytest.param(body([user("q")], stream=False, temperature=0.5), id="different_temperature"),
        pytest.param(body([user("q")], stream=True), id="different_stream_mode"),
    ],
)
def test_same_key_different_request_409_idempotency_conflict(lc, second):
    lc.upstream.respond_json(NONSTREAM)
    assert lc.post(SID, body([user("q")], stream=False),
                   headers={"Idempotency-Key": "k1"}).status_code == 200

    r = lc.post(SID, second, headers={"Idempotency-Key": "k1"})

    assert_rejected(r, 409, "idempotency_conflict")
    assert len(lc.upstream.requests) == 1
    assert NONSTREAM not in r.content


def test_same_key_in_other_session_is_independent(lc):
    payload = body([user("q")], stream=False)
    for session in ("ses_one", "ses_two"):
        lc.upstream.respond_json(NONSTREAM)
        r = lc.post(session, payload, headers={"Idempotency-Key": "k1"})
        assert r.status_code == 200, r.content[:300]

    assert len(lc.upstream.requests) == 2
    assert len(history(lc, "ses_two")) == 2


def test_repeated_streaming_key_409_streaming_replay_unsupported_no_upstream(lc):
    lc.upstream.respond_sse(answer("A1"))
    payload = body([user("q")])
    assert lc.post(SID, payload, headers={"Idempotency-Key": "k1"}).status_code == 200

    r = lc.post(SID, payload, headers={"Idempotency-Key": "k1"})

    assert_rejected(r, 409, "streaming_replay_unsupported")
    assert len(lc.upstream.requests) == 1


def test_idempotent_retry_adds_no_occurrences(lc):
    lc.upstream.respond_json(b'{"error":{"message":"busy"}}', status=503)
    payload = body([user("q")], stream=False)
    assert lc.post(SID, payload, headers={"Idempotency-Key": "k1"}).status_code == 503

    lc.upstream.respond_json(NONSTREAM)
    r = lc.post(SID, payload, headers={"Idempotency-Key": "k1"})

    assert r.status_code == 200
    assert r.content == NONSTREAM
    with lc.db() as c:
        assert c.execute("SELECT count(*) FROM requests").fetchone()[0] == 1
        assert [n for (n,) in c.execute("SELECT n FROM attempts ORDER BY n")] == [1, 2]
    assert [(a.role, a.source) for a in history(lc)] == [
        ("user", "client"), ("assistant", "generated")]


def test_identical_tool_results_in_one_request_are_distinct(lc):
    calls = [{"index": i, "id": f"call_{c}", "type": "function",
              "function": {"name": "read", "arguments": '{"filePath":"a.txt"}'}}
             for i, c in enumerate("ab")]
    lc.upstream.respond_sse([chunk({"role": "assistant", "content": ""}),
                             chunk({"tool_calls": calls}), chunk({}, "tool_calls"), DONE])
    assert lc.post(SID, body([user("read a twice")])).status_code == 200

    lc.upstream.respond_sse(answer("same twice"))
    tool_calls = [{"id": f"call_{c}", "type": "function",
                   "function": {"name": "read", "arguments": '{"filePath":"a.txt"}'}}
                  for c in "ab"]
    r = lc.post(SID, body([
        user("read a twice"),
        {"role": "assistant", "content": None, "tool_calls": tool_calls},
        {"role": "tool", "tool_call_id": "call_a", "content": "same"},
        {"role": "tool", "tool_call_id": "call_b", "content": "same"},
    ]))

    assert r.status_code == 200, r.content[:300]
    tools = [a.occ_id for a in history(lc) if a.role == "tool"]
    assert len(set(tools)) == 2
    with lc.db() as c:
        aliases = c.execute("SELECT alias FROM aliases WHERE target_id IN (?, ?)",
                            tools).fetchall()
    assert len(set(aliases)) == 2


# --- §11: commit order and storage failure -----------------------------------


def test_input_committed_before_upstream_sees_request(lc):
    seen: dict = {}

    def snapshot():
        with lc.db() as c:
            seen["requests"] = c.execute("SELECT count(*) FROM requests").fetchone()[0]
            seen["kinds"] = [k for (k,) in c.execute("SELECT kind FROM events")]
            seen["roles"] = [r for (r,) in c.execute("SELECT role FROM occurrences ORDER BY seq")]
            seen["bindings"] = c.execute(
                "SELECT key, stream FROM idempotency_bindings").fetchall()

    lc.on_upstream_request = snapshot
    lc.upstream.respond_sse(answer("A1"))

    r = lc.post(SID, body([SYSTEM, user("U1")]), headers={"Idempotency-Key": "k1"})

    assert r.status_code == 200
    # A1: the excerpt selection for the new instruction is durable before inference too.
    assert seen == {"requests": 1, "kinds": ["accepted_input", "attempt_started",
                                             "excerpts_selected"],
                    "roles": ["system", "user"], "bindings": [("k1", 1)]}


def _lock_db(lc) -> sqlite3.Connection:
    conn = sqlite3.connect(lc.db_path, isolation_level=None, check_same_thread=False)
    conn.execute("BEGIN IMMEDIATE")
    return conn


def test_input_commit_failure_503_archive_unavailable(lc):
    lock = _lock_db(lc)
    try:
        r = lc.post(SID, body([user("q")]))
    finally:
        lock.execute("ROLLBACK")
        lock.close()

    assert r.status_code == 503
    assert error_of(r)["code"] == "archive_unavailable"
    assert r.headers["retry-after"] == "2"
    assert r.headers["x-should-retry"] == "true"
    assert lc.upstream.requests == []
    assert lc.count("requests") == 0


def _fail_mid_stream_commit(lc) -> httpx.Response:
    """Lock the DB once input is accepted and hold it past the writer's busy
    timeout until the relay gives up on the stream."""
    releasers: list[threading.Thread] = []

    def lock_after_accept():
        conn = _lock_db(lc)

        def release():
            eventually(lambda: bool(lc.upstream.closed_streams), timeout=30)
            conn.execute("ROLLBACK")
            conn.close()

        releasers.append(threading.Thread(target=release, daemon=True))
        releasers[0].start()

    lc.on_upstream_request = lock_after_accept
    lc.upstream.respond_sse([chunk({"role": "assistant", "content": ""}),
                             chunk({"content": "UNCOMMITTED"})]
                            + [(0.05, chunk({"content": "n"}))] * 600)

    r = lc.post(SID, body([user("q")]))
    lc.on_upstream_request = None
    releasers[0].join(30)
    return r


def test_commit_failure_mid_stream_stops_forwarding_closes_upstream(lc):
    r = _fail_mid_stream_commit(lc)

    assert r.status_code == 200
    assert b"UNCOMMITTED" not in r.content
    data = sse_data(r.content)
    assert data and all("error" in json.loads(d) for d in data)  # only the error event
    assert lc.upstream.closed_streams == [CHAT]
    assert lc.upstream.completed_streams == []
    assert lc.events("turn_complete") == []


def test_session_usable_after_mid_stream_commit_failure(lc):
    _fail_mid_stream_commit(lc)
    assert lc.events("attempt_failed") == []  # storage was down when the relay gave up

    lc.upstream.respond_sse(answer("A1"))
    r = lc.post(SID, body([user("q")]))

    assert r.status_code == 200, r.content[:300]


# --- Keepalive relay (R4) ----------------------------------------------------


def test_upstream_comments_forwarded_promptly_on_archive_path(lc):
    keepalive = b": keepalive\n\n"
    sent = [keepalive, (2.0, chunk({"role": "assistant", "content": ""})),
            chunk({"content": "late"}), chunk({}, "stop"), DONE]
    lc.upstream.respond_sse(sent)

    with httpx.stream("POST", lc.url(SID), content=body([user("q")]), timeout=30) as r:
        headers_at = time.monotonic()
        received, keepalive_at = b"", None
        for piece in r.iter_raw():
            received += piece
            if keepalive_at is None and keepalive in received:
                keepalive_at = time.monotonic()

    assert keepalive_at is not None
    assert keepalive_at - headers_at < 0.5
    assert received == b"".join(c if isinstance(c, bytes) else c[1] for c in sent)


# --- Continue and length (D10.3, opencode_partials.md) -----------------------


def _fixture(run: str, n: int) -> bytes:
    return (PARTIALS / run / f"req-{n:02d}.json").read_bytes()


R = "Thinking about attempt-1"
T = "Partial answer attempt-1"
R_WS = "\nThinking about attempt-1\n\n"
T_WS = "\n\nPartial answer attempt-1 \n"


def _halves(field: str, text: str) -> list[bytes]:
    mid = len(text) // 2
    return [chunk({field: part}) for part in (text[:mid], text[mid:]) if part]


def _tool_start() -> list[bytes]:
    return [chunk({"tool_calls": [{"index": 0, "id": "call_fault_1", "type": "function",
                                   "function": {"name": "read", "arguments": ""}}]}),
            chunk({"tool_calls": [{"index": 0,
                                   "function": {"arguments": '{"filePath": "notes.tx'}}]})]


def _fail_turn_one(lc, run: str, reasoning: str, text: str, tool: bool) -> None:
    """Stream the run's partial (reasoning, text[, tool call]) then end without [DONE]."""
    sent = [chunk({"role": "assistant", "content": ""})]
    sent += _halves("reasoning_content", reasoning) + _halves("content", text)
    sent += _tool_start() if tool else []
    lc.upstream.respond_sse(sent)
    first = lc.post(SID, _fixture(run, 2))
    assert first.status_code == 200
    assert json.loads(sse_data(first.content)[-1])["error"]["code"] == "upstream_stream_failed"
    assert history(lc)[-1].complete is False


@pytest.mark.parametrize(
    "run, reasoning, text, followups",
    [
        pytest.param("A_reason_text_err_noretry", R, T, [3], id="A_next_turn"),
        pytest.param("A2_reason_err_noretry", R, "", [3], id="A2_reasoning_only"),
        pytest.param("A3_ws_reason_text_err_noretry", R_WS, T_WS, [3], id="A3_whitespace"),
        pytest.param("B_text_err_noretry", "", T, [3], id="B_text_only"),
        pytest.param("C_text_eof_noretry", "", T, [3, 4], id="C_continue"),
        pytest.param("D_text_eof", "", T, [3, 4], id="D_continue"),
        pytest.param("D2_reason_text_eof", R, T, [3, 4], id="D2_continue"),
        pytest.param("D2_reason_text_eof_v1", R, T, [3, 4], id="D2_v1_no_reasoning_field"),
        pytest.param("D3_ws_reason_text_eof", R_WS, T_WS, [3, 4], id="D3_whitespace_continue"),
    ],
)
def test_continue_flattened_partial_maps_to_archive(lc, run, reasoning, text, followups):
    _fail_turn_one(lc, run, reasoning, text, tool=False)
    flattened = reasoning + text

    for n in followups:
        lc.upstream.respond_sse(answer("OK from fault server"))
        sent = _fixture(run, n)
        r = lc.post(SID, sent)

        assert r.status_code == 200, (n, r.content[:300])
        client = json.loads(sent)["messages"]
        upstream = json.loads(lc.upstream.requests[-1].body)["messages"]
        assert client[2]["content"] == flattened  # the probe's flattened shape
        assert client[2].get("reasoning_content", "") == ""
        # D10.3: upstream sees reasoning and text split again at the extent.
        assert upstream[2] == {"role": "assistant", "content": text,
                               "reasoning_content": reasoning}
        assert upstream[:2] == client[:2] and upstream[3:] == client[3:]
        if n == 3 and len(client) > 3 and client[3]["role"] == "user" and run[0] in "CD":
            assert client[3] == {"role": "user", "content": CONTINUE_TEXT}

    extents = [p["extent"] for _, p in lc.events("partial_acknowledged")]
    assert extents and extents[0] == len(flattened)
    archived = history(lc)
    assert (archived[2].reasoning, archived[2].text, archived[2].complete) == (
        reasoning, text, False)
    assert len(archived) == len(json.loads(_fixture(run, followups[-1]))["messages"]) + 1


@pytest.mark.parametrize(
    "run, reasoning, text, followups",
    [
        pytest.param("E_tool_err_noretry", "", "", [3], id="E_tool_only"),
        pytest.param("E2_reason_text_tool_err_noretry", R, "Let me look attempt-1", [3],
                     id="E2_reason_text_tool"),
        pytest.param("E3_tool_eof", "", "", [3, 4], id="E3_tool_continue"),
    ],
)
def test_partial_tool_call_then_tool_error_message_extends(lc, run, reasoning, text, followups):
    _fail_turn_one(lc, run, reasoning, text, tool=True)

    for n in followups:
        lc.upstream.respond_sse(answer("OK from fault server"))
        sent = _fixture(run, n)
        r = lc.post(SID, sent)

        assert r.status_code == 200, (n, r.content[:300])
        client = json.loads(sent)["messages"]
        upstream = json.loads(lc.upstream.requests[-1].body)["messages"]
        assert client[2]["tool_calls"][0]["function"]["arguments"] == "{}"
        assert client[3]["role"] == "tool" and client[3]["tool_call_id"] == "call_fault_1"
        assert upstream[2]["tool_calls"] == client[2]["tool_calls"]
        assert upstream[2].get("content") == (text or None)
        assert upstream[2].get("reasoning_content", "") == reasoning
        assert upstream[:2] == client[:2] and upstream[3:] == client[3:]

    extents = [p["extent"] for _, p in lc.events("partial_acknowledged")]
    assert extents and extents[0] == len(reasoning + text)
    roles = [(a.role, a.source) for a in history(lc)]
    assert roles[2:5] == [("assistant", "generated"), ("tool", "client"), ("user", "client")]


def test_length_followups_extend(lc):
    lc.upstream.respond_sse(answer("Part one", finish="length"))
    assert lc.post(SID, body([user("long please")])).status_code == 200
    lc.upstream.respond_sse(answer("Part two"))

    r = lc.post(SID, body([user("long please"), assistant("Part one"), user("go on")]))

    assert r.status_code == 200, r.content[:300]
    archived = history(lc)
    assert [a.role for a in archived] == ["user", "assistant", "user", "assistant"]
    assert archived[1].complete and archived[1].text == "Part one"
    assert lc.events("partial_acknowledged") == []


# --- GL7: hidden internal events (D10.9) -------------------------------------

HIDDEN_CALL = {"role": "assistant", "content": None,
               "tool_calls": [{"id": "call_h1", "type": "function",
                               "function": {"name": "read",
                                            "arguments": '{"filePath":"notes.txt"}'}}]}
HIDDEN_RESULT = {"role": "tool", "tool_call_id": "call_h1", "content": "notes: buy milk"}


def _seed_hidden_events(lc, session: str) -> None:
    """Insert an internal tool call and its result after the accepted user turn,
    as an internal tool loop would, while the upstream is still thinking."""
    conn = sqlite3.connect(lc.db_path, isolation_level=None, timeout=10)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        branch = branch_id_for(session)
        (request_id,) = conn.execute("SELECT request_id FROM requests").fetchone()
        (seq,) = conn.execute("SELECT max(seq) FROM occurrences WHERE branch_id = ?",
                              (branch,)).fetchone()
        rows = [
            ("occ_hidden_call", "assistant", "tool_call",
             {"id": "call_h1", "name": "read"}, b'{"filePath":"notes.txt"}'),
            ("occ_hidden_result", "tool", "tool_result",
             {"tool_call_id": "call_h1"}, b"notes: buy milk"),
        ]
        for offset, (occ_id, role, kind, meta, data) in enumerate(rows, start=1):
            conn.execute(
                "INSERT INTO occurrences VALUES (?, ?, ?, NULL, ?, 'internal', 'internal_tool',"
                " ?, NULL, '{}', ?)",
                (occ_id, branch, seq + offset, role, request_id, "sha-" + occ_id))
            conn.execute("INSERT INTO blocks VALUES (?, ?, 0, ?, 'utf-8', ?)",
                         ("blk_" + occ_id, occ_id, kind, json.dumps(meta)))
            conn.execute("INSERT INTO segments VALUES (?, 0, ?)", ("blk_" + occ_id, data))
        conn.execute("COMMIT")
    finally:
        conn.close()


def test_followup_upstream_body_contains_hidden_events_once_in_order(lc):
    first_sent = [(1.0, chunk({"role": "assistant", "content": ""})),
                  chunk({"content": "A1"}), chunk({}, "stop"), DONE]
    lc.upstream.respond_sse(first_sent)
    t, first = in_thread(lambda: lc.post(SID, body([SYSTEM, user("U1")])))
    assert eventually(lambda: len(lc.upstream.requests) == 1)
    _seed_hidden_events(lc, SID)
    t.join(10)
    assert first["value"].status_code == 200
    assert first["value"].content == b"".join(c if isinstance(c, bytes) else c[1]
                                              for c in first_sent)

    second_sent = answer("A2")
    lc.upstream.respond_sse(second_sent)
    client_msgs = [SYSTEM, user("U1"), assistant("A1"), user("U2")]
    r = lc.post(SID, body(client_msgs))

    assert r.status_code == 200, r.content[:300]
    assert r.content == b"".join(second_sent)
    upstream = json.loads(lc.upstream.requests[1].body)["messages"]
    assert len(upstream) == 6
    assert upstream[:2] == client_msgs[:2]
    assert upstream[2]["role"] == "assistant"
    assert upstream[2]["tool_calls"] == HIDDEN_CALL["tool_calls"]
    assert upstream[2].get("content") in (None, "")
    assert upstream[3] == HIDDEN_RESULT
    assert upstream[4:] == client_msgs[2:]
    assert sum(1 for m in upstream if m.get("tool_call_id") == "call_h1") == 1
    assert sum(1 for m in upstream if m.get("tool_calls")) == 1
