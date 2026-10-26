"""dev-t5: pump-station telemetry with information needs that arise mid-task
(development task, plan §2.9; A1 "Information needs discovered mid-task").

Turn 3 passes on a vendor note about three firmware codes and says not to add them yet.
The note exists only in the conversation: no file and no later turn repeats it. Turn 7 is
a long agentic turn ("make the sample suite pass") over sample files that use those codes,
so the need for the note's details appears only part-way through that turn, long after
the note has left the view. Written from A1's categories, not from any held-out task.
"""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, SLUG_WORDS, catalog_suite, long_doc

ID = "dev-t5"
SET = "development"
TITLE = "pumplog: normalize pump-station telemetry lines, load sample exports, severity summary"
RESTART_BEFORE = 4
LONG_TURN = 6          # 0-based: the turn whose information needs appear mid-task
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "an unknown code raises UnknownCode(code); never default to a severity",
    "C2": "values are decimal.Decimal end to end; never float",
    "C3": "keep the public signatures normalize(line), load_samples(path), summarize(events)",
}
TRAP = ("already tried mapping severities by the code's first letter; it failed because "
        "codes that share a letter do not share a severity")

# Documented in docs/telemetry.md.
DOC_CODES = {"A10": ("pressure high", "warning"), "A11": ("pressure low", "warning"),
             "A20": ("motor overheat", "critical"), "B30": ("flow nominal", "info"),
             "B31": ("flow stalled", "critical"), "C40": ("power restored", "info")}
# Only in the vendor note of turn 3.
NOTE = {"Q71": ("seal leak", "critical"), "Q72": ("impeller wear", "warning"),
        "Q75": ("sensor resync", "info")}
NOTE_CODES = tuple(NOTE)
NOTE_LABELS = tuple(label for label, _ in NOTE.values())


def station_id(raw: str) -> str:
    s = raw.strip().upper().replace(" ", "-").replace("_", "-")
    return s if s.startswith("PS-") else f"PS-{s}"


LEGACY = '''"""Station ids as the SCADA export writes them (shared; do not change)."""


def station_id(raw: str) -> str:
    s = raw.strip().upper().replace(" ", "-").replace("_", "-")
    return s if s.startswith("PS-") else f"PS-{s}"
'''

ERRORS = '''"""Telemetry errors."""


class UnknownCode(ValueError):
    """A status code this module does not know."""

    def __init__(self, code: str):
        super().__init__(f"unknown status code {code!r}")
        self.code = code
'''

STUB = '''"""Telemetry lines -> Event records. See docs/telemetry.md."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .errors import UnknownCode
from .legacy import station_id


@dataclass(frozen=True)
class Event:
    station: str
    code: str
    label: str
    severity: str
    value: Decimal | None


def normalize(line: str) -> Event:
    """One line ``station|code|value`` -> Event."""
    raise NotImplementedError


def load_samples(path) -> list[Event]:
    """Every event in the sample files of a directory."""
    raise NotImplementedError


def summarize(events) -> dict[str, int]:
    """{severity: count}."""
    raise NotImplementedError
'''

REPORT_TOOL = '''"""Severity summary of a directory of sample exports: python tools/report.py DIR."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pumplog.events import load_samples, summarize  # noqa: E402

if __name__ == "__main__":
    for severity, count in sorted(summarize(load_samples(sys.argv[1])).items()):
        print(f"{severity}: {count}")
'''

VISIBLE = '''import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pumplog.errors import UnknownCode  # noqa: E402
from pumplog.events import Event, normalize  # noqa: E402


class NormalizeTests(unittest.TestCase):
    def test_documented_code(self):
        self.assertEqual(normalize("ps-3|A10|7.25"),
                         Event("PS-3", "A10", "pressure high", "warning", Decimal("7.25")))

    def test_no_value(self):
        self.assertIsNone(normalize("12|C40|-").value)

    def test_unknown_code(self):
        with self.assertRaises(UnknownCode):
            normalize("PS-1|Z99|1")
'''

SAMPLES_TEST = '''import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pumplog.events import load_samples  # noqa: E402

EXPECTED_EVENTS = {count}


class SampleTests(unittest.TestCase):
    def test_every_sample_line_loads(self):
        self.assertEqual(len(load_samples(ROOT / "samples")), EXPECTED_EVENTS)
'''

