"""ho4-t5: a hand-written JSON Pointer resolver, JSON Patch applier and patch generator
(fourth held-out task set; the hardest of the five, as ho3-t5 was in its set).

A1 categories: several distant facts needed together (turn 7's patch generator needs C2
and C3 from turn 1, the add-onto-an-existing-member decision from turn 5, and the
generated-patch rule, the escaping rule and the JSON equality rule from the document read
in turn 2); a vague "continue ... the way we settled"; a decision that overrides the
document (turn 5's "add never replaces an existing member" against the document's add,
which replaces it, and which the visible test still encodes); information needs that arise
mid-task (move, copy and test in turn 5, from the document); an oversized read; restart
before turn 5.
"""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho4-t5"
SET = "heldout4"
TITLE = "jpatch: resolve JSON pointers, apply JSON patches all or nothing, generate patches"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "written by hand: the package imports none of jsonpatch, jsonpointer or deepdiff",
    "C2": "apply_patch never changes the document or the patch it is given, applies a patch "
          "all or nothing, and returns a document that shares no list or dict with either",
    "C3": "every failure raises PatchError from jpatch/errors.py with .index set to the "
          "0-based position of the failing operation in the patch, or None when the failure "
          "is not in an operation (resolve_pointer, or a patch that is not a list)",
}
TRAP = ("already tried splitting the pointer on '/' and indexing straight into the data; it "
        "failed because '~1' and '~0' were left encoded, so '/a~1b' looked for the wrong key, "
        "and '-' on an array raised an error instead of meaning the end")
DECISION = "add onto an existing object member is an error (turn 5, overrides the document)"


def json_kind(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise TypeError(type(value).__name__)


LEGACY = '''"""JSON type names for the audit log (do not change)."""


def json_kind(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise TypeError(type(value).__name__)
'''

ERRORS = '''"""Errors."""


class PatchError(ValueError):
    """A pointer or patch that cannot be applied. ``index`` is the failing operation."""

    def __init__(self, index, message):
        super().__init__(f"operation {index}: {message}")
        self.index = index
'''

STUB = '''"""JSON Pointer and JSON Patch. See docs/patch_rules.md."""

from .errors import PatchError  # noqa: F401


def resolve_pointer(doc, pointer):
    """The value ``pointer`` refers to in ``doc``."""
    raise NotImplementedError


def apply_patch(doc, patch):
    """A new document: ``doc`` with ``patch`` applied."""
    raise NotImplementedError


def make_patch(old, new):
    """A patch that turns ``old`` into ``new``."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jpatch.patch import apply_patch, resolve_pointer  # noqa: E402


class PatchTests(unittest.TestCase):
    def test_pointer(self):
        self.assertEqual(resolve_pointer({"a": [1, 2]}, "/a/1"), 2)

    def test_add_replaces_member(self):
        self.assertEqual(apply_patch({"a": 1}, [{"op": "add", "path": "/a", "value": 2}]),
                         {"a": 2})
'''

DOC_INTRO = [
    "How the config service reads JSON pointers and applies JSON patches (after RFC 6901",
    "and RFC 6902).",
    "",
    "## Pointers",
    "",
    "- The pointer `\"\"` is the whole document. Any other pointer starts with `/` and is a",
    "  list of reference tokens separated by `/`; a pointer that does not start with `/` is",
    "  invalid.",
    "- In a token, `~1` stands for `/` and `~0` for `~`. Decode `~1` first, then `~0`, so",
    "  `~01` is the text `~1`. A `~` followed by anything else is invalid.",
    "- On an object, a token is a member name, compared exactly. On an array it is an index:",
    "  `0`, or digits without a leading zero. `-` on an array means the position after the",
    "  last element; it may only be the target of an add. A token on anything else, a",
    "  missing member and an index past the end are errors.",
    "",
    "## Operations",
    "",
    "- A patch is a list of operations, applied in order; each is an object with `op` and",
    "  `path`, plus `value` (add, replace, test) or `from` (move, copy). A missing member or",
    "  an unknown op is an error.",
    "- add: on an array, inserts the value at the index (`-` appends). On an object, adds the",
    "  member, replacing it if it already exists. The parent must exist. Path `\"\"`",
    "  replaces the whole document.",
    "- remove: removes the target, which must exist. Removing `\"\"` is an error.",
    "- replace: replaces the target, which must exist. Path `\"\"` replaces the whole",
    "  document.",
    "- move: the same as a remove at `from` followed by an add at `path`. `from` must not be",
    "  a proper prefix of `path` (a value cannot move into its own child); a move onto",
    "  itself changes nothing.",
    "- copy: the same as an add at `path` of the value at `from`.",
    "- test: succeeds when the value at `path` equals `value` under JSON equality; fails",
    "  otherwise.",
    "- JSON equality: same JSON type and same value. Numbers compare by value (`1` equals",
    "  `1.0`), but `true` is a boolean and never equals `1`. Objects are equal when they have",
    "  the same members with equal values, in any order; arrays element by element.",
    "- A patch applies all or nothing: if any operation fails, the patch fails and the",
    "  document is as it was.",
    "",
    "## Generated patches",
    "",
    "- Patches our tools generate use only add, remove and replace, never move, copy or test.",
    "  Member names in generated paths are escaped (`/` as `~1`, `~` as `~0`).",
    "",
    "## Retired: merge patches",
    "",
    "- The 2021 service accepted merge patches (RFC 7396), where `null` deleted a member.",
    "  Nothing reads them now.",
]

POINTERS = ["/a~1b", "/m~0n", "/items/-", "/items/0", "", "/", "/x/y/3", "/~01"]
SERVICES = ["billing", "edge", "mailer", "search", "uploads", "metrics", "auth", "jobs"]


def _record(rnd: random.Random, i: int) -> str:
    return (f"`{rnd.choice(POINTERS)}` | {rnd.choice(['add', 'remove', 'replace', 'move', 'copy', 'test'])} "
            f"in the {rnd.choice(SERVICES)} config, revision {rnd.randint(1, 900)}")


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        value = rnd.choice([None, True, False, rnd.randint(-99, 99), rnd.uniform(-9, 9),
                            rnd.choice(SERVICES), [rnd.randint(0, 9)], {"k": rnd.randint(0, 9)}])
        slug = rnd.choice(["scalar_value", "container_value", "audit_entry", "edge_case"])
        cases.append((slug, repr(value), repr(json_kind(value))))
    return {
        "jpatch/__init__.py": '"""JSON pointers and patches for the config service."""\n',
        "jpatch/errors.py": ERRORS,
        "jpatch/legacy.py": LEGACY,
        "jpatch/patch.py": STUB,
        "docs/patch_rules.md": long_doc(rnd, "Pointers and patches in the config service",
                                        DOC_INTRO, _record),
        "tests/test_patch.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("jpatch.legacy", "json_kind",
                                                      "JsonKindCatalogTests", cases),
    }


