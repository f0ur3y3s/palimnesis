"""ho2-t4: scaling recipe quantities, unit promotion and metric output (fresh held-out task,
O-B1).

A1 categories: information needs discovered mid-task (turn 5 needs the promotion rule and
turn 7 the house metric conversion, both from the reference document read in turn 2 and
named only by reference); irrelevant retrieval matches (the document's appendix carries US
customary millilitre figures that differ from the house conversion); an oversized read;
restart before turn 5.
"""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho2-t4"
SET = "heldout2"
TITLE = "recipescale: scale recipe quantities in kitchen fractions, promote units, metric output"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "tsp, tbsp and cup amounts are written as whole numbers, fractions or mixed numbers "
          "with denominator 2, 3, 4 or 8 (1 1/2, 3/8), rounded to the nearest such value; "
          "never decimals",
    "C2": "an unknown unit raises UnitError from recipescale/errors.py with the unit in .unit; "
          "the ingredient text after the unit is kept exactly as written",
    "C3": "the factor may be an int, a Fraction or a string such as '3/2'; a zero or negative "
          "factor raises ValueError",
}
TRAP = ("already tried float(quantity) * factor formatted with :.2f; it failed because 1/3 "
        "cup times 3 came out as 0.99 cup, and nobody can measure 0.33 of a cup")


def fahrenheit(celsius: int) -> int:
    return round(celsius * 9 / 5) + 32


LEGACY = '''"""Oven temperatures for the printed cards (do not change)."""


def fahrenheit(celsius: int) -> int:
    return round(celsius * 9 / 5) + 32
'''

ERRORS = '''"""Errors."""


class UnitError(ValueError):
    """An ingredient line with a unit this package does not know. ``unit`` is that unit."""

    def __init__(self, unit):
        super().__init__(f"unknown unit {unit!r}")
        self.unit = unit
'''

STUB = '''"""Scaling recipe quantities. See docs/kitchen_units.md."""

from .errors import UnitError  # noqa: F401


def scale_line(line, factor):
    """``("1 1/2 cup sugar", 2)`` -> ``"3 cups sugar"``."""
    raise NotImplementedError


def scale_recipe(text, factor):
    """Scale every ingredient line of a recipe; other lines stay as they are."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from recipescale.scale import scale_line  # noqa: E402


class ScaleTests(unittest.TestCase):
    def test_double(self):
        self.assertEqual(scale_line("1 1/2 cup sugar", 2), "3 cups sugar")

    def test_third(self):
        self.assertEqual(scale_line("1/3 cup oil", 3), "1 cup oil")
'''

DOC_INTRO = [
    "How the test kitchen writes and scales the quantities on its recipe cards.",
    "",
    "## Ingredient lines",
    "",
    "- An ingredient line is `<quantity> <unit> <ingredient>`. A quantity is a whole number",
    "  (`2`), a fraction (`3/4`) or a mixed number (`1 1/2`).",
    "- Units: `tsp`, `tbsp`, `cup` (written `cups` above one), `g`, and `pc` for counted",
    "  items such as eggs. A line that does not start with a quantity is a heading, a step or",
    "  a note.",
    "",
    "## Scaling",
    "",
    "1. Multiply exactly.",
    "2. Round: tsp, tbsp and cup amounts go to the nearest kitchen fraction (a whole number,",
    "   or a fraction with denominator 2, 3, 4 or 8); ties go to the larger value, and an",
    "   amount that would round to zero becomes 1/8. Grams go to the nearest whole gram,",
    "   halves up. Pieces always round up to whole pieces.",
    "3. Rule U-2, promotion: an amount of 3 tsp or more is rewritten in tbsp (3 tsp = 1 tbsp),",
    "   then an amount of 4 tbsp or more in cups (16 tbsp = 1 cup), each only when the new",
    "   amount is still a kitchen fraction. Otherwise the unit stays.",
    "",
    "## Metric cards",
    "",
    "- The kitchen uses its own house conversion, not US customary measures: 1 tsp = 5 ml,",
    "  1 tbsp = 15 ml, 1 cup = 240 ml.",
    "- Convert the exact scaled amount, then round to the nearest 5 ml, halves up, never",
    "  below 5 ml. Write it as `<n> ml`. Gram and piece lines are scaled as usual.",
]

