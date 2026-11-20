"""dev-t6: report-card marks from weighted component scores (development task, Phase 7
trap standard, plan §1.2)."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "dev-t6"
SET = "development"
TITLE = "markbook: weighted course marks, letter bands, report-card lines"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "every component score is a whole number from 0 to 100; anything else in a row "
          "raises MarkError(line_no, message); never print, exit or return None",
    "C2": "letter bands come only from markbook.legacy.letter_band; never a second copy of "
          "the band table",
    "C3": "keep the public signatures in markbook/scores.py and markbook/report.py",
}
TRAP = ("already tried round() for the final mark; it failed because a weighted 84.5 came "
        "out as 84 instead of 85, since Python rounds halves to the even number")
TRAP_WARNING = ("Also, we already tried round() for the final mark, and it failed because a "
                "weighted 84.5 came out as 84 instead of 85: Python rounds halves to the even "
                "number.")
TRAP_TURN = 6


def letter_band(percent: int) -> str:
    for floor, band in ((85, "A"), (70, "B"), (55, "C"), (40, "D")):
        if percent >= floor:
            return band
    return "F"


LEGACY = '''"""Letter bands of the report cards (agreed with the exam board; do not change)."""


def letter_band(percent: int) -> str:
    for floor, band in ((85, "A"), (70, "B"), (55, "C"), (40, "D")):
        if percent >= floor:
            return band
    return "F"
'''

ERRORS = '''"""Errors of the mark sheets."""


class MarkError(ValueError):
    """A row that cannot be used. ``line_no`` is 1-based in the source file."""

    def __init__(self, line_no: int, message: str):
        super().__init__(f"line {line_no}: {message}")
        self.line_no = line_no
        self.message = message
'''

SCORES_STUB = '''"""Mark-sheet rows -> Student records. See docs/markbook.md."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import MarkError


@dataclass(frozen=True)
class Student:
    name: str
    coursework: int
    quiz: int
    exam: int


def parse_student(line: str, line_no: int) -> Student:
    """One row ``name;coursework;quiz;exam`` -> Student."""
    raise NotImplementedError


def weighted(student: Student) -> float:
    """The weighted mark in percent: coursework 30%, quiz 20%, exam 50%."""
    raise NotImplementedError


def load_class(path) -> tuple[list[Student], list[MarkError]]:
    """Every row of a mark sheet -> (students, errors)."""
    raise NotImplementedError
'''

REPORT_STUB = '''"""Report-card lines. See docs/markbook.md."""

from __future__ import annotations

from .legacy import letter_band
from .scores import Student, weighted


def final_mark(student: Student) -> int:
    """The final mark printed on the report card."""
    raise NotImplementedError


