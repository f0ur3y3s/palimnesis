"""Phase 8 S1: where a turn-1 warning left the notes (eval/notes_audit.py)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
import notes_audit as na  # noqa: E402

sys.path.remove(str(ROOT / "eval"))

WARNING = ("Also, we already tried `sorted(filled)` for the pick-list wells, and it failed "
           "because A10 landed between A1 and A2.")

V1 = """Objective
Finish the racking module.
Requirements and constraints
- Wells are A1..H12.
Dead ends
- sorted(filled) failed: A10 landed between A1 and A2; sort by row then column."""

V2_OMITTED = """Objective
Finish the racking module.
Requirements and constraints
- Wells are A1..H12.
Dead ends
- None yet."""

V1_IN_REQUIREMENTS = """Objective
Finish the racking module.
Requirements and constraints
- Do not use sorted(filled): it failed, A10 landed between A1 and A2.
Dead ends
- None yet."""


def test_fragments_are_the_warnings_backticked_code():
    assert na.fragments(WARNING) == ["sorted(filled)"]


def test_hits_name_the_section_of_each_matching_line():
    assert na.hits(V1, ["sorted(filled)"]) == [("Dead ends", 5)]
    assert na.hits(V1_IN_REQUIREMENTS, ["sorted(filled)"]) == [("Requirements", 3)]
    assert na.hits(V2_OMITTED, ["sorted(filled)"]) == []


def test_classifies_omission_and_cut():
    # v2's reply leaves the line out: omitted by the model.
    rows = na.audit([(V1, V1, []), (V2_OMITTED, V2_OMITTED, [])], ["sorted(filled)"])
    assert [r["state"] for r in rows] == ["kept", "omitted"]
    # v2's reply has it but the stored version does not: cut by fit_notes (line 6 dropped).
    cut_text = "\n".join(V1.split("\n")[:5])
    rows = na.audit([(V1, V1, []), (V1, cut_text, [5])], ["sorted(filled)"])
    assert [r["state"] for r in rows] == ["kept", "cut"]
    # Never recorded at all.
    rows = na.audit([(V2_OMITTED, V2_OMITTED, [])], ["sorted(filled)"])
    assert [r["state"] for r in rows] == ["absent"]


def test_counterfactual_carry_keeps_dead_ends_lines_the_rewrite_omitted():
    merged, carried = na.carry_dead_ends(V1, V2_OMITTED)
    assert carried == ["- sorted(filled) failed: A10 landed between A1 and A2; sort by row then column."]
    assert merged.split("\n")[-1] == carried[0]
    assert na.hits(merged, ["sorted(filled)"]) == [("Dead ends", 6)]
    # A line the rewrite kept (whitespace and case aside) is not carried twice.
    same = V2_OMITTED.replace("- None yet.", "-  SORTED(filled) failed: a10 landed between a1 and a2; sort by row then column.")
    assert na.carry_dead_ends(V1, same)[1] == []
    # A missing Dead ends heading is created.
    no_heading = "Objective\nFinish the racking module."
    merged, carried = na.carry_dead_ends(V1, no_heading)
    assert merged.split("\n")[-2:] == ["Dead ends", carried[0]]


def test_counterfactual_carry_does_not_reach_other_sections():
    # The carry covers Dead ends only: a warning recorded under Requirements is not carried.
    merged, carried = na.carry_dead_ends(V1_IN_REQUIREMENTS, V2_OMITTED)
    assert carried == []
    assert na.hits(merged, ["sorted(filled)"]) == []


def test_replay_applies_the_carry_version_by_version():
    v3 = V2_OMITTED.replace("Finish", "Still finish")
    out = na.replay_carry([V1, V2_OMITTED, v3])
    assert all(na.hits(t, ["sorted(filled)"]) for t in out)
    assert out[0] == V1


def test_a_wider_carry_also_keeps_a_warning_recorded_under_requirements():
    merged, carried = na.carry_dead_ends(V1_IN_REQUIREMENTS, V2_OMITTED,
                                         ("Dead ends", "Requirements"))
    assert carried == ["- Do not use sorted(filled): it failed, A10 landed between A1 and A2."]
    assert na.hits(merged, ["sorted(filled)"]) == [("Dead ends", 6)]
