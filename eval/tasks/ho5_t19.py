"""Quarterly water register rounds settle the district's supply bills."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t19"
SET = "heldout5"
TITLE = "meterbook: reading-round lines, meter serials, newest readings, water consumption"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "raise ReadingError(line_no, message) for unusable rounds without output or exit",
    "C2": "group serial digits exclusively through meterbook.legacy.meter_serial",
    "C3": "preserve supplied lists and Reading objects when ordering entries",
}
TRAP = ("already tried taking the later register minus the earlier one as integers; it failed "
        "because the dials roll over to zero after all nines, so a meter read at 99950 and "
        "then at 00020 showed a consumption of -99930 and the household was sent a huge credit "
        "instead of a bill for 70 cubic metres")
TRAP_WARNING = ("Also, we already tried taking the later register minus the earlier one as "
                "plain integers, and it failed because the dials roll over to zero once they "
                "pass all nines: a meter read at 99950 and next at 00020 came out at -99930 "
                "cubic metres, and that household got a huge credit note instead of a bill "
                "for 70.")
TRAP_TURN = 6


def meter_serial(raw: str) -> str:
    s = raw.strip().upper()
    for ch in " -/.":
        s = s.replace(ch, "")
    if len(s) != 9 or not s[0].isalpha() or not s[0].isascii() or not s[1:].isdigit():
        raise ValueError(f"bad meter serial {raw!r}")
    return f"{s[0]}-{s[1:5]}-{s[5:]}"


LEGACY = '''"""Meter serials grouped the way they are stamped on the meter body. The billing system
looks meters up by this exact text (do not change)."""


def meter_serial(raw: str) -> str:
    s = raw.strip().upper()
    for ch in " -/.":
        s = s.replace(ch, "")
    if len(s) != 9 or not s[0].isalpha() or not s[0].isascii() or not s[1:].isdigit():
        raise ValueError(f"bad meter serial {raw!r}")
    return f"{s[0]}-{s[1:5]}-{s[5:]}"
'''

ERRORS = '''"""Errors in a meter-round file."""


class ReadingError(ValueError):
    """A round line that cannot be used; ``line_no`` is its place in the file, from 1."""

    def __init__(self, line_no: int, message: str):
        super().__init__(f"round line {line_no}: {message}")
        self.line_no = line_no
        self.message = message
'''

READINGS_STUB = '''"""Lines of a meter-round file. See docs/meter_rounds.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .errors import ReadingError
from .legacy import meter_serial


@dataclass(frozen=True)
class Reading:
    serial: str
    day: date
    register: str


def parse_reading(line: str, line_no: int) -> Reading:
    """One round line ``serial|date|register`` -> Reading."""
    raise NotImplementedError


def latest_readings(readings: list[Reading]) -> dict[str, Reading]:
    """The most recent reading of each meter."""
    raise NotImplementedError
'''

USAGE_STUB = '''"""Water used between readings. See docs/meter_rounds.md."""

from __future__ import annotations

from .readings import Reading


def units_used(earlier: Reading, later: Reading) -> int:
    """Cubic metres recorded between two readings of one meter."""
    raise NotImplementedError


