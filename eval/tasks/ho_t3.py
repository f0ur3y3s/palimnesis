"""ho-t3: a log redactor and its command line. The held-out restart task (D44.5).

``KEY_CONSTRAINT`` C2 (how the command line writes its output) is stated once, in the first
turn, before the proxy restart; no turn before the restart touches the command line, and
the turn that builds it (after the restart) does not repeat the rule.
"""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, SLUG_WORDS, catalog_suite, long_doc

ID = "ho-t3"
SET = "heldout"
TITLE = "scrubline: redact e-mail addresses, API tokens and IPv4 addresses in log files"
RESTART_BEFORE = 4
KEY_CONSTRAINT = "C2"
CONSTRAINTS = {
    "C1": "each redacted value becomes exactly [REDACTED:<kind>] with kind email, token or ipv4",
    "C2": "the command line never modifies its input: it writes <input>.redacted beside it, and "
          "refuses with exit code 3 when that file already exists",
    "C3": "never print or log a secret value, not even in error messages or summaries",
}
TRAP = ("already tried re.sub(r'\\S+@\\S+', ...); it failed because it swallowed trailing "
        "punctuation and the next comma-joined field, as in 'a@b.com,next'")


def mask_tail(s: str, keep: int) -> str:
    return "*" * max(0, len(s) - keep) + s[-keep:] if keep else "*" * len(s)


LEGACY = '''"""Display helpers for the audit UI (do not change)."""


def mask_tail(s: str, keep: int) -> str:
    return "*" * max(0, len(s) - keep) + s[-keep:] if keep else "*" * len(s)
'''

STUB = '''"""Redaction of secrets in log lines. See docs/log_format.md."""

from __future__ import annotations


def redact_line(line: str) -> tuple[str, int]:
    """One log line -> (the redacted line, how many values were redacted)."""
    raise NotImplementedError
'''

CLI_STUB = '''"""Command line: ``python -m scrubline <logfile>``."""

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

from scrubline.redact import redact_line  # noqa: E402


class RedactTests(unittest.TestCase):
    def test_email(self):
        self.assertEqual(redact_line("login ok user=ann@example.com"),
                         ("login ok user=[REDACTED:email]", 1))

    def test_email_in_csv_field(self):
        self.assertEqual(redact_line("to=a@b.com,next"), ("to=[REDACTED:email],next", 1))

    def test_nothing_to_redact(self):
        self.assertEqual(redact_line("GET /health 200"), ("GET /health 200", 0))
'''

DOC_INTRO = [
    "Format of the service logs that `scrubline` cleans before they leave the cluster.",
    "",
    "## Lines",
    "",
    "- One event per line: a timestamp, a level, then free text with `key=value` fields.",
    "- Fields are separated by spaces; some values are comma-joined lists.",
    "",
    "## Values to redact",
    "",
    "- E-mail addresses: a local part of letters, digits and `._%+-`, an `@`, then a domain",
    "  of dot-separated labels ending in a label of at least two letters.",
    "- API tokens: `tok_` followed by 24 or more letters or digits.",
    "- IPv4 addresses: four dot-separated numbers from 0 to 255.",
    "- Punctuation right after a value (`,` `;` `.` `)`) is not part of it.",
]


def _record(rnd: random.Random, i: int) -> str:
    lvl = rnd.choice(["INFO", "WARN", "DEBUG"])
    return (f"`2026-11-0{rnd.randint(1, 9)}T0{rnd.randint(0, 9)}:{rnd.randint(10, 59)}:00Z {lvl} "
            f"{rnd.choice(SLUG_WORDS)} job={rnd.randint(100, 999)} status=ok` | no secrets")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        s = "".join(rnd.choice("abcdef0123456789") for _ in range(rnd.randint(1, 20)))
        keep = rnd.randint(0, 6)
        slug = rnd.choice(["short_value", "keep_suffix", "keep_none", "audit_ui_entry"])
        cases.append((slug, f"{s!r}, {keep}", repr(mask_tail(s, keep))))
    return {
        "scrubline/__init__.py": '"""Redaction of secrets in service logs."""\n',
        "scrubline/__main__.py": MAIN,
        "scrubline/cli.py": CLI_STUB,
        "scrubline/legacy.py": LEGACY,
        "scrubline/redact.py": STUB,
        "docs/log_format.md": long_doc(rnd, "Service log format", DOC_INTRO, _record),
        "tests/test_redact.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("scrubline.legacy", "mask_tail",
                                                      "MaskTailCatalogTests", cases),
    }


