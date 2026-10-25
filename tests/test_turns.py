"""Turn numbering shared by excerpt headers and transcript files (A1)."""

from __future__ import annotations

from palimnesis.turns import turn_numbers


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
