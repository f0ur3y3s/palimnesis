"""Meter cards for potting-media batching."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc


ID = "ho6-t1"
SET = "heldout6"
TITLE = "substrate metering cards"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "bad cards raise MediaCardFault(card_no, reason) without stdout or sentinel values",
    "C2": "normalize media codes only with substratebench.legacy.media_bin_code",
    "C3": "preserve the input list in meter_totals",
}
TRAP = ("already tried round(litres, 1); it failed because the batch printer must send "
        "exact half-tenths upward, including 2.25 L, which prints 2.3 L")
TRAP_WARNING = ("Also, we already tried `round(litres, 1)` for metering labels, and it failed "
                "because the supplier requires half-tenths upward: 2.25 L came out as 2.2 "
                "instead of 2.3 L.")
TRAP_TURN = 6


def media_bin_code(raw):
    return "-".join(raw.casefold().replace("_", " ").split())


LEGACY = '''"""Keep the meter's existing media-bin spelling."""

def media_bin_code(raw):
    return "-".join(raw.casefold().replace("_", " ").split())
'''

METER_HEAD = '''"""Potting-media meter cards."""

from dataclasses import dataclass
from .legacy import media_bin_code


class MediaCardFault(ValueError):
    def __init__(self, card_no, reason):
        super().__init__(reason)
        self.card_no = card_no
        self.reason = reason


@dataclass(frozen=True)
class MediaMeterCard:
    bin_code: str
    litres: float
'''

METER_STUB = METER_HEAD + '''

def parse_meter_card(raw: str, card_no: int) -> MediaMeterCard:
    raise NotImplementedError


def meter_totals(cards: list[MediaMeterCard]) -> dict[str, float]:
    raise NotImplementedError
'''

LABEL_STUB = '''"""Format labels for media totes."""

def tote_volume_label(bin_code: str, litres: float) -> str:
    raise NotImplementedError
'''

VISIBLE = '''import unittest
from substratebench.metercards import MediaMeterCard, parse_meter_card
from substratebench.tote_labels import tote_volume_label


class MeterCardExamples(unittest.TestCase):
    def test_peat_card(self):
        self.assertEqual(parse_meter_card(" DARK_ Peat : 12.4 ", 8),
                         MediaMeterCard("dark-peat", 12.4))

    def test_tote_label(self):
        self.assertEqual(tote_volume_label("dry-coir", 3.17), "dry-coir 3.2 L")
        self.assertEqual(tote_volume_label("washed-grit", 8), "washed-grit 8.0 L")
