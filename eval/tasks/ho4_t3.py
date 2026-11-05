"""ho4-t3: problems in pinned requirements files, and its command line. The restart task of
the fourth held-out task set (as ho3-t3).

``KEY_CONSTRAINT`` C2 (what the command line prints and its exit status) is stated once, in
the first turn, before the proxy restart. No turn before the restart touches the command
line, and the turn that builds it (turn 5, after the restart) does not repeat the rule.

Other A1 categories: an information need that arises mid-task (turn 7's hash options follow
a rule in the reference document read in turn 2, including the hash-mode rule and its code
PN5, which turn 7 does not restate); restarts and multiple eviction events; an oversized
read.
"""

from __future__ import annotations

import random
import re

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho4-t3"
SET = "heldout4"
TITLE = "pinlint: report unpinned, duplicate and unreadable requirements, with a command line"
RESTART_BEFORE = 4
KEY_CONSTRAINT = "C2"
CONSTRAINTS = {
    "C1": "scan_requirements returns its problems as (line, code, name) tuples with 1-based "
          "line numbers and the name in normalized form (lower case, every run of '-', '_' and "
          "'.' as one '-'), sorted by line, then code",
    "C2": "the command line prints only the problems on stdout, one per line as the code, a "
          "space, the path as given, ':', the line, a space and the name, with files in the "
          "order given and each file's problems in line order, and exits with status 3 when "
          "it printed any problem and 0 when it printed none",
    "C3": "comments never count ('#' at the start of a line or after whitespace starts one), "
          "and a line ending in a backslash continues on the next line, the joined "
          "requirement being reported at the line where it starts",
}
TRAP = ("already tried splitting each line on '==' and putting the left side in a set; it "
        "failed because 'Django' and 'django' both passed, and so did 'zope.interface' and "
        "'zope_interface'")


def wheel_tag(name: str, version: str) -> str:
    return f"{re.sub(r'[-_.]+', '_', name).lower()}-{version}-py3-none-any.whl"


LEGACY = '''"""Wheel file names for the mirror upload (do not change)."""

import re


def wheel_tag(name: str, version: str) -> str:
    return f"{re.sub(r'[-_.]+', '_', name).lower()}-{version}-py3-none-any.whl"
'''

STUB = '''"""Problems in requirements files. See docs/pin_rules.md."""

from __future__ import annotations

from typing import NamedTuple


class PinIssue(NamedTuple):
    line: int
    code: str
    name: str


def scan_requirements(text: str) -> list[PinIssue]:
    """Every problem in the requirements ``text``."""
    raise NotImplementedError
'''

CLI_STUB = '''"""Command line: ``python -m pinlint <file> [<file> ...]``."""

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

from pinlint.scan import scan_requirements  # noqa: E402


class ScanTests(unittest.TestCase):
    def test_all_pinned(self):
        self.assertEqual(scan_requirements("requests==2.31.0\\nattrs==23.1.0\\n"), [])

    def test_unpinned(self):
        self.assertEqual([tuple(p) for p in scan_requirements("flask>=2\\n")],
                         [(1, "PN1", "flask")])
'''

