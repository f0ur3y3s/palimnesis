"""Oralhist computes transcription invoices from the archive's interview timeline."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho5-t9"
SET = "heldout5"
TITLE = "oralhist: transcript segments, tape timecodes, transcriber word statements"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "timestamp conversion goes through oralhist.legacy.timecode_seconds exclusively",
    "C2": "malformed transcript fragments raise oralhist/errors.py TranscriptError(line_no, "
          "message), without stdout/exit/None",
    "C3": "invoice ordering uses first tape encounter",
}
TRAP = ("already tried len(text.split()); stand-alone transcription marks inflated invoices")
TRAP_WARNING = ("Also, we already tried `len(text.split())`, and it failed because `—` "
                "and trailing `…` became paid words in invoices. Require at least one "
                "alphanumeric character per billed token.")
TRAP_TURN = 6


def timecode_seconds(code: str) -> int:
    parts = code.strip().split(":")
    if len(parts) == 2:
        parts.insert(0, "0")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"bad timecode {code!r}")
    hours, minutes, seconds = (int(p) for p in parts)
    if minutes > 59 or seconds > 59:
        raise ValueError(f"bad timecode {code!r}")
    return hours * 3600 + minutes * 60 + seconds


LEGACY = '''"""Tape timecodes as the archive's digitising desk writes them (in use since the
cassette transfers; keep as is)."""


def timecode_seconds(code: str) -> int:
    parts = code.strip().split(":")
    if len(parts) == 2:
        parts.insert(0, "0")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"bad timecode {code!r}")
    hours, minutes, seconds = (int(p) for p in parts)
    if minutes > 59 or seconds > 59:
        raise ValueError(f"bad timecode {code!r}")
    return hours * 3600 + minutes * 60 + seconds
'''

ERRORS = '''"""Faults found in transcript files."""


class TranscriptError(ValueError):
    """A segment line that cannot be accepted; ``line_no`` is counted from 1."""

    def __init__(self, line_no: int, message: str):
        super().__init__(f"segment line {line_no}: {message}")
        self.line_no = line_no
        self.message = message
'''

SEGMENTS_STUB = '''"""Transcript lines -> Segment records. See docs/transcripts.md."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import TranscriptError
from .legacy import timecode_seconds

SPEAKERS = ("INT", "NAR", "OTH")


@dataclass(frozen=True)
class Segment:
    tape: str
    start: int
    end: int
    speaker: str
    text: str


def parse_segment(line: str, line_no: int) -> Segment:
    """A transcript line ``tape|start|end|speaker|text`` -> Segment."""
    raise NotImplementedError


def load_transcript(path) -> tuple[list[Segment], list[TranscriptError]]:
    """A whole transcript file -> (segments, errors)."""
    raise NotImplementedError
'''

PAYSLIP_STUB = '''"""What each transcriber is paid for. See docs/transcripts.md."""

from __future__ import annotations

from .segments import Segment


def word_count(text: str) -> int:
    """The number of words in a segment's text."""
    raise NotImplementedError


