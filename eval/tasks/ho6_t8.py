"""Weight-based oral suspension volumes for the small-animal dispensary."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho6-t8"
SET = "heldout6"
TITLE = "pawscript: weight chart lines, client references, syringe volumes, the dispensing sheet"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "Account codes are cleaned only by pawscript.legacy.client_ref; no second cleaner.",
    "C2": "An unusable chart entry raises ChartLineError(line_no, message); no printing, "
          "no exiting, no None in its place.",
    "C3": "Animals stay in chart sequence, on the sheet too; no sorting, merging or dropping "
          "of repeats.",
}
TRAP = ("already tried round(ml, 1); it failed because Rufus, a 4.5 kg terrier on 1 mg/kg of a "
        "2 mg/mL suspension, got a label reading 2.2 mL, not 2.3, as halves go to the even digit")
TRAP_WARNING = ("Also, we already tried `round(ml, 1)` for the syringe volume, and it failed "
                "because Rufus, a 4.5 kg terrier prescribed 1 mg/kg of a 2 mg/mL suspension, "
                "got a label reading 2.2 mL instead of 2.3: Python sends an exact half to the "
                "even digit, and the vets expect a half to go up.")
TRAP_TURN = 6


def client_ref(raw: str) -> str:
    core = "".join(ch for ch in raw if ch.isalnum()).upper()
    head = core.rstrip("0123456789")
    tail = core[len(head):]
    return f"{head}-{tail.zfill(5)}" if tail else head


LEGACY = '''"""Account codes as the practice till prints them (legacy; leave untouched)."""


def client_ref(raw: str) -> str:
    core = "".join(ch for ch in raw if ch.isalnum()).upper()
    head = core.rstrip("0123456789")
    tail = core[len(head):]
    return f"{head}-{tail.zfill(5)}" if tail else head
'''

ERRORS = '''"""Weight chart errors."""


class ChartLineError(ValueError):
    """An entry the dispensary cannot use. ``line_no`` counts from 1 in the chart file."""

    def __init__(self, line_no: int, message: str):
        super().__init__(f"chart line {line_no}: {message}")
        self.line_no = line_no
        self.message = message
'''

PATIENTS_STUB = '''"""Weight chart entries -> Patient records. See docs/weight_chart.md."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ChartLineError
from .legacy import client_ref


@dataclass(frozen=True)
class Patient:
    client: str
    pet: str
    species: str
    weight_kg: float


def parse_patient(line: str, line_no: int) -> Patient:
    """One entry ``client;pet;species;weight_kg`` -> Patient."""
    raise NotImplementedError


def load_patients(path) -> tuple[list[Patient], list[ChartLineError]]:
    """A whole weight chart file -> (patients, errors)."""
    raise NotImplementedError
'''

LIQUID_STUB = '''"""Syringe volumes and the dispensing sheet. See docs/weight_chart.md."""

from __future__ import annotations

from .patients import Patient


def dose_ml(weight_kg: float, mg_per_kg: float, mg_per_ml: float) -> float:
    """How many millilitres of suspension one dose is."""
    raise NotImplementedError


