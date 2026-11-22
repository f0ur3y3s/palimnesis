"""Phase 8 S1: where a task's turn-1 warning left the working notes, and whether a carry of
earlier Dead-ends lines would have kept it.

    uv run python eval/notes_audit.py RUN_DIR [--config a4-d77] [--tasks ID,...] [--json]

For each designated attempt of ``--config`` in ``RUN_DIR`` (an ``eval/tasks/run.py`` run
directory) that has an archive, every notes version is read with the model's raw reply
(``notes_outputs.content``), the stored version text and the lines ``fit_notes`` cut
(``notes_outputs.dropped``). The warning is found by the code it names: the backticked
fragments of the task's ``TRAP_WARNING``. Each committed version is then

- ``kept``: the version text holds the warning;
- ``cut``: the reply holds it but the stored version does not (``fit_notes`` dropped it);
- ``omitted``: an earlier version held it and the reply leaves it out (the model);
- ``absent``: no version so far held it.

The counterfactual replays the recorded replies through ``carry_dead_ends``: every line
under the previous version's Dead ends heading that the next reply lacks (whitespace- and
case-normalized) is appended under that reply's Dead ends heading, which is created when
missing. It is the merge planned for notes format n3 (Phase 8 plan §1.1), before any cut.
The report gives the state of the version in force at the trap turn under both, the
section each hit sat in, and the characters the carry adds (about 4 per token, an
estimate). Retired sets only (heldout.UNSEEN_SETS are refused until unlocked).
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.append(str(Path(__file__).resolve().parent))
from palimnesis.view.builder import _section_key  # noqa: E402

DEAD_ENDS = "Dead ends"


def _norm(s: str) -> str:
    return " ".join(s.split()).casefold()


def fragments(warning: str) -> list[str]:
    """The code a warning names: its backticked fragments, in order."""
    return re.findall(r"`([^`]+)`", warning)


def hits(text: str, frags: list[str]) -> list[tuple[str | None, int]]:
    """(section key, 0-based line index) of each line of ``text`` holding a fragment."""
    out, section = [], None
    wanted = [_norm(f) for f in frags]
    for i, line in enumerate(text.split("\n")):
        key = _section_key(line)
        if key:
            section = key
            continue
        if any(w in _norm(line) for w in wanted):
            out.append((section, i))
    return out


def _section_lines(text: str, keys: tuple[str, ...]) -> list[str]:
    lines, inside = [], False
    for line in text.split("\n"):
        key = _section_key(line)
        if key:
            inside = key in keys
        elif inside and line.strip():
            lines.append(line)
    return lines


def carry_dead_ends(previous: str, reply: str,
                    keys: tuple[str, ...] = (DEAD_ENDS,)) -> tuple[str, list[str]]:
    """``reply`` with every line of the previous version's ``keys`` sections (Dead ends by
    default) that it lacks appended under its Dead ends heading (created at the end when
    missing), and the carried lines."""
    have = {_norm(x) for x in reply.split("\n")}
    carried = [x for x in _section_lines(previous, keys) if _norm(x) not in have]
    if not carried:
        return reply, []
    lines = reply.split("\n")
    start = next((i for i, x in enumerate(lines) if _section_key(x) == DEAD_ENDS), None)
    if start is None:
        return "\n".join([*lines, DEAD_ENDS, *carried]), carried
    end = next((i for i in range(start + 1, len(lines)) if _section_key(lines[i])), len(lines))
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return "\n".join([*lines[:end], *carried, *lines[end:]]), carried


def replay_carry(replies: list[str], keys: tuple[str, ...] = (DEAD_ENDS,)) -> list[str]:
    """The version texts the carry would have produced from ``replies`` (no cut)."""
    out: list[str] = []
    for reply in replies:
        out.append(reply if not out else carry_dead_ends(out[-1], reply, keys)[0])
    return out


WIDE = (DEAD_ENDS, "Requirements", "Decisions")


def audit(versions: list[tuple[str, str, list[int]]], frags: list[str]) -> list[dict]:
    """Per committed version (reply, stored text, dropped line indices): its state."""
    rows, seen = [], False
    for reply, text, dropped in versions:
        in_text, in_reply = hits(text, frags), hits(reply, frags)
        if in_text:
            state = "kept"
        elif in_reply:
            state = "cut"
        elif seen:
            state = "omitted"
        else:
            state = "absent"
        seen = seen or bool(in_text) or bool(in_reply)
        rows.append({"state": state, "sections": sorted({s or "-" for s, _ in in_reply}),
                     "dropped": len(dropped or [])})
    return rows


def _decode(blob) -> str:
    return blob.decode("utf-8", errors="replace") if isinstance(blob, bytes) else str(blob or "")


def read_versions(db: Path) -> list[dict]:
    """Committed notes versions of the archive's main branch, oldest first."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT v.n, v.text, v.created_at, o.content, o.dropped FROM notes_versions v"
            " LEFT JOIN notes_outputs o ON o.notes_id = v.notes_id"
            " WHERE v.status = 'committed' ORDER BY v.n").fetchall()
    finally:
        conn.close()
    return [{"n": n, "text": text, "created_at": at, "reply": _decode(content) or text,
             "dropped": json.loads(dropped) if dropped else []}
            for n, text, at, content, dropped in rows]


