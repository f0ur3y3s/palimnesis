"""ho-t5: splitting invoice amounts into cents (held-out task, D44.5)."""

from __future__ import annotations

import random

from common import CATALOG_TESTS, NO_QUESTIONS, catalog_suite, long_doc

ID = "ho-t5"
SET = "heldout"
TITLE = "splitbill: even splits, weighted allocation and discounts in integer cents"
RESTART_BEFORE = 4
KEY_CONSTRAINT = None
CONSTRAINTS = {
    "C1": "integer cents only, and the parts always add up exactly to the amount split",
    "C2": "leftover cents go to the largest fractional remainders, ties to the earliest line",
    "C3": "negative amounts or weights, or a zero total weight, raise ValueError; a non-empty "
          "input never yields an empty list",
}
TRAP = ("already tried round(total * w / sum(weights)) per line; it failed because the parts "
        "summed to one cent more or less than the total")


def cents_label(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"


LEGACY = '''"""Money display (used on printed invoices; do not change)."""


def cents_label(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"
'''

STUB = '''"""Splitting amounts in integer cents. See docs/allocation.md."""

from __future__ import annotations


def split_even(total_cents: int, n: int) -> list[int]:
    """``total_cents`` split into ``n`` parts that differ by at most one cent."""
    raise NotImplementedError


def allocate(total_cents: int, weights: list[int]) -> list[int]:
    """``total_cents`` split in proportion to ``weights``."""
    raise NotImplementedError


def apply_discount(lines: list[int], discount_cents: int) -> list[int]:
    """Line amounts after spreading ``discount_cents`` over them in proportion."""
    raise NotImplementedError
'''

VISIBLE = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from splitbill.alloc import allocate, split_even  # noqa: E402


class AllocTests(unittest.TestCase):
    def test_split_even(self):
        self.assertEqual(split_even(1000, 3), [334, 333, 333])

    def test_split_even_exact(self):
        self.assertEqual(split_even(900, 3), [300, 300, 300])

    def test_allocate_sums(self):
        self.assertEqual(sum(allocate(1000, [1, 1, 1])), 1000)
'''

DOC_INTRO = [
    "How invoice amounts are split between lines, people or cost centres.",
    "",
    "## Even splits",
    "",
    "- `split_even(total, n)` gives `n` parts that differ by at most one cent; the extra",
    "  cents go to the first parts.",
    "",
    "## Weighted allocation",
    "",
    "- `allocate(total, weights)` gives each line `total * w / sum(weights)` rounded down,",
    "  then hands out the cents that are left over, one each.",
    "- Zero weights are allowed and receive nothing.",
    "",
    "## Discounts",
    "",
    "- `apply_discount(lines, d)` spreads `d` over the lines in proportion to their amounts",
    "  and subtracts each share. A discount larger than the sum of the lines is an error.",
]


def _record(rnd: random.Random, i: int) -> str:
    total = rnd.randint(100, 99999)
    n = rnd.randint(2, 6)
    q, r = divmod(total, n)
    return f"total {total} into {n} | {[q + 1] * r + [q] * (n - r)}"


def files(rnd: random.Random) -> dict[str, str]:
    cases = []
    for _ in range(CATALOG_TESTS):
        c = rnd.choice([rnd.randint(0, 99), rnd.randint(100, 999999), -rnd.randint(1, 50000)])
        slug = rnd.choice(["small_amount", "large_amount", "credit_note", "printed_total"])
        cases.append((slug, repr(c), repr(cents_label(c))))
    return {
        "splitbill/__init__.py": '"""Invoice splitting."""\n',
        "splitbill/legacy.py": LEGACY,
        "splitbill/alloc.py": STUB,
        "docs/allocation.md": long_doc(rnd, "Allocation rules", DOC_INTRO, _record),
        "tests/test_alloc.py": VISIBLE,
        "tests/test_legacy_catalog.py": catalog_suite("splitbill.legacy", "cents_label",
                                                      "CentsLabelCatalogTests", cases),
    }


TURNS = [
    "This session is `splitbill`, the code that splits invoice amounts. Constraints: (1) "
    "integer cents only, and the parts always add up to exactly the amount being split; (2) "
    "leftover cents go to the lines with the largest fractional remainders, with ties going "
    "to the earliest line; (3) negative amounts or weights, or a total weight of zero, raise "
    "ValueError, and a non-empty input never produces an empty list. Note: we already tried "
    "round(total * w / sum(weights)) per line, and it failed because the parts summed to one "
    "cent more or less than the total. Start by reading splitbill/alloc.py and tell me what "
    "needs doing; no changes yet. " + NO_QUESTIONS,
    "Read docs/allocation.md in full, roughly 300 lines, down to the line 'End of document.', "
    "and summarize it in five bullet points.",
    "Implement `split_even(total_cents, n)`. Then run `python -m unittest tests.test_alloc -v`; "
    "the allocate test may still fail.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me "
    "how many tests ran and which failed.",
    "Implement `allocate(total_cents, weights)`. Then run "
    "`python -m unittest tests.test_alloc -v`.",
    "Run the whole suite verbosely again (`python -m unittest discover -s tests -v`) and give "
    "me the totals.",
    "Implement `apply_discount(lines, discount_cents)` on top of allocate, and validate the "
    "inputs of all three functions. Add tests for apply_discount and for bad inputs to "
    "tests/test_alloc.py and run that module.",
    "Wrap up: run `python -m unittest discover -s tests` once more and summarize what changed.",
]

HIDDEN = {"_check/test_hidden.py": '''import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from splitbill.alloc import allocate, apply_discount, split_even  # noqa: E402


class HiddenTests(unittest.TestCase):
    def test_f_split_even(self):
        self.assertEqual(split_even(1000, 3), [334, 333, 333])
        self.assertEqual(split_even(5, 4), [2, 1, 1, 1])
        self.assertEqual(split_even(0, 2), [0, 0])

    def test_f_allocate(self):
        self.assertEqual(allocate(1000, [1, 1, 1]), [334, 333, 333])
        self.assertEqual(allocate(100, [1, 0, 3]), [25, 0, 75])
        self.assertEqual(allocate(10, [3, 3, 4]), [3, 3, 4])

    def test_f_discount(self):
        self.assertEqual(apply_discount([1000, 3000], 400), [900, 2700])
        out = apply_discount([333, 333, 334], 100)
        self.assertEqual(sum(out), 900)
        self.assertTrue(all(x >= 0 for x in out))
        with self.assertRaises(ValueError):
            apply_discount([100, 100], 300)

    def test_c1_exact_sums(self):
        rnd = random.Random(5)
        for _ in range(300):
            total = rnd.randint(0, 100000)
            weights = [rnd.randint(0, 50) for _ in range(rnd.randint(1, 8))]
            if not any(weights):
                weights[0] = 1
            parts = allocate(total, weights)
            self.assertEqual(sum(parts), total)
            self.assertTrue(all(isinstance(p, int) for p in parts))

    def test_c2_largest_remainder(self):
        self.assertEqual(allocate(10, [1, 2, 3, 4, 5]), [1, 1, 2, 3, 3])
        self.assertEqual(allocate(100, [1, 1, 1]), [34, 33, 33])
        self.assertEqual(allocate(7, [2, 3, 3]), [2, 3, 2])
        self.assertEqual(allocate(1, [1, 1]), [1, 0])

    def test_c3_validation(self):
        for bad in ((-1, [1]), (10, [1, -1]), (10, [0, 0])):
            with self.assertRaises(ValueError, msg=bad):
                allocate(*bad)
        for bad in ((-5, 2), (5, 0)):
            with self.assertRaises(ValueError, msg=bad):
                split_even(*bad)
        with self.assertRaises(ValueError):
            apply_discount([100], -1)
        self.assertEqual(allocate(0, [1, 2]), [0, 0])


if __name__ == "__main__":
    unittest.main()
'''}

REFERENCE = {"splitbill/alloc.py": '''"""Splitting amounts in integer cents. See docs/allocation.md."""

from __future__ import annotations


def split_even(total_cents: int, n: int) -> list[int]:
    if total_cents < 0 or n <= 0:
        raise ValueError("total must be >= 0 and n >= 1")
    q, r = divmod(total_cents, n)
    return [q + 1] * r + [q] * (n - r)


def allocate(total_cents: int, weights: list[int]) -> list[int]:
    if total_cents < 0 or not weights or any(w < 0 for w in weights) or sum(weights) == 0:
        raise ValueError("bad total or weights")
    s = sum(weights)
    base = [total_cents * w // s for w in weights]
    rems = [total_cents * w % s for w in weights]
    left = total_cents - sum(base)
    order = sorted(range(len(weights)), key=lambda i: (-rems[i], i))
    for i in order[:left]:
        base[i] += 1
    return base


def apply_discount(lines: list[int], discount_cents: int) -> list[int]:
    if discount_cents < 0 or any(x < 0 for x in lines) or discount_cents > sum(lines):
        raise ValueError("bad lines or discount")
    if discount_cents == 0:
        return list(lines)
    shares = allocate(discount_cents, lines)
    return [x - s for x, s in zip(lines, shares)]
'''}