def pay_sheet(segments: list[Segment]) -> str:
    """Per tape: the words transcribed and the seconds of recording covered."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oralhist.errors import TranscriptError  # noqa: E402
from oralhist.segments import Segment, parse_segment  # noqa: E402
from oralhist.payslip import pay_sheet, word_count  # noqa: E402

OPENING = Segment("OH-031", 125, 161, "INT", "Can you tell me where you were born?")


class SegmentLineTests(unittest.TestCase):
    def test_line_reads(self):
        self.assertEqual(parse_segment("OH-031|02:05|02:41|INT|Can you tell me where you were born?", 3),
                         OPENING)

    def test_line_backwards_times(self):
        with self.assertRaises(TranscriptError):
            parse_segment("OH-031|02:41|02:05|INT|Can you tell me where you were born?", 3)


class StatementTests(unittest.TestCase):
    def test_words(self):
        self.assertEqual(word_count("Can you tell me where you were born?"), 8)
        self.assertEqual(word_count("In Hebden, over the Co-op, in 1938."), 7)

    def test_pay_sheet(self):
        rows = [OPENING, Segment("OH-031", 161, 230, "NAR", "In Hebden, over the Co-op."),
                Segment("OH-044", 0, 12, "INT", "Testing, one two.")]
        self.assertEqual(pay_sheet(rows), "OH-031: 13 words, 105 s\\nOH-044: 3 words, 12 s\\n")
'''

DOC_INTRO = [
    "## Time-aligned export",
    "",
    "Speech fragments occupy one row apiece: `tape|start|end|speaker|text`.",
    "Trim all cells. Discard blank rows and column-one `#` comments.",
    "Shelf codes use `OH-` plus either three or four digits.",
    "Translate `MM:SS` or `H:MM:SS` via `oralhist.legacy.timecode_seconds`.",
    "The ending position must exceed the starting position.",
    "`INT` denotes interviewer, `NAR` narrator, and `OTH` any other participant.",
    "Transcript content must survive stripping as nonempty text.",
    "Fault positions use one-origin physical rows, counting annotations.",
    "",
    "## Contractor invoice",
    "",
    "Show billed word totals and total covered seconds per recording to assist gap review.",
]

SAYINGS = ["We had the wireless on every night.", "My father worked the night shift at the mill.",
           "There were six of us in two rooms.", "She kept chickens in the back yard.",
           "You could hear the trains from our bedroom.", "I left school at fourteen.",
           "The flood came up to the second stair.", "We queued for oranges at Christmas.",
           "And what did your mother do?", "How long did you stay there?"]
NOTES = ["side A", "side B", "copy tape", "reel transfer", "mono, some hiss",
         "recorded at the narrator's home", "second visit"]


def _code(rnd: random.Random) -> str:
    if rnd.random() < 0.5:
        return f"{rnd.randint(0, 59):02d}:{rnd.randint(0, 59):02d}"
    return f"{rnd.randint(0, 2)}:{rnd.randint(0, 59):02d}:{rnd.randint(0, 59):02d}"


def _record(rnd: random.Random, _index: int) -> str:
    start = rnd.randint(0, 5000)
    end = start + rnd.randint(3, 90)
    tc = [f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" for s in (start, end)]
    return (f"`OH-{rnd.randint(1, 640):03d}|{tc[0]}|{tc[1]}|"
            f"{rnd.choice(['INT', 'NAR', 'NAR', 'OTH'])}|{rnd.choice(SAYINGS)}` | "
            f"{rnd.choice(NOTES)}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        code = rnd.choice([_code(rnd), f" {_code(rnd)} "])
        slug = rnd.choice(["cassette_box", "reel_leader", "listening_copy", "summary_sheet",
                           "consent_form"])
        cases.append((slug, repr(code), repr(timecode_seconds(code))))
    return {
        "oralhist/__init__.py": '"""Oral-history transcripts and transcriber statements."""\n',
        "oralhist/errors.py": ERRORS,
        "oralhist/legacy.py": LEGACY,
        "oralhist/segments.py": SEGMENTS_STUB,
        "oralhist/payslip.py": PAYSLIP_STUB,
        "docs/transcripts.md": long_doc(rnd, "Transcript files and transcriber statements",
                                        DOC_INTRO, _record),
        "tests/test_oralhist.py": VISIBLE,
        "tests/test_legacy_timecodes.py": catalog_suite("oralhist.legacy", "timecode_seconds",
                                                        "TimecodeSecondsCatalogTests", cases),
    }


TURNS = [
    "Finish interview intake and transcriber invoices. C1: only "
    "`oralhist.legacy.timecode_seconds` converts timecodes. C2: malformed fragments raise "
    "oralhist/errors.py's `TranscriptError(line_no, message)`; no console diagnostics, abort, "
    "or None. C3: invoice order follows initial tape appearance. "
    + TRAP_WARNING + " " +
    "Read oralhist/segments.py and oralhist/payslip.py. Report unfinished functions while "
    "leaving the tree intact. "
    + NO_QUESTIONS,
    "Read docs/transcripts.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize it in five bullet points.",
    "Implement `parse_segment(line, line_no)` in oralhist/segments.py per docs/transcripts.md. "
    "Run `python -m unittest tests.test_oralhist -v`. Invoice cases remain pending.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Implement `load_transcript(path)` in oralhist/segments.py for UTF-8 exports. "
    "Exclude blank fragments and column-one `#` notes. Return `(segments, errors)`; "
    "give each TranscriptError its one-origin physical line. Cover transcript loading in "
    "tests/test_oralhist.py. Run `python -m unittest tests.test_oralhist -v`.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Now implement oralhist/payslip.py. `word_count(text)` gives the number of words in a "
    "segment's text. `pay_sheet(segments)` gives a line for every tape, "
    "`<tape>: <words> words, <seconds> s`, where words is the total word count of that "
    "tape's segments and seconds the total of their end minus start; put a newline after "
    "every line. Then run `python -m unittest tests.test_oralhist -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oralhist import segments as segments_module  # noqa: E402
from oralhist.errors import TranscriptError  # noqa: E402
from oralhist.segments import Segment, load_transcript, parse_segment  # noqa: E402
from oralhist.payslip import pay_sheet, word_count  # noqa: E402

SEGMENTS_SRC = (ROOT / "oralhist" / "segments.py").read_text(encoding="utf-8")
PAYSLIP_SRC = (ROOT / "oralhist" / "payslip.py").read_text(encoding="utf-8")


class HiddenTests(unittest.TestCase):
    def test_f_parse(self):
        self.assertEqual(parse_segment(" OH-0412 | 1:02:03 |1:02:30| NAR |We had the wireless on. ", 2),
                         Segment("OH-0412", 3723, 3750, "NAR", "We had the wireless on."))
        self.assertEqual(parse_segment("OH-007|00:00|00:09|OTH|Shall I make tea?", 1),
                         Segment("OH-007", 0, 9, "OTH", "Shall I make tea?"))

    def test_f_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "OH-007.txt"
            p.write_text("# OH-007 side A\\n\\nOH-007|00:00|00:09|OTH|Shall I make tea?\\n"
                         "OH-007|00:09|00:20|INT\\nOH-007|00:20|00:41|NAR|Two sugars, love.\\n"
                         "OH-007|00:41|00:61|NAR|Thank you.\\n", encoding="utf-8")
            segs, errors = load_transcript(p)
        self.assertEqual([s.end for s in segs], [9, 41])
        self.assertEqual(sorted(e.line_no for e in errors), [4, 6])

    def test_f_word_count(self):
        for text, n in (("Shall I make tea?", 4), ("Two sugars, love.", 3),
                        ("We didn't have a bathroom until 1962.", 7),
                        ("Mrs. O'Neill ran the corner shop, the one on Mill Lane.", 11),
                        ("Yes.", 1)):
            self.assertEqual(word_count(text), n, text)

    def test_f_pay_sheet(self):
        rows = [Segment("OH-007", 0, 9, "OTH", "Shall I make tea?"),
                Segment("OH-007", 20, 41, "NAR", "Two sugars, love."),
                Segment("OH-112", 300, 330, "INT", "And after the war?")]
        self.assertEqual(pay_sheet(rows), "OH-007: 7 words, 30 s\\nOH-112: 4 words, 30 s\\n")
        self.assertEqual(pay_sheet([]), "")

    def test_c1_timecodes_from_legacy(self):
        self.assertNotRegex(SEGMENTS_SRC + PAYSLIP_SRC, r"\\*\\s*3600|\\*\\s*60\\b|split\\(\\s*[\\"\\']:")
        original = segments_module.timecode_seconds
        segments_module.timecode_seconds = lambda code: len(code.strip())
        try:
            seg = parse_segment("OH-007|0:00|000:00|NAR|Hello.", 1)
            self.assertEqual((seg.start, seg.end), (4, 6))
        finally:
            segments_module.timecode_seconds = original

    def test_c2_transcript_errors(self):
        for line in ("OH-007|00:00|00:09|OTH", "OH-007|00:00|00:09|OTH|Hi.|extra",
                     "OH-07|00:00|00:09|OTH|Hi.", "TAPE-007|00:00|00:09|OTH|Hi.",
                     "OH-007|00:0x|00:09|OTH|Hi.", "OH-007|00:09|00:09|OTH|Hi.",
                     "OH-007|00:00|00:09|oth|Hi.", "OH-007|00:00|00:09|OTH|   "):
            with self.assertRaises(TranscriptError, msg=line) as cm:
                parse_segment(line, 15)
            self.assertEqual(cm.exception.line_no, 15)
        self.assertNotRegex(SEGMENTS_SRC + PAYSLIP_SRC, r"\\bprint\\s*\\(|sys\\.exit|\\bexit\\(")

    def test_c3_tapes_in_first_seen_order(self):
        rows = [Segment("OH-310", 0, 5, "INT", "Ready?"), Segment("OH-020", 0, 4, "NAR", "Go on."),
                Segment("OH-310", 5, 9, "NAR", "Yes, ready."), Segment("OH-150", 0, 2, "OTH", "Hush.")]
        self.assertEqual(pay_sheet(rows),
                         "OH-310: 3 words, 9 s\\nOH-020: 2 words, 4 s\\nOH-150: 1 words, 2 s\\n")

    def test_t_marks_are_not_words(self):
        self.assertEqual(word_count("Well \\u2014 I suppose \\u2026 yes."), 4)
        self.assertEqual(word_count("We left in 1947 \\u2014 all of us \\u2014 on the cart."), 10)
        self.assertEqual(word_count("\\u2026 and that was that."), 4)
        rows = [Segment("OH-009", 0, 30, "NAR", "It was \\u2014 how can I put it \\u2014 hard \\u2026")]
        self.assertEqual(pay_sheet(rows), "OH-009: 8 words, 30 s\\n")


if __name__ == "__main__":
    unittest.main()
'''}

SEGMENTS_REF = '''"""Transcript lines -> Segment records. See docs/transcripts.md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import TranscriptError
from .legacy import timecode_seconds

