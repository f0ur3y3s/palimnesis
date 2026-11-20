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

**Any arm** (Phase 7 S4). An attempt without an archive (arm 1, ``--passthrough``) is read
from the tap's captured upstream request bodies (``bodies/NNNN.json``): the model's tool
calls come from the conversation history those bodies carry, keyed by protocol (Chat
``tool_calls[].function``, Messages ``tool_use`` blocks), each counted once, and classified
by the same D109 rule (``_call_hits``).

**Need-turn eligibility** (plan §1.2 T7). A task with ``TRAP_TURN`` (the 0-based turn whose
request needs the code the trap applies to) also reports ``trap_eligible_at_need``: whether
the turn-1 statement had left the view when that turn's first request arrived.
- From the archive: the view version in force for that request (the latest made for it or
  before it arrived) has ``collapse_seq`` at or past the statement.
- From bodies: that request no longer carries the full turn-1 statement in any message
  (whitespace-normalized), because compaction replaced it.
``trap_repeat_at_need`` is the repeat outcome when eligible at need, else None. The
end-of-session fields (``eligible``, ``trap_repeated``) are kept.

Unseen held-out sets (``heldout.UNSEEN_SETS``) are refused until unlocked (D96, plan §1.1).
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

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.append(str(Path(__file__).resolve().parent))
import heldout  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MIN_MOVES = 3
REFUSED_SETS = heldout.UNSEEN_SETS


def task_module(task_id: str):
    """The task's module (``dev-t1`` -> ``eval/tasks/dev_t1.py``). A task of a locked
    unseen set is refused before its module is imported."""
    try:
        heldout.require_unlocked(heldout.set_of_task(task_id))
    except heldout.Locked as e:
        raise ValueError(f"{task_id}: {e}") from None
    sys.path.insert(0, str(ROOT / "eval" / "tasks"))
    try:
        module = importlib.import_module(task_id.replace("-", "_"))
    finally:
        sys.path.remove(str(ROOT / "eval" / "tasks"))
    try:
        heldout.require_unlocked(getattr(module, "SET", None))
    except heldout.Locked as e:
        raise ValueError(f"{task_id}: {e}") from None
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


def _call_hits(tool, arguments: str, compiled, run_ws: Path | None) -> list[dict]:
    """The D109 classification of one generated tool call, whatever its protocol: every
    pattern found in its arguments, ``code`` when the trap is outside comments and strings
    in what a write or an edit's new text put into a task source file inside ``run_ws``,
    else ``doubtful``."""
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
    hits = []
    for p in compiled:
        if not p.search(searched):
            continue
        code = (rel is not None and _source(rel) and written is not None
                and p.search(code_only(written)) is not None)
        hit = {"tool": tool, "pattern": p.pattern, "kind": "code" if code else "doubtful"}
        if rel is not None:
            hit["path"] = rel
        hits.append(hit)
    return hits


def _file_hits(workspace: Path | None, compiled) -> list[dict]:
    """Pattern matches in the final workspace's task source files (D109)."""
    hits = []
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


def _trap_hits(conn, branch: str, after_seq: int, patterns, workspace: Path | None,
               run_ws: Path | None) -> list[dict]:
    """Every pattern match after the statement in the archive's generated tool calls and
    the final source files, each ``kind`` ``code`` or ``doubtful`` (D109, ``_call_hits``)."""
    compiled = [re.compile(p) for p in patterns]
    hits = []
    for occ_id, seq in conn.execute("SELECT occ_id, seq FROM occurrences WHERE branch_id = ?"
                                    " AND source = 'generated' AND seq > ? ORDER BY seq",
                                    (branch, after_seq)):
        for block_id, meta in conn.execute("SELECT block_id, meta FROM blocks WHERE occ_id = ?"
                                           " AND kind = 'tool_call'", (occ_id,)):
            tool = json.loads(meta).get("name")
            hits += [{"where": "tool_call", "seq": seq, **h}
                     for h in _call_hits(tool, _text(conn, block_id), compiled, run_ws)]
    return hits + _file_hits(workspace, compiled)


# ---------------------------------------------------------------- captured upstream bodies

def _norm(text: str) -> str:
    return " ".join(text.split())


def _message_text(msg: dict) -> str:
    """A message's text in either protocol: a string, or the ``text`` of its content parts
    (Chat parts and Messages blocks alike)."""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return LF.join(b["text"] for b in content
                       if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


def _message_calls(msg: dict) -> list[tuple]:
    """(id, name, arguments JSON text) of each tool call an assistant message carries:
    Chat ``tool_calls[].function`` and Messages ``tool_use`` content blocks."""
    if msg.get("role") != "assistant":
        return []
    out = []
    for tc in msg.get("tool_calls") or ():
        if isinstance(tc, dict):
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            out.append((tc.get("id"), fn.get("name"),
                        args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)))
    content = msg.get("content")
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                out.append((b.get("id"), b.get("name"),
                            json.dumps(b.get("input") or {}, ensure_ascii=False)))
    return out


