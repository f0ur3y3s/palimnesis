"""Hilltop station logs and the village bulletin."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t2"
SET = "heldout5"
TITLE = "stationlog: logger lines, tenth-degree temperatures, daily extremes, the bulletin"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "invalid readings raise HilltopLogError(line_no, detail) without output, exit or None",
    "C2": "decode each temperature solely via stationlog.legacy.decode_station_tenths",
    "C3": "leave every list argument unchanged, including its ordering",
}
TRAP = ("already tried giving each reading its day with the reading's own .date(); it failed "
        "because the station's observing day runs from 09:00 one morning to 09:00 the next, "
        "so the frost at 05:40 on 14 January went into the 14th instead of the night of the "
        "13th and both days' minima were wrong")
TRAP_WARNING = ("Also, we already tried giving each reading its day with the timestamp's own "
                "`.date()`, and it failed because this station's observing day runs from 09:00 "
                "one morning to 09:00 the next: the frost logged at 05:40 on 14 January was "
                "booked to the 14th instead of the night of the 13th, and the minima of both "
                "days came out wrong.")
TRAP_TURN = 6


def decode_station_tenths(raw: str) -> float:
    s = raw.strip()
    digits = s[1:]
    if s[:1] not in ("+", "-") or len(digits) != 4 or not digits.isdigit():
        raise ValueError(f"bad temperature field {raw!r}")
    value = int(digits) / 10
    return -value if s[0] == "-" else value


LEGACY = '''"""Stable decoder for station temperature tokens. Keep it intact."""


def decode_station_tenths(raw: str) -> float:
    s = raw.strip()
    digits = s[1:]
    if s[:1] not in ("+", "-") or len(digits) != 4 or not digits.isdigit():
        raise ValueError(f"bad temperature field {raw!r}")
    value = int(digits) / 10
    return -value if s[0] == "-" else value
'''

ERRORS = '''"""Logger file errors."""


class HilltopLogError(ValueError):
    """Invalid observation and its one-based dump index."""

    def __init__(self, line_no: int, detail: str):
        super().__init__(f"logger line {line_no}: {detail}")
        self.line_no = line_no
        self.detail = detail
'''

_READINGS_HEAD = '''"""Logger lines -> HilltopObservation records. See docs/logger.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .errors import HilltopLogError
from .legacy import decode_station_tenths


@dataclass(frozen=True)
class HilltopObservation:
    when: datetime
    temp_c: float
    wind_kmh: int
'''

READINGS_STUB = _READINGS_HEAD + '''

def parse_station_sample(line: str, line_no: int) -> HilltopObservation:
    """One logger line ``<timestamp> <temperature> <wind>`` -> HilltopObservation."""
    raise NotImplementedError


def load_station_dump(path) -> tuple[list[HilltopObservation], list[HilltopLogError]]:
    """A whole logger file -> (readings, errors)."""
    raise NotImplementedError
'''

_DAILY_HEAD = '''"""Derive shop-window weather summaries (docs/logger.md)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .logger_observations import HilltopObservation


@dataclass(frozen=True)
class HilltopExtremes:
    day: date
    low: float
    high: float
    wind: int
'''

DAILY_STUB = _DAILY_HEAD + '''

def hilltop_extremes(readings: list[HilltopObservation]) -> list[HilltopExtremes]:
    """Summarize dates represented in the observations."""
    raise NotImplementedError


def weather_bulletin(rows: list[HilltopExtremes]) -> str:
    """Render the shop-window notice."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stationlog.hilltop_summary import HilltopExtremes, weather_bulletin, hilltop_extremes  # noqa: E402
from stationlog.errors import HilltopLogError  # noqa: E402
from stationlog.logger_observations import HilltopObservation, parse_station_sample  # noqa: E402


class StationSampleTests(unittest.TestCase):
    def test_line_as_logged(self):
        self.assertEqual(parse_station_sample("2025-03-02T14:10 +0087 22", 1),
                         HilltopObservation(datetime(2025, 3, 2, 14, 10), 8.7, 22))

    def test_line_without_sign(self):
        with self.assertRaises(HilltopLogError):
            parse_station_sample("2025-03-02T14:10 0087 22", 1)


