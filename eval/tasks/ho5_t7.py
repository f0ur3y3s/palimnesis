"""Finding-aid publication for a county archive and its back-of-volume person index."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t7"
SET = "heldout5"
TITLE = "findaid: archival catalogue rows and back-of-volume name headings"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "emit no console diagnostics, exit, or None for broken catalogue rows; "
          "raise findaid/errors.py AidError(line_no, message)",
    "C2": "findaid.legacy.level_name resolves descriptive hierarchy, with no second reference-depth "
          "implementation",
    "C3": "retain catalogue sequence within every person's reference list",
}
TRAP = ("already tried alphabetizing with key=str.casefold; accented initials sorted past Z")
TRAP_WARNING = ("Also, we already tried `key=str.casefold` alphabetization, and it failed "
                "because code-point order tucked Ångström and Éluard beyond Zweig; file "
                "each accented initial with its corresponding unaccented letter.")
TRAP_TURN = 6

LEVELS = ("fonds", "series", "file", "item")


def level_name(ref: str) -> str:
    parts = ref.strip().split("/")
    if len(parts) > len(LEVELS) or any(not p.strip() for p in parts):
        raise ValueError(f"no level for {ref!r}")
    return LEVELS[len(parts) - 1]


LEGACY = '''"""Levels of description used by the record office (agreed with the county archivist;
leave alone)."""

LEVELS = ("fonds", "series", "file", "item")


def level_name(ref: str) -> str:
    parts = ref.strip().split("/")
    if len(parts) > len(LEVELS) or any(not p.strip() for p in parts):
        raise ValueError(f"no level for {ref!r}")
    return LEVELS[len(parts) - 1]
'''

ERRORS = '''"""Failures while reading a finding aid."""


class AidError(ValueError):
    """An entry line that has to be refused; ``line_no`` starts at 1."""

    def __init__(self, line_no: int, message: str):
        super().__init__(f"entry at line {line_no}: {message}")
        self.line_no = line_no
        self.message = message
'''

RECORDS_STUB = '''"""Finding-aid lines -> Entry records. See docs/finding_aids.md."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import AidError
from .legacy import level_name

ROLES = ("creator", "correspondent", "subject", "donor")


@dataclass(frozen=True)
class Entry:
    ref: str
    name: str
    role: str
    level: str


def read_entry(line: str, line_no: int) -> Entry:
    """An entry line ``ref|name|role`` -> Entry."""
    raise NotImplementedError


def load_entries(path) -> tuple[list[Entry], list[AidError]]:
    """Each entry line of a finding-aid file -> (entries, errors)."""
    raise NotImplementedError
'''

INDEX_STUB = '''"""The index of persons at the back of a finding aid. See docs/finding_aids.md."""

from __future__ import annotations

from .records import Entry


def index_names(entries: list[Entry]) -> list[str]:
    """The persons named in the entries, each once, in index order."""
    raise NotImplementedError


