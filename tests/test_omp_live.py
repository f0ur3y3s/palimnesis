"""Opt-in OMP smoke test; run with PALIMNESIS_TEST_OMP=1 and OMP installed."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from palimnesis.api import create_app
from palimnesis.cli import main
from palimnesis.config import Settings

from .fake_upstream import FakeUpstream
from .servers import serve


@pytest.mark.skipif(os.environ.get("PALIMNESIS_TEST_OMP") != "1", reason="requires installed OMP")
def test_omp_print_routes_to_its_own_session(tmp_path: Path):
    fake = FakeUpstream()
    fake.respond_counted("hello from proxy")
    fake.respond_counted("second session")
    with serve(fake.app()) as upstream:
        settings = Settings(upstream_base_url=upstream, db_path=tmp_path / "archive.db")
        with serve(create_app(settings), palimnesis=True) as proxy:
            port = proxy.rsplit(":", 1)[1]
            agent_dir = tmp_path / "omp-agent"
            assert main(["setup", "omp", "--model", "qwen3.8-flash-next-iq3_xxs",
                         "--agent-dir", str(agent_dir), "--port", port]) == 0
            env = os.environ.copy()
            env["PI_CODING_AGENT_DIR"] = str(agent_dir)
            run = subprocess.run(
                ["omp", "--print", "--model", "palimnesis/qwen3.8-flash-next-iq3_xxs",
                 "Say hello."], env=env, capture_output=True, text=True, timeout=90,
            )
            second = subprocess.run(
                ["omp", "--print", "--model", "palimnesis/qwen3.8-flash-next-iq3_xxs",
                 "Say hello again."], env=env, capture_output=True, text=True, timeout=90,
            )
    assert run.returncode == 0, run.stderr
    assert second.returncode == 0, second.stderr
    assert "hello from proxy" in run.stdout
    assert "second session" in second.stdout
    assert len(fake.requests) == 2
    assert fake.requests[0].path == "/v1/chat/completions"
    with sqlite3.connect(tmp_path / "archive.db") as db:
        sessions = db.execute("select session_id from sessions").fetchall()
    assert len(sessions) == 2
