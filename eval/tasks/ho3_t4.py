"""ho3-t4: parcel rates from a rate card, with oversize and fuel surcharges (third held-out
task set).

A1 categories: information needs discovered mid-task (turn 5 needs the oversize rule S-3 and
turn 7 the fuel rule F-1, both from the reference document read in turn 2 and named only by
reference); irrelevant retrieval matches (the document carries a superseded 2024 card and an
appendix of competitor quotes with other divisors and fuel rates); an oversized read;
restart before turn 5.
"""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho3-t4"
SET = "heldout3"
TITLE = "parcelrate: chargeable weight, zone prices, oversize and fuel surcharges"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "prices are Decimal values with exactly two decimal places, computed without floats, "
          "so dimension strings such as '30.5' are used exactly as written; halves round up",
    "C2": "invalid input raises RateError from parcelrate/errors.py with .field naming the bad "
          "argument: 'weight', 'dims' or 'zone'",
    "C3": "the three dimensions may come in any order; the longest one is always the length",
}
TRAP = ("already tried float(l) * float(w) * float(h) / 5000 with math.ceil to the next half "
        "kilo; it failed because a parcel of exactly 80.5 kg volumetric came out as 81 kg, and "
        "round() on the price sent 2.685 to 2.68")


def label_band(weight_g: int) -> str:
    for limit, band in ((2000, "S"), (10000, "M"), (20000, "L")):
        if weight_g <= limit:
            return band
    return "XL"


LEGACY = '''"""Label size bands for the depot printer (do not change)."""


def label_band(weight_g: int) -> str:
    for limit, band in ((2000, "S"), (10000, "M"), (20000, "L")):
        if weight_g <= limit:
            return band
    return "XL"
'''

ERRORS = '''"""Errors."""


class RateError(ValueError):
    """Input the rate card cannot price. ``field`` names the bad argument."""

    def __init__(self, field, message):
        super().__init__(f"{field}: {message}")
        self.field = field
'''

STUB = '''"""Parcel prices from the rate card. See docs/rate_card.md."""

from .errors import RateError  # noqa: F401


def chargeable_weight(weight_g, dims):
    """``(1200, (30, 20, 10))`` -> ``1500``: the weight the parcel is charged at, in grams."""
    raise NotImplementedError


def quote_parcel(weight_g, dims, zone):
    """``(1200, (30, 20, 10), "B")`` -> ``Decimal("7.20")``."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parcelrate.quote import chargeable_weight, quote_parcel  # noqa: E402


class QuoteTests(unittest.TestCase):
    def test_weight(self):
        self.assertEqual(chargeable_weight(1200, (30, 20, 10)), 1500)

    def test_price(self):
        self.assertEqual(quote_parcel(1200, (30, 20, 10), "B"), Decimal("7.20"))
'''

DOC_INTRO = [
    "How the depot prices a parcel from the 2026 rate card.",
    "",
    "## The parcel",
    "",
    "- Weight is in whole grams. The three dimensions are in centimetres and may have",
    "  decimals; they may be listed in any order. The longest is the length, the other two",
    "  are the width and the height.",
    "- The depot refuses a parcel heavier than 30000 g, or one whose length is over 150 cm.",
    "",
    "## Chargeable weight",
    "",
    "- Volumetric weight in grams is length x width x height (cubic centimetres) divided",
    "  by 5, that is, a divisor of 5000 cubic centimetres per kilogram.",
    "- The chargeable weight is the larger of the actual and the volumetric weight, rounded",
    "  up to the next full 500 g. An exact multiple of 500 g stays as it is.",
    "",
    "## Zone prices",
    "",
    "| zone | first 500 g | each further 500 g |",
    "|---|---|---|",
    "| A | 4.20 | 0.85 |",
    "| B | 5.10 | 1.05 |",
    "| C | 6.75 | 1.40 |",
    "| D | 8.90 | 1.95 |",
    "| E | 12.40 | 2.60 |",
    "",
    "- Zone letters may be written in either case.",
    "",
    "## Surcharges",
    "",
    "- Rule S-3, oversize: when the length is over 100 cm, or the length plus the girth is",
    "  over 250 cm (girth = 2 x (width + height)), add 9.50 to the price.",
    "- Rule F-1, fuel: when fuel is charged, add 7.5 percent of the price, including any",
    "  S-3 surcharge, rounded to the cent with halves going up.",
    "",
    "## Superseded: the 2024 card",
    "",
    "- The 2024 card used a divisor of 6000, a fuel rate of 6.25 percent and an oversize",
    "  surcharge of 7.00 from 120 cm. None of it applies now.",
]

CARRIERS = ["Northlane", "Bluefinch", "Parcelo", "Stagecoach Freight", "Kestrel Couriers"]


