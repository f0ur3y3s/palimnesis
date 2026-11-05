"""ho4-t4: ten-pin bowling scores, league handicap and score-sheet notation (fourth held-out
task set).

A1 categories: information needs discovered mid-task (turn 5 needs the handicap rules H-2
and H-4 and turn 7 the notation rule N-1, all from the reference document read in turn 2
and named only by reference); irrelevant retrieval matches (the document carries a
superseded 2019 handicap rule and an appendix of other leagues' handicap bases and
percentages); an oversized read; restart before turn 5.
"""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho4-t4"
SET = "heldout4"
TITLE = "tenpin: frame-by-frame bowling scores, league handicap, score-sheet notation"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "invalid input raises GameError from tenpin/errors.py with .frame set to the 1-based "
          "frame where the problem is, 11 for rolls after the game is over, and None for a "
          "problem that is not in a frame",
    "C2": "no function changes the rolls it is given, and rolls may come as a list or a tuple",
    "C3": "partial games are allowed: only frames whose score is already known count, and the "
          "running totals stop at the first frame that cannot be scored yet",
}
TRAP = ("already tried summing all the rolls and adding ten for every strike and spare; it "
        "failed because the bonus is the pins of the next rolls rather than a flat ten, and "
        "the tenth frame's bonus balls were counted twice")


def lane_pair(lane: int) -> str:
    first = lane if lane % 2 else lane - 1
    return f"{first}-{first + 1}"


LEGACY = '''"""Lane pairs for the house display (do not change)."""


def lane_pair(lane: int) -> str:
    first = lane if lane % 2 else lane - 1
    return f"{first}-{first + 1}"
'''

ERRORS = '''"""Errors."""


class GameError(ValueError):
    """An impossible game. ``frame`` says where the problem is."""

    def __init__(self, frame, message):
        super().__init__(f"frame {frame}: {message}")
        self.frame = frame
'''

STUB = '''"""Bowling scores. See docs/league_handbook.md."""

from .errors import GameError  # noqa: F401


def frame_scores(rolls):
    """Running totals, one per frame that can be scored."""
    raise NotImplementedError


def score_game(rolls):
    """The total of the frames that can be scored."""
    raise NotImplementedError


def handicap(average):
    """The league handicap for a bowler's average."""
    raise NotImplementedError


def with_handicap(rolls, average):
    """The score with handicap."""
    raise NotImplementedError


def parse_sheet(text):
    """One score-sheet line -> the list of rolls."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tenpin.game import score_game  # noqa: E402


class GameTests(unittest.TestCase):
    def test_gutter_game(self):
        self.assertEqual(score_game([0] * 20), 0)

    def test_all_ones(self):
        self.assertEqual(score_game([1] * 20), 20)
'''

