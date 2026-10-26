"""dev-t4: latency rollups across a proxy restart (development task, plan §2.9; A1
"Restarts and multiple eviction events").

The restart task of the development set. Its key constraint C2 (how millisecond figures
are rounded in the report) is stated only in turn 1 and needed only in turn 5, the first
turn after the proxy restart, which asks for the report without repeating it. Written
from A1's categories, not from any held-out task.
"""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, SLUG_WORDS, catalog_suite, long_doc

ID = "dev-t4"
SET = "development"
TITLE = "rollup: nearest-rank latency percentiles and a per-service report"
RESTART_BEFORE = 4
KEY_CONSTRAINT = "C2"
CONSTRAINTS = {
    "C1": "percentiles use the nearest-rank method on the sorted values; never interpolate",
    "C2": "millisecond figures in the report are whole numbers rounded half up (2.5 -> 3, "
          "3.5 -> 4), never with round(), which rounds half to even",
    "C3": "summarize never changes the caller's lists (no in-place sort)",
}
TRAP = ("already tried statistics.quantiles; it failed because it interpolates between "
        "samples and reported values no request ever took")

UNITS = {"us": 0.001, "ms": 1.0, "s": 1000.0}


def to_ms(text: str) -> float:
    t = text.strip().lower()
    for unit in ("us", "ms", "s"):
        if t.endswith(unit):
            return float(t[: -len(unit)]) * UNITS[unit]
    return float(t)


LEGACY = '''"""Duration parsing shared with the dashboards (do not change)."""

UNITS = {"us": 0.001, "ms": 1.0, "s": 1000.0}


def to_ms(text: str) -> float:
    t = text.strip().lower()
    for unit in ("us", "ms", "s"):
        if t.endswith(unit):
            return float(t[: -len(unit)]) * UNITS[unit]
    return float(t)
'''

STUB = '''"""Latency percentiles and the per-service report. See docs/rollup.md."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Summary:
    n: int
    p50: float
    p95: float
    max: float


def percentile(values: list[float], p: float) -> float:
    """The ``p``-th percentile (0 < p <= 100) of ``values``."""
    raise NotImplementedError


def summarize(samples: dict[str, list[float]]) -> dict[str, Summary]:
    """{service: durations in ms} -> {service: Summary}."""
    raise NotImplementedError


def render_report(summaries: dict[str, Summary]) -> str:
    """The text report, one line per service."""
    raise NotImplementedError
'''

LOAD = '''"""Reading sample files: one ``service duration`` pair per line."""

from __future__ import annotations

from pathlib import Path

from .legacy import to_ms


def read_samples(path) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        service, duration = line.split()
        out.setdefault(service, []).append(to_ms(duration))
    return out
'''

CLI = '''"""Command line: ``python -m rollup.cli SAMPLES`` prints the report."""

from __future__ import annotations


def main(argv: list[str]) -> int:
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rollup.stats import Summary, percentile, summarize  # noqa: E402


class PercentileTests(unittest.TestCase):
    def test_median_of_odd_count(self):
        self.assertEqual(percentile([3, 1, 2], 50), 2)

    def test_maximum(self):
        self.assertEqual(percentile([4, 9, 1], 100), 9)


class SummarizeTests(unittest.TestCase):
    def test_one_service(self):
        self.assertEqual(summarize({"api": [5, 1, 3]}), {"api": Summary(3, 3, 5, 5)})
'''

DOC_INTRO = [
    "How `rollup` turns raw request timings into the daily latency report.",
    "",
    "## Samples",
    "",
    "- A sample file holds one `service duration` pair per line, for example `api 12.5ms`.",
    "- Durations carry a unit: `us`, `ms` or `s`; `rollup.legacy.to_ms` converts them.",
    "- Blank lines and lines starting with `#` are not samples.",
    "",
    "## Percentiles",
    "",
    "- The p-th percentile of n sorted values is the value at 1-based rank",
    "  `ceil(p / 100 * n)`: the smallest value with at least p% of the values at or below",
    "  it. For example, p50 of `1 2 3 4` is 2, and p95 of the values 1 to 20 is 19.",
    "- p is greater than 0 and at most 100; p100 is the maximum.",
    "- An empty list of values has no percentile; asking for one is a ValueError.",
    "",
    "## Summary",
    "",
    "- Each service gets its count, p50, p95 and maximum.",
]


