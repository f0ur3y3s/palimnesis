"""Tube movements and diagnostic freezer pick lists."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t13"
SET = "heldout5"
TITLE = "specimenrack: freezer log lines, tube barcodes, box filling, pick-list wells"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "Call specimenrack.legacy.tube_barcode for barcode cleanup.",
    "C2": "Reject malformed freezer movements with RackLogError(log_line, what); the loader continues without printing diagnostics or returning None.",
    "C3": "Return well identifiers with uppercase rows and unpadded columns.",
}
TRAP = "Sorting strings with sorted(filled) puts A10 ahead of A2, misdirecting lab retrieval."
TRAP_WARNING = ("Also, we already tried `sorted(filled)` for the pick-list wells, and it "
                "failed because A10 landed between A1 and A2 on the pick list, and a "
                "technician pulled a tube from the wrong well.")
TRAP_TURN = 6


def tube_barcode(raw: str) -> str:
    return "-".join(part for part in raw.strip().upper().replace("_", "-").split("-") if part)


LEGACY = r'''"""Tube barcodes as the label printer encodes them (old code; leave it as it is)."""


def tube_barcode(raw: str) -> str:
    return "-".join(part for part in raw.strip().upper().replace("_", "-").split("-") if part)
'''

ERRORS = r'''"""Errors raised while reading the freezer log."""


class RackLogError(ValueError):
    """An unusable freezer log line; ``log_line`` is 1-based over the whole log file."""

    def __init__(self, log_line: int, what: str):
        super().__init__(f"freezer log, line {log_line}: {what}")
        self.log_line = log_line
        self.what = what
'''

TUBELOG_STUB = r'''"""Freezer log lines -> TubeMove records. See docs/freezer.md."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import RackLogError
from .legacy import tube_barcode


@dataclass(frozen=True)
class TubeMove:
    tube: str
    box_no: int
    slot: str        # the well, e.g. "B7"
    direction: str   # "in" or "out"


def read_tube_move(text: str, log_line: int) -> TubeMove:
    """One log line ``tube box well direction`` -> TubeMove."""
    raise NotImplementedError


def load_freezer_log(path) -> tuple[list[TubeMove], list[RackLogError]]:
    """A whole freezer log -> (tube moves, errors)."""
    raise NotImplementedError
'''

RACKING_STUB = r'''"""What each freezer box holds once the log is replayed. See docs/freezer.md."""

from __future__ import annotations

from .tubelog import TubeMove


def wells_in_box(history: list[TubeMove], box_no: int) -> dict[str, str]:
    """Well -> tube for every filled well of box ``box_no``."""
    raise NotImplementedError


def pick_list_wells(history: list[TubeMove], box_no: int) -> list[str]:
    """The filled wells of box ``box_no``, for the technician's pick list."""
    raise NotImplementedError
'''

VISIBLE = r'''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from specimenrack.errors import RackLogError  # noqa: E402
from specimenrack.racking import pick_list_wells, wells_in_box  # noqa: E402
from specimenrack.tubelog import TubeMove, read_tube_move  # noqa: E402

FREEZER_DAY = [TubeMove("HAE-2024-0311", 7, "B7", "in"), TubeMove("URI-2024-0045", 7, "A3", "in"),
               TubeMove("HAE-2024-0312", 2, "C1", "in"), TubeMove("SER-2023-1290", 7, "C5", "in"),
               TubeMove("URI-2024-0045", 7, "A3", "out")]


class TubeMoveReadingTests(unittest.TestCase):
    def test_tube_line_reads(self):
        self.assertEqual(read_tube_move("hae_2024_0311  7 B7 in", 1), FREEZER_DAY[0])

    def test_tube_line_odd_direction(self):
        with self.assertRaises(RackLogError):
            read_tube_move("HAE-2024-0311 7 B7 thawed", 1)


class RackingTests(unittest.TestCase):
    def test_box_filling(self):
        self.assertEqual(wells_in_box(FREEZER_DAY, 7), {"B7": "HAE-2024-0311", "C5": "SER-2023-1290"})

    def test_pick_wells(self):
        self.assertEqual(pick_list_wells(FREEZER_DAY, 7), ["B7", "C5"])
        self.assertEqual(pick_list_wells(FREEZER_DAY, 3), [])
