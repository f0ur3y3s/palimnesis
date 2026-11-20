"""Shearing-lot slips and wool dispatch tickets."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc


ID = "ho6-t3"
SET = "heldout6"
TITLE = "shearing lots and wool consignees"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "a rejected clip slip raises ClipSlipFault(slip_number, detail)",
    "C2": "only wooldispatch.legacy.clip_mark normalizes clip marks",
    "C3": "both clip_book public functions preserve parameter names and arity",
}
TRAP = ("already tried cutting each buyer ticket on bare commas; it failed because the "
        "quoted consignee Moor, East is one buyer and was split into two")
TRAP_WARNING = ("Also, we already tried `ticket.split(',')` for the buyer cells, and it "
                "failed because the manifest spells one buyer as \"Moor, East\". "
                "That name was split into two consignees.")
TRAP_TURN = 6


def clip_mark(raw: str) -> str:
    return raw.replace(" ", "").strip().upper()


LEGACY = '''"""Existing stencil spellings for wool clips."""

def clip_mark(raw: str) -> str:
    return raw.replace(" ", "").strip().upper()
'''

CLIP_HEAD = '''"""Wool shed weigh slips."""

from dataclasses import dataclass
from .legacy import clip_mark


class ClipSlipFault(ValueError):
    def __init__(self, slip_number, detail):
        super().__init__(detail)
        self.slip_number = slip_number
        self.detail = detail


@dataclass(frozen=True)
class WoolClip:
    mark: str
    kilograms: int
'''

CLIP_STUB = CLIP_HEAD + '''

def read_wool_clip(line: str, slip_number: int) -> WoolClip:
    raise NotImplementedError


def wool_kg(clips: list[WoolClip], mark: str) -> int:
    raise NotImplementedError
'''

TICKET_STUB = '''"""Read buyer cells from dispatch tickets."""

def consignee_names(ticket: str) -> list[str]:
    raise NotImplementedError
'''

VISIBLE = '''import unittest
from wooldispatch.clip_book import WoolClip, read_wool_clip
from wooldispatch.buyer_cells import consignee_names


class WoolDispatchExamples(unittest.TestCase):
    def test_clip_slip(self):
        self.assertEqual(read_wool_clip(" aw 7 / 68 ", 15), WoolClip("AW7", 68))

    def test_buyer_cells(self):
        self.assertEqual(consignee_names("Red Shed, Walling Co, Upland"), ["Red Shed", "Walling Co", "Upland"])
'''

INTRO = [
    "At the press the shed clerk weighs each packed clip and records its stencil mark.",
    "The dispatch office pools wool weights by stencil mark, with separate buyer tickets.",
    "",
    "Read `mark / kilograms` with exactly one slash. Strip both cells.",
    "Apply `wooldispatch.legacy.clip_mark`; reject a blank mark.",
    "The press accepts integer weights in 1–240 kg.",
    "Situate `ClipSlipFault` at the requested slip number for any rejected slip.",
    "",
    "Each archived slip names its press bay and the labeler's observation.",
]
STENCILS = ("aw 7", "M1 N", " rk 32", " he 13 ", "CS 56", "DF 81")
PRESS_BAYS = ("north rack", "scale plank", "bag stand", "dispatch skid")
HANDLERS = ("pressed dry", "stitched twice", "tied corner", "marked clean", "fleece card set")


def _clip_record(rng: random.Random, index: int) -> str:
    return (
        f"`{rng.choice(STENCILS)} / {rng.randrange(40, 241)}` | "
        f"press tag WO-{index + 4501} from {rng.choice(PRESS_BAYS)}, {rng.choice(HANDLERS)}; "
        f"seam tally {rng.randrange(2, 9)} and stencil tray {rng.randrange(5, 28)}"
    )


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = f" {rnd.choice(STENCILS)} ".lower()
        cases.append(("clip_press", repr(raw), repr(clip_mark(raw))))
    return {
        "wooldispatch/__init__.py": '"""Wool-clip dispatch package."""\n',
        "wooldispatch/legacy.py": LEGACY,
        "wooldispatch/clip_book.py": CLIP_STUB,
        "wooldispatch/buyer_cells.py": TICKET_STUB,
        "docs/wool-press.md": long_doc(rnd, "Wool press slips", INTRO, _clip_record),
        "tests/test_dispatch_book.py": VISIBLE,
        "tests/test_clip_stencils.py": catalog_suite(
            "wooldispatch.legacy", "clip_mark", "WoolStencilChecks", cases,
        ),
    }


TURNS = [
    "Implement weigh slips and buyer cells for the wool shed. "
    "(1) Corrupt slips raise `ClipSlipFault(slip_number, detail)`; no prints or sentinels, "
    "and no process exit. (2) Normalize clip marks exclusively with `wooldispatch.legacy.clip_mark`."
    " (3) Keep existing public parameter names and arity in wooldispatch/clip_book.py. "
    + TRAP_WARNING + " Read wooldispatch/clip_book.py and wooldispatch/buyer_cells.py, "
    "and inventory their stubs. Inspection only. " + NO_QUESTIONS,
    "Read docs/wool-press.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Define `read_wool_clip(line, slip_number)` in wooldispatch/clip_book.py according to "
    "docs/wool-press.md. Run `python -m unittest tests.test_dispatch_book -v`. "
    "Buyer cells are still unfinished.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Complete `wool_kg(clips, mark)` in wooldispatch/clip_book.py. Sum weights for the "
    "normalized stencil mark, defaulting to zero. Extend "
    "tests/test_dispatch_book.py with a dispatch tally test and run it.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Implement `consignee_names(ticket)` in wooldispatch/buyer_cells.py. "
    "Read comma-delimited buyer cells. Return the buyer names in manifest order with "
    "outer whitespace stripped. "
    "Execute `python -m unittest tests.test_dispatch_book -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import inspect
import unittest

from wooldispatch import clip_book as book
from wooldispatch.buyer_cells import consignee_names


class WoolShedHiddenChecks(unittest.TestCase):
    def test_f_weigh_slip(self):
        self.assertEqual(book.read_wool_clip(" dm 14 / 169 ", 6), book.WoolClip("DM14", 169))

    def test_f_kg(self):
        tags = [book.WoolClip("UF1", 45), book.WoolClip("DE5", 40), book.WoolClip("UF1", 39)]
        self.assertEqual(book.wool_kg(tags, " uf 1 "), 84)
        self.assertEqual(book.wool_kg(tags, "NG24"), 0)

    def test_f_names(self):
        self.assertEqual(consignee_names(" East Skid, Reed Co , West Yard "),
                         ["East Skid", "Reed Co", "West Yard"])

    def test_c1_fault_location(self):
        for line in ("", " / 80", "GA8 / nan", "GA8 / 0", "GA8 / 241", "GA8 / 9 / 4"):
            with self.assertRaises(book.ClipSlipFault) as cc:
                book.read_wool_clip(line, 21)
            self.assertEqual(cc.exception.slip_number, 21)
            self.assertIsInstance(cc.exception.detail, str)

    def test_c2_stencil_normalization(self):
        self.assertIn("clip_mark(", inspect.getsource(book.read_wool_clip))
        self.assertIn("clip_mark(", inspect.getsource(book.wool_kg))

    def test_c3_keep_parameters(self):
        self.assertEqual(list(inspect.signature(book.read_wool_clip).parameters), ["line", "slip_number"])
        self.assertEqual(list(inspect.signature(book.wool_kg).parameters), ["clips", "mark"])

    def test_t_combined_buyer_name(self):
        self.assertEqual(consignee_names('"Moor, East", Daley, "Toll, New"'),
                         ["Moor, East", "Daley", "Toll, New"])
'''}

CLIP_REF = CLIP_HEAD + '''

def read_wool_clip(line: str, slip_number: int) -> WoolClip:
    parts = line.split("/")
    if len(parts) != 2:
        raise ClipSlipFault(slip_number, "slash separator missing or repeated")
    mark = clip_mark(parts[0])
    kilos = parts[1].strip()
    if not mark or not kilos.isascii() or not kilos.isdecimal():
        raise ClipSlipFault(slip_number, "unreadable clip stamp or weight")
    if not 1 <= int(kilos) <= 240:
        raise ClipSlipFault(slip_number, "clip exceeds press limits")
    return WoolClip(mark, int(kilos))


def wool_kg(clips: list[WoolClip], mark: str) -> int:
    wanted = clip_mark(mark)
    return sum(clip.kilograms for clip in clips if clip.mark == wanted)
'''

TICKET_REF = '''import csv


def consignee_names(ticket: str) -> list[str]:
    cells = next(csv.reader([ticket], skipinitialspace=True))
    return [cell.strip() for cell in cells]
'''

REFERENCE = {"wooldispatch/clip_book.py": CLIP_REF, "wooldispatch/buyer_cells.py": TICKET_REF}
TRAP_SOLUTION = {"wooldispatch/buyer_cells.py": '''def consignee_names(ticket: str) -> list[str]:
    return [cell.strip() for cell in ticket.split(",")]
'''}
TRAP_PATTERNS = (r"\b(?:ticket|text|manifest)\.split\(",)
