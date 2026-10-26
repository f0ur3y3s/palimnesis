"""ho2-t2: transposing chord symbols and song sheets (fresh held-out task, O-B1).

A1 categories: a superseded decision with conflicting evidence (turn 1 asks for sharps; turn
5, after the restart, switches to flats, while the reference document's house style and the
visible test still say sharps); vague references and "continue" (turn 7: "continue with the
sheet side ... the rules we agreed on"); several distant facts needed together in turn 7
(C1 and C2 from turn 1, the flats decision from turn 5, the chord-line and column rules
from the document read in turn 2); an oversized read; restart before turn 5.
"""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho2-t2"
SET = "heldout2"
TITLE = "chordshift: transpose chord symbols and whole song sheets"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "the chord's quality suffix (m7, sus4, add9, 7#9, m(maj7) ...) is kept exactly as "
          "written; only the root and the slash bass change",
    "C2": "lyric lines, and every other line that is not a chord line, come out byte for byte "
          "unchanged",
    "C3": "an unreadable chord raises ChordError from chordshift/errors.py with the token in "
          ".token; it is never passed through unchanged",
}
TRAP = ("already tried a dict from each chord name to the next one up; it failed because it "
        "only knew plain major and minor chords and dropped suffixes such as m7b5 and slash "
        "basses such as D/F#")

SUPERSEDED = "sharps"  # turn 1's spelling; turn 5 replaces it with flats


def bpm_label(bpm: int) -> str:
    for limit, name in ((60, "largo"), (76, "adagio"), (108, "andante"), (120, "moderato"),
                        (168, "allegro")):
        if bpm < limit:
            return name
    return "presto"


LEGACY = '''"""Tempo labels for the set-list printout (do not change)."""


def bpm_label(bpm: int) -> str:
    for limit, name in ((60, "largo"), (76, "adagio"), (108, "andante"), (120, "moderato"),
                        (168, "allegro")):
        if bpm < limit:
            return name
    return "presto"
'''

ERRORS = '''"""Errors."""


class ChordError(ValueError):
    """A token that is not a chord. ``token`` is the rejected text."""

    def __init__(self, token, reason="not a chord"):
        super().__init__(f"{token!r}: {reason}")
        self.token = token
'''

STUB = '''"""Transposing chord symbols. See docs/chord_sheets.md."""

from .errors import ChordError  # noqa: F401


def transpose_chord(chord, steps):
    """``("Am7", 3)`` -> ``"Cm7"``: move the root (and any slash bass) by ``steps`` semitones."""
    raise NotImplementedError


def transpose_sheet(text, steps):
    """Transpose every chord line of a song sheet."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chordshift.transpose import transpose_chord  # noqa: E402


class TransposeTests(unittest.TestCase):
    def test_whole_step(self):
        self.assertEqual(transpose_chord("G", 2), "A")

    def test_suffix_kept(self):
        self.assertEqual(transpose_chord("Am7", 3), "Cm7")

    def test_house_style_sharps(self):
        self.assertEqual(transpose_chord("C", 1), "C#")
'''

DOC_INTRO = [
    "Conventions for the song sheets the band keeps in songs/.",
    "",
    "## Chords",
    "",
    "- A chord is a root, an optional quality suffix, and an optional slash bass: `F#m7b5`,",
    "  `Csus4`, `D/F#`. Roots and basses are A to G, optionally followed by `#` or `b`.",
    "- A suffix is built only from these pieces: `maj`, `min`, `m`, `dim`, `aug`, `sus`,",
    "  `add`, digits, `#`, `b`, `+`, `-`, `(` and `)`. Anything else is not a chord.",
    "- Input may use E#, B#, Cb and Fb; they are the same notes as F, C, B and E.",
    "",
    "## Lines",
    "",
    "- A chord line is a line whose whitespace-separated tokens are all chords. A blank line",
    "  is not a chord line. Every other line is lyrics or a heading.",
    "- When a chord line is transposed, each chord starts at the column where the original",
    "  chord started, or one column after the end of the previous chord if that is further",
    "  right. Trailing spaces on a chord line are dropped.",
    "",
    "## House style (2019)",
    "",
    "- Accidentals are written as sharps: C#, D#, F#, G#, A#.",
]

