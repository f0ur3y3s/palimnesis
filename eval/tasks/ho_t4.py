"""ho-t4: layered settings with file and environment overrides (held-out task, D44.5)."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, SLUG_WORDS, catalog_suite, long_doc

ID = "ho-t4"
SET = "heldout"
TITLE = "layerconf: defaults, a settings file and environment overrides"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "precedence is environment over file over defaults; only variables prefixed LAYER_ "
          "count, and a double underscore nests (LAYER_DB__HOST is db.host)",
    "C2": "load() never reads os.environ itself; the caller passes the environment mapping",
    "C3": "values from the environment take the type of the default (int, float, bool, str); "
          "bools accept only true/false/1/0 in any case, anything else raises SettingsError "
          "naming the key",
}
TRAP = ("already tried os.environ.get(key.upper()) for each key; it failed for nested keys and "
        "picked up an unrelated HOST variable on CI")


def dotted(parts: list[str]) -> str:
    return ".".join(p.strip().lower() for p in parts if p.strip())


LEGACY = '''"""Key helpers (shared with the admin console; do not change)."""


def dotted(parts: list[str]) -> str:
    return ".".join(p.strip().lower() for p in parts if p.strip())
'''

ERRORS = '''"""Errors."""


class SettingsError(ValueError):
    """A setting that cannot be loaded. ``key`` is its dotted name."""

    def __init__(self, key: str, message: str):
        super().__init__(f"{key}: {message}")
        self.key = key
'''

STUB = '''"""Layered settings. See docs/settings.md."""

from __future__ import annotations

from collections.abc import Mapping

from .errors import SettingsError  # noqa: F401


def load(defaults: dict, file_path: str | None = None,
         environ: Mapping[str, str] | None = None) -> dict:
    """Nested settings: ``defaults``, overlaid by the file, overlaid by the environment."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from layerconf.load import load  # noqa: E402

DEFAULTS = {"db": {"host": "localhost", "port": 5432}, "debug": False, "name": "svc"}