def read_bodies(bodies: Path) -> list[tuple[int, dict]]:
    """(n, request body) of every captured upstream request (``bodies/NNNN.json``), in order."""
    out = []
    for f in sorted(bodies.glob("[0-9][0-9][0-9][0-9].json")):
        try:
            body = json.loads(f.read_bytes())
        except ValueError:
            continue
        if isinstance(body, dict):
            out.append((int(f.name[:4]), body))
    return out


def body_tool_calls(bodies: list[tuple[int, dict]]) -> list[dict]:
    """The model's generated tool calls, read from the conversation history the captured
    request bodies carry, each once: ``{n, id, tool, arguments}`` with ``n`` the first body
    that carried it. A call recurring in later bodies is the same call when it has the same
    id, or, without an id, the same name and arguments at the same position among the
    body's calls. Internal (``palimnesis_``) calls are skipped."""
    seen, out = set(), []
    for n, body in bodies:
        pos = 0
        for msg in body.get("messages") or ():
            if not isinstance(msg, dict):
                continue
            for cid, name, args in _message_calls(msg):
                key = ("id", cid) if cid else ("pos", pos, name, args)
                pos += 1
                if str(name or "").startswith("palimnesis_") or key in seen:
                    continue
                seen.add(key)
                out.append({"n": n, "id": cid, "tool": name, "arguments": args})
    return out


def trap_hits_from_bodies(bodies: list[tuple[int, dict]], patterns, workspace: Path | None,
                          run_ws: Path | None) -> list[dict]:
    """``_trap_hits`` for any arm: the same D109 classification over the generated tool
    calls in the captured upstream bodies (``body_tool_calls``) and the final files."""
    compiled = [re.compile(p) for p in patterns]
    hits = []
    for c in body_tool_calls(bodies):
        hits += [{"where": "tool_call", "body": c["n"], **h}
                 for h in _call_hits(c["tool"], c["arguments"], compiled, run_ws)]
    return hits + _file_hits(workspace, compiled)


def trap_turn(task) -> int | None:
    """The task's ``TRAP_TURN`` (0-based index into ``TURNS``), or None."""
    t = getattr(task, "TRAP_TURN", None)
    turns = getattr(task, "TURNS", ())
    return t if isinstance(t, int) and not isinstance(t, bool) and 0 < t < len(turns) else None


def need_from_bodies(bodies: list[tuple[int, dict]], task) -> dict:
    """Need-turn eligibility from captured bodies (any arm; arm 1's only source). The trap
    turn's request is the first body with a user message containing ``TURNS[TRAP_TURN]``
    (whitespace-normalized). The statement has left the view when no message of that body,
    nor a string ``system``, contains ``TURNS[0]``, the turn-1 statement, in full: native
    compaction replaced it."""
    t = trap_turn(task)
    if t is None:
        return {"trap_turn_body": None, "trap_eligible_at_need": None}
    want, statement = _norm(task.TURNS[t]), _norm(task.TURNS[0])
    for n, body in bodies:
        msgs = [m for m in body.get("messages") or () if isinstance(m, dict)]
        if any(m.get("role") == "user" and want in _norm(_message_text(m)) for m in msgs):
            texts = [_norm(_message_text(m)) for m in msgs]
            if isinstance(body.get("system"), str):
                texts.append(_norm(body["system"]))
            return {"trap_turn_body": n,
                    "trap_eligible_at_need": not any(statement in x for x in texts)}
    return {"trap_turn_body": None, "trap_eligible_at_need": None}


def _repeat_at_need(patterns, hits, eligible_at_need) -> bool | None:
    if not patterns or not eligible_at_need:
        return None
    return any(h["kind"] == "code" for h in hits)


def evaluate_bodies(bodies_dir: Path, task, *, check: dict | None = None,
                    workspace: Path | None = None, run_ws: Path | None = None) -> dict:
    """One attempt's trap report from its captured upstream bodies, for an arm without an
    archive (arm 1, ``--passthrough``). Without view versions there are no moves, so
    ``eligible`` and ``trap_repeated`` are None; ``trap_eligible_at_need`` and
    ``trap_repeat_at_need`` carry the outcome."""
    bodies = read_bodies(bodies_dir)
    patterns = tuple(getattr(task, "TRAP_PATTERNS", ()))
    hits = trap_hits_from_bodies(bodies, patterns, workspace, run_ws) if patterns else []
    need = need_from_bodies(bodies, task)
    return {"task": task.ID, "source": "bodies", "bodies": len(bodies),
            "eligible": None, **need,
            "constraints": (check or {}).get("constraints") or {},
            "trap": "pattern" if patterns else "manual",
            "trap_hits": hits,
            "trap_doubtful": sum(h["kind"] == "doubtful" for h in hits),
            "trap_repeated": None,
            "trap_repeat_at_need": _repeat_at_need(patterns, hits, need["trap_eligible_at_need"])}