TURNS = [
    "This session builds `jpatch`, the JSON pointer and JSON patch code of our config "
    "service. Rules: (1) it is written by hand, so the package imports none of jsonpatch, "
    "jsonpointer or deepdiff; (2) apply_patch never changes the document or the patch it is "
    "given, applies a patch all or nothing, and returns a document that shares no list or "
    "dict with either of them; (3) every failure raises PatchError from jpatch/errors.py with "
    "`.index` set to the 0-based position of the failing operation in the patch, or None "
    "when the failure is not in an operation (resolve_pointer, or a patch that is not a "
    "list). We already tried splitting the pointer on '/' and indexing straight into the "
    "data, and it failed because '~1' and '~0' were left encoded, so '/a~1b' looked for the "
    "wrong key, and '-' on an array raised an error instead of meaning the end. To begin, "
    "read jpatch/patch.py and jpatch/errors.py and tell me what has to be written; do not "
    "edit yet. " + NO_QUESTIONS,
    "Read docs/patch_rules.md completely, all of its roughly 300 lines, down to the line "
    "'End of document.'. Then summarize its rules in five bullet points.",
    "Implement `resolve_pointer(doc, pointer)` and `apply_patch(doc, patch)` for the add, "
    "remove and replace operations; leave the others for later. Then run `python -m unittest "
    "tests.test_patch -v`.",
    "Run all tests verbosely with `python -m unittest discover -s tests -v` and tell me how "
    "many ran and which failed.",
    "Add the move, copy and test operations to apply_patch, as the patch rules document "
    "describes them. One decision overrides the document: in our service, add onto an "
    "object member that already exists is an error, never a replacement; replace is the "
    "only way to change an existing member. Update the tests to match and run `python -m "
    "unittest tests.test_patch -v`.",
    "Run all tests verbosely again (`python -m unittest discover -s tests -v`) and report "
    "the totals.",
    "Continue: write `make_patch(old, new)`, which returns a patch that turns old into new "
    "when given to apply_patch, so our patch tooling works the way we settled. Add tests in "
    "tests/test_make.py and run `python -m unittest tests.test_make -v`.",
    "Finally, run `python -m unittest discover -s tests` once more and list what you "
    "changed.",
]

