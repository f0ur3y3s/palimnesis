"""Versioned model-facing affordances: stub formats, system addenda, tool descriptions.

Every string the model sees about masking and recall is a registered version
(v1_plan "Model-facing recall affordances", D14.5). Changing the text of a
version in use is a one-time, recorded prefix invalidation (contracts §10:
view policy/format version change), so a change ships as a new id rather
than an edit. ``docs/affordances.md`` documents each id and holds the Phase 3
A/B matrix that selects among them.
"""

from __future__ import annotations

from dataclasses import dataclass

from .stubs import HINT_S1, STUB_FORMAT


@dataclass(frozen=True)
class Affordance:
    id: str
    family: str  # "stub", "addendum" or "tools"
    phase: int  # first phase that can render it
    text: str
    empty: bool = False  # renders nothing on purpose (a0)


S1 = Affordance("s1", "stub", 2, (
    f"[palimnesis {STUB_FORMAT} §{{alias}}.{{block}} {{kind}} · {{tokens}} tok · {{lines}} lines"
    " · sha {sha6}]\n"
    "{head preview}\n"
    "…[{omitted} tok not shown]…\n"
    "{tail preview}\n"
    f"[{HINT_S1}]"
))

S2 = Affordance("s2", "stub", 3, (
    "[palimnesis s2 §{alias}.{block} {kind} · {tokens} tok · {lines} lines · sha {sha6}]\n"
    "{head preview}\n"
    "…[{omitted} tok not shown]…\n"
    "{tail preview}\n"
    "[archived exactly]"
))

S3 = Affordance("s3", "stub", 3, (
    "[palimnesis s3 §{alias}.{block} {kind} · {tokens} tok · {lines} lines · sha {sha6}]\n"
    "{head preview}\n"
    "…[{omitted} tok not shown]…\n"
    "{tail preview}\n"
    "[archived exactly · omitted part: "
    'palimnesis_recall(id="§{alias}.{block}", offset={head_length}, limit={omitted_length})]'
))

A0 = Affordance("a0", "addendum", 2, "", empty=True)

A1 = Affordance("a1", "addendum", 3, (
    "Older content may appear as address stubs; use palimnesis_recall for exact details "
    "and catalog or search tools when the needed address is unknown."
))

A2 = Affordance("a2", "addendum", 3, (
    "Older content may appear as address stubs like §K7Q2MX.0; an address never changes "
    "meaning. When a stub's preview is not enough to act correctly, call palimnesis_recall "
    "with its address. When you need something old but have no address, page "
    "palimnesis_catalog or search with palimnesis_grep. Do not recall what the preview already shows."
))

T1 = Affordance("t1", "tools", 3, (
    "palimnesis_recall(id, offset?, limit?): Exact archived content for an address such as "
    "§K7Q2MX.0. Long items continue from next_offset.\n"
    "palimnesis_catalog(cursor?, page?): Archived messages, 20 per page, oldest first; each "
    "line is §alias seq role kind tokens flags preview.\n"
    "palimnesis_grep(query, mode, scope?, cursor?): Search archived content; mode is text "
    "(full-text) or regex (RE2). Results carry addresses."
))

T2 = Affordance("t2", "tools", 3, (
    "palimnesis_recall(id, offset?, limit?): Returns the exact archived content behind an "
    "address shown in a stub, such as §K7Q2MX.0 (message K7Q2MX, block 0) or §K7Q2MX "
    "(whole message). Use it when a stub's preview leaves out a detail you need: an "
    "exact value, a line of output, an earlier decision. Results are chunked; pass "
    "next_offset as offset to continue. Content is returned verbatim, whitespace "
    "included. An unknown address returns an error with suggestions, never other "
    "content.\n"
    "palimnesis_catalog(cursor?, page?): Lists every archived message of this conversation, "
    "20 per page, oldest first, including masked ones. Each line is: §alias seq role kind "
    "tokens flags preview, where flags are masked, superseded or internal. Call with no "
    "arguments for page 1, pass the returned cursor for the next page, or pass page to "
    "jump. Use it to find an address when you know roughly when something happened.\n"
    "palimnesis_grep(query, mode, scope?, cursor?): Searches archived content. mode text "
    "matches words (full-text); mode regex takes RE2 syntax (no backreferences or "
    "lookaround). Results list the address and a short excerpt; pass the cursor for "
    "more. Use it when you know a distinctive string but not where it appeared."
))

REGISTRY: dict[str, Affordance] = {a.id: a for a in (S1, S2, S3, A0, A1, A2, T1, T2)}

# What Phase 2 renders: s1 stubs and no addendum (there are no recall tools yet,
# so an addendum naming them would mislead).
ACTIVE: dict[str, str] = {"stub": STUB_FORMAT, "addendum": "a0"}
