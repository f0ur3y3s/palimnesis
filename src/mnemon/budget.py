"""Token budgets for every upstream call (contracts §2; D8, D14).

All values are exact rendered template tokens. With ``n_ctx`` read from the
upstream at runtime:

- ``reserve`` R is the generation allowance, ``min(client limit, cap)``. The
  upstream limit is rewritten to R when the client's is absent or above the
  cap, so the upstream's silent clamp can never take effect.
- ``input_budget`` is ``min(configured cap, n_ctx − R − M)``, so
  ``input + R + M ≤ n_ctx`` always holds.
- ``catalog`` P and ``recall`` Q are reserved slots inside the input budget
  (D14.4); in Phase 2 they render empty.

Non-evictable input (system, tool schemas, current user turn, preamble) that
cannot fit is a ``BudgetError``, never truncation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BudgetPolicy:
    input_cap: int = 48_000
    reserve_cap: int = 8_192
    margin: int = 256
    min_recent: int = 4_096
    catalog_cap: int = 1_024
    catalog_share: float = 0.05
    recall_cap: int = 4_096
    recall_share: float = 0.10


@dataclass(frozen=True)
class Budget:
    n_ctx: int
    reserve: int
    margin: int
    input_budget: int
    catalog: int
    recall: int
    rewrite_limit: int | None  # value to send upstream, or None to keep the client's


class BudgetError(Exception):
    def __init__(self, message: str, terms: dict[str, int]) -> None:
        super().__init__(message)
        self.terms = terms


def plan_budget(n_ctx: int, *, client_limit: int | None, policy: BudgetPolicy,
                extra_margin: int = 0) -> Budget:
    usable_client = client_limit if client_limit and client_limit > 0 else None
    reserve = min(usable_client or policy.reserve_cap, policy.reserve_cap)
    rewrite = reserve if usable_client is None or usable_client > policy.reserve_cap else None
    margin = policy.margin + extra_margin
    input_budget = min(policy.input_cap, n_ctx - reserve - margin)
    if input_budget <= 0:
        raise BudgetError(
            f"the upstream context ({n_ctx} tokens) leaves no room for input after the "
            f"generation reserve ({reserve}) and margin ({margin})",
            {"n_ctx": n_ctx, "reserve": reserve, "margin": margin},
        )
    return Budget(
        n_ctx=n_ctx,
        reserve=reserve,
        margin=margin,
        input_budget=input_budget,
        catalog=min(policy.catalog_cap, int(policy.catalog_share * input_budget)),
        recall=min(policy.recall_cap, int(policy.recall_share * input_budget)),
        rewrite_limit=rewrite,
    )


def check_fixed(budget: Budget, *, fixed_tokens: int) -> None:
    """Non-evictable input must fit the input budget (and hence the context)."""
    if fixed_tokens <= budget.input_budget:
        return
    terms = {"fixed": fixed_tokens, "reserve": budget.reserve, "margin": budget.margin,
             "n_ctx": budget.n_ctx, "input_budget": budget.input_budget}
    raise BudgetError(
        f"system instructions, tool schemas and the current input need {fixed_tokens} tokens; "
        f"with the generation reserve {budget.reserve} and margin {budget.margin}, the upstream "
        f"context of {budget.n_ctx} tokens allows {budget.input_budget}. Nothing was truncated.",
        terms,
    )


def check_floor(n_ctx: int, *, fixed_min: int, client_limit: int | None,
                policy: BudgetPolicy) -> None:
    """Startup floor: the smallest fixed input plus a minimum recent window must fit."""
    budget = plan_budget(n_ctx, client_limit=client_limit, policy=policy)
    need = fixed_min + policy.min_recent + budget.reserve + budget.margin
    if need > n_ctx:
        terms = {"fixed_min": fixed_min, "min_recent": policy.min_recent,
                 "reserve": budget.reserve, "margin": budget.margin, "n_ctx": n_ctx}
        raise BudgetError(
            f"bounded views need {need} tokens (fixed {fixed_min} + recent window "
            f"{policy.min_recent} + reserve {budget.reserve} + margin {budget.margin}) but the "
            f"upstream context is {n_ctx}",
            terms,
        )
