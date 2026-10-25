"""dev-t1: an inventory CSV importer (development task; harness check only, D44.5)."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, SLUG_WORDS, catalog_suite, long_doc

ID = "dev-t1"
SET = "development"
TITLE = "inventory CSV importer: rows, prices in cents, file import"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "prices are integer cents end to end; never convert through float",
    "C2": "bad rows raise RowError(line_no, message); never print, exit or return None",
    "C3": "keep the public signatures parse_row(line, line_no), parse_price(text), parse_file(path)",
}
TRAP = "already tried int(float(price) * 100); it failed because '0.29' became 28 cents"


def normalize_sku(raw: str) -> str:
    s = raw.strip().upper().replace("_", "-").replace(" ", "-")
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-")


LEGACY = '''"""SKU normalization (in production since 2019; do not change)."""


def normalize_sku(raw: str) -> str:
    s = raw.strip().upper().replace("_", "-").replace(" ", "-")
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-")
'''

ERRORS = '''"""Import errors."""


class RowError(ValueError):
    """A row that cannot be imported. ``line_no`` is 1-based in the source file."""

    def __init__(self, line_no: int, message: str):
        super().__init__(f"line {line_no}: {message}")
        self.line_no = line_no
        self.message = message
'''

STUB = '''"""Inventory CSV rows -> Item records. See docs/csv_format.md."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import RowError
from .legacy import normalize_sku


@dataclass(frozen=True)
class Item:
    sku: str
    name: str
    quantity: int
    price_cents: int


def parse_row(line: str, line_no: int) -> Item:
    """One data row ``sku;name;quantity;price`` -> Item."""
    raise NotImplementedError


def parse_price(text: str) -> int:
    """A price such as ``12.30`` -> integer cents."""
    raise NotImplementedError


