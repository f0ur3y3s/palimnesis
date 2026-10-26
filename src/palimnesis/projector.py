"""Publishing transcript files: archive reader, crash-safe publisher, background Projector.

Protocol plumbing around ``palimnesis.projection`` (which names the mechanism and its
source). Contracts §14 (proposed); docs/plans/phase3.md §3.

**Location.** One directory per session under a root (default ``<db dir>/transcripts``),
named ``safe(id[:40]).lower() + "-" + sha256(id)[:12]``: session ids may differ only in
case or be Windows device names (D4), and ``safe`` maps everything outside
``[A-Za-z0-9_-]`` (dots included, so no device stem or trailing dot) to ``_``. An explicit
root inside a git work tree is refused; a default root inside one turns projection off
with a warning (D32). Transcripts never land in a project repository.
POSIX modes are 0700 for directories and 0600 for files; on Windows files inherit the
root's ACL (per-user under ``%LOCALAPPDATA%``).

**Publication.** Every file is written to ``<root>/.staging`` (same volume, outside
every session directory, emptied when the Projector starts), fsynced, then moved with
``os.replace``, in this order:

1. write-once files: sealed turns, the in-progress turn under a new ``.pKKKK`` name,
   linked payloads (existing ones are never rewritten, except by an explicit repair);
2. ``manifest.json``;
3. ``index.md``;

then superseded ``.p`` files are deleted, best effort. The index therefore only names
files that were complete before it moved. Replacing ``manifest.json`` or ``index.md``
retries a ``PermissionError`` (Windows: a reader holding the file without
``FILE_SHARE_DELETE``) 3 times, 50 ms apart; after that the previous generation stays
published and the next trigger tries again. ``PALIMNESIS_CRASH_AT`` names
``publish_staged``, ``publish_after_files``, ``publish_after_manifest`` and
``publish_after_index`` for crash tests.

**Scheduling.** ``Projector`` is one daemon thread with its own read-only SQLite
connection. ``trigger(session)`` is non-blocking and coalesces: a session already
pending is published once, from the newest archive state (the D25 pattern). It holds
no write lock, makes no upstream call, and logs counts and directory hashes only,
never content or session ids.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from . import ledger, projection
from .projection import Block, Message, Payload, ProjectionError, Summary, Turn
from .turns import turn_numbers

log = logging.getLogger(__name__)

STAGING = ".staging"
REPLACE_RETRIES = 3
REPLACE_DELAY = 0.05
CRASH_POINTS = ("publish_staged", "publish_after_files", "publish_after_manifest",
                "publish_after_index")
_TERMINAL = {"turn_complete": "complete", "cancelled": "incomplete: cancelled",
             "attempt_abandoned": "incomplete: abandoned",
             "attempt_failed": "incomplete: failed"}
_POSIX = sys.platform != "win32"
_REVISIONED = re.compile(r"^(turn-\d{4,}\.p\d{4,}\.md|payloads/.+\.p\d{4,}\.(txt|bin))$")
# Paths a session directory may contain; anything else read through it is refused.
PUBLISHED_PATH = re.compile(
    r"^(manifest\.json|index\.md|turn-\d{4,}(\.p\d{4,})?\.md"
    r"|payloads/[0-9A-Za-z_.:-]+\.\d+(\.p\d{4,})?\.(txt|bin))$")


def _crash_point(name: str) -> None:
    from .archive import crash_point

    crash_point(name)


# --- location ----------------------------------------------------------------


def dir_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]


def session_dir_name(session_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id[:40])
    return f"{safe.lower()}-{dir_hash(session_id)}"


def session_dir(root: Path | str, session_id: str) -> Path:
    """The one directory a harness is pointed at for this session (never the root)."""
    return Path(root) / session_dir_name(session_id)


def default_root(db_path: Path | str) -> Path:
    return Path(db_path).parent / "transcripts"


def git_work_tree(path: Path | str) -> Path | None:
    """The git work tree containing ``path`` (existing or not), if any."""
    p = Path(os.path.abspath(path))
    for candidate in (p, *p.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def check_root(root: Path | str) -> None:
    if git_work_tree(root) is not None:
        raise ProjectionError("the transcripts root is inside a git work tree; transcripts "
                              "must stay outside project repositories")


def _mkdir(path: Path) -> None:
    created = not path.exists()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if _POSIX and created:
        os.chmod(path, 0o700)


def prepare_root(root: Path | str, *, empty_staging: bool = True) -> None:
    """Create the root and its staging directory; empty staging (Projector startup)."""
    root = Path(root)
    _mkdir(root)
    staging = root / STAGING
    if empty_staging and staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    _mkdir(staging)


# --- reading the archive -----------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    """A branch's turns at one consistent archive state."""

    session_id: str
    generation: int  # the cutoff seq
    numbers: tuple[int, ...]  # every turn, in order
    turns: Mapping[int, Turn]  # the turns loaded (all but the reused sealed ones)

    def payloads(self) -> dict[str, bytes]:
        return {f"{m.alias}.{b.idx}": b.data for t in self.turns.values()
                for m in t.messages for b in m.blocks}