def _record(rnd: random.Random, i: int) -> str:
    service = rnd.choice(SLUG_WORDS)
    value = rnd.choice([f"{rnd.randint(1, 900)}ms", f"{rnd.randint(1, 9)}.{rnd.randint(0, 9)}s",
                        f"{rnd.randint(100, 990)}us", f"{rnd.randint(1, 400)}.5ms"])
    return f"`{service} {value}` | sample {i}"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        unit = rnd.choice(["ms", "s", "us", "MS", ""])
        raw = f"{rnd.randint(0, 999)}{rnd.choice(['', '.5', '.25'])}{unit}"
        if rnd.random() < 0.3:
            raw = f"  {raw} "
        slug = rnd.choice(["milliseconds", "seconds", "microseconds", "padded_value", "dashboard_entry"])
        cases.append((slug, repr(raw), repr(to_ms(raw))))
    services = ["checkout", "search", "auth", "inventory"]
    sample = ["# service duration"] + [
        f"{rnd.choice(services)} {rnd.randint(1, 300)}{rnd.choice(['', '.5'])}ms" for _ in range(60)]
    return {
        "rollup/__init__.py": '"""Latency rollups for the daily report."""\n',
        "rollup/legacy.py": LEGACY,
        "rollup/load.py": LOAD,
        "rollup/stats.py": STUB,
        "rollup/cli.py": CLI,
        "data/sample.txt": "\n".join(sample) + "\n",
        "docs/rollup.md": long_doc(rnd, "Latency rollups", DOC_INTRO, _record),
        "tests/test_stats.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("rollup.legacy", "to_ms", "ToMsCatalogTests", cases),
    }


