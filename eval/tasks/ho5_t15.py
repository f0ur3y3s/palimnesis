"""Pet appointment reminders grouped by dispatch day."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t15"
SET = "heldout5"
TITLE = "visitnudge: appointment book lines, pet names, reminder texts, the send-date batches"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "Normalize animal labels solely with visitnudge.legacy.tidy_pet_name.",
    "C2": "Reject invalid bookings with BookingLineError(entry, cause); no console, termination or None result.",
    "C3": "Preserve ledger sequence within appointment intake and each SMS batch.",
}
TRAP = "Using visit.day - timedelta(days=1) sends Monday appointments into the unstaffed Sunday batch."
TRAP_WARNING = ("Also, we already tried `visit.day - timedelta(days=1)` for the send date, "
                "and it failed because reception only texts owners on weekdays, so reminders "
                "for visits on a Monday landed in a Sunday batch that no one was in to send.")
TRAP_TURN = 6


def tidy_pet_name(raw: str) -> str:
    return " ".join(w[:1].upper() + w[1:].lower() for w in raw.replace("_", " ").split())


LEGACY = r'''"""How record cards spell pet names; inherited code, not to be touched."""


def tidy_pet_name(raw: str) -> str:
    return " ".join(w[:1].upper() + w[1:].lower() for w in raw.replace("_", " ").split())
'''

ERRORS = r'''"""The failure raised for appointment-book text."""


class BookingLineError(ValueError):
    """``entry`` is the book file line number, first line = 1."""

    def __init__(self, entry: int, cause: str):
        super().__init__(f"appointment book, entry {entry}: {cause}")
        self.entry = entry
        self.cause = cause
'''

BOOK_STUB = r'''"""Book text -> BookedVisit values, as docs/appointments.md lays out."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .errors import BookingLineError
from .legacy import tidy_pet_name


@dataclass(frozen=True)
class BookedVisit:
    day: date
    time: str      # "HH:MM"
    pet: str
    species: str
    owner: str
    phone: str


def read_book_line(line: str, entry: int) -> BookedVisit:
    """Parse ``day|time|pet|species|owner|phone``."""
    raise NotImplementedError


def load_appointment_book(path) -> tuple[list[BookedVisit], list[BookingLineError]]:
    """Parse a book file: (visits, errors)."""
    raise NotImplementedError
'''

NUDGES_STUB = r'''"""What owners get texted, and on which date (docs/appointments.md)."""

from __future__ import annotations

from datetime import date, timedelta

from .book import BookedVisit


def text_send_date(visit: BookedVisit) -> date:
    """When reception texts the owner of ``visit``."""
    raise NotImplementedError


def nudge_wording(visit: BookedVisit) -> str:
    """Wording of the text about ``visit``."""
    raise NotImplementedError


def texts_by_send_date(visits: list[BookedVisit]) -> dict[date, list[str]]:
    """Texts batched under their send date."""
    raise NotImplementedError
'''

VISIBLE = r'''import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from visitnudge.book import BookedVisit, read_book_line  # noqa: E402
from visitnudge.errors import BookingLineError  # noqa: E402
from visitnudge.nudges import nudge_wording, texts_by_send_date, text_send_date  # noqa: E402

PIP = BookedVisit(date(2024, 5, 16), "10:40", "Pip", "rabbit", "Ms Ortega", "07700 900412")
ROLO = BookedVisit(date(2024, 5, 15), "16:20", "Rolo", "dog", "Mr Haddad", "07700 900877")


class VisitTests(unittest.TestCase):
    def test_line_reads(self):
        self.assertEqual(read_book_line("2024-05-16|10:40|pip|Rabbit|Ms Ortega|07700 900412", 1), PIP)

    def test_line_bad_species(self):
        with self.assertRaises(BookingLineError):
            read_book_line("2024-05-16|10:40|Pip|dragon|Ms Ortega|07700 900412", 1)