'''

INTRO = [
    "By the potting bench, the mixer operator transcribes each meter draw onto a card.",
    "The trolley marshal creates a tote label from the accumulated draw volume.",
    "",
    "A meter card is `bin_code : litres`. Require exactly one colon.",
    "Trim surrounding spaces. A normalized bin code cannot be empty.",
    "Pass bin codes through `substratebench.legacy.media_bin_code`.",
    "The volume is a finite decimal float, zero or above. Retain its unformatted value.",
    "Invalid cards raise `MediaCardFault` with the caller-supplied number and a text reason.",
    "Meter examples excerpt the queued tickets and the mixer's shift notes.",
]
BINS = ("Dark Peat", "washed_grit", " bark fines ", "dry coir", "Screened Leaf Mould")
SHIFTS = ("north potting", "west propagation", "seedling trial", "shade tunnel")
NOTES = ("bench swept", "hopper cleared", "grit screened", "liner replaced", "drawing paused")


def _card_record(rng: random.Random, index: int) -> str:
    return (
        f"`{rng.choice(BINS)} : {rng.uniform(1.5, 48):.3f}` | "
        f"{rng.choice(SHIFTS)} ticket ME-{index + 1870}: {rng.choice(NOTES)}; "
        f"trolley wheel count {rng.randrange(14, 88)} and cover clips {rng.randrange(2, 9)}"
    )


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = rnd.choice(BINS).swapcase() if rnd.random() < 0.3 else rnd.choice(BINS)
        cases.append(("meter_rack", repr(raw), repr(media_bin_code(raw))))
    return {
        "substratebench/__init__.py": '"""Media mixing records."""\n',
        "substratebench/legacy.py": LEGACY,
        "substratebench/metercards.py": METER_STUB,
        "substratebench/tote_labels.py": LABEL_STUB,
        "docs/mixer-draws.md": long_doc(rnd, "Mixer draws", INTRO, _card_record),
        "tests/test_meter_cards.py": VISIBLE,
        "tests/test_substrate_spellings.py": catalog_suite(
            "substratebench.legacy", "media_bin_code", "MediaSpellingChecks", cases,
        ),
    }


TURNS = [
    "The potting bench needs Python routines for meter cards and tote labels. "
    "(1) Raise `MediaCardFault(card_no, reason)` for invalid cards; don't print or return "
    "a sentinel. (2) Route all bin-code normalization through "
    "`substratebench.legacy.media_bin_code`. (3) `meter_totals` must leave its list argument "
    "intact including order. " + TRAP_WARNING + " Inspect substratebench/metercards.py and "
    "substratebench/tote_labels.py for unfinished routines. Report those routines without edits. "
    + NO_QUESTIONS,
    "Read docs/mixer-draws.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Implement `parse_meter_card(raw, card_no)` in substratebench/metercards.py, using "
    "docs/mixer-draws.md. Execute `python -m unittest tests.test_meter_cards -v`. "
    "Tote-label checks remain pending.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Add `meter_totals(cards)` to substratebench/metercards.py. Return per-bin volume sums "
    "keyed by bin code. Add a repeated-bin test in tests/test_meter_cards.py and execute it.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Finish `tote_volume_label(bin_code, litres)` in substratebench/tote_labels.py. "
    "Produce `<bin_code> <litres> L` with exactly one decimal digit for the volume. "
    "Execute `python -m unittest tests.test_meter_cards -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import inspect
import unittest

from substratebench import metercards as meter
from substratebench.tote_labels import tote_volume_label


class MediaBenchHiddenChecks(unittest.TestCase):
    def test_f_draw(self):
        self.assertEqual(meter.parse_meter_card("DARK__PEAT : 5.75", 4),
                         meter.MediaMeterCard("dark-peat", 5.75))

    def test_f_sums(self):
        cards = [meter.MediaMeterCard("grit", 3.25), meter.MediaMeterCard("coir", 5),
                 meter.MediaMeterCard("grit", 0.75)]
        self.assertEqual(meter.meter_totals(cards), {"grit": 4, "coir": 5})

    def test_f_non_tie(self):
        self.assertEqual(tote_volume_label("dry-peat", 17.83), "dry-peat 17.8 L")
        self.assertEqual(tote_volume_label("clay-grit", 2.68), "clay-grit 2.7 L")

    def test_c1_invalid_cards(self):
        for bad in ("", " : 1", "sand : nan", "sand : inf", "sand : -2", "sand : 1 : 2"):
            with self.assertRaises(meter.MediaCardFault) as cc:
                meter.parse_meter_card(bad, 32)
            self.assertEqual(cc.exception.card_no, 32)
            self.assertIsInstance(cc.exception.reason, str)

    def test_c2_legacy_reuse(self):
        self.assertIn("media_bin_code(", inspect.getsource(meter.parse_meter_card))

    def test_c3_input_list(self):
        cards = [meter.MediaMeterCard("peat", 3), meter.MediaMeterCard("bark", 5)]
        initial = cards[:]
        meter.meter_totals(cards)
        self.assertEqual(cards, initial)

    def test_t_half_tenths(self):
        self.assertEqual(tote_volume_label("peat-lane", 2.25), "peat-lane 2.3 L")
        self.assertEqual(tote_volume_label("bark-lane", 2.65), "bark-lane 2.7 L")
'''}

METER_REF = METER_HEAD + '''

def parse_meter_card(raw: str, card_no: int) -> MediaMeterCard:
    from math import isfinite

    fields = raw.split(":")
    if len(fields) != 2:
        raise MediaCardFault(card_no, "use a single card separator")
    bin_code = media_bin_code(fields[0])
    if not bin_code:
        raise MediaCardFault(card_no, "meter bin missing")
    try:
        litres = float(fields[1].strip())
    except ValueError as exc:
        raise MediaCardFault(card_no, "unreadable draw volume") from exc
    if not isfinite(litres) or litres < 0:
        raise MediaCardFault(card_no, "draw must be finite and nonnegative")
    return MediaMeterCard(bin_code, litres)


def meter_totals(cards: list[MediaMeterCard]) -> dict[str, float]:
    totals = {}
    for card in cards:
        totals[card.bin_code] = totals.get(card.bin_code, 0.0) + card.litres
    return totals
'''

LABEL_REF = '''from decimal import Decimal, ROUND_HALF_UP


def tote_volume_label(bin_code: str, litres: float) -> str:
    printed = Decimal(str(litres)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{bin_code} {printed:.1f} L"
'''

REFERENCE = {"substratebench/metercards.py": METER_REF, "substratebench/tote_labels.py": LABEL_REF}
TRAP_SOLUTION = {"substratebench/tote_labels.py": '''def tote_volume_label(bin_code: str, litres: float) -> str:
    printed = round(litres, 1)
    return f"{bin_code} {printed:.1f} L"
'''}
TRAP_PATTERNS = (
    r"\bround\(\s*litres\s*,\s*1\b",
    r"\{\s*litres\s*:[^{}\n]*\}",
    r"\.format\([^()\n]*\blitres\b",
)