def parse_file(path) -> tuple[list[Item], list[RowError]]:
    """Every data row of a file -> (items, errors)."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from invimport.errors import RowError  # noqa: E402
from invimport.parse import Item, parse_price, parse_row  # noqa: E402


class ParseRowTests(unittest.TestCase):
    def test_row_basic(self):
        self.assertEqual(parse_row("ab 12;Widget;4;2.50", 3), Item("AB-12", "Widget", 4, 250))

    def test_row_bad_quantity(self):
        with self.assertRaises(RowError):
            parse_row("ab-12;Widget;-1;2.50", 3)


class ParsePriceTests(unittest.TestCase):
    def test_price_two_decimals(self):
        self.assertEqual(parse_price("12.30"), 1230)

    def test_price_whole(self):
        self.assertEqual(parse_price("7"), 700)
'''

DOC_INTRO = [
    "This document describes the inventory export that the warehouse system writes every",
    "night and that `invimport` reads.",
    "",
    "## Rows",
    "",
    "- One record per line, fields separated by `;`: `sku;name;quantity;price`.",
    "- Lines that are empty, or whose first character is `#`, are not records.",
    "- `sku` is normalized with `invimport.legacy.normalize_sku`.",
    "- `name` is free text; leading and trailing spaces are removed. It is never empty.",
    "- `quantity` is a whole number, zero or more.",
    "- `price` is a decimal with `.` as the separator and at most two digits after it,",
    "  optionally prefixed with `$`: `12.3`, `12.30`, `$7`, `0.05`.",
    "- A row with the wrong number of fields, or with any invalid field, is rejected; the",
    "  rest of the file is still imported.",
    "",
    "## Line numbers",
    "",
    "Line numbers in error reports count every line of the file from 1, including comments",
    "and blank lines.",
]


def _record(rnd: random.Random, i: int) -> str:
    sku = f"{rnd.choice(SLUG_WORDS)} {rnd.randint(1, 999)}"
    price = f"{rnd.randint(0, 400)}.{rnd.randint(0, 99):02d}"
    return f"`{sku};{rnd.choice(SLUG_WORDS).title()} {rnd.choice(SLUG_WORDS)};{rnd.randint(0, 90)};{price}` | sample {i}"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for k in range(CATALOG_TESTS):
        raw = rnd.choice([f"  {rnd.choice(SLUG_WORDS)} {rnd.randint(1, 99)} ",
                          f"{rnd.choice(SLUG_WORDS)}__{rnd.choice(SLUG_WORDS)}",
                          f"-{rnd.choice(SLUG_WORDS)}-{rnd.randint(100, 999)}-",
                          f"{rnd.choice(SLUG_WORDS)} _ {rnd.choice(SLUG_WORDS)}"])
        slug = rnd.choice(["mixed_case_with_spaces", "double_underscore", "edge_dashes",
                           "spaced_underscore", "legacy_catalog_entry"])
        cases.append((slug, repr(raw), repr(normalize_sku(raw))))
    return {
        "invimport/__init__.py": '"""Warehouse inventory import."""\n',
        "invimport/errors.py": ERRORS,
        "invimport/legacy.py": LEGACY,
        "invimport/parse.py": STUB,
        "docs/csv_format.md": long_doc(rnd, "Inventory export format", DOC_INTRO, _record),
        "tests/test_parse.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("invimport.legacy", "normalize_sku",
                                                      "NormalizeSkuCatalogTests", cases),
    }


TURNS = [
    "We're finishing `invimport`, the importer for the warehouse's nightly inventory export. "
    "Three rules for this work: (1) prices are integer cents end to end, never converted "
    "through float; (2) a bad row raises `RowError(line_no, message)` from "
    "invimport/errors.py, and the code never prints, never calls sys.exit and never returns "
    "None for a bad row; (3) the public signatures in invimport/parse.py stay exactly as they "
    "are. Also, we already tried `int(float(price) * 100)` for prices, and it failed because "
    "'0.29' came out as 28 cents. For now just read invimport/parse.py and invimport/errors.py "
    "and tell me what is left to implement; don't change anything yet. " + NO_QUESTIONS,
    "Read docs/csv_format.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize the row format in five bullet points.",
    "Implement `parse_row` in invimport/parse.py: split the fields, normalize the sku with "
    "normalize_sku, strip the name, check the quantity, and get the price from parse_price. "
    "Then run `python -m unittest tests.test_parse -v`. The price tests may still fail.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Now implement `parse_price` as docs/csv_format.md describes: `12.3`, `12.30`, `$7` and "
    "`0.05` are valid; more than two decimals or anything else is invalid and raises "
    "ValueError. Then run `python -m unittest tests.test_parse -v`.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Implement `parse_file(path)`: read the file as UTF-8, skip blank lines and lines starting "
    "with `#`, and return `(items, errors)`, where `errors` collects the failures of bad rows "
    "with their 1-based line numbers in the file. Add a test for it to tests/test_parse.py and "
    "run that module.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import inspect
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from invimport.errors import RowError  # noqa: E402
from invimport import parse  # noqa: E402
from invimport.parse import Item, parse_file, parse_price, parse_row  # noqa: E402

SOURCE = (ROOT / "invimport" / "parse.py").read_text(encoding="utf-8")


class HiddenTests(unittest.TestCase):
    def test_f_row(self):
        self.assertEqual(parse_row(" ab 12 ; Widget ;4;$2.5", 9), Item("AB-12", "Widget", 4, 250))
        self.assertEqual(parse_row("x;Y;0;0.05", 1), Item("X", "Y", 0, 5))

    def test_f_price_values(self):
        for text, cents in (("12.3", 1230), ("12.30", 1230), ("$7", 700), ("0.05", 5),
                            ("0.29", 29), ("1.15", 115), ("19.99", 1999), ("4.35", 435)):
            self.assertEqual(parse_price(text), cents, text)

    def test_f_price_invalid(self):
        for text in ("1.234", "abc", "", "1.2.3", "-1"):
            with self.assertRaises(ValueError, msg=text):
                parse_price(text)

    def test_f_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "inv.csv"
            p.write_text("# sku;name;quantity;price\\n\\nab;A;1;1.00\\nbad row\\ncd;C;2;0.29\\n"
                         "ef;E;-3;1\\n", encoding="utf-8")
            items, errors = parse_file(p)
        self.assertEqual(items, [Item("AB", "A", 1, 100), Item("CD", "C", 2, 29)])
        self.assertEqual(sorted(e.line_no for e in errors), [4, 6])

    def test_c1_no_float(self):
        self.assertNotRegex(SOURCE, r"\\bfloat\\s*\\(")
        self.assertEqual(parse_price("0.29"), 29)

    def test_c2_row_error(self):
        with self.assertRaises(RowError) as cm:
            parse_row("only;three;fields", 7)
        self.assertEqual(cm.exception.line_no, 7)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "inv.csv"
            p.write_text("ab;A;x;1\\n", encoding="utf-8")
            items, errors = parse_file(p)
        self.assertTrue(errors and all(isinstance(e, RowError) for e in errors))
        self.assertNotRegex(SOURCE, r"\\bprint\\s*\\(|sys\\.exit")

    def test_c3_signatures(self):
        self.assertEqual(list(inspect.signature(parse_row).parameters), ["line", "line_no"])
        self.assertEqual(list(inspect.signature(parse_price).parameters), ["text"])
        self.assertEqual(list(inspect.signature(parse_file).parameters), ["path"])


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"invimport/parse.py": '''"""Inventory CSV rows -> Item records. See docs/csv_format.md."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import RowError
from .legacy import normalize_sku


@dataclass(frozen=True)
class Item:
    sku: str
    name: str
    quantity: int
    price_cents: int


def parse_row(line: str, line_no: int) -> Item:
    fields = line.rstrip("\\n").split(";")
    if len(fields) != 4:
        raise RowError(line_no, f"expected 4 fields, got {len(fields)}")
    sku, name, qty, price = fields
    sku, name = normalize_sku(sku), name.strip()
    if not sku or not name:
        raise RowError(line_no, "empty sku or name")
    if not qty.strip().isdigit():
        raise RowError(line_no, f"bad quantity {qty!r}")
    try:
        cents = parse_price(price)
    except ValueError as e:
        raise RowError(line_no, str(e)) from None
    return Item(sku, name, int(qty), cents)


def parse_price(text: str) -> int:
    t = text.strip().removeprefix("$")
    whole, _, frac = t.partition(".")
    if not whole.isdigit() or (frac and not frac.isdigit()) or len(frac) > 2 or t.count(".") > 1:
        raise ValueError(f"bad price {text!r}")
    return int(whole) * 100 + int(frac.ljust(2, "0") or 0)


def parse_file(path) -> tuple[list[Item], list[RowError]]:
    items, errors = [], []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        try:
            items.append(parse_row(line, n))
        except RowError as e:
            errors.append(e)
    return items, errors
'''}
