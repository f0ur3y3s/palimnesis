"""Resident curb authorizations and the wardens' daily district sheets."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t18"
SET = "heldout5"
TITLE = "permitdesk: permit applications, number plates, validity periods, parking zones"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "PermitError(line_no, message) handles rejected applications without output or exit",
    "C2": "permitdesk.legacy.compact_plate exclusively cleans registration marks",
    "C3": "keep the original public parameter names and sequence in both permit modules",
}
TRAP = ("already tried ordering the wardens' street lists with sorted() keyed on the lower-case "
        "name; it failed because that still compares code points, so streets opening with an "
        "umlaut, such as Ährenweg, Ölmühle and Überfahrt, sank below Zwinger to the very foot "
        "of the printed sheet, where the wardens never looked for them")
TRAP_WARNING = ("Also, we already tried ordering the wardens' street lists with `sorted()` keyed "
                "on the lower-case name, and it failed because that still compares code "
                "points: streets opening with an umlaut, such as Ährenweg, Ölmühle and "
                "Überfahrt, sank below Zwinger to the very foot of the printed sheet, where no "
                "warden ever looked for them.")
TRAP_TURN = 6


def compact_plate(raw: str) -> str:
    s = "".join(raw.split()).replace("-", "").upper()
    if not (2 <= len(s) <= 8 and s.isascii() and s.isalnum()) or s.isdigit() or s.isalpha():
        raise ValueError(f"bad number plate {raw!r}")
    return s


LEGACY = '''"""Number plates in the vehicle registry's compact form. The enforcement handhelds
match plates on exactly this form (do not change)."""


def compact_plate(raw: str) -> str:
    s = "".join(raw.split()).replace("-", "").upper()
    if not (2 <= len(s) <= 8 and s.isascii() and s.isalnum()) or s.isdigit() or s.isalpha():
        raise ValueError(f"bad number plate {raw!r}")
    return s
'''

ERRORS = '''"""Errors in the permit application export."""


class PermitError(ValueError):
    """A row of the export that cannot be used; ``line_no`` is the row's 1-based line."""

    def __init__(self, line_no: int, message: str):
        super().__init__(f"row {line_no}: {message}")
        self.line_no = line_no
        self.message = message
'''

APPS_STUB = '''"""Permit applications. See docs/permits.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .errors import PermitError
from .legacy import compact_plate

# Days of validity for each permit length the office sells, in months.
DURATIONS = {1: 30, 3: 91, 6: 182, 12: 365}


@dataclass(frozen=True)
class Application:
    plate: str
    street: str
    start: date
    months: int


def parse_application(line: str, line_no: int) -> Application:
    """One export row ``plate|street|start|months`` -> Application."""
    raise NotImplementedError


def last_valid_day(app: Application) -> date:
    """The last day on which the permit is valid."""
    raise NotImplementedError


def is_valid(app: Application, day: date) -> bool:
    """Whether the permit covers ``day``."""
    raise NotImplementedError
'''

ZONES_STUB = '''"""Parking zones and the streets in them. See docs/permits.md."""

from __future__ import annotations

from .applications import Application


def zone_for(street: str, register: dict[str, list[str]]) -> str | None:
    """The code of the zone that ``street`` belongs to."""
    raise NotImplementedError


def zone_counts(apps: list[Application], register: dict[str, list[str]]) -> dict[str, int]:
    """How many applications fall in each zone."""
    raise NotImplementedError


def warden_list(register: dict[str, list[str]], code: str) -> list[str]:
    """The streets of one zone, listed for the wardens' printed sheet."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from permitdesk.applications import Application, last_valid_day, parse_application  # noqa: E402
from permitdesk.errors import PermitError  # noqa: E402
from permitdesk.zones import warden_list, zone_counts, zone_for  # noqa: E402

REGISTER = {"A": ["Am Markt", "Kirchgasse"], "B": ["MÜHLENWEG", "Uferweg"]}


class RowTests(unittest.TestCase):
    def test_row(self):
        self.assertEqual(parse_application("b-kx 4471|Kirchgasse|2026-03-01|3", 1),
                         Application("BKX4471", "Kirchgasse", date(2026, 3, 1), 3))

    def test_row_bad_months(self):
        with self.assertRaises(PermitError):
            parse_application("b-kx 4471|Kirchgasse|2026-03-01|2", 1)


class LastDayTests(unittest.TestCase):
    def test_one_month(self):
        app = Application("BKX4471", "Kirchgasse", date(2026, 3, 1), 1)
        self.assertEqual(last_valid_day(app), date(2026, 3, 30))


