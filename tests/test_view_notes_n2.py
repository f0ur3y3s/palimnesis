"""Working notes, format n2 (D74, R34-C).

Pure tests of ``palimnesis.view.builder``. Under ``ViewPolicy(notes_format="n2")``:

- the refresh prompt asks for the sections in the order Objective, Current step and next
  move, Requirements and constraints, Decisions, Done so far, Dead ends; for a length
  derived from the slot (about 0.3 words per token, rounded to 100); and for the notes as
  the reply, not as reasoning;
- ``fit_notes(text, fits, sections=True)`` keeps every section's heading and that
  section's first lines, the same number of lines per section, the most that fits; text
  without section headings, or whose headings alone do not fit, is cut at a line as in n1;
- ``notes_from_reasoning(text)`` returns the reasoning from its first section heading on
  when at least three distinct section headings stand as lines of their own, else None.

n1 (D72) is unchanged and stays the default."""

from __future__ import annotations

import pytest

from palimnesis.view.budget import BudgetPolicy, plan_budget
from palimnesis.upstreams.strata import tokens
from palimnesis.view.builder import (NOTES_PROMPT, ViewPolicy, ViewState, build, fit_notes,
                             notes_from_reasoning, notes_prompt)

from .test_view import TOOLS
from .test_view_notes import _long

SECTIONS = ["Objective", "Current step and next move", "Requirements and constraints",
            "Decisions", "Done so far", "Dead ends"]


def _notes(lines_per_section=30, heading=lambda s: s):
    out = []
    for s in SECTIONS:
        out.append(heading(s))
        out += [f"- {s.split()[0].lower()} fact {k}: " + "x" * 40 for k in range(lines_per_section)]
    return "\n".join(out)


def _under(chars):
    return lambda t: len(t) <= chars


def test_n1_is_the_default_and_keeps_the_d72_prompt():
    assert ViewPolicy().notes_format == "n1"
    assert notes_prompt(ViewPolicy(notes_tokens=2048)) == NOTES_PROMPT


def test_the_n2_prompt_puts_the_current_step_second_and_sizes_itself_to_the_slot():
    prompt = notes_prompt(ViewPolicy(notes_tokens=2048, notes_format="n2"))

    positions = [prompt.index(f"\n{s}") for s in SECTIONS]
    assert positions == sorted(positions)
    assert "about 600 words" in prompt
    assert "about 300 words" in notes_prompt(ViewPolicy(notes_tokens=1024, notes_format="n2"))
    assert "reply" in prompt and "not in your reasoning" in prompt


def test_an_n2_refresh_sends_the_n2_prompt():
    counter = tokens.default()
    policy = ViewPolicy(notes_tokens=2048, notes_format="n2")
    view = build(_long().items, tools=TOOLS, render_kwargs={},
                 budget=plan_budget(32768, client_limit=8192, policy=BudgetPolicy()),
                 state=ViewState(), policy=policy, counter=counter)

    assert view.refresh is not None
    assert view.refresh.messages[-1] == {"role": "user", "content": notes_prompt(policy)}


def test_notes_that_fit_are_unchanged():
    text = _notes(3)
    assert fit_notes(text, _under(10_000), sections=True) == text


def test_a_cut_keeps_every_section_heading_and_its_first_lines():
    text = _notes(30)
    cut = fit_notes(text, _under(2_500), sections=True)

    assert len(cut) <= 2_500
    lines = cut.split("\n")
    assert [line for line in lines if line in SECTIONS] == SECTIONS
    kept = [sum(1 for line in lines if line.startswith(f"- {s.split()[0].lower()} fact"))
            for s in SECTIONS]
    assert len(set(kept)) == 1 and kept[0] >= 1  # the same first lines of each section
    k = kept[0]
    for s in SECTIONS:
        assert f"- {s.split()[0].lower()} fact {k - 1}: " in cut
        assert f"- {s.split()[0].lower()} fact {k}: " not in cut
    # The most that fits: one more line per section would not.
    more = fit_notes(_notes(k + 1), _under(10**6), sections=True)
    assert len(more) > 2_500


@pytest.mark.parametrize("heading", [lambda s: f"## {s}", lambda s: f"**{s}**",
                                     lambda s: f"{s}:", lambda s: f"{s} (details)"])
def test_decorated_headings_are_sections(heading):
    cut = fit_notes(_notes(30, heading), _under(2_500), sections=True)

    for s in SECTIONS:
        assert heading(s) in cut.split("\n")


def test_sections_shorter_than_the_cap_keep_all_their_lines():
    text = "\n".join(["Objective", "- one goal", *_notes(30).split("\n")[31:]])
    cut = fit_notes(text, _under(2_500), sections=True)

    assert cut.startswith("Objective\n- one goal\nCurrent step and next move\n")


