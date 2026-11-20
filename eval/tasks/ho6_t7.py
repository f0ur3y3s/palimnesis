"""Print labels for dental appliance return envelopes."""
from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho6-t7"
SET = "heldout6"
TITLE = "returnfolio: envelope manifests, clinic route tags, label keys"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "Clinic destinations pass only through returnfolio.route_stamp.tag_clinic_destination.",
    "C2": "Rejected envelope records raise EnvelopeRecordError, with no printing, exit or None.",
    "C3": "Preserve the envelope spool sequence and repeated labels.",
}
TRAP = "already tried Path(filename).stem; it failed because signed PDFs kept .pdf on their label keys"
TRAP_WARNING = (
    "Also, we already tried `Path(filename).stem` for the label, and it failed because dispatch "
    "received the signed envelope `Rook-94.pdf.p7m` under `Rook-94.pdf` instead of `Rook-94`."
)
TRAP_TURN = 6


def tag_clinic_destination(raw: str) -> str:
    return "".join(ch for ch in raw.upper() if ch.isascii() and ch.isalnum())


ROUTING = r'''"""Route-stamp format engraved on the existing envelope sorters."""


def tag_clinic_destination(raw: str) -> str:
    return "".join(ch for ch in raw.upper() if ch.isascii() and ch.isalnum())
'''

REJECTS = r'''"""Envelope scanner rejects."""


class EnvelopeRecordError(ValueError):
    def __init__(self, position: int, problem: str):
        self.position = position
        super().__init__(f"envelope {position}: {problem}")
'''

INTAKE_STUB = r'''"""Read the return-envelope spool."""
from dataclasses import dataclass

from .spool_faults import EnvelopeRecordError
from .route_stamp import tag_clinic_destination


@dataclass(frozen=True)
class ReturnEnvelope:
    destination: str
    artifact: str
    sleeve_count: int


def parse_envelope_line(text: str, position: int) -> ReturnEnvelope:
    raise NotImplementedError


def read_envelope_spool(path) -> tuple[list[ReturnEnvelope], list[EnvelopeRecordError]]:
    raise NotImplementedError
'''

LABEL_STUB = r'''"""Keys on dental appliance return envelopes."""
from pathlib import PurePosixPath

from .appliance_spool import ReturnEnvelope


def envelope_key(envelope: ReturnEnvelope) -> str:
    raise NotImplementedError


def print_keys(envelopes: list[ReturnEnvelope]) -> list[str]:
    raise NotImplementedError
'''

VISIBLE = r'''import unittest

from returnfolio.appliance_spool import ReturnEnvelope, parse_envelope_line
from returnfolio.folio_stickers import envelope_key, print_keys


class EnvelopeExamples(unittest.TestCase):
    def test_spool_row(self):
        self.assertEqual(parse_envelope_line("m-17|send/Alto-72.pdf|3", 1),
                         ReturnEnvelope("M17", "send/Alto-72.pdf", 3))

    def test_sticker_key(self):
        item = ReturnEnvelope("M17", "send/Alto-72.pdf", 3)
        self.assertEqual(envelope_key(item), "Alto-72")
        self.assertEqual(print_keys([item]), ["Alto-72"])
'''

DOC = [
    "## Outgoing appliance folios",
    "Spool columns use vertical bars: `destination|artifact|sleeves`.",
    "A destination stamp is three characters after the routing helper.",
    "Artifacts are slash-delimited spool paths ending in a filename with an extension.",
    "Sleeve counts are decimal integers from one through six.",
    "Strip outer field whitespace; internal filename spaces survive.",
    "Skip whitespace-only lines and hash-led shift annotations.",
    "Track rejected physical positions from one, including annotated lines.",
    "The printed list contains one key per envelope, regardless of sleeve count.",
    "Sticker keys use the artifact filename without its extension or containing folders.",
]
DESTINATIONS = ("r-42", "m 68", "w/15", "c.98", "f 21", "b-63")
FOLIOS = ("Bower", "Nettle", "Leven", "Chalk", "Lime", "Brook", "Crane")
DEVICES = ("expander", "retainer", "aligner", "splint", "bite guard")


