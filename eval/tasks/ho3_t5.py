"""ho3-t5: a hand-written cron expression parser, matcher and next-run search (third held-out
task set; the hardest of the five, as ho2-t5 was in its set).

A1 categories: several distant facts needed together (turn 7's next-run search and @
shortcuts need C2 and C3 from turn 1, the day-of-week numbering decided in turn 5, and the
shortcut table and the two-day-field rule from the document read in turn 2); a vague
"continue ... the way we settled"; a decision that overrides the document (turn 5's 1-7
Monday-first numbering against the document's 0/7 Sunday, which also makes the document's
own ``@weekly`` expansion invalid); information needs that arise mid-task (names and the
two-day-field rule in turn 5, from the document); an oversized read; restart before turn 5.
"""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho3-t5"
SET = "heldout3"
TITLE = "cronwheel: parse cron expressions with names and @ shortcuts, match times, find the next run"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "the parser is hand-written: the package imports none of re, croniter, dateutil or "
          "calendar",
    "C2": "every invalid expression raises CronError from cronwheel/errors.py with .field set "
          "to the 0-based index of the bad field (0 minute ... 4 day of week), or to None when "
          "the expression does not have five fields, an unknown @ name included",
    "C3": "next_fire returns the first whole minute strictly after the given time (its seconds "
          "are dropped and its own minute never counts), and raises CronError with .field None "
          "when nothing matches in the four years after it",
}
TRAP = ("already tried stepping forward one minute at a time and calling the matcher until it "
        "hit; it failed because '0 0 29 2 *' walked through more than a million minutes and the "
        "suite timed out")
DECISION = "day of week 1 = Monday ... 7 = Sunday, 0 invalid (turn 5, overrides the document)"


def day_ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


LEGACY = '''"""Ordinal day labels for the job calendar page (do not change)."""


def day_ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"
'''

ERRORS = '''"""Errors."""


class CronError(ValueError):
    """An expression that cannot be used. ``field`` is the bad field's index, or None."""

    def __init__(self, field, message):
        super().__init__(f"field {field}: {message}")
        self.field = field
'''

STUB = '''"""Cron schedules for the job runner. See docs/cron_syntax.md."""

from .errors import CronError  # noqa: F401


def parse_cron(expr):
    """Parse a five-field cron expression."""
    raise NotImplementedError


def cron_matches(expr, when):
    """Does the datetime ``when`` (seconds ignored) fall on the schedule ``expr``?"""
    raise NotImplementedError


def next_fire(expr, after):
    """The first time after ``after`` that the schedule ``expr`` fires."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cronwheel.schedule import cron_matches  # noqa: E402


class MatchTests(unittest.TestCase):
    def test_every_quarter_hour(self):
        self.assertTrue(cron_matches("*/15 * * * *", datetime(2027, 3, 1, 10, 30)))

    def test_sunday_is_zero(self):
        self.assertTrue(cron_matches("0 9 * * 0", datetime(2027, 3, 7, 9, 0)))
'''

DOC_INTRO = [
    "The schedule syntax the job runner reads from its jobs file.",
    "",
    "## Fields",
    "",
    "- An expression has five fields separated by spaces or tabs: minute (0-59), hour",
    "  (0-23), day of month (1-31), month (1-12) and day of week (0-7, where 0 and 7 are both",
    "  Sunday, 1 is Monday). Leading and trailing whitespace is ignored.",
    "- A field is a comma-separated list of items. An item is `*`, a number `n` or a range",
    "  `a-b` with a <= b, optionally followed by `/s` with s >= 1: `*/s` takes every s-th",
    "  value from the field's minimum, `a-b/s` every s-th value from a up to b, and `a/s`",
    "  every s-th value from a up to the field's maximum.",
    "- Three-letter English names may be used wherever a number may, in any case and in",
    "  ranges: JAN to DEC for months, SUN to SAT for days of the week (SUN = 0).",
    "",
    "## The two day fields",
    "",
    "- When both the day-of-month and the day-of-week field are restricted, a day matches",
    "  when either of them matches. A field counts as restricted unless it is exactly `*`",
    "  (so `*/1` is restricted). When one of the two is `*`, only the other decides.",
    "",
    "## Shortcuts",
    "",
    "| shortcut | means |",
    "|---|---|",
    "| @yearly | 0 0 1 1 * |",
    "| @monthly | 0 0 1 * * |",
    "| @weekly | 0 0 * * 0 |",
    "| @daily | 0 0 * * * |",
    "| @hourly | 0 * * * * |",
    "",
    "## Next run",
    "",
    "- The next run after a given time is the first whole minute strictly after it that",
    "  matches; the given time's seconds are ignored. Times are naive local wall-clock times.",
    "- When nothing matches in the four years after the given time, the expression never",
    "  runs (for example `0 0 30 2 *`).",
    "",
    "## Retired: the 2017 runner",
    "",
    "- The 2017 runner read six fields with seconds first and accepted `?` and `L`. Neither",
    "  is accepted now.",
]

