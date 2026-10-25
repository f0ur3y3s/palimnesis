"""Strata's prefix-cache reuse model (placeholder until Phase 2 slice 9)."""

from __future__ import annotations


class StrataCacheModel:
    """``palimnesis.profile.CacheReuseModel`` for Strata; slice 9 implements ``expected``."""

    def expected(self, previous_render: str | None, render: str) -> int:
        raise NotImplementedError("Strata cache-reuse model lands in Phase 2 slice 9")