DOC_INTRO = [
    "What the pin checker in the release pipeline reports about requirements files.",
    "",
    "## Lines",
    "",
    "- A physical line whose last character is a backslash continues on the next line: the",
    "  backslash is dropped and the next line is appended. The joined logical line counts as",
    "  being on the line where it starts.",
    "- After joining, a `#` at the start of the line or after whitespace starts a comment",
    "  that runs to the end of the line. Blank and comment-only lines are skipped.",
    "- A line starting with `-` (`-r base.txt`, `--index-url ...`) is an option line and is",
    "  skipped.",
    "- Every other line is a requirement: a name, optional extras in brackets",
    "  (`black[jupyter]`), an optional version specifier, an optional environment marker",
    "  after `;` (ignored), and optional options after the requirement, each starting",
    "  with `--`.",
    "",
    "## Names",
    "",
    "- A name is letters, digits, `.`, `_` and `-`, starting and ending with a letter or a",
    "  digit. Names are compared in normalized form: lower case, with every run of `-`, `_`",
    "  and `.` written as one `-`. `Zope.Interface` and `zope_interface` are the same name.",
    "",
    "## Specifiers",
    "",
    "- A specifier is one clause, or several separated by commas. A clause is an operator",
    "  (`===`, `==`, `!=`, `~=`, `>=`, `<=`, `<` or `>`) and a version: numbers separated",
    "  by dots, optionally followed by `a`, `b` or `rc` and a number, then optionally",
    "  `.postN` and `.devN`. `==` and `!=` also accept a version ending in `.*`.",
    "- A requirement is pinned when its specifier is exactly one `==` clause with a full",
    "  version (no `.*`).",
    "",
    "## Problems",
    "",
    "- PN1: a requirement that is not pinned (no specifier, any other operator, `.*`, or",
    "  several clauses).",
    "- PN2: a requirement whose name already appeared on an earlier requirement line. It is",
    "  reported on every later line, not on the first.",
    "- PN3: a requirement line that cannot be read (bad name, bad extras, bad specifier).",
    "  Its name is reported as `?`, and it takes part in no other check.",
    "",
    "## Hashes",
    "",
    "- The options after a requirement may only be hashes, each written",
    "  `--hash=sha256:` followed by exactly 64 lower-case hexadecimal digits. Anything else",
    "  there (another algorithm, a short or upper-case digest, another option) is PN4,",
    "  reported once per requirement line.",
    "- Hash mode: when any requirement in a file carries a `--hash` option, every",
    "  requirement in that file must carry one. A requirement without any `--hash` option",
    "  in such a file is PN5.",
    "",
    "## Retired: codes of the 2018 hook",
    "",
    "- The 2018 hook printed W1 for an unpinned requirement, W2 for a duplicate and E1 for a",
    "  line it could not read. Nothing reads these codes now.",
]

PACKAGES = ["requests==2.31.0", "Django>=4.2", "numpy", "zope.interface==6.0", "black[jupyter]==24.1.0",
            "pandas==2.*", "attrs ~= 23.1", "urllib3==2.0.7"]
SERVICES = ["billing", "search", "ingest", "notifier", "gateway", "scheduler", "reports", "auth"]


def _record(rnd: random.Random, i: int) -> str:
    return (f"`{rnd.choice(PACKAGES)}` | from the {rnd.choice(SERVICES)} service, line "
            f"{rnd.randint(1, 400)}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        name = rnd.choice(["Flask", "zope.interface", "typing_extensions", "Pillow", "ruamel.yaml",
                           "python-dateutil", "PyYAML", "jaraco.text"])
        version = f"{rnd.randint(0, 9)}.{rnd.randint(0, 30)}.{rnd.randint(0, 9)}"
        slug = rnd.choice(["plain_name", "dotted_name", "mixed_case", "mirror_upload"])
        cases.append((slug, f"{name!r}, {version!r}", repr(wheel_tag(name, version))))
    return {
        "pinlint/__init__.py": '"""Pin problems for the release pipeline."""\n',
        "pinlint/__main__.py": MAIN,
        "pinlint/cli.py": CLI_STUB,
        "pinlint/legacy.py": LEGACY,
        "pinlint/scan.py": STUB,
        "docs/pin_rules.md": long_doc(rnd, "Pin rules of the release pipeline", DOC_INTRO,
                                      _record),
        "tests/test_scan.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("pinlint.legacy", "wheel_tag",
                                                      "WheelTagCatalogTests", cases),
    }


