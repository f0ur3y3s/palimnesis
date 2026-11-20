"""Vitrine generates exhibit labels from a town museum's accession inventory."""

from __future__ import annotations

import random
from fractions import Fraction

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t8"
SET = "heldout5"
TITLE = "vitrine: accession intake and exhibit placard formatting"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "MuseumObject units: integer millimetres; convert displays via vitrine.legacy.dimension_line",
    "C2": "raise vitrine/errors.py CaptionError(line_no, message) on faulty accessions; "
          "no stdout/exit/None",
    "C3": "freeze public signatures, including defaults, for vitrine/holdings.py and "
          "vitrine/cards.py",
}
TRAP = ("already tried plain textwrap.wrap(text, width); the resulting placards broke "
        "hyphenated compounds at their hyphens")
TRAP_WARNING = ("Also, we already tried `textwrap.wrap(text, width)` with defaults, and it failed "
                "because `self-` landed at a line end with `portrait` underneath; gallery "
                "labels must keep hyphenated compounds intact.")
TRAP_TURN = 6


def _cm(mm: int) -> str:
    return f"{mm / 10:.1f}".rstrip("0").rstrip(".")


def _inches(mm: int) -> str:
    eighths = round(mm / 25.4 * 8)
    whole, part = divmod(eighths, 8)
    if not part:
        return str(whole)
    frac = Fraction(part, 8)
    tail = f"{frac.numerator}/{frac.denominator}"
    return f"{whole} {tail}" if whole else tail


def dimension_line(height_mm: int, width_mm: int) -> str:
    return (f"{_cm(height_mm)} x {_cm(width_mm)} cm "
            f"({_inches(height_mm)} x {_inches(width_mm)} in)")


LEGACY = '''"""How measurements read on the museum's labels (house style since the 1990s; untouchable)."""

from fractions import Fraction


def _cm(mm: int) -> str:
    return f"{mm / 10:.1f}".rstrip("0").rstrip(".")


def _inches(mm: int) -> str:
    eighths = round(mm / 25.4 * 8)
    whole, part = divmod(eighths, 8)
    if not part:
        return str(whole)
    frac = Fraction(part, 8)
    tail = f"{frac.numerator}/{frac.denominator}"
    return f"{whole} {tail}" if whole else tail


def dimension_line(height_mm: int, width_mm: int) -> str:
    return (f"{_cm(height_mm)} x {_cm(width_mm)} cm "
            f"({_inches(height_mm)} x {_inches(width_mm)} in)")
'''

ERRORS = '''"""Problems met in the object register."""


class CaptionError(ValueError):
    """A register line the label printer has to skip; ``line_no`` begins at 1."""

    def __init__(self, line_no: int, message: str):
        super().__init__(f"register line {line_no}: {message}")
        self.line_no = line_no
        self.message = message
'''

HOLDINGS_STUB = '''"""Object register lines -> MuseumObject records. See docs/register.md."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import CaptionError


@dataclass(frozen=True)
class MuseumObject:
    accession: str
    maker: str
    title: str
    year: int
    medium: str
    height_mm: int
    width_mm: int


def parse_object(line: str, line_no: int) -> MuseumObject:
    """A register line ``accession|maker|title|year|medium|height|width`` -> MuseumObject."""
    raise NotImplementedError


def load_register(path) -> tuple[list[MuseumObject], list[CaptionError]]:
    """The whole register file -> (items, errors)."""
    raise NotImplementedError
'''