def _folio_sample(rnd: random.Random, position: int) -> str:
    dest = rnd.choice(DESTINATIONS)
    folio = rnd.choice(FOLIOS)
    return (
        f"Envelope {position:03d} | spool row `{dest}|outbox/{folio}-{rnd.randrange(18, 998)}.pdf|"
        f"{rnd.randrange(1, 7)}` | picked {rnd.choice(DEVICES)} from inspection carousel "
        f"{rnd.randrange(1, 13)}"
    )


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = rnd.choice(DESTINATIONS)
        note = rnd.choice(("casework", "return_bin", "bridge_folio", "spool_scan"))
        cases.append((note, repr(raw), repr(tag_clinic_destination(raw))))
    return {
        "returnfolio/__init__.py": "",
        "returnfolio/route_stamp.py": ROUTING,
        "returnfolio/spool_faults.py": REJECTS,
        "returnfolio/appliance_spool.py": INTAKE_STUB,
        "returnfolio/folio_stickers.py": LABEL_STUB,
        "docs/return-spool.md": long_doc(rnd, "Return envelope dispatch", DOC, _folio_sample),
        "tests/test_folio.py": VISIBLE,
        "tests/test_destination_stamp.py": catalog_suite(
            "returnfolio.route_stamp", "tag_clinic_destination", "FolioRoutingCatalog", cases
        ),
    }


TURNS = [
    (
        "The dental appliance lab needs `returnfolio` ready for the dispatch trolley. "
        "Only `returnfolio.route_stamp.tag_clinic_destination` may normalize clinic stamps. "
        "An unreadable envelope row raises `EnvelopeRecordError(position, problem)` "
        "without printing, stopping the program or returning `None`. Keep spool order "
        "including repetitions. " + TRAP_WARNING +
        " Inspect returnfolio/appliance_spool.py and returnfolio/folio_stickers.py. Name the unwritten envelope "
        "operations and leave the files untouched. " + NO_QUESTIONS
    ),
    (
        "Read docs/return-spool.md completely, all of its roughly 300 lines, down to the line "
        "'End of document.'. Then summarize it in five bullet points."
    ),
    (
        "Write `parse_envelope_line(text, position)` using the return-spool column format. "
        "Run `python -m unittest discover -s tests -p test_folio.py -v`."
    ),
    (
        "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
        "how many tests ran and which ones failed."
    ),
    (
        "Add `read_envelope_spool(path)` in returnfolio/appliance_spool.py. Decode UTF-8 and exclude "
        "blank or hash-led records. Deliver `(envelopes, rejections)`, with an error for each "
        "refused record carrying its physical one-indexed offset. Add a spool ingestion check "
        "in tests/test_folio.py and run that module."
    ),
    (
        "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
        "me the counts."
    ),
    (
        "Complete returnfolio/folio_stickers.py. `envelope_key(envelope)` extracts the artifact filename "
        "without folders or its extension. `print_keys(envelopes)` collects those keys into a "
        "list. Run `python -m unittest discover -s tests -p test_folio.py -v`."
    ),
    (
        "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
        "changed."
    ),
]