US_ML = {"tsp": 4.929, "tbsp": 14.787, "cup": 236.588}
INGREDIENTS = ["flour", "sugar", "milk", "oil", "butter", "cocoa", "oats", "rice", "stock",
               "cream", "honey", "vinegar", "yogurt", "water", "lentils"]


def _record(rnd: random.Random, i: int) -> str:
    unit = rnd.choice(["tsp", "tbsp", "cup"])
    n = rnd.choice([1, 2, 3, 4])
    d = rnd.choice([1, 2, 3, 4, 8])
    qty = f"{n}" if d == 1 else f"{n}/{d}"
    ml = n / d * US_ML[unit]
    return (f"`{qty} {unit} {rnd.choice(INGREDIENTS)}` | {ml:.1f} ml in US customary measure "
            f"(supplier sheet, for reference only)")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        c = rnd.randrange(80, 260, 5)
        slug = rnd.choice(["low_oven", "moderate_oven", "hot_oven", "recipe_card"])
        cases.append((slug, f"{c}", repr(fahrenheit(c))))
    return {
        "recipescale/__init__.py": '"""Scaling for the test kitchen\'s recipe cards."""\n',
        "recipescale/errors.py": ERRORS,
        "recipescale/legacy.py": LEGACY,
        "recipescale/scale.py": STUB,
        "docs/kitchen_units.md": long_doc(rnd, "Kitchen units and scaling", DOC_INTRO, _record),
        "tests/test_scale.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("recipescale.legacy", "fahrenheit",
                                                      "FahrenheitCatalogTests", cases),
    }