ROOTS = ["C", "D", "E", "F", "G", "A", "B", "Bb", "Eb", "F#", "C#", "Ab"]
SUFFIXES = ["", "m", "7", "m7", "maj7", "sus4", "add9", "dim", "6", "9", "m7b5"]


def _record(rnd: random.Random, i: int) -> str:
    chords = [rnd.choice(ROOTS) + rnd.choice(SUFFIXES) for _ in range(rnd.randint(3, 6))]
    return f"`{'   '.join(chords)}` | bar group {i}, {rnd.choice(['verse', 'chorus', 'bridge', 'outro'])}"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        bpm = rnd.randint(40, 200)
        slug = rnd.choice(["slow_tempo", "mid_tempo", "fast_tempo", "setlist_label"])
        cases.append((slug, f"{bpm}", repr(bpm_label(bpm))))
    return {
        "chordshift/__init__.py": '"""Chord transposition for the band\'s song sheets."""\n',
        "chordshift/errors.py": ERRORS,
        "chordshift/legacy.py": LEGACY,
        "chordshift/transpose.py": STUB,
        "docs/chord_sheets.md": long_doc(rnd, "Song sheet conventions", DOC_INTRO, _record),
        "songs/river_road.txt": "[Verse]\nG       D/F#    Em\nWalking down the river road,\n"
                                "C   Am7   D\nnothing but the morning light\n",
        "tests/test_transpose.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("chordshift.legacy", "bpm_label",
                                                      "BpmLabelCatalogTests", cases),
    }


