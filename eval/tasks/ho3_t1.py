"""ho3-t1: IBAN formats and validation with exact error codes (third held-out task set).

A1 categories: explicit identifiers and error codes (four codes and their checking order,
stated once in turn 1 and needed after the restart in turn 5, which refers to them only as
"the codes and the order I gave you"); irrelevant retrieval matches (the reference document
carries a retired error table with look-alike codes and an appendix with look-alike
``IB-4xxx`` case numbers); an oversized read (the document); restart before turn 5.
"""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho3-t1"
SET = "heldout3"
TITLE = "ibancheck: IBAN electronic and print formats, validation codes, check digits"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "every invalid input raises IbanError from ibancheck/errors.py with .code exactly "
          "IB-41 (a character not allowed at its position), IB-42 (unknown country code), "
          "IB-43 (wrong length for the country) or IB-44 (check digits do not verify), checked "
          "in that order so the first rule broken decides the code",
    "C2": "the electronic form is upper case with no spaces and the print form is upper case "
          "in groups of four separated by single spaces; input is accepted in any case and "
          "with any number of spaces",
    "C3": "standard library only: no schwifty, stdnum or other third-party packages",
}
TRAP = ("already tried int(text) % 97 straight on the account text; it failed because the "
        "letters have to become numbers first (A=10 ... Z=35) and the first four characters "
        "have to move to the end before the remainder is taken")


def statement_mask(acct: str) -> str:
    digits = acct.replace(" ", "")
    return "*" * max(len(digits) - 4, 0) + digits[-4:]


LEGACY = '''"""Masked account numbers for the printed statement (do not change)."""


def statement_mask(acct: str) -> str:
    digits = acct.replace(" ", "")
    return "*" * max(len(digits) - 4, 0) + digits[-4:]
'''

ERRORS = '''"""Errors."""


class IbanError(ValueError):
    """An invalid IBAN or BBAN. ``code`` says which rule was broken."""

    def __init__(self, code, message):
        super().__init__(f"{code}: {message}")
        self.code = code
'''

STUB = '''"""IBAN formats and validation. See docs/iban_rules.md."""

from .errors import IbanError  # noqa: F401


def to_electronic(text):
    """``"gb82 west 1234 5698 7654 32"`` -> ``"GB82WEST12345698765432"``."""
    raise NotImplementedError


def to_print(text):
    """``"GB82WEST12345698765432"`` -> ``"GB82 WEST 1234 5698 7654 32"``."""
    raise NotImplementedError


def validate(text):
    """The electronic form of a valid IBAN; IbanError otherwise."""
    raise NotImplementedError


def make_iban(country, bban):
    """``("GB", "WEST12345698765432")`` -> ``"GB82WEST12345698765432"``."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ibancheck.iban import to_electronic, to_print  # noqa: E402


class FormatTests(unittest.TestCase):
    def test_electronic(self):
        self.assertEqual(to_electronic("GB82 WEST 1234 5698 7654 32"), "GB82WEST12345698765432")

    def test_print(self):
        self.assertEqual(to_print("GB82WEST12345698765432"), "GB82 WEST 1234 5698 7654 32")
'''