JOBS = ["backup", "reindex", "invoice-run", "digest-mail", "cache-warm", "log-rotate", "sync-crm"]
EXPRS = ["0 2 * * *", "*/10 * * * *", "30 6 * * 1-5", "0 0 1 * *", "15 3 * * SUN", "0 */4 * * *",
         "45 23 L * *", "0 0 ? * MON", "5,35 * * * *"]


def _record(rnd: random.Random, i: int) -> str:
    return (f"`{rnd.choice(EXPRS)}` | job {rnd.choice(JOBS)} on runner "
            f"{rnd.randint(1, 12)}, last edited {rnd.randint(2016, 2026)}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        n = rnd.choice([rnd.randint(1, 31), rnd.randint(1, 400)])
        slug = rnd.choice(["calendar_day", "teens", "large_number", "job_calendar"])
        cases.append((slug, f"{n}", repr(day_ordinal(n))))
    return {
        "cronwheel/__init__.py": '"""Schedules for the job runner."""\n',
        "cronwheel/errors.py": ERRORS,
        "cronwheel/legacy.py": LEGACY,
        "cronwheel/schedule.py": STUB,
        "docs/cron_syntax.md": long_doc(rnd, "Job runner schedule syntax", DOC_INTRO, _record),
        "tests/test_schedule.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("cronwheel.legacy", "day_ordinal",
                                                      "DayOrdinalCatalogTests", cases),
    }


