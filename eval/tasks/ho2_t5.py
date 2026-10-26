"""ho2-t5: an ignore-pattern matcher and rule files (fresh held-out task, O-B1).

A1 categories: several distant facts needed together (turn 7's rule files need C2 and C3
from turn 1, the comment character decided in turn 5 and the anchoring, directory and
parent rules from the document read in turn 2); a vague "continue ... the way we settled";
a decision that overrides the document (turn 5's ';' comments against the document's
'#'); information needs that arise mid-task (``**`` in turn 5 from the document); an
oversized read; restart before turn 5.
"""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho2-t5"
SET = "heldout2"
TITLE = "ignorekit: glob-style ignore patterns with ** and ordered rule files"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "the matcher is hand-written: the package imports none of re, fnmatch, glob or "
          "pathlib",
    "C2": "paths are always '/'-separated; a backslash in a pattern makes the next character "
          "literal and is never a path separator",
    "C3": "in a rule list the last matching rule wins, and a rule starting with '!' "
          "re-includes the path",
}
TRAP = ("already tried fnmatch.fnmatch; it failed because its * matched across '/', so "
        "'src/*.py' matched 'src/a/b.py', and it has no ** at all")


def ext_of(name: str) -> str:
    base = name.rsplit("/", 1)[-1]
    i = base.rfind(".")
    return base[i + 1:] if i > 0 else ""


LEGACY = '''"""File-type column of the cleanup report (do not change)."""


def ext_of(name: str) -> str:
    base = name.rsplit("/", 1)[-1]
    i = base.rfind(".")
    return base[i + 1:] if i > 0 else ""
'''

STUB = '''"""Ignore patterns and rule files. See docs/ignore_patterns.md."""


def match(pattern, path):
    """Does the glob ``pattern`` match the whole '/'-separated ``path``?"""
    raise NotImplementedError


def load_rules(text):
    """The rules of a rule file, in order."""
    raise NotImplementedError


def is_ignored(path, rules, is_dir=False):
    """Is ``path`` ignored under ``rules``?"""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ignorekit.match import match  # noqa: E402


class MatchTests(unittest.TestCase):
    def test_star(self):
        self.assertTrue(match("*.py", "setup.py"))

    def test_star_stays_in_segment(self):
        self.assertFalse(match("src/*.py", "src/a/b.py"))
'''

DOC_INTRO = [
    "The pattern language of the cleanup tool's ignore files.",
    "",
    "## Paths and wildcards",
    "",
    "- Paths are relative and '/'-separated, with no leading '/'.",
    "- `*` matches any run of characters inside one path segment, including none; it never",
    "  matches '/'. `?` matches exactly one character other than '/'.",
    "- `[...]` matches one character from the set; ranges such as `a-z` are allowed and",
    "  `[!...]` negates the set. A `]` right after `[` or `[!` is literal, and a `[` without",
    "  a closing `]` is a literal `[`. A set never matches '/'.",
    "- A backslash makes the next character literal.",
    "- `**` as a whole segment: at the start (`**/x`) it matches in any directory, the top",
    "  included; at the end (`x/**`) it matches everything inside x, but not x itself; in the",
    "  middle (`a/**/b`) it matches zero or more directories. Any other `**` acts like `*`.",
    "",
    "## Rule files",
    "",
    "- One pattern per line; leading and trailing whitespace is ignored, and so are blank",
    "  lines. Lines starting with `#` are comments.",
    "- A leading `!` turns a rule into a re-include; write `\\!` for a pattern that starts",
    "  with a literal '!'.",
    "- A trailing `/` makes a rule match directories only.",
    "- A pattern with a '/' anywhere except at the end is anchored at the top (a leading '/'",
    "  is dropped). A pattern with no '/' matches a name at any depth.",
    "- A rule matches a path when it matches the path itself or any of its parent",
    "  directories; parents always count as directories. Unlike git, a later `!` rule can",
    "  re-include a file inside an ignored directory.",
]

PATTERNS = ["*.pyc", "build/", "dist/", "*.log", "!keep.log", "/coverage/*.html", "**/tmp/",
            "node_modules/", "*.swp", "docs/_build/", "**/*.bak", "cache/**", "?.tmp",
            "[Tt]humbs.db", "*.o", "/vendor/"]
PROJECTS = ["harrier", "pipit", "osprey", "linnet", "plover", "dunlin", "merlin", "shrike"]


def _record(rnd: random.Random, i: int) -> str:
    return (f"`{rnd.choice(PATTERNS)}` | seen in the {rnd.choice(PROJECTS)} repository, "
            f"line {rnd.randint(1, 40)}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        stem = rnd.choice(PROJECTS + [".env", ".gitkeep", "notes", "src/main", "a/b/c"])
        name = stem + rnd.choice(["", ".py", ".tar.gz", ".log", ".", ".md"])
        slug = rnd.choice(["plain_name", "nested_path", "dotfile", "report_column"])
        cases.append((slug, repr(name), repr(ext_of(name))))
    return {
        "ignorekit/__init__.py": '"""Ignore patterns for the cleanup tool."""\n',
        "ignorekit/legacy.py": LEGACY,
        "ignorekit/match.py": STUB,
        "docs/ignore_patterns.md": long_doc(rnd, "Ignore patterns", DOC_INTRO, _record),
        "tests/test_match.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("ignorekit.legacy", "ext_of",
                                                      "ExtOfCatalogTests", cases),
    }


