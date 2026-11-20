"""County soil sheets and the allotment's liming report."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t3"
SET = "heldout5"
TITLE = "soilcard: sample lines, plot labels, combined plot pH, the liming report"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "bad cores raise SoilError(line_no, text) without stdout, sys.exit or None",
    "C2": "only soilcard.legacy.plot_label canonicalizes plot labels",
    "C3": "emit plots in first-core order",
}
TRAP = ("already tried giving each plot the arithmetic mean of its cores' pH readings; it "
        "failed because pH is a logarithmic scale and the county soil lab combines cores by "
        "their hydrogen-ion concentration, so a bed sampled at 5.0 and 7.0 came out at 6.0 "
        "and was left unlimed, where the lab's figure is 5.3")
TRAP_WARNING = ("Also, we already tried giving each plot the plain arithmetic mean of its "
                "cores' pH readings, and it failed because pH is a logarithmic scale and the "
                "county soil lab combines cores by their hydrogen-ion concentration: a bed "
                "sampled at 5.0 and 7.0 came out at 6.0 and went unlimed, while the lab's "
                "figure for it is 5.3.")
TRAP_TURN = 6


def plot_label(raw: str) -> str:
    parts = raw.replace("/", " ").replace("-", " ").split()
    if not parts or not all(p.isalnum() for p in parts):
        raise ValueError(f"bad plot name {raw!r}")
    return "/".join(p.upper() for p in parts)


LEGACY = '''"""Plot labels as written on the society's site plan (do not change)."""


def plot_label(raw: str) -> str:
    parts = raw.replace("/", " ").replace("-", " ").split()
    if not parts or not all(p.isalnum() for p in parts):
        raise ValueError(f"bad plot name {raw!r}")
    return "/".join(p.upper() for p in parts)
'''

ERRORS = '''"""Soil sheet errors."""


class SoilError(ValueError):
    """Unusable laboratory row and its one-based sheet position."""

    def __init__(self, line_no: int, text: str):
        super().__init__(f"sheet line {line_no}: {text}")
        self.line_no = line_no
        self.text = text
'''

_SAMPLES_HEAD = '''"""Soil sheet lines -> CoreSample records. See docs/soil.md."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import SoilError
from .legacy import plot_label


@dataclass(frozen=True)
class CoreSample:
    plot: str
    depth_cm: int
    ph: float
    nitrate_ppm: int
'''

SAMPLES_STUB = _SAMPLES_HEAD + '''

def parse_sample(line: str, line_no: int) -> CoreSample:
    """One sheet line ``plot;depth;ph;nitrate`` -> CoreSample."""
    raise NotImplementedError


def load_sheet(path) -> tuple[list[CoreSample], list[SoilError]]:
    """A whole soil sheet -> (cores, errors)."""
    raise NotImplementedError
'''

_REPORT_HEAD = '''"""Per-plot pH and the liming report. See docs/soil.md."""

from __future__ import annotations

from .cores import CoreSample

LIME_BELOW = 6.0
SULPHUR_ABOVE = 7.5
'''

REPORT_STUB = _REPORT_HEAD + '''

def plot_ph(cores: list[CoreSample]) -> dict[str, float]:
    """The pH of every plot that has cores."""
    raise NotImplementedError


def liming_report(cores: list[CoreSample]) -> str:
    """The report for the committee, one line per plot."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soilcard.errors import SoilError  # noqa: E402
from soilcard.report import liming_report, plot_ph  # noqa: E402
from soilcard.cores import CoreSample, parse_sample  # noqa: E402


class ParseSampleTests(unittest.TestCase):
    def test_sheet_line(self):
        self.assertEqual(parse_sample("north 14a;15;6.4;22", 1),
                         CoreSample("NORTH/14A", 15, 6.4, 22))

    def test_sheet_line_comma_decimal(self):
        with self.assertRaises(SoilError):
            parse_sample("north 14a;15;6,4;22", 1)


class PlotReportTests(unittest.TestCase):
    SAMPLES = [CoreSample("WEST/3", 15, 6.5, 30), CoreSample("EAST/9", 15, 5.5, 12),
               CoreSample("WEST/3", 30, 6.5, 18), CoreSample("EAST/2", 15, 7.75, 25)]

    def test_plot_ph(self):
        self.assertEqual(plot_ph(self.SAMPLES), {"WEST/3": 6.5, "EAST/9": 5.5, "EAST/2": 7.75})

    def test_liming_report(self):
        self.assertEqual(liming_report(self.SAMPLES),
                         "WEST/3 pH 6.50 ok\\nEAST/9 pH 5.50 lime\\nEAST/2 pH 7.75 sulphur\\n")