class HilltopBulletinTests(unittest.TestCase):
    READINGS = [HilltopObservation(datetime(2025, 3, 2, 11, 0), 4.5, 12),
                HilltopObservation(datetime(2025, 3, 2, 15, 30), 9.0, 30),
                HilltopObservation(datetime(2025, 3, 3, 13, 0), -1.5, 41),
                HilltopObservation(datetime(2025, 3, 2, 21, 45), 2.0, 8)]

    def test_extremes(self):
        self.assertEqual(hilltop_extremes(self.READINGS),
                         [HilltopExtremes(date(2025, 3, 2), 2.0, 9.0, 30),
                          HilltopExtremes(date(2025, 3, 3), -1.5, -1.5, 41)])

    def test_bulletin(self):
        self.assertEqual(weather_bulletin([HilltopExtremes(date(2025, 3, 3), -1.5, 4.0, 41)]),
                         "2025-03-03 min -1.5 max 4.0 wind 41\\n")
'''

DOC_INTRO = [
    "Weekly logger dumps from the allotment hill feed the shop-window bulletin.",
    "",
    "## Logger lines",
    "",
    "- Read three space-delimited tokens, allowing repeated spaces:",
    "  `<timestamp> <temperature> <wind>`.",
    "- Skip empty rows and `*` headers.",
    "- `timestamp`: Minute-resolution hilltop clock time (`YYYY-MM-DDTHH:MM`).",
    "- `temperature`: Signed four-digit Celsius tenths, decoded by",
    "  `stationlog.legacy.decode_station_tenths` (`+0087` = 8.7; `-0042` = -4.2).",
    "- `wind`: Ten-minute mean from the anemometer, integer km/h in [0, 250].",
    "- Discard a malformed line individually and continue scanning.",
    "- Report a rejected line's 1-based position in the physical logger file.",
    "  Headers and empties still occupy positions.",
    "",
    "## Readings in memory",
    "",
    "- `HilltopObservation.when` is a naive `datetime`, `HilltopObservation.temp_c` a float in degrees Celsius",
    "  and `HilltopObservation.wind_kmh` an int.",
    "- A power-cut replay can scramble timestamps, so arrival order can differ.",
    "",
    "## Appendix notes",
    "",
    "Winter samples also list battery voltage, shield condition and the observer's sky notes.",
]

SKIES = ["hoar frost on the fence", "low cloud over the ridge", "clear and starry",
         "sleet showers", "fog lifting from the brook", "steady drizzle", "bright, thin sun",
         "gale from the south-west", "snow lying on the north side"]
SHIELD = ["shield clean", "shield iced", "shield needs a wipe", "shield checked"]


def _stamp(rnd: random.Random) -> str:
    return (f"2025-{rnd.choice(['01', '02', '11', '12'])}-{rnd.randint(1, 28):02d}"
            f"T{rnd.randint(0, 23):02d}:{rnd.choice(['00', '10', '20', '30', '40', '50'])}")


def _record(rnd: random.Random, i: int) -> str:
    tenths = rnd.randint(-95, 140)
    line = f"{_stamp(rnd)} {'-' if tenths < 0 else '+'}{abs(tenths):04d} {rnd.randint(0, 70)}"
    return (f"`{line}` | battery {rnd.randint(118, 134) / 10:.1f} V; {rnd.choice(SHIELD)}; "
            f"{rnd.choice(SKIES)}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        tenths = rnd.randint(1, 455)
        raw = rnd.choice([f"+{tenths:04d}", f"-{tenths:04d}", f" +{tenths:04d} ",
                          f"-{tenths % 200 + 1:04d}\t"])
        slug = rnd.choice(["night_frost", "noon_sun", "storm_front", "dawn_mist",
                           "thaw_morning"])
        cases.append((slug, repr(raw), repr(decode_station_tenths(raw))))
    return {
        "stationlog/__init__.py": '"""Hilltop weather station logger files."""\n',
        "stationlog/errors.py": ERRORS,
        "stationlog/legacy.py": LEGACY,
        "stationlog/logger_observations.py": READINGS_STUB,
        "stationlog/hilltop_summary.py": DAILY_STUB,
        "docs/logger.md": long_doc(rnd, "The station logger files", DOC_INTRO, _record),
        "tests/test_stationlog.py": VISIBLE,
        "tests/test_legacy_tenths.py": catalog_suite("stationlog.legacy", "decode_station_tenths",
                                                     "DecodeTenthsCatalogTests", cases),
    }


TURNS = [
    "The station on our hill sends us logger files. `stationlog` should turn them into "
    "the bulletin for the shop window. Observe three rules. (1) On invalid input raise "
    "`HilltopLogError(line_no, detail)` from stationlog/errors.py without printing, quitting "
    "via sys.exit or returning None. (2) Reuse `stationlog.legacy.decode_station_tenths` for all "
    "temperature decoding. (3) Callers' lists must remain intact; no in-place sorting, "
    "appending or deleting. " + TRAP_WARNING + " Inspect stationlog/logger_observations.py plus "
    "stationlog/hilltop_summary.py. Report the missing pieces before making any changes. " + NO_QUESTIONS,
    "Read docs/logger.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Fill in `parse_station_sample(line, line_no)` in stationlog/logger_observations.py using the logger "
    "format documented in docs/logger.md. Execute `python -m unittest tests.test_stationlog -v`. "
    "Ignore the bulletin's expected failures at this stage.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Complete `load_station_dump(path)` in stationlog/logger_observations.py. Scan the UTF-8 dump, omitting "
    "blanks and `*` headers. Return `(readings, errors)` with readings in arrival order and "
    "one `HilltopLogError` per refused row. Use physical line numbers beginning at 1. "
    "Extend tests/test_stationlog.py with a loader check. Execute the module.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Complete stationlog/hilltop_summary.py for the village notice. `hilltop_extremes(readings)` "
    "produces chronologically ordered `HilltopExtremes` entries for dates represented in the "
    "observations. Include date, temperature minimum and maximum, and peak wind. "
    "`weather_bulletin(rows)` prints `<YYYY-MM-DD> min <low> max <high> wind <wind>` plus LF "
    "for each entry, using tenths for temperatures. Execute "
    "`python -m unittest tests.test_stationlog -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import inspect
import random
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stationlog.hilltop_summary import HilltopExtremes, weather_bulletin, hilltop_extremes  # noqa: E402
from stationlog.errors import HilltopLogError  # noqa: E402
from stationlog.logger_observations import HilltopObservation, load_station_dump, parse_station_sample  # noqa: E402

READINGS_SRC = (ROOT / "stationlog" / "logger_observations.py").read_text(encoding="utf-8")
DAILY_SRC = (ROOT / "stationlog" / "hilltop_summary.py").read_text(encoding="utf-8")


def logger_observation(month, day, hour, temp, wind=10):
    return HilltopObservation(datetime(2025, month, day, hour, 15), temp, wind)


class StationlogHiddenChecks(unittest.TestCase):
    def test_f_parse_line(self):
        self.assertEqual(parse_station_sample("  2025-12-01T16:40   -0003\\t7 ", 4),
                         HilltopObservation(datetime(2025, 12, 1, 16, 40), -0.3, 7))
        self.assertEqual(parse_station_sample("2025-12-01T10:00 +0000 250", 4).wind_kmh, 250)

    def test_f_load_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "week.log"
            p.write_text("* station 2 logger\\n\\n2025-11-04T12:00 +0051 14\\n2025-11-04T13:00 +0051\\n"
                         "2025-11-04T14:00 +51 3\\n2025-11-04T15:00 +0049 9\\n", encoding="utf-8")
            found, errors = load_station_dump(p)
        self.assertEqual(found, [HilltopObservation(datetime(2025, 11, 4, 12, 0), 5.1, 14),
                                 HilltopObservation(datetime(2025, 11, 4, 15, 0), 4.9, 9)])
        self.assertEqual(sorted(e.line_no for e in errors), [4, 5])

    def test_f_extremes(self):
        got = hilltop_extremes([logger_observation(2, 7, 14, 3.5, 18), logger_observation(2, 6, 10, 1.0, 5), logger_observation(2, 7, 9, -0.5, 25),
                              logger_observation(2, 6, 22, -2.5, 9), logger_observation(2, 7, 23, 0.0, 2)])
        self.assertEqual(got, [HilltopExtremes(date(2025, 2, 6), -2.5, 1.0, 9),
                               HilltopExtremes(date(2025, 2, 7), -0.5, 3.5, 25)])

    def test_f_bulletin(self):
        rows = hilltop_extremes([logger_observation(1, 20, 12, 6.25, 33), logger_observation(1, 20, 19, -0.5, 12)])
        self.assertEqual(weather_bulletin(rows), "2025-01-20 min -0.5 max 6.2 wind 33\\n")
        self.assertEqual(weather_bulletin([HilltopExtremes(date(2025, 1, 2), -7.0, 0.0, 0),
                                   HilltopExtremes(date(2025, 1, 3), 1.0, 12.5, 64)]),
                         "2025-01-02 min -7.0 max 0.0 wind 0\\n2025-01-03 min 1.0 max 12.5 wind 64\\n")

    def test_c1_reading_error(self):
        for line in ("2025-12-01T10:00 +0012", "2025-12-01T10:00 +0012 4 9",
                     "2025-12-32T10:00 +0012 4", "2025-12-01T10:00 0012 4",
                     "2025-12-01T10:00 +12 4", "2025-12-01T10:00 +0012 251",
                     "2025-12-01T10:00 +0012 -4", "2025-12-01T10:00 +0012 fast"):
            with self.assertRaises(HilltopLogError, msg=line) as cm:
                parse_station_sample(line, 11)
            self.assertEqual(cm.exception.line_no, 11)
        self.assertNotRegex(READINGS_SRC + DAILY_SRC, r"\\bprint\\s*\\(|sys\\.exit")

    def test_c2_decoded_by_legacy(self):
        self.assertIn("decode_station_tenths", READINGS_SRC)
        self.assertEqual(parse_station_sample("2025-12-01T10:00 -0105 4", 1).temp_c, -10.5)

    def test_c3_arguments_untouched(self):
        readings = [logger_observation(3, d, h, float(d - h), d) for d in (4, 2, 3) for h in (17, 11, 14)]
        random.Random(5).shuffle(readings)
        before = list(readings)
        rows = hilltop_extremes(readings)
        self.assertEqual(readings, before)
        rows_before = list(rows)
        weather_bulletin(rows)
        self.assertEqual(rows, rows_before)

    def test_t_observing_day_starts_at_nine(self):
        readings = [HilltopObservation(datetime(2025, 1, 13, 15, 0), 6.1, 20),
                    HilltopObservation(datetime(2025, 1, 14, 5, 40), -4.2, 3),
                    HilltopObservation(datetime(2025, 1, 14, 10, 0), 3.5, 12),
                    HilltopObservation(datetime(2025, 1, 14, 14, 0), 8.0, 31),
                    HilltopObservation(datetime(2025, 1, 15, 8, 50), -1.0, 6)]
        self.assertEqual(hilltop_extremes(readings),
                         [HilltopExtremes(date(2025, 1, 13), -4.2, 6.1, 20),
                          HilltopExtremes(date(2025, 1, 14), -1.0, 8.0, 31)])
        early = [HilltopObservation(datetime(2025, 2, 1, 0, 30), -3.0, 4),
                 HilltopObservation(datetime(2025, 2, 1, 9, 0), 2.0, 9)]
        self.assertEqual(weather_bulletin(hilltop_extremes(early)),
                         "2025-01-31 min -3.0 max -3.0 wind 4\\n2025-02-01 min 2.0 max 2.0 wind 9\\n")


if __name__ == "__main__":
    unittest.main()
'''}

