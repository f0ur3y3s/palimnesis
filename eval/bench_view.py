"""Bounded-view watermark frequency, re-read cost, excerpt starvation and builder latency.

Usage:
    python eval/bench_view.py [--ingress 300000] [--seed 11] [--json] [--out FILE]

Pure: drives ``palimnesis.view.build`` with the Strata 0.1.48 profile counter (plan
Phase 2 GL7 and the builder-latency row; D14.6, D20). No sockets.

Sessions are OpenCode-shaped: the system prompt and the real ~11 KB tools array of
live body 0 (``eval/fixtures/opencode-2.1.4/live``), so the fixed input F is ~5K tokens.
Each session grows request by request, the way the archive path sees it: a request is
built after every new user message and after every tool result; the model's assistant
turn is then appended and the next request built. The view state carries from one
request to the next exactly as the proxy persists it.

Workloads (seeded):

- ``tool_heavy``: one user message, then 4-12 tool groups (assistant reasoning and a
  tool call, a tool output of 200-6000 tokens, log-uniform), then a short answer.
- ``chatty``: a user message of 10-150 tokens and an answer of 30-400 tokens with
  20-200 tokens of reasoning; every request is a new user message.
- ``big_single``: a user message, one tool group with a 3000-15000-token output, then a
  short answer.

Budgets: 24,320 (``n_ctx`` 32K) and 48,000 (``n_ctx`` 64K), reserve 8192, margin 256.

Excerpt arms, mirroring ``ArchiveHandler._bound``: on a request carrying a new user
message the base view is built, the allocation is ``budget.excerpt_allocation`` of the
base view, a block is selected and rendered with ``excerpts.render_block`` (a real
earlier archived span: the newest earlier tool output, else an earlier user message,
cut to fit) at ``min(q_msg, allocation)`` tokens, attached to the host and the view
rebuilt from the base state.

- ``none``: no blocks.
- ``every``: a full-cap block on every new user message.
- ``third``: a full-cap block on every third new user message.

Metrics (``ingress`` = tokens of new content: user text, tool outputs, assistant text,
reasoning and tool-call arguments, each counted alone with the pinned tokenizer):

- moves (view-state changes) per 100K ingress tokens, split into watermark, collapse,
  oversized and excerpt-omission-only; ingress tokens between moves;
- re-read per move: rendered tokens of the moved view after its token LCP with the
  previous request's view (``counter.layout`` ids). Also the Strata checkpoint model's
  re-read, ``len − StrataCacheModel.expected`` (an estimate), and the same two figures
  for non-move (append) requests as a baseline;
- amortized re-read: Σ re-read over moves ÷ Σ ingress;
- excerpt omissions per 100K ingress, and starvation: the share of new user messages
  (that the arm gives a block) whose allocation is below the per-message cap;
- ``build`` latency (``build`` includes the exact count) p50/p95: natural in-session
  (warm process, earlier fragments cached, new content counted for the first time) and
  an identical rebuild (all fragments cached). Target: p95 ≤ 30 ms at 48K.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from palimnesis.budget import BudgetPolicy, excerpt_allocation, plan_budget  # noqa: E402
from palimnesis.capture import load_exchanges  # noqa: E402
from palimnesis.excerpts import Excerpt, render_block  # noqa: E402
from palimnesis.profile import common_prefix  # noqa: E402
from palimnesis.upstreams.strata import pins, tokens  # noqa: E402
from palimnesis.upstreams.strata.cache import StrataCacheModel  # noqa: E402
from palimnesis.view import ViewItem, ViewPolicy, ViewState, build, warm  # noqa: E402

LIVE_DIR = ROOT / "eval/fixtures/opencode-2.1.4/live/exchanges"
BUDGETS = {"32K": 32_768, "64K": 65_536}
ARMS = ("none", "every", "third")
WORKLOADS = ("tool_heavy", "chatty", "big_single")
MIN_BLOCK = 64  # an allocation below this selects nothing

WORDS = ("def class return self value result request handler render module config "
         "import from if else for while try except raise async await yield lambda None "
         "True False assert parse token stream buffer cache index offset length error "
         "path file line column status header body json data item key list dict set "
         "the a to of in and is that it with as on be this was by not are or at").split()


def pct(values, q):
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[q - 1]


def r2(x):
    return None if x is None else round(x, 2)


class Text:
    """Seeded code-ish and prose-ish text sized in pinned tokens."""

    def __init__(self, rng: random.Random, counter):
        self.rng, self.counter = rng, counter

    def _line(self, code: bool) -> str:
        r = self.rng
        if code:
            ind = "    " * r.randint(0, 3)
            name = f"{r.choice(WORDS)}_{r.randint(0, 999)}"
            kind = r.random()
            if kind < 0.3:
                return f"{ind}def {name}({r.choice(WORDS)}, {r.choice(WORDS)}={r.randint(0, 99)}):"
            if kind < 0.6:
                return f"{ind}{name} = {r.choice(WORDS)}.{r.choice(WORDS)}({r.randint(0, 9999)})"
            if kind < 0.8:
                return (f"src/{r.choice(WORDS)}/{name}.py:{r.randint(1, 900)}: "
                        f"{' '.join(r.choice(WORDS) for _ in range(r.randint(3, 9)))}")
            return f"{ind}# {' '.join(r.choice(WORDS) for _ in range(r.randint(4, 12)))}"
        return " ".join(self.rng.choice(WORDS) for _ in range(self.rng.randint(6, 18))) + "."

    def make(self, target: int, code: bool) -> str:
        lines, n = [], 0
        while n < target:
            line = self._line(code)
            lines.append(line)
            n += self.counter.count_cached(line) + 1
        return ("\n" if code else " ").join(lines)


class Session:
    """One growing session: archive-like ViewItems, requests and metrics."""

    def __init__(self, workload, n_ctx, arm, seed, counter, base_body, ingress_target,
                 warm=True):
        self.workload, self.arm = workload, arm
        self.warm_stubs = warm
        self.counter = counter
        self.rng = random.Random(f"{workload}:{seed}")  # same content for every budget/arm
        self.text = Text(self.rng, counter)
        self.policy = BudgetPolicy()
        self.budget = plan_budget(n_ctx, client_limit=None, policy=self.policy)
        self.view_policy = ViewPolicy()
        self.tools, self.kw = counter.render_args(base_body)
        self.items: list[ViewItem] = []
        self.add({"role": "system", "content": base_body["messages"][0]["content"]})
        self.state = ViewState()
        self.ingress = 0
        self.ingress_target = ingress_target
        self.prev_layout = None
        self.call_n = 0
        self.user_n = 0
        self.cm = StrataCacheModel()
        self.records: list[dict] = []
        self.excerpt_events: list[dict] = []
        self.second_build_moves = 0
        self.errors: list[str] = []

    # -- history ------------------------------------------------------------------

    def add(self, message: dict, ingress: bool = False) -> int:
        seq = len(self.items) + 1
        blocks = {}
        if message.get("role") == "tool":
            blocks = {"tool_result": 0}
        elif message.get("role") == "assistant":
            blocks = {"reasoning": 0}
        self.items.append(ViewItem(message=message, occ_id=f"occ{seq}", seq=seq,
                                   alias=f"A{seq:05d}", blocks=blocks))
        if ingress:
            for key in ("content", "reasoning_content"):
                if isinstance(message.get(key), str):
                    self.ingress += self.counter.count_cached(message[key])
            for call in message.get("tool_calls") or []:
                self.ingress += self.counter.count_cached(call["function"]["arguments"])
        return len(self.items) - 1

    def user(self, lo, hi):
        self.user_n += 1
        host = self.add({"role": "user", "content": self.text.make(self.rng.randint(lo, hi),
                                                                   code=False)}, ingress=True)
        self.request(host=host)

    def tool_group(self, out_tokens):
        i = len(self.items)
        call_id = f"call_{i:06d}"
        args = json.dumps({"command": f"python tools/check.py --step {i}",
                           "description": self.text.make(self.rng.randint(5, 20), False)})
        self.add({"role": "assistant", "content": None,
                  "reasoning_content": self.text.make(self.rng.randint(40, 300), False),
                  "tool_calls": [{"id": call_id, "type": "function",
                                  "function": {"name": "shell", "arguments": args}}]},
                 ingress=True)
        self.add({"role": "tool", "tool_call_id": call_id,
                  "content": self.text.make(out_tokens, code=True)}, ingress=True)
        self.request()

    def answer(self, lo, hi, rlo=20, rhi=200):
        self.add({"role": "assistant",
                  "content": self.text.make(self.rng.randint(lo, hi), False),
                  "reasoning_content": self.text.make(self.rng.randint(rlo, rhi), False)},
                 ingress=True)

    def done(self):
        return self.ingress >= self.ingress_target

    # -- one request ------------------------------------------------------------

    def _build(self, items, state):
        return build(items, tools=self.tools, render_kwargs=self.kw, budget=self.budget,
                     state=state, policy=self.view_policy, counter=self.counter)

    def warm(self):
        """What ``ViewEngine`` does after each build, while the upstream generates
        (D25): warm stubs off the request path. Not timed."""
        if self.warm_stubs:
            warm(self.items, tools=self.tools, render_kwargs=self.kw, budget=self.budget,
                 state=self.state, policy=self.view_policy, counter=self.counter)

    def _excerpt_source(self, host):
        for item in reversed(self.items[:host]):
            if item.message.get("role") == "tool":
                return item, "tool", "shell"
        for item in self.items[1:host]:
            if item.message.get("role") == "user":
                return item, "user", None
        return None, None, None

    def _block(self, host, target):
        src, role, tool = self._excerpt_source(host)
        if src is None:
            return None
        text = src.message["content"]
        added = self.counter.added_token_strings

        def rendered(n):
            return render_block([Excerpt(src.alias, 0, src.seq, role, tool, text[:n])],
                                added_tokens=added)

        if self.counter.count(rendered(1)) > target:
            return None
        lo, hi = 1, len(text)
        while lo < hi:  # largest prefix whose block fits
            mid = (lo + hi + 1) // 2
            if self.counter.count(rendered(mid)) <= target:
                lo = mid
            else:
                hi = mid - 1
        out = rendered(lo)
        return out, self.counter.count(out)

    def request(self, host=None):
        self.call_n += 1
        before = self.state
        t0 = time.perf_counter()
        try:
            base = self._build(self.items, self.state)
        except Exception as e:  # BudgetError: recorded, session continues
            self.errors.append(f"call {self.call_n}: {type(e).__name__}: {e}")
            return
        t_build = (time.perf_counter() - t0) * 1000
        view, t_second = base, None
        wants = host is not None and (self.arm == "every"
                                      or (self.arm == "third" and self.user_n % 3 == 1))
        if wants:
            charges = {i.excerpt[0]: i.excerpt[2] for i in self.items if i.excerpt}
            allocation = excerpt_allocation(
                self.budget, fixed_tokens=base.fixed_tokens,
                included=[charges[b] for b in base.included_excerpts if b in charges],
                policy=self.policy)
            ev = {"call": self.call_n, "allocation": allocation,
                  "cap": self.budget.excerpt_per_message,
                  "starved": allocation < self.budget.excerpt_per_message, "charge": 0}
            block = (self._block(host, min(self.budget.excerpt_per_message, allocation))
                     if allocation >= MIN_BLOCK else None)
            if block is not None:
                rendered, charge = block
                ev["charge"] = charge
                self.items[host] = dataclasses.replace(
                    self.items[host], excerpt=(f"blk{self.call_n}", rendered, charge))
                t1 = time.perf_counter()
                view = self._build(self.items, base.state)
                t_second = (time.perf_counter() - t1) * 1000
                if view.moved:
                    # ArchiveHandler._bound persists only the base view's state.
                    self.second_build_moves += 1
            self.excerpt_events.append(ev)
        # The proxy persists the base view's state; the next request starts from it.
        self.state = base.state
        t2 = time.perf_counter()
        layout = self.counter.layout(view.messages, self.tools, **self.kw)
        t_layout = (time.perf_counter() - t2) * 1000
        rec = {"call": self.call_n, "ingress": self.ingress, "tokens": view.tokens,
               "moved": base.moved, "t_build_ms": t_build, "t_second_ms": t_second,
               "t_layout_ms": t_layout, "new_user": host is not None}
        if base.moved:
            s = base.state
            rec["kinds"] = [k for k, changed in (
                ("watermark", s.watermark_seq != before.watermark_seq),
                ("collapse", s.collapse_seq != before.collapse_seq),
                ("oversized", s.oversized != before.oversized),
                ("excerpt_omitted", s.omitted_excerpts != before.omitted_excerpts)) if changed]
            rec["omitted_now"] = len(s.omitted_excerpts - before.omitted_excerpts)
        if self.prev_layout is not None:
            lcp = common_prefix(self.prev_layout.ids, layout.ids)
            est = self.cm.expected(self.prev_layout, layout)
            rec["reread_lcp"] = len(layout.ids) - lcp
            rec["reread_est"] = len(layout.ids) - est
            rec["lcp"], rec["est"] = lcp, est
        rec["len"] = len(layout.ids)
        if len(layout.ids) != view.tokens:
            self.errors.append(f"call {self.call_n}: layout {len(layout.ids)} != tokens {view.tokens}")
        if view.tokens > self.budget.input_budget:
            self.errors.append(f"call {self.call_n}: {view.tokens} over budget")
        self.prev_layout = layout
        self.records.append(rec)
        self.warm()

    def rebuild_timing(self, n=15):
        """Identical rebuilds of the final state: every fragment cached."""
        times = []
        for _ in range(n):
            t = time.perf_counter()
            self._build(self.items, self.state)
            times.append((time.perf_counter() - t) * 1000)
        return times


def drive(s: Session):
    rng = s.rng
    while not s.done():
        if s.workload == "tool_heavy":
            s.user(30, 200)
            for _ in range(rng.randint(4, 12)):
                s.tool_group(int(math.exp(rng.uniform(math.log(200), math.log(6000)))))
            s.answer(50, 300)
        elif s.workload == "chatty":
            s.user(10, 150)
            s.answer(30, 400)
        else:
            s.user(30, 100)
            s.tool_group(rng.randint(3000, 15000))
            s.answer(50, 300)


def summarize(s: Session) -> dict:
    recs = s.records
    ingress = s.ingress
    per100k = 100_000 / ingress
    moves = [r for r in recs if r["moved"]]
    appends = [r for r in recs if not r["moved"] and "reread_lcp" in r]
    kinds: dict[str, int] = {}
    for r in moves:
        for k in r["kinds"]:
            kinds[k] = kinds.get(k, 0) + 1
    gaps = [b["ingress"] - a["ingress"] for a, b in zip(moves, moves[1:])]
    rr = [r["reread_lcp"] for r in moves if "reread_lcp" in r]
    rre = [r["reread_est"] for r in moves if "reread_est" in r]
    omissions = sum(r.get("omitted_now", 0) for r in moves)
    ev = s.excerpt_events
    builds = [r["t_build_ms"] for r in recs[5:]]
    builds_move = [r["t_build_ms"] for r in recs[5:] if r["moved"]]
    builds_plain = [r["t_build_ms"] for r in recs[5:] if not r["moved"]]
    seconds = [r["t_second_ms"] for r in recs if r["t_second_ms"] is not None]
    rebuild = s.rebuild_timing()
    return {
        "workload": s.workload, "budget": s.budget.input_budget, "arm": s.arm,
        "requests": len(recs), "user_messages": s.user_n, "ingress_tokens": ingress,
        "history_items": len(s.items), "final_view_tokens": recs[-1]["tokens"] if recs else None,
        "moves": len(moves), "moves_per_100k": r2(len(moves) * per100k),
        "move_kinds": kinds,
        "watermark_per_100k": r2(kinds.get("watermark", 0) * per100k),
        "collapse_per_100k": r2(kinds.get("collapse", 0) * per100k),
        "ingress_between_moves": {"n": len(gaps), "median": r2(pct(gaps, 50)),
                                  "p10": r2(pct(gaps, 10)), "mean": r2(statistics.fmean(gaps))
                                  if gaps else None},
        "reread_per_move_lcp": {"median": r2(pct(rr, 50)), "p95": r2(pct(rr, 95)),
                                "mean": r2(statistics.fmean(rr)) if rr else None},
        "reread_per_move_est": {"median": r2(pct(rre, 50)), "p95": r2(pct(rre, 95)),
                                "mean": r2(statistics.fmean(rre)) if rre else None,
                                "label": "estimate (StrataCacheModel)"},
        "append_reread_lcp_median": r2(pct([r["reread_lcp"] for r in appends], 50)),
        "append_reread_est_median": r2(pct([r["reread_est"] for r in appends], 50)),
        "amortized_reread_per_ingress_lcp": round(sum(rr) / ingress, 4),
        "amortized_reread_per_ingress_est": round(sum(rre) / ingress, 4),
        "all_calls_prefill_per_ingress_est": round(
            sum(r.get("reread_est", r["len"]) for r in recs) / ingress, 3),
        "excerpt": {
            "wanted": len(ev), "selected": sum(1 for e in ev if e["charge"]),
            "starved": sum(e["starved"] for e in ev),
            "starvation_share": round(sum(e["starved"] for e in ev) / len(ev), 3) if ev else None,
            "zero_allocation": sum(1 for e in ev if e["allocation"] < MIN_BLOCK),
            "mean_charge": r2(statistics.fmean([e["charge"] for e in ev])) if ev else None,
            "cap": s.budget.excerpt_per_message, "q": s.budget.recall_excerpts,
            "omissions": omissions, "omissions_per_100k": r2(omissions * per100k),
            "second_build_moves": s.second_build_moves,
        },
        "latency_ms": {
            "build_p50": r2(pct(builds, 50)), "build_p95": r2(pct(builds, 95)),
            "build_max": r2(max(builds)) if builds else None,
            "build_move_p50": r2(pct(builds_move, 50)), "build_move_p95": r2(pct(builds_move, 95)),
            "build_plain_p50": r2(pct(builds_plain, 50)),
            "build_plain_p95": r2(pct(builds_plain, 95)),
            "second_build_p50": r2(pct(seconds, 50)), "second_build_p95": r2(pct(seconds, 95)),
            "identical_rebuild_p50": r2(pct(rebuild, 50)),
            "identical_rebuild_p95": r2(pct(rebuild, 95)),
            "layout_p50": r2(pct([r["t_layout_ms"] for r in recs[5:]], 50)),
            "layout_p95": r2(pct([r["t_layout_ms"] for r in recs[5:]], 95)),
        },
        "errors": s.errors[:10], "error_count": len(s.errors),
    }


def environment() -> dict:
    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                                  check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    import tokenizers

    return {"commit": os.environ.get("BENCH_COMMIT") or git("rev-parse", "HEAD"),
            "dirty": os.environ.get("BENCH_DIRTY") or git("status", "--porcelain"),
            "python": platform.python_version(), "tokenizers": tokenizers.__version__,
            "platform": platform.platform(), "processor": platform.processor(),
            "cpus": os.cpu_count(), "profile": "strata-0.1.48",
            "view_policy": dataclasses.asdict(ViewPolicy()),
            "budget_policy": dataclasses.asdict(BudgetPolicy())}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--ingress", type=int, default=300_000, help="ingress tokens per session")
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--workloads", default=",".join(WORKLOADS))
    p.add_argument("--budgets", default=",".join(BUDGETS))
    p.add_argument("--arms", default=",".join(ARMS))
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-warm", action="store_true",
                   help="skip the engine's off-path stub warm-up (R12's cold-stub numbers)")
    p.add_argument("--out", type=Path)
    a = p.parse_args(argv)
    pin = pins.load()
    base = json.loads(load_exchanges(LIVE_DIR)[0].request_body)
    report = {"environment": environment(), "ingress_target": a.ingress, "seed": a.seed,
              "runs": []}
    for wl in a.workloads.split(","):
        for bname in a.budgets.split(","):
            for arm in a.arms.split(","):
                # A fresh counter per session, so arms sharing content do not inherit each
                # other's fragment caches; a throwaway session (other seed) warms the
                # process: template, tokenizer and the system/tools fragments.
                counter = tokens.Tokens(pin)
                drive(Session(wl, BUDGETS[bname], "none", a.seed + 1000, counter, base, 20_000))
                t = time.perf_counter()
                s = Session(wl, BUDGETS[bname], arm, a.seed, counter, base, a.ingress,
                            warm=not a.no_warm)
                drive(s)
                out = summarize(s)
                out["wall_s"] = round(time.perf_counter() - t, 1)
                report["runs"].append(out)
                if not a.json:
                    lat = out["latency_ms"]
                    ex = out["excerpt"]
                    print(f"{wl:10} {out['budget']:>6} {arm:5} req={out['requests']:>4} "
                          f"moves/100K={out['moves_per_100k']:>5} kinds={out['move_kinds']} "
                          f"gap~{out['ingress_between_moves']['median']} "
                          f"reread lcp~{out['reread_per_move_lcp']['median']} "
                          f"est~{out['reread_per_move_est']['median']} "
                          f"amort={out['amortized_reread_per_ingress_lcp']}/"
                          f"{out['amortized_reread_per_ingress_est']} "
                          f"starve={ex['starvation_share']} omit/100K={ex['omissions_per_100k']} "
                          f"2nd-moves={ex['second_build_moves']} "
                          f"build p50/p95={lat['build_p50']}/{lat['build_p95']} "
                          f"err={out['error_count']} ({out['wall_s']}s)", flush=True)
    if a.out:
        a.out.write_text(json.dumps(report, indent=2))
    if a.json:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
