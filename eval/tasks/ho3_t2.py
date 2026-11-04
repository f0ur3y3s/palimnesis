"""ho3-t2: phone numbers to E.164 and contact sheets (third held-out task set).

A1 categories: a superseded decision with conflicting evidence (turn 1 asks for
`` ext. `` extensions; turn 5, after the restart, switches to ``;ext=``, while the reference
document's house style and the visible test still say `` ext. ``); vague references and
"continue" (turn 7: "carry on with the sheet side ... the rules we agreed on"); several
distant facts needed together in turn 7 (C1 and C2 from turn 1, the extension decision from
turn 5, the contact-line, comment and ``@region`` rules from the document read in turn 2);
an oversized read; restart before turn 5.
"""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho3-t2"
SET = "heldout3"
TITLE = "dialkit: normalize phone numbers to E.164 and rewrite contact sheets"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "separators in the input (spaces, dots, dashes and parentheses) are dropped; the "
          "number in the output is '+', the country code and the national significant number, "
          "digits only, followed by the extension when there is one",
    "C2": "in a contact sheet, every line that is not a contact line, and the name side of "
          "every contact line, comes out byte for byte unchanged",
    "C3": "an unreadable number raises DialError from dialkit/errors.py with the original "
          "text, exactly as given, in .raw; it is never passed through unchanged",
}
TRAP = ("already tried stripping every non-digit and putting +44 in front; it failed because "
        "numbers that were already international got their country code twice, the trunk 0 "
        "stayed in, and extensions were glued onto the end of the number")

SUPERSEDED = " ext. "  # turn 1's extension style; turn 5 replaces it with ";ext="

KEYPAD = {c: str(d) for d, letters in ((2, "ABC"), (3, "DEF"), (4, "GHI"), (5, "JKL"),
                                       (6, "MNO"), (7, "PQRS"), (8, "TUV"), (9, "WXYZ"))
          for c in letters}


def vanity_digits(word: str) -> str:
    return "".join(KEYPAD.get(c, c) for c in word.upper())


LEGACY = '''"""Vanity numbers for the advert printer (do not change)."""

KEYPAD = {c: str(d) for d, letters in ((2, "ABC"), (3, "DEF"), (4, "GHI"), (5, "JKL"),
                                       (6, "MNO"), (7, "PQRS"), (8, "TUV"), (9, "WXYZ"))
          for c in letters}


def vanity_digits(word: str) -> str:
    return "".join(KEYPAD.get(c, c) for c in word.upper())
'''

ERRORS = '''"""Errors."""


class DialError(ValueError):
    """A phone number that cannot be read. ``raw`` is the text as it was given."""

    def __init__(self, raw, reason="unreadable number"):
        super().__init__(f"{raw!r}: {reason}")
        self.raw = raw
'''

STUB = '''"""Phone numbers in E.164 form. See docs/dialling_plan.md."""

from .errors import DialError  # noqa: F401


def to_e164(raw, region="GB"):
    """``("020 7946 0958", "GB")`` -> ``"+442079460958"``."""
    raise NotImplementedError


def rewrite_sheet(text, region="GB"):
    """Rewrite the number of every contact line of a contact sheet."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dialkit.numbers import to_e164  # noqa: E402


class E164Tests(unittest.TestCase):
    def test_national(self):
        self.assertEqual(to_e164("020 7946 0958", "GB"), "+442079460958")

    def test_international(self):
        self.assertEqual(to_e164("+33 1 42 68 53 00", "GB"), "+33142685300")

    def test_house_style_extension(self):
        self.assertEqual(to_e164("020 7946 0958 x12", "GB"), "+442079460958 ext. 12")
'''

