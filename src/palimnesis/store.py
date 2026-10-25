"""SQLite archive store: schema, durability settings and connection policy.

Contracts §11. One writer thread owns the write connection and runs each
unit of work in a bounded ``BEGIN IMMEDIATE`` transaction; a second thread
owns a read connection. Callers await both from the event loop, so database
work never blocks it. Every connection has its durability pragmas read back,
and a mismatch refuses startup.

Archive tables are insert-only, enforced in the database itself so any
connection, including a plain ``sqlite3`` one, is bound by it:

- ``BEFORE UPDATE`` and ``BEFORE DELETE`` triggers abort;
- ``BEFORE INSERT`` guards on every unique key abort a conflicting insert,
  so ``INSERT OR REPLACE`` cannot delete an existing row even on connections
  with ``recursive_triggers`` off (insert-once callers use a plain INSERT and
  handle ``IntegrityError``).

Store connections also deny ``DROP`` and ``ALTER`` via an authorizer. A
connection outside the store can still run DDL; that limit is documented,
not prevented. Derived tables (``branch_heads``) stay mutable and rebuildable.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")

SYNCHRONOUS_MODES = {"FULL": 2, "NORMAL": 1}
_SYNCHRONOUS_NAMES = {v: k for k, v in SYNCHRONOUS_MODES.items()}
BUSY_TIMEOUT_MS = 5000


class StoreError(Exception):
    pass


# Unique keys per immutable table, in creation order. Each gets an insert guard.
_UNIQUE_KEYS: dict[str, list[tuple[str, ...]]] = {
    "sessions": [("session_id",)],
    "branches": [("branch_id",)],
    "raw_bodies": [("raw_id",)],
    "requests": [("request_id",)],
    "idempotency_bindings": [("session_id", "branch_id", "key")],
    "attempts": [("attempt_id",), ("request_id", "n")],
    "occurrences": [("occ_id",), ("branch_id", "seq")],
    "generations": [("generation_id",)],
    "blocks": [("block_id",), ("occ_id", "idx")],
    "segments": [("block_id", "seq")],
    "visible_map": [("visible_block_id", "offset")],
    "events": [("event_id",)],
    "prepared_responses": [("request_id",)],
    "aliases": [("scope_session_id", "alias"), ("target_id",)],
}
IMMUTABLE_TABLES = tuple(_UNIQUE_KEYS)  # view_versions (migration 3) is immutable too

_SCHEMA_V1 = """
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    association TEXT NOT NULL
) STRICT;

CREATE TABLE branches (
    branch_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions,
    parent_branch_id TEXT REFERENCES branches,
    fork_occ_id TEXT,
    created_at REAL NOT NULL
) STRICT;

CREATE TABLE raw_bodies (
    raw_id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions,
    branch_id TEXT NOT NULL REFERENCES branches,
    format INTEGER NOT NULL,
    base_raw_id INTEGER REFERENCES raw_bodies,
    depth INTEGER NOT NULL,
    prefix_len INTEGER NOT NULL,
    suffix_len INTEGER NOT NULL,
    payload BLOB NOT NULL,
    total_len INTEGER NOT NULL,
    sha256 BLOB NOT NULL,
    created_at REAL NOT NULL
) STRICT;

CREATE TABLE requests (
    request_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions,
    branch_id TEXT NOT NULL REFERENCES branches,
    endpoint TEXT NOT NULL,
    raw_id INTEGER NOT NULL REFERENCES raw_bodies,
    fp_version INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    stream INTEGER NOT NULL,
    idem_key TEXT,
    visible_parent_occ TEXT,
    retry_hint INTEGER,
    envelope TEXT NOT NULL,
    arrived_at REAL NOT NULL
) STRICT;

CREATE TABLE idempotency_bindings (
    session_id TEXT NOT NULL,
    branch_id TEXT NOT NULL REFERENCES branches,
    key TEXT NOT NULL,
    request_id TEXT NOT NULL REFERENCES requests,
    fingerprint TEXT NOT NULL,
    stream INTEGER NOT NULL,
    PRIMARY KEY (session_id, branch_id, key)
) STRICT;

CREATE TABLE attempts (
    attempt_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES requests,
    n INTEGER NOT NULL,
    started_at REAL NOT NULL,
    UNIQUE (request_id, n)
) STRICT;

CREATE TABLE occurrences (
    occ_id TEXT PRIMARY KEY,
    branch_id TEXT NOT NULL REFERENCES branches,
    seq INTEGER NOT NULL,
    parent_occ_id TEXT REFERENCES occurrences,
    role TEXT NOT NULL,
    view TEXT NOT NULL CHECK (view IN ('both', 'visible', 'internal')),
    source TEXT NOT NULL
        CHECK (source IN ('client', 'generated', 'client_import', 'internal_tool')),
    request_id TEXT REFERENCES requests,
    generation_id TEXT,
    envelope TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    UNIQUE (branch_id, seq)
) STRICT;

CREATE TABLE generations (
    generation_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL REFERENCES attempts,
    visible_occ_id TEXT REFERENCES occurrences,
    ordinal INTEGER NOT NULL
) STRICT;

