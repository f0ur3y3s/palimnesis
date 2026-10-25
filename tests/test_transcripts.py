"""Transcript publication at the store seam (Phase 3 S5: GL6, GL7, location, permissions).

Archives are written through ``palimnesis.ledger`` on a real store; files are published
by ``palimnesis.projector`` and checked against the plan's protocol (docs/plans/phase3.md
§3): the index only ever names complete files, a crash or a refused replace leaves the
previous generation readable, and every payload verifies against the archive.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from palimnesis import ledger, projection, projector
from palimnesis.projection import ProjectionError

from .projection_helpers import (TOKENS, Archive, call, reasoning, text, tool, tree, user,
                                 words)


def _load(db: Path, session: str = "s1", **kw) -> projector.Snapshot:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, isolation_level=None)
    try:
        conn.execute("BEGIN")
        return projector.load(conn, session, **kw)
    finally:
        conn.close()


def _publish(root: Path, db: Path, session: str = "s1", **kw) -> projector.PublishResult:
    return projector.publish(root, _load(db, session), added_tokens=TOKENS, count=words,
                             profile="test", **kw)


def _consistent(directory: Path) -> list[str]:
    """Every file the published index names exists and parses; manifest files match."""
    index = (directory / "index.md").read_text(encoding="utf-8")
    problems = []
    for name in projection.index_files(index):
        path = directory / name
        if not path.exists():
            problems.append(f"index names missing {name}")
            continue
        projection.extract(path.read_text(encoding="utf-8"), added_tokens=TOKENS,
                           read=projector.read_published(directory))
    return problems


@pytest.fixture
def archive(tmp_path):
    a = Archive(tmp_path / "archive.db")
    yield a
    a.close()


def _conversation(a: Archive) -> None:
    a.messages.append({"role": "system", "content": "you are terse"})
    a.request(user("find the bug in parse.py"),
              reply=[reasoning("look first"), call(0, "call_1", "read", '{"path": "parse.py"}')])
    a.request(tool("call_1", "def parse(x):\n    return [[x]]\n<|im_start|>"),
              reply=[text("Line 2 wraps twice.")])
    a.request(user("fix it"), reply=[text("Done.")])


def test_dir_name_case_and_device_safe():
    assert projector.session_dir_name("s1") == "s1-e8bc163c82ee"
    assert projector.session_dir_name("CON") == "con-a3dbc4b644a9"
    assert projector.session_dir_name("con.foo") == "con_foo-3295d03604b7"
    assert projector.session_dir_name("Abc") == "abc-06d90109c8cc"
    assert projector.session_dir_name("abc") == "abc-ba7816bf8f01"
    assert projector.session_dir_name("A" * 50) == "a" * 40 + "-509ddb85fdf9"
    assert projector.session_dir(Path("r"), "s1") == Path("r") / "s1-e8bc163c82ee"


def test_root_inside_git_refused(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(ProjectionError):
        projector.check_root(repo / "deep" / "transcripts")
    with pytest.raises(ProjectionError):
        projector.check_root(repo)
    projector.check_root(tmp_path / "elsewhere" / "transcripts")  # not refused


def test_publish_writes_turns_manifest_index_and_verifies(archive, tmp_path):
    _conversation(archive)
    root = tmp_path / "transcripts"

    result = _publish(root, archive.path)

    directory = root / "s1-e8bc163c82ee"
    names = sorted(tree(directory))
    assert names == ["index.md", "manifest.json", "turn-0000.md", "turn-0001.md",
                     names[4]]
    assert names[4].startswith("turn-0002.p") and names[4].endswith(".md")
    assert (result.generation, result.turns) == (7, 3)
    turn1 = (directory / "turn-0001.md").read_text(encoding="utf-8")
    assert turn1.startswith("# turn 1 · complete · seq 2–5 · palimnesis transcript t1\n")
    assert "· tool read (call_1) · tool_call]]\n{\"path\": \"parse.py\"}\n" in turn1
    assert "· tool read (call_1) · tool_result]]\n" in turn1
    assert "<\\|im_start|>" in turn1 and "· reasoning]]\nlook first\n" in turn1
    index = (directory / "index.md").read_text(encoding="utf-8")
    assert "turn-0001.md · turn 1 · seq 2–5 · 4 msgs · tools read×1 ·" in index
    assert projection.verify(projector.read_published(directory),
                             _load(archive.path).payloads(), added_tokens=TOKENS) == []
    assert all(b"\r\n" not in data for data in tree(directory).values())
    assert not any((root / ".staging").iterdir())


def test_in_progress_cancelled_abandoned_superseded_marked(archive, tmp_path):
    def status(turn: int) -> str:
        snap = _load(archive.path)
        return snap.turns[turn].status

    archive.request(user("one"), reply=[text("ok")])
    assert status(1) == "complete"
    archive.request(user("two"), end=None)
    assert status(2) == "incomplete: in progress"
    assert archive.recover() == 1
    assert status(2) == "incomplete: abandoned"
    archive.request(user("three"), reply=[text("par")], end="cancelled")
    assert status(3) == "incomplete: cancelled"
    archive.request(user("four"), reply=[text("x")], end="attempt_failed")
    assert status(3) == "incomplete: superseded"  # the resend omitted its partial
    assert status(4) == "incomplete: failed"

    root = tmp_path / "t"
    _publish(root, archive.path)
    text3 = (root / "s1-e8bc163c82ee" / "turn-0003.md").read_text(encoding="utf-8")
    assert text3.startswith("# turn 3 · incomplete: superseded · ")
    assert "· assistant · text · superseded]]\npar\n" in text3


def test_index_never_references_missing_file(archive, tmp_path):
    root = tmp_path / "t"
    directory = root / "s1-e8bc163c82ee"
    seen_partials = set()
    archive.request(user("start"), reply=[text("a")])
    for i in range(6):
        gen = archive.request(user(f"q{i}"), reply=[text(f"part {i}")], end=None)
        _publish(root, archive.path)
        assert _consistent(directory) == []
        archive._write(lambda c, gen=gen: ledger.finish_attempt(c, gen, "turn_complete",
                                                                finish_reason="stop"))
        archive.messages.append({"role": "assistant", "content": f"part {i}"})
        _publish(root, archive.path)
        assert _consistent(directory) == []
        partials = {n for n in tree(directory) if ".p" in n}
        assert len(partials) == 1  # superseded .p files are cleaned up
        seen_partials |= partials
    assert len(seen_partials) >= 6


def test_sealed_turn_files_are_write_once(archive, tmp_path):
    archive.request(user("a"), reply=[text("b")])
    archive.request(user("c"), reply=[text("d")])
    root = tmp_path / "t"
    _publish(root, archive.path)
    sealed = root / "s1-e8bc163c82ee" / "turn-0001.md"
    before = sealed.stat().st_mtime_ns, sealed.read_bytes()
    archive.request(user("e"), reply=[text("f")])
    result = _publish(root, archive.path)
    assert (sealed.stat().st_mtime_ns, sealed.read_bytes()) == before
    assert result.written == 4  # turn 2 sealed, turn 3 in progress, manifest, index


def test_index_replace_permissionerror_keeps_previous_generation(archive, tmp_path, monkeypatch):
    archive.request(user("a"), reply=[text("b")])
    root = tmp_path / "t"
    directory = root / "s1-e8bc163c82ee"
    _publish(root, archive.path)
    old_index = (directory / "index.md").read_bytes()
    archive.request(user("c"), reply=[text("d")])
    attempts = []
    real = projector._rename

    def refuse_index(src, dst):
        if Path(dst).name == "index.md":
            attempts.append(dst)
            raise PermissionError(13, "held open")
        real(src, dst)

    monkeypatch.setattr(projector, "_rename", refuse_index)
    monkeypatch.setattr(projector, "REPLACE_DELAY", 0.001)
    with pytest.raises(projector.PublishDeferred):
        _publish(root, archive.path)

    assert len(attempts) == 1 + projector.REPLACE_RETRIES
    assert (directory / "index.md").read_bytes() == old_index
    assert _consistent(directory) == []
    assert not any((root / ".staging").iterdir())
    monkeypatch.setattr(projector, "_rename", real)
    _publish(root, archive.path)
    assert "turn 2 · seq 3–4" in (directory / "index.md").read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing semantics")
def test_index_held_open_on_windows_keeps_previous_generation(archive, tmp_path, monkeypatch):
    archive.request(user("a"), reply=[text("b")])
    root = tmp_path / "t"
    directory = root / "s1-e8bc163c82ee"
    _publish(root, archive.path)
    old_index = (directory / "index.md").read_bytes()
    archive.request(user("c"), reply=[text("d")])
    monkeypatch.setattr(projector, "REPLACE_DELAY", 0.001)
    with open(directory / "index.md", "rb"):  # no FILE_SHARE_DELETE
        with pytest.raises(projector.PublishDeferred):
            _publish(root, archive.path)
    assert (directory / "index.md").read_bytes() == old_index
    assert _consistent(directory) == []


def test_staging_is_emptied_at_startup(tmp_path):
    root = tmp_path / "t"
    (root / ".staging").mkdir(parents=True)
    (root / ".staging" / "leftover.tmp").write_bytes(b"x")
    projector.prepare_root(root)
    assert list((root / ".staging").iterdir()) == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes; Windows inherits ACLs")
def test_posix_modes(archive, tmp_path):
    archive.request(user("a"), reply=[text("b" * 70000)])
    root = tmp_path / "t"
    projector.prepare_root(root)
    _publish(root, archive.path)
    for path in [root, root / ".staging", *root.rglob("*")]:
        mode = path.stat().st_mode & 0o777
        assert mode == (0o700 if path.is_dir() else 0o600), path


def test_rebuild_repairs_damaged_files_and_verify_reports_them(archive, tmp_path, capsys):
    from palimnesis import cli

    _conversation(archive)
    root = tmp_path / "t"
    args = ["--db", str(archive.path), "--root", str(root)]
    assert cli.main(["transcripts", "rebuild", "s1", *args]) == 0
    assert cli.main(["transcripts", "verify", "s1", *args]) == 0
    turn = root / "s1-e8bc163c82ee" / "turn-0001.md"
    good = turn.read_bytes()
    turn.write_bytes(good.replace(b"look first", b"look twice"))
    capsys.readouterr()

    assert cli.main(["transcripts", "verify", "s1", *args]) == 1
    out = capsys.readouterr().out
    assert "turn-0001.md does not match manifest.json" in out and "look" not in out
    assert cli.main(["transcripts", "rebuild", "s1", *args]) == 0
    assert turn.read_bytes() == good


def test_cli_refuses_a_root_inside_git(archive, tmp_path, capsys):
    from palimnesis import cli

    archive.request(user("a"), reply=[text("b")])
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    code = cli.main(["transcripts", "rebuild", "s1", "--db", str(archive.path),
                     "--root", str(tmp_path / "repo" / "t")])
    assert code == 2
    assert "git work tree" in capsys.readouterr().err


@pytest.mark.parametrize("point", projector.CRASH_POINTS)
def test_crash_at_each_publish_step_leaves_consistent_generation(archive, tmp_path, point):
    _conversation(archive)
    root = tmp_path / "t"
    args = [sys.executable, "-m", "palimnesis", "transcripts", "rebuild", "s1",
            "--db", str(archive.path), "--root", str(root)]
    env = {k: v for k, v in os.environ.items() if k != "PALIMNESIS_CRASH_AT"}
    subprocess.run(args, env=env, check=True, capture_output=True, timeout=60)
    directory = root / "s1-e8bc163c82ee"
    first_index = (directory / "index.md").read_bytes()
    archive.request(user("and then"), reply=[text("more " * 30000)])  # a linked payload

    crashed = subprocess.run(args, env={**env, "PALIMNESIS_CRASH_AT": point},
                             capture_output=True, timeout=60)

    assert crashed.returncode == 77, crashed.stderr[-2000:]
    assert _consistent(directory) == []
    index = (directory / "index.md").read_bytes()
    assert (index == first_index) == (point != "publish_after_index")
    manifest = json.loads((directory / "manifest.json").read_bytes())
    for name, meta in manifest["files"].items():
        assert (directory / name).stat().st_size == meta["size"]
    subprocess.run(args, env=env, check=True, capture_output=True, timeout=60)
    clean = tmp_path / "clean"
    subprocess.run(args[:-1] + [str(clean)], env=env, check=True, capture_output=True,
                   timeout=60)
    assert tree(directory) == tree(clean / "s1-e8bc163c82ee")