def _record(rnd: random.Random, i: int) -> str:
    dims = sorted((rnd.randint(10, 120) for _ in range(3)), reverse=True)
    return (f"`{rnd.randint(200, 25000)} g, {dims[0]}x{dims[1]}x{dims[2]} cm` | "
            f"{rnd.choice(CARRIERS)} quote: divisor {rnd.choice([4000, 6000])}, "
            f"fuel {rnd.choice(['9', '11.5', '12', '14'])} percent")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        w = rnd.randint(50, 32000)
        slug = rnd.choice(["small_band", "medium_band", "large_band", "depot_label"])
        cases.append((slug, f"{w}", repr(label_band(w))))
    return {
        "parcelrate/__init__.py": '"""Parcel prices for the depot."""\n',
        "parcelrate/errors.py": ERRORS,
        "parcelrate/legacy.py": LEGACY,
        "parcelrate/quote.py": STUB,
        "docs/rate_card.md": long_doc(rnd, "The 2026 parcel rate card", DOC_INTRO, _record),
        "tests/test_quote.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("parcelrate.legacy", "label_band",
                                                      "LabelBandCatalogTests", cases),
    }


TURNS = [
    "Today's job is `parcelrate`, which prices parcels at our depot from the rate card. "
    "Requirements: (1) prices are Decimal values with exactly two decimal places, computed "
    "without floats, so dimension strings such as '30.5' are used exactly as written, and "
    "halves round up; (2) invalid input raises RateError from parcelrate/errors.py with "
    "`.field` naming the bad argument: 'weight', 'dims' or 'zone'; (3) the three dimensions "
    "may come in any order, and the longest one is always the length. We already tried "
    "float(l) * float(w) * float(h) / 5000 with math.ceil to the next half kilo, and it failed "
    "because a parcel of exactly 80.5 kg volumetric came out as 81 kg, and round() on the "
    "price sent 2.685 to 2.68. First read parcelrate/quote.py and parcelrate/errors.py and "
    "tell me what is missing; do not change anything yet. " + NO_QUESTIONS,
    "Read docs/rate_card.md all the way through, all of its roughly 300 lines, until the line "
    "'End of document.', and give me its rules in five bullet points.",
    "Implement `chargeable_weight(weight_g, dims)` and `quote_parcel(weight_g, dims, zone)` "
    "with the zone prices from the rate card, including its limits on weight and length. No "
    "surcharges yet. Then run `python -m unittest tests.test_quote -v`.",
    "Run the full suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and what failed.",
    "Now apply the oversize surcharge rule from the rate card in quote_parcel. Add tests for "
    "it and run `python -m unittest tests.test_quote -v`.",
    "Run the full suite verbosely again (`python -m unittest discover -s tests -v`) and "
    "report the numbers.",
    "Finance wants fuel shown on request. Give quote_parcel a keyword argument `with_fuel`, "
    "False by default; with with_fuel=True the price includes the fuel surcharge, computed "
    "the way the rate card specifies. Add tests and run `python -m unittest tests.test_quote "
    "-v`.",
    "Wrap up: run `python -m unittest discover -s tests` one more time and list what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parcelrate.errors import RateError  # noqa: E402
from parcelrate.quote import chargeable_weight, quote_parcel  # noqa: E402


def D(s):
    return Decimal(s)


class HiddenTests(unittest.TestCase):
    def test_f_weight(self):
        for weight, dims, want in ((1200, (30, 20, 10), 1500), (400, (10, 10, 10), 500),
                                   (500, (10, 10, 10), 500), (501, (10, 10, 10), 1000),
                                   (2600, (60, 40, 40), 19500), (2600, ("60", "40", "40"), 19500),
                                   (100, ("12.5", "10", "8"), 500), (9000, (50, 50, 20), 10000),
                                   (30000, (150, 10, 10), 30000)):
            self.assertEqual(chargeable_weight(weight, dims), want, (weight, dims))

    def test_f_quote(self):
        for weight, dims, zone, want in ((1200, (30, 20, 10), "B", "7.20"),
                                         (400, (10, 10, 10), "A", "4.20"),
                                         (2600, (60, 40, 40), "D", "83.00"),
                                         (9000, (50, 50, 20), "e", "61.80"),
                                         (3000, (40, 30, 20), "C", "19.35"),
                                         (1000, (100, 20, 10), "B", "12.45"),
                                         (1000, (80, 45, 40), "A", "52.65")):
            self.assertEqual(quote_parcel(weight, dims, zone), D(want), (weight, dims, zone))

    def test_f_oversize(self):
        for weight, dims, zone, want in ((5000, (110, 30, 20), "A", "35.80"),
                                         (3000, (90, 45, 40), "C", "105.85"),
                                         (1000, (80, 45, "40.5"), "A", "63.00"),
                                         (200, ("100.1", 5, 5), "b", "15.65")):
            self.assertEqual(quote_parcel(weight, dims, zone), D(want), (weight, dims, zone))

    def test_f_fuel(self):
        for weight, dims, zone, want in ((1200, (30, 20, 10), "B", "7.74"),
                                         (5000, (110, 30, 20), "A", "38.49"),
                                         (400, (10, 10, 10), "A", "4.52"),
                                         (3000, (90, 45, 40), "C", "113.79")):
            self.assertEqual(quote_parcel(weight, dims, zone, with_fuel=True), D(want),
                             (weight, dims, zone))
        self.assertEqual(quote_parcel(1200, (30, 20, 10), "B", with_fuel=False), D("7.20"))

    def test_c1_decimal(self):
        self.assertEqual(chargeable_weight(1000, ("128.8", "62.5", "50")), 80500)
        self.assertEqual(quote_parcel(1000, ("128.8", "62.5", "50"), "A"), D("149.70"))
        for args in ((1200, (30, 20, 10), "B"), (5000, (110, 30, 20), "A"),
                     (9000, (50, 50, 20), "E")):
            got = quote_parcel(*args)
            self.assertIsInstance(got, Decimal)
            self.assertEqual(got.as_tuple().exponent, -2, got)
            got = quote_parcel(*args, with_fuel=True)
            self.assertIsInstance(got, Decimal)
            self.assertEqual(got.as_tuple().exponent, -2, got)

    def test_c2_errors(self):
        cases = [("weight", lambda: quote_parcel(0, (10, 10, 10), "A")),
                 ("weight", lambda: quote_parcel(-5, (10, 10, 10), "A")),
                 ("weight", lambda: quote_parcel(30001, (10, 10, 10), "A")),
                 ("weight", lambda: quote_parcel("heavy", (10, 10, 10), "A")),
                 ("weight", lambda: chargeable_weight(0, (10, 10, 10))),
                 ("dims", lambda: quote_parcel(100, (10, 10), "A")),
                 ("dims", lambda: quote_parcel(100, (10, 0, 10), "A")),
                 ("dims", lambda: quote_parcel(100, (10, -3, 10), "A")),
                 ("dims", lambda: quote_parcel(100, (151, 10, 10), "A")),
                 ("dims", lambda: quote_parcel(100, (10, "x", 10), "A")),
                 ("dims", lambda: chargeable_weight(100, (10, 10, 10, 10))),
                 ("zone", lambda: quote_parcel(100, (10, 10, 10), "F")),
                 ("zone", lambda: quote_parcel(100, (10, 10, 10), "")),
                 ("zone", lambda: quote_parcel(100, (10, 10, 10), None))]
        for field, call in cases:
            with self.assertRaises(RateError) as cm:
                call()
            self.assertEqual(cm.exception.field, field)

    def test_c3_any_order(self):
        self.assertEqual(chargeable_weight(100, (10, 110, 20)), chargeable_weight(100, (110, 20, 10)))
        self.assertEqual(quote_parcel(5000, (20, 30, 110), "A"), D("35.80"))
        self.assertEqual(quote_parcel(3000, (40, 90, 45), "C"), D("105.85"))
        self.assertEqual(quote_parcel(1000, (10, 20, 100), "B"), D("12.45"))
        for dims in ((151, 10, 10), (10, 151, 10), (10, 10, 151)):
            with self.assertRaises(RateError):
                quote_parcel(100, dims, "A")


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"parcelrate/quote.py": '''"""Parcel prices from the rate card. See docs/rate_card.md."""

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation

from .errors import RateError

ZONES = {"A": ("4.20", "0.85"), "B": ("5.10", "1.05"), "C": ("6.75", "1.40"),
         "D": ("8.90", "1.95"), "E": ("12.40", "2.60")}
CENT = Decimal("0.01")


def _weight(w):
    if isinstance(w, bool) or not isinstance(w, int) or w <= 0 or w > 30000:
        raise RateError("weight", "whole grams from 1 to 30000")
    return w


def _dims(dims):
    try:
        vals = list(dims)
    except TypeError:
        raise RateError("dims", "three dimensions") from None
    if len(vals) != 3:
        raise RateError("dims", "three dimensions")
    out = []
    for x in vals:
        if isinstance(x, bool):
            raise RateError("dims", "not a number")
        try:
            if isinstance(x, int):
                d = Decimal(x)
            elif isinstance(x, float):
                d = Decimal(repr(x))
            elif isinstance(x, str):
                d = Decimal(x.strip())
            else:
                raise RateError("dims", "not a number")
        except InvalidOperation:
            raise RateError("dims", "not a number") from None
        if not d.is_finite() or d <= 0:
            raise RateError("dims", "dimensions must be positive")
        out.append(d)
    out.sort(reverse=True)
    if out[0] > 150:
        raise RateError("dims", "longer than 150 cm")
    return out


def chargeable_weight(weight_g, dims):
    w = _weight(weight_g)
    length, width, height = _dims(dims)
    heavier = max(Decimal(w), length * width * height / 5)
    return int((heavier / 500).to_integral_value(rounding=ROUND_CEILING)) * 500


def quote_parcel(weight_g, dims, zone, with_fuel=False):
    charged = chargeable_weight(weight_g, dims)
    if not isinstance(zone, str) or zone.strip().upper() not in ZONES:
        raise RateError("zone", "zones are A to E")
    first, step = ZONES[zone.strip().upper()]
    price = Decimal(first) + Decimal(step) * ((charged - 500) // 500)
    length, width, height = _dims(dims)
    if length > 100 or length + 2 * (width + height) > 250:
        price += Decimal("9.50")
    if with_fuel:
        price += (price * Decimal("0.075")).quantize(CENT, rounding=ROUND_HALF_UP)
    return price.quantize(CENT)
'''}
