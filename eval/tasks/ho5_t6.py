"""Circdesk models nightly lending receipts from a branch circulation counter."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t6"
SET = "heldout5"
TITLE = "circdesk: scanner receipts, branch loan expiry, check-in arrears"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "use circdesk/errors.py SlipError(line_no, message) for malformed receipts; "
          "no stdout/exit/None",
    "C2": "loan-period lookup: circdesk.legacy.loan_period only",
    "C3": "verbatim barcode strings, zero padding included",
}
TRAP = ("already tried borrowed + timedelta(days=period); Sunday closures made Monday "
        "returns spuriously overdue")
TRAP_WARNING = ("Also, we already tried `borrowed + timedelta(days=period)`, and it failed "
                "because the locked Sunday branch made Monday check-ins spuriously overdue. "
                "Advance Sunday expiries to Monday.")
TRAP_TURN = 6

PERIODS = {"book": 21, "audiobook": 21, "magazine": 14, "dvd": 7}


def loan_period(material: str, card: str) -> int:
    kind = material.strip().lower()
    days = PERIODS[kind]
    holder = card.strip()[:1].upper()
    if holder == "S":
        return days * 2
    if holder == "J" and kind == "book":
        return 28
    return days


LEGACY = '''"""Lending periods of the branch (fixed by the library board; leave as is)."""

PERIODS = {"book": 21, "audiobook": 21, "magazine": 14, "dvd": 7}


def loan_period(material: str, card: str) -> int:
    kind = material.strip().lower()
    days = PERIODS[kind]
    holder = card.strip()[:1].upper()
    if holder == "S":
        return days * 2
    if holder == "J" and kind == "book":
        return 28
    return days
'''

ERRORS = '''"""What goes wrong with desk slips."""


class SlipError(ValueError):
    """A slip the desk export cannot turn into a loan; ``line_no`` counts from 1."""

    def __init__(self, line_no: int, message: str):
        super().__init__(f"slip on line {line_no}: {message}")
        self.line_no = line_no
        self.message = message
'''

LOANS_STUB = '''"""Desk slips -> Loan records. See docs/circulation.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .errors import SlipError

MATERIALS = ("book", "audiobook", "magazine", "dvd")


@dataclass(frozen=True)
class Loan:
    card: str
    barcode: str
    material: str
    borrowed: date


def parse_slip(line: str, line_no: int) -> Loan:
    """A slip ``card|barcode|material|borrowed`` -> Loan."""
    raise NotImplementedError


def load_slips(path) -> tuple[list[Loan], list[SlipError]]:
    """Every slip in a desk export -> (loans, errors)."""
    raise NotImplementedError
'''

RETURNS_STUB = '''"""When loans are due back, and how late they came in. See docs/circulation.md."""

from __future__ import annotations

from datetime import date, timedelta

from .legacy import loan_period
from .loans import Loan


def due_date(loan: Loan) -> date:
    """The day this item has to be back at the desk."""
    raise NotImplementedError


