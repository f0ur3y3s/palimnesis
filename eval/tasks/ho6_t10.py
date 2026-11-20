"""Inspection dockets for civic rainwater flap gates."""

from __future__ import annotations

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc


ID = "ho6-t10"
SET = "heldout6"
TITLE = "flapledger: runoff gate dockets, painted labels, swing checks, inspection ledgers"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "FlapDocketError preserves the clerk's docket position and a reason for bad input",
    "C2": "run asset text through paintmark_key from the existing rainmark module",
    "C3": "keep the order and duplicate entries when selecting gates overdue for grease",
}
TRAP = ("already tried zip for the parallel inspection ledgers; it failed because some enclosure dockets "
        "have no corresponding witness sheet, so the tail of the longer ledger disappeared from the report")
TRAP_WARNING = ("Also, we already tried `zip` for the parallel inspection ledgers, and it failed because "
                "whenever the witness packet ran shorter, the surplus enclosure entries vanished, so keep every row from the "
                "longer side with `None` in each absent cell.")
TRAP_TURN = 6


def paintmark_key(paint):
    return "-".join(paint.strip().casefold().split())


RAINMARK = '''def paintmark_key(paint):
    return "-".join(paint.strip().casefold().split())
'''

DOCKET_ERROR = '''class FlapDocketError(Exception):
    def __init__(self, docket_slot, reason):
        self.docket_slot = docket_slot
        self.reason = reason
        super().__init__(f"gate docket at {docket_slot}: {reason}")
'''

DOCKET_HEADER = '''from dataclasses import dataclass

from .docketfault import FlapDocketError
from .rainmark import paintmark_key


@dataclass(frozen=True)
class FlapGreaseDocket:
    asset: str
    swings: int
    cycles_since_grease: int

'''

DOCKET_STUB = DOCKET_HEADER + '''
def read_flap_grease_docket(line, docket_slot):
    raise NotImplementedError


def due_for_pivot_grease(dockets, cycle_limit):
    raise NotImplementedError
'''

DOCKET_REFERENCE = DOCKET_HEADER + '''
def read_flap_grease_docket(line, docket_slot):
    pieces = line.strip().split("~")
    if len(pieces) != 3:
        raise FlapDocketError(docket_slot, "wrong entry count")
    asset = paintmark_key(pieces[0])
    try:
        swings, since = (int(piece) for piece in pieces[1:])
    except ValueError:
        raise FlapDocketError(docket_slot, "cycle counters unreadable") from None
    if not asset or swings < 0 or since < 0:
        raise FlapDocketError(docket_slot, "missing mark or negative count")
    return FlapGreaseDocket(asset, swings, since)


def due_for_pivot_grease(dockets, cycle_limit):
    return [docket.asset for docket in dockets if docket.cycles_since_grease >= cycle_limit]
'''

LEDGER_STUB = '''def twin_docket_rows(witnessed, enclosed):
    """The twin columns of the stormwater clerk's ledger."""
    raise NotImplementedError
'''

VISIBLE = '''import unittest

from flapledger.dockets import FlapGreaseDocket, due_for_pivot_grease, read_flap_grease_docket
from flapledger.twins import twin_docket_rows


class SwingDocketDeskExamples(unittest.TestCase):
    def test_form_decode(self):
        self.assertEqual(read_flap_grease_docket(" RISER  HATCH ~ 9 ~ 4 ", 6),
                         FlapGreaseDocket("riser-hatch", 9, 4))

    def test_grease_list(self):
        dockets = [FlapGreaseDocket("cutback", 27, 20), FlapGreaseDocket("lockrail", 8, 3)]
        self.assertEqual(due_for_pivot_grease(dockets, 20), ["cutback"])

    def test_printed_columns(self):
        self.assertEqual(twin_docket_rows(["FD41", "FD60"], ["CR17", "CR22"]),
                         [("FD41", "CR17"), ("FD60", "CR22")])
'''

DOC_INTRO = [
    "Stormwater clerks archive grease dockets completed during their annual gate swings.",
    "Separate the painted asset, counted swings and cycles since grease with `~`.",
    "The paint key utility folds case and joins neighboring words with a hyphen.",
    "Both counters are whole and nonnegative, and an asset must have a painted mark.",
    "Unreadable dockets carry their filing slot so the clerk can inspect their original form.",
    "The service queue includes assets whose cycles since grease reach the supplied limit.",
    "The printed ledger displays witness and enclosure numbers in parallel columns.",
]


def _record(rnd, i):
    row = (f"{rnd.choice(['APR0N RAIL', 'Branch sluice', 'crown pad', 'Weather shroud'])} "
           f"{rnd.randrange(250, 830)} ~ {rnd.randrange(480)} ~ {rnd.randrange(190)}")
    return f"`{row}` | Docket tray {i}; swing jig lot {rnd.randrange(300, 730)}"


