"""Documented refuse rounds become dispatch slips and weighbridge tallies."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t17"
SET = "heldout5"
TITLE = "binround: crew lift logs, weighbridge tonnages, bins per street, trips to the tip"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "reject unusable lifts with LiftError(line_no, message) and no output or exit",
    "C2": "binround.legacy.weighbridge_tonnes is the sole scale interpreter",
    "C3": "street totals follow first appearances on the lift pad",
}
TRAP = ("already tried float(tonnes) for incremental truck loads; it failed because binary "
        "arithmetic yielded 0.6000000000000001 for 0.1 + 0.2 + 0.3, causing a needless dump run")
TRAP_WARNING = ("Also, we already tried accumulating truck loads with `float(tonnes)`, and it failed because "
                "lifts of 0.1, 0.2 and 0.3 on one 0.6-tonne truck summed in binary to "
                "0.6000000000000001 and wrongly pushed the third load onto another dump run.")
TRAP_TURN = 6


def weighbridge_tonnes(raw: str) -> str:
    s = raw.strip().lower().replace(" ", "").replace(",", ".")
    if s.endswith("kg"):
        digits = s[:-2]
        if not (digits.isascii() and digits.isdigit()):
            raise ValueError(f"bad weight {raw!r}")
        kilos = int(digits)
    else:
        if s.endswith("t"):
            s = s[:-1]
        whole, _, frac = s.partition(".")
        if not (whole.isascii() and whole.isdigit()) or len(frac) > 3 or \
                (frac and not (frac.isascii() and frac.isdigit())):
            raise ValueError(f"bad weight {raw!r}")
        kilos = int(whole) * 1000 + int((frac + "000")[:3])
    if kilos <= 0:
        raise ValueError(f"bad weight {raw!r}")
    return f"{kilos // 1000}.{kilos % 1000:03d}"


LEGACY = '''"""Weights as the depot weighbridge ticket states them, in tonnes with three decimals.
Shared with the depot's billing scripts (do not change)."""


def weighbridge_tonnes(raw: str) -> str:
    s = raw.strip().lower().replace(" ", "").replace(",", ".")
    if s.endswith("kg"):
        digits = s[:-2]
        if not (digits.isascii() and digits.isdigit()):
            raise ValueError(f"bad weight {raw!r}")
        kilos = int(digits)
    else:
        if s.endswith("t"):
            s = s[:-1]
        whole, _, frac = s.partition(".")
        if not (whole.isascii() and whole.isdigit()) or len(frac) > 3 or \\
                (frac and not (frac.isascii() and frac.isdigit())):
            raise ValueError(f"bad weight {raw!r}")
        kilos = int(whole) * 1000 + int((frac + "000")[:3])
    if kilos <= 0:
        raise ValueError(f"bad weight {raw!r}")
    return f"{kilos // 1000}.{kilos % 1000:03d}"
'''

ERRORS = '''"""Errors raised while reading a crew's lift log."""


class LiftError(ValueError):
    """A log line that cannot be used; ``line_no`` is its 1-based position in the log."""

    def __init__(self, line_no: int, message: str):
        super().__init__(f"log line {line_no}: {message}")
        self.line_no = line_no
        self.message = message
'''

LIFTS_STUB = '''"""The crew's lift log. See docs/lift_log.md."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import LiftError
from .legacy import weighbridge_tonnes


@dataclass(frozen=True)
class StreetLift:
    street: str
    bins: int
    tonnes: str


def parse_crew_line(line: str, line_no: int) -> StreetLift:
    """One log line ``street|bins|weight`` -> StreetLift."""
    raise NotImplementedError


def bins_by_street(pickups: list[StreetLift]) -> dict[str, int]:
    """How many bins were emptied in each street."""
    raise NotImplementedError
'''

TRIPS_STUB = '''"""Trips between the round and the tip. See docs/lift_log.md."""

from __future__ import annotations

from .crewlog import StreetLift


def plan_trips(pickups: list[StreetLift], capacity: float) -> list[list[StreetLift]]:
    """The lifts grouped into the lorry's trips."""
    raise NotImplementedError


