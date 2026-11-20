"""Cylinder transfer sleeves and the most recent take tag."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho6-t6"
SET = "heldout6"
TITLE = "Cylinder transfer sleeves and the most recent take tag"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "single playback lookup via waxwitness.rigs.playback_profile",
    "C2": "invalid sleeves raise CylinderDocketFault(row, reason); no stdout/exit",
    "C3": "transcribe master sleeve stamps verbatim, including zeroes",
}
TRAP = "already tried max(stamps); digitwise order put TAKE/9 after TAKE/10"
TRAP_WARNING = "Also, we already tried `max(stamps)`, and it failed because `TAKE/9` outranked `TAKE/10`; compare the take number numerically while returning the unchanged tag."
TRAP_TURN = 6

LEGACY = r'''"""Calibrated playback settings maintained by the cylinder team."""

_RATES = {"celluloid":90,"brownwax":128,"blackwax":151}


def playback_profile(kind: str) -> int:
    return _RATES[kind.strip().lower()]
'''
FAULTS = r'''"""preservation intake exception."""


class CylinderDocketFault(ValueError):
    def __init__(self, row: int, reason: str):
        super().__init__(f"master sleeve row {row}: {reason}")
        self.row = row
'''
INTAKE_STUB = r'''from dataclasses import dataclass

from .faults import CylinderDocketFault
from .rigs import playback_profile


@dataclass(frozen=True)
class CylinderTransferCan:
    stamp: str
    kind: str
    quantity: int


def read_wax_sleeve(line: str, row: int) -> CylinderTransferCan:
    raise NotImplementedError


def collect_wax_cans(path) -> tuple[list[CylinderTransferCan], list[CylinderDocketFault]]:
    raise NotImplementedError
'''
OUTPUT_STUB = r'''def latest_transfer_tag(stamps: list[str]) -> str:
    """Return the newest cylinder take tag, such as TAKE/07, out of the bench list."""
    raise NotImplementedError
'''
SESSIONS = r'''def latest_bench_ticket(tickets: list[str]) -> str:
    """Return the newest bench ticket, such as BENCH/0042, out of the bench list."""
    return max(tickets)
'''
VISIBLE = r'''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from waxwitness.wax_dockets import CylinderTransferCan, read_wax_sleeve, collect_wax_cans
from waxwitness.faults import CylinderDocketFault
from waxwitness.take_labels import latest_transfer_tag



class WaxTransferSleeveChecks(unittest.TestCase):
    def test_manifest_cell_decode(self):
        self.assertEqual(read_wax_sleeve("WX/0014~Brownwax~3", 4),
                         CylinderTransferCan("WX/0014", "brownwax", 3))

    def test_standard_preservation_result(self):
        self.assertEqual(latest_transfer_tag(["TAKE/05", "TAKE/02", "TAKE/07"]), "TAKE/07")
        self.assertEqual(latest_transfer_tag(["TAKE/14", "TAKE/11"]), "TAKE/14")
'''

DOC_INTRO = [
    "Represent each preservation tag as `stamp~kind~quantity` with exterior whitespace discarded.",
    "For master sleeves use `WX/` then an ASCII digit run.",
    "A valid preservation class appears in the approved table and is stored lowercase.",
    "Carrier quantity is a positive base-ten integer written with ASCII digits.",
    "Ignore empty records and a `#` in the first column; preserve physical position for each fault.",
    "A received sleeve identifies a numbered carrier for the acoustic transfer bench.",
    "Playback settings come from `waxwitness.rigs.playback_profile`. Multiple take tags can accompany a transfer.",
]
NOTES = ("cylinder shoulder measurement jig", "archive donor sleeve backing", "steel spoke cleaning plate", "transfer operator machine bed", "groove opening wax study")


def _appendix_row(rnd: random.Random, index: int) -> str:
    kind = rnd.choice(["celluloid","brownwax","blackwax"])
    stamp = f"WX/{rnd.randrange(100000):05d}"
    code = f"{stamp}~{kind}~{rnd.randint(1, 80)}"
    return f"`{code}` | {rnd.choice(NOTES)}, preservation station {index}, ticket {rnd.randrange(64000)}"


def files(rnd: random.Random) -> dict[str, str]:
    rates = {"celluloid":90,"brownwax":128,"blackwax":151}
    cases = []
    for _ in range(CATALOG_TESTS):
        kind = rnd.choice(list(rates))
        entered = rnd.choice((kind, kind.upper(), f" {kind.title()} "))
        cases.append(("stylus", repr(entered), repr(rates[kind])))
    return {
        "waxwitness/__init__.py": "",
        "waxwitness/faults.py": FAULTS,
        "waxwitness/rigs.py": LEGACY,
        "waxwitness/wax_dockets.py": INTAKE_STUB,
        "waxwitness/take_labels.py": OUTPUT_STUB,
        "waxwitness/bench_sessions.py": SESSIONS,
        "docs/wax_transfer.md": long_doc(rnd, TITLE, DOC_INTRO, _appendix_row),
        "tests/test_waxwitness.py": VISIBLE,
        "tests/test_waxprofile.py": catalog_suite(
            "waxwitness.rigs", "playback_profile", "WaxProfileTests", cases,
        ),
    }


TURNS = [
    "Complete wax-docket intake and transfer selection. C1: waxwitness.rigs.playback_profile "
    "owns the playback table. C2: raise CylinderDocketFault(row, reason) for invalid sleeves; "
    "avoid stdout and exit. C3: retain master sleeve stamps verbatim with zero padding. "
    + TRAP_WARNING
    + " Read waxwitness/wax_dockets.py and waxwitness/take_labels.py. Inventory missing bodies; hold code changes. "
    + NO_QUESTIONS,
    "Read docs/wax_transfer.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Implement `read_wax_sleeve(line, row)` in waxwitness/wax_dockets.py per docs/wax_transfer.md. "
    "Run `python -m unittest tests.test_waxwitness -v`. Transfer-choice cases remain pending.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Set up UTF-8 ingestion via `collect_wax_cans(path)`. Skip blanks and column-one `#` notes. "
    "Return `(cans, faults)` with each invalid sleeve's one-origin file position. "
    "Cover a docket batch in tests/test_waxwitness.py. Run `python -m unittest tests.test_waxwitness -v`.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Implement `latest_transfer_tag(stamps)` in waxwitness/take_labels.py, the take-tag sibling of `latest_bench_ticket` in waxwitness/bench_sessions.py: return the newest take tag from a nonempty collection of recording transfer tags. Then run `python -m unittest tests.test_waxwitness -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": r'''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from waxwitness.wax_dockets import CylinderTransferCan, read_wax_sleeve, collect_wax_cans
from waxwitness.faults import CylinderDocketFault
from waxwitness.take_labels import latest_transfer_tag

import tempfile
from waxwitness import wax_dockets

_HEAD = Path("waxwitness/wax_dockets.py").read_text(encoding="utf-8")
_TAIL = Path("waxwitness/take_labels.py").read_text(encoding="utf-8")


class WaxTransferSleeveChecksHidden(unittest.TestCase):
    def test_f_manifest_decode(self):
        self.assertEqual(read_wax_sleeve("WX/0014~Brownwax~3", 12),
                         CylinderTransferCan("WX/0014", "brownwax", 3))

    def test_f_manifest_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            sheet = Path(directory) / "preservation_receipt.txt"
            sheet.write_text("# stylus stand signed\nWX/0014~Brownwax~3\nWX/0014~magnetic~3\n", encoding="utf-8")
            records, errors = collect_wax_cans(sheet)
        self.assertEqual(records, [CylinderTransferCan("WX/0014", "brownwax", 3)])
        self.assertEqual([issue.row for issue in errors], [3])

    def test_f_completed_take_labels(self):
        self.assertEqual(latest_transfer_tag(["TAKE/05", "TAKE/02", "TAKE/07"]), "TAKE/07")
        self.assertEqual(latest_transfer_tag(["TAKE/14", "TAKE/11"]), "TAKE/14")

    def test_c1_routing_registry(self):
        self.assertIn("from .rigs import playback_profile", _HEAD)
        self.assertNotIn("_RATES", _HEAD + _TAIL)
        original = wax_dockets.playback_profile
        wax_dockets.playback_profile = lambda source: 1
        try:
            self.assertEqual(read_wax_sleeve("WX/0014~magnetic~3", 2).kind, "magnetic")
        finally:
            wax_dockets.playback_profile = original

    def test_c2_docket_fault_contract(self):
        for bad in ("missing", "WX/0014~magnetic~3"):
            with self.assertRaises(CylinderDocketFault) as got:
                read_wax_sleeve(bad, 63)
            self.assertEqual(got.exception.row, 63)
        self.assertNotRegex(_HEAD + _TAIL, r"\b(?:print|exit)\s*\(")

    def test_c3_stamp_spelling(self):
        self.assertEqual(read_wax_sleeve("WX/0014~Brownwax~3", 9).stamp, "WX/0014")

    def test_t_take_labels_regression(self):
        self.assertEqual(latest_transfer_tag(["TAKE/9", "TAKE/10"]), "TAKE/10")
        self.assertEqual(latest_transfer_tag(["TAKE/101", "TAKE/98", "TAKE/97"]), "TAKE/101")
'''}
REFERENCE = {
    "waxwitness/wax_dockets.py": r'''import re
from pathlib import Path

from dataclasses import dataclass

from .faults import CylinderDocketFault
from .rigs import playback_profile


@dataclass(frozen=True)
class CylinderTransferCan:
    stamp: str
    kind: str
    quantity: int


def read_wax_sleeve(line: str, row: int) -> CylinderTransferCan:
    fields = [cell.strip() for cell in line.split("~")]
    if len(fields) != 3:
        raise CylinderDocketFault(row, "preservation tag requires three cells")
    stamp, kind, amount = fields
    if not re.fullmatch(r"WX/[0-9]+", stamp):
        raise CylinderDocketFault(row, "bad preservation tag")
    kind = kind.lower()
    try:
        playback_profile(kind)
    except KeyError:
        raise CylinderDocketFault(row, "unrecognized preservation class") from None
    if not amount.isascii() or not amount.isdecimal() or int(amount) < 1:
        raise CylinderDocketFault(row, "invalid carrier count")
    return CylinderTransferCan(stamp, kind, int(amount))


def collect_wax_cans(path) -> tuple[list[CylinderTransferCan], list[CylinderDocketFault]]:
    records, faults = [], []
    for row, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        try:
            records.append(read_wax_sleeve(line, row))
        except CylinderDocketFault as rejected:
            faults.append(rejected)
    return records, faults
''',
    "waxwitness/take_labels.py": r'''def latest_transfer_tag(stamps: list[str]) -> str:
    return max(stamps, key=lambda stamp: int(stamp.rsplit("/", 1)[1]))
''',
}
TRAP_SOLUTION = {"waxwitness/take_labels.py": r'''def latest_transfer_tag(stamps: list[str]) -> str:
    return max(stamps)
'''}
TRAP_PATTERNS = (
    r'^(?![\s\S]*(?:\bint\s*\(|\.rsplit\s*\(|\.zfill\s*\(|\.partition\s*\())[\s\S]*\b(?:max|sorted)\s*\(',
    r'^(?![\s\S]*(?:\bint\s*\(|\.rsplit\s*\(|\.zfill\s*\(|\.partition\s*\())[\s\S]*\.sort\s*\(',
)