READINGS_REF = _READINGS_HEAD + '''

def _wind(raw: str, line_no: int) -> int:
    if not (raw.isascii() and raw.isdigit()) or int(raw) > 250:
        raise HilltopLogError(line_no, f"bad wind speed {raw!r}")
    return int(raw)


def parse_station_sample(line: str, line_no: int) -> HilltopObservation:
    fields = line.split()
    if len(fields) != 3:
        raise HilltopLogError(line_no, f"expected 3 fields, found {len(fields)}")
    stamp, temp, wind = fields
    try:
        when = datetime.strptime(stamp, "%Y-%m-%dT%H:%M")
    except ValueError:
        raise HilltopLogError(line_no, f"bad timestamp {stamp!r}") from None
    try:
        temp_c = decode_station_tenths(temp)
    except ValueError as exc:
        raise HilltopLogError(line_no, str(exc)) from None
    return HilltopObservation(when, temp_c, _wind(wind, line_no))


def load_station_dump(path) -> tuple[list[HilltopObservation], list[HilltopLogError]]:
    found, errors = [], []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("*"):
            continue
        try:
            found.append(parse_station_sample(line, n))
        except HilltopLogError as exc:
            errors.append(exc)
    return found, errors
'''

DAILY_REF = _DAILY_HEAD + '''
from datetime import timedelta

# The observing day runs from 09:00 to 09:00 and is named after the morning it starts.
OBSERVING_SHIFT = timedelta(hours=9)


def _observing_day(reading: HilltopObservation) -> date:
    return (reading.when - OBSERVING_SHIFT).date()


def hilltop_extremes(readings: list[HilltopObservation]) -> list[HilltopExtremes]:
    days: dict[date, list[HilltopObservation]] = {}
    for reading in readings:
        days.setdefault(_observing_day(reading), []).append(reading)
    out = []
    for day in sorted(days):
        temps = [r.temp_c for r in days[day]]
        out.append(HilltopExtremes(day, min(temps), max(temps), max(r.wind_kmh for r in days[day])))
    return out


def weather_bulletin(rows: list[HilltopExtremes]) -> str:
    return "".join(f"{r.day.isoformat()} min {r.low:.1f} max {r.high:.1f} wind {r.wind}\\n"
                   for r in rows)
'''

