"""ho4-t2: storage sizes, read and written, and team quota sheets (fourth held-out task set).

A1 categories: a superseded decision with conflicting evidence (turn 1 asks for decimal
units, kB to TB; turn 5, after the restart, switches to binary units, KiB to TiB, while the
reference document's house style and the visible test still say decimal); vague references
and "continue" (turn 7: "carry on with the sheet side ... the rules we agreed on"); several
distant facts needed together in turn 7 (C1 and C2 from turn 1, the unit decision from
turn 5, and the size-line, comment and ``_bytes`` rules from the document read in turn 2);
an oversized read; restart before turn 5.
"""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho4-t2"
SET = "heldout4"
TITLE = "sizewise: read and write storage sizes and rewrite team quota sheets"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "parse_size returns a whole number of bytes computed without floats, so '4.35 MB' is "
          "exactly 4350000; a fraction of a byte rounds half up",
    "C2": "in a quota sheet, every line that is not a size line comes out byte for byte "
          "unchanged, and so does everything on a size line except the size itself",
    "C3": "unreadable text raises SizeError from sizewise/errors.py with .text set to the text "
          "exactly as given; nothing unreadable is ever passed through",
}
TRAP = ("already tried float(number) * 1000 ** power with int() on the result; it failed "
        "because '4.35 MB' came out as 4349999 bytes and 'KiB' was read as 1000")

SUPERSEDED = "decimal units kB..TB"  # turn 1's output units; turn 5 replaces them with KiB..TiB


def pad_label(label: str, width: int) -> str:
    return label.ljust(width)[:width]


LEGACY = '''"""Fixed-width labels for the quota printout (do not change)."""


def pad_label(label: str, width: int) -> str:
    return label.ljust(width)[:width]
'''

ERRORS = '''"""Errors."""


class SizeError(ValueError):
    """Text that is not a size. ``text`` is the input as given."""

    def __init__(self, text, message="not a size"):
        super().__init__(f"{message}: {text!r}")
        self.text = text
'''

STUB = '''"""Storage sizes. See docs/quota_style.md."""

from .errors import SizeError  # noqa: F401


def parse_size(text):
    """``"1.5 kB"`` -> ``1500``."""
    raise NotImplementedError


def format_size(n):
    """``1500`` -> the size written in the house style."""
    raise NotImplementedError


def rewrite_quota(text):
    """A whole quota sheet with every size rewritten."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sizewise.sizes import format_size, parse_size  # noqa: E402


class SizeTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_size("2 KiB"), 2048)

    def test_house_units(self):
        self.assertEqual(format_size(1500), "1.5 kB")
'''

SHEET = """# team quotas, reviewed every quarter
[team.alpha]
owner = alice
disk_quota = 5 GB
  upload_limit=1536 KiB   # per file
max_body_bytes = 2 MiB

[team.beta]
owner = bob
cache_size = 0.5 GB # shared with gamma
note = 5 GB is plenty
scratch_size =   1048575
"""