def dosing_sheet(patients: list[Patient], drug: str, mg_per_kg: float, mg_per_ml: float) -> str:
    """The sheet the dispensary prints for one suspension."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pawscript.errors import ChartLineError  # noqa: E402
from pawscript.patients import Patient, parse_patient  # noqa: E402
from pawscript.liquid import dose_ml, dosing_sheet  # noqa: E402

BISCUIT = Patient("AB-01234", "Biscuit", "dog", 12.4)


class ParsePatientTests(unittest.TestCase):
    def test_entry_basic(self):
        self.assertEqual(parse_patient("ab-1234;Biscuit;dog;12.4", 1), BISCUIT)

    def test_entry_bad_weight(self):
        with self.assertRaises(ChartLineError):
            parse_patient("ab-1234;Biscuit;dog;heavy", 1)


class VolumeTests(unittest.TestCase):
    def test_volume(self):
        self.assertEqual(dose_ml(12.0, 2, 10), 2.4)

    def test_volume_whole(self):
        self.assertEqual(dose_ml(20.0, 1.5, 10), 3.0)

    def test_sheet(self):
        self.assertEqual(dosing_sheet([BISCUIT], "Fenocalm", 2, 10),
                         "AB-01234 Biscuit: 2.5 mL of Fenocalm\\n")
'''

DOC_INTRO = [
    "How `pawscript` reads the practice weight chart and produces the dispensing sheet that",
    "the dispensary hatch prints for each prescribed drug.",
    "",
    "## Chart entries",
    "",
    "- Every animal sits on its own line, four fields split by `;`:",
    "  `client;pet;species;weight_kg`.",
    "- An empty line, or a line opening with `#`, carries no animal.",
    "- `client` is the owner's account code, cleaned by `pawscript.legacy.client_ref` exactly",
    "  as the till prints it. A code that cleans to nothing is unusable.",
    "- `pet` holds what the family calls the animal, trimmed at both ends; a blank one is",
    "  unusable.",
    "- `species` must be `dog`, `cat`, `rabbit` or `ferret`; capitals do not matter, and the",
    "  stored form is lower case.",
    "- `weight_kg` is a decimal number of kilograms, above 0 and at most 150.",
    "- An entry whose field count is not four, or that holds an unusable field, is turned",
    "  away; reading carries on with the following entries.",
    "- Error reports number lines physically: the chart's first line is 1, and blank and",
    "  `#` lines are counted too.",
    "",
    "## Syringe volumes",
    "",
    "- The dose in milligrams is the weight in kilograms times the prescribed mg per kg.",
    "- The volume drawn up is that dose divided by the suspension's strength in mg per mL,",
    "  given in millilitres to one decimal place, the finest mark on the oral syringes.",
    "",
    "## The dispensing sheet",
    "",
    "- One line per animal, in the sequence of the chart, naming the account code, the",
    "  pet, the volume in mL and the suspension's name.",
]

PETS = ["Biscuit", "Pepper", "Clover", "Quillon", "Dumpling", "Saffron", "Wicket", "Tofu",
        "Marzipan", "Gherkin", "Pippin", "Bramblewick", "Noodlepaw", "Custard", "Fennick"]
SPECIES_W = [("dog", 3.0, 48.0), ("cat", 2.1, 7.8), ("rabbit", 0.9, 4.6), ("ferret", 0.6, 2.2)]
CHART_NOTES = ["weighed on the floor scale at check-in", "owner read it off the home scale",
               "weight carried over from the spring booster", "nurse re-weighed after fasting",
               "estimate only, the animal would not sit still", "post-surgery recheck weight",
               "weighed in the carrier, carrier subtracted", "from the referral letter",
               "puppy growth check, weigh again next visit", "senior wellness clinic figure"]
REF_SHAPES = ["{l}-{d}", " {l}{d} ", "{l}.{d}", "{l} {d}", "{lo}/{d}", "{lo}-{d}x"]


def _raw_ref(rnd: random.Random) -> str:
    letters = "".join(rnd.choice("ABCDEFGHJKMNPRSTVWXZ") for _ in range(rnd.randint(1, 3)))
    digits = str(rnd.randint(1, 99999))
    return rnd.choice(REF_SHAPES).format(l=letters, lo=letters.lower(), d=digits)


def _record(rnd: random.Random, i: int) -> str:
    species, low, high = rnd.choice(SPECIES_W)
    weight = rnd.randint(int(low * 10), int(high * 10)) / 10
    return (f"`{_raw_ref(rnd).strip()};{rnd.choice(PETS)};{species};{weight}` | "
            f"{rnd.choice(CHART_NOTES)} (visit {i})")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = _raw_ref(rnd)
        slug = rnd.choice(["front_desk", "card_index", "old_till", "phone_booking",
                           "lapsed_account"])
        cases.append((slug, repr(raw), repr(client_ref(raw))))
    return {
        "pawscript/__init__.py": '"""Small-animal dispensary suspension volumes."""\n',
        "pawscript/errors.py": ERRORS,
        "pawscript/legacy.py": LEGACY,
        "pawscript/patients.py": PATIENTS_STUB,
        "pawscript/liquid.py": LIQUID_STUB,
        "docs/weight_chart.md": long_doc(rnd, "The weight chart and the dispensing sheet",
                                         DOC_INTRO, _record),
        "tests/test_pawscript.py": VISIBLE,
        "tests/test_legacy_refs.py": catalog_suite("pawscript.legacy", "client_ref",
                                                   "ClientRefCatalogTests", cases),
    }


TURNS = [
    "We're finishing `pawscript`, which reads our vet practice's weight chart and produces "
    "the dispensing sheet our dispensary hatch prints. Please keep to three rules throughout: (1) owner "
    "account codes are cleaned by `pawscript.legacy.client_ref` and by nothing else, no "
    "home-made cleaner beside it; (2) an unusable chart entry raises "
    "`ChartLineError(line_no, message)` from pawscript/errors.py, and the module must not print, "
    "must not call sys.exit and must not hand back None when an entry is bad; (3) animals stay in chart "
    "sequence, on the sheet as well: no sorting, merging or dropping of repeats. "
    + TRAP_WARNING + " To start, look through pawscript/patients.py and pawscript/liquid.py "
    "and list which pieces still need writing; leave every file as it is for the moment. " + NO_QUESTIONS,
    "Read docs/weight_chart.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Implement `parse_patient(line, line_no)` in pawscript/patients.py following "
    "docs/weight_chart.md. Then run `python -m unittest tests.test_pawscript -v`. The volume "
    "tests are expected to fail for now.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Now implement `load_patients(path)` in pawscript/patients.py: open the chart as UTF-8, "
    "pass over empty lines and lines beginning with `#`, and return `(patients, errors)`, "
    "with `errors` gathering the ChartLineError of every unusable entry, numbered by its "
    "physical line in the chart counting from 1. Put a test covering it into "
    "tests/test_pawscript.py and run that module.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Implement pawscript/liquid.py. `dose_ml(weight_kg, mg_per_kg, mg_per_ml)` works out "
    "the dose in mg as the weight times the mg per kg, divides it by the suspension "
    "strength, and returns the volume in mL to one decimal place, as a float. "
    "`dosing_sheet(patients, drug, mg_per_kg, mg_per_ml)` returns the sheet as one string "
    "with a line per patient in chart order, `<client> <pet>: <ml> mL of <drug>`, the "
    "volume shown as `dose_ml` gives it (for example `2.5`), with a newline closing every "
    "line. After that, run `python -m unittest tests.test_pawscript -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pawscript.errors import ChartLineError  # noqa: E402
from pawscript.patients import Patient, load_patients, parse_patient  # noqa: E402
from pawscript.liquid import dose_ml, dosing_sheet  # noqa: E402

SOURCE = "\\n".join((ROOT / "pawscript" / f).read_text(encoding="utf-8")
                   for f in ("patients.py", "liquid.py"))
BISCUIT = Patient("AB-01234", "Biscuit", "dog", 12.4)
PEPPER = Patient("KX-00077", "Pepper", "cat", 3.9)
CLOVER = Patient("RM-50210", "Clover", "rabbit", 2.2)
WICKET = Patient("T-00309", "Wicket", "dog", 31.0)


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(parse_patient(" ab-1234 ; Biscuit ;Dog; 12.4 ", 5), BISCUIT)
        self.assertEqual(parse_patient("kx 77;Pepper;CAT;3.9", 1), PEPPER)

    def test_f_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "chart.txt"
            p.write_text("# client;pet;species;kg\\n\\nab-1234;Biscuit;dog;12.4\\nnonsense\\n"
                         "kx 77;Pepper;CAT;3.9\\nrm50210;Clover;rabbit;0\\n", encoding="utf-8")
            patients, errors = load_patients(p)
        self.assertEqual(patients, [BISCUIT, PEPPER])
        self.assertEqual(sorted(e.line_no for e in errors), [4, 6])

    def test_f_volumes(self):
        for args, want in (((12.0, 2, 10), 2.4), ((20.0, 1.5, 10), 3.0), ((7.3, 4, 5), 5.8),
                           ((1.0, 1, 10), 0.1), ((18.6, 3, 20), 2.8), ((2.2, 2, 10), 0.4),
                           ((31.0, 2, 10), 6.2), ((3.9, 2, 10), 0.8), ((12.4, 2, 10), 2.5)):
            got = dose_ml(*args)
            self.assertEqual(got, want, args)
            self.assertIsInstance(got, float)

    def test_f_sheet(self):
        self.assertEqual(dosing_sheet([BISCUIT, PEPPER, CLOVER, WICKET], "Fenocalm", 2, 10),
                         "AB-01234 Biscuit: 2.5 mL of Fenocalm\\n"
                         "KX-00077 Pepper: 0.8 mL of Fenocalm\\n"
                         "RM-50210 Clover: 0.4 mL of Fenocalm\\n"
                         "T-00309 Wicket: 6.2 mL of Fenocalm\\n")

    def test_c1_codes_from_legacy(self):
        self.assertIn("client_ref", SOURCE)
        self.assertEqual(parse_patient("t.309x;Wicket;dog;31", 2).client, "T309X")

    def test_c2_chart_line_error(self):
        for line in ("ab1;Rex;dog", "ab1;Rex;dog;x", "ab1;Rex;dog;0", "ab1;Rex;dog;-3",
                     "ab1;Rex;lizard;3", "ab1; ;dog;3", " - ;Rex;dog;3", "ab1;Rex;dog;151",
                     "ab1;Rex;dog;4;extra"):
            with self.assertRaises(ChartLineError, msg=line) as cm:
                parse_patient(line, 9)
            self.assertEqual(cm.exception.line_no, 9)
        self.assertNotRegex(SOURCE, r"\\bprint\\s*\\(|sys\\.exit")

    def test_c3_chart_sequence(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "chart.txt"
            p.write_text("t309;Wicket;dog;31\\nab1234;Biscuit;dog;12.4\\nt309;Wicket;dog;31\\n",
                         encoding="utf-8")
            patients, errors = load_patients(p)
        self.assertEqual([x.pet for x in patients], ["Wicket", "Biscuit", "Wicket"])
        sheet = dosing_sheet(patients, "Fenocalm", 2, 10).splitlines()
        self.assertEqual([s.split(":")[0] for s in sheet],
                         ["T-00309 Wicket", "AB-01234 Biscuit", "T-00309 Wicket"])

    def test_t_half_goes_up(self):
        self.assertEqual(dose_ml(4.5, 1, 2), 2.3)
        self.assertEqual(dose_ml(3.5, 0.5, 5), 0.4)
        self.assertEqual(dosing_sheet([Patient("SQ-00042", "Gherkin", "dog", 4.5)],
                                      "Fenocalm", 1, 2),
                         "SQ-00042 Gherkin: 2.3 mL of Fenocalm\\n")


if __name__ == "__main__":
    unittest.main()
'''}

PATIENTS_REF = '''"""Weight chart entries -> Patient records. See docs/weight_chart.md."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import ChartLineError
from .legacy import client_ref

