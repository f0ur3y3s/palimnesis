"""dev-t8: a record shop's catalog lines and its artist and release page links (development
task, Phase 7 trap standard, plan §1.2)."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "dev-t8"
SET = "development"
TITLE = "crate: record-shop catalog lines, release records, artist and release page links"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "every link starts with the base URL the caller passes; no host is ever written "
          "into the code",
    "C2": "a bad line raises EntryError(line_no, message); never print, exit or return None",
    "C3": "catalog numbers always go through crate.legacy.catalog_number; never a second "
          "normalizer",
}
TRAP = ("already tried urllib.parse.quote(name) for the link parts; it failed because AC/DC "
        "stayed AC/DC, so the shop's router split it into two path segments and answered 404")
TRAP_WARNING = ("Also, we already tried `urllib.parse.quote(name)` for the parts of the links, "
                "and it failed because AC/DC stayed `AC/DC`, so the shop's router split it "
                "into two path segments and answered 404.")
TRAP_TURN = 6


def catalog_number(raw: str) -> str:
    s = raw.strip().upper().replace(" ", "").replace("-", "")
    letters = s.rstrip("0123456789")
    digits = s[len(letters):]
    if not letters.isalpha() or not digits:
        raise ValueError(f"bad catalog number {raw!r}")
    return f"{letters}-{int(digits):04d}"


LEGACY = '''"""Catalog numbers as the shop's stock system prints them (do not change)."""


def catalog_number(raw: str) -> str:
    s = raw.strip().upper().replace(" ", "").replace("-", "")
    letters = s.rstrip("0123456789")
    digits = s[len(letters):]
    if not letters.isalpha() or not digits:
        raise ValueError(f"bad catalog number {raw!r}")
    return f"{letters}-{int(digits):04d}"
'''

ERRORS = '''"""Catalog errors."""


class EntryError(ValueError):
    """A line that cannot be used. ``line_no`` is 1-based in the source file."""

    def __init__(self, line_no: int, message: str):
        super().__init__(f"line {line_no}: {message}")
        self.line_no = line_no
        self.message = message
'''

ENTRIES_STUB = '''"""Catalog lines -> Release records. See docs/catalog.md."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import EntryError
from .legacy import catalog_number

FORMATS = ("LP", "EP", "7in", "CD")


@dataclass(frozen=True)
class Release:
    catalog: str
    artist: str
    title: str
    year: int
    fmt: str


def parse_entry(line: str, line_no: int) -> Release:
    """One line ``catalog|artist|title|year|format`` -> Release."""
    raise NotImplementedError


def load_catalog(path) -> tuple[list[Release], list[EntryError]]:
    """Every line of a catalog file -> (releases, errors)."""
    raise NotImplementedError
'''

LINKS_STUB = '''"""Links to the shop's artist and release pages. See docs/catalog.md."""

from __future__ import annotations

from .entries import Release


def artist_url(base: str, artist: str) -> str:
    """The link to an artist's page."""
    raise NotImplementedError


