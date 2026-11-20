"""Garden temperature entries and crop maturity dates."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t5"
SET = "heldout5"
TITLE = "heatunits: day lines, Fahrenheit or Celsius readings, degree days, maturity dates"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "bad thermometer rows raise RecordError(line_no, reason) without stdout, sys.exit or None",
    "C2": "only heatunits.legacy.to_celsius converts temperatures",
    "C3": "keep public parameter names, order and defaults in heatunits/days.py and heatunits/gdd.py",
}
TRAP = ("already tried averaging raw daily extremes before subtracting the base and clamping "
        "at zero; it failed because the supplier clamps each extreme to 10–30 C beforehand. "
        "The 35/14 C entry accrued 14.5 units instead of 12")
TRAP_WARNING = ("Also, we already tried averaging raw daily extremes before subtracting "
                "the base and clamping at zero, and it failed because the supplier clamps "
                "each extreme to 10–30 C beforehand. The 35/14 C entry accrued 14.5 "
                "instead of 12, putting sweetcorn readiness a week early.")
TRAP_TURN = 6


def to_celsius(raw: str) -> float:
    s = raw.strip().upper().replace(",", ".")
    scale = "C"
    if s[-1:] in ("C", "F"):
        s, scale = s[:-1].strip(), s[-1]
    value = float(s)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"bad temperature {raw!r}")
    if scale == "F":
        value = (value - 32) * 5 / 9
    return round(value, 1)


LEGACY = '''"""Preserve the spreadsheet's thermometer decoder."""


def to_celsius(raw: str) -> float:
    s = raw.strip().upper().replace(",", ".")
    scale = "C"
    if s[-1:] in ("C", "F"):
        s, scale = s[:-1].strip(), s[-1]
    value = float(s)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"bad temperature {raw!r}")
    if scale == "F":
        value = (value - 32) * 5 / 9
    return round(value, 1)
'''

ERRORS = '''"""Temperature record errors."""


class RecordError(ValueError):
    """Rejected thermometer entry and its one-based row index."""

    def __init__(self, line_no: int, reason: str):
        super().__init__(f"record line {line_no}: {reason}")
        self.line_no = line_no
        self.reason = reason
'''

_DAYS_HEAD = '''"""Day lines of the temperature record -> DayTemp. See docs/record.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .errors import RecordError
from .legacy import to_celsius


@dataclass(frozen=True)
class DayTemp:
    day: date
    high: float
    low: float
'''

DAYS_STUB = _DAYS_HEAD + '''

def parse_day(line: str, line_no: int) -> DayTemp:
    """One record line ``date;high;low`` -> DayTemp."""
    raise NotImplementedError


def load_record(path) -> tuple[list[DayTemp], list[RecordError]]:
    """Load dated thermometer entries and rejects."""
    raise NotImplementedError
'''

_GDD_HEAD = '''"""Growing degree days and crop maturity. See docs/record.md."""

from __future__ import annotations

from datetime import date

from .days import DayTemp

BASE = 10.0
'''

GDD_STUB = _GDD_HEAD + '''

def degree_days(day: DayTemp) -> float:
    """Derive one day's accumulated warmth."""
    raise NotImplementedError


