"""Apiary visit logs and the hut's colony register."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t1"
SET = "heldout5"
TITLE = "hivebook: inspection rows, colony codes, newest visits, the colony register"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "invalid rows raise InspectionError(row, why) without stdout, process exit, or None",
    "C2": "only hivebook.legacy.colony_code canonicalizes a stand identifier",
    "C3": "public parameters keep their spelling and positions in hivebook/inspections.py and hivebook/standsheet.py",
}
TRAP = ("already tried ordering the register with a plain sorted() over the colony code "
        "strings; it failed because the codes were compared as text, so B-10 and B-11 were "
        "printed ahead of B-9 and the sheet no longer matched the row of hive stands")
TRAP_WARNING = ("Also, we already tried ordering the register with a plain `sorted()` over the "
                "colony code strings, and it failed because the codes were compared as text: "
                "B-10 and B-11 were printed ahead of B-9, and the sheet no longer matched the "
                "row of hive stands in the field.")
TRAP_TURN = 6


def colony_code(raw: str) -> str:
    s = "".join(ch for ch in raw if ch.isalnum()).upper()
    letter, digits = s[:1], s[1:]
    if not letter.isalpha() or not digits.isdigit():
        raise ValueError(f"bad colony code {raw!r}")
    return f"{letter}-{int(digits)}"


LEGACY = '''"""Painted hive-stand spellings. Preserve this implementation."""


def colony_code(raw: str) -> str:
    s = "".join(ch for ch in raw if ch.isalnum()).upper()
    letter, digits = s[:1], s[1:]
    if not letter.isalpha() or not digits.isdigit():
        raise ValueError(f"bad colony code {raw!r}")
    return f"{letter}-{int(digits)}"
'''

ERRORS = '''"""Inspection log errors."""


class InspectionError(ValueError):
    """Rejected hive visit, with its one-based notebook row."""

    def __init__(self, row: int, why: str):
        super().__init__(f"row {row}: {why}")
        self.row = row
        self.why = why
'''

_HEAD = '''"""Inspection log rows -> Inspection records. See docs/hives.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .errors import InspectionError
from .legacy import colony_code

TEMPERS = ("calm", "nervous", "defensive")


@dataclass(frozen=True)
class Inspection:
    colony: str
    day: date
    brood: int
    temper: str
    queen_seen: bool
'''

INSPECTIONS_STUB = _HEAD + '''

def read_inspection(row: str, row_no: int) -> Inspection:
    """Decode ``colony,date,brood,temper,queen``."""
    raise NotImplementedError


def load_inspection_log(path) -> tuple[list[Inspection], list[InspectionError]]:
    """Read physical notebook rows."""
    raise NotImplementedError
'''

REGISTER_STUB = '''"""Printable colony register (docs/hives.md)."""

from __future__ import annotations

from .inspections import Inspection


def newest_by_colony(inspections: list[Inspection]) -> dict[str, Inspection]:
    """Select the latest visit for each stand code."""
    raise NotImplementedError


