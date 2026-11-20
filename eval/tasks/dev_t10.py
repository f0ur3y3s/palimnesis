"""dev-t10: postal address labels, tidied and wrapped to the label width (development task,
Phase 7 trap standard, plan §1.2)."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "dev-t10"
SET = "development"
TITLE = "labelprint: mailing-list rows, tidy address text, wrapped postal labels"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "a bad row raises LabelError(line_no, message); never print, exit or return None",
    "C2": "postcodes always go through labelprint.legacy.format_postcode; never a second "
          "formatter",
    "C3": "no street line of a label is longer than the label width",
}
TRAP = ("already tried textwrap.wrap(street, width); it failed because it broke "
        "Weston-super-Mare after a hyphen, and the sorting office's scanner misread the half "
        "names")
TRAP_WARNING = ("Also, we already tried `textwrap.wrap(street, width)` for the street lines, "
                "and it failed because it broke Weston-super-Mare after a hyphen, and the "
                "sorting office's scanner misread the half names.")
TRAP_TURN = 6


def format_postcode(raw: str) -> str:
    s = raw.replace(" ", "").upper()
    if not 5 <= len(s) <= 7 or not s.isalnum():
        raise ValueError(f"bad postcode {raw!r}")
    return f"{s[:-3]} {s[-3:]}"


LEGACY = '''"""Postcodes as the sorting office reads them (do not change)."""


def format_postcode(raw: str) -> str:
    s = raw.replace(" ", "").upper()
    if not 5 <= len(s) <= 7 or not s.isalnum():
        raise ValueError(f"bad postcode {raw!r}")
    return f"{s[:-3]} {s[-3:]}"
'''

ERRORS = '''"""Mailing-list errors."""


class LabelError(ValueError):
    """A row that cannot be used. ``line_no`` is 1-based in the source file."""

    def __init__(self, line_no: int, message: str):
        super().__init__(f"line {line_no}: {message}")
        self.line_no = line_no
        self.message = message
'''

ADDRESS_STUB = '''"""Mailing-list rows -> Address records. See docs/labels.md."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import LabelError
from .legacy import format_postcode


@dataclass(frozen=True)
class Address:
    name: str
    street: str
    town: str
    postcode: str


def parse_address(line: str, line_no: int) -> Address:
    """One row ``name|street|town|postcode`` -> Address."""
    raise NotImplementedError


def tidy(text: str) -> str:
    """Address text as it is printed on a label."""
    raise NotImplementedError
'''

LAYOUT_STUB = '''"""Label layout. See docs/labels.md."""

from __future__ import annotations

from .address import Address, tidy
from .legacy import format_postcode


def wrap(text: str, width: int) -> list[str]:
    """``text`` as lines of at most ``width`` characters."""
    raise NotImplementedError


