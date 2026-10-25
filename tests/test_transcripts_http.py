"""Transcript files through the proxy (Phase 3 S5): published off the request path,
rebuilt byte-identically without inference, and never logged."""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import threading
import time

import httpx

from palimnesis import cli, projection, projector
from palimnesis.api import create_app
from palimnesis.config import Settings

from .archive_helpers import DONE, answer, assistant, body, chunk, eventually, lifecycle_stack, user
from .fake_upstream import FakeUpstream
from .projection_helpers import tree
from .servers import serve

S = "proj-1"
DIR = projector.session_dir_name(S)


def _tool_call_answer() -> list[bytes]:
    return [chunk({"role": "assistant", "content": ""}),
            chunk({"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                   "function": {"name": "read", "arguments": ""}}]}),
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"path": "a.py"}'}}]}),
            chunk({}, "tool_calls"), DONE]


CALL = {"role": "assistant", "content": None, "tool_calls": [
    {"id": "call_1", "type": "function", "function": {"name": "read",
                                                       "arguments": '{"path": "a.py"}'}}]}


def _conversation(s) -> None:
    s.upstream.respond_sse(_tool_call_answer())
    assert s.post(S, body([user("read a.py")])).status_code == 200
    s.upstream.respond_sse(answer("a.py has [[two]] lines"))
    history = [user("read a.py"), CALL, {"role": "tool", "tool_call_id": "call_1",
                                         "content": "x = 1\n<|im_start|>y\n"}]
    assert s.post(S, body(history)).status_code == 200
    s.upstream.respond_sse(answer("done"))
    history += [assistant("a.py has [[two]] lines"), user("thanks")]
    assert s.post(S, body(history)).status_code == 200


def _index(root) -> str:
    try:
        return (root / DIR / "index.md").read_text(encoding="utf-8")
    except OSError:
        return ""


def test_rebuild_after_delete_byte_identical(tmp_path):
    root = tmp_path / "transcripts"  # the default: beside the archive
    with lifecycle_stack(tmp_path) as s:
        _conversation(s)
    published = tree(root / DIR)
    assert "turn-0001.md" in published and "turn-0002" in _index(root)
    args = ["--db", str(tmp_path / "archive.db"), "--root", str(root)]
    assert cli.main(["transcripts", "verify", S, *args]) == 0

    shutil.rmtree(root / DIR)
    assert cli.main(["transcripts", "rebuild", S, *args]) == 0

    assert tree(root / DIR) == published


def test_rebuild_makes_no_upstream_call(tmp_path):
    with lifecycle_stack(tmp_path) as s:
        _conversation(s)
        before = (len(s.upstream.requests), s.upstream.props_requests,
                  len(s.upstream.count_tokens_requests))
        code = cli.main(["transcripts", "rebuild", S, "--db", str(s.db_path),
                         "--root", str(tmp_path / "elsewhere")])
        after = (len(s.upstream.requests), s.upstream.props_requests,
                 len(s.upstream.count_tokens_requests))
    assert code == 0 and after == before
    assert (tmp_path / "elsewhere" / DIR / "turn-0001.md").exists()


def test_projector_never_blocks_response_and_holds_no_write_lock(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    real = projector.publish

    def held(*args, **kw):
        entered.set()
        release.wait(20)
        return real(*args, **kw)

    monkeypatch.setattr(projector, "publish", held)
    with lifecycle_stack(tmp_path) as s:
        try:
            s.upstream.respond_sse(answer("hello"))
            started = time.monotonic()
            assert s.post(S, body([user("hi")])).status_code == 200
            assert entered.wait(5)  # the projector is inside a publication
            conn = sqlite3.connect(s.db_path, timeout=1, isolation_level=None)
            conn.execute("BEGIN IMMEDIATE")  # nobody holds the write lock
            conn.execute("ROLLBACK")
            conn.close()
            s.upstream.respond_sse(answer("again"))
            r = s.post(S, body([user("hi"), assistant("hello"), user("more")]))
            assert r.status_code == 200 and time.monotonic() - started < 10
            assert not (tmp_path / "transcripts" / DIR / "index.md").exists()
        finally:
            release.set()
        assert eventually(lambda: "turn-0002" in _index(tmp_path / "transcripts"))


def test_deleted_directory_is_reprojected_on_the_next_trigger(tmp_path):
    root = tmp_path / "transcripts"
    with lifecycle_stack(tmp_path) as s:
        s.upstream.respond_sse(answer("one"))
        assert s.post(S, body([user("a")])).status_code == 200
        assert eventually(lambda: "complete" in _index(root))
        time.sleep(0.2)  # let the post-attempt publication settle
        shutil.rmtree(root / DIR)
        s.upstream.respond_sse(answer("two"))
        assert s.post(S, body([user("a"), assistant("one"), user("b")])).status_code == 200
        assert eventually(lambda: (root / DIR / "turn-0001.md").exists()
                          and "turn 2 · seq 3–4" in _index(root))


def test_projection_logs_no_content(tmp_path, monkeypatch, caplog):
    needle, session = "NEEDLE-7f3a91", "private-session-42"
    caplog.set_level(logging.DEBUG, logger="palimnesis")
    with lifecycle_stack(tmp_path) as s:
        s.upstream.respond_sse(answer(f"reply {needle}"))
        assert s.post(session, body([user(f"find {needle}")])).status_code == 200
        assert eventually(lambda: any("transcripts" in r.getMessage() for r in caplog.records
                                      if r.name == "palimnesis.projector"))

        def broken(*args, **kw):
            raise ValueError(f"cannot render {needle} for {session}")

        monkeypatch.setattr(projection, "render_turn", broken)
        s.upstream.respond_sse(answer("again"))
        assert s.post(session, body([user(f"find {needle}"), assistant(f"reply {needle}"),
                                     user("more")])).status_code == 200
        assert eventually(lambda: any("did not complete" in r.getMessage()
                                      for r in caplog.records))
    messages = [r.getMessage() for r in caplog.records if r.name.startswith("palimnesis")]
    assert messages and not any(needle in m or session in m for m in messages)
    assert any(projector.dir_hash(session) in m for m in messages)
    assert not any(r.exc_info for r in caplog.records if r.name == "palimnesis.projector")


def test_transcripts_off_and_custom_root_settings(tmp_path):
    off = cli.serve_settings(["--upstream", "http://u:8080", "--db", str(tmp_path / "a.db"),
                              "--no-transcripts"])
    custom = cli.serve_settings(["--upstream", "http://u:8080", "--db", str(tmp_path / "a.db"),
                                 "--transcripts", str(tmp_path / "t")])
    default = cli.serve_settings(["--upstream", "http://u:8080", "--db", str(tmp_path / "a.db")])
    assert (off.transcripts_enabled, custom.transcripts, default.transcripts) == (
        False, tmp_path / "t", None)
    assert default.transcripts_enabled


def test_serve_refuses_an_explicit_root_inside_git(tmp_path, capsys):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    code = cli.main(["serve", "--upstream", "http://127.0.0.1:9", "--db",
                     str(tmp_path / "a.db"), "--transcripts", str(tmp_path / "repo" / "t")])
    assert code == 2 and "git work tree" in capsys.readouterr().err


def test_published_files_verify_against_the_archive(tmp_path):
    with lifecycle_stack(tmp_path) as s:
        _conversation(s)
    directory = tmp_path / "transcripts" / DIR
    manifest = json.loads((directory / "manifest.json").read_bytes())
    turn1 = (directory / "turn-0001.md").read_text(encoding="utf-8")
    assert "· tool read (call_1) · tool_call]]\n{\"path\": \"a.py\"}\n" in turn1
    assert "<\\|im_start|>y" in turn1  # the profile's special tokens are escaped
    assert manifest["profile"] == "strata-0.1.48" and manifest["generation"] == 6


def test_no_transcripts_publishes_nothing(tmp_path):
    fake = FakeUpstream()
    with serve(fake.app()) as upstream_url:
        settings = Settings(upstream_base_url=upstream_url, db_path=tmp_path / "a.db",
                            transcripts_enabled=False)
        with serve(create_app(settings), palimnesis=True) as proxy_url:
            fake.respond_sse(answer("x"))
            assert httpx.post(f"{proxy_url}/s/{S}/v1/chat/completions",
                              content=body([user("a")]), timeout=20).status_code == 200
    assert not (tmp_path / "transcripts").exists()