class ZoneTests(unittest.TestCase):
    def test_zone_for(self):
        self.assertEqual(zone_for("  am   markt ", REGISTER), "A")
        self.assertEqual(zone_for("Mühlenweg", REGISTER), "B")
        self.assertIsNone(zone_for("Bahnhofsplatz", REGISTER))

    def test_counts(self):
        apps = [Application("BKX4471", "Uferweg", date(2026, 1, 5), 12),
                Application("HHZ12", "uferweg", date(2026, 2, 5), 1)]
        self.assertEqual(zone_counts(apps, REGISTER), {"A": 0, "B": 2})

    def test_warden_list(self):
        self.assertEqual(warden_list(REGISTER, "B"), ["MÜHLENWEG", "Uferweg"])
        self.assertEqual(warden_list({"C": ["kirchgasse", "Am Markt"]}, "C"),
                         ["Am Markt", "kirchgasse"])
'''

DOC_INTRO = [
    "Old-town curb authorizations begin as nightly web-form exports. Use `plate|street|start|months`.",
    "Skip note rows beginning `#` and vacant lines without changing their physical row numbers.",
    "Pass typed plate spellings through `permitdesk.legacy.compact_plate`, for example `b-kx 4471`",
    "yields `BKX4471`. Trim address margins and keep a nonempty street field.",
    "Write commencement as `YYYY-MM-DD`. Offered terms have 1, 3, 6 or 12 months.",
    "A permit starts on commencement and spans 30, 91, 182 or 365 days respectively per `DURATIONS`.",
    "Malformed applications fail individually. Row positions on the export begin at 1.",
    "The curb register holds the office's street labels under single-letter district codes.",
    "Assign applications to districts through their address street memberships.",
]

STREETS = ["Am Markt", "Kirchgasse", "Mühlenweg", "Uferweg", "Hafenkante", "Rosengarten",
           "Schillerplatz", "Am Stadttor", "Klosterhof", "Gerberzeile", "Töpfermarkt",
           "Lindenweg"]


def _plate(rnd: random.Random) -> str:
    city = rnd.choice(["b", "HH", "m", "K", "dd", "F", "hb", "LG"])
    letters = "".join(rnd.choice("abcdefghjklmnprstuvwxyz") for _ in range(rnd.randint(1, 2)))
    num = rnd.randint(1, 9999)
    return rnd.choice([f"{city}-{letters} {num}", f"{city.upper()} {letters.upper()} {num}",
                       f"{city}{letters}{num}", f" {city} - {letters}-{num} "])


def _record(rnd: random.Random, i: int) -> str:
    start = f"2026-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}"
    return (f"`{_plate(rnd)}|{rnd.choice(STREETS)}|{start}|{rnd.choice([1, 3, 6, 12])}` | "
            f"{rnd.choice(['online form', 'counter', 'renewal', 'visitor upgrade'])}, row {i}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = _plate(rnd)
        slug = rnd.choice(["warden_handheld", "camera_capture", "renewal_letter",
                           "counter_application", "fine_appeal"])
        cases.append((slug, repr(raw), repr(compact_plate(raw))))
    return {
        "permitdesk/__init__.py": '"""Residents\' parking permits."""\n',
        "permitdesk/errors.py": ERRORS,
        "permitdesk/legacy.py": LEGACY,
        "permitdesk/applications.py": APPS_STUB,
        "permitdesk/zones.py": ZONES_STUB,
        "docs/permits.md": long_doc(rnd, "Permit applications and parking zones", DOC_INTRO,
                                    _record),
        "tests/test_permitdesk.py": VISIBLE,
        "tests/test_legacy_plates.py": catalog_suite("permitdesk.legacy", "compact_plate",
                                                     "CompactPlateCatalogTests", cases),
    }


TURNS = [
    "Finish `permitdesk` for the old-town curb office. Reject bad applications through "
    "`PermitError(line_no, message)` from permitdesk/errors.py without console output or an exit. "
    "Clean plates exclusively with `permitdesk.legacy.compact_plate`. Retain public parameter "
    "names and their existing sequence in permitdesk/applications.py and permitdesk/zones.py. "
    + TRAP_WARNING + " Read those two files for an inventory of omissions before editing. " + NO_QUESTIONS,
    "Read docs/permits.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Decode web-form rows with `parse_application(line, line_no)` per the curb registry manual. "
    "Check with `python -m unittest tests.test_permitdesk -v`; validity and district features come later.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Implement `last_valid_day(app)` and `is_valid(app, day)` for the permit ledger. Commencement "
    "counts as the first of the authorized `DURATIONS` days. Return the final covered date, and "
    "answer validity from the inclusive term. Add an `is_valid` case under tests/test_permitdesk.py "
    "and execute the module.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Please implement permitdesk/zones.py now. The register maps each zone code to the "
    "street names of that zone as the office typed them. `zone_for(street, register)` "
    "returns the code of the zone whose list holds the street, where two names count as "
    "the same street regardless of upper or lower case and of extra spaces between or "
    "around the words; it returns None when no zone lists it. `zone_counts(apps, register)` "
    "returns, for every zone code in register order, how many of the applications have a "
    "street in that zone. `warden_list(register, code)` returns the streets of zone `code` "
    "in alphabetical order for the wardens' printed sheet, paying no attention to upper "
    "or lower case, and [] for a code the register lacks. Afterwards run "
    "`python -m unittest tests.test_permitdesk -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import inspect
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from permitdesk.applications import Application, last_valid_day, is_valid, parse_application  # noqa: E402
from permitdesk.errors import PermitError  # noqa: E402
from permitdesk.zones import warden_list, zone_counts, zone_for  # noqa: E402

APPS_SRC = (ROOT / "permitdesk" / "applications.py").read_text(encoding="utf-8")
ZONES_SRC = (ROOT / "permitdesk" / "zones.py").read_text(encoding="utf-8")
REGISTER = {"A": ["Am Markt", "Kirchgasse"], "B": ["MÜHLENWEG", "Uferweg", "Hafenkante"],
            "C": ["Klosterhof"]}


def _app(street, plate="HB7Q12"):
    return Application(plate, street, date(2026, 6, 1), 6)


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(parse_application(" HH z 902 | Am Stadttor |2026-11-30| 12 ", 3),
                         Application("HHZ902", "Am Stadttor", date(2026, 11, 30), 12))

    def test_f_validity(self):
        app = Application("K9", "Uferweg", date(2026, 1, 1), 12)
        self.assertEqual(last_valid_day(app), date(2026, 12, 31))
        app = Application("K9", "Uferweg", date(2026, 2, 10), 3)
        self.assertEqual(last_valid_day(app), date(2026, 5, 11))
        self.assertTrue(is_valid(app, date(2026, 2, 10)))
        self.assertTrue(is_valid(app, date(2026, 5, 11)))
        self.assertFalse(is_valid(app, date(2026, 5, 12)))
        self.assertFalse(is_valid(app, date(2026, 2, 9)))

    def test_f_zone_for(self):
        self.assertEqual(zone_for("Kirchgasse", REGISTER), "A")
        self.assertEqual(zone_for("  hafenkante", REGISTER), "B")
        self.assertEqual(zone_for("KLOSTERHOF", REGISTER), "C")
        self.assertEqual(zone_for("am\\tMarkt", REGISTER), "A")
        self.assertEqual(zone_for("mühlenweg ", REGISTER), "B")
        self.assertIsNone(zone_for("Schillerplatz", REGISTER))

    def test_f_zone_counts(self):
        apps = [_app("Uferweg"), _app("Am  Markt"), _app("Lindenweg"), _app("UFERWEG")]
        self.assertEqual(zone_counts(apps, REGISTER), {"A": 1, "B": 2, "C": 0})
        self.assertEqual(list(zone_counts([], REGISTER)), ["A", "B", "C"])

    def test_c1_permit_error(self):
        for line in ("BKX4471|Kirchgasse|2026-03-01", "BKX4471|Kirchgasse|2026-03-01|3|x",
                     "BKX4471| |2026-03-01|3", "BKX4471|Kirchgasse|2026-02-30|3",
                     "BKX4471|Kirchgasse|01.03.2026|3", "BKX4471|Kirchgasse|2026-03-01|24",
                     "1234|Kirchgasse|2026-03-01|3", "BKX4471|Kirchgasse|2026-03-01|three"):
            with self.assertRaises(PermitError, msg=line) as cm:
                parse_application(line, 14)
            self.assertEqual(cm.exception.line_no, 14)
        self.assertNotRegex(APPS_SRC + ZONES_SRC, r"\\bprint\\s*\\(|sys\\.exit|\\bexit\\(|\\bquit\\(")

    def test_c2_plates_from_legacy(self):
        self.assertIn("compact_plate", APPS_SRC)
        self.assertNotRegex(APPS_SRC, r"\\.upper\\(|isalnum")
        self.assertEqual(parse_application("dd - ab-17|Uferweg|2026-01-01|1", 1).plate, "DDAB17")

    def test_c3_signatures(self):
        for fn, names in ((parse_application, ["line", "line_no"]), (last_valid_day, ["app"]),
                          (is_valid, ["app", "day"]), (zone_for, ["street", "register"]),
                          (zone_counts, ["apps", "register"]),
                          (warden_list, ["register", "code"])):
            self.assertEqual(list(inspect.signature(fn).parameters), names, fn.__name__)

    def test_f_warden_list(self):
        reg = {"A": ["Rosengarten", "am Stadttor", "Hafenkante", "Kirchgasse", "gerberzeile"],
               "B": []}
        self.assertEqual(warden_list(reg, "A"), ["am Stadttor", "gerberzeile", "Hafenkante",
                                                 "Kirchgasse", "Rosengarten"])
        self.assertEqual(warden_list(reg, "B"), [])
        self.assertEqual(warden_list(reg, "Q"), [])
        self.assertEqual(reg["A"][0], "Rosengarten")

    def test_t_umlaut_initials(self):
        reg = {"D": ["Zwinger", "Überfahrt", "Ährenweg", "Ostwall", "Ölmühle", "Am Markt",
                     "Uferweg"]}
        self.assertEqual(warden_list(reg, "D"), ["Ährenweg", "Am Markt", "Ölmühle", "Ostwall",
                                                 "Überfahrt", "Uferweg", "Zwinger"])


if __name__ == "__main__":
    unittest.main()
'''}

