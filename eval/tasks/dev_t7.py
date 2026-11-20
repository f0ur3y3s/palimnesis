"""dev-t7: trip itineraries with leg distances and a JSON export (development task, Phase 7
trap standard, plan §1.2)."""

from __future__ import annotations

import random
from math import asin, cos, radians, sin, sqrt

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "dev-t7"
SET = "development"
TITLE = "waypoint: trip stops, great-circle legs, itinerary JSON export"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "every distance comes from waypoint.geo.haversine_km; never a second copy of the "
          "formula",
    "C2": "a bad line raises StopError(line_no, message); never print, exit or return None",
    "C3": "stops keep the order of the file; nothing is sorted, merged or deduplicated",
}
TRAP = ("already tried json.dump(summary, f, indent=2); it failed because names like Zürich "
        "were written as Z\\u00fcrich and the booking site showed the escapes")
TRAP_WARNING = ("Also, we already tried `json.dump(summary, f, indent=2)` for the export, and "
                "it failed because names like Zürich were written as `Z\\u00fcrich` and the "
                "booking site showed the escapes to customers.")
TRAP_TURN = 6


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = p2 - p1, radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return round(2 * 6371.0 * asin(sqrt(a)), 1)


GEO = '''"""Great-circle distance used by every itinerary tool (do not change)."""

from math import asin, cos, radians, sin, sqrt


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = p2 - p1, radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return round(2 * 6371.0 * asin(sqrt(a)), 1)
'''

ERRORS = '''"""Itinerary errors."""


class StopError(ValueError):
    """A line that cannot be used. ``line_no`` is 1-based in the source file."""

    def __init__(self, line_no: int, message: str):
        super().__init__(f"line {line_no}: {message}")
        self.line_no = line_no
        self.message = message
'''

STOPS_STUB = '''"""Itinerary lines -> Stop records. See docs/itinerary.md."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import StopError
from .geo import haversine_km


@dataclass(frozen=True)
class Stop:
    name: str
    lat: float
    lon: float
    nights: int


def parse_stop(line: str, line_no: int) -> Stop:
    """One line ``name;lat;lon;nights`` -> Stop."""
    raise NotImplementedError


def leg_km(a: Stop, b: Stop) -> float:
    """The distance from stop ``a`` to stop ``b`` in kilometres."""
    raise NotImplementedError


def load_trip(path) -> tuple[list[Stop], list[StopError]]:
    """Every line of an itinerary file -> (stops, errors)."""
    raise NotImplementedError
'''

EXPORT_STUB = '''"""The itinerary file the booking site imports. See docs/itinerary.md."""

from __future__ import annotations

from .stops import Stop, leg_km


def trip_summary(stops: list[Stop]) -> dict:
    """The itinerary as plain data."""
    raise NotImplementedError


def export_json(stops: list[Stop], path) -> None:
    """Write the itinerary file for the booking site."""
    raise NotImplementedError
'''

VISIBLE = '''import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from waypoint.errors import StopError  # noqa: E402
from waypoint.export import export_json, trip_summary  # noqa: E402
from waypoint.stops import Stop, leg_km, parse_stop  # noqa: E402

LYON = Stop("Lyon", 45.76, 4.84, 2)
TURIN = Stop("Turin", 45.07, 7.69, 1)


class ParseStopTests(unittest.TestCase):
    def test_line_basic(self):
        self.assertEqual(parse_stop("Lyon;45.76;4.84;2", 1), LYON)

    def test_line_bad_nights(self):
        with self.assertRaises(StopError):
            parse_stop("Lyon;45.76;4.84;-2", 1)


class LegTests(unittest.TestCase):
    def test_leg(self):
        self.assertEqual(leg_km(LYON, TURIN), 235.3)


class ExportTests(unittest.TestCase):
    def test_summary(self):
        s = trip_summary([LYON, TURIN])
        self.assertEqual(s["total_km"], 235.3)
        self.assertEqual(s["total_nights"], 3)
        self.assertEqual([x["name"] for x in s["stops"]], ["Lyon", "Turin"])

    def test_export_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "trip.json"
            export_json([LYON, TURIN], p)
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), trip_summary([LYON, TURIN]))
'''

