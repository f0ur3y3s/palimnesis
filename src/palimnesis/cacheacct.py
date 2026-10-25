"""Cache accounting for every upstream call on the archive path (contracts §10, §1.3).

Plan Phase 2 slices 9 and 10; D14.8 (events rows, tokens in memory, re-render after a
restart) and D14.14 (allowed causes). Protocol plumbing: no paper mechanism.

Per call, ``Accountant.begin`` (before dispatch) links the call to the previous call on
its branch and to the previous call in the process (the global predecessor, for eviction
attribution), and starts tokenizing the body actually sent into a ``profile.Layout``.
``Accountant.finish`` (once the usage is known, or the call failed) writes one immutable
``upstream_call`` event:

- ``input_tokens`` (I, the view's exact count) and the upstream ``usage`` read through
  ``profile.cross_check.usage``: ``prompt_tokens``, ``cached_tokens``, ``prompt_ms``;
- ``lcp_tokens``: the token longest common prefix with the previous call on the branch.
  The previous call's tokens are held in memory; after a restart (or when the branch fell
  out of memory) they are rebuilt by re-planning that request at the archive position,
  view version and budget it was sent under (``lcp_source: rerender``);
- ``first_diff``: the first rendered turn that differs, with its view messages;
- ``cause`` (``explain``): ``first_call``, ``append`` (nothing before the previous
  generation prompt changed), ``system_change`` (a ``context_version``), ``effort_change``,
  ``tool_change``, ``watermark_move``, ``collapse``, ``oversized_output``,
  ``excerpt_omitted``, ``excerpt_included``, ``capacity_budget_change``,
  ``view_format_change``, ``model_template_change``, ``view_disabled``; several are
  comma-joined. A change no recorded decision accounts for is ``unexplained``;
- ``expected_reuse_est`` from ``profile.cache_model`` (labeled an estimate) and
  ``reuse_class`` (``classify``): ``full``, ``checkpoint_limited``,
  ``restart_or_eviction`` or ``unexplained``.

The same step reconciles I with ``usage.prompt_tokens`` (contracts §1.3): a difference
writes a ``count_drift`` event and raises the view engine's margin (``DriftMonitor``).
Accounting failures are logged; they never fail the request.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import anyio

from . import ledger
from .budget import Budget
from .profile import Layout, UpstreamProfile, common_prefix
from .view import ViewPolicy, build

log = logging.getLogger(__name__)

ESTIMATE_LABEL = "estimate"
BRANCHES_HELD = 32  # branches whose previous call's tokens stay in memory
VIEW_CAUSES = ("watermark_move", "collapse", "oversized_output", "excerpt_omitted",
               "excerpt_included")


def classify(cause: str, *, lcp: int | None, cached: int | None, estimate: int,
             generation_start: int) -> str | None:
    """The reuse class of one call (None when the upstream reported no usage).

    ``full``: everything reusable was reused (the common prefix, short of the always
    re-read generation prompt). ``checkpoint_limited``: less, but at least what the
    checkpoint model expects. ``restart_or_eviction``: below even that, with every input
    change accounted for. An unexplained change is ``unexplained`` whatever the reuse."""
    if cause == "unexplained" or "unexplained" in cause.split(","):
        return "unexplained"
    if cached is None or lcp is None:
        return None
    if cached >= min(lcp, generation_start):
        return "full"
    if cached >= estimate:
        return "checkpoint_limited"
    return "restart_or_eviction"


@dataclass(frozen=True)
class Turn:
    """One rendered view message: its occurrences, form and included excerpt block."""

    occs: tuple[str | None, ...]
    form: str  # verbatim | stub | collapsed
    excerpt: str | None = None

    def as_json(self) -> dict:
        return {"occs": list(self.occs), "form": self.form, "excerpt": self.excerpt}


def describe(items: Sequence, view) -> tuple[Turn, ...] | None:
    """The view's messages as ``Turn``s (a collapsed run is one message), or None when
    the manifest does not line up with the messages."""
    excerpt_of = {i.occ_id: i.excerpt[0] for i in items if i.excerpt}
    included = set(view.included_excerpts)
    out: list[Turn] = []
    run: list[str | None] = []
    for occ, form in view.manifest:
        if form == "collapsed":
            run.append(occ)
            continue
        if run:
            out.append(Turn(tuple(run), "collapsed"))
            run = []
        block = excerpt_of.get(occ)
        out.append(Turn((occ,), form, block if block in included else None))
    if run:
        out.append(Turn(tuple(run), "collapsed"))
    return tuple(out) if len(out) == len(view.messages) else None


@dataclass
class Call:
    """What accounting knows of one upstream call."""

    call_id: str
    request_id: str
    branch_id: str
    view_mode: str  # on | off | disabled
    view_id: str | None = None
    view_n: int = 0
    input_tokens: int | None = None
    settings: dict = field(default_factory=dict)
    tools_sha256: str | None = None
    identity: list = field(default_factory=list)
    budget: dict | None = None
    formats: dict = field(default_factory=dict)
    archive_seq: int = 0
    oversized: tuple[str, ...] = ()
    included_excerpts: tuple[str, ...] = ()
    turns: tuple[Turn, ...] | None = None
    layout: Layout | None = None
    # In memory only.
    prev: Call | None = None
    global_prev_id: str | None = None
    pending: Any = None  # future of the layout

    @property
    def disabled(self) -> bool:
        return self.view_mode == "disabled"

    def meta(self) -> dict:
        return {"call_id": self.call_id, "branch_id": self.branch_id, "view_mode": self.view_mode,
                "view_id": self.view_id, "view_n": self.view_n, "input_tokens": self.input_tokens,
                "settings": self.settings, "tools_sha256": self.tools_sha256,
                "identity": self.identity, "budget": self.budget, "formats": self.formats,
                "archive_seq": self.archive_seq, "oversized": list(self.oversized),
                "included_excerpts": list(self.included_excerpts)}

    @classmethod
    def from_payload(cls, request_id: str, p: Mapping[str, Any]) -> Call:
        return cls(call_id=p["call_id"], request_id=request_id, branch_id=p["branch_id"],
                   view_mode=p["view_mode"], view_id=p.get("view_id"), view_n=p.get("view_n", 0),
                   input_tokens=p.get("input_tokens"), settings=p.get("settings") or {},
                   tools_sha256=p.get("tools_sha256"), identity=p.get("identity") or [],
                   budget=p.get("budget"), formats=p.get("formats") or {},
                   archive_seq=p.get("archive_seq", 0), oversized=tuple(p.get("oversized") or ()),
                   included_excerpts=tuple(p.get("included_excerpts") or ()))


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=False)
                          .encode("utf-8", "surrogatepass")).hexdigest()


def _first_difference(prev: Sequence[Turn], cur: Sequence[Turn]):
    for p, c in zip(prev, cur):
        if p != c:
            return p, c
    if len(prev) != len(cur):
        longer = prev if len(prev) > len(cur) else cur
        extra = longer[min(len(prev), len(cur))]
        return (extra, None) if longer is prev else (None, extra)
    return None


def _view_cause(p: Turn | None, c: Turn | None, prev: Call, cur: Call) -> str | None:
    """Which recorded view decision turns ``p`` into ``c``, if one does."""
    if p is None or c is None:
        return None
    moved = prev.view_n != cur.view_n
    budget_changed = prev.budget != cur.budget
    if c.form == "collapsed" and (p.form != "collapsed" or p.occs != c.occs):
        return "collapse" if moved else None
    if p.occs != c.occs:
        return None
    if p.form != c.form:
        if c.form != "stub" or not moved:
            return None
        oversized = set(cur.oversized) - set(prev.oversized)
        return "oversized_output" if c.occs[0] in oversized else "watermark_move"
    if p.excerpt and not c.excerpt and (moved or budget_changed):
        return "excerpt_omitted"
    if c.excerpt and not p.excerpt and budget_changed:
        return "excerpt_included"
    return None


def explain(prev: Call | None, cur: Call, model, versions=frozenset()) -> dict:
    """lcp, first differing turn, cause and reuse estimate of ``cur`` after ``prev``.

    ``versions`` holds the ``(new occ, superseded occ)`` context versions that ``cur``'s
    request recorded or whose new occurrence ``cur`` renders."""
    if prev is None:
        return {"lcp_tokens": None, "first_diff": None, "cause": "first_call",
                "expected_reuse_est": 0}
    if prev.disabled or cur.disabled or prev.layout is None or cur.layout is None:
        return {"lcp_tokens": None, "first_diff": None,
                "cause": "view_disabled" if prev.disabled or cur.disabled else "unexplained",
                "expected_reuse_est": 0}
    a, b = prev.layout, cur.layout
    lcp = common_prefix(a.ids, b.ids)
    estimate = model.expected(a, b)
    out = {"lcp_tokens": lcp, "first_diff": None, "expected_reuse_est": estimate}
    if lcp >= a.generation_start:
        out["cause"] = "append"
        return out
    s = a.segment_at(lcp)
    ps = a.segments[s]
    cs = b.segments[s] if s < len(b.segments) else None
    causes: list[str] = []
    if prev.identity != cur.identity:
        causes.append("model_template_change")
    diff = None
    if "head" in (ps.kind, cs.kind if cs else None):
        if prev.settings != cur.settings:
            causes.append("effort_change")
        if prev.tools_sha256 != cur.tools_sha256:
            causes.append("tool_change")
        if prev.formats.get("addendum") != cur.formats.get("addendum"):
            causes.append("view_format_change")
        p_sys = [o for i in ps.messages for o in (prev.turns or ())[i].occs] if prev.turns else []
        c_sys = ([o for i in cs.messages for o in (cur.turns or ())[i].occs]
                 if cs and cur.turns else [])
        # A context version (contracts §4) keeps the superseded occurrence's place in the
        # request that carries it and appears under its own id from the next one on.
        if len(p_sys) == len(c_sys) and any(
                (c, p) in versions or (c == p and any(old == p for _, old in versions))
                for p, c in zip(p_sys, c_sys)):
            causes.append("system_change")
    elif prev.turns is not None and cur.turns is not None and cs is not None \
            and ps.kind != "unmapped" and cs.kind != "unmapped":
        diff = _first_difference([prev.turns[i] for i in ps.messages],
                                 [cur.turns[i] for i in cs.messages])
        cause = _view_cause(*diff, prev, cur) if diff else None
        if cause:
            causes.append(cause)
            if prev.budget != cur.budget:
                causes.append("capacity_budget_change")
        elif diff is None and prev.formats != cur.formats:
            causes.append("view_format_change")
    out["first_diff"] = {
        "segment": s, "kind": ps.kind, "prev_tokens": [ps.start, ps.end],
        "cur_tokens": [cs.start, cs.end] if cs else None,
        "turns": [t.as_json() if t else None for t in diff] if diff else None}
    out["cause"] = ",".join(causes) or "unexplained"
    return out


class Accountant:
    """Writes the ``upstream_call`` (and ``count_drift``) events for one process."""

    def __init__(self, profile: UpstreamProfile, store, views=None) -> None:
        self.profile = profile
        self.store = store
        self.views = views  # the view engine whose margin drift raises
        self._last: OrderedDict[str, Call] = OrderedDict()
        self._global: str | None = None

    # -- before dispatch ------------------------------------------------------

    def begin(self, plan, mode: str) -> Call:
        """Register a call about to be sent (event-loop thread, in dispatch order)."""
        view, prepared = plan.view, plan.prepared
        call = Call(call_id=plan.attempt_id, request_id=plan.request_id,
                    branch_id=plan.branch_id, view_mode=mode if view is not None else "disabled")
        if view is not None:
            from .viewengine import EXCERPT_FORMAT, VIEW_FORMAT, ViewEngine

            call.input_tokens = view.tokens
            call.settings = dict(prepared.render_kwargs)
            call.tools_sha256 = _sha(prepared.tools)
            facts = self.profile.facts.facts
            call.identity = [self.profile.id, *(facts.identity if facts else ())]
            call.budget = ViewEngine.snapshot(prepared.budget)
            call.formats = {**VIEW_FORMAT,
                            "excerpt_format": getattr(self.views, "excerpt_renderer",
                                                      EXCERPT_FORMAT),
                            "addendum": _sha(plan.addendum) if plan.addendum else None}
            call.archive_seq = max((i.seq for i in plan.items if i.seq is not None), default=0)
            call.oversized = tuple(sorted(view.state.oversized))
            call.included_excerpts = tuple(view.included_excerpts)
            call.view_n = plan.view_n
            call.view_id = plan.view_id
            call.turns = describe(plan.items, view)
            body = plan.upstream_body
            call.pending = asyncio.get_running_loop().run_in_executor(
                None, self._layout_of, body)
        call.prev = self._last.pop(plan.branch_id, None)
        self._last[plan.branch_id] = call
        while len(self._last) > BRANCHES_HELD:
            self._last.popitem(last=False)
        call.global_prev_id = self._global
        self._global = call.call_id
        return call

    def _layout_of(self, body: bytes) -> Layout:
        doc = json.loads(body)
        tools, kw = self.profile.counter.render_args(doc)
        return self.profile.counter.layout(doc.get("messages") or [], tools, **kw)

    # -- once the outcome is known --------------------------------------------

    async def finish(self, plan, call: Call, payload: Mapping | None, outcome: str) -> None:
        try:
            with anyio.CancelScope(shield=True):
                await self._finish(plan, call, payload, outcome)
        except Exception:
            log.exception("cache accounting failed for one upstream call")
        finally:
            call.prev = None  # hold one call per branch, not a chain

    async def _finish(self, plan, call: Call, payload, outcome: str) -> None:
        usage = self.profile.cross_check.usage(payload) if isinstance(payload, Mapping) else None
        if call.pending is not None:
            call.layout = await call.pending
            call.pending = None
        prev, source = call.prev, "memory"
        if prev is not None and prev.pending is not None:
            try:
                prev.layout = await prev.pending
            except Exception:
                prev.layout = None
            prev.pending = None
        segments = call.layout.segments if call.layout is not None else ()
        head = [o for s in segments if s.kind == "head" for i in s.messages
                if call.turns and i < len(call.turns) for o in call.turns[i].occs if o]

        def read(conn):
            earlier = None
            if prev is None:
                last = ledger.last_upstream_call(conn, call.branch_id)
                if last is not None:
                    earlier = self._rerender(conn, *last)
            return earlier, ledger.context_versions(conn, call.request_id, head)

        earlier, versions = await self.store.read(read)
        if prev is None and earlier is not None:
            # A previous call that cannot be rebuilt leaves this one unexplained.
            prev = earlier
            source = "rerender" if earlier.layout is not None or earlier.disabled else "rerender_failed"
        result = await anyio.to_thread.run_sync(
            lambda: explain(prev, call, self.profile.cache_model, versions))
        cached = usage.cached_tokens if usage else None
        reuse = classify(result["cause"], lcp=result["lcp_tokens"], cached=cached,
                         estimate=result["expected_reuse_est"],
                         generation_start=call.layout.generation_start if call.layout else 0)
        if call.disabled or (prev is not None and prev.disabled):
            reuse = None
        evicted_by = None
        if reuse == "restart_or_eviction" and call.global_prev_id not in (None, prev and prev.call_id):
            evicted_by = call.global_prev_id
        event = {**call.meta(), "outcome": outcome,
                 "prompt_tokens": usage.prompt_tokens if usage else None,
                 "cached_tokens": cached, "prompt_ms": usage.prompt_ms if usage else None,
                 "prev_call_id": prev.call_id if prev else None,
                 "global_prev_call_id": call.global_prev_id,
                 "lcp_source": source if prev is not None else None,
                 **result, "expected_reuse_label": ESTIMATE_LABEL,
                 "reuse_model": type(self.profile.cache_model).__name__,
                 "reuse_class": reuse, "evicted_by": evicted_by}
        drift = None
        if usage is not None and call.input_tokens is not None and self.views is not None:
            drift = self.views.observe_usage(call.input_tokens, usage.prompt_tokens)

        def write(conn):
            ledger.record_event(conn, plan, "upstream_call", **event)
            if drift is not None:
                ledger.record_event(conn, plan, "count_drift", call_id=call.call_id, **drift)

        await self.store.write(write)

    def _rerender(self, conn, request_id: str, payload: Mapping) -> Call:
        """The previous call rebuilt from the archive (D14.8); without a layout if the
        re-render fails or does not reproduce the recorded count."""
        prev = Call.from_payload(request_id, payload)
        if prev.disabled or prev.budget is None:
            return prev
        try:
            req, items = ledger.replan(conn, prev.branch_id, request_id, prev.archive_seq)
            if prev.formats.get("addendum"):
                from .viewengine import with_addendum

                fixed = ledger.fixed_addendum(conn, prev.branch_id)
                if fixed is None or _sha(fixed["text"]) != prev.formats["addendum"]:
                    return prev
                items = with_addendum(items, fixed["text"])
            tools, kw = self.profile.counter.render_args(json.loads(req.raw))
            budget = Budget(**prev.budget, rewrite_limit=None)
            _, state = ledger.view_at(conn, prev.branch_id, prev.view_n)
            policy = (ViewPolicy(high=float("inf")) if prev.view_mode == "off"
                      else getattr(self.views, "view_policy", ViewPolicy()))
            view = build(items, tools=tools, render_kwargs=kw, budget=budget, state=state,
                         policy=policy, counter=self.profile.counter)
        except Exception:
            log.exception("could not re-render the previous upstream call")
            return prev
        if view.tokens != prev.input_tokens:
            log.warning("re-rendered previous call counts %d tokens, recorded %s",
                        view.tokens, prev.input_tokens)
            return prev
        prev.layout = self.profile.counter.layout(view.messages, tools, **kw)
        prev.turns = describe(items, view)
        return prev
