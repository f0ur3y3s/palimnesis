"""The bounded view: what the upstream sees of a session (plan Phase 2, D14).

``build`` is pure and deterministic. It takes the session's messages in
upstream order (client objects with internal occurrences and split partials
already spliced in), the persisted ``ViewState`` and a counter, and returns
the messages to render. It makes no upstream calls.

Mechanisms (docs/papers.md):

- **Observation masking** (The Complexity Trap; ARC). In the masked region,
  tool results over ρ tokens become s1 stubs with an alias, size, hash and
  head/tail previews; shorter ones stay inline. Assistant actions (tool calls
  and text) stay verbatim.
- **Reasoning stubs** (adaptation, D14.12). Masked-region reasoning becomes a
  reasoning stub, because the pinned template renders all earlier reasoning
  (contracts §9).
- **Span collapse** (ARC's bounded catalog, adapted). When stubs alone cannot
  reach the target, the oldest masked span becomes one user-role note naming
  its alias range (D14.13). Every entry stays addressed and listed in the
  internal catalog; model-facing catalog navigation is deferred to optional
  Phase 3B (A1, D19, D20.3), and ARC's bare-id tier is skipped (D16.6).
- **Pinned instructions** (D65, adapted from Phase 4A's pinned constraints). With
  ``pin_tokens`` set, a collapse move keeps short user instructions behind its
  boundary verbatim in place, newest first, within ``min(pin_tokens, B_in // 6)``;
  the rest are absorbed. Pins live in ``ViewState.kept``, so they change only with a
  collapse move, and the last-resort collapse absorbs them before any budget error.
- **The current turn last** (D70, R33-A). With ``protect_turn``, a collapse move first
  reaches only up to the current turn, which starts at the latest genuine instruction
  (``turns.is_instruction``). Inside the turn it then stubs the largest tool results and
  reasoning in place (``ViewState.oversized``), never the newest group's, and collapses
  the turn's own groups only when the view still exceeds ``H``, oldest first to ``T``.
  Without it, a large read collapsed the steps the model had just taken, and the model
  invented their history (R33-B).
- **Working notes** (D72; R33-D, adapting the summary checkpoint of native compaction).
  With ``notes_tokens`` S, S is reserved out of the maskable capacity, as Q is, and the
  oversized and last-resort steps leave S free. A state naming a notes version renders
  its text as one user-role block right after the leading system message, once anything
  is collapsed: a fixed place, so a later collapse never moves it past a kept message. A move that advances the collapse boundary returns ``refresh``: the request
  as it rendered before the move, plus ``NOTES_PROMPT``, which the proxy sends upstream
  to have the model rewrite its notes before the older messages leave its view. The
  builder itself still makes no upstream calls. Notes format n2 (D74, R34-C) asks for the
  current step second and for a length sized to S, and ``fit_notes`` then cuts every
  section to its first lines instead of cutting the text to a prefix. A reply with no
  text whose reasoning holds a draft of the notes is committed from that draft
  (``notes_from_reasoning``).
- **Hysteresis watermarks** (adaptation of the per-turn rolling window). The
  view changes only when it would exceed ``H = F + h·C``; it then masks
  oldest-first until ``I ≤ T = F + t·C``. Here ``C`` is the maskable
  capacity and ``F`` the non-evictable input. Unchanged views keep the
  upstream's prefix cache.

- **Excerpt blocks** (amendment A1, D20). An item may carry a frozen excerpt
  block that is appended to its user message in the view only. Rules:
  - R1: a block is included whole iff its host is at or after the watermark,
    not collapsed, not omitted, and its charge fits the per-message cap.
  - R2: omission is monotone.
  - R3: omissions happen only at threshold events, as blocks behind the new
    watermark and then the oldest until ``Σ ≤ Q_eff − q_msg``.
  - R4: every block is omitted before the view is declared too large.

  Excerpt charges never count toward the watermark thresholds, so excerpts
  never move the watermark themselves.

Invariants:
- ``I ≤ input_budget`` always, or ``BudgetError``.
- The watermark and collapse boundaries are monotone and fall on group
  starts: a user message, or an assistant message plus its tool results.
- System messages and the current user message are never masked, and any
  message kept when a boundary moved stays kept. The newest group is masked
  only when it alone cannot fit (oversized newest output).
- A stub replaces content only when it is smaller.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Sequence

from .budget import Budget, BudgetError, check_fixed
from .excerpts import attach
from .profile import empty_assistant
from .stubs import fit_prefix, reasoning_stub, span_note, tool_result_stub
from .turns import is_instruction

POLICY_VERSION = "v2"  # v2: excerpt blocks (A1), collapse may absorb kept messages
PIN_MESSAGE_TOKENS = 1_024  # D65: longer user messages are never pinned
PIN_BUDGET_SHARE = 6  # D65: pins take at most input_budget // 6
NOTES_PROMPT = (
    "[palimnesis notes request] Older messages of this conversation are about to leave your "
    "view. They stay archived exactly. Rewrite your working notes so that you can continue "
    "the task without them; they replace any earlier notes. Use these sections:\n"
    "Objective\n"
    "Requirements and constraints (quote the user's rules and the exact values, names and "
    "formats from documents and specs)\n"
    "Decisions\n"
    "Done so far (files and functions changed, the latest test results)\n"
    "Current step and next move\n"
    "Dead ends (what was tried and failed, and why)\n"
    "Write plain text, at most about 1,200 words. Do not call tools, and do not continue the "
    "task in this reply.")


# D74: n2 puts the current step right after the objective, so a cut that still falls on
# the last sections loses the least-used ones (R34-C).
NOTES_SECTIONS = ("Objective", "Current step and next move", "Requirements and constraints",
                  "Decisions", "Done so far", "Dead ends")
_SECTION_KEYS = ("Objective", "Current step", "Requirements", "Decisions", "Done so far",
                 "Dead ends")
NOTES_FORMATS = ("n1", "n2")


def notes_prompt(policy: "ViewPolicy") -> str:
    """The refresh prompt of ``policy``'s notes format: n1 is D72's ``NOTES_PROMPT``."""
    if policy.notes_format not in NOTES_FORMATS:
        raise ValueError(f"unknown notes format {policy.notes_format!r}")
    if policy.notes_format == "n1":
        return NOTES_PROMPT
    words = max(100, round(policy.notes_tokens * 0.3, -2))
    return (
        "[palimnesis notes request] Older messages of this conversation are about to leave "
        "your view. They stay archived exactly. Rewrite your working notes so that you can "
        "continue the task without them; they replace any earlier notes. Use these "
        "sections, in this order:\n"
        "Objective\n"
        "Current step and next move\n"
        "Requirements and constraints (quote the user's rules and the exact values, names "
        "and formats from documents and specs)\n"
        "Decisions\n"
        "Done so far (files and functions changed, the latest test results)\n"
        "Dead ends (what was tried and failed, and why)\n"
        f"Write plain text, at most about {words:.0f} words, as your reply, not in your "
        "reasoning. Do not call tools, and do not continue the task in this reply.")


_HEADINGS = {name.lower(): key for name, key in
             (*zip(NOTES_SECTIONS, _SECTION_KEYS), *zip(_SECTION_KEYS, _SECTION_KEYS))}


def _section_key(line: str) -> str | None:
    """The notes section ``line`` heads, if it is a heading of its own: the section's name
    or key in any case, after Markdown heading marks, a number or bold, and before an
    optional parenthetical and colon. Bullets and sentences are not headings."""
    bare = line.strip()
    if bare.startswith(("- ", "* ", "+ ")):
        return None
    bare = re.sub(r"^#+\s*", "", bare)
    bare = re.sub(r"^\d+[.)]\s*", "", bare).replace("**", "").replace("__", "")
    bare = re.sub(r"\s*\(.*\)\s*:?\s*$", "", bare).strip().rstrip(":").strip()
    return _HEADINGS.get(bare.lower())


def notes_from_reasoning(text: str) -> str | None:
    """D74: notes the model wrote only as reasoning, or None. A draft starts at a heading
    and ends where a section repeats; the last draft in which at least three distinct
    sections have a line under them is taken, from its first heading to the end."""
    lines = text.split("\n")
    drafts: list[tuple[int, set[str], set[str]]] = []  # (start, keys, keys with a body)
    current = None
    for i, line in enumerate(lines):
        key = _section_key(line)
        if key:
            if current is None or key in drafts[-1][1]:
                drafts.append((i, set(), set()))
            drafts[-1][1].add(key)
            current = key
        elif current is not None and line.strip():
            drafts[-1][2].add(current)
    for start, _, bodied in reversed(drafts):
        if len(bodied) >= 3:
            return "\n".join(lines[start:]).strip()
    return None


def fit_notes(text: str, fits: Callable[[str], bool], *, sections: bool) -> str:
    """``text`` cut so ``fits`` holds (D72, D74). With ``sections`` every section keeps
    its heading and its first k non-blank lines, the largest k that fits; otherwise, or
    when the headings alone do not fit, the text is cut at a line."""
    if fits(text):
        return text
    lines = text.split("\n")
    if sections and any(map(_section_key, lines)):
        parts: list[tuple[str | None, list[str]]] = [(None, [])]
        for line in lines:
            if _section_key(line):
                parts.append((line, []))
            elif line.strip():
                parts[-1][1].append(line)

        def render(k: int) -> str:
            return "\n".join(line for head, body in parts
                             for line in ([head] if head else []) + body[:k])

        if fits(render(1)):  # headings alone are no notes: then cut at a line
            lo, hi = 1, max(len(body) for _, body in parts)
            while lo < hi:  # the most first lines per section that fit (binary search)
                mid = (lo + hi + 1) // 2
                if fits(render(mid)):
                    lo = mid
                else:
                    hi = mid - 1
            return render(lo)
    lo, hi = 0, len(lines)  # the longest line prefix that fits (binary search)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits("\n".join(lines[:mid])):
            lo = mid
        else:
            hi = mid - 1
    if lo:
        return "\n".join(lines[:lo])
    if not fits(""):  # not even the header fits the slot
        return ""
    return fit_prefix(lines[0], fits)  # one line longer than the slot: cut it


NOTES_HEADERS = ("h1", "h2")
# D75: h2 asks for values quoted from the notes in full (R38-E: fewer answers cut short).
_HEADER_TAILS = {"h1": "", "h2": ". When you quote a value from these notes, write it out in "
                               "full, exactly as recorded"}


def notes_block(n: int, text: str, header: str = "h1") -> str:
    """The rendered working-notes block of notes version ``n`` (D72) with ``header`` (D75)."""
    if header not in NOTES_HEADERS:
        raise ValueError(f"unknown notes header {header!r}")
    return (f"[palimnesis notes · v{n} · your own working notes from earlier in this "
            f"conversation; the user's messages win{_HEADER_TAILS[header]}]\n\n{text}")


@dataclass(frozen=True)
class ViewPolicy:
    high: float = 0.90
    target: float = 0.50
    inline_tokens: int = 64  # ρ: tool results at or below stay inline
    min_recent: int = 4_096
    stub_format: str = "s1"  # s1 (Phases 2-3) or a 3B matrix variant (docs/affordances.md)
    pin_tokens: int = 0  # D65: total for pinned instructions; 0 turns pinning off
    protect_turn: bool = False  # D70: collapse the current turn last
    notes_tokens: int = 0  # D72: the working-notes slot S; 0 turns notes off
    notes_format: str = "n1"  # D74: n1 (D72) or n2
    notes_header: str = "h1"  # D75: h1 (D72) or h2


@dataclass(frozen=True)
class ViewItem:
    message: dict
    occ_id: str | None
    seq: int | None
    alias: str | None
    blocks: Mapping[str, int] = field(default_factory=dict)  # kind → block index for §ALIAS.N
    # Frozen excerpt block pinned to this user message: (block_id, rendered, charge).
    excerpt: tuple[str, str, int] | None = None


@dataclass(frozen=True)
class ViewState:
    watermark_seq: int = 0
    collapse_seq: int = 0
    oversized: frozenset[str] = frozenset()
    # Messages kept verbatim inside the masked region when a boundary moved
    # (system, then-current user message). They stay kept, so a persisted
    # boundary means the same view on every later rebuild.
    kept: frozenset[str] = frozenset()
    omitted_excerpts: frozenset[str] = frozenset()  # excerpt block ids, monotone (R2)
    notes: str | None = None  # D72: the notes version this view renders


@dataclass(frozen=True)
class View:
    messages: list[dict]
    tokens: int
    state: ViewState
    moved: bool
    fixed_tokens: int
    capacity: int
    manifest: tuple[tuple[str, str], ...]  # (occ_id, verbatim|stub|collapsed)
    included_excerpts: tuple[str, ...] = ()
    excerpt_charge: int = 0
    # Occurrences this build newly masked or collapsed: the spans retrieval
    # must cover because they are leaving the active view now (A1 Phase 3).
    evicted_now: tuple[str, ...] = ()
    # D72: the refresh request for a move that advanced the collapse boundary.
    refresh: "View | None" = None


def _group_starts(items: Sequence[ViewItem]) -> list[int]:
    """Indices where a group starts: user messages and assistant messages."""
    return [i for i, item in enumerate(items) if item.message.get("role") in ("user", "assistant")]


def _content_text(message: Mapping[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, list):
        return "".join(p.get("text") or "" for p in content if isinstance(p, dict))
    return content if isinstance(content, str) else ""


def _text_of(message: Mapping[str, Any]) -> str:
    parts = [message.get("content") or "", message.get("reasoning_content") or ""]
    for call in message.get("tool_calls") or []:
        parts.append((call.get("function") or {}).get("arguments") or "")
    return "\n".join(p for p in parts if isinstance(p, str))


class _Builder:
    def __init__(self, items, tools, render_kwargs, budget, policy, counter,
                 drops_empty_assistant=False, notes=None):
        self.items = list(items)
        self.notes = dict(notes or {})
        self.notes_charges: dict[ViewState, int] = {}  # per measured state (D72)
        self._wrap: int | None = None
        self.tools = tools
        self.render_kwargs = dict(render_kwargs)
        self.budget = budget
        self.policy = policy
        self.counter = counter
        self.users = [i for i, it in enumerate(self.items) if it.message.get("role") == "user"]
        self.last_user = self.users[-1] if self.users else None
        self.fixed = {i for i, it in enumerate(self.items) if it.message.get("role") == "system"}
        if self.last_user is not None:
            self.fixed.add(self.last_user)
        self.starts = _group_starts(self.items)
        self.turn_start = max((i for i in self.users if is_instruction(
            "user", _content_text(self.items[i].message))), default=0)
        # Turns the upstream renders as nothing (TemplateRules.drops_empty_assistant):
        # they count zero toward min_recent and are never masked.
        self.dropped = ({i for i, it in enumerate(self.items[:-1]) if empty_assistant(it.message)}
                        if drops_empty_assistant else set())
        self._stub_cache: dict[tuple[int, str], tuple[dict, bool]] = {}
        self.pin_budget = min(policy.pin_tokens, budget.input_budget // PIN_BUDGET_SHARE)
        self.pinnable = {i: n for i, n in ((i, self._pin_size(it)) for i, it in enumerate(self.items))
                         if n is not None} if self.pin_budget > 0 else {}
        self._measured: dict[ViewState, tuple] = {}

    # -- rendering ------------------------------------------------------------

    def count(self, messages: list[dict]) -> int:
        return self.counter.count_messages(messages, self.tools, **self.render_kwargs)

    def measure(self, state: ViewState):
        """``apply(state)`` plus its exact rendered count, memoized per build: the
        searches and the final view revisit the same states."""
        hit = self._measured.get(state)
        if hit is None:
            messages, manifest, included, charge = self.apply(state)
            hit = self._measured[state] = (messages, manifest, included, charge,
                                           self.count(messages))
        return hit

    def seq_index(self, seq: int) -> int:
        """Index of the first item with seq >= ``seq`` (len if none)."""
        for i, item in enumerate(self.items):
            if item.seq is not None and item.seq >= seq:
                return i
        return len(self.items)

    def masked_message(self, index: int) -> tuple[dict, bool]:
        key = (index, "masked")
        if key not in self._stub_cache:
            self._stub_cache[key] = ((dict(self.items[index].message), False)
                                     if index in self.dropped
                                     else _masked(self.items[index], self.policy, self.counter))
        return self._stub_cache[key]

    def is_fixed(self, index: int, state: ViewState) -> bool:
        return index in self.fixed or self.items[index].occ_id in state.kept

    def keep_fixed(self, state: ViewState) -> ViewState:
        """Record the fixed messages now inside the masked or collapsed region."""
        reach = max(self.seq_index(state.watermark_seq) if state.watermark_seq else 0,
                    self.seq_index(state.collapse_seq) if state.collapse_seq else 0)
        inside = {self.items[i].occ_id for i in self.fixed if i < reach and self.items[i].occ_id}
        return replace(state, kept=state.kept | inside)

    def apply(self, state: ViewState):
        """(messages, manifest, included excerpt block ids, their total charge)."""
        watermark = self.seq_index(state.watermark_seq) if state.watermark_seq else 0
        collapse = self.seq_index(state.collapse_seq) if state.collapse_seq else 0
        messages: list[dict] = []
        manifest: list[tuple[str, str]] = []
        included: list[str] = []
        charge = 0
        # Each contiguous run of collapsed items (fixed messages break runs and
        # stay in place) becomes one span note at the run's position.
        runs: dict[int, list[int]] = {}
        run_start = None
        for i in range(collapse):
            if self.is_fixed(i, state):
                run_start = None
                continue
            if run_start is None:
                run_start = i
            runs.setdefault(run_start, []).append(i)
        collapsed = {i for run in runs.values() for i in run}
        last_span = None
        for i, item in enumerate(self.items):
            if i in collapsed:
                run = runs.get(i)
                if run is not None:
                    last_span = len(messages)
                    first, last = self.items[run[0]], self.items[run[-1]]
                    messages.append({"role": "user", "content": span_note(
                        first.alias, last.alias, len(run), fmt=self.policy.stub_format)})
                manifest.append((item.occ_id, "collapsed"))
                continue
            maskable = not self.is_fixed(i, state) and (
                i < watermark or item.occ_id in state.oversized)
            if maskable:
                message, changed = self.masked_message(i)
                manifest.append((item.occ_id, "stub" if changed else "verbatim"))
            else:
                message = item.message
                manifest.append((item.occ_id, "verbatim"))
            if self.excerpt_included(i, watermark, state):
                block_id, rendered, block_charge = item.excerpt
                message = attach(message, rendered)
                included.append(block_id)
                charge += block_charge
            messages.append(message)
        notes = self.notes.get(state.notes) if state.notes else None
        if notes is not None and last_span is not None:  # D72: right after the system message
            lead = next((k for k, it in enumerate(self.items) if it.message.get("role") != "system"),
                        len(self.items))
            manifest.insert(lead, (f"notes:{state.notes}", "notes"))
            block = {"role": "user", "content": notes_block(*notes, self.policy.notes_header)}
            messages.insert(lead, block)
            n = self.counter.count_cached(block["content"]) + self.message_overhead()
            self.notes_charges[state] = n
            charge += n
        return messages, tuple(manifest), tuple(included), charge

    def message_overhead(self) -> int:
        """Template tokens one user message adds beyond its content."""
        if self._wrap is None:
            one = [{"role": "user", "content": "x"}]
            self._wrap = (self.count(one + one) - self.count(one)
                          - self.counter.count_cached("x"))
        return self._wrap

    def excerpt_included(self, index: int, watermark: int, state: ViewState) -> bool:
        excerpt = self.items[index].excerpt
        return (excerpt is not None and bool(excerpt[1]) and index >= watermark
                and excerpt[0] not in state.omitted_excerpts
                and excerpt[2] <= self.budget.excerpt_per_message)

    def _pin_size(self, item: ViewItem) -> int | None:
        """Tokens of a pinnable instruction's own content, else None (D65)."""
        content = item.message.get("content")
        if (item.occ_id is None or item.message.get("role") != "user"
                or not isinstance(content, str) or not is_instruction("user", content)):
            return None
        n = self.counter.count_cached(content)
        return n if n <= PIN_MESSAGE_TOKENS else None

    def with_collapse(self, state: ViewState, seq: int, pins: bool = True) -> ViewState:
        """A collapse move to ``seq``. It may absorb messages kept earlier (they are
        no longer fixed); the move itself is the recorded cause of that change. With
        ``pins``, instructions behind ``seq`` that are not yet collapsed stay kept,
        newest first, within the pin budget (D65)."""
        old = self.seq_index(state.collapse_seq) if state.collapse_seq else 0
        behind = [i for i, item in enumerate(self.items)
                  if item.seq is not None and item.seq < seq and i not in self.fixed]
        pinned: set[str] = set()
        if pins:
            room = self.pin_budget
            for i in reversed(behind):
                n = self.pinnable.get(i)
                occ = self.items[i].occ_id
                if n is None or not (i >= old or occ in state.kept):
                    continue
                if n > room:
                    break  # oldest go first: nothing older is pinned past a miss
                pinned.add(occ)
                room -= n
        absorbed = {self.items[i].occ_id for i in behind} - pinned
        return self.keep_fixed(replace(state, collapse_seq=seq,
                                       kept=(state.kept - absorbed) | pinned))

    def omit_for_event(self, state: ViewState, fixed: int) -> ViewState:
        """R3: at a threshold event, omit blocks behind the watermark or collapsed,
        then the oldest included until Σ ≤ Q_eff − q_msg (room for the next one)."""
        watermark = self.seq_index(state.watermark_seq) if state.watermark_seq else 0
        collapse = self.seq_index(state.collapse_seq) if state.collapse_seq else 0
        omitted = set(state.omitted_excerpts)
        live = []
        for i, item in enumerate(self.items):
            if item.excerpt is None or item.excerpt[0] in omitted:
                continue
            if i < max(watermark, collapse):
                omitted.add(item.excerpt[0])
            elif self.excerpt_included(i, watermark, state):
                live.append(item.excerpt)
        b = self.budget
        q_eff = min(b.recall_excerpts,
                    max(0, b.input_budget - b.catalog - fixed - self.policy.min_recent))
        limit = max(0, q_eff - b.excerpt_per_message)
        total = sum(e[2] for e in live)
        for block_id, _, block_charge in live:  # chronological: oldest first
            if total <= limit:
                break
            omitted.add(block_id)
            total -= block_charge
        return replace(state, omitted_excerpts=frozenset(omitted))

    # -- policy ---------------------------------------------------------------

    def fixed_tokens(self) -> int:
        return self.count([self.items[i].message for i in sorted(self.fixed)])

    def max_watermark_index(self) -> int:
        """Latest group start that keeps the newest group and min_recent tokens verbatim."""
        if not self.starts:
            return 0
        recent = 0
        candidate = self.starts[-1]
        for start in reversed(self.starts):
            end = next((s for s in self.starts if s > start), len(self.items))
            recent += sum(self.counter.count_cached(_text_of(self.items[i].message))
                          for i in range(start, end)
                          if i not in self.fixed and i not in self.dropped)
            candidate = start
            if recent >= self.policy.min_recent:
                break
        return candidate

    def stubbable(self, i: int) -> bool:
        """A tool result, or an assistant message with reasoning, that a stub could replace."""
        message = self.items[i].message
        return (message.get("role") == "tool"
                or (message.get("role") == "assistant" and bool(message.get("reasoning_content"))
                    and i not in self.dropped))

    def saving(self, i: int) -> int:
        """Tokens item ``i``'s masked form saves; 0 when a stub would not replace it."""
        masked, changed = self.masked_message(i)
        if not changed:
            return 0
        count = self.counter.count_cached
        return count(_text_of(self.items[i].message)) - count(_text_of(masked))

    def stub_largest(self, state: ViewState, lo: int, hi: int, goal: int) -> ViewState:
        """Stub unmasked items in ``[lo, hi)`` in place, largest saving first, until the
        view's non-excerpt total fits ``goal`` (D70). Items a stub leaves unchanged are
        never recorded: a move must change what renders."""
        watermark = self.seq_index(state.watermark_seq) if state.watermark_seq else 0
        order = sorted((i for i in range(max(lo, watermark), hi)
                        if not self.is_fixed(i, state) and self.stubbable(i)
                        and self.items[i].occ_id not in state.oversized and self.saving(i) > 0),
                       key=lambda i: -self.saving(i))
        for i in order:
            *_, charge, total = self.measure(state)
            if total - charge <= goal:
                break
            state = replace(state, oversized=state.oversized | {self.items[i].occ_id})
        return state

    def search(self, candidates: list[int], make_state, target: int):
        """Smallest candidate whose view fits ``target``; total is monotone in it."""
        lo, hi = 0, len(candidates) - 1
        best = None
        while lo <= hi:
            mid = (lo + hi) // 2
            _, _, _, charge, total = self.measure(make_state(candidates[mid]))
            if total - charge <= target:
                best, hi = candidates[mid], mid - 1
            else:
                lo = mid + 1
        return best