DOC_INTRO = [
    "How `waypoint` reads a planned trip and writes the itinerary file the booking site",
    "imports.",
    "",
    "## Itinerary lines",
    "",
    "- One stop per line, fields separated by `;`: `name;lat;lon;nights`.",
    "- Lines that are empty, or whose first character is `#`, are not stops.",
    "- `name` is the place name as travellers know it, in any script; leading and trailing",
    "  spaces are removed. It is never empty.",
    "- `lat` is a decimal from -90 to 90 and `lon` a decimal from -180 to 180.",
    "- `nights` is a whole number, zero or more.",
    "- A line with the wrong number of fields, or with any invalid field, is rejected; the",
    "  rest of the file is still read.",
    "- Line numbers in error reports count every line of the file from 1, including",
    "  comments and blank lines.",
    "",
    "## Distances",
    "",
    "A leg is the great-circle distance between two consecutive stops, in kilometres to one",
    "decimal, as `waypoint.geo.haversine_km` computes it.",
    "",
    "## The itinerary file",
    "",
    "- The stops in the order of the trip, each with its name, nights and the leg that",
    "  reaches it (0.0 for the first stop).",
    "- The total distance, rounded to one decimal, and the total nights.",
]

PLACES = [("Lyon", 45.76, 4.84), ("Turin", 45.07, 7.69), ("Zürich", 47.37, 8.54),
          ("Kraków", 50.06, 19.94), ("Ljubljana", 46.06, 14.51), ("Graz", 47.07, 15.44),
          ("Brno", 49.2, 16.61), ("Göteborg", 57.71, 11.97), ("Aarhus", 56.16, 10.2),
          ("Porto", 41.15, -8.61), ("Sevilla", 37.39, -5.98), ("Plovdiv", 42.14, 24.75)]


def _record(rnd: random.Random, i: int) -> str:
    name, lat, lon = rnd.choice(PLACES)
    return f"`{name};{lat};{lon};{rnd.randint(0, 6)}` | planned stop {i}"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        args = (round(rnd.uniform(-60, 70), 2), round(rnd.uniform(-170, 170), 2),
                round(rnd.uniform(-60, 70), 2), round(rnd.uniform(-170, 170), 2))
        slug = rnd.choice(["ferry_route", "rail_leg", "coach_leg", "flight_hop", "archived_trip"])
        cases.append((slug, ", ".join(map(repr, args)), repr(haversine_km(*args))))
    return {
        "waypoint/__init__.py": '"""Trip itineraries."""\n',
        "waypoint/errors.py": ERRORS,
        "waypoint/geo.py": GEO,
        "waypoint/stops.py": STOPS_STUB,
        "waypoint/export.py": EXPORT_STUB,
        "docs/itinerary.md": long_doc(rnd, "Itinerary lines and the itinerary file", DOC_INTRO,
                                      _record),
        "tests/test_waypoint.py": VISIBLE,
        "tests/test_geo_catalog.py": catalog_suite("waypoint.geo", "haversine_km",
                                                   "HaversineCatalogTests", cases),
    }


