"""Session commands print base URLs that route to the session they name."""

from __future__ import annotations

import subprocess
import sys

import pytest

from palimnesis.sessions import resolve_session


def _palimnesis(*args):
    out = subprocess.run(
        [sys.executable, "-m", "palimnesis", *args], capture_output=True, text=True, timeout=30
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_new_session_prints_a_fresh_valid_id_with_both_base_urls():
    first, second = _palimnesis("session", "new"), _palimnesis("session", "new")

    lines = dict(line.split(": ", 1) for line in first.strip().splitlines())
    session = lines["session"]
    assert resolve_session(session, None) == session
    assert lines["openai_base_url"] == f"http://127.0.0.1:9000/s/{session}/v1"
    assert lines["anthropic_base_url"] == f"http://127.0.0.1:9000/s/{session}"
    assert first != second


def test_resume_prints_urls_for_an_existing_session_on_a_custom_port():
    out = _palimnesis("session", "url", "proj-a", "--port", "9100")

    assert "openai_base_url: http://127.0.0.1:9100/s/proj-a/v1" in out
    assert "anthropic_base_url: http://127.0.0.1:9100/s/proj-a" in out


def test_resume_rejects_an_invalid_session_id():
    out = subprocess.run(
        [sys.executable, "-m", "palimnesis", "session", "url", "bad..id"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 2
    assert "Session identifiers" in out.stderr


def test_default_archive_path_is_under_local_app_data_on_windows(monkeypatch, tmp_path):
    from palimnesis.cli import default_db_path

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert default_db_path() == tmp_path / "palimnesis" / "palimnesis.db"


def test_default_archive_path_follows_xdg_elsewhere(monkeypatch, tmp_path):
    from palimnesis.cli import default_db_path

    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    assert default_db_path() == tmp_path / "palimnesis" / "palimnesis.db"


def test_serve_settings_default_to_archive_mode_and_passthrough_disables_it(tmp_path):
    from palimnesis.cli import serve_settings

    archive = serve_settings(["--upstream", "http://u:8080", "--db", str(tmp_path / "a.db")])
    passthrough = serve_settings(["--upstream", "http://u:8080", "--passthrough"])

    assert (archive.db_path, archive.synchronous) == (tmp_path / "a.db", "FULL")
    assert passthrough.db_path is None


def test_normal_synchronous_must_be_requested_explicitly(tmp_path):
    from palimnesis.cli import serve_settings

    s = serve_settings(["--upstream", "http://u:8080", "--db", str(tmp_path / "a.db"),
                        "--synchronous", "NORMAL"])

    assert s.synchronous == "NORMAL"


def test_capture_dir_requires_passthrough_instead_of_being_ignored(tmp_path):
    out = subprocess.run(
        [sys.executable, "-m", "palimnesis", "serve", "--upstream", "http://u:8080",
         "--db", str(tmp_path / "a.db"), "--capture-dir", str(tmp_path / "c")],
        capture_output=True, text=True, timeout=30,
    )

    assert out.returncode == 2
    assert "--capture-dir" in out.stderr and "--passthrough" in out.stderr


def test_serve_view_mode_and_input_budget_flags(tmp_path):
    from palimnesis.cli import serve_settings

    s = serve_settings(["--upstream", "http://u:8080", "--db", str(tmp_path / "a.db"),
                        "--view", "off", "--input-budget", "16000"])
    default = serve_settings(["--upstream", "http://u:8080", "--db", str(tmp_path / "a.db")])

    assert (s.view, s.input_budget) == ("off", 16000)
    assert (default.view, default.input_budget) == ("on", None)


def _archive_with_turns(tmp_path, turns=3):
    import asyncio
    import json as _json

    from palimnesis.archive import ledger
    from palimnesis.protocols.chat import parse
    from palimnesis.recall.excerpts import NoExcerpts
    from palimnesis.archive.fingerprint import fingerprint_v1
    from palimnesis.archive.store import Store

    db = tmp_path / "archive.db"

    async def build():
        store = Store.open(db)
        try:
            messages = []
            for t in range(turns):
                messages = messages + [{"role": "user", "content": f"question number {t}"}]
                req = parse(_json.dumps({"model": "m", "stream": True, "messages": messages}).encode())
                fp = fingerprint_v1(ledger.ENDPOINT_CHAT, "cli-1", ledger.branch_id_for("cli-1"),
                                    _json.loads(req.raw))
                plan = await store.write(lambda c, req=req, fp=fp: ledger.accept(
                    c, session_id="cli-1", association="path", req=req, fingerprint=fp,
                    retry_hint=None))
                selection = await NoExcerpts().select(plan, None, 0)
                await store.write(lambda c, plan=plan, selection=selection: ledger.record_excerpts(
                    c, plan, host_occ_id=plan.host_occ_id, selection=selection, rendered="",
                    token_charge=0, allocation=972, base_view_n=0, base_watermark_seq=0,
                    base_collapse_seq=0, renderer_version="x1", profile_id="test"))
                gen = ledger.Generation(plan)
                await store.write(lambda c, gen=gen, t=t: ledger.commit_batch(
                    c, gen, [("text", "text", f"answer {t}", {})], 0))
                await store.write(lambda c, gen=gen: ledger.finish_attempt(
                    c, gen, "turn_complete", finish_reason="stop"))
                messages = messages + [{"role": "assistant", "content": f"answer {t}"}]
        finally:
            store.close()

    asyncio.run(build())
    return db


def test_catalog_command_lists_every_occurrence_with_its_address(tmp_path):
    db = _archive_with_turns(tmp_path)

    out = _palimnesis("catalog", "cli-1", "--db", str(db))

    lines = [line for line in out.splitlines() if line.startswith("§")]
    assert len(lines) == 6
    assert "question number 0" in out and "answer 2" in out
    assert out.splitlines()[0].startswith("page 1")


def test_catalog_command_rejects_an_unknown_session(tmp_path):
    db = _archive_with_turns(tmp_path, turns=1)
    out = subprocess.run([sys.executable, "-m", "palimnesis", "catalog", "nope", "--db", str(db)],
                         capture_output=True, text=True, timeout=60)

    assert out.returncode == 2 and "nope" in out.stderr


def test_excerpts_command_lists_each_block(tmp_path):
    db = _archive_with_turns(tmp_path)

    out = _palimnesis("excerpts", "cli-1", "--db", str(db))

    assert out.count("status empty") == 3


def test_serve_pin_instructions_defaults_off_and_rejects_negative_values(tmp_path, capsys):
    """D65: ``--pin-instructions TOKENS``; a negative total is an error (exit 2), not a
    silently disabled pin recorded as pinned."""
    from palimnesis.cli import serve_settings

    base = ["--upstream", "http://u:8080", "--db", str(tmp_path / "a.db")]
    assert serve_settings(base).pin_tokens == 0
    assert serve_settings(base + ["--pin-instructions", "4096"]).pin_tokens == 4096
    with pytest.raises(SystemExit) as e:
        serve_settings(base + ["--pin-instructions", "-5"])
    assert e.value.code == 2


SHIPPED_D78 = dict(protect_turn=True, retrieval="r2", notes_tokens=2048, notes_format="n2",
                   notes_header="h2")
BASE_D43 = dict(protect_turn=False, retrieval="r1", notes_tokens=0, notes_format="n1",
                notes_header="h1")


def _fields(s, keys):
    return {k: getattr(s, k) for k in keys}


def test_serve_ships_the_arm_d77_froze_d78(tmp_path):
    from palimnesis.cli import serve_settings

    s = serve_settings(["--upstream", "http://u:8080", "--db", str(tmp_path / "a.db")])

    assert _fields(s, SHIPPED_D78) == SHIPPED_D78
    assert (s.recall, s.query_policy, s.excerpt_renderer, s.addendum, s.stub, s.hidden_tools,
            s.pin_tokens, s.transcripts_enabled) == ("fts", "q1", "x2", "a3", "s1", None, 0, True)


def test_serve_turns_each_d78_default_back_off(tmp_path):
    from palimnesis.cli import serve_settings

    s = serve_settings(["--upstream", "http://u:8080", "--db", str(tmp_path / "a.db"),
                        "--no-protect-turn", "--retrieval", "r1", "--notes", "0",
                        "--notes-format", "n1", "--notes-header", "h1"])

    assert _fields(s, BASE_D43) == BASE_D43
    assert serve_settings(["--upstream", "http://u:8080", "--db", str(tmp_path / "a.db"),
                           "--protect-turn"]).protect_turn is True


def test_settings_defaults_stay_the_frozen_base_d78():
    # Eval configurations that name none of these fields (a4-d43, arm 5) build Settings from
    # these defaults, so D78 moves only `serve`'s defaults (contracts §2).
    from palimnesis.config import Settings

    assert _fields(Settings(upstream_base_url="http://u:8080"), BASE_D43) == BASE_D43


def test_serve_refuses_a_negative_notes_slot(tmp_path):
    from palimnesis.cli import serve_settings

    with pytest.raises(SystemExit):
        serve_settings(["--upstream", "http://u:8080", "--db", str(tmp_path / "a.db"),
                        "--notes", "-5"])
