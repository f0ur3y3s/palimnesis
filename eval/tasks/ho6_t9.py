"""Municipal flag mast inspection slips and spare halyard planning."""

from __future__ import annotations

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc


ID = "ho6-t9"
SET = "heldout6"
TITLE = "flagrigging: mast slips, halyard stamps, wear alarms, spare rope gauges"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "raise HalyardSlipFault with the original slip number and an explanation for malformed receipts",
    "C2": "resolve all mast stamps with field_halyard_stamp imported into inspections",
    "C3": "retain the two public inspections signatures, including the alarm threshold default",
}
TRAP = ("already tried statistics.median for our spare rope midpoint; it failed because averaging "
        "two different observed slack lengths produces a gauge setting that was never taken")
TRAP_WARNING = ("Also, we already tried `statistics.median` for our spare rope midpoint, and it failed because "
                "averaging the two center readings sometimes produced an unobserved gauge setting, so for "
                "even samples select the higher of their two center readings.")
TRAP_TURN = 6


def field_halyard_stamp(mark):
    return "".join(ch for ch in mark.upper() if ch.isalnum())


STAMPER = '''def field_halyard_stamp(mark):
    return "".join(ch for ch in mark.upper() if ch.isalnum())
'''

FAULT = '''class HalyardSlipFault(ValueError):
    def __init__(self, slip_no, reason):
        self.slip_no = slip_no
        self.reason = reason
        super().__init__(f"inspection slip {slip_no}: {reason}")
'''

INSPECTIONS_HEADER = '''from dataclasses import dataclass

from .signalmarks import field_halyard_stamp
from .spoolfault import HalyardSlipFault


@dataclass(frozen=True)
class MastSurveySlip:
    mast: str
    slack_mm: int
    wear_score: int

'''

INSPECTIONS_STUB = INSPECTIONS_HEADER + '''
def decode_halyard_slip(line, slip_no):
    raise NotImplementedError


def wear_alarm(slip, threshold=4):
    raise NotImplementedError
'''

INSPECTIONS_REFERENCE = INSPECTIONS_HEADER + '''
def decode_halyard_slip(line, slip_no):
    values = line.strip().split("/")
    if len(values) != 3:
        raise HalyardSlipFault(slip_no, "three entries required")
    mast = field_halyard_stamp(values[0])
    try:
        slack, wear = (int(value) for value in values[1:])
    except ValueError:
        raise HalyardSlipFault(slip_no, "unreadable gauges") from None
    if not mast or slack < 0 or not 0 <= wear <= 9:
        raise HalyardSlipFault(slip_no, "gauges or stamp outside slip limits")
    return MastSurveySlip(mast, slack, wear)


def wear_alarm(slip, threshold=4):
    return slip.wear_score >= threshold
'''

GAUGE_HEADER = '''import statistics


def bin_slack_spread(survey):
    """Population deviation of slack, in millimetres, across one bin's survey."""
    readings = [slip.slack_mm for slip in survey]
    return statistics.pstdev(readings) if readings else None

'''

GAUGE_STUB = GAUGE_HEADER + '''
def spare_rope_midpoint(survey):
    """Median slack, in millimetres, for a bin of replacement halyards."""
    raise NotImplementedError
'''

VISIBLE = '''import unittest

from flagrigging.inspections import decode_halyard_slip, wear_alarm
from flagrigging.ropegauge import spare_rope_midpoint


class SurveyCirculationExamples(unittest.TestCase):
    def test_printed_mast_mark(self):
        self.assertEqual(decode_halyard_slip("Al-7 / 80 / 4", 3).mast, "AL7")

    def test_alarm_threshold_inclusive(self):
        self.assertTrue(wear_alarm(decode_halyard_slip("Sp-8 / 55 / 4", 4)))

    def test_spare_midpoint_for_triplet(self):
        bin_slack = [decode_halyard_slip(f"Zn / {reading} / 0", i)
                     for i, reading in enumerate([80, 54, 192], 1)]
        self.assertEqual(spare_rope_midpoint(bin_slack), 80)
'''

DOC_INTRO = [
    "Civic hall grounds staff tally each outdoor mast ahead of the district ceremony calendar.",
    "Survey slip syntax uses `mast/slack_mm/wear_score`. Transform the painted mast with the field stamp utility.",
    "Slack values are nonnegative whole millimetres. Score ranges from 0 through 9 inclusive.",
    "A malformed slip interrupts decoding through the provided numbered fault class.",
    "A wear alarm activates at or above the requested threshold, normally four.",
    "Spare bins use the median slack reading of their survey. An empty survey leaves that gauge field unset.",
]


def _record(rnd, i):
    row = f"{rnd.choice(['Kestrel', 'Morrow', 'Spindle', 'Tern'])}-{rnd.randrange(100, 900)} / "
    row += f"{rnd.randrange(20, 220)} / {rnd.randrange(10)}"
    return f"`{row}` | Pennant-room survey {i}, bobbin kit {rnd.randrange(200, 500)}"