DOC_INTRO = [
    "How the front office writes the telephone numbers in its contact sheets.",
    "",
    "## Regions",
    "",
    "| region | country code | trunk prefix | national significant number |",
    "|---|---|---|---|",
    "| GB | 44 | 0 | 10 digits |",
    "| IE | 353 | 0 | 9 digits |",
    "| FR | 33 | 0 | 9 digits |",
    "| NL | 31 | 0 | 9 digits |",
    "| DE | 49 | 0 | 10 or 11 digits |",
    "| NO | 47 | none | 8 digits |",
    "",
    "## Reading a number",
    "",
    "- International form: `+` or `00`, then the country code, then the national significant",
    "  number (NSN). The country code is found from the table; any other is unknown. A `(0)`",
    "  written right after the country code (`+44 (0)20 7946 0958`) is dropped.",
    "- National form: the region's trunk prefix, then the NSN; the region is the caller's",
    "  default region. In a region without a trunk prefix the national form is the NSN alone.",
    "- Spaces, dots, dashes and parentheses may separate digits anywhere.",
    "- An extension may follow the number: `x`, `ext`, `ext.` or `#` (any case), optional",
    "  spaces, then 1 to 6 digits.",
    "",
    "## Writing a number",
    "",
    "- E.164: `+`, the country code and the NSN, with no separators: `+442079460958`.",
    "",
    "## Contact sheets",
    "",
    "- A contact line contains the separator ` :: ` (space, two colons, space) exactly once:",
    "  the name side before it, the number after it. When a sheet is rewritten, only the",
    "  number side changes; whitespace around the number is dropped.",
    "- A line whose first non-blank character is `#` is a comment, even when it contains",
    "  ` :: `.",
    "- A line `@region XX` sets the default region for the contact lines below it, until the",
    "  next such line. It stays in the sheet unchanged.",
    "- Every other line is a note and stays as it is.",
    "",
    "## House style (2018)",
    "",
    "- Extensions are written after the number as ` ext. ` and the digits:",
    "  `+442079460958 ext. 12`.",
]

SAMPLES = ["020 7946 0958", "+44 20 7946 0000", "01 42 68 53 00", "087 123 4567",
           "22 33 44 55", "030 12345678", "020-1234567", "0151 12345678", "+47 22 33 44 55"]
OFFICES = ["Leeds", "Cork", "Lyon", "Utrecht", "Bremen", "Bergen", "Bristol", "Nantes"]


def _record(rnd: random.Random, i: int) -> str:
    return (f"`{rnd.choice(OFFICES)} desk :: {rnd.choice(SAMPLES)}` | "
            f"{rnd.choice(['2019', '2021', '2023'])} sheet, old PBX ext {rnd.randint(10, 999)}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    words = ["FLOWERS", "taxi", "Call-NOW", "1800 PIZZA", "help", "QUOTE", "go2bed", "Rx-7"]
    for _ in range(CATALOG_TESTS):
        w = rnd.choice(words) + rnd.choice(["", "S", "-24", " now", "9"])
        slug = rnd.choice(["upper_word", "mixed_case", "with_digits", "advert_line"])
        cases.append((slug, repr(w), repr(vanity_digits(w))))
    return {
        "dialkit/__init__.py": '"""Telephone numbers for the front office."""\n',
        "dialkit/errors.py": ERRORS,
        "dialkit/legacy.py": LEGACY,
        "dialkit/numbers.py": STUB,
        "docs/dialling_plan.md": long_doc(rnd, "Telephone numbers in contact sheets", DOC_INTRO,
                                          _record),
        "sheets/offices.txt": "# front office contacts\nReception :: 020 7946 0958\n"
                              "Night desk :: +44 (0)20 7946 0000 x4\n\n@region NO\n"
                              "Oslo branch :: 22 33 44 55\ncall Oslo before 9\n",
        "tests/test_numbers.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("dialkit.legacy", "vanity_digits",
                                                      "VanityDigitsCatalogTests", cases),
    }


