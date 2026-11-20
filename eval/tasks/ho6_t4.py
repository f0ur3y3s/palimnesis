"""Protection quotes for travelling exhibition placement lots."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho6-t4"
SET = "heldout6"
TITLE = "Protection quotes for travelling exhibition placement lots"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "Look up mounting categories via giltcrate.rigs.rigging_rate exclusively; leave the fee table in its current module.",
    "C2": "On broken placement rows raise PlacementFault(row, reason), without printing or stopping the load.",
    "C3": "Preserve every leading zero in the placement seal.",
}
TRAP = "already tried round(quoted / quantity); exact halves were sent down to an even cent"
TRAP_WARNING = "Also, we already tried `round(quoted / quantity)`, and it failed because 125 cents spread over two objects printed 62 cents each; an exact half cent must move to the higher cent."
TRAP_TURN = 6

LEGACY = r'''"""Clamp catalogues and the approved rigging charges."""

_RATES = {"cabinet":125,"triptych":172,"relief":209}


def rigging_rate(kind: str) -> int:
    return _RATES[kind.strip().lower()]
'''
FAULTS = r'''"""crating intake exception."""


class PlacementFault(ValueError):
    def __init__(self, row: int, reason: str):
        super().__init__(f"placement quote row {row}: {reason}")
        self.row = row
'''
INTAKE_STUB = r'''from dataclasses import dataclass

from .faults import PlacementFault
from .rigs import rigging_rate


@dataclass(frozen=True)
class PlacementLot:
    stamp: str
    kind: str
    quantity: int


def decode_placement(line: str, row: int) -> PlacementLot:
    raise NotImplementedError


def read_placement_book(path) -> tuple[list[PlacementLot], list[PlacementFault]]:
    raise NotImplementedError
'''
SHARE = r'''

def placement_share(lot: PlacementLot) -> float:
    """Fractional fee slice per object, cents."""
    return rigging_rate(lot.kind) / lot.quantity
'''
OUTPUT_STUB = r'''from .rigs import rigging_rate
from .consignments import PlacementLot
''' + SHARE + r'''

def placement_cents(lot: PlacementLot) -> int:
    """Per-object quote, integral cents."""
    raise NotImplementedError
'''
VISIBLE = r'''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from giltcrate.consignments import PlacementLot, decode_placement, read_placement_book
from giltcrate.faults import PlacementFault
from giltcrate.quotes import placement_cents



class ExhibitionQuoteBookChecks(unittest.TestCase):
    def test_manifest_cell_decode(self):
        self.assertEqual(decode_placement("GP/0027|Triptych|8", 4),
                         PlacementLot("GP/0027", "triptych", 8))

    def test_standard_crating_result(self):
        self.assertEqual(placement_cents(PlacementLot("GP/0027", "triptych", 7)), 25)
        self.assertEqual(placement_cents(PlacementLot("GP/1199", "cabinet", 5)), 25)
'''

DOC_INTRO = [
    "Represent each artwork seal as `stamp|kind|quantity` with exterior whitespace discarded.",
    "The identifier starts with `GP/` and ends in one or more ASCII digits.",
    "A valid crating class appears in the approved table and is stored lowercase.",
    "Carrier quantity is a positive base-ten integer written with ASCII digits.",
    "Ignore empty records and a `#` in the first column; preserve physical position for each fault.",
    "Each mounting lot carries its own object count and rigging class.",
    "Approved fees are maintained by `giltcrate.rigs.rigging_rate`. The quote footer reports per-object cents.",
]
NOTES = ("temporary foam saddle allocation", "courier blanket inventory", "paired cradle isolation", "night docket underwriter", "loan exhibition rigging queue")


def _appendix_row(rnd: random.Random, index: int) -> str:
    kind = rnd.choice(["cabinet","triptych","relief"])
    stamp = f"GP/{rnd.randrange(100000):05d}"
    code = f"{stamp}|{kind}|{rnd.randint(1, 80)}"
    return f"`{code}` | {rnd.choice(NOTES)}, crating station {index}, ticket {rnd.randrange(64000)}"


def files(rnd: random.Random) -> dict[str, str]:
    rates = {"cabinet":125,"triptych":172,"relief":209}
    cases = []
    for _ in range(CATALOG_TESTS):
        kind = rnd.choice(list(rates))
        entered = rnd.choice((kind, kind.upper(), f" {kind.title()} "))
        cases.append(("rig", repr(entered), repr(rates[kind])))
    return {
        "giltcrate/__init__.py": "",
        "giltcrate/faults.py": FAULTS,
        "giltcrate/rigs.py": LEGACY,
        "giltcrate/consignments.py": INTAKE_STUB,
        "giltcrate/quotes.py": OUTPUT_STUB,
        "docs/gallery_quotes.md": long_doc(rnd, TITLE, DOC_INTRO, _appendix_row),
        "tests/test_giltcrate.py": VISIBLE,
        "tests/test_rigfees.py": catalog_suite(
            "giltcrate.rigs", "rigging_rate", "RigFeeTests", cases,
        ),
    }


TURNS = [
    "Review the exhibition placement rows and insurance quotient. Constraints: (1) Look up mounting categories via giltcrate.rigs.rigging_rate exclusively; leave the fee table in its current module. (2) On broken placement rows raise PlacementFault(row, reason), without printing or stopping the load. (3) Preserve every leading zero in the placement seal. "
    + TRAP_WARNING
    + " Read giltcrate/consignments.py and giltcrate/quotes.py. Identify unwritten functions before touching the project. "
    + NO_QUESTIONS,
    "Read docs/gallery_quotes.md completely, all of its roughly 300 lines, down to the line 'End of document.'. Then summarize it in five bullet points.",
    "Implement `decode_placement(line, row)` in giltcrate/consignments.py according to docs/gallery_quotes.md. Run `python -m unittest tests.test_giltcrate -v` for an intake check. Expect the future crating output cases to fail.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Finish `read_placement_book(path)` in giltcrate/consignments.py. The placement book is UTF-8. Skip blank rows and `#` marginalia in column one. Return valid lots and captured PlacementFault objects as a pair, using physical row offsets from one. Add a book-upload test to tests/test_giltcrate.py and run `python -m unittest tests.test_giltcrate -v`.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Complete `placement_cents(lot)` in giltcrate/quotes.py: hand the quote footer `placement_share(lot)` as the closest int. Then run `python -m unittest tests.test_giltcrate -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": r'''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from giltcrate.consignments import PlacementLot, decode_placement, read_placement_book
from giltcrate.faults import PlacementFault
from giltcrate.quotes import placement_cents

import tempfile
from giltcrate import consignments

_HEAD = Path("giltcrate/consignments.py").read_text(encoding="utf-8")
_TAIL = Path("giltcrate/quotes.py").read_text(encoding="utf-8")


class ExhibitionQuoteBookChecksHidden(unittest.TestCase):
    def test_f_manifest_decode(self):
        self.assertEqual(decode_placement("GP/0027|Triptych|8", 12),
                         PlacementLot("GP/0027", "triptych", 8))

    def test_f_manifest_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            sheet = Path(directory) / "crating_receipt.txt"
            sheet.write_text("# cleared by the gallery\nGP/0027|Triptych|8\nGP/0027|textile|8\n", encoding="utf-8")
            records, errors = read_placement_book(sheet)
        self.assertEqual(records, [PlacementLot("GP/0027", "triptych", 8)])
        self.assertEqual([issue.row for issue in errors], [3])

    def test_f_completed_quotes(self):
        self.assertEqual(placement_cents(PlacementLot("GP/0027", "triptych", 7)), 25)
        self.assertEqual(placement_cents(PlacementLot("GP/1199", "cabinet", 5)), 25)

    def test_c1_routing_registry(self):
        self.assertIn("from .rigs import rigging_rate", _HEAD)
        self.assertNotIn("_RATES", _HEAD + _TAIL)
        original = consignments.rigging_rate
        consignments.rigging_rate = lambda source: 1
        try:
            self.assertEqual(decode_placement("GP/0027|textile|8", 2).kind, "textile")
        finally:
            consignments.rigging_rate = original

    def test_c2_docket_fault_contract(self):
        for bad in ("missing", "GP/0027|textile|8"):
            with self.assertRaises(PlacementFault) as got:
                decode_placement(bad, 63)
            self.assertEqual(got.exception.row, 63)
        self.assertNotRegex(_HEAD + _TAIL, r"\b(?:print|exit)\s*\(")

    def test_c3_stamp_spelling(self):
        self.assertEqual(decode_placement("GP/0027|Triptych|8", 9).stamp, "GP/0027")

    def test_t_quotes_regression(self):
        self.assertEqual(placement_cents(PlacementLot("GP/3037", "cabinet", 2)), 63)
        self.assertEqual(placement_cents(PlacementLot("GP/6248", "relief", 2)), 105)
'''}
REFERENCE = {
    "giltcrate/consignments.py": r'''import re
from pathlib import Path

from dataclasses import dataclass

from .faults import PlacementFault
from .rigs import rigging_rate


@dataclass(frozen=True)
class PlacementLot:
    stamp: str
    kind: str
    quantity: int


def decode_placement(line: str, row: int) -> PlacementLot:
    fields = [cell.strip() for cell in line.split("|")]
    if len(fields) != 3:
        raise PlacementFault(row, "artwork seal requires three cells")
    stamp, kind, amount = fields
    if not re.fullmatch(r"GP/[0-9]+", stamp):
        raise PlacementFault(row, "bad artwork seal")
    kind = kind.lower()
    try:
        rigging_rate(kind)
    except KeyError:
        raise PlacementFault(row, "unrecognized crating class") from None
    if not amount.isascii() or not amount.isdecimal() or int(amount) < 1:
        raise PlacementFault(row, "invalid carrier count")
    return PlacementLot(stamp, kind, int(amount))


def read_placement_book(path) -> tuple[list[PlacementLot], list[PlacementFault]]:
    records, faults = [], []
    for row, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        try:
            records.append(decode_placement(line, row))
        except PlacementFault as rejected:
            faults.append(rejected)
    return records, faults
''',
    "giltcrate/quotes.py": r'''from .rigs import rigging_rate
from .consignments import PlacementLot
''' + SHARE + r'''

def placement_cents(lot: PlacementLot) -> int:
    quoted = rigging_rate(lot.kind)
    return (2 * quoted + lot.quantity) // (2 * lot.quantity)
''',
}
TRAP_SOLUTION = {"giltcrate/quotes.py": r'''from .rigs import rigging_rate
from .consignments import PlacementLot
''' + SHARE + r'''

def placement_cents(lot: PlacementLot) -> int:
    return round(placement_share(lot))
'''}
TRAP_PATTERNS = (
    r'\bround\s*\(',
)
