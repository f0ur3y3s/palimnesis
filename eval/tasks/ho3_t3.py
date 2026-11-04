"""ho3-t3: bracket problems in source text, and its command line. The restart task of the
third held-out task set (as ho2-t3, D45.9.7).

``KEY_CONSTRAINT`` C2 (what the command line prints and its exit status) is stated once, in
the first turn, before the proxy restart. No turn before the restart touches the command
line, and the turn that builds it (turn 5, after the restart) does not repeat the rule.

Other A1 categories: an information need that arises mid-task (turn 7's triple-quoted
strings follow a rule in the reference document read in turn 2, including the unterminated
case and its code BC4, which turn 7 does not restate); restarts and multiple eviction
events; an oversized read.
"""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho3-t3"
SET = "heldout3"
TITLE = "bracecheck: report unbalanced brackets in source text, with a command line"
RESTART_BEFORE = 4
KEY_CONSTRAINT = "C2"
CONSTRAINTS = {
    "C1": "positions are 1-based line and column numbers, every character (a tab too) counting "
          "as one column; scan_text returns its problems as (line, column, code) tuples sorted "
          "by line, then column",
    "C2": "the command line prints only the problems on stdout, one per line as the path as "
          "given, ':', line, ':', column, ': ', code, with files in the order given and each "
          "file's problems in position order, and exits with status 5 when it printed any "
          "problem and 0 when it printed none",
    "C3": "brackets inside strings and comments never count, and a '#' inside a string does "
          "not start a comment",
}
TRAP = ("already tried counting the openers and closers of each kind and comparing the "
        "totals; it failed because ')(' came out balanced and '([)]' passed")


def leading_width(line: str) -> int:
    width = 0
    for c in line:
        if c == " ":
            width += 1
        elif c == "\t":
            width += 8 - width % 8
        else:
            break
    return width


LEGACY = '''"""Indentation width for the style report (do not change)."""


def leading_width(line: str) -> int:
    width = 0
    for c in line:
        if c == " ":
            width += 1
        elif c == "\\t":
            width += 8 - width % 8
        else:
            break
    return width
'''

STUB = '''"""Bracket problems in source text. See docs/bracket_rules.md."""

from __future__ import annotations

from typing import NamedTuple


class BraceIssue(NamedTuple):
    line: int
    col: int
    code: str


def scan_text(text: str) -> list[BraceIssue]:
    """Every bracket problem in ``text``."""
    raise NotImplementedError
'''

CLI_STUB = '''"""Command line: ``python -m bracecheck <file> [<file> ...]``."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
'''

MAIN = '''from .cli import main

raise SystemExit(main())
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bracecheck.scan import scan_text  # noqa: E402


class ScanTests(unittest.TestCase):
    def test_balanced(self):
        self.assertEqual(scan_text("f(a[1], {b: 2})\\n"), [])

    def test_stray_closer(self):
        self.assertEqual([tuple(p) for p in scan_text("x)\\n")], [(1, 2, "BC1")])
'''

DOC_INTRO = [
    "What the bracket checker in the pre-commit hook reports, and where.",
    "",
    "## Brackets",
    "",
    "- The brackets are `(` `)`, `[` `]` and `{` `}`. Each closer must close the innermost",
    "  bracket still open.",
    "",
    "## Strings and comments",
    "",
    "- A `'` or `\"` starts a string, which ends at the next unescaped quote of the same kind",
    "  on the same line. Inside a string a backslash escapes the next character. A string",
    "  still open at the end of its line ends there; that is not a problem.",
    "- Outside strings, `#` starts a comment that runs to the end of the line.",
    "- Triple-quoted strings (`'''` or `\"\"\"`) may span lines and end at the next unescaped",
    "  occurrence of the same three quotes. A triple-quoted string that is still open at the",
    "  end of the text is problem BC4, reported at its first quote, and the rest of the text",
    "  is part of it.",
    "- Brackets inside strings and comments are not brackets.",
    "",
    "## Problems",
    "",
    "- BC1: a closer when no bracket is open. Reported at the closer.",
    "- BC2: an opener still open at the end of the text. Reported at the opener.",
    "- BC3: a closer that does not match the innermost open bracket. Reported at the closer;",
    "  the innermost bracket then counts as closed.",
    "",
    "## Retired: codes of the 2019 hook",
    "",
    "- The 2019 hook printed E101 for an unmatched closer, E102 for an unclosed opener and",
    "  E103 for a crossed pair. Nothing reads these codes now.",
]

