"""Orchard picking records and household crate allocations."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t4"
SET = "heldout5"
TITLE = "orchardshare: picking lines, apple variety names, crate totals, the share sheet"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "unparseable tallies raise TallyError(line, problem) without printing, "
          "quitting, or returning None",
    "C2": "only orchardshare.legacy.apple_variety standardizes cultivar spelling",
    "C3": "every stored or returned crate count is an int",
}
TRAP = ("already tried giving each household round() of its proportional share of the "
        "crates; it failed because the rounded shares did not add up to the crates picked: "
        "three households with equal hours and 10 crates got 3 each and one crate sat "
        "unclaimed in the barn, and on another day two households were promised 4 each of "
        "7 crates")
TRAP_WARNING = ("Also, we already tried giving each household `round()` of its proportional "
                "share of the crates, and it failed because the rounded shares did not add up "
                "to the crates picked: three households with equal hours and 10 crates got 3 "
                "each and one crate sat unclaimed in the barn, and on another day two "
                "households were promised 4 each out of 7 crates.")
TRAP_TURN = 6


def apple_variety(raw: str) -> str:
    words = raw.replace("_", " ").split()
    if not words or not all(w.replace("'", "").isalpha() for w in words):
        raise ValueError(f"bad variety {raw!r}")
    return " ".join(w[:1].upper() + w[1:].lower() for w in words)


LEGACY = '''"""Established tree-label spelling. Keep this module intact."""


def apple_variety(raw: str) -> str:
    words = raw.replace("_", " ").split()
    if not words or not all(w.replace("'", "").isalpha() for w in words):
        raise ValueError(f"bad variety {raw!r}")
    return " ".join(w[:1].upper() + w[1:].lower() for w in words)
'''

ERRORS = '''"""Picking tally errors."""


class TallyError(ValueError):
    """Invalid picking entry, with its one-based tally position."""

    def __init__(self, line: int, problem: str):
        super().__init__(f"tally line {line}: {problem}")
        self.line = line
        self.problem = problem
'''

_TALLY_HEAD = '''"""Translate raw tallies into harvest records (docs/tally.md)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .errors import TallyError
from .legacy import apple_variety


@dataclass(frozen=True)
class OrchardLoad:
    day: date
    variety: str
    crates: int
    picker: str
'''

TALLY_STUB = _TALLY_HEAD + '''

def parse_pick(text: str, line: int) -> OrchardLoad:
    """Decode ``day | variety | crates | picker``."""
    raise NotImplementedError


def crates_by_variety(picks: list[OrchardLoad]) -> dict[str, int]:
    """Aggregate the harvest by cultivar."""
    raise NotImplementedError
'''

SHARES_STUB = '''"""Produce the barn's household pickup board (docs/tally.md)."""

from __future__ import annotations


def hours_fraction(hours: dict[str, int], household: str) -> float:
    """That household's part of everyone's logged hours, between 0 and 1."""
    return hours[household] / sum(hours.values())


def household_share(total: int, hours: dict[str, int], household: str) -> int:
    """Pickup quantity for one member's household."""
    raise NotImplementedError


def share_sheet(total: int, hours: dict[str, int]) -> str:
    """Format the notices displayed on the barn board."""
    return "".join(f"{name}: {household_share(total, hours, name)} crates\\n"
                   for name in hours)
'''

VISIBLE = '''import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchardshare.errors import TallyError  # noqa: E402
from orchardshare.collection_board import household_share, share_sheet  # noqa: E402
from orchardshare.harvest_ledger import OrchardLoad, parse_pick  # noqa: E402


class ParsePickTests(unittest.TestCase):
    def test_tally_line(self):
        self.assertEqual(parse_pick("2025-09-14 | bramley | 12 | Ruth", 1),
                         OrchardLoad(date(2025, 9, 14), "Bramley", 12, "Ruth"))

    def test_tally_line_no_crates(self):
        with self.assertRaises(TallyError):
            parse_pick("2025-09-14 | bramley | 0 | Ruth", 1)


class HouseholdPickupTests(unittest.TestCase):
    HOURS = {"Abbots": 6, "Dunmore": 3, "Pryce": 3}

    def test_household_share(self):
        self.assertEqual(household_share(24, self.HOURS, "Abbots"), 12)
        self.assertEqual(household_share(24, self.HOURS, "Pryce"), 6)
        self.assertEqual(household_share(10, {"Abbots": 2, "Pryce": 1}, "Abbots"), 7)
        self.assertEqual(household_share(10, {"Abbots": 2, "Pryce": 1}, "Pryce"), 3)

    def test_share_sheet(self):
        self.assertEqual(share_sheet(8, {"Abbots": 1, "Pryce": 3}),
                         "Abbots: 2 crates\\nPryce: 6 crates\\n")