DOC_INTRO = [
    "The rules the Thursday league scores by, as of the 2026 season.",
    "",
    "## Frames and scoring (S-1 to S-4)",
    "",
    "- S-1: a game is ten frames. In frames 1 to 9 the bowler has two balls to knock down",
    "  ten pins; a frame never has more than ten pins in total.",
    "- S-2: a strike (all ten with the first ball) ends the frame and scores 10 plus the",
    "  pins of the next two balls. A spare (all ten with two balls) scores 10 plus the pins",
    "  of the next ball. Any other frame scores the pins knocked down.",
    "- S-3: the tenth frame has bonus balls: after a strike two more balls, after a spare",
    "  one more. The pins are reset after each strike or spare in the tenth, so the tenth",
    "  scores at most 30. After an open tenth frame the game is over.",
    "- S-4: a frame's score is known once its own balls and its bonus balls have been",
    "  rolled. The sheet shows a running total for every frame up to the first one whose",
    "  score is not known yet.",
    "",
    "## Handicap (H-1 to H-4)",
    "",
    "- H-1: a bowler's average is a whole number from 0 to 300.",
    "- H-2: the handicap is 90 percent of the difference between the basis of 220 and the",
    "  bowler's average, rounded down to a whole pin. A bowler averaging 220 or more gets",
    "  no handicap.",
    "- H-3: the 2019 rule (80 percent of the difference to a basis of 200) was replaced by",
    "  H-2 in 2024 and no longer applies.",
    "- H-4: the handicap is added to the score of a finished game only. An unfinished game",
    "  counts its pins with no handicap.",
    "",
    "## Score-sheet notation (N-1)",
    "",
    "- N-1: one character per ball. `X` is a strike, `/` a spare (the pins left standing by",
    "  the previous ball of the frame), `-` a miss (no pins), `F` a foul (no pins) and the",
    "  digits 1 to 9 that many pins. `x` and `f` are accepted too. Spaces and `|` between",
    "  balls are ignored. A ball written as a digit, `-` or `F` must leave at least one pin",
    "  standing; clearing the rest of the pins is written `/`. `X` is only possible with all",
    "  ten pins standing, and `/` only when the ball before it left some standing.",
    "",
    "## Retired: the 2012 sheet",
    "",
    "- The 2012 sheets wrote `S` for a strike and `P` for a spare and used `0` for a miss.",
    "  Nothing reads them now.",
]

LEAGUES = ["Riverside Tuesday", "Northgate Seniors", "Harbour Mixed", "Elm Street Juniors",
           "Westfield Scratch", "Lakeside Monday", "Oakwood Trios", "Hillcrest Doubles"]


def _record(rnd: random.Random, i: int) -> str:
    return (f"{rnd.choice(LEAGUES)} league | handicap {rnd.choice([70, 75, 80, 85, 95, 100])} "
            f"percent of {rnd.choice([200, 205, 210, 215, 225, 230])}, season {rnd.randint(2008, 2025)}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        lane = rnd.randint(1, 48)
        slug = rnd.choice(["odd_lane", "even_lane", "house_display", "end_lane"])
        cases.append((slug, repr(lane), repr(lane_pair(lane))))
    return {
        "tenpin/__init__.py": '"""Bowling scores for the Thursday league."""\n',
        "tenpin/errors.py": ERRORS,
        "tenpin/legacy.py": LEGACY,
        "tenpin/game.py": STUB,
        "docs/league_handbook.md": long_doc(rnd, "Thursday league handbook", DOC_INTRO, _record),
        "tests/test_game.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("tenpin.legacy", "lane_pair",
                                                      "LanePairCatalogTests", cases),
    }