DOC_INTRO = [
    "How the platform team reads and writes storage sizes, and the quota sheets that use them.",
    "",
    "## Reading sizes",
    "",
    "- A size is a number, optional spaces, then an optional unit. Spaces around the size",
    "  are ignored. The number is digits with at most one decimal point, and a decimal point",
    "  needs digits on both sides (`.5` and `5.` are not numbers). There is no sign and there",
    "  are no thousands separators.",
    "- Decimal units: kB, MB, GB, TB are 1000, 1000^2, 1000^3 and 1000^4 bytes.",
    "- Binary units: KiB, MiB, GiB, TiB are 1024, 1024^2, 1024^3 and 1024^4 bytes.",
    "- `B`, or no unit at all, means bytes. Units are matched without regard to case, so",
    "  `kb`, `KB` and `kB` are all kilobytes and `kib` is a kibibyte.",
    "",
    "## Writing sizes (house style)",
    "",
    "- Below 1000 bytes: the whole number and ` B` (`0 B`, `999 B`).",
    "- Otherwise the largest decimal unit the size reaches, kB to TB, with at most one",
    "  decimal place, rounded half up, and a trailing `.0` dropped; one space before the",
    "  unit: 1500 is `1.5 kB`, 1000000 is `1 MB`, 1234567 is `1.2 MB`.",
    "- When rounding reaches 1000 of a unit, the next unit is used instead: 999950 is `1 MB`,",
    "  not `1000 kB`. Above that TB is kept: 1500 TB stays `1500 TB`.",
    "",
    "## Quota sheets",
    "",
    "- A quota sheet is text with one setting per line, `key = value`, with optional spaces",
    "  around `=` and optional indentation. Keys are letters, digits, `_`, `.` and `-`.",
    "- Only keys ending in `_size`, `_limit`, `_quota` or `_bytes` hold sizes; those lines",
    "  are size lines. Every other line (other keys, `[section]` headers, comments, blank",
    "  lines) is not a size line.",
    "- On a size line, a `#` preceded by whitespace starts a comment that runs to the end of",
    "  the line.",
    "- Rewriting a sheet writes each size in the house style. Keys ending in `_bytes` are the",
    "  exception: their size is written as the plain whole number of bytes, no unit",
    "  (`max_body_bytes = 2 MiB` becomes `max_body_bytes = 2097152`).",
    "- A size line whose size cannot be read is an error; it is never copied through.",
    "",
    "## Retired: the 2017 sizes",
    "",
    "- The 2017 tooling wrote `K`, `M` and `G` after the number with no space, meaning 1024",
    "  and its powers. Nothing writes those now; on input they are not valid units.",
]

TEAMS = ["alpha", "beta", "gamma", "delta", "omega", "sigma", "kappa", "lambda"]
SIZES = ["5 GB", "512 MiB", "1.5 TB", "750 kB", "2 GiB", "64 MiB", "10 GB", "0.5 TiB"]


def _record(rnd: random.Random, i: int) -> str:
    key = rnd.choice(["disk_quota", "upload_limit", "cache_size", "max_body_bytes"])
    return (f"`{key} = {rnd.choice(SIZES)}` | team {rnd.choice(TEAMS)}, sheet revision "
            f"{rnd.randint(1, 60)}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        label = rnd.choice(TEAMS) + rnd.choice(["", "_disk", "_cache", "_uploads"])
        width = rnd.randint(3, 14)
        slug = rnd.choice(["short_label", "long_label", "exact_width", "printout_column"])
        cases.append((slug, f"{label!r}, {width}", repr(pad_label(label, width))))
    return {
        "sizewise/__init__.py": '"""Storage sizes for the platform team."""\n',
        "sizewise/errors.py": ERRORS,
        "sizewise/legacy.py": LEGACY,
        "sizewise/sizes.py": STUB,
        "quotas/teams.conf": SHEET,
        "docs/quota_style.md": long_doc(rnd, "Sizes and quota sheets", DOC_INTRO, _record),
        "tests/test_sizes.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("sizewise.legacy", "pad_label",
                                                      "PadLabelCatalogTests", cases),
    }


