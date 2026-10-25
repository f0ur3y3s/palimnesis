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
  its alias range (D14.13). The catalog keeps every entry reachable.
- **Hysteresis watermarks** (adaptation of the per-turn rolling window). The
  view changes only when it would exceed ``H = F + h·C``; it then masks
  oldest-first until ``I ≤ T = F + t·C``. Here ``C`` is the maskable
  capacity and ``F`` the non-evictable input. Unchanged views keep the
  upstream's prefix cache.

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
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

from .budget import Budget, BudgetError, check_fixed
from .stubs import reasoning_stub, span_note, tool_result_stub

POLICY_VERSION = "v1"


@dataclass(frozen=True)
class ViewPolicy:
    high: float = 0.90
    target: float = 0.50
    inline_tokens: int = 64  # ρ: tool results at or below stay inline
    min_recent: int = 4_096


@dataclass(frozen=True)
class ViewItem:
    message: dict
    occ_id: str | None
    seq: int | None
    alias: str | None
    blocks: Mapping[str, int] = field(default_factory=dict)  # kind → block index for §ALIAS.N


@dataclass(frozen=True)
class ViewState:
    watermark_seq: int = 0
    collapse_seq: int = 0
    oversized: frozenset[str] = frozenset()
    # Messages kept verbatim inside the masked region when a boundary moved
    # (system, then-current user message). They stay kept, so a persisted
    # boundary means the same view on every later rebuild.
    kept: frozenset[str] = frozenset()


@dataclass(frozen=True)
class View:
    messages: list[dict]
    tokens: int
    state: ViewState
    moved: bool
    fixed_tokens: int
    capacity: int
    manifest: tuple[tuple[str, str], ...]  # (occ_id, verbatim|stub|collapsed)


def _group_starts(items: Sequence[ViewItem]) -> list[int]:
    """Indices where a group starts: user messages and assistant messages."""
    return [i for i, item in enumerate(items) if item.message.get("role") in ("user", "assistant")]


def _text_of(message: Mapping[str, Any]) -> str:
    parts = [message.get("content") or "", message.get("reasoning_content") or ""]
    for call in message.get("tool_calls") or []:
        parts.append((call.get("function") or {}).get("arguments") or "")
    return "\n".join(p for p in parts if isinstance(p, str))


class _Builder:
    def __init__(self, items, tools, render_kwargs, budget, policy, counter):
        self.items = list(items)
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
        self._stub_cache: dict[tuple[int, str], dict] = {}

    # -- rendering ------------------------------------------------------------

    def count(self, messages: list[dict]) -> int:
        return self.counter.count_messages(messages, self.tools, **self.render_kwargs)

    def seq_index(self, seq: int) -> int:
        """Index of the first item with seq >= ``seq`` (len if none)."""
        for i, item in enumerate(self.items):
            if item.seq is not None and item.seq >= seq:
                return i
        return len(self.items)

    def masked_message(self, index: int) -> tuple[dict, bool]:
        key = (index, "masked")
        if key in self._stub_cache:
            return self._stub_cache[key]["message"], self._stub_cache[key]["changed"]
        item = self.items[index]
        message = dict(item.message)
        changed = False
        count = self.counter.count_cached
        if message.get("role") == "tool" and isinstance(message.get("content"), str):
            text = message["content"]
            if count(text) > self.policy.inline_tokens and item.alias:
                stub = tool_result_stub(item.alias, item.blocks.get("tool_result", 0), text,
                                        count=count)
                if count(stub) < count(text):
                    message["content"], changed = stub, True
        reasoning = message.get("reasoning_content")
        if message.get("role") == "assistant" and isinstance(reasoning, str) and reasoning \
                and item.alias:
            stub = reasoning_stub(item.alias, item.blocks.get("reasoning", 0), reasoning,
                                  count=count)
            if count(stub) < count(reasoning):
                message["reasoning_content"], changed = stub, True
        self._stub_cache[key] = {"message": message, "changed": changed}
        return message, changed

    def is_fixed(self, index: int, state: ViewState) -> bool:
        return index in self.fixed or self.items[index].occ_id in state.kept

    def keep_fixed(self, state: ViewState) -> ViewState:
        """Record the fixed messages now inside the masked or collapsed region."""
        reach = max(self.seq_index(state.watermark_seq) if state.watermark_seq else 0,
                    self.seq_index(state.collapse_seq) if state.collapse_seq else 0)
        inside = {self.items[i].occ_id for i in self.fixed if i < reach and self.items[i].occ_id}
        return replace(state, kept=state.kept | inside)

    def apply(self, state: ViewState) -> tuple[list[dict], tuple[tuple[str, str], ...]]:
        watermark = self.seq_index(state.watermark_seq) if state.watermark_seq else 0
        collapse = self.seq_index(state.collapse_seq) if state.collapse_seq else 0
        messages: list[dict] = []
        manifest: list[tuple[str, str]] = []
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
        for i, item in enumerate(self.items):
            if i in collapsed:
                run = runs.get(i)
                if run is not None:
                    first, last = self.items[run[0]], self.items[run[-1]]
                    messages.append({"role": "user", "content": span_note(
                        first.alias, last.alias, len(run))})
                manifest.append((item.occ_id, "collapsed"))
                continue
            maskable = not self.is_fixed(i, state) and (
                i < watermark or item.occ_id in state.oversized)
            if maskable:
                message, changed = self.masked_message(i)
                messages.append(message)
                manifest.append((item.occ_id, "stub" if changed else "verbatim"))
            else:
                messages.append(item.message)
                manifest.append((item.occ_id, "verbatim"))
        return messages, tuple(manifest)

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
                          for i in range(start, end) if i not in self.fixed)
            candidate = start
            if recent >= self.policy.min_recent:
                break
        return candidate

    def search(self, candidates: list[int], make_state, target: int):
        """Smallest candidate whose view fits ``target``; total is monotone in it."""
        lo, hi = 0, len(candidates) - 1
        best = None
        while lo <= hi:
            mid = (lo + hi) // 2
            messages, _ = self.apply(make_state(candidates[mid]))
            if self.count(messages) <= target:
                best, hi = candidates[mid], mid - 1
            else:
                lo = mid + 1
        return best


