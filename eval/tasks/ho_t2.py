"""ho-t2: semantic version parsing, ordering and ranges (held-out task, D44.5)."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho-t2"
SET = "heldout"
TITLE = "verso: parse SemVer 2.0 versions, compare them, pick the best match for a range"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "ordering follows SemVer 2.0 section 11: numeric pre-release identifiers compare "
          "numerically and sort before alphanumeric ones, a release sorts after its "
          "pre-releases, build metadata is ignored",
    "C2": "invalid versions raise InvalidVersion from verso/errors.py; no None or -1 sentinels",
    "C3": "standard library only: no packaging, semver or other packages",
}
TRAP = ("already tried tuple(map(int, v.split('.'))); it failed on '1.0.0-rc.1' and "
        "'2.0.0+build.7'")


def zero_pad(n: int, width: int) -> str:
    return str(n).rjust(width, "0")


LEGACY = '''"""Formatting helpers for release notes (do not change)."""


def zero_pad(n: int, width: int) -> str:
    return str(n).rjust(width, "0")
'''

ERRORS = '''"""Errors."""


class InvalidVersion(ValueError):
    """Text that is not a SemVer 2.0 version."""
'''

STUB = '''"""SemVer 2.0 versions. See docs/semver_notes.md."""

from __future__ import annotations

from typing import NamedTuple

from .errors import InvalidVersion  # noqa: F401


class Version(NamedTuple):
    major: int
    minor: int
    patch: int
    pre: tuple = ()
    build: str = ""


def parse(text: str) -> Version:
    """``"1.2.3-rc.1+b7"`` -> Version(1, 2, 3, ("rc", 1), "b7")."""
    raise NotImplementedError


def compare(a: str, b: str) -> int:
    """-1, 0 or 1 as version ``a`` sorts before, with or after ``b``."""
    raise NotImplementedError


def max_satisfying(versions: list[str], spec: str) -> str | None:
    """The highest of ``versions`` inside ``spec`` (``^1.2.0``, ``~1.2.0`` or ``1.2.0``)."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from verso.version import Version, compare, parse  # noqa: E402


class VersionTests(unittest.TestCase):
    def test_parse_release(self):
        self.assertEqual(parse("1.2.3"), Version(1, 2, 3))

    def test_parse_prerelease(self):
        self.assertEqual(parse("1.0.0-rc.1+b7"), Version(1, 0, 0, ("rc", 1), "b7"))

    def test_release_after_prerelease(self):
        self.assertEqual(compare("1.0.0-rc.1", "1.0.0"), -1)
