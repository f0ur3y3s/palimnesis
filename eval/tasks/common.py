"""Shared pieces of the Phase 3 coding tasks (plan §5, R14 shape, D44.5).

Every task is a module ``eval/tasks/<id>.py`` (``dev_t1`` … ``ho_t5``) with:

- ``ID``, ``SET`` (``development`` or ``heldout``), ``TITLE``;
- ``files(rnd)``: the initial repository, as {relative path: text};
- ``TURNS``: the user turns of one OpenCode session, in order;
- ``RESTART_BEFORE``: the 0-based turn the proxy restarts before;
- ``CONSTRAINTS``: {constraint id: what the user stated}, and ``TRAP``: the
  "already tried X, it failed because Y" note;
- ``KEY_CONSTRAINT`` (the restart task only): stated only before the restart and
  needed only after it;
- ``HIDDEN``: the executable check, written only into a copy of the workspace made in the
  records tree after the session (``run.py``).
  Its ``test_f_*`` methods decide task success; ``test_c<N>_*`` methods check
  constraint ``C<N>``;
- ``REFERENCE``: a solution that passes the check (tests only; never shown to a model).

Context pressure: each task asks for a full read of a long document (``long_doc``) and
for verbose runs of a large passing suite (``catalog_suite``), so the session passes
32K tokens and the arms differ: arm 4 masks, arm 1 compacts.
"""

from __future__ import annotations

import random

DOC_LINES = 300       # about 10K tokens: one full read
CATALOG_TESTS = 300   # about 11.5K tokens per verbose run of the suite

NO_QUESTIONS = ("Work autonomously: do not ask me questions; if something is unclear, make a "
                "reasonable assumption and say what it was.")


def long_doc(rnd: random.Random, title: str, intro: list[str], record: callable,
             lines: int = DOC_LINES) -> str:
    """A long reference document: an introduction, then an appendix of example records
    (one table row per line, ``record(rnd, i)``) until ``lines`` lines."""
    out = [f"# {title}", "", *intro, "", "## Appendix A: example records", "",
           "| # | example | notes |", "|---|---|---|"]
    i = 0
    while len(out) < lines - 2:
        i += 1
        out.append(f"| {i} | {record(rnd, i)} |")
    out += ["", "End of document."]
    return "\n".join(out) + "\n"


def catalog_suite(module: str, func: str, cls: str, cases: list[tuple[str, str, str]]) -> str:
    """A passing unittest module, one test per ``(slug, input_repr, expected_repr)``, for a
    helper that already works. Verbose runs print one long line per test."""
    out = ["import sys", "import unittest", "from pathlib import Path", "",
           'sys.path.insert(0, str(Path(__file__).resolve().parents[1]))', "",
           f"from {module} import {func}  # noqa: E402", "", "",
           f"class {cls}(unittest.TestCase):"]
    for k, (slug, arg, want) in enumerate(cases, 1):
        out += [f"    def test_{func}_{k:04d}_{slug}(self):",
                f"        self.assertEqual({func}({arg}), {want})", ""]
    out.append("")
    return "\n".join(out)


def words(rnd: random.Random, bank: list[str], k: int) -> list[str]:
    return [rnd.choice(bank) for _ in range(k)]


SLUG_WORDS = ["alpha", "bravo", "cedar", "delta", "ember", "fjord", "gamma", "harbor", "indigo",
              "juniper", "kepler", "lumen", "maple", "nimbus", "onyx", "prairie", "quartz",
              "raven", "sierra", "tundra", "umber", "violet", "willow", "xenon", "yarrow", "zephyr"]
