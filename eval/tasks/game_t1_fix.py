"""game-t1-fix: fix the TINY TANK WAR crash from a player's bug report (user's test, 2026-11-07).

Both arms start from the same buggy page: pair 2's `a4-d77` game (`pi-game-ws/attempt-005`,
R53), kept in `fixtures/game-t1-fix/index.html`. It crashes on its first explosion because
`drawEffects` reads `b.maxR` where `boom()` stored `max`, so a gradient radius is NaN. The
one turn is the user's report in their words, with the console error they pasted.

The hidden check is game-t1's (the corrected one, R53): the page must still have every
feature, parse, stay one self-contained file, and now run 900 frames with shots exploding.
The reference is the one-word fix. How much else an agent changed is read from the diff
against the fixture, which the run keeps in its workspace's git history.
"""

from __future__ import annotations

import random
from pathlib import Path

from game_t1 import CONSTRAINTS, HIDDEN, SMOKE  # noqa: F401  (SMOKE re-exported for tools)

ID = "game-t1-fix"
SET = "development"
TITLE = "TINY TANK WAR: fix the crash a player reported"
RESTART_BEFORE = None
KEY_CONSTRAINT = None

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "game-t1-fix" / "index.html"
BUGGY = FIXTURE.read_text(encoding="utf-8")

TURNS = [
    "index.html is TINY TANK WAR, a single-file HTML5 canvas game. A player reports: the game "
    "crashes when the screen shakes. The browser console shows:\n\n"
    "index.html:652 Uncaught TypeError: Failed to execute 'createRadialGradient' on "
    "'CanvasRenderingContext2D': The provided double value is non-finite.\n"
    "    at drawEffects (index.html:652:19)\n"
    "    at draw (index.html:869:3)\n"
    "    at frame (index.html:922:3)\n\n"
    "Fix the bug. Keep everything in the one index.html, with no external files or network.",
]


def files(rnd: random.Random) -> dict[str, str]:
    return {"index.html": BUGGY}


REFERENCE = {"index.html": BUGGY.replace("const R = b.maxR * (1", "const R = b.max * (1", 1)}
