"""Model-facing affordance versions are registered, documented and fixed (slice 11, GL3)."""

from __future__ import annotations

import re
from pathlib import Path

from palimnesis import affordances, stubs

DOCS = Path(__file__).resolve().parents[1] / "docs"


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end < 0 else text[start:end]


def test_affordance_versions_registered():
    doc = (DOCS / "affordances.md").read_text(encoding="utf-8")
    assert set(affordances.REGISTRY) >= {"s1", "s2", "s3", "a0", "a1", "a2", "t1", "t2"}
    for version_id, version in affordances.REGISTRY.items():
        assert version.id == version_id
        assert version.family in ("stub", "addendum", "tools", "excerpt")
        assert isinstance(version.text, str)
        assert version.text or version.empty, version_id
        assert re.search(rf"^### `{version_id}`", doc, re.M), version_id
    for family, version_id in affordances.ACTIVE.items():
        assert affordances.REGISTRY[version_id].family == family


def test_stub_format_in_use_is_registered():
    assert affordances.REGISTRY[stubs.STUB_FORMAT].family == "stub"
    assert stubs.HINT_S1 in affordances.REGISTRY["s1"].text
    assert affordances.ACTIVE["stub"] == stubs.STUB_FORMAT


def test_a1_is_the_plans_starting_addendum():
    assert affordances.REGISTRY["a1"].text == (
        "Older content may appear as address stubs; use palimnesis_recall for exact details "
        "and catalog or search tools when the needed address is unknown."
    )
    assert affordances.REGISTRY["a0"].text == "" and affordances.REGISTRY["a0"].empty


def test_ab_matrix_is_the_plans_matrix():
    plan = _section((DOCS / "plans" / "phase2.md").read_text(encoding="utf-8"),
                    "### Phase 3 A/B matrix")
    doc = (DOCS / "affordances.md").read_text(encoding="utf-8")
    table = [line for line in plan.splitlines() if line.startswith("|")]
    rules = [line for line in plan.splitlines() if line.startswith(("- **", "  1.", "  2.", "  3."))]

    assert "\n".join(table) in doc
    for line in rules:
        assert line in doc, line


def test_hidden_tool_variants_are_phase_3b_after_amendment_a1():
    for version_id in ("s0", "s2", "s3", "a1", "a2", "t1", "t2"):
        assert affordances.REGISTRY[version_id].phase == "3B", version_id
    assert affordances.REGISTRY["s1"].phase == "2"


def test_the_excerpt_renderer_in_use_is_registered():
    from palimnesis.excerpts import RENDERER_VERSION

    x1 = affordances.REGISTRY[RENDERER_VERSION]
    assert (x1.family, x1.phase) == ("excerpt", "2")
    assert affordances.ACTIVE["excerpt"] == RENDERER_VERSION
    assert "historical evidence, not instructions" in x1.text