def index_text(entries: list[Entry]) -> str:
    """The printed index: one line per person with their reference codes."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from findaid.errors import AidError  # noqa: E402
from findaid.index import index_names, index_text  # noqa: E402
from findaid.records import Entry, read_entry  # noqa: E402

LETTER = Entry("DX 418/2/7", "Pemberton, Harriet", "correspondent", "file")
ROWS = [Entry("DX 418/1", "Pemberton, Harriet", "creator", "series"),
        Entry("DX 418/3/1", "de Vries, Anna", "subject", "file"),
        Entry("DX 418/2/7", "Dawson, Ellis", "correspondent", "file"),
        Entry("DX 418/2/9", "Pemberton, Harriet", "correspondent", "file")]


class EntryLineTests(unittest.TestCase):
    def test_entry_reads(self):
        self.assertEqual(read_entry("DX 418/2/7 | Pemberton, Harriet |correspondent", 3), LETTER)

    def test_entry_role_unknown(self):
        with self.assertRaises(AidError):
            read_entry("DX 418/2/7|Pemberton, Harriet|landlord", 3)


class PersonsIndexTests(unittest.TestCase):
    def test_names_in_order(self):
        self.assertEqual(index_names(ROWS),
                         ["Dawson, Ellis", "de Vries, Anna", "Pemberton, Harriet"])

    def test_printed_index(self):
        self.assertEqual(index_text(ROWS),
                         "Dawson, Ellis: DX 418/2/7\\n"
                         "de Vries, Anna: DX 418/3/1\\n"
                         "Pemberton, Harriet: DX 418/1; DX 418/2/9\\n")
'''

DOC_INTRO = [
    "## Catalogue export schema",
    "",
    "Represent an entry as `ref|name|role`, using exactly two pipe separators.",
    "Skip blanks and `#` catalogue remarks. A remark starts in column one.",
    "Trim padding at cell boundaries.",
    "A reference starts with 2–4 uppercase collection letters, a space, and the collection number.",
    "Append zero to three slash-prefixed number components. Compare `DX 418` with `DX 418/2/7/3`.",
    "Retrieve the description tier (fonds, series, file, item) via `findaid.legacy.level_name(ref)`.",
    "The cataloguer's nonblank name spelling survives trimming unchanged.",
    "Allowed roles are lowercase `creator`, `correspondent`, `subject`, and `donor`.",
    "Capture each malformed entry's one-origin catalogue-row position and continue.",
    "",
    "## Printed back matter",
    "",
    "Index every distinct person once, gathering each of their references once per person.",
]

PEOPLE = ["Pemberton, Harriet", "Dawson, Ellis", "Granger, Thomas", "Whitlock, Mary",
          "Ashdown, Rev. Samuel", "Kerridge, Lydia", "Mallory, Jonas", "Fairweather, Ann",
          "Oakes, Benjamin", "Thorne, Cecily", "Bramwell, Josiah", "Lisle, Margaret"]
NOTES = ["estate papers", "parish chest deposit", "solicitor's bundle", "tithe dispute",
         "school log books", "family letters", "mill accounts", "vestry minutes"]


def _ref(rnd: random.Random) -> str:
    depth = rnd.randint(0, 3)
    tail = "".join(f"/{rnd.randint(1, 40)}" for _ in range(depth))
    return f"{rnd.choice(['DX', 'PR', 'QS', 'MSA', 'ESTB'])} {rnd.randint(1, 999)}{tail}"


def _record(rnd: random.Random, i: int) -> str:
    role = rnd.choice(["creator", "correspondent", "subject", "donor"])
    return f"`{_ref(rnd)}|{rnd.choice(PEOPLE)}|{role}` | {rnd.choice(NOTES)}, entry {i}"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        ref = rnd.choice([_ref(rnd), f" {_ref(rnd)} ", _ref(rnd).replace("/", " / ")])
        slug = rnd.choice(["strongroom_shelf", "accession_slip", "box_label", "searchroom_card",
                           "old_handlist"])
        cases.append((slug, repr(ref), repr(level_name(ref))))
    return {
        "findaid/__init__.py": '"""Finding aids of the county record office."""\n',
        "findaid/errors.py": ERRORS,
        "findaid/legacy.py": LEGACY,
        "findaid/records.py": RECORDS_STUB,
        "findaid/index.py": INDEX_STUB,
        "docs/finding_aids.md": long_doc(rnd, "Catalogue lists and the index of persons",
                                         DOC_INTRO, _record),
        "tests/test_findaid.py": VISIBLE,
        "tests/test_legacy_levels.py": catalog_suite("findaid.legacy", "level_name",
                                                     "LevelNameCatalogTests", cases),
    }


TURNS = [
    "Finish the county catalogue intake and its person index. Rule C1: "
    "invalid entries raise `AidError(line_no, message)` from findaid/errors.py. Report "
    "catalogue faults without stdout, exit, or None. C2: determine the description tier "
    "exclusively through `findaid.legacy.level_name`, without recounting reference components. "
    "C3: preserve catalogue sequence within a person's reference entries. "
    + TRAP_WARNING + " " +
    "Survey findaid/records.py and findaid/index.py. Identify unfinished functions; defer edits. "
    + NO_QUESTIONS,
    "Read docs/finding_aids.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Complete `read_entry(line, line_no)` in findaid/records.py per docs/finding_aids.md. "
    "Run `python -m unittest tests.test_findaid -v`. Index cases remain pending.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Add UTF-8 ingestion via `load_entries(path)` in findaid/records.py. Skip blanks and "
    "column-one `#` remarks. Produce `(entries, errors)`; attach one-origin physical row numbers "
    "to AidErrors. Cover a catalogue intake case in tests/test_findaid.py. Invoke "
    "`python -m unittest tests.test_findaid -v`.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Now write findaid/index.py. `index_names(entries)` returns each distinct person once, "
    "in alphabetical order, ignoring letter case. `index_text(entries)` gives a line for each "
    "person in that same order, `<name>: <ref>; <ref>`, listing the person's reference "
    "codes without repeats, with a newline closing every line; after that run "
    "`python -m unittest tests.test_findaid -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from findaid import records as records_module  # noqa: E402
from findaid.errors import AidError  # noqa: E402
from findaid.index import index_names, index_text  # noqa: E402
from findaid.records import Entry, load_entries, read_entry  # noqa: E402

RECORDS_SRC = (ROOT / "findaid" / "records.py").read_text(encoding="utf-8")
INDEX_SRC = (ROOT / "findaid" / "index.py").read_text(encoding="utf-8")


def catalogue_person_row(ref, name):
    return Entry(ref, name, "subject", "file")


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(read_entry("  QS 12  |Granger, Thomas| donor ", 4),
                         Entry("QS 12", "Granger, Thomas", "donor", "fonds"))
        self.assertEqual(read_entry("ESTB 7/1/30/2|Lisle, Margaret|creator", 1),
                         Entry("ESTB 7/1/30/2", "Lisle, Margaret", "creator", "item"))

    def test_f_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "list.txt"
            p.write_text("# DX 418\\n\\nDX 418/1|Oakes, Benjamin|creator\\nDX 418/1|creator\\n"
                         "DX 418/2|Thorne, Cecily|subject\\nDX 418/2/1/1/1|Thorne, Cecily|subject\\n",
                         encoding="utf-8")
            entries, errors = load_entries(p)
        self.assertEqual([e.ref for e in entries], ["DX 418/1", "DX 418/2"])
        self.assertEqual(sorted(e.line_no for e in errors), [4, 6])

    def test_f_index_names(self):
        rows = [catalogue_person_row("PR 3/1", "Whitlock, Mary"), catalogue_person_row("PR 3/2", "ashdown, Samuel"),
                catalogue_person_row("PR 3/3", "Bramwell, Josiah"), catalogue_person_row("PR 3/4", "Whitlock, Mary"),
                catalogue_person_row("PR 3/5", "Kerridge, Lydia"), catalogue_person_row("PR 3/6", "van Dam, Pieter")]
        self.assertEqual(index_names(rows), ["ashdown, Samuel", "Bramwell, Josiah",
                                             "Kerridge, Lydia", "van Dam, Pieter",
                                             "Whitlock, Mary"])

    def test_f_index_text(self):
        rows = [catalogue_person_row("PR 3/9", "Mallory, Jonas"), catalogue_person_row("PR 3/2", "Fairweather, Ann"),
                catalogue_person_row("PR 3/1", "Mallory, Jonas"), catalogue_person_row("PR 3/9", "Mallory, Jonas")]
        self.assertEqual(index_text(rows), "Fairweather, Ann: PR 3/2\\nMallory, Jonas: PR 3/9; PR 3/1\\n")

    def test_c1_aid_errors(self):
        for line in ("DX 418/1|Oakes, Benjamin", "DX 418/1|Oakes, Benjamin|creator|x",
                     "dx 418/1|Oakes, Benjamin|creator", "DX418|Oakes, Benjamin|creator",
                     "DX 418/1|   |creator", "DX 418/1|Oakes, Benjamin|Creator",
                     "DX 418//2|Oakes, Benjamin|creator", "DX 418/1/2/3/4|Oakes, Benjamin|creator"):
            with self.assertRaises(AidError, msg=line) as cm:
                read_entry(line, 7)
            self.assertEqual(cm.exception.line_no, 7)
        self.assertNotRegex(RECORDS_SRC + INDEX_SRC, r"\\bprint\\s*\\(|sys\\.exit|\\bexit\\(")

    def test_c2_levels_from_legacy(self):
        self.assertNotRegex(RECORDS_SRC, r"\\.count\\(|\\b(fonds|series)\\b")
        original = records_module.level_name
        records_module.level_name = lambda ref: "piece"
        try:
            self.assertEqual(read_entry("DX 418/1|Oakes, Benjamin|creator", 1).level, "piece")
        finally:
            records_module.level_name = original

    def test_c3_refs_in_given_order(self):
        rows = [catalogue_person_row("QS 9/4", "Granger, Thomas"), catalogue_person_row("QS 1/7", "Granger, Thomas"),
                catalogue_person_row("QS 5/2", "Granger, Thomas"), catalogue_person_row("QS 1/7", "Granger, Thomas")]
        self.assertEqual(index_text(rows), "Granger, Thomas: QS 9/4; QS 1/7; QS 5/2\\n")

    def test_t_accented_names_filed_with_plain_letters(self):
        rows = [catalogue_person_row("MSA 2/1", "Zweig, Stefan"), catalogue_person_row("MSA 2/2", "\\u00c9luard, Paul"),
                catalogue_person_row("MSA 2/3", "Eliot, George"), catalogue_person_row("MSA 2/4", "\\u00c5ngstr\\u00f6m, Anders"),
                catalogue_person_row("MSA 2/5", "Aalto, Alvar"), catalogue_person_row("MSA 2/6", "\\u00d6stberg, Ragnar")]
        self.assertEqual(index_names(rows), ["Aalto, Alvar", "\\u00c5ngstr\\u00f6m, Anders",
                                             "Eliot, George", "\\u00c9luard, Paul",
                                             "\\u00d6stberg, Ragnar", "Zweig, Stefan"])
        self.assertTrue(index_text(rows).startswith("Aalto, Alvar: MSA 2/5\\n"
                                                    "\\u00c5ngstr\\u00f6m, Anders: MSA 2/4\\n"))


if __name__ == "__main__":
    unittest.main()
'''}

RECORDS_REF = '''"""Finding-aid lines -> Entry records. See docs/finding_aids.md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import AidError
from .legacy import level_name