TURNS = [
    "We're finishing `rollup`, which turns request timings into our daily latency report. "
    "Three rules for this work: (1) percentiles use the nearest-rank method on the sorted "
    "values, never interpolation; (2) every millisecond figure in the report is a whole "
    "number rounded half up, so 2.5 becomes 3 and 3.5 becomes 4, and never with Python's "
    "round(), which rounds half to even; (3) summarize never changes the lists it is given, "
    "so no in-place sorting. Also, we already tried statistics.quantiles, and it failed "
    "because it interpolates between samples and reported values no request ever took. For "
    "now just read rollup/stats.py and rollup/load.py and tell me what is left to implement; "
    "don't change anything yet. " + NO_QUESTIONS,
    "Read docs/rollup.md completely, all of its roughly 300 lines, down to the line 'End of "
    "document.'. Then summarize it in five bullet points.",
    "Implement `percentile(values, p)` and `summarize(samples)` in rollup/stats.py as "
    "docs/rollup.md describes. Then run `python -m unittest tests.test_stats -v`.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Now implement `render_report(summaries)` in rollup/stats.py. One line per service, "
    "services in name order, each line `<service>: n=<count> p50=<p50>ms p95=<p95>ms "
    "max=<max>ms` with every figure in whole milliseconds; lines are joined with newlines and "
    "the text ends with a newline. Add a test for it to tests/test_stats.py and run "
    "`python -m unittest tests.test_stats -v`.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Implement `main(argv)` in rollup/cli.py: `argv[0]` is a sample file; read it with "
    "`rollup.load.read_samples`, print the report and return 0. Then run "
    "`python -m rollup.cli data/sample.txt` and show me the output.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import contextlib
import io
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rollup import cli  # noqa: E402
from rollup.stats import Summary, percentile, render_report, summarize  # noqa: E402

SOURCE = (ROOT / "rollup" / "stats.py").read_text(encoding="utf-8")


class HiddenTests(unittest.TestCase):
    def test_f_percentile(self):
        self.assertEqual(percentile([1, 2, 3, 4], 50), 2)
        self.assertEqual(percentile(list(range(1, 21)), 95), 19)
        self.assertEqual(percentile([7, 3, 5], 100), 7)
        self.assertEqual(percentile([7, 3, 5], 1), 3)
        with self.assertRaises(ValueError):
            percentile([], 50)

    def test_f_summarize(self):
        got = summarize({"b": [3.0, 1.0, 2.0], "a": [10.0]})
        self.assertEqual(got, {"a": Summary(1, 10.0, 10.0, 10.0), "b": Summary(3, 2.0, 3.0, 3.0)})

    def test_f_report(self):
        text = render_report(summarize({"b": [3, 1, 2], "a": [10]}))
        self.assertEqual(text, "a: n=1 p50=10ms p95=10ms max=10ms\\nb: n=3 p50=2ms p95=3ms max=3ms\\n")

    def test_f_cli(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main([str(ROOT / "data" / "sample.txt")])
        self.assertEqual(code, 0)
        lines = out.getvalue().strip().splitlines()
        self.assertEqual([l.split(":")[0] for l in lines], ["auth", "checkout", "inventory", "search"])
        for line in lines:
            self.assertRegex(line, r"^[a-z]+: n=\\d+ p50=\\d+ms p95=\\d+ms max=\\d+ms$")

    def test_c1_nearest_rank(self):
        self.assertNotRegex(SOURCE, r"statistics|quantiles")
        self.assertEqual(percentile([10, 20], 75), 20)
        self.assertEqual(percentile([1, 2, 3, 4], 30), 2)

    def test_c2_half_up(self):
        text = render_report({"api": Summary(4, 2.5, 3.5, 10.5), "db": Summary(2, 0.5, 1.49, 4.5)})
        self.assertEqual(text, "api: n=4 p50=3ms p95=4ms max=11ms\\ndb: n=2 p50=1ms p95=1ms max=5ms\\n")

    def test_c3_inputs_unchanged(self):
        values = [5.0, 1.0, 3.0]
        samples = {"api": values}
        summarize(samples)
        self.assertEqual(values, [5.0, 1.0, 3.0])
        self.assertEqual(samples, {"api": [5.0, 1.0, 3.0]})
        percentile(values, 50)
        self.assertEqual(values, [5.0, 1.0, 3.0])


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"rollup/stats.py": '''"""Latency percentiles and the per-service report. See docs/rollup.md."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Summary:
    n: int
    p50: float
    p95: float
    max: float


def percentile(values: list[float], p: float) -> float:
    if not values or not 0 < p <= 100:
        raise ValueError("percentile needs values and 0 < p <= 100")
    ordered = sorted(values)
    return ordered[max(1, math.ceil(p / 100 * len(ordered))) - 1]


def summarize(samples: dict[str, list[float]]) -> dict[str, Summary]:
    return {s: Summary(len(v), percentile(v, 50), percentile(v, 95), max(v))
            for s, v in samples.items()}


def _ms(x: float) -> int:
    return math.floor(x + 0.5)


def render_report(summaries: dict[str, Summary]) -> str:
    return "".join(f"{s}: n={m.n} p50={_ms(m.p50)}ms p95={_ms(m.p95)}ms max={_ms(m.max)}ms\\n"
                   for s, m in sorted(summaries.items()))
''', "rollup/cli.py": '''"""Command line: ``python -m rollup.cli SAMPLES`` prints the report."""

from __future__ import annotations

import sys

from .load import read_samples
from .stats import render_report, summarize


def main(argv: list[str]) -> int:
    print(render_report(summarize(read_samples(argv[0]))), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''}