def consumption(readings: list[Reading]) -> dict[str, int]:
    """Cubic metres recorded by each meter over all its readings."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from meterbook.errors import ReadingError  # noqa: E402
from meterbook.readings import Reading, latest_readings, parse_reading  # noqa: E402
from meterbook.usage import consumption, units_used  # noqa: E402

S1, S2 = "W-3108-7752", "K-0046-1199"


class RoundLineTests(unittest.TestCase):
    def test_line(self):
        self.assertEqual(parse_reading("w 3108 7752|2026-04-14|04821", 1),
                         Reading(S1, date(2026, 4, 14), "04821"))

    def test_register_with_letters(self):
        with self.assertRaises(ReadingError):
            parse_reading("w 3108 7752|2026-04-14|048O1", 1)


class LatestTests(unittest.TestCase):
    def test_latest(self):
        a = Reading(S1, date(2026, 1, 9), "04500")
        b = Reading(S1, date(2026, 4, 14), "04821")
        c = Reading(S2, date(2026, 2, 2), "0310")
        self.assertEqual(latest_readings([b, c, a]), {S1: b, S2: c})


class UsageTests(unittest.TestCase):
    def test_units(self):
        self.assertEqual(units_used(Reading(S1, date(2026, 1, 9), "04821"),
                                    Reading(S1, date(2026, 4, 14), "05000")), 179)

    def test_consumption(self):
        rs = [Reading(S1, date(2026, 4, 14), "04821"), Reading(S2, date(2026, 2, 2), "0310"),
              Reading(S1, date(2026, 1, 9), "04500"), Reading(S1, date(2026, 7, 20), "05102")]
        self.assertEqual(consumption(rs), {S1: 602, S2: 0})
'''

DOC_INTRO = [
    "Quarterly meter rounds produce handheld files with `serial|date|register` entries.",
    "Omit `#` notes and empty rows. Preserve their positions in the original line numbering from 1.",
    "Serial punctuation varies at entry. `meterbook.legacy.meter_serial` makes the filing key, so",
    "`w 3108 7752` produces `W-3108-7752`.",
    "Use `YYYY-MM-DD` for collection dates and the literal four, five or six register digits",
    "for whole cubic metres. Leading zeroes belong to the register string.",
    "Send an invalid record to billing exceptions individually, leaving other readings available.",
    "Billing consumption uses sequential date readings within each serial's record.",
]


def _serial(rnd: random.Random) -> str:
    letter = rnd.choice("WKHPRT")
    d = f"{rnd.randint(0, 99999999):08d}"
    return rnd.choice([f"{letter}-{d[:4]}-{d[4:]}", f"{letter.lower()} {d[:4]} {d[4:]}",
                       f"{letter}{d}", f" {letter}/{d[:2]}.{d[2:5]}.{d[5:]} ",
                       f"{letter.lower()}-{d}"])


def _record(rnd: random.Random, i: int) -> str:
    dials = rnd.choice([4, 5, 5, 6])
    reg = f"{rnd.randint(0, 10 ** dials - 1):0{dials}d}"
    day = f"2026-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}"
    return (f"`{_serial(rnd)}|{day}|{reg}` | "
            f"{rnd.choice(['north round', 'south round', 'access refused', 'card left'])}, "
            f"reading {i}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = _serial(rnd)
        slug = rnd.choice(["handheld_upload", "meter_exchange", "customer_card", "leak_survey",
                           "final_reading"])
        cases.append((slug, repr(raw), repr(meter_serial(raw))))
    return {
        "meterbook/__init__.py": '"""Water-meter rounds."""\n',
        "meterbook/errors.py": ERRORS,
        "meterbook/legacy.py": LEGACY,
        "meterbook/readings.py": READINGS_STUB,
        "meterbook/usage.py": USAGE_STUB,
        "docs/meter_rounds.md": long_doc(rnd, "Meter-round files and consumption", DOC_INTRO,
                                         _record),
        "tests/test_meterbook.py": VISIBLE,
        "tests/test_legacy_serials.py": catalog_suite("meterbook.legacy", "meter_serial",
                                                      "MeterSerialCatalogTests", cases),
    }


TURNS = [
    "The billing office needs its quarterly register importer `meterbook`. Use "
    "`ReadingError(line_no, message)` from meterbook/errors.py for unusable lines without printing "
    "or exiting. Group all stamped serials exclusively with `meterbook.legacy.meter_serial`. Never "
    "mutate incoming lists or Reading objects. " + TRAP_WARNING + " Audit meterbook/readings.py "
    "and meterbook/usage.py for unfinished features before editing. " + NO_QUESTIONS,
    "Read docs/meter_rounds.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Make `parse_reading(line, line_no)` decode quarterly rows per the meter rounds manual. Check "
    "with `python -m unittest tests.test_meterbook -v`; disregard stubs beyond import for this step.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Complete `latest_readings(readings)` to index each serial by its most recent reading. For "
    "equal dates, choose the later list entry. Add a same-date case under tests/test_meterbook.py "
    "and execute that suite.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Now write meterbook/usage.py. `units_used(earlier, later)` returns how many cubic "
    "metres one meter recorded between an earlier and a later reading of it. "
    "`consumption(readings)` maps every serial, in the order the serials "
    "first occur, to the total that meter recorded across its readings taken in date "
    "order (readings on the same date keep their list order); a meter read only once has "
    "0. Run `python -m unittest tests.test_meterbook -v` when it's done.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from meterbook.errors import ReadingError  # noqa: E402
from meterbook.readings import Reading, latest_readings, parse_reading  # noqa: E402
from meterbook.usage import consumption, units_used  # noqa: E402

READINGS_SRC = (ROOT / "meterbook" / "readings.py").read_text(encoding="utf-8")
USAGE_SRC = (ROOT / "meterbook" / "usage.py").read_text(encoding="utf-8")
SA, SB, SC = "H-2201-0378", "P-9000-0001", "T-5555-1234"


def _r(serial, m, d, reg):
    return Reading(serial, date(2026, m, d), reg)


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(parse_reading(" h/22.010.378 | 2026-09-30 | 000412 ", 6),
                         _r(SA, 9, 30, "000412"))
        self.assertEqual(parse_reading("P-90000001|2026-01-02|0007", 1), _r(SB, 1, 2, "0007"))

    def test_f_latest(self):
        a, b, c = _r(SA, 3, 1, "01000"), _r(SA, 6, 1, "01200"), _r(SA, 6, 1, "01210")
        d = _r(SB, 2, 2, "4400")
        self.assertEqual(latest_readings([c, d, a, b]), {SA: b, SB: d})
        self.assertEqual(latest_readings([]), {})

    def test_f_units(self):
        self.assertEqual(units_used(_r(SA, 1, 1, "01000"), _r(SA, 4, 1, "01250")), 250)
        self.assertEqual(units_used(_r(SA, 1, 1, "0007"), _r(SA, 4, 1, "0007")), 0)
        self.assertEqual(units_used(_r(SA, 1, 1, "000999"), _r(SA, 4, 1, "001000")), 1)

    def test_f_consumption(self):
        rs = [_r(SB, 5, 1, "4500"), _r(SA, 4, 1, "01250"), _r(SA, 1, 1, "01000"),
              _r(SB, 2, 2, "4400"), _r(SC, 3, 3, "777"), _r(SA, 7, 1, "01400")]
        self.assertEqual(consumption(rs), {SB: 100, SA: 400, SC: 0})
        self.assertEqual(list(consumption(rs)), [SB, SA, SC])
        self.assertEqual(consumption([]), {})

    def test_c1_reading_error(self):
        for line in ("W-3108-7752|2026-04-14", "W-3108-7752|2026-04-14|04821|x",
                     "W-3108-775|2026-04-14|04821", "W-3108-7752|2026-13-01|04821",
                     "W-3108-7752|14/04/2026|04821", "W-3108-7752|2026-04-14|481",
                     "W-3108-7752|2026-04-14|0004821", "W-3108-7752|2026-04-14|-4821"):
            with self.assertRaises(ReadingError, msg=line) as cm:
                parse_reading(line, 21)
            self.assertEqual(cm.exception.line_no, 21)
        self.assertNotRegex(READINGS_SRC + USAGE_SRC, r"\\bprint\\s*\\(|sys\\.exit|\\bexit\\(|\\bquit\\(")

    def test_c2_serials_from_legacy(self):
        self.assertIn("meter_serial", READINGS_SRC)
        self.assertNotRegex(READINGS_SRC, r"\\[\\s*1\\s*:\\s*5\\s*\\]|\\[\\s*5\\s*:\\s*\\]")
        self.assertEqual(parse_reading("t 5555 1234|2026-02-02|1000", 1).serial, SC)

    def test_c3_inputs_untouched(self):
        rs = [_r(SA, 7, 1, "01400"), _r(SB, 5, 1, "4500"), _r(SA, 1, 1, "01000"),
              _r(SB, 2, 2, "4400")]
        before = list(rs)
        latest_readings(rs)
        self.assertEqual(rs, before)
        consumption(rs)
        self.assertEqual(rs, before)

    def test_t_dials_roll_over(self):
        self.assertEqual(units_used(_r(SA, 1, 1, "99950"), _r(SA, 4, 1, "00020")), 70)
        self.assertEqual(units_used(_r(SB, 1, 1, "9990"), _r(SB, 4, 1, "0005")), 15)
        self.assertEqual(units_used(_r(SC, 1, 1, "999999"), _r(SC, 4, 1, "000000")), 1)
        rs = [_r(SA, 1, 1, "99800"), _r(SA, 3, 1, "00110"), _r(SA, 2, 1, "99990")]
        self.assertEqual(consumption(rs), {SA: 310})


if __name__ == "__main__":
    unittest.main()
'''}

READINGS_REF = '''"""Lines of a meter-round file. See docs/meter_rounds.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .errors import ReadingError
from .legacy import meter_serial


