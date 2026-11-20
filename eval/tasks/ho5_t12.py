"""Controlled-drug stocktake for the clinic cabinet."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t12"
SET = "heldout5"
TITLE = "cdledger: register lines, drug keys, millilitre balances, night-count mismatches"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "Derive cabinet keys exclusively via cdledger.legacy.drug_key.",
    "C2": "Reject malformed movements with LedgerLineError(number, why); leave reconciliation running and emit no console message.",
    "C3": "Retain register insertion order for drugs and leave the caller's movement list untouched.",
}
TRAP = "already tried summing signed_numeric_ml; it failed because the cabinet count flagged 9.7 as a mismatch"
TRAP_WARNING = ("Also, we already tried accumulating each movement's `signed_numeric_ml`, and it failed "
                "because after three 0.1 ml doses from a fresh 10 ml vial the balance came out "
                "as 9.700000000000001, so the nurses' count of 9.7 was flagged as a mismatch "
                "every night.")
TRAP_TURN = 6


def drug_key(raw: str) -> str:
    return " ".join(raw.replace("/", " / ").lower().split()).replace(" / ", "/")


LEGACY = r'''"""Drug keys exactly as the pharmacy's stock cards use them (legacy code: leave it)."""


def drug_key(raw: str) -> str:
    return " ".join(raw.replace("/", " / ").lower().split()).replace(" / ", "/")
'''

ERRORS = r'''"""Errors raised while reading the controlled-drug register."""


class LedgerLineError(ValueError):
    """An unusable register line; ``number`` is its 1-based position in the register file."""

    def __init__(self, number: int, why: str):
        super().__init__(f"register line {number}: {why}")
        self.number = number
        self.why = why
