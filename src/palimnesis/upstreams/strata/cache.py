"""Strata's prefix-cache reuse model (docs/probes/strata.md §7).

Strata's engine has recurrent state, so it resumes only from saved checkpoints, never
from an arbitrary token. Checkpoints are taken at the start of each new assistant turn
(including the generation prompt) and every 16K prompt tokens; at most 6 are kept by
least recent use, plus a system-prompt root when the system prompt is 2,048 tokens or
more. The generation prompt is always re-read.

``expected`` estimates reuse from the previous call's render alone:

    expected = max { c ∈ checkpoints(previous) : c ≤ min(LCP, generation_start(current)) }

where ``checkpoints(previous)`` are its six latest assistant-turn starts and 16K
multiples plus the system root. The most recent checkpoints are taken to be the latest
positions, an approximation of LRU. Checkpoints left by older calls are ignored, so this
is a lower bound when the upstream is otherwise idle (the probe's ``edit_turn_4`` resumed
from such a checkpoint), and the parked state after generation, which can reach past the
previous prompt on an append, is not counted. It is an estimate, and is labeled as one
wherever it is recorded (contracts §10).
"""

from __future__ import annotations

from ...profile import Layout, common_prefix

CHECKPOINT_INTERVAL = 16_384
MAX_CHECKPOINTS = 6
SYSTEM_ROOT_MIN = 2_048


class StrataCacheModel:
    """``palimnesis.profile.CacheReuseModel`` for Strata 0.1.48."""

    def checkpoints(self, layout: Layout) -> tuple[int, ...]:
        """Resume points the upstream holds after prefilling ``layout``."""
        starts = {s.start for s in layout.segments if s.kind in ("assistant", "generation")}
        starts |= set(range(CHECKPOINT_INTERVAL, len(layout.ids), CHECKPOINT_INTERVAL))
        kept = set(sorted(starts)[-MAX_CHECKPOINTS:])
        head = next((s for s in layout.segments if s.kind == "head"), None)
        if head is not None and head.end - head.start >= SYSTEM_ROOT_MIN:
            kept.add(head.end)
        return tuple(sorted(kept))

    def expected(self, previous: Layout | None, current: Layout) -> int:
        if previous is None:
            return 0
        limit = min(common_prefix(previous.ids, current.ids), current.generation_start)
        return max((c for c in self.checkpoints(previous) if c <= limit), default=0)