class LoadTests(unittest.TestCase):
    def test_defaults_only(self):
        self.assertEqual(load(DEFAULTS), DEFAULTS)

    def test_file_overrides(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "app.ini"
            p.write_text("name = api\\n[db]\\nhost = db1\\n", encoding="utf-8")
            got = load(DEFAULTS, str(p))
        self.assertEqual(got["db"]["host"], "db1")
        self.assertEqual(got["name"], "api")

    def test_environment_overrides(self):
        got = load(DEFAULTS, None, {"LAYER_DB__PORT": "6000"})
        self.assertEqual(got["db"]["port"], 6000)
'''

DOC_INTRO = [
    "How services load their settings.",
    "",
    "## Settings file",
    "",
    "- INI style: `key = value` lines; `[section]` starts a nested table, so `host` under",
    "  `[db]` is `db.host`. Lines starting with `#` or `;` are comments.",
    "- Keys are case-insensitive and stored lowercase.",
    "- A key that is not in the defaults is still kept, as a string.",
    "- File values take the type of the default, like environment values.",
    "",
    "## Environment",
    "",
    "- Variables are named after the dotted key, uppercased, with `.` written as `__`.",
    "",
    "## Types",
    "",
    "- int and float are parsed as numbers; a value that does not parse is an error.",
]


def _record(rnd: random.Random, i: int) -> str:
    sec, key = rnd.choice(SLUG_WORDS), rnd.choice(SLUG_WORDS)
    return f"`[{sec}]` `{key} = {rnd.randint(1, 900)}` | {sec}.{key}"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        parts = [rnd.choice([f" {w.title()} ", w.upper(), w, "  "]) for w in
                 (rnd.choice(SLUG_WORDS) for _ in range(rnd.randint(1, 4)))]
        slug = rnd.choice(["mixed_case_parts", "blank_part", "single_part", "console_key"])
        cases.append((slug, repr(parts), repr(dotted(parts))))
    return {
        "layerconf/__init__.py": '"""Layered service settings."""\n',
        "layerconf/errors.py": ERRORS,
        "layerconf/legacy.py": LEGACY,
        "layerconf/load.py": STUB,
        "docs/settings.md": long_doc(rnd, "Service settings", DOC_INTRO, _record),
        "tests/test_load.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("layerconf.legacy", "dotted",
                                                      "DottedCatalogTests", cases),
    }


TURNS = [
    "We're implementing `layerconf`, the settings loader every service will share. The "
    "rules: (1) precedence is environment over file over defaults; only environment variables "
    "with the prefix `LAYER_` count, and a double underscore nests, so `LAYER_DB__HOST` sets "
    "db.host; (2) `load()` never reads os.environ itself: the caller passes the environment "
    "mapping; (3) values from the environment take the type of the default (int, float, bool "
    "or str), bools accept only true/false/1/0 in any case, and anything else raises "
    "SettingsError naming the key. And we already tried os.environ.get(key.upper()) for each "
    "key; that failed for nested keys and picked up an unrelated HOST variable on CI. Please "
    "read layerconf/load.py and layerconf/errors.py first and tell me what is left; don't "
    "edit yet. " + NO_QUESTIONS,
    "Read docs/settings.md all the way through, roughly 300 lines, down to the line 'End of "
    "document.', then summarize it in five bullet points.",
    "Implement the defaults and settings-file part of `load`: parse the INI-style file, nest "
    "sections, and overlay it on a copy of the defaults. Leave the environment for later. Run "
    "`python -m unittest tests.test_load -v`; the environment test may still fail.",
    "Run the full suite verbosely, `python -m unittest discover -s tests -v`, and tell me how "
    "many tests ran and which ones failed.",
    "Now add the environment overrides to `load`. Then run "
    "`python -m unittest tests.test_load -v`.",
    "Run the full suite verbosely again (`python -m unittest discover -s tests -v`) and report "
    "the totals.",
    "Add type handling to `load`: environment and file values are converted to the type of "
    "the default value, and a value that cannot be converted raises SettingsError. Add tests "
    "for it to tests/test_load.py and run that module.",
    "To finish, run `python -m unittest discover -s tests` once more and summarize your "
    "changes.",
]

HIDDEN = {"_check/test_hidden.py": '''import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from layerconf.errors import SettingsError  # noqa: E402
from layerconf.load import load  # noqa: E402

DEFAULTS = {"db": {"host": "localhost", "port": 5432, "ssl": False}, "debug": False,
            "name": "svc", "ratio": 0.5}
INI = "# comment\\nname = api\\nratio = 0.75\\n[db]\\nhost = db1\\nport = 6001\\n"


def with_file(text):
    d = tempfile.TemporaryDirectory()
    p = Path(d.name) / "app.ini"
    p.write_text(text, encoding="utf-8")
    return d, str(p)


class HiddenTests(unittest.TestCase):
    def test_f_defaults_and_file(self):
        self.assertEqual(load(DEFAULTS), DEFAULTS)
        d, p = with_file(INI)
        with d:
            got = load(DEFAULTS, p)
        self.assertEqual(got["db"], {"host": "db1", "port": 6001, "ssl": False})
        self.assertEqual((got["name"], got["ratio"], got["debug"]), ("api", 0.75, False))
        self.assertEqual(DEFAULTS["db"]["host"], "localhost")

    def test_f_environment(self):
        d, p = with_file(INI)
        with d:
            got = load(DEFAULTS, p, {"LAYER_DB__HOST": "db9", "LAYER_DEBUG": "true",
                                     "LAYER_NAME": "env"})
        self.assertEqual((got["db"]["host"], got["debug"], got["name"]), ("db9", True, "env"))
        self.assertEqual(got["db"]["port"], 6001)

    def test_f_types(self):
        got = load(DEFAULTS, None, {"LAYER_DB__PORT": "7000", "LAYER_RATIO": "0.25",
                                    "LAYER_DB__SSL": "1"})
        self.assertEqual((got["db"]["port"], got["ratio"], got["db"]["ssl"]), (7000, 0.25, True))
        with self.assertRaises(SettingsError):
            load(DEFAULTS, None, {"LAYER_DB__PORT": "many"})

    def test_c1_precedence_prefix(self):
        d, p = with_file(INI)
        with d:
            got = load(DEFAULTS, p, {"LAYER_DB__PORT": "7100", "DB__PORT": "1", "HOST": "x",
                                     "NAME": "nope", "layer_name": "lower"})
        self.assertEqual(got["db"]["port"], 7100)
        self.assertEqual(got["db"]["host"], "db1")
        self.assertIn(got["name"], ("api", "lower"))

    def test_c2_no_os_environ(self):
        with mock.patch.dict(os.environ, {"LAYER_NAME": "from-os", "LAYER_DB__PORT": "1"}):
            got = load(DEFAULTS, None, {})
            got2 = load(DEFAULTS)
        self.assertEqual(got["name"], "svc")
        self.assertEqual(got2["name"], "svc")
        self.assertEqual(got2["db"]["port"], 5432)

    def test_c3_bools(self):
        for raw, want in (("true", True), ("FALSE", False), ("1", True), ("0", False), ("True", True)):
            self.assertIs(load(DEFAULTS, None, {"LAYER_DEBUG": raw})["debug"], want, raw)
        for raw in ("yes", "on", "2", ""):
            with self.assertRaises(SettingsError, msg=raw) as cm:
                load(DEFAULTS, None, {"LAYER_DEBUG": raw})
            self.assertIn("debug", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"layerconf/load.py": '''"""Layered settings. See docs/settings.md."""

from __future__ import annotations

import copy
import configparser
from collections.abc import Mapping

from .errors import SettingsError

PREFIX = "LAYER_"


def _convert(key: str, raw: str, default):
    if isinstance(default, bool):
        v = raw.strip().lower()
        if v in ("true", "1"):
            return True
        if v in ("false", "0"):
            return False
        raise SettingsError(key, "expected true, false, 1 or 0")
    if isinstance(default, int):
        try:
            return int(raw)
        except ValueError:
            raise SettingsError(key, "expected an integer") from None
    if isinstance(default, float):
        try:
            return float(raw)
        except ValueError:
            raise SettingsError(key, "expected a number") from None
    return raw


def _set(tree: dict, path: list[str], raw: str, defaults: dict) -> None:
    node, dnode = tree, defaults
    for part in path[:-1]:
        node = node.setdefault(part, {})
        dnode = dnode.get(part, {}) if isinstance(dnode, dict) else {}
    key = ".".join(path)
    default = dnode.get(path[-1]) if isinstance(dnode, dict) else None
    node[path[-1]] = _convert(key, raw, default) if default is not None else raw


def load(defaults: dict, file_path: str | None = None,
         environ: Mapping[str, str] | None = None) -> dict:
    out = copy.deepcopy(defaults)
    if file_path:
        cp = configparser.ConfigParser(interpolation=None, comment_prefixes=("#", ";"))
        with open(file_path, encoding="utf-8") as f:
            cp.read_string("[__top__]\\n" + f.read())
        for section in cp.sections():
            for key, raw in cp.items(section, raw=True):
                path = [key.lower()] if section == "__top__" else [section.lower(), key.lower()]
                _set(out, path, raw, defaults)
    for name, raw in (environ or {}).items():
        if name.startswith(PREFIX) and len(name) > len(PREFIX):
            _set(out, [p.lower() for p in name[len(PREFIX):].split("__")], raw, defaults)
    return out
'''}
