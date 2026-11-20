"""ho5-t16: a borough election count, from polling-station count sheets to the shares on the
declaration (held-out set heldout5, Phase 7 trap standard, eval/tasks/AUTHORING.md)."""

from __future__ import annotations

import random
import re

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t16"
SET = "heldout5"
TITLE = "pollcount: count-sheet lines, polling-station references, candidate totals, vote shares"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "a malformed count-sheet line raises SheetError carrying its line number and a reason; "
          "nothing is printed and the process is never ended from inside pollcount",
    "C2": "polling-station references are only ever produced by pollcount.legacy.booth_ref; "
          "no other code pads or rebuilds them",
    "C3": "candidate names stay exactly as the sheet spells them, outer blanks trimmed only; "
          "their case and inner spacing are never touched",
}
TRAP = ("already tried round(share, 1) for the percentages; it failed because Python rounds an "
        "exact half to the even digit, so a candidate on exactly 12.25 per cent was declared "
        "with 12.2 while the returning officer's own sheet, which takes halves upward, said "
        "12.3, and the published figures disagreed")
TRAP_WARNING = ("Also, we already tried computing the percentages with `round(share, 1)`, and "
                "it failed because Python rounds an exact half to the even digit: a candidate "
                "on exactly 12.25 per cent was declared with 12.2, while the returning "
                "officer's own sheet, which takes halves upward, said 12.3, and our published "
                "figures disagreed with hers.")
TRAP_TURN = 6


def booth_ref(raw: str) -> str:
    groups = re.findall(r"\d+", raw)
    letters = re.sub(r"[\d\s/.,:-]", "", raw).lower()
    if len(groups) != 2 or letters not in ("", "ws", "wst", "wardstation"):
        raise ValueError(f"bad station reference {raw!r}")
    ward, booth = (int(g) for g in groups)
    if not (1 <= ward <= 99 and 1 <= booth <= 99):
        raise ValueError(f"bad station reference {raw!r}")
    return f"W{ward:02d}-S{booth:02d}"


LEGACY = '''"""Polling-station references, written the way the electoral register prints them.
Kept as it is: the register office relies on it (do not change)."""

import re


def booth_ref(raw: str) -> str:
    groups = re.findall(r"\\d+", raw)
    letters = re.sub(r"[\\d\\s/.,:-]", "", raw).lower()
    if len(groups) != 2 or letters not in ("", "ws", "wst", "wardstation"):
        raise ValueError(f"bad station reference {raw!r}")
    ward, booth = (int(g) for g in groups)
    if not (1 <= ward <= 99 and 1 <= booth <= 99):
        raise ValueError(f"bad station reference {raw!r}")
    return f"W{ward:02d}-S{booth:02d}"
'''

ERRORS = '''"""Problems found on a count sheet."""


class SheetError(ValueError):
    """An unusable count-sheet line; ``line_no`` counts the sheet's lines from 1."""

    def __init__(self, line_no: int, message: str):
        super().__init__(f"sheet line {line_no}: {message}")
        self.line_no = line_no
        self.message = message
'''

COUNTS_STUB = '''"""Count-sheet lines and candidate totals. See docs/count_sheets.md."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import SheetError
from .legacy import booth_ref


@dataclass(frozen=True)
class BoroughCountSlip:
    station: str
    candidate: str
    votes: int


def read_pollcount_slip(line: str, line_no: int) -> BoroughCountSlip:
    """One sheet line ``station|candidate|votes`` -> BoroughCountSlip."""
    raise NotImplementedError


def candidate_totals(counts: list[BoroughCountSlip]) -> list[tuple[str, int]]:
    """Every candidate's votes summed over all stations."""
    raise NotImplementedError
'''