def test_text_without_headings_is_cut_at_a_line():
    text = "\n".join(f"line {k} " + "y" * 40 for k in range(100))
    cut = fit_notes(text, _under(1_000), sections=True)

    assert text.startswith(cut) and len(cut) <= 1_000 and text.startswith(cut + "\n")


def test_headings_that_alone_do_not_fit_fall_back_to_a_line_cut():
    text = _notes(30)
    cut = fit_notes(text, _under(60), sections=True)

    assert text.startswith(cut) and len(cut) <= 60


def test_n1_cuts_a_prefix():
    text = _notes(30)
    cut = fit_notes(text, _under(2_500), sections=False)

    assert text.startswith(cut + "\n") and "Dead ends" not in cut


def test_reasoning_holding_the_notes_is_taken_from_its_first_heading():
    notes = _notes(2)
    reasoning = "I should write the notes now.\n" + notes

    assert notes_from_reasoning(reasoning) == notes


def test_reasoning_with_fewer_than_three_headings_is_not_notes():
    reasoning = "Objective\nBuild the tool. Next move: report.\n\nRequirements and constraints\n"

    assert notes_from_reasoning(reasoning) is None


def test_headings_inside_a_sentence_do_not_count():
    reasoning = ("The Objective is clear. Decisions were made. Done so far is little, "
                 "and Dead ends are none.")

    assert notes_from_reasoning(reasoning) is None


# --- review of the D74 draft ------------------------------------------------------------

@pytest.mark.parametrize("heading", [
    lambda s: f"## {s.title()}",                      # Title Case
    lambda s: f"{SECTIONS.index(s) + 1}. {s}",        # numbered
    lambda s: f"### {SECTIONS.index(s) + 1}) {s}",
    lambda s: f"**{s}** (details of this section)",   # bold, then a parenthetical
    lambda s: f"{s} (quote the user's rules and the exact values, names and formats from "
              "documents and specs)",                 # the prompt's own long heading
])
def test_more_heading_styles_are_sections(heading):
    cut = fit_notes(_notes(30, heading), _under(3_500), sections=True)

    for s in SECTIONS:
        assert heading(s) in cut.split("\n")


@pytest.mark.parametrize("line", [
    "* Done so far: edited foo.py",          # a bullet
    "- Decisions",                           # a bullet
    "Decisions made so far include:",        # a sentence
    "Current step is to rerun the tests",
    "Objective is to fix the parser",
    "Decisions: we chose SQLite",            # inline content
])
def test_bullets_and_sentences_are_not_headings(line):
    reasoning = "\n".join([line, "Objective is clear", "Dead ends are none", "x"])

    assert notes_from_reasoning(reasoning) is None
    text = "\n".join(["Objective", "- a", "Decisions", line, *(["- d " + "z" * 40] * 30)])
    assert line in fit_notes(text, _under(400), sections=True).split("\n")[:5]


def test_one_long_first_line_falls_back_to_a_line_cut():
    """F1: a cut that would keep only headings keeps a line prefix instead."""
    lines = _notes(3).split("\n")
    i = lines.index("Requirements and constraints")
    lines[i + 1] = "- " + "q" * 3_000
    text = "\n".join(lines)
    cut = fit_notes(text, _under(1_000), sections=True)

    assert text.startswith(cut) and "- objective fact 0: " in cut


def test_a_preamble_before_the_first_heading_keeps_its_first_lines():
    text = "\n".join(["Here are my notes.", "More preamble.", *_notes(30).split("\n")])
    cut = fit_notes(text, _under(2_500), sections=True)

    assert cut.startswith("Here are my notes.\n")
    assert [line for line in cut.split("\n") if line in SECTIONS] == SECTIONS


def test_a_slot_too_small_for_anything_returns_empty_without_hanging():
    text = _notes(3)
    assert fit_notes(text, lambda t: False, sections=True) == ""
    assert fit_notes(text, lambda t: False, sections=False) == ""


def test_an_echo_of_the_prompts_section_list_is_not_notes():
    reasoning = "The prompt wants these sections:\n" + "\n".join(SECTIONS) + "\nLet me recall."

    assert notes_from_reasoning(reasoning) is None


def test_of_two_drafts_in_reasoning_the_last_is_taken():
    first, second = _notes(1), _notes(2)

    assert notes_from_reasoning(f"Draft:\n{first}\nToo short; again.\n{second}") == second


def test_an_unknown_notes_format_is_refused():
    with pytest.raises(ValueError):
        notes_prompt(ViewPolicy(notes_tokens=2048, notes_format="N2"))
