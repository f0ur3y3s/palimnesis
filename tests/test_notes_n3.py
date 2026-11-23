"""Working notes format n3 (Phase 8 S2, D121): ``serve --notes TOKENS --notes-format n3``.

n3 is n2 plus two rules. The prompt asks the model to record, under Dead ends and in the
user's own words, everything the user said was already tried and failed, and to carry
earlier Dead-ends entries forward. A deterministic carry then appends every Dead-ends line
of the notes in force that the reply leaves out (whitespace and case aside), under the
reply's Dead ends heading (created when missing). Carried lines are capped; past the cap
the newest carried lines are left out, so the earliest recorded failure goes last. The cut
keeps Dead ends whole and cuts the other sections. n1 and n2 are unchanged."""

from __future__ import annotations

import json

from palimnesis.upstreams.strata import tokens
from palimnesis.view.builder import (ViewPolicy, carry_dead_ends, fit_notes, fit_notes_report,
                                     fits_keeping, notes_prompt)

from dataclasses import replace

from .fake_upstream import FakeUpstream
from .test_notes_http import BUDGET, _body, _messages, _notes_rows, _sent
from .test_state_golden import _probe, _turns
from .test_view_http import post, rows, view_stack

N3 = dict(input_budget=BUDGET, notes_tokens=2048, notes_format="n3")
WARN = "- The user: we already tried round() of each share; it failed, one crate sat unclaimed."

V1 = f"""Objective
Split the crates.
Current step and next move
Write household_share.
Requirements and constraints
- Shares sum to the crates picked.
Decisions
- Largest remainder.
Done so far
- Read the docs.
Dead ends
{WARN}"""

V2 = """Objective
Split the crates.
Current step and next move
Test household_share.
Requirements and constraints
- Shares sum to the crates picked.
Decisions
- Largest remainder.
Done so far
- household_share written.
Dead ends
- None new."""


def _all(_lines):
    return True


# --- pure: the carry ---------------------------------------------------------------------

def test_carry_appends_a_dead_end_the_rewrite_left_out():
    merged, origin, carried, over = carry_dead_ends([V1], V2, _all)
    assert (carried, over) == (1, 0)
    lines = merged.split("\n")
    assert lines[-2:] == ["- None new.", WARN]
    # Every merged line maps to its reply line, or None when carried.
    assert origin == [*range(len(V2.split("\n"))), None]


def test_carry_skips_lines_the_reply_kept_whitespace_and_case_aside():
    reply = V2.replace("- None new.", "-  the USER: we already tried round() of each share;"
                                      " it failed, one crate sat unclaimed.")
    merged, _, carried, _ = carry_dead_ends([V1], reply, _all)
    assert carried == 0 and merged == reply


def test_carry_creates_the_heading_when_the_reply_has_none():
    reply = "Objective\nSplit the crates."
    merged, origin, carried, _ = carry_dead_ends([V1], reply, _all)
    assert carried == 1
    assert merged.split("\n")[-2:] == ["Dead ends", WARN]
    assert origin == [0, 1, None, None]


def test_carry_inserts_before_a_section_that_follows_dead_ends():
    reply = V2 + "\nDecisions\n- extra"  # a repeated section after Dead ends
    merged, _, _, _ = carry_dead_ends([V1], reply, _all)
    lines = merged.split("\n")
    assert lines.index(WARN) == lines.index("- None new.") + 1


def test_the_cap_keeps_the_earliest_carried_lines():
    previous = "Dead ends\n" + "\n".join(f"- failed {k}" for k in range(5))
    merged, _, carried, over = carry_dead_ends([previous], "Dead ends\n- new", lambda ls: len(ls) <= 2)
    assert (carried, over) == (2, 3)
    assert merged.split("\n") == ["Dead ends", "- new", "- failed 0", "- failed 1"]


def test_without_previous_notes_the_reply_is_unchanged():
    assert carry_dead_ends([], V2, _all) == (V2, list(range(len(V2.split("\n")))), 0, 0)