REFERENCE = {"stationlog/logger_observations.py": READINGS_REF, "stationlog/hilltop_summary.py": DAILY_REF}

TRAP_SOLUTION = {"stationlog/hilltop_summary.py": _DAILY_HEAD + '''

def hilltop_extremes(readings: list[HilltopObservation]) -> list[HilltopExtremes]:
    grouped: dict[date, list[HilltopObservation]] = {}
    for r in readings:
        grouped.setdefault(r.when.date(), []).append(r)
    result = []
    for day in sorted(grouped):
        group = grouped[day]
        result.append(HilltopExtremes(day=day, low=min(r.temp_c for r in group),
                                  high=max(r.temp_c for r in group),
                                  wind=max(r.wind_kmh for r in group)))
    return result


def weather_bulletin(rows: list[HilltopExtremes]) -> str:
    lines = [f"{row.day:%Y-%m-%d} min {row.low:.1f} max {row.high:.1f} wind {row.wind}"
             for row in rows]
    return "".join(line + "\\n" for line in lines)
'''}

# X in code: a reading's day taken from its own timestamp (its date, its date fields, its
# text up to the day, or the timestamp truncated to midnight), with no shift for 09:00.
TRAP_PATTERNS = (
    r'\b(?:\w+\.)?(?:when|ts|stamp|dt|moment|timestamp|t)\.date\(\)',
    r'\.when\.(?:year|month|day)\b',
    r'\.when\.(?:strftime|isoformat)\(',
    r'\.when\.replace\(\s*hour\s*=\s*0',
    r'\bstr\(\s*\w+\.when\s*\)\s*\[',
    r'\bdate\.fromordinal\(\s*\w+\.when\.toordinal\(',
)