'''

DOC_INTRO = [
    "Autumn pickers log trailer loads in the barn's tally. `orchardshare` totals",
    "the harvest by cultivar and issues household collection notices.",
    "",
    "## Tally lines",
    "",
    "- A full load entry looks like `day | variety | crates | picker`.",
    "- Omit vacant tally rows and `;` margins.",
    "- Trim each delimited field.",
    "- `day`: Harvest date (`YYYY-MM-DD`).",
    "- `variety`: Use the picker's spelling (`bramley`, `COX_S ORANGE PIPPIN`,",
    "  `egremont russet`) as input to `orchardshare.legacy.apple_variety`.",
    "- `crates`: Whole crates, integer 1 through trailer capacity (40).",
    "- `picker` gives the hauler's first name. Require a nonempty name.",
    "- A damaged record doesn't invalidate its neighbors.",
    "- Ledger positions are 1-based; count margins and blanks too.",
    "",
    "## Households and hours",
    "",
    "- Include pruning, mowing, picking and pressing in household volunteer hours.",
    "  Log whole hours.",
    "- The hours table follows the household signup ledger.",
    "",
    "## Appendix notes",
    "",
    "Historic tallies include side notes with the tree row, weather and fruit condition.",
]

VARIETIES = ["bramley", "COX_S ORANGE PIPPIN", "egremont russet", "Discovery", "worcester pearmain",
             "ashmead's kernel", "LORD LAMBOURNE", "blenheim orange", "katy", "spartan"]
PICKERS = ["Ruth", "Tomasz", "Delyth", "Aled", "Wendy", "Kofi", "Sian", "Barnaby", "Nell"]
FRUIT = ["windfalls bruised", "crisp and sharp", "a little scabby", "heavy crop", "wasps about",
         "colouring well", "picked from ladders", "sweet already", "some codling moth"]
SKY = ["dry", "drizzle", "bright", "overcast", "blustery", "first frost"]


def _record(rnd: random.Random, i: int) -> str:
    line = (f"2025-{rnd.choice(['08', '09', '10'])}-{rnd.randint(1, 30):02d} | "
            f"{rnd.choice(VARIETIES)} | {rnd.randint(1, 18)} | {rnd.choice(PICKERS)}")
    return (f"`{line}` | tree row {rnd.randint(1, 14)}; {rnd.choice(SKY)}; "
            f"{rnd.choice(FRUIT)}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = rnd.choice(VARIETIES)
        raw = rnd.choice([raw, raw.upper(), raw.lower().replace(" ", "_"), f"  {raw}  ",
                          raw.replace(" ", "   ")])
        slug = rnd.choice(["tree_label", "barn_board", "press_day", "graft_list",
                           "wassail_menu"])
        cases.append((slug, repr(raw), repr(apple_variety(raw))))
    return {
        "orchardshare/__init__.py": '"""Community orchard picking tally."""\n',
        "orchardshare/errors.py": ERRORS,
        "orchardshare/legacy.py": LEGACY,
        "orchardshare/harvest_ledger.py": TALLY_STUB,
        "orchardshare/collection_board.py": SHARES_STUB,
        "docs/tally.md": long_doc(rnd, "The picking tally", DOC_INTRO, _record),
        "tests/test_orchardshare.py": VISIBLE,
        "tests/test_legacy_varieties.py": catalog_suite("orchardshare.legacy", "apple_variety",
                                                        "AppleVarietyCatalogTests", cases),
    }


TURNS = [
    "Our apple orchard writes up each trailer load. We'd like `orchardshare` to make "
    "cultivar totals and household collection notices. Follow the orchard rules. "
    "(1) Reject a malformed tally via `TallyError(line, problem)` in orchardshare/errors.py. "
    "Reject via the exception alone. Avoid print, sys.exit and None. "
    "(2) Use `orchardshare.legacy.apple_variety` exclusively for cultivar spelling. "
    "(3) Store and return crate counts as Python ints throughout. " + TRAP_WARNING +
    " Inspect orchardshare/harvest_ledger.py and orchardshare/collection_board.py. List the missing "
    "implementations and leave both untouched. " + NO_QUESTIONS,
    "Read docs/tally.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Implement `parse_pick(text, line)` in orchardshare/harvest_ledger.py using the tally format "
    "from docs/tally.md. Run `python -m unittest tests.test_orchardshare -v`. Pickup "
    "board cases can still fail.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Implement `crates_by_variety(picks)` in orchardshare/harvest_ledger.py. Sum the crate counts "
    "by cultivar in first-picking order. Exercise cultivar totals in "
    "tests/test_orchardshare.py and run its suite.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Finish orchardshare/collection_board.py. The barn kiosk looks up a single household "
    "with `household_share(total, hours, household)`, one name at a time: take the crate "
    "total times that household's `hours_fraction` and hand back the whole-crate count "
    "closest to it. "
    "`hours` maps names to volunteer hours, and `share_sheet` already lays out the board "
    "from those pickup counts. Run `python -m unittest tests.test_orchardshare -v`.",
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

from orchardshare.errors import TallyError  # noqa: E402
from orchardshare.collection_board import household_share, share_sheet  # noqa: E402
from orchardshare.harvest_ledger import OrchardLoad, crates_by_variety, parse_pick  # noqa: E402

TALLY_SRC = (ROOT / "orchardshare" / "harvest_ledger.py").read_text(encoding="utf-8")
SHARES_SRC = (ROOT / "orchardshare" / "collection_board.py").read_text(encoding="utf-8")


def _pickup_counts(total, hours):
    return {h: household_share(total, hours, h) for h in hours}


def _picking(day, variety, crates):
    return OrchardLoad(date(2025, 9, day), variety, crates, "Nell")


class OrchardshareHiddenChecks(unittest.TestCase):
    def test_f_tally_line(self):
        self.assertEqual(parse_pick(" 2025-10-02|ashmead's   KERNEL |40|  Kofi ", 3),
                         OrchardLoad(date(2025, 10, 2), "Ashmead's Kernel", 40, "Kofi"))
        self.assertEqual(parse_pick("2025-08-30 | COX_S ORANGE PIPPIN | 1 | Aled", 3).variety,
                         "Cox S Orange Pippin")

    def test_f_variety_totals(self):
        got = crates_by_variety([_picking(1, "Spartan", 4), _picking(1, "Katy", 2),
                                 _picking(2, "Spartan", 9), _picking(3, "Discovery", 1),
                                 _picking(3, "Katy", 5)])
        self.assertEqual(got, {"Spartan": 13, "Katy": 7, "Discovery": 1})
        self.assertEqual(list(got), ["Spartan", "Katy", "Discovery"])

    def test_f_shares(self):
        self.assertEqual(_pickup_counts(16, {"Hale": 2, "Ince": 2, "Jory": 4}),
                         {"Hale": 4, "Ince": 4, "Jory": 8})
        self.assertEqual(list(_pickup_counts(30, {"Zed": 5, "Amos": 1})), ["Zed", "Amos"])
        self.assertEqual(_pickup_counts(30, {"Zed": 5, "Amos": 1}), {"Zed": 25, "Amos": 5})
        self.assertEqual(_pickup_counts(9, {"Hale": 3, "Ince": 0}), {"Hale": 9, "Ince": 0})

    def test_f_sheet(self):
        self.assertEqual(share_sheet(20, {"Wren": 1, "Moss": 4}), "Wren: 4 crates\\nMoss: 16 crates\\n")

    def test_c1_tally_error(self):
        for text in ("2025-09-14 | bramley | 12", "2025-09-14 | bramley | 12 | Ruth | x",
                     "2025-09-31 | bramley | 12 | Ruth", "2025-09-14 |  | 12 | Ruth",
                     "2025-09-14 | bramley | 41 | Ruth", "2025-09-14 | bramley | 2.5 | Ruth",
                     "2025-09-14 | bramley | 12 |  ", "2025-09-14 | br4mley | 12 | Ruth"):
            with self.assertRaises(TallyError, msg=text) as cm:
                parse_pick(text, 7)
            self.assertEqual(cm.exception.line, 7)
        self.assertNotRegex(TALLY_SRC + SHARES_SRC, r"\\bprint\\s*\\(|sys\\.exit")

    def test_c2_varieties_from_legacy(self):
        self.assertIn("apple_variety", TALLY_SRC)
        self.assertEqual(parse_pick("2025-09-14 | blenheim_ORANGE | 3 | Sian", 1).variety,
                         "Blenheim Orange")

    def test_c3_whole_crates_as_ints(self):
        self.assertIs(type(parse_pick("2025-09-14 | katy | 3 | Sian", 1).crates), int)
        totals = crates_by_variety([_picking(1, "Katy", 2), _picking(2, "Katy", 3)])
        self.assertIs(type(totals["Katy"]), int)
        for total, hours in ((12, {"a": 1, "b": 2}), (10, {"a": 2, "b": 2, "c": 1}), (0, {"a": 4})):
            for value in _pickup_counts(total, hours).values():
                self.assertIs(type(value), int, (total, hours))

    def test_t_shares_add_up_to_the_crates(self):
        self.assertEqual(_pickup_counts(10, {"Hale": 1, "Ince": 1, "Jory": 1}),
                         {"Hale": 4, "Ince": 3, "Jory": 3})
        self.assertEqual(_pickup_counts(7, {"Wren": 2, "Moss": 2}), {"Wren": 4, "Moss": 3})
        got = _pickup_counts(11, {"a": 1, "b": 1, "c": 1, "d": 1, "e": 1, "f": 1})
        self.assertEqual(sum(got.values()), 11)
        self.assertEqual(_pickup_counts(5, {"a": 3, "b": 3, "c": 4}), {"a": 2, "b": 1, "c": 2})


if __name__ == "__main__":
    unittest.main()
'''}

