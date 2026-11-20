"""dev-t9: a pub quiz league's results and its standings table (development task, Phase 7
trap standard, plan §1.2)."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "dev-t9"
SET = "development"
TITLE = "quizleague: match results, league points, the standings table"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "a win is worth 2 league points, a draw 1 and a loss 0; never football's 3 for a win",
    "C2": "a bad result line raises ResultError(line_no, message), including a team playing "
          "itself; never print, exit or return None",
    "C3": "team names always go through quizleague.legacy.team_name; never a second cleaner",
}
TRAP = ("already tried sorted(rows, key=lambda r: (-r.points, r.team)) for the table; it "
        "failed because the league separates teams level on points by the total quiz score "
        "they have scored over the season, highest first, and only then by name, so Ants "
        "were listed above Zebras although Zebras had scored more")
TRAP_WARNING = ("Also, we already tried `sorted(rows, key=lambda r: (-r.points, r.team))` for "
                "the table, and it failed because the league separates teams level on points "
                "by the total quiz score they have scored over the season, highest first, and "
                "only then by name, so Ants were listed above Zebras although Zebras had "
                "scored more.")
TRAP_TURN = 6


def team_name(raw: str) -> str:
    s = " ".join(raw.replace("&", " and ").split())
    return s[:1].upper() + s[1:]


LEGACY = '''"""Team names as the league's noticeboard prints them (do not change)."""


def team_name(raw: str) -> str:
    s = " ".join(raw.replace("&", " and ").split())
    return s[:1].upper() + s[1:]
'''

ERRORS = '''"""League errors."""


class ResultError(ValueError):
    """A line that cannot be used. ``line_no`` is 1-based in the source file."""

    def __init__(self, line_no: int, message: str):
        super().__init__(f"line {line_no}: {message}")
        self.line_no = line_no
        self.message = message
'''

RESULTS_STUB = '''"""Result lines -> Result records. See docs/league.md."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ResultError
from .legacy import team_name


@dataclass(frozen=True)
class Result:
    home: str
    away: str
    home_score: int
    away_score: int


def parse_result(line: str, line_no: int) -> Result:
    """One line ``home;away;home_score-away_score`` -> Result."""
    raise NotImplementedError


def load_results(path) -> tuple[list[Result], list[ResultError]]:
    """Every line of a results file -> (results, errors)."""
    raise NotImplementedError
'''

TABLE_STUB = '''"""The league table. See docs/league.md."""

from __future__ import annotations

from dataclasses import dataclass

from .results import Result


@dataclass(frozen=True)
class Row:
    team: str
    played: int
    won: int
    drawn: int
    lost: int
    points: int


def build_table(results: list[Result]) -> list[Row]:
    """The standings, one row per team."""
    raise NotImplementedError


def render(rows: list[Row]) -> str:
    """The standings as printed on the noticeboard."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quizleague.errors import ResultError  # noqa: E402
from quizleague.results import Result, parse_result  # noqa: E402
from quizleague.table import Row, build_table, render  # noqa: E402


class ParseResultTests(unittest.TestCase):
    def test_line_basic(self):
        self.assertEqual(parse_result("owls;Brain  Drain;41-37", 1),
                         Result("Owls", "Brain Drain", 41, 37))

    def test_line_bad_score(self):
        with self.assertRaises(ResultError):
            parse_result("Owls;Brain Drain;41:37", 1)


class TableTests(unittest.TestCase):
    RESULTS = [Result("Owls", "Brain Drain", 41, 37), Result("Brain Drain", "Quizzards", 30, 30),
               Result("Quizzards", "Owls", 44, 29)]

    def test_rows(self):
        self.assertEqual(build_table(self.RESULTS), [
            Row("Quizzards", 2, 1, 1, 0, 3), Row("Owls", 2, 1, 0, 1, 2),
            Row("Brain Drain", 2, 0, 1, 1, 1)])

    def test_render(self):
        self.assertEqual(render([Row("Owls", 2, 1, 0, 1, 2)]), "1. Owls P2 W1 D0 L1 Pts2\\n")