HIDDEN = {"_check/test_hidden.py": r'''import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jpatch.errors import PatchError  # noqa: E402
from jpatch.patch import apply_patch, make_patch, resolve_pointer  # noqa: E402

PKG = ROOT / "jpatch"
RFC = {"foo": ["bar", "baz"], "": 0, "a/b": 1, "c%d": 2, "e^f": 3, "g|h": 4, "i\\j": 5,
       "k\"l": 6, " ": 7, "m~n": 8}


def kind(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    return type(v).__name__


def same(a, b):
    if kind(a) != kind(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


def containers(v):
    if isinstance(v, (dict, list)):
        yield v
        for x in (v.values() if isinstance(v, dict) else v):
            yield from containers(x)


def frozen(v):
    return json.dumps(v, sort_keys=True)


class HiddenTests(unittest.TestCase):
    def apply(self, doc, patch, want):
        got = apply_patch(doc, patch)
        self.assertTrue(same(got, want), f"{got!r} != {want!r}")

    def test_f_pointer(self):
        for ptr, want in (("", RFC), ("/foo", ["bar", "baz"]), ("/foo/0", "bar"), ("/", 0),
                          ("/a~1b", 1), ("/c%d", 2), ("/e^f", 3), ("/g|h", 4), ("/i\\j", 5),
                          ("/k\"l", 6), ("/ ", 7), ("/m~0n", 8)):
            self.assertTrue(same(resolve_pointer(RFC, ptr), want), ptr)
        self.assertEqual(resolve_pointer({"~1": 10, "/": 9}, "/~01"), 10)
        self.assertEqual(resolve_pointer([[1, [2, 3]]], "/0/1/1"), 3)
        for ptr in ("foo", "/foo/2", "/foo/-", "/foo/01", "/nope", "/m~2n", "/foo/0/x", "/foo/a"):
            with self.assertRaises(PatchError, msg=ptr):
                resolve_pointer(RFC, ptr)

    def test_f_add_remove_replace(self):
        self.apply({"foo": "bar"}, [{"op": "add", "path": "/baz", "value": "qux"}],
                   {"baz": "qux", "foo": "bar"})
        self.apply({"foo": ["bar", "baz"]}, [{"op": "add", "path": "/foo/1", "value": "qux"}],
                   {"foo": ["bar", "qux", "baz"]})
        self.apply({"foo": ["bar"]}, [{"op": "add", "path": "/foo/-", "value": ["abc", "def"]}],
                   {"foo": ["bar", ["abc", "def"]]})
        self.apply({"foo": ["bar"]}, [{"op": "add", "path": "/foo/1", "value": 1}], {"foo": ["bar", 1]})
        self.apply({"baz": "qux", "foo": "bar"}, [{"op": "remove", "path": "/baz"}], {"foo": "bar"})
        self.apply({"foo": ["bar", "qux", "baz"]}, [{"op": "remove", "path": "/foo/1"}],
                   {"foo": ["bar", "baz"]})
        self.apply({"baz": "qux", "foo": "bar"}, [{"op": "replace", "path": "/baz", "value": "boo"}],
                   {"baz": "boo", "foo": "bar"})
        self.apply({"foo": "bar"}, [{"op": "add", "path": "/child", "value": {"grandchild": {}}}],
                   {"foo": "bar", "child": {"grandchild": {}}})
        self.apply({"a": 1}, [{"op": "replace", "path": "", "value": [1, 2]}], [1, 2])
        self.apply([1, 2], [{"op": "add", "path": "", "value": {"x": None}}], {"x": None})
        self.apply({"a/b": {"m~n": 1}}, [{"op": "replace", "path": "/a~1b/m~0n", "value": 2}],
                   {"a/b": {"m~n": 2}})
        for patch in ([{"op": "add", "path": "/baz/bat", "value": "qux"}],
                      [{"op": "remove", "path": "/nope"}], [{"op": "remove", "path": ""}],
                      [{"op": "replace", "path": "/nope", "value": 1}],
                      [{"op": "add", "path": "/foo/5", "value": 1}],
                      [{"op": "add", "path": "/x"}], [{"op": "frobnicate", "path": "/x"}],
                      [{"path": "/x", "value": 1}], [{"op": "remove", "path": "/foo/-"}]):
            with self.assertRaises(PatchError, msg=repr(patch)):
                apply_patch({"foo": ["bar"]}, patch)

    def test_f_add_existing_member(self):
        with self.assertRaises(PatchError):
            apply_patch({"a": 1}, [{"op": "add", "path": "/a", "value": 2}])
        with self.assertRaises(PatchError):
            apply_patch({"a": {"b": None}}, [{"op": "add", "path": "/a/b", "value": None}])
        self.apply({"a": [1]}, [{"op": "add", "path": "/a/0", "value": 0}], {"a": [0, 1]})

    def test_f_move_copy_test(self):
        self.apply({"foo": {"bar": "baz", "waldo": "fred"}, "qux": {"corge": "grault"}},
                   [{"op": "move", "from": "/foo/waldo", "path": "/qux/thud"}],
                   {"foo": {"bar": "baz"}, "qux": {"corge": "grault", "thud": "fred"}})
        self.apply({"foo": ["all", "grass", "cows", "eat"]},
                   [{"op": "move", "from": "/foo/1", "path": "/foo/3"}],
                   {"foo": ["all", "cows", "eat", "grass"]})
        self.apply({"a": {"b": 1}}, [{"op": "move", "from": "/a", "path": "/a"}], {"a": {"b": 1}})
        self.apply({"a": [1, 2]}, [{"op": "copy", "from": "/a", "path": "/b"}],
                   {"a": [1, 2], "b": [1, 2]})
        self.apply({"a": [1, 2]}, [{"op": "copy", "from": "/a/1", "path": "/a/0"}], {"a": [2, 1, 2]})
        doc = {"baz": "qux", "foo": ["a", 2, "c"], "n": 1, "o": {"x": [1.0, None]}}
        self.apply(doc, [{"op": "test", "path": "/baz", "value": "qux"},
                         {"op": "test", "path": "/foo/1", "value": 2},
                         {"op": "test", "path": "/n", "value": 1.0},
                         {"op": "test", "path": "/o", "value": {"x": [1, None]}}], doc)
        self.apply({"/": 9, "~1": 10}, [{"op": "test", "path": "/~01", "value": 10}], {"/": 9, "~1": 10})
        for patch in ([{"op": "test", "path": "/baz", "value": "bar"}],
                      [{"op": "test", "path": "/n", "value": True}],
                      [{"op": "test", "path": "/t", "value": 1}],
                      [{"op": "test", "path": "/s", "value": 10}],
                      [{"op": "test", "path": "/foo", "value": ["a", 2]}],
                      [{"op": "test", "path": "/o", "value": {"x": [1.0, None], "y": 1}}],
                      [{"op": "move", "from": "/o", "path": "/o/x/2"}],
                      [{"op": "move", "from": "/nope", "path": "/b"}],
                      [{"op": "copy", "from": "/nope", "path": "/b"}],
                      [{"op": "move", "path": "/b"}]):
            with self.assertRaises(PatchError, msg=repr(patch)):
                apply_patch({"baz": "qux", "foo": ["a", 2, "c"], "n": 1, "t": True, "s": "10",
                             "o": {"x": [1.0, None]}}, patch)

    def test_f_make_patch(self):
        pairs = [({"a": 1}, {"a": 2}), ({"a": 1, "b": 2}, {"b": 2, "c": 3}), ({}, {"a/b": 1, "m~n": 2}),
                 ({"a": 1}, {"a": True}), ({"a": True}, {"a": 1}), ({"a": [1, 2, 3]}, {"a": [1, 3]}),
                 ({"a": [1]}, {"a": [1, 2, {"x": None}]}), ([1, 2, 3, 4], [4]), (1, [1]),
                 ({"a": {"b": {"c": 1}}}, {"a": {"b": {"c": 1, "d": [2]}}}), ({"x": None}, {"x": 0}),
                 ({"x": 0}, {"x": False}), ({"x": "1"}, {"x": 1}), ({"a": 1}, {"a": 1.0}),
                 ({"~": {"/": 1}}, {"~": {"/": 2}}), ([[1, 2], [3]], [[1], [3, 4], []]),
                 ({"k": [True, 1]}, {"k": [1, True]}), ({"a": 1, "b": [1]}, {"a": 1, "b": [1]})]
        for old, new in pairs:
            before = frozen(old)
            patch = make_patch(old, new)
            self.assertEqual(frozen(old), before)
            self.assertIsInstance(patch, list)
            for op in patch:
                self.assertIn(op["op"], ("add", "remove", "replace"), repr(op))
            self.assertTrue(same(apply_patch(old, patch), new), f"{old!r} -> {new!r}: {patch!r}")
        self.assertEqual(make_patch({"a": [1, {"b": 2}]}, {"a": [1, {"b": 2}]}), [])

    def test_c1_no_banned_imports(self):
        banned = {"jsonpatch", "jsonpointer", "deepdiff"}
        for path in PKG.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [node.module or ""]
                else:
                    continue
                for m in mods:
                    self.assertNotIn(m.split(".")[0], banned, f"{path.name} imports {m}")

    def test_c2_untouched_and_unshared(self):
        doc = {"a": [1, {"b": [2]}], "c": {"d": None}}
        before = frozen(doc)
        patch = [{"op": "add", "path": "/e", "value": []}, {"op": "add", "path": "/e/-", "value": 1},
                 {"op": "replace", "path": "/c", "value": {"z": [0]}},
                 {"op": "add", "path": "/c/z/-", "value": 5},
                 {"op": "copy", "from": "/a/1", "path": "/f"}, {"op": "add", "path": "/f/b/-", "value": 3}]
        patch_before = frozen(patch)
        out = apply_patch(doc, patch)
        self.assertEqual(frozen(doc), before)
        self.assertEqual(frozen(patch), patch_before)
        self.assertTrue(same(out, {"a": [1, {"b": [2]}], "c": {"z": [0, 5]}, "e": [1], "f": {"b": [2, 3]}}))
        inner = {id(x) for x in containers(doc)} | {id(x) for x in containers(patch)}
        for x in containers(out):
            self.assertNotIn(id(x), inner)
        out = apply_patch(doc, [])
        self.assertTrue(same(out, doc))
        self.assertIsNot(out, doc)
        failing = [{"op": "remove", "path": "/a/0"}, {"op": "add", "path": "/c/q", "value": 1},
                   {"op": "test", "path": "/a/0", "value": 99}]
        with self.assertRaises(PatchError):
            apply_patch(doc, failing)
        self.assertEqual(frozen(doc), before)

    def test_c3_index(self):
        doc = {"a": [1, 2], "b": {"c": 1}}
        cases = [(0, [{"op": "remove", "path": "/zz"}]),
                 (2, [{"op": "add", "path": "/x", "value": 1}, {"op": "remove", "path": "/x"},
                      {"op": "remove", "path": "/x"}]),
                 (0, [{"op": "jump", "path": "/a"}]),
                 (1, [{"op": "add", "path": "/y", "value": 0}, {"op": "replace", "path": "/y"}]),
                 (3, [{"op": "test", "path": "/a/0", "value": 1}, {"op": "test", "path": "/b/c", "value": 1},
                      {"op": "add", "path": "/a/-", "value": 3}, {"op": "test", "path": "/a/2", "value": 4}]),
                 (0, [{"op": "move", "from": "/b", "path": "/b/c/d"}]),
                 (1, [{"op": "copy", "from": "/a", "path": "/z"}, {"op": "add", "path": "/z", "value": 1}]),
                 (0, ["not an operation"])]
        for index, patch in cases:
            with self.assertRaises(PatchError, msg=repr(patch)) as cm:
                apply_patch(doc, patch)
            self.assertEqual(cm.exception.index, index, repr(patch))
        with self.assertRaises(PatchError) as cm:
            apply_patch(doc, {"op": "remove", "path": "/a"})
        self.assertIsNone(cm.exception.index)
        for ptr in ("a", "/zz", "/a/9", "/a/-"):
            with self.assertRaises(PatchError) as cm:
                resolve_pointer(doc, ptr)
            self.assertIsNone(cm.exception.index)


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"jpatch/patch.py": r'''"""JSON Pointer and JSON Patch. See docs/patch_rules.md."""

import re

from .errors import PatchError

OPS = {"add": ("value",), "remove": (), "replace": ("value",), "move": ("from",),
       "copy": ("from",), "test": ("value",)}
INDEX = re.compile(r"0|[1-9][0-9]*")


class _Bad(Exception):
    pass


def _clone(v):
    if isinstance(v, dict):
        return {k: _clone(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_clone(x) for x in v]
    return v


def _kind(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return "other"


def _same(a, b):
    if _kind(a) != _kind(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _tokens(pointer):
    if not isinstance(pointer, str):
        raise _Bad("a pointer is text")
    if pointer == "":
        return []
    if not pointer.startswith("/") or re.search(r"~(?![01])", pointer):
        raise _Bad(f"invalid pointer {pointer!r}")
    return [t.replace("~1", "/").replace("~0", "~") for t in pointer[1:].split("/")]


def _index(token, n, end_ok):
    if token == "-" and end_ok:
        return n
    if not INDEX.fullmatch(token) or int(token) > n or (int(token) == n and not end_ok):
        raise _Bad(f"bad index {token!r}")
    return int(token)


def _get(doc, tokens):
    cur = doc
    for t in tokens:
        if isinstance(cur, dict):
            if t not in cur:
                raise _Bad(f"no member {t!r}")
            cur = cur[t]
        elif isinstance(cur, list):
            cur = cur[_index(t, len(cur), False)]
        else:
            raise _Bad(f"cannot step into a {_kind(cur)}")
    return cur


def resolve_pointer(doc, pointer):
    try:
        return _get(doc, _tokens(pointer))
    except _Bad as e:
        raise PatchError(None, str(e)) from None


def _add(root, tokens, value):
    if not tokens:
        return value
    parent, last = _get(root, tokens[:-1]), tokens[-1]
    if isinstance(parent, dict):
        if last in parent:
            raise _Bad(f"member {last!r} exists; use replace")
        parent[last] = value
    elif isinstance(parent, list):
        parent.insert(_index(last, len(parent), True), value)
    else:
        raise _Bad(f"cannot add into a {_kind(parent)}")
    return root


def _remove(root, tokens):
    if not tokens:
        raise _Bad("cannot remove the whole document")
    parent, last = _get(root, tokens[:-1]), tokens[-1]
    if isinstance(parent, dict):
        if last not in parent:
            raise _Bad(f"no member {last!r}")
        return parent.pop(last)
    if isinstance(parent, list):
        return parent.pop(_index(last, len(parent), False))
    raise _Bad(f"cannot remove from a {_kind(parent)}")


def _one(root, op):
    if not isinstance(op, dict) or op.get("op") not in OPS or "path" not in op:
        raise _Bad("not an operation")
    for member in OPS[op["op"]]:
        if member not in op:
            raise _Bad(f"{op['op']} needs {member!r}")
    path = _tokens(op["path"])
    kind = op["op"]
    if kind == "add":
        return _add(root, path, _clone(op["value"]))
    if kind == "remove":
        _remove(root, path)
        return root
    if kind == "replace":
        _get(root, path)
        if not path:
            return _clone(op["value"])
        parent, last = _get(root, path[:-1]), path[-1]
        if isinstance(parent, list):
            parent[_index(last, len(parent), False)] = _clone(op["value"])
        else:
            parent[last] = _clone(op["value"])
        return root
    if kind == "test":
        if not _same(_get(root, path), op["value"]):
            raise _Bad("test failed")
        return root
    src = _tokens(op["from"])
    if kind == "copy":
        return _add(root, path, _clone(_get(root, src)))
    if src == path:
        _get(root, src)
        return root
    if path[:len(src)] == src:
        raise _Bad("cannot move a value into its own child")
    value = _remove(root, src)
    return _add(root, path, value)


def apply_patch(doc, patch):
    if not isinstance(patch, list):
        raise PatchError(None, "a patch is a list")
    work = _clone(doc)
    for i, op in enumerate(patch):
        try:
            work = _one(work, op)
        except _Bad as e:
            raise PatchError(i, str(e)) from None
    return work


def _esc(token):
    return token.replace("~", "~0").replace("/", "~1")


def _diff(a, b, path, ops):
    if _same(a, b):
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k not in b:
                ops.append({"op": "remove", "path": f"{path}/{_esc(k)}"})
        for k in b:
            if k in a:
                _diff(a[k], b[k], f"{path}/{_esc(k)}", ops)
            else:
                ops.append({"op": "add", "path": f"{path}/{_esc(k)}", "value": _clone(b[k])})
        return
    if isinstance(a, list) and isinstance(b, list):
        n = min(len(a), len(b))
        for i in range(n):
            _diff(a[i], b[i], f"{path}/{i}", ops)
        for i in range(len(a) - 1, n - 1, -1):
            ops.append({"op": "remove", "path": f"{path}/{i}"})
        for i in range(n, len(b)):
            ops.append({"op": "add", "path": f"{path}/-", "value": _clone(b[i])})
        return
    ops.append({"op": "replace", "path": path, "value": _clone(b)})


def make_patch(old, new):
    ops = []
    _diff(old, new, "", ops)
    return ops
'''}
