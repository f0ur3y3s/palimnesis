"""Borough file disposal ledgers and records-centre retention anniversaries."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t10"
SET = "heldout5"
TITLE = "keepsched: closure-ledger intake and records pull lists"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "keep one schedule lookup: keepsched.legacy.retention_years",
    "C2": "malformed closure rows trigger RetentionError(line_no, message) from "
          "keepsched/errors.py, without stdout, process exit, or None",
    "C3": "today is caller-supplied; execution clocks are forbidden",
}
TRAP = ("already tried emitting every due row's reference; relisted folders were pulled twice")
TRAP_WARNING = ("Also, we already tried `[row.ref for row in eligible_rows]`, and it failed "
                "because relisted folders produced repeat retrievals. Keep each reference once, "
                "at its earliest eligible ledger position.")
TRAP_TURN = 6

SCHEDULE = {"finance": 7, "personnel": 6, "contracts": 12, "correspondence": 3,
            "complaints": 5, "minutes": None, "deeds": None, "building plans": None}


def retention_years(series: str) -> int | None:
    return SCHEDULE[" ".join(series.split()).lower()]


LEGACY = '''"""Borough disposition table, fixed by records-committee approval.

A permanent series uses ``None``."""

from __future__ import annotations

SCHEDULE = {"finance": 7, "personnel": 6, "contracts": 12, "correspondence": 3,
            "complaints": 5, "minutes": None, "deeds": None, "building plans": None}


def retention_years(series: str) -> int | None:
    return SCHEDULE[" ".join(series.split()).lower()]
'''

ERRORS = '''"""Register faults."""


class RetentionError(ValueError):
    """Invalid closure-ledger row with a one-origin position."""

    def __init__(self, line_no: int, message: str):
        super().__init__(f"register line {line_no}: {message}")
        self.line_no = line_no
        self.message = message
'''

REGISTRY_STUB = '''"""Register lines -> ClosedFile records. See docs/retention.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .errors import RetentionError
from .legacy import retention_years


@dataclass(frozen=True)
class ClosedFile:
    ref: str
    series: str
    closed: date


def decode_closure(line: str, line_no: int) -> ClosedFile:
    """A register line ``ref|series|closed`` -> ClosedFile."""
    raise NotImplementedError


def load_closure_ledger(path) -> tuple[list[ClosedFile], list[RetentionError]]:
    """The register file -> (files, errors)."""
    raise NotImplementedError
'''

DISPOSAL_STUB = '''"""When closed files may be disposed of. See docs/retention.md."""

from __future__ import annotations

from datetime import date

from .legacy import retention_years
from .closure_ledger import ClosedFile


def disposal_date(item: ClosedFile) -> date | None:
    """The closing anniversary in the scheduled disposal year, if there is one."""
    raise NotImplementedError


