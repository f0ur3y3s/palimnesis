"""ho-t1: a strict duration parser and formatter (held-out task, D44.5)."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho-t1"
SET = "heldout"
TITLE = "spanparse: parse and format durations like 1h30m"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "the package must still run on Python 3.8: no match statements, no X | Y type "
          "unions, no str.removeprefix or removesuffix",
    "C2": "every invalid input raises DurationError from spanparse/errors.py, carrying the "
          "offending text in .text",
    "C3": "units are exactly w, d, h, m, s, and m always means minutes",
}
TRAP = ("already tried re.findall(r'(\\d+)([dhms])'); it failed because it silently skipped "
        "garbage such as '1h xyz 5m' and accepted '1h1h'")


def pluralize(n: int, unit: str) -> str:
    return f"{n} {unit}" + ("" if n == 1 else "s")


LEGACY = '''"""Wording helpers (used by the scheduler UI; do not change)."""


def pluralize(n: int, unit: str) -> str:
    return f"{n} {unit}" + ("" if n == 1 else "s")
'''

ERRORS = '''"""Errors."""


class DurationError(ValueError):
    """An invalid duration. ``text`` is the input that was rejected."""

    def __init__(self, text, reason):
        super().__init__(f"invalid duration {text!r}: {reason}")
        self.text = text
        self.reason = reason
'''

STUB = '''"""Durations such as ``1h30m``. See docs/duration_grammar.md."""

from typing import Optional  # noqa: F401

from .errors import DurationError  # noqa: F401


def parse_duration(text):
    """``"1h30m"`` -> 5400 (seconds)."""
    raise NotImplementedError


def format_duration(seconds):
    """5400 -> ``"1h30m"``."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spanparse.errors import DurationError  # noqa: E402
from spanparse.parse import parse_duration  # noqa: E402


class ParseTests(unittest.TestCase):
    def test_single_units(self):
        self.assertEqual(parse_duration("45s"), 45)
        self.assertEqual(parse_duration("2h"), 7200)

    def test_combined(self):
        self.assertEqual(parse_duration("1h30m"), 5400)

    def test_garbage_rejected(self):
        with self.assertRaises(DurationError):
            parse_duration("1h xyz 5m")