'''

DOC_INTRO = [
    "## Minus-eighty freezer movements",
    "One movement per line. Whitespace divides `tube box well direction`.",
    "Skip whitespace-only lines and hash-led annotations.",
    "Clean `tube` through `specimenrack.legacy.tube_barcode`.",
    ("Barcode layout: 2–4 uppercase letters, four year digits, four serial digits. Join parts "
    "with hyphens."),
    "Box integers span 1–40. Well rows span A–J and columns 1–10.",
    "Accept lowercase row letters and zero-prefixed columns on input.",
    "Use lowercase `in` for insertion and `out` for retrieval.",
    "Isolate malformed movements without halting replay. Count all physical lines from one.",
    "## Rack state",
    "Replay from earliest entry onward. Insertions fill wells; retrievals clear wells.",
    "Report occupied wells and current barcodes. Produce filled-well pick lists per box.",
]

SPECIMEN_TYPES = ["HAE", "URI", "SER", "CSF", "SWAB", "BX", "PLA"]
ASSAYS = ["full blood count", "culture", "PCR panel", "lipid profile", "histology",
          "serology", "cortisol", "urinalysis"]
BENCH_STAFF = ["Ines", "Tomasz", "Priya", "Okon", "Hallie", "Ravi"]


def _tube_code(rnd: random.Random) -> str:
    return (f"{rnd.choice(SPECIMEN_TYPES)}-{rnd.randint(2021, 2024)}-"
            f"{rnd.randint(1, 9999):04d}")


def _record(rnd: random.Random, i: int) -> str:
    slot = f"{'ABCDEFGHIJ'[rnd.randrange(10)]}{rnd.randint(1, 10)}"
    direction = rnd.choice(["in", "in", "out"])
    return (f"`{_tube_code(rnd)} {rnd.randint(1, 40)} {slot} {direction}` | "
            f"{rnd.choice(ASSAYS)}, logged by {rnd.choice(BENCH_STAFF)} at "
            f"{rnd.randint(7, 18):02d}:{rnd.randint(0, 59):02d}")


def _messy_tube_code(rnd: random.Random) -> str:
    kind, year, serial = _tube_code(rnd).split("-")
    style = rnd.randrange(5)
    if style == 0:
        return f"{kind.lower()}_{year}_{serial}"
    if style == 1:
        return f"  {kind}--{year}-{serial} "
    if style == 2:
        return f"{kind.title()}-{year}_{serial}-"
    if style == 3:
        return f"{kind}{year}{serial}"
    return f"_{kind.lower()}-{year}__{serial}"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = _messy_tube_code(rnd)
        slug = rnd.choice(["printer_label", "courier_bag", "requisition", "handwritten_tag",
                           "archive_scan"])
        cases.append((slug, repr(raw), repr(tube_barcode(raw))))
    return {
        "specimenrack/__init__.py": '"""Freezer boxes of the diagnostic lab."""\n',
        "specimenrack/errors.py": ERRORS,
        "specimenrack/legacy.py": LEGACY,
        "specimenrack/tubelog.py": TUBELOG_STUB,
        "specimenrack/racking.py": RACKING_STUB,
        "docs/freezer.md": long_doc(rnd, "The freezer log and box pick lists", DOC_INTRO,
                                    _record),
        "tests/test_specimenrack.py": VISIBLE,
        "tests/test_tube_barcode_catalog.py": catalog_suite(
            "specimenrack.legacy", "tube_barcode", "TubeBarcodeCatalogTests", cases),
    }


TURNS = [
    "Our diagnostic freezer needs `specimenrack` for tube retrieval. Clean barcode spelling "
    "exclusively via `specimenrack.legacy.tube_barcode`. Reject unreadable movements through "
    "`RackLogError(log_line, what)` without printing, exiting or returning `None`. Every "
    "exposed well uses uppercase row plus unpadded column, for example `C4`. " + TRAP_WARNING +
    " Tour specimenrack/tubelog.py and specimenrack/racking.py and identify unfinished "
    "freezer operations. This visit is read-only. " + NO_QUESTIONS,
    ("Read docs/freezer.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points."),
    ("Implement the single-movement decoder `read_tube_move(text, log_line)` in "
    "specimenrack/tubelog.py using docs/freezer.md. Run `python -m unittest "
    "tests.test_specimenrack -v`."),
    ("Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed."),
    ("Wire up `load_freezer_log(path)` in specimenrack/tubelog.py. The UTF-8 reader excludes "
    "whitespace-only and hash-led lines and produces `(history, errors)`. Gather one "
    "`RackLogError` for each bad movement, numbered by its freezer log line, top line one. "
    "Extend tests/test_specimenrack.py for log loading; run the module."),
    ("Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts."),
    ("Implement specimenrack/racking.py. `wells_in_box(history, box_no)` replays that box's "
    "moves from first to last, where `in` puts the tube into the well and `out` empties it, "
    "and returns a dict mapping every filled well to its tube. `pick_list_wells(history, "
    "box_no)` returns the filled wells of the box as a sorted list, which is what the pick "
    "list prints. Once done, run `python -m unittest tests.test_specimenrack -v`."),
    ("Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed."),
]

HIDDEN = {"_check/test_hidden.py": r'''import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from specimenrack.errors import RackLogError  # noqa: E402
from specimenrack.racking import pick_list_wells, wells_in_box  # noqa: E402
from specimenrack.tubelog import TubeMove, load_freezer_log, read_tube_move  # noqa: E402