def load(conn: sqlite3.Connection, session_id: str, *, max_seq: int | None = None,
         reuse: Iterable[int] = ()) -> Snapshot:
    """Read one session's main branch. Sealed turns in ``reuse`` are not loaded (their
    published files are known to be current). Run inside one read transaction."""
    branch = ledger.branch_id_for(session_id)
    if conn.execute("SELECT 1 FROM branches WHERE branch_id = ?", (branch,)).fetchone() is None:
        raise ProjectionError("unknown session")
    cutoff = max_seq if max_seq is not None else 2**62
    occs = conn.execute(
        "SELECT o.occ_id, o.seq, o.role, o.source, o.view, o.request_id, o.generation_id,"
        " json_extract(o.envelope, '$.supersedes'), a.alias FROM occurrences o"
        " LEFT JOIN aliases a ON a.target_id = o.occ_id"
        " WHERE o.branch_id = ? AND o.seq <= ? ORDER BY o.seq", (branch, cutoff)).fetchall()
    firsts: dict[int, str] = {}
    for seq, head in conn.execute(
            "SELECT o.seq, substr(s.bytes, 1, 512) FROM occurrences o"
            " JOIN blocks b ON b.occ_id = o.occ_id"
            " JOIN segments s ON s.block_id = b.block_id AND s.seq = 0"
            " WHERE o.branch_id = ? AND o.seq <= ? AND o.role = 'user' AND b.kind = 'text'"
            " ORDER BY o.seq, b.idx", (branch, cutoff)):
        firsts.setdefault(seq, bytes(head).decode("utf-8", "ignore"))
    number_of = turn_numbers([(o[1], o[2]) for o in occs], firsts)
    numbers = tuple(sorted(set(number_of.values())))
    last = numbers[-1] if numbers else None
    reuse = {n for n in reuse if n != last}

    by_occ = {o[0]: o for o in occs}
    seq_of = {o[0]: o[1] for o in occs}
    alias_of = {o[0]: o[8] or "?" for o in occs}
    request_turn: dict[str, int] = {}
    for o in occs:
        if o[5] is not None:
            request_turn[o[5]] = number_of[o[1]]  # ordered by seq: the max wins
    for request_id, parent in conn.execute(
            "SELECT request_id, visible_parent_occ FROM requests WHERE branch_id = ?", (branch,)):
        if request_id not in request_turn and (parent is None or parent in seq_of):
            request_turn[request_id] = number_of[seq_of[parent]] if parent else 0
    attempts = [(rowid, attempt, request) for rowid, attempt, request in conn.execute(
        "SELECT a.rowid, a.attempt_id, a.request_id FROM attempts a"
        " JOIN requests r ON r.request_id = a.request_id WHERE r.branch_id = ?"
        " ORDER BY a.rowid", (branch,)) if request in request_turn]
    terminal: dict[str, str] = {}
    superseded: set[str] = set()
    for attempt, kind, target in conn.execute(
            "SELECT e.attempt_id, e.kind, json_extract(e.payload, '$.occ_id') FROM events e"
            " JOIN requests r ON r.request_id = e.request_id WHERE r.branch_id = ?"
            " AND e.kind IN ('turn_complete', 'cancelled', 'attempt_abandoned',"
            " 'attempt_failed', 'partial_superseded') ORDER BY e.event_id", (branch,)):
        if kind == "partial_superseded":
            superseded.add(target)
        elif attempt is not None:
            terminal.setdefault(attempt, kind)
    attempt_of_generation = dict(conn.execute(
        "SELECT g.generation_id, g.attempt_id FROM generations g"
        " JOIN attempts a ON a.attempt_id = g.attempt_id"
        " JOIN requests r ON r.request_id = a.request_id WHERE r.branch_id = ?", (branch,)))
    occ_of_attempt = {attempt_of_generation.get(o[6]): o[0] for o in occs if o[6]}
    call_names: dict[str, str] = {}
    for (meta,) in conn.execute(
            "SELECT b.meta FROM blocks b JOIN occurrences o ON o.occ_id = b.occ_id"
            " WHERE o.branch_id = ? AND o.seq <= ? AND b.kind = 'tool_call'", (branch, cutoff)):
        meta = json.loads(meta)
        if meta.get("id") is not None:
            call_names.setdefault(meta["id"], meta.get("name"))

    wanted = [o for o in occs if number_of[o[1]] not in reuse]
    blocks: dict[str, list] = {}
    if wanted:
        current: dict[str, list] = {}
        for occ_id, block_id, idx, kind, meta, data in conn.execute(
                "SELECT b.occ_id, b.block_id, b.idx, b.kind, b.meta, s.bytes FROM blocks b"
                " JOIN occurrences o ON o.occ_id = b.occ_id"
                " LEFT JOIN segments s ON s.block_id = b.block_id"
                " WHERE o.branch_id = ? AND o.seq BETWEEN ? AND ?"
                " ORDER BY o.seq, b.idx, s.seq", (branch, wanted[0][1], wanted[-1][1])):
            if block_id not in current:
                current[block_id] = [idx, kind, json.loads(meta), [], 0]
                blocks.setdefault(occ_id, []).append(current[block_id])
            if data is not None:
                current[block_id][3].append(bytes(data))
                current[block_id][4] += 1

    turns: dict[int, Turn] = {}
    grouped: dict[int, list] = {}
    for o in wanted:
        grouped.setdefault(number_of[o[1]], []).append(o)
    attempts_by_turn: dict[int, list] = {}
    for rowid, attempt, request in attempts:
        attempts_by_turn.setdefault(request_turn[request], []).append(attempt)
    for n, rows in grouped.items():
        messages = []
        revision = 0
        for occ_id, seq, role, source, view, _req, generation_id, supersedes, _alias in rows:
            attempt = attempt_of_generation.get(generation_id) if generation_id else None
            final = source != "generated" or attempt in terminal
            out_blocks = []
            for idx, kind, meta, parts, nseg in blocks.get(occ_id, []):
                call_id = meta.get("id") if kind == "tool_call" else meta.get("tool_call_id")
                tool = meta.get("name") if kind == "tool_call" else call_names.get(call_id)
                if kind not in ("tool_call", "tool_result"):
                    call_id = tool = None
                out_blocks.append(Block(idx, kind, b"".join(parts), tool=tool, call_id=call_id,
                                        final=final))
                revision += 1 + nseg
            flags = []
            if supersedes:
                flags.append(f"replaces §{alias_of.get(supersedes, '?')}")
            if occ_id in superseded:
                flags.append("superseded")
                revision += 1
            if source == "client_import":
                flags.append("imported")
            if view == "internal":
                flags.append("internal")
            messages.append(Message(seq, alias_of[occ_id], role, tuple(out_blocks), tuple(flags)))
            revision += 1
        turn_attempts = attempts_by_turn.get(n, [])
        revision += len(turn_attempts) + sum(a in terminal for a in turn_attempts)
        turns[n] = Turn(n, tuple(messages), _status(turn_attempts, terminal, occ_of_attempt,
                                                    superseded),
                        sealed=n != last, revision=revision)
    generation = occs[-1][1] if occs else 0
    return Snapshot(session_id, generation, numbers, turns)