TURNS = [
    "Today's work is `dialkit`, which normalizes the phone numbers in our front office's "
    "contact sheets. Rules: (1) separators in the input (spaces, dots, dashes and "
    "parentheses) are dropped, and the number in the output is '+', the country code and "
    "the national significant number, digits only, followed by the extension when there is "
    "one; (2) in a contact sheet, every line that is not a contact line, and the name side of "
    "every contact line, comes out byte for byte unchanged; (3) an unreadable number raises "
    "DialError from dialkit/errors.py with the original text, exactly as given, in `.raw`, and "
    "is never passed through. For now, write an extension as ' ext. ' and its digits after "
    "the number (+442079460958 ext. 12). We already tried stripping every non-digit and "
    "putting +44 in front, and it failed because numbers that were already international got "
    "their country code twice, the trunk 0 stayed in, and extensions were glued onto the end "
    "of the number. First read dialkit/numbers.py and dialkit/errors.py and tell me what has "
    "to be written; no edits yet. " + NO_QUESTIONS,
    "Read docs/dialling_plan.md from beginning to end, all of its roughly 300 lines, until the "
    "line 'End of document.'. Then summarize how numbers are read and written in five bullet "
    "points.",
    "Implement `to_e164(raw, region)`: international and national forms and extensions, as "
    "the document describes. Then run `python -m unittest tests.test_numbers -v`.",
    "Run the complete suite verbosely with `python -m unittest discover -s tests -v` and tell "
    "me how many tests ran and which failed.",
    "Change of plan from the switchboard team: their import reads RFC 3966 style. From now "
    "on every extension in the output is written as ';ext=' and its digits, with no spaces "
    "(+442079460958;ext=12), whatever the input used and whatever older notes say; the "
    "earlier extension rule no longer applies. Update to_e164 and the tests to match, then run "
    "`python -m unittest tests.test_numbers -v`.",
    "Run the complete suite verbosely again (`python -m unittest discover -s tests -v`) and "
    "give me the totals.",
    "Carry on with the sheet side: implement `rewrite_sheet(text, region)` so a whole contact "
    "sheet such as sheets/offices.txt comes out with every number rewritten, following the "
    "rules we agreed on and the sheet conventions in the document. Add tests to "
    "tests/test_numbers.py and run `python -m unittest tests.test_numbers -v`.",
    "Wrap up: run `python -m unittest discover -s tests` a last time and list what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dialkit.errors import DialError  # noqa: E402
from dialkit.numbers import rewrite_sheet, to_e164  # noqa: E402

SHEET = ("# front office contacts\\n"
         "Reception :: 020 7946 0958\\n"
         "  Night desk :: +44 (0)20 7946 0000 x4  \\n"
         "\\n"
         "@region NO\\n"
         "Oslo branch :: 22 33 44 55\\n"
         "call Oslo before 9\\n")
WANT = ("# front office contacts\\n"
        "Reception :: +442079460958\\n"
        "  Night desk :: +442079460000;ext=4\\n"
        "\\n"
        "@region NO\\n"
        "Oslo branch :: +4722334455\\n"
        "call Oslo before 9\\n")


class HiddenTests(unittest.TestCase):
    def test_f_numbers(self):
        for raw, region, want in (("020 7946 0958", "GB", "+442079460958"),
                                  ("+44 (0)20 7946 0958", "FR", "+442079460958"),
                                  ("0044 20 7946 0958", "GB", "+442079460958"),
                                  ("01 42 68 53 00", "FR", "+33142685300"),
                                  ("+33 1 42 68 53 00", "GB", "+33142685300"),
                                  ("087 123 4567", "IE", "+353871234567"),
                                  ("00353 87 123 4567", "NO", "+353871234567"),
                                  ("22 33 44 55", "NO", "+4722334455"),
                                  ("+47 22.33.44.55", "GB", "+4722334455"),
                                  ("030 12345678", "DE", "+493012345678"),
                                  ("0151 12345678", "DE", "+4915112345678"),
                                  ("020-1234567", "NL", "+31201234567")):
            self.assertEqual(to_e164(raw, region), want, (raw, region))

    def test_f_extensions(self):
        for raw, want in (("020 7946 0958 x12", "+442079460958;ext=12"),
                          ("+44 20 7946 0958 ext. 7", "+442079460958;ext=7"),
                          ("020 7946 0958 EXT 345", "+442079460958;ext=345"),
                          ("020 7946 0958#9", "+442079460958;ext=9"),
                          ("020 7946 0958 X 123456", "+442079460958;ext=123456")):
            self.assertEqual(to_e164(raw, "GB"), want, raw)

    def test_f_sheet(self):
        self.assertEqual(rewrite_sheet(SHEET, "GB"), WANT)
        self.assertEqual(rewrite_sheet("Lyon :: 01 42 68 53 00\\n", "FR"), "Lyon :: +33142685300\\n")
        self.assertEqual(rewrite_sheet("@region IE\\nCork :: 087 123 4567\\n@region GB\\n"
                                       "Leeds :: 020 7946 0958 #5\\n", "FR"),
                         "@region IE\\nCork :: +353871234567\\n@region GB\\n"
                         "Leeds :: +442079460958;ext=5\\n")

    def test_c1_separators(self):
        forms = ["020 7946 0958", "020-7946-0958", "(020) 7946 0958", "020.7946.0958",
                 "0 2 0 7 9 4 6 0 9 5 8", "+44 (0) 20-7946-0958", "+44.20.7946.0958"]
        for raw in forms:
            out = to_e164(raw, "GB")
            self.assertEqual(out, "+442079460958", raw)
        out = to_e164("(020) 7946-0958 ext 77", "GB")
        number = out.split(";")[0]
        self.assertTrue(number.startswith("+") and number[1:].isdigit(), out)

    def test_c2_lines_unchanged(self):
        lines = ["Name with no number", "  # old desk :: 020 7946 0958", "a :: b :: c", "",
                 "   ", "\\t", "Reception::020 7946 0958", "notes :: are not :: numbers"]
        for line in lines:
            self.assertEqual(rewrite_sheet(line + "\\n", "GB"), line + "\\n", repr(line))
        self.assertEqual(rewrite_sheet("  Dr. O\\u2019Brien (home)\\t :: 087 123 4567\\n", "IE"),
                         "  Dr. O\\u2019Brien (home)\\t :: +353871234567\\n")
        self.assertEqual(rewrite_sheet("x\\r\\nBo :: 22334455\\r\\n", "NO"),
                         "x\\r\\nBo :: +4722334455\\r\\n")

    def test_c3_errors(self):
        for raw in ("020 7946 095", "+99 1234 5678", "020 7946 0958 x", "020 7946 09a8",
                    "7946 0958", "", "  +44 20 7946 0958 ext 1234567", "+44 20 7946 095"):
            with self.assertRaises(DialError, msg=raw) as cm:
                to_e164(raw, "GB")
            self.assertEqual(cm.exception.raw, raw)
        with self.assertRaises(DialError):
            rewrite_sheet("Desk :: 12\\n", "GB")


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"dialkit/numbers.py": '''"""Phone numbers in E.164 form. See docs/dialling_plan.md."""

import re

from .errors import DialError

REGIONS = {"GB": ("44", "0", (10,)), "IE": ("353", "0", (9,)), "FR": ("33", "0", (9,)),
           "NL": ("31", "0", (9,)), "DE": ("49", "0", (10, 11)), "NO": ("47", "", (8,))}
EXT = re.compile(r"(?i)\\s*(?:ext\\.?|x|#)\\s*([0-9]{1,6})\\s*$")
SEPARATORS = " .-()"


def to_e164(raw, region="GB"):
    if not isinstance(raw, str):
        raise DialError(raw, "not text")
    text = raw.strip()
    ext = None
    m = EXT.search(text)
    if m:
        ext, text = m.group(1), text[:m.start()].strip()
    intl = text.startswith("+") or text.startswith("00")
    body = text[1:] if text.startswith("+") else text[2:] if intl else text
    if intl:
        body = body.replace("(0)", "", 1)
    if not body or any(c not in SEPARATORS and not c.isdigit() for c in body):
        raise DialError(raw, "unexpected character")
    digits = "".join(c for c in body if c in "0123456789")
    if intl:
        for cc, trunk, lengths in REGIONS.values():
            if digits.startswith(cc):
                nsn = digits[len(cc):]
                break
        else:
            raise DialError(raw, "unknown country code")
    else:
        if region not in REGIONS:
            raise DialError(raw, "unknown region")
        cc, trunk, lengths = REGIONS[region]
        if trunk and not digits.startswith(trunk):
            raise DialError(raw, "national number without trunk prefix")
        nsn = digits[len(trunk):]
    if len(nsn) not in lengths or not nsn.isdigit():
        raise DialError(raw, "wrong length")
    return "+" + cc + nsn + (f";ext={ext}" if ext else "")


def rewrite_sheet(text, region="GB"):
    out = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\\r\\n")
        end = line[len(body):]
        stripped = body.strip()
        words = stripped.split()
        if len(words) == 2 and words[0] == "@region":
            region = words[1].upper()
            out.append(line)
        elif stripped.startswith("#") or body.count(" :: ") != 1:
            out.append(line)
        else:
            name, number = body.split(" :: ")
            out.append(name + " :: " + to_e164(number.strip(), region) + end)
    return "".join(out)
'''}