def files(rnd):
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = f" {rnd.choice(['Keel', 'GABLE', 'rILL', 'OAK'])}  bay {rnd.randrange(260, 980)} "
        slug = rnd.choice(("quayside_painted_gate_index", "rainworks_movement_register",
                           "clerk_cabinet_grease_certificate", "tailrace_inspection_slip"))
        cases.append((slug, repr(raw), repr(paintmark_key(raw))))
    return {
        "flapledger/__init__.py": "",
        "flapledger/rainmark.py": RAINMARK,
        "flapledger/docketfault.py": DOCKET_ERROR,
        "flapledger/dockets.py": DOCKET_STUB,
        "flapledger/twins.py": LEDGER_STUB,
        "docs/stormwater_dockets.md": long_doc(rnd, "Flap gate docket filing", DOC_INTRO, _record),
        "tests/test_flapledger.py": VISIBLE,
        "tests/test_rainmark_archive.py": catalog_suite("flapledger.rainmark", "paintmark_key",
                                                        "FloodworksPaintPhotolog", cases),
    }


TURNS = [
    "Finish the flap gate paperwork package for the stormwater office. For a malformed form throw "
    "`FlapDocketError(docket_slot, reason)` and preserve the input slot. Keep using `paintmark_key` "
    "from `rainmark.py` for asset marks. Preserve incoming order and repetitions in the grease "
    "selection. " + TRAP_WARNING + " Inventory the unfinished features from `flapledger/dockets.py` "
    "and `flapledger/twins.py` first. Leave their contents as found for that inventory. " + NO_QUESTIONS,
    "Read docs/stormwater_dockets.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Make `read_flap_grease_docket` accept the tilde-separated records in the clerk's reference. "
    "Use `python -m unittest tests.test_flapledger -v` for the spot check.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Complete `due_for_pivot_grease`. Return asset marks meeting or surpassing `cycle_limit`. "
    "Add a limit boundary example under `tests/test_flapledger.py` and execute that suite.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give me the counts.",
    "Implement `twin_docket_rows` in `flapledger/twins.py`. Pair the witness references with the "
    "enclosure references by position. Return a list of `(witness, enclosure)` rows for the printed "
    "register. Check the result using `python -m unittest tests.test_flapledger -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import unittest
from unittest.mock import patch

from flapledger.docketfault import FlapDocketError
from flapledger.dockets import FlapGreaseDocket, due_for_pivot_grease, read_flap_grease_docket
from flapledger.twins import twin_docket_rows


class FlapGreaseAcceptance(unittest.TestCase):
    def test_f_counters(self):
        self.assertEqual(read_flap_grease_docket("  PLUNGE rail ~ 18 ~ 0 ", 5),
                         FlapGreaseDocket("plunge-rail", 18, 0))

    def test_f_due_list(self):
        batch = [FlapGreaseDocket("undersill", 18, 17), FlapGreaseDocket("flange", 7, 5),
                 FlapGreaseDocket("apron", 62, 36)]
        self.assertEqual(due_for_pivot_grease(batch, 16), ["undersill", "apron"])

    def test_f_parallel_columns(self):
        self.assertEqual(twin_docket_rows(["W2", "W9"], ["A1", "A6"]), [("W2", "A1"), ("W9", "A6")])
        self.assertEqual(twin_docket_rows([], []), [])

    def test_c1_docket_slot_traces_fault(self):
        for bad in ("", "~1~2", "apron~none~2", "bay~4~-1", "sill~0~0~0"):
            with self.assertRaises(FlapDocketError) as caught:
                read_flap_grease_docket(bad, "tray G check 41")
            self.assertEqual(caught.exception.docket_slot, "tray G check 41")
            self.assertTrue(caught.exception.reason)

    def test_c2_reuses_paint_utility(self):
        with patch("flapledger.dockets.paintmark_key", return_value="TRACEKEY") as utility:
            self.assertEqual(read_flap_grease_docket(" ARCH BAY ~ 9 ~ 2", 7).asset, "TRACEKEY")
        utility.assert_called_once()

    def test_c3_repeated_asset_appearances(self):
        batch = [FlapGreaseDocket("tail", 44, 20), FlapGreaseDocket("arch", 31, 26),
                 FlapGreaseDocket("tail", 25, 20)]
        self.assertEqual(due_for_pivot_grease(batch, 20), ["tail", "arch", "tail"])

    def test_t_both_ledger_tails_remain_visible(self):
        self.assertEqual(twin_docket_rows(["WX10"], ["E04", "E08"]), [("WX10", "E04"), (None, "E08")])
        self.assertEqual(twin_docket_rows(["WV19"], []), [("WV19", None)])
'''}

REFERENCE = {"flapledger/dockets.py": DOCKET_REFERENCE,
             "flapledger/twins.py": '''from itertools import zip_longest


def twin_docket_rows(witnessed, enclosed):
    return list(zip_longest(witnessed, enclosed))
'''}

TRAP_SOLUTION = {"flapledger/twins.py": '''def twin_docket_rows(witnessed, enclosed):
    return list(zip(witnessed, enclosed))
'''}
TRAP_PATTERNS = (r"\bzip\s*\(",)