@dataclass(frozen=True)
class Reading:
    serial: str
    day: date
    register: str


def parse_reading(line: str, line_no: int) -> Reading:
    parts = [p.strip() for p in line.rstrip("\\r\\n").split("|")]
    if len(parts) != 3:
        raise ReadingError(line_no, f"expected 3 fields, found {len(parts)}")
    serial, day, register = parts
    try:
        serial = meter_serial(serial)
    except ValueError as exc:
        raise ReadingError(line_no, str(exc)) from None
    if len(day) != 10 or day[4] != "-" or day[7] != "-":
        raise ReadingError(line_no, f"bad date {day!r}")
    try:
        when = date.fromisoformat(day)
    except ValueError:
        raise ReadingError(line_no, f"bad date {day!r}") from None
    if not (register.isascii() and register.isdigit() and 4 <= len(register) <= 6):
        raise ReadingError(line_no, f"bad register {register!r}")
    return Reading(serial, when, register)


def latest_readings(readings: list[Reading]) -> dict[str, Reading]:
    newest: dict[str, Reading] = {}
    for r in readings:
        seen = newest.get(r.serial)
        if seen is None or r.day >= seen.day:
            newest[r.serial] = r
    return newest
'''

USAGE_REF = '''"""Water used between readings. See docs/meter_rounds.md."""