def test_the_cap_keeps_the_oldest_failure_across_three_versions():
    # v1 records A; v2's reply has only B, so v2 = B then carried A; v3's reply has only C.
    # The oldest failure (A, recorded first in v1) must be the last to go, whatever its
    # place in v2's text (protocol review of eee9146, finding 1).
    v1 = "Dead ends\n- A failed"
    v2, _, _, _ = carry_dead_ends([v1], "Dead ends\n- B failed", _all)
    assert v2.split("\n") == ["Dead ends", "- B failed", "- A failed"]
    v3, _, carried, over = carry_dead_ends([v1, v2], "Dead ends\n- C failed",
                                           lambda ls: len(ls) <= 1)
    assert (carried, over) == (1, 1)
    assert v3.split("\n") == ["Dead ends", "- C failed", "- A failed"]


def test_carried_lines_are_ordered_oldest_first():
    v1 = "Dead ends\n- A failed"
    v2 = "Dead ends\n- B failed\n- A failed"
    merged, _, _, _ = carry_dead_ends([v1, v2], "Dead ends\n- C failed", _all)
    assert merged.split("\n") == ["Dead ends", "- C failed", "- A failed", "- B failed"]


def test_the_carry_shrinks_rather_than_push_out_the_models_own_lines():
    # The merged text must still fit with Dead ends whole; otherwise the newest carried
    # lines go (protocol review, finding 2).
    previous = "Dead ends\n" + "\n".join(f"- old {k}" for k in range(5))
    reply = "Objective\nx\nDead ends\n- new"

    def fits_merged(text):
        return text.count("- old") <= 2

    merged, _, carried, over = carry_dead_ends([previous], reply, _all, fits_merged)
    assert (carried, over) == (2, 3)
    assert "- old 0" in merged and "- old 1" in merged and "- new" in merged


def test_placeholders_are_not_carried_and_bullets_do_not_duplicate():
    previous = "Dead ends\n- None new.\n* tried X: failed\n- N/A\n- Nothing yet"
    merged, _, carried, _ = carry_dead_ends([previous], "Dead ends\n- tried X: failed", _all)
    assert carried == 0 and merged == "Dead ends\n- tried X: failed"


def test_a_crlf_reply_keeps_crlf_line_endings():
    merged, _, carried, _ = carry_dead_ends(["Dead ends\n- A failed"],
                                           "Objective\r\nx\r", _all)
    assert carried == 1
    assert merged == "Objective\r\nx\r\nDead ends\r\n- A failed"


def test_fits_keeping_tells_whether_the_whole_section_fits():
    text = "Objective\n- a\n- b\nDead ends\n- c\n- d"
    assert fits_keeping(text, lambda t: True, keep=("Dead ends",))
    # Fits only once Objective is cut to one line, with Dead ends whole.
    assert fits_keeping(text, lambda t: len(t) <= len("Objective\n- a\nDead ends\n- c\n- d"),
                        keep=("Dead ends",))
    assert not fits_keeping(text, lambda t: len(t) <= 20, keep=("Dead ends",))


# --- pure: the cut keeps Dead ends whole ------------------------------------------------

def test_the_n3_cut_keeps_dead_ends_whole_and_cuts_the_others():
    body = "\n".join(f"- line {k} " + "word " * 10 for k in range(30))
    text = f"Objective\n{body}\nDead ends\n{body}"
    budget = len(text) * 3 // 4  # Dead ends whole fits; the whole text does not

    def fits(t):
        return len(t) <= budget

    kept = fit_notes(text, fits, sections=True, keep=("Dead ends",))
    dead = kept.split("Dead ends\n", 1)[1]
    assert dead == body  # whole
    assert kept.split("\nDead ends")[0].count("- line") < 30  # the rest is cut
    # When Dead ends alone does not fit, the n2 rule applies.
    tiny = fit_notes(text, lambda t: len(t) <= 300, sections=True, keep=("Dead ends",))
    assert tiny == fit_notes(text, lambda t: len(t) <= 300, sections=True)
    # fit_notes_report reports the lines left out under the same rule.
    kept2, dropped = fit_notes_report(text, fits, sections=True, keep=("Dead ends",))
    assert kept2 == kept and dropped and all(i < 31 for i in dropped)


