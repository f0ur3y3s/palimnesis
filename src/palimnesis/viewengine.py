"""Bounded views on the archive path: facts, budgets and view builds (Phase 2).

Per request:

1. ``ready`` refreshes the profile's upstream facts when stale. The view is
   enabled only when the profile reports them pinned (for Strata: template,
   build and canary all agree, contracts §1) and the core implements the
   profile's template rules. Otherwise the proxy is view-disabled and
   forwards as in Phase 1 (D14.9).
2. ``prepare`` (before acceptance) computes the budget from ``n_ctx`` and the
   client's output limit, and rejects non-evictable input that cannot fit.
   With ``view="off"`` it also rejects any history over the budget, since
   nothing will be masked. A ``BudgetError`` here means nothing is archived
   (D14.10).
3. ``build`` (after acceptance) builds the bounded view from the plan's
   items and the branch's persisted view state.
4. ``body`` is the upstream body: the planned body unchanged when the view
   equals the full history and no limit is rewritten, otherwise a render of
   the view with the generation reserve applied (D14.11).

Counting and facts come from the ``palimnesis.profile.UpstreamProfile``;
nothing here depends on a particular backend. CPU-heavy steps (rendering,
counting) run in worker threads.

Count drift (contracts §1.3): ``drift`` (a ``DriftMonitor``) is told the local count
and the upstream's ``usage.prompt_tokens`` of every accounted call. A difference raises
the margin to ``M_eff = min(2048, M + 2·max recent |drift|)``, so later budgets (and the
excerpt caps derived from them) shrink; three consecutive drifts, or one over 1024,
disable the view for the rest of the process (logged, and reported by ``diagnostics``).
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from dataclasses import dataclass, replace
from typing import Any

import anyio

from . import chat
from .budget import (
    Budget,
    BudgetError,
    BudgetPolicy,
    check_fixed,
    excerpt_allocation,
    plan_budget,
)
from .excerpts import RENDERER_VERSION, NoExcerpts, render_block
from .profile import UpstreamProfile, unsupported_rules
from .stubs import STUB_FORMAT
from .view import POLICY_VERSION, View, ViewPolicy, build, warm


log = logging.getLogger(__name__)

DRIFT_WINDOW = 8  # calls whose drift sets the margin
MARGIN_CAP = 2_048
DRIFT_DISABLE_CONSECUTIVE = 3
DRIFT_DISABLE_OVER = 1_024


class DriftMonitor:
    """Reconciles local counts with the upstream's per-call usage (contracts §1.3)."""

    def __init__(self, margin: int) -> None:
        self.margin = margin
        self.recent: deque[int] = deque(maxlen=DRIFT_WINDOW)
        self.consecutive = 0
        self.disabled_reason: str | None = None

    @property
    def extra_margin(self) -> int:
        """``M_eff − M``, with ``M_eff = min(2048, M + 2·max recent |drift|)``."""
        worst = max(self.recent, default=0)
        return max(0, min(MARGIN_CAP, self.margin + 2 * worst) - self.margin)

    def observe(self, local: int, upstream: int) -> dict | None:
        """Record one call; returns the drift record when the counts differ."""
        drift = upstream - local
        self.recent.append(abs(drift))
        if drift == 0:
            self.consecutive = 0
            return None
        self.consecutive += 1
        if self.disabled_reason is None:
            if abs(drift) > DRIFT_DISABLE_OVER:
                self.disabled_reason = f"count drift {drift} exceeds {DRIFT_DISABLE_OVER}"
            elif self.consecutive >= DRIFT_DISABLE_CONSECUTIVE:
                self.disabled_reason = f"{self.consecutive} consecutive count drifts"
        return {"local": local, "upstream": upstream, "drift": drift,
                "consecutive": self.consecutive, "margin": self.margin + self.extra_margin,
                "disabled": self.disabled_reason is not None}

    def diagnostics(self) -> dict:
        return {"recent": list(self.recent), "consecutive": self.consecutive,
                "margin": self.margin + self.extra_margin, "disabled_reason": self.disabled_reason}


@dataclass(frozen=True)
class Prepared:
    budget: Budget
    tools: list | None
    render_kwargs: dict
    limit_field: str