def trip_weights(trips: list[list[StreetLift]]) -> list[float]:
    """The load of every trip."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from binround.errors import LiftError  # noqa: E402
from binround.crewlog import StreetLift, bins_by_street, parse_crew_line  # noqa: E402
from binround.trips import plan_trips, trip_weights  # noqa: E402


class LiftLineTests(unittest.TestCase):
    def test_line(self):
        self.assertEqual(parse_crew_line("Quarry Hill|14|850kg", 1),
                         StreetLift("Quarry Hill", 14, "0.850"))

    def test_line_without_bins(self):
        with self.assertRaises(LiftError):
            parse_crew_line("Quarry Hill||850kg", 1)


class StreetTests(unittest.TestCase):
    def test_bins(self):
        pickups = [StreetLift("Quarry Hill", 3, "0.250"), StreetLift("Tanner Row", 5, "0.500"),
                 StreetLift("Quarry Hill", 2, "0.125")]
        self.assertEqual(bins_by_street(pickups), {"Quarry Hill": 5, "Tanner Row": 5})


class TripTests(unittest.TestCase):
    def test_two_trips(self):
        pickups = [StreetLift("Quarry Hill", 3, "1.500"), StreetLift("Tanner Row", 5, "2.250"),
                 StreetLift("Osier Lane", 4, "1.000")]
        trips = plan_trips(pickups, 4.0)
        self.assertEqual([[x.street for x in t] for t in trips],
                         [["Quarry Hill", "Tanner Row"], ["Osier Lane"]])
        self.assertEqual(trip_weights(trips), [3.75, 1.0])
'''

DOC_INTRO = [
    "Depot drivers log each bin lift location and its weighbridge increment.",
    "The lift-pad template is `street|bins|weight`. Empty slots and `#` notes need no lift entry.",
    "Retain the entered street spelling after trimming its margins. A street label cannot be empty.",
    "The bin entry accepts digits representing 1 through 999 inclusive.",
    "Send the scale entry straight to `binround.legacy.weighbridge_tonnes`; typical sticker forms",
    "include `850kg`, `0,85 t` and `1.2`. It gives the docket three-place tonnes, for example `0.850`.",
    "A rejected lift leaves subsequent lifts usable. Count original pad lines from 1, notes included.",
    "A plated lorry carries up to its stated tonnes, such as `10.5`. Unload before a new lift",
    "would exceed the plate, then resume the itinerary with an empty body.",
]

STREETS = ["Quarry Hill", "Tanner Row", "Osier Lane", "Bellfounder Close", "Pinfold Street",
           "Wharfside Mews", "Lime Kiln Road", "Rope Walk", "Cuckoo Bank", "Saltpan Drive",
           "Fleece Yard", "Hob Moor Terrace"]


def _weight(rnd: random.Random) -> str:
    kilos = rnd.randint(40, 2400)
    return rnd.choice([f"{kilos}kg", f"{kilos // 1000},{kilos % 1000:03d} t",
                       f"{kilos / 1000:.3f}".rstrip("0").rstrip("."), f"{kilos} KG",
                       f"{kilos // 1000}.{(kilos % 1000) // 10:02d}t"])


def _record(rnd: random.Random, i: int) -> str:
    return (f"`{rnd.choice(STREETS)}|{rnd.randint(1, 120)}|{_weight(rnd)}` | "
            f"{rnd.choice(['Monday round', 'Tuesday round', 'garden waste', 'bulky pick-up'])}"
            f", stop {i}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = _weight(rnd)
        slug = rnd.choice(["onboard_scale", "depot_ticket", "crew_handheld", "transfer_station",
                           "contract_audit"])
        cases.append((slug, repr(raw), repr(weighbridge_tonnes(raw))))
    return {
        "binround/__init__.py": '"""Refuse-collection rounds."""\n',
        "binround/errors.py": ERRORS,
        "binround/legacy.py": LEGACY,
        "binround/crewlog.py": LIFTS_STUB,
        "binround/trips.py": TRIPS_STUB,
        "docs/lift_log.md": long_doc(rnd, "The crew lift log and trips to the tip", DOC_INTRO,
                                     _record),
        "tests/test_binround.py": VISIBLE,
        "tests/test_legacy_weights.py": catalog_suite("binround.legacy", "weighbridge_tonnes",
                                                      "WeighbridgeCatalogTests", cases),
    }


TURNS = [
    "The depot needs `binround` ready for refuse dispatch. Put any unusable lift through "
    "`LiftError(line_no, message)` from binround/errors.py without printing or terminating Python. "
    "Interpret every scale entry solely with `binround.legacy.weighbridge_tonnes`. For street totals "
    "retain the order of each crew's first appearance on the lift pad. " + TRAP_WARNING + " "
    "Inventory unfinished features in binround/crewlog.py and binround/trips.py before making edits. "
    + NO_QUESTIONS,
    "Read docs/lift_log.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Implement `parse_crew_line(line, line_no)` using the lift-pad specification. Run "
    "`python -m unittest tests.test_binround -v`; leave the unfinished street and trip cases for later.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Complete the street accumulator `bins_by_street(pickups)`. Its dictionary gives every street's "
    "cumulative lifts in bins. Put a fresh street case in tests/test_binround.py and execute that suite.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Time for binround/trips.py. `plan_trips(pickups, capacity)` takes the lifts in logged "
    "order and the lorry's limit in tonnes as a float such as `10.5`, and splits them into "
    "trips: a trip keeps taking the next lift as long as its load stays at or under the "
    "limit, and a lift heavier than the limit on its own forms a trip by itself. "
    "`trip_weights(trips)` gives each trip's load in tonnes as a float, rounded to three "
    "decimals. Finish by running `python -m unittest tests.test_binround -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from binround.errors import LiftError  # noqa: E402
from binround.crewlog import StreetLift, bins_by_street, parse_crew_line  # noqa: E402
from binround.trips import plan_trips, trip_weights  # noqa: E402

LIFTS_SRC = (ROOT / "binround" / "crewlog.py").read_text(encoding="utf-8")
TRIPS_SRC = (ROOT / "binround" / "trips.py").read_text(encoding="utf-8")


def _streets(trips):
    return [[x.street for x in t] for t in trips]


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(parse_crew_line("  Rope Walk | 7 | 1,2 t ", 3), StreetLift("Rope Walk", 7, "1.200"))
        self.assertEqual(parse_crew_line("Fleece Yard|120|2.375", 1), StreetLift("Fleece Yard", 120, "2.375"))

    def test_f_bins(self):
        pickups = [StreetLift("Rope Walk", 4, "0.500"), StreetLift("Cuckoo Bank", 9, "1.000"),
                 StreetLift("Rope Walk", 6, "0.250"), StreetLift("Saltpan Drive", 1, "0.125")]
        self.assertEqual(bins_by_street(pickups),
                         {"Rope Walk": 10, "Cuckoo Bank": 9, "Saltpan Drive": 1})
        self.assertEqual(bins_by_street([]), {})

    def test_f_trips(self):
        pickups = [StreetLift("A Row", 1, "2.500"), StreetLift("B Row", 1, "3.000"), StreetLift("C Row", 1, "0.500"),
                 StreetLift("D Row", 1, "9.000"), StreetLift("E Row", 1, "0.250")]
        trips = plan_trips(pickups, 6.0)
        self.assertEqual(_streets(trips), [["A Row", "B Row", "C Row"], ["D Row"], ["E Row"]])
        self.assertEqual(trip_weights(trips), [6.0, 9.0, 0.25])
        self.assertEqual(plan_trips([], 6.0), [])

    def test_f_heavy_alone(self):
        pickups = [StreetLift("A Row", 1, "0.750"), StreetLift("B Row", 1, "12.000"), StreetLift("C Row", 1, "0.750")]
        trips = plan_trips(pickups, 10.5)
        self.assertEqual(_streets(trips), [["A Row"], ["B Row"], ["C Row"]])
        self.assertEqual(trip_weights(trips), [0.75, 12.0, 0.75])

    def test_c1_lift_error(self):
        for line in ("Rope Walk|3", "Rope Walk|3|1t|x", " |3|1t", "Rope Walk|0|1t",
                     "Rope Walk|1000|1t", "Rope Walk|2.5|1t", "Rope Walk|3|heavy", "Rope Walk|3|0kg"):
            with self.assertRaises(LiftError, msg=line) as cm:
                parse_crew_line(line, 9)
            self.assertEqual(cm.exception.line_no, 9)
        self.assertNotRegex(LIFTS_SRC + TRIPS_SRC, r"\\bprint\\s*\\(|sys\\.exit|\\bexit\\(|\\bquit\\(")

    def test_c2_weights_from_legacy(self):
        self.assertIn("weighbridge_tonnes", LIFTS_SRC)
        self.assertNotRegex(LIFTS_SRC, r"kg|1000|03d")
        self.assertEqual(parse_crew_line("Rope Walk|2|75 kg", 1).tonnes, "0.075")

    def test_c3_street_order(self):
        pickups = [StreetLift("Zinc Row", 1, "0.500"), StreetLift("Ash Walk", 2, "0.500"),
                 StreetLift("Mill Gate", 3, "0.500"), StreetLift("Ash Walk", 1, "0.500")]
        self.assertEqual(list(bins_by_street(pickups)), ["Zinc Row", "Ash Walk", "Mill Gate"])

    def test_t_decimal_tonnages(self):
        pickups = [StreetLift("A Row", 1, "0.100"), StreetLift("B Row", 1, "0.200"), StreetLift("C Row", 1, "0.300")]
        self.assertEqual(_streets(plan_trips(pickups, 0.6)), [["A Row", "B Row", "C Row"]])
        self.assertEqual(_streets(plan_trips(pickups[:2], 0.3)), [["A Row", "B Row"]])
        pickups = [StreetLift("A Row", 1, "1.100"), StreetLift("B Row", 1, "2.200"), StreetLift("C Row", 1, "0.100")]
        trips = plan_trips(pickups, 3.3)
        self.assertEqual(_streets(trips), [["A Row", "B Row"], ["C Row"]])
        self.assertEqual(trip_weights(trips), [3.3, 0.1])


if __name__ == "__main__":
    unittest.main()
'''}

LIFTS_REF = '''"""The crew's lift log. See docs/lift_log.md."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import LiftError
from .legacy import weighbridge_tonnes