TURNS = [
    "Today's job is `tenpin`, which scores games for our Thursday bowling league. "
    "Requirements: (1) invalid input raises GameError from tenpin/errors.py with `.frame` set "
    "to the 1-based frame where the problem is, 11 for rolls after the game is over, and None "
    "for a problem that is not in a frame; (2) no function changes the rolls it is given, and "
    "rolls may come as a list or a tuple; (3) partial games are allowed: only frames whose "
    "score is already known count, and the running totals stop at the first frame that "
    "cannot be scored yet. We already tried summing all the rolls and adding ten for every "
    "strike and spare, and it failed because the bonus is the pins of the next rolls rather "
    "than a flat ten, and the tenth frame's bonus balls were counted twice. First read "
    "tenpin/game.py and tenpin/errors.py and tell me what is missing; do not change anything "
    "yet. " + NO_QUESTIONS,
    "Read docs/league_handbook.md all the way through, all of its roughly 300 lines, until "
    "the line 'End of document.', and give me its rules in five bullet points.",
    "Implement `frame_scores(rolls)`, the running total after each frame, and "
    "`score_game(rolls)`, following the scoring rules in the handbook. Then run `python -m "
    "unittest tests.test_game -v`.",
    "Run the full suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and what failed.",
    "Now the league handicap: add `handicap(average)` and `with_handicap(rolls, average)`, "
    "the score with handicap, following the handbook's current handicap rules. Add tests for "
    "them and run `python -m unittest tests.test_game -v`.",
    "Run the full suite verbosely again (`python -m unittest discover -s tests -v`) and "
    "report the numbers.",
    "The lane computers export score sheets in the handbook's notation. Write "
    "`parse_sheet(text)`, which turns one sheet line into the list of rolls, following the "
    "notation rule. Add tests and run `python -m unittest tests.test_game -v`.",
    "Wrap up: run `python -m unittest discover -s tests` one more time and list what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tenpin.errors import GameError  # noqa: E402
from tenpin.game import frame_scores, handicap, parse_sheet, score_game, with_handicap  # noqa: E402

EXAMPLE = [10, 7, 3, 9, 0, 10, 0, 8, 8, 2, 0, 6, 10, 10, 10, 8, 1]
EXAMPLE_TOTALS = [20, 39, 48, 66, 74, 84, 90, 120, 148, 167]


class HiddenTests(unittest.TestCase):
    def test_f_score(self):
        self.assertEqual(score_game([10] * 12), 300)
        self.assertEqual(score_game([5] * 21), 150)
        self.assertEqual(score_game([9, 0] * 10), 90)
        self.assertEqual(score_game([0] * 20), 0)
        self.assertEqual(score_game(EXAMPLE), 167)
        self.assertEqual(frame_scores(EXAMPLE), EXAMPLE_TOTALS)
        self.assertEqual(frame_scores([10] * 12), [30 * k for k in range(1, 11)])
        self.assertEqual(score_game([0] * 18 + [10, 7, 3]), 20)
        self.assertEqual(score_game([0] * 18 + [3, 7, 10]), 20)
        self.assertEqual(score_game([0] * 18 + [10, 10, 10]), 30)
        self.assertEqual(score_game([10, 3, 4]), 24)
        self.assertEqual(frame_scores([10, 3, 4]), [17, 24])

    def test_f_invalid(self):
        for rolls in ([11], [5, 6], [-1], [3, 2.0], [True], [0] * 20 + [5], [10] * 13,
                      [0] * 18 + [5, 6], [0] * 18 + [7, 2, 1], [0] * 18 + [10, 5, 6], ["5"]):
            with self.assertRaises(GameError, msg=repr(rolls)):
                frame_scores(rolls)
            with self.assertRaises(GameError, msg=repr(rolls)):
                score_game(rolls)

    def test_f_handicap(self):
        self.assertEqual(handicap(150), 63)
        self.assertEqual(handicap(171), 44)
        self.assertEqual(handicap(219), 0)
        self.assertEqual(handicap(220), 0)
        self.assertEqual(handicap(250), 0)
        self.assertEqual(handicap(0), 198)
        self.assertEqual(handicap(120), 90)
        self.assertEqual(with_handicap([10] * 12, 150), 363)
        self.assertEqual(with_handicap(EXAMPLE, 171), 211)
        self.assertEqual(with_handicap([5] * 21, 230), 150)
        self.assertEqual(with_handicap([10, 3, 4], 150), 24)
        self.assertEqual(with_handicap([9, 0] * 9 + [9], 100), 81)
        for bad in (-1, 301, 150.5, "150", None, True):
            with self.assertRaises(GameError, msg=repr(bad)):
                handicap(bad)

    def test_f_sheet(self):
        self.assertEqual(parse_sheet("X X X X X X X X X XXX"), [10] * 12)
        self.assertEqual(parse_sheet("9- 9- 9- 9- 9- 9- 9- 9- 9- 9-"), [9, 0] * 10)
        self.assertEqual(parse_sheet("X|7/|9-|X|-8|8/|-6|X|X|X81"), EXAMPLE)
        self.assertEqual(parse_sheet("5/5/5/5/5/5/5/5/5/5/5"), [5] * 21)
        self.assertEqual(parse_sheet("F/ 9-"), [0, 10, 9, 0])
        self.assertEqual(parse_sheet("x 7/ f2"), [10, 7, 3, 0, 2])
        self.assertEqual(parse_sheet("-- -- -- -- -- -- -- -- -- X7/"), [0] * 18 + [10, 7, 3])
        self.assertEqual(parse_sheet("-- -- -- -- -- -- -- -- -- 6/X"), [0] * 18 + [6, 4, 10])
        self.assertEqual(parse_sheet(""), [])
        for bad in ("/5", "9-X/", "64", "9-9-9-9-9-9-9-9-9-9-5", "9-?", "7X", "-- -- -- -- -- -- -- -- -- X7X",
                    "S", "0"):
            with self.assertRaises(GameError, msg=bad):
                parse_sheet(bad)

    def test_c1_frames(self):
        cases = [(1, lambda: frame_scores([11])), (1, lambda: frame_scores([5, 6])),
                 (2, lambda: frame_scores([10, 5, 6])), (1, lambda: frame_scores([-1])),
                 (1, lambda: frame_scores([3, 2.0])), (1, lambda: score_game([True])),
                 (3, lambda: score_game([1, 2, 3, 4, "5"])),
                 (11, lambda: frame_scores([0] * 20 + [5])), (11, lambda: score_game([10] * 13)),
                 (10, lambda: frame_scores([0] * 18 + [10, 5, 6])),
                 (11, lambda: frame_scores([0] * 18 + [7, 2, 1])),
                 (10, lambda: frame_scores([0] * 18 + [5, 6])),
                 (None, lambda: handicap(301)), (None, lambda: handicap(-1)),
                 (None, lambda: handicap(150.5)), (None, lambda: with_handicap([0] * 20, 400)),
                 (1, lambda: parse_sheet("/5")), (3, lambda: parse_sheet("9-X/")),
                 (1, lambda: parse_sheet("64")), (11, lambda: parse_sheet("9-9-9-9-9-9-9-9-9-9-5")),
                 (2, lambda: parse_sheet("9-?")), (1, lambda: parse_sheet("7X")),
                 (10, lambda: parse_sheet("-- -- -- -- -- -- -- -- -- X7X")),
                 (4, lambda: parse_sheet("X X X S"))]
        for frame, call in cases:
            with self.assertRaises(GameError) as cm:
                call()
            self.assertEqual(cm.exception.frame, frame)

    def test_c2_rolls_untouched(self):
        rolls = list(EXAMPLE)
        frame_scores(rolls)
        score_game(rolls)
        with_handicap(rolls, 150)
        self.assertEqual(rolls, EXAMPLE)
        partial = [10, 10, 3]
        frame_scores(partial)
        score_game(partial)
        self.assertEqual(partial, [10, 10, 3])
        self.assertEqual(score_game(tuple(EXAMPLE)), 167)
        self.assertEqual(frame_scores(tuple(EXAMPLE)), EXAMPLE_TOTALS)
        self.assertEqual(with_handicap(tuple([10] * 12), 200), 318)

    def test_c3_partial(self):
        self.assertEqual(frame_scores([]), [])
        self.assertEqual(frame_scores([10]), [])
        self.assertEqual(frame_scores([10, 10]), [])
        self.assertEqual(frame_scores([10, 10, 10]), [30])
        self.assertEqual(frame_scores([3]), [])
        self.assertEqual(frame_scores([3, 4]), [7])
        self.assertEqual(frame_scores([5, 5]), [])
        self.assertEqual(frame_scores([5, 5, 3]), [13])
        self.assertEqual(frame_scores([10] * 11), [30 * k for k in range(1, 10)])
        self.assertEqual(frame_scores([10, 3]), [])
        self.assertEqual(score_game([5, 5, 3]), 13)
        self.assertEqual(score_game([]), 0)
        self.assertEqual(score_game([10, 10]), 0)
        self.assertEqual(score_game([10] * 11), 270)


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"tenpin/game.py": '''"""Bowling scores. See docs/league_handbook.md."""

from .errors import GameError

BASIS = 220


def _pins(value, frame):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10:
        raise GameError(frame, f"not a number of pins: {value!r}")
    return value


def _frames(rolls):
    """Validated frames, each a list of its own balls (the tenth with its bonus balls)."""
    rolls = list(rolls)
    frames, i = [], 0
    for frame in range(1, 11):
        if i >= len(rolls):
            break
        a = _pins(rolls[i], frame)
        if frame < 10:
            if a == 10 or i + 1 >= len(rolls):
                frames.append([a])
                i += 1
                continue
            b = _pins(rolls[i + 1], frame)
            if a + b > 10:
                raise GameError(frame, "more than ten pins")
            frames.append([a, b])
            i += 2
            continue
        balls = [a]
        if i + 1 < len(rolls):
            b = _pins(rolls[i + 1], 10)
            if a < 10 and a + b > 10:
                raise GameError(10, "more than ten pins")
            balls.append(b)
            if i + 2 < len(rolls) and (a == 10 or a + b == 10):
                c = _pins(rolls[i + 2], 10)
                if a == 10 and b < 10 and b + c > 10:
                    raise GameError(10, "more than ten pins")
                balls.append(c)
        frames.append(balls)
        i += len(balls)
    if i < len(rolls):
        raise GameError(11, "rolls after the game is over")
    return frames


def frame_scores(rolls):
    frames = _frames(rolls)
    flat = [p for f in frames for p in f]
    totals, total, pos = [], 0, 0
    for k, f in enumerate(frames):
        if k == 9:
            done = len(f) == 3 or (len(f) == 2 and sum(f) < 10)
            if not done:
                break
            total += sum(f)
        elif f[0] == 10:
            if pos + 2 >= len(flat):
                break
            total += 10 + flat[pos + 1] + flat[pos + 2]
        elif len(f) < 2:
            break
        elif sum(f) == 10:
            if pos + 2 >= len(flat):
                break
            total += 10 + flat[pos + 2]
        else:
            total += sum(f)
        totals.append(total)
        pos += len(f)
    return totals


def score_game(rolls):
    totals = frame_scores(rolls)
    return totals[-1] if totals else 0


def handicap(average):
    if isinstance(average, bool) or not isinstance(average, int) or not 0 <= average <= 300:
        raise GameError(None, f"not an average: {average!r}")
    return max(BASIS - average, 0) * 9 // 10


def with_handicap(rolls, average):
    h = handicap(average)
    totals = frame_scores(rolls)
    if len(totals) == 10:
        return totals[-1] + h
    return totals[-1] if totals else 0


def parse_sheet(text):
    rolls, frame, standing, ball, fresh = [], 1, 10, 0, True
    for c in text:
        if c in " |":
            continue
        if frame > 10:
            raise GameError(11, "balls after the game is over")
        u = c.upper()
        if u == "X":
            if not fresh:
                raise GameError(frame, "a strike needs a fresh rack")
            pins = 10
        elif c == "/":
            if fresh:
                raise GameError(frame, "a spare needs a ball before it")
            pins = standing
        elif c in "-123456789" or u == "F":
            pins = 0 if c == "-" or u == "F" else int(c)
            if pins >= standing:
                raise GameError(frame, "clearing the pins is written /")
        else:
            raise GameError(frame, f"not a ball: {c!r}")
        rolls.append(pins)
        ball += 1
        standing -= pins
        fresh = False
        if frame < 10:
            if standing == 0 or ball == 2:
                frame, standing, ball, fresh = frame + 1, 10, 0, True
        else:
            if standing == 0:
                standing, fresh = 10, True
            if ball == 3 or (ball == 2 and sum(rolls[-2:]) < 10):
                frame = 11
    return rolls
'''}