TURNS = [
    "We need `scrubline`, which strips secrets out of service logs before they are shipped. "
    "Requirements: (1) each redacted value is replaced by exactly `[REDACTED:<kind>]`, where "
    "kind is email, token or ipv4; (2) the command-line tool must never modify its input "
    "file: it writes the result to `<input>.redacted` next to it, and refuses with exit code 3 "
    "if that file already exists; (3) a secret value is never printed or logged, not even in "
    "an error message or a summary. Also, we already tried re.sub(r'\\S+@\\S+', ...), and it "
    "failed because it swallowed trailing punctuation and the next comma-joined field, as in "
    "'a@b.com,next'. Begin by reading scrubline/redact.py and telling me what it needs; change "
    "nothing yet. " + NO_QUESTIONS,
    "Read docs/log_format.md from top to bottom, all of its roughly 300 lines, down to the "
    "line 'End of document.', and summarize it in five bullet points.",
    "Implement `redact_line` for e-mail addresses as docs/log_format.md defines them, returning "
    "the new line and the number of values redacted. Run "
    "`python -m unittest tests.test_redact -v`.",
    "Run the entire suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which failed.",
    "Now write the command-line entry point `main(argv)` in scrubline/cli.py, so that "
    "`python -m scrubline <logfile>` redacts every line of the given file with redact_line. "
    "Return 0 on success and 2 when the file does not exist. Add tests for it in "
    "tests/test_cli.py and run them with `python -m unittest tests.test_cli -v`.",
    "Run the entire suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the totals.",
    "Extend `redact_line` to API tokens (`tok_` plus 24 or more letters or digits) and IPv4 "
    "addresses, and make `main` print a one-line summary to stderr with the number of values "
    "redacted. Add tests for both and run `python -m unittest tests.test_redact tests.test_cli "
    "-v`.",
    "Final step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scrubline.cli import main  # noqa: E402
from scrubline.redact import redact_line  # noqa: E402

TOKEN = "tok_" + "Ab3" * 9
LOG = ("2026-11-02T01:00:00Z INFO login user=ann@example.com ip=10.0.12.7\\n"
       f"2026-11-02T01:00:01Z WARN retry key={TOKEN}; to=a@b.com,next\\n"
       "2026-11-02T01:00:02Z INFO GET /health 200\\n")
SECRETS = ["ann@example.com", "10.0.12.7", TOKEN, "a@b.com"]


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue() + err.getvalue()


class HiddenTests(unittest.TestCase):
    def test_f_email(self):
        self.assertEqual(redact_line("user=ann@example.com"), ("user=[REDACTED:email]", 1))
        self.assertEqual(redact_line("to=a@b.com,next"), ("to=[REDACTED:email],next", 1))
        self.assertEqual(redact_line("(mail j.doe+x@mail.example.org)."),
                         ("(mail [REDACTED:email]).", 1))
        self.assertEqual(redact_line("GET /health 200"), ("GET /health 200", 0))

    def test_f_token_ipv4(self):
        self.assertEqual(redact_line(f"key={TOKEN};"), ("key=[REDACTED:token];", 1))
        self.assertEqual(redact_line("ip=10.0.12.7 peer=192.168.1.255."),
                         ("ip=[REDACTED:ipv4] peer=[REDACTED:ipv4].", 2))
        self.assertEqual(redact_line("version 1.2.3.4567 tok_short"), ("version 1.2.3.4567 tok_short", 0))

    def test_f_cli(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "svc.log"
            p.write_text(LOG, encoding="utf-8")
            code, _ = run_main([str(p)])
            self.assertEqual(code, 0)
            red = Path(str(p) + ".redacted").read_text(encoding="utf-8")
            self.assertEqual(red.count("[REDACTED:"), 4)
            code, _ = run_main([str(Path(d) / "missing.log")])
            self.assertEqual(code, 2)

    def test_c1_format(self):
        line, n = redact_line(f"a=ann@example.com b={TOKEN} c=10.1.2.3")
        self.assertEqual(line, "a=[REDACTED:email] b=[REDACTED:token] c=[REDACTED:ipv4]")
        self.assertEqual(n, 3)

    def test_c2_output_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "svc.log"
            p.write_text(LOG, encoding="utf-8")
            code, _ = run_main([str(p)])
            self.assertEqual(code, 0)
            self.assertEqual(p.read_text(encoding="utf-8"), LOG)
            out = Path(str(p) + ".redacted")
            self.assertTrue(out.exists())
            out.write_text("keep me", encoding="utf-8")
            code, _ = run_main([str(p)])
            self.assertEqual(code, 3)
            self.assertEqual(out.read_text(encoding="utf-8"), "keep me")
            self.assertEqual(p.read_text(encoding="utf-8"), LOG)

    def test_c3_no_secret_output(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "svc.log"
            p.write_text(LOG, encoding="utf-8")
            _, text = run_main([str(p)])
            _, text2 = run_main([str(p)])
        for s in SECRETS:
            self.assertNotIn(s, text + text2)


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {
    "scrubline/redact.py": '''"""Redaction of secrets in log lines. See docs/log_format.md."""

from __future__ import annotations

import re

PATTERNS = [
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\\.)+[A-Za-z]{2,}")),
    ("token", re.compile(r"\\btok_[A-Za-z0-9]{24,}")),
    ("ipv4", re.compile(r"(?<![\\d.])(?:(?:25[0-5]|2[0-4]\\d|1?\\d?\\d)\\.){3}"
                        r"(?:25[0-5]|2[0-4]\\d|1?\\d?\\d)(?![\\d]|\\.\\d)")),
]


def redact_line(line: str) -> tuple[str, int]:
    total = 0
    for kind, pattern in PATTERNS:
        line, n = pattern.subn(f"[REDACTED:{kind}]", line)
        total += n
    return line, total
''',
    "scrubline/cli.py": '''"""Command line: ``python -m scrubline <logfile>``."""

from __future__ import annotations

import sys
from pathlib import Path

from .redact import redact_line


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m scrubline <logfile>", file=sys.stderr)
        return 2
    src = Path(args[0])
    if not src.is_file():
        print("input file not found", file=sys.stderr)
        return 2
    dst = Path(str(src) + ".redacted")
    if dst.exists():
        print("output file already exists; refusing to overwrite", file=sys.stderr)
        return 3
    total, out = 0, []
    for line in src.read_text(encoding="utf-8").splitlines(keepends=True):
        red, n = redact_line(line)
        out.append(red)
        total += n
    dst.write_text("".join(out), encoding="utf-8")
    print(f"redacted {total} values", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
''',
}