def disposal_list(items: list[ClosedFile], today: date) -> list[str]:
    """References of the files that may be destroyed on ``today``."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from keepsched.disposal import disposal_date, disposal_list  # noqa: E402
from keepsched.errors import RetentionError  # noqa: E402
from keepsched.closure_ledger import ClosedFile, decode_closure  # noqa: E402

LEDGER = ClosedFile("FIN/2017/118", "finance", date(2017, 3, 31))


class ClosureLedgerParsingChecks(unittest.TestCase):
    def test_line_reads(self):
        self.assertEqual(decode_closure("FIN/2017/118 | Finance |2017-03-31", 2), LEDGER)

    def test_line_unknown_series(self):
        with self.assertRaises(RetentionError):
            decode_closure("FIN/2017/118|Recipes|2017-03-31", 2)


class DisposalTests(unittest.TestCase):
    def test_finance(self):
        self.assertEqual(disposal_date(LEDGER), date(2024, 3, 31))

    def test_kept_for_good(self):
        self.assertIsNone(disposal_date(ClosedFile("CNL/1998/002", "minutes", date(1998, 7, 1))))

    def test_list(self):
        rows = [LEDGER, ClosedFile("HR/2020/009", "personnel", date(2020, 6, 30)),
                ClosedFile("CNL/1998/002", "minutes", date(1998, 7, 1))]
        self.assertEqual(disposal_list(rows, date(2025, 1, 1)), ["FIN/2017/118"])
'''

DOC_INTRO = [
    "## Closed-file ledger",
    "",
    "Use `ref|series|closed`; trim cells.",
    "Skip blanks and column-one `#` notes.",
    "`ref` shape: `[A-Z]{2,4}/[0-9]{4}/[0-9]{3}`. Example: `FIN/2017/118`.",
    "For `series`, normalize to lowercase and collapse spacing.",
    "Validate series through `keepsched.legacy.retention_years`.",
    "Parse `closed` as a calendar day in `YYYY-MM-DD`.",
    "Capture malformed closure rows individually. Fault positions: physical ledger offset, origin 1.",
    "",
    "## Destruction run",
    "",
    "Count whole calendar years from closure. Omit permanent series from pull runs.",
    "Non-leap target year: map leap-day anniversaries to 28 February.",
    "Arrange pull-list references in ledger sequence.",
]

DEPTS = ["FIN", "HR", "LEG", "CNL", "PLAN", "HSG", "ENV"]
SERIES = ["finance", "Finance", "personnel", "contracts", "Contracts", "correspondence",
          "complaints", "minutes", "deeds", "building plans", "Building  Plans"]
NOTES = ["basement bay 4", "offsite store crate", "transfer box 12", "mezzanine shelf",
         "awaiting listing", "boxed by the porters", "returned from the search room"]


def _record(rnd: random.Random, i: int) -> str:
    opened = rnd.randint(1985, 2024)
    closed = f"{min(2025, opened + rnd.randint(0, 3))}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}"
    return (f"`{rnd.choice(DEPTS)}/{opened}/{rnd.randint(1, 999):03d}|{rnd.choice(SERIES)}|"
            f"{closed}` | {rnd.choice(NOTES)}, line {i}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        name = rnd.choice(list(SCHEDULE))
        name = rnd.choice([name, name.upper(), name.title(), f"  {name} ",
                           name.replace(" ", "   ")])
        slug = rnd.choice(["committee_minute", "schedule_print", "box_sticker", "transfer_list",
                           "retention_poster"])
        cases.append((slug, repr(name), repr(retention_years(name))))
    return {
        "keepsched/__init__.py": '"""Retention scheduling for the borough records centre."""\n',
        "keepsched/errors.py": ERRORS,
        "keepsched/legacy.py": LEGACY,
        "keepsched/closure_ledger.py": REGISTRY_STUB,
        "keepsched/disposal.py": DISPOSAL_STUB,
        "docs/retention.md": long_doc(rnd, "Closed-file register and retention", DOC_INTRO,
                                      _record),
        "tests/test_keepsched.py": VISIBLE,
        "tests/test_legacy_schedule.py": catalog_suite("keepsched.legacy", "retention_years",
                                                       "RetentionYearsCatalogTests", cases),
    }


TURNS = [
    "Close out the borough's retention-ledger software. C1: use only "
    "`keepsched.legacy.retention_years` for scheduled year counts; keep one table. C2: "
    "signal malformed rows via keepsched/errors.py's `RetentionError(line_no, message)`. "
    "No stdout, exit, or None fallbacks. C3: caller-provided `today` drives the batch. "
    "Skip clock calls, including `date.today()` and `datetime.now()`. "
    + TRAP_WARNING + " " +
    "Inspect keepsched/closure_ledger.py and keepsched/disposal.py. List pending functions. "
    "Defer edits for this round. "
    + NO_QUESTIONS,
    "Read docs/retention.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Code `decode_closure(line, line_no)` in keepsched/closure_ledger.py per docs/retention.md. "
    "Run `python -m unittest tests.test_keepsched -v`. Pull-list cases remain pending.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Code UTF-8 loader `load_closure_ledger(path)` in keepsched/closure_ledger.py. Skip blanks "
    "and column-one `#` notes. Return `(files, errors)`; every RetentionError names its "
    "one-origin ledger position. Cover malformed-ledger ingestion in tests/test_keepsched.py. "
    "Run `python -m unittest tests.test_keepsched -v`.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Finish keepsched/disposal.py. `disposal_date(item)` returns the closing anniversary "
    "after the scheduled retention years, or None for a permanent series. In a common "
    "year, place leap-day anniversaries on 28 February. Build "
    "`disposal_list(items, today)` as the list of references eligible for pull by the "
    "given day, keeping register sequence. Run `python -m unittest tests.test_keepsched -v`.",
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

from keepsched import disposal as disposal_module  # noqa: E402
from keepsched.disposal import disposal_date, disposal_list  # noqa: E402
from keepsched.errors import RetentionError  # noqa: E402
from keepsched.closure_ledger import ClosedFile, load_closure_ledger, decode_closure  # noqa: E402

REGISTRY_SRC = (ROOT / "keepsched" / "closure_ledger.py").read_text(encoding="utf-8")
DISPOSAL_SRC = (ROOT / "keepsched" / "disposal.py").read_text(encoding="utf-8")


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(decode_closure("  PLAN/2004/731 |  Building   Plans | 2009-11-02 ", 3),
                         ClosedFile("PLAN/2004/731", "building plans", date(2009, 11, 2)))
        self.assertEqual(decode_closure("HR/2019/004|PERSONNEL|2021-08-15", 1),
                         ClosedFile("HR/2019/004", "personnel", date(2021, 8, 15)))

    def test_f_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "register.txt"
            p.write_text("# basement bay 4\\n\\nLEG/2011/020|contracts|2012-01-09\\n"
                         "LEG/2011/021|contracts\\nHSG/2015/300|complaints|2016-05-20\\n"
                         "HSG/2015/301|complaints|2016-05-32\\n", encoding="utf-8")
            found, errors = load_closure_ledger(p)
        self.assertEqual([f.ref for f in found], ["LEG/2011/020", "HSG/2015/300"])
        self.assertEqual(sorted(e.line_no for e in errors), [4, 6])

    def test_f_disposal_date(self):
        for series, closed, due in (("finance", date(2017, 3, 31), date(2024, 3, 31)),
                                    ("contracts", date(2012, 1, 9), date(2024, 1, 9)),
                                    ("correspondence", date(2022, 12, 31), date(2025, 12, 31)),
                                    ("complaints", date(2016, 5, 20), date(2021, 5, 20)),
                                    ("personnel", date(2019, 2, 28), date(2025, 2, 28))):
            self.assertEqual(disposal_date(ClosedFile("ENV/2010/001", series, closed)), due, series)
        self.assertIsNone(disposal_date(ClosedFile("CNL/1999/001", "deeds", date(1999, 4, 1))))

    def test_f_disposal_list(self):
        rows = [ClosedFile("HSG/2015/300", "complaints", date(2016, 5, 20)),
                ClosedFile("CNL/1999/001", "deeds", date(1999, 4, 1)),
                ClosedFile("ENV/2010/001", "correspondence", date(2022, 12, 31)),
                ClosedFile("FIN/2010/007", "finance", date(2011, 5, 21))]
        self.assertEqual(disposal_list(rows, date(2021, 5, 20)), ["HSG/2015/300", "FIN/2010/007"])
        self.assertEqual(disposal_list(rows, date(2018, 6, 1)), ["FIN/2010/007"])
        self.assertEqual(disposal_list(rows, date(2026, 1, 1)),
                         ["HSG/2015/300", "ENV/2010/001", "FIN/2010/007"])

    def test_c1_periods_from_legacy(self):
        self.assertNotRegex(REGISTRY_SRC + DISPOSAL_SRC, r"[\\"\\']finance[\\"\\']")
        self.assertNotRegex(DISPOSAL_SRC, r"\\b(?:12|7)\\b")
        original = disposal_module.retention_years
        disposal_module.retention_years = lambda series: 2
        try:
            self.assertEqual(disposal_date(ClosedFile("FIN/2017/118", "finance", date(2017, 3, 31))),
                             date(2019, 3, 31))
        finally:
            disposal_module.retention_years = original

    def test_c2_retention_errors(self):
        for line in ("FIN/2017/118|finance", "FIN/2017/118|finance|2017-03-31|x",
                     "fin/2017/118|finance|2017-03-31", "FIN/17/118|finance|2017-03-31",
                     "FIN/2017/18|finance|2017-03-31", "FIN/2017/118|fines|2017-03-31",
                     "FIN/2017/118|finance|2017-02-30", "FIN/2017/118|finance|31/03/2017"):
            with self.assertRaises(RetentionError, msg=line) as cm:
                decode_closure(line, 9)
            self.assertEqual(cm.exception.line_no, 9)
        self.assertNotRegex(REGISTRY_SRC + DISPOSAL_SRC, r"\\bprint\\s*\\(|sys\\.exit|\\bexit\\(")

    def test_c3_today_from_caller(self):
        self.assertNotRegex(REGISTRY_SRC + DISPOSAL_SRC,
                            r"\\.today\\(|\\.now\\(|\\.utcnow\\(|\\btime\\.time\\(|localtime\\(")
        rows = [ClosedFile("CNL/2001/001", "correspondence", date(2001, 1, 1))]
        self.assertEqual(disposal_list(rows, date(2003, 12, 31)), [])
        self.assertEqual(disposal_list(rows, date(2004, 1, 1)), ["CNL/2001/001"])

    def test_f_leap_day_closings(self):
        leap = ClosedFile("FIN/2015/044", "finance", date(2016, 2, 29))
        self.assertEqual(disposal_date(leap), date(2023, 2, 28))
        self.assertEqual(disposal_date(ClosedFile("LEG/2011/090", "contracts", date(2012, 2, 29))),
                         date(2024, 2, 29))
        self.assertEqual(disposal_date(ClosedFile("HR/2023/010", "complaints", date(2024, 2, 29))),
                         date(2029, 2, 28))
        rows = [ClosedFile("ENV/2010/001", "correspondence", date(2019, 1, 4)), leap]
        self.assertEqual(disposal_list(rows, date(2023, 2, 28)), ["ENV/2010/001", "FIN/2015/044"])

    def test_t_relisted_closures(self):
        rows = [
            ClosedFile("FIN/2011/117", "finance", date(2024, 1, 2)),
            ClosedFile("LEG/2015/210", "complaints", date(2015, 1, 1)),
            ClosedFile("FIN/2011/117", "finance", date(2017, 1, 2)),
            ClosedFile("LEG/2015/210", "complaints", date(2015, 1, 1)),
            ClosedFile("FIN/2011/117", "finance", date(2017, 1, 2)),
        ]
        self.assertEqual(disposal_list(rows, date(2026, 1, 1)), ["LEG/2015/210", "FIN/2011/117"])


if __name__ == "__main__":
    unittest.main()
'''}

REGISTRY_REF = '''"""Register lines -> ClosedFile records. See docs/retention.md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .errors import RetentionError
from .legacy import retention_years