class ViewEngine:
    def __init__(self, profile: UpstreamProfile, *, mode: str = "on",
                 input_budget: int | None = None, excerpts=None) -> None:
        self.profile = profile
        self.excerpts = excerpts if excerpts is not None else NoExcerpts()
        self.counter = profile.counter
        # Declared template rules the view builder does not implement: views stay off.
        self.unsupported_rules = unsupported_rules(profile.rules)
        self.mode = mode
        self.policy = BudgetPolicy() if input_budget is None else BudgetPolicy(input_cap=input_budget)
        self.view_policy = ViewPolicy()
        self._warm_lock = threading.Lock()
        self._warm_next = None
        self._warming = False
        self.drift = DriftMonitor(self.policy.margin)

    @property
    def extra_margin(self) -> int:
        return self.drift.extra_margin

    def observe_usage(self, local: int, upstream: int) -> dict | None:
        """Reconcile one call's local count with its usage; the drift record, if any."""
        was_disabled = self.drift.disabled_reason is not None
        record = self.drift.observe(local, upstream)
        if record is not None and not was_disabled and self.drift.disabled_reason:
            log.warning("bounded views disabled: %s (diagnostics: %s)",
                        self.drift.disabled_reason, self.diagnostics())
        return record

    def diagnostics(self) -> dict:
        return {"profile": self.profile.id, "mode": self.mode,
                "unsupported_rules": list(self.unsupported_rules),
                "drift": self.drift.diagnostics(), "facts": self.profile.facts.diagnostics()}

    async def ready(self, client) -> bool:
        if self.unsupported_rules or self.drift.disabled_reason:
            return False
        await self.profile.facts.refresh(client)
        return self.profile.facts.pinned_ok

    def _prepare(self, req: chat.ChatRequest) -> Prepared:
        tools, args = self.counter.render_args(json.loads(req.raw))
        limit_field = ("max_completion_tokens" if "max_completion_tokens" in req.settings
                       else "max_tokens" if "max_tokens" in req.settings else "max_completion_tokens")
        budget = plan_budget(self.profile.facts.facts.n_ctx, client_limit=req.settings.get(limit_field),
                             policy=self.policy, extra_margin=self.extra_margin)
        messages = [m.raw_object for m in req.messages]
        users = [i for i, m in enumerate(req.messages) if m.role == "user"]
        fixed = [m for i, m in enumerate(messages)
                 if req.messages[i].role == "system" or (users and i == users[-1])]
        check_fixed(budget, fixed_tokens=self.counter.count_messages(fixed, tools, **args))
        if self.mode == "off":
            total = self.counter.count_messages(messages, tools, **args)
            if total > budget.input_budget:
                raise BudgetError(
                    f"the history needs {total} tokens and the input budget is "
                    f"{budget.input_budget}; masking is off (--view off)",
                    {"history": total, "input_budget": budget.input_budget})
        return Prepared(budget, tools, args, limit_field)

    async def prepare(self, req: chat.ChatRequest) -> Prepared:
        return await anyio.to_thread.run_sync(self._prepare, req)

    async def build(self, prepared: Prepared, plan) -> View:
        # view="off" never masks; _prepare already verified the full history fits.
        policy = ViewPolicy(high=float("inf")) if self.mode == "off" else self.view_policy

        def run() -> View:
            return build(plan.items, tools=prepared.tools, render_kwargs=prepared.render_kwargs,
                         budget=prepared.budget, state=plan.view_state, policy=policy,
                         counter=self.counter)

        view = await anyio.to_thread.run_sync(run)
        if self.mode != "off":
            self._warm(dict(items=list(plan.items), tools=prepared.tools,
                            render_kwargs=prepared.render_kwargs, budget=prepared.budget,
                            state=view.state, policy=policy, counter=self.counter))
        return view

    def _warm(self, job: dict) -> None:
        """Warm stubs for the next watermark move while the upstream generates. One
        worker, newest request wins: a pending warm-up is superseded, not queued."""
        with self._warm_lock:
            self._warm_next = job
            if self._warming:
                return
            self._warming = True

        def work() -> None:
            while True:
                with self._warm_lock:
                    job, self._warm_next = self._warm_next, None
                    if job is None:
                        self._warming = False
                        return
                try:
                    warm(**job)
                except Exception:
                    log.exception("stub warm-up failed; builds compute stubs on demand")

        threading.Thread(target=work, name="palimnesis-stub-warm", daemon=True).start()

    async def select(self, prepared: Prepared, plan, base: View):
        """Excerpt selection for the plan's host message within the allocation the
        base view leaves (D20.2). Returns (selection, rendered, charge, allocation)."""
        charges = {item.excerpt[0]: item.excerpt[2] for item in plan.items if item.excerpt}
        allocation = excerpt_allocation(
            prepared.budget, fixed_tokens=base.fixed_tokens,
            included=[charges[b] for b in base.included_excerpts if b in charges],
            policy=self.policy)
        selection = await self.excerpts.select(plan, base, allocation)
        rendered = render_block(selection.excerpts(),
                                added_tokens=self.counter.added_token_strings)
        charge = self.counter.count(rendered) if rendered else 0
        if charge > allocation:  # a source overreaching its allocation selects nothing
            selection = replace(selection, items=())
            rendered, charge = "", 0
        return selection, rendered, charge, allocation

    @staticmethod
    def body(req: chat.ChatRequest, plan, prepared: Prepared, view: View) -> bytes:
        overrides: dict[str, Any] = {}
        if prepared.budget.rewrite_limit is not None:
            overrides[prepared.limit_field] = prepared.budget.rewrite_limit
        if not overrides and view.messages == [item.message for item in plan.items]:
            return plan.upstream_body
        return chat.render_messages(req, view.messages, overrides)

    @staticmethod
    def cause(old, new) -> str:
        """Recorded cause(s) of a view move, comma-separated (contracts §10)."""
        causes = []
        if new.watermark_seq != old.watermark_seq:
            causes.append("watermark_move")
        if new.collapse_seq != old.collapse_seq:
            causes.append("collapse")
        if new.oversized != old.oversized:
            causes.append("oversized_output")
        if new.omitted_excerpts != old.omitted_excerpts:
            causes.append("excerpt_omitted")
        return ",".join(causes) or "view_state"

    @staticmethod
    def snapshot(budget: Budget) -> dict:
        return {"n_ctx": budget.n_ctx, "reserve": budget.reserve, "margin": budget.margin,
                "input_budget": budget.input_budget, "catalog": budget.catalog,
                "recall_excerpts": budget.recall_excerpts,
                "excerpt_per_message": budget.excerpt_per_message}


VIEW_FORMAT = {"policy_version": POLICY_VERSION, "stub_format": STUB_FORMAT}
EXCERPT_FORMAT = RENDERER_VERSION