def release_url(base: str, release: Release) -> str:
    """The link to a release's page."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crate.entries import Release, parse_entry  # noqa: E402
from crate.errors import EntryError  # noqa: E402
from crate.links import artist_url, release_url  # noqa: E402

BOOKENDS = Release("CBS-0101", "Simon & Garfunkel", "Bookends", 1968, "LP")


class ParseEntryTests(unittest.TestCase):
    def test_line_basic(self):
        self.assertEqual(parse_entry("cbs 101|Simon & Garfunkel|Bookends|1968|LP", 1), BOOKENDS)

    def test_line_bad_format(self):
        with self.assertRaises(EntryError):
            parse_entry("cbs 101|Simon & Garfunkel|Bookends|1968|8track", 1)


class LinkTests(unittest.TestCase):
    def test_artist(self):
        self.assertEqual(artist_url("https://shop.test", "Sigur Rós"),
                         "https://shop.test/artists/Sigur%20R%C3%B3s")

    def test_release(self):
        self.assertEqual(release_url("https://shop.test/", BOOKENDS),
                         "https://shop.test/artists/Simon%20%26%20Garfunkel/releases/Bookends")
'''

DOC_INTRO = [
    "How `crate` reads the shop's catalog export and links each release to its pages on",
    "the shop's website.",
    "",
    "## Catalog lines",
    "",
    "- One release per line, fields separated by `|`: `catalog|artist|title|year|format`.",
    "- Lines that are empty, or whose first character is `#`, are not releases.",
    "- `catalog` is normalized with `crate.legacy.catalog_number`, as the stock system",
    "  prints it: `cbs 101` becomes `CBS-0101`.",
    "- `artist` and `title` are free text, exactly as printed on the sleeve; leading and",
    "  trailing spaces are removed. Neither is ever empty.",
    "- `year` is a whole number from 1900 to 2100.",
    "- `format` is one of `LP`, `EP`, `7in` and `CD`, written exactly so.",
    "- A line with the wrong number of fields, or with any invalid field, is rejected; the",
    "  rest of the file is still read.",
    "- Line numbers in error reports count every line of the file from 1, including",
    "  comments and blank lines.",
    "",
    "## Links",
    "",
    "- The website's address is configured per deployment and passed in as `base`.",
    "- An artist's page is `<base>/artists/<artist>`.",
    "- A release's page is `<base>/artists/<artist>/releases/<title>`.",
]

SLEEVES = [("Sigur Rós", "Ágætis byrjun"), ("Simon & Garfunkel", "Bookends"),
           ("Hüsker Dü", "Zen Arcade"), ("Os Mutantes", "Os Mutantes"),
           ("Café Tacvba", "Re"), ("Can", "Tago Mago"), ("Talk Talk", "Spirit of Eden"),
           ("Low", "Things We Lost in the Fire"), ("Stereolab", "Dots and Loops"),
           ("Broadcast", "Tender Buttons"), ("Slint", "Spiderland")]


def _record(rnd: random.Random, i: int) -> str:
    artist, title = rnd.choice(SLEEVES)
    cat = f"{rnd.choice(['cbs', 'rtd', 'sst', 'wl', 'tgo'])} {rnd.randint(1, 999)}"
    return (f"`{cat}|{artist}|{title}|{rnd.randint(1960, 2024)}|"
            f"{rnd.choice(['LP', 'EP', '7in', 'CD'])}` | catalog line {i}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = rnd.choice([f"{rnd.choice(['cbs', 'rtd', 'sst'])} {rnd.randint(1, 9999)}",
                          f" {rnd.choice(['WL', 'Tgo', 'mute'])}-{rnd.randint(1, 999)} ",
                          f"{rnd.choice(['stumm', 'Kill', 'ada'])}{rnd.randint(0, 99)}"])
        slug = rnd.choice(["stock_label", "sleeve_spine", "import_sticker", "dealer_list",
                           "archived_price_card"])
        cases.append((slug, repr(raw), repr(catalog_number(raw))))
    return {
        "crate/__init__.py": '"""Record-shop catalog."""\n',
        "crate/errors.py": ERRORS,
        "crate/legacy.py": LEGACY,
        "crate/entries.py": ENTRIES_STUB,
        "crate/links.py": LINKS_STUB,
        "docs/catalog.md": long_doc(rnd, "Catalog export and shop links", DOC_INTRO, _record),
        "tests/test_crate.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("crate.legacy", "catalog_number",
                                                      "CatalogNumberCatalogTests", cases),
    }


TURNS = [
    "We're finishing `crate`, which reads our record shop's catalog export and builds the "
    "links to each artist's and release's page on the website. Three rules for this work: "
    "(1) every link starts with the base URL the caller passes, and no host is ever written "
    "into the code; (2) a bad line raises `EntryError(line_no, message)` from "
    "crate/errors.py, and the code never prints, never calls sys.exit and never returns None "
    "for a bad line; (3) catalog numbers always go through `crate.legacy.catalog_number`, "
    "never through a second normalizer. " + TRAP_WARNING + " For now just read "
    "crate/entries.py and crate/links.py and tell me what is left to implement; don't change "
    "anything yet. " + NO_QUESTIONS,
    "Read docs/catalog.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Implement `parse_entry(line, line_no)` in crate/entries.py as docs/catalog.md describes. "
    "Then run `python -m unittest tests.test_crate -v`. The link tests may still fail.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Now implement `load_catalog(path)` in crate/entries.py: read the file as UTF-8, skip "
    "blank lines and lines starting with `#`, and return `(releases, errors)`, where "
    "`errors` collects the failures of bad lines with their 1-based line numbers in the "
    "file. Add a test for it to tests/test_crate.py and run that module.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Implement crate/links.py. `artist_url(base, artist)` returns `<base>/artists/<artist>`, "
    "and `release_url(base, release)` returns `<base>/artists/<artist>/releases/<title>` with "
    "the release's artist and title. A trailing slash on `base` is dropped, and the artist "
    "and the title are percent-encoded as UTF-8, a space becoming `%20`. Then run "
    "`python -m unittest tests.test_crate -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crate.entries import Release, load_catalog, parse_entry  # noqa: E402
from crate.errors import EntryError  # noqa: E402
from crate.links import artist_url, release_url  # noqa: E402

ENTRIES_SRC = (ROOT / "crate" / "entries.py").read_text(encoding="utf-8")
LINKS_SRC = (ROOT / "crate" / "links.py").read_text(encoding="utf-8")
BASE = "https://records.example.org"


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(parse_entry(" sst 27 | Hüsker Dü | Zen Arcade |1984|LP", 2),
                         Release("SST-0027", "Hüsker Dü", "Zen Arcade", 1984, "LP"))
        self.assertEqual(parse_entry("tgo-5|Can|Tago Mago|1971|CD", 1),
                         Release("TGO-0005", "Can", "Tago Mago", 1971, "CD"))

    def test_f_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "catalog.txt"
            p.write_text("# catalog|artist|title|year|format\\n\\ncbs 101|Simon & Garfunkel|"
                         "Bookends|1968|LP\\nnot a line\\nwl 7|Low|Long Division|1995|CD\\n"
                         "x 1|Can|Ege Bamyasi|1872|LP\\n", encoding="utf-8")
            releases, errors = load_catalog(p)
        self.assertEqual([r.catalog for r in releases], ["CBS-0101", "WL-0007"])
        self.assertEqual(sorted(e.line_no for e in errors), [4, 6])

    def test_f_artist_links(self):
        for artist, tail in (("Sigur Rós", "Sigur%20R%C3%B3s"), ("Can", "Can"),
                             ("Simon & Garfunkel", "Simon%20%26%20Garfunkel"),
                             ("Café Tacvba", "Caf%C3%A9%20Tacvba"),
                             ("? and the Mysterians", "%3F%20and%20the%20Mysterians")):
            self.assertEqual(artist_url(BASE, artist), f"{BASE}/artists/{tail}", artist)
            self.assertEqual(artist_url(BASE + "/", artist), f"{BASE}/artists/{tail}", artist)

    def test_f_release_links(self):
        r = Release("RTD-0001", "Sigur Rós", "Ágætis byrjun", 1999, "LP")
        self.assertEqual(release_url(BASE, r),
                         f"{BASE}/artists/Sigur%20R%C3%B3s/releases/%C3%81g%C3%A6tis%20byrjun")
        r = Release("TGO-0005", "Talk Talk", "What's Going On", 1988, "CD")
        self.assertEqual(release_url(BASE + "/", r),
                         f"{BASE}/artists/Talk%20Talk/releases/What%27s%20Going%20On")

    def test_c1_base_from_caller(self):
        self.assertNotRegex(LINKS_SRC, r"https?:|\\.(com|org|net|test)\\b")
        self.assertEqual(artist_url("http://localhost:8001", "Can"), "http://localhost:8001/artists/Can")

    def test_c2_entry_error(self):
        for line in ("a 1|B|C|1999", "a 1|B|C|19x9|LP", "a 1|B|C|1899|LP", "a 1|B|C|1999|lp",
                     "a 1| |C|1999|LP", "123|B|C|1999|LP"):
            with self.assertRaises(EntryError, msg=line) as cm:
                parse_entry(line, 8)
            self.assertEqual(cm.exception.line_no, 8)
        self.assertNotRegex(ENTRIES_SRC + LINKS_SRC, r"\\bprint\\s*\\(|sys\\.exit")

    def test_c3_catalog_numbers_from_legacy(self):
        self.assertIn("catalog_number", ENTRIES_SRC)
        self.assertNotRegex(ENTRIES_SRC, r":04d|zfill|rjust")
        self.assertEqual(parse_entry("ada9|Low|Drums and Guns|2007|LP", 1).catalog, "ADA-0009")

    def test_t_slash_in_names(self):
        self.assertEqual(artist_url(BASE, "AC/DC"), f"{BASE}/artists/AC%2FDC")
        r = Release("KRS-0045", "Elliott Smith", "Either/Or", 1997, "LP")
        self.assertEqual(release_url(BASE, r), f"{BASE}/artists/Elliott%20Smith/releases/Either%2FOr")


if __name__ == "__main__":
    unittest.main()
'''}

ENTRIES_REF = '''"""Catalog lines -> Release records. See docs/catalog.md."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import EntryError
from .legacy import catalog_number