def _seq(items: Sequence[ViewItem], index: int) -> int:
    if index >= len(items):
        return (items[-1].seq or 0) + 1
    return items[index].seq or 0


def build(items: Sequence[ViewItem], *, tools: Sequence[Mapping] | None,
          render_kwargs: Mapping[str, Any], budget: Budget, state: ViewState,
          policy: ViewPolicy, counter) -> View:
    b = _Builder(items, tools, render_kwargs, budget, policy, counter)
    fixed = b.fixed_tokens()
    check_fixed(budget, fixed_tokens=fixed)
    capacity = budget.input_budget - budget.catalog - budget.recall_excerpts - fixed
    high = fixed + policy.high * capacity
    target = fixed + policy.target * capacity

    messages, manifest = b.apply(state)
    total = b.count(messages)
    if total <= high and total <= budget.input_budget:
        return View(messages, total, state, False, fixed, capacity, manifest)

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
    messages, manifest = b.apply(new_state)
    total = b.count(messages)

    # Collapse the oldest masked span when stubs alone do not reach the target.
    if total > target:
        old_c = b.seq_index(new_state.collapse_seq) if new_state.collapse_seq else 0
        w_index = b.seq_index(new_state.watermark_seq) if new_state.watermark_seq else 0
        candidates = [s for s in b.starts if old_c < s <= w_index]
        if candidates:
            found = b.search(candidates, lambda i: b.keep_fixed(
                replace(new_state, collapse_seq=_seq(b.items, i))), target)
            new_state = replace(new_state, collapse_seq=_seq(b.items, found if found is not None
                                                             else candidates[-1]))
            messages, manifest = b.apply(new_state)
            total = b.count(messages)

    # Oversized newest output: stub the largest unmasked tool results in place.
    if total > budget.input_budget:
        w_index = b.seq_index(new_state.watermark_seq) if new_state.watermark_seq else 0
        unmasked = sorted(
            (i for i in range(w_index, len(b.items))
             if i not in b.fixed and b.items[i].message.get("role") == "tool"
             and b.items[i].occ_id not in new_state.oversized),
            key=lambda i: -b.counter.count_cached(_text_of(b.items[i].message)))
        for i in unmasked:
            new_state = replace(new_state, oversized=new_state.oversized | {b.items[i].occ_id})
            messages, manifest = b.apply(new_state)
            total = b.count(messages)
            if total <= budget.input_budget:
                break
    if new_state != state:
        new_state = b.keep_fixed(new_state)
        messages, manifest = b.apply(new_state)
        total = b.count(messages)
    if total > budget.input_budget:
        raise BudgetError(
            f"the view needs {total} tokens after masking everything maskable; the input "
            f"budget is {budget.input_budget}",
            {"view": total, "input_budget": budget.input_budget, "fixed": fixed},
        )
    return View(messages, total, new_state, new_state != state, fixed, capacity, manifest)


def view_state_json(state: ViewState) -> str:
    return json.dumps({"watermark_seq": state.watermark_seq, "collapse_seq": state.collapse_seq,
                       "oversized": sorted(state.oversized), "kept": sorted(state.kept)})
