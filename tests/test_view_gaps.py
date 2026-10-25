"""Phase 2 gap tests (delta slice F): startup floor, n_ctx changes, a client-free builder.

- §2 floor (contracts §2; D14.9): when bounded views cannot fit even an empty
  conversation plus the minimum recent window, the generation reserve and the margin,
  the proxy runs view-disabled (archive and forward) and says which terms failed.
- §2 capacity change: facts marked stale by a 5xx are re-read before the next build, so
  the next budget uses the new ``n_ctx``; a request already admitted keeps its body.
- GL5: ``view.build`` takes no client and opens no socket; the proxy makes exactly one
  upstream chat POST per client request even when it masks.
- GL2 groups: an assistant message with tool calls and its tool results stay together.
"""

from __future__ import annotations

import inspect
import json
import logging
import random
import socket
import threading
import time

import httpx
import pytest

from palimnesis.api import create_app
from palimnesis.budget import BudgetError, BudgetPolicy, plan_budget
from palimnesis.config import Settings
from palimnesis.upstreams.strata import tokens
from palimnesis.view import ViewItem, ViewPolicy, ViewState, build

from .fake_upstream import FakeUpstream
from .servers import serve
from .test_view_http import DONE, SID, body, history, post, rows, upstream_tokens, view_stack

LIMIT = 8192  # the client's own output limit, so the body is not rewritten


def _wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.01)


# --- §2 startup floor -----------------------------------------------------------------


def test_startup_floor_failure_names_terms_view_disabled(tmp_path, caplog):
    # 12,000 tokens cannot hold the 4,096-token recent window plus the 8,192 reserve
    # and the 256 margin, so bounded views must not run at all.
    fake = FakeUpstream()
    fake.props_n_ctx = 12_000
    caplog.set_level(logging.WARNING, logger="palimnesis")
    with serve(fake.app()) as upstream_url:
        s = Settings(upstream_base_url=upstream_url, db_path=tmp_path / "a.db")
        with serve(create_app(s), palimnesis=True) as url:
            data = body(history(30), max_completion_tokens=LIMIT)
            fake.respond_sse([DONE])
            assert post(url, data).status_code == 200

    # forwarded unbounded, as in Phase 1, and still archived
    assert fake.requests[-1].body == data
    assert rows(s, "SELECT count(*) FROM requests") == [(1,)]
    floor_logs = [r.getMessage() for r in caplog.records if "floor" in r.getMessage()]
    assert floor_logs, [r.getMessage() for r in caplog.records]
    text = " ".join(floor_logs)
    for term in ("fixed_min", "min_recent", "reserve", "margin", "n_ctx"):
        assert term in text
    assert "12000" in text and "4096" in text and "8192" in text


def test_floor_recomputed_when_n_ctx_grows_enables_views(tmp_path):
    # Starting below the floor, a 5xx makes the facts stale; the re-read n_ctx clears it.
    fake = FakeUpstream()
    fake.props_n_ctx = 12_000
    with serve(fake.app()) as upstream_url:
        s = Settings(upstream_base_url=upstream_url, db_path=tmp_path / "a.db", input_budget=8000)
        with serve(create_app(s), palimnesis=True) as url:
            data = body(history(30), max_completion_tokens=LIMIT)
            fake.respond_json(b'{"error":{"message":"busy"}}', status=503)
            assert post(url, data).status_code == 503
            fake.props_n_ctx = 65_536
            fake.respond_sse([DONE])
            assert post(url, data).status_code == 200

    assert fake.requests[0].body == data  # view-disabled below the floor
    assert upstream_tokens(fake.requests[1].body) <= 8000  # bounded once it fits


# --- §2 capacity change -----------------------------------------------------------------


def _input_budget(n_ctx: int) -> int:
    return plan_budget(n_ctx, client_limit=LIMIT, policy=BudgetPolicy()).input_budget