def days_late(loan: Loan, returned: date) -> int:
    """Whole days between the due-back date and the return (0 when not late)."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from circdesk.returns import days_late, due_date  # noqa: E402
from circdesk.errors import SlipError  # noqa: E402
from circdesk.loans import Loan, parse_slip  # noqa: E402

NOVEL = Loan("A20417", "31170004528813", "book", date(2026, 3, 2))


class SlipTests(unittest.TestCase):
    def test_slip_reads(self):
        self.assertEqual(parse_slip("a20417|31170004528813|Book|2026-03-02", 5), NOVEL)

    def test_slip_unknown_material(self):
        with self.assertRaises(SlipError):
            parse_slip("A20417|31170004528813|vinyl|2026-03-02", 5)


class DueBackTests(unittest.TestCase):
    def test_adult_book(self):
        self.assertEqual(due_date(NOVEL), date(2026, 3, 23))

    def test_dvd_on_staff_card(self):
        self.assertEqual(due_date(Loan("S00912", "31170000000417", "dvd", date(2026, 3, 4))),
                         date(2026, 3, 18))

    def test_days_late(self):
        self.assertEqual(days_late(NOVEL, date(2026, 3, 26)), 3)
        self.assertEqual(days_late(NOVEL, date(2026, 3, 20)), 0)
'''

DOC_INTRO = [
    "## Nightly scanner manifest",
    "",
    "One scanner transaction: `card|barcode|material|borrowed`.",
    "Skip empty receipts and column-one `#` annotations.",
    "Trim every cell.",
    "Patron-code syntax: `[A-Za-z][0-9]{5}`. Capitalize the prefix.",
    "Patron types: `A` adult, `J` junior, `S` staff.",
    "Preserve the exact fourteen-digit asset barcode.",
    "Store material lowercase: `book`, `audiobook`, `magazine`, `dvd`.",
    "`borrowed` requires a valid Gregorian `YYYY-MM-DD` date.",
    "Scanner intake continues after malformed rows.",
    "Label faults by physical scanner-row position, origin 1.",
    "",
    "## Counter policy",
    "",
    "`circdesk.legacy.loan_period(material, card)` owns the board-approved lending table.",
    "Arrears count calendar days past expiry with minimum zero.",
]

READERS = ["A", "J", "S", "a", "j"]
NOTES = ["evening desk", "kiosk", "bookmobile", "returns chute", "reading room",
         "home delivery", "school batch"]


def _record(rnd: random.Random, _index: int) -> str:
    card = f"{rnd.choice(READERS)}{rnd.randint(0, 99999):05d}"
    barcode = f"3117{rnd.randint(0, 10 ** 10 - 1):010d}"
    material = rnd.choice(["book", "Book", "audiobook", "magazine", "DVD", "dvd"])
    day = f"2026-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}"
    return f"`{card}|{barcode}|{material}|{day}` | {rnd.choice(NOTES)}"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        material = rnd.choice(["book", " Book", "audiobook", "magazine", "DVD", "dvd "])
        card = f"{rnd.choice(READERS)}{rnd.randint(0, 99999):05d}"
        slug = rnd.choice(["board_minutes", "desk_handbook", "policy_poster", "kiosk_screen",
                           "branch_leaflet"])
        cases.append((slug, f"{material!r}, {card!r}", repr(loan_period(material, card))))
    return {
        "circdesk/__init__.py": '"""Circulation desk tools of the branch library."""\n',
        "circdesk/errors.py": ERRORS,
        "circdesk/legacy.py": LEGACY,
        "circdesk/loans.py": LOANS_STUB,
        "circdesk/returns.py": RETURNS_STUB,
        "docs/circulation.md": long_doc(rnd, "Desk slips and due-back dates", DOC_INTRO,
                                        _record),
        "tests/test_circdesk.py": VISIBLE,
        "tests/test_legacy_periods.py": catalog_suite("circdesk.legacy", "loan_period",
                                                      "LoanPeriodCatalogTests", cases),
    }


TURNS = [
    "Finish scanner intake plus returns. C1: malformed receipts raise circdesk/errors.py's "
    "`SlipError(line_no, message)`; no stdout/exit/None. C2: all period lookups use "
    "`circdesk.legacy.loan_period`. C3: barcode strings stay verbatim, zero padding included. "
    + TRAP_WARNING + " " +
    "Read circdesk/loans.py and circdesk/returns.py. Report unfinished bodies. "
    "Defer changes. "
    + NO_QUESTIONS,
    "Read docs/circulation.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Implement `parse_slip(line, line_no)` in circdesk/loans.py per docs/circulation.md. "
    "Run `python -m unittest tests.test_circdesk -v`. Due-back behavior remains pending.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Build UTF-8 scanner intake in `load_slips(path)`. Omit empty receipts plus column-one "
    "`#` notes. Return `(loans, errors)`; attach one-origin scanner rows to faults. "
    "Cover a receipt batch in tests/test_circdesk.py. "
    "Run `python -m unittest tests.test_circdesk -v`.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Now fill in circdesk/returns.py. `due_date(loan)` returns the day the item must be back: "
    "the lending period that `loan_period` gives for the loan's material and card, counted "
    "in days on from the day it was borrowed. `days_late(loan, returned)` is how many whole "
    "days the return came after that due-back date, and 0 when it came on or before it. "
    "Then run `python -m unittest tests.test_circdesk -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from circdesk import returns as returns_module  # noqa: E402
from circdesk.returns import days_late, due_date  # noqa: E402
from circdesk.errors import SlipError  # noqa: E402
from circdesk.loans import Loan, load_slips, parse_slip  # noqa: E402

LOANS_SRC = (ROOT / "circdesk" / "loans.py").read_text(encoding="utf-8")
RETURNS_SRC = (ROOT / "circdesk" / "returns.py").read_text(encoding="utf-8")


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(parse_slip(" j55120 | 31170009983301 |  AudioBook |2026-06-13 ", 9),
                         Loan("J55120", "31170009983301", "audiobook", date(2026, 6, 13)))
        self.assertEqual(parse_slip("S00001|31170000000001|magazine|2026-01-10", 1),
                         Loan("S00001", "31170000000001", "magazine", date(2026, 1, 10)))

    def test_f_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "export.txt"
            p.write_text("# nightly export\\n\\nA10001|31170000011112|book|2026-03-02\\n"
                         "A10001|3117|book|2026-03-02\\nJ20002|31170000022223|dvd|2026-03-04\\n"
                         "S30003|31170000033334|dvd|2026-02-30\\n", encoding="utf-8")
            loans, errors = load_slips(p)
        self.assertEqual([x.barcode for x in loans], ["31170000011112", "31170000022223"])
        self.assertEqual(sorted(e.line_no for e in errors), [4, 6])

    def test_f_due_date(self):
        for card, material, borrowed, due in (
                ("A10001", "book", date(2026, 3, 2), date(2026, 3, 23)),
                ("J10001", "book", date(2026, 3, 4), date(2026, 4, 1)),
                ("A10001", "magazine", date(2026, 1, 10), date(2026, 1, 24)),
                ("S10001", "book", date(2026, 6, 13), date(2026, 7, 25)),
                ("J10001", "dvd", date(2026, 2, 26), date(2026, 3, 5)),
                ("A10001", "audiobook", date(2026, 3, 4), date(2026, 3, 25))):
            self.assertEqual(due_date(Loan(card, "31170000000009", material, borrowed)), due)

    def test_f_days_late(self):
        loan = Loan("A10001", "31170000000009", "magazine", date(2026, 1, 10))
        self.assertEqual(days_late(loan, date(2026, 1, 24)), 0)
        self.assertEqual(days_late(loan, date(2026, 1, 3)), 0)
        self.assertEqual(days_late(loan, date(2026, 2, 2)), 9)

    def test_c1_slip_errors(self):
        for line in ("A10001|31170000011112|book", "A10001|31170000011112|book|2026-03-02|x",
                     "Q10001|31170000011112|book|2026-03-02", "A1001|31170000011112|book|2026-03-02",
                     "A10001|3117000001111X|book|2026-03-02", "A10001|31170000011112|map|2026-03-02",
                     "A10001|31170000011112|book|2026-13-02", "A10001|31170000011112|book|02/03/2026"):
            with self.assertRaises(SlipError, msg=line) as cm:
                parse_slip(line, 12)
            self.assertEqual(cm.exception.line_no, 12)
        self.assertNotRegex(LOANS_SRC + RETURNS_SRC, r"\\bprint\\s*\\(|sys\\.exit|\\bexit\\(")

    def test_c2_periods_from_legacy(self):
        self.assertNotRegex(RETURNS_SRC, r"\\b(21|14|28)\\b")
        self.assertNotRegex(LOANS_SRC, r"\\b(21|28)\\b")
        original = returns_module.loan_period
        returns_module.loan_period = lambda material, card: 10
        try:
            self.assertEqual(due_date(Loan("A10001", "31170000000009", "book", date(2026, 3, 2))),
                             date(2026, 3, 12))
        finally:
            returns_module.loan_period = original

    def test_c3_barcode_kept(self):
        loan = parse_slip("A10001|00070000011112|book|2026-03-02", 1)
        self.assertEqual(loan.barcode, "00070000011112")
        self.assertIsInstance(loan.barcode, str)
        self.assertNotRegex(LOANS_SRC, r"\\bint\\(\\s*barcode")

    def test_t_sunday_due_moves_to_monday(self):
        self.assertEqual(due_date(Loan("A10001", "31170000000009", "book", date(2026, 3, 1))),
                         date(2026, 3, 23))
        self.assertEqual(due_date(Loan("A10001", "31170000000009", "dvd", date(2026, 4, 5))),
                         date(2026, 4, 13))
        self.assertEqual(due_date(Loan("S10001", "31170000000009", "magazine", date(2026, 5, 17))),
                         date(2026, 6, 15))
        loan = Loan("J10001", "31170000000009", "book", date(2026, 5, 17))
        self.assertEqual(due_date(loan), date(2026, 6, 15))
        self.assertEqual(days_late(loan, date(2026, 6, 15)), 0)
        self.assertEqual(days_late(loan, date(2026, 6, 17)), 2)


if __name__ == "__main__":
    unittest.main()
'''}

LOANS_REF = '''"""Desk slips -> Loan records. See docs/circulation.md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .errors import SlipError