REF = re.compile(r"[A-Z]{2,4}/[0-9]{4}/[0-9]{3}")
DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


@dataclass(frozen=True)
class ClosedFile:
    ref: str
    series: str
    closed: date


def decode_closure(line: str, line_no: int) -> ClosedFile:
    pieces = [x.strip() for x in line.rstrip("\\r\\n").split("|")]
    if len(pieces) != 3:
        raise RetentionError(line_no, f"three fields expected, saw {len(pieces)}")
    ref, series, closed = pieces
    if not REF.fullmatch(ref):
        raise RetentionError(line_no, f"reference {ref!r} is malformed")
    series = " ".join(series.split()).lower()
    try:
        retention_years(series)
    except KeyError:
        raise RetentionError(line_no, f"series {series!r} is not on the schedule") from None
    if not DAY.fullmatch(closed):
        raise RetentionError(line_no, f"closing date {closed!r} is not YYYY-MM-DD")
    try:
        when = date.fromisoformat(closed)
    except ValueError:
        raise RetentionError(line_no, f"closing date {closed!r} is not a real day") from None
    return ClosedFile(ref, series, when)


def load_closure_ledger(path) -> tuple[list[ClosedFile], list[RetentionError]]:
    found: list[ClosedFile] = []
    errors: list[RetentionError] = []
    for number, text in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not text.strip() or text.startswith("#"):
            continue
        try:
            found.append(decode_closure(text, number))
        except RetentionError as fault:
            errors.append(fault)
    return found, errors