'''

DOC_INTRO = [
    "The duration grammar used in job schedules and timeouts.",
    "",
    "## Grammar",
    "",
    "- A duration is one or more `<number><unit>` groups with nothing between them, for",
    "  example `1h30m` or `2d4h`. Surrounding spaces are ignored.",
    "- Numbers are non-negative whole numbers in decimal.",
    "- Units, largest first: `w` (7 days), `d` (24 hours), `h`, `m` (60 seconds), `s`.",
    "- Each unit appears at most once, and units appear from largest to smallest.",
    "- The empty string is not a duration.",
    "",
    "## Formatting",
    "",
    "- Formatting writes the largest units first and leaves out zero groups: 5400 is",
    "  `1h30m`, 90061 is `1d1h1m1s`, 0 is `0s`. Negative numbers are invalid.",
]


def _record(rnd: random.Random, i: int) -> str:
    parts = [(rnd.randint(1, 6), "d"), (rnd.randint(1, 23), "h"), (rnd.randint(1, 59), "m")]
    rnd.shuffle(parts)
    keep = sorted(parts[:rnd.randint(1, 3)], key=lambda p: "dhm".index(p[1]))
    secs = sum(n * {"d": 86400, "h": 3600, "m": 60}[u] for n, u in keep)
    return f"`{''.join(f'{n}{u}' for n, u in keep)}` | {secs} seconds"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        n = rnd.choice([0, 1, 1, 2, rnd.randint(3, 500)])
        unit = rnd.choice(["second", "minute", "hour", "day", "week", "retry", "attempt"])
        slug = rnd.choice(["singular_unit", "plural_unit", "zero_count", "scheduler_label"])
        cases.append((slug, f"{n}, {unit!r}", repr(pluralize(n, unit))))
    return {
        "spanparse/__init__.py": '"""Durations for job schedules."""\n',
        "spanparse/errors.py": ERRORS,
        "spanparse/legacy.py": LEGACY,
        "spanparse/parse.py": STUB,
        "docs/duration_grammar.md": long_doc(rnd, "Duration grammar", DOC_INTRO, _record),
        "tests/test_parse.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("spanparse.legacy", "pluralize",
                                                      "PluralizeCatalogTests", cases),
    }


TURNS = [
    "This session is about `spanparse`, the parser for the durations in our job schedules. "
    "Ground rules: (1) the package must keep running on Python 3.8, so no match statements, no "
    "`X | Y` type unions and no str.removeprefix or removesuffix; (2) every invalid input "
    "raises DurationError from spanparse/errors.py, with the offending text in `.text`; (3) "
    "the units are exactly w, d, h, m and s, and m always means minutes, never months. One "
    "more thing: we already tried re.findall(r'(\\d+)([dhms])'), and it failed because it "
    "silently skipped garbage such as '1h xyz 5m' and accepted '1h1h'. To start, read "
    "spanparse/parse.py and spanparse/errors.py and tell me what is missing; no edits yet. "
    + NO_QUESTIONS,
    "Go through docs/duration_grammar.md in full, all of its roughly 300 lines, down to the "
    "line 'End of document.'. Then give me the grammar in five bullet points.",
    "Implement `parse_duration` for the simple cases: one or more number-unit groups such as "
    "`45s`, `2h` or `1h30m`. Then run `python -m unittest tests.test_parse -v`; it is fine if "
    "the garbage test still fails.",
    "Run every test verbosely with `python -m unittest discover -s tests -v` and tell me how "
    "many ran and what failed.",
    "Make `parse_duration` strict, following the grammar document: reject anything between "
    "groups, repeated units, units out of order, unknown units and the empty string. Then run "
    "`python -m unittest tests.test_parse -v`.",
    "Run every test verbosely again (`python -m unittest discover -s tests -v`) and report the "
    "numbers.",
    "Now implement `format_duration(seconds)`: largest units first, zero groups left out, `0s` "
    "for zero, and negative or non-integer input rejected. Add tests for it and for a round "
    "trip through parse_duration to tests/test_parse.py, then run that module.",
    "Wrap up: run `python -m unittest discover -s tests` one last time and list what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spanparse.errors import DurationError  # noqa: E402
from spanparse.parse import format_duration, parse_duration  # noqa: E402

PKG = ROOT / "spanparse"


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        for text, secs in (("45s", 45), ("2h", 7200), ("1h30m", 5400), ("1w", 604800),
                           ("2d4h", 187200), (" 1d1h1m1s ", 90061), ("0s", 0), ("90m", 5400)):
            self.assertEqual(parse_duration(text), secs, text)

    def test_f_parse_strict(self):
        for text in ("", "1h xyz 5m", "1h1h", "5m1h", "1x", "h", "1.5h", "1h 30m", "-1h", "10"):
            with self.assertRaises(DurationError, msg=text):
                parse_duration(text)

    def test_f_format(self):
        for secs, text in ((5400, "1h30m"), (90061, "1d1h1m1s"), (0, "0s"), (604800, "1w"),
                           (3600, "1h"), (61, "1m1s")):
            self.assertEqual(format_duration(secs), text, secs)
        for secs in (1, 59, 3601, 86399, 1209600 + 7):
            self.assertEqual(parse_duration(format_duration(secs)), secs)
        with self.assertRaises(ValueError):
            format_duration(-5)

    def test_c1_python38(self):
        for path in PKG.glob("*.py"):
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src, feature_version=(3, 8))
            for node in ast.walk(tree):
                self.assertNotIsInstance(node, getattr(ast, "Match", ()), path.name)
                ann = []
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    ann = [a.annotation for a in node.args.args + node.args.kwonlyargs] + [node.returns]
                elif isinstance(node, ast.AnnAssign):
                    ann = [node.annotation]
                for a in ann:
                    for sub in ast.walk(a) if a is not None else ():
                        self.assertFalse(isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr),
                                         f"X | Y annotation in {path.name}")
            self.assertNotIn(".removeprefix(", src)
            self.assertNotIn(".removesuffix(", src)

    def test_c2_duration_error(self):
        for text in ("1h xyz 5m", "1h1h", ""):
            with self.assertRaises(DurationError) as cm:
                parse_duration(text)
            self.assertEqual(cm.exception.text, text)

    def test_c3_units(self):
        self.assertEqual(parse_duration("1m"), 60)
        self.assertEqual(parse_duration("1w1d"), 691200)
        for text in ("1y", "1mo", "1M", "1ms"):
            with self.assertRaises(DurationError, msg=text):
                parse_duration(text)


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"spanparse/parse.py": '''"""Durations such as ``1h30m``. See docs/duration_grammar.md."""

from .errors import DurationError

UNITS = [("w", 604800), ("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]


def parse_duration(text):
    s = text.strip() if isinstance(text, str) else ""
    if not s:
        raise DurationError(text, "empty")
    total, i, last = 0, 0, -1
    while i < len(s):
        j = i
        while j < len(s) and s[j].isdigit() and s[j].isascii():
            j += 1
        if j == i or j >= len(s):
            raise DurationError(text, "expected a number followed by a unit")
        unit = s[j]
        order = [u for u, _ in UNITS]
        if unit not in order:
            raise DurationError(text, f"unknown unit {unit!r}")
        k = order.index(unit)
        if k <= last:
            raise DurationError(text, "units repeated or out of order")
        last = k
        total += int(s[i:j]) * UNITS[k][1]
        i = j + 1
    return total


def format_duration(seconds):
    if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 0:
        raise DurationError(seconds, "must be a non-negative whole number")
    if seconds == 0:
        return "0s"
    out = []
    for unit, size in UNITS:
        n, seconds = divmod(seconds, size)
        if n:
            out.append(f"{n}{unit}")
    return "".join(out)
'''}
