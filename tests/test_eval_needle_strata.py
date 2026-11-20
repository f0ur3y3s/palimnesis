"""Phase 7 S6: the needle stratifier (``eval/needle_strata.py``). Pure functions: labels
from a development history's definition, and measured depth from a synthetic archive
built on the real schema. No held-out data is read."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval")]

import needle_strata  # noqa: E402

sys.path.remove(str(ROOT / "eval"))

# (source role, placement, planned depth, distractors, depth tokens, shape decoys) per
# question of dev-h1, from its definition and the pinned tokenizer; checked by hand
# against eval/needle_gen.py: q1's code sits in the first test run's output beside three
# same-shaped distractor codes, q2's branch is stated in turn 1 with one near-miss (the
# docs branch), q9's tag is in the pasted canary log and q10's new name first appears in
# the assistant's edit call.
DEV_H1 = {
    "h1q1": ("tool_output", "first", "1-2x", "lexical_decoys", 40474, 3),
    "h1q2": ("user_instruction", "first", "1-2x", "near_miss_key", 48541, 1),
    "h1q3": ("user_instruction", "first", "1-2x", "superseded", 40399, 37),
    "h1q4": ("tool_output", "first", "other", "lexical_decoys", 50380, 5),
    "h1q5": ("tool_output", "first", "other", "lexical_decoys", 50401, 38),
    "h1q6": ("tool_output", "first", "1-2x", "lexical_decoys", 43451, 424),
    "h1q7": ("user_instruction", "first", "other", "lexical_decoys", 58191, 53),
    "h1q8": ("tool_output", "first", "other", "lexical_decoys", 53306, 53),
    "h1q9": ("user_paste", "last", "other", "near_miss_key", 12613, 1),
    "h1q10": ("assistant_statement", "first", "other", "lexical_decoys", 53086, 424),
}


def test_strata_dev_h1_literal():
    h = json.loads((ROOT / "eval" / "needles" / "dev" / "dev-h1.json").read_text(encoding="utf-8"))
    got = needle_strata.strata(h, b_in=24_320)
    assert {q: (s["source_role"], s["placement"], s["planned_depth"], s["distractors"],
                s["depth_tokens"], s["decoys"]) for q, s in got.items()} == DEV_H1
    assert got["h1q8"]["fact_index"] == 26  # the deepest of its three evidence strings
    assert [e["role"] for e in got["h1q8"]["evidence"]] == [
        "tool_output", "user_instruction", "tool_output"]


def _history(**step):
    return {"import": [{"role": "user", "content": "use port 1111 for now"},
                       {"role": "assistant", "content": None, "tool_calls": [
                           {"id": "c1", "type": "function",
                            "function": {"name": "read", "arguments": "{\"path\":\"a\"}"}}]},
                       {"role": "tool", "tool_call_id": "c1", "content": "key = ABC-1234-X"},
                       {"role": "user", "content": "Q?"}],
            "steps": [{"kind": "question", "id": "q1", "text": "Q?", "category": "identifier",
                       "answer": "ABC-1234-X", "parts": ["ABC-1234-X"], **step}]}


def test_depth_bins_and_rules_with_a_unit_counter():
    count = lambda text: 10  # noqa: E731 - every message 10 tokens
    s = needle_strata.strata(_history(), b_in=100, count=count)["q1"]
    assert (s["source_role"], s["placement"], s["depth_tokens"]) == ("tool_output", "middle", 0)
    assert (s["planned_depth"], s["distractors"]) == ("<0.5x", "none")
    # port 1111 is two messages (20 tokens) before the question
    assert needle_strata.strata(_history(evidence=["port 1111"]), b_in=10, count=count)["q1"][
        "planned_depth"] == "1-2x"
    assert needle_strata.strata(_history(evidence=["port 1111"]), b_in=6, count=count)["q1"][
        "planned_depth"] == ">3x"
    assert needle_strata.strata(_history(evidence=["port 1111"]), b_in=8, count=count)["q1"][
        "planned_depth"] == "other"
    s = needle_strata.strata(_history(evidence=["nowhere"]), count=count)["q1"]
    assert s["located"] is False and s["source_role"] == "unlocated"
    s = needle_strata.strata(_history(strata={"source_role": "tool_output"}), count=count)["q1"]
    assert s["declared"] == {"source_role": "tool_output"}


# ---------------------------------------------------------------- the declared format (S9)

GOOD = {"source_role": "tool_output", "placement": "middle", "planned_depth": "<0.5x",
        "distractors": "none"}


def test_declared_strata_must_match_the_computed_labels():
    """The pinned ``strata`` format: exactly the four dimensions, each a computed level,
    and equal to what ``strata()`` computes from the definition (S9)."""
    count = lambda text: 10  # noqa: E731
    assert needle_strata.check_declared(_history(strata=GOOD), b_in=100, count=count) == []
    assert needle_strata.check_declared(_history(), b_in=100, count=count) == ["q1: no strata"]
    wrong = {**GOOD, "placement": "first"}
    assert needle_strata.check_declared(_history(strata=wrong), b_in=100, count=count) == [
        "q1: placement declared first, computed middle"]
    extra = {**GOOD, "mood": "calm"}
    assert needle_strata.check_declared(_history(strata=extra), b_in=100, count=count) == [
        "q1: strata keys must be distractors, placement, planned_depth, source_role"]
    bad = {**GOOD, "planned_depth": "deep"}
    assert needle_strata.check_declared(_history(strata=bad), b_in=100, count=count)[0] == (
        "q1: planned_depth level 'deep' is not one of <0.5x, 1-2x, >3x")
    lost = _history(strata=GOOD, evidence=["nowhere"])
    assert needle_strata.check_declared(lost, b_in=100, count=count) == ["q1: evidence not located"]


def test_coverage_counts_declared_levels_and_reports_gaps():
    hs = [_history(strata=GOOD), _history(strata={**GOOD, "placement": "last"})]
    cov = needle_strata.coverage(hs)
    assert cov["placement"] == {"first": 0, "middle": 1, "last": 1}
    assert cov["source_role"]["tool_output"] == 2 and cov["source_role"]["user_paste"] == 0
    gaps = needle_strata.coverage_gaps(cov, minimum=2)
    assert "placement first: 0" in gaps and "placement middle: 1" in gaps
    assert not any(g.startswith("source_role tool_output") for g in gaps)


# ---------------------------------------------------------------- measured depth

def _archive(path: Path) -> Path:
    from palimnesis.archive import store

    conn = sqlite3.connect(path, isolation_level=None)
    store._migrate(conn)
    ins = conn.execute
    for s in ("s1", "s2"):
        ins("INSERT INTO branches VALUES (?, ?, NULL, NULL, 0)", (f"{s}/main", s))
    for rid, s, t in (("r1", "s1", 1.0), ("r2", "s1", 2.0), ("r3", "s1", 3.0), ("r4", "s1", 4.0),
                      ("r5", "s1", 5.0), ("x1", "s2", 1.0)):
        ins("INSERT INTO requests VALUES (?, ?, ?, 'chat', 0, 1, 'fp', 0, NULL, NULL, NULL, '{}', ?)",
            (rid, s, f"{s}/main", t))

    def occ(occ_id, branch, seq, role, source, request, text):
        ins("INSERT INTO occurrences VALUES (?, ?, ?, NULL, ?, 'both', ?, ?, NULL, '{}', '')",
            (occ_id, branch, seq, role, source, request))
        ins("INSERT INTO blocks VALUES (?, ?, 0, 'text', 'utf-8', '{}')", (f"b-{occ_id}", occ_id))
        ins("INSERT INTO segments VALUES (?, 0, ?)", (f"b-{occ_id}", text.encode()))

    occ("o1", "s1/main", 1, "user", "client", "r1", "use port 9282 from now on")
    occ("o2", "s1/main", 2, "tool", "client", "r1", 'read_timeout = "1.25s"')
    occ("o3", "s1/main", 3, "assistant", "generated", "r1", "ok")
    occ("o4", "s1/main", 4, "user", "client", "r1", "log: new tag r2026.10.16-hf9")
    occ("o10", "s1/main", 10, "user", "client", "r4", "Which port now?")
    occ("x10", "s2/main", 1, "user", "client", "x1", "Which port now?")

    def view(n, request, watermark, collapse, created, kept=()):
        ins("INSERT INTO view_versions VALUES (?, 's1/main', ?, ?, 'p', 's1', ?, ?, ?, '{}', 'move', ?)",
            (f"v{n}", n, request, watermark, collapse,
             json.dumps({"oversized": [], "kept": list(kept)}), created))

    view(1, "r2", 3, 0, 2.1)   # watermark 0 -> 3: a move
    view(2, "r3", 5, 2, 3.1)   # watermark and collapse advance: a move
    view(3, "r4", 5, 2, 4.1)   # the question's own version: no boundary moved
    view(4, "r5", 11, 11, 5.1)  # after the question: never read
    ins("INSERT INTO excerpt_blocks VALUES ('e1', 's1/main', 'o10', 'r4', 9, 3, 5, 2, 'q', 'q1', 'r1',"
        " 'x1', 'p', 100, 40, ?, '', 'selected', NULL, 4.1)",
        ("[palimnesis excerpts] use port 9282 from now on",))
    conn.close()
    return path


@pytest.mark.parametrize("evidence, where", [
    (["tag r2026.10.16-hf9"], "in_view"),             # user text behind the watermark stays
    (["port 9282"], "in_excerpt"),                    # collapsed, but in the question's excerpt
    (['read_timeout = "1.25s"'], "absent"),            # a tool result behind the watermark
    (["tag r2026.10.16-hf9", "port 9282"], "in_excerpt"),
    (["tag r2026.10.16-hf9", "read_timeout"], "absent"),
])
def test_measured_depth_from_view_versions(tmp_path, evidence, where):
    db = _archive(tmp_path / "archive.db")
    m = needle_strata.measured_depth(db, question="Which port now?", evidence=evidence, session="s1")
    assert (m["where"], m["view_n"], m["moves"]) == (where, 3, 2)


def test_measured_depth_reads_the_statuses_and_needs_a_session_when_ambiguous(tmp_path):
    db = _archive(tmp_path / "archive.db")
    m = needle_strata.measured_depth(db, question="Which port now?", session="s1",
                                     evidence=["port 9282", "read_timeout", "r2026", "gone"])
    assert [e["status"] for e in m["evidence"]] == ["collapsed", "masked", "verbatim", "not_archived"]
    with pytest.raises(ValueError, match="session"):
        needle_strata.measured_depth(db, question="Which port now?", evidence=["port 9282"])