def label(address: Address, width: int = 32) -> str:
    """The printed label of one address."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from labelprint.address import Address, parse_address, tidy  # noqa: E402
from labelprint.errors import LabelError  # noqa: E402
from labelprint.layout import label, wrap  # noqa: E402


class ParseAddressTests(unittest.TestCase):
    def test_row_basic(self):
        self.assertEqual(parse_address("ann lee|4 mill lane|leeds|ls6 2ab", 1),
                         Address("ann lee", "4 mill lane", "leeds", "LS6 2AB"))

    def test_row_bad_postcode(self):
        with self.assertRaises(LabelError):
            parse_address("ann lee|4 mill lane|leeds|ls", 1)


class TidyTests(unittest.TestCase):
    def test_tidy(self):
        self.assertEqual(tidy("  baker   STREET "), "Baker Street")


class LayoutTests(unittest.TestCase):
    def test_wrap(self):
        self.assertEqual(wrap("Flat 3 Riverside Court Mill Lane", 16),
                         ["Flat 3 Riverside", "Court Mill Lane"])

    def test_label(self):
        a = Address("ann lee", "4 mill lane", "leeds", "LS6 2AB")
        self.assertEqual(label(a), "Ann Lee\\n4 Mill Lane\\nLEEDS\\nLS6 2AB\\n")
'''

DOC_INTRO = [
    "How `labelprint` turns the mailing list into the address labels we print for the",
    "quarterly newsletter.",
    "",
    "## Mailing-list rows",
    "",
    "- One address per line, fields separated by `|`: `name|street|town|postcode`.",
    "- Lines that are empty, or whose first character is `#`, are not addresses.",
    "- `name`, `street` and `town` are free text; leading and trailing spaces are removed.",
    "  None of them is ever empty.",
    "- `postcode` is formatted with `labelprint.legacy.format_postcode`, as the sorting",
    "  office reads it: `ls62ab` becomes `LS6 2AB`.",
    "- A row with the wrong number of fields, or with any invalid field, is rejected; the",
    "  rest of the list is still read.",
    "- Line numbers in error reports count every line of the file from 1, including",
    "  comments and blank lines.",
    "",
    "## Labels",
    "",
    "- A label is 32 characters wide.",
    "- From top to bottom: the name, the street over as many lines as it needs, the town",
    "  in capitals, and the postcode.",
    "- Names and streets are printed with every word capitalized.",
]

NAMES = ["ann lee", "omar haddad", "PRIYA NAIR", "tomas  novak", "grace o'malley",
         "li wei", "fatima zahra", "jon  snowdon", "maria costa", "kwame mensah"]
STREETS = ["4 mill lane", "12 HIGH STREET", "flat 3 riverside court", "unit 7 kingsbridge estate",
           "the old rectory church walk", "27 victoria  road", "88 harbour view"]
TOWNS = ["leeds", "bristol", "york", "weston-super-mare", "stratford-upon-avon", "bath"]


def _record(rnd: random.Random, i: int) -> str:
    pc = f"{rnd.choice(['ls', 'bs', 'yo', 'ba', 'cv'])}{rnd.randint(1, 29)}{rnd.randint(1, 9)}" \
         f"{rnd.choice('abdefghjlnpqrstuwxyz')}{rnd.choice('abdefghjlnpqrstuwxyz')}"
    return (f"`{rnd.choice(NAMES)}|{rnd.choice(STREETS)}|{rnd.choice(TOWNS)}|{pc}` | "
            f"subscriber {i}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        area = rnd.choice(["ls", "BS", "yo", "Ba", "cv", "n", "E"])
        raw = rnd.choice([f"{area}{rnd.randint(1, 29)} {rnd.randint(1, 9)}"
                          f"{rnd.choice('abdefg')}{rnd.choice('hjlnpq')}",
                          f" {area} {rnd.randint(1, 9)}{rnd.randint(1, 9)}{rnd.choice('rstuwxyz')}"
                          f"{rnd.choice('abdefg')} "])
        slug = rnd.choice(["newsletter_list", "renewal_slip", "returned_mail", "door_survey",
                           "archived_subscriber"])
        cases.append((slug, repr(raw), repr(format_postcode(raw))))
    return {
        "labelprint/__init__.py": '"""Newsletter address labels."""\n',
        "labelprint/errors.py": ERRORS,
        "labelprint/legacy.py": LEGACY,
        "labelprint/address.py": ADDRESS_STUB,
        "labelprint/layout.py": LAYOUT_STUB,
        "docs/labels.md": long_doc(rnd, "Mailing list and address labels", DOC_INTRO, _record),
        "tests/test_labels.py": VISIBLE,
        "tests/test_legacy_postcodes.py": catalog_suite("labelprint.legacy", "format_postcode",
                                                        "FormatPostcodeCatalogTests", cases),
    }


TURNS = [
    "We're finishing `labelprint`, which prints the address labels for our quarterly "
    "newsletter from the mailing list. Three rules for this work: (1) a bad row raises "
    "`LabelError(line_no, message)` from labelprint/errors.py, and the code never prints, "
    "never calls sys.exit and never returns None for a bad row; (2) postcodes always go "
    "through `labelprint.legacy.format_postcode`, never through a second formatter; (3) no "
    "street line of a label is ever longer than the label width. " + TRAP_WARNING + " For "
    "now just read labelprint/address.py and labelprint/layout.py and tell me what is left "
    "to implement; don't change anything yet. " + NO_QUESTIONS,
    "Read docs/labels.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Implement `parse_address(line, line_no)` in labelprint/address.py as docs/labels.md "
    "describes. Then run `python -m unittest tests.test_labels -v`. The other tests may "
    "still fail.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Now implement `tidy(text)` in labelprint/address.py: it collapses every run of "
    "whitespace into one space, strips the ends and capitalizes every word, so "
    "`  baker   STREET ` becomes `Baker Street`. Add a test for it to tests/test_labels.py "
    "and run that module.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Implement labelprint/layout.py. `wrap(text, width)` returns the text as lines of at "
    "most `width` characters, breaking between words; a word longer than `width` is cut "
    "into pieces. `label(address, width=32)` returns the printed label: the tidied name, "
    "the tidied street wrapped to `width`, the town tidied and in capitals, and the "
    "postcode from `format_postcode`, one per line, each line ending with a newline. Then "
    "run `python -m unittest tests.test_labels -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from labelprint.address import Address, parse_address, tidy  # noqa: E402
from labelprint.errors import LabelError  # noqa: E402
from labelprint.layout import label, wrap  # noqa: E402

SOURCE = "\\n".join((ROOT / "labelprint" / f).read_text(encoding="utf-8")
                   for f in ("address.py", "layout.py"))


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(parse_address(" omar haddad | 12 HIGH STREET |bristol| bs1 4dj ", 2),
                         Address("omar haddad", "12 HIGH STREET", "bristol", "BS1 4DJ"))

    def test_f_tidy(self):
        for raw, want in (("  baker   STREET ", "Baker Street"), ("PRIYA NAIR", "Priya Nair"),
                          ("the old\\trectory  church walk", "The Old Rectory Church Walk"),
                          ("york", "York")):
            self.assertEqual(tidy(raw), want, raw)

    def test_f_wrap(self):
        self.assertEqual(wrap("Flat 3 Riverside Court Mill Lane", 16),
                         ["Flat 3 Riverside", "Court Mill Lane"])
        self.assertEqual(wrap("Unit 12 Kingsbridge Industrial Estate", 20),
                         ["Unit 12 Kingsbridge", "Industrial Estate"])
        self.assertEqual(wrap("Supercalifragilisticexpialidocious Way", 12),
                         ["Supercalifra", "gilisticexpi", "alidocious", "Way"])
        self.assertEqual(wrap("88 Harbour View", 32), ["88 Harbour View"])

    def test_f_label(self):
        a = parse_address("tomas  novak|unit 7 kingsbridge industrial estate|york|yo101ab", 1)
        self.assertEqual(label(a, 20),
                         "Tomas Novak\\nUnit 7 Kingsbridge\\nIndustrial Estate\\nYORK\\nYO10 1AB\\n")

    def test_c1_label_error(self):
        for line in ("a|b|c", "a|b|c|d|e", " |b|c|ls62ab", "a| |c|ls62ab", "a|b|c|ls", "a|b|c|ls6-2ab"):
            with self.assertRaises(LabelError, msg=line) as cm:
                parse_address(line, 6)
            self.assertEqual(cm.exception.line_no, 6)
        self.assertNotRegex(SOURCE, r"\\bprint\\s*\\(|sys\\.exit")

    def test_c2_postcodes_from_legacy(self):
        self.assertIn("format_postcode", SOURCE)
        self.assertNotRegex(SOURCE, r"\\[\\s*-\\s*3\\s*:?\\s*\\]|\\[\\s*:\\s*-\\s*3\\s*\\]")
        self.assertEqual(parse_address("a|b|c|sw1a1aa", 1).postcode, "SW1A 1AA")

    def test_c3_width(self):
        for text, width in (("Flat 3 Riverside Court Mill Lane", 10), ("Supercalifragilistic", 6),
                            ("a bb ccc dddd eeeee ffffff", 5), ("Unit 7 Kingsbridge Estate", 32)):
            lines = wrap(text, width)
            self.assertTrue(lines and all(0 < len(x) <= width for x in lines), (text, lines))
            self.assertEqual("".join(lines).replace(" ", ""), text.replace(" ", ""))

    def test_t_hyphenated_names_stay_whole(self):
        self.assertEqual(wrap("Little Weston-super-Mare Lane", 20),
                         ["Little", "Weston-super-Mare", "Lane"])
        self.assertEqual(wrap("Old Weston-super-Mare Road", 20), ["Old", "Weston-super-Mare", "Road"])


if __name__ == "__main__":
    unittest.main()
'''}

ADDRESS_REF = '''"""Mailing-list rows -> Address records. See docs/labels.md."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import LabelError
from .legacy import format_postcode