CREATE TABLE blocks (
    block_id TEXT PRIMARY KEY,
    occ_id TEXT NOT NULL REFERENCES occurrences,
    idx INTEGER NOT NULL,
    kind TEXT NOT NULL,
    encoding TEXT NOT NULL CHECK (encoding IN ('utf-8', 'wtf-8')),
    meta TEXT NOT NULL,
    UNIQUE (occ_id, idx)
) STRICT;

CREATE TABLE segments (
    block_id TEXT NOT NULL REFERENCES blocks,
    seq INTEGER NOT NULL,
    bytes BLOB NOT NULL,
    PRIMARY KEY (block_id, seq)
) STRICT;

CREATE TABLE visible_map (
    visible_block_id TEXT NOT NULL REFERENCES blocks,
    offset INTEGER NOT NULL,
    len INTEGER NOT NULL,
    internal_block_id TEXT NOT NULL REFERENCES blocks,
    internal_offset INTEGER NOT NULL,
    PRIMARY KEY (visible_block_id, offset)
) STRICT;

CREATE TABLE events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT REFERENCES requests,
    attempt_id TEXT REFERENCES attempts,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    at REAL NOT NULL
) STRICT;

CREATE TABLE prepared_responses (
    request_id TEXT PRIMARY KEY REFERENCES requests,
    status INTEGER NOT NULL,
    headers TEXT NOT NULL,
    body BLOB NOT NULL
) STRICT;

CREATE TABLE aliases (
    scope_session_id TEXT NOT NULL REFERENCES sessions,
    alias TEXT NOT NULL,
    target_id TEXT NOT NULL UNIQUE,
    PRIMARY KEY (scope_session_id, alias)
) STRICT;

