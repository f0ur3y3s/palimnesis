"""The independence check for new held-out files (Phase 7 S9, plan §1.1, D112.6).

    uv run python eval/independence.py FILE [FILE ...] [--against dev,ho,ho2,ho3,ho4]
        [--also FILE ...] [--explain]

A new task module (``.py``) or needle history (``.json``) passes when it shares, with
every earlier set:
- **no four-word run of wording.** Wording is prose: a module's string literals and
  comments, except that a string which is itself Python code (a reference file, a stub,
  a test module) contributes only its own comments, docstrings and string literals. For a
  history it is the user and assistant text and the steps' text (not tool output), as in
  ``needle_gen_ho2._grams``. Words are letters only. A path, an identifier, a number or a
  backtick code span breaks a run. The exempt wording comes from ``eval/tasks/common.py``,
  turns 1, 3, 5 and 7 of dev-t6..t10, and the fixed parts of the trap warning template
  (``AUTHORING.md`` §1.3 and §3);
- **no defined identifier**: a package, module, function or class that the module's
  embedded code defines, matched case-sensitively as a whole token in any earlier file;
- **no planted needle value**: an answer or part with a letter that occurs in an earlier
  history, or a numeric one that is an earlier answer (the ho2 rule).

Output is one line per file, ``pass`` or ``fail`` with counts. ``--explain`` lists what
is shared, but only with sets the lead may read. A sealed set (ho4 and any ``--also``
file) is counted and never shown (D96).
"""

from __future__ import annotations

import argparse
import ast
import importlib
import io
import json
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "eval" / "tasks"
NEEDLES = ROOT / "eval" / "needles"
# Phase 8 S12 (D136): heldout7 is checked against every earlier set, retired ho5 included,
# and sealed ho6 by counts only, like ho4.
SET_TASK_PREFIX = {"dev": "dev_t", "ho": "ho_t", "ho2": "ho2_t", "ho3": "ho3_t", "ho4": "ho4_t",
                   "ho5": "ho5_t", "ho6": "ho6_t"}
SET_NEEDLE_DIR = {"dev": "dev", "ho": "heldout", "ho2": "heldout2", "ho3": "heldout3",
                  "ho4": "heldout4", "ho5": "heldout5", "ho6": "heldout6"}
SEALED = {"ho4", "ho6"}
FIXED_TURNS = (1, 3, 5, 7)
FORMAT_TASKS = [f"dev_t{n}" for n in range(6, 11)]

_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*")
_STRIP = "\"“”‘’()[]{}<>.,;:!?*—–-"
_PATH_KEY = re.compile(r"^(?:[A-Za-z_]\w*/)+[A-Za-z_]\w*\.py$")
_NOT_IDENT = {"tests", "docs", "__init__", "conftest"}


# ---------------------------------------------------------------- extraction

def _is_code(s: str) -> bool:
    """A multi-line string that parses as Python with at least one statement that is not a
    bare string."""
    if "\n" not in s:
        return False
    try:
        tree = ast.parse(s)
    except (SyntaxError, ValueError):
        return False
    return any(not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))
               for n in tree.body)


def _comments(src: str) -> list[str]:
    try:
        return [t.string.lstrip("#") for t in tokenize.generate_tokens(io.StringIO(src).readline)
                if t.type == tokenize.COMMENT]
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return []


def _strings(src: str) -> list[str]:
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return []
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def prose_of_module(src: str, depth: int = 0) -> list[str]:
    """The wording of a Python source: its comments and string literals, with a string that
    is itself code replaced by that code's own wording."""
    out = _comments(src)
    for s in _strings(src):
        if depth < 3 and _is_code(s):
            out += prose_of_module(s, depth + 1)
        else:
            out.append(s)
    return out


def prose_of_needle(h: dict) -> list[str]:
    """User and assistant text and the steps' text before any paste body."""
    texts = [m.get("content") or "" for m in h.get("import", []) if m.get("role") in ("user", "assistant")]
    texts += [s.get("text", "").split("```")[0] for s in h.get("steps", [])]
    return texts


def identifiers_of_module(src: str) -> set[str]:
    """Packages, modules, functions and classes the module's embedded code defines."""
    out = set()
    for s in _strings(src):
        if _PATH_KEY.match(s):
            parts = s[:-3].split("/")
            out |= {p for p in parts if _ident(p)}
        elif _is_code(s):
            for n in ast.walk(ast.parse(s)):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if _ident(n.name):
                        out.add(n.name)
            out |= identifiers_of_module(s)
    return out


def _ident(name: str) -> bool:
    """A name worth checking: not a harness path, a test, a private name or a short one."""
    return len(name) >= 3 and name not in _NOT_IDENT and not name.startswith(("_", "test"))


def values_of_needle(h: dict) -> list[str]:
    return [x for s in h.get("steps", []) if s.get("kind") == "question"
            for x in [s.get("answer", ""), *s.get("parts", [])] if x]


def grams(texts) -> set[tuple[str, ...]]:
    """Four-word runs; a token that is not a plain word (a path, an identifier, a number)
    and a backtick code span end a run."""
    out = set()
    for t in texts:
        t = re.sub(r"```.*?```", " | ", t, flags=re.S)
        t = re.sub(r"`[^`\n]*`", " | ", t).replace("’", "'")
        run = []
        for tok in t.split():
            core = tok.strip(_STRIP)
            if core and _WORD.fullmatch(core) and not any(c in tok for c in "/_=\\"):
                run.append(core.lower())
            else:
                run = []
                continue
            if len(run) >= 4:
                out.add(tuple(run[-4:]))
    return out


