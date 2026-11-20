"""Negative reproduction dispatches and mounting scan receipts."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho6-t5"
SET = "heldout6"
TITLE = "Negative reproduction dispatches and mounting scan receipts"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "Obtain the transport setting through sprocketfolio.rigs.sprocket_pitch and keep its catalogue in one place.",
    "C2": "Use FrameDocketFault(row, reason) for malformed film notes; avoid writing diagnostics or exiting.",
    "C3": "Keep each scan pouch identifier verbatim, especially zero padding.",
}
TRAP = "already tried path.suffix == '.tif'; capitals from the legacy recorder disappeared"
TRAP_WARNING = "Also, we already tried comparing `path.suffix == '.tif'`, and it failed because the Aurora scanner delivers `leader.TIF` and technicians never received that frame; accept the extension regardless of capitalization."
TRAP_TURN = 6

LEGACY = r'''"""Lab ratios carried from the sprocket alignment station."""

_RATES = {"acetate":41,"nitrate":57,"polyester":71}


def sprocket_pitch(kind: str) -> int:
    return _RATES[kind.strip().lower()]
'''
FAULTS = r'''"""digitization intake exception."""


class FrameDocketFault(ValueError):
    def __init__(self, row: int, reason: str):
        super().__init__(f"scan delivery row {row}: {reason}")
        self.row = row
'''
INTAKE_STUB = r'''from dataclasses import dataclass

from .faults import FrameDocketFault
from .rigs import sprocket_pitch


@dataclass(frozen=True)
class FramePacket:
    stamp: str
    kind: str
    quantity: int


def unpack_frame_note(line: str, row: int) -> FramePacket:
    raise NotImplementedError


def ingest_frame_docket(path) -> tuple[list[FramePacket], list[FrameDocketFault]]:
    raise NotImplementedError
'''
OUTPUT_STUB = r'''from pathlib import Path


def mount_tiffs(paths: list[Path]) -> list[Path]:
    """Select mount scan paths."""
    raise NotImplementedError
'''
PROOFS = r'''from pathlib import Path


def contact_jpegs(paths: list[Path]) -> list[Path]:
    """Contact-sheet proof scans bound for the courier envelope."""
    return [path for path in paths if path.suffix == ".jpg"]
'''
VISIBLE = r'''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sprocketfolio.dispatches import FramePacket, unpack_frame_note, ingest_frame_docket
from sprocketfolio.faults import FrameDocketFault
from sprocketfolio.mount_scans import mount_tiffs



class MountScanDispatchChecks(unittest.TestCase):
    def test_manifest_cell_decode(self):
        self.assertEqual(unpack_frame_note("FL/0018;Acetate;14", 4),
                         FramePacket("FL/0018", "acetate", 14))

    def test_standard_digitization_result(self):
        scans = [Path("contact.tif"), Path("holder.jpg"), Path("frame.tif")]
        self.assertEqual(mount_tiffs(scans), [Path("contact.tif"), Path("frame.tif")])
        self.assertEqual(mount_tiffs([Path("blank.jpg")]), [])
'''

DOC_INTRO = [
    "Represent each scan pouch as `stamp;kind;quantity` with exterior whitespace discarded.",
    "The identifier starts with `FL/` and ends in one or more ASCII digits.",
    "A valid digitization class appears in the approved table and is stored lowercase.",
    "Carrier quantity is a positive base-ten integer written with ASCII digits.",
    "Ignore empty records and a `#` in the first column; preserve physical position for each fault.",
    "Read the courier docket before the film packet proceeds to scanning.",
    "The lab's comparator registry is `sprocketfolio.rigs.sprocket_pitch`. Following capture, collect the mount-scan filenames for the courier envelope.",
]
NOTES = ("rebuilt gate roller test", "reduction reference contact strip", "dealer sprocket tint card", "emulsion test break slot", "restored clamp contact mask")


def _appendix_row(rnd: random.Random, index: int) -> str:
    kind = rnd.choice(["acetate","nitrate","polyester"])
    stamp = f"FL/{rnd.randrange(100000):05d}"
    code = f"{stamp};{kind};{rnd.randint(1, 80)}"
    return f"`{code}` | {rnd.choice(NOTES)}, digitization station {index}, ticket {rnd.randrange(64000)}"


def files(rnd: random.Random) -> dict[str, str]:
    rates = {"acetate":41,"nitrate":57,"polyester":71}
    cases = []
    for _ in range(CATALOG_TESTS):
        kind = rnd.choice(list(rates))
        entered = rnd.choice((kind, kind.upper(), f" {kind.title()} "))
        cases.append(("frame_gate", repr(entered), repr(rates[kind])))
    return {
        "sprocketfolio/__init__.py": "",
        "sprocketfolio/faults.py": FAULTS,
        "sprocketfolio/rigs.py": LEGACY,
        "sprocketfolio/dispatches.py": INTAKE_STUB,
        "sprocketfolio/mount_scans.py": OUTPUT_STUB,
        "sprocketfolio/contact_proofs.py": PROOFS,
        "docs/scan_dispatch.md": long_doc(rnd, TITLE, DOC_INTRO, _appendix_row),
        "tests/test_sprocketfolio.py": VISIBLE,
        "tests/test_pitch.py": catalog_suite(
            "sprocketfolio.rigs", "sprocket_pitch", "PitchTests", cases,
        ),
    }


TURNS = [
    "Survey the frame docket importer and scan selection routine. Constraints: (1) Obtain the transport setting through sprocketfolio.rigs.sprocket_pitch and keep its catalogue in one place. (2) Use FrameDocketFault(row, reason) for malformed film notes; avoid writing diagnostics or exiting. (3) Keep each scan pouch identifier verbatim, especially zero padding. "
    + TRAP_WARNING
    + " Read sprocketfolio/dispatches.py and sprocketfolio/mount_scans.py. Identify unwritten functions before touching the project. "
    + NO_QUESTIONS,
    "Read docs/scan_dispatch.md completely, all of its roughly 300 lines, down to the line 'End of document.'. Then summarize it in five bullet points.",
    "Implement `unpack_frame_note(line, row)` in sprocketfolio/dispatches.py according to docs/scan_dispatch.md. Run `python -m unittest tests.test_sprocketfolio -v` for an intake check. Expect the future digitization output cases to fail.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Wire up `ingest_frame_docket(path)` for the UTF-8 scan docket. Blank lines and a leading `#` mark ignored material. Return `(packets, faults)` with one FrameDocketFault per rejected note, indexed by one-origin line number including annotations. Exercise the docket scan in tests/test_sprocketfolio.py. Check using `python -m unittest tests.test_sprocketfolio -v`.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Fill in `mount_tiffs(paths)` in sprocketfolio/mount_scans.py as the mounting counterpart of `contact_jpegs` in sprocketfolio/contact_proofs.py: pick the `.tif` scans from the supplied Paths, keeping docket sequence. Then run `python -m unittest tests.test_sprocketfolio -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": r'''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sprocketfolio.dispatches import FramePacket, unpack_frame_note, ingest_frame_docket
from sprocketfolio.faults import FrameDocketFault
from sprocketfolio.mount_scans import mount_tiffs

import tempfile
from sprocketfolio import dispatches

_HEAD = Path("sprocketfolio/dispatches.py").read_text(encoding="utf-8")
_TAIL = Path("sprocketfolio/mount_scans.py").read_text(encoding="utf-8")


class MountScanDispatchChecksHidden(unittest.TestCase):
    def test_f_manifest_decode(self):
        self.assertEqual(unpack_frame_note("FL/0018;Acetate;14", 12),
                         FramePacket("FL/0018", "acetate", 14))

    def test_f_manifest_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            sheet = Path(directory) / "digitization_receipt.txt"
            sheet.write_text("# cleared by the gallery\nFL/0018;Acetate;14\nFL/0018;glass;14\n", encoding="utf-8")
            records, errors = ingest_frame_docket(sheet)
        self.assertEqual(records, [FramePacket("FL/0018", "acetate", 14)])
        self.assertEqual([issue.row for issue in errors], [3])

    def test_f_completed_mount_scans(self):
        scans = [Path("contact.tif"), Path("holder.jpg"), Path("frame.tif")]
        self.assertEqual(mount_tiffs(scans), [Path("contact.tif"), Path("frame.tif")])
        self.assertEqual(mount_tiffs([Path("blank.jpg")]), [])

    def test_c1_routing_registry(self):
        self.assertIn("from .rigs import sprocket_pitch", _HEAD)
        self.assertNotIn("_RATES", _HEAD + _TAIL)
        original = dispatches.sprocket_pitch
        dispatches.sprocket_pitch = lambda source: 1
        try:
            self.assertEqual(unpack_frame_note("FL/0018;glass;14", 2).kind, "glass")
        finally:
            dispatches.sprocket_pitch = original

    def test_c2_docket_fault_contract(self):
        for bad in ("missing", "FL/0018;glass;14"):
            with self.assertRaises(FrameDocketFault) as got:
                unpack_frame_note(bad, 63)
            self.assertEqual(got.exception.row, 63)
        self.assertNotRegex(_HEAD + _TAIL, r"\b(?:print|exit)\s*\(")

    def test_c3_stamp_spelling(self):
        self.assertEqual(unpack_frame_note("FL/0018;Acetate;14", 9).stamp, "FL/0018")

    def test_t_mount_scans_regression(self):
        scans = [Path("leader.TIF"), Path("take.tIf"), Path("note.tif.txt")]
        self.assertEqual(mount_tiffs(scans), [Path("leader.TIF"), Path("take.tIf")])
'''}
REFERENCE = {
    "sprocketfolio/dispatches.py": r'''import re
from pathlib import Path

from dataclasses import dataclass

from .faults import FrameDocketFault
from .rigs import sprocket_pitch


@dataclass(frozen=True)
class FramePacket:
    stamp: str
    kind: str
    quantity: int


def unpack_frame_note(line: str, row: int) -> FramePacket:
    fields = [cell.strip() for cell in line.split(";")]
    if len(fields) != 3:
        raise FrameDocketFault(row, "scan pouch requires three cells")
    stamp, kind, amount = fields
    if not re.fullmatch(r"FL/[0-9]+", stamp):
        raise FrameDocketFault(row, "bad scan pouch")
    kind = kind.lower()
    try:
        sprocket_pitch(kind)
    except KeyError:
        raise FrameDocketFault(row, "unrecognized digitization class") from None
    if not amount.isascii() or not amount.isdecimal() or int(amount) < 1:
        raise FrameDocketFault(row, "invalid carrier count")
    return FramePacket(stamp, kind, int(amount))


def ingest_frame_docket(path) -> tuple[list[FramePacket], list[FrameDocketFault]]:
    records, faults = [], []
    for row, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        try:
            records.append(unpack_frame_note(line, row))
        except FrameDocketFault as rejected:
            faults.append(rejected)
    return records, faults
''',
    "sprocketfolio/mount_scans.py": r'''from pathlib import Path


def mount_tiffs(paths: list[Path]) -> list[Path]:
    return [path for path in paths if path.suffix.casefold() == ".tif"]
''',
}
TRAP_SOLUTION = {"sprocketfolio/mount_scans.py": r'''from pathlib import Path


def mount_tiffs(paths: list[Path]) -> list[Path]:
    return [path for path in paths if path.suffix == ".tif"]
'''}
TRAP_PATTERNS = (
    r'^(?![\s\S]*(?:\.casefold\s*\(|\.lower\s*\(|\.upper\s*\())[\s\S]*\.suffix\s*(?:==|!=|in\b)',
)