TURNS = [
    "Today's job is `recipescale`, which scales the quantities on our test kitchen's recipe "
    "cards. Requirements: (1) tsp, tbsp and cup amounts are written as whole numbers, "
    "fractions or mixed numbers with denominator 2, 3, 4 or 8 (like 1 1/2 or 3/8), rounded "
    "to the nearest such value, and never as decimals; (2) an unknown unit raises UnitError "
    "from recipescale/errors.py with the unit in `.unit`, and the ingredient text after the "
    "unit is kept exactly as written; (3) the factor may be an int, a Fraction or a string "
    "such as '3/2', and a zero or negative factor raises ValueError. We already tried "
    "float(quantity) * factor formatted with :.2f, and it failed because 1/3 cup times 3 came "
    "out as 0.99 cup, and nobody can measure 0.33 of a cup. First read recipescale/scale.py "
    "and recipescale/errors.py and tell me what is missing; do not change anything yet. "
    + NO_QUESTIONS,
    "Read docs/kitchen_units.md all the way through, all of its roughly 300 lines, until the "
    "line 'End of document.', and give me its rules in five bullet points.",
    "Implement `scale_line(line, factor)` for all five units, and `scale_recipe(text, "
    "factor)`, which scales every ingredient line and leaves the other lines as they are. "
    "No unit conversions yet. Then run `python -m unittest tests.test_scale -v`.",
    "Run the full suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and what failed.",
    "Now apply the unit promotion rule from the kitchen units document in scale_line. Add "
    "tests for it and run `python -m unittest tests.test_scale -v`.",
    "Run the full suite verbosely again (`python -m unittest discover -s tests -v`) and "
    "report the numbers.",
    "The export team needs metric cards. Give scale_line and scale_recipe a keyword argument "
    "`system`, \"us\" by default; with system=\"metric\", tsp, tbsp and cup amounts come out "
    "in millilitres, converted the way the kitchen units document specifies. Add tests and "
    "run `python -m unittest tests.test_scale -v`.",
    "Wrap up: run `python -m unittest discover -s tests` one more time and list what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import re
import sys
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from recipescale.errors import UnitError  # noqa: E402
from recipescale.scale import scale_line, scale_recipe  # noqa: E402

RECIPE = ("Pancakes\\n"
          "Serves 4\\n"
          "1 1/2 cup flour\\n"
          "1 tbsp sugar\\n"
          "2 pc eggs\\n"
          "120 g butter\\n"
          "\\n"
          "Mix well; rest for 10 minutes.\\n")


def parse_qty(text):
    m = re.fullmatch(r"(\\d+) (\\d+)/(\\d+)|(\\d+)/(\\d+)|(\\d+)", text)
    if not m:
        return None
    if m.group(1):
        return Fraction(int(m.group(1))) + Fraction(int(m.group(2)), int(m.group(3)))
    if m.group(4):
        return Fraction(int(m.group(4)), int(m.group(5)))
    return Fraction(int(m.group(6)))


class HiddenTests(unittest.TestCase):
    def test_f_scale(self):
        for line, factor, want in (("1 1/2 cup sugar", 2, "3 cups sugar"),
                                   ("1/3 cup oil", 3, "1 cup oil"),
                                   ("2 tsp salt", "1/2", "1 tsp salt"),
                                   ("250 g butter", "3/2", "375 g butter"),
                                   ("3 pc eggs", "1/2", "2 pc eggs"),
                                   ("1 tsp vanilla", Fraction(1, 3), "1/3 tsp vanilla"),
                                   ("1 cup milk", Fraction(5, 7), "3/4 cup milk"),
                                   ("2 cups flour", Fraction(1, 2), "1 cup flour"),
                                   ("1 tbsp honey", 2, "2 tbsp honey"),
                                   ("100 g oats", Fraction(1, 3), "33 g oats"),
                                   ("5 g yeast", "1/2", "3 g yeast")):
            self.assertEqual(scale_line(line, factor), want, (line, factor))

    def test_f_promotion(self):
        for line, factor, want in (("1 tsp x", 6, "2 tbsp x"), ("1 tsp x", 4, "1 1/3 tbsp x"),
                                   ("1 tbsp x", 4, "1/4 cup x"), ("1 tbsp x", 5, "5 tbsp x"),
                                   ("1 tsp x", 48, "1 cup x"), ("2 tbsp x", 3, "3/8 cup x"),
                                   ("1 tsp x", Fraction(10, 3), "3 1/3 tsp x"),
                                   ("2 tsp x", 6, "1/4 cup x")):
            self.assertEqual(scale_line(line, factor), want, (line, factor))

    def test_f_recipe(self):
        self.assertEqual(scale_recipe(RECIPE, 2),
                         "Pancakes\\nServes 4\\n3 cups flour\\n2 tbsp sugar\\n4 pc eggs\\n"
                         "240 g butter\\n\\nMix well; rest for 10 minutes.\\n")

    def test_f_metric(self):
        for line, factor, want in (("1 1/2 cup flour", 1, "360 ml flour"),
                                   ("1 tbsp oil", "1/2", "10 ml oil"),
                                   ("1/3 cup milk", 1, "80 ml milk"),
                                   ("2 tsp salt", 1, "10 ml salt"),
                                   ("2/3 cup cream", 2, "320 ml cream"),
                                   ("1 cup water", Fraction(1, 3), "80 ml water"),
                                   ("250 g butter", 2, "500 g butter"),
                                   ("3 pc eggs", 1, "3 pc eggs")):
            self.assertEqual(scale_line(line, factor, system="metric"), want, (line, factor))
        self.assertEqual(scale_recipe(RECIPE, 2, system="metric"),
                         "Pancakes\\nServes 4\\n720 ml flour\\n30 ml sugar\\n4 pc eggs\\n"
                         "240 g butter\\n\\nMix well; rest for 10 minutes.\\n")

    def test_c1_kitchen_fractions(self):
        grid = {Fraction(n, d) for d in (1, 2, 3, 4, 8) for n in range(0, 60)}
        for k in range(1, 31):
            exact = Fraction(k, 7)
            out = scale_line("1 cup x", exact)
            self.assertNotIn(".", out)
            qty = parse_qty(out.rsplit(" ", 2)[0])
            self.assertIsNotNone(qty, out)
            self.assertIn(qty.denominator, (1, 2, 3, 4, 8), out)
            best = min(grid, key=lambda c: (abs(c - exact), -c))
            self.assertEqual(qty, best, (k, out))

    def test_c2_units_and_text(self):
        for line, unit in (("2 pints milk", "pints"), ("1 handful nuts", "handful")):
            with self.assertRaises(UnitError) as cm:
                scale_line(line, 2)
            self.assertEqual(cm.exception.unit, unit)
        self.assertEqual(scale_line("1 cup Flour, sifted (Type 00)", 2),
                         "2 cups Flour, sifted (Type 00)")
        self.assertEqual(scale_line("1/2 tsp  sea salt, flaky ", 2), "1 tsp  sea salt, flaky ")

    def test_c3_factor(self):
        for factor in ("3/2", Fraction(3, 2)):
            self.assertEqual(scale_line("2 cup x", factor), "3 cups x")
        for factor in (2, "2"):
            self.assertEqual(scale_line("2 cup x", factor), "4 cups x")
        for factor in (0, "0", -1, "-1/2", Fraction(-1, 3)):
            with self.assertRaises(ValueError, msg=repr(factor)):
                scale_line("2 cup x", factor)


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"recipescale/scale.py": '''"""Scaling recipe quantities. See docs/kitchen_units.md."""

import math
import re
from fractions import Fraction

from .errors import UnitError

LINE = re.compile(r"(\\d+ \\d+/\\d+|\\d+/\\d+|\\d+) (\\S+)(.*)", re.S)
VOLUME = ("tsp", "tbsp", "cup")
ML = {"tsp": 5, "tbsp": 15, "cup": 240}
KITCHEN = (1, 2, 3, 4, 8)


def _factor(factor):
    if isinstance(factor, bool):
        raise ValueError("factor must be a number")
    f = Fraction(factor) if isinstance(factor, (int, Fraction, str)) else None
    if f is None or f <= 0:
        raise ValueError("factor must be positive")
    return f


def _qty(text):
    if " " in text:
        whole, frac = text.split(" ")
        return int(whole) + Fraction(frac)
    return Fraction(text)


def _kitchen(x):
    cands = set()
    for d in (8, 3):
        lo = Fraction(math.floor(x * d), d)
        cands |= {lo, lo + Fraction(1, d)}
    best = min(cands, key=lambda c: (abs(c - x), -c))
    return best if best > 0 else Fraction(1, 8)


def _fmt(x):
    whole, rest = divmod(x.numerator, x.denominator)
    if not rest:
        return str(whole)
    frac = f"{rest}/{x.denominator}"
    return f"{whole} {frac}" if whole else frac


def scale_line(line, factor, system="us"):
    f = _factor(factor)
    m = LINE.fullmatch(line)
    if not m:
        return line
    qty, unit, rest = m.groups()
    unit = "cup" if unit == "cups" else unit
    if unit not in VOLUME + ("g", "pc"):
        raise UnitError(m.group(2))
    amount = _qty(qty) * f
    if unit == "g":
        return f"{math.floor(amount + Fraction(1, 2))} g{rest}"
    if unit == "pc":
        return f"{math.ceil(amount)} pc{rest}"
    if system == "metric":
        ml = 5 * math.floor(amount * ML[unit] / 5 + Fraction(1, 2))
        return f"{max(ml, 5)} ml{rest}"
    amount = _kitchen(amount)
    for small, big, ratio in (("tsp", "tbsp", 3), ("tbsp", "cup", 16)):
        if unit == small and amount >= (3 if small == "tsp" else 4):
            new = amount / ratio
            if new.denominator in KITCHEN:
                unit, amount = big, new
    word = "cups" if unit == "cup" and amount > 1 else unit
    return f"{_fmt(amount)} {word}{rest}"


def scale_recipe(text, factor, system="us"):
    _factor(factor)
    out = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\\r\\n")
        out.append(scale_line(body, factor, system=system) + line[len(body):])
    return "".join(out)
'''}