-- Derived, mutable, rebuildable from the archive.
CREATE TABLE branch_heads (
    branch_id TEXT PRIMARY KEY REFERENCES branches,
    tip_occ_id TEXT REFERENCES occurrences,
    active_request_id TEXT REFERENCES requests,
    version INTEGER NOT NULL
) STRICT;
"""


def _immutability_triggers() -> str:
    statements = []
    for table, keys in _UNIQUE_KEYS.items():
        message = f"archive rows are immutable: {table}"
        for verb in ("UPDATE", "DELETE"):
            statements.append(
                f"CREATE TRIGGER {table}_no_{verb.lower()} BEFORE {verb} ON {table} "
                f"BEGIN SELECT RAISE(ABORT, '{message}'); END;"
            )
        for i, columns in enumerate(keys):
            match = " AND ".join(f"{c} = NEW.{c}" for c in columns)
            statements.append(
                f"CREATE TRIGGER {table}_no_replace_{i} BEFORE INSERT ON {table} "
                f"WHEN EXISTS (SELECT 1 FROM {table} WHERE {match}) "
                f"BEGIN SELECT RAISE(ABORT, '{message}'); END;"
            )
    return "\n".join(statements)


_VIEW_VERSIONS = """
CREATE TABLE view_versions (
    view_id TEXT PRIMARY KEY,
    branch_id TEXT NOT NULL REFERENCES branches,
    n INTEGER NOT NULL,
    request_id TEXT REFERENCES requests,
    policy_version TEXT NOT NULL,
    stub_format TEXT NOT NULL,
    watermark_seq INTEGER NOT NULL,
    collapse_seq INTEGER NOT NULL,
    oversized TEXT NOT NULL,
    budget TEXT NOT NULL,
    cause TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE (branch_id, n)
) STRICT;
""" + "\n".join(
    f"CREATE TRIGGER view_versions_no_{verb.lower()} BEFORE {verb} ON view_versions "
    "BEGIN SELECT RAISE(ABORT, 'archive rows are immutable: view_versions'); END;"
    for verb in ("UPDATE", "DELETE")
) + """
CREATE TRIGGER view_versions_no_replace_0 BEFORE INSERT ON view_versions
WHEN EXISTS (SELECT 1 FROM view_versions WHERE view_id = NEW.view_id)
BEGIN SELECT RAISE(ABORT, 'archive rows are immutable: view_versions'); END;
CREATE TRIGGER view_versions_no_replace_1 BEFORE INSERT ON view_versions
WHEN EXISTS (SELECT 1 FROM view_versions WHERE branch_id = NEW.branch_id AND n = NEW.n)
BEGIN SELECT RAISE(ABORT, 'archive rows are immutable: view_versions'); END;
"""

MIGRATIONS: list[str] = [
    _SCHEMA_V1 + _immutability_triggers(),
    # v2: derived full-text index (palimnesis.search), filled from existing blocks.
    "CREATE VIRTUAL TABLE fts_blocks USING fts5(text, content='', contentless_delete=1);\n"
    "INSERT INTO fts_blocks (rowid, text) SELECT b.rowid, (SELECT group_concat("
    "CAST(s.bytes AS TEXT), '' ORDER BY s.seq) FROM segments s WHERE s.block_id = b.block_id)"
    " FROM blocks b;",
    # v3: persisted view decisions (palimnesis.view); immutable like the archive.
    _VIEW_VERSIONS,
]

_DENIED_ACTIONS = frozenset(
    {
        sqlite3.SQLITE_ALTER_TABLE,
        sqlite3.SQLITE_DROP_INDEX,
        sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_INDEX,
        sqlite3.SQLITE_DROP_TEMP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_TRIGGER,
        sqlite3.SQLITE_DROP_TEMP_VIEW,
        sqlite3.SQLITE_DROP_TRIGGER,
        sqlite3.SQLITE_DROP_VIEW,
        sqlite3.SQLITE_DROP_VTABLE,
    }
)


def _authorizer(action, *_args) -> int:
    return sqlite3.SQLITE_DENY if action in _DENIED_ACTIONS else sqlite3.SQLITE_OK


class _FileLock:
    """Exclusive, process-lifetime lock released by the OS if the process dies."""

    def __init__(self, path: Path) -> None:
        self._fd = os.open(path, os.O_RDWR | os.O_CREAT)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self._fd)
            raise StoreError(f"archive database is in use by another process: {path}")

    def release(self) -> None:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(self._fd, 0, os.SEEK_SET)
            msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
        os.close(self._fd)


def _pragmas(conn: sqlite3.Connection) -> dict[str, str]:
    journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    sync = conn.execute("PRAGMA synchronous").fetchone()[0]
    return {"journal_mode": journal, "synchronous": _SYNCHRONOUS_NAMES.get(sync, str(sync))}


def _connect(path: str, synchronous: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA synchronous = {synchronous}")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA recursive_triggers = ON")
    actual = _pragmas(conn)
    expected = {"journal_mode": "wal", "synchronous": synchronous}
    for name, value in expected.items():
        if actual[name] != value:
            conn.close()
            raise StoreError(f"{name} is {actual[name]!r}, required {value!r}")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        conn.close()
        raise StoreError("foreign_keys could not be enabled")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for target, script in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in _split_statements(script):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {target}")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise


def _split_statements(script: str) -> list[str]:
    statements, buffer = [], ""
    for line in script.splitlines(keepends=True):
        if line.lstrip().startswith("--"):
            continue
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    return [s for s in statements if s]


class Store:
    def __init__(self) -> None:
        raise TypeError("use Store.open()")

    @classmethod
    def open(cls, path: str | os.PathLike, synchronous: str = "FULL") -> "Store":
        if synchronous not in SYNCHRONOUS_MODES:
            raise StoreError(
                f"synchronous must be one of {sorted(SYNCHRONOUS_MODES)}, got {synchronous!r}"
            )
        self = object.__new__(cls)
        self.path = str(path)
        self.synchronous = synchronous
        in_memory = self.path == ":memory:"
        self._lock = None if in_memory else _FileLock(Path(self.path + ".lock"))
        self._writer = ThreadPoolExecutor(1, thread_name_prefix="palimnesis-db-writer")
        self._reader = ThreadPoolExecutor(1, thread_name_prefix="palimnesis-db-reader")
        self._write_conn = self._read_conn = None
        try:
            self._write_conn = self._writer.submit(self._open_writer).result()
            self._read_conn = self._reader.submit(self._open_reader).result()
        except BaseException:
            self.close()
            raise
        return self

    def _open_writer(self) -> sqlite3.Connection:
        conn = _connect(self.path, self.synchronous)
        _migrate(conn)
        conn.set_authorizer(_authorizer)
        return conn

    def _open_reader(self) -> sqlite3.Connection:
        conn = _connect(self.path, self.synchronous)
        conn.set_authorizer(_authorizer)
        return conn

    async def write(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run ``fn`` in one write transaction on the writer thread."""

        def run() -> T:
            conn = self._write_conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = fn(conn)
                conn.execute("COMMIT")
                return result
            except BaseException:
                conn.execute("ROLLBACK")
                raise

        return await asyncio.wrap_future(self._writer.submit(run))

    async def read(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run ``fn`` against one consistent snapshot on the reader thread."""

        def run() -> T:
            conn = self._read_conn
            conn.execute("BEGIN")
            try:
                return fn(conn)
            finally:
                conn.execute("COMMIT")

        return await asyncio.wrap_future(self._reader.submit(run))

    async def diagnostics(self) -> dict:
        writer = await asyncio.wrap_future(
            self._writer.submit(lambda: _pragmas(self._write_conn))
        )
        reader = await asyncio.wrap_future(
            self._reader.submit(lambda: _pragmas(self._read_conn))
        )
        return {
            "path": self.path,
            "writer": writer,
            "reader": reader,
            # Contracts §11: only FULL carries the power-loss claim.
            "power_loss_durable": self.synchronous == "FULL",
        }

    def close(self) -> None:
        for executor, attr in ((self._writer, "_write_conn"), (self._reader, "_read_conn")):
            conn = getattr(self, attr)
            if conn is not None:
                executor.submit(conn.close).result()
                setattr(self, attr, None)
            executor.shutdown(wait=True)
        if self._lock is not None:
            self._lock.release()
            self._lock = None
