"""Phase 7 S6: needle strata (plan §1.3) from a history's definition, and measured depth
from an archive.

    python eval/needle_strata.py HISTORY.json [...] [--b-in 24320] [--json]

``strata(history)`` labels every question of one needle history file
(``eval/needle_gen.py`` format: ``import`` messages, then ``steps``). It reads only the
definition, the question's ``evidence`` strings and its ``parts`` and ``category``; it
never compares a model's answer.

**The defined transcript.** The ``import`` messages (their last one is the first
question), then each later step's text as a user message, in order. Model replies to
steps are not defined, so they are left out; a mid-task command's output comes after its
question and is left out too. Each message's text is its content plus its tool calls'
arguments. Token counts use the pinned Strata tokenizer (``count`` can be replaced); they
count message text, not chat-template overhead.

**The fact message.** Each evidence string's first message before the question that
contains it (content or raw tool-call arguments). When a question has several evidence
strings, the earliest such message (the deepest) sets every label; ``evidence`` lists
each one. An evidence string found nowhere before the question leaves the labels
``unlocated``.

Labels:
- ``source_role``: ``user_paste`` (a paste step), ``user_instruction`` (any other user
  message), ``assistant_statement`` (assistant text or tool-call arguments) or
  ``tool_output`` (a tool result: read, grep, shell).
- ``placement``: ``first``, ``middle`` or ``last`` third of the whole defined transcript
  (all steps), by the token offset where the fact message starts over the total tokens.
- ``planned_depth``: tokens of the messages strictly after the fact message and before
  the question, over ``b_in`` (B_in; 24,320 at n_ctx 32,768): ``<0.5x`` below 0.5,
  ``1-2x`` from 1 to 2, ``>3x`` above 3, else ``other``.
- ``distractors``: ``superseded`` for category ``superseded``; ``lexical_decoys`` for
  ``irrelevant_matches``; otherwise by shape decoys: each answer part's shape (a run of
  n digits must be n digits, a run of capitals or of small letters any run of the same
  case, other characters themselves, bounded by non-word characters) is searched in the
  transcript before the question; distinct matches other than the part are decoys. The
  largest count over the parts gives ``none`` (0), ``near_miss_key`` (1-2) or
  ``lexical_decoys`` (3 or more).
- ``declared``: a step's own ``strata`` object (heldout5 declares them), passed through.

``measured_depth(db, ...)`` reads one archive (reported, not gated): on the question's
first upstream call, whether every evidence string was in view verbatim (``in_view``), in
view or in the question's excerpt block with at least one only in the excerpt
(``in_excerpt``, as ``needle.context_check`` judges it from bodies), or neither
(``absent``); and how many view moves (a watermark or collapse advance, as
``state_eval._moves_after`` counts them) happened after the fact arrived.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Callable

ROLES = ("user_instruction", "user_paste", "assistant_statement", "tool_output")
B_IN_32K = 24_320  # gate_inputs.input_budget_for(32768), the default budget at n_ctx 32K


def _default_count() -> Callable[[str], int]:
    from palimnesis.upstreams.strata import tokens

    return tokens.count


def _text(message: dict) -> str:
    parts = [message.get("content") if isinstance(message.get("content"), str) else ""]
    for call in message.get("tool_calls") or []:
        parts.append((call.get("function") or {}).get("arguments") or "")
    return "\n".join(p for p in parts if p)


def defined_transcript(history: dict) -> list[dict]:
    """[{role, text, kind (import, paste or question), step}] in history order."""
    out = [{"role": m["role"], "text": _text(m), "kind": "import", "step": None}
           for m in history["import"]]
    steps = history["steps"]
    if steps and out and out[-1]["role"] == "user" and out[-1]["text"] == steps[0]["text"]:
        out[-1].update(kind=steps[0]["kind"], step=steps[0]["id"])
        rest = steps[1:]
    else:
        rest = steps
    out += [{"role": "user", "text": s["text"], "kind": s["kind"], "step": s["id"]} for s in rest]
    return out


def _role(m: dict) -> str:
    if m["role"] == "user":
        return "user_paste" if m["kind"] == "paste" else "user_instruction"
    return "tool_output" if m["role"] == "tool" else "assistant_statement"


def _shape(value: str) -> re.Pattern:
    out = []
    for run in re.findall(r"\d+|[A-Z]+|[a-z]+|.", value, re.S):
        if run.isdigit():
            out.append(rf"\d{{{len(run)}}}")
        elif run.isupper() and run.isalpha():
            out.append("[A-Z]+")
        elif run.islower() and run.isalpha():
            out.append("[a-z]+")
        else:
            out.append(re.escape(run))
    return re.compile(r"(?<![\w])" + "".join(out) + r"(?![\w])")


def _decoys(parts: list[str], before: str) -> int:
    return max((len({m.group(0) for m in _shape(p).finditer(before)} - {p}) for p in parts), default=0)


def _depth_label(ratio: float) -> str:
    if ratio < 0.5:
        return "<0.5x"
    if 1 <= ratio <= 2:
        return "1-2x"
    if ratio > 3:
        return ">3x"
    return "other"


def strata(history: dict, *, b_in: int = B_IN_32K, count: Callable[[str], int] | None = None) -> dict:
    """{question id: labels} for one history (module docstring for the rules)."""
    count = count or _default_count()
    msgs = defined_transcript(history)
    sizes = [count(m["text"]) for m in msgs]
    starts = [sum(sizes[:i]) for i in range(len(msgs))]
    total = sum(sizes)
    where = {m["step"]: i for i, m in enumerate(msgs) if m["step"]}
    out = {}
    for st in history["steps"]:
        if st["kind"] != "question":
            continue
        q = where[st["id"]]
        evidence = st.get("evidence") or st.get("parts") or [st["answer"]]
        found = [next((i for i in range(q) if e in msgs[i]["text"]), None) for e in evidence]
        located = all(i is not None for i in found)
        labels = {"category": st["category"], "located": located, "question_index": q,
                  "evidence": [{"text": e, "index": i, "role": None if i is None else _role(msgs[i])}
                               for e, i in zip(evidence, found)]}
        if located:
            f = min(found)
            depth = sum(sizes[f + 1:q])
            share = starts[f] / total if total else 0.0
            labels.update(
                fact_index=f, source_role=_role(msgs[f]),
                placement="first" if share < 1 / 3 else "middle" if share < 2 / 3 else "last",
                depth_tokens=depth, depth_ratio=round(depth / b_in, 4),
                planned_depth=_depth_label(depth / b_in))
        else:
            labels.update(fact_index=None, source_role="unlocated", placement="unlocated",
                          depth_tokens=None, depth_ratio=None, planned_depth="unlocated")
        decoys = _decoys(st.get("parts") or [st["answer"]], "\n".join(m["text"] for m in msgs[:q]))
        labels["decoys"] = decoys
        labels["distractors"] = ("superseded" if st["category"] == "superseded"
                                 else "lexical_decoys" if st["category"] == "irrelevant_matches"
                                 else "none" if decoys == 0 else "near_miss_key" if decoys <= 2
                                 else "lexical_decoys")
        if st.get("strata"):
            labels["declared"] = st["strata"]
        out[st["id"]] = labels
    return out


# ---------------------------------------------------------------- measured depth

def _occ_text(conn: sqlite3.Connection, occ_id: str) -> str:
    parts = []
    for (block_id,) in conn.execute("SELECT block_id FROM blocks WHERE occ_id = ? ORDER BY idx", (occ_id,)):
        parts.append(b"".join(r[0] for r in conn.execute(
            "SELECT bytes FROM segments WHERE block_id = ? ORDER BY seq", (block_id,))).decode("utf-8", "replace"))
    return "\n".join(parts)


def measured_depth(db: Path | str, *, question: str, evidence: list[str],
                   session: str | None = None) -> dict:
    """Where the evidence was on the question's first upstream call, from the archive.

    The question is the first client user occurrence whose text is ``question`` (on a
    branch of ``session`` when given; one branch must match). The view in force is the
    branch's newest view version recorded at or before that request (its own, if the
    request recorded one). Each evidence string's occurrence is its first occurrence on
    the branch before the question that contains it; it is in view verbatim unless it is
    behind the collapse boundary, or is a tool result (a ``tool`` occurrence or one with a
    ``tool_result`` block, so Chat and Messages alike) behind the watermark or oversized,
    and not kept (pinned). A masked tool result counts as out of view even when its stub
    would have been no smaller (the archive does not record that choice). Moves: view versions up to the one in force, created after the
    first evidence occurrence's request arrived, whose watermark or collapse advanced."""
    conn = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
    try:
        where, args = "", ()
        if session is not None:
            where, args = " AND b.session_id = ?", (session,)
        cands = []
        for occ_id, branch, seq, request in conn.execute(
                "SELECT o.occ_id, o.branch_id, o.seq, o.request_id FROM occurrences o JOIN branches b"
                " ON b.branch_id = o.branch_id WHERE o.role = 'user' AND o.source IN ('client',"
                " 'client_import')" + where + " ORDER BY o.branch_id, o.seq", args):
            if _occ_text(conn, occ_id).strip() == question.strip():
                cands.append((occ_id, branch, seq, request))
        branches = {c[1] for c in cands}
        if len(branches) != 1:
            raise ValueError(f"question found on {len(branches)} branches; give the session")
        q_occ, branch, q_seq, q_request = cands[0]
        arrived = conn.execute("SELECT arrived_at FROM requests WHERE request_id = ?",
                               (q_request,)).fetchone()[0]
        views = conn.execute(
            "SELECT n, request_id, watermark_seq, collapse_seq, oversized, created_at FROM view_versions"
            " WHERE branch_id = ? ORDER BY n", (branch,)).fetchall()
        in_force = [v for v in views if v[1] == q_request or v[5] <= arrived]
        view = in_force[-1] if in_force else None
        n, watermark, collapse = (view[0], view[2], view[3]) if view else (0, 0, 0)
        masks = json.loads(view[4]) if view else {}
        if isinstance(masks, list):
            masks = {"oversized": masks, "kept": []}
        kept, oversized = set(masks.get("kept") or []), set(masks.get("oversized") or [])
        excerpt = conn.execute("SELECT rendered FROM excerpt_blocks WHERE host_occ_id = ?"
                               " AND status = 'selected'", (q_occ,)).fetchone()
        excerpt = excerpt[0] if excerpt else ""
        occs = conn.execute("SELECT occ_id, seq, role, request_id FROM occurrences WHERE branch_id = ?"
                            " AND seq < ? ORDER BY seq", (branch, q_seq)).fetchall()
        texts = {o[0]: _occ_text(conn, o[0]) for o in occs}
        items, first_arrival = [], None
        for e in evidence:
            occ = next((o for o in occs if e in texts[o[0]]), None)
            if occ is None:
                items.append({"text": e, "occ_id": None, "status": "not_archived",
                              "in_excerpt": e in excerpt})
                continue
            occ_id, seq, role, request = occ
            result = role == "tool" or conn.execute(
                "SELECT 1 FROM blocks WHERE occ_id = ? AND kind = 'tool_result'", (occ_id,)).fetchone()
            collapsed = seq < collapse and occ_id not in kept
            masked = bool(result) and (seq < watermark or occ_id in oversized) and occ_id not in kept
            status = "collapsed" if collapsed else "masked" if masked else "verbatim"
            items.append({"text": e, "occ_id": occ_id, "seq": seq, "role": role, "status": status,
                          "in_excerpt": e in excerpt})
            if request is not None:
                t = conn.execute("SELECT arrived_at FROM requests WHERE request_id = ?",
                                 (request,)).fetchone()[0]
                first_arrival = t if first_arrival is None else min(first_arrival, t)
        moves, prev = 0, (0, 0)
        for v in views:
            if v[0] > n:
                break
            if (first_arrival is None or v[5] > first_arrival) and (v[2] > prev[0] or v[3] > prev[1]):
                moves += 1
            prev = (v[2], v[3])
    finally:
        conn.close()
    verbatim = [i["status"] == "verbatim" for i in items]
    if all(verbatim):
        place = "in_view"
    elif all(v or i["in_excerpt"] for v, i in zip(verbatim, items)):
        place = "in_excerpt"
    else:
        place = "absent"
    return {"where": place, "view_n": n, "moves": moves, "evidence": items}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("histories", nargs="+", type=Path)
    ap.add_argument("--b-in", type=int, default=B_IN_32K)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    out = {}
    for p in a.histories:
        h = json.loads(p.read_text(encoding="utf-8"))
        out[h["id"]] = strata(h, b_in=a.b_in)
    if a.json:
        print(json.dumps(out, indent=1))
        return 0
    print("| History | Question | Category | Source role | Placement | Planned depth (x B_in) | Distractors |")
    print("|---|---|---|---|---|---|---|")
    for hid, qs in out.items():
        for qid, s in qs.items():
            print(f"| {hid} | {qid} | {s['category']} | {s['source_role']} | {s['placement']} | "
                  f"{s['planned_depth']} ({s['depth_ratio']}) | {s['distractors']} ({s['decoys']}) |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