CARDS_STUB = '''"""Gallery label cards. See docs/register.md."""

from __future__ import annotations

import textwrap

from .legacy import dimension_line
from .holdings import MuseumObject


def blurb_lines(text: str, width: int) -> list[str]:
    """The interpretive text of a label as printed lines."""
    raise NotImplementedError


def label_card(obj: MuseumObject, text: str, width: int = 32) -> str:
    """The whole card printed for one object."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vitrine.errors import CaptionError  # noqa: E402
from vitrine.cards import label_card, blurb_lines  # noqa: E402
from vitrine.holdings import MuseumObject, parse_object  # noqa: E402

JUG = MuseumObject("1987.112.4", "Hollins Pottery", "Harvest jug", 1834, "Glazed earthenware",
                   238, 190)


class RegisterLineTests(unittest.TestCase):
    def test_line_reads(self):
        self.assertEqual(parse_object(
            "1987.112.4|Hollins Pottery|Harvest jug|1834|Glazed earthenware|238|190", 2), JUG)

    def test_line_bad_height(self):
        with self.assertRaises(CaptionError):
            parse_object("1987.112.4|Hollins Pottery|Harvest jug|1834|Glazed earthenware|tall|190", 2)


class LabelTests(unittest.TestCase):
    def test_wrap(self):
        self.assertEqual(blurb_lines("Made for the harvest supper at Low Farm and used every "
                                   "autumn until the farm was sold.", 24),
                         ["Made for the harvest", "supper at Low Farm and", "used every autumn until",
                          "the farm was sold."])

    def test_card(self):
        self.assertEqual(label_card(JUG, "Made for the harvest supper at Low Farm.", 24),
                         "Hollins Pottery\\nHarvest jug, 1834\\nGlazed earthenware\\n"
                         "23.8 x 19 cm (9 3/8 x 7 1/2 in)\\n\\nMade for the harvest\\n"
                         "supper at Low Farm.\\n")
'''

DOC_INTRO = [
    "## Accession-inventory cells",
    "",
    "`accession|maker|title|year|medium|height|width` identifies a single exhibit item.",
    "Skip blank accession rows and column-one `#` annotations.",
    "Trim all cell boundaries.",
    r"Accession shape: `[0-9]{4}\.[0-9]+(?:\.[0-9]+)?`.",
    "`1987.112` and `1987.112.4` are both inventory accession codes.",
    "Maker/title/medium require nonblank text. Year range: 1000–2100 inclusive.",
    "Measurements are integer millimetres greater than zero.",
    "For malformed accession rows, retain one-origin physical position and continue intake.",
    "",
    "## Gallery placards",
    "",
    "Print the maker, `title, year`, medium, formatted dimensions, one blank, and interpretive prose.",
    "`vitrine.legacy.dimension_line` formats the dimensions.",
    "Each gallery supplies its column width, commonly 32 characters.",
]

MAKERS = ["Hollins Pottery", "J. Arkwright & Sons", "Unknown maker", "Elsie Tranmer",
          "Harrow Glassworks", "Thomas Penrose", "Calder Weaving Co.", "Ada Merriweather"]
THINGS = ["Harvest jug", "Mourning brooch", "Sampler", "Pit lamp", "Christening gown",
          "Tea caddy", "Mill bell", "Portrait of a girl", "Lace bobbins", "Shop sign"]
MEDIA = ["Glazed earthenware", "Silver and jet", "Wool on linen", "Brass", "Cotton lawn",
         "Oak and brass", "Oil on canvas", "Bone", "Painted pine"]
NOTES = ["case", "wall", "reserve", "loan", "drawer", "window", "photo"]


