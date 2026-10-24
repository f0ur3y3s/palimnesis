"""Session commands print base URLs that route to the session they name."""

from __future__ import annotations

import subprocess
import sys

from mnemon.sessions import resolve_session


def _mnemon(*args):
    out = subprocess.run(
        [sys.executable, "-m", "mnemon", *args], capture_output=True, text=True, timeout=30
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_new_session_prints_a_fresh_valid_id_with_both_base_urls():
    first, second = _mnemon("session", "new"), _mnemon("session", "new")

    lines = dict(line.split(": ", 1) for line in first.strip().splitlines())
    session = lines["session"]
    assert resolve_session(session, None) == session
    assert lines["openai_base_url"] == f"http://127.0.0.1:9000/s/{session}/v1"
    assert lines["anthropic_base_url"] == f"http://127.0.0.1:9000/s/{session}"
    assert first != second


def test_resume_prints_urls_for_an_existing_session_on_a_custom_port():
    out = _mnemon("session", "url", "proj-a", "--port", "9100")

    assert "openai_base_url: http://127.0.0.1:9100/s/proj-a/v1" in out
    assert "anthropic_base_url: http://127.0.0.1:9100/s/proj-a" in out


def test_resume_rejects_an_invalid_session_id():
    out = subprocess.run(
        [sys.executable, "-m", "mnemon", "session", "url", "bad..id"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 2
    assert "Session identifiers" in out.stderr