SPECIES = ("dog", "cat", "rabbit", "ferret")


@dataclass(frozen=True)
class Patient:
    client: str
    pet: str
    species: str
    weight_kg: float


def parse_patient(line: str, line_no: int) -> Patient:
    fields = line.rstrip("\\n").split(";")
    if len(fields) != 4:
        raise ChartLineError(line_no, f"expected 4 fields, got {len(fields)}")
    client = client_ref(fields[0])
    if not client:
        raise ChartLineError(line_no, "empty account code")
    pet = fields[1].strip()
    if not pet:
        raise ChartLineError(line_no, "empty pet name")
    species = fields[2].strip().lower()
    if species not in SPECIES:
        raise ChartLineError(line_no, f"unknown species {fields[2]!r}")
    try:
        weight = float(fields[3])
    except ValueError:
        raise ChartLineError(line_no, f"bad weight {fields[3]!r}") from None
    if not 0 < weight <= 150:
        raise ChartLineError(line_no, f"weight {fields[3]!r} out of range")
    return Patient(client, pet, species, weight)


def load_patients(path) -> tuple[list[Patient], list[ChartLineError]]:
    patients, errors = [], []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        try:
            patients.append(parse_patient(line, n))
        except ChartLineError as e:
            errors.append(e)
    return patients, errors
