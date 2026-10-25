"""Cache accounting and count drift on the archive path (contracts §10, §1.3).

Every upstream call writes one immutable ``upstream_call`` event; its cause comes from the
first rendered turn that differs from the previous call on the branch. Expected values
come from independent renders of the bodies the fake upstream received.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from palimnesis.api import create_app
from palimnesis.config import Settings
from palimnesis.upstreams.strata import tokens

from .fake_upstream import FakeUpstream
from .servers import serve

ROOT = Path(__file__).resolve().parents[1]
REPLAY = ROOT / "eval" / "replay.py"
SID = "acct-1"
TOOLS = [{"type": "function", "function": {"name": "read", "description": "read a file",
                                           "parameters": {"type": "object", "properties": {}}}}]
GEN_PROMPT_THINKING = 5  # "<|im_start|>assistant\n<think>\n" (docs/probes/strata.md §7)


@contextmanager
def acct_stack(tmp_path, fake=None, **settings):
    fake = fake or FakeUpstream()
    with serve(fake.app()) as upstream_url:
        s = Settings(upstream_base_url=upstream_url, db_path=tmp_path / "archive.db", **settings)
        with serve(create_app(s), palimnesis=True) as proxy_url:
            yield fake, proxy_url, s


def _code(i, lines):
    return "\n".join(f"def f{i}_{n}(x): return x * {n}  # {n}" for n in range(lines))


def history(turns, lines=80, system="You are a coding agent."):
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": "refactor the project"}]
    for i in range(turns):
        messages.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": f"call_{i}", "type": "function", "function": {"name": "read", "arguments": "{}"}}]})
        messages.append({"role": "tool", "tool_call_id": f"call_{i}", "content": _code(i, lines)})
    return messages


def body(messages, tools=TOOLS, **settings) -> bytes:
    doc = {"model": "m", "messages": messages, "stream": True, "max_completion_tokens": 8192,
           **settings}
    if tools is not None:
        doc["tools"] = tools
    return json.dumps(doc).encode()


def post(proxy_url, data: bytes, session=SID) -> httpx.Response:
    with httpx.stream("POST", f"{proxy_url}/s/{session}/v1/chat/completions", content=data,
                      timeout=60) as r:
        r.read()
    return r


def rows(settings, sql, *params):
    c = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    try:
        return c.execute(sql, params).fetchall()
    finally:
        c.close()


def events(settings, kind="upstream_call") -> list[dict]:
    return [json.loads(p) for (p,) in rows(
        settings, "SELECT payload FROM events WHERE kind = ? ORDER BY event_id", kind)]


def encoded(raw: bytes) -> list[int]:
    """Token ids of a received body, from a full render (not the proxy's turn layout)."""
    t = tokens.default()
    return t.encode(t.render(**tokens.render_args_from_openai(json.loads(raw))))


def lcp(a, b) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def test_upstream_call_event_fields(tmp_path):
    first = history(2)
    second = first + [{"role": "assistant", "content": "ok"}, {"role": "user", "content": "next"}]
    with acct_stack(tmp_path) as (fake, url, settings):
        fake.respond_counted(cached=0, prompt_ms=812.5)
        assert post(url, body(first)).status_code == 200
        fake.respond_counted(cached=lambda prompt: prompt - 9, prompt_ms=40.25)
        assert post(url, body(second)).status_code == 200

    sent = [encoded(r.body) for r in fake.requests]
    attempts = [a for (a,) in rows(settings, "SELECT attempt_id FROM attempts"
                                             " ORDER BY started_at")]
    one, two = events(settings)
    assert one["call_id"] == attempts[0] and two["call_id"] == attempts[1]
    assert one["prev_call_id"] is None and one["cause"] == "first_call"
    assert two["prev_call_id"] == one["call_id"] == two["global_prev_call_id"]
    assert two["branch_id"] == f"{SID}/main"
    assert two["view_id"] is None and two["view_n"] == 0  # no view version: unmasked
    assert two["input_tokens"] == len(sent[1]) == two["prompt_tokens"]
    assert two["cached_tokens"] == len(sent[1]) - 9 and two["prompt_ms"] == 40.25
    assert one["prompt_ms"] == 812.5 and one["cached_tokens"] == 0
    # The second call extends the first: all of it up to the generation prompt is common
    # (here the newline after "<think>" merges with the empty reasoning's into one token).
    assert two["lcp_tokens"] == lcp(sent[0], sent[1]) == len(sent[0]) - 1
    assert two["first_diff"] is None and two["cause"] == "append"
    # Strata keeps the first call's generation-prompt checkpoint (labeled an estimate).
    assert two["expected_reuse_est"] == len(sent[0]) - GEN_PROMPT_THINKING
    assert two["expected_reuse_label"] == "estimate"
    assert two["reuse_class"] == "full"
    # Events are immutable archive rows.
    c = sqlite3.connect(settings.db_path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            c.execute("UPDATE events SET payload = '{}' WHERE kind = 'upstream_call'")
    finally:
        c.close()


def turn(messages, text="ok", user="next"):
    """The client resends the generated answer and asks again."""
    return messages + [{"role": "assistant", "content": text}, {"role": "user", "content": user}]


def test_cause_append(tmp_path):
    messages = history(2)
    with acct_stack(tmp_path) as (fake, url, settings):
        for i in range(3):
            fake.respond_counted()
            assert post(url, body(messages)).status_code == 200
            messages = turn(messages, user=f"next {i}")

    causes = [(e["cause"], e["first_diff"]) for e in events(settings)]
    assert causes == [("first_call", None), ("append", None), ("append", None)]


def _grow_until_view_moves(fake, url, settings, messages, user_text, limit=12):
    """Append turns until a view version is recorded; returns that call's event."""
    for i in range(limit):
        fake.respond_counted()
        assert post(url, body(messages)).status_code == 200
        if rows(settings, "SELECT count(*) FROM view_versions")[0][0]:
            return events(settings)[-1], messages
        messages = turn(messages, user=f"{user_text} {i} " * 150)
    raise AssertionError("the view never moved")


def test_cause_watermark_move(tmp_path):
    # Tool results grow the session until it crosses H; stubbing the oldest reaches T.
    messages = history(7)
    with acct_stack(tmp_path, input_budget=16000) as (fake, url, settings):
        for i in range(7, 12):
            fake.respond_counted(tool_call=(f"call_{i}", "read", "{}"))
            assert post(url, body(messages)).status_code == 200
            if rows(settings, "SELECT count(*) FROM view_versions")[0][0]:
                break
            messages = messages + [
                {"role": "assistant", "content": None, "tool_calls": [{
                    "id": f"call_{i}", "type": "function",
                    "function": {"name": "read", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": f"call_{i}", "content": _code(i, 80)}]
        moved = events(settings)[-1]
        cause = rows(settings, "SELECT cause FROM view_versions")

    assert cause == [("watermark_move",)]
    assert moved["cause"] == "watermark_move"
    assert moved["view_n"] == 1 and moved["view_id"] is not None
    assert moved["first_diff"]["kind"] == "tool"
    before, after = moved["first_diff"]["turns"]
    assert before["occs"] == after["occs"] and (before["form"], after["form"]) == ("verbatim", "stub")
    assert moved["lcp_tokens"] < moved["first_diff"]["prev_tokens"][1]


def test_cause_collapse(tmp_path):
    # Plain user/assistant turns have nothing to stub, so only a collapse can shrink them.
    messages = [{"role": "system", "content": "You are a coding agent."}]
    for i in range(30):
        messages += [{"role": "user", "content": f"question {i} " * 20},
                     {"role": "assistant", "content": f"answer {i} " * 20}]
    messages.append({"role": "user", "content": "go on"})
    with acct_stack(tmp_path, input_budget=8000) as (fake, url, settings):
        moved, _ = _grow_until_view_moves(fake, url, settings, messages, "more")

    assert moved["cause"] == "collapse"
    before, after = moved["first_diff"]["turns"]
    assert before["form"] == "verbatim" and after["form"] == "collapsed"
    assert before["occs"][0] == after["occs"][0]


def test_cause_system_change(tmp_path):
    first = history(2, system="You are a coding agent. Today is Monday.")
    with acct_stack(tmp_path) as (fake, url, settings):
        fake.respond_counted()
        post(url, body(first))
        second = turn(first)
        second[0] = {"role": "system", "content": "You are a coding agent. Today is Tuesday."}
        fake.respond_counted()
        assert post(url, body(second)).status_code == 200

    last = events(settings)[-1]
    assert last["cause"] == "system_change"
    assert last["first_diff"]["kind"] == "head" and last["first_diff"]["segment"] == 0
    assert rows(settings, "SELECT count(*) FROM events WHERE kind = 'context_version'") == [(1,)]


def test_cause_effort_change(tmp_path):
    first = history(2)
    with acct_stack(tmp_path) as (fake, url, settings):
        fake.respond_counted()
        post(url, body(first))
        fake.respond_counted()
        assert post(url, body(turn(first), reasoning_effort="low")).status_code == 200

    last = events(settings)[-1]
    assert last["cause"] == "effort_change" and last["first_diff"]["kind"] == "head"
    assert last["settings"]["effort"] == "low"


def test_cause_tool_change(tmp_path):
    first = history(2)
    more = TOOLS + [{"type": "function", "function": {
        "name": "write", "description": "write a file",
        "parameters": {"type": "object", "properties": {}}}}]
    with acct_stack(tmp_path) as (fake, url, settings):
        fake.respond_counted()
        post(url, body(first))
        fake.respond_counted()
        assert post(url, body(turn(first), tools=more)).status_code == 200

    one, two = events(settings)
    assert two["cause"] == "tool_change" and two["tools_sha256"] != one["tools_sha256"]


# --- excerpt blocks: inclusion follows the per-message cap, which follows the budget ---

LONG_RULE = "use tabs, never spaces; " * 90  # its seeded excerpt costs ~1K tokens


def _excerpt_flow(tmp_path, *, back_up: bool):
    """A block included at n_ctx 65,536 drops out of the view when the upstream returns
    with n_ctx 20,000 (q_msg 462 < its charge) and, with ``back_up``, returns at 65,536."""
    from .test_excerpts_http import SeededExcerpts

    first = [{"role": "user", "content": LONG_RULE}]
    with acct_stack(tmp_path, excerpt_source=SeededExcerpts()) as (fake, url, settings):
        fake.respond_counted()
        assert post(url, body(first, tools=None)).status_code == 200
        second = turn(first, user="now indent it")
        fake.respond_json(b'{"error":{"message":"restarting"}}', status=503)
        assert post(url, body(second, tools=None)).status_code == 503
        fake.props_n_ctx = 20_000
        fake.respond_counted()
        assert post(url, body(second, tools=None)).status_code == 200
        if back_up:
            third = turn(second, user="and wrap it")
            fake.respond_json(b'{"error":{"message":"restarting"}}', status=503)
            assert post(url, body(third, tools=None)).status_code == 503
            fake.props_n_ctx = 65_536
            fake.respond_counted()
            assert post(url, body(third, tools=None)).status_code == 200
    return fake, settings, events(settings)


def test_cause_excerpt_omitted(tmp_path):
    fake, settings, (one, failed, shrunk) = _excerpt_flow(tmp_path, back_up=False)

    [(block, charge)] = rows(settings, "SELECT block_id, token_charge FROM excerpt_blocks"
                                       " WHERE status = 'selected' ORDER BY created_at LIMIT 1")
    assert 462 < charge <= 1920
    assert block in one["included_excerpts"] and block not in shrunk["included_excerpts"]
    assert failed["outcome"] == "upstream_status" and failed["prompt_tokens"] is None
    assert shrunk["prev_call_id"] == failed["call_id"]
    assert shrunk["cause"] == "excerpt_omitted,capacity_budget_change"
    before, after = shrunk["first_diff"]["turns"]
    assert before["excerpt"] == block and after["excerpt"] is None
    assert shrunk["budget"]["excerpt_per_message"] == 462
    assert "palimnesis excerpts" in fake.requests[0].body.decode()
    assert "palimnesis excerpts" not in fake.requests[2].body.decode()


def test_an_omitted_block_stays_omitted_when_the_budget_grows_back(tmp_path):
    # Cache audit (Phase 2): re-including an older block when the cap grew back made
    # blocks churn with the budget. Omission is monotone (D20.1, R2) and recorded.
    fake, settings, calls = _excerpt_flow(tmp_path, back_up=True)
    [(old_block,)] = rows(settings, "SELECT block_id FROM excerpt_blocks"
                                    " WHERE status = 'selected' ORDER BY created_at LIMIT 1")

    regrown = calls[-1]
    assert regrown["budget"]["excerpt_per_message"] == 1920
    assert old_block not in regrown["included_excerpts"]
    assert "excerpt_included" not in regrown["cause"]
    causes = [c for (c,) in rows(settings, "SELECT cause FROM view_versions ORDER BY n")]
    assert any("excerpt_omitted" in c for c in causes)


def explain(db, *extra):
    return subprocess.run([sys.executable, str(REPLAY), "--explain", str(db), "--json", *extra],
                          capture_output=True, text=True, timeout=60)


def test_unexplained_change_fails(tmp_path, monkeypatch):
    from palimnesis import chat, viewengine

    original = viewengine.ViewEngine.body

    def perturbed(req, plan, prepared, view):
        sent = original(req, plan, prepared, view)
        if len(view.messages) <= 4:
            return sent
        # A defect no recorded decision explains: an early message changes in transit.
        messages = [dict(m) for m in view.messages]
        messages[1]["content"] += " (silently edited)"
        return chat.render_messages(req, messages)

    monkeypatch.setattr(viewengine.ViewEngine, "body", staticmethod(perturbed))
    first = history(1)
    with acct_stack(tmp_path) as (fake, url, settings):
        fake.respond_counted()
        post(url, body(first))
        fake.respond_counted()
        assert post(url, body(turn(first))).status_code == 200

    one, two = events(settings)
    assert two["cause"] == "unexplained" and two["reuse_class"] == "unexplained"
    assert two["first_diff"]["kind"] == "user" and two["first_diff"]["segment"] == 1
    report = explain(settings.db_path)
    assert report.returncode != 0
    [pair] = json.loads(report.stdout)["pairs"]
    assert (pair["prev_call_id"], pair["call_id"]) == (one["call_id"], two["call_id"])
    assert pair["cause"] == "unexplained"


def test_explain_reports_each_consecutive_pair(tmp_path):
    messages = history(2)
    with acct_stack(tmp_path) as (fake, url, settings):
        for i in range(3):
            fake.respond_counted(cached=lambda prompt: prompt - 40)
            assert post(url, body(messages)).status_code == 200
            messages = turn(messages, user=f"next {i}")
        fake.respond_counted()
        assert post(url, body(history(1)), session="other").status_code == 200

    report = explain(settings.db_path, "--session", SID)
    assert report.returncode == 0, report.stderr
    out = json.loads(report.stdout)
    calls = events(settings)
    assert [(p["prev_call_id"], p["call_id"]) for p in out["pairs"]] == [
        (calls[0]["call_id"], calls[1]["call_id"]), (calls[1]["call_id"], calls[2]["call_id"])]
    for pair, call in zip(out["pairs"], calls[1:3]):
        assert pair == {"session": SID, "prev_call_id": call["prev_call_id"],
                        "call_id": call["call_id"], "lcp_tokens": call["lcp_tokens"],
                        "cached_tokens": call["cached_tokens"],
                        "expected_reuse_est": call["expected_reuse_est"],
                        "cause": "append", "reuse_class": call["reuse_class"]}
    classes = [c["reuse_class"] for c in calls[1:3]]
    assert out["summary"] == {"calls": 3, "pairs": 2, "unexplained": 0,
                              "classes": {k: classes.count(k) for k in set(classes)}}


def test_previous_call_rerendered_after_restart(tmp_path):
    """D14.8: after a restart the previous call's tokens come from a deterministic
    re-render of its request under its recorded view version and budget."""
    fake = FakeUpstream()
    messages = history(30)
    with serve(fake.app()) as upstream_url:
        s = Settings(upstream_base_url=upstream_url, db_path=tmp_path / "archive.db",
                     input_budget=8000)
        with serve(create_app(s), palimnesis=True) as url:
            fake.respond_counted()
            assert post(url, body(messages)).status_code == 200
        with serve(create_app(s), palimnesis=True) as url:  # a new process, same archive
            fake.respond_counted()
            assert post(url, body(turn(messages))).status_code == 200

    one, two = events(s)
    sent = [encoded(r.body) for r in fake.requests]
    assert one["view_n"] == 1 and "[palimnesis s1" in fake.requests[0].body.decode()
    assert two["lcp_source"] == "rerender" and two["prev_call_id"] == one["call_id"]
    assert two["global_prev_call_id"] is None  # nothing earlier in this process
    assert two["lcp_tokens"] == lcp(sent[0], sent[1]) >= len(sent[0]) - GEN_PROMPT_THINKING
    assert two["cause"] == "append"


def test_live_opencode_exchanges_are_explained(tmp_path):
    """The 10 live OpenCode 2.1.4 exchanges through the proxy, answered with their recorded
    Strata responses (usage included): every call pair has an allowed cause."""
    from palimnesis.capture import load_exchanges

    exchanges = load_exchanges(ROOT / "eval" / "fixtures" / "opencode-2.1.4" / "live" / "exchanges")
    with acct_stack(tmp_path) as (fake, url, settings):
        for ex in exchanges:
            fake.respond_sse([ex.response_body])
            r = post(url, ex.request_body, session=ex.session)
            assert r.status_code == 200

    calls = events(settings)
    assert [c["prompt_tokens"] for c in calls] == [5004, 5107, 5189, 5261, 5344, 9101, 10279,
                                                  10392, 10731, 10808]
    assert [c["cached_tokens"] for c in calls] == [0, 5088, 5172, 5211, 5311, 9043, 10231,
                                                  10361, 10708, 10791]
    assert all(c["input_tokens"] == c["prompt_tokens"] for c in calls)  # no drift
    assert events(settings, "count_drift") == []
    assert [c["cause"] for c in calls] == ["first_call"] + ["append"] * 9
    assert [c["reuse_class"] for c in calls[1:]] == ["full"] * 9
    report = explain(settings.db_path)
    assert report.returncode == 0, report.stdout
    assert json.loads(report.stdout)["summary"] == {"calls": 10, "pairs": 9, "unexplained": 0,
                                                    "classes": {"full": 9}}


def test_cause_capacity_budget_change(tmp_path):
    """A smaller upstream context forces a further view move; both the view version and
    the call record the budget change (D14.14)."""
    messages = history(30)
    with acct_stack(tmp_path, input_budget=16000) as (fake, url, settings):
        fake.respond_counted()
        assert post(url, body(messages)).status_code == 200
        fake.respond_json(b'{"error":{"message":"restarting"}}', status=503)
        assert post(url, body(turn(messages))).status_code == 503
        fake.props_n_ctx = 16_000  # B_in 16,000 − 8,192 − 256 = 7,552
        fake.respond_counted()
        assert post(url, body(turn(messages))).status_code == 200

    versions = rows(settings, "SELECT n, cause, json_extract(budget, '$.input_budget')"
                              " FROM view_versions ORDER BY n")
    assert [(n, b) for n, _, b in versions] == [(1, 16000), (2, 7552)]
    assert "capacity_budget_change" not in versions[0][1].split(",")
    assert "capacity_budget_change" in versions[1][1].split(",")
    last = events(settings)[-1]
    view_cause, budget_cause = last["cause"].split(",")
    assert view_cause in ("watermark_move", "collapse") and budget_cause == "capacity_budget_change"
    assert last["view_n"] == 2 and last["budget"]["input_budget"] == 7552