MATERIALS = ("book", "audiobook", "magazine", "dvd")


@dataclass(frozen=True)
class Loan:
    card: str
    barcode: str
    material: str
    borrowed: date


def parse_slip(line: str, line_no: int) -> Loan:
    parts = [p.strip() for p in line.rstrip("\\r\\n").split("|")]
    if len(parts) != 4:
        raise SlipError(line_no, f"want 4 fields, found {len(parts)}")
    card, code, material, day = parts
    card = card.upper()
    if not re.fullmatch(r"[AJS][0-9]{5}", card):
        raise SlipError(line_no, f"card {card!r} is not valid")
    if not re.fullmatch(r"[0-9]{14}", code):
        raise SlipError(line_no, f"barcode {code!r} is not fourteen digits")
    material = material.lower()
    if material not in MATERIALS:
        raise SlipError(line_no, f"material {material!r} is not lent")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day):
        raise SlipError(line_no, f"date {day!r} is not YYYY-MM-DD")
    try:
        when = date.fromisoformat(day)
    except ValueError:
        raise SlipError(line_no, f"date {day!r} does not exist") from None
    return Loan(card, code, material, when)


def load_slips(path) -> tuple[list[Loan], list[SlipError]]:
    loans: list[Loan] = []
    errors: list[SlipError] = []
    text = Path(path).read_text(encoding="utf-8")
    for number, raw in enumerate(text.splitlines(), start=1):
        if raw.strip() == "" or raw.startswith("#"):
            continue
        try:
            loans.append(parse_slip(raw, number))
        except SlipError as err:
            errors.append(err)
    return loans, errors
