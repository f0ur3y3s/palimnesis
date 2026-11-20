"""Arrival rosters and clinician call order."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t14"
SET = "heldout5"
TITLE = "triagedesk: arrival sheet parsing, dispenser tickets, triage levels, call order"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "Format tickets solely with triagedesk.legacy.walkin_ticket.",
    "C2": "Reject malformed arrivals with ArrivalLineError(position, problem); keep stdout, process and None out of error handling.",
    "C3": "Represent arrival clocks as HH:MM strings with zero padding.",
}
TRAP = "Queueing (walkin.level, walkin) via heapq.heappush calls a later patient first when simultaneous arrivals also share severity."
TRAP_WARNING = ("Also, we already tried `heapq.heappush(self._waiting, (walkin.level, walkin))` "
                "for the queue, and it failed because two patients who walked in during the "
                "same minute at the same triage level were called in ticket-number order "
                "rather than in the order the nurse admitted them, so W-020, admitted first, "
                "was called after W-005.")
TRAP_TURN = 6


def walkin_ticket(raw: str) -> str:
    digits = raw.replace(" ", "").upper()
    for prefix in ("W-", "W"):
        if digits.startswith(prefix):
            digits = digits[len(prefix):]
            break
    return f"W-{digits:0>3}"


LEGACY = r'''"""Dispenser ticket numbering, kept from the old system; leave it alone."""


def walkin_ticket(raw: str) -> str:
    digits = raw.replace(" ", "").upper()
    for prefix in ("W-", "W"):
        if digits.startswith(prefix):
            digits = digits[len(prefix):]
            break
    return f"W-{digits:0>3}"
'''

ERRORS = r'''"""What goes wrong when an arrival sheet is parsed."""


class ArrivalLineError(ValueError):
    """Unparseable sheet line; ``position`` counts file lines from 1."""

    def __init__(self, position: int, problem: str):
        super().__init__(f"sheet position {position}: {problem}")
        self.position = position
        self.problem = problem
'''

ARRIVALS_STUB = r'''"""Turns arrival-sheet text into WalkIn values (docs/walkin.md)."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ArrivalLineError
from .legacy import walkin_ticket


@dataclass(frozen=True, order=True)
class WalkIn:
    time: str        # "HH:MM"
    ticket: str      # "W-012"
    level: int       # 1 = see soonest ... 5 = can wait longest
    complaint: str


def parse_walkin(line: str, position: int) -> WalkIn:
    """Parse ``time,ticket,level,complaint`` into a WalkIn."""
    raise NotImplementedError


def read_walkins(path) -> tuple[list[WalkIn], list[ArrivalLineError]]:
    """Parse each line in a sheet file: (walk-ins, errors)."""
    raise NotImplementedError
'''

LOUNGE_STUB = r'''"""Patients waiting to be called in; docs/walkin.md has the rules."""

from __future__ import annotations

import heapq

from .arrivals import WalkIn


class TriageRoom:
    def __init__(self) -> None:
        self._waiting: list = []

    def admit(self, walkin: WalkIn) -> None:
        """Put a triaged patient in the queue."""
        raise NotImplementedError

    def next_patient(self) -> WalkIn:
        """Hand the next patient to a free clinician."""
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError
'''

VISIBLE = r'''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from triagedesk.arrivals import WalkIn, parse_walkin  # noqa: E402
from triagedesk.errors import ArrivalLineError  # noqa: E402
from triagedesk.lounge import TriageRoom  # noqa: E402

SPRAIN = WalkIn("08:40", "W-014", 4, "rolled ankle")
BURN = WalkIn("08:52", "W-015", 2, "kettle scald, hand")
WASP = WalkIn("09:03", "W-016", 3, "wasp sting, puffy")


class WalkInParsingChecks(unittest.TestCase):
    def test_sheet_line_parses(self):
        self.assertEqual(parse_walkin("8:40,w14,4,rolled ankle", 1), SPRAIN)

    def test_level_nine_rejected(self):
        with self.assertRaises(ArrivalLineError):
            parse_walkin("08:40,W-014,9,rolled ankle", 1)


class CallOrderChecks(unittest.TestCase):
    def test_lowest_level_called_first(self):
        lounge = TriageRoom()
        for walkin in (SPRAIN, BURN, WASP):
            lounge.admit(walkin)
        self.assertEqual(len(lounge), 3)
        self.assertEqual([lounge.next_patient() for _ in range(3)], [BURN, WASP, SPRAIN])
        self.assertEqual(len(lounge), 0)