TURNS = [
    "This session is about `pinlint`, which reports problems in the requirements files our "
    "release pipeline installs from. Requirements: (1) `scan_requirements` returns its "
    "problems as (line, code, name) tuples with 1-based line numbers and the name in "
    "normalized form (lower case, with every run of '-', '_' and '.' written as one '-'), "
    "sorted by line and then code; (2) the command-line tool prints only the problems on "
    "stdout, one per line as the code, a space, the path exactly as given, a colon, the line "
    "number, a space and the name (for example `PN1 reqs/dev.txt:4 black`), with the files in "
    "the order given and each file's problems in line order, and it exits with status 3 when "
    "it printed any problem and 0 when it printed none; (3) comments never count, a '#' at "
    "the start of a line or after whitespace starting one, and a line ending in a backslash "
    "continues on the next line, the joined requirement being reported at the line where it "
    "starts. Also: we already tried splitting each line on '==' and putting the left side in "
    "a set, and it failed because 'Django' and 'django' both passed, and so did "
    "'zope.interface' and 'zope_interface'. Begin by reading pinlint/scan.py and telling me "
    "what needs writing; change nothing yet. " + NO_QUESTIONS,
    "Read docs/pin_rules.md in full, all of its roughly 300 lines, through the line 'End of "
    "document.', and summarize it in five bullet points.",
    "Implement `scan_requirements` for names, specifiers, duplicates and unreadable lines, "
    "with comments and continuation lines; leave hash options for later. Then run `python -m "
    "unittest tests.test_scan -v`.",
    "Run every test verbosely with `python -m unittest discover -s tests -v` and tell me how "
    "many ran and which failed.",
    "Now write the entry point `main(argv)` in pinlint/cli.py, so that `python -m pinlint "
    "<file> [<file> ...]` checks each file with scan_requirements and reports the problems "
    "it finds. Return 2 when a file does not exist, with a short message on stderr. Add tests "
    "for it in tests/test_cli.py and run them with `python -m unittest tests.test_cli -v`.",
    "Run every test verbosely again (`python -m unittest discover -s tests -v`) and give me "
    "the totals.",
    "Next, hashes: make scan_requirements check `--hash` options as the pin rules document "
    "describes. Also add a `--skip CODE` option to the command line that leaves problems with "
    "that code out of the report. Add tests for both and run `python -m unittest "
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

from pinlint.cli import main  # noqa: E402
from pinlint.scan import scan_requirements  # noqa: E402

BAD = "flask>=2\nrequests==2.31.0\nRequests==2.31.0\n"
OTHER = "!!!\n"
GOOD = "requests==2.31.0  # ok\n"
H = "a" * 64


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
    return [tuple(p) for p in scan_requirements(text)]


def line_with(text, *parts):
    return any(all(p in line for p in parts) for line in text.splitlines())


class HiddenTests(unittest.TestCase):
    def test_f_scan(self):
        for text, want in (("requests==2.31.0\nflask>=2\n", [(2, "PN1", "flask")]),
                           ("Django==4.2\ndjango==4.2.1\n", [(2, "PN2", "django")]),
                           ("zope.interface==6.0\nzope_interface==6.1\n",
                            [(2, "PN2", "zope-interface")]),
                           ("numpy\n", [(1, "PN1", "numpy")]),
                           ("pkg==\n", [(1, "PN3", "?")]),
                           ("!!!\n", [(1, "PN3", "?")]),
                           ("-r base.txt\n--index-url https://pypi.example/simple\n\n", []),
                           ("black[jupyter]==24.1.0\n", []),
                           ("attrs == 23.1 ; python_version < '3.12'\n", []),
                           ("pandas==2.*\n", [(1, "PN1", "pandas")]),
                           ("idna>=3,<4\n", [(1, "PN1", "idna")]),
                           ("pytest==8.0.0rc1\nsix==1.16.0.post1\n", []),
                           ("a==1\nA==2\na>=1\n", [(2, "PN2", "a"), (3, "PN1", "a"), (3, "PN2", "a")]),
                           ("x==1\n???\nx==1\n", [(2, "PN3", "?"), (3, "PN2", "x")]),
                           ("", [])):
            self.assertEqual(scan(text), want, repr(text))

    def test_f_hashes(self):
        for text, want in ((f"foo==1.0 --hash=sha256:{H}\nbar==2.0\n", [(2, "PN5", "bar")]),
                           (f"foo==1.0 --hash=sha256:{H[:-1]}\n", [(1, "PN4", "foo")]),
                           (f"foo==1.0 --hash=sha256:{H.upper()}\n", [(1, "PN4", "foo")]),
                           (f"foo==1.0 --hash=md5:abc\nbar==1 --hash=sha256:{H}\n",
                            [(1, "PN4", "foo")]),
                           (f"foo==1.0 \\\n    --hash=sha256:{H} \\\n    --hash=sha256:{'b' * 64}\n"
                            "bar>=1\n", [(4, "PN1", "bar"), (4, "PN5", "bar")]),
                           (f"foo==1.0 --hash=sha256:{H} --hash=sha1:{H[:40]}\n",
                            [(1, "PN4", "foo")]),
                           ("foo==1.0\nbar==2.0\n", []),
                           (f"# x==1 --hash=sha256:{H}\nfoo==1.0\n", []),
                           (f"foo==1.0 --hash=sha256:{H}\nFoo==1.0\n",
                            [(2, "PN2", "foo"), (2, "PN5", "foo")])):
            self.assertEqual(scan(text), want, repr(text))

    def test_f_cli(self):
        with tempfile.TemporaryDirectory() as d:
            bad, good = write(d, "bad.txt", BAD), write(d, "good.txt", GOOD)
            code, out, err = run_main([bad])
            self.assertTrue(line_with(out + err, "1", "PN1", "flask"), out + err)
            self.assertTrue(line_with(out + err, "3", "PN2", "requests"), out + err)
            self.assertEqual(run_main([good])[0], 0)
            self.assertEqual(run_main([str(Path(d) / "missing.txt")])[0], 2)
            self.assertEqual(run_main([good, str(Path(d) / "missing.txt")])[0], 2)

    def test_f_skip(self):
        with tempfile.TemporaryDirectory() as d:
            bad = write(d, "bad.txt", BAD)
            code, out, err = run_main([bad, "--skip", "PN1"])
            self.assertTrue(line_with(out + err, "3", "PN2", "requests"), out + err)
            self.assertNotIn("PN1", out + err)

    def test_c1_positions(self):
        self.assertEqual(scan("\n\nB_C==1\nb.c==1\n"), [(4, "PN2", "b-c")])
        self.assertEqual(scan("x>=1\n\ny\n"), [(1, "PN1", "x"), (3, "PN1", "y")])
        self.assertEqual(scan("Ruamel.YAML>=0.17\n"), [(1, "PN1", "ruamel-yaml")])
        self.assertEqual(scan("Foo__Bar..Baz\n"), [(1, "PN1", "foo-bar-baz")])
        self.assertEqual(scan("q\nQ\n"), [(1, "PN1", "q"), (2, "PN1", "q"), (2, "PN2", "q")])
        self.assertIsInstance(scan_requirements("x>=1\n"), list)

    def test_c2_cli_output(self):
        with tempfile.TemporaryDirectory() as d:
            bad, other = write(d, "bad.txt", BAD), write(d, "other.txt", OTHER)
            good = write(d, "good.txt", GOOD)
            code, out, _ = run_main([bad])
            self.assertEqual((code, out), (3, f"PN1 {bad}:1 flask\nPN2 {bad}:3 requests\n"))
            code, out, _ = run_main([other, good, bad])
            self.assertEqual((code, out), (3, f"PN3 {other}:1 ?\nPN1 {bad}:1 flask\n"
                                              f"PN2 {bad}:3 requests\n"))
            code, out, _ = run_main([bad, "--skip", "PN1"])
            self.assertEqual((code, out), (3, f"PN2 {bad}:3 requests\n"))
            code, out, _ = run_main([other, "--skip", "PN3"])
            self.assertEqual((code, out), (0, ""))
            code, out, _ = run_main([good])
            self.assertEqual((code, out), (0, ""))

    def test_c3_comments_continuation(self):
        for text, want in (("flask==2.0 # pinned for a reason\n", []),
                           ("# flask\n   # numpy>=1\n", []),
                           ("foo==1.0#egg\n", [(1, "PN3", "?")]),
                           ("foo\\\n==1.0\n", []),
                           ("a==1\nfoo \\\n  >= 2\n", [(2, "PN1", "foo")]),
                           ("x==1 \\\n# comment\ny\n", [(3, "PN1", "y")]),
                           ("a==1\\\n\nb\n", [(3, "PN1", "b")]),
                           ("\tsix>=1\t# old\n", [(1, "PN1", "six")])):
            self.assertEqual(scan(text), want, repr(text))


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {
    "pinlint/scan.py": r'''"""Problems in requirements files. See docs/pin_rules.md."""

from __future__ import annotations

import re
from typing import NamedTuple

NAME = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
REQ = re.compile(rf"({NAME})\s*(\[[^\]]*\])?\s*(.*)", re.S)
EXTRAS = re.compile(rf"\[\s*(?:{NAME}(?:\s*,\s*{NAME})*)?\s*\]")
VERSION = r"\d+(?:\.\d+)*(?:(?:a|b|rc)\d+)?(?:\.post\d+)?(?:\.dev\d+)?"
CLAUSE = re.compile(rf"\s*(===|==|!=|~=|>=|<=|<|>)\s*({VERSION})(\.\*)?\s*")
HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}")
COMMENT = re.compile(r"(^|\s)#.*", re.S)


class PinIssue(NamedTuple):
    line: int
    code: str
    name: str


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def logical_lines(text: str) -> list[tuple[int, str]]:
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        start, buf = i, lines[i]
        while buf.endswith("\\"):
            buf = buf[:-1]
            i += 1
            if i >= len(lines):
                break
            buf += lines[i]
        out.append((start + 1, buf))
        i += 1
    return out


def _pinned(spec: str) -> bool | None:
    """True when pinned, False when not, None when unreadable."""
    if not spec:
        return False
    clauses = [CLAUSE.fullmatch(c) for c in spec.split(",")]
    if not all(clauses):
        return None
    for m in clauses:
        if m.group(3) and m.group(1) not in ("==", "!="):
            return None
    return len(clauses) == 1 and clauses[0].group(1) == "==" and not clauses[0].group(3)


def scan_requirements(text: str) -> list[PinIssue]:
    reqs = []
    for line, raw in logical_lines(text):
        body = COMMENT.sub("", raw).strip()
        if not body or body.startswith("-"):
            continue
        parts = re.split(r"\s+(?=--)", body)
        req, options = parts[0].split(";", 1)[0].strip(), parts[1:]
        m = REQ.fullmatch(req)
        pinned = None
        if m and (m.group(2) is None or EXTRAS.fullmatch(m.group(2))):
            pinned = _pinned(m.group(3).strip())
        if pinned is None:
            reqs.append((line, None, None, options))
        else:
            reqs.append((line, normalize(m.group(1)), pinned, options))
    hash_mode = any(o.startswith("--hash") for _, name, _, opts in reqs if name for o in opts)
    out, seen = [], set()
    for line, name, pinned, options in reqs:
        if name is None:
            out.append(PinIssue(line, "PN3", "?"))
            continue
        if not pinned:
            out.append(PinIssue(line, "PN1", name))
        if name in seen:
            out.append(PinIssue(line, "PN2", name))
        seen.add(name)
        if any(not HASH.fullmatch(o) for o in options):
            out.append(PinIssue(line, "PN4", name))
        if hash_mode and not any(o.startswith("--hash") for o in options):
            out.append(PinIssue(line, "PN5", name))
    return sorted(out)
''',
    "pinlint/cli.py": '''"""Command line: ``python -m pinlint <file> [<file> ...] [--skip CODE]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .scan import scan_requirements


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pinlint")
    p.add_argument("paths", nargs="+")
    p.add_argument("--skip")
    a = p.parse_args(sys.argv[1:] if argv is None else argv)
    missing = [x for x in a.paths if not Path(x).is_file()]
    if missing:
        print(f"no such file: {missing[0]}", file=sys.stderr)
        return 2
    printed = 0
    for path in a.paths:
        for line, code, name in scan_requirements(Path(path).read_text(encoding="utf-8")):
            if code != a.skip:
                print(f"{code} {path}:{line} {name}")
                printed += 1
    return 3 if printed else 0


if __name__ == "__main__":
    sys.exit(main())
''',
}