def _status(attempts: Sequence[str], terminal: Mapping[str, str],
            occ_of_attempt: Mapping[str, str], superseded: set[str]) -> str:
    if not attempts:
        return "complete"  # imported history: no attempt of this proxy's
    latest = attempts[-1]
    if occ_of_attempt.get(latest) in superseded:
        return "incomplete: superseded"
    kind = terminal.get(latest)
    return "incomplete: in progress" if kind is None else _TERMINAL[kind]


# --- publishing --------------------------------------------------------------


@dataclass(frozen=True)
class Published:
    """One turn as published: what the manifest and index need to republish it."""

    number: int
    name: str
    revision: int
    files: dict[str, tuple[str, int]]  # path -> (sha256, size), the turn file included
    payloads: tuple[Payload, ...]
    summary: Summary


@dataclass(frozen=True)
class PublishResult:
    generation: int
    revision: int
    turns: int
    written: int
    bytes_written: int


class PublishDeferred(ProjectionError):
    """manifest.json or index.md could not be replaced; the previous generation stands."""


def _rename(src: str, dst: str) -> None:
    os.replace(src, dst)


def _fsync_dir(path: Path) -> None:
    if not _POSIX:
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class _Writer:
    def __init__(self, root: Path, directory: Path) -> None:
        self.staging = root / STAGING
        self.directory = directory
        self.written = 0
        self.bytes = 0
        self._staged = False

    def _stage(self, data: bytes) -> str:
        _mkdir(self.staging)
        fd, tmp = tempfile.mkstemp(dir=self.staging, prefix=self.directory.name + ".",
                                   suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:  # bytes: LF stays LF on every platform
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            if _POSIX:
                os.chmod(tmp, 0o600)
        except BaseException:
            _unlink(tmp)
            raise
        if not self._staged:
            self._staged = True
            _crash_point("publish_staged")
        return tmp

    def put(self, rel: str, data: bytes, *, retry: bool) -> bool:
        target = self.directory / rel
        _mkdir(target.parent)
        tmp = self._stage(data)
        attempts = REPLACE_RETRIES + 1 if retry else 1
        for attempt in range(attempts):
            try:
                _rename(tmp, str(target))
                break
            except PermissionError:
                if attempt == attempts - 1:
                    _unlink(tmp)
                    raise PublishDeferred(f"{rel} is held open; the previous generation stays")
                time.sleep(REPLACE_DELAY)
            except BaseException:
                _unlink(tmp)
                raise
        _fsync_dir(target.parent)
        self.written += 1
        self.bytes += len(data)
        return True

    def write_once(self, rel: str, data: bytes, *, repair: bool) -> None:
        target = self.directory / rel
        if target.exists() and (not repair or target.read_bytes() == data):
            return
        self.put(rel, data, retry=True)

    def replace(self, rel: str, data: bytes) -> None:
        target = self.directory / rel
        try:
            if target.read_bytes() == data:
                return
        except OSError:
            pass
        self.put(rel, data, retry=True)


def _unlink(path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def publish(root: Path | str, snapshot: Snapshot, *, added_tokens: Sequence[str],
            count: Callable[[str], int], profile: str,
            cache: dict[int, Published] | None = None, repair: bool = False) -> PublishResult:
    """Publish one snapshot into its session directory (see the module docstring).

    ``cache`` holds sealed turns already published (it is updated); a turn missing from
    ``snapshot.turns`` must be in it. ``repair`` rewrites write-once files whose bytes
    differ (``transcripts rebuild``)."""
    root = Path(root)
    directory = session_dir(root, snapshot.session_id)
    _mkdir(directory)
    cache = {} if cache is None else cache
    writer = _Writer(root, directory)
    published: list[Published] = []
    for n in snapshot.numbers:
        turn = snapshot.turns.get(n)
        if turn is None:
            published.append(cache[n])
            continue
        rendered = projection.render_turn(turn, added_tokens=added_tokens, count=count)
        for path, blob in sorted(rendered.files.items()):
            writer.write_once(path, blob, repair=repair)
        writer.write_once(rendered.name, rendered.data, repair=repair)
        files = projection.file_meta(rendered)
        meta = Published(n, rendered.name, turn.revision, files, rendered.payloads,
                         rendered.summary)
        if turn.sealed:
            cache[n] = meta
        published.append(meta)
    _crash_point("publish_after_files")
    revision = sum(p.revision for p in published)
    writer.replace("manifest.json", projection.manifest(
        {path: meta for p in published for path, meta in p.files.items()},
        [pl for p in published for pl in p.payloads], generation=snapshot.generation,
        revision=revision, branch="main", profile=profile))
    _crash_point("publish_after_manifest")
    index = projection.render_index([p.summary for p in published],
                                    generation=snapshot.generation, revision=revision,
                                    count=count)
    writer.replace("index.md", index.encode("utf-8"))
    _crash_point("publish_after_index")
    keep = {path for p in published for path in p.files}
    for path in directory.rglob("*"):
        rel = path.relative_to(directory).as_posix()
        if path.is_file() and _REVISIONED.match(rel) and rel not in keep:
            _unlink(path)
    return PublishResult(snapshot.generation, revision, len(published), writer.written,
                         writer.bytes)


def read_published(directory: Path) -> Callable[[str], bytes]:
    """A reader for ``projection.verify`` confined to a session directory's own files."""
    def read(rel: str) -> bytes:
        if not PUBLISHED_PATH.match(rel):
            raise OSError(f"not a transcript path: {rel!r}")
        return (directory / rel).read_bytes()
    return read


# --- background worker -------------------------------------------------------


def _connect_read_only(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True,
                           isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@dataclass
class Projector:
    """One background thread that keeps each session's transcript files current."""

    db_path: Path
    root: Path
    added_tokens: tuple[str, ...]
    count: Callable[[str], int]
    profile: str
    published: int = 0
    failures: int = 0
    _pending: dict[str, None] = field(default_factory=dict)
    _cond: threading.Condition = field(default_factory=threading.Condition)
    _stop: bool = False
    _thread: threading.Thread | None = None
    _cache: dict[str, dict[int, Published]] = field(default_factory=dict)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._work, name="palimnesis-projector",
                                        daemon=True)
        self._thread.start()

    def trigger(self, session_id: str) -> None:
        """Ask for a publication of this session; never blocks on I/O."""
        with self._cond:
            self._pending.setdefault(session_id, None)
            self._cond.notify()

    def close(self, timeout: float = 30.0) -> None:
        """Publish what is pending, then stop."""
        with self._cond:
            self._stop = True
            self._cond.notify()
        if self._thread is not None:
            self._thread.join(timeout)

    def _work(self) -> None:
        try:
            prepare_root(self.root)
        except OSError as e:
            log.warning("transcripts root unavailable: %s", type(e).__name__)
        conn = None
        while True:
            with self._cond:
                while not self._pending and not self._stop:
                    self._cond.wait()
                if not self._pending:
                    break
                session = next(iter(self._pending))
                del self._pending[session]
            try:
                if conn is None:
                    conn = _connect_read_only(self.db_path)
                self._publish(conn, session)
                self.published += 1
            except Exception as e:  # noqa: BLE001 - a projection never fails a request
                self.failures += 1
                log.warning("transcript publication for %s did not complete: %s",
                            dir_hash(session), type(e).__name__)
        if conn is not None:
            conn.close()

    def _publish(self, conn: sqlite3.Connection, session: str) -> None:
        cache = self._cache.setdefault(session, {})
        directory = session_dir(self.root, session)
        reuse = [n for n, meta in cache.items()
                 if all((directory / path).exists() for path in meta.files)]
        conn.execute("BEGIN")
        try:
            snapshot = load(conn, session, reuse=reuse)
        finally:
            conn.execute("COMMIT")
        result = publish(self.root, snapshot, added_tokens=self.added_tokens, count=self.count,
                         profile=self.profile, cache=cache)
        log.debug("transcripts %s: generation %d, %d turns, %d files written (%d bytes)",
                  dir_hash(session), result.generation, result.turns, result.written,
                  result.bytes_written)
