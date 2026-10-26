"""ho2-t3: overlapping shifts in a staff roster, and its command line. The fresh held-out
restart task (O-B1, D45.9.7).

``KEY_CONSTRAINT`` C2 (what the command line prints and its exit status) is stated once, in
the first turn, before the proxy restart. No turn before the restart touches the command
line, and the turn that builds it (turn 5, after the restart) does not repeat the rule.

Other A1 categories: an information need that arises mid-task (turn 7's night shifts follow
a rule in the reference document read in turn 2, including the end-equals-start case it
does not restate); restarts and multiple eviction events; an oversized read.
"""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho2-t3"
SET = "heldout2"
TITLE = "rosterlap: find overlapping shifts in a staff roster, with a command line"
RESTART_BEFORE = 4
KEY_CONSTRAINT = "C2"
CONSTRAINTS = {
    "C1": "times are 24-hour HH:MM from 00:00 to 23:59 and dates are YYYY-MM-DD; any bad row "
          "raises ShiftError from roster/errors.py carrying that row's id in .shift_id",
    "C2": "the command line prints only the overlaps on stdout, one per line as person, tab, "
          "first id, tab, second id (first id sorting before second, lines sorted), and exits "
          "with status 4 when it found any overlap and 0 when it found none",
    "C3": "shifts that only touch (one ends at 14:00, the next starts at 14:00) never overlap",
}
TRAP = ("already tried sorting by start time and comparing each shift only with the next one; "
        "it failed because one long shift can overlap several later ones, and only the first "
        "of them was reported")


def initials(name: str) -> str:
    return "".join(p[0].upper() for p in name.replace("-", " ").split() if p)


LEGACY = '''"""Initials for the printed wall roster (do not change)."""


def initials(name: str) -> str:
    return "".join(p[0].upper() for p in name.replace("-", " ").split() if p)
'''

ERRORS = '''"""Errors."""


class ShiftError(ValueError):
    """A roster row that cannot be read. ``shift_id`` is the row's id field."""

    def __init__(self, shift_id, reason):
        super().__init__(f"shift {shift_id}: {reason}")
        self.shift_id = shift_id
        self.reason = reason
'''

STUB = '''"""Overlapping shifts in a roster. See docs/roster_format.md."""

from __future__ import annotations

from typing import NamedTuple
from datetime import datetime

from .errors import ShiftError  # noqa: F401


class Shift(NamedTuple):
    id: str
    person: str
    start: datetime
    end: datetime


def parse_rows(text: str) -> list[Shift]:
    """The text of a roster CSV file (with its header line) -> its shifts, in file order."""
    raise NotImplementedError


def find_overlaps(shifts: list[Shift]) -> list[tuple[str, str, str]]:
    """Every overlapping pair of one person's shifts, as (person, first id, second id),
    sorted."""
    raise NotImplementedError
'''

CLI_STUB = '''"""Command line: ``python -m roster <roster.csv>``."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
'''

MAIN = '''from .cli import main

raise SystemExit(main())
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roster.overlap import find_overlaps, parse_rows  # noqa: E402

HEADER = "id,person,date,start,end\\n"


class OverlapTests(unittest.TestCase):
    def test_parse(self):
        shifts = parse_rows(HEADER + "S1,ana,2026-12-07,08:00,16:00\\n")
        self.assertEqual([s.id for s in shifts], ["S1"])

    def test_simple_overlap(self):
        shifts = parse_rows(HEADER + "S1,ana,2026-12-07,08:00,16:00\\n"
                                     "S2,ana,2026-12-07,15:00,18:00\\n")
        self.assertEqual(find_overlaps(shifts), [("ana", "S1", "S2")])
'''

