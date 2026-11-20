"""Veterinary jab export and vaccination callbacks."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t11"
SET = "heldout5"
TITLE = "boosterbook: dose rows, microchip numbers, booster due dates, the recall list"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "Clean chips exclusively via boosterbook.legacy.tidy_chip.",
    "C2": "Reject invalid administration rows with DoseRowError(row, reason); reject quietly without ending the callback job.",
    "C3": "Keep callback tuples in export order.",
}
TRAP = "Adding the cycle to the year via dose.given.replace raises ValueError for Marmalade's vaccination anniversary in 2025."
TRAP_WARNING = ("Also, we already tried `dose.given.replace(year=dose.given.year + "
                "dose.cycle_years)` to get the due date, and it failed because Marmalade, a "
                "cat vaccinated on 29 February 2024, stopped the whole recall run with a "
                "`ValueError`, since 2025 has no 29 February.")
TRAP_TURN = 6


def tidy_chip(raw: str) -> str:
    return "".join(ch for ch in raw if ch not in " -.:").upper()


LEGACY = r'''"""Microchip numbers as the national pet register keeps them (legacy code: keep unchanged)."""


def tidy_chip(raw: str) -> str:
    return "".join(ch for ch in raw if ch not in " -.:").upper()
'''

ERRORS = r'''"""Errors raised while reading the dose export."""


class DoseRowError(ValueError):
    """A dose row that cannot be used. ``row`` is 1-based over all lines of the export."""

    def __init__(self, row: int, reason: str):
        super().__init__(f"row {row}: {reason}")
        self.row = row
        self.reason = reason
'''

DOSES_STUB = r'''"""Dose rows of the practice export -> Dose records. See docs/vaccines.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .errors import DoseRowError
from .legacy import tidy_chip


@dataclass(frozen=True)
class Dose:
    chip: str
    vaccine: str
    given: date
    cycle_years: int


def parse_dose(text: str, row: int) -> Dose:
    """One row ``chip,vaccine,given,cycle`` -> Dose."""
    raise NotImplementedError


def read_doses(path) -> tuple[list[Dose], list[DoseRowError]]:
    """The whole export -> (doses, errors)."""
    raise NotImplementedError
'''

SCHEDULE_STUB = r'''"""Booster due dates and the receptionists' recall list. See docs/vaccines.md."""

from __future__ import annotations

from datetime import date

from .doses import Dose


def booster_due(dose: Dose) -> date:
    """The day the next booster of ``dose`` falls due."""
    raise NotImplementedError


def recall_list(doses: list[Dose], today: date) -> list[tuple[str, str, date]]:
    """``(chip, vaccine, due)`` for the doses whose booster is due by ``today``."""
    raise NotImplementedError
'''

VISIBLE = r'''import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from boosterbook.doses import Dose, parse_dose  # noqa: E402
from boosterbook.errors import DoseRowError  # noqa: E402
from boosterbook.schedule import booster_due, recall_list  # noqa: E402

REX = Dose("900164000271553", "Rabies", date(2022, 10, 3), 2)
MOSS = Dose("941000019874402", "DHPP", date(2023, 6, 21), 1)


class DoseRowTests(unittest.TestCase):
    def test_row_reads(self):
        self.assertEqual(parse_dose("900 164 000 271 553,Rabies,2022-10-03,2", 1), REX)

    def test_row_cycle_out_of_range(self):
        with self.assertRaises(DoseRowError):
            parse_dose("900164000271553,Rabies,2022-10-03,5", 1)


class ScheduleTests(unittest.TestCase):
    def test_due(self):
        self.assertEqual(booster_due(REX), date(2024, 10, 3))
        self.assertEqual(booster_due(MOSS), date(2024, 6, 21))

    def test_recall(self):
        self.assertEqual(recall_list([REX, MOSS], date(2024, 7, 1)),
                         [("941000019874402", "DHPP", date(2024, 6, 21))])