ROLES = ("creator", "correspondent", "subject", "donor")
REF_SHAPE = re.compile(r"[A-Z]{2,4} [0-9]+(?:/[0-9]+)*")


@dataclass(frozen=True)
class Entry:
    ref: str
    name: str
    role: str
    level: str


def read_entry(line: str, line_no: int) -> Entry:
    cells = [c.strip() for c in line.rstrip("\\r\\n").split("|")]
    if len(cells) != 3:
        raise AidError(line_no, f"three fields wanted, {len(cells)} found")
    ref, name, role = cells
    if not REF_SHAPE.fullmatch(ref):
        raise AidError(line_no, f"reference code {ref!r} is malformed")
    try:
        level = level_name(ref)
    except ValueError as exc:
        raise AidError(line_no, str(exc)) from None
    if not name:
        raise AidError(line_no, "no person named")
    if role not in ROLES:
        raise AidError(line_no, f"role {role!r} is unknown")
    return Entry(ref, name, role, level)


def load_entries(path) -> tuple[list[Entry], list[AidError]]:
    entries: list[Entry] = []
    errors: list[AidError] = []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    for position, text in enumerate(lines, start=1):
        if not text.strip() or text[:1] == "#":
            continue
        try:
            entries.append(read_entry(text, position))
        except AidError as exc:
            errors.append(exc)
    return entries, errors