'''

DOC_INTRO = [
    "County lab results arrive as sample sheets after the allotment's spring survey.",
    "`soilcard` reads those results for the committee's liming report.",
    "",
    "## CoreSample lines",
    "",
    "- Write four semicolon-delimited fields for each core:",
    "  `plot;depth;ph;nitrate`.",
    "- Ignore empty rows and lab notes marked by an initial `%`.",
    "- Strip field whitespace.",
    "- `plot`: Bag label (site word, plot number, optional half-plot letter).",
    "  `soilcard.legacy.plot_label` canonicalizes `north 14a`, `West-3` and `orchard/2b`",
    "  to `NORTH/14A`, `WEST/3` and `ORCHARD/2B` respectively.",
    "- `depth`: Integer core depth in cm, 5–60.",
    "- `ph`: Lab pH, 3.0–10.0. Use a decimal point rather than a comma.",
    "- `nitrate`: Nitrate nitrogen, nonnegative integer ppm.",
    "- Reject malformed samples individually without stopping the reader.",
    "- Report the original sheet row, numbering from 1. Keep empty and remark rows",
    "  in the row count.",
    "",
    "## Advice thresholds",
    "",
    "- A plot whose pH is below 6.0 is advised to lime; above 7.5 it is advised to add",
    "  sulphur; otherwise no change is needed.",
    "",
    "## Appendix notes",
    "",
    "Archived entries carry bag numbers, the plot's crop and the technician's observation.",
]

SITES = ["north", "West", "orchard", "BROOK", "south", "Top-field", "mill", "Glebe"]
CROPS = ["leeks", "broad beans", "potatoes", "brassicas", "onions", "rhubarb", "squash",
         "runner beans", "fallow", "soft fruit"]
REMARKS = ["stony core", "heavy clay", "good tilth", "recently manured", "waterlogged corner",
           "sandy topsoil", "worms plentiful", "compacted path edge"]


def _raw_plot(rnd: random.Random) -> str:
    site, number = rnd.choice(SITES), rnd.randint(1, 40)
    half = rnd.choice(["", "a", "b", "", ""])
    return rnd.choice([f"{site} {number}{half}", f"{site}-{number}{half}",
                       f"{site.lower()}/{number}{half}"])


def _record(rnd: random.Random, i: int) -> str:
    line = (f"{_raw_plot(rnd)};{rnd.choice([10, 15, 20, 30])};"
            f"{rnd.randint(48, 82) / 10:.1f};{rnd.randint(4, 60)}")
    return (f"`{line}` | bag {rnd.randint(100, 999)}; under {rnd.choice(CROPS)}; "
            f"{rnd.choice(REMARKS)}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = _raw_plot(rnd)
        raw = rnd.choice([raw, f"  {raw} ", raw.upper(), raw.replace(" ", "  ")])
        slug = rnd.choice(["spring_cores", "bag_label", "site_plan", "rent_list",
                           "waiting_list"])
        cases.append((slug, repr(raw), repr(plot_label(raw))))
    return {
        "soilcard/__init__.py": '"""Allotment soil sample sheets."""\n',
        "soilcard/errors.py": ERRORS,
        "soilcard/legacy.py": LEGACY,
        "soilcard/cores.py": SAMPLES_STUB,
        "soilcard/report.py": REPORT_STUB,
        "docs/soil.md": long_doc(rnd, "The soil sample sheet", DOC_INTRO, _record),
        "tests/test_soilcard.py": VISIBLE,
        "tests/test_legacy_plots.py": catalog_suite("soilcard.legacy", "plot_label",
                                                    "PlotLabelCatalogTests", cases),
    }


TURNS = [
    "The allotment committee needs a liming report from the county lab's core results. "
    "`soilcard` has three rules. (1) Raise `SoilError(line_no, text)` from "
    "soilcard/errors.py when a sample fails validation. No printing, sys.exit or None. "
    "(2) Send every plot name through `soilcard.legacy.plot_label` without another formatter. "
    "(3) Use first-seen plot order in all output. Don't alphabetize or otherwise sort. "
    + TRAP_WARNING + " Survey soilcard/cores.py and soilcard/report.py. "
    "Describe their missing behavior and leave both modules alone. " + NO_QUESTIONS,
    "Read docs/soil.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Implement `parse_sample(line, line_no)` in soilcard/cores.py using the lab sheet "
    "format in docs/soil.md. Execute `python -m unittest tests.test_soilcard -v`. "
    "The unfinished liming report will still cause failures.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Fill in `load_sheet(path)` in soilcard/cores.py. Read a UTF-8 sheet, omitting blanks "
    "and `%` notes. Return `(cores, errors)`; keep accepted cores in row order and attach "
    "one `SoilError` to each rejected row, with its actual number on the sheet (1-based). "
    "Add a combined sheet case in tests/test_soilcard.py, then run the module.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Finish soilcard/report.py for the allotment committee. In `plot_ph(cores)`, build "
    "a dictionary of plot label to combined core pH, rounded to hundredths. "
    "Make `liming_report(cores)` emit `<label> pH <ph> <advice>` and LF for every plot. "
    "Show pH to two decimal places. Advice is `lime` below `LIME_BELOW`, "
    "`sulphur` above `SULPHUR_ABOVE`, otherwise `ok`. Execute "
    "`python -m unittest tests.test_soilcard -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from soilcard.errors import SoilError  # noqa: E402
from soilcard.report import liming_report, plot_ph  # noqa: E402
from soilcard.cores import CoreSample, load_sheet, parse_sample  # noqa: E402

SAMPLES_SRC = (ROOT / "soilcard" / "cores.py").read_text(encoding="utf-8")
REPORT_SRC = (ROOT / "soilcard" / "report.py").read_text(encoding="utf-8")


def core(plot, ph, depth=15, nitrate=20):
    return CoreSample(plot, depth, ph, nitrate)


class SoilcardHiddenChecks(unittest.TestCase):
    def test_f_sample_line(self):
        self.assertEqual(parse_sample("  orchard/2b ; 30 ; 7.1 ; 0 ", 6),
                         CoreSample("ORCHARD/2B", 30, 7.1, 0))
        self.assertEqual(parse_sample("Top-field 7;5;3.0;140", 6), CoreSample("TOP/FIELD/7", 5, 3.0, 140))

    def test_f_sheet_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sheet.txt"
            p.write_text("% lab batch 41\\n\\nmill 4;15;6.8;19\\nmill 4;15;6.8\\nmill 5;15;11.2;3\\n"
                         "glebe 1;20;5.9;44\\n", encoding="utf-8")
            found, errors = load_sheet(p)
        self.assertEqual(found, [CoreSample("MILL/4", 15, 6.8, 19), CoreSample("GLEBE/1", 20, 5.9, 44)])
        self.assertEqual(sorted(e.line_no for e in errors), [4, 5])

    def test_f_plot_ph(self):
        got = plot_ph([core("A/1", 6.2), core("B/7", 5.4), core("A/1", 6.2), core("C/3", 7.9),
                       core("B/7", 5.4), core("B/7", 5.4)])
        self.assertEqual(got, {"A/1": 6.2, "B/7": 5.4, "C/3": 7.9})

    def test_f_report(self):
        cores = [core("MILL/2", 5.95), core("MILL/1", 7.5), core("MILL/2", 5.95), core("GLEBE/4", 7.6)]
        self.assertEqual(liming_report(cores),
                         "MILL/2 pH 5.95 lime\\nMILL/1 pH 7.50 ok\\nGLEBE/4 pH 7.60 sulphur\\n")
        self.assertEqual(liming_report([core("A/1", 6.0)]), "A/1 pH 6.00 ok\\n")

    def test_c1_soil_error(self):
        for line in ("mill 4;15;6.8", "mill 4;15;6.8;19;2", ";15;6.8;19", "mill 4!;15;6.8;19",
                     "mill 4;4;6.8;19", "mill 4;61;6.8;19", "mill 4;15;2.9;19", "mill 4;15;nan;19",
                     "mill 4;15;6.8;-1", "mill 4;15;6.8;lots"):
            with self.assertRaises(SoilError, msg=line) as cm:
                parse_sample(line, 8)
            self.assertEqual(cm.exception.line_no, 8)
        self.assertNotRegex(SAMPLES_SRC + REPORT_SRC, r"\\bprint\\s*\\(|sys\\.exit")

    def test_c2_labels_from_legacy(self):
        self.assertIn("plot_label", SAMPLES_SRC)
        self.assertEqual(parse_sample("brook - 12 / a;15;6.0;9", 1).plot, "BROOK/12/A")

    def test_c3_first_appearance_order(self):
        cores = [core("Z/9", 6.6), core("A/1", 6.1), core("M/4", 7.0), core("A/1", 6.1),
                   core("B/2", 6.3)]
        self.assertEqual(list(plot_ph(cores)), ["Z/9", "A/1", "M/4", "B/2"])
        self.assertEqual([line.split()[0] for line in liming_report(cores).splitlines()],
                         ["Z/9", "A/1", "M/4", "B/2"])

    def test_t_ph_combined_by_concentration(self):
        got = plot_ph([core("BED/1", 5.0), core("BED/2", 6.0), core("BED/1", 7.0),
                       core("BED/2", 6.0), core("BED/2", 8.0)])
        self.assertEqual(got, {"BED/1": 5.3, "BED/2": 6.17})
        self.assertEqual(liming_report([core("BED/3", 5.5), core("BED/3", 7.0)]),
                         "BED/3 pH 5.79 lime\\n")


if __name__ == "__main__":
    unittest.main()
'''}