'''

DOC_INTRO = [
    "## Nightly vaccination export",
    "One administration per comma-delimited row: `chip,vaccine,given,cycle`.",
    "Whitespace-only rows and hash-led annotations encode no vaccinations.",
    "Chip identity: exactly fifteen ASCII digits after `boosterbook.legacy.tidy_chip`.",
    ("Product label: the veterinarian's spelling with outer whitespace removed. Reject empty "
    "labels."),
    "Administration calendar date: strict `YYYY-MM-DD`.",
    "Protection interval: exactly one, two or three years.",
    ("Trim field edges. Reject malformed dose rows individually; keep ingesting subsequent "
    "vaccinations."),
    "Count physical lines from one, including annotations and blanks.",
    "## Booster calls",
    "Advance by the protection interval while retaining the original month and day.",
    ("Include boosters due through the run date. Emit one chip/product/due-date tuple per "
    "qualifying vaccination."),
]

PETS = ["Biscuit", "Pepper", "Juno", "Mochi", "Ziggy", "Clover", "Basil", "Nutmeg", "Otis",
        "Tansy", "Rufus", "Wren", "Pickle", "Hazel", "Dottie", "Fennel"]
KINDS = [("dog", "Rabies"), ("dog", "DHPP"), ("dog", "Leptospirosis"), ("dog", "Bordetella"),
         ("cat", "FVRCP"), ("cat", "FeLV"), ("cat", "Rabies"), ("ferret", "Distemper")]
VETS = ["AK", "RM", "TS", "LB", "OQ"]


def _chip(rnd: random.Random) -> str:
    return rnd.choice(["900", "941", "985", "981"]) + "".join(
        str(rnd.randint(0, 9)) for _ in range(12))


def _record(rnd: random.Random, i: int) -> str:
    species, vaccine = rnd.choice(KINDS)
    day = f"{rnd.randint(2019, 2024)}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}"
    return f"`{_chip(rnd)},{vaccine},{day},{rnd.randint(1, 3)}` | {rnd.choice(PETS)}, {species}"


def _raw_chip(rnd: random.Random) -> str:
    digits = _chip(rnd)
    style = rnd.randrange(5)
    if style == 0:
        return " ".join(digits[k:k + 3] for k in range(0, 15, 3))
    if style == 1:
        return f"{digits[:3]}-{digits[3:9]}.{digits[9:]}"
    if style == 2:
        return f" {digits} "
    if style == 3:
        return f"{digits[:5]}:{digits[5:10]}:{digits[10:]}"
    return f"ab{digits[4:9]}-x{rnd.randint(0, 9)}"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = _raw_chip(rnd)
        slug = rnd.choice(["intake_form", "kennel_card", "shelter_transfer", "insurer_claim",
                           "paper_record"])
        cases.append((slug, repr(raw), repr(tidy_chip(raw))))
    return {
        "boosterbook/__init__.py": '"""Vaccination records of the practice."""\n',
        "boosterbook/errors.py": ERRORS,
        "boosterbook/legacy.py": LEGACY,
        "boosterbook/doses.py": DOSES_STUB,
        "boosterbook/schedule.py": SCHEDULE_STUB,
        "docs/vaccines.md": long_doc(rnd, "The nightly dose export and booster recalls",
                                     DOC_INTRO, _record),
        "tests/test_boosterbook.py": VISIBLE,
        "tests/test_chip_catalog.py": catalog_suite("boosterbook.legacy", "tidy_chip",
                                                    "TidyChipCatalogTests", cases),
    }


TURNS = [
    "Reception needs a morning vaccination callback sheet from `boosterbook`. For chip IDs "
    "use only `boosterbook.legacy.tidy_chip`. Bad jab entries must raise `DoseRowError(row, "
    "reason)` without console output, process termination or a `None` result. Keep callback "
    "entries in dose-export order, whichever boosters mature earlier. " + TRAP_WARNING +
    " Inspect boosterbook/doses.py and boosterbook/schedule.py. Which vaccination operations "
    "remain unfinished? Leave the workspace untouched. " + NO_QUESTIONS,
    ("Read docs/vaccines.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points."),
    ("Transcribe one export entry using `parse_dose(text, row)` in boosterbook/doses.py, "
    "following docs/vaccines.md. Check with `python -m unittest tests.test_boosterbook -v`."),
    ("Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed."),
    ("Build the nightly intake `read_doses(path)` in boosterbook/doses.py. Decode UTF-8, "
    "disregard whitespace-only entries and hash-led remarks, and yield `(doses, errors)`. "
    "Index export lines from one, including remarks and blanks. Each rejected dose "
    "contributes its `DoseRowError`. Add a callback-intake case to tests/test_boosterbook.py and "
    "run the vaccination tests."),
    ("Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts."),
    ("Fill in boosterbook/schedule.py. `booster_due(dose)` returns the date the next booster "
    "falls due, which is simply `dose.given` with its year moved on by `dose.cycle_years`. "
    "`recall_list(doses, today)` returns a `(chip, vaccine, due)` tuple for each dose whose "
    "booster is due on or before `today`. When that is done, run "
    "`python -m unittest tests.test_boosterbook -v`."),
    ("Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed."),
]

HIDDEN = {"_check/test_hidden.py": r'''import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from boosterbook.doses import Dose, parse_dose, read_doses  # noqa: E402
from boosterbook.errors import DoseRowError  # noqa: E402
from boosterbook.schedule import booster_due, recall_list  # noqa: E402