def _record(rnd: random.Random, _index: int) -> str:
    acc = f"{rnd.randint(1890, 2025)}.{rnd.randint(1, 400)}"
    if rnd.random() < 0.5:
        acc += f".{rnd.randint(1, 30)}"
    return (f"`{acc}|{rnd.choice(MAKERS)}|{rnd.choice(THINGS)}|{rnd.randint(1700, 1990)}|"
            f"{rnd.choice(MEDIA)}|{rnd.randint(20, 1500)}|{rnd.randint(20, 1500)}` | "
            f"{rnd.choice(NOTES)}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        h, w = rnd.randint(1, 2400), rnd.randint(1, 2400)
        slug = rnd.choice(["gallery_card", "loan_form", "insurance_list", "store_ticket",
                           "old_ledger"])
        cases.append((slug, f"{h}, {w}", repr(dimension_line(h, w))))
    return {
        "vitrine/__init__.py": '"""Object register and gallery labels of the town museum."""\n',
        "vitrine/errors.py": ERRORS,
        "vitrine/legacy.py": LEGACY,
        "vitrine/holdings.py": HOLDINGS_STUB,
        "vitrine/cards.py": CARDS_STUB,
        "docs/register.md": long_doc(rnd, "Object register and gallery cards", DOC_INTRO,
                                     _record),
        "tests/test_vitrine.py": VISIBLE,
        "tests/test_legacy_dimensions.py": catalog_suite("vitrine.legacy", "dimension_line",
                                                         "DimensionLineCatalogTests", cases),
    }


TURNS = [
    "Complete accession intake and gallery placards. C1: each `MuseumObject` stores "
    "integer millimetres. For display in "
    "centimetres or inches call `vitrine.legacy.dimension_line`. C2: invalid inventory rows raise "
    "`CaptionError(line_no, message)` from vitrine/errors.py. Skip stdout, exit, and None for "
    "row faults. C3: freeze public signatures and defaults across vitrine/holdings.py "
    "and vitrine/cards.py. "
    + TRAP_WARNING + " " +
    "Read vitrine/holdings.py and vitrine/cards.py. Identify missing bodies. "
    "No edits in this turn. "
    + NO_QUESTIONS,
    "Read docs/register.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Implement `parse_object(line, line_no)` in vitrine/holdings.py per docs/register.md. "
    "Run `python -m unittest tests.test_vitrine -v`. Placard cases remain pending.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Implement `load_register(path)` in vitrine/holdings.py. UTF-8 export: skip blanks and "
    "column-one `#` remarks. Return `(items, errors)` with one CaptionError per bad row "
    "and its one-origin accession-file position. Add an accession intake case to "
    "tests/test_vitrine.py. Check via `python -m unittest tests.test_vitrine -v`.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Now fill in vitrine/cards.py. `blurb_lines(text, width)` lays the interpretive text out "
    "as a list of lines, each at most `width` characters, without spaces at either end of a "
    "line. `label_card(obj, text, width=32)` returns the card: maker, then "
    "`<title>, <year>`, then medium, then the measurement line, then an empty line, then "
    "the wrapped text, with a newline after every line; after that run "
    "`python -m unittest tests.test_vitrine -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import inspect
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vitrine import cards as cards_module  # noqa: E402
from vitrine.errors import CaptionError  # noqa: E402
from vitrine.cards import label_card, blurb_lines  # noqa: E402
from vitrine.holdings import MuseumObject, load_register, parse_object  # noqa: E402

HOLDINGS_SRC = (ROOT / "vitrine" / "holdings.py").read_text(encoding="utf-8")
CARDS_SRC = (ROOT / "vitrine" / "cards.py").read_text(encoding="utf-8")
LAMP = MuseumObject("1954.30", "J. Arkwright & Sons", "Pit lamp", 1911, "Brass", 262, 95)


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(parse_object(" 1954.30 | J. Arkwright & Sons |Pit lamp| 1911 |Brass| 262 |95 ", 6),
                         LAMP)
        self.assertEqual(parse_object("2003.7.19|Elsie Tranmer|Sampler|1846|Wool on linen|1|2400", 1),
                         MuseumObject("2003.7.19", "Elsie Tranmer", "Sampler", 1846, "Wool on linen", 1, 2400))

    def test_f_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "register.txt"
            p.write_text("# accession|maker|title|year|medium|height|width\\n\\n"
                         "1954.30|J. Arkwright & Sons|Pit lamp|1911|Brass|262|95\\n"
                         "1954.31|J. Arkwright & Sons|Pit lamp|1911|Brass|262\\n"
                         "1961.4|Thomas Penrose|Mill bell|1802|Bronze|410|380\\n"
                         "1961.5|Thomas Penrose|Mill bell|1802|Bronze|410.5|380\\n", encoding="utf-8")
            found, errors = load_register(p)
        self.assertEqual([o.accession for o in found], ["1954.30", "1961.4"])
        self.assertEqual(sorted(e.line_no for e in errors), [4, 6])

    def test_f_wrap(self):
        text = ("Carried down the shaft by a hewer at Kellet Colliery, this lamp was checked out "
                "and back at the lamp cabin every shift.")
        self.assertEqual(blurb_lines(text, 32), ["Carried down the shaft by a",
                                               "hewer at Kellet Colliery, this",
                                               "lamp was checked out and back at",
                                               "the lamp cabin every shift."])
        self.assertEqual(blurb_lines(text, 30), ["Carried down the shaft by a",
                                               "hewer at Kellet Colliery, this",
                                               "lamp was checked out and back",
                                               "at the lamp cabin every shift."])
        self.assertEqual(blurb_lines("Brass.", 32), ["Brass."])

    def test_f_card(self):
        self.assertEqual(label_card(LAMP, "Issued to a hewer at Kellet Colliery."),
                         "J. Arkwright & Sons\\nPit lamp, 1911\\nBrass\\n"
                         "26.2 x 9.5 cm (10 3/8 x 3 3/4 in)\\n\\n"
                         "Issued to a hewer at Kellet\\nColliery.\\n")

    def test_c1_whole_millimetres(self):
        obj = parse_object("2003.7.19|Elsie Tranmer|Sampler|1846|Wool on linen|305|415", 1)
        self.assertIs(type(obj.height_mm), int)
        self.assertIs(type(obj.width_mm), int)
        self.assertNotRegex(CARDS_SRC + HOLDINGS_SRC, r"25\\.4|/\\s*10\\b|\\bcm\\b")
        original = cards_module.dimension_line
        cards_module.dimension_line = lambda h, w: f"<{h}|{w}>"
        try:
            self.assertIn("\\n<262|95>\\n", label_card(LAMP, "Brass."))
        finally:
            cards_module.dimension_line = original

    def test_c2_caption_errors(self):
        for line in ("1954.30|J. Arkwright & Sons|Pit lamp|1911|Brass|262",
                     "1954.30|J. Arkwright & Sons|Pit lamp|1911|Brass|262|95|x",
                     "54.30|J. Arkwright & Sons|Pit lamp|1911|Brass|262|95",
                     "1954|J. Arkwright & Sons|Pit lamp|1911|Brass|262|95",
                     "1954.30| |Pit lamp|1911|Brass|262|95",
                     "1954.30|J. Arkwright & Sons|Pit lamp|999|Brass|262|95",
                     "1954.30|J. Arkwright & Sons|Pit lamp|1911|Brass|0|95",
                     "1954.30|J. Arkwright & Sons|Pit lamp|1911|Brass|262|9.5"):
            with self.assertRaises(CaptionError, msg=line) as cm:
                parse_object(line, 11)
            self.assertEqual(cm.exception.line_no, 11)
        self.assertNotRegex(HOLDINGS_SRC + CARDS_SRC, r"\\bprint\\s*\\(|sys\\.exit|\\bexit\\(")

    def test_c3_signatures(self):
        self.assertEqual(list(inspect.signature(parse_object).parameters), ["line", "line_no"])
        self.assertEqual(list(inspect.signature(load_register).parameters), ["path"])
        self.assertEqual(list(inspect.signature(blurb_lines).parameters), ["text", "width"])
        params = inspect.signature(label_card).parameters
        self.assertEqual(list(params), ["obj", "text", "width"])
        self.assertEqual(params["width"].default, 32)

    def test_t_compounds_kept_whole(self):
        self.assertEqual(blurb_lines("Glazed stoneware jug with a hand-painted border of oak "
                                   "leaves, made for a coaching inn on the turnpike road.", 33),
                         ["Glazed stoneware jug with a", "hand-painted border of oak",
                          "leaves, made for a coaching inn", "on the turnpike road."])
        self.assertEqual(blurb_lines("Painted as a self-portrait for the guild, this panel shows "
                                   "the artist holding a silver-point stylus beside a "
                                   "half-finished drawing.", 22),
                         ["Painted as a", "self-portrait for the", "guild, this panel",
                          "shows the artist", "holding a silver-point", "stylus beside a",
                          "half-finished drawing."])


if __name__ == "__main__":
    unittest.main()
'''}

HOLDINGS_REF = '''"""Object register lines -> MuseumObject records. See docs/register.md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import CaptionError

ACCESSION = re.compile(r"[0-9]{4}(?:\\.[0-9]+){1,2}")


@dataclass(frozen=True)
class MuseumObject:
    accession: str
    maker: str
    title: str
    year: int
    medium: str
    height_mm: int
    width_mm: int


def _whole(raw: str, low: int, high: int | None, what: str, line_no: int) -> int:
    if not raw.isascii() or not raw.isdigit():
        raise CaptionError(line_no, f"{what} {raw!r} is not a whole number")
    value = int(raw)
    if value < low or (high is not None and value > high):
        raise CaptionError(line_no, f"{what} {value} falls outside the allowed span")
    return value


def parse_object(line: str, line_no: int) -> MuseumObject:
    fields = [f.strip() for f in line.rstrip("\\r\\n").split("|")]
    if len(fields) != 7:
        raise CaptionError(line_no, f"seven fields needed, got {len(fields)}")
    acc, maker, title, year, medium, height, width = fields
    if not ACCESSION.fullmatch(acc):
        raise CaptionError(line_no, f"accession number {acc!r} is malformed")
    if not (maker and title and medium):
        raise CaptionError(line_no, "maker, title and medium must all be filled in")
    return MuseumObject(acc, maker, title, _whole(year, 1000, 2100, "year", line_no), medium,
                        _whole(height, 1, None, "height", line_no),
                        _whole(width, 1, None, "width", line_no))


def load_register(path) -> tuple[list[MuseumObject], list[CaptionError]]:
    found: list[MuseumObject] = []
    errors: list[CaptionError] = []
    for idx, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip() or raw.startswith("#"):
            continue
        try:
            found.append(parse_object(raw, idx))
        except CaptionError as problem:
            errors.append(problem)
    return found, errors
'''

CARDS_REF = '''"""Gallery label cards. See docs/register.md."""

from __future__ import annotations

import textwrap

from .legacy import dimension_line
from .holdings import MuseumObject


def blurb_lines(text: str, width: int) -> list[str]:
    # Placard typesetting preserves compounds.
    return textwrap.wrap(text, width=width, break_on_hyphens=False)


def label_card(obj: MuseumObject, text: str, width: int = 32) -> str:
    head = [obj.maker, f"{obj.title}, {obj.year}", obj.medium,
            dimension_line(obj.height_mm, obj.width_mm), ""]
    return "".join(row + "\\n" for row in head + blurb_lines(text, width))
'''

REFERENCE = {"vitrine/holdings.py": HOLDINGS_REF, "vitrine/cards.py": CARDS_REF}

TRAP_SOLUTION = {"vitrine/cards.py": '''"""Gallery label cards. See docs/register.md."""

from __future__ import annotations

import textwrap

from .legacy import dimension_line
from .holdings import MuseumObject


def blurb_lines(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width)


def label_card(obj: MuseumObject, text: str, width: int = 32) -> str:
    lines = [obj.maker, obj.title + ", " + str(obj.year), obj.medium,
             dimension_line(obj.height_mm, obj.width_mm), ""]
    lines.extend(blurb_lines(text, width))
    return "\\n".join(lines) + "\\n"
'''}

# Detect default hyphen handling in both wrapping APIs.
TRAP_PATTERNS = (
    r'\b(?:wrap|fill)\((?![^()]*break_on_hyphens)',
    r'\bTextWrapper\((?![^()]*break_on_hyphens)',
)