def test_the_n3_prompt_asks_for_user_stated_failures_under_dead_ends():
    p3 = notes_prompt(ViewPolicy(notes_tokens=2048, notes_format="n3"))
    p2 = notes_prompt(ViewPolicy(notes_tokens=2048, notes_format="n2"))
    assert p3 != p2
    assert "in the user's own words" in p3
    assert "already tried" in p3
    assert "carry forward every earlier Dead ends entry" in p3
    # Same sections, in the same order, as n2.
    for name in ("Objective", "Current step and next move", "Requirements and constraints",
                 "Decisions", "Done so far", "Dead ends"):
        assert name in p3


# --- through the proxy -------------------------------------------------------------------
# The session grows as in the golden tests (``_turns``): each call is answered as
# generated, and a notes refresh is answered with the next scripted notes reply.

def _queue(fake, answer, script):
    """One reply: the next scripted notes reply (text, or an HTTP status) if the request is
    a refresh, else ``answer``."""
    plain = _probe(answer)

    def build(raw: bytes):
        last = json.loads(raw)["messages"][-1]
        if "[palimnesis notes request]" not in str(last.get("content")):
            return plain.build(raw)
        nxt = script[0] if len(script) == 1 else script.pop(0)
        if isinstance(nxt, int):
            probe = FakeUpstream()
            probe.respond_json(b'{"error": {"message": "busy"}}', status=nxt)
            return probe._script[0].build(raw)
        return _probe(nxt).build(raw)

    fake._script.append(replace(plain, build=build))


def _run(tmp_path, script, *, calls=5, fmt="n3"):
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048, notes_format=fmt) as (
            fake, url, s):
        for k in range(calls):
            _queue(fake, f"answer {k}", script)
            _queue(fake, f"answer {k}", script)
            assert post(url, _body(_messages(_turns(k)))).status_code == 200
            fake._script.clear()
    return fake, s


def _refreshes(fake):
    return [i for i, r in enumerate(fake.requests)
            if "[palimnesis notes request]" in str(json.loads(r.body)["messages"][-1].get("content"))]


def _notes_block(fake, k):
    return next(m["content"] for m in _sent(fake, k) if "palimnesis notes" in str(m.get("content")))


def test_an_n3_refresh_sends_the_n3_prompt_and_names_n3_in_the_policy(tmp_path):
    fake, s = _run(tmp_path, [V1], calls=1)
    expected = notes_prompt(ViewPolicy(notes_tokens=2048, notes_format="n3"))
    assert _sent(fake, _refreshes(fake)[0])[-1] == {"role": "user", "content": expected}
    [(policy,)] = rows(s, "SELECT policy_version FROM view_versions ORDER BY n DESC LIMIT 1")
    assert policy.endswith("+notes2048n3")


def test_n3_keeps_a_dead_end_the_rewrite_left_out(tmp_path):
    fake, s = _run(tmp_path, [V1, V2], calls=3)
    versions = [v for v in _notes_rows(s) if v[1] == "committed"]
    assert [n for n, *_ in versions[:2]] == [1, 2]
    v2_text = versions[1][3]
    assert WARN in v2_text and "- None new." in v2_text
    # The call after the second refresh carries the warning, verbatim, in the notes block.
    second = _refreshes(fake)[1]
    block = _notes_block(fake, second + 1)
    assert WARN in block and "v2" in block
    assert tokens.default().count_cached(block) <= 2048
    # The archive keeps the raw reply; the event counts the carried line, without text.
    [(content,)] = rows(s, "SELECT content FROM notes_outputs o JOIN notes_versions v"
                           " ON v.notes_id = o.notes_id WHERE v.n = 2")
    assert bytes(content).decode("utf-8") == V2
    events = [json.loads(p) for (p,) in rows(
        s, "SELECT payload FROM events WHERE kind = 'notes_version' ORDER BY event_id")]
    assert [e.get("carried") for e in events[:2]] == [0, 1]
    assert all(WARN not in json.dumps(e) for e in events)