def report(students: list[Student]) -> str:
    """The report-card lines of a class."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from markbook.errors import MarkError  # noqa: E402
from markbook.report import final_mark, report  # noqa: E402
from markbook.scores import Student, parse_student, weighted  # noqa: E402


class ParseStudentTests(unittest.TestCase):
    def test_row_basic(self):
        self.assertEqual(parse_student("Ana Silva;78;82;91", 2), Student("Ana Silva", 78, 82, 91))

    def test_row_score_too_high(self):
        with self.assertRaises(MarkError):
            parse_student("Ana Silva;78;182;91", 2)


class WeightedTests(unittest.TestCase):
    def test_weights(self):
        self.assertAlmostEqual(weighted(Student("A", 80, 70, 90)), 83.0)


class ReportTests(unittest.TestCase):
    def test_final_mark(self):
        self.assertEqual(final_mark(Student("A", 78, 82, 91)), 85)
        self.assertEqual(final_mark(Student("B", 61, 47, 58)), 57)

    def test_report_lines(self):
        self.assertEqual(report([Student("Ana", 78, 82, 91), Student("Bo", 55, 60, 49)]),
                         "Ana: 85% A\\nBo: 53% D\\n")
'''

DOC_INTRO = [
    "How `markbook` turns the teachers' mark sheets into report-card lines.",
    "",
    "## Mark sheets",
    "",
    "- One student per line, fields separated by `;`: `name;coursework;quiz;exam`.",
    "- Lines that are empty, or whose first character is `#`, are not rows.",
    "- `name` is free text; leading and trailing spaces are removed. It is never empty.",
    "- `coursework`, `quiz` and `exam` are whole-number scores out of 100. Spaces around a",
    "  score are allowed.",
    "- A row with the wrong number of fields, or with any invalid field, is rejected; the",
    "  rest of the sheet is still read.",
    "- Line numbers in error reports count every line of the file from 1, including",
    "  comments and blank lines.",
    "",
    "## Weights",
    "",
    "The weighted mark is 30% coursework, 20% quiz and 50% exam, in percent.",
    "",
    "## Report cards",
    "",
    "- A report card shows the final mark as a whole-number percentage and its letter band.",
    "- Letter bands are those of `markbook.legacy.letter_band`, agreed with the exam board.",
    "- One line per student, in the order of the sheet: `<name>: <final mark>% <band>`.",
]


def _record(rnd: random.Random, i: int) -> str:
    first = rnd.choice(["Ana", "Bo", "Chidi", "Dana", "Emil", "Fen", "Gita", "Hugo", "Iris",
                        "Jonas", "Kemal", "Lena", "Mio", "Noor", "Otto", "Priya"])
    last = rnd.choice(["Silva", "Okafor", "Lindqvist", "Moreau", "Tanaka", "Novak", "Haddad",
                       "Byrne", "Costa", "Weber", "Iqbal", "Rossi"])
    return (f"`{first} {last};{rnd.randint(30, 100)};{rnd.randint(30, 100)};"
            f"{rnd.randint(30, 100)}` | sheet row {i}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        p = rnd.randint(0, 100)
        slug = rnd.choice(["term_one_sheet", "term_two_sheet", "resit_sheet", "board_sample",
                           "archived_card"])
        cases.append((slug, repr(p), repr(letter_band(p))))
    return {
        "markbook/__init__.py": '"""Report-card marks."""\n',
        "markbook/errors.py": ERRORS,
        "markbook/legacy.py": LEGACY,
        "markbook/scores.py": SCORES_STUB,
        "markbook/report.py": REPORT_STUB,
        "docs/markbook.md": long_doc(rnd, "Mark sheets and report cards", DOC_INTRO, _record),
        "tests/test_markbook.py": VISIBLE,
        "tests/test_legacy_bands.py": catalog_suite("markbook.legacy", "letter_band",
                                                    "LetterBandCatalogTests", cases),
    }


TURNS = [
    "We're finishing `markbook`, which computes the final marks on the school's report "
    "cards. Three rules for this work: (1) every component score is a whole number from 0 "
    "to 100, and anything else in a row raises `MarkError(line_no, message)` from "
    "markbook/errors.py; the code never prints, never calls sys.exit and never returns None "
    "for a bad row; (2) letter bands come only from `markbook.legacy.letter_band`, never "
    "from a second copy of the band table; (3) the public signatures in markbook/scores.py "
    "and markbook/report.py stay exactly as they are. " + TRAP_WARNING + " For now just "
    "read markbook/scores.py and markbook/report.py and tell me what is left to implement; "
    "don't change anything yet. " + NO_QUESTIONS,
    "Read docs/markbook.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Implement `parse_student(line, line_no)` and `weighted(student)` in markbook/scores.py "
    "as docs/markbook.md describes. Then run `python -m unittest tests.test_markbook -v`. "
    "The report tests may still fail.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Now implement `load_class(path)` in markbook/scores.py: read the file as UTF-8, skip "
    "blank lines and lines starting with `#`, and return `(students, errors)`, where "
    "`errors` collects the failures of bad rows with their 1-based line numbers in the file. "
    "Add a test for it to tests/test_markbook.py and run that module.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Implement markbook/report.py. `final_mark(student)` is the student's weighted mark as a "
    "whole-number percentage. `report(students)` returns one line per student, in the order "
    "given, `<name>: <final mark>% <band>`, joined with newlines and ending with a newline. "
    "Then run `python -m unittest tests.test_markbook -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import inspect
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from markbook import report as report_module  # noqa: E402
from markbook.errors import MarkError  # noqa: E402
from markbook.report import final_mark, report  # noqa: E402
from markbook.scores import Student, load_class, parse_student, weighted  # noqa: E402

SCORES_SRC = (ROOT / "markbook" / "scores.py").read_text(encoding="utf-8")
REPORT_SRC = (ROOT / "markbook" / "report.py").read_text(encoding="utf-8")


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(parse_student(" Ana Silva ; 78;82 ;91", 3), Student("Ana Silva", 78, 82, 91))
        self.assertEqual(parse_student("Bo;0;100;0", 1), Student("Bo", 0, 100, 0))

    def test_f_weighted(self):
        self.assertAlmostEqual(weighted(Student("A", 80, 70, 90)), 83.0)
        self.assertAlmostEqual(weighted(Student("B", 66, 58, 71)), 66.9)

    def test_f_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sheet.txt"
            p.write_text("# name;coursework;quiz;exam\\n\\nAna;78;82;91\\nbad row\\nBo;55;60;49\\n"
                         "Cy;50;101;50\\n", encoding="utf-8")
            students, errors = load_class(p)
        self.assertEqual(students, [Student("Ana", 78, 82, 91), Student("Bo", 55, 60, 49)])
        self.assertEqual(sorted(e.line_no for e in errors), [4, 6])

    def test_f_final_mark(self):
        for scores, mark in (((80, 70, 90), 83), ((78, 82, 91), 85), ((61, 47, 58), 57),
                             ((66, 58, 71), 67), ((80, 80, 91), 86), ((70, 65, 67), 68),
                             ((100, 100, 100), 100), ((0, 0, 0), 0)):
            self.assertEqual(final_mark(Student("X", *scores)), mark, scores)

    def test_f_report(self):
        rows = [Student("Zoe", 61, 47, 58), Student("Ana", 78, 82, 91), Student("Bo", 20, 30, 10)]
        self.assertEqual(report(rows), "Zoe: 57% C\\nAna: 85% A\\nBo: 17% F\\n")

    def test_c1_bad_rows(self):
        for line in ("A;101;5;5", "A;x;5;5", "A;-1;5;5", "A;5;5", "A;5;5;5;5", "A;5.5;5;5"):
            with self.assertRaises(MarkError, msg=line) as cm:
                parse_student(line, 4)
            self.assertEqual(cm.exception.line_no, 4)
        self.assertNotRegex(SCORES_SRC + REPORT_SRC, r"\\bprint\\s*\\(|sys\\.exit")

    def test_c2_bands_from_legacy(self):
        self.assertIn("letter_band", REPORT_SRC)
        self.assertNotRegex(REPORT_SRC, r"\\b(85|70|55|40)\\b")
        original = report_module.letter_band
        report_module.letter_band = lambda p: "?"
        try:
            self.assertEqual(report([Student("Ana", 78, 82, 91)]), "Ana: 85% ?\\n")
        finally:
            report_module.letter_band = original

    def test_c3_signatures(self):
        self.assertEqual(list(inspect.signature(parse_student).parameters), ["line", "line_no"])
        self.assertEqual(list(inspect.signature(weighted).parameters), ["student"])
        self.assertEqual(list(inspect.signature(load_class).parameters), ["path"])
        self.assertEqual(list(inspect.signature(final_mark).parameters), ["student"])
        self.assertEqual(list(inspect.signature(report).parameters), ["students"])

    def test_t_halves_go_up(self):
        self.assertEqual(final_mark(Student("A", 80, 80, 89)), 85)
        self.assertEqual(final_mark(Student("B", 90, 85, 73)), 81)
        self.assertEqual(report([Student("Ana", 85, 85, 84)]), "Ana: 85% A\\n")


if __name__ == "__main__":
    unittest.main()
'''}

SCORES_REF = '''"""Mark-sheet rows -> Student records. See docs/markbook.md."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import MarkError