def test_n_ctx_change_recomputed_before_next_call(tmp_path):
    small = 20_000
    with view_stack(tmp_path) as (fake, url, _):
        data = body(history(15), max_completion_tokens=LIMIT)
        assert _input_budget(small) < upstream_tokens(data) < 0.9 * _input_budget(65_536)
        fake.respond_json(b'{"error":{"message":"restarting"}}', status=503)
        assert post(url, data).status_code == 503
        fake.props_n_ctx = small  # the upstream came back with a smaller context
        fake.respond_sse([DONE])
        assert post(url, data).status_code == 200

    first, second = (r.body for r in fake.requests)
    assert first == data  # fits under the old n_ctx, unchanged
    assert upstream_tokens(second) <= _input_budget(small)
    assert "[palimnesis s1" in second.decode()


def test_in_flight_keeps_admitted_budget(tmp_path):
    small = 20_000
    slow = [(0.0, b'data: {"choices":[{"index":0,"delta":{"content":"o"}}]}\n\n'),
            (1.0, DONE)]
    with view_stack(tmp_path) as (fake, url, _):
        data = body(history(15), max_completion_tokens=LIMIT)
        fake.respond_sse(slow)
        result = {}

        def run_slow():
            result["status"] = post(url, data).status_code

        t = threading.Thread(target=run_slow)
        t.start()
        _wait_for(lambda: len(fake.requests) == 1)
        # Mid-flight: another session sees a 5xx and the upstream's n_ctx shrinks.
        fake.props_n_ctx = small
        other = f"{url}/s/{SID}-other/v1/chat/completions"
        fake.respond_json(b'{"error":{"message":"restarting"}}', status=503)
        assert httpx.post(other, content=body([{"role": "user", "content": "hi"}]),
                          timeout=30).status_code == 503
        fake.respond_sse([DONE])
        third = f"{url}/s/{SID}-third/v1/chat/completions"
        with httpx.stream("POST", third, content=data, timeout=60) as r:
            r.read()
        assert r.status_code == 200
        t.join(timeout=30)

    assert result["status"] == 200
    assert fake.completed_streams.count("/v1/chat/completions") == 2
    admitted, _, after = (r.body for r in fake.requests)
    assert admitted == data  # admitted under the old n_ctx and relayed to completion
    assert upstream_tokens(after) <= _input_budget(small) < upstream_tokens(admitted)


# --- GL5: the builder makes no upstream calls ----------------------------------------------

TOOLS = [{"type": "function", "function": {"name": "read", "description": "read a file",
                                           "parameters": {"type": "object", "properties": {
                                               "path": {"type": "string"}}}}}]


@pytest.fixture(scope="module")
def counter():
    return tokens.default()


class Session:
    def __init__(self):
        self.items: list[ViewItem] = []

    def add(self, message: dict) -> "Session":
        seq = len(self.items) + 1
        self.items.append(ViewItem(message=message, occ_id=f"occ{seq}", seq=seq,
                                   alias=f"{seq:06d}"))
        return self

    def tool_turn(self, ids, outputs, reasoning=""):
        calls = [{"id": cid, "type": "function",
                  "function": {"name": "read", "arguments": json.dumps({"path": f"{cid}.py"})}}
                 for cid in ids]
        self.add({"role": "assistant", "content": None, "reasoning_content": reasoning,
                  "tool_calls": calls})
        for cid, out in zip(ids, outputs):
            self.add({"role": "tool", "tool_call_id": cid, "content": out})
        return self


def _code(tag, lines):
    return "\n".join(f"def f{tag}_{n}(x):\n    return x * {n}  # line {n}" for n in range(lines))


@pytest.fixture
def no_sockets(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("the view builder opened a socket")

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)


def test_builder_signature_has_no_client(counter, no_sockets):
    params = inspect.signature(build).parameters
    assert not any("client" in name or "http" in name for name in params)

    s = Session().add({"role": "system", "content": "You are a coding agent."})
    s.add({"role": "user", "content": "refactor everything"})
    for i in range(40):
        s.tool_turn([f"c{i}"], [_code(i, 120)], reasoning="I should read the next file. " * 20)
    s.add({"role": "user", "content": "now summarize"})
    budget = plan_budget(32_768, client_limit=LIMIT, policy=BudgetPolicy(input_cap=16_000))

    view = build(s.items, tools=TOOLS, render_kwargs={}, budget=budget, state=ViewState(),
                 policy=ViewPolicy(), counter=counter)

    assert view.moved and view.tokens <= budget.input_budget
    assert any(form != "verbatim" for _, form in view.manifest)


