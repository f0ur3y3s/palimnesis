"""ho5-t20: noise-nuisance cases at the council's environmental health team, from the
monitoring logs to each case's level (held-out set heldout5, Phase 7 trap standard,
eval/tasks/AUTHORING.md)."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t20"
SET = "heldout5"
TITLE = "noisewatch: monitoring-log lines, case references, night-time measurements, case levels"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "a monitoring-log line that is wrong raises LogError(line_no, message); noisewatch "
          "code contains no print call and no exit call",
    "C2": "case references come out of noisewatch.legacy.case_ref and nowhere else; no code "
          "pads or reassembles them",
    "C3": "the night window is read from NIGHT_START and NIGHT_END in noisewatch/meterlog.py "
          "each time it is needed; the hours are written nowhere else",
}
TRAP = ("already tried the plain average of the dB values, sum(dbs) / len(dbs); it "
        "failed because decibels are a logarithmic scale, so measurements of 50 and 70 dB came out "
        "at 60.0 while the sound level meter, which averages the sound energy, showed 67.0, "
        "and a case was closed as below the threshold")
TRAP_WARNING = ("Also, we already tried taking the plain average of the dB values, "
                "`sum(dbs) / len(dbs)`, and it failed because decibels sit on a "
                "logarithmic scale: measurements of 50 and 70 dB gave 60.0, while the officers' "
                "sound level meter, which averages the sound energy, read 67.0, and one "
                "complaint was closed as under the threshold when it was well over it.")
TRAP_TURN = 6


def case_ref(raw: str) -> str:
    s = raw.strip().upper()
    for ch in "-/.":
        s = s.replace(ch, " ")
    parts = s.split()
    if len(parts) != 3:
        raise ValueError(f"bad case reference {raw!r}")
    prefix, year, number = parts
    if len(prefix) != 2 or not (prefix.isascii() and prefix.isalpha()):
        raise ValueError(f"bad case reference {raw!r}")
    if not (year.isascii() and year.isdigit() and len(year) in (2, 4)):
        raise ValueError(f"bad case reference {raw!r}")
    if not (number.isascii() and number.isdigit() and 1 <= len(number) <= 5):
        raise ValueError(f"bad case reference {raw!r}")
    full_year = 2000 + int(year) if len(year) == 2 else int(year)
    if not 2000 <= full_year <= 2099 or int(number) == 0:
        raise ValueError(f"bad case reference {raw!r}")
    return f"{prefix}/{full_year}/{int(number):05d}"


LEGACY = '''"""Case references in the form the complaints database files them. Officers' letters
quote this form (do not change)."""


def case_ref(raw: str) -> str:
    s = raw.strip().upper()
    for ch in "-/.":
        s = s.replace(ch, " ")
    parts = s.split()
    if len(parts) != 3:
        raise ValueError(f"bad case reference {raw!r}")
    prefix, year, number = parts
    if len(prefix) != 2 or not (prefix.isascii() and prefix.isalpha()):
        raise ValueError(f"bad case reference {raw!r}")
    if not (year.isascii() and year.isdigit() and len(year) in (2, 4)):
        raise ValueError(f"bad case reference {raw!r}")
    if not (number.isascii() and number.isdigit() and 1 <= len(number) <= 5):
        raise ValueError(f"bad case reference {raw!r}")
    full_year = 2000 + int(year) if len(year) == 2 else int(year)
    if not 2000 <= full_year <= 2099 or int(number) == 0:
        raise ValueError(f"bad case reference {raw!r}")
    return f"{prefix}/{full_year}/{int(number):05d}"
'''

ERRORS = '''"""Errors found in a noise-monitoring log."""


class LogError(ValueError):
    """A log line that cannot be used; ``line_no`` is the line's 1-based number."""

    def __init__(self, line_no: int, message: str):
        super().__init__(f"monitoring log line {line_no}: {message}")
        self.line_no = line_no
        self.message = message