@dataclass(frozen=True)
class StreetLift:
    street: str
    bins: int
    tonnes: str


def parse_crew_line(line: str, line_no: int) -> StreetLift:
    fields = line.rstrip("\\r\\n").split("|")
    if len(fields) != 3:
        raise LiftError(line_no, f"expected 3 fields, found {len(fields)}")
    street, bins, weight = (f.strip() for f in fields)
    if not street:
        raise LiftError(line_no, "missing street")
    if not (bins.isascii() and bins.isdigit()) or not 1 <= int(bins) <= 999:
        raise LiftError(line_no, f"bad bin count {bins!r}")
    try:
        tonnes = weighbridge_tonnes(weight)
    except ValueError as exc:
        raise LiftError(line_no, str(exc)) from None
    return StreetLift(street, int(bins), tonnes)


def bins_by_street(pickups: list[StreetLift]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for entry in pickups:
        totals[entry.street] = totals.get(entry.street, 0) + entry.bins
    return totals
'''

TRIPS_REF = '''"""Trips between the round and the tip. See docs/lift_log.md."""

from __future__ import annotations

from .crewlog import StreetLift


def _kilos(tonnes: str) -> int:
    # Ticket weights have exactly three decimals: whole kilograms, added exactly as integers.
    whole, _, frac = tonnes.partition(".")
    return int(whole) * 1000 + int(frac)


def plan_trips(pickups: list[StreetLift], capacity: float) -> list[list[StreetLift]]:
    limit = round(capacity * 1000)
    trips: list[list[StreetLift]] = []
    load = 0
    for entry in pickups:
        weight = _kilos(entry.tonnes)
        if trips and load + weight <= limit:
            trips[-1].append(entry)
            load += weight
        else:
            trips.append([entry])
            load = weight
    return trips


def trip_weights(trips: list[list[StreetLift]]) -> list[float]:
    return [sum(_kilos(x.tonnes) for x in t) / 1000 for t in trips]
'''

REFERENCE = {"binround/crewlog.py": LIFTS_REF, "binround/trips.py": TRIPS_REF}

TRAP_SOLUTION = {"binround/trips.py": '''"""Trips between the round and the tip. See docs/lift_log.md."""

from __future__ import annotations

from .crewlog import StreetLift


def plan_trips(pickups: list[StreetLift], capacity: float) -> list[list[StreetLift]]:
    limit = capacity
    trips: list[list[StreetLift]] = []
    current: list[StreetLift] = []
    load = 0.0
    for entry in pickups:
        weight = float(entry.tonnes)
        if current and load + weight > limit:
            trips.append(current)
            current, load = [], 0.0
        current.append(entry)
        load += weight
    if current:
        trips.append(current)
    return trips


def trip_weights(trips: list[list[StreetLift]]) -> list[float]:
    return [round(sum(float(x.tonnes) for x in t), 3) for t in trips]
'''}

# What X looks like in code: tonnages turned into binary floats before they are added up
# and compared with the limit.
TRAP_PATTERNS = (r'\bfloat\(',)
