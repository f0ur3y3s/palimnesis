"""Turn numbering shared by excerpt headers and transcript files (A1)."""

from __future__ import annotations

from palimnesis.archive.turns import turn_numbers


def test_each_genuine_user_message_starts_a_turn_and_others_belong_to_it():
    seq_roles = [(1, "system"), (2, "user"), (3, "assistant"), (4, "tool"), (5, "assistant"),
                 (6, "user"), (7, "assistant")]

    assert turn_numbers(seq_roles) == {1: 0, 2: 1, 3: 1, 4: 1, 5: 1, 6: 2, 7: 2}


def test_numbering_follows_seq_order_not_input_order():
    assert turn_numbers([(5, "user"), (2, "user"), (9, "assistant")]) == {2: 1, 5: 2, 9: 2}


def test_messages_before_the_first_instruction_are_turn_zero():
    assert turn_numbers([(1, "system"), (2, "assistant")]) == {1: 0, 2: 0}


def test_synthetic_continue_messages_do_not_start_a_turn():
    cont = ("The previous response was interrupted. Continue from where you left off "
            "without repeating completed content.")
    seq_roles = [(1, "user"), (2, "assistant"), (3, "user")]

    assert turn_numbers(seq_roles, texts={3: cont}) == {1: 1, 2: 1, 3: 1}


# OpenCode 2.1.4's follow-up after a ``length`` stop, verbatim from the recorded fixture
# (eval/fixtures/opencode-2.1.4/hidden_stream/b_length_text/req-03.json; S10b F3 / D67).
LENGTH_FOLLOW_UP = ("Your last response hit the output token limit (stop reason: length). Do not "
                    "apologize, recap, or repeat yourself. Break the remaining work into smaller "
                    "pieces.")


def test_the_length_follow_up_is_not_an_instruction():
    from palimnesis.archive.turns import is_instruction

    assert is_instruction("user", LENGTH_FOLLOW_UP) is False
    # The recorded prefix is the marker; the rest of OpenCode's wording may vary.
    assert is_instruction("user", "Your last response hit the output token limit "
                                  "(stop reason: length). Keep going.") is False
    assert is_instruction("user", "Your last response was great.") is True


def test_the_length_follow_up_does_not_start_a_turn():
    seq_roles = [(1, "user"), (2, "assistant"), (3, "user"), (4, "assistant"), (5, "user")]

    numbers = turn_numbers(seq_roles, texts={1: "fix it", 3: LENGTH_FOLLOW_UP, 5: "next"})

    assert numbers == {1: 1, 2: 1, 3: 1, 4: 1, 5: 2}