TALLY_REF = _TALLY_HEAD + '''

def parse_pick(text: str, line: int) -> OrchardLoad:
    fields = [f.strip() for f in text.rstrip("\\n").split("|")]
    if len(fields) != 4:
        raise TallyError(line, f"expected 4 fields, found {len(fields)}")
    raw_day, raw_variety, raw_crates, picker = fields
    try:
        day = date.fromisoformat(raw_day)
    except ValueError:
        raise TallyError(line, f"bad day {raw_day!r}") from None
    try:
        variety = apple_variety(raw_variety)
    except ValueError as exc:
        raise TallyError(line, str(exc)) from None
    if not (raw_crates.isascii() and raw_crates.isdigit()) or not 1 <= int(raw_crates) <= 40:
        raise TallyError(line, f"crates must be a whole number from 1 to 40, not {raw_crates!r}")
    if not picker:
        raise TallyError(line, "no picker named")
    return OrchardLoad(day, variety, int(raw_crates), picker)


def crates_by_variety(picks: list[OrchardLoad]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for pick in picks:
        totals[pick.variety] = totals.get(pick.variety, 0) + pick.crates
    return totals
'''

SHARES_REF = '''"""Sharing the crop between households. See docs/tally.md."""

from __future__ import annotations


def _allocation(total: int, hours: dict[str, int]) -> dict[str, int]:
    # Largest remainder: whole parts first, then the crates left over go one each to the
    # biggest remainders, ties in sign-up order, so the shares sum to exactly ``total``.
    whole_hours = sum(hours.values())
    parts = {h: divmod(total * n, whole_hours) for h, n in hours.items()}
    given = {h: q for h, (q, _) in parts.items()}
    leftover = total - sum(given.values())
    order = sorted(hours, key=lambda h: -parts[h][1])
    for h in order[:leftover]:
        given[h] += 1
    return given


def household_share(total: int, hours: dict[str, int], household: str) -> int:
    return _allocation(total, hours)[household]


def share_sheet(total: int, hours: dict[str, int]) -> str:
    return "".join(f"{h}: {n} crates\\n" for h, n in _allocation(total, hours).items())
'''