TURNS = [
    "Today we build `chordshift`, which transposes the chords on our band's song sheets. "
    "Rules: (1) a chord's quality suffix (m7, sus4, add9, 7#9, m(maj7) and so on) is kept "
    "exactly as written, and only the root and the slash bass change; (2) lyric lines, and "
    "any other line that is not a chord line, come out byte for byte unchanged; (3) an "
    "unreadable chord raises ChordError from chordshift/errors.py with the token in `.token`, "
    "and is never passed through. For now, spell accidentals in the output with sharps (C#, "
    "not Db). We already tried a dict from each chord name to the next one up, and it failed "
    "because it only knew plain major and minor chords and dropped suffixes such as m7b5 and "
    "slash basses such as D/F#. Start by reading chordshift/transpose.py and "
    "chordshift/errors.py and tell me what has to be written; no edits yet. " + NO_QUESTIONS,
    "Read docs/chord_sheets.md from start to end, all of its roughly 300 lines, until the "
    "line 'End of document.'. Then summarize the conventions in five bullet points.",
    "Implement `transpose_chord(chord, steps)`: move the root and any slash bass by `steps` "
    "semitones (negative steps go down). Then run `python -m unittest tests.test_transpose "
    "-v`.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell "
    "me how many tests ran and which failed.",
    "Change of plan from the band: they read flats. From now on every accidental in the "
    "output is a flat (Db, Eb, Gb, Ab, Bb), whatever the input used and whatever older notes "
    "say; the earlier spelling rule no longer applies. Update transpose_chord and the tests "
    "to match, then run `python -m unittest tests.test_transpose -v`.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and "
    "give me the totals.",
    "Continue with the sheet side: implement `transpose_sheet(text, steps)` so a whole song "
    "sheet such as songs/river_road.txt comes out transposed, following the rules we agreed "
    "on and the line conventions in the document. Add tests to tests/test_transpose.py and "
    "run `python -m unittest tests.test_transpose -v`.",
    "Wrap up: run `python -m unittest discover -s tests` a final time and list what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chordshift.errors import ChordError  # noqa: E402
from chordshift.transpose import transpose_chord, transpose_sheet  # noqa: E402

SHEET = ("[Verse]\\n"
         "G       D/F#    Em\\n"
         "Walking down the river road,   \\n"
         "\\n"
         "C   Am7   D\\n"
         "nothing but the morning light\\n")
WANT = ("[Verse]\\n"
        "Ab      Eb/G    Fm\\n"
        "Walking down the river road,   \\n"
        "\\n"
        "Db  Bbm7  Eb\\n"
        "nothing but the morning light\\n")


class HiddenTests(unittest.TestCase):
    def test_f_chord(self):
        for chord, steps, want in (("C", 2, "D"), ("Am7", 3, "Cm7"), ("G", 12, "G"),
                                   ("Cmaj7", -13, "Bmaj7"), ("Bb", 1, "B"), ("E", -1, "Eb"),
                                   ("D/F#", 2, "E/Ab"), ("F#m7b5", 1, "Gm7b5"), ("Cb", 1, "C"),
                                   ("E#", 0, "F")):
            self.assertEqual(transpose_chord(chord, steps), want, (chord, steps))

    def test_f_flats(self):
        for chord, steps, want in (("C", 1, "Db"), ("F#", 0, "Gb"), ("A", 1, "Bb"),
                                   ("C#m", 0, "Dbm"), ("G/B", 1, "Ab/C"), ("D", 1, "Eb")):
            self.assertEqual(transpose_chord(chord, steps), want, (chord, steps))

    def test_f_sheet(self):
        self.assertEqual(transpose_sheet(SHEET, 1), WANT)
        self.assertEqual(transpose_sheet("C D  E\\n", 1), "Db Eb F\\n")
        self.assertEqual(transpose_sheet("Am   F   C   G\\n", -2), "Gm   Eb  Bb  F\\n")

    def test_c1_suffix(self):
        for suffix in ("sus4", "add9", "7#9", "m(maj7)", "dim7", "aug", "13", "m7b5", "maj9",
                       "7sus2", "6", "-7", "+"):
            self.assertEqual(transpose_chord("D" + suffix, 2), "E" + suffix, suffix)
            self.assertEqual(transpose_chord("D" + suffix + "/A", 2), "E" + suffix + "/B", suffix)

    def test_c2_lyrics_unchanged(self):
        lines = ["Am I the one you wanted,\\t ", "  [Chorus]  ", "", "   ",
                 "C'mon now, Em-brace it", "x2"]
        for line in lines:
            self.assertEqual(transpose_sheet(line + "\\n", 3), line + "\\n", repr(line))
        self.assertEqual(transpose_sheet("la la\\nG\\n", 1), "la la\\nAb\\n")

    def test_c3_chord_error(self):
        for token in ("H7", "Cx", "", "C/H", "c", "Gmaj7/"):
            with self.assertRaises(ChordError, msg=token) as cm:
                transpose_chord(token, 1)
            self.assertEqual(cm.exception.token, token)


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"chordshift/transpose.py": '''"""Transposing chord symbols. See docs/chord_sheets.md."""

import re

from .errors import ChordError

NOTES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
FLATS = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
CHORD = re.compile(r"([A-G])([#b]?)((?:maj|min|dim|aug|sus|add|m|[0-9#b+()-])*)(?:/([A-G])([#b]?))?")


def _note(letter, accidental, steps):
    n = NOTES[letter] + {"": 0, "#": 1, "b": -1}[accidental]
    return FLATS[(n + steps) % 12]


def transpose_chord(chord, steps):
    m = CHORD.fullmatch(chord) if isinstance(chord, str) else None
    if not m:
        raise ChordError(chord)
    root, acc, suffix, bass, bass_acc = m.groups()
    out = _note(root, acc, steps) + suffix
    if bass:
        out += "/" + _note(bass, bass_acc, steps)
    return out


def _is_chord_line(line):
    tokens = line.split()
    return bool(tokens) and all(CHORD.fullmatch(t) for t in tokens)


def _transpose_line(line, steps):
    out = ""
    for m in re.finditer(r"\\S+", line):
        new = transpose_chord(m.group(), steps)
        col = max(m.start(), len(out) + 1 if out else 0)
        out = out.ljust(col) + new
    return out


def transpose_sheet(text, steps):
    out = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\\r\\n")
        end = line[len(body):]
        out.append(_transpose_line(body, steps) + end if _is_chord_line(body) else line)
    return "".join(out)
'''}
