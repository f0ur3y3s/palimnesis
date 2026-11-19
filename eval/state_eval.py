"""Phase 4A GL2: early constraints and already-tried traps over several watermark moves.

    uv run python eval/state_eval.py ATTEMPT_DIR --task ID [--json]

Reads one task attempt's records (``eval/tasks/run.py``: ``result.json``, the archive
``archive.db`` and the checked workspace ``check/ws``) and reports, for the session:

- **statement**: the seq of the first user instruction. Every development, ho2 and ho3
  task states its rules and its trap there (checked by ``tests/test_state_eval.py``).
- **moves after**: view versions after the statement whose watermark or collapse boundary
  advanced. A constraint or trap counts toward GL2 only when at least ``MIN_MOVES`` (3)
  follow it (D105, plan §3).
- **constraints**: ``test_c<N>`` outcomes from ``result.json`` (``run.py``'s check).
- **trap repeats**: the task's ``TRAP_PATTERNS`` searched in the model's generated
  tool-call arguments after the statement, and in the final workspace's source files
  (tests excluded). A task without patterns reports ``trap: "manual"``: hits there are
  reviewed by hand, as are doubtful pattern hits.
- **state**: committed state versions after the statement, and whether the statement's
  own turn was collapsed out of view by the end (then only the state, excerpts and
  transcripts could carry it).

Held-out set ``heldout4`` is refused: it stays unseen until Phase 7 (D96).
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_MOVES = 3
REFUSED_SETS = ("heldout4",)


def task_module(task_id: str):
    """The task's module (``dev-t1`` -> ``eval/tasks/dev_t1.py``); ho4 is refused."""
    if task_id.startswith("ho4-"):
        raise ValueError(f"{task_id}: heldout4 stays unseen until Phase 7 (D96)")
    sys.path.insert(0, str(ROOT / "eval" / "tasks"))
    try:
        module = importlib.import_module(task_id.replace("-", "_"))
    finally:
        sys.path.remove(str(ROOT / "eval" / "tasks"))
    if getattr(module, "SET", None) in REFUSED_SETS:
        raise ValueError(f"{task_id}: {module.SET} stays unseen until Phase 7 (D96)")
    return module


def _text(conn: sqlite3.Connection, block_id: str) -> str:
    return b"".join(r[0] for r in conn.execute(
        "SELECT bytes FROM segments WHERE block_id = ? ORDER BY seq", (block_id,))).decode(
        "utf-8", "replace")


def _statement(conn: sqlite3.Connection, branch: str) -> tuple[int, str] | None:
    """(seq, request_id) of the branch's first client user message."""
    row = conn.execute("SELECT seq, request_id FROM occurrences WHERE branch_id = ? AND"
                       " role = 'user' AND source IN ('client', 'client_import')"
                       " ORDER BY seq LIMIT 1", (branch,)).fetchone()
    return (row[0], row[1]) if row else None


def _moves_after(conn: sqlite3.Connection, branch: str, since: float) -> tuple[int, int]:
    """(boundary advances after ``since``, the last view's collapse seq)."""
    rows = conn.execute("SELECT watermark_seq, collapse_seq, created_at FROM view_versions"
                        " WHERE branch_id = ? ORDER BY n", (branch,)).fetchall()
    moves, prev = 0, (0, 0)
    for watermark, collapse, created in rows:
        if created > since and (watermark > prev[0] or collapse > prev[1]):
            moves += 1
        prev = (watermark, collapse)
    return moves, (rows[-1][1] if rows else 0)


def _trap_hits(conn, branch: str, after_seq: int, patterns, workspace: Path | None) -> list[dict]:
    compiled = [re.compile(p) for p in patterns]
    hits = []
    for occ_id, seq in conn.execute("SELECT occ_id, seq FROM occurrences WHERE branch_id = ?"
                                    " AND source = 'generated' AND seq > ? ORDER BY seq",
                                    (branch, after_seq)):
        for block_id, meta in conn.execute("SELECT block_id, meta FROM blocks WHERE occ_id = ?"
                                           " AND kind = 'tool_call'", (occ_id,)):
            arguments = _text(conn, block_id)
            for p in compiled:
                if p.search(arguments):
                    hits.append({"where": "tool_call", "seq": seq,
                                 "tool": json.loads(meta).get("name"), "pattern": p.pattern})
    if workspace is not None and workspace.is_dir():
        for path in sorted(workspace.rglob("*.py")):
            rel = path.relative_to(workspace).as_posix()
            if rel.startswith(("tests/", "_check/")) or "/tests/" in rel:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for p in compiled:
                if p.search(text):
                    hits.append({"where": "file", "path": rel, "pattern": p.pattern})
    return hits


def evaluate(db: Path, task, *, check: dict | None = None,
             workspace: Path | None = None) -> list[dict]:
    """One report per session in the archive (a task attempt has one)."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        out = []
        for (branch,) in conn.execute("SELECT branch_id FROM branches ORDER BY branch_id"):
            stated = _statement(conn, branch)
            if stated is None:
                continue
            seq, request = stated
            arrived = conn.execute("SELECT arrived_at FROM requests WHERE request_id = ?",
                                   (request,)).fetchone()[0]
            moves, collapse_seq = _moves_after(conn, branch, arrived)
            states = conn.execute(
                "SELECT count(*) FROM notes_versions WHERE branch_id = ? AND status ="
                " 'committed' AND created_at > ?", (branch, arrived)).fetchone()[0]
            patterns = tuple(getattr(task, "TRAP_PATTERNS", ()))
            hits = _trap_hits(conn, branch, seq, patterns, workspace) if patterns else []
            eligible = moves >= MIN_MOVES
            constraints = (check or {}).get("constraints") or {}
            out.append({
                "session": branch.rsplit("/", 1)[0], "task": task.ID,
                "statement_seq": seq, "moves_after": moves, "eligible": eligible,
                "statement_collapsed": collapse_seq >= seq,
                "state_versions_after": states,
                "constraints": constraints if eligible else {},
                "constraints_held": sum(constraints.values()) if eligible else None,
                "constraints_eligible": len(constraints) if eligible else 0,
                "trap": "pattern" if patterns else "manual",
                "trap_hits": hits,
                "trap_repeated": (bool(hits) if patterns else None) if eligible else None,
            })
        return out
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("attempt", type=Path, help="one attempt's records directory")
    ap.add_argument("--task", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        task = task_module(args.task)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    result = json.loads((args.attempt / "result.json").read_text(encoding="utf-8"))
    db = args.attempt / "archive.db"
    reports = evaluate(db, task, check=result.get("check"), workspace=args.attempt / "check" / "ws")
    if args.json:
        print(json.dumps(reports, indent=1))
    else:
        for r in reports:
            print(f"{r['task']} {r['session']}: moves after the rules {r['moves_after']}"
                  f" ({'eligible' if r['eligible'] else 'not eligible'}),"
                  f" constraints {r['constraints_held']}/{r['constraints_eligible']},"
                  f" trap {r['trap']} repeated={r['trap_repeated']} hits={len(r['trap_hits'])},"
                  f" state versions after {r['state_versions_after']},"
                  f" statement collapsed={r['statement_collapsed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