'''

DOC_INTRO = [
    "## Triage nurse's arrival sheet",
    ("Row layout: `time,ticket,level,complaint`. The complaint consumes everything after "
    "comma three."),
    "Whitespace-only lines and hash-led comments represent no patient.",
    "Hours have one or two digits on input, minutes two. Clock range: `0:00`–`23:59`.",
    ("Store `HH:MM`. Canonicalize tickets with `triagedesk.legacy.walkin_ticket` and require "
    "W- plus three digits."),
    "Use severity 1 through 5, with 1 most urgent. Trim and require complaint text.",
    ("Trim the before-complaint fields. Report malformed entries individually and continue "
    "intake."),
    "Number every physical line from one, irrespective of content.",
    "## Clinician calls",
    ("Admit accepted patients, then call by lowest severity number. Calling removes the "
    "patient."),
]

COMPLAINTS = ["wrist hurt in a tumble", "nail splinter", "fortnight-long cough",
              "earache (6-year-old)", "knife nick on finger", "arm rash",
              "bee sting, puffy", "lifting strain, lower back", "bike graze on knee",
              "grit in left eye", "nosebleed, settled", "throat sore, feverish"]
NURSES = ["Nurse Adeyemi", "Nurse Fitzgerald", "Nurse Kowalczyk", "Nurse Varga", "Nurse Lund"]


def _record(rnd: random.Random, i: int) -> str:
    hour, minute = rnd.randint(7, 21), rnd.randint(0, 59)
    stamp = f"{hour}:{minute:02d}" if rnd.random() < 0.4 else f"{hour:02d}:{minute:02d}"
    return (f"`{stamp},W-{rnd.randint(1, 250):03d},{rnd.randint(1, 5)},"
            f"{rnd.choice(COMPLAINTS)}` | triaged by {rnd.choice(NURSES)}, chair "
            f"{rnd.randint(1, 24)}")


def _raw_ticket(rnd: random.Random) -> str:
    n = rnd.randint(1, 250)
    style = rnd.randrange(6)
    if style == 0:
        return f"w{n}"
    if style == 1:
        return f" W-{n} "
    if style == 2:
        return f"W {n:03d}"
    if style == 3:
        return f"{n}"
    if style == 4:
        return f"w - {n}"
    return f"x{n}"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = _raw_ticket(rnd)
        slug = rnd.choice(["dispenser_roll", "reception_pad", "night_sheet", "phone_note",
                           "audit_sample"])
        cases.append((slug, repr(raw), repr(walkin_ticket(raw))))
    return {
        "triagedesk/__init__.py": '"""Walk-in clinic reception."""\n',
        "triagedesk/errors.py": ERRORS,
        "triagedesk/legacy.py": LEGACY,
        "triagedesk/arrivals.py": ARRIVALS_STUB,
        "triagedesk/lounge.py": LOUNGE_STUB,
        "docs/walkin.md": long_doc(rnd, "Reception: arrival sheet and triage order",
                                   DOC_INTRO, _record),
        "tests/test_triagedesk.py": VISIBLE,
        "tests/test_ticket_catalog.py": catalog_suite("triagedesk.legacy", "walkin_ticket",
                                                      "WalkinTicketCatalogTests", cases),
    }


TURNS = [
    "Finish `triagedesk` for our walk-in clinic. Ticket spelling comes exclusively from "
    "`triagedesk.legacy.walkin_ticket`. Signal malformed arrivals with "
    "`ArrivalLineError(position, problem)` without printing, quitting or returning `None`. "
    "Keep the arrival clock as zero-padded text such as `07:05`, never `datetime.time`. " + TRAP_WARNING +
    " Read triagedesk/arrivals.py and triagedesk/lounge.py and inventory the unfinished "
    "triage operations. Leave the files intact. " + NO_QUESTIONS,
    ("Read docs/walkin.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points."),
    ("Implement the arrival-sheet decoder `parse_walkin(line, position)` in "
    "triagedesk/arrivals.py according to docs/walkin.md. Check it with `python -m unittest "
    "tests.test_triagedesk -v`."),
    ("Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed."),
    ("Add `read_walkins(path)` in triagedesk/arrivals.py. UTF-8 intake skips whitespace-only "
    "rows and hash remarks. Return `(walkins, errors)` with one `ArrivalLineError` per "
    "rejected arrival keyed by arrival-sheet offset, starting at one. Exercise intake in "
    "tests/test_triagedesk.py and run the triage tests."),
    ("Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts."),
    ("Implement `TriageRoom` in triagedesk/lounge.py. `admit(walkin)` adds a patient to "
    "those waiting; `next_patient()` takes out and returns whoever a free clinician calls "
    "next, lowest level number first; `len(lounge)` counts the patients not yet called. Then run `python -m unittest tests.test_triagedesk -v`."),
    ("Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed."),
]

HIDDEN = {"_check/test_hidden.py": r'''import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from triagedesk.arrivals import WalkIn, parse_walkin, read_walkins  # noqa: E402
from triagedesk.errors import ArrivalLineError  # noqa: E402
from triagedesk.lounge import TriageRoom  # noqa: E402