TURNS = [
    "This session builds `ignorekit`, the pattern matcher behind our cleanup tool's ignore "
    "files. Rules: (1) the matcher is hand-written, so the package imports none of re, "
    "fnmatch, glob or pathlib; (2) paths are always '/'-separated, and a backslash in a "
    "pattern makes the next character literal and is never a path separator; (3) in a rule "
    "list the last matching rule wins, and a rule starting with '!' re-includes the path. We "
    "already tried fnmatch.fnmatch, and it failed because its * matched across '/', so "
    "'src/*.py' matched 'src/a/b.py', and it has no ** at all. To begin, read "
    "ignorekit/match.py and tell me what has to be written; do not edit yet. " + NO_QUESTIONS,
    "Read docs/ignore_patterns.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize the pattern language in five bullet points.",
    "Implement `match(pattern, path)` for `*`, `?`, character sets and backslash escapes, "
    "matching the whole path; leave `**` for later. Then run `python -m unittest "
    "tests.test_match -v`.",
    "Run all tests verbosely with `python -m unittest discover -s tests -v` and tell me how "
    "many ran and which failed.",
    "Add `**` to match, as the pattern document describes it. One decision for later, too: "
    "in our rule files a line starting with ';' is a comment, and '#' is not, because some "
    "of our file names start with '#'. Add tests for `**` and run `python -m unittest "
    "tests.test_match -v`.",
    "Run all tests verbosely again (`python -m unittest discover -s tests -v`) and report "
    "the totals.",
    "Continue: write `load_rules(text)` and `is_ignored(path, rules, is_dir=False)` so our "
    "rule files work the way we settled. Add tests in tests/test_rules.py and run `python -m "
    "unittest tests.test_rules -v`.",
    "Finally, run `python -m unittest discover -s tests` once more and list what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": r'''import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ignorekit.match import is_ignored, load_rules, match  # noqa: E402

PKG = ROOT / "ignorekit"
RULES = "\n".join([
    "; build outputs",
    "build/",
    "  *.log  ",
    "!keep.log",
    "",
    "/docs/*.html",
    "#notes.txt",
    "logs/**/*.tmp",
    "\\!important",
    ""])


class HiddenTests(unittest.TestCase):
    def test_f_match(self):
        for pattern, path, want in (("*.py", "a.py", True), ("*.py", "src/a.py", False),
                                    ("src/?.py", "src/a.py", True), ("src/?.py", "src/ab.py", False),
                                    ("[ab]x", "bx", True), ("[!ab]x", "cx", True),
                                    ("[!ab]x", "ax", False), ("[a-c]", "b", True), ("[a-c]", "d", False),
                                    ("a*", "a/b", False), ("a?b", "a/b", False),
                                    ("src/*.py", "src/a/b.py", False), ("*", "anything", True),
                                    ("[]]x", "]x", True), ("a[b", "a[b", True)):
            self.assertEqual(match(pattern, path), want, (pattern, path))

    def test_f_doublestar(self):
        for pattern, path, want in (("**/x.txt", "x.txt", True), ("**/x.txt", "a/b/x.txt", True),
                                    ("a/**", "a/b/c", True), ("a/**", "a", False),
                                    ("a/**/b", "a/b", True), ("a/**/b", "a/x/y/b", True),
                                    ("a/**/b", "a/xb", False), ("a**b", "axxb", True),
                                    ("a**b", "a/b", False), ("**/*.tmp", "q/r.tmp", True)):
            self.assertEqual(match(pattern, path), want, (pattern, path))

    def test_f_rules(self):
        rules = load_rules(RULES)
        for path, is_dir, want in (("build/a.o", False, True), ("build", True, True),
                                   ("build", False, False), ("src/build/x", False, True),
                                   ("x.log", False, True), ("a/b/x.log", False, True),
                                   ("keep.log", False, False), ("a/keep.log", False, False),
                                   ("docs/a.html", False, True), ("src/docs/a.html", False, False),
                                   ("docs/sub/a.html", False, False), ("#notes.txt", False, True),
                                   ("logs/a/b/c.tmp", False, True), ("logs/c.tmp", False, True),
                                   ("x/logs/c.tmp", False, False), ("!important", False, True),
                                   ("src/main.py", False, False), ("; build outputs", False, False)):
            self.assertEqual(is_ignored(path, rules, is_dir=is_dir), want, (path, is_dir))

    def test_c1_hand_written(self):
        banned = {"re", "fnmatch", "glob", "pathlib"}
        for path in PKG.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    mods = [node.module or ""]
                for m in mods:
                    self.assertNotIn(m.split(".")[0], banned, f"{path.name} imports {m}")

    def test_c2_escapes(self):
        for pattern, path, want in (("a\\*b", "a*b", True), ("a\\*b", "axb", False),
                                    ("a\\?", "a?", True), ("a\\?", "ab", False),
                                    ("a\\b", "ab", True), ("a\\b", "a/b", False),
                                    ("a/b", "a\\b", False), ("\\[x]", "[x]", True)):
            self.assertEqual(match(pattern, path), want, (pattern, path))

    def test_c3_order(self):
        self.assertFalse(is_ignored("a.txt", load_rules("*.txt\n!a.txt\n")))
        self.assertTrue(is_ignored("a.txt", load_rules("!a.txt\n*.txt\n")))
        self.assertTrue(is_ignored("b.txt", load_rules("*.txt\n!a.txt\n")))
        rules = load_rules("build/\n!build/keep.txt\n")
        self.assertFalse(is_ignored("build/keep.txt", rules))
        self.assertTrue(is_ignored("build/x.o", rules))
        self.assertFalse(is_ignored("other.txt", load_rules("!other.txt\n")))


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"ignorekit/match.py": r'''"""Ignore patterns and rule files. See docs/ignore_patterns.md."""

DSTAR = object()


def _split(pattern):
    """Unescaped '/' splits segments; escapes stay in the segment text."""
    segs, cur, i = [], "", 0
    while i < len(pattern):
        c = pattern[i]
        if c == "\\" and i + 1 < len(pattern):
            cur += pattern[i:i + 2]
            i += 2
            continue
        if c == "/":
            segs.append(cur)
            cur = ""
        else:
            cur += c
        i += 1
    segs.append(cur)
    return [DSTAR if s == "**" else _tokens(s) for s in segs]


def _tokens(seg):
    out, i = [], 0
    while i < len(seg):
        c = seg[i]
        if c == "\\" and i + 1 < len(seg):
            out.append(("lit", seg[i + 1]))
            i += 2
        elif c == "*":
            while i < len(seg) and seg[i] == "*":
                i += 1
            out.append(("star",))
        elif c == "?":
            out.append(("one",))
            i += 1
        elif c == "[":
            j = i + 1
            neg = j < len(seg) and seg[j] == "!"
            if neg:
                j += 1
            start = j
            items = []
            while j < len(seg) and (seg[j] != "]" or j == start):
                if seg[j] == "\\" and j + 1 < len(seg):
                    j += 1
                if j + 2 < len(seg) and seg[j + 1] == "-" and seg[j + 2] != "]":
                    items.append((seg[j], seg[j + 2]))
                    j += 3
                else:
                    items.append((seg[j], seg[j]))
                    j += 1
            if j >= len(seg):
                out.append(("lit", "["))
                i += 1
            else:
                out.append(("set", neg, items))
                i = j + 1
        else:
            out.append(("lit", c))
            i += 1
    return out


def _seg_match(toks, s):
    memo = {}

    def go(i, j):
        key = (i, j)
        if key in memo:
            return memo[key]
        if i == len(toks):
            r = j == len(s)
        else:
            t = toks[i]
            if t[0] == "star":
                r = go(i + 1, j) or (j < len(s) and go(i, j + 1))
            elif j >= len(s):
                r = False
            elif t[0] == "lit":
                r = s[j] == t[1] and go(i + 1, j + 1)
            elif t[0] == "one":
                r = go(i + 1, j + 1)
            else:
                hit = any(lo <= s[j] <= hi for lo, hi in t[2])
                r = hit != t[1] and go(i + 1, j + 1)
        memo[key] = r
        return r

    return go(0, 0)


def _match_segs(pat, segs):
    def go(i, j):
        if i == len(pat):
            return j == len(segs)
        if pat[i] is DSTAR:
            if i == len(pat) - 1:
                return j < len(segs)
            return any(go(i + 1, k) for k in range(j, len(segs) + 1))
        return j < len(segs) and _seg_match(pat[i], segs[j]) and go(i + 1, j + 1)

    return go(0, 0)


def match(pattern, path):
    return _match_segs(_split(pattern), path.split("/"))


def _has_slash(pattern):
    i = 0
    while i < len(pattern):
        if pattern[i] == "\\":
            i += 2
            continue
        if pattern[i] == "/":
            return True
        i += 1
    return False


def load_rules(text):
    rules = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        negate = line.startswith("!")
        if negate:
            line = line[1:]
        dir_only = line.endswith("/") and not line.endswith("\\/")
        if dir_only:
            line = line[:-1]
        anchored = _has_slash(line)
        if line.startswith("/"):
            line = line[1:]
        rules.append({"negate": negate, "dir_only": dir_only, "anchored": anchored,
                      "pattern": _split(line)})
    return rules


def _rule_matches(rule, segs, is_dir):
    for k in range(1, len(segs) + 1):
        cand_dir = k < len(segs) or is_dir
        if rule["dir_only"] and not cand_dir:
            continue
        if rule["anchored"]:
            if _match_segs(rule["pattern"], segs[:k]):
                return True
        elif _match_segs(rule["pattern"], segs[k - 1:k]):
            return True
    return False


def is_ignored(path, rules, is_dir=False):
    segs = path.split("/")
    ignored = False
    for rule in rules:
        if _rule_matches(rule, segs, is_dir):
            ignored = not rule["negate"]
    return ignored
'''}
