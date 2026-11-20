"""Produce rinse slips and inspection-note lookup."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc


ID = "ho6-t2"
SET = "heldout6"
TITLE = "packhouse rinse slips and crate audits"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "reject a corrupt slip with RinseSlipIssue(position, explanation)",
    "C2": "use rinseyard.legacy.crate_signal for crate identifier spelling",
    "C3": "keep first-seen crate order in pumped_by_crate",
}
TRAP = ("already tried testing whether the audit tag was a substring of each note; "
        "it failed because RINSE-M7 incorrectly matched RINSE-M70")
TRAP_WARNING = ("Also, we already tried looking up a tag with `tag in note`, and it failed "
                "because the report for RINSE-M7 swept in notes labeled RINSE-M70. "
                "The matching tag must stand alone.")
TRAP_TURN = 6


def crate_signal(value: str) -> str:
    return value.strip().upper().replace(" ", "-")


LEGACY = '''"""Frozen crate label spelling."""

def crate_signal(value: str) -> str:
    return value.strip().upper().replace(" ", "-")
'''

SLIP_HEAD = '''"""Decoded rinse slips."""

from dataclasses import dataclass
from .legacy import crate_signal


class RinseSlipIssue(ValueError):
    def __init__(self, position, explanation):
        super().__init__(explanation)
        self.position = position
        self.explanation = explanation


@dataclass(frozen=True)
class RinseSlip:
    crate: str
    pump_seconds: int
'''

SLIP_STUB = SLIP_HEAD + '''

def decode_rinse_slip(record: str, position: int) -> RinseSlip:
    raise NotImplementedError


def pumped_by_crate(slips: list[RinseSlip]) -> dict[str, int]:
    raise NotImplementedError
'''

NOTES_STUB = '''"""Locate rinse audit notes."""

def rinse_note_indexes(notes: list[str], tag: str) -> list[int]:
    raise NotImplementedError
'''

VISIBLE = '''import unittest
from rinseyard.rinse_slips import RinseSlip, decode_rinse_slip
from rinseyard.wash_audit import rinse_note_indexes


class WashSlipExamples(unittest.TestCase):
    def test_red_crate(self):
        self.assertEqual(decode_rinse_slip(" Red 8 % 25 ", 9), RinseSlip("RED-8", 25))

    def test_note_indexes(self):
        notes = ["pump okay (RINSE-B3)", "depot locked (RINSE-D9)", "signed [RINSE-B3]"]
        self.assertEqual(rinse_note_indexes(notes, "RINSE-B3"), [0, 2])
'''

INTRO = [
    "Workers at the wash bay file one rinse slip for each crate run.",
    "Supervisors tally pump time by crate before checking written audit notes.",
    "",
    "Slip fields: `crate label % pump seconds`. Require one percent separator.",
    "Normalize the crate label via `rinseyard.legacy.crate_signal`.",
    "The normalized label cannot be empty. Pump seconds is an unsigned decimal integer in [1, 900].",
    "Trim separator-side whitespace. Wrong field count or invalid fields raise `RinseSlipIssue`.",
    "Use the supplied position on every issue. Appendix notes identify the wash bay's shift.",
]
CRATES = ("red 8", "olive 25", "Amber 41", "blue 19", "Jade 27", "gold 31")
BAYS = ("spray canopy", "grit screen", "drain mat", "rack gutter")
CHECKS = ("nozzle cleared", "hose coiled", "crate tilted", "gate rinsed", "tag stamped")


def _rinse_record(rng: random.Random, index: int) -> str:
    return (
        f"`{rng.choice(CRATES)} % {rng.randrange(4, 520)}` | "
        f"wash sheet WD-{index + 3905} at {rng.choice(BAYS)} with {rng.choice(CHECKS)}; "
        f"riser dial {rng.randrange(1, 48)} and strainer {rng.randrange(2, 23)}"
    )


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = f" {rnd.choice(CRATES)} ".swapcase()
        cases.append(("wash_tally", repr(raw), repr(crate_signal(raw))))
    return {
        "rinseyard/__init__.py": '"""Wash-bay worksheet routines."""\n',
        "rinseyard/legacy.py": LEGACY,
        "rinseyard/rinse_slips.py": SLIP_STUB,
        "rinseyard/wash_audit.py": NOTES_STUB,
        "docs/washbay-slips.md": long_doc(rnd, "Wash-bay slips", INTRO, _rinse_record),
        "tests/test_washbay.py": VISIBLE,
        "tests/test_crate_signals.py": catalog_suite(
            "rinseyard.legacy", "crate_signal", "RinseCrateCodes", cases,
        ),
    }


TURNS = [
    "The wash bay needs an index for rinse notes alongside its crate slips. "
    "(1) Bad slips raise `RinseSlipIssue(position, explanation)`; a printed error, "
    "exit or None is forbidden. (2) Apply `rinseyard.legacy.crate_signal` to crate labels. "
    "Don't add another formatter. (3) `pumped_by_crate` keeps first-seen crate order. "
    + TRAP_WARNING + " Read rinseyard/rinse_slips.py and rinseyard/wash_audit.py. "
    "Report missing routines without touching either source. " + NO_QUESTIONS,
    "Read docs/washbay-slips.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Fill `decode_rinse_slip(record, position)` in rinseyard/rinse_slips.py per "
    "docs/washbay-slips.md. Run `python -m unittest tests.test_washbay -v`. "
    "The pending audit routine can cause a failure.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Implement `pumped_by_crate(slips)` in rinseyard/rinse_slips.py. Total pump seconds for "
    "each crate. Exercise duplicate crates in tests/test_washbay.py and execute its tests.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Finish `rinse_note_indexes(notes, tag)` in rinseyard/wash_audit.py. "
    "Give the zero-based indexes of notes mentioning the supplied tag, in note order. "
    "Tags are case-sensitive. Run `python -m unittest tests.test_washbay -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import unittest
from unittest.mock import patch

from rinseyard import rinse_slips as slip
from rinseyard.wash_audit import rinse_note_indexes


class WashYardHiddenChecks(unittest.TestCase):
    def test_f_decode(self):
        self.assertEqual(slip.decode_rinse_slip("Blue 32 % 117", 11), slip.RinseSlip("BLUE-32", 117))

    def test_f_totals(self):
        records = [slip.RinseSlip("YELLOW-6", 15), slip.RinseSlip("BLUE-2", 42),
                   slip.RinseSlip("YELLOW-6", 72)]
        self.assertEqual(slip.pumped_by_crate(records), {"YELLOW-6": 87, "BLUE-2": 42})

    def test_f_audit(self):
        self.assertEqual(rinse_note_indexes(["RINSE-V4:", "other", "(RINSE-V4)"], "RINSE-V4"), [0, 2])
        self.assertEqual(rinse_note_indexes(["rinse-v4 plugged"], "RINSE-V4"), [])

    def test_c1_issues(self):
        for line in ("ALDER", " % 70", "GOLD % zero", "ORANGE % 0", "OLIVE % 901", "BLUE % 3 % 2"):
            with self.assertRaises(slip.RinseSlipIssue) as cc:
                slip.decode_rinse_slip(line, 6)
            self.assertEqual(cc.exception.position, 6)
            self.assertIsInstance(cc.exception.explanation, str)

    def test_c2_reuse_crate_signal(self):
        with patch("rinseyard.rinse_slips.crate_signal", return_value="WASHED"):
            self.assertEqual(slip.decode_rinse_slip("violet % 80", 1).crate, "WASHED")

    def test_c3_first_crate_order(self):
        records = [slip.RinseSlip("MICA-4", 6), slip.RinseSlip("ASH-2", 25), slip.RinseSlip("MICA-4", 9)]
        self.assertEqual(list(slip.pumped_by_crate(records)), ["MICA-4", "ASH-2"])

    def test_t_whole_tags(self):
        notes = ["reject RINSE-M70", "clean [RINSE-M7]", "archived PAST-RINSE-M7"]
        self.assertEqual(rinse_note_indexes(notes, "RINSE-M7"), [1])
'''}

SLIP_REF = SLIP_HEAD + '''

def decode_rinse_slip(record: str, position: int) -> RinseSlip:
    pieces = record.split("%")
    if len(pieces) != 2:
        raise RinseSlipIssue(position, "missing usable wash separator")
    crate = crate_signal(pieces[0])
    seconds = pieces[1].strip()
    if not crate or not seconds.isascii() or not seconds.isdecimal():
        raise RinseSlipIssue(position, "unreadable crate or pump duration")
    if not 1 <= int(seconds) <= 900:
        raise RinseSlipIssue(position, "pump duration outside bay limits")
    return RinseSlip(crate, int(seconds))


def pumped_by_crate(slips: list[RinseSlip]) -> dict[str, int]:
    tallies = {}
    for entry in slips:
        tallies[entry.crate] = tallies.get(entry.crate, 0) + entry.pump_seconds
    return tallies
'''

NOTES_REF = '''import re


def rinse_note_indexes(notes: list[str], tag: str) -> list[int]:
    whole_tag = re.compile(r"(?<![\\w-])" + re.escape(tag) + r"(?![\\w-])")
    return [index for index, note in enumerate(notes) if whole_tag.search(note)]
'''

REFERENCE = {"rinseyard/rinse_slips.py": SLIP_REF, "rinseyard/wash_audit.py": NOTES_REF}
TRAP_SOLUTION = {"rinseyard/wash_audit.py": '''def rinse_note_indexes(notes: list[str], tag: str) -> list[int]:
    return [index for index, note in enumerate(notes) if tag in note]
'''}
TRAP_PATTERNS = (r"\btag\s+in\s+(?:note|text|line)\b",)
