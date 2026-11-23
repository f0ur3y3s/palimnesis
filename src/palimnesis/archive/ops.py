"""Archive operations (Phase 8 S9, D133): export, delete, backup and restore.

- ``export_session``: JSONL of one session's exact bytes with their SHA-256: the
  reconstructed client request bodies (each checked against its stored hash), every
  occurrence with its blocks, the notes versions and the excerpt blocks.
- ``delete_session``: removes one session from every table, from the derived full-text
  indexes, and its transcript directory, then VACUUMs. The archive's immutability
  triggers are dropped and re-created inside the deleting transaction (contracts §11:
  user-invoked deletion is the one exception). Refused while a proxy holds the archive,
  and while a fork depends on the session (its copies point at the session's rows).
- ``backup``: SQLite's online backup API from a read-only connection: safe while a proxy
  serves the archive (WAL readers see one consistent snapshot).
- ``restore``: refused while a proxy holds the archive. The source must pass SQLite's
  integrity check and be no newer than the code before anything is replaced; then it is
  migrated, its interrupted attempts are abandoned as at a restart (a backup taken while
  serving holds the requests then in flight), it is checked (``integrity.check``), and the
  caller rebuilds the transcripts.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Iterator

from palimnesis.archive import integrity, store
from palimnesis.archive.rawarchive import get_raw
from palimnesis.archive.store import StoreError, _FileLock


class OpError(Exception):
    pass


def _ro(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# --- export -------------------------------------------------------------------------------

def export_lines(conn: sqlite3.Connection, session: str) -> Iterator[dict]:
    row = conn.execute("SELECT created_at, association FROM sessions WHERE session_id = ?",
                       (session,)).fetchone()
    if row is None:
        raise OpError(f"no archived session {session!r}")
    yield {"type": "session", "export_version": 1, "session_id": session,
           "created_at": row[0], "association": row[1]}
    for (rid, endpoint, raw_id, fp, stream, key, arrived, sha) in conn.execute(
            "SELECT r.request_id, r.endpoint, r.raw_id, r.fingerprint, r.stream, r.idem_key,"
            " r.arrived_at, b.sha256 FROM requests r JOIN raw_bodies b ON b.raw_id = r.raw_id"
            " WHERE r.session_id = ? ORDER BY r.arrived_at", (session,)).fetchall():
        data = get_raw(conn, raw_id)
        digest = hashlib.sha256(data).digest()
        if digest != bytes(sha):
            raise OpError(f"request {rid}: reconstructed body does not match its SHA-256")
        yield {"type": "request", "request_id": rid, "endpoint": endpoint, "fingerprint": fp,
               "stream": bool(stream), "idem_key": key, "arrived_at": arrived,
               "body_b64": _b64(data), "body_sha256": digest.hex()}
    for (occ, seq, parent, role, view, source, rid, gen, env, sha, alias) in conn.execute(
            "SELECT o.occ_id, o.seq, o.parent_occ_id, o.role, o.view, o.source, o.request_id,"
            " o.generation_id, o.envelope, o.content_sha256,"
            " (SELECT alias FROM aliases a WHERE a.target_id = o.occ_id)"
            " FROM occurrences o JOIN branches b ON b.branch_id = o.branch_id"
            " WHERE b.session_id = ? ORDER BY o.branch_id, o.seq", (session,)).fetchall():
        blocks = []
        for block_id, idx, kind, encoding, meta in conn.execute(
                "SELECT block_id, idx, kind, encoding, meta FROM blocks WHERE occ_id = ?"
                " ORDER BY idx", (occ,)).fetchall():
            data = b"".join(r[0] for r in conn.execute(
                "SELECT bytes FROM segments WHERE block_id = ? ORDER BY seq", (block_id,)))
            blocks.append({"idx": idx, "kind": kind, "encoding": encoding,
                           "meta": json.loads(meta), "bytes_b64": _b64(data),
                           "sha256": hashlib.sha256(data).hexdigest()})
        yield {"type": "occurrence", "occ_id": occ, "seq": seq, "parent_occ_id": parent,
               "role": role, "view": view, "source": source, "request_id": rid,
               "generation_id": gen, "envelope": json.loads(env), "content_sha256": sha,
               "alias": alias, "blocks": blocks}
    for (nid, n, status, text, created) in conn.execute(
            "SELECT v.notes_id, v.n, v.status, v.text, v.created_at FROM notes_versions v"
            " JOIN branches b ON b.branch_id = v.branch_id WHERE b.session_id = ?"
            " ORDER BY v.n", (session,)).fetchall():
        yield {"type": "notes", "notes_id": nid, "n": n, "status": status, "text": text,
               "text_sha256": hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest(),
               "created_at": created}
    for (bid, host, rendered, rsha, status) in conn.execute(
            "SELECT e.block_id, e.host_occ_id, e.rendered, e.rendered_sha256, e.status"
            " FROM excerpt_blocks e JOIN branches b ON b.branch_id = e.branch_id"
            " WHERE b.session_id = ?", (session,)).fetchall():
        items = [{"idx": i, "source_occ_id": s, "start": a, "end": z, "source_sha256": h}
                 for i, s, a, z, h in conn.execute(
                     'SELECT idx, source_occ_id, start, "end", source_sha256 FROM excerpt_items'
                     " WHERE block_id = ? ORDER BY idx", (bid,))]
        yield {"type": "excerpt", "block_id": bid, "host_occ_id": host, "rendered": rendered,
               "rendered_sha256": rsha, "status": status, "items": items}


def export_session(db: Path, session: str, out: Path) -> int:
    conn = _ro(db)
    try:
        lines = list(export_lines(conn, session))
    finally:
        conn.close()
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return len(lines)


# --- delete -------------------------------------------------------------------------------

def _in(ids: list[str]) -> str:
    return ",".join("?" * len(ids)) or "NULL"


def delete_session(db: Path, session: str, root: Path | None = None) -> dict:
    """Remove ``session`` everywhere; returns per-table row counts removed."""
    lock = _FileLock(Path(str(db) + ".lock"))  # StoreError while a proxy serves it
    try:
        conn = sqlite3.connect(db, isolation_level=None)
        try:
            counts = _delete(conn, session)
            conn.execute("VACUUM")
        finally:
            conn.close()
    finally:
        lock.release()
    if root is not None:
        from palimnesis.transcripts import projector

        directory = projector.session_dir(root, session)
        if directory.exists():
            shutil.rmtree(directory)
    return counts


def _delete(conn: sqlite3.Connection, session: str) -> dict:
    q = lambda sql, *a: [r[0] for r in conn.execute(sql, a)]  # noqa: E731
    if not q("SELECT session_id FROM sessions WHERE session_id = ?", session):
        raise OpError(f"no archived session {session!r}")
    forks = q("SELECT session_id FROM forks WHERE source_session_id = ?", session)
    if forks:
        raise OpError(f"forks depend on {session!r}: delete {', '.join(forks)} first")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("BEGIN IMMEDIATE")
    try:
        triggers = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'"
                                " AND name LIKE '%\\_no\\_delete' ESCAPE '\\'").fetchall()
        for name, _ in triggers:
            conn.execute(f'DROP TRIGGER "{name}"')
        B = q("SELECT branch_id FROM branches WHERE session_id = ?", session)
        R = q("SELECT request_id FROM requests WHERE session_id = ?", session)
        A = q(f"SELECT attempt_id FROM attempts WHERE request_id IN ({_in(R)})", *R)
        O = q(f"SELECT occ_id FROM occurrences WHERE branch_id IN ({_in(B)})", *B)
        G = q(f"SELECT generation_id FROM generations WHERE attempt_id IN ({_in(A)})", *A)
        BL = conn.execute(f"SELECT block_id, rowid FROM blocks WHERE occ_id IN ({_in(O)})",
                          O).fetchall()
        blocks, rowids = [b for b, _ in BL], [r for _, r in BL]
        NV = q(f"SELECT notes_id FROM notes_versions WHERE branch_id IN ({_in(B)})", *B)
        EB = q(f"SELECT block_id FROM excerpt_blocks WHERE branch_id IN ({_in(B)})", *B)
        chunks = q(f"SELECT rowid FROM chunk_map WHERE block_rowid IN ({_in(rowids)})", *rowids)
        counts: dict[str, int] = {}

        def run(table: str, where: str, args: list) -> None:
            if args:
                counts[table] = counts.get(table, 0) + conn.execute(
                    f"DELETE FROM {table} WHERE {where}", args).rowcount

        run("fts_chunks", f"rowid IN ({_in(chunks)})", chunks)
        run("chunk_map", f"rowid IN ({_in(chunks)})", chunks)
        run("fts_blocks", f"rowid IN ({_in(rowids)})", rowids)
        run("visible_map", f"visible_block_id IN ({_in(blocks)}) OR internal_block_id IN"
                           f" ({_in(blocks)})", blocks + blocks)
        run("segments", f"block_id IN ({_in(blocks)})", blocks)
        run("excerpt_items", f"block_id IN ({_in(EB)})", EB)
        run("excerpt_blocks", f"block_id IN ({_in(EB)})", EB)
        run("notes_sources", f"notes_id IN ({_in(NV)})", NV)
        run("notes_outputs", f"notes_id IN ({_in(NV)})", NV)
        run("notes_versions", f"notes_id IN ({_in(NV)})", NV)
        run("view_versions", f"branch_id IN ({_in(B)})", B)
        run("fork_occurrences", f"occ_id IN ({_in(O)})", O)
        run("forks", "session_id = ?", [session])
        run("blocks", f"block_id IN ({_in(blocks)})", blocks)
        run("aliases", "scope_session_id = ?", [session])
        run("branch_heads", f"branch_id IN ({_in(B)})", B)
        run("stream_terminals", f"request_id IN ({_in(R)})", R)
        run("prepared_responses", f"request_id IN ({_in(R)})", R)
        run("events", f"request_id IN ({_in(R)}) OR attempt_id IN ({_in(A)})", R + A)
        run("generations", f"generation_id IN ({_in(G)})", G)
        run("occurrences", f"occ_id IN ({_in(O)})", O)
        run("idempotency_bindings", "session_id = ?", [session])
        run("attempts", f"attempt_id IN ({_in(A)})", A)
        run("requests", f"request_id IN ({_in(R)})", R)
        run("raw_bodies", "session_id = ?", [session])
        run("branches", f"branch_id IN ({_in(B)})", B)
        run("sessions", "session_id = ?", [session])
        dangling = conn.execute("PRAGMA foreign_key_check").fetchall()
        if dangling:
            raise OpError(f"the deletion would leave dangling references: {dangling[:5]}")
        for _, sql in triggers:
            conn.execute(sql)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return counts


# --- backup and restore -------------------------------------------------------------------

def backup(db: Path, dest: Path) -> None:
    """A consistent copy of the archive, safe while a proxy serves it."""
    dest = Path(dest)
    if dest.exists():
        raise OpError(f"{dest} exists; choose a new file")
    src = _ro(db)
    try:
        out = sqlite3.connect(dest)
        try:
            src.backup(out)
            ok = out.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            out.close()
    finally:
        src.close()
    if ok != "ok":
        raise OpError(f"the backup failed its integrity check: {ok}")


def _validate(path: Path) -> None:
    if not Path(path).is_file():
        raise OpError(f"no file {path}")
    try:
        c = _ro(path)
        try:
            ok = c.execute("PRAGMA integrity_check").fetchone()[0]
            version = c.execute("PRAGMA user_version").fetchone()[0]
        finally:
            c.close()
    except sqlite3.DatabaseError as e:
        raise OpError(f"{path} is not a readable archive: {e}") from e
    if ok != "ok":
        raise OpError(f"{path} fails SQLite's integrity check: {ok}")
    if version > len(store.MIGRATIONS):
        raise StoreError(f"{path} has schema v{version}, newer than this Palimnesis "
                         f"(v{len(store.MIGRATIONS)}); upgrade Palimnesis first")


def restore(src: Path, db: Path, *, root: Path | None = None) -> list[str]:
    """Replace the archive at ``db`` with ``src`` after validating it; returns the
    sessions whose transcripts the caller should rebuild."""
    _validate(src)
    lock = _FileLock(Path(str(db) + ".lock"))  # StoreError while a proxy serves it
    try:
        staged = Path(str(db) + ".restoring")
        shutil.copyfile(src, staged)
        for suffix in ("-wal", "-shm"):
            if Path(str(db) + suffix).exists():
                os.remove(str(db) + suffix)
        os.replace(staged, db)
    finally:
        lock.release()
    s = store.Store.open(db)  # migrates a valid older archive forward
    s.close()
    c = sqlite3.connect(db)
    try:
        # A backup taken while serving holds the requests then in flight, as a crash
        # would: abandon them as a restart does (and index their partial output).
        from palimnesis.archive import ledger

        ledger.recover(c)
        c.commit()
        problems = integrity.check(c)
        sessions = [r[0] for r in c.execute("SELECT session_id FROM sessions ORDER BY session_id")]
    finally:
        c.close()
    if problems:
        raise OpError("the restored archive has problems: " + "; ".join(problems[:5]))
    if root is not None:
        from palimnesis.transcripts import projector

        for session in sessions:
            directory = projector.session_dir(root, session)
            if directory.exists():
                shutil.rmtree(directory)
    return sessions
