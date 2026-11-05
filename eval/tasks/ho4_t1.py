"""ho4-t1: Roman numerals with exact error codes (fourth held-out task set).

A1 categories: explicit identifiers and error codes (five codes and their checking order,
stated once in turn 1 and needed after the restart in turn 5, which refers to them only as
"the codes and the order I gave you"); irrelevant retrieval matches (the reference document
carries a retired error table with look-alike codes and an appendix with look-alike
``RN-7xxx`` catalogue numbers); an oversized read (the document); restart before turn 5.
"""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho4-t1"
SET = "heldout4"
TITLE = "romanum: Roman numerals to and from integers, validation codes, regnal names"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "every invalid input raises NumeralError from romanum/errors.py with .code exactly "
          "RN-70 (to_roman given anything but a whole number from 1 to 3999), or, when "
          "reading, RN-71 (empty, or a character that is not a Roman digit), RN-72 (a digit "
          "repeated in a row more often than allowed), RN-73 (a smaller digit before a larger "
          "one that is not an allowed subtractive pair) or RN-74 (anything else that is not "
          "the standard form), RN-71 to RN-74 checked in that order so the first rule broken "
          "decides the code",
    "C2": "input numerals are accepted in any case and with surrounding whitespace; numerals "
          "in the output are always upper case",
    "C3": "standard library only: no roman, roman-numerals or other third-party packages",
}
TRAP = ("already tried adding up the letter values from left to right; it failed because IV "
        "came out as 6, and IIII and VX were accepted as 4 and 5")


def century_of(year: int) -> int:
    return (year - 1) // 100 + 1


LEGACY = '''"""Century of a year for the catalogue headings (do not change)."""


def century_of(year: int) -> int:
    return (year - 1) // 100 + 1
'''

ERRORS = '''"""Errors."""


class NumeralError(ValueError):
    """An invalid numeral or value. ``code`` says which rule was broken."""

    def __init__(self, code, message):
        super().__init__(f"{code}: {message}")
        self.code = code
'''

STUB = '''"""Roman numerals. See docs/numeral_rules.md."""

from .errors import NumeralError  # noqa: F401


def to_roman(n):
    """``1994`` -> ``"MCMXCIV"``."""
    raise NotImplementedError


def from_roman(text):
    """``"MCMXCIV"`` -> ``1994``."""
    raise NotImplementedError


def split_regnal(text):
    """``"Louis XIV"`` -> ``("Louis", 14)``."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from romanum.numeral import from_roman, to_roman  # noqa: E402


class NumeralTests(unittest.TestCase):
    def test_write(self):
        self.assertEqual(to_roman(1994), "MCMXCIV")

    def test_read(self):
        self.assertEqual(from_roman("MMXXIV"), 2024)
'''

DOC_INTRO = [
    "How the catalogue desk writes and reads Roman numerals (volume numbers, plates, regnal",
    "names).",
    "",
    "## Digits",
    "",
    "| digit | value | | digit | value |",
    "|---|---|---|---|---|",
    "| I | 1 | | C | 100 |",
    "| V | 5 | | D | 500 |",
    "| X | 10 | | M | 1000 |",
    "| L | 50 | | | |",
    "",
    "- There is no digit for zero and no negative numerals. The desk writes the whole",
    "  numbers from 1 to 3999 and nothing else.",
    "",
    "## The standard form",
    "",
    "- Digits are written from the largest value to the smallest and added up.",
    "- A smaller digit written before a larger one is subtracted from it. Only six such",
    "  subtractive pairs exist: IV (4), IX (9), XL (40), XC (90), CD (400) and CM (900).",
    "- I, X, C and M may stand at most three times in a row; V, L and D never stand twice",
    "  in a row.",
    "- Every value from 1 to 3999 has exactly one standard form. Writing a number means",
    "  taking the largest value of the table above, or of the six pairs, that still fits, as",
    "  often as it fits, then the next one: 1994 is M + CM + XC + IV = MCMXCIV.",
    "- Reading accepts the standard form only. IIX, VIV, XCX and IVI break none of the",
    "  rules on repeats and pairs, but they are not standard forms and are rejected.",
    "- Numerals are typed in lower case often enough; the desk accepts any case and",
    "  ignores spaces around the numeral. Spaces inside a numeral are not allowed.",
    "",
    "## Regnal names",
    "",
    "- A regnal name is a name followed by a numeral, separated by whitespace: `Louis XIV`,",
    "  `Juan Carlos I`. The numeral is the last word; the name is everything before it, with",
    "  the whitespace around it removed and the whitespace inside it kept as written.",
    "- A single full stop directly after the numeral is allowed and dropped",
    "  (`Henry VIII.` is Henry, 8): old catalogue cards end every entry with one.",
    "- A text without both a name and a numeral is not a regnal name.",
    "",
    "## Retired: codes of the 2015 converter",
    "",
    "- The 2015 converter reported R-1 for a bad character, R-2 for too many repeats and R-9",
    "  for a value it could not write. Nothing reads these codes now.",
]