def test_one_upstream_chat_post_per_client_request_when_masking(tmp_path):
    with view_stack(tmp_path, input_budget=8000) as (fake, url, settings):
        messages = history(30)
        sent = 0
        for turn in range(3):
            fake.respond_sse([DONE])
            assert post(url, body(messages, max_completion_tokens=LIMIT)).status_code == 200
            sent += 1
            # the client resends the generated answer and asks again
            messages = messages + [{"role": "assistant", "content": "ok"},
                                   {"role": "user", "content": f"next {turn} " * 200}]

    chat_posts = [r for r in fake.requests
                  if r.method == "POST" and r.path == "/v1/chat/completions"]
    assert len(fake.requests) == len(chat_posts) == sent
    assert all("[palimnesis s1" in r.body.decode() for r in chat_posts)
    assert rows(settings, "SELECT count(*) FROM view_versions")[0][0] >= 1


# --- GL2: tool groups never split ------------------------------------------------------------


def _random_session(rng: random.Random) -> list[Session]:
    """Growing snapshots of one random session, each ending in a user message."""
    s = Session().add({"role": "system", "content": "You are a coding agent."})
    s.add({"role": "user", "content": "start the task"})
    snapshots = []
    call = 0
    for turn in range(rng.randint(30, 50)):
        r = rng.random()
        if r < 0.6:
            n = rng.choice([1, 1, 2, 3])
            ids = [f"t{turn}_{k}" for k in range(n)]
            call += n
            outputs = [rng.choice(["ok", "done.", _code(f"{turn}_{k}", rng.randint(1, 8)),
                                   _code(f"{turn}_{k}", rng.randint(30, 250))])
                       for k in range(n)]
            reasoning = rng.choice(["", "Think. " * rng.randint(1, 120)])
            s.tool_turn(ids, outputs, reasoning)
        elif r < 0.8:
            s.add({"role": "assistant", "content": "progress " * rng.randint(1, 60)})
        else:
            s.add({"role": "user", "content": "continue " * rng.randint(1, 30)})
        if rng.random() < 0.3 or turn % 6 == 5:
            snap = Session()
            snap.items = list(s.items) + [ViewItem(
                message={"role": "user", "content": f"go on {turn}"}, occ_id=f"cur{turn}",
                seq=len(s.items) + 1, alias=f"{len(s.items) + 1:06d}")]
            snapshots.append(snap)
    return snapshots


def _assert_groups_whole(messages: list[dict]) -> None:
    for i, m in enumerate(messages):
        if m.get("role") == "tool":
            j = i - 1
            while j >= 0 and messages[j].get("role") == "tool":
                j -= 1
            assert j >= 0 and messages[j].get("role") == "assistant", (i, m)
            ids = {c["id"] for c in messages[j].get("tool_calls") or []}
            assert m["tool_call_id"] in ids, (i, m["tool_call_id"], ids)
        if m.get("role") == "assistant" and m.get("tool_calls"):
            ids = [c["id"] for c in m["tool_calls"]]
            following = []
            for n in messages[i + 1:]:
                if n.get("role") != "tool":
                    break
                following.append(n["tool_call_id"])
            assert following == ids, (i, ids, following)


@pytest.mark.parametrize("seed", range(8))
def test_tool_groups_never_split_property(counter, seed):
    rng = random.Random(seed)
    budget = plan_budget(rng.choice([24_576, 32_768]), client_limit=LIMIT,
                         policy=BudgetPolicy(input_cap=rng.choice([5_000, 8_000, 12_000])))
    state = ViewState()
    forms = set()
    for snap in _random_session(rng):
        try:
            view = build(snap.items, tools=TOOLS, render_kwargs={}, budget=budget, state=state,
                         policy=ViewPolicy(), counter=counter)
        except BudgetError:
            continue
        _assert_groups_whole(view.messages)
        assert view.tokens <= budget.input_budget
        forms |= {form for _, form in view.manifest}
        state = view.state
    assert "stub" in forms or "collapsed" in forms  # the property was exercised under masking