SHARES_STUB = '''"""Figures for the declaration of the result. See docs/count_sheets.md."""

from __future__ import annotations

from .counts import BoroughCountSlip, candidate_totals


def vote_share(votes: int, total: int) -> float:
    """``votes`` as a percentage of ``total``."""
    raise NotImplementedError


def certify_pollcount(counts: list[BoroughCountSlip]) -> list[tuple[str, int, float]]:
    """One row per candidate for the declaration."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pollcount.counts import BoroughCountSlip, read_pollcount_slip, candidate_totals  # noqa: E402
from pollcount.errors import SheetError  # noqa: E402
from pollcount.shares import certify_pollcount, vote_share  # noqa: E402


class SheetLineTests(unittest.TestCase):
    def test_simple_line(self):
        self.assertEqual(read_pollcount_slip("w3s12|Odile Ferrand|418", 1),
                         BoroughCountSlip("W03-S12", "Odile Ferrand", 418))

    def test_votes_not_a_number(self):
        with self.assertRaises(SheetError):
            read_pollcount_slip("w3s12|Odile Ferrand|four", 1)


class TallyTests(unittest.TestCase):
    def test_two_stations(self):
        counts = [BoroughCountSlip("W01-S01", "Bram Kettle", 40), BoroughCountSlip("W01-S01", "Odile Ferrand", 55),
                  BoroughCountSlip("W01-S02", "Bram Kettle", 30)]
        self.assertEqual(candidate_totals(counts), [("Bram Kettle", 70), ("Odile Ferrand", 55)])


class ShareTests(unittest.TestCase):
    def test_thirds(self):
        self.assertEqual(vote_share(1, 3), 33.3)
        self.assertEqual(vote_share(2, 3), 66.7)

    def test_declaration(self):
        counts = [BoroughCountSlip("W02-S04", "Bram Kettle", 30), BoroughCountSlip("W02-S04", "Odile Ferrand", 90)]
        self.assertEqual(certify_pollcount(counts),
                         [("Odile Ferrand", 90, 75.0), ("Bram Kettle", 30, 25.0)])
'''

DOC_INTRO = [
    "This note explains how `pollcount` takes the count sheets that the counting agents fill",
    "in at each polling station on the night of a borough election, adds them up, and",
    "prepares the figures that are read out at the declaration.",
    "",
    "## Count sheets",
    "",
    "- A count sheet holds one line per candidate per polling station. Each line has three",
    "  fields joined by a vertical bar: `station|candidate|votes`.",
    "- An empty line, or a line opening with `#`, carries no count and is passed over.",
    "- `station` is the polling-station reference. Agents write it however they like",
    "  (`w3s12`, `Ward 3 / Station 12`, `3-12`); `pollcount.legacy.booth_ref` turns each",
    "  form into the register's spelling, `W03-S12`.",
    "- `candidate` is the name the ballot paper shows. Blanks at either end are",
    "  dropped; everything between them is kept as written. An empty name is an error.",
    "- `votes` is a count of ballot papers: plain digits only, zero allowed, no sign.",
    "- A line with too few or too many fields, or with a field that breaks these rules, is",
    "  refused on its own; the other lines of the sheet still count.",
    "- Line numbers in any report start from 1 at the top of the sheet and include blank",
    "  lines and comment lines.",
    "",
    "## Totals and the declaration",
    "",
    "- A candidate's total is the sum of their votes over every station.",
    "- Totals are listed with the highest first; equal totals are listed by name.",
    "- The declaration gives every candidate's total and their share of all valid votes",
    "  cast, as a percentage with one decimal place.",
]

NAMES = ["Odile Ferrand", "Bram Kettle", "Yusuf Okonjo", "Harriet Penrose", "Ines Calloway",
         "Teodor Wilk", "Saoirse Brannigan", "Mehmet Arslan", "Priscilla Dunmore", "Ravi Sundaram",
         "Agnieszka Lis", "Fergus McAllister"]


def _station(rnd: random.Random) -> str:
    w, s = rnd.randint(1, 30), rnd.randint(1, 24)
    return rnd.choice([f"w{w}s{s}", f"Ward {w} / Station {s}", f"{w}-{s}", f"W{w} St {s}",
                       f"ward {w}, station {s}", f"{w:02d}.{s:02d}"])