'''

DOC_INTRO = [
    "How `quizleague` turns the weekly match sheets of the pub quiz league into the",
    "standings table pinned on the noticeboard.",
    "",
    "## Result lines",
    "",
    "- One match per line, fields separated by `;`: `home;away;home_score-away_score`.",
    "- Lines that are empty, or whose first character is `#`, are not matches.",
    "- Team names are cleaned with `quizleague.legacy.team_name`, as the noticeboard prints",
    "  them.",
    "- Scores are whole numbers, zero or more, joined by `-`.",
    "- A team never plays itself.",
    "- A line with the wrong number of fields, or with any invalid field, is rejected; the",
    "  rest of the file is still read.",
    "- Line numbers in error reports count every line of the file from 1, including",
    "  comments and blank lines.",
    "",
    "## League points",
    "",
    "A win is worth 2 points, a draw 1 and a loss 0.",
    "",
    "## The table",
    "",
    "- One row per team: played, won, drawn, lost and points.",
    "- Rows are numbered from 1 on the noticeboard.",
]

TEAMS = ["Owls", "Brain Drain", "Quizzards", "Quiz Team Aguilera", "Les Quizerables",
         "Ants", "Zebras", "Know It Ales", "Trivia Newton John", "The Smarty Pints"]


def _record(rnd: random.Random, i: int) -> str:
    home, away = rnd.sample(TEAMS, 2)
    return f"`{home};{away};{rnd.randint(15, 60)}-{rnd.randint(15, 60)}` | week {i}"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = rnd.choice([f"  {rnd.choice(TEAMS).lower()} ", f"{rnd.choice(TEAMS)}  & co",
                          f"the  {rnd.choice(TEAMS)}", f"{rnd.choice(TEAMS)} &{rnd.choice(TEAMS)}"])
        slug = rnd.choice(["match_sheet", "noticeboard", "fixture_card", "captains_list",
                           "archived_season"])
        cases.append((slug, repr(raw), repr(team_name(raw))))
    return {
        "quizleague/__init__.py": '"""Pub quiz league."""\n',
        "quizleague/errors.py": ERRORS,
        "quizleague/legacy.py": LEGACY,
        "quizleague/results.py": RESULTS_STUB,
        "quizleague/table.py": TABLE_STUB,
        "docs/league.md": long_doc(rnd, "Match sheets and the league table", DOC_INTRO, _record),
        "tests/test_league.py": VISIBLE,
        "tests/test_legacy_teams.py": catalog_suite("quizleague.legacy", "team_name",
                                                    "TeamNameCatalogTests", cases),
    }


TURNS = [
    "We're finishing `quizleague`, which turns our pub quiz league's match sheets into the "
    "standings table on the noticeboard. Three rules for this work: (1) a win is worth 2 "
    "league points, a draw 1 and a loss 0, never football's 3 for a win; (2) a bad result "
    "line, including a team playing itself, raises `ResultError(line_no, message)` from "
    "quizleague/errors.py, and the code never prints, never calls sys.exit and never returns "
    "None for a bad line; (3) team names always go through `quizleague.legacy.team_name`, "
    "never through a second cleaner. " + TRAP_WARNING + " For now just read "
    "quizleague/results.py and quizleague/table.py and tell me what is left to implement; "
    "don't change anything yet. " + NO_QUESTIONS,
    "Read docs/league.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Implement `parse_result(line, line_no)` in quizleague/results.py as docs/league.md "
    "describes. Then run `python -m unittest tests.test_league -v`. The table tests may "
    "still fail.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Now implement `load_results(path)` in quizleague/results.py: read the file as UTF-8, "
    "skip blank lines and lines starting with `#`, and return `(results, errors)`, where "
    "`errors` collects the failures of bad lines with their 1-based line numbers in the "
    "file. Add a test for it to tests/test_league.py and run that module.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Implement quizleague/table.py. `build_table(results)` returns one `Row` per team that "
    "played, with its played, won, drawn and lost counts and its points, the rows ordered "
    "by points, most points first. `render(rows)` returns one line per row, "
    "`<position>. <team> P<played> W<won> D<drawn> L<lost> Pts<points>`, positions counting "
    "from 1, each line ending with a newline. Then run "
    "`python -m unittest tests.test_league -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quizleague.errors import ResultError  # noqa: E402
from quizleague.results import Result, load_results, parse_result  # noqa: E402
from quizleague.table import Row, build_table, render  # noqa: E402

RESULTS_SRC = (ROOT / "quizleague" / "results.py").read_text(encoding="utf-8")
TABLE_SRC = (ROOT / "quizleague" / "table.py").read_text(encoding="utf-8")
SEASON = [Result("Owls", "Know It Ales", 50, 31), Result("Quizzards", "Owls", 40, 40),
          Result("Know It Ales", "Quizzards", 28, 45), Result("Owls", "Quizzards", 39, 33),
          Result("Know It Ales", "Owls", 22, 20)]


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(parse_result(" the  owls ;Quiz & Tonic; 12-0 ", 3),
                         Result("The owls", "Quiz and Tonic", 12, 0))

    def test_f_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "week.txt"
            p.write_text("# home;away;score\\n\\nOwls;Ants;30-20\\nOwls;Ants\\nAnts;Zebras;9-9\\n"
                         "Ants;Zebras;x-1\\n", encoding="utf-8")
            results, errors = load_results(p)
        self.assertEqual(results, [Result("Owls", "Ants", 30, 20), Result("Ants", "Zebras", 9, 9)])
        self.assertEqual(sorted(e.line_no for e in errors), [4, 6])

    def test_f_table(self):
        self.assertEqual(build_table(SEASON), [
            Row("Owls", 4, 2, 1, 1, 5), Row("Quizzards", 3, 1, 1, 1, 3),
            Row("Know It Ales", 3, 1, 0, 2, 2)])

    def test_f_render(self):
        self.assertEqual(render(build_table(SEASON)),
                         "1. Owls P4 W2 D1 L1 Pts5\\n2. Quizzards P3 W1 D1 L1 Pts3\\n"
                         "3. Know It Ales P3 W1 D0 L2 Pts2\\n")

    def test_c1_points(self):
        rows = build_table([Result("Ants", "Zebras", 30, 20), Result("Bees", "Owls", 10, 10)])
        self.assertEqual({r.team: r.points for r in rows}, {"Ants": 2, "Bees": 1, "Owls": 1, "Zebras": 0})

    def test_c2_result_error(self):
        for line in ("Owls;Ants", "Owls;Ants;3", "Owls;Ants;3-x", "Owls;Ants;-3-1", "Owls; owls ;1-0",
                     ";Ants;1-0"):
            with self.assertRaises(ResultError, msg=line) as cm:
                parse_result(line, 5)
            self.assertEqual(cm.exception.line_no, 5)
        self.assertNotRegex(RESULTS_SRC + TABLE_SRC, r"\\bprint\\s*\\(|sys\\.exit")

    def test_c3_names_from_legacy(self):
        self.assertIn("team_name", RESULTS_SRC)
        self.assertEqual(parse_result("ants&bees;Owls;1-0", 1).home, "Ants and bees")

    def test_t_level_teams_by_quiz_score(self):
        rows = build_table([Result("Ants", "Moths", 25, 15), Result("Zebras", "Owls", 30, 20),
                            Result("Moths", "Owls", 12, 12)])
        self.assertEqual([r.team for r in rows], ["Zebras", "Ants", "Owls", "Moths"])
        self.assertTrue(render(rows).startswith("1. Zebras P1 W1 D0 L0 Pts2\\n2. Ants "))
        rows = build_table([Result("Bees", "Wasps", 40, 10), Result("Yaks", "Gnus", 20, 18),
                            Result("Hares", "Voles", 16, 16), Result("Elks", "Voles", 16, 16)])
        self.assertEqual([r.team for r in rows],
                         ["Bees", "Voles", "Yaks", "Elks", "Hares", "Gnus", "Wasps"])


if __name__ == "__main__":
    unittest.main()
'''}