APPS_REF = '''"""Permit applications. See docs/permits.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .errors import PermitError
from .legacy import compact_plate

# Days of validity for each permit length the office sells, in months.
DURATIONS = {1: 30, 3: 91, 6: 182, 12: 365}


@dataclass(frozen=True)
class Application:
    plate: str
    street: str
    start: date
    months: int


def parse_application(line: str, line_no: int) -> Application:
    cells = [c.strip() for c in line.rstrip("\\r\\n").split("|")]
    if len(cells) != 4:
        raise PermitError(line_no, f"expected 4 fields, found {len(cells)}")
    plate, street, start, months = cells
    try:
        plate = compact_plate(plate)
    except ValueError as exc:
        raise PermitError(line_no, str(exc)) from None
    if not street:
        raise PermitError(line_no, "street is empty")
    if len(start) != 10 or start[4] != "-" or start[7] != "-":
        raise PermitError(line_no, f"bad start date {start!r}")
    try:
        first = date.fromisoformat(start)
    except ValueError:
        raise PermitError(line_no, f"bad start date {start!r}") from None
    if not months.isdigit() or int(months) not in DURATIONS:
        raise PermitError(line_no, f"bad permit length {months!r}")
    return Application(plate, street, first, int(months))


def last_valid_day(app: Application) -> date:
    return app.start + timedelta(days=DURATIONS[app.months] - 1)


def is_valid(app: Application, day: date) -> bool:
    return app.start <= day <= last_valid_day(app)
'''