# ---------------------------------------------------------------- the check

def _load(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        h = json.loads(text)
        return {"text": text, "grams": grams(prose_of_needle(h)), "ids": set(),
                "values": values_of_needle(h), "needle": True}
    return {"text": text, "grams": grams(prose_of_module(text)), "ids": identifiers_of_module(text),
            "values": [], "needle": False}


def _has_ident(name: str, corpus: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", corpus) is not None


def _shared(cand: dict, earlier: list[dict], generic: set, generic_ids: set) -> dict:
    wording = (cand["grams"] - generic) & set().union(*(e["grams"] for e in earlier)) \
        if earlier else set()
    corpus = "\n".join(e["text"] for e in earlier)
    ids = {i for i in cand["ids"] - generic_ids if _has_ident(i, corpus)}
    needle_corpus = "\n".join(e["text"] for e in earlier if e["needle"]).casefold()
    answers = {v.casefold() for e in earlier for v in e["values"]}
    values = {v for v in cand["values"]
              if (any(c.isalpha() for c in v) and v.casefold() in needle_corpus)
              or (not any(c.isalpha() for c in v) and v.casefold() in answers)}
    return {"wording": wording, "identifiers": ids, "values": values}


def _per_set(candidates, sets, exempt):
    """Each candidate's matches per earlier set. A run or an identifier that two or more
    earlier sets share is generic (the skeleton or common English) and exempt."""
    own = {c.resolve() for c in candidates}
    loaded = {name: [_load(p) for p in paths if p.resolve() not in own]
              for name, paths in sets.items()}
    counts: dict[tuple, int] = {}
    set_text = {}
    for name, earlier in loaded.items():
        for x in set().union(*(e["grams"] for e in earlier)) if earlier else set():
            counts[x] = counts.get(x, 0) + 1
        set_text[name] = "\n".join(e["text"] for e in earlier)
    generic = exempt | {x for x, n in counts.items() if n >= 2}
    for c in candidates:
        cand = _load(c)
        generic_ids = {i for i in cand["ids"]
                       if sum(_has_ident(i, t) for t in set_text.values()) >= 2}
        yield c, {name: _shared(cand, earlier, generic, generic_ids)
                  for name, earlier in loaded.items()}


def check(candidates: list[Path], sets: dict[str, list[Path]], exempt: set) -> dict[str, dict]:
    """Per candidate file: pass, and the numbers of shared runs, identifiers and values."""
    out = {}
    for c, by_set in _per_set(candidates, sets, exempt):
        n = {k: len(set().union(*(s[k] for s in by_set.values()))) if by_set else 0
             for k in ("wording", "identifiers", "values")}
        out[str(c)] = {"pass": not any(n.values()), **n}
    return out


def explain(candidates: list[Path], sets: dict[str, list[Path]], exempt: set,
            sealed: set[str]) -> list[str]:
    """What each candidate shares, per set; a sealed set's matches are counted, not shown."""
    lines = []
    for c, by_set in _per_set(candidates, sets, exempt):
        for name, s in by_set.items():
            for kind, found in s.items():
                if not found:
                    continue
                if name in sealed:
                    lines.append(f"{c}: {len(found)} {kind} shared with sealed set {name} (not shown)")
                else:
                    shown = sorted(" ".join(x) if isinstance(x, tuple) else x for x in found)
                    lines.append(f"{c}: {kind} shared with {name}: " + "; ".join(shown))
    return lines


def default_sets(names=None) -> dict[str, list[Path]]:
    """The earlier sets' task modules and needle histories, by set name."""
    out = {}
    for name in names or SET_TASK_PREFIX:
        paths = sorted(TASKS.glob(f"{SET_TASK_PREFIX[name]}*.py"))
        paths += sorted((NEEDLES / SET_NEEDLE_DIR[name]).glob("*.json"))
        out[name] = paths
    return out


def default_exempt() -> set:
    """The wording authors are told to reuse in the requests and trap warning."""
    texts = prose_of_module((TASKS / "common.py").read_text(encoding="utf-8"))
    texts.extend(("Also, we already tried", "and it failed because"))
    # The answer-format rule's fixed sentences (D127): every new question ends with one.
    import needle_format
    texts.extend(needle_format._SINGLE.values())
    for sep in needle_format.SEPARATORS:
        texts.append(needle_format.sentence({"kind": "list", "n": 3, "sep": sep}))
    sys.path.insert(0, str(TASKS))
    try:
        for m in FORMAT_TASKS:
            turns = importlib.import_module(m).TURNS
            texts += [turns[i] for i in FIXED_TURNS]
    finally:
        sys.path.remove(str(TASKS))
    return grams(texts)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--against", default=",".join(SET_TASK_PREFIX),
                   help="earlier sets (dev,ho,ho2,ho3,ho4,ho5,ho6)")
    p.add_argument("--also", nargs="*", type=Path, default=[],
                   help="more files to compare with, treated as sealed (other authors' files)")
    p.add_argument("--explain", action="store_true",
                   help="list what is shared with sets that are not sealed")
    a = p.parse_args()
    sets = default_sets(a.against.split(","))
    if a.also:
        sets["also"] = a.also
    exempt = default_exempt()
    result = check(a.files, sets, exempt)
    if a.explain:
        for line in explain(a.files, sets, exempt, SEALED | {"also"}):
            print(line)
    for f, r in result.items():
        print(f"{f}: pass" if r["pass"] else
              f"{f}: fail (wording {r['wording']}, identifiers {r['identifiers']}, values {r['values']})")
    return 0 if all(r["pass"] for r in result.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