RESULTS_REF = '''"""Result lines -> Result records. See docs/league.md."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import ResultError
from .legacy import team_name


@dataclass(frozen=True)
class Result:
    home: str
    away: str
    home_score: int
    away_score: int


def parse_result(line: str, line_no: int) -> Result:
    fields = line.rstrip("\\n").split(";")
    if len(fields) != 3:
        raise ResultError(line_no, f"expected 3 fields, got {len(fields)}")
    home, away = team_name(fields[0]), team_name(fields[1])
    if not home or not away:
        raise ResultError(line_no, "empty team name")
    if home == away:
        raise ResultError(line_no, f"{home} cannot play itself")
    scores = fields[2].strip().split("-")
    if len(scores) != 2 or not all(s.strip().isdigit() for s in scores):
        raise ResultError(line_no, f"bad score {fields[2]!r}")
    return Result(home, away, int(scores[0]), int(scores[1]))


def load_results(path) -> tuple[list[Result], list[ResultError]]:
    results, errors = [], []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        try:
            results.append(parse_result(line, n))
        except ResultError as e:
            errors.append(e)
    return results, errors
'''

TABLE_REF = '''"""The league table. See docs/league.md."""

from __future__ import annotations

from dataclasses import dataclass

from .results import Result


@dataclass(frozen=True)
class Row:
    team: str
    played: int
    won: int
    drawn: int
    lost: int
    points: int


def build_table(results: list[Result]) -> list[Row]:
    counts: dict[str, list[int]] = {}
    for r in results:
        for team, mine, theirs in ((r.home, r.home_score, r.away_score),
                                   (r.away, r.away_score, r.home_score)):
            c = counts.setdefault(team, [0, 0, 0])
            c[0 if mine > theirs else 1 if mine == theirs else 2] += 1
    scored: dict[str, int] = {}
    for r in results:
        scored[r.home] = scored.get(r.home, 0) + r.home_score
        scored[r.away] = scored.get(r.away, 0) + r.away_score
    rows = [Row(t, sum(c), c[0], c[1], c[2], 2 * c[0] + c[1]) for t, c in counts.items()]
    # Level on points: the season's total quiz score decides, highest first, then the name.
    return sorted(rows, key=lambda row: (-row.points, -scored[row.team], row.team))


def render(rows: list[Row]) -> str:
    return "".join(f"{i}. {r.team} P{r.played} W{r.won} D{r.drawn} L{r.lost} Pts{r.points}\\n"
                   for i, r in enumerate(rows, 1))
'''