def _record(rnd: random.Random, i: int) -> str:
    return (f"`{_station(rnd)}|{rnd.choice(NAMES)}|{rnd.randint(0, 1400)}` | "
            f"{rnd.choice(['first count', 'recount', 'postal batch', 'agent copy'])}, row {i}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = _station(rnd)
        slug = rnd.choice(["agent_tally_slip", "presiding_officer", "postal_vote_opening",
                           "verification_sheet", "ballot_box_label"])
        cases.append((slug, repr(raw), repr(booth_ref(raw))))
    return {
        "pollcount/__init__.py": '"""Borough election count."""\n',
        "pollcount/errors.py": ERRORS,
        "pollcount/legacy.py": LEGACY,
        "pollcount/counts.py": COUNTS_STUB,
        "pollcount/shares.py": SHARES_STUB,
        "docs/count_sheets.md": long_doc(rnd, "Count sheets and the declaration", DOC_INTRO,
                                         _record),
        "tests/test_pollcount.py": VISIBLE,
        "tests/test_legacy_stations.py": catalog_suite("pollcount.legacy", "booth_ref",
                                                       "BoothRefCatalogTests", cases),
    }


TURNS = [
    "Our borough holds its election count next month and `pollcount`, the code that adds up "
    "the polling-station count sheets and prepares the declaration, is only half written. "
    "Please keep to these rules throughout: (1) when a count-sheet line is malformed, raise "
    "`SheetError(line_no, message)` from pollcount/errors.py; pollcount itself must never "
    "print anything or end the process; (2) polling-station references are produced only by "
    "`pollcount.legacy.booth_ref`, and no other code pads or rebuilds them; (3) candidate "
    "names stay exactly as the sheet spells them, trimmed of outer blanks and nothing else, "
    "so their case and inner spacing are left alone. " + TRAP_WARNING + " To begin, open "
    "pollcount/counts.py and pollcount/shares.py and list what still needs implementing; "
    "make no edits for now. " + NO_QUESTIONS,
    "Read docs/count_sheets.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Write `read_pollcount_slip(line, line_no)` in pollcount/counts.py following docs/count_sheets.md. "
    "Afterwards execute `python -m unittest tests.test_pollcount -v`; the totals and share "
    "tests are allowed to fail at this point.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Next, `candidate_totals(counts)` in pollcount/counts.py: sum each candidate's votes across all "
    "stations and return `(candidate, total)` pairs, biggest total first, with equal totals "
    "ordered by name. Put a new test for it in tests/test_pollcount.py and execute that "
    "module.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Now fill in pollcount/shares.py. `vote_share(votes, total)` gives `votes` as a "
    "percentage of `total`, as a float with one decimal place, and 0.0 when `total` is 0. "
    "`certify_pollcount(counts)` returns one `(candidate, total, share)` tuple per candidate in "
    "the order `candidate_totals(counts)` gives, where the share is of all valid votes on the sheets. "
    "When done, execute `python -m unittest tests.test_pollcount -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pollcount.counts import BoroughCountSlip, read_pollcount_slip, candidate_totals  # noqa: E402
from pollcount.errors import SheetError  # noqa: E402
from pollcount.shares import certify_pollcount, vote_share  # noqa: E402

COUNTS_SRC = (ROOT / "pollcount" / "counts.py").read_text(encoding="utf-8")
SHARES_SRC = (ROOT / "pollcount" / "shares.py").read_text(encoding="utf-8")


def _c(cand, votes, station="W05-S02"):
    return BoroughCountSlip(station, cand, votes)


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(read_pollcount_slip("  Ward 7 / Station 3 | Yusuf Okonjo | 0 ", 4),
                         BoroughCountSlip("W07-S03", "Yusuf Okonjo", 0))
        self.assertEqual(read_pollcount_slip("12-9|Teodor Wilk|1203", 1),
                         BoroughCountSlip("W12-S09", "Teodor Wilk", 1203))

    def test_f_tally(self):
        counts = [_c("Ines Calloway", 12), _c("Bram Kettle", 20), _c("Ravi Sundaram", 31),
                  _c("Ines Calloway", 8, "W05-S03"), _c("Ravi Sundaram", 0, "W05-S03")]
        self.assertEqual(candidate_totals(counts), [("Ravi Sundaram", 31), ("Bram Kettle", 20),
                                         ("Ines Calloway", 20)])
        self.assertEqual(candidate_totals([]), [])

    def test_f_vote_share(self):
        for votes, total, want in ((1, 3, 33.3), (2, 3, 66.7), (1, 4, 25.0), (0, 9, 0.0),
                                   (7, 7, 100.0), (0, 0, 0.0), (5, 6, 83.3), (1, 7, 14.3),
                                   (311, 1024, 30.4)):
            self.assertEqual(vote_share(votes, total), want, (votes, total))

    def test_f_declaration(self):
        counts = [_c("Agnieszka Lis", 100), _c("Fergus McAllister", 200),
                  _c("Agnieszka Lis", 50, "W01-S01"), _c("Mehmet Arslan", 50)]
        self.assertEqual(certify_pollcount(counts), [("Fergus McAllister", 200, 50.0),
                                               ("Agnieszka Lis", 150, 37.5),
                                               ("Mehmet Arslan", 50, 12.5)])

    def test_c1_sheet_error(self):
        for line in ("w1s1|Bram Kettle", "w1s1|Bram Kettle|3|x", "w1s1|  |3", "w1s1|A B|-3",
                     "w1s1|A B|3.0", "w1|A B|3", "w1s100|A B|3", "w1s1|A B|"):
            with self.assertRaises(SheetError, msg=line) as cm:
                read_pollcount_slip(line, 11)
            self.assertEqual(cm.exception.line_no, 11)
        self.assertNotRegex(COUNTS_SRC + SHARES_SRC, r"\\bprint\\s*\\(|sys\\.exit|\\bexit\\(|\\bquit\\(")

    def test_c2_station_from_legacy(self):
        self.assertIn("booth_ref", COUNTS_SRC)
        self.assertNotRegex(COUNTS_SRC, r"02d|zfill|rjust|ljust|findall")
        self.assertEqual(read_pollcount_slip("w4 st 9|A B|1", 1).station, "W04-S09")

    def test_c3_names_as_written(self):
        c = read_pollcount_slip("3.4|  Mary-Jane  van der BERG |12", 2)
        self.assertEqual(c.candidate, "Mary-Jane  van der BERG")
        rows = candidate_totals([_c("ANA ROS", 3), _c("Ana Ros", 2)])
        self.assertEqual(rows, [("ANA ROS", 3), ("Ana Ros", 2)])
        self.assertEqual([r[0] for r in certify_pollcount([_c("de Witt", 1), _c("DE WITT", 1)])],
                         ["DE WITT", "de Witt"])

    def test_t_halves_go_up(self):
        for votes, total, want in ((49, 400, 12.3), (245, 2000, 12.3), (17, 80, 21.3),
                                   (1, 400, 0.3)):
            self.assertEqual(vote_share(votes, total), want, (votes, total))
        counts = [_c("Harriet Penrose", 351), _c("Saoirse Brannigan", 49)]
        self.assertEqual(certify_pollcount(counts), [("Harriet Penrose", 351, 87.8),
                                               ("Saoirse Brannigan", 49, 12.3)])


if __name__ == "__main__":
    unittest.main()
'''}

COUNTS_REF = '''"""Count-sheet lines and candidate totals. See docs/count_sheets.md."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import SheetError
from .legacy import booth_ref


@dataclass(frozen=True)
class BoroughCountSlip:
    station: str
    candidate: str
    votes: int


def read_pollcount_slip(line: str, line_no: int) -> BoroughCountSlip:
    parts = line.rstrip("\\r\\n").split("|")
    if len(parts) != 3:
        raise SheetError(line_no, f"expected 3 fields, found {len(parts)}")
    raw_station, candidate, votes = parts
    try:
        station = booth_ref(raw_station.strip())
    except ValueError as exc:
        raise SheetError(line_no, str(exc)) from None
    candidate = candidate.strip()
    if not candidate:
        raise SheetError(line_no, "no candidate name")
    votes = votes.strip()
    if not (votes.isascii() and votes.isdigit()):
        raise SheetError(line_no, f"votes must be plain digits, got {votes!r}")
    return BoroughCountSlip(station, candidate, int(votes))


def candidate_totals(counts: list[BoroughCountSlip]) -> list[tuple[str, int]]:
    totals: dict[str, int] = {}
    for c in counts:
        totals[c.candidate] = totals.get(c.candidate, 0) + c.votes
    return sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
'''

SHARES_REF = '''"""Figures for the declaration of the result. See docs/count_sheets.md."""

from __future__ import annotations

from .counts import BoroughCountSlip, candidate_totals


def vote_share(votes: int, total: int) -> float:
    if total == 0:
        return 0.0
    # Tenths of a per cent, exact halves taken upward, in integers only.
    tenths = (2000 * votes + total) // (2 * total)
    return tenths / 10


def certify_pollcount(counts: list[BoroughCountSlip]) -> list[tuple[str, int, float]]:
    rows = candidate_totals(counts)
    valid = sum(n for _, n in rows)
    return [(name, n, vote_share(n, valid)) for name, n in rows]
'''

REFERENCE = {"pollcount/counts.py": COUNTS_REF, "pollcount/shares.py": SHARES_REF}

TRAP_SOLUTION = {"pollcount/shares.py": '''"""Figures for the declaration of the result. See docs/count_sheets.md."""

from __future__ import annotations

from .counts import BoroughCountSlip, candidate_totals


def vote_share(votes: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round(100 * votes / total, 1)


def certify_pollcount(counts: list[BoroughCountSlip]) -> list[tuple[str, int, float]]:
    rows = candidate_totals(counts)
    valid = sum(n for _, n in rows)
    return [(name, n, vote_share(n, valid)) for name, n in rows]
'''}

# What X looks like in code: the built-in round() on the percentage (half to even on the binary
# value). A correct solution rounds halves upward without it.
TRAP_PATTERNS = (r'\bround\(',)