SNIPPETS = ["f(a[1])", "d = {k: [v]}", "print((x)", "xs[0]]", "g({)}", "s = '(' + y", "# (", "call(a, b,"]
PROJECTS = ["wren", "heron", "egret", "kestrel", "lapwing", "avocet", "bittern", "curlew"]


def _record(rnd: random.Random, i: int) -> str:
    return (f"`{rnd.choice(SNIPPETS)}` | from the {rnd.choice(PROJECTS)} repository, line "
            f"{rnd.randint(1, 900)}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        indent = "".join(rnd.choice([" ", "  ", "\t", "    "]) for _ in range(rnd.randint(0, 4)))
        line = indent + rnd.choice(["return x", "pass", "if a:", "", "# note", "x = 1"])
        slug = rnd.choice(["spaces_only", "tabs_only", "mixed_indent", "style_report"])
        cases.append((slug, repr(line), repr(leading_width(line))))
    return {
        "bracecheck/__init__.py": '"""Bracket problems for the pre-commit hook."""\n',
        "bracecheck/__main__.py": MAIN,
        "bracecheck/cli.py": CLI_STUB,
        "bracecheck/legacy.py": LEGACY,
        "bracecheck/scan.py": STUB,
        "docs/bracket_rules.md": long_doc(rnd, "Bracket rules of the pre-commit hook", DOC_INTRO,
                                          _record),
        "tests/test_scan.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("bracecheck.legacy", "leading_width",
                                                      "LeadingWidthCatalogTests", cases),
    }