SAMPLES_REF = _SAMPLES_HEAD + '''

def _whole(raw: str, line_no: int, what: str, low: int, high: int | None) -> int:
    if not (raw.isascii() and raw.isdigit()):
        raise SoilError(line_no, f"{what} must be a whole number, not {raw!r}")
    value = int(raw)
    if value < low or (high is not None and value > high):
        raise SoilError(line_no, f"{what} {value} out of range")
    return value


def parse_sample(line: str, line_no: int) -> CoreSample:
    fields = [f.strip() for f in line.rstrip("\\n").split(";")]
    if len(fields) != 4:
        raise SoilError(line_no, f"expected 4 fields, found {len(fields)}")
    raw_plot, raw_depth, raw_ph, raw_nitrate = fields
    try:
        plot = plot_label(raw_plot)
    except ValueError as exc:
        raise SoilError(line_no, str(exc)) from None
    depth = _whole(raw_depth, line_no, "depth", 5, 60)
    try:
        ph = float(raw_ph)
    except ValueError:
        raise SoilError(line_no, f"bad pH {raw_ph!r}") from None
    if not 3.0 <= ph <= 10.0:
        raise SoilError(line_no, f"pH {raw_ph} out of range")
    return CoreSample(plot, depth, ph, _whole(raw_nitrate, line_no, "nitrate", 0, None))


def load_sheet(path) -> tuple[list[CoreSample], list[SoilError]]:
    found, errors = [], []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("%"):
            continue
        try:
            found.append(parse_sample(line, n))
        except SoilError as exc:
            errors.append(exc)
    return found, errors
'''