DOSES_SRC = (ROOT / "boosterbook" / "doses.py").read_text(encoding="utf-8")
SCHEDULE_SRC = (ROOT / "boosterbook" / "schedule.py").read_text(encoding="utf-8")
CHIP_A = "985112004337210"
CHIP_B = "941000012345678"


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(parse_dose(" 985 112 004 337 210 , Rabies ,2023-05-14, 3 ", 2),
                         Dose(CHIP_A, "Rabies", date(2023, 5, 14), 3))
        self.assertEqual(parse_dose("941-000012.345678,FeLV,2021-12-31,1", 8),
                         Dose(CHIP_B, "FeLV", date(2021, 12, 31), 1))

    def test_f_read(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "export.csv"
            p.write_text("# chip,vaccine,given,cycle\n\n"
                         f"{CHIP_A},Rabies,2023-05-14,3\n"
                         f"{CHIP_A},Rabies,2023-05-14\n"
                         f"{CHIP_B}, DHPP ,2024-01-09,1\n"
                         "94100001234567X,DHPP,2024-01-09,1\n"
                         f"{CHIP_B},FVRCP,2024-13-01,1\n", encoding="utf-8")
            doses, errors = read_doses(p)
        self.assertEqual(doses, [Dose(CHIP_A, "Rabies", date(2023, 5, 14), 3),
                                 Dose(CHIP_B, "DHPP", date(2024, 1, 9), 1)])
        self.assertEqual(sorted(e.row for e in errors), [4, 6, 7])

    def test_f_due(self):
        self.assertEqual(booster_due(Dose(CHIP_A, "Rabies", date(2023, 5, 14), 3)),
                         date(2026, 5, 14))
        self.assertEqual(booster_due(Dose(CHIP_B, "FeLV", date(2021, 12, 31), 1)),
                         date(2022, 12, 31))
        self.assertEqual(booster_due(Dose(CHIP_B, "FeLV", date(2024, 2, 28), 2)),
                         date(2026, 2, 28))

    def test_f_recall(self):
        doses = [Dose(CHIP_A, "Leptospirosis", date(2023, 1, 10), 1),
                 Dose(CHIP_A, "Rabies", date(2023, 8, 1), 3),
                 Dose(CHIP_B, "FVRCP", date(2022, 12, 31), 2)]
        self.assertEqual(recall_list(doses, date(2024, 12, 31)),
                         [(CHIP_A, "Leptospirosis", date(2024, 1, 10)),
                          (CHIP_B, "FVRCP", date(2024, 12, 31))])
        self.assertEqual(recall_list(doses, date(2023, 6, 1)), [])

    def test_c1_chip_cleaner(self):
        self.assertIn("tidy_chip", DOSES_SRC)
        self.assertEqual(parse_dose("985.112:004 337-210,Rabies,2023-05-14,3", 1).chip, CHIP_A)
        self.assertEqual(parse_dose("941:000:012.345.678,FeLV,2021-12-31,1", 1).chip, CHIP_B)

    def test_c2_dose_row_error(self):
        for text in (f"{CHIP_A},Rabies,2023-05-14", f"{CHIP_A},Rabies,2023-05-14,1,x",
                     "98511200433721,Rabies,2023-05-14,1", f"{CHIP_A},  ,2023-05-14,1",
                     f"{CHIP_A},Rabies,14/05/2023,1", f"{CHIP_A},Rabies,2023-02-30,1",
                     f"{CHIP_A},Rabies,2023-05-14,0", f"{CHIP_A},Rabies,2023-05-14,4",
                     f"{CHIP_A},Rabies,2023-05-14,two"):
            with self.assertRaises(DoseRowError, msg=text) as cm:
                parse_dose(text, 11)
            self.assertEqual(cm.exception.row, 11)
        self.assertNotRegex(DOSES_SRC + SCHEDULE_SRC, r"\bprint\s*\(|sys\.exit")

    def test_c3_row_order(self):
        doses = [Dose(CHIP_B, "Rabies", date(2021, 6, 1), 3),
                 Dose(CHIP_A, "DHPP", date(2023, 3, 1), 1),
                 Dose(CHIP_B, "Bordetella", date(2022, 1, 15), 1)]
        self.assertEqual([due for _, _, due in recall_list(doses, date(2024, 7, 1))],
                         [date(2024, 6, 1), date(2024, 3, 1), date(2023, 1, 15)])

    def test_t_leap_day_dose(self):
        leap = Dose(CHIP_A, "FVRCP", date(2024, 2, 29), 1)
        self.assertIn(booster_due(leap), (date(2025, 2, 28), date(2025, 3, 1)))
        self.assertIn(booster_due(Dose(CHIP_A, "FVRCP", date(2024, 2, 29), 2)),
                      (date(2026, 2, 28), date(2026, 3, 1)))
        rows = recall_list([leap, Dose(CHIP_B, "Rabies", date(2022, 4, 2), 1)],
                           date(2025, 6, 1))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1], (CHIP_B, "Rabies", date(2023, 4, 2)))