DOC_INTRO = [
    "The roster files the ward planners export, one CSV file per week.",
    "",
    "## Rows",
    "",
    "- The first line is the header `id,person,date,start,end`; every other line is one shift.",
    "- `id` is unique in the file. `person` is a staff login. `date` is the day the shift",
    "  starts, as YYYY-MM-DD. `start` and `end` are 24-hour HH:MM times.",
    "",
    "## Time",
    "",
    "- A shift covers the half-open interval from its start up to, but not including, its",
    "  end.",
    "- Night shifts: when the end time is earlier than the start time, the shift ends on the",
    "  following day (22:00 to 06:00 ends at 06:00 the next morning).",
    "- A shift whose end equals its start is an error, not a 24-hour shift.",
    "",
    "## Overlaps",
    "",
    "- Two shifts overlap when they belong to the same person and their intervals share any",
    "  time. Different people never overlap.",
]

PEOPLE = ["ana", "bo", "cyril", "dana", "emeka", "farah", "goran", "hana", "ivo", "jun"]


def _record(rnd: random.Random, i: int) -> str:
    start = rnd.choice(["06:00", "07:00", "08:00", "14:00", "15:00", "22:00"])
    end = {"06:00": "14:00", "07:00": "15:00", "08:00": "16:00", "14:00": "22:00",
           "15:00": "23:00", "22:00": "06:00"}[start]
    return (f"`W{rnd.randint(1000, 9999)},{rnd.choice(PEOPLE)},2026-12-{rnd.randint(1, 28):02d},"
            f"{start},{end}` | {'night' if start == '22:00' else 'day'} shift")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        name = " ".join(rnd.choice(PEOPLE).title() for _ in range(rnd.randint(1, 3)))
        if rnd.random() < 0.3:
            name = name.replace(" ", "-", 1)
        slug = rnd.choice(["single_name", "double_name", "hyphenated", "wall_roster"])
        cases.append((slug, repr(name), repr(initials(name))))
    return {
        "roster/__init__.py": '"""Overlapping shifts in ward rosters."""\n',
        "roster/__main__.py": MAIN,
        "roster/cli.py": CLI_STUB,
        "roster/errors.py": ERRORS,
        "roster/legacy.py": LEGACY,
        "roster/overlap.py": STUB,
        "docs/roster_format.md": long_doc(rnd, "Ward roster files", DOC_INTRO, _record),
        "tests/test_overlap.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("roster.legacy", "initials",
                                                      "InitialsCatalogTests", cases),
    }