'''

ENTRIES_STUB = r'''"""Register lines -> CabinetMovement records. See docs/register.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .errors import LedgerLineError
from .legacy import drug_key


@dataclass(frozen=True)
class CabinetMovement:
    day: date
    kind: str      # "received", "given" or "wasted"
    drug: str      # the drug key
    ml: str        # millilitres, e.g. "2.5"
    staff: str     # initials of whoever signed the line

    @property
    def signed_numeric_ml(self) -> float:
        """Numeric contribution to the cabinet stock figure."""
        direction = 1 if self.kind == "received" else -1
        return direction * float(self.ml)


def read_line_entry(text: str, number: int) -> CabinetMovement:
    """One register line ``day;kind;drug;ml;staff`` -> CabinetMovement."""
    raise NotImplementedError


def read_register(path) -> tuple[list[CabinetMovement], list[LedgerLineError]]:
    """The whole register file -> (entries, errors)."""
    raise NotImplementedError
'''

STOCK_STUB = r'''"""Stock held of each drug, and the nightly count check. See docs/register.md."""

from __future__ import annotations

from .entries import CabinetMovement


def balances(entries: list[CabinetMovement]) -> dict[str, float]:
    """Cabinet totals consumed directly by the JSON report."""
    raise NotImplementedError


def discrepancies(entries: list[CabinetMovement], counted: dict[str, float]) -> list[str]:
    """The drugs whose counted amount does not agree with the register."""
    raise NotImplementedError
'''

VISIBLE = r'''import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cdledger.entries import CabinetMovement, read_line_entry  # noqa: E402
from cdledger.errors import LedgerLineError  # noqa: E402
from cdledger.stock import balances, discrepancies  # noqa: E402

MORPH = "morphine 10mg/ml"
DAY = date(2024, 5, 6)
LINES = [CabinetMovement(DAY, "received", MORPH, "10", "PK"), CabinetMovement(DAY, "given", MORPH, "2", "PK"),
         CabinetMovement(DAY, "wasted", MORPH, "0.5", "AL")]


class EntryTests(unittest.TestCase):
    def test_line_reads(self):
        self.assertEqual(read_line_entry("2024-05-06;given;Morphine 10mg/ml;2;PK", 1), LINES[1])

    def test_line_unknown_kind(self):
        with self.assertRaises(LedgerLineError):
            read_line_entry("2024-05-06;borrowed;Morphine 10mg/ml;2;PK", 1)


class StockTests(unittest.TestCase):
    def test_balance(self):
        self.assertEqual(balances(LINES), {MORPH: 7.5})

    def test_counts(self):
        self.assertEqual(discrepancies(LINES, {MORPH: 7.5}), [])
        self.assertEqual(discrepancies(LINES, {MORPH: 6.0}), [MORPH])
'''

DOC_INTRO = [
    "## Locked cabinet register",
    "Five semicolon-delimited fields: `day;kind;drug;ml;staff`.",
    "Ignore blank records and hash-prefixed commentary.",
    "Movement dates follow `YYYY-MM-DD` and must exist.",
    "Movement kind: `received` into stock, `given` to a patient, `wasted` under witness.",
    "Inventory key: apply `cdledger.legacy.drug_key`; reject an empty result.",
    "Positive millilitres: digits with optional point plus one or two further digits.",
    "Keep volume text in the movement record.",
    "Staff initials: two or three uppercase letters.",
    ("Trim each field. Archive errors with one-based physical line positions and keep valid "
    "movements."),
    "## Cabinet reconciliation",
    "Per drug: received millilitres less both given and wasted millilitres.",
    "Nurses key measured remainders into the night sheet as numbers, such as `12.5`.",
    "Forward discrepant amounts to the pharmacist on the following morning.",
]

DRUGS = ["Morphine 10mg/ml", "Methadone 1mg/ml", "Ketamine 100mg/ml", "Midazolam 5mg/ml",
         "Buprenorphine 0.3mg/ml", "Fentanyl 50mcg/ml", "Diazepam 5mg/ml", "Pethidine 50mg/ml"]
STAFF = ["PK", "AL", "JMW", "RT", "SBO", "NF"]
WHERE = ["kennel", "cattery ward", "theatre", "recovery bay", "isolation room"]
PATIENTS = ["Bramble", "Captain", "Saffron", "Noodle", "Maple", "Kipper", "Thistle", "Domino"]


def _record(rnd: random.Random, i: int) -> str:
    kind = rnd.choice(["received", "given", "given", "given", "wasted"])
    ml = (f"{rnd.randint(10, 50)}" if kind == "received"
          else f"{rnd.randint(0, 4)}.{rnd.randint(1, 9)}{rnd.choice(['', '5'])}")
    day = f"2024-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}"
    note = ("delivery checked against the invoice" if kind == "received"
            else f"for {rnd.choice(PATIENTS)} in the {rnd.choice(WHERE)} {rnd.randint(1, 6)}")
    return f"`{day};{kind};{rnd.choice(DRUGS)};{ml};{rnd.choice(STAFF)}` | {note}"


def _raw_drug(rnd: random.Random) -> str:
    name, strength = rnd.choice(DRUGS).split(" ")
    num, unit = strength.split("/")
    style = rnd.randrange(5)
    if style == 0:
        return f"  {name.upper()}   {num} / {unit.upper()} "
    if style == 1:
        return f"{name.lower()}\t{num}/{unit}"
    if style == 2:
        return f"{name} {num.upper()}/ {unit}"
    if style == 3:
        return f"{name}  {num} /{unit}  (vial)"
    return f"{name.title()} {num}/{unit}"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = _raw_drug(rnd)
        slug = rnd.choice(["wholesaler_note", "stock_card", "theatre_sheet", "audit_copy",
                           "old_register"])
        cases.append((slug, repr(raw), repr(drug_key(raw))))
    return {
        "cdledger/__init__.py": '"""Controlled-drug register of the clinic."""\n',
        "cdledger/errors.py": ERRORS,
        "cdledger/legacy.py": LEGACY,
        "cdledger/entries.py": ENTRIES_STUB,
        "cdledger/stock.py": STOCK_STUB,
        "docs/register.md": long_doc(rnd, "The controlled-drug register and the night count",
                                     DOC_INTRO, _record),
        "tests/test_cdledger.py": VISIBLE,
        "tests/test_drug_key_catalog.py": catalog_suite("cdledger.legacy", "drug_key",
                                                        "DrugKeyCatalogTests", cases),
    }


TURNS = [
    "I handle our clinic's controlled-drug cabinet and need `cdledger` ready for stock "
    "reconciliation. Drug identity comes solely from `cdledger.legacy.drug_key`. Raise "
    "`LedgerLineError(number, why)` on invalid register material without printing, exiting "
    "or yielding `None`. Preserve first-appearance drug order and leave callers' entry lists "
    "intact. " + TRAP_WARNING +
    " Audit cdledger/entries.py and cdledger/stock.py for unimplemented operations. Report "
    "those gaps before making edits. " + NO_QUESTIONS,
    ("Read docs/register.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points."),
    ("Implement `read_line_entry(text, number)` in cdledger/entries.py using the cabinet "
    "format in docs/register.md. Run `python -m unittest tests.test_cdledger -v`."),
    ("Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed."),
    ("Implement cabinet register intake via `read_register(path)` in cdledger/entries.py. "
    "Decode UTF-8. Skip blank or hash-led records. Return `(entries, errors)`, collecting "
    "each refused record's `LedgerLineError` numbered with the source register line, counting from one. "
    "Extend tests/test_cdledger.py for cabinet intake; run the module."),
    ("Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts."),
    ("Implement cdledger/stock.py. `balances(entries)` maps every drug to the "
    "millilitres in stock: the received amounts minus the given and wasted ones. The report "
    "serializes that mapping directly as JSON numeric properties. "
    "`discrepancies(entries, counted)` takes the night count, a dict from drug to the amount "
    "the nurses measured (a number such as `12.5`), and returns, following that dict's "
    "sequence, the drugs whose counted amount differs from their balance; a drug the register "
    "never mentions has a balance of nothing. After that, run "
    "`python -m unittest tests.test_cdledger -v`."),
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

from cdledger.entries import CabinetMovement, read_line_entry, read_register  # noqa: E402
from cdledger.errors import LedgerLineError  # noqa: E402
from cdledger.stock import balances, discrepancies  # noqa: E402

ENTRIES_SRC = (ROOT / "cdledger" / "entries.py").read_text(encoding="utf-8")
STOCK_SRC = (ROOT / "cdledger" / "stock.py").read_text(encoding="utf-8")
MOR = "morphine 10mg/ml"
KET = "ketamine 100mg/ml"
MID = "midazolam 5mg/ml"
D1 = date(2024, 3, 2)


def e(kind, drug, ml):
    return CabinetMovement(D1, kind, drug, ml, "JK")


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(read_line_entry(" 2024-03-02 ; received ; Morphine 10MG/ML ; 10 ; JK ", 4),
                         CabinetMovement(D1, "received", MOR, "10", "JK"))
        self.assertEqual(read_line_entry("2024-03-02;wasted;Ketamine 100mg/ml;0.25;SBO", 1),
                         CabinetMovement(D1, "wasted", KET, "0.25", "SBO"))

    def test_f_read(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "register.txt"
            p.write_text("# day;kind;drug;ml;staff\n\n"
                         "2024-03-02;received;Morphine 10mg/ml;10;JK\n"
                         "2024-03-02;given;Morphine 10mg/ml;2.5\n"
                         "2024-03-03;given;Morphine 10mg/ml;2.5;JK\n"
                         "2024-03-03;given;Morphine 10mg/ml;0;JK\n", encoding="utf-8")
            entries, errors = read_register(p)
        self.assertEqual(entries, [CabinetMovement(D1, "received", MOR, "10", "JK"),
                                   CabinetMovement(date(2024, 3, 3), "given", MOR, "2.5", "JK")])
        self.assertEqual(sorted(x.number for x in errors), [4, 6])

    def test_f_balances(self):
        lines = [e("received", MOR, "10"), e("given", MOR, "2.5"), e("wasted", MOR, "0.25"),
                 e("received", KET, "20"), e("given", KET, "4.5")]
        self.assertEqual(balances(lines), {MOR: 7.25, KET: 15.5})

    def test_f_discrepancies(self):
        lines = [e("received", MOR, "10"), e("given", MOR, "2.5"), e("wasted", MOR, "0.25"),
                 e("received", KET, "20"), e("given", KET, "4.5")]
        counted = {MOR: 7.25, KET: 15.0, "methadone 1mg/ml": 0.0, "diazepam 5mg/ml": 2.0}
        self.assertEqual(discrepancies(lines, counted), [KET, "diazepam 5mg/ml"])

    def test_c1_drug_key(self):
        self.assertIn("drug_key", ENTRIES_SRC)
        self.assertEqual(read_line_entry("2024-03-02;given;KETAMINE   100 mg / ML;1;JK", 1).drug,
                         "ketamine 100 mg/ml")

    def test_c2_ledger_line_error(self):
        for text in ("2024-03-02;given;Morphine 10mg/ml;1", "2024-03-02;given;Morphine;1;JK;x",
                     "2024-02-30;given;Morphine;1;JK", "02/03/2024;given;Morphine;1;JK",
                     "2024-03-02;used;Morphine;1;JK", "2024-03-02;given; ;1;JK",
                     "2024-03-02;given;Morphine;-1;JK", "2024-03-02;given;Morphine;0.00;JK",
                     "2024-03-02;given;Morphine;1.255;JK", "2024-03-02;given;Morphine;one;JK",
                     "2024-03-02;given;Morphine;1;J", "2024-03-02;given;Morphine;1;jk"):
            with self.assertRaises(LedgerLineError, msg=text) as cm:
                read_line_entry(text, 13)
            self.assertEqual(cm.exception.number, 13)
        self.assertNotRegex(ENTRIES_SRC + STOCK_SRC, r"\bprint\s*\(|sys\.exit")

    def test_c3_first_line_order(self):
        lines = [e("received", MID, "5"), e("received", KET, "10"), e("given", MID, "1"),
                 e("received", "alfentanil 0.5mg/ml", "4")]
        before = list(lines)
        self.assertEqual(list(balances(lines)), [MID, KET, "alfentanil 0.5mg/ml"])
        discrepancies(lines, {KET: 3.0, MID: 4.0})
        self.assertEqual(lines, before)

    def test_t_tenths_add_up_exactly(self):
        lines = [e("received", MID, "10"), e("given", MID, "0.1"), e("given", MID, "0.1"),
                 e("given", MID, "0.1")]
        self.assertEqual(balances(lines)[MID], 9.7)
        self.assertEqual(discrepancies(lines, {MID: 9.7}), [])
        lines = [e("received", KET, "0.3"), e("given", KET, "0.1"), e("wasted", KET, "0.2")]
        self.assertEqual(balances(lines)[KET], 0)
        self.assertEqual(discrepancies(lines, {KET: 0.0}), [])


if __name__ == "__main__":
    unittest.main()
'''}

ENTRIES_REF = r'''"""Register lines -> CabinetMovement records. See docs/register.md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .errors import LedgerLineError
from .legacy import drug_key