def register_sheet(inspections: list[Inspection]) -> str:
    """Render the hut's stand list."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hivebook.errors import InspectionError  # noqa: E402
from hivebook.inspections import Inspection, read_inspection  # noqa: E402
from hivebook.standsheet import newest_by_colony, register_sheet  # noqa: E402


class ReadInspectionTests(unittest.TestCase):
    def test_plain_row(self):
        self.assertEqual(read_inspection("b3,2025-05-03,6,calm,yes", 1),
                         Inspection("B-3", date(2025, 5, 3), 6, "calm", True))

    def test_unknown_temper(self):
        with self.assertRaises(InspectionError):
            read_inspection("b3,2025-05-03,6,grumpy,yes", 1)


class RegisterSheetTests(unittest.TestCase):
    LOG = [Inspection("B-1", date(2025, 5, 3), 4, "calm", True),
           Inspection("A-7", date(2025, 5, 3), 7, "nervous", False),
           Inspection("B-1", date(2025, 5, 17), 5, "calm", False),
           Inspection("A-3", date(2025, 5, 10), 3, "defensive", True)]

    def test_latest(self):
        newest = newest_by_colony(self.LOG)
        self.assertEqual(set(newest), {"A-3", "A-7", "B-1"})
        self.assertEqual(newest["B-1"].brood, 5)

    def test_register(self):
        self.assertEqual(register_sheet(self.LOG),
                         "A-3 2025-05-10 brood=3 defensive queen:yes\\n"
                         "A-7 2025-05-03 brood=7 nervous queen:no\\n"
                         "B-1 2025-05-17 brood=5 calm queen:no\\n")
'''

DOC_INTRO = [
    "Hut register inputs come from the club's out-apiaries.",
    "",
    "## Log rows",
    "",
    "- Five comma-delimited columns per hive visit:",
    "  `colony,date,brood,temper,queen`.",
    "- Omit whitespace-only rows and `#` remarks.",
    "- Strip surrounding column whitespace.",
    "- `colony`: Painted stand ID (apiary letter + stand number). Keep spellings such",
    "  as `b12`, `B 012` and `b/12` equivalent via `hivebook.legacy.colony_code`.",
    "- `date`: Visit date (`YYYY-MM-DD`).",
    "- `brood`: Occupied brood frames, integer 0 through 20 inclusive.",
    "- `temper`: Accept `calm`, `nervous` or `defensive` case-insensitively.",
    "  Normalize to lowercase.",
    "- `queen`: Case-insensitive `yes` for sighted queens, `no` otherwise.",
    "- A rejected visit leaves the rest of the notebook readable.",
    "- Index every notebook row (1-based) for the inspector, including remarks and blanks.",
    "",
    "## The register",
    "",
    "- Show only the newest inspection per colony.",
    "- Break same-day ties by preferring the later notebook row.",
    "",
    "## Notes column of the appendix",
    "",
    "Archived visits include observer names, remaining food frames, the week's",
    "varroa-board drop and the apiary weather.",
]

INSPECTORS = ["Mabel", "Idris", "Ffion", "Gareth", "Rhiannon", "Osian", "Bethan", "Huw",
              "Carys", "Emrys"]
APIARY_WEATHER = ["warm and still", "breezy, high cloud", "sunny spells", "close and thundery",
           "cool after rain", "bright but gusty", "muggy, light drizzle", "clear blue sky"]
TEMPER_SPELLINGS = ["calm", "Calm", "nervous", "NERVOUS", "defensive", "Defensive"]


def _raw_code(rnd: random.Random) -> str:
    letter, number = rnd.choice("ABCDEFGH"), rnd.randint(1, 40)
    return rnd.choice([f"{letter.lower()}{number}", f"{letter} {number:03d}",
                       f"{letter.lower()}/{number}", f"{letter}-{number}"])


def _record(rnd: random.Random, i: int) -> str:
    day = f"2025-{rnd.randint(4, 9):02d}-{rnd.randint(1, 28):02d}"
    row = (f"{_raw_code(rnd)},{day},{rnd.randint(0, 12)},{rnd.choice(TEMPER_SPELLINGS)},"
           f"{rnd.choice(['yes', 'no', 'Yes', 'NO'])}")
    return (f"`{row}` | inspector {rnd.choice(INSPECTORS)}; stores {rnd.randint(1, 9)} frames; "
            f"{rnd.randint(0, 60)} mites on the board; {rnd.choice(APIARY_WEATHER)}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        letter, number = rnd.choice("ABCDEFGHJK"), rnd.randint(1, 250)
        raw = rnd.choice([f" {letter.lower()}{number} ", f"{letter}-{number:04d}",
                          f"{letter.lower()} / {number}", f"{letter}.{number}",
                          f"{letter}{number:02d}"])
        slug = rnd.choice(["spring_check", "swarm_watch", "winter_feed", "mite_count",
                           "super_lift"])
        cases.append((slug, repr(raw), repr(colony_code(raw))))
    return {
        "hivebook/__init__.py": '"""Beekeeping club inspection log."""\n',
        "hivebook/errors.py": ERRORS,
        "hivebook/legacy.py": LEGACY,
        "hivebook/inspections.py": INSPECTIONS_STUB,
        "hivebook/standsheet.py": REGISTER_STUB,
        "docs/hives.md": long_doc(rnd, "The hive inspection log", DOC_INTRO, _record),
        "tests/test_hivebook.py": VISIBLE,
        "tests/test_legacy_colonies.py": catalog_suite("hivebook.legacy", "colony_code",
                                                       "ColonyCodeCatalogTests", cases),
    }


TURNS = [
    "At each hive visit we fill an inspection log. We need `hivebook` to prepare a "
    "colony register for the club hut. Follow our inspection rules. "
    "(1) Reject invalid visits with `InspectionError(row, why)` from hivebook/errors.py. "
    "Neither print nor sys.exit nor None can replace this exception. "
    "(2) Standardize stand codes exclusively via `hivebook.legacy.colony_code`. "
    "(3) Keep public parameters' spelling and positions in hivebook/inspections.py and "
    "hivebook/standsheet.py. " + TRAP_WARNING + " Inspect both modules. Which stubs remain? "
    "This visit is read-only. " + NO_QUESTIONS,
    "Read docs/hives.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Implement `read_inspection(row, row_no)` in hivebook/inspections.py. Follow docs/hives.md "
    "and run `python -m unittest tests.test_hivebook -v`. Register failures are expected.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Implement `load_inspection_log(path)` in hivebook/inspections.py. Decode UTF-8, "
    "skip blanks and `#` remarks, then return `(inspections, errors)`. Keep notebook "
    "order. Each `InspectionError` identifies its physical row (1-based). "
    "Exercise log loading in tests/test_hivebook.py and run its suite.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Complete hivebook/standsheet.py. `newest_by_colony(inspections)` returns a mapping "
    "from stand code to latest visit. Prefer the later list item when two visits share a date. "
    "`register_sheet(inspections)` prints the hut register in colony-code order. "
    "Format as `<colony> <date> brood=<frames> <temper> queen:<yes|no>`, "
    "using ISO dates. Append LF to every stand entry. Run "
    "`python -m unittest tests.test_hivebook -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import inspect
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hivebook.errors import InspectionError  # noqa: E402
from hivebook.inspections import Inspection, load_inspection_log, read_inspection  # noqa: E402
from hivebook.standsheet import newest_by_colony, register_sheet  # noqa: E402

INSPECTIONS_SRC = (ROOT / "hivebook" / "inspections.py").read_text(encoding="utf-8")
REGISTER_SRC = (ROOT / "hivebook" / "standsheet.py").read_text(encoding="utf-8")


def hive_visit(code, day, brood=4, temper="calm", queen=True):
    return Inspection(code, date(2025, 6, day), brood, temper, queen)


class HivebookHiddenChecks(unittest.TestCase):
    def test_f_read(self):
        self.assertEqual(read_inspection(" a 07 ,2025-04-19, 5 , Calm ,YES", 2),
                         Inspection("A-7", date(2025, 4, 19), 5, "calm", True))
        self.assertEqual(read_inspection("d4,2025-08-30,0,DEFENSIVE,no", 3),
                         Inspection("D-4", date(2025, 8, 30), 0, "defensive", False))

    def test_f_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "log.txt"
            p.write_text("# colony,date,brood,temper,queen\\n\\nc2,2025-06-01,8,nervous,no\\n"
                         "c2,2025-06-01\\nd4,2025-06-02,3,calm,maybe\\nd4,2025-06-09,4,calm,no\\n",
                         encoding="utf-8")
            found, errors = load_inspection_log(p)
        self.assertEqual(found, [Inspection("C-2", date(2025, 6, 1), 8, "nervous", False),
                                 Inspection("D-4", date(2025, 6, 9), 4, "calm", False)])
        self.assertEqual(sorted(e.row for e in errors), [4, 5])

    def test_f_latest(self):
        log = [hive_visit("A-1", 3, 2), hive_visit("A-1", 9, 6), hive_visit("A-1", 9, 7), hive_visit("C-5", 4, 3),
               hive_visit("A-1", 5, 1)]
        newest = newest_by_colony(log)
        self.assertEqual(set(newest), {"A-1", "C-5"})
        self.assertEqual(newest["A-1"], hive_visit("A-1", 9, 7))
        self.assertEqual(newest["C-5"].brood, 3)

    def test_f_register(self):
        log = [hive_visit("C-2", 2, 5, "nervous", False), hive_visit("A-4", 1, 3), hive_visit("B-6", 8, 9),
               hive_visit("C-2", 12, 6, "calm", True), hive_visit("A-4", 6, 4, "defensive", False)]
        self.assertEqual(register_sheet(log),
                         "A-4 2025-06-06 brood=4 defensive queen:no\\n"
                         "B-6 2025-06-08 brood=9 calm queen:yes\\n"
                         "C-2 2025-06-12 brood=6 calm queen:yes\\n")

    def test_c1_inspection_error(self):
        for row in ("a1,2025-05-03,6,calm", "a1,2025-05-03,6,calm,yes,x",
                    "1a,2025-05-03,6,calm,yes", "a1,2025-13-03,6,calm,yes",
                    "a1,2025-05-03,-2,calm,yes", "a1,2025-05-03,21,calm,yes",
                    "a1,2025-05-03,6,calm,perhaps", ",2025-05-03,6,calm,yes"):
            with self.assertRaises(InspectionError, msg=row) as cm:
                read_inspection(row, 9)
            self.assertEqual(cm.exception.row, 9)
        self.assertNotRegex(INSPECTIONS_SRC + REGISTER_SRC, r"\\bprint\\s*\\(|sys\\.exit")

    def test_c2_codes_from_legacy(self):
        self.assertIn("colony_code", INSPECTIONS_SRC)
        self.assertEqual(read_inspection("k/0042,2025-05-03,1,calm,no", 1).colony, "K-42")
        self.assertEqual(read_inspection("h.9,2025-05-03,1,calm,no", 1).colony, "H-9")

    def test_c3_parameters(self):
        self.assertEqual(list(inspect.signature(read_inspection).parameters), ["row", "row_no"])
        self.assertEqual(list(inspect.signature(load_inspection_log).parameters), ["path"])
        self.assertEqual(list(inspect.signature(newest_by_colony).parameters), ["inspections"])
        self.assertEqual(list(inspect.signature(register_sheet).parameters), ["inspections"])

    def test_t_stand_numbers_in_number_order(self):
        log = [hive_visit("B-10", 1), hive_visit("A-11", 2), hive_visit("B-9", 3), hive_visit("A-2", 4),
               hive_visit("C-100", 5), hive_visit("C-20", 6), hive_visit("B-9", 7)]
        codes = [line.split()[0] for line in register_sheet(log).splitlines()]
        self.assertEqual(codes, ["A-2", "A-11", "B-9", "B-10", "C-20", "C-100"])


if __name__ == "__main__":
    unittest.main()
'''}

INSPECTIONS_REF = _HEAD + '''

def _row_refused(row_no: int, why: str) -> InspectionError:
    return InspectionError(row_no, why)


def read_inspection(row: str, row_no: int) -> Inspection:
    parts = [p.strip() for p in row.rstrip("\\n").split(",")]
    if len(parts) != 5:
        raise _row_refused(row_no, f"expected 5 columns, found {len(parts)}")
    raw_colony, raw_day, raw_brood, raw_temper, raw_queen = parts
    try:
        colony = colony_code(raw_colony)
    except ValueError as exc:
        raise _row_refused(row_no, str(exc)) from None
    try:
        day = date.fromisoformat(raw_day)
    except ValueError:
        raise _row_refused(row_no, f"bad date {raw_day!r}") from None
    if not (raw_brood.isascii() and raw_brood.isdigit()) or int(raw_brood) > 20:
        raise _row_refused(row_no, f"bad brood count {raw_brood!r}")
    temper = raw_temper.lower()
    if temper not in TEMPERS:
        raise _row_refused(row_no, f"unknown temper {raw_temper!r}")
    queen = raw_queen.lower()
    if queen not in ("yes", "no"):
        raise _row_refused(row_no, f"queen column must be yes or no, not {raw_queen!r}")
    return Inspection(colony, day, int(raw_brood), temper, queen == "yes")


def load_inspection_log(path) -> tuple[list[Inspection], list[InspectionError]]:
    found, errors = [], []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        try:
            found.append(read_inspection(line, n))
        except InspectionError as exc:
            errors.append(exc)
    return found, errors
'''

REGISTER_REF = '''"""The colony register. See docs/hives.md."""

from __future__ import annotations

from .inspections import Inspection


def _stand_order(code: str) -> tuple[str, int]:
    # A code is an apiary letter and a stand number; the stand number counts as a number.
    letter, _, number = code.partition("-")
    return letter, int(number)


def newest_by_colony(inspections: list[Inspection]) -> dict[str, Inspection]:
    newest: dict[str, Inspection] = {}
    for item in inspections:
        seen = newest.get(item.colony)
        if seen is None or item.day >= seen.day:
            newest[item.colony] = item
    return newest


def register_sheet(inspections: list[Inspection]) -> str:
    newest = newest_by_colony(inspections)
    out = []
    for code in sorted(newest, key=_stand_order):
        item = newest[code]
        queen = "yes" if item.queen_seen else "no"
        out.append(f"{code} {item.day.isoformat()} brood={item.brood} {item.temper} "
                   f"queen:{queen}\\n")
    return "".join(out)
'''

REFERENCE = {"hivebook/inspections.py": INSPECTIONS_REF, "hivebook/standsheet.py": REGISTER_REF}

TRAP_SOLUTION = {"hivebook/standsheet.py": '''"""The colony register. See docs/hives.md."""

from __future__ import annotations

from .inspections import Inspection


def newest_by_colony(inspections: list[Inspection]) -> dict[str, Inspection]:
    newest: dict[str, Inspection] = {}
    for item in inspections:
        if item.colony not in newest or item.day >= newest[item.colony].day:
            newest[item.colony] = item
    return newest


def register_sheet(inspections: list[Inspection]) -> str:
    rows = sorted(newest_by_colony(inspections).values(), key=lambda i: i.colony)
    lines = []
    for i in rows:
        queen = "yes" if i.queen_seen else "no"
        lines.append(f"{i.colony} {i.day:%Y-%m-%d} brood={i.brood} {i.temper} queen:{queen}")
    return "".join(line + "\\n" for line in lines)
'''}

# Detect lexical stand ordering, including tuple keys and attribute getters.
TRAP_PATTERNS = (
    r'\bsorted\(\s*[\w.]+(?:\([^()]*\))?(?:\.(?:keys|items|values)\(\s*\))?\s*(?:,\s*reverse\s*=\s*\w+\s*)?\)',
    r'\.sort\(\s*\)',
    r'key\s*=\s*lambda\s+(\w+)\s*:\s*\(?\s*\1\.colony\s*[,)]',
    r'key\s*=\s*lambda\s+(\w+)\s*:\s*\(?\s*\1\[0\]\s*[,)]',
    r'\b(?:attrgetter\(\s*["\']colony["\']|itemgetter\(\s*0\s*)\)',
)