TURNS = [
    "This session is about `roster`, which finds overlapping shifts in the ward roster files. "
    "Requirements: (1) times are 24-hour HH:MM from 00:00 to 23:59 and dates are YYYY-MM-DD; "
    "any bad row raises ShiftError from roster/errors.py carrying that row's id in "
    "`.shift_id`; (2) the command-line tool prints only the overlaps on stdout, one per line "
    "as `<person>`, a tab, `<first id>`, a tab, `<second id>`, with the first id sorting "
    "before the second and the lines sorted, and it exits with status 4 when it found any "
    "overlap and 0 when it found none; (3) shifts that only touch, where one ends at 14:00 "
    "and the next starts at 14:00, never overlap. Also: we already tried sorting by start "
    "time and comparing each shift only with the next one, and it failed because one long "
    "shift can overlap several later ones, and only the first of them was reported. Begin by "
    "reading roster/overlap.py and roster/errors.py and telling me what needs writing; change "
    "nothing yet. " + NO_QUESTIONS,
    "Read docs/roster_format.md in full, all of its roughly 300 lines, through the line "
    "'End of document.', and summarize it in five bullet points.",
    "Implement `parse_rows` and `find_overlaps` for day shifts, where the end time is later "
    "than the start time; leave night shifts for later. Then run `python -m unittest "
    "tests.test_overlap -v`.",
    "Run every test verbosely with `python -m unittest discover -s tests -v` and tell me how "
    "many ran and which failed.",
    "Now write the entry point `main(argv)` in roster/cli.py, so that `python -m roster "
    "<roster.csv>` reads the file with parse_rows and reports the overlapping shifts that "
    "find_overlaps finds. Return 2 when the file does not exist, and 1 when a row is invalid, "
    "with a short message on stderr. Add tests for it in tests/test_cli.py and run them with "
    "`python -m unittest tests.test_cli -v`.",
    "Run every test verbosely again (`python -m unittest discover -s tests -v`) and give me "
    "the totals.",
    "Next, night shifts: make parse_rows and find_overlaps handle them as the roster format "
    "document describes. Also add a `--person LOGIN` option to the command line that limits "
    "the report to that person's overlaps. Add tests for both and run `python -m unittest "
    "tests.test_overlap tests.test_cli -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from roster.cli import main  # noqa: E402
from roster.errors import ShiftError  # noqa: E402
from roster.overlap import find_overlaps, parse_rows  # noqa: E402

HEADER = "id,person,date,start,end\\n"
DAY = HEADER + ("A1,ana,2026-12-07,06:00,18:00\\n"
                "A2,ana,2026-12-07,08:00,10:00\\n"
                "A3,ana,2026-12-07,12:00,14:00\\n"
                "B1,bo,2026-12-07,08:00,16:00\\n"
                "B2,bo,2026-12-07,15:30,20:00\\n"
                "C1,cyril,2026-12-07,08:00,16:00\\n"
                "C2,cyril,2026-12-08,08:00,16:00\\n"
                "D1,dana,2026-12-07,09:00,17:00\\n")
CLEAN = HEADER + "A1,ana,2026-12-07,06:00,14:00\\nA2,ana,2026-12-07,14:00,22:00\\n"


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


def write(d, name, text):
    p = Path(d) / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def pair_on_one_line(text, a, b):
    return any(a in line and b in line for line in text.splitlines())


class HiddenTests(unittest.TestCase):
    def test_f_overlaps(self):
        self.assertEqual(find_overlaps(parse_rows(DAY)),
                         [("ana", "A1", "A2"), ("ana", "A1", "A3"), ("bo", "B1", "B2")])
        self.assertEqual(find_overlaps(parse_rows(CLEAN)), [])
        shifts = parse_rows(HEADER + "Z2,ana,2026-12-07,10:00,12:00\\nZ1,ana,2026-12-07,11:00,13:00\\n")
        self.assertEqual(find_overlaps(shifts), [("ana", "Z1", "Z2")])

    def test_f_night(self):
        text = HEADER + ("N1,dana,2026-12-03,22:00,06:00\\n"
                         "N2,dana,2026-12-04,05:00,09:00\\n"
                         "N3,dana,2026-12-04,08:30,10:00\\n"
                         "N4,emeka,2026-12-03,23:00,07:00\\n"
                         "N5,emeka,2026-12-03,20:00,23:30\\n")
        self.assertEqual(find_overlaps(parse_rows(text)),
                         [("dana", "N1", "N2"), ("dana", "N2", "N3"), ("emeka", "N4", "N5")])
        with self.assertRaises(ShiftError):
            parse_rows(HEADER + "N9,dana,2026-12-03,08:00,08:00\\n")

    def test_f_cli(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, err = run_main([write(d, "week.csv", DAY)])
            for a, b in (("A1", "A2"), ("A1", "A3"), ("B1", "B2")):
                self.assertTrue(pair_on_one_line(out + err, a, b), (a, b))
            self.assertFalse(pair_on_one_line(out + err, "C1", "C2"))
            self.assertEqual(run_main([write(d, "clean.csv", CLEAN)])[0], 0)
            self.assertEqual(run_main([str(Path(d) / "missing.csv")])[0], 2)
            self.assertEqual(run_main([write(d, "bad.csv", HEADER + "X1,ana,2026-12-07,8am,16:00\\n")])[0], 1)

    def test_f_person(self):
        with tempfile.TemporaryDirectory() as d:
            path = write(d, "week.csv", DAY)
            code, out, err = run_main([path, "--person", "bo"])
            self.assertTrue(pair_on_one_line(out + err, "B1", "B2"))
            self.assertNotIn("A2", out + err)
            self.assertNotIn("A3", out + err)

    def test_c1_bad_rows(self):
        for row in ("S9,ana,2026-12-03,24:00,25:00", "S8,ana,2026-12-3x,08:00,09:00",
                    "S7,ana,2026-12-03,8:00,09:00", "S6,ana,2026-12-03,08:00",
                    "S5,ana,2026-12-03,08:60,09:00", "S4,ana,2026-13-03,08:00,09:00"):
            with self.assertRaises(ShiftError, msg=row) as cm:
                parse_rows(HEADER + "OK1,ana,2026-12-01,08:00,09:00\\n" + row + "\\n")
            self.assertEqual(cm.exception.shift_id, row.split(",")[0])

    def test_c2_cli_output(self):
        with tempfile.TemporaryDirectory() as d:
            path = write(d, "week.csv", DAY)
            code, out, _ = run_main([path])
            self.assertEqual(code, 4)
            self.assertEqual(out, "ana\\tA1\\tA2\\nana\\tA1\\tA3\\nbo\\tB1\\tB2\\n")
            code, out, _ = run_main([path, "--person", "ana"])
            self.assertEqual(code, 4)
            self.assertEqual(out, "ana\\tA1\\tA2\\nana\\tA1\\tA3\\n")
            code, out, _ = run_main([path, "--person", "dana"])
            self.assertEqual((code, out), (0, ""))
            code, out, _ = run_main([write(d, "clean.csv", CLEAN)])
            self.assertEqual((code, out), (0, ""))

    def test_c3_touching(self):
        self.assertEqual(find_overlaps(parse_rows(CLEAN)), [])
        night = HEADER + "T1,ana,2026-12-03,22:00,06:00\\nT2,ana,2026-12-04,06:00,10:00\\n"
        self.assertEqual(find_overlaps(parse_rows(night)), [])


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {
    "roster/overlap.py": '''"""Overlapping shifts in a roster. See docs/roster_format.md."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import NamedTuple

from .errors import ShiftError

TIME = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class Shift(NamedTuple):
    id: str
    person: str
    start: datetime
    end: datetime


def _row(line: str) -> Shift:
    fields = line.split(",")
    sid = fields[0].strip()
    if len(fields) != 5:
        raise ShiftError(sid, "expected 5 fields")
    _, person, date, start, end = (f.strip() for f in fields)
    if not DATE.fullmatch(date):
        raise ShiftError(sid, "bad date")
    try:
        day = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ShiftError(sid, "bad date") from None
    times = []
    for t in (start, end):
        m = TIME.fullmatch(t)
        if not m:
            raise ShiftError(sid, "bad time")
        times.append(day + timedelta(hours=int(m.group(1)), minutes=int(m.group(2))))
    s, e = times
    if e == s:
        raise ShiftError(sid, "end equals start")
    if e < s:
        e += timedelta(days=1)
    return Shift(sid, person, s, e)


def parse_rows(text: str) -> list[Shift]:
    lines = [l for l in text.splitlines() if l.strip()]
    return [_row(l) for l in lines[1:]]


def find_overlaps(shifts: list[Shift]) -> list[tuple[str, str, str]]:
    out = []
    for i, a in enumerate(shifts):
        for b in shifts[i + 1:]:
            if a.person == b.person and a.start < b.end and b.start < a.end:
                x, y = sorted((a.id, b.id))
                out.append((a.person, x, y))
    return sorted(out)
''',
    "roster/cli.py": '''"""Command line: ``python -m roster <roster.csv> [--person LOGIN]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .errors import ShiftError
from .overlap import find_overlaps, parse_rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="roster")
    p.add_argument("path")
    p.add_argument("--person")
    a = p.parse_args(sys.argv[1:] if argv is None else argv)
    path = Path(a.path)
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    try:
        shifts = parse_rows(path.read_text(encoding="utf-8"))
    except ShiftError as e:
        print(f"invalid row: {e}", file=sys.stderr)
        return 1
    found = [o for o in find_overlaps(shifts) if a.person is None or o[0] == a.person]
    for person, x, y in found:
        print(f"{person}\\t{x}\\t{y}")
    return 4 if found else 0


if __name__ == "__main__":
    sys.exit(main())
''',
}