_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_ML = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?")
_STAFF = re.compile(r"[A-Z]{2,3}")
KINDS = ("received", "given", "wasted")


@dataclass(frozen=True)
class CabinetMovement:
    day: date
    kind: str      # "received", "given" or "wasted"
    drug: str      # the drug key
    ml: str        # millilitres, e.g. "2.5"
    staff: str     # initials of whoever signed the line

    @property
    def signed_numeric_ml(self) -> float:
        """Numeric contribution to the cabinet stock figure."""
        direction = 1 if self.kind == "received" else -1
        return direction * float(self.ml)


def read_line_entry(text: str, number: int) -> CabinetMovement:
    fields = [f.strip() for f in text.rstrip("\n").split(";")]
    if len(fields) != 5:
        raise LedgerLineError(number, f"expected 5 fields, saw {len(fields)}")
    stamp, kind, drug, ml, staff = fields
    if not _DAY.fullmatch(stamp):
        raise LedgerLineError(number, f"day {stamp!r} is not YYYY-MM-DD")
    try:
        day = date.fromisoformat(stamp)
    except ValueError:
        raise LedgerLineError(number, f"no such day {stamp!r}") from None
    if kind not in KINDS:
        raise LedgerLineError(number, f"unknown kind {kind!r}")
    key = drug_key(drug)
    if not key:
        raise LedgerLineError(number, "drug missing")
    if not _ML.fullmatch(ml) or not ml.replace("0", "").replace(".", ""):
        raise LedgerLineError(number, f"volume {ml!r} is not a positive amount")
    if not _STAFF.fullmatch(staff):
        raise LedgerLineError(number, f"initials {staff!r} are not 2 or 3 capitals")
    return CabinetMovement(day, kind, key, ml, staff)