'''

LIQUID_REF = '''"""Syringe volumes and the dispensing sheet. See docs/weight_chart.md."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .patients import Patient

TENTH = Decimal("0.1")


def dose_ml(weight_kg: float, mg_per_kg: float, mg_per_ml: float) -> float:
    ml = Decimal(str(weight_kg)) * Decimal(str(mg_per_kg)) / Decimal(str(mg_per_ml))
    # A half tenth goes up, never to the even digit.
    return float(ml.quantize(TENTH, rounding=ROUND_HALF_UP))


def dosing_sheet(patients: list[Patient], drug: str, mg_per_kg: float, mg_per_ml: float) -> str:
    return "".join(f"{p.client} {p.pet}: {dose_ml(p.weight_kg, mg_per_kg, mg_per_ml)} mL of "
                   f"{drug}\\n" for p in patients)
'''

REFERENCE = {"pawscript/patients.py": PATIENTS_REF, "pawscript/liquid.py": LIQUID_REF}

TRAP_SOLUTION = {"pawscript/liquid.py": '''"""Syringe volumes and the dispensing sheet. See docs/weight_chart.md."""

from __future__ import annotations

from .patients import Patient


def dose_ml(weight_kg: float, mg_per_kg: float, mg_per_ml: float) -> float:
    ml = weight_kg * mg_per_kg / mg_per_ml
    return round(ml, 1)


def dosing_sheet(patients: list[Patient], drug: str, mg_per_kg: float, mg_per_ml: float) -> str:
    lines = []
    for p in patients:
        ml = dose_ml(p.weight_kg, mg_per_kg, mg_per_ml)
        lines.append(f"{p.client} {p.pet}: {ml} mL of {drug}\\n")
    return "".join(lines)
'''}

# Pattern for X as it shows up in model-written code after turn 1: a call of the
# built-in round, which takes an exact half to the even neighbour.
TRAP_PATTERNS = (r'(?<![.\w])round\(',)