FORMATS = ("LP", "EP", "7in", "CD")


@dataclass(frozen=True)
class Release:
    catalog: str
    artist: str
    title: str
    year: int
    fmt: str


def parse_entry(line: str, line_no: int) -> Release:
    fields = line.rstrip("\\n").split("|")
    if len(fields) != 5:
        raise EntryError(line_no, f"expected 5 fields, got {len(fields)}")
    cat, artist, title, year, fmt = (f.strip() for f in fields)
    try:
        cat = catalog_number(cat)
    except ValueError as e:
        raise EntryError(line_no, str(e)) from None
    if not artist or not title:
        raise EntryError(line_no, "empty artist or title")
    if not year.isdigit() or not 1900 <= int(year) <= 2100:
        raise EntryError(line_no, f"bad year {year!r}")
    if fmt not in FORMATS:
        raise EntryError(line_no, f"bad format {fmt!r}")
    return Release(cat, artist, title, int(year), fmt)


def load_catalog(path) -> tuple[list[Release], list[EntryError]]:
    releases, errors = [], []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        try:
            releases.append(parse_entry(line, n))
        except EntryError as e:
            errors.append(e)
    return releases, errors
'''

LINKS_REF = '''"""Links to the shop's artist and release pages. See docs/catalog.md."""

from __future__ import annotations

from urllib.parse import quote

from .entries import Release


def _segment(text: str) -> str:
    return quote(text, safe="")


def artist_url(base: str, artist: str) -> str:
    return base.rstrip("/") + "/artists/" + _segment(artist)


def release_url(base: str, release: Release) -> str:
    return artist_url(base, release.artist) + "/releases/" + _segment(release.title)
'''

REFERENCE = {"crate/entries.py": ENTRIES_REF, "crate/links.py": LINKS_REF}

TRAP_SOLUTION = {"crate/links.py": '''"""Links to the shop's artist and release pages. See docs/catalog.md."""

from __future__ import annotations

from urllib.parse import quote

from .entries import Release


def artist_url(base: str, artist: str) -> str:
    return base.rstrip("/") + "/artists/" + quote(artist)


def release_url(base: str, release: Release) -> str:
    return artist_url(base, release.artist) + "/releases/" + quote(release.title)
'''}

# D105/D109: the trap's code shape, searched in what the model writes after turn 1: a
# quote call with no safe argument (quote_plus does not match).
TRAP_PATTERNS = (r'\bquote\((?![\s\S]{0,80}?\bsafe\s*=)',)