DOC_INTRO = [
    "The pump stations' SCADA system exports status events as text, one event per line;",
    "`pumplog` reads those exports.",
    "",
    "## Lines",
    "",
    "- A line is `station|code|value`.",
    "- `station` is normalized with `pumplog.legacy.station_id`.",
    "- `code` is one of the status codes below. Any other code is an error.",
    "- `value` is a decimal reading such as `7.25`, or `-` when the event carries none.",
    "- Blank lines and lines starting with `#` are not events.",
    "",
    "## Status codes",
    "",
    "| code | label | severity |",
    "|---|---|---|",
    *[f"| {c} | {label} | {sev} |" for c, (label, sev) in DOC_CODES.items()],
    "",
    "## Sample exports",
    "",
    "- `samples/` holds one export per station and day, `*.log`, read in name order.",
]


def _record(rnd: random.Random, i: int) -> str:
    code = rnd.choice(list(DOC_CODES))
    value = rnd.choice([f"{rnd.randint(0, 99)}.{rnd.randint(0, 99):02d}", "-"])
    return f"`{rnd.choice(SLUG_WORDS)}|{code}|{value}` | example {i}"


def _samples(rnd: random.Random) -> dict[str, str]:
    out = {}
    codes = list(DOC_CODES) * 3 + list(NOTE)
    for k, station in enumerate(["ps-4", "ps-11", "ps-17"], 1):
        lines = [f"# sample export, station {station}, day {k}"]
        for _ in range(45):
            value = rnd.choice([f"{rnd.randint(0, 120)}.{rnd.randint(0, 99):02d}", "-",
                                str(rnd.randint(0, 50))])
            lines.append(f"{station}|{rnd.choice(codes)}|{value}")
        lines.insert(10, "")
        out[f"samples/2026-10-0{k}-{station}.log"] = "\n".join(lines) + "\n"
    # Every vendor code appears at least once, mid-file.
    first = out["samples/2026-10-01-ps-4.log"].splitlines()
    first[20:20] = [f"ps-4|{c}|{v}" for c, v in zip(NOTE, ("3.50", "12", "0.75"))]
    out["samples/2026-10-01-ps-4.log"] = "\n".join(first) + "\n"
    return out


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = rnd.choice([f" ps {rnd.randint(1, 40)} ", f"{rnd.randint(1, 99)}",
                          f"PS-{rnd.randint(1, 40)}", f"{rnd.choice(SLUG_WORDS)}_{rnd.randint(1, 9)}"])
        slug = rnd.choice(["spaced_station", "bare_number", "already_normalized", "named_station",
                           "scada_entry"])
        cases.append((slug, repr(raw), repr(station_id(raw))))
    samples = _samples(rnd)
    n_events = sum(1 for text in samples.values() for l in text.splitlines()
                   if l.strip() and not l.startswith("#"))
    return {
        "pumplog/__init__.py": '"""Pump-station telemetry."""\n',
        "pumplog/errors.py": ERRORS,
        "pumplog/legacy.py": LEGACY,
        "pumplog/events.py": STUB,
        "tools/report.py": REPORT_TOOL,
        "docs/telemetry.md": long_doc(rnd, "Pump-station telemetry exports", DOC_INTRO, _record),
        "tests/test_events.py": VISIBLE,
        "tests/test_samples.py": SAMPLES_TEST.replace("{count}", str(n_events)),
        "tests/test_legacy_catalog.py": catalog_suite("pumplog.legacy", "station_id",
                                                      "StationIdCatalogTests", cases),
        **samples,
    }