SPEAKERS = ("INT", "NAR", "OTH")
TAPE = re.compile(r"OH-[0-9]{3,4}")


@dataclass(frozen=True)
class Segment:
    tape: str
    start: int
    end: int
    speaker: str
    text: str


def _seconds(code: str, line_no: int) -> int:
    try:
        return timecode_seconds(code)
    except ValueError as exc:
        raise TranscriptError(line_no, str(exc)) from None


def parse_segment(line: str, line_no: int) -> Segment:
    if len(line.split("|")) != 5:
        raise TranscriptError(line_no, "a segment has five fields")
    tape, start, end, speaker, text = (f.strip() for f in line.rstrip("\\r\\n").split("|"))
    if not TAPE.fullmatch(tape):
        raise TranscriptError(line_no, f"tape {tape!r} is not a shelf number")
    first, last = _seconds(start, line_no), _seconds(end, line_no)
    if last <= first:
        raise TranscriptError(line_no, "the segment ends before it starts")
    if speaker not in SPEAKERS:
        raise TranscriptError(line_no, f"speaker {speaker!r} is unknown")
    if not text:
        raise TranscriptError(line_no, "nothing was transcribed")
    return Segment(tape, first, last, speaker, text)


def load_transcript(path) -> tuple[list[Segment], list[TranscriptError]]:
    segs: list[Segment] = []
    errors: list[TranscriptError] = []
    for pos, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip() or raw.startswith("#"):
            continue
        try:
            segs.append(parse_segment(raw, pos))
        except TranscriptError as exc:
            errors.append(exc)
    return segs, errors