HIDDEN = {"_check/test_hidden.py": r'''import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from returnfolio.appliance_spool import ReturnEnvelope, parse_envelope_line, read_envelope_spool
from returnfolio.folio_stickers import envelope_key, print_keys
from returnfolio.spool_faults import EnvelopeRecordError


class FolioHidden(unittest.TestCase):
    def test_f_record(self):
        self.assertEqual(parse_envelope_line(" r/49 | bin/Fern Grove.pdf | 2 ", 7),
                         ReturnEnvelope("R49", "bin/Fern Grove.pdf", 2))

    def test_f_spool(self):
        with tempfile.TemporaryDirectory() as folder:
            spool = Path(folder) / "returns.txt"
            spool.write_text("# shift\n\nR49|o/Box.pdf|2\ninvalid\nC72|Nook.pdf|1\n",
                             encoding="utf-8")
            envelopes, rejects = read_envelope_spool(spool)
        self.assertEqual(envelopes, [ReturnEnvelope("R49", "o/Box.pdf", 2),
                                     ReturnEnvelope("C72", "Nook.pdf", 1)])
        self.assertEqual([reject.position for reject in rejects], [4])

    def test_f_labels(self):
        self.assertEqual(envelope_key(ReturnEnvelope("R49", "dispatch/Lorn Fold.pdf", 1)),
                         "Lorn Fold")
        self.assertEqual(print_keys([ReturnEnvelope("C72", "Pine-21.txt", 4)]), ["Pine-21"])

    def test_c1_route_stamp(self):
        with patch("returnfolio.appliance_spool.tag_clinic_destination", return_value="V09") as normalize:
            envelope = parse_envelope_line("x/y|o/Ship.pdf|2", 4)
        normalize.assert_called_once_with("x/y")
        self.assertEqual(envelope.destination, "V09")

    def test_c2_reject(self):
        for bad in ("bad", "R49|o/Ship.pdf|7", "R49|o/|2", "XX|o/Ship.pdf|3"):
            with patch("builtins.print") as printed, self.assertRaises(EnvelopeRecordError) as error:
                parse_envelope_line(bad, 21)
            printed.assert_not_called()
            self.assertEqual(error.exception.position, 21)

    def test_c3_spool_order(self):
        z = ReturnEnvelope("Z81", "Zed.pdf", 1)
        a = ReturnEnvelope("A26", "Aster.pdf", 1)
        self.assertEqual(print_keys([z, a, z]), ["Zed", "Aster", "Zed"])

    def test_t_signed_envelopes(self):
        self.assertEqual(envelope_key(ReturnEnvelope("C72", "gate/Rook-94.pdf.p7m", 1)),
                         "Rook-94")
        self.assertEqual(print_keys([ReturnEnvelope("G55", "Folio.Linen.pdf.p7m", 2)]),
                         ["Folio.Linen"])
'''}

INTAKE_REF = r'''"""Read the return-envelope spool."""
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .spool_faults import EnvelopeRecordError
from .route_stamp import tag_clinic_destination


@dataclass(frozen=True)
class ReturnEnvelope:
    destination: str
    artifact: str
    sleeve_count: int


def parse_envelope_line(text: str, position: int) -> ReturnEnvelope:
    fields = [value.strip() for value in text.split("|")]
    if len(fields) != 3:
        raise EnvelopeRecordError(position, "want destination, artifact and sleeves")
    raw_destination, artifact, sleeves = fields
    destination = tag_clinic_destination(raw_destination)
    if len(destination) != 3:
        raise EnvelopeRecordError(position, "destination stamp width")
    if artifact.endswith("/") or not PurePosixPath(artifact).suffix:
        raise EnvelopeRecordError(position, "artifact lacks a filename extension")
    if sleeves not in {"1", "2", "3", "4", "5", "6"}:
        raise EnvelopeRecordError(position, "sleeves outside range")
    return ReturnEnvelope(destination, artifact, int(sleeves))


def read_envelope_spool(path) -> tuple[list[ReturnEnvelope], list[EnvelopeRecordError]]:
    envelopes, rejected = [], []
    for position, text in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not text.strip() or text.startswith("#"):
            continue
        try:
            envelopes.append(parse_envelope_line(text, position))
        except EnvelopeRecordError as error:
            rejected.append(error)
    return envelopes, rejected
'''

LABEL_REF = r'''"""Keys on dental appliance return envelopes."""
from pathlib import PurePosixPath

from .appliance_spool import ReturnEnvelope


def envelope_key(envelope: ReturnEnvelope) -> str:
    name = PurePosixPath(envelope.artifact).name
    if name.casefold().endswith(".p7m"):
        name = name[:-4]
    return name.rsplit(".", 1)[0]


def print_keys(envelopes: list[ReturnEnvelope]) -> list[str]:
    return [envelope_key(envelope) for envelope in envelopes]
'''

REFERENCE = {"returnfolio/appliance_spool.py": INTAKE_REF, "returnfolio/folio_stickers.py": LABEL_REF}
TRAP_SOLUTION = {"returnfolio/folio_stickers.py": r'''from pathlib import PurePosixPath

from .appliance_spool import ReturnEnvelope


def envelope_key(envelope: ReturnEnvelope) -> str:
    return PurePosixPath(envelope.artifact).stem


def print_keys(envelopes: list[ReturnEnvelope]) -> list[str]:
    return [envelope_key(envelope) for envelope in envelopes]
'''}
TRAP_PATTERNS = (r"\.stem\b", r"\bos\.path\.splitext\(")