from __future__ import annotations

from .readings import Reading


def units_used(earlier: Reading, later: Reading) -> int:
    # The dials wrap to zero after all nines, so the step is taken modulo their range.
    span = 10 ** len(later.register)
    return (int(later.register) - int(earlier.register)) % span


def consumption(readings: list[Reading]) -> dict[str, int]:
    by_meter: dict[str, list[Reading]] = {}
    for r in readings:
        by_meter.setdefault(r.serial, []).append(r)
    totals: dict[str, int] = {}
    for serial, rs in by_meter.items():
        ordered = sorted(rs, key=lambda r: r.day)
        totals[serial] = sum(units_used(a, b) for a, b in zip(ordered, ordered[1:]))
    return totals
'''

REFERENCE = {"meterbook/readings.py": READINGS_REF, "meterbook/usage.py": USAGE_REF}

TRAP_SOLUTION = {"meterbook/usage.py": '''"""Water used between readings. See docs/meter_rounds.md."""

from __future__ import annotations

from .readings import Reading


def units_used(earlier: Reading, later: Reading) -> int:
    return int(later.register) - int(earlier.register)


def consumption(readings: list[Reading]) -> dict[str, int]:
    by_meter: dict[str, list[Reading]] = {}
    for r in readings:
        by_meter.setdefault(r.serial, []).append(r)
    totals: dict[str, int] = {}
    for serial, rs in by_meter.items():
        ordered = sorted(rs, key=lambda r: r.day)
        totals[serial] = sum(units_used(a, b) for a, b in zip(ordered, ordered[1:]))
    return totals
'''}

# What X looks like in code: one register subtracted from the other as plain integers, with
# no wrap-around handled in that file (no modulo, power or divmod).
_NO_WRAP = r'^(?![\s\S]*(?:%|\*\*|\bpow\(|\bdivmod\())[\s\S]*'
TRAP_PATTERNS = (
    _NO_WRAP + r'\bint\([^()]*\)\s*-\s*int\(',
    _NO_WRAP + r'\b\w*(?:later|newer|after|current|curr|new|end|second|next)\w*\s*-\s*'
               r'\w*(?:earlier|older|before|previous|prev|old|start|first|last)\w*',
)