TURNS = [
    "This session is about `bracecheck`, which reports unbalanced brackets in source files "
    "for our pre-commit hook. Requirements: (1) positions are 1-based line and column "
    "numbers, with every character, a tab included, counting as one column, and `scan_text` "
    "returns its problems as (line, column, code) tuples sorted by line and then column; (2) "
    "the command-line tool prints only the problems on stdout, one per line as the path "
    "exactly as given, a colon, the line, a colon, the column, a colon and a space, and the "
    "code (for example `src/a.py:3:14: BC2`), with the files in the order given and each "
    "file's problems in position order, and it exits with status 5 when it printed any "
    "problem and 0 when it printed none; (3) brackets inside strings and comments never "
    "count, and a '#' inside a string does not start a comment. Also: we already tried "
    "counting the openers and closers of each kind and comparing the totals, and it failed "
    "because ')(' came out balanced and '([)]' passed. Begin by reading bracecheck/scan.py "
    "and telling me what needs writing; change nothing yet. "
    + NO_QUESTIONS,
    "Read docs/bracket_rules.md in full, all of its roughly 300 lines, through the line "
    "'End of document.', and summarize it in five bullet points.",
    "Implement `scan_text` for brackets, ordinary one-line strings and comments; leave "
    "triple-quoted strings for later. Then run `python -m unittest tests.test_scan -v`.",
    "Run every test verbosely with `python -m unittest discover -s tests -v` and tell me how "
    "many ran and which failed.",
    "Now write the entry point `main(argv)` in bracecheck/cli.py, so that `python -m "
    "bracecheck <file> [<file> ...]` checks each file with scan_text and reports the problems "
    "it finds. Return 2 when a file does not exist, with a short message on stderr. Add tests "
    "for it in tests/test_cli.py and run them with `python -m unittest tests.test_cli -v`.",
    "Run every test verbosely again (`python -m unittest discover -s tests -v`) and give me "
    "the totals.",
    "Next, triple-quoted strings: make scan_text handle them as the bracket rules document "
    "describes. Also add an `--only CODE` option to the command line that limits the report "
    "to problems with that code. Add tests for both and run `python -m unittest "
    "tests.test_scan tests.test_cli -v`.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": r'''import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bracecheck.cli import main  # noqa: E402
from bracecheck.scan import scan_text  # noqa: E402

BAD = "f(a]\nx = (1\n"
OTHER = ")\n"
GOOD = "f(a[1])  # ok)\n"


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


def write(d, name, text):
    p = Path(d) / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def scan(text):
    return [tuple(p) for p in scan_text(text)]


def line_with(text, *parts):
    return any(all(p in line for p in parts) for line in text.splitlines())


class HiddenTests(unittest.TestCase):
    def test_f_scan(self):
        for text, want in (("f(a[1], {b: 2})\n", []),
                           ("f(a]\n", [(1, 4, "BC3")]),
                           (")(\n", [(1, 1, "BC1"), (1, 2, "BC2")]),
                           ("([)]\n", [(1, 3, "BC3"), (1, 4, "BC3")]),
                           ("def f(\n    x,\n    y\n", [(1, 6, "BC2")]),
                           ("a = [1,\n  2]]\n", [(2, 5, "BC1")]),
                           ("{[(\n)]}\n}", [(3, 1, "BC1")]),
                           ("", [])):
            self.assertEqual(scan(text), want, repr(text))

    def test_f_triple(self):
        s3, d3 = "'" * 3, '"' * 3
        for text, want in (("x = " + d3 + "(\n[\n" + d3 + " + (1)\n", []),
                           ("s = " + s3 + "unclosed (\n", [(1, 5, "BC4")]),
                           ("f(" + d3 + "a)" + d3 + ", " + s3 + "b]" + s3 + ")\n", []),
                           ("f(" + s3 + "\n", [(1, 2, "BC2"), (1, 3, "BC4")]),
                           ("x = " + d3 + "a\\" + d3 + "b" + d3 + " (\n", [(1, 18, "BC2")]),
                           (d3 + "\n)\n" + d3 + " )\n", [(3, 5, "BC1")]),
                           ("s = " + s3 + "a\n" + d3 + "\n]" + s3 + " + [1]\n", [])):
            self.assertEqual(scan(text), want, repr(text))

    def test_f_cli(self):
        with tempfile.TemporaryDirectory() as d:
            bad, good = write(d, "bad.py", BAD), write(d, "good.py", GOOD)
            code, out, err = run_main([bad])
            self.assertTrue(line_with(out + err, "1", "4", "BC3"), out + err)
            self.assertTrue(line_with(out + err, "2", "5", "BC2"), out + err)
            self.assertEqual(run_main([good])[0], 0)
            self.assertEqual(run_main([str(Path(d) / "missing.py")])[0], 2)
            self.assertEqual(run_main([good, str(Path(d) / "missing.py")])[0], 2)

    def test_f_only(self):
        with tempfile.TemporaryDirectory() as d:
            bad = write(d, "bad.py", BAD)
            code, out, err = run_main([bad, "--only", "BC2"])
            self.assertTrue(line_with(out + err, "2", "5", "BC2"), out + err)
            self.assertNotIn("BC3", out + err)

    def test_c1_positions(self):
        self.assertEqual(scan("\t\t)\n"), [(1, 3, "BC1")])
        self.assertEqual(scan("é)\n"), [(1, 2, "BC1")])
        self.assertEqual(scan("((\n]\n"), [(1, 1, "BC2"), (2, 1, "BC3")])
        self.assertEqual(scan("(\n]\n)\n["), [(2, 1, "BC3"), (3, 1, "BC1"), (4, 1, "BC2")])
        self.assertIsInstance(scan_text("((\n]\n"), list)

    def test_c2_cli_output(self):
        with tempfile.TemporaryDirectory() as d:
            bad, other = write(d, "bad.py", BAD), write(d, "other.py", OTHER)
            good = write(d, "good.py", GOOD)
            code, out, _ = run_main([bad])
            self.assertEqual((code, out), (5, f"{bad}:1:4: BC3\n{bad}:2:5: BC2\n"))
            code, out, _ = run_main([other, good, bad])
            self.assertEqual((code, out), (5, f"{other}:1:1: BC1\n{bad}:1:4: BC3\n{bad}:2:5: BC2\n"))
            code, out, _ = run_main([bad, "--only", "BC3"])
            self.assertEqual((code, out), (5, f"{bad}:1:4: BC3\n"))
            code, out, _ = run_main([bad, "--only", "BC1"])
            self.assertEqual((code, out), (0, ""))
            code, out, _ = run_main([good])
            self.assertEqual((code, out), (0, ""))

    def test_c3_strings_comments(self):
        for text, want in (("s = ')'  # (\n", []),
                           ("s = '#' + (\n", [(1, 11, "BC2")]),
                           ("s = 'it\\'s (' + ]\n", [(1, 17, "BC1")]),
                           ("s = 'abc (\n)\n", [(2, 1, "BC1")]),
                           ('d = {"k": "}"}\n', []),
                           ("# ) ] }\nx = 1\n", []),
                           ('s = "a\\"(" + ")"\n', [])):
            self.assertEqual(scan(text), want, repr(text))


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {
    "bracecheck/scan.py": r'''"""Bracket problems in source text. See docs/bracket_rules.md."""

from __future__ import annotations

from typing import NamedTuple

PAIRS = {")": "(", "]": "[", "}": "{"}


class BraceIssue(NamedTuple):
    line: int
    col: int
    code: str


def scan_text(text: str) -> list[BraceIssue]:
    out, stack = [], []
    n, i, line, start = len(text), 0, 1, 0
    while i < n:
        c = text[i]
        col = i - start + 1
        if c == "\n":
            line, start, i = line + 1, i + 1, i + 1
        elif c == "#":
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif c in "'\"" and text.startswith(c * 3, i):
            j = i + 3
            while j < n and not text.startswith(c * 3, j):
                j += 2 if text[j] == "\\" else 1
            if j >= n:
                out.append(BraceIssue(line, col, "BC4"))
                break
            seg = text[i:j + 3]
            if "\n" in seg:
                line += seg.count("\n")
                start = i + seg.rfind("\n") + 1
            i = j + 3
        elif c in "'\"":
            j = i + 1
            while j < n and text[j] not in ("\n", c):
                j += 2 if text[j] == "\\" and j + 1 < n and text[j + 1] != "\n" else 1
            i = j + 1 if j < n and text[j] == c else j
        else:
            if c in "([{":
                stack.append((line, col, c))
            elif c in PAIRS:
                if not stack:
                    out.append(BraceIssue(line, col, "BC1"))
                elif stack.pop()[2] != PAIRS[c]:
                    out.append(BraceIssue(line, col, "BC3"))
            i += 1
    out += [BraceIssue(l, k, "BC2") for l, k, _ in stack]
    return sorted(out)
''',
    "bracecheck/cli.py": '''"""Command line: ``python -m bracecheck <file> [<file> ...] [--only CODE]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .scan import scan_text


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bracecheck")
    p.add_argument("paths", nargs="+")
    p.add_argument("--only")
    a = p.parse_args(sys.argv[1:] if argv is None else argv)
    missing = [x for x in a.paths if not Path(x).is_file()]
    if missing:
        print(f"no such file: {missing[0]}", file=sys.stderr)
        return 2
    printed = 0
    for path in a.paths:
        for line, col, code in scan_text(Path(path).read_text(encoding="utf-8")):
            if a.only is None or code == a.only:
                print(f"{path}:{line}:{col}: {code}")
                printed += 1
    return 5 if printed else 0


if __name__ == "__main__":
    sys.exit(main())
''',
}