ZONES_REF = '''"""Parking zones and the streets in them. See docs/permits.md."""

from __future__ import annotations

import unicodedata

from .applications import Application


def _key(name: str) -> str:
    return " ".join(name.casefold().split())


def _alphabetical(name: str) -> str:
    # Wardens look an umlaut up under its base letter: drop the marks before comparing.
    decomposed = unicodedata.normalize("NFD", name.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def zone_for(street: str, register: dict[str, list[str]]) -> str | None:
    wanted = _key(street)
    for code, streets in register.items():
        if any(_key(s) == wanted for s in streets):
            return code
    return None


def zone_counts(apps: list[Application], register: dict[str, list[str]]) -> dict[str, int]:
    counts = {code: 0 for code in register}
    for app in apps:
        code = zone_for(app.street, register)
        if code is not None:
            counts[code] += 1
    return counts


def warden_list(register: dict[str, list[str]], code: str) -> list[str]:
    return sorted(register.get(code, []), key=lambda s: (_alphabetical(s), s))
'''

REFERENCE = {"permitdesk/applications.py": APPS_REF, "permitdesk/zones.py": ZONES_REF}

TRAP_SOLUTION = {"permitdesk/zones.py": '''"""Parking zones and the streets in them. See docs/permits.md."""

from __future__ import annotations

from .applications import Application


def _key(name: str) -> str:
    return " ".join(name.lower().split())


def zone_for(street: str, register: dict[str, list[str]]) -> str | None:
    wanted = _key(street)
    for code, streets in register.items():
        if any(_key(s) == wanted for s in streets):
            return code
    return None


def zone_counts(apps: list[Application], register: dict[str, list[str]]) -> dict[str, int]:
    counts = {code: 0 for code in register}
    for app in apps:
        code = zone_for(app.street, register)
        if code is not None:
            counts[code] += 1
    return counts


def warden_list(register: dict[str, list[str]], code: str) -> list[str]:
    return sorted(register.get(code, []), key=str.lower)
'''}

# What X looks like in code: the street list sorted on its code points (plain, or keyed
# on lower() or casefold()), with no Unicode decomposition anywhere in the file.
TRAP_PATTERNS = (r'^(?![\s\S]*\bnormalize\()[\s\S]*(?:\bsorted\(|\.sort\()',)
