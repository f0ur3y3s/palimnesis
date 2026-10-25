"""dev-t2: URL slugs with transliteration and length limits (development task, D44.5)."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, SLUG_WORDS, catalog_suite, long_doc

ID = "dev-t2"
SET = "development"
TITLE = "slugify: ASCII slugs, transliteration, length limit, unique slugs"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "slugs contain only lowercase ASCII letters, digits and single hyphens, with no "
          "hyphen at either end",
    "C2": "never cut a word in half when shortening; drop whole words from the end",
    "C3": "standard library only (no unidecode or other packages)",
}
TRAP = ("already tried unicodedata.normalize('NFKD') then encode('ascii', 'ignore'); it failed "
        "because ß, Ø, Æ and Ł vanished instead of becoming ss, o, ae and l")


def collapse_ws(s: str) -> str:
    return " ".join(s.split())


LEGACY = '''"""Whitespace helpers (shared with the CMS; do not change)."""


def collapse_ws(s: str) -> str:
    return " ".join(s.split())
'''

STUB = '''"""URL slugs for article titles. See docs/slug_rules.md."""

from __future__ import annotations


def slugify(title: str, max_len: int = 60) -> str:
    """An article title -> its URL slug."""
    raise NotImplementedError


def unique_slug(title: str, existing: set[str], max_len: int = 60) -> str:
    """``slugify(title)``, or with ``-2``, ``-3``, ... appended until it is not in ``existing``."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from slugkit.slug import slugify  # noqa: E402