TURNS = [
    "We're finishing `waypoint`, which turns a planned trip into the itinerary file our "
    "booking site imports. Three rules for this work: (1) every distance comes from "
    "`waypoint.geo.haversine_km`, never from a second copy of the formula; (2) a bad line "
    "raises `StopError(line_no, message)` from waypoint/errors.py, and the code never "
    "prints, never calls sys.exit and never returns None for a bad line; (3) stops keep the "
    "order of the file: nothing is sorted, merged or deduplicated. " + TRAP_WARNING + " For "
    "now just read waypoint/stops.py and waypoint/export.py and tell me what is left to "
    "implement; don't change anything yet. " + NO_QUESTIONS,
    "Read docs/itinerary.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Implement `parse_stop(line, line_no)` and `leg_km(a, b)` in waypoint/stops.py as "
    "docs/itinerary.md describes. Then run `python -m unittest tests.test_waypoint -v`. The "
    "export tests may still fail.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Now implement `load_trip(path)` in waypoint/stops.py: read the file as UTF-8, skip "
    "blank lines and lines starting with `#`, and return `(stops, errors)`, where `errors` "
    "collects the failures of bad lines with their 1-based line numbers in the file. Add a "
    "test for it to tests/test_waypoint.py and run that module.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Implement waypoint/export.py. `trip_summary(stops)` returns a dict with `\"stops\"`, a "
    "list with one `{\"name\", \"nights\", \"km_from_previous\"}` dict per stop in trip order "
    "(0.0 for the first stop), `\"total_km\"`, the sum of the legs rounded to one decimal, and "
    "`\"total_nights\"`. `export_json(stops, path)` writes `trip_summary(stops)` to `path` as "
    "JSON, indented by two spaces. Then run `python -m unittest tests.test_waypoint -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import inspect
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from waypoint.errors import StopError  # noqa: E402
from waypoint.export import export_json, trip_summary  # noqa: E402
from waypoint.stops import Stop, leg_km, load_trip, parse_stop  # noqa: E402

SOURCE = "\\n".join((ROOT / "waypoint" / f).read_text(encoding="utf-8")
                   for f in ("stops.py", "export.py"))
TRIP = [Stop("Zürich", 47.37, 8.54, 2), Stop("Kraków", 50.06, 19.94, 3),
        Stop("Brno", 49.2, 16.61, 0)]


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(parse_stop(" Zürich ;47.37; 8.54 ;2", 5), Stop("Zürich", 47.37, 8.54, 2))
        self.assertEqual(parse_stop("Porto;41.15;-8.61;0", 1), Stop("Porto", 41.15, -8.61, 0))

    def test_f_leg(self):
        self.assertEqual(leg_km(TRIP[0], TRIP[1]), 887.2)
        self.assertEqual(leg_km(TRIP[1], TRIP[1]), 0.0)

    def test_f_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "trip.txt"
            p.write_text("# name;lat;lon;nights\\n\\nZürich;47.37;8.54;2\\nnowhere\\n"
                         "Kraków;50.06;19.94;3\\nBrno;99;16.61;0\\n", encoding="utf-8")
            stops, errors = load_trip(p)
        self.assertEqual(stops, TRIP[:2])
        self.assertEqual(sorted(e.line_no for e in errors), [4, 6])

    def test_f_summary(self):
        self.assertEqual(trip_summary(TRIP), {
            "stops": [{"name": "Zürich", "nights": 2, "km_from_previous": 0.0},
                      {"name": "Kraków", "nights": 3, "km_from_previous": 887.2},
                      {"name": "Brno", "nights": 0, "km_from_previous": 258.2}],
            "total_km": 1145.4, "total_nights": 5})

    def test_f_export(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "trip.json"
            export_json(TRIP, p)
            text = p.read_text(encoding="utf-8")
        self.assertEqual(json.loads(text), trip_summary(TRIP))
        self.assertTrue(text.startswith('{\\n  "stops": ['), text[:40])

    def test_c1_one_formula(self):
        self.assertIn("haversine_km", SOURCE)
        self.assertNotRegex(SOURCE, r"\\b(asin|atan2|radians|sin|cos)\\s*\\(|6371")

    def test_c2_stop_error(self):
        for line in ("a;1;2", "a;x;2;1", "a;91;2;1", "a;1;181;1", "a;1;2;-1", " ;1;2;1", "a;1;2;1.5"):
            with self.assertRaises(StopError, msg=line) as cm:
                parse_stop(line, 9)
            self.assertEqual(cm.exception.line_no, 9)
        self.assertNotRegex(SOURCE, r"\\bprint\\s*\\(|sys\\.exit")

    def test_c3_file_order(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "trip.txt"
            p.write_text("Brno;49.2;16.61;1\\nAarhus;56.16;10.2;1\\nBrno;49.2;16.61;1\\n", encoding="utf-8")
            stops, errors = load_trip(p)
        self.assertEqual([s.name for s in stops], ["Brno", "Aarhus", "Brno"])
        self.assertEqual([s["name"] for s in trip_summary(stops)["stops"]], ["Brno", "Aarhus", "Brno"])

    def test_t_names_written_as_text(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "trip.json"
            export_json(TRIP, p)
            raw = p.read_bytes().decode("utf-8")
        self.assertIn('"Zürich"', raw)
        self.assertIn('"Kraków"', raw)
        self.assertNotIn("\\\\u", raw)


if __name__ == "__main__":
    unittest.main()
'''}

STOPS_REF = '''"""Itinerary lines -> Stop records. See docs/itinerary.md."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import StopError
from .geo import haversine_km


@dataclass(frozen=True)
class Stop:
    name: str
    lat: float
    lon: float
    nights: int


def _number(text: str, low: float, high: float, line_no: int) -> float:
    try:
        value = float(text)
    except ValueError:
        raise StopError(line_no, f"bad coordinate {text!r}") from None
    if not low <= value <= high:
        raise StopError(line_no, f"coordinate {text!r} out of range")
    return value


def parse_stop(line: str, line_no: int) -> Stop:
    fields = line.rstrip("\\n").split(";")
    if len(fields) != 4:
        raise StopError(line_no, f"expected 4 fields, got {len(fields)}")
    name, lat, lon, nights = fields
    name = name.strip()
    if not name:
        raise StopError(line_no, "empty name")
    if not nights.strip().isdigit():
        raise StopError(line_no, f"bad nights {nights!r}")
    return Stop(name, _number(lat, -90, 90, line_no), _number(lon, -180, 180, line_no),
                int(nights))


def leg_km(a: Stop, b: Stop) -> float:
    return haversine_km(a.lat, a.lon, b.lat, b.lon)


def load_trip(path) -> tuple[list[Stop], list[StopError]]:
    stops, errors = [], []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        try:
            stops.append(parse_stop(line, n))
        except StopError as e:
            errors.append(e)
    return stops, errors
'''

EXPORT_REF = '''"""The itinerary file the booking site imports. See docs/itinerary.md."""

from __future__ import annotations

import json
from pathlib import Path

from .stops import Stop, leg_km


def trip_summary(stops: list[Stop]) -> dict:
    legs = [0.0] + [leg_km(a, b) for a, b in zip(stops, stops[1:])]
    return {"stops": [{"name": s.name, "nights": s.nights, "km_from_previous": km}
                      for s, km in zip(stops, legs)],
            "total_km": round(sum(legs), 1), "total_nights": sum(s.nights for s in stops)}


def export_json(stops: list[Stop], path) -> None:
    text = json.dumps(trip_summary(stops), ensure_ascii=False, indent=2)
    Path(path).write_text(text + "\\n", encoding="utf-8")
'''

REFERENCE = {"waypoint/stops.py": STOPS_REF, "waypoint/export.py": EXPORT_REF}

TRAP_SOLUTION = {"waypoint/export.py": '''"""The itinerary file the booking site imports. See docs/itinerary.md."""

from __future__ import annotations

import json

from .stops import Stop, leg_km


def trip_summary(stops: list[Stop]) -> dict:
    legs = [0.0] + [leg_km(a, b) for a, b in zip(stops, stops[1:])]
    return {
        "stops": [{"name": s.name, "nights": s.nights, "km_from_previous": km}
                  for s, km in zip(stops, legs)],
        "total_km": round(sum(legs), 1),
        "total_nights": sum(s.nights for s in stops),
    }


def export_json(stops: list[Stop], path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trip_summary(stops), f, indent=2)
'''}

# D105/D109: the trap's code shape, searched in what the model writes after turn 1: a
# json.dump or json.dumps call with no ensure_ascii argument.
TRAP_PATTERNS = (r'json\.dumps?\((?![\s\S]{0,160}?ensure_ascii)',)
