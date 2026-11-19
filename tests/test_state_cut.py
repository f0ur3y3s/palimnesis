"""Phase 4A S1: the cut report (D105.4). ``fit_notes_report`` applies ``fit_notes``'s rule
unchanged and also names the reply lines the cut left out, so the originals of a cut
state stay retrievable. Pure functions."""

from __future__ import annotations

import pytest

from palimnesis.view.builder import fit_notes, fit_notes_report

SECTIONS = ["Objective", "Current step and next move", "Requirements and constraints",
            "Decisions", "Done so far", "Dead ends"]


def _notes(lines_per_section: int) -> str:
    out = []
    for s in SECTIONS:
        out.append(s)
        out += [f"- {s.split()[0].lower()} fact {k}" for k in range(lines_per_section)]
    return "\n".join(out)


def _fits(limit: int):
    return lambda text: len(text) <= limit


@pytest.mark.parametrize("sections", [True, False])
@pytest.mark.parametrize("limit", [40, 200, 400, 10_000])
def test_fit_report_kept_equals_fit_notes(sections, limit):
    text = _notes(5)
    kept, _ = fit_notes_report(text, _fits(limit), sections=sections)
    assert kept == fit_notes(text, _fits(limit), sections=sections)


def test_fit_report_of_fitting_text_drops_nothing():
    text = _notes(2)
    assert fit_notes_report(text, _fits(10_000), sections=True) == (text, [])


def test_fit_report_lists_exactly_the_lines_the_cut_dropped():
    text = _notes(5)
    lines = text.split("\n")
    kept, dropped = fit_notes_report(text, _fits(400), sections=True)
    # Every section keeps its first k lines; the dropped ones are the rest, by index.
    assert dropped and all(lines[i] not in kept.split("\n") for i in dropped)
    assert [lines[i] for i in dropped] == [l for l in lines if l not in kept.split("\n")]


@pytest.mark.parametrize("sections", [True, False])
def test_kept_and_dropped_rebuild_the_reply_lines(sections):
    text = _notes(5).replace("- decisions fact 2", "- decisions fact 2\n\n")
    lines = text.split("\n")
    kept, dropped = fit_notes_report(text, _fits(300), sections=sections)
    kept_lines = [l for l in kept.split("\n") if l.strip()]
    rebuilt = sorted(set(range(len(lines))) - set(dropped))
    assert [lines[i] for i in rebuilt if lines[i].strip()] == kept_lines


def test_a_line_cut_inside_counts_as_dropped():
    """A single line longer than the slot is cut inside; the report names it dropped,
    since the archived reply holds the whole line."""
    text = "x" * 500
    kept, dropped = fit_notes_report(text, _fits(100), sections=False)
    assert kept == fit_notes(text, _fits(100), sections=False) and dropped == [0]