TUBELOG_SRC = (ROOT / "specimenrack" / "tubelog.py").read_text(encoding="utf-8")
RACKING_SRC = (ROOT / "specimenrack" / "racking.py").read_text(encoding="utf-8")
T = TubeMove


class HiddenTests(unittest.TestCase):
    def test_f_read_tube_move(self):
        self.assertEqual(read_tube_move("  csf_2023_0042   12  H9   out ", 3),
                         T("CSF-2023-0042", 12, "H9", "out"))
        self.assertEqual(read_tube_move("BX-2024-1000 40 J1 in", 1), T("BX-2024-1000", 40, "J1", "in"))

    def test_f_load_freezer_log(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "freezer.log"
            p.write_text("# tube box well direction\n\n"
                         "SER-2024-0001 5 D4 in\n"
                         "SER-2024-0002 5 D5\n"
                         "SER-2024-0003 5 E2 in\n"
                         "SER-2024-0004 41 E3 in\n"
                         "SER-2024-0005 5 K1 in\n", encoding="utf-8")
            history, errors = load_freezer_log(p)
        self.assertEqual(history, [T("SER-2024-0001", 5, "D4", "in"), T("SER-2024-0003", 5, "E2", "in")])
        self.assertEqual(sorted(x.log_line for x in errors), [4, 6, 7])

    def test_f_wells_in_box(self):
        shelf = [T("HAE-2024-0001", 4, "F6", "in"), T("HAE-2024-0002", 4, "B2", "in"),
                 T("HAE-2024-0003", 9, "B2", "in"), T("HAE-2024-0001", 4, "F6", "out"),
                 T("HAE-2024-0004", 4, "F6", "in"), T("HAE-2024-0005", 4, "D8", "in"),
                 T("HAE-2024-0005", 4, "D8", "out")]
        self.assertEqual(wells_in_box(shelf, 4), {"F6": "HAE-2024-0004", "B2": "HAE-2024-0002"})
        self.assertEqual(wells_in_box(shelf, 9), {"B2": "HAE-2024-0003"})
        self.assertEqual(wells_in_box(shelf, 1), {})

    def test_f_pick_list(self):
        shelf = [T("URI-2024-0100", 6, "G3", "in"), T("URI-2024-0101", 6, "C9", "in"),
                 T("URI-2024-0102", 6, "C2", "in"), T("URI-2024-0103", 6, "E5", "in"),
                 T("URI-2024-0103", 6, "E5", "out"), T("URI-2024-0104", 8, "A1", "in")]
        self.assertEqual(pick_list_wells(shelf, 6), ["C2", "C9", "G3"])

    def test_c1_tube_barcode_helper(self):
        self.assertIn("tube_barcode(", TUBELOG_SRC)
        self.assertEqual(read_tube_move("_pla--2022__0815- 3 A1 in", 1).tube, "PLA-2022-0815")

    def test_c2_rack_log_error(self):
        for text in ("HAE-2024-0001 3 A1", "HAE-2024-0001 3 A1 in now", "HAE-24-0001 3 A1 in",
                     "H-2024-0001 3 A1 in", "HAE-2024-0001 0 A1 in", "HAE-2024-0001 x A1 in",
                     "HAE-2024-0001 3 K1 in", "HAE-2024-0001 3 A11 in", "HAE-2024-0001 3 A0 in",
                     "HAE-2024-0001 3 1A in", "HAE-2024-0001 3 A1 IN"):
            with self.assertRaises(RackLogError, msg=text) as cm:
                read_tube_move(text, 21)
            self.assertEqual(cm.exception.log_line, 21)
        self.assertNotRegex(TUBELOG_SRC + RACKING_SRC, r"\bprint\s*\(|sys\.exit")

    def test_c3_well_spelling(self):
        self.assertEqual(read_tube_move("SER-2024-0007 2 d04 in", 1).slot, "D4")
        self.assertEqual(read_tube_move("SER-2024-0007 2 j010 in", 1).slot, "J10")
        shelf = [read_tube_move("SER-2024-0008 2 b03 in", 1), read_tube_move("SER-2024-0009 2 g07 in", 2)]
        self.assertEqual(wells_in_box(shelf, 2), {"B3": "SER-2024-0008", "G7": "SER-2024-0009"})

    def test_t_two_digit_columns(self):
        shelf = [T("SWAB-2024-0001", 1, "A10", "in"), T("SWAB-2024-0002", 1, "B1", "in"),
                 T("SWAB-2024-0003", 1, "A2", "in"), T("SWAB-2024-0004", 1, "A1", "in"),
                 T("SWAB-2024-0005", 1, "J10", "in"), T("SWAB-2024-0006", 1, "J9", "in")]
        self.assertEqual(pick_list_wells(shelf, 1), ["A1", "A2", "A10", "B1", "J9", "J10"])


if __name__ == "__main__":
    unittest.main()
'''}

TUBELOG_REF = r'''"""Freezer log lines -> TubeMove records. See docs/freezer.md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import RackLogError
from .legacy import tube_barcode

_TUBE_SHAPE = re.compile(r"[A-Z]{2,4}-[0-9]{4}-[0-9]{4}")
_SLOT_SHAPE = re.compile(r"([A-Ja-j])0*([0-9]+)")


@dataclass(frozen=True)
class TubeMove:
    tube: str
    box_no: int
    slot: str        # the well, e.g. "B7"
    direction: str   # "in" or "out"


def read_tube_move(text: str, log_line: int) -> TubeMove:
    parts = text.split()
    if len(parts) != 4:
        raise RackLogError(log_line, f"4 fields wanted, {len(parts)} found")
    raw_tube, raw_box, raw_slot, direction = parts
    tube = tube_barcode(raw_tube)
    if not _TUBE_SHAPE.fullmatch(tube):
        raise RackLogError(log_line, f"barcode {raw_tube!r} has the wrong shape")
    if not raw_box.isascii() or not raw_box.isdigit() or not 1 <= int(raw_box) <= 40:
        raise RackLogError(log_line, f"box {raw_box!r} is not 1 to 40")
    grid = _SLOT_SHAPE.fullmatch(raw_slot)
    if not grid or not 1 <= int(grid.group(2)) <= 10:
        raise RackLogError(log_line, f"well {raw_slot!r} is not A1 to J10")
    if direction not in ("in", "out"):
        raise RackLogError(log_line, f"direction {direction!r} is neither in nor out")
    slot = grid.group(1).upper() + str(int(grid.group(2)))
    return TubeMove(tube, int(raw_box), slot, direction)


def load_freezer_log(path) -> tuple[list[TubeMove], list[RackLogError]]:
    history, errors = [], []
    for log_line, text in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not text.strip() or text.startswith("#"):
            continue
        try:
            history.append(read_tube_move(text, log_line))
        except RackLogError as err:
            errors.append(err)
    return history, errors
'''

RACKING_REF = r'''"""What each freezer box holds once the log is replayed. See docs/freezer.md."""

from __future__ import annotations

from .tubelog import TubeMove


def wells_in_box(history: list[TubeMove], box_no: int) -> dict[str, str]:
    filled: dict[str, str] = {}
    for step in history:
        if step.box_no != box_no:
            continue
        if step.direction == "in":
            filled[step.slot] = step.tube
        else:
            filled.pop(step.slot, None)
    return filled


def _grid_order(slot: str) -> tuple[str, int]:
    # Row letter first, then the column as a number, so A2 comes before A10.
    return slot[0], int(slot[1:])


def pick_list_wells(history: list[TubeMove], box_no: int) -> list[str]:
    filled = wells_in_box(history, box_no)
    return sorted(filled, key=_grid_order)
'''

REFERENCE = {"specimenrack/tubelog.py": TUBELOG_REF, "specimenrack/racking.py": RACKING_REF}

TRAP_SOLUTION = {"specimenrack/racking.py": r'''"""What each freezer box holds once the log is replayed. See docs/freezer.md."""

from __future__ import annotations

from .tubelog import TubeMove


def wells_in_box(history: list[TubeMove], box_no: int) -> dict[str, str]:
    filled: dict[str, str] = {}
    for m in history:
        if m.box_no == box_no:
            if m.direction == "in":
                filled[m.slot] = m.tube
            else:
                filled.pop(m.slot, None)
    return filled


def pick_list_wells(history: list[TubeMove], box_no: int) -> list[str]:
    filled = wells_in_box(history, box_no)
    return sorted(filled)
'''}

TRAP_PATTERNS = (r'\bsorted\((?![^)]*\bkey\s*=)(?![^)]*\berr)', r'\.sort\(\s*\)')