def _masked(item: ViewItem, policy: ViewPolicy, counter) -> tuple[dict, bool]:
    """``item``'s masked form (s1 stubs where they pay, D16.5) and whether it changed."""
    message = dict(item.message)
    changed = False
    count = counter.count_cached
    if message.get("role") == "tool" and isinstance(message.get("content"), str):
        text = message["content"]
        if count(text) > policy.inline_tokens and item.alias:
            stub = tool_result_stub(item.alias, item.blocks.get("tool_result", 0), text,
                                    count=count, fmt=policy.stub_format)
            if count(stub) < count(text):
                message["content"], changed = stub, True
    reasoning = message.get("reasoning_content")
    if message.get("role") == "assistant" and isinstance(reasoning, str) and reasoning \
            and item.alias:
        stub = reasoning_stub(item.alias, item.blocks.get("reasoning", 0), reasoning,
                              count=count, fmt=policy.stub_format)
        if count(stub) < count(reasoning):
            message["reasoning_content"], changed = stub, True
    return message, changed


def warm(items: Sequence[ViewItem], *, tools: Sequence[Mapping] | None,
         render_kwargs: Mapping[str, Any], budget: Budget, state: ViewState,
         policy: ViewPolicy, counter, drops_empty_assistant: bool = False) -> None:
    """Fill the process-wide stub and count caches for the next watermark move, off
    the request path (D25). Stubs and counts are pure functions of their inputs,
    so this never changes a view; it moves the cold cost of a move (fitting stub
    previews, counting each masked message's rendered fragment) to idle time.

    It renders once with every unfixed message masked, which stubs and counts each
    message a later move could mask, in its real context. That includes the
    newest group, which the next request makes maskable."""
    b = _Builder(items, tools, render_kwargs, budget, policy, counter, drops_empty_assistant)
    old = b.seq_index(state.watermark_seq) if state.watermark_seq else 0
    if len(b.items) > old:
        b.measure(b.keep_fixed(replace(state, watermark_seq=_seq(b.items, len(b.items)))))


