"""Phase 8 S4: the needle answer-format rule (plan §1.2, AUTHORING.md §2).

    python eval/needle_format.py lint FILE...

Every question step declares ``answer_format``: ``{"kind": K}`` with K one of identifier,
number, path or value, or ``{"kind": "list", "n": N, "sep": S}`` with S one of the named
separators. Its text ends with exactly one fixed sentence, the one ``sentence`` gives for
that format, and no other fixed sentence appears in it. Its gold answer has the kind's
shape: digits for a number, no whitespace for an identifier or a path, and for a list
exactly N parts joined by S, in the order of ``parts``.

Why (R65): on heldout5, the generator whose questions all ended in a short fixed
instruction ("Code only.") scored 47/50 loose, and the one with conversational endings
12/40. The scorer was the same; the phrasing decided the answer's shape.

``infer_format`` and ``stem_of`` exist for validating the rule on retired heldout5
questions written before it (R70). New questions declare their format; nothing infers it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEPARATORS = {"|": "a vertical bar", ";": "a semicolon", ",": "a comma", "/": "a slash"}
_SINGLE = {
    "identifier": "Reply with the identifier alone, exactly as recorded, and nothing else.",
    "number": "Reply with the number alone, in digits, and nothing else.",
    "path": "Reply with the path alone, exactly as recorded, and nothing else.",
    "value": "Reply with the value alone, exactly as recorded, and nothing else.",
}
KINDS = (*_SINGLE, "list")
_LIST = "Reply with the {n} values in that order, joined by {name} ({sep}) with no spaces, and nothing else."
# Any fixed sentence, for "exactly one": the single kinds and the list form.
_ANY_FIXED = re.compile("|".join([*(re.escape(x) for x in _SINGLE.values()),
                                  r"Reply with the \d+ values in that order, joined by .+? \(.\) "
                                  r"with no spaces, and nothing else\."]))


def sentence(fmt: dict) -> str:
    """The fixed sentence for an answer format."""
    kind = fmt.get("kind")
    if kind in _SINGLE:
        return _SINGLE[kind]
    if kind == "list":
        n, sep = fmt.get("n"), fmt.get("sep")
        if not isinstance(n, int) or n < 2:
            raise ValueError(f"a list needs n >= 2, got {n!r}")
        if sep not in SEPARATORS:
            raise ValueError(f"unknown separator {sep!r}; use one of {list(SEPARATORS)}")
        return _LIST.format(n=n, name=SEPARATORS[sep], sep=sep)
    raise ValueError(f"unknown answer kind {kind!r}; use one of {list(KINDS)}")


def apply(stem: str, fmt: dict) -> str:
    """A question's text: its stem, then the fixed sentence."""
    return f"{stem.rstrip()} {sentence(fmt)}"


def lint_step(step: dict) -> list[str]:
    """Problems with one question step; [] when it follows the rule."""
    fmt = step.get("answer_format")
    if not isinstance(fmt, dict):
        return ["no answer_format"]
    try:
        want = sentence(fmt)
    except ValueError as e:
        return [str(e)]
    text, answer, out = step.get("text") or "", step.get("answer") or "", []
    if not text.rstrip().endswith(" " + want):
        out.append(f"text does not end with the {fmt['kind']} sentence")
    if len(_ANY_FIXED.findall(text)) > 1:
        out.append("more than one fixed sentence")
    kind = fmt["kind"]
    if kind == "number" and not re.fullmatch(r"\d+", answer):
        out.append("answer is not digits")
    if kind in ("identifier", "path") and re.search(r"\s", answer):
        out.append("answer has whitespace")
    if kind == "value" and not answer.strip():
        out.append("answer is empty")
    if kind == "list":
        got = answer.split(fmt["sep"])
        if len(got) != fmt["n"]:
            out.append(f"answer has {len(got)} parts, format says {fmt['n']}")
        elif got != list(step.get("parts") or []):
            out.append("answer is not the parts in order")
    return out


def lint_history(history: dict) -> dict[str, list[str]]:
    """{question step id: problems} for every question step that breaks the rule."""
    out = {}
    for s in history.get("steps") or []:
        if s.get("kind") == "question" and (p := lint_step(s)):
            out[s["id"]] = p
    return out


# --- validation on questions written before the rule (R70) ------------------------------

def infer_format(step: dict) -> dict:
    """The format a pre-rule question's answer implies: a list when it has several parts
    joined by one named separator, a number when all digits, a value when it has spaces,
    else an identifier."""
    answer, parts = step["answer"], list(step.get("parts") or [])
    if len(parts) > 1:
        for sep in SEPARATORS:
            if sep.join(parts) == answer:
                return {"kind": "list", "n": len(parts), "sep": sep}
    if re.fullmatch(r"\d+", answer):
        return {"kind": "number"}
    if re.search(r"\s", answer):
        return {"kind": "value"}
    return {"kind": "identifier"}


# The pre-rule generators' closing sentences that only state the answer's form (R70): the
# heldout5 generators draw them from fixed phrase banks. Endings that also carry content
# ("Name the check after `x`, omitting the result.", "Format: `bay|shelf|packet`.",
# "Ignore the rehearsal duplicates.", "Give the marker without the label.") are not listed.
FORMAT_ONLY_ENDINGS = frozenset({
    "Return its code.", "Cabinet code.", "Stamp only.", "Return only that reference.",
    "Layout code only.", "Code only.", "Give the recorded token.", "Token only.",
    "Version only.", "Alias only.", "Return the token.", "Code alone.", "Value only.",
    "Provide that composite alone.", "Name only.", "Give that value alone.",
    "Branch string only.", "Give its identifier.", "Return the mode by itself.",
    "Supply the new name.", "Cite the mark alone.",
    "Separate inscriptions with a single vertical bar.", "Give that marker.",
    "Give its entire mark.", "Bare value, please.", "I need its literal checkout label.",
    "Just its receipt.",
})
# A sentence ends at . ? or ! followed by whitespace and a capital: dotted code such as
# `tests/test_maple_trial.py` or `tests.test_x` never splits.
_SPLIT = re.compile(r"(?<=[.?!])\s+(?=[A-Z])")


def stem_of(text: str) -> str:
    """A pre-rule question without its closing sentence when that sentence is one of
    ``FORMAT_ONLY_ENDINGS``; otherwise the whole text (a one-sentence question, or an
    ending that carries content, keeps it and gets the fixed sentence after it)."""
    t = text.strip()
    sents = _SPLIT.split(t)
    if len(sents) > 1 and sents[-1] in FORMAT_ONLY_ENDINGS:
        return " ".join(sents[:-1])
    return t


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    lint = sub.add_parser("lint")
    lint.add_argument("files", nargs="+", type=Path)
    a = p.parse_args(argv)
    bad = 0
    for f in a.files:
        h = json.loads(f.read_text(encoding="utf-8"))
        problems = lint_history(h)
        n = sum(s.get("kind") == "question" for s in h.get("steps") or [])
        print(f"{h.get('id', f.stem)}: {n - len(problems)}/{n} questions follow the format rule")
        for sid, ps in problems.items():
            print(f"  {sid}: {'; '.join(ps)}")
        bad += bool(problems)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