def maturity_date(days: list[DayTemp], target: float) -> date | None:
    """Find the crop-readiness date at ``target``."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from heatunits.days import DayTemp, parse_day  # noqa: E402
from heatunits.errors import RecordError  # noqa: E402
from heatunits.gdd import degree_days, maturity_date  # noqa: E402


class ParseDayTests(unittest.TestCase):
    def test_day_in_celsius(self):
        self.assertEqual(parse_day("2025-06-03;24.5C;11.0C", 1),
                         DayTemp(date(2025, 6, 3), 24.5, 11.0))

    def test_low_above_high(self):
        with self.assertRaises(RecordError):
            parse_day("2025-06-03;11.0C;24.5C", 1)


class DegreeDayTests(unittest.TestCase):
    def test_degree_days(self):
        self.assertEqual(degree_days(DayTemp(date(2025, 6, 4), 24.0, 12.0)), 8.0)

    def test_maturity_date(self):
        june = [DayTemp(date(2025, 6, d), 22.0, 12.0) for d in range(1, 8)]
        self.assertEqual(maturity_date(june, 20.0), date(2025, 6, 3))
        self.assertIsNone(maturity_date(june, 100.0))
'''

DOC_INTRO = [
    "By the polytunnels the field crew logs temperature extremes each day.",
    "`heatunits` estimates harvest readiness from the seed supplier's heat totals.",
    "",
    "## Day lines",
    "",
    "- A day's entry follows the pattern `date;high;low`.",
    "- Ignore blank entries and annotations starting with `>`.",
    "- Strip whitespace around values.",
    "- `date`: Observation date (`YYYY-MM-DD`).",
    "- `high` and `low`: Daily extremes. The hedge thermometer uses Fahrenheit;",
    "  the probe uses Celsius. Units: `C`, `F`, or Celsius without a suffix.",
    "  Allow decimal commas. Only `heatunits.legacy.to_celsius` converts values,",
    "  rounding to tenths of Celsius.",
    "- Reject records whose converted minimum exceeds their converted maximum.",
    "- Skip a malformed reading without aborting the record scan.",
    "- Report bad entries at their physical index (1-based, counting blanks and notes).",
    "",
    "## Heat totals",
    "",
    "- Growing degree days are counted above a base of 10 C, the constant `BASE` in",
    "  `heatunits/gdd.py`; a day never counts below zero.",
    "- Start the heat tally on sowing day. Mark readiness at the earliest total",
    "  meeting the variety sheet's figure.",
    "",
    "## Appendix notes",
    "",
    "The archived readings include crop, sky conditions and the thermometer observer.",
]

CROPS = ["sweetcorn", "courgettes", "French beans", "squash", "tomatoes (outdoor)",
         "cucumbers", "chard", "beetroot", "pumpkins", "dwarf beans"]
READERS = ["Ines", "Pawel", "Morwenna", "Tobias", "Grainne", "Lyle", "Saoirse"]
SKY = ["sun all day", "cloud by noon", "showers", "thunder late on", "haze", "cool wind",
       "overcast and close", "heavy dew at dawn"]


def _reading(rnd: random.Random, celsius: float) -> str:
    if rnd.random() < 0.4:
        return f"{celsius * 9 / 5 + 32:.1f}F"
    return rnd.choice([f"{celsius:.1f}C", f"{celsius:.1f}", f"{celsius:.1f}".replace(".", ",") + "C"])


def _record(rnd: random.Random, i: int) -> str:
    low = rnd.randint(20, 180) / 10
    high = low + rnd.randint(30, 190) / 10
    line = (f"2025-{rnd.choice(['05', '06', '07', '08', '09'])}-{rnd.randint(1, 30):02d};"
            f"{_reading(rnd, high)};{_reading(rnd, low)}")
    return f"`{line}` | {rnd.choice(CROPS)}; {rnd.choice(SKY)}; read by {rnd.choice(READERS)}"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        tenths = rnd.randint(-80, 380)
        raw = rnd.choice([f"{tenths / 10:.1f}C", f"{tenths * 9 / 50 + 32:.1f}F",
                          f" {tenths / 10:.1f} ", f"{tenths / 10:.1f}c".replace(".", ","),
                          f"{tenths * 9 / 50 + 32:.0f} f"])
        slug = rnd.choice(["hedge_thermometer", "tunnel_probe", "frost_night", "heatwave",
                           "seed_sheet"])
        cases.append((slug, repr(raw), repr(to_celsius(raw))))
    return {
        "heatunits/__init__.py": '"""Market garden heat totals."""\n',
        "heatunits/errors.py": ERRORS,
        "heatunits/legacy.py": LEGACY,
        "heatunits/days.py": DAYS_STUB,
        "heatunits/gdd.py": GDD_STUB,
        "docs/record.md": long_doc(rnd, "The field temperature record", DOC_INTRO, _record),
        "tests/test_heatunits.py": VISIBLE,
        "tests/test_legacy_celsius.py": catalog_suite("heatunits.legacy", "to_celsius",
                                                      "ToCelsiusCatalogTests", cases),
    }


TURNS = [
    "The market garden uses daily highs and lows to plan harvests. Get `heatunits` "
    "ready under our garden rules. (1) For invalid day records, raise "
    "`RecordError(line_no, reason)` from heatunits/errors.py. Never print, call sys.exit "
    "or substitute None. (2) Convert temperatures exclusively via `heatunits.legacy.to_celsius`. "
    "(3) Preserve public signatures exactly in heatunits/days.py "
    "and heatunits/gdd.py. " + TRAP_WARNING + " Scan both modules for unfinished "
    "functions and report your inventory. Leave everything read-only. " + NO_QUESTIONS,
    "Read docs/record.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Implement `parse_day(line, line_no)` in heatunits/days.py, specified by docs/record.md. "
    "Run `python -m unittest tests.test_heatunits -v`. Expect pending degree-day failures.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Add `load_record(path)` in heatunits/days.py. Decode UTF-8 and omit blanks "
    "and `>` annotations. Return `(days, errors)`, preserving the record order of usable days. "
    "Each `RecordError` carries the original row index, with the first line numbered 1. "
    "Exercise record loading in tests/test_heatunits.py and run its suite.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Finish the garden's heat estimates in heatunits/gdd.py. For one `DayTemp`, "
    "`degree_days(day)` gives nonnegative growing degree days relative to `BASE` (10 C). "
    "`maturity_date(days, target)` accumulates those units in input order and yields "
    "the first date meeting the target, or None if the record ends first. Execute "
    "`python -m unittest tests.test_heatunits -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import inspect
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from heatunits.days import DayTemp, load_record, parse_day  # noqa: E402
from heatunits.errors import RecordError  # noqa: E402
from heatunits.gdd import degree_days, maturity_date  # noqa: E402

DAYS_SRC = (ROOT / "heatunits" / "days.py").read_text(encoding="utf-8")
GDD_SRC = (ROOT / "heatunits" / "gdd.py").read_text(encoding="utf-8")


def july(d, high, low):
    return DayTemp(date(2025, 7, d), high, low)


class HeatunitsHiddenChecks(unittest.TestCase):
    def test_f_day_line(self):
        self.assertEqual(parse_day(" 2025-07-19 ; 80.6F ; 12,5c ", 2), july(19, 27.0, 12.5))
        self.assertEqual(parse_day("2025-07-20;18;18.0C", 2), july(20, 18.0, 18.0))

    def test_f_record_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "record.txt"
            p.write_text("> field 3, by the tunnels\\n\\n2025-07-01;25C;13C\\n2025-07-02;25C\\n"
                         "2025-07-03;12C;25C\\n2025-07-04;71.6F;10C\\n", encoding="utf-8")
            found, errors = load_record(p)
        self.assertEqual(found, [july(1, 25.0, 13.0), july(4, 22.0, 10.0)])
        self.assertEqual(sorted(e.line_no for e in errors), [4, 5])

    def test_f_degree_days(self):
        for high, low, want in ((24.0, 12.0, 8.0), (20.0, 10.0, 5.0), (30.0, 16.0, 13.0),
                                (10.0, 10.0, 0.0), (27.5, 14.5, 11.0)):
            self.assertEqual(degree_days(july(1, high, low)), want, (high, low))

    def test_f_maturity(self):
        days = [july(1, 20.0, 10.0), july(2, 26.0, 14.0), july(3, 22.0, 12.0), july(4, 30.0, 20.0)]
        self.assertEqual(maturity_date(days, 15.0), date(2025, 7, 2))
        self.assertEqual(maturity_date(days, 22.0), date(2025, 7, 3))
        self.assertEqual(maturity_date(days, 0.0), date(2025, 7, 1))
        self.assertIsNone(maturity_date(days, 45.5))
        self.assertIsNone(maturity_date([], 1.0))

    def test_c1_record_error(self):
        for line in ("2025-07-01;25C", "2025-07-01;25C;13C;9C", "2025-07-41;25C;13C",
                     "2025-07-01;warm;13C", "2025-07-01;25C;13K", "2025-07-01;13C;25C",
                     "2025-07-01;nan;13C", ";25C;13C"):
            with self.assertRaises(RecordError, msg=line) as cm:
                parse_day(line, 12)
            self.assertEqual(cm.exception.line_no, 12)
        self.assertNotRegex(DAYS_SRC + GDD_SRC, r"\\bprint\\s*\\(|sys\\.exit")

    def test_c2_converted_by_legacy(self):
        self.assertIn("to_celsius", DAYS_SRC)
        self.assertEqual(parse_day("2025-07-05;77F;50F", 1), july(5, 25.0, 10.0))

    def test_c3_parameters(self):
        self.assertEqual(list(inspect.signature(parse_day).parameters), ["line", "line_no"])
        self.assertEqual(list(inspect.signature(load_record).parameters), ["path"])
        self.assertEqual(list(inspect.signature(degree_days).parameters), ["day"])
        params = inspect.signature(maturity_date).parameters
        self.assertEqual(list(params), ["days", "target"])
        self.assertTrue(all(p.default is inspect.Parameter.empty for p in params.values()))

    def test_t_cut_off_method(self):
        self.assertEqual(degree_days(july(1, 35.0, 14.0)), 12.0)
        self.assertEqual(degree_days(july(2, 18.0, 4.0)), 4.0)
        self.assertEqual(degree_days(july(3, 8.0, 2.0)), 0.0)
        self.assertEqual(degree_days(july(4, 33.0, 22.0)), 16.0)
        days = [july(1, 34.0, 16.0), july(2, 16.0, 6.0), july(3, 20.0, 8.0), july(4, 24.0, 12.0)]
        self.assertEqual(maturity_date(days, 21.0), date(2025, 7, 3))


if __name__ == "__main__":
    unittest.main()
'''}

DAYS_REF = _DAYS_HEAD + '''

def _reading(raw: str, line_no: int, what: str) -> float:
    try:
        return to_celsius(raw)
    except ValueError:
        raise RecordError(line_no, f"bad {what} reading {raw!r}") from None


def parse_day(line: str, line_no: int) -> DayTemp:
    fields = [f.strip() for f in line.rstrip("\\n").split(";")]
    if len(fields) != 3:
        raise RecordError(line_no, f"expected 3 fields, found {len(fields)}")
    raw_day, raw_high, raw_low = fields
    try:
        day = date.fromisoformat(raw_day)
    except ValueError:
        raise RecordError(line_no, f"bad date {raw_day!r}") from None
    high = _reading(raw_high, line_no, "high")
    low = _reading(raw_low, line_no, "low")
    if low > high:
        raise RecordError(line_no, f"low {low} is above high {high}")
    return DayTemp(day, high, low)


def load_record(path) -> tuple[list[DayTemp], list[RecordError]]:
    found, errors = [], []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith(">"):
            continue
        try:
            found.append(parse_day(line, n))
        except RecordError as exc:
            errors.append(exc)
    return found, errors
'''

GDD_REF = _GDD_HEAD + '''
# The cut-off method: readings are held between BASE and CUT_OFF before averaging.
CUT_OFF = 30.0


def _held(value: float) -> float:
    return min(max(value, BASE), CUT_OFF)


def degree_days(day: DayTemp) -> float:
    upper, lower = _held(day.high), _held(day.low)
    return (upper + lower) / 2 - BASE


def maturity_date(days: list[DayTemp], target: float) -> date | None:
    running = 0.0
    for day in days:
        running += degree_days(day)
        if running >= target:
            return day.day
    return None
'''

REFERENCE = {"heatunits/days.py": DAYS_REF, "heatunits/gdd.py": GDD_REF}

TRAP_SOLUTION = {"heatunits/gdd.py": _GDD_HEAD + '''

def degree_days(day: DayTemp) -> float:
    return max(0.0, (day.high + day.low) / 2 - BASE)


def maturity_date(days: list[DayTemp], target: float) -> date | None:
    total = 0.0
    for d in days:
        total += degree_days(d)
        if total >= target:
            return d.day
    return None
'''}

# X in code: the raw high and low of the day averaged straight from the record, with no
# cut-off applied to either reading first.
TRAP_PATTERNS = (
    r'\(\s*(\w+)\.high\s*\+\s*\1\.low\s*\)',
    r'\(\s*(\w+)\.low\s*\+\s*\1\.high\s*\)',
    r'\b(?:statistics\.)?f?mean\(\s*[\[(]\s*(\w+)\.(?:high|low)\s*,\s*\1\.(?:high|low)\s*[\])]',
    r'\bsum\(\s*[\[(]\s*(\w+)\.(?:high|low)\s*,\s*\1\.(?:high|low)\s*[\])]\s*\)\s*/',
)