ARRIVALS_SRC = (ROOT / "triagedesk" / "arrivals.py").read_text(encoding="utf-8")
LOUNGE_SRC = (ROOT / "triagedesk" / "lounge.py").read_text(encoding="utf-8")


def fill_lounge(*walkins):
    lounge = TriageRoom()
    for w in walkins:
        lounge.admit(w)
    return lounge


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(parse_walkin(" 7:05 , w12 , 3 , thumb cut, oozing ", 2),
                         WalkIn("07:05", "W-012", 3, "thumb cut, oozing"))
        self.assertEqual(parse_walkin("23:59,W-250,5,repeat script mislaid", 1),
                         WalkIn("23:59", "W-250", 5, "repeat script mislaid"))

    def test_f_read(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "monday_sheet.txt"
            p.write_text("# time,ticket,level,complaint\n\n"
                         "10:15,W-101,2,tight chest\n"
                         "10:17,W-102,3\n"
                         "10:20,W-103,5,fit note, return to work\n"
                         "10:24,W-104,0,dizzy\n", encoding="utf-8")
            walkins, errors = read_walkins(p)
        self.assertEqual(walkins, [WalkIn("10:15", "W-101", 2, "tight chest"),
                                   WalkIn("10:20", "W-103", 5, "fit note, return to work")])
        self.assertEqual(sorted(x.position for x in errors), [4, 6])

    def test_f_room(self):
        a = WalkIn("11:00", "W-031", 4, "eyes itching")
        b = WalkIn("11:02", "W-032", 2, "ladder tumble")
        c = WalkIn("11:05", "W-033", 5, "new dressing due")
        d = WalkIn("11:09", "W-034", 1, "hives after peanuts")
        lounge = fill_lounge(a, b, c)
        self.assertEqual(lounge.next_patient(), b)
        lounge.admit(d)
        self.assertEqual(len(lounge), 3)
        self.assertEqual([lounge.next_patient() for _ in range(3)], [d, a, c])
        self.assertEqual(len(lounge), 0)

    def test_c1_ticket_formatter(self):
        self.assertIn("walkin_ticket", ARRIVALS_SRC)
        self.assertEqual(parse_walkin("9:00,w - 7,3,earache", 1).ticket, "W-007")

    def test_c2_arrival_line_error(self):
        for line in ("9:00,W-077,3", "9:00,W-077", "24:00,W-077,3,hiccups", "9:60,W-077,3,hiccups",
                     "9.00,W-077,3,hiccups", "9:5,W-077,3,hiccups", "9:00,X1,3,hiccups",
                     "9:00,W-1000,3,hiccups", "9:00,W-077,6,hiccups", "9:00,W-077,0,hiccups",
                     "9:00,W-077,two,hiccups", "9:00,W-077,3,  "):
            with self.assertRaises(ArrivalLineError, msg=line) as cm:
                parse_walkin(line, 17)
            self.assertEqual(cm.exception.position, 17)
        self.assertNotRegex(ARRIVALS_SRC + LOUNGE_SRC, r"\bprint\s*\(|sys\.exit")

    def test_c3_times_as_text(self):
        for raw, want in (("0:00", "00:00"), ("7:05", "07:05"), ("13:45", "13:45")):
            got = parse_walkin(f"{raw},W-077,3,hiccups", 1).time
            self.assertIs(type(got), str)
            self.assertEqual(got, want)

    def test_t_same_level_in_arrival_order(self):
        a = WalkIn("10:00", "W-020", 3, "jammed thumb")
        b = WalkIn("10:00", "W-030", 1, "short of breath")
        c = WalkIn("10:00", "W-005", 3, "midge bites")
        d = WalkIn("10:00", "W-011", 3, "waxy ear")
        e = WalkIn("10:00", "W-002", 1, "palm laceration")
        lounge = fill_lounge(a, b, c, d, e)
        self.assertEqual([lounge.next_patient() for _ in range(5)], [b, e, a, c, d])


if __name__ == "__main__":
    unittest.main()
'''}

ARRIVALS_REF = r'''"""Turns arrival-sheet text into WalkIn values (docs/walkin.md)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import ArrivalLineError
from .legacy import walkin_ticket

_ARRIVED = re.compile(r"(?P<hh>[0-9]{1,2}):(?P<mm>[0-5][0-9])")
_DISPENSED = re.compile(r"W-[0-9]{3}")
_SCALE = {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5}


@dataclass(frozen=True, order=True)
class WalkIn:
    time: str        # "HH:MM"
    ticket: str      # "W-012"
    level: int       # 1 = see soonest ... 5 = can wait longest
    complaint: str


def parse_walkin(line: str, position: int) -> WalkIn:
    pieces = line.rstrip("\n").split(",", maxsplit=3)
    if len(pieces) < 4:
        raise ArrivalLineError(position, f"only {len(pieces)} comma-separated parts")
    when, raw_ticket, raw_level, note = pieces
    arrived = _ARRIVED.fullmatch(when.strip())
    if arrived is None or int(arrived["hh"]) >= 24:
        raise ArrivalLineError(position, f"clock reading {when.strip()!r} unusable")
    ticket = walkin_ticket(raw_ticket)
    if _DISPENSED.fullmatch(ticket) is None:
        raise ArrivalLineError(position, f"ticket {raw_ticket.strip()!r} unusable")
    if raw_level.strip() not in _SCALE:
        raise ArrivalLineError(position, f"triage level {raw_level.strip()!r} outside the scale")
    if not note.strip():
        raise ArrivalLineError(position, "nurse gave no complaint")
    hh = arrived["hh"].rjust(2, "0")
    return WalkIn(f"{hh}:{arrived['mm']}", ticket, _SCALE[raw_level.strip()], note.strip())


def read_walkins(path) -> tuple[list[WalkIn], list[ArrivalLineError]]:
    walkins, errors = [], []
    for position, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        try:
            walkins.append(parse_walkin(line, position))
        except ArrivalLineError as err:
            errors.append(err)
    return walkins, errors
'''

LOUNGE_REF = r'''"""Patients waiting to be called in; docs/walkin.md has the rules."""

from __future__ import annotations

import heapq
from itertools import count

from .arrivals import WalkIn


class TriageRoom:
    def __init__(self) -> None:
        self._waiting: list = []
        # Equal levels: a running admission count keeps them in arrival order.
        self._admitted = count()

    def admit(self, walkin: WalkIn) -> None:
        entry = (walkin.level, next(self._admitted), walkin)
        heapq.heappush(self._waiting, entry)

    def next_patient(self) -> WalkIn:
        *_, called = heapq.heappop(self._waiting)
        return called

    def __len__(self) -> int:
        seated = self._waiting
        return len(seated)
'''

REFERENCE = {"triagedesk/arrivals.py": ARRIVALS_REF, "triagedesk/lounge.py": LOUNGE_REF}

TRAP_SOLUTION = {"triagedesk/lounge.py": r'''"""Patients waiting to be called in; docs/walkin.md has the rules."""

from __future__ import annotations

import heapq

from .arrivals import WalkIn


class TriageRoom:
    def __init__(self) -> None:
        self._waiting: list = []

    def admit(self, walkin: WalkIn) -> None:
        heapq.heappush(self._waiting, (walkin.level, walkin))

    def next_patient(self) -> WalkIn:
        level, walkin = heapq.heappop(self._waiting)
        return walkin

    def __len__(self) -> int:
        seated = self._waiting
        return len(seated)
'''}

# equal levels then fall back on the record's own ordering, not on admission.
TRAP_PATTERNS = (
    r'heappush\(\s*[\w.]+\s*,\s*\(\s*[^,()]+,\s*[^,()]+\)\s*\)',
    r'heappush\(\s*[\w.]+\s*,\s*\(\s*[^,()]+,\s*\w+\.(?:ticket|time)\s*,',
)
