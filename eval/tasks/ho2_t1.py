"""ho2-t1: Maidenhead grid locators with exact error codes (fresh held-out task, O-B1).

A1 categories: explicit identifiers and error codes (three codes stated once, in turn 1,
needed after the restart in turn 5, which refers to them only as "the codes I gave you");
irrelevant retrieval matches (the reference document carries a retired error table with
look-alike codes and an appendix with look-alike ``GR-3xxx`` card numbers); an oversized
read (the document); restart before turn 5.
"""

from __future__ import annotations

import random
from fractions import Fraction

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho2-t1"
SET = "heldout2"
TITLE = "gridloc: Maidenhead grid locators, to and from latitude and longitude"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "every invalid input raises LocatorError from gridloc/errors.py with .code exactly "
          "GR-301 (wrong locator length), GR-302 (a character not allowed at its position) or "
          "GR-303 (latitude, longitude or pair count out of range, or not a number)",
    "C2": "locators are written with upper-case field letters and lower-case subsquare "
          "letters; locators are read in any case",
    "C3": "standard library only: no maidenhead, pyproj or other third-party packages",
}
TRAP = ("already tried chr(65 + int(x)) for every letter pair; it failed because the subsquare "
        "pair then used the field alphabet, and a latitude of exactly 90 produced the letter S")

POINTS = "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split()


def compass_point(deg: int) -> str:
    return POINTS[int((deg % 360) / 22.5 + 0.5) % 16]


LEGACY = '''"""Wind-rose labels for the contact log screen (do not change)."""

POINTS = "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split()


def compass_point(deg: int) -> str:
    return POINTS[int((deg % 360) / 22.5 + 0.5) % 16]
'''

ERRORS = '''"""Errors."""


class LocatorError(ValueError):
    """An invalid locator or coordinate. ``code`` says which rule was broken."""

    def __init__(self, code, message):
        super().__init__(f"{code}: {message}")
        self.code = code
'''

STUB = '''"""Maidenhead grid locators. See docs/maidenhead.md."""

from .errors import LocatorError  # noqa: F401


def to_locator(lat, lon, pairs=3):
    """(41.714775, -72.72726) -> ``"FN31pr"``; ``pairs`` is 2, 3 or 4 character pairs."""
    raise NotImplementedError


def from_locator(locator):
    """``"FN31pr"`` -> (latitude, longitude) of the cell."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gridloc.locator import to_locator  # noqa: E402


class ToLocatorTests(unittest.TestCase):
    def test_square(self):
        self.assertEqual(to_locator(41.714775, -72.72726, 2), "FN31")

    def test_subsquare(self):
        self.assertEqual(to_locator(41.714775, -72.72726), "FN31pr")
'''

DOC_INTRO = [
    "How the station log writes positions as Maidenhead grid locators.",
    "",
    "## The grid",
    "",
    "- A locator is 2, 3 or 4 pairs of characters. Each pair gives longitude first, then",
    "  latitude, and each pair divides the cell named by the pairs before it.",
    "- Pair 1, the field: letters A to R. Longitude is counted east from 180 degrees west in",
    "  steps of 20 degrees; latitude north from 90 degrees south in steps of 10 degrees.",
    "- Pair 2, the square: digits 0 to 9, steps of 2 degrees of longitude and 1 degree of",
    "  latitude.",
    "- Pair 3, the subsquare: letters a to x, steps of 5 minutes of longitude (1/12 degree)",
    "  and 2.5 minutes of latitude (1/24 degree).",
    "- Pair 4, the extended square: digits 0 to 9 again, each subsquare cut into 10 by 10.",
    "",
    "## Edges",
    "",
    "- Latitude runs from -90 to 90 inclusive; 90 belongs to the top row of cells.",
    "- Longitude runs from -180 to 180; 180 is the same meridian as -180 and is written as",
    "  -180.",
    "",
    "## Reading a locator",
    "",
    "- Decoding a locator gives the centre of its cell, not a corner, as (latitude,",
    "  longitude) rounded to 6 decimal places.",
    "",
    "## Retired: error numbers of the v1 converter",
    "",
    "- The v1 converter (removed in 2021) used GR-101 for a bad length, GR-102 for a bad",
    "  character and GR-104 for coordinates out of range. Nothing reads these numbers now.",
]