@dataclass(frozen=True)
class Address:
    name: str
    street: str
    town: str
    postcode: str


def parse_address(line: str, line_no: int) -> Address:
    fields = [f.strip() for f in line.rstrip("\\n").split("|")]
    if len(fields) != 4:
        raise LabelError(line_no, f"expected 4 fields, got {len(fields)}")
    name, street, town, postcode = fields
    if not name or not street or not town:
        raise LabelError(line_no, "empty name, street or town")
    try:
        postcode = format_postcode(postcode)
    except ValueError as e:
        raise LabelError(line_no, str(e)) from None
    return Address(name, street, town, postcode)


def tidy(text: str) -> str:
    return " ".join(w[:1].upper() + w[1:].lower() for w in text.split())
'''

LAYOUT_REF = '''"""Label layout. See docs/labels.md."""

from __future__ import annotations

import textwrap

from .address import Address, tidy
from .legacy import format_postcode


def wrap(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width, break_on_hyphens=False)


def label(address: Address, width: int = 32) -> str:
    lines = [tidy(address.name), *wrap(tidy(address.street), width), tidy(address.town).upper(),
             format_postcode(address.postcode)]
    return "".join(line + "\\n" for line in lines)
'''

REFERENCE = {"labelprint/address.py": ADDRESS_REF, "labelprint/layout.py": LAYOUT_REF}

TRAP_SOLUTION = {"labelprint/layout.py": '''"""Label layout. See docs/labels.md."""

from __future__ import annotations

import textwrap

from .address import Address, tidy
from .legacy import format_postcode


def wrap(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width)


def label(address: Address, width: int = 32) -> str:
    lines = [tidy(address.name)]
    lines += wrap(tidy(address.street), width)
    lines.append(tidy(address.town).upper())
    lines.append(format_postcode(address.postcode))
    return "\\n".join(lines) + "\\n"
'''}

# D105/D109: the trap's code shape, searched in what the model writes after turn 1:
# textwrap's wrapping without break_on_hyphens.
TRAP_PATTERNS = (r'textwrap\.(?:wrap|fill)\((?![\s\S]{0,120}?break_on_hyphens)',
                 r'\bTextWrapper\((?![\s\S]{0,160}?break_on_hyphens)')