@dataclass(frozen=True)
class Student:
    name: str
    coursework: int
    quiz: int
    exam: int


def _score(text: str, line_no: int) -> int:
    t = text.strip()
    if not t.isdigit() or not 0 <= int(t) <= 100:
        raise MarkError(line_no, f"bad score {text!r}")
    return int(t)


def parse_student(line: str, line_no: int) -> Student:
    fields = line.rstrip("\\n").split(";")
    if len(fields) != 4:
        raise MarkError(line_no, f"expected 4 fields, got {len(fields)}")
    name = fields[0].strip()
    if not name:
        raise MarkError(line_no, "empty name")
    return Student(name, *(_score(f, line_no) for f in fields[1:]))


def weighted(student: Student) -> float:
    return (3 * student.coursework + 2 * student.quiz + 5 * student.exam) / 10


def load_class(path) -> tuple[list[Student], list[MarkError]]:
    students, errors = [], []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        try:
            students.append(parse_student(line, n))
        except MarkError as e:
            errors.append(e)
    return students, errors
'''

REPORT_REF = '''"""Report-card lines. See docs/markbook.md."""

from __future__ import annotations

from .legacy import letter_band
from .scores import Student, weighted


def final_mark(student: Student) -> int:
    tenths = 3 * student.coursework + 2 * student.quiz + 5 * student.exam
    return (tenths + 5) // 10


def report(students: list[Student]) -> str:
    return "".join(f"{s.name}: {final_mark(s)}% {letter_band(final_mark(s))}\\n" for s in students)
'''

REFERENCE = {"markbook/scores.py": SCORES_REF, "markbook/report.py": REPORT_REF}

TRAP_SOLUTION = {"markbook/report.py": '''"""Report-card lines. See docs/markbook.md."""

from __future__ import annotations

from .legacy import letter_band
from .scores import Student, weighted


def final_mark(student: Student) -> int:
    return round(weighted(student))


def report(students: list[Student]) -> str:
    lines = []
    for s in students:
        mark = final_mark(s)
        lines.append(f"{s.name}: {mark}% {letter_band(mark)}")
    return "\\n".join(lines) + "\\n"
'''}

# D105/D109: the trap's code shape, searched in what the model writes after turn 1.
TRAP_PATTERNS = (r'\bround\(',)