DOC_INTRO = [
    "How the payments desk writes and checks International Bank Account Numbers.",
    "",
    "## Structure",
    "",
    "- An IBAN is a two-letter country code, two check digits, then the BBAN (the domestic",
    "  account number). Positions 1-2 are letters, positions 3-4 are digits, and every later",
    "  position is a letter or a digit.",
    "- The total length is fixed per country. The countries the desk handles:",
    "",
    "| country | length | | country | length |",
    "|---|---|---|---|---|",
    "| AT | 20 | | FR | 27 |",
    "| BE | 16 | | GB | 22 |",
    "| CH | 21 | | IE | 22 |",
    "| DE | 22 | | IT | 27 |",
    "| ES | 24 | | NL | 18 |",
    "| NO | 15 | | PL | 28 |",
    "",
    "- Any other country code is unknown to the desk.",
    "",
    "## Formats",
    "",
    "- Electronic format: upper case, no spaces (`GB82WEST12345698765432`).",
    "- Print format: upper case, in groups of four characters separated by one space; the",
    "  last group may be shorter (`GB82 WEST 1234 5698 7654 32`).",
    "- People type IBANs with spaces anywhere and in lower case; both are accepted. No other",
    "  separator is: a dash or a dot is a character that is not allowed.",
    "",
    "## Check digits",
    "",
    "- To verify: move the first four characters to the end, replace every letter by two",
    "  digits (A = 10, B = 11, ... Z = 35), read the result as one integer, and take it modulo",
    "  97. The IBAN verifies when the remainder is 1.",
    "- To compute the check digits for a country and a BBAN: put `00` as check digits, do the",
    "  same rearrangement and conversion, and take 98 minus the remainder modulo 97. Write the",
    "  result as two digits, with a leading zero below 10.",
    "",
    "## Retired: codes of the 2016 checker",
    "",
    "- The 2016 checker reported IB-31 for a bad length, IB-32 for a bad character and IB-35",
    "  for a failed checksum. Nothing reads these codes now.",
]

DESK_IBANS = ["GB82WEST12345698765432", "DE89370400440532013000", "NL91ABNA0417164300",
              "BE68539007547034", "FR1420041010050500013M02606", "NO9386011117947",
              "CH9300762011623852957", "AT611904300234573201", "ES9121000418450200051332"]


def _record(rnd: random.Random, i: int) -> str:
    iban = rnd.choice(DESK_IBANS)
    grouped = " ".join(iban[k:k + 4] for k in range(0, len(iban), 4))
    return (f"`{grouped}` | payee on desk case IB-4{rnd.randint(100, 999)}, "
            f"{rnd.choice(['salary run', 'supplier payment', 'refund', 'standing order'])}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        n = rnd.randint(3, 14)
        acct = "".join(rnd.choice("0123456789") for _ in range(n))
        if rnd.random() < 0.4:
            acct = " ".join(acct[k:k + 4] for k in range(0, len(acct), 4))
        slug = rnd.choice(["short_account", "long_account", "grouped_digits", "statement_line"])
        cases.append((slug, repr(acct), repr(statement_mask(acct))))
    return {
        "ibancheck/__init__.py": '"""IBAN handling for the payments desk."""\n',
        "ibancheck/errors.py": ERRORS,
        "ibancheck/legacy.py": LEGACY,
        "ibancheck/iban.py": STUB,
        "docs/iban_rules.md": long_doc(rnd, "IBANs at the payments desk", DOC_INTRO, _record),
        "tests/test_iban.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("ibancheck.legacy", "statement_mask",
                                                      "StatementMaskCatalogTests", cases),
    }