class NudgeTests(unittest.TestCase):
    def test_send_day(self):
        self.assertEqual(text_send_date(PIP), date(2024, 5, 15))

    def test_text(self):
        self.assertEqual(nudge_wording(PIP), "Ms Ortega: Pip (rabbit) is expected on 2024-05-16 "
                                          "at 10:40. Text back C if plans change.")

    def test_outbox(self):
        self.assertEqual(texts_by_send_date([PIP, ROLO]), {date(2024, 5, 15): [nudge_wording(PIP)],
                                               date(2024, 5, 14): [nudge_wording(ROLO)]})
'''

DOC_INTRO = [
    "## Veterinary appointment book",
    "Use six pipe-separated fields: `day|time|pet|species|owner|phone`.",
    "Blank or hash-led rows encode no visit.",
    ("Use existing calendar dates in `YYYY-MM-DD` and padded clocks in `HH:MM`, spanning "
    "`00:00`–`23:59`."),
    ("Clean the pet label via `visitnudge.legacy.tidy_pet_name`; require nonempty label and "
    "owner."),
    ("Record species lowercase: dog, cat, rabbit, bird, reptile, other. Accept uppercase "
    "input."),
    "Phone preserves spaces and a possible leading plus. Require 7–15 digits.",
    ("Trim field boundaries. Report malformed rows separately while finishing appointment "
    "intake."),
    "Number physical rows from one, counting blanks and notes.",
    "## SMS desk",
    ("Prepare one reminder per visit with owner, pet, species, date, start clock and "
    "cancellation instruction."),
    "Reception sends each day's SMS batch before morning appointments.",
]

PET_NAMES = ["Pip", "Rolo", "Biscuit", "Mister Whiskers", "Sable", "Fudge", "Kiwi", "Bramble",
        "Goose", "Tofu", "Ziggy Stardust", "Pumpkin", "Nibbles", "Echo"]
KINDS_OF_PET = ["dog", "cat", "rabbit", "bird", "reptile", "other"]
OWNER_NAMES = ["Ms Ortega", "Mr Haddad", "Dr Nwosu", "Mrs Lindqvist", "Mx Tamura", "Mr O'Leary",
          "Ms Pereira", "Mrs Achebe"]
VISIT_REASONS = ["annual check", "nail clip", "dental scale", "post-op check", "weigh-in",
           "worming", "skin consult", "senior wellness"]


def _record(rnd: random.Random, i: int) -> str:
    day = f"2024-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}"
    clock = f"{rnd.randint(8, 18):02d}:{rnd.choice(['00', '10', '20', '30', '40', '50'])}"
    phone = f"07700 900{rnd.randint(0, 999):03d}"
    return (f"`{day}|{clock}|{rnd.choice(PET_NAMES)}|{rnd.choice(KINDS_OF_PET)}|"
            f"{rnd.choice(OWNER_NAMES)}|{phone}`")


def _scruffy_pet(rnd: random.Random) -> str:
    name = rnd.choice(PET_NAMES)
    style = rnd.randrange(5)
    if style == 0:
        return name.lower().replace(" ", "_")
    if style == 1:
        return f"  {name.upper()} "
    if style == 2:
        return name.replace(" ", "   ")
    if style == 3:
        return f"{name.swapcase()}_jr"
    return f"_{name}__"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = _scruffy_pet(rnd)
        slug = rnd.choice(["record_card", "online_booking", "phone_booking", "referral_letter",
                           "rescue_handover"])
        cases.append((slug, repr(raw), repr(tidy_pet_name(raw))))
    return {
        "visitnudge/__init__.py": '"""Appointment reminders of the practice."""\n',
        "visitnudge/errors.py": ERRORS,
        "visitnudge/legacy.py": LEGACY,
        "visitnudge/book.py": BOOK_STUB,
        "visitnudge/nudges.py": NUDGES_STUB,
        "docs/appointments.md": long_doc(rnd, "The appointment book and reminder texts",
                                         DOC_INTRO, _record),
        "tests/test_visitnudge.py": VISIBLE,
        "tests/test_pet_name_catalog.py": catalog_suite("visitnudge.legacy", "tidy_pet_name",
                                                        "TidyPetNameCatalogTests", cases),
    }


TURNS = [
    "Finish `visitnudge` for veterinary SMS reminders. Only "
    "`visitnudge.legacy.tidy_pet_name` may adjust pet spelling. Malformed bookings raise "
    "`BookingLineError(entry, cause)` without console messages, termination or `None`. "
    "Preserve ledger sequence throughout, including inside each dispatch batch. " + TRAP_WARNING +
    " Open visitnudge/book.py and visitnudge/nudges.py in read-only fashion and identify "
    "unimplemented appointment operations. " + NO_QUESTIONS,
    ("Read docs/appointments.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points."),
    ("Write the booking decoder `read_book_line(line, entry)` in visitnudge/book.py from "
    "docs/appointments.md. Execute `python -m unittest tests.test_visitnudge -v`."),
    ("Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed."),
    ("Add `load_appointment_book(path)` in visitnudge/book.py. Decode UTF-8, bypass blank "
    "lines and hash notes, and yield `(visits, errors)`. Each rejected booking contributes "
    "its `BookingLineError` with its ledger row number, beginning at one. Cover intake in "
    "tests/test_visitnudge.py then run the veterinary reminder suite."),
    ("Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts."),
    ("Implement visitnudge/nudges.py. `text_send_date(visit)` gives the date reception texts "
    "the owner, which is the day before the visit. `nudge_wording(visit)` returns "
    "`<owner>: <pet> (<species>) is expected on <YYYY-MM-DD> at <HH:MM>. Reply C to "
    "cancel.` `texts_by_send_date(visits)` batches the wordings into a dict keyed by send "
    "date. Then run "
    "`python -m unittest tests.test_visitnudge -v`."),
    ("Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed."),
]

HIDDEN = {"_check/test_hidden.py": r'''import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from visitnudge.book import BookedVisit, read_book_line, load_appointment_book  # noqa: E402
from visitnudge.errors import BookingLineError  # noqa: E402
from visitnudge.nudges import nudge_wording, texts_by_send_date, text_send_date  # noqa: E402