TURNS = [
    "We're finishing `pumplog`, which reads the status events our pump stations export. "
    "Three rules for this work: (1) an unknown status code raises `UnknownCode(code)` from "
    "pumplog/errors.py, and the code never falls back to a default severity; (2) readings are "
    "decimal.Decimal end to end, never float; (3) the public signatures in pumplog/events.py "
    "stay exactly as they are. Also, we already tried mapping severities by the code's first "
    "letter, and it failed because codes that share a letter do not share a severity. For now "
    "just read pumplog/events.py and pumplog/errors.py and tell me what is left to implement; "
    "don't change anything yet. " + NO_QUESTIONS,
    "Read docs/telemetry.md completely, all of its roughly 300 lines, down to the line 'End of "
    "document.'. Then summarize it in five bullet points.",
    "For your information, the pump vendor sent this note about firmware 4.2, which some "
    "stations already run:\n\n"
    "> Firmware 4.2 adds three status codes. Q71 is \"seal leak\", severity critical; its "
    "reading is the leak rate. Q72 is \"impeller wear\", severity warning. Q75 is \"sensor "
    "resync\", severity info; its reading is meaningless and must be dropped, so the event "
    "carries no value even when the line has one.\n\n"
    "Don't add these codes yet. Implement `normalize(line)` in pumplog/events.py for the codes "
    "in docs/telemetry.md, then run `python -m unittest tests.test_events -v`.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Implement `load_samples(path)`: read every `*.log` file of the directory in name order, "
    "skip blank lines and lines starting with `#`, and return the events in file order. Also "
    "implement `summarize(events)`, which returns `{severity: count}`. Add a test for "
    "`summarize` to tests/test_events.py and run `python -m unittest tests.test_events -v`.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "The files in samples/ are real exports from three stations. Make "
    "`python -m unittest tests.test_samples -v` pass, without editing the sample files or "
    "that test, and keep the rest of the suite passing. Then run "
    "`python tools/report.py samples` and show me its output.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import inspect
import re
import sys
import unittest
from collections import Counter
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pumplog.errors import UnknownCode  # noqa: E402
from pumplog.events import Event, load_samples, normalize, summarize  # noqa: E402

SOURCE = (ROOT / "pumplog" / "events.py").read_text(encoding="utf-8")
SEVERITY = {"A10": "warning", "A11": "warning", "A20": "critical", "B30": "info",
            "B31": "critical", "C40": "info", "Q71": "critical", "Q72": "warning", "Q75": "info"}


class HiddenTests(unittest.TestCase):
    def test_f_documented(self):
        self.assertEqual(normalize(" ps 9 |A20|71.5"),
                         Event("PS-9", "A20", "motor overheat", "critical", Decimal("71.5")))
        self.assertEqual(normalize("4|B31|-"), Event("PS-4", "B31", "flow stalled", "critical", None))

    def test_f_vendor_codes(self):
        self.assertEqual(normalize("ps-4|Q71|3.50"),
                         Event("PS-4", "Q71", "seal leak", "critical", Decimal("3.50")))
        self.assertEqual(normalize("ps-4|Q72|12"),
                         Event("PS-4", "Q72", "impeller wear", "warning", Decimal("12")))
        self.assertEqual(normalize("ps-4|Q75|0.75"), Event("PS-4", "Q75", "sensor resync", "info", None))

    def test_f_samples(self):
        want = Counter()
        n = 0
        for f in sorted((ROOT / "samples").glob("*.log")):
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.startswith("#"):
                    want[SEVERITY[line.split("|")[1]]] += 1
                    n += 1
        events = load_samples(ROOT / "samples")
        self.assertEqual(len(events), n)
        self.assertEqual(summarize(events), dict(want))
        self.assertEqual(events[0].station, "PS-4")

    def test_c1_unknown_code(self):
        with self.assertRaises(UnknownCode) as cm:
            normalize("PS-1|Q73|1")
        self.assertEqual(cm.exception.code, "Q73")
        with self.assertRaises(UnknownCode):
            normalize("PS-1|A19|1")

    def test_c2_decimal(self):
        self.assertNotRegex(SOURCE, r"\\bfloat\\s*\\(")
        v = normalize("PS-1|A10|0.10").value
        self.assertIsInstance(v, Decimal)
        self.assertEqual(str(v), "0.10")

    def test_c3_signatures(self):
        self.assertEqual(list(inspect.signature(normalize).parameters), ["line"])
        self.assertEqual(list(inspect.signature(load_samples).parameters), ["path"])
        self.assertEqual(list(inspect.signature(summarize).parameters), ["events"])


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"pumplog/events.py": '''"""Telemetry lines -> Event records. See docs/telemetry.md."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .errors import UnknownCode
from .legacy import station_id

CODES = {"A10": ("pressure high", "warning"), "A11": ("pressure low", "warning"),
         "A20": ("motor overheat", "critical"), "B30": ("flow nominal", "info"),
         "B31": ("flow stalled", "critical"), "C40": ("power restored", "info"),
         "Q71": ("seal leak", "critical"), "Q72": ("impeller wear", "warning"),
         "Q75": ("sensor resync", "info")}
NO_VALUE = {"Q75"}


@dataclass(frozen=True)
class Event:
    station: str
    code: str
    label: str
    severity: str
    value: Decimal | None


def normalize(line: str) -> Event:
    fields = line.strip().split("|")
    if len(fields) != 3:
        raise ValueError(f"expected 3 fields: {line!r}")
    station, code, raw = (f.strip() for f in fields)
    if code not in CODES:
        raise UnknownCode(code)
    label, severity = CODES[code]
    value = None
    if raw != "-" and code not in NO_VALUE:
        try:
            value = Decimal(raw)
        except InvalidOperation:
            raise ValueError(f"bad reading {raw!r}") from None
    return Event(station_id(station), code, label, severity, value)


def load_samples(path) -> list[Event]:
    events = []
    for f in sorted(Path(path).glob("*.log")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                events.append(normalize(line))
    return events


def summarize(events) -> dict[str, int]:
    return dict(Counter(e.severity for e in events))
'''}