'''

DOC_INTRO = [
    "Notes on the version strings our release tooling handles (SemVer 2.0).",
    "",
    "## Shape",
    "",
    "- `MAJOR.MINOR.PATCH`, three non-negative integers without leading zeros.",
    "- An optional pre-release after `-`: dot-separated identifiers of ASCII letters, digits",
    "  and hyphens; numeric identifiers have no leading zeros.",
    "- Optional build metadata after `+`: dot-separated identifiers of the same characters.",
    "",
    "## Ranges",
    "",
    "- `^1.2.3` allows 1.2.3 up to, not including, 2.0.0 (for 0.x: `^0.2.3` stops before",
    "  0.3.0).",
    "- `~1.2.3` allows 1.2.3 up to, not including, 1.3.0.",
    "- A bare version matches only itself (build metadata ignored).",
    "- Pre-release versions never satisfy a range unless the range names a pre-release",
    "  of the same major.minor.patch.",
]


def _record(rnd: random.Random, i: int) -> str:
    v = f"{rnd.randint(0, 9)}.{rnd.randint(0, 20)}.{rnd.randint(0, 40)}"
    if rnd.random() < 0.4:
        v += "-" + rnd.choice(["alpha", "beta", "rc"]) + f".{rnd.randint(1, 12)}"
    if rnd.random() < 0.2:
        v += f"+build.{rnd.randint(1, 999)}"
    return f"`{v}` | seen in release notes batch {rnd.randint(1, 60)}"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        n, w = rnd.randint(0, 99999), rnd.randint(1, 8)
        slug = rnd.choice(["short_number", "wide_column", "release_note_id", "exact_width"])
        cases.append((slug, f"{n}, {w}", repr(zero_pad(n, w))))
    return {
        "verso/__init__.py": '"""Version handling for the release tooling."""\n',
        "verso/errors.py": ERRORS,
        "verso/legacy.py": LEGACY,
        "verso/version.py": STUB,
        "docs/semver_notes.md": long_doc(rnd, "Version notes", DOC_INTRO, _record),
        "tests/test_version.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("verso.legacy", "zero_pad",
                                                      "ZeroPadCatalogTests", cases),
    }


TURNS = [
    "Today's work is `verso`, the version module of our release tooling. Constraints: (1) "
    "ordering follows SemVer 2.0 section 11 exactly: numeric pre-release identifiers compare "
    "as numbers and sort before alphanumeric ones, a release sorts after all of its "
    "pre-releases, and build metadata is ignored when comparing; (2) invalid versions raise "
    "InvalidVersion from verso/errors.py, never a None or -1 sentinel; (3) standard library "
    "only, so no packaging, semver or any other package. Note that we already tried "
    "tuple(map(int, v.split('.'))), and it failed on '1.0.0-rc.1' and '2.0.0+build.7'. First "
    "read verso/version.py and verso/errors.py and tell me what has to be written; don't edit "
    "anything yet. " + NO_QUESTIONS,
    "Now read docs/semver_notes.md end to end, all of its roughly 300 lines, down to the line "
    "'End of document.', and sum it up in five bullet points.",
    "Write `parse(text)`: major, minor and patch as ints, the pre-release as a tuple (numeric "
    "identifiers as ints, the others as strings), the build metadata as a string. Run "
    "`python -m unittest tests.test_version -v`; the comparison test may still fail.",
    "Run all tests verbosely with `python -m unittest discover -s tests -v` and tell me how "
    "many ran and which failed.",
    "Write `compare(a, b)` returning -1, 0 or 1. Then run "
    "`python -m unittest tests.test_version -v`.",
    "Run all tests verbosely once more (`python -m unittest discover -s tests -v`) and give me "
    "the totals.",
    "Write `max_satisfying(versions, spec)` for the range forms in docs/semver_notes.md (`^`, "
    "`~` and a bare version): return the highest matching version string, or None when none "
    "matches. Add tests for compare and max_satisfying to tests/test_version.py and run that "
    "module.",
    "Finish: run `python -m unittest discover -s tests` a final time and summarize your "
    "changes.",
]

HIDDEN = {"_check/test_hidden.py": '''import ast
import functools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from verso.errors import InvalidVersion  # noqa: E402
from verso.version import Version, compare, max_satisfying, parse  # noqa: E402