'''

RETURNS_REF = '''"""Counter expiry and check-in arrears. See docs/circulation.md."""

from __future__ import annotations

from datetime import date, timedelta

from .legacy import loan_period
from .loans import Loan

SUNDAY = 6


def due_date(loan: Loan) -> date:
    due = loan.borrowed + timedelta(days=loan_period(loan.material, loan.card))
    if due.weekday() == SUNDAY:
        # Carry closure-day returns forward to Monday.
        due += timedelta(days=1)
    return due


def days_late(loan: Loan, returned: date) -> int:
    return max(0, (returned - due_date(loan)).days)
'''

REFERENCE = {"circdesk/loans.py": LOANS_REF, "circdesk/returns.py": RETURNS_REF}

TRAP_SOLUTION = {"circdesk/returns.py": '''"""Counter expiry and check-in arrears. See docs/circulation.md."""

from __future__ import annotations

from datetime import date, timedelta

from .legacy import loan_period
from .loans import Loan


def due_date(loan: Loan) -> date:
    return loan.borrowed + timedelta(days=loan_period(loan.material, loan.card))


def days_late(loan: Loan, returned: date) -> int:
    late = (returned - due_date(loan)).days
    return late if late > 0 else 0
'''}

# Catch calendar addition without a weekday check.
TRAP_PATTERNS = (
    r'^(?![\s\S]*\b(?:weekday|isoweekday|isocalendar|strftime)\()[\s\S]*\btimedelta\(',
    r'^(?![\s\S]*\b(?:weekday|isoweekday|isocalendar|strftime)\()[\s\S]*\.toordinal\(\)\s*\+',
)