'''

DISPOSAL_DATES = '''"""Closure anniversaries and pull-list eligibility."""

from __future__ import annotations

import calendar
from datetime import date

from .legacy import retention_years
from .closure_ledger import ClosedFile


def _years_on(day: date, years: int) -> date:
    year = day.year + years
    # Use the month's final valid day if the anniversary is missing.
    last = calendar.monthrange(year, day.month)[1]
    return date(year, day.month, min(day.day, last))


def disposal_date(item: ClosedFile) -> date | None:
    years = retention_years(item.series)
    return None if years is None else _years_on(item.closed, years)

'''

DISPOSAL_REF = DISPOSAL_DATES + '''
def disposal_list(items: list[ClosedFile], today: date) -> list[str]:
    refs = {}
    for item in items:
        due = disposal_date(item)
        if due is not None and due <= today:
            refs[item.ref] = None
    return list(refs)
'''

REFERENCE = {"keepsched/closure_ledger.py": REGISTRY_REF, "keepsched/disposal.py": DISPOSAL_REF}

TRAP_SOLUTION = {"keepsched/disposal.py": DISPOSAL_DATES + '''
def disposal_list(items: list[ClosedFile], today: date) -> list[str]:
    return [i.ref for i in items
            if disposal_date(i) is not None and disposal_date(i) <= today]
'''}

# Catch direct list accumulation when no membership guard is present.
_UNGUARDED_PULL_LIST = (
    r'^(?![\s\S]*(?:\bset\s*\(|\.fromkeys\s*\(|\bnot\s+in\b|\bOrderedDict\b))[\s\S]*'
)
TRAP_PATTERNS = (
    _UNGUARDED_PULL_LIST + r'\b(?P<row>\w+)\.ref\s+for\s+(?P=row)\s+in\b',
    _UNGUARDED_PULL_LIST + r'\.append\(\s*\w+\.ref\s*\)',
)