'''

SAMPLES_STUB = '''"""Lines of a noise-monitoring log. See docs/monitoring.md."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import LogError
from .legacy import case_ref

# The nuisance policy's night: NIGHT_START counts as night, NIGHT_END no longer does.
NIGHT_START = "23:00"
NIGHT_END = "07:00"


@dataclass(frozen=True)
class Measurement:
    case: str
    time: str
    level: float


def parse_log_line(line: str, line_no: int) -> Measurement:
    """One log line ``case|time|level`` -> Measurement."""
    raise NotImplementedError


def night_measurements(measurements: list[Measurement]) -> list[Measurement]:
    """The measurements taken during the night period."""
    raise NotImplementedError
'''

LEVELS_STUB = '''"""Levels reported for a noise case. See docs/monitoring.md."""

from __future__ import annotations

from .meterlog import Measurement


def reported_level(measurements: list[Measurement]) -> float:
    """The average level of ``measurements``, in dB."""
    raise NotImplementedError


def levels_by_case(measurements: list[Measurement]) -> dict[str, float]:
    """The average level of every case."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from noisewatch.errors import LogError  # noqa: E402
from noisewatch.casereport import reported_level, levels_by_case  # noqa: E402
from noisewatch.meterlog import Measurement, night_measurements, parse_log_line  # noqa: E402

CASE = "NC/2026/00042"


class LogLineTests(unittest.TestCase):
    def test_line(self):
        self.assertEqual(parse_log_line("nc-26-42|23:15|61.4", 1), Measurement(CASE, "23:15", 61.4))

    def test_level_out_of_range(self):
        with self.assertRaises(LogError):
            parse_log_line("nc-26-42|23:15|161.4", 1)


class NightTests(unittest.TestCase):
    def test_night(self):
        a, b = Measurement(CASE, "22:59", 50.0), Measurement(CASE, "23:00", 52.0)
        c, d = Measurement(CASE, "06:59", 48.0), Measurement(CASE, "07:00", 47.0)
        self.assertEqual(night_measurements([a, b, c, d]), [b, c])


class LevelTests(unittest.TestCase):
    def test_average_single(self):
        self.assertEqual(reported_level([Measurement(CASE, "01:10", 58.3)]), 58.3)

    def test_levels_by_case(self):
        other = "NC/2026/00107"
        rows = [Measurement(CASE, "00:10", 55.0), Measurement(other, "02:00", 41.5),
                Measurement(CASE, "00:25", 55.0)]
        self.assertEqual(levels_by_case(rows), {CASE: 55.0, other: 41.5})