TURNS = [
    "Today's work is `sizewise`, which reads and writes the storage sizes in our team quota "
    "sheets. Rules: (1) parse_size returns a whole number of bytes computed without floats, "
    "so '4.35 MB' is exactly 4350000, and a fraction of a byte rounds half up; (2) in a quota "
    "sheet, every line that is not a size line comes out byte for byte unchanged, and so does "
    "everything on a size line except the size itself; (3) unreadable text raises SizeError "
    "from sizewise/errors.py with `.text` set to the text exactly as given, and nothing "
    "unreadable is ever passed through. For now, write sizes in decimal units, kB, MB, GB "
    "and TB, powers of 1000 (1500 bytes is '1.5 kB'). We already tried float(number) * "
    "1000 ** power with int() on the result, and it failed because '4.35 MB' came out as "
    "4349999 bytes and 'KiB' was read as 1000. First read sizewise/sizes.py and "
    "sizewise/errors.py and tell me what has to be written; no edits yet. " + NO_QUESTIONS,
    "Read docs/quota_style.md from beginning to end, all of its roughly 300 lines, until the "
    "line 'End of document.'. Then summarize how sizes are read and written in five bullet "
    "points.",
    "Implement `parse_size(text)` and `format_size(n)` as the document describes them. Then "
    "run `python -m unittest tests.test_sizes -v`.",
    "Run the complete suite verbosely with `python -m unittest discover -s tests -v` and tell "
    "me how many tests ran and which failed.",
    "Change of plan from the storage team: their dashboards show binary units. From now on "
    "format_size writes binary units, KiB, MiB, GiB and TiB, powers of 1024 (1536 bytes is "
    "'1.5 KiB', 1023 bytes is '1023 B'), with the same rounding and layout as before, "
    "whatever the house style or older notes say; decimal output no longer applies. Reading "
    "is unchanged. Update format_size and the tests to match, then run `python -m unittest "
    "tests.test_sizes -v`.",
    "Run the complete suite verbosely again (`python -m unittest discover -s tests -v`) and "
    "give me the totals.",
    "Carry on with the sheet side: implement `rewrite_quota(text)` so a whole quota sheet such "
    "as quotas/teams.conf comes out with every size rewritten, following the rules we agreed "
    "on and the sheet conventions in the document. Add tests to tests/test_sizes.py and run "
    "`python -m unittest tests.test_sizes -v`.",
    "Wrap up: run `python -m unittest discover -s tests` a last time and list what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sizewise.errors import SizeError  # noqa: E402
from sizewise.sizes import format_size, parse_size, rewrite_quota  # noqa: E402

SHEET = ("# team quotas\\n"
         "[team.alpha]\\n"
         "owner = alice\\n"
         "disk_quota = 5 GB\\n"
         "  upload_limit=1536 KiB   # per file\\n"
         "max_body_bytes = 2 MiB\\n"
         "\\n"
         "cache_size = 0.5 GB # shared\\n"
         "note = 5 GB is plenty\\n"
         "scratch_size =   1048575\\n")
WANT = ("# team quotas\\n"
        "[team.alpha]\\n"
        "owner = alice\\n"
        "disk_quota = 4.7 GiB\\n"
        "  upload_limit=1.5 MiB   # per file\\n"
        "max_body_bytes = 2097152\\n"
        "\\n"
        "cache_size = 476.8 MiB # shared\\n"
        "note = 5 GB is plenty\\n"
        "scratch_size =   1 MiB\\n")


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        for text, want in (("0", 0), ("512", 512), ("512 B", 512), ("1.5 kB", 1500),
                           ("2 KiB", 2048), ("1.5KiB", 1536), ("3 MB", 3000000),
                           ("1 MiB", 1048576), ("2 GB", 2000000000), ("1 GiB", 1073741824),
                           ("1 TB", 10 ** 12), ("1 TiB", 1024 ** 4), (" 10 kB ", 10000)):
            self.assertEqual(parse_size(text), want, text)

    def test_f_format(self):
        for n, want in ((0, "0 B"), (1, "1 B"), (1023, "1023 B"), (1024, "1 KiB"),
                        (1536, "1.5 KiB"), (1126, "1.1 KiB"), (1075, "1 KiB"),
                        (1048575, "1 MiB"), (1048576, "1 MiB"), (10 ** 9, "953.7 MiB"),
                        (5 * 1024 ** 3, "5 GiB"), (5 * 1024 ** 4, "5 TiB"),
                        (2000 * 1024 ** 4, "2000 TiB"), (1000, "1000 B"), (1500, "1.5 KiB")):
            self.assertEqual(format_size(n), want, n)
        for bad in (-1, 1.5, "12", None):
            with self.assertRaises(SizeError, msg=repr(bad)):
                format_size(bad)

    def test_f_sheet(self):
        self.assertEqual(rewrite_quota(SHEET), WANT)
        self.assertEqual(rewrite_quota("a_size = 1 KiB"), "a_size = 1 KiB")
        self.assertEqual(rewrite_quota("a_size = 1280 B\\n"), "a_size = 1.3 KiB\\n")
        self.assertEqual(rewrite_quota("x.y-z_limit = 3 MB\\n"), "x.y-z_limit = 2.9 MiB\\n")
        self.assertEqual(rewrite_quota("dump_bytes = 1.5 kB\\n"), "dump_bytes = 1500\\n")
        with self.assertRaises(SizeError):
            rewrite_quota("owner = bob\\ndisk_quota = lots\\n")

    def test_c1_exact(self):
        for text, want in (("4.35 MB", 4350000), ("1.15 kB", 1150), ("0.0005 kB", 1),
                           ("0.0004 kB", 0), ("2.5 B", 3), ("2.5", 3), ("0.3 KiB", 307),
                           ("0.1 TiB", 109951162778), ("9007199254740993", 9007199254740993),
                           ("9007199254740993 B", 9007199254740993), ("1.0000000000000001 GB", 1000000000),
                           ("0.000000001 TB", 1000), ("1.0005 kB", 1001)):
            got = parse_size(text)
            self.assertEqual(got, want, text)
            self.assertIs(type(got), int, text)
        self.assertEqual(format_size(1280), "1.3 KiB")
        self.assertEqual(format_size(1310720), "1.3 MiB")

    def test_c2_sheet_preserved(self):
        keep = ("# disk_quota = 5 GB\\n"
                "\\towner\\t=\\tcarol  \\n"
                "[team.gamma]   \\n"
                "   \\n"
                "free text with = signs = 5 GB\\n"
                "quota_note = 5 GB\\n")
        self.assertEqual(rewrite_quota(keep), keep)
        self.assertEqual(rewrite_quota("\\t disk_quota\\t =  2 GiB \\t# big  # really\\n"),
                         "\\t disk_quota\\t =  2 GiB \\t# big  # really\\n")
        self.assertEqual(rewrite_quota("cache_size= 2048 kib  # x \\n"),
                         "cache_size= 2 MiB  # x \\n")
        self.assertEqual(rewrite_quota("disk_quota = 1024 MiB"), "disk_quota = 1 GiB")
        self.assertEqual(rewrite_quota(""), "")

    def test_c3_errors(self):
        for bad in ("", "lots", "1,5 MB", "-3 kB", "5 XB", "1.2.3 MB", ".5 MB", "5. MB", "MB",
                    "1 M B", "12 parsecs", " 7 K ", "1e3"):
            with self.assertRaises(SizeError, msg=bad) as cm:
                parse_size(bad)
            self.assertEqual(cm.exception.text, bad)
        for sheet in ("disk_quota = \\n", "a_size = ten\\n", "upload_limit = 5 GB extra\\n",
                      "x_bytes = 5#kB\\n"):
            with self.assertRaises(SizeError, msg=sheet):
                rewrite_quota(sheet)


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"sizewise/sizes.py": r'''"""Storage sizes. See docs/quota_style.md."""

import re
from fractions import Fraction

from .errors import SizeError

UNITS = {"": 1, "b": 1, "kb": 1000, "mb": 1000 ** 2, "gb": 1000 ** 3, "tb": 1000 ** 4,
         "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4}
SIZE = re.compile(r"\s*(\d+(?:\.\d+)?)\s*([A-Za-z]*)\s*")
LINE = re.compile(r"(\s*([A-Za-z0-9_.-]+)\s*=[ \t]*)(.*?)((?:[ \t]+#.*)?[ \t]*)")
NAMES = ("KiB", "MiB", "GiB", "TiB")


def parse_size(text):
    m = SIZE.fullmatch(text) if isinstance(text, str) else None
    if not m or m.group(2).lower() not in UNITS:
        raise SizeError(text)
    value = Fraction(m.group(1)) * UNITS[m.group(2).lower()]
    return int((value * 2 + 1) // 2)


def format_size(n):
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise SizeError(n, "not a byte count")
    if n < 1024:
        return f"{n} B"
    k = 1
    while k < 4 and n >= 1024 ** (k + 1):
        k += 1
    tenths = (n * 20 + 1024 ** k) // (2 * 1024 ** k)
    if tenths >= 10240 and k < 4:
        k += 1
        tenths = (n * 20 + 1024 ** k) // (2 * 1024 ** k)
    whole, frac = divmod(tenths, 10)
    return f"{whole}{'' if frac == 0 else f'.{frac}'} {NAMES[k - 1]}"


def rewrite_quota(text):
    out = []
    for line in text.split("\n"):
        m = LINE.fullmatch(line)
        if m and m.group(2).endswith(("_size", "_limit", "_quota", "_bytes")):
            n = parse_size(m.group(3))
            size = str(n) if m.group(2).endswith("_bytes") else format_size(n)
            line = m.group(1) + size + m.group(4)
        out.append(line)
    return "\n".join(out)
'''}