REFERENCE = {"orchardshare/harvest_ledger.py": TALLY_REF, "orchardshare/collection_board.py": SHARES_REF}

TRAP_SOLUTION = {"orchardshare/collection_board.py": '''"""Sharing the crop between households. See docs/tally.md."""

from __future__ import annotations


def household_share(total: int, hours: dict[str, int], household: str) -> int:
    return round(total * hours[household] / sum(hours.values()))


def share_sheet(total: int, hours: dict[str, int]) -> str:
    lines = [f"{h}: {household_share(total, hours, h)} crates" for h in hours]
    return "".join(line + "\\n" for line in lines)
'''}

# X in code: each share turned into whole crates by itself, with round(), by adding a half
# before truncating, or with a Decimal quantize.
TRAP_PATTERNS = (
    r'\bround\(',
    r'\bint\([^()\n]*(?:\([^()\n]*\)[^()\n]*)*\+\s*0?\.5\s*\)',
    r'\bmath\.floor\([^()\n]*\+\s*0?\.5\s*\)',
    r'\.quantize\(',
    r'\bfloor\([^()\n]*(?:\([^()\n]*\)[^()\n]*)*\+\s*0?\.5\s*\)',
    r'\b(?:int|floor)\(\s*0?\.5\s*\+',
    r'\bROUND_HALF_\w+|\.to_integral(?:_value)?\(',
    r'//\s*\(\s*2\s*\*|//\s*\([^()\n]*\*\s*2\s*\)',
    r'\+\s*\(?\s*\w+(?:\([^()\n]*\))?\s*//\s*2\s*\)?\s*\)\s*//',
)