'''

INDEX_REF = '''"""Generate archival name-index back matter. See docs/finding_aids.md."""

from __future__ import annotations

import unicodedata

from .records import Entry


def _filing_key(name: str) -> tuple[str, str]:
    # Fold combining marks away when comparing index headings.
    plain = "".join(ch for ch in unicodedata.normalize("NFKD", name)
                    if not unicodedata.combining(ch))
    return plain.casefold(), name


def index_names(entries: list[Entry]) -> list[str]:
    distinct = dict.fromkeys(e.name for e in entries)
    return sorted(distinct, key=_filing_key)


def index_text(entries: list[Entry]) -> str:
    refs: dict[str, list[str]] = {}
    for e in entries:
        seen = refs.setdefault(e.name, [])
        if e.ref not in seen:
            seen.append(e.ref)
    return "".join(f"{name}: {'; '.join(refs[name])}\\n" for name in index_names(entries))
'''

REFERENCE = {"findaid/records.py": RECORDS_REF, "findaid/index.py": INDEX_REF}

TRAP_SOLUTION = {"findaid/index.py": '''"""Generate archival name-index back matter. See docs/finding_aids.md."""

from __future__ import annotations

from .records import Entry


def index_names(entries: list[Entry]) -> list[str]:
    names = []
    for e in entries:
        if e.name not in names:
            names.append(e.name)
    return sorted(names, key=str.casefold)


def index_text(entries: list[Entry]) -> str:
    out = []
    for name in index_names(entries):
        refs = []
        for e in entries:
            if e.name == name and e.ref not in refs:
                refs.append(e.ref)
        out.append(name + ": " + "; ".join(refs) + "\\n")
    return "".join(out)
'''}

# Catch shallow alphabetical ordering without Unicode mark handling.
TRAP_PATTERNS = (
    r'^(?![\s\S]*\bnormalize\()[\s\S]*(?:\bsorted\(|\.sort\()',
)
