"""Phase 4A S4: a state commit's prefix cost is measured (GL1, D105.5).

The notes block sits right after the leading system message, so a commit re-reads from
there. When the same move also collapses later turns, part of that re-read is the
collapse's. ``state_marginal_tokens`` is the part the commit alone causes: from the first
differing token (in the notes block) to the next turn the move changed, or to the end
when nothing else changed. ``eval/replay.py --explain --by-cause`` sums re-read tokens and
prompt time per cause, and reports the refresh calls apart."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from .test_state_golden import scenario

MARGINALS = [143, 1920]  # the second notes block was cut to fill its slot

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
import replay  # noqa: E402

sys.path.remove(str(ROOT / "eval"))


def _calls(db: Path) -> list[dict]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return [json.loads(p) for (p,) in c.execute(
            "SELECT payload FROM events WHERE kind = 'upstream_call' ORDER BY event_id")]
    finally:
        c.close()


def test_state_commit_pairs_record_marginal_tokens_within_the_reread(tmp_path):
    scenario(tmp_path)
    calls = _calls(tmp_path / "archive.db")
    commits = [x for x in calls if "state_commit" in (x["cause"] or "").split(",")]
    # Each commit lands with a collapse, so its own share is the rest of the notes block:
    # from the first changed token to the collapsed span's segment (literal values of the
    # scenario's layout, D106).
    assert [x["state_marginal_tokens"] for x in commits] == MARGINALS
    for x in commits:
        reread = x["input_tokens"] - x["lcp_tokens"]
        assert 0 < x["state_marginal_tokens"] < reread
    others = [x for x in calls if "state_commit" not in (x["cause"] or "").split(",")]
    assert all(x.get("state_marginal_tokens") is None for x in others)


def test_explain_by_cause_sums_reread_and_prompt_ms(tmp_path):
    scenario(tmp_path)
    db = tmp_path / "archive.db"
    report = replay.explain(db, by_cause=True)
    by_cause = report["by_cause"]
    calls = _calls(db)
    pairs = [x for x in calls if x["prev_call_id"] is not None and not x["call_id"].endswith("#notes")]
    for cause, row in by_cause["calls"].items():
        mine = [x for x in pairs if x["cause"] == cause]
        assert row["pairs"] == len(mine)
        assert row["reread_tokens"] == sum(x["input_tokens"] - x["lcp_tokens"] for x in mine)
        assert row["prompt_ms"] == sum(x["prompt_ms"] or 0 for x in mine)
        assert row["state_marginal_tokens"] + row["with_state_tokens"] == (
            row["reread_tokens"] if cause == "state_commit" else 0)
    commit_rows = [r for c, r in by_cause["calls"].items() if "state_commit" in c.split(",")]
    assert sum(r["state_marginal_tokens"] for r in commit_rows) == sum(
        x["state_marginal_tokens"] for x in calls if x.get("state_marginal_tokens"))


def test_explain_by_cause_reports_refresh_calls_apart(tmp_path):
    scenario(tmp_path)
    db = tmp_path / "archive.db"
    refreshes = [x for x in _calls(db) if x["call_id"].endswith("#notes")]
    row = replay.explain(db, by_cause=True)["by_cause"]["refresh_calls"]
    assert row["calls"] == len(refreshes) == 2
    assert row["reread_tokens"] == sum(x["input_tokens"] - x["lcp_tokens"]
                                       for x in refreshes if x["lcp_tokens"] is not None)
    # Recorded on upstream_call events since Phase 7 S2 (F2).
    assert row["completion_tokens"] == sum(x["completion_tokens"] for x in refreshes) > 0
    assert row["prompt_tokens"] == sum(x["prompt_tokens"] for x in refreshes)
    assert row["cached_tokens"] == sum(x["cached_tokens"] or 0 for x in refreshes)
    assert row["prompt_ms"] == sum(x["prompt_ms"] or 0 for x in refreshes)


# --- the definition on hand-built layouts (cache audit of D106) ---------------------------

from palimnesis.upstreams.profile import Layout, Segment  # noqa: E402
from palimnesis.view.cacheacct import Call, Turn, _state_marginal  # noqa: E402


def _call(turns: list[Turn], kinds: list[str]) -> Call:
    """A call whose turn k renders as tokens [10k, 10k + 10), then a 5-token generation."""
    segments = [Segment(kind, (k,), 10 * k, 10 * k + 10) for k, kind in enumerate(kinds)]
    end = 10 * len(kinds)
    segments.append(Segment("generation", (), end, end + 5))
    return Call(call_id="c", request_id="r", branch_id="b", view_mode="on", turns=tuple(turns),
                layout=Layout(ids=tuple(range(end + 5)), segments=tuple(segments)))


SYS, T1, T2, T3 = (Turn((o,), "verbatim") for o in ("sys", "t1", "t2", "t3"))
NOTES = Turn(("notes_v1",), "notes")


def test_a_first_notes_block_alone_owns_the_whole_reread():
    """Inserted after the system message: nothing else changed, so every later turn is
    re-read because of the commit, up to the generation prompt (not counted)."""
    prev = _call([SYS, T1, T2, T3], ["head", "user", "tool", "tool"])
    cur = _call([SYS, NOTES, T1, T2, T3], ["head", "user", "user", "tool", "tool"])
    assert _state_marginal(prev, cur, lcp=10) == 40


def test_the_commit_owns_the_reread_up_to_the_next_changed_turn():
    collapsed = Turn(("t2",), "collapsed")
    prev = _call([SYS, T1, T2, T3], ["head", "user", "tool", "tool"])
    cur = _call([SYS, NOTES, T1, collapsed, T3], ["head", "user", "user", "user", "tool"])
    assert _state_marginal(prev, cur, lcp=10) == 20


def test_appended_turns_are_not_changes():
    prev = _call([SYS, T1], ["head", "user"])
    cur = _call([SYS, NOTES, T1, T2], ["head", "user", "user", "tool"])
    assert _state_marginal(prev, cur, lcp=10) == 30