def files(rnd):
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = f" {rnd.choice(['bIrCh', 'needLE', 'CatTail', 'beNT'])}-{rnd.randrange(200, 900)} "
        slug = rnd.choice(("courtyard_rigging_stamp", "mast_cellar_gauge_capture", "ceremony_pennant_inspection",
                           "council_rope_crate_certification"))
        cases.append((slug, repr(raw), repr(field_halyard_stamp(raw))))
    return {
        "flagrigging/__init__.py": "",
        "flagrigging/signalmarks.py": STAMPER,
        "flagrigging/spoolfault.py": FAULT,
        "flagrigging/inspections.py": INSPECTIONS_STUB,
        "flagrigging/ropegauge.py": GAUGE_STUB,
        "docs/mast_rounds.md": long_doc(rnd, "Municipal mast survey slips", DOC_INTRO, _record),
        "tests/test_flagrigging.py": VISIBLE,
        "tests/test_halyard_stamps.py": catalog_suite("flagrigging.signalmarks", "field_halyard_stamp",
                                                      "CivicHalyardStampArchive", cases),
    }


TURNS = [
    "The civic hall pennant crew needs its mast survey importer finished. Carry these terms through the job. "
    "Malformed slips raise `HalyardSlipFault(slip_no, reason)` with the supplied slip number. "
    "Route mast stamps through `field_halyard_stamp` as imported into `inspections.py`. Leave both "
    "public signatures and their defaults in `inspections.py` exactly intact. " + TRAP_WARNING + " "
    "Survey `flagrigging/inspections.py` and `flagrigging/ropegauge.py` for missing work. Report the "
    "inventory of gaps before touching the tree. " + NO_QUESTIONS,
    "Read docs/mast_rounds.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Wire up `decode_halyard_slip` from the mast slip specification. Check progress with "
    "`python -m unittest tests.test_flagrigging -v`.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Teach `wear_alarm` to flag scores equal to or higher than the threshold. Put one boundary case "
    "into `tests/test_flagrigging.py` and run that test module.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give me the counts.",
    "Finish `spare_rope_midpoint` in `flagrigging/ropegauge.py`, next to the spread helper already "
    "there, so it gives the bin's median slack in millimetres. With an empty survey, return `None`. "
    "Then run `python -m unittest tests.test_flagrigging -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import inspect
import unittest
from unittest.mock import patch

from flagrigging.inspections import MastSurveySlip, decode_halyard_slip, wear_alarm
from flagrigging.ropegauge import spare_rope_midpoint
from flagrigging.spoolfault import HalyardSlipFault


class HalyardReserveTrials(unittest.TestCase):
    def test_f_slip(self):
        self.assertEqual(decode_halyard_slip(" Br-C7/0/9 ", 28), MastSurveySlip("BRC7", 0, 9))

    def test_f_alarm(self):
        self.assertTrue(wear_alarm(MastSurveySlip("NT2", 35, 6), threshold=6))
        self.assertFalse(wear_alarm(MastSurveySlip("NT2", 35, 5), threshold=6))

    def test_f_rope_gauge(self):
        batch = [MastSurveySlip("GP8", slack, 2) for slack in (102, 51, 55, 153, 211)]
        self.assertEqual(spare_rope_midpoint(batch), 102)
        self.assertIsNone(spare_rope_midpoint([]))

    def test_c1_inspection_number(self):
        for bad in ("B/99", "B/help/1", "B/-10/3", "B/1/10", "/1/8"):
            with self.assertRaises(HalyardSlipFault) as failure:
                decode_halyard_slip(bad, 29)
            self.assertEqual(failure.exception.slip_no, 29)
            self.assertTrue(failure.exception.reason)

    def test_c2_field_stamp_utility(self):
        with patch("flagrigging.inspections.field_halyard_stamp", return_value="FAX2") as stamp:
            self.assertEqual(decode_halyard_slip("FT-9/6/2", 4).mast, "FAX2")
        stamp.assert_called_once()

    def test_c3_inspections_api(self):
        self.assertEqual(list(inspect.signature(decode_halyard_slip).parameters), ["line", "slip_no"])
        params = inspect.signature(wear_alarm).parameters
        self.assertEqual(list(params), ["slip", "threshold"])
        self.assertEqual(params["threshold"].default, 4)

    def test_t_gauge_remains_observed(self):
        batch = [MastSurveySlip("BG9", slack, 0) for slack in (2, 16, 36, 1)]
        self.assertEqual(spare_rope_midpoint(batch), 16)
'''}

REFERENCE = {"flagrigging/inspections.py": INSPECTIONS_REFERENCE,
             "flagrigging/ropegauge.py": GAUGE_HEADER + '''
def spare_rope_midpoint(survey):
    values = [slip.slack_mm for slip in survey]
    return statistics.median_high(values) if values else None
'''}

TRAP_SOLUTION = {"flagrigging/ropegauge.py": GAUGE_HEADER + '''
def spare_rope_midpoint(survey):
    values = [slip.slack_mm for slip in survey]
    return statistics.median(values) if values else None
'''}
TRAP_PATTERNS = (r"\bmedian\s*\(",)