PLATES = ["MCMXCIV", "XLII", "MMXXIV", "CDXLIV", "DCCCLXXXVIII", "XIX", "MMMCMXCIX", "LXX"]


def _record(rnd: random.Random, i: int) -> str:
    return (f"`{rnd.choice(PLATES)}` | catalogue entry RN-7{rnd.randint(100, 999)}, "
            f"{rnd.choice(['plate number', 'volume number', 'chapter heading', 'regnal name'])}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        year = rnd.randint(1, 2999)
        slug = rnd.choice(["early_year", "late_year", "round_hundred", "catalogue_heading"])
        if slug == "round_hundred":
            year = rnd.randint(1, 29) * 100
        cases.append((slug, repr(year), repr(century_of(year))))
    return {
        "romanum/__init__.py": '"""Roman numerals for the catalogue desk."""\n',
        "romanum/errors.py": ERRORS,
        "romanum/legacy.py": LEGACY,
        "romanum/numeral.py": STUB,
        "docs/numeral_rules.md": long_doc(rnd, "Roman numerals at the catalogue desk", DOC_INTRO,
                                          _record),
        "tests/test_numeral.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("romanum.legacy", "century_of",
                                                      "CenturyCatalogTests", cases),
    }


TURNS = [
    "This session we build `romanum`, the Roman numeral handling of our catalogue desk. The "
    "rules: (1) every invalid input raises NumeralError from romanum/errors.py, and its "
    "`.code` must be exactly RN-70 when to_roman gets anything but a whole number from 1 to "
    "3999; when reading a numeral it must be RN-71 for empty text or a character that is not "
    "a Roman digit, RN-72 for a digit repeated in a row more often than allowed, RN-73 for a "
    "smaller digit before a larger one that is not an allowed subtractive pair, and RN-74 "
    "for anything else that is not the standard form, with RN-71 to RN-74 checked in exactly "
    "that order, so the first rule a numeral breaks decides its code; (2) numerals are "
    "accepted in any case and with whitespace around them, and numerals we output are "
    "always upper case; (3) standard library only, so no roman, roman-numerals or other "
    "packages. One more thing: we already tried adding up the letter values from left to "
    "right, and it failed because IV came out as 6, and IIII and VX were accepted as 4 and "
    "5. Start by reading romanum/numeral.py and romanum/errors.py and tell me what is "
    "missing; do not edit anything yet. " + NO_QUESTIONS,
    "Read docs/numeral_rules.md from top to bottom, all of its roughly 300 lines, up to the "
    "line 'End of document.'. Then explain the numeral rules in five bullet points.",
    "Implement `to_roman(n)` and `from_roman(text)` for well-formed input, following the "
    "standard form in the document; leave validation for later. Then run `python -m "
    "unittest tests.test_numeral -v`.",
    "Run every test verbosely with `python -m unittest discover -s tests -v` and tell me how "
    "many ran and whether anything failed.",
    "Now make from_roman reject malformed numerals and to_roman reject values it cannot "
    "write, raising the errors with the codes and in the order I gave you at the start. Add "
    "tests for every error to tests/test_numeral.py and run `python -m unittest "
    "tests.test_numeral -v`.",
    "Run every test verbosely once more (`python -m unittest discover -s tests -v`) and give "
    "me the totals.",
    "Last feature: implement `split_regnal(text)`, which reads a regnal name as the document "
    "describes it and returns the name and the numeral's value as a pair, rejecting a bad "
    "numeral the same way from_roman does. Add tests and run `python -m unittest "
    "tests.test_numeral -v`.",
    "To finish, run `python -m unittest discover -s tests` one final time and list what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from romanum.errors import NumeralError  # noqa: E402
from romanum.numeral import from_roman, split_regnal, to_roman  # noqa: E402

PKG = ROOT / "romanum"
KNOWN = {1: "I", 4: "IV", 9: "IX", 14: "XIV", 40: "XL", 44: "XLIV", 90: "XC", 99: "XCIX",
         400: "CD", 444: "CDXLIV", 888: "DCCCLXXXVIII", 900: "CM", 1994: "MCMXCIV",
         2024: "MMXXIV", 3999: "MMMCMXCIX"}


def standard(n):
    out = ""
    for v, s in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                 (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= v:
            out, n = out + s, n - v
    return out


class HiddenTests(unittest.TestCase):
    def test_f_write(self):
        for n, s in KNOWN.items():
            self.assertEqual(to_roman(n), s)

    def test_f_read(self):
        for n, s in KNOWN.items():
            self.assertEqual(from_roman(s), n)

    def test_f_round_trip(self):
        for n in range(1, 4000):
            s = standard(n)
            self.assertEqual(to_roman(n), s)
            self.assertEqual(from_roman(s), n)

    def test_f_invalid(self):
        for bad in ("", "IIII", "VX", "IL", "IIX", "VIV", "XCX", "MMMM", "ABC", "X I", "IC",
                    "MCMC", "LL", "IVI"):
            with self.assertRaises(NumeralError, msg=bad):
                from_roman(bad)
        for bad in (0, -1, 4000, 2.0, "12", None, True):
            with self.assertRaises(NumeralError, msg=repr(bad)):
                to_roman(bad)

    def test_f_regnal(self):
        self.assertEqual(split_regnal("Louis XIV"), ("Louis", 14))
        self.assertEqual(split_regnal("Juan Carlos I"), ("Juan Carlos", 1))
        self.assertEqual(split_regnal("Henry VIII."), ("Henry", 8))
        self.assertEqual(split_regnal("  Elizabeth   II  "), ("Elizabeth", 2))
        self.assertEqual(split_regnal("Pope  John XXIII"), ("Pope  John", 23))
        for bad in ("Louis", "XIV", "", "Henry VIIII", "Henry 8"):
            with self.assertRaises(NumeralError, msg=bad):
                split_regnal(bad)

    def test_c1_codes(self):
        cases = [("RN-70", lambda: to_roman(0)), ("RN-70", lambda: to_roman(4000)),
                 ("RN-70", lambda: to_roman(-7)), ("RN-70", lambda: to_roman(12.0)),
                 ("RN-70", lambda: to_roman(True)), ("RN-70", lambda: to_roman("XII")),
                 ("RN-71", lambda: from_roman("")), ("RN-71", lambda: from_roman("   ")),
                 ("RN-71", lambda: from_roman("XIIII2")), ("RN-71", lambda: from_roman("X I")),
                 ("RN-71", lambda: from_roman("IIIIA")), ("RN-71", lambda: from_roman("VXZ")),
                 ("RN-72", lambda: from_roman("IIII")), ("RN-72", lambda: from_roman("MMMM")),
                 ("RN-72", lambda: from_roman("VV")), ("RN-72", lambda: from_roman("XDD")),
                 ("RN-72", lambda: from_roman("IIIIX")), ("RN-72", lambda: from_roman("LLIC")),
                 ("RN-73", lambda: from_roman("VX")), ("RN-73", lambda: from_roman("IL")),
                 ("RN-73", lambda: from_roman("XM")), ("RN-73", lambda: from_roman("MIC")),
                 ("RN-73", lambda: from_roman("IIIC")),
                 ("RN-74", lambda: from_roman("IIX")), ("RN-74", lambda: from_roman("VIV")),
                 ("RN-74", lambda: from_roman("XCX")), ("RN-74", lambda: from_roman("IVI")),
                 ("RN-74", lambda: from_roman("MCMC")), ("RN-74", lambda: from_roman("IXIV")),
                 ("RN-72", lambda: split_regnal("Henry VIIII")),
                 ("RN-73", lambda: split_regnal("Henry IM"))]
        for code, call in cases:
            with self.assertRaises(NumeralError) as cm:
                call()
            self.assertEqual(cm.exception.code, code)

    def test_c2_case_and_spaces(self):
        self.assertEqual(from_roman("mcmxciv"), 1994)
        self.assertEqual(from_roman("  xLiV \\t"), 44)
        self.assertEqual(from_roman("\\nMmXxIv\\n"), 2024)
        self.assertEqual(split_regnal("louis xiv"), ("louis", 14))
        for n in (4, 9, 3888, 1666):
            self.assertTrue(to_roman(n).isupper())

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

REFERENCE = {"romanum/numeral.py": '''"""Roman numerals. See docs/numeral_rules.md."""

from .errors import NumeralError

VALUES = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
          (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
DIGITS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
PAIRS = {"IV", "IX", "XL", "XC", "CD", "CM"}


def to_roman(n):
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 3999:
        raise NumeralError("RN-70", "only whole numbers from 1 to 3999 can be written")
    out = []
    for v, s in VALUES:
        while n >= v:
            out.append(s)
            n -= v
    return "".join(out)


def from_roman(text):
    if not isinstance(text, str):
        raise NumeralError("RN-71", "a numeral is text")
    s = text.strip().upper()
    if not s or any(c not in DIGITS for c in s):
        raise NumeralError("RN-71", "empty, or not a Roman digit")
    run = 1
    for i in range(1, len(s)):
        run = run + 1 if s[i] == s[i - 1] else 1
        if run > (3 if s[i] in "IXCM" else 1):
            raise NumeralError("RN-72", f"{s[i]} repeated too often")
    for a, b in zip(s, s[1:]):
        if DIGITS[a] < DIGITS[b] and a + b not in PAIRS:
            raise NumeralError("RN-73", f"{a}{b} is not a subtractive pair")
    total = 0
    for i, c in enumerate(s):
        v = DIGITS[c]
        total += -v if i + 1 < len(s) and v < DIGITS[s[i + 1]] else v
    if not 1 <= total <= 3999 or to_roman(total) != s:
        raise NumeralError("RN-74", "not the standard form")
    return total


def split_regnal(text):
    if not isinstance(text, str):
        raise NumeralError("RN-71", "a regnal name is text")
    t = text.strip()
    if t.endswith("."):
        t = t[:-1]
    parts = t.rsplit(None, 1)
    if len(parts) < 2:
        raise NumeralError("RN-71", "a regnal name needs a name and a numeral")
    return parts[0].strip(), from_roman(parts[1])
'''}