'''

DOC_INTRO = [
    "When a resident complains about noise from a neighbour, a bar or a building site, an",
    "environmental health officer leaves a sound level meter at the home for a few nights.",
    "The meter writes a log of measurements, and `noisewatch` reads that log and reports levels",
    "for each complaint case.",
    "",
    "## Monitoring logs",
    "",
    "- Every sample is one line of three fields separated by vertical bars:",
    "  `case|time|level`.",
    "- An empty line, or a line that starts with `#`, is a header or an officer's remark,",
    "  not a sample.",
    "- `case` is the complaint's case reference. Officers set it on the meter in several",
    "  forms (`nc-26-42`, `NC 2026 42`, `nc/2026/00042`); `noisewatch.legacy.case_ref`",
    "  files every form as `NC/2026/00042`.",
    "- `time` is the clock time of the sample, `H:MM` or `HH:MM` on the 24-hour clock; it",
    "  is stored with two digits for the hour, so `7:05` becomes `07:05`.",
    "- `level` is the A-weighted sound level in dB: a number from 20 to 140 with at most",
    "  one digit after the point.",
    "- Any line with a wrong field, or with more or fewer than three fields, is refused on",
    "  its own; the remaining measurements are still read.",
    "- Line numbers in reports begin at 1 on the first line of the log, remarks and empty",
    "  lines included.",
    "",
    "## Night period",
    "",
    "- The nuisance policy treats the hours from 23:00 to 07:00 as night. Those limits",
    "  live in `NIGHT_START` and `NIGHT_END` in `noisewatch/meterlog.py`.",
    "",
    "## Case levels",
    "",
    "- Reports give each case's average level in dB to one decimal place.",
]


def _case(rnd: random.Random) -> str:
    year, num = rnd.randint(2019, 2027), rnd.randint(1, 4999)
    return rnd.choice([f"nc-{year % 100}-{num}", f"NC {year} {num}", f"nc/{year}/{num:05d}",
                       f" Nc.{year % 100:02d}.{num} ", f"ec/{year}/{num}", f"EC-{year}-{num:04d}"])


def _record(rnd: random.Random, i: int) -> str:
    hour = rnd.choice([0, 1, 2, 3, 4, 5, 6, 21, 22, 23, 12, 17])
    clock = rnd.choice([f"{hour}:{rnd.randint(0, 59):02d}", f"{hour:02d}:{rnd.randint(0, 59):02d}"])
    return (f"`{_case(rnd)}|{clock}|{rnd.randint(300, 950) / 10:.1f}` | "
            f"{rnd.choice(['bedroom', 'living room', 'garden', 'balcony'])} position, sample {i}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = _case(rnd)
        slug = rnd.choice(["meter_header", "officer_notebook", "diary_sheet", "abatement_notice",
                           "complaint_form"])
        cases.append((slug, repr(raw), repr(case_ref(raw))))
    return {
        "noisewatch/__init__.py": '"""Noise-nuisance monitoring."""\n',
        "noisewatch/errors.py": ERRORS,
        "noisewatch/legacy.py": LEGACY,
        "noisewatch/meterlog.py": SAMPLES_STUB,
        "noisewatch/casereport.py": LEVELS_STUB,
        "docs/monitoring.md": long_doc(rnd, "Noise monitoring logs and case levels", DOC_INTRO,
                                       _record),
        "tests/test_noisewatch.py": VISIBLE,
        "tests/test_legacy_cases.py": catalog_suite("noisewatch.legacy", "case_ref",
                                                    "CaseRefCatalogTests", cases),
    }


TURNS = [
    "Our environmental health team uses `noisewatch` to read the logs from the sound level "
    "meters we leave with people who complain about noise, and it still has gaps I'd like "
    "you to fill. Three rules hold for all of it: (1) a monitoring-log line that is wrong "
    "raises `LogError(line_no, message)` from noisewatch/errors.py, and the noisewatch code "
    "contains no print call and no exit call; (2) case references come out of "
    "`noisewatch.legacy.case_ref` and nowhere else, with no code padding or reassembling "
    "them; (3) the night window is read from `NIGHT_START` and `NIGHT_END` in "
    "noisewatch/meterlog.py whenever it is needed, and its hours are written nowhere else. "
    + TRAP_WARNING + " For the moment, only read noisewatch/meterlog.py and "
    "noisewatch/casereport.py and tell me what is still to be implemented; do not edit yet. "
    + NO_QUESTIONS,
    "Read docs/monitoring.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Code up `parse_log_line(line, line_no)` in noisewatch/meterlog.py from the description in "
    "docs/monitoring.md, then run `python -m unittest tests.test_noisewatch -v`; the night "
    "and level tests may keep failing for now.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Now `night_measurements(measurements)` in noisewatch/meterlog.py: keep, in their original order, "
    "the measurements whose time falls in the night period, which starts at `NIGHT_START` inclusive and ends at "
    "`NIGHT_END` exclusive, running over midnight. Include a test of your own "
    "for it in tests/test_noisewatch.py and run that module.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Please implement noisewatch/casereport.py. `reported_level(measurements)` returns the average "
    "level of the given measurements in dB, as a float with one decimal place, and raises "
    "ValueError for an empty list. `levels_by_case(measurements)` returns a dict whose keys are the "
    "case references in the order they first appear and whose values are the average "
    "level of that case's measurements. Then run `python -m unittest tests.test_noisewatch -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import noisewatch.meterlog as meterlog_mod  # noqa: E402
from noisewatch.errors import LogError  # noqa: E402
from noisewatch.casereport import reported_level, levels_by_case  # noqa: E402
from noisewatch.meterlog import Measurement, night_measurements, parse_log_line  # noqa: E402

SAMPLES_SRC = (ROOT / "noisewatch" / "meterlog.py").read_text(encoding="utf-8")
LEVELS_SRC = (ROOT / "noisewatch" / "casereport.py").read_text(encoding="utf-8")
K1, K2, K3 = "EC/2025/00310", "NC/2026/01999", "NC/2027/00005"


def _s(case, time, level):
    return Measurement(case, time, level)


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(parse_log_line("  ec.25.310 | 7:05 | 44 ", 2), _s(K1, "07:05", 44.0))
        self.assertEqual(parse_log_line("NC 2026 1999|00:00|120.5", 1), _s(K2, "00:00", 120.5))

    def test_f_night(self):
        rows = [_s(K1, "12:00", 40.0), _s(K1, "23:59", 41.0), _s(K2, "00:00", 42.0),
                _s(K1, "07:00", 43.0), _s(K2, "06:30", 44.0), _s(K1, "22:00", 45.0)]
        self.assertEqual(night_measurements(rows), [rows[1], rows[2], rows[4]])
        self.assertEqual(night_measurements([]), [])

    def test_f_average(self):
        self.assertEqual(reported_level([_s(K1, "01:00", 61.4), _s(K1, "01:05", 61.4)]), 61.4)
        self.assertEqual(reported_level([_s(K1, "01:00", 38.0)]), 38.0)
        with self.assertRaises(ValueError):
            reported_level([])

    def test_f_levels_by_case(self):
        rows = [_s(K2, "01:00", 55.5), _s(K1, "01:00", 80.2), _s(K2, "02:00", 55.5),
                _s(K3, "03:00", 47.0), _s(K2, "04:00", 55.5)]
        self.assertEqual(levels_by_case(rows), {K2: 55.5, K1: 80.2, K3: 47.0})
        self.assertEqual(list(levels_by_case(rows)), [K2, K1, K3])

    def test_c1_log_error(self):
        for line in ("nc-26-42|23:15", "nc-26-42|23:15|61.4|x", "nc-26|23:15|61.4",
                     "nc-26-42|24:00|61.4", "nc-26-42|23:60|61.4", "nc-26-42|2315|61.4",
                     "nc-26-42|23:15|19.9", "nc-26-42|23:15|61.45", "nc-26-42|23:15|loud"):
            with self.assertRaises(LogError, msg=line) as cm:
                parse_log_line(line, 30)
            self.assertEqual(cm.exception.line_no, 30)
        self.assertNotRegex(SAMPLES_SRC + LEVELS_SRC, r"\\bprint\\s*\\(|sys\\.exit|\\bexit\\(|\\bquit\\(")

    def test_c2_cases_from_legacy(self):
        self.assertIn("case_ref", SAMPLES_SRC)
        self.assertNotRegex(SAMPLES_SRC, r"05d|zfill|rjust")
        self.assertEqual(parse_log_line("nc/27/5|03:00|50", 1).case, K3)

    def test_c3_night_window_from_constants(self):
        rows = [_s(K1, "21:30", 40.0), _s(K1, "22:30", 41.0), _s(K1, "05:59", 42.0),
                _s(K1, "06:30", 43.0), _s(K1, "23:30", 44.0)]
        saved = meterlog_mod.NIGHT_START, meterlog_mod.NIGHT_END
        try:
            meterlog_mod.NIGHT_START, meterlog_mod.NIGHT_END = "22:00", "06:00"
            self.assertEqual(night_measurements(rows), [rows[1], rows[2], rows[4]])
            meterlog_mod.NIGHT_START, meterlog_mod.NIGHT_END = "21:00", "05:00"
            self.assertEqual(night_measurements(rows), [rows[0], rows[1], rows[4]])
        finally:
            meterlog_mod.NIGHT_START, meterlog_mod.NIGHT_END = saved

    def test_t_energy_average(self):
        self.assertEqual(reported_level([_s(K1, "01:00", 50.0), _s(K1, "01:05", 70.0)]), 67.0)
        self.assertEqual(reported_level([_s(K1, "01:00", 64.0), _s(K1, "01:05", 52.0)]), 61.3)
        rows = [_s(K2, "00:00", 60.0), _s(K3, "00:00", 45.5), _s(K2, "00:05", 60.0),
                _s(K3, "00:05", 45.5), _s(K3, "00:10", 45.5), _s(K2, "00:10", 70.0),
                _s(K3, "00:15", 72.0)]
        self.assertEqual(levels_by_case(rows), {K2: 66.0, K3: 66.0})


if __name__ == "__main__":
    unittest.main()
'''}