TURNS = [
    "This session builds `cronwheel`, the schedule parser of our job runner. Rules: (1) the "
    "parser is hand-written, so the package imports none of re, croniter, dateutil or "
    "calendar; (2) every invalid expression raises CronError from cronwheel/errors.py with "
    "`.field` set to the 0-based index of the bad field (0 for minute up to 4 for day of "
    "week), or to None when the expression does not have five fields, an unknown @ name "
    "included; (3) next_fire returns the first whole minute strictly after the given time, "
    "so the given time's seconds are dropped and its own minute never counts, and it raises "
    "CronError with `.field` None when nothing matches in the four years after it. We already "
    "tried stepping forward one minute at a time and calling the matcher until it hit, and it "
    "failed because '0 0 29 2 *' walked through more than a million minutes and the suite "
    "timed out. To begin, read cronwheel/schedule.py and cronwheel/errors.py and tell me what "
    "has to be written; do not edit yet. " + NO_QUESTIONS,
    "Read docs/cron_syntax.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize the syntax in five bullet points.",
    "Implement `parse_cron(expr)` and `cron_matches(expr, when)` for numbers, `*`, lists, "
    "ranges and steps; leave names and the @ shortcuts for later. Then run `python -m "
    "unittest tests.test_schedule -v`.",
    "Run all tests verbosely with `python -m unittest discover -s tests -v` and tell me how "
    "many ran and which failed.",
    "Add month and day names to the parser, as the syntax document describes them, and make "
    "cron_matches follow the document's rule for the two day fields. One decision overrides "
    "the document: in our schedules the day of week runs from 1 for Monday to 7 for Sunday, "
    "0 is not allowed, and MON to SUN are 1 to 7. Update the tests to match and run `python "
    "-m unittest tests.test_schedule -v`.",
    "Run all tests verbosely again (`python -m unittest discover -s tests -v`) and report "
    "the totals.",
    "Continue: write `next_fire(expr, after)` and support the @ shortcuts, so our schedules "
    "work the way we settled. Add tests in tests/test_next.py and run `python -m unittest "
    "tests.test_next -v`.",
    "Finally, run `python -m unittest discover -s tests` once more and list what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": r'''import ast
import sys
import unittest
from datetime import datetime as T
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cronwheel.errors import CronError  # noqa: E402
from cronwheel.schedule import cron_matches, next_fire, parse_cron  # noqa: E402

PKG = ROOT / "cronwheel"


class HiddenTests(unittest.TestCase):
    def check(self, cases):
        for expr, when, want in cases:
            self.assertEqual(cron_matches(expr, when), want, (expr, when))

    def test_f_match(self):
        self.check([("*/15 * * * *", T(2027, 3, 1, 10, 30), True),
                    ("*/15 * * * *", T(2027, 3, 1, 10, 31), False),
                    ("0 9-17/2 * * *", T(2027, 3, 1, 9, 0), True),
                    ("0 9-17/2 * * *", T(2027, 3, 1, 17, 0), True),
                    ("0 9-17/2 * * *", T(2027, 3, 1, 10, 0), False),
                    ("0 9-17/2 * * *", T(2027, 3, 1, 19, 0), False),
                    ("5,10-12 0 1 1 *", T(2028, 1, 1, 0, 11), True),
                    ("5,10-12 0 1 1 *", T(2028, 1, 1, 0, 13), False),
                    ("30 6 * * 1-5", T(2027, 3, 1, 6, 30), True),
                    ("30 6 * * 1-5", T(2027, 3, 6, 6, 30), False),
                    ("0 12 */10 * *", T(2027, 5, 31, 12, 0), True),
                    ("0 12 */10 * *", T(2027, 5, 21, 12, 0), True),
                    ("0 12 */10 * *", T(2027, 5, 30, 12, 0), False),
                    ("15/20 * * * *", T(2027, 3, 1, 4, 55), True),
                    ("15/20 * * * *", T(2027, 3, 1, 4, 5), False),
                    ("0 0 1 * *", T(2027, 4, 1, 0, 0, 45), True),
                    ("  0\t0  1 *   * ", T(2027, 4, 1, 0, 0), True)])

    def test_f_names(self):
        self.check([("0 8 * JAN-MAR MON-FRI", T(2027, 3, 5, 8, 0), True),
                    ("0 8 * JAN-MAR MON-FRI", T(2027, 3, 6, 8, 0), False),
                    ("0 8 * JAN-MAR MON-FRI", T(2027, 4, 1, 8, 0), False),
                    ("0 8 * * sun", T(2027, 3, 7, 8, 0), True),
                    ("0 8 * * 7", T(2027, 3, 7, 8, 0), True),
                    ("0 8 * * 7", T(2027, 3, 1, 8, 0), False),
                    ("0 8 * * 1", T(2027, 3, 1, 8, 0), True),
                    ("0 8 * * 1", T(2027, 3, 7, 8, 0), False),
                    ("0 10 * * FRI-SUN", T(2027, 3, 6, 10, 0), True),
                    ("0 10 * * FRI-SUN", T(2027, 3, 7, 10, 0), True),
                    ("0 10 * * FRI-SUN", T(2027, 3, 3, 10, 0), False),
                    ("0 0 1 jan,Jul *", T(2027, 7, 1, 0, 0), True)])
        for expr in ("0 8 * * 0", "0 8 * * 0-6", "0 8 * * SUN-SAT"):
            with self.assertRaises(CronError, msg=expr):
                cron_matches(expr, T(2027, 3, 7, 8, 0))

    def test_f_day_rule(self):
        self.check([("0 0 13 * FRI", T(2027, 8, 13), True),
                    ("0 0 13 * FRI", T(2027, 9, 13), True),
                    ("0 0 13 * FRI", T(2027, 3, 5), True),
                    ("0 0 13 * FRI", T(2027, 3, 3), False),
                    ("0 0 13 * *", T(2027, 3, 5), False),
                    ("0 0 13 * *", T(2027, 9, 13), True),
                    ("0 0 * * FRI", T(2027, 9, 13), False),
                    ("0 0 * * FRI", T(2027, 3, 5), True),
                    ("0 0 */1 * 5", T(2027, 3, 1), True)])

    def test_f_next(self):
        for expr, after, want in (("*/15 * * * *", T(2027, 3, 1, 10, 7, 30), T(2027, 3, 1, 10, 15)),
                                  ("0 0 29 2 *", T(2027, 3, 1), T(2028, 2, 29)),
                                  ("@weekly", T(2027, 3, 3, 12, 0), T(2027, 3, 7)),
                                  ("@weekly", T(2027, 3, 7), T(2027, 3, 14)),
                                  ("@hourly", T(2027, 3, 1, 10, 59, 59), T(2027, 3, 1, 11, 0)),
                                  ("@daily", T(2027, 3, 1, 23, 59), T(2027, 3, 2)),
                                  ("@monthly", T(2027, 5, 31, 23, 59), T(2027, 6, 1)),
                                  ("@yearly", T(2027, 6, 1), T(2028, 1, 1)),
                                  ("30 6 * * MON-FRI", T(2027, 3, 5, 7, 0), T(2027, 3, 8, 6, 30)),
                                  ("0 0 31 * *", T(2027, 4, 1), T(2027, 5, 31)),
                                  ("0 0 13 * FRI", T(2027, 3, 1), T(2027, 3, 5))):
            self.assertEqual(next_fire(expr, after), want, (expr, after))

    def test_c1_hand_written(self):
        banned = {"re", "croniter", "dateutil", "calendar"}
        for path in PKG.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    mods = [node.module or ""]
                for m in mods:
                    self.assertNotIn(m.split(".")[0], banned, f"{path.name} imports {m}")

    def test_c2_field_errors(self):
        cases = [("60 * * * *", 0), ("* 24 * * *", 1), ("* * 0 * *", 2), ("* * 32 * *", 2),
                 ("* * * 13 *", 3), ("* * * FOO *", 3), ("* * * * 8", 4), ("* * * * FUN", 4),
                 ("*/0 * * * *", 0), ("5-1 * * * *", 0), ("* * * *", None),
                 ("* * * * * *", None), ("1,,2 * * * *", 0), ("@fortnightly", None), ("", None),
                 ("* * * * MON-", 4), ("a * * * *", 0), ("* * * JAN-FRI *", 3),
                 ("* 1-2-3 * * *", 1), ("-1 * * * *", 0), ("* 3/x * * *", 1)]
        for expr, field in cases:
            with self.assertRaises(CronError, msg=expr) as cm:
                parse_cron(expr)
            self.assertEqual(cm.exception.field, field, expr)
        with self.assertRaises(CronError) as cm:
            cron_matches("* 24 * * *", T(2027, 3, 1))
        self.assertEqual(cm.exception.field, 1)
        with self.assertRaises(CronError) as cm:
            next_fire("* * * 13 *", T(2027, 3, 1))
        self.assertEqual(cm.exception.field, 3)

    def test_c3_next_strict(self):
        self.assertEqual(next_fire("* * * * *", T(2027, 3, 1, 10, 0)), T(2027, 3, 1, 10, 1))
        self.assertEqual(next_fire("* * * * *", T(2027, 3, 1, 10, 0, 59, 999999)),
                         T(2027, 3, 1, 10, 1))
        self.assertEqual(next_fire("*/15 * * * *", T(2027, 3, 1, 10, 15)), T(2027, 3, 1, 10, 30))
        got = next_fire("30 * * * *", T(2027, 3, 1, 10, 29, 59, 5))
        self.assertEqual((got, got.second, got.microsecond), (T(2027, 3, 1, 10, 30), 0, 0))
        self.assertEqual(next_fire("0 0 29 2 *", T(2028, 3, 1)), T(2032, 2, 29))
        for expr in ("0 0 30 2 *", "0 0 31 4,6 *"):
            with self.assertRaises(CronError, msg=expr) as cm:
                next_fire(expr, T(2027, 3, 1))
            self.assertIsNone(cm.exception.field, expr)


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"cronwheel/schedule.py": '''"""Cron schedules for the job runner. See docs/cron_syntax.md."""

from datetime import datetime, time, timedelta

from .errors import CronError

MONTHS = {n: i + 1 for i, n in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
DAYS = {n: i + 1 for i, n in enumerate("MON TUE WED THU FRI SAT SUN".split())}
FIELDS = [(0, 59, {}), (0, 23, {}), (1, 31, {}), (1, 12, MONTHS), (1, 7, DAYS)]
MACROS = {"@yearly": "0 0 1 1 *", "@monthly": "0 0 1 * *", "@weekly": "0 0 * * 7",
          "@daily": "0 0 * * *", "@hourly": "0 * * * *"}
DIGITS = set("0123456789")


def _value(tok, idx):
    lo, hi, names = FIELDS[idx]
    if tok and set(tok) <= DIGITS:
        v = int(tok)
    elif tok.upper() in names:
        v = names[tok.upper()]
    else:
        raise CronError(idx, f"bad value {tok!r}")
    if not lo <= v <= hi:
        raise CronError(idx, f"{v} out of range")
    return v


def _field(text, idx):
    lo, hi, _ = FIELDS[idx]
    out = set()
    for item in text.split(","):
        rng, slash, step = item.partition("/")
        if slash:
            if not step or not set(step) <= DIGITS or int(step) < 1:
                raise CronError(idx, f"bad step {step!r}")
            step = int(step)
        else:
            step = 1
        if rng == "*":
            a, b = lo, hi
        elif "-" in rng:
            x, y = rng.split("-", 1)
            a, b = _value(x, idx), _value(y, idx)
            if a > b:
                raise CronError(idx, "range runs backwards")
        else:
            a = _value(rng, idx)
            b = hi if slash else a
        out |= set(range(a, b + 1, step))
    return out


def parse_cron(expr):
    if not isinstance(expr, str):
        raise CronError(None, "not text")
    text = expr.strip()
    if text.startswith("@"):
        if text.lower() not in MACROS:
            raise CronError(None, f"unknown shortcut {text!r}")
        text = MACROS[text.lower()]
    parts = text.split()
    if len(parts) != 5:
        raise CronError(None, "five fields expected")
    sets = [_field(p, i) for i, p in enumerate(parts)]
    return {"minute": sets[0], "hour": sets[1], "dom": sets[2], "month": sets[3], "dow": sets[4],
            "dom_any": parts[2] == "*", "dow_any": parts[4] == "*"}


def _day_ok(c, day):
    dom, dow = day.day in c["dom"], day.isoweekday() in c["dow"]
    if c["dom_any"] and c["dow_any"]:
        return True
    if c["dom_any"]:
        return dow
    if c["dow_any"]:
        return dom
    return dom or dow


def cron_matches(expr, when):
    c = parse_cron(expr)
    return (when.minute in c["minute"] and when.hour in c["hour"] and when.month in c["month"]
            and _day_ok(c, when.date()))


def next_fire(expr, after):
    c = parse_cron(expr)
    start = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    try:
        limit = after.replace(year=after.year + 4)
    except ValueError:
        limit = after.replace(year=after.year + 4, month=3, day=1)
    day = start.date()
    while datetime.combine(day, time()) <= limit:
        if day.month in c["month"] and _day_ok(c, day):
            for h in sorted(c["hour"]):
                for m in sorted(c["minute"]):
                    t = datetime(day.year, day.month, day.day, h, m)
                    if start <= t <= limit:
                        return t
        day += timedelta(days=1)
    raise CronError(None, "no run in the next four years")
'''}