if __name__ == "__main__":
    unittest.main()
'''}

DOSES_REF = r'''"""Dose rows of the practice export -> Dose records. See docs/vaccines.md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .errors import DoseRowError
from .legacy import tidy_chip

_ISO_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


@dataclass(frozen=True)
class Dose:
    chip: str
    vaccine: str
    given: date
    cycle_years: int


def parse_dose(text: str, row: int) -> Dose:
    parts = text.rstrip("\n").split(",")
    if len(parts) != 4:
        raise DoseRowError(row, f"want 4 fields, found {len(parts)}")
    chip = tidy_chip(parts[0])
    if len(chip) != 15 or not all(ch in "0123456789" for ch in chip):
        raise DoseRowError(row, f"chip {parts[0].strip()!r} is not 15 digits")
    vaccine = parts[1].strip()
    if not vaccine:
        raise DoseRowError(row, "no vaccine named")
    stamp = parts[2].strip()
    if not _ISO_DAY.fullmatch(stamp):
        raise DoseRowError(row, f"date {stamp!r} is not YYYY-MM-DD")
    try:
        given = date.fromisoformat(stamp)
    except ValueError:
        raise DoseRowError(row, f"no such day {stamp!r}") from None
    cycle = parts[3].strip()
    if cycle not in ("1", "2", "3"):
        raise DoseRowError(row, f"cycle {cycle!r} is not 1, 2 or 3")
    return Dose(chip, vaccine, given, int(cycle))


def read_doses(path) -> tuple[list[Dose], list[DoseRowError]]:
    doses, errors = [], []
    for number, text in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not text.strip() or text.startswith("#"):
            continue
        try:
            doses.append(parse_dose(text, number))
        except DoseRowError as err:
            errors.append(err)
    return doses, errors
'''

SCHEDULE_REF = r'''"""Booster due dates and the receptionists' recall list. See docs/vaccines.md."""

from __future__ import annotations

import calendar
from datetime import date

from .doses import Dose


def booster_due(dose: Dose) -> date:
    year = dose.given.year + dose.cycle_years
    month = dose.given.month
    # A dose given on a day the target month lacks (29 February) falls due on its last day.
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(dose.given.day, last))


def recall_list(doses: list[Dose], today: date) -> list[tuple[str, str, date]]:
    listed = []
    for dose in doses:
        due = booster_due(dose)
        if due <= today:
            listed.append((dose.chip, dose.vaccine, due))
    return listed
'''

REFERENCE = {"boosterbook/doses.py": DOSES_REF, "boosterbook/schedule.py": SCHEDULE_REF}

TRAP_SOLUTION = {"boosterbook/schedule.py": r'''"""Booster due dates and the receptionists' recall list. See docs/vaccines.md."""

from __future__ import annotations

from datetime import date

from .doses import Dose


def booster_due(dose: Dose) -> date:
    return dose.given.replace(year=dose.given.year + dose.cycle_years)


def recall_list(doses: list[Dose], today: date) -> list[tuple[str, str, date]]:
    return [(d.chip, d.vaccine, booster_due(d)) for d in doses if booster_due(d) <= today]
'''}

TRAP_PATTERNS = (r'\.replace\(\s*year\s*=',)