SOURCE = (ROOT / "verso" / "version.py").read_text(encoding="utf-8")
ORDER = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2",
         "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0", "1.0.1", "1.1.0", "2.0.0-rc.1", "2.0.0"]


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(parse("1.2.3"), Version(1, 2, 3))
        self.assertEqual(parse("1.0.0-rc.1+b7"), Version(1, 0, 0, ("rc", 1), "b7"))
        self.assertEqual(parse("2.0.0+build.7"), Version(2, 0, 0, (), "build.7"))
        self.assertEqual(parse("1.0.0-x-y.0"), Version(1, 0, 0, ("x-y", 0), ""))

    def test_f_compare_basic(self):
        self.assertEqual(compare("1.2.3", "1.2.4"), -1)
        self.assertEqual(compare("1.10.0", "1.9.0"), 1)
        self.assertEqual(compare("1.2.3", "1.2.3"), 0)

    def test_f_max_satisfying(self):
        vs = ["1.2.0", "1.2.9", "1.3.0", "1.9.9", "2.0.0", "2.0.0-rc.1", "0.2.5", "0.3.1"]
        self.assertEqual(max_satisfying(vs, "^1.2.0"), "1.9.9")
        self.assertEqual(max_satisfying(vs, "~1.2.0"), "1.2.9")
        self.assertEqual(max_satisfying(vs, "^0.2.0"), "0.2.5")
        self.assertEqual(max_satisfying(vs, "1.3.0"), "1.3.0")
        self.assertIsNone(max_satisfying(vs, "^3.0.0"))
        self.assertEqual(max_satisfying(["2.0.0-rc.1", "1.0.0"], "^1.0.0"), "1.0.0")

    def test_c1_precedence(self):
        for i, a in enumerate(ORDER):
            for j, b in enumerate(ORDER):
                self.assertEqual(compare(a, b), (i > j) - (i < j), (a, b))
        self.assertEqual(compare("1.0.0+a", "1.0.0+b"), 0)
        self.assertEqual(sorted(reversed(ORDER), key=functools.cmp_to_key(compare)), ORDER)

    def test_c2_invalid(self):
        for text in ("1.2", "1.2.3.4", "01.2.3", "1.2.3-", "1.2.3-01", "a.b.c", "", "1.2.3+"):
            with self.assertRaises(InvalidVersion, msg=text):
                parse(text)
        with self.assertRaises(InvalidVersion):
            compare("1.2", "1.2.0")

    def test_c3_stdlib_only(self):
        for node in ast.walk(ast.parse(SOURCE)):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            for n in names:
                self.assertIn(n.split(".")[0], sys.stdlib_module_names, n)


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"verso/version.py": '''"""SemVer 2.0 versions. See docs/semver_notes.md."""

from __future__ import annotations

import re
from typing import NamedTuple

from .errors import InvalidVersion

NUM = r"(0|[1-9]\\d*)"
IDENT = r"(?:0|[1-9]\\d*|\\d*[A-Za-z-][0-9A-Za-z-]*)"
PATTERN = re.compile(rf"^{NUM}\\.{NUM}\\.{NUM}(?:-({IDENT}(?:\\.{IDENT})*))?"
                     r"(?:\\+([0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*))?$")


class Version(NamedTuple):
    major: int
    minor: int
    patch: int
    pre: tuple = ()
    build: str = ""


def parse(text: str) -> Version:
    m = PATTERN.match(text or "")
    if not m:
        raise InvalidVersion(text)
    pre = tuple(int(p) if p.isdigit() else p for p in m.group(4).split(".")) if m.group(4) else ()
    return Version(int(m.group(1)), int(m.group(2)), int(m.group(3)), pre, m.group(5) or "")


def _key(v: Version):
    pre = tuple((0, p, "") if isinstance(p, int) else (1, 0, p) for p in v.pre)
    return (v.major, v.minor, v.patch, 0 if v.pre else 1, pre)


def compare(a: str, b: str) -> int:
    ka, kb = _key(parse(a)), _key(parse(b))
    return (ka > kb) - (ka < kb)


def max_satisfying(versions: list[str], spec: str) -> str | None:
    op = spec[0] if spec[:1] in "^~" else ""
    base = parse(spec[1:] if op else spec)
    if op == "^":
        upper = (base.major + 1, 0, 0) if base.major else (0, base.minor + 1, 0)
    elif op == "~":
        upper = (base.major, base.minor + 1, 0)
    best = None
    for text in versions:
        v = parse(text)
        if v.pre and (v.major, v.minor, v.patch) != (base.major, base.minor, base.patch):
            continue
        if op:
            ok = _key(v) >= _key(base) and (v.major, v.minor, v.patch) < upper
        else:
            ok = _key(v) == _key(base)
        if ok and (best is None or compare(text, best) > 0):
            best = text
    return best
'''}