def _need_from_archive(conn, branch: str, statement_seq: int, task) -> bool | None:
    """Need-turn eligibility (T7) from the archive: the first client user message holding
    ``TURNS[TRAP_TURN]`` arrived with request R; the view in force for R is the latest view
    version made for R or before R arrived. Eligible when its collapse boundary had reached
    the statement. None without ``TRAP_TURN`` or when the trap turn never arrived."""
    t = trap_turn(task)
    if t is None:
        return None
    want = _norm(task.TURNS[t])
    for occ_id, request in conn.execute(
            "SELECT occ_id, request_id FROM occurrences WHERE branch_id = ? AND role = 'user'"
            " AND source IN ('client', 'client_import') ORDER BY seq", (branch,)):
        text = LF.join(_text(conn, b) for (b,) in conn.execute(
            "SELECT block_id FROM blocks WHERE occ_id = ? AND kind = 'text' ORDER BY idx",
            (occ_id,)))
        if want not in _norm(text):
            continue
        arrived = conn.execute("SELECT arrived_at FROM requests WHERE request_id = ?",
                               (request,)).fetchone()
        row = conn.execute(
            "SELECT collapse_seq FROM view_versions WHERE branch_id = ? AND (request_id = ?"
            " OR created_at <= ?) ORDER BY n DESC LIMIT 1",
            (branch, request, arrived[0] if arrived else 0)).fetchone()
        return bool(row) and row[0] >= statement_seq
    return None


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
            at_need = _need_from_archive(conn, branch, seq, task)
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
                "trap_eligible_at_need": at_need,
                "trap_repeat_at_need": _repeat_at_need(patterns, hits, at_need),
            })
        return out
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("attempt", type=Path, help="one attempt's records directory")
    ap.add_argument("--task", required=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--bodies", action="store_true",
                    help="read the captured upstream bodies, not the archive (the default "
                         "when the attempt has no archive.db, e.g. arm 1)")
    ap.add_argument("--run-ws", type=Path, help="the workspace the harness ran in")
    args = ap.parse_args(argv)
    try:
        task = task_module(args.task)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    result = json.loads((args.attempt / "result.json").read_text(encoding="utf-8"))
    db = args.attempt / "archive.db"
    run_ws = args.run_ws or attempt_run_ws(args.attempt, result)
    workspace = args.attempt / "check" / "ws"
    if args.bodies or not db.exists():
        r = evaluate_bodies(args.attempt / "bodies", task, check=result.get("check"),
                            workspace=workspace, run_ws=run_ws)
        if args.json:
            print(json.dumps(r, indent=1))
        else:
            print(f"{r['task']} (bodies, {r['bodies']} requests): trap {r['trap']}"
                  f" hits={len(r['trap_hits'])} (doubtful {r['trap_doubtful']}),"
                  f" code={sum(h['kind'] == 'code' for h in r['trap_hits'])},"
                  f" eligible at need={r['trap_eligible_at_need']}"
                  f" (body {r['trap_turn_body']}), repeat at need={r['trap_repeat_at_need']}")
        return 0
    reports = evaluate(db, task, check=result.get("check"), workspace=workspace, run_ws=run_ws)
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
                  f" statement collapsed={r['statement_collapsed']},"
                  f" eligible at need={r['trap_eligible_at_need']},"
                  f" repeat at need={r['trap_repeat_at_need']}")
    return 0


def attempt_run_ws(attempt: Path, result: dict) -> Path | None:
    """The workspace the harness ran in: ``<attempt ws>/ws``. Found beside the transcript
    root ``run.py`` records, or, for an arm without transcripts (arm 1), from the run's
    ``attempts.json`` entry whose records directory holds ``attempt``."""
    transcripts = (result.get("settings") or {}).get("transcripts")
    if transcripts:
        return Path(transcripts).parent / "ws"
    index = attempt.parent.parent.parent / "attempts.json"
    try:
        entries = json.loads(index.read_text(encoding="utf-8")).get("attempts") or []
    except (OSError, ValueError):
        return None
    here = attempt.parent.resolve()
    for e in entries:
        if e.get("records") and e.get("ws") and Path(e["records"]).resolve() == here:
            return Path(e["ws"]) / "ws"
    return None


if __name__ == "__main__":
    sys.exit(main())