class SlugTests(unittest.TestCase):
    def test_ascii_title(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")

    def test_collapses_separators(self):
        self.assertEqual(slugify("  A -- B  "), "a-b")

    def test_transliteration(self):
        self.assertEqual(slugify("Straße in Łódź"), "strasse-in-lodz")
'''

DOC_INTRO = [
    "Rules for article URL slugs in the CMS.",
    "",
    "## Characters",
    "",
    "- Letters are lowercased. Accented Latin letters lose their accents (é to e, ñ to n,",
    "  ü to u). Letters without a decomposition are spelled out: ß to ss, æ to ae, œ to oe,",
    "  ø to o, ł to l, đ to d, þ to th.",
    "- Every run of other characters (spaces, punctuation, symbols) becomes one hyphen.",
    "- Characters that are not Latin letters or digits are dropped.",
    "",
    "## Length",
    "",
    "- The default maximum length is 60 characters.",
    "",
    "## Collisions",
    "",
    "- When a slug is taken, `-2` is appended, then `-3`, and so on.",
]


def _record(rnd: random.Random, i: int) -> str:
    title = " ".join(rnd.choice(SLUG_WORDS).title() for _ in range(rnd.randint(2, 5)))
    return f"title: {title} | slug: {'-'.join(title.lower().split())}"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        raw = rnd.choice([f"  {rnd.choice(SLUG_WORDS)}   {rnd.choice(SLUG_WORDS)} ",
                          f"{rnd.choice(SLUG_WORDS)}\\t{rnd.choice(SLUG_WORDS)}",
                          f"\\n{rnd.choice(SLUG_WORDS)} \\n {rnd.choice(SLUG_WORDS)}",
                          f"{rnd.choice(SLUG_WORDS)}"])
        slug = rnd.choice(["leading_and_trailing", "tab_separated", "newline_mixed", "single_word",
                           "cms_headline_entry"])
        raw_value = raw.encode().decode("unicode_escape")
        cases.append((slug, repr(raw_value), repr(collapse_ws(raw_value))))
    return {
        "slugkit/__init__.py": '"""Slugs for CMS articles."""\n',
        "slugkit/legacy.py": LEGACY,
        "slugkit/slug.py": STUB,
        "docs/slug_rules.md": long_doc(rnd, "Slug rules", DOC_INTRO, _record),
        "tests/test_slug.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("slugkit.legacy", "collapse_ws",
                                                      "CollapseWsCatalogTests", cases),
    }


TURNS = [
    "We're building `slugkit`, which turns article titles into URL slugs for the CMS. Rules for "
    "this work: (1) a slug contains only lowercase ASCII letters, digits and single hyphens, "
    "with no hyphen at either end; (2) when a slug has to be shortened, never cut a word in "
    "half: drop whole words from the end; (3) standard library only, so no unidecode or any "
    "other package. Also, we already tried unicodedata.normalize('NFKD') followed by "
    "encode('ascii', 'ignore'), and it failed because ß, Ø, Æ and Ł vanished instead of "
    "becoming ss, o, ae and l. For now just read slugkit/slug.py and tell me what is left to "
    "implement; don't change anything yet. " + NO_QUESTIONS,
    "Read docs/slug_rules.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize the rules in five bullet points.",
    "Implement `slugify` for plain ASCII titles: lowercase, and every run of other characters "
    "becomes one hyphen. Ignore max_len for now. Run `python -m unittest tests.test_slug -v`; "
    "the transliteration test may still fail.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which ones failed.",
    "Now make `slugify` handle accented and other Latin letters as docs/slug_rules.md says: "
    "café gives cafe, Straße gives strasse, Øresund gives oresund, Æther gives aether, Łódź "
    "gives lodz. Then run `python -m unittest tests.test_slug -v`.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the counts.",
    "Add the `max_len` limit to `slugify` (default 60), and implement `unique_slug(title, "
    "existing, max_len=60)`, which appends -2, -3 and so on until the slug is not in "
    "`existing`, with the result still within max_len. Add tests for both to "
    "tests/test_slug.py and run that module.",
    "Last step: run `python -m unittest discover -s tests` once more and summarize what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from slugkit.slug import slugify, unique_slug  # noqa: E402

SOURCE = (ROOT / "slugkit" / "slug.py").read_text(encoding="utf-8")
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
TITLES = ["Hello, World!", "  A -- B  ", "Straße in Łódź", "Øresund Bridge", "Æther & Œuvre",
          "Crème brûlée: 10 tips", "Đà Nẵng travel", "Þorsteinn's saga", "C++ / C# --- 2026",
          "ÜBER Café", "naïve façade", "---", "Mañana!!", "x" * 80]


class HiddenTests(unittest.TestCase):
    def test_f_ascii(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")
        self.assertEqual(slugify("C++ / C# --- 2026"), "c-c-2026")

    def test_f_transliteration(self):
        for title, want in (("Straße in Łódź", "strasse-in-lodz"), ("Øresund", "oresund"),
                            ("Æther", "aether"), ("café", "cafe"), ("Œuvre", "oeuvre"),
                            ("Mañana", "manana"), ("Đà", "da"), ("Þing", "thing"), ("Über", "uber")):
            self.assertEqual(slugify(title), want, title)

    def test_f_max_len(self):
        s = slugify("alpha bravo cedar delta ember", max_len=17)
        self.assertEqual(s, "alpha-bravo-cedar")
        self.assertLessEqual(len(slugify(" ".join(["word"] * 40))), 60)

    def test_f_unique(self):
        self.assertEqual(unique_slug("Hello World", set()), "hello-world")
        self.assertEqual(unique_slug("Hello World", {"hello-world"}), "hello-world-2")
        self.assertEqual(unique_slug("Hello World", {"hello-world", "hello-world-2"}), "hello-world-3")
        s = unique_slug("alpha bravo cedar", {"alpha-bravo-cedar"}, max_len=17)
        self.assertLessEqual(len(s), 17)
        self.assertTrue(s.endswith("-2"))

    def test_c1_charset(self):
        for t in TITLES:
            s = slugify(t)
            if s:
                self.assertRegex(s, SLUG, t)

    def test_c2_whole_words(self):
        for n in range(12, 40):
            s = slugify("alpha bravo cedar delta ember fjord", max_len=n)
            self.assertLessEqual(len(s), n)
            for part in s.split("-"):
                self.assertIn(part, {"alpha", "bravo", "cedar", "delta", "ember", "fjord"})

    def test_c3_stdlib_only(self):
        for node in ast.walk(ast.parse(SOURCE)):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            for n in names:
                self.assertIn(n.split(".")[0], sys.stdlib_module_names, n)


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"slugkit/slug.py": '''"""URL slugs for article titles. See docs/slug_rules.md."""

from __future__ import annotations

import re
import unicodedata

SPELLED = {"ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "ł": "l", "đ": "d", "þ": "th"}


def _ascii(title: str) -> str:
    out = []
    for ch in title.lower():
        ch = SPELLED.get(ch, ch)
        out.append(unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode())
    return "".join(out)


def slugify(title: str, max_len: int = 60) -> str:
    words = [w for w in re.split(r"[^a-z0-9]+", _ascii(title)) if w]
    out = []
    for w in words:
        if len("-".join(out + [w])) > max_len:
            break
        out.append(w)
    if not out and words:
        return words[0][:max_len]
    return "-".join(out)


def unique_slug(title: str, existing: set[str], max_len: int = 60) -> str:
    base = slugify(title, max_len)
    if base not in existing:
        return base
    n = 2
    while True:
        suffix = f"-{n}"
        candidate = slugify(title, max_len - len(suffix)) + suffix
        if candidate not in existing:
            return candidate
        n += 1
'''}
