"""Working-notes header h2 (D75): ``serve --notes TOKENS --notes-header h2``.

The notes block's header adds one sentence asking the model to quote values from the
notes in full (R38-E). h1 keeps D72's header; the slot fit counts the header in use."""

from __future__ import annotations

import pytest

from palimnesis.config import Settings
from palimnesis.upstreams import strata
from palimnesis.upstreams.strata import tokens
from palimnesis.view import NOTES_HEADERS, notes_block
from palimnesis.viewengine import ViewEngine

from .test_notes_http import BUDGET, _body, _messages, _notes_rows, _sent
from .test_notes_n2_http import _notes
from .test_view_http import post, rows, view_stack

H2 = dict(input_budget=BUDGET, notes_tokens=2048, notes_format="n2", notes_header="h2")

H1_BLOCK = ("[palimnesis notes · v4 · your own working notes from earlier in this conversation; "
            "the user's messages win]\n\nObjective: finish.")
H2_BLOCK = ("[palimnesis notes · v4 · your own working notes from earlier in this conversation; "
            "the user's messages win. When you quote a value from these notes, write it out in "
            "full, exactly as recorded]\n\nObjective: finish.")


def test_h1_is_d72s_header_and_the_default():
    assert NOTES_HEADERS == ("h1", "h2")
    assert notes_block(4, "Objective: finish.") == H1_BLOCK
    assert notes_block(4, "Objective: finish.", "h1") == H1_BLOCK
    assert Settings(upstream_base_url="http://x").notes_header == "h1"


def test_h2_adds_the_quote_in_full_sentence_inside_the_header():
    assert notes_block(4, "Objective: finish.", "h2") == H2_BLOCK


def test_an_unknown_header_is_refused():
    with pytest.raises(ValueError, match="notes header"):
        notes_block(1, "x", "h9")


def test_an_unknown_header_is_refused_when_the_engine_starts():
    with pytest.raises(ValueError, match="notes header"):
        ViewEngine(strata.profile("http://127.0.0.1:1"), notes_tokens=2048, notes_header="h9")


def test_an_h2_view_renders_the_h2_block(tmp_path):
    with view_stack(tmp_path, **H2) as (fake, url, s):
        fake.respond_counted(_notes(2))
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    [(_, status, _, text)] = _notes_rows(s)
    assert status == "committed"
    assert {"role": "user", "content": notes_block(1, text, "h2")} in _sent(fake, 1)


def test_the_policy_version_names_the_header(tmp_path):
    with view_stack(tmp_path, **H2) as (fake, url, s):
        fake.respond_counted(_notes(2))
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    [(policy,)] = rows(s, "SELECT policy_version FROM view_versions ORDER BY n DESC LIMIT 1")
    assert policy.endswith("+notes2048n2h2")


@pytest.mark.parametrize("header, outcome", [("h1", ("committed", None)),
                                              ("h2", ("failed", "too_long"))])
def test_the_slot_fit_counts_the_header_in_use(tmp_path, header, outcome):
    """A slot with room for the h1 header and a line, but not for the longer h2 header."""
    counter = tokens.default()
    h1 = counter.count_cached(notes_block(999_999, ""))
    h2 = counter.count_cached(notes_block(999_999, "", "h2"))
    assert h2 - h1 >= 10
    slot = h1 + 8 + (h2 - h1) // 2  # 8: the block's own template tokens, which the fit reserves
    with view_stack(tmp_path, **dict(H2, notes_tokens=slot, notes_header=header)) as (fake, url, s):
        fake.respond_counted(_notes(2))
        fake.respond_counted("visible answer")
        assert post(url, _body(_messages())).status_code == 200

    [(_, status, reason, _)] = _notes_rows(s)
    assert (status, reason) == outcome


def test_serve_takes_the_notes_header_flag(tmp_path):
    from palimnesis.cli import serve_settings

    base = ["--upstream", "http://u:8080", "--db", str(tmp_path / "a.db")]
    assert serve_settings(base).notes_header == "h2"  # the shipped default since D78
    assert serve_settings(base + ["--notes-header", "h1"]).notes_header == "h1"
    with pytest.raises(SystemExit):
        serve_settings(base + ["--notes-header", "h9"])