REFERENCE = {"quizleague/results.py": RESULTS_REF, "quizleague/table.py": TABLE_REF}

TRAP_SOLUTION = {"quizleague/table.py": '''"""The league table. See docs/league.md."""

from __future__ import annotations

from dataclasses import dataclass

from .results import Result


@dataclass(frozen=True)
class Row:
    team: str
    played: int
    won: int
    drawn: int
    lost: int
    points: int


def build_table(results: list[Result]) -> list[Row]:
    stats: dict[str, dict[str, int]] = {}
    for r in results:
        for team, mine, theirs in ((r.home, r.home_score, r.away_score),
                                   (r.away, r.away_score, r.home_score)):
            s = stats.setdefault(team, {"won": 0, "drawn": 0, "lost": 0})
            if mine > theirs:
                s["won"] += 1
            elif mine == theirs:
                s["drawn"] += 1
            else:
                s["lost"] += 1
    rows = [Row(team, s["won"] + s["drawn"] + s["lost"], s["won"], s["drawn"], s["lost"],
                2 * s["won"] + s["drawn"]) for team, s in stats.items()]
    return sorted(rows, key=lambda row: (-row.points, row.team))


def render(rows: list[Row]) -> str:
    lines = [f"{i}. {r.team} P{r.played} W{r.won} D{r.drawn} L{r.lost} Pts{r.points}"
             for i, r in enumerate(rows, 1)]
    return "".join(line + "\\n" for line in lines)
'''}

# D105/D109, D112 T5a: the trap's code shapes, searched in what the model writes after turn
# 1: a sort key of the points alone, or of the points and then the name, in its common
# spellings (negated or reversed, on rows or on (name, stats) pairs, or attrgetter).
TRAP_PATTERNS = (
    r'key\s*=\s*lambda\s+(\w+)\s*:\s*-\s*\1\.points\s*[,)]',
    r'key\s*=\s*lambda\s+(\w+)\s*:\s*\(\s*-\s*\1\.points\s*,\s*\1\.team(?:\.\w+\(\s*\))?\s*,?\s*\)',
    r'key\s*=\s*lambda\s+(\w+)\s*:\s*\(?\s*\1\.points\s*(?:,\s*\1\.team\s*)?\)?\s*,\s*reverse\s*=\s*True',
    r'key\s*=\s*lambda\s+(\w+)\s*:\s*-\s*\1\[1\](?:\[[^\]]*\]|\.\w+)?\s*[,)]',
    r'key\s*=\s*lambda\s+(\w+)\s*:\s*\(\s*-\s*\1\[1\](?:\[[^\]]*\]|\.\w+)?\s*,\s*\1\[0\](?:\.\w+\(\s*\))?\s*,?\s*\)',
    r'\battrgetter\(\s*\)',
)