def read_register(path) -> tuple[list[CabinetMovement], list[LedgerLineError]]:
    entries, errors = [], []
    for number, text in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not text.strip() or text.startswith("#"):
            continue
        try:
            entries.append(read_line_entry(text, number))
        except LedgerLineError as err:
            errors.append(err)
    return entries, errors
'''

STOCK_REF = r'''"""Stock held of each drug, and the nightly count check. See docs/register.md."""

from __future__ import annotations

from decimal import Decimal

from .entries import CabinetMovement

_SIGN = {"received": 1, "given": -1, "wasted": -1}


def _exact_balances(entries: list[CabinetMovement]) -> dict[str, Decimal]:
    stock: dict[str, Decimal] = {}
    for entry in entries:
        # Decimal keeps written tenths and hundredths exact.
        stock[entry.drug] = stock.get(entry.drug, Decimal(0)) + _SIGN[entry.kind] * Decimal(entry.ml)
    return stock


def balances(entries: list[CabinetMovement]) -> dict[str, float]:
    return {drug: float(total) for drug, total in _exact_balances(entries).items()}


def discrepancies(entries: list[CabinetMovement], counted: dict[str, float]) -> list[str]:
    stock = balances(entries)
    return [drug for drug, amount in counted.items() if amount != stock.get(drug, 0)]
'''

REFERENCE = {"cdledger/entries.py": ENTRIES_REF, "cdledger/stock.py": STOCK_REF}

TRAP_SOLUTION = {"cdledger/stock.py": r'''"""Stock held of each drug, and the nightly count check. See docs/register.md."""

from __future__ import annotations

from .entries import CabinetMovement


def balances(entries: list[CabinetMovement]) -> dict[str, float]:
    stock: dict[str, float] = {}
    for e in entries:
        stock[e.drug] = stock.get(e.drug, 0.0) + e.signed_numeric_ml
    return stock


def discrepancies(entries: list[CabinetMovement], counted: dict[str, float]) -> list[str]:
    stock = balances(entries)
    return [drug for drug, amount in counted.items() if amount != stock.get(drug, 0.0)]
'''}

TRAP_PATTERNS = (r'\.signed_numeric_ml\b', r'\bfloat\(\s*(?!self\b)\w+\.ml\b',
                 r'\bmap\(\s*float\b', r'\bfloat\(\s*counted\[',
                 r'\bfloat\(\s*(?:amount|counted_ml|count_text|written|ml|ml_text|volume_text)\s*\)')