def _locator(lat: float, lon: float) -> str:
    la, lo = Fraction(repr(lat)) + 90, Fraction(repr(lon)) + 180
    f1, f2 = int(lo // 20), int(la // 10)
    lo, la = lo - 20 * f1, la - 10 * f2
    s1, s2 = int(lo // 2), int(la)
    lo, la = lo - 2 * s1, la - s2
    return (chr(65 + f1) + chr(65 + f2) + str(s1) + str(s2)
            + chr(97 + int(lo * 12)) + chr(97 + int(la * 24)))


def _record(rnd: random.Random, i: int) -> str:
    lat, lon = round(rnd.uniform(-60, 70), 4), round(rnd.uniform(-170, 170), 4)
    card = f"GR-3{rnd.randint(100, 999)}"
    return f"`{_locator(lat, lon)}` | {lat}, {lon}; QSL card {card}"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        deg = rnd.randint(0, 359)
        slug = rnd.choice(["cardinal", "intercardinal", "wind_rose", "log_screen"])
        cases.append((slug, f"{deg}", repr(compass_point(deg))))
    return {
        "gridloc/__init__.py": '"""Maidenhead grid locators for the station log."""\n',
        "gridloc/errors.py": ERRORS,
        "gridloc/legacy.py": LEGACY,
        "gridloc/locator.py": STUB,
        "docs/maidenhead.md": long_doc(rnd, "Maidenhead locators in the station log", DOC_INTRO,
                                       _record),
        "tests/test_locator.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("gridloc.legacy", "compass_point",
                                                      "CompassPointCatalogTests", cases),
    }


TURNS = [
    "This session builds `gridloc`, which turns positions in our station log into Maidenhead "
    "grid locators and back. Rules: (1) every invalid input raises LocatorError from "
    "gridloc/errors.py, and its `.code` must be exactly GR-301 for a locator of the wrong "
    "length, GR-302 for a character that is not allowed at its position, and GR-303 for a "
    "latitude, longitude or pair count that is out of range or not a number; (2) locators are "
    "written with upper-case field letters and lower-case subsquare letters, and are read in "
    "any case; (3) standard library only, no maidenhead, pyproj or other packages. Note: we "
    "already tried chr(65 + int(x)) for every letter pair, and it failed because the "
    "subsquare pair then used the field alphabet, and a latitude of exactly 90 produced the "
    "letter S. First read gridloc/locator.py and gridloc/errors.py and tell me what is "
    "missing; do not edit anything yet. " + NO_QUESTIONS,
    "Read docs/maidenhead.md completely, all of its roughly 300 lines, through the line "
    "'End of document.'. Then sum up how the grid works in five bullet points.",
    "Implement `to_locator(lat, lon, pairs)` for 2 and 3 pairs (4 or 6 characters), "
    "following the document, edges included. Then run `python -m unittest "
    "tests.test_locator -v`.",
    "Run all the tests verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many ran and whether any failed.",
    "Now implement `from_locator(locator)` for 4- and 6-character locators, returning what "
    "the document says decoding gives. Validate the input of both functions and raise the "
    "errors with the codes I gave you at the start. Add tests for decoding and for the "
    "errors to tests/test_locator.py and run `python -m unittest tests.test_locator -v`.",
    "Run all the tests verbosely once more (`python -m unittest discover -s tests -v`) and "
    "report the totals.",
    "Add the fourth pair, the extended square, to both functions, so 8-character locators "
    "work in both directions (`pairs=4` for to_locator). Add tests and run `python -m "
    "unittest tests.test_locator -v`.",
    "To finish, run `python -m unittest discover -s tests` one last time and list what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gridloc.errors import LocatorError  # noqa: E402
from gridloc.locator import from_locator, to_locator  # noqa: E402

PKG = ROOT / "gridloc"


def close(a, b):
    return abs(a[0] - b[0]) < 2e-6 and abs(a[1] - b[1]) < 2e-6


class HiddenTests(unittest.TestCase):
    def test_f_to_locator(self):
        for lat, lon, pairs, want in ((41.714775, -72.72726, 3, "FN31pr"),
                                      (41.714775, -72.72726, 2, "FN31"),
                                      (-33.8568, 151.2153, 3, "QF56od"),
                                      (0, 0, 2, "JJ00"), (0, 0, 3, "JJ00aa"),
                                      (-90, -180, 3, "AA00aa"), (90, 0, 3, "JR09ax"),
                                      (10, 180, 2, "AK00")):
            self.assertEqual(to_locator(lat, lon, pairs), want, (lat, lon, pairs))
        self.assertEqual(to_locator(-33.8568, 151.2153), "QF56od")

    def test_f_from_locator(self):
        for loc, want in (("FN31", (41.5, -73.0)), ("FN31pr", (41.729167, -72.708333)),
                          ("JJ00aa", (0.020833, 0.041667)), ("AA00", (-89.5, -179.0))):
            got = from_locator(loc)
            self.assertTrue(close(got, want), (loc, got, want))
        for lat, lon in ((12.3456, -45.6789), (-0.5, 0.5), (59.9, 10.7)):
            got = from_locator(to_locator(lat, lon))
            self.assertLess(abs(got[0] - lat), 1 / 48 + 2e-6)
            self.assertLess(abs(got[1] - lon), 1 / 24 + 2e-6)

    def test_f_extended(self):
        self.assertEqual(to_locator(41.714775, -72.72726, 4), "FN31pr21")
        self.assertEqual(to_locator(-33.8568, 151.2153, 4), "QF56od54")
        self.assertTrue(close(from_locator("FN31pr21"), (41.714583, -72.729167)))

    def test_f_invalid(self):
        bad = [lambda: from_locator("FN3"), lambda: from_locator("FN31pr2"),
               lambda: from_locator("SN31"), lambda: from_locator("FN31py"),
               lambda: to_locator(91, 0), lambda: to_locator(0, 180.5), lambda: to_locator(0, 0, 5)]
        for call in bad:
            with self.assertRaises(LocatorError):
                call()

    def test_c1_codes(self):
        cases = [("GR-301", lambda: from_locator("FN3")), ("GR-301", lambda: from_locator("FN31p")),
                 ("GR-301", lambda: from_locator("FN31pr2")), ("GR-301", lambda: from_locator("")),
                 ("GR-302", lambda: from_locator("SN31")), ("GR-302", lambda: from_locator("FNx1")),
                 ("GR-302", lambda: from_locator("FN31py")),
                 ("GR-302", lambda: from_locator("FN31pr2a")),
                 ("GR-303", lambda: to_locator(91, 0)), ("GR-303", lambda: to_locator(-90.5, 0)),
                 ("GR-303", lambda: to_locator(0, 180.5)), ("GR-303", lambda: to_locator(0, 0, 5)),
                 ("GR-303", lambda: to_locator(0, 0, 1)), ("GR-303", lambda: to_locator("12", 0))]
        for code, call in cases:
            with self.assertRaises(LocatorError) as cm:
                call()
            self.assertEqual(cm.exception.code, code)

    def test_c2_case(self):
        loc = to_locator(-33.8568, 151.2153)
        self.assertTrue(loc[:2].isupper() and loc[4:].islower(), loc)
        self.assertTrue(close(from_locator("fn31PR"), from_locator("FN31pr")))
        self.assertTrue(close(from_locator("qf56OD54"), from_locator("QF56od54")))

    def test_c3_stdlib_only(self):
        std = set(sys.stdlib_module_names)
        for path in PKG.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    mods = [node.module or ""]
                else:
                    continue
                for m in mods:
                    self.assertIn(m.split(".")[0], std, f"{path.name} imports {m}")


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"gridloc/locator.py": '''"""Maidenhead grid locators. See docs/maidenhead.md."""

from fractions import Fraction

from .errors import LocatorError

# (alphabet, longitude step, latitude step) for each pair, in degrees.
PAIRS = [("ABCDEFGHIJKLMNOPQR", Fraction(20), Fraction(10)),
         ("0123456789", Fraction(2), Fraction(1)),
         ("abcdefghijklmnopqrstuvwx", Fraction(1, 12), Fraction(1, 24)),
         ("0123456789", Fraction(1, 120), Fraction(1, 240))]


def _number(x, lo, hi, name):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x:
        raise LocatorError("GR-303", f"{name} is not a number")
    if x < lo or x > hi:
        raise LocatorError("GR-303", f"{name} out of range")
    return Fraction(repr(x)) if isinstance(x, float) else Fraction(x)


def to_locator(lat, lon, pairs=3):
    if isinstance(pairs, bool) or pairs not in (2, 3, 4):
        raise LocatorError("GR-303", "pairs must be 2, 3 or 4")
    la = _number(lat, -90, 90, "latitude") + 90
    lo = _number(lon, -180, 180, "longitude") + 180
    if lo == 360:
        lo = Fraction(0)
    if la == 180:
        la -= Fraction(1, 10 ** 9)
    out = []
    for alphabet, dlo, dla in PAIRS[:pairs]:
        i, j = int(lo // dlo), int(la // dla)
        out += [alphabet[i], alphabet[j]]
        lo -= i * dlo
        la -= j * dla
    return out[0].upper() + out[1].upper() + "".join(out[2:])


def from_locator(locator):
    if not isinstance(locator, str) or len(locator) not in (4, 6, 8):
        raise LocatorError("GR-301", "a locator has 4, 6 or 8 characters")
    lo, la = Fraction(-180), Fraction(-90)
    for k in range(len(locator) // 2):
        alphabet, dlo, dla = PAIRS[k]
        a, b = locator[2 * k].lower(), locator[2 * k + 1].lower()
        letters = alphabet.lower()
        if a not in letters or b not in letters:
            raise LocatorError("GR-302", f"character not allowed in pair {k + 1}")
        lo += letters.index(a) * dlo
        la += letters.index(b) * dla
        last = (dlo, dla)
    return round(float(la + last[1] / 2), 6), round(float(lo + last[0] / 2), 6)
'''}
