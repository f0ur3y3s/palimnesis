"""Pi 1.5.0 through the proxy (Phase 4B S9), replaying the bodies Pi sent in the S0 probes.

The adapter (``integrations/pi/``) sets ``supportsDeveloperRole: false`` and
``supportsStore: false`` on Chat and ``allowEmptySignature: true`` on Messages (D82). With
those, Pi's requests are inside the subsets: user content as text parts (Chat, O-4B-9),
``budget_tokens`` and ``display`` (Messages, D84). Pi leaves every failed partial out of
later requests; the archive supersedes it (O-4B-5, D91).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import httpx

from palimnesis.api import create_app
from palimnesis.config import Settings

from .archive_helpers import chunk
from .fake_upstream import FakeUpstream
from .harness_replay import next_answer, pi_compat, recorded
from .servers import serve

ROOT = Path(__file__).resolve().parents[1]
PATHS = {"chat": "/v1/chat/completions", "messages": "/v1/messages"}


@contextmanager
def stack(tmp_path, **settings):
    fake = FakeUpstream()
    with serve(fake.app()) as upstream_url:
        s = Settings(upstream_base_url=upstream_url, db_path=tmp_path / "archive.db", **settings)
        with serve(create_app(s), palimnesis=True) as proxy_url:
            yield fake, proxy_url, s


def post(url: str, session: str, protocol: str, body: dict) -> httpx.Response:
    # Pi's header extension carries the session (HP2); the base URL has no /s/ prefix.
    query = "?beta=true" if protocol == "messages" else ""
    return httpx.post(f"{url}{PATHS[protocol]}{query}", timeout=60,
                      headers={"X-Palimnesis-Session": session},
                      content=json.dumps(body, ensure_ascii=False).encode())


def rows(db, sql: str):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def replay(tmp_path, run: str, protocol: str, compat=lambda b: b):
    bodies = [compat(b) for b in recorded(f"pi-1.5.0/{run}")]
    with stack(tmp_path) as (fake, url, s):
        statuses = []
        for i, body in enumerate(bodies):
            fake.respond_sse(next_answer(bodies, i))
            statuses.append(post(url, "01a1abec-4181-7000-8000-0123456789ab", protocol, body))
        return bodies, fake, s, statuses


def test_the_adapter_config_is_what_the_probes_verified():
    models = json.loads((ROOT / "integrations/pi/models.json").read_text(encoding="utf-8"))
    chat, messages = models["providers"]["palimnesis"], models["providers"]["palimnesis-messages"]
    assert chat["api"] == "openai-completions" and chat["baseUrl"].endswith("/v1")
    assert chat["compat"] == {"supportsDeveloperRole": False, "supportsStore": False}
    assert messages["api"] == "anthropic-messages" and not messages["baseUrl"].endswith("/v1")
    assert messages["compat"] == {"allowEmptySignature": True}
    settings = json.loads((ROOT / "integrations/pi/settings.json").read_text(encoding="utf-8"))
    assert settings["compaction"] == {"enabled": False}
    ext = (ROOT / "integrations/pi/extensions/palimnesis-session.ts").read_text(encoding="utf-8")
    assert 'event.headers["X-Palimnesis-Session"] = ctx.sessionManager.getSessionId()' in ext


def test_pi_chat_session_round_trip(tmp_path):
    bodies, fake, s, statuses = replay(tmp_path, "hp3_chat_compat", "chat")

    assert [r.status_code for r in statuses] == [200] * len(bodies), statuses[-1].content[:300]
    assert len(bodies) >= 3 and isinstance(bodies[0]["messages"][1]["content"], list)
    sent = json.loads(fake.requests[-1].body)
    assert sent["messages"][0]["role"] == "system"
    assert rows(s.db_path, "SELECT count(*) FROM requests")[0][0] == len(bodies)
    assert {e for (e,) in rows(s.db_path, "SELECT DISTINCT endpoint FROM requests")} == {PATHS["chat"]}


def test_pi_messages_session_round_trip(tmp_path):
    bodies, fake, s, statuses = replay(tmp_path, "hp3_messages_empty_sig_allowed", "messages")

    assert [r.status_code for r in statuses] == [200] * len(bodies), statuses[-1].content[:300]
    assert bodies[0]["thinking"] == {"type": "enabled", "budget_tokens": 7168, "display": "summarized"}
    sent = json.loads(fake.requests[-1].body)
    assert sent["reasoning_effort"] == "medium"  # 7168 < 8192 (D84)
    assert any(m.get("tool_calls") for m in sent["messages"])
    assert rows(s.db_path, "SELECT count(*) FROM requests")[0][0] == len(bodies)


def test_pi_retry_after_partial_policy(tmp_path):
    """HP4.3: turn 1 fails after streaming; Pi does not retry (the proxy's error wording
    matches none of its retry patterns) and sends turn 2 without the partial."""
    bodies = [pi_compat(b) for b in recorded("pi-1.5.0/hp4_partial_error_then_ok_chat_retryoff")]
    with stack(tmp_path) as (fake, url, s):
        fake.respond_sse([chunk({"role": "assistant", "content": ""}),
                          chunk({"reasoning_content": "Thinking"}), chunk({"content": "Partial"})])
        first = post(url, "pi-partial", "chat", bodies[0])
        fake.respond_sse(next_answer(bodies, 1))
        second = post(url, "pi-partial", "chat", bodies[1])
        superseded = rows(s.db_path, "SELECT count(*) FROM events WHERE kind = 'partial_superseded'")

    assert first.status_code == 200 and b"upstream_stream_failed" in first.content
    assert second.status_code == 200, second.content[:300]
    assert [m["role"] for m in bodies[1]["messages"]] == ["system", "user", "user"]
    assert superseded[0][0] == 1  # the failed partial stays archived, superseded
    occ = rows(s.db_path, "SELECT role, source FROM occurrences ORDER BY seq")
    assert occ[:3] == [("system", "client"), ("user", "client"), ("assistant", "generated")]
    assert ("user", "client") in occ[3:]