def need_time(db: Path, task) -> float | None:
    """Arrival time of the request carrying the task's trap turn (state_eval's T7 rule)."""
    import state_eval as se

    t = se.trap_turn(task)
    if t is None:
        return None
    want = se._norm(task.TURNS[t])
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        for occ, req in conn.execute(
                "SELECT occ_id, request_id FROM occurrences WHERE role = 'user' AND source IN"
                " ('client', 'client_import') ORDER BY seq"):
            text = " ".join(se._text(conn, b) for (b,) in conn.execute(
                "SELECT block_id FROM blocks WHERE occ_id = ? AND kind = 'text'", (occ,)))
            if want in se._norm(text):
                row = conn.execute("SELECT arrived_at FROM requests WHERE request_id = ?",
                                   (req,)).fetchone()
                return row[0] if row else None
    finally:
        conn.close()
    return None


def audit_run(db: Path, task) -> dict:
    frags = fragments(getattr(task, "TRAP_WARNING", "") or "")
    vs = read_versions(db)
    rows = audit([(v["reply"], v["text"], v["dropped"]) for v in vs], frags)
    carried = replay_carry([v["reply"] for v in vs])
    wide = replay_carry([v["reply"] for v in vs], WIDE)
    at = need_time(db, task)
    idx = max((i for i, v in enumerate(vs) if at is None or v["created_at"] <= at), default=None)
    first_loss = next(((vs[i]["n"], r["state"]) for i, r in enumerate(rows)
                       if r["state"] in ("cut", "omitted")), None)
    return {"task": task.ID, "fragments": frags, "versions": len(vs),
            "states": [r["state"] for r in rows],
            "sections": sorted({s for r in rows for s in r["sections"]}),
            "first_loss": first_loss,
            "at_need": None if idx is None else {
                "n": vs[idx]["n"], "actual": rows[idx]["state"],
                "with_carry": "kept" if hits(carried[idx], frags) else rows[idx]["state"],
                "with_wide_carry": "kept" if hits(wide[idx], frags) else rows[idx]["state"]},
            "carry_chars_max": max((len(c) - len(v["reply"]) for c, v in zip(carried, vs)),
                                   default=0),
            "wide_chars_max": max((len(c) - len(v["reply"]) for c, v in zip(wide, vs)),
                                  default=0),
            "reply_chars_max": max((len(v["reply"]) for v in vs), default=0)}


def main(argv: list[str] | None = None) -> int:
    import state_eval as se

    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run", type=Path)
    p.add_argument("--config", default="a4-d77")
    p.add_argument("--tasks", help="ID,ID,...: only these tasks")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    manifest = json.loads((a.run / "attempts.json").read_text(encoding="utf-8"))["attempts"]
    want = set(a.tasks.split(",")) if a.tasks else None
    latest: dict[str, dict] = {}
    for x in manifest:
        tid = x["ids"][0]
        if x["config"] == a.config and (want is None or tid in want):
            if tid not in latest or x["attempt"] > latest[tid]["attempt"]:
                latest[tid] = x
    out = []
    for tid in sorted(latest, key=lambda t: (t.split("-t")[0], int(t.split("-t")[1]))):
        x = latest[tid]
        db = a.run / "records" / f"attempt-{x['attempt']:03d}" / f"{tid}-{a.config}" / "archive.db"
        if db.exists():
            out.append(audit_run(db, se.task_module(tid)))
    if a.json:
        print(json.dumps(out, indent=1))
    else:
        for r in out:
            print(f"{r['task']:8} versions={r['versions']:<3} first_loss={r['first_loss']} "
                  f"at_need={r['at_need']} sections={r['sections']} "
                  f"carry_chars_max={r['carry_chars_max']} wide_chars_max={r['wide_chars_max']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
