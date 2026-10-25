"""Query policy q1 for proactive recall (docs/plans/phase3.md §2, D28)."""

from __future__ import annotations

import random
import sqlite3

import pytest

from palimnesis.recall import QUERY_VERSION, build_query


def test_code_punctuation_becomes_phrases_of_tokenizer_subtokens():
    q = build_query("Why does parse_config fail on src/app/main.py with E-1234?")

    assert q.terms[:3] == ("parse config", "src app main py", "e 1234")
    assert q.match.startswith('"parse config" OR "src app main py" OR "e 1234"')


def test_code_like_terms_come_first_then_words_in_order_of_first_occurrence():
    q = build_query("please fix the flaky retry logic in fetchUser and the 404 handler")

    assert q.terms == ("fetchuser", "404", "fix", "flaky", "retry", "logic", "handler")


def test_backticked_text_is_code_like():
    q = build_query("rename the `widget` helper")

    assert q.terms == ("widget", "rename", "helper")


def test_fts_operators_in_user_text_are_quoted_literally():
    q = build_query('NEAR(alpha beta) OR gamma* AND ^delta "quoted" col:value -x')

    # ":" alone is not code (D28 as amended): plain words in first-occurrence order.
    assert q.terms == ("near", "alpha", "beta", "gamma", "delta", "quoted", "col value")
    assert q.match == ('"near" OR "alpha" OR "beta" OR "gamma" OR "delta" OR "quoted"'
                       ' OR "col value"')


def test_query_strings_never_raise_fts_syntax_errors():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE t USING fts5(text)")
    conn.execute("INSERT INTO t VALUES ('alpha beta gamma')")
    alphabet = 'abcXYZ019 _-./:#@"*^()[]{}+!?,;`\'\\\n\tñé日本'
    rng = random.Random(7)
    for _ in range(2000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
        q = build_query(text)
        if q.match:
            conn.execute("SELECT count(*) FROM t WHERE t MATCH ?", (q.match,)).fetchone()


def test_stopwords_single_letters_and_single_digits_are_dropped():
    q = build_query("ok so can you please continue with it 5 x")

    assert q.terms == ()
    assert q.match == ""
    assert q.reason == "empty_query"


@pytest.mark.parametrize("text", ["", "   ", "continue", "Continue.", "ok thanks!", "?!"])
def test_empty_and_filler_messages_have_an_empty_query(text):
    assert build_query(text).reason == "empty_query"


def test_terms_are_deduplicated_and_capped_at_32():
    words = " ".join(f"term{i} plain{i}word" for i in range(40))
    q = build_query(words + " term0 TERM1")

    assert len(q.terms) == 32
    assert q.terms[0] == "term0" and q.terms.count("term1") == 1


def test_long_messages_use_the_head_and_tail_only():
    middle = "middleword " * 5000
    q = build_query("headword " + middle + " tailword")

    assert "headword" in q.terms and "tailword" in q.terms
    assert "middleword" in q.terms  # inside the first 12,000 code points
    hidden = build_query("x " * 7000 + "hiddenword " + "y " * 3000)
    assert "hiddenword" not in hidden.terms  # past the head, before the tail


def test_version_is_frozen():
    assert QUERY_VERSION == "q1"