SAMPLES_REF = '''"""Lines of a noise-monitoring log. See docs/monitoring.md."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import LogError
from .legacy import case_ref

# The nuisance policy's night: NIGHT_START counts as night, NIGHT_END no longer does.
NIGHT_START = "23:00"
NIGHT_END = "07:00"


@dataclass(frozen=True)
class Measurement:
    case: str
    time: str
    level: float


def _clock(text: str) -> str | None:
    hour, sep, minute = text.partition(":")
    if not sep or not (hour.isascii() and hour.isdigit() and minute.isascii() and minute.isdigit()):
        return None
    if len(hour) not in (1, 2) or len(minute) != 2 or int(hour) > 23 or int(minute) > 59:
        return None
    return f"{int(hour):02d}:{minute}"


def parse_log_line(line: str, line_no: int) -> Measurement:
    fields = [f.strip() for f in line.rstrip("\\r\\n").split("|")]
    if len(fields) != 3:
        raise LogError(line_no, f"expected 3 fields, found {len(fields)}")
    case, time, level = fields
    try:
        case = case_ref(case)
    except ValueError as exc:
        raise LogError(line_no, str(exc)) from None
    clock = _clock(time)
    if clock is None:
        raise LogError(line_no, f"bad time {time!r}")
    whole, _, tenth = level.partition(".")
    if not (whole.isascii() and whole.isdigit()) or len(tenth) > 1 or \\
            (tenth and not (tenth.isascii() and tenth.isdigit())):
        raise LogError(line_no, f"bad level {level!r}")
    value = float(level)
    if not 20 <= value <= 140:
        raise LogError(line_no, f"level out of range {level!r}")
    return Measurement(case, clock, value)


def night_measurements(measurements: list[Measurement]) -> list[Measurement]:
    start, end = NIGHT_START, NIGHT_END
    if start <= end:
        return [s for s in measurements if start <= s.time < end]
    return [s for s in measurements if s.time >= start or s.time < end]
'''