def _seq(items: Sequence[ViewItem], index: int) -> int:
    if index >= len(items):
        return (items[-1].seq or 0) + 1
    return items[index].seq or 0


def _refresh(b: _Builder, state: ViewState, budget: Budget) -> View | None:
    """D72: ``state``'s rendering plus the notes prompt, within the input budget. If it
    would overflow, unmasked results are stubbed newest first, so the previous call's
    prompt stays a prefix as long as the new messages suffice."""
    prompt = {"role": "user", "content": notes_prompt(b.policy)}
    watermark = b.seq_index(state.watermark_seq) if state.watermark_seq else 0
    order = [i for i in reversed(range(watermark, len(b.items)))
             if not b.is_fixed(i, state) and b.stubbable(i)
             and b.items[i].occ_id not in state.oversized and b.saving(i) > 0]
    for i in [None, *order]:
        if i is not None:
            state = replace(state, oversized=state.oversized | {b.items[i].occ_id})
        messages, manifest, included, charge, _ = b.measure(state)
        tokens = b.count([*messages, prompt])
        if tokens <= budget.input_budget:
            return View([*messages, prompt], tokens, state, False, 0, 0,
                        (*manifest, ("notes-request", "notes_request")), included, charge)
    return None


def build(items: Sequence[ViewItem], *, tools: Sequence[Mapping] | None,
          render_kwargs: Mapping[str, Any], budget: Budget, state: ViewState,
          policy: ViewPolicy, counter, drops_empty_assistant: bool = False,
          notes: Mapping[str, tuple[int, str]] | None = None) -> View:
    b = _Builder(items, tools, render_kwargs, budget, policy, counter, drops_empty_assistant,
                 notes)
    fixed = b.fixed_tokens()
    check_fixed(budget, fixed_tokens=fixed)
    capacity = (budget.input_budget - budget.catalog - budget.recall_excerpts - fixed
                - policy.notes_tokens)
    high = fixed + policy.high * capacity
    target = fixed + policy.target * capacity

    def view(st: ViewState, moved: bool, base_manifest=()) -> View:
        messages, manifest, included, charge, total = b.measure(st)
        base = dict(base_manifest)
        evicted = tuple(occ for occ, form in manifest
                        if moved and form != "verbatim" and base.get(occ) == "verbatim")
        return View(messages, total, st, moved, fixed, capacity, manifest,
                    included, charge, evicted)

    original = state
    # A budget change that shrinks the per-message cap is a threshold event: blocks
    # now over the cap are omitted for good and the move is recorded (D20.1, R2).
    # Re-checking the cap per build instead made blocks churn with the client limit.
    watermark = b.seq_index(state.watermark_seq) if state.watermark_seq else 0
    over_cap = {item.excerpt[0] for i, item in enumerate(b.items)
                if item.excerpt and item.excerpt[1] and i >= watermark
                and item.excerpt[0] not in state.omitted_excerpts
                and item.excerpt[2] > budget.excerpt_per_message}
    if over_cap:
        state = replace(state, omitted_excerpts=state.omitted_excerpts | over_cap)

    messages, manifest, _, charge, total = b.measure(state)
    if total - charge <= high and total <= budget.input_budget:
        return view(state, state != original)
    base_manifest = manifest
    before = state

    # Advance the watermark over group starts, oldest first.
    old_w = b.seq_index(state.watermark_seq) if state.watermark_seq else 0
    w_max = b.max_watermark_index()
    candidates = [s for s in b.starts if old_w < s <= w_max]
    new_state = state
    if candidates:
        found = b.search(candidates, lambda i: b.keep_fixed(
            replace(state, watermark_seq=_seq(b.items, i))), target)
        new_state = replace(state, watermark_seq=_seq(b.items, found if found is not None
                                                       else candidates[-1]))
    messages, _, _, charge, total = b.measure(new_state)

    def collapse_to(state: ViewState, limit: int) -> ViewState:
        """The smallest collapse move up to group start ``limit`` that reaches the target."""
        old_c = b.seq_index(state.collapse_seq) if state.collapse_seq else 0
        candidates = [s for s in b.starts if old_c < s <= limit]
        if not candidates:
            return state
        found = b.search(candidates, lambda i: b.with_collapse(state, _seq(b.items, i)), target)
        return b.with_collapse(state, _seq(b.items, found if found is not None
                                           else candidates[-1]))

    # Collapse the oldest masked span when stubs alone do not reach the target.
    if total - charge > target:
        w_index = b.seq_index(new_state.watermark_seq) if new_state.watermark_seq else 0
        if not policy.protect_turn:
            new_state = collapse_to(new_state, w_index)
        else:  # D70: what precedes the turn, then the turn's largest items, then the turn
            new_state = collapse_to(new_state, min(w_index, b.turn_start))
            newest = b.starts[-1] if b.starts else len(b.items)
            new_state = b.stub_largest(new_state, b.turn_start, newest, target)
            *_, charge, total = b.measure(new_state)
            if total - charge > high:
                new_state = collapse_to(new_state, w_index)

    # A threshold event: excerpt omissions are scheduled with it (R3).
    new_state = b.omit_for_event(b.keep_fixed(new_state), fixed)
    messages, _, included, charge, total = b.measure(new_state)

    if total > budget.input_budget and included:  # R4: excerpts go first
        new_state = replace(new_state, omitted_excerpts=new_state.omitted_excerpts | set(included))
        messages, _, included, charge, total = b.measure(new_state)

    # D72: with notes on, the filling steps below leave the notes slot free.
    fill = budget.input_budget - policy.notes_tokens

    def over(st, total) -> bool:
        return total - b.notes_charges.get(st, 0) > fill

    # Oversized items in the recent window: stub the largest unmasked tool results
    # and assistant reasoning in place (the newest output may be the culprit).
    if over(new_state, total):
        w_index = b.seq_index(new_state.watermark_seq) if new_state.watermark_seq else 0
        unmasked = sorted(
            (i for i in range(w_index, len(b.items))
             if not b.is_fixed(i, new_state) and b.stubbable(i)
             and b.items[i].occ_id not in new_state.oversized),
            key=lambda i: -b.counter.count_cached(_text_of(b.items[i].message)))
        for i in unmasked:
            new_state = replace(new_state, oversized=new_state.oversized | {b.items[i].occ_id})
            *_, total = b.measure(new_state)
            if not over(new_state, total):
                break

    # Last resort before a budget error: let the recent window shrink below
    # min_recent to the newest group, masking and collapsing everything older.
    if over(new_state, total) and b.starts:
        newest = b.starts[-1]
        old_w = b.seq_index(new_state.watermark_seq) if new_state.watermark_seq else 0
        if newest > old_w:
            new_state = replace(new_state, watermark_seq=_seq(b.items, newest))
        old_c = b.seq_index(new_state.collapse_seq) if new_state.collapse_seq else 0
        candidates = [s for s in b.starts if old_c < s <= newest]
        if candidates:
            found = b.search(candidates,
                             lambda i: b.with_collapse(new_state, _seq(b.items, i)), fill)
            new_state = b.with_collapse(new_state, _seq(b.items, found if found is not None
                                                        else candidates[-1]))
        *_, total = b.measure(b.keep_fixed(new_state))
        if over(b.keep_fixed(new_state), total) and b.pinnable:  # pins give way first
            new_state = b.with_collapse(new_state, max(new_state.collapse_seq,
                                                       _seq(b.items, newest)), pins=False)
            *_, total = b.measure(b.keep_fixed(new_state))
    new_state = b.keep_fixed(new_state)
    result = view(new_state, new_state != original, base_manifest)
    if policy.notes_tokens and new_state.collapse_seq != before.collapse_seq:
        result = replace(result, refresh=_refresh(b, before, budget))
    if result.tokens > budget.input_budget:
        raise BudgetError(
            f"the view needs {result.tokens} tokens after masking everything maskable; the "
            f"input budget is {budget.input_budget}",
            {"view": result.tokens, "input_budget": budget.input_budget, "fixed": fixed},
        )
    return result


def view_state_json(state: ViewState) -> str:
    return json.dumps({"watermark_seq": state.watermark_seq, "collapse_seq": state.collapse_seq,
                       "oversized": sorted(state.oversized), "kept": sorted(state.kept),
                       "omitted_excerpts": sorted(state.omitted_excerpts),
                       **({"notes": state.notes} if state.notes else {})})