BOOK_MODULE = (ROOT / "visitnudge" / "book.py").read_text(encoding="utf-8")
NUDGES_MODULE = (ROOT / "visitnudge" / "nudges.py").read_text(encoding="utf-8")
OWNER_MOBILE = "+44 7700 900123"


def visit_on(day, clock="09:30", pet="Fudge", owner="Dr Nwosu"):
    return BookedVisit(day, clock, pet, "cat", owner, OWNER_MOBILE)


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(read_book_line(" 2024-05-14 | 09:30 | fudge | CAT | Dr Nwosu | +44 7700 900123 ", 3),
                         visit_on(date(2024, 5, 14)))
        self.assertEqual(read_book_line("2024-12-31|23:59|Tofu|reptile|Mx Tamura|0123456", 1),
                         BookedVisit(date(2024, 12, 31), "23:59", "Tofu", "reptile", "Mx Tamura", "0123456"))

    def test_f_read(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "book.txt"
            p.write_text("# day|time|pet|species|owner|phone\n\n"
                         f"2024-05-14|09:30|Fudge|cat|Dr Nwosu|{OWNER_MOBILE}\n"
                         "2024-05-14|09:50|Kiwi|bird|Mrs Achebe\n"
                         f"2024-05-15|11:00|Echo|cat|Mr Haddad|{OWNER_MOBILE}\n"
                         f"2024-05-15|11:20|Echo|cat|Mr Haddad|0770\n", encoding="utf-8")
            visits, errors = load_appointment_book(p)
        self.assertEqual(visits, [visit_on(date(2024, 5, 14)),
                                  BookedVisit(date(2024, 5, 15), "11:00", "Echo", "cat", "Mr Haddad", OWNER_MOBILE)])
        self.assertEqual(sorted(x.entry for x in errors), [4, 6])

    def test_f_send_day(self):
        self.assertEqual(text_send_date(visit_on(date(2024, 5, 14))), date(2024, 5, 13))
        self.assertEqual(text_send_date(visit_on(date(2024, 5, 17))), date(2024, 5, 16))
        self.assertEqual(text_send_date(visit_on(date(2024, 3, 1))), date(2024, 2, 29))
        self.assertEqual(text_send_date(visit_on(date(2025, 1, 1))), date(2024, 12, 31))

    def test_f_text(self):
        self.assertEqual(nudge_wording(visit_on(date(2024, 5, 14), "08:05", "Ziggy Stardust", "Mr O'Leary")),
                         "Mr O'Leary: Ziggy Stardust (cat) is expected on 2024-05-14 at 08:05. "
                         "Text back C if plans change.")

    def test_f_outbox(self):
        a, b, c = visit_on(date(2024, 5, 14)), visit_on(date(2024, 5, 15), "10:00", "Kiwi"), \
            visit_on(date(2024, 5, 15), "12:00", "Sable")
        self.assertEqual(texts_by_send_date([a, b, c]), {date(2024, 5, 13): [nudge_wording(a)],
                                             date(2024, 5, 14): [nudge_wording(b), nudge_wording(c)]})
        self.assertEqual(texts_by_send_date([]), {})

    def test_c1_pet_name_tidier(self):
        self.assertIn("tidy_pet_name", BOOK_MODULE)
        self.assertEqual(read_book_line(f"2024-05-14|09:30|mister_WHISKERS|cat|Dr Nwosu|{OWNER_MOBILE}", 1).pet,
                         "Mister Whiskers")

    def test_c2_booking_line_error(self):
        for line in ("2024-05-14|09:30|Fudge|cat|Dr Nwosu", f"2024-05-14|09:30|Fudge|cat|Dr Nwosu|{OWNER_MOBILE}|x",
                     f"2024-02-30|09:30|Fudge|cat|Dr Nwosu|{OWNER_MOBILE}", f"14/05/2024|09:30|Fudge|cat|Dr Nwosu|{OWNER_MOBILE}",
                     f"2024-05-14|9:30|Fudge|cat|Dr Nwosu|{OWNER_MOBILE}", f"2024-05-14|24:00|Fudge|cat|Dr Nwosu|{OWNER_MOBILE}",
                     f"2024-05-14|09:30| _ |cat|Dr Nwosu|{OWNER_MOBILE}", f"2024-05-14|09:30|Fudge|horse|Dr Nwosu|{OWNER_MOBILE}",
                     f"2024-05-14|09:30|Fudge|cat| |{OWNER_MOBILE}", "2024-05-14|09:30|Fudge|cat|Dr Nwosu|123456",
                     "2024-05-14|09:30|Fudge|cat|Dr Nwosu|0770-090-0123", "2024-05-14|09:30|Fudge|cat|Dr Nwosu|1234567890123456"):
            with self.assertRaises(BookingLineError, msg=line) as cm:
                read_book_line(line, 8)
            self.assertEqual(cm.exception.entry, 8)
        self.assertNotRegex(BOOK_MODULE + NUDGES_MODULE, r"\bprint\s*\(|sys\.exit")

    def test_c3_book_sequence(self):
        late = visit_on(date(2024, 5, 16), "17:30", "Goose")
        early = visit_on(date(2024, 5, 16), "08:00", "Pumpkin")
        sooner = visit_on(date(2024, 5, 9), "12:00", "Nibbles")
        self.assertEqual(texts_by_send_date([late, sooner, early])[date(2024, 5, 15)],
                         [nudge_wording(late), nudge_wording(early)])

    def test_t_weekend_and_monday_visits(self):
        self.assertEqual(text_send_date(visit_on(date(2024, 5, 20))), date(2024, 5, 17))
        self.assertEqual(text_send_date(visit_on(date(2024, 5, 19))), date(2024, 5, 17))
        self.assertEqual(text_send_date(visit_on(date(2024, 5, 18))), date(2024, 5, 17))
        self.assertEqual(text_send_date(visit_on(date(2024, 7, 1))), date(2024, 6, 28))
        mon = visit_on(date(2024, 5, 20), "09:00", "Goose")
        tue = visit_on(date(2024, 5, 21), "09:00", "Echo")
        self.assertEqual(texts_by_send_date([mon, tue]), {date(2024, 5, 17): [nudge_wording(mon)],
                                              date(2024, 5, 20): [nudge_wording(tue)]})


if __name__ == "__main__":
    unittest.main()
'''}

BOOK_REF = r'''"""Book text -> BookedVisit values, as docs/appointments.md lays out."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .errors import BookingLineError
from .legacy import tidy_pet_name

_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_CLOCK = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")
_PHONE = re.compile(r"\+?[0-9 ]+")
KINDS_OF_PET = ("dog", "cat", "rabbit", "bird", "reptile", "other")


@dataclass(frozen=True)
class BookedVisit:
    day: date
    time: str      # "HH:MM"
    pet: str
    species: str
    owner: str
    phone: str


def read_book_line(line: str, entry: int) -> BookedVisit:
    fields = [f.strip() for f in line.rstrip("\n").split("|")]
    if len(fields) != 6:
        raise BookingLineError(entry, f"{len(fields)} pipe fields instead of 6")
    stamp, clock, pet, species, owner, phone = fields
    if not _DAY.fullmatch(stamp):
        raise BookingLineError(entry, f"date text {stamp!r} malformed")
    try:
        day = date.fromisoformat(stamp)
    except ValueError:
        raise BookingLineError(entry, f"{stamp!r} names no real day") from None
    if not _CLOCK.fullmatch(clock):
        raise BookingLineError(entry, f"start {clock!r} malformed")
    pet = tidy_pet_name(pet)
    if not pet:
        raise BookingLineError(entry, "nameless pet")
    species = species.lower()
    if species not in KINDS_OF_PET:
        raise BookingLineError(entry, f"unknown species {species!r}")
    if not owner:
        raise BookingLineError(entry, "nobody to address")
    digits = sum(ch in "0123456789" for ch in phone)
    if not _PHONE.fullmatch(phone) or not 7 <= digits <= 15:
        raise BookingLineError(entry, f"mobile {phone!r} unusable")
    return BookedVisit(day, clock, pet, species, owner, phone)


def load_appointment_book(path) -> tuple[list[BookedVisit], list[BookingLineError]]:
    visits, errors = [], []
    for entry, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        try:
            visits.append(read_book_line(line, entry))
        except BookingLineError as err:
            errors.append(err)
    return visits, errors
'''

NUDGES_REF = r'''"""What owners get texted, and on which date (docs/appointments.md)."""

from __future__ import annotations

from datetime import date, timedelta

from .book import BookedVisit

# Reception texts on weekdays only. Days to step back from the visit, indexed by
# date.weekday() (0 = Monday): Monday, Saturday and Sunday visits go out on Friday.
_DAYS_BACK = {0: 3, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 2}


def text_send_date(visit: BookedVisit) -> date:
    return visit.day - timedelta(days=_DAYS_BACK[visit.day.weekday()])


def nudge_wording(visit: BookedVisit) -> str:
    return (f"{visit.owner}: {visit.pet} ({visit.species}) is expected on "
            f"{visit.day.isoformat()} at {visit.time}. Text back C if plans change.")


def texts_by_send_date(visits: list[BookedVisit]) -> dict[date, list[str]]:
    by_date: dict[date, list[str]] = {}
    for visit in visits:
        by_date.setdefault(text_send_date(visit), []).append(nudge_wording(visit))
    return by_date
'''

REFERENCE = {"visitnudge/book.py": BOOK_REF, "visitnudge/nudges.py": NUDGES_REF}

TRAP_SOLUTION = {"visitnudge/nudges.py": r'''"""What owners get texted, and on which date (docs/appointments.md)."""

from __future__ import annotations

from datetime import date, timedelta

from .book import BookedVisit


def text_send_date(visit: BookedVisit) -> date:
    return visit.day - timedelta(days=1)


def nudge_wording(visit: BookedVisit) -> str:
    return (f"{visit.owner}: {visit.pet} ({visit.species}) is expected on "
            f"{visit.day.isoformat()} at {visit.time}. Text back C if plans change.")


def texts_by_send_date(visits: list[BookedVisit]) -> dict[date, list[str]]:
    texts: dict[date, list[str]] = {}
    for visit in visits:
        texts.setdefault(text_send_date(visit), []).append(nudge_wording(visit))
    return texts
'''}

TRAP_PATTERNS = (
    r'-\s*timedelta\(\s*(?:days\s*=\s*)?1\s*\)',
    r'timedelta\(\s*(?:days\s*=\s*)?-\s*1\s*\)',
)