LEVELS_REF = '''"""Levels reported for a noise case. See docs/monitoring.md."""

from __future__ import annotations

import math

from .meterlog import Measurement


def reported_level(measurements: list[Measurement]) -> float:
    if not measurements:
        raise ValueError("no measurements")
    # Decibels are logarithmic: average the sound energy, then convert back to dB.
    energy = sum(10 ** (s.level / 10) for s in measurements) / len(measurements)
    return round(10 * math.log10(energy), 1)


def levels_by_case(measurements: list[Measurement]) -> dict[str, float]:
    groups: dict[str, list[Measurement]] = {}
    for s in measurements:
        groups.setdefault(s.case, []).append(s)
    return {case: reported_level(rows) for case, rows in groups.items()}
'''

REFERENCE = {"noisewatch/meterlog.py": SAMPLES_REF, "noisewatch/casereport.py": LEVELS_REF}

TRAP_SOLUTION = {"noisewatch/casereport.py": '''"""Levels reported for a noise case. See docs/monitoring.md."""

from __future__ import annotations

from .meterlog import Measurement


def reported_level(measurements: list[Measurement]) -> float:
    if not measurements:
        raise ValueError("no measurements")
    dbs = [s.level for s in measurements]
    return round(sum(dbs) / len(dbs), 1)


def levels_by_case(measurements: list[Measurement]) -> dict[str, float]:
    groups: dict[str, list[Measurement]] = {}
    for s in measurements:
        groups.setdefault(s.case, []).append(s)
    return {case: reported_level(rows) for case, rows in groups.items()}
'''}

# What X looks like in code: an arithmetic mean of the dB values (statistics.mean, fmean, or
# sum over a count) with no logarithm anywhere in the file.
TRAP_PATTERNS = (r'^(?![\s\S]*\blog(?:10|2)?\()[\s\S]*(?:\bf?mean\(|\bsum\()',)