REPORT_REF = _REPORT_HEAD + '''
import math


def _combined(values: list[float]) -> float:
    # The lab combines cores by hydrogen-ion concentration, then converts back to pH.
    return -math.log10(sum(10.0 ** -v for v in values) / len(values))


def plot_ph(cores: list[CoreSample]) -> dict[str, float]:
    by_plot: dict[str, list[float]] = {}
    for s in cores:
        by_plot.setdefault(s.plot, []).append(s.ph)
    return {plot: round(_combined(values), 2) for plot, values in by_plot.items()}


def _advice(ph: float) -> str:
    if ph < LIME_BELOW:
        return "lime"
    return "sulphur" if ph > SULPHUR_ABOVE else "ok"


def liming_report(cores: list[CoreSample]) -> str:
    return "".join(f"{plot} pH {ph:.2f} {_advice(ph)}\\n" for plot, ph in plot_ph(cores).items())
'''

REFERENCE = {"soilcard/cores.py": SAMPLES_REF, "soilcard/report.py": REPORT_REF}

TRAP_SOLUTION = {"soilcard/report.py": _REPORT_HEAD + '''
from statistics import mean


def plot_ph(cores: list[CoreSample]) -> dict[str, float]:
    readings: dict[str, list[float]] = {}
    for sample in cores:
        readings.setdefault(sample.plot, []).append(sample.ph)
    return {plot: round(mean(values), 2) for plot, values in readings.items()}


def liming_report(cores: list[CoreSample]) -> str:
    lines = []
    for plot, ph in plot_ph(cores).items():
        if ph < LIME_BELOW:
            advice = "lime"
        elif ph > SULPHUR_ABOVE:
            advice = "sulphur"
        else:
            advice = "ok"
        lines.append(f"{plot} pH {ph:.2f} {advice}")
    return "".join(line + "\\n" for line in lines)
'''}

# X in code: pH values averaged as plain numbers, through statistics, a sum over the
# readings divided by their count, or a running total of the readings.
TRAP_PATTERNS = (
    r'\b(?:statistics\.)?f?mean\(',
    r'\bsum\(\s*[\w.]+\s*\)\s*/',
    r'\bsum\(\s*(\w+)(?:\.ph)?\s+for\s+\w+\s+in\b[^)]*\)\s*/',
    r'\bsum\(\s*\w+\.ph\s+for\b',
    r'\+=\s*\w+\.ph\b',
    r'\bnp\.(?:average|mean)\(',
)
