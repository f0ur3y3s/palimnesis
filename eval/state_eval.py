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
  (tests excluded). Each hit is ``code`` or ``doubtful`` (D109). Only ``code`` counts as a
  repeat: the trap outside comments and strings, in what a ``write`` or an ``edit``'s new
  text put into a task source file in the workspace the harness ran in, or in a final
  source file. Searches, shell commands, scratch files, tests, comments, strings and an
  edit's old text are ``doubtful`` and reviewed by hand (D107.7). A task without
  patterns reports ``trap: "manual"`` and is reviewed by hand.
- **state**: committed state versions after the statement, and whether the statement's
  own turn was collapsed out of view by the end (then only the state, excerpts and
  transcripts could carry it).

Held-out set ``heldout4`` is refused: it stays unseen until Phase 7 (D96).
"""

from __future__ import annotations

import argparse
import importlib
import io
import json
import posixpath
import re
import sqlite3
import sys
import tokenize
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


_LITERAL = re.compile(
    r'[rRbBuUfF]{0,2}(?:"""[\s\S]*?"""' + r"|'''[\s\S]*?'''" + r'|"(?:\\.|[^"\\\n])*"'
    + r"|'(?:\\.|[^'\\\n])*')" + r"|#[^\n]*")
# Write and edit argument shapes of every supported harness (lower-cased tool names):
# OpenCode write/edit/multiedit (filePath or path), Pi 1.5.0 edit with edits[{oldText,
# newText}], Claude Code Write/Edit (file_path). Old text is never what was written.
LF = "\n"
_WRITE_TOOLS = ("write", "edit", "multiedit")
_PATH_KEYS = ("path", "filePath", "file_path")
_NEW_KEYS = ("content", "newString", "new_string", "newText")


def _blank(text: str, spans) -> str:
    out = list(text)
    for start, end in spans:
        for i in range(start, end):
            if out[i] != "\n":
                out[i] = " "
    return "".join(out)


def code_only(text: str) -> str:
    """``text`` with Python comments and string literals blanked, so a trap named in a
    comment, a docstring or a printed message is not code. An f-string's literal text is
    blanked and the code in its replacement fields kept, since that code runs. A fragment
    that does not tokenize (an edit's new text) falls back to a scan for comments and
    complete literals."""
    starts, pos = [], 0
    for line in text.split(LF):  # the tokenizer's lines: split on LF only
        starts.append(pos)
        pos += len(line) + 1

    def offset(rc):
        return min(starts[rc[0] - 1] + rc[1], len(text)) if rc[0] - 1 < len(starts) else len(text)

    literal = {tokenize.COMMENT, tokenize.STRING} | {
        getattr(tokenize, n) for n in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")
        if hasattr(tokenize, n)}
    spans = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text, newline=LF).readline):
            if tok.type in literal:
                spans.append((offset(tok.start), offset(tok.end)))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        spans = [m.span() for m in _LITERAL.finditer(text)]
    return _blank(text, spans)


def _source(rel: str) -> bool:
    """A task source file: Python, not a test, a pytest file or the checker's copy."""
    name = rel.rsplit("/", 1)[-1]
    return (rel.endswith(".py") and not rel.startswith(("tests/", "_check/", "../"))
            and "/tests/" not in rel and not name.startswith("test_")
            and not name.endswith("_test.py") and name != "conftest.py")


def _relative(path: str, run_ws: Path | None) -> str | None:
    if run_ws is None or not path:
        return None
    path = path.replace("\\", "/")
    if not re.match(r"[A-Za-z]:|/|~", path):  # relative: the harness resolves it in run_ws
        rel = posixpath.normpath(path)
    else:
        root = posixpath.normpath(str(run_ws).replace("\\", "/"))
        path = posixpath.normpath(path)
        if not path.lower().startswith(root.lower() + "/"):
            return None
        rel = path[len(root) + 1:]
    return None if rel == ".." or rel.startswith("../") or rel == "." else rel


def _strings(value) -> list[str]:
    """Every string in decoded JSON arguments, so a pattern spanning a newline matches."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _new_text(args: dict) -> str | None:
    """What a write or edit puts into the file: its content or new text, including each
    entry of an ``edits`` list. Old text is what the edit removes."""
    texts = [args[k] for k in _NEW_KEYS if isinstance(args.get(k), str)]
    for e in args.get("edits") or ():
        if isinstance(e, dict):
            texts += [e[k] for k in _NEW_KEYS if isinstance(e.get(k), str)]
    return LF.join(texts) if texts else None


def _trap_hits(conn, branch: str, after_seq: int, patterns, workspace: Path | None,
               run_ws: Path | None) -> list[dict]:
    """Every pattern match after the statement, each ``kind`` ``code`` or ``doubtful``
    (D109). ``code``: outside comments and strings, in what a ``write`` or an ``edit``'s
    new text put into a task source file inside ``run_ws`` (the workspace the harness
    ran in), or in a final source file. Everything else that matches is ``doubtful``."""
    compiled = [re.compile(p) for p in patterns]
    hits = []
    for occ_id, seq in conn.execute("SELECT occ_id, seq FROM occurrences WHERE branch_id = ?"
                                    " AND source = 'generated' AND seq > ? ORDER BY seq",
                                    (branch, after_seq)):
        for block_id, meta in conn.execute("SELECT block_id, meta FROM blocks WHERE occ_id = ?"
                                           " AND kind = 'tool_call'", (occ_id,)):
            arguments, tool = _text(conn, block_id), json.loads(meta).get("name")
            try:
                args = json.loads(arguments)
            except ValueError:
                args = None
            rel, written = None, None
            if isinstance(args, dict) and str(tool).lower() in _WRITE_TOOLS:
                path = next((args[k] for k in _PATH_KEYS if isinstance(args.get(k), str)), "")
                rel = _relative(path, run_ws)
                written = _new_text(args)
            searched = LF.join([arguments, *_strings(args)])
            for p in compiled:
                if not p.search(searched):
                    continue
                code = (rel is not None and _source(rel) and written is not None
                        and p.search(code_only(written)) is not None)
                hit = {"where": "tool_call", "seq": seq, "tool": tool, "pattern": p.pattern,
                       "kind": "code" if code else "doubtful"}
                if rel is not None:
                    hit["path"] = rel
                hits.append(hit)
    if workspace is not None and workspace.is_dir():
        for path in sorted(workspace.rglob("*.py")):
            rel = path.relative_to(workspace).as_posix()
            if not _source(rel):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for p in compiled:
                if p.search(text):
                    hits.append({"where": "file", "path": rel, "pattern": p.pattern,
                                 "kind": "code" if p.search(code_only(text)) else "doubtful"})
    return hits


def evaluate(db: Path, task, *, check: dict | None = None,
             workspace: Path | None = None, run_ws: Path | None = None) -> list[dict]:
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
            hits = _trap_hits(conn, branch, seq, patterns, workspace, run_ws) if patterns else []
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
                "trap_doubtful": sum(h["kind"] == "doubtful" for h in hits),
                "trap_repeated": (any(h["kind"] == "code" for h in hits) if patterns else None)
                if eligible else None,
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
    # The harness ran in <attempt ws>/ws; run.py records the attempt's transcript root
    # beside it.
    transcripts = (result.get("settings") or {}).get("transcripts")
    run_ws = Path(transcripts).parent / "ws" if transcripts else None
    reports = evaluate(db, task, check=result.get("check"),
                       workspace=args.attempt / "check" / "ws", run_ws=run_ws)
    if args.json:
        print(json.dumps(reports, indent=1))
    else:
        for r in reports:
            print(f"{r['task']} {r['session']}: moves after the rules {r['moves_after']}"
                  f" ({'eligible' if r['eligible'] else 'not eligible'}),"
                  f" constraints {r['constraints_held']}/{r['constraints_eligible']},"
                  f" trap {r['trap']} repeated={r['trap_repeated']} hits={len(r['trap_hits'])}"
                  f" (doubtful {r['trap_doubtful']}),"
                  f" state versions after {r['state_versions_after']},"
                  f" statement collapsed={r['statement_collapsed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
