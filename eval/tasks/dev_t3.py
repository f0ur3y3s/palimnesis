"""dev-t3: a retry and backoff schedule (development task, D44.5)."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "dev-t3"
SET = "development"
TITLE = "backoff: exponential delays, deterministic jitter, retry loop"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "the library never sleeps itself; callers pass a sleep callable",
    "C2": "jitter comes only from the random.Random passed in, never the module-level random "
          "functions",
    "C3": "no delay ever exceeds cap, jitter included",
}
TRAP = ("already tried calling time.sleep inside retry(); it failed because the test suite "
        "took six minutes and was flaky")


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


LEGACY = '''"""Numeric helpers (shared with the scheduler; do not change)."""


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x
'''

STUB = '''"""Retry delays and a retry loop. See docs/backoff.md."""

from __future__ import annotations

import random
from typing import Callable


def delays(attempts: int, *, base: float = 0.5, factor: float = 2.0, cap: float = 30.0,
           jitter: float = 0.0, rng: random.Random | None = None) -> list[float]:
    """The waits before retries 1..attempts-1 (``attempts - 1`` values)."""
    raise NotImplementedError


def retry(fn: Callable[[], object], *, attempts: int = 5, schedule: list[float] | None = None,
          sleep: Callable[[float], None] | None = None,
          retry_on: tuple[type[BaseException], ...] = (Exception,)) -> object:
    """Call ``fn`` until it returns, at most ``attempts`` times."""
    raise NotImplementedError
'''

VISIBLE = '''import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backoff.schedule import delays  # noqa: E402


class DelayTests(unittest.TestCase):
    def test_exponential(self):
        self.assertEqual(delays(5), [0.5, 1.0, 2.0, 4.0])

    def test_cap(self):
        self.assertEqual(delays(9, cap=10.0)[-1], 10.0)

    def test_jitter_is_reproducible(self):
        a = delays(6, jitter=0.2, rng=random.Random(7))
        b = delays(6, jitter=0.2, rng=random.Random(7))
        self.assertEqual(a, b)
'''

DOC_INTRO = [
    "How the client library waits between retries.",
    "",
    "## Schedule",
    "",
    "- With `attempts` tries there are `attempts - 1` waits.",
    "- Wait `i` (from 0) is `base * factor ** i`, limited to `cap`.",
    "- Defaults: base 0.5 s, factor 2, cap 30 s, no jitter.",
    "",
    "## Jitter",
    "",
    "- With jitter `j`, each wait is multiplied by a factor drawn uniformly from",
    "  `[1 - j, 1 + j]`, then limited to `cap` again.",
    "",
    "## Retry loop",
    "",
    "- `retry` calls `fn`; when it raises one of `retry_on`, it waits the next scheduled",
    "  delay and calls again. After the last attempt the last exception propagates.",
    "- Exceptions not in `retry_on` propagate at once.",
]


def _record(rnd: random.Random, i: int) -> str:
    base, factor = rnd.choice([0.25, 0.5, 1.0]), rnd.choice([1.5, 2.0, 3.0])
    return (f"base={base} factor={factor} cap=30 | waits "
            f"{', '.join(str(round(min(30, base * factor ** k), 3)) for k in range(rnd.randint(3, 7)))}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        lo = rnd.randint(-50, 10)
        hi = lo + rnd.randint(0, 60)
        x = rnd.randint(-80, 90) + rnd.choice([0, 0.5, 0.25])
        slug = rnd.choice(["below_range", "above_range", "inside_range", "scheduler_entry"])
        cases.append((slug, f"{x!r}, {lo!r}, {hi!r}", repr(clamp(x, lo, hi))))
    return {
        "backoff/__init__.py": '"""Retry helpers for the client library."""\n',
        "backoff/legacy.py": LEGACY,
        "backoff/schedule.py": STUB,
        "docs/backoff.md": long_doc(rnd, "Retry backoff", DOC_INTRO, _record),
        "tests/test_schedule.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("backoff.legacy", "clamp",
                                                      "ClampCatalogTests", cases),
    }


TURNS = [
    "We're writing `backoff`, the retry helper for our client library. Rules for this work: "
    "(1) the library never sleeps by itself; callers pass a `sleep` callable, and with none "
    "given there is no waiting at all; (2) jitter comes only from the random.Random instance "
    "passed in as `rng`, never from the module-level random functions; (3) no delay may ever "
    "exceed `cap`, jitter included. Also, we already tried calling time.sleep inside retry(), "
    "and it failed because the test suite took six minutes and was flaky. For now just read "
    "backoff/schedule.py and tell me what is left to implement; don't change anything yet. "
    + NO_QUESTIONS,
    "Read docs/backoff.md completely, all of its roughly 300 lines, down to the line 'End of "
    "document.'. Then summarize it in five bullet points.",
    "Implement `delays` without jitter: `base * factor ** i`, limited to cap. Run "
    "`python -m unittest tests.test_schedule -v`; the jitter test may still fail.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Now add jitter to `delays` as docs/backoff.md describes: each wait is multiplied by a "
    "factor drawn uniformly from [1 - jitter, 1 + jitter]. Then run "
    "`python -m unittest tests.test_schedule -v`.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Implement `retry(fn, attempts=5, schedule=None, sleep=None, retry_on=(Exception,))`: call "
    "fn; on an exception in retry_on, wait the next delay (from `schedule`, or `delays(attempts)` "
    "when it is None) and try again; after the last attempt re-raise the last exception. Add "
    "tests for it to tests/test_schedule.py and run that module.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import random
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backoff import schedule  # noqa: E402
from backoff.schedule import delays, retry  # noqa: E402

SOURCE = (ROOT / "backoff" / "schedule.py").read_text(encoding="utf-8")


class Flaky:
    def __init__(self, fails, exc=ConnectionError):
        self.fails, self.exc, self.calls = fails, exc, 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.fails:
            raise self.exc(f"fail {self.calls}")
        return "ok"


class HiddenTests(unittest.TestCase):
    def test_f_delays(self):
        self.assertEqual(delays(5), [0.5, 1.0, 2.0, 4.0])
        self.assertEqual(delays(4, base=1.0, factor=3.0), [1.0, 3.0, 9.0])
        self.assertEqual(delays(10)[-1], 30.0)
        self.assertEqual(delays(1), [])

    def test_f_jitter_range(self):
        ds = delays(6, jitter=0.25, rng=random.Random(3))
        for d, plain in zip(ds, delays(6)):
            self.assertGreaterEqual(d, plain * 0.75 - 1e-9)
            self.assertLessEqual(d, plain * 1.25 + 1e-9)
        self.assertNotEqual(ds, delays(6))

    def test_f_retry(self):
        waits = []
        f = Flaky(2)
        self.assertEqual(retry(f, attempts=5, schedule=[0.1, 0.2, 0.3, 0.4], sleep=waits.append), "ok")
        self.assertEqual(f.calls, 3)
        self.assertEqual(waits, [0.1, 0.2])
        f = Flaky(9)
        with self.assertRaises(ConnectionError):
            retry(f, attempts=3, sleep=waits.append)
        self.assertEqual(f.calls, 3)
        g = Flaky(1, exc=KeyError)
        with self.assertRaises(KeyError):
            retry(g, attempts=5, retry_on=(ConnectionError,))
        self.assertEqual(g.calls, 1)

    def test_c1_never_sleeps(self):
        self.assertNotRegex(SOURCE, r"time\\.sleep|from time import")
        with mock.patch("time.sleep", side_effect=AssertionError("slept")):
            self.assertEqual(retry(Flaky(3), attempts=5), "ok")

    def test_c2_only_given_rng(self):
        with mock.patch.object(random, "random", side_effect=AssertionError("module random")), \\
                mock.patch.object(random, "uniform", side_effect=AssertionError("module uniform")):
            a = delays(6, jitter=0.3, rng=random.Random(11))
            b = delays(6, jitter=0.3, rng=random.Random(11))
        self.assertEqual(a, b)

    def test_c3_cap_with_jitter(self):
        for seed in range(30):
            for d in delays(12, cap=5.0, jitter=0.5, rng=random.Random(seed)):
                self.assertLessEqual(d, 5.0)


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"backoff/schedule.py": '''"""Retry delays and a retry loop. See docs/backoff.md."""

from __future__ import annotations

import random
from typing import Callable


def delays(attempts: int, *, base: float = 0.5, factor: float = 2.0, cap: float = 30.0,
           jitter: float = 0.0, rng: random.Random | None = None) -> list[float]:
    out = []
    for i in range(max(0, attempts - 1)):
        d = min(cap, base * factor ** i)
        if jitter and rng is not None:
            d = min(cap, d * rng.uniform(1 - jitter, 1 + jitter))
        out.append(d)
    return out


def retry(fn: Callable[[], object], *, attempts: int = 5, schedule: list[float] | None = None,
          sleep: Callable[[float], None] | None = None,
          retry_on: tuple[type[BaseException], ...] = (Exception,)) -> object:
    waits = delays(attempts) if schedule is None else list(schedule)
    for i in range(attempts):
        try:
            return fn()
        except retry_on:
            if i == attempts - 1:
                raise
            if sleep is not None and i < len(waits):
                sleep(waits[i])
'''}