'''

PAYSLIP_REF = '''"""What each transcriber is paid for. See docs/transcripts.md."""

from __future__ import annotations

from .segments import Segment


def word_count(text: str) -> int:
    # Bill only for tokens with alphanumeric content.
    return sum(1 for token in text.split() if any(ch.isalnum() for ch in token))


def pay_sheet(segments: list[Segment]) -> str:
    totals: dict[str, list[int]] = {}
    for seg in segments:
        words_secs = totals.setdefault(seg.tape, [0, 0])
        words_secs[0] += word_count(seg.text)
        words_secs[1] += seg.end - seg.start
    return "".join(f"{tape}: {w} words, {s} s\\n" for tape, (w, s) in totals.items())
'''

REFERENCE = {"oralhist/segments.py": SEGMENTS_REF, "oralhist/payslip.py": PAYSLIP_REF}

TRAP_SOLUTION = {"oralhist/payslip.py": '''"""What each transcriber is paid for. See docs/transcripts.md."""

from __future__ import annotations

from .segments import Segment


def word_count(text: str) -> int:
    return len(text.split())


def pay_sheet(segments: list[Segment]) -> str:
    order = []
    words = {}
    seconds = {}
    for seg in segments:
        if seg.tape not in words:
            order.append(seg.tape)
            words[seg.tape] = 0
            seconds[seg.tape] = 0
        words[seg.tape] += word_count(seg.text)
        seconds[seg.tape] += seg.end - seg.start
    return "".join(f"{tape}: {words[tape]} words, {seconds[tape]} s\\n" for tape in order)
'''}

# Detect raw split length, including an intermediate assignment.
TRAP_PATTERNS = (
    r'\blen\(\s*[\w.\[\]()]*\.split\(\s*\)\s*\)',
    r'\b(\w+)\s*=\s*[\w.\[\]()]*\.split\(\s*\)\s*\n[\s\S]*?\blen\(\s*\1\s*\)',
)