def test_n3_failed_refresh_keeps_the_previous_notes_with_the_warning(tmp_path):
    fake, s = _run(tmp_path, [V1, 503], calls=3)
    statuses = [status for _, status, _, _ in _notes_rows(s)]
    assert statuses[0] == "committed" and statuses[1] == "failed"
    second = _refreshes(fake)[1]
    assert WARN in _notes_block(fake, second + 1) and "v1" in _notes_block(fake, second + 1)


def test_n2_still_lets_a_rewrite_drop_a_dead_end(tmp_path):
    fake, s = _run(tmp_path, [V1, V2], calls=3, fmt="n2")
    assert _notes_rows(s)[1][3] == V2
    assert WARN not in _notes_block(fake, _refreshes(fake)[1] + 1)


def test_n3_carries_from_the_version_in_force_across_a_failed_refresh(tmp_path):
    fake, s = _run(tmp_path, [V1, 503, V2], calls=4)
    versions = _notes_rows(s)
    statuses = [status for _, status, _, _ in versions]
    assert statuses[:2] == ["committed", "failed"]
    later = [v for v in versions[2:] if v[1] == "committed"]
    assert later, statuses  # a later refresh committed
    assert WARN in later[0][3] and "- None new." in later[0][3]


def test_an_n3_session_has_no_unexplained_prefix_change(tmp_path):
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "eval"))
    import replay  # noqa: E402

    sys.path.remove(str(root / "eval"))
    fake, s = _run(tmp_path, [V1, V2], calls=3)
    report = replay.explain(s.db_path)
    assert report["summary"]["unexplained"] == 0
    causes = {c for p in report["pairs"] for c in p["cause"].split(",")}
    assert {"state_refresh", "state_commit"} <= causes


def test_the_event_counts_carried_lines_left_out(tmp_path):
    fake, s = _run(tmp_path, [V1, V2], calls=3)
    events = [json.loads(p) for (p,) in rows(
        s, "SELECT payload FROM events WHERE kind = 'notes_version' ORDER BY event_id")]
    assert all("carry_left_out" in e for e in events if e.get("status") == "committed")
    assert events[1]["carry_left_out"] == 0


# --- D137: a reworded lead-in does not duplicate a quoted dead end -----------------------

QUOTE = '"we already tried `round()` for each share, and it failed because the shares did not add up"'


def test_a_quoted_dead_end_under_a_new_lead_in_is_not_carried_again():
    previous = f"Dead ends\n- User, in their own words: {QUOTE}."
    reply = f"Dead ends\n- User (their own words): {QUOTE}. Plain rounding is ruled out."
    merged, _, carried, _ = carry_dead_ends([previous], reply, _all)
    assert carried == 0 and merged == reply
    assert merged.count("we already tried") == 1


def test_a_quoted_dead_end_the_reply_left_out_is_still_carried():
    previous = f"Dead ends\n- User, in their own words: {QUOTE}."
    reply = "Dead ends\n- Plain `round()` is ruled out."  # a paraphrase never replaces the quote
    merged, _, carried, _ = carry_dead_ends([previous], reply, _all)
    assert carried == 1 and QUOTE in merged


def test_short_quotes_and_unquoted_lines_still_match_whole():
    previous = 'Dead ends\n- tried "fast" mode: it hung'
    reply = 'Dead ends\n- the "fast" mode hung'  # a short quote is not a signature
    merged, _, carried, _ = carry_dead_ends([previous], reply, _all)
    assert carried == 1