TURNS = [
    "In this session we write `ibancheck`, the IBAN handling for our payments desk. The "
    "rules: (1) every invalid input raises IbanError from ibancheck/errors.py, and its "
    "`.code` must be exactly IB-41 for a character that is not allowed at its position, "
    "IB-42 for an unknown country code, IB-43 for a length that is wrong for the country, and "
    "IB-44 when the check digits do not verify, checked in exactly that order, so the first "
    "rule an input breaks decides its code; (2) the electronic form is upper case with no "
    "spaces and the print form is upper case in groups of four separated by single spaces, "
    "while input is accepted in any case and with any number of spaces; (3) standard library "
    "only, so no schwifty, stdnum or other packages. One more thing: we already tried "
    "int(text) % 97 straight on the account text, and it failed because the letters have to "
    "become numbers first (A=10 up to Z=35) and the first four characters have to move to "
    "the end before taking the remainder. Start by reading ibancheck/iban.py and "
    "ibancheck/errors.py and tell me what is missing; do not edit anything yet. "
    + NO_QUESTIONS,
    "Read docs/iban_rules.md from top to bottom, all of its roughly 300 lines, up to the line "
    "'End of document.'. Then explain the IBAN rules in five bullet points.",
    "Implement `to_electronic(text)` and `to_print(text)` for well-formed input, following "
    "the formats in the document; leave validation for later. Then run `python -m unittest "
    "tests.test_iban -v`.",
    "Run every test verbosely with `python -m unittest discover -s tests -v` and tell me how "
    "many ran and whether anything failed.",
    "Now implement `validate(text)`, which returns the electronic form of a valid IBAN, and make "
    "to_electronic and to_print validate their input too. Use the structure, country lengths "
    "and check-digit method from the document, and raise the errors with the codes and in "
    "the order I gave you at the start. Add tests for validation and for every error to "
    "tests/test_iban.py and run `python -m unittest tests.test_iban -v`.",
    "Run every test verbosely once more (`python -m unittest discover -s tests -v`) and give "
    "me the totals.",
    "Last feature: implement `make_iban(country, bban)`, which builds a complete IBAN in electronic "
    "form from a country code and a BBAN by computing the check digits, and rejects bad input "
    "the same way validate does. Add tests and run `python -m unittest tests.test_iban -v`.",
    "To finish, run `python -m unittest discover -s tests` one final time and list what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ibancheck.errors import IbanError  # noqa: E402
from ibancheck.iban import make_iban, to_electronic, to_print, validate  # noqa: E402

PKG = ROOT / "ibancheck"
VALID = ["GB82WEST12345698765432", "DE89370400440532013000", "NL91ABNA0417164300",
         "BE68539007547034", "FR1420041010050500013M02606", "NO9386011117947",
         "CH9300762011623852957", "AT611904300234573201", "ES9121000418450200051332",
         "IT60X0542811101000000123456", "PL61109010140000071219812874", "IE29AIBK93115212345678"]


class HiddenTests(unittest.TestCase):
    def test_f_formats(self):
        self.assertEqual(to_electronic("GB82 WEST 1234 5698 7654 32"), "GB82WEST12345698765432")
        self.assertEqual(to_electronic("  NL91ABNA 0417164300 "), "NL91ABNA0417164300")
        self.assertEqual(to_print("GB82WEST12345698765432"), "GB82 WEST 1234 5698 7654 32")
        self.assertEqual(to_print("NO9386011117947"), "NO93 8601 1117 947")
        self.assertEqual(to_print("BE68 5390 0754 7034"), "BE68 5390 0754 7034")
        self.assertEqual(to_print("FR14 2004 1010 0505 0001 3M02 606"),
                         "FR14 2004 1010 0505 0001 3M02 606")

    def test_f_validate(self):
        for iban in VALID:
            self.assertEqual(validate(iban), iban)
            grouped = " ".join(iban[k:k + 4] for k in range(0, len(iban), 4))
            self.assertEqual(validate(grouped), iban)
        for bad in ("GB82WEST12345698765433", "GB82WEST1234569876543", "XX82WEST12345698765432",
                    "GB82-WEST-1234-5698-7654-32", "DE89370400440532013001"):
            with self.assertRaises(IbanError, msg=bad):
                validate(bad)
            with self.assertRaises(IbanError, msg=bad):
                to_print(bad)

    def test_f_make(self):
        self.assertEqual(make_iban("GB", "WEST12345698765432"), "GB82WEST12345698765432")
        self.assertEqual(make_iban("DE", "370400440532013000"), "DE89370400440532013000")
        self.assertEqual(make_iban("NO", "86011117947"), "NO9386011117947")
        self.assertEqual(make_iban("BE", "000000000000"), "BE54000000000000")
        self.assertEqual(make_iban("NO", "86011117943"), "NO0786011117943")
        self.assertEqual(make_iban("NL", "ABNA0417164300"), "NL91ABNA0417164300")
        for iban in VALID:
            self.assertEqual(make_iban(iban[:2], iban[4:]), iban)

    def test_f_invalid(self):
        bad = [lambda: validate("GB82WEST1234569876543"), lambda: validate("ZZ82WEST12345698765432"),
               lambda: validate("GB82WEST12345698765433"), lambda: validate("GB82WEST1234569876543!"),
               lambda: make_iban("ZZ", "123"), lambda: make_iban("GB", "WEST1234"),
               lambda: make_iban("GB", "WEST-12345698765432")]
        for call in bad:
            with self.assertRaises(IbanError):
                call()

    def test_c1_codes(self):
        cases = [("IB-41", lambda: validate("GB82WEST1234569876543!")),
                 ("IB-41", lambda: validate("GB82-WEST-1234-5698-7654-32")),
                 ("IB-41", lambda: validate("G182WEST12345698765432")),
                 ("IB-41", lambda: validate("GBX2WEST12345698765432")),
                 ("IB-41", lambda: validate("ZZ8!")),
                 ("IB-42", lambda: validate("ZZ82WEST12345698765432")),
                 ("IB-42", lambda: validate("US64SVBKUS6S3300958879")),
                 ("IB-42", lambda: validate("ZZ82")),
                 ("IB-43", lambda: validate("GB82WEST1234569876543")),
                 ("IB-43", lambda: validate("NO93860111179470")),
                 ("IB-43", lambda: validate("GB83WEST123456987654")),
                 ("IB-44", lambda: validate("GB83WEST12345698765432")),
                 ("IB-44", lambda: validate("DE89370400440532013001")),
                 ("IB-44", lambda: to_electronic("NL91ABNA0417164301")),
                 ("IB-42", lambda: make_iban("ZZ", "12345678")),
                 ("IB-41", lambda: make_iban("GB", "WEST-12345698765432")),
                 ("IB-43", lambda: make_iban("GB", "WEST1234569876543"))]
        for code, call in cases:
            with self.assertRaises(IbanError) as cm:
                call()
            self.assertEqual(cm.exception.code, code)

    def test_c2_case_and_spaces(self):
        self.assertEqual(to_electronic("gb82 west 1234 5698 7654 32"), "GB82WEST12345698765432")
        self.assertEqual(to_print("fr1420041010050500013m02606"), "FR14 2004 1010 0505 0001 3M02 606")
        self.assertEqual(validate("  ch93   0076 2011 6238 5295 7  "), "CH9300762011623852957")
        self.assertEqual(make_iban("gb", "west12345698765432"), "GB82WEST12345698765432")
        self.assertEqual(make_iban("NL", "abna 0417 1643 00"), "NL91ABNA0417164300")

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

REFERENCE = {"ibancheck/iban.py": '''"""IBAN formats and validation. See docs/iban_rules.md."""

from .errors import IbanError

LENGTHS = {"AT": 20, "BE": 16, "CH": 21, "DE": 22, "ES": 24, "FR": 27, "GB": 22, "IE": 22,
           "IT": 27, "NL": 18, "NO": 15, "PL": 28}
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIGITS = "0123456789"


def _compact(text):
    if not isinstance(text, str):
        raise IbanError("IB-41", "an IBAN is text")
    return text.replace(" ", "").upper()


def _remainder(s):
    return int("".join(str(int(c, 36)) for c in s[4:] + s[:4])) % 97


def _check_chars(s):
    for i, c in enumerate(s):
        allowed = LETTERS if i < 2 else DIGITS if i < 4 else LETTERS + DIGITS
        if c not in allowed:
            raise IbanError("IB-41", f"character {c!r} not allowed at position {i + 1}")


def validate(text):
    s = _compact(text)
    _check_chars(s)
    if len(s) < 2 or s[:2] not in LENGTHS:
        raise IbanError("IB-42", "unknown country")
    if len(s) != LENGTHS[s[:2]]:
        raise IbanError("IB-43", "wrong length for the country")
    if _remainder(s) != 1:
        raise IbanError("IB-44", "check digits do not verify")
    return s


def to_electronic(text):
    return validate(text)


def to_print(text):
    s = validate(text)
    return " ".join(s[k:k + 4] for k in range(0, len(s), 4))


def make_iban(country, bban):
    if not isinstance(country, str) or not isinstance(bban, str):
        raise IbanError("IB-41", "country and BBAN are text")
    s = _compact(country) + "00" + _compact(bban)
    _check_chars(s)
    if len(_compact(country)) != 2 or s[:2] not in LENGTHS:
        raise IbanError("IB-42", "unknown country")
    if len(s) != LENGTHS[s[:2]]:
        raise IbanError("IB-43", "wrong length for the country")
    check = 98 - _remainder(s)
    return s[:2] + f"{check:02d}" + s[4:]
'''}
