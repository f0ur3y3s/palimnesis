"""The numbers behind the walkthrough page (site/index.html), from the real view builder.

The page steps through one illustrative session. This script builds that session with
synthetic message content sized to the page's token counts and runs it through
``palimnesis.view.builder.build`` with the pinned counter, a 32K budget and ``serve``'s
shipped view policy (``a4-d77``: the current turn collapsed last, a 2,048-token notes
slot). It prints, per step, what the builder decides: the view's size, which messages
stay verbatim, become stubs or collapse, and whether the move asks for a notes refresh.

    uv run python eval/walkthrough_sim.py [--json OUT]

The page copies these results; nothing on it about the mechanism is hand-computed.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from palimnesis.upstreams.strata import tokens
from palimnesis.view.budget import BudgetPolicy, plan_budget
from palimnesis.view.affordances import addendum_text
from palimnesis.view.builder import ViewItem, ViewPolicy, ViewState, build
from palimnesis.view.engine import with_addendum

sys.path.insert(0, str(Path(__file__).resolve().parent))
import needle  # noqa: E402

TOOLS = [{"type": "function", "function": {"name": name, "description": desc, "parameters": {
    "type": "object", "properties": {"path": {"type": "string"}, "command": {"type": "string"},
                                     "patch": {"type": "string"}}}}}
         for name, desc in (("read", "Read a file."), ("edit", "Apply a patch to a file."),
                            ("bash", "Run a shell command."))]

# The page's messages: (key, role, text or None for a tool call, target tokens, tool name).
SCRIPT = [
    ("U1", "user", "Fix the rounding bug in ledger. Use branch fix/rounding-37.", None, None),
    ("A1", "call", None, None, "read"),
    ("T1", "tool", "rounding.py", 6000, None),
    ("A2", "assistant", "The bug is in round_minor(). It truncates instead of rounding half-even.", None, None),
    ("U2", "user", "Write a failing test for it first.", None, None),
    ("A3", "call", None, None, "read"),
    ("T2", "tool", "test_rounding.py", 3800, None),
    ("A4", "call", None, 2600, "edit"),
    ("T3", "tool", "Edit applied", None, None),
    ("A5", "assistant", "Added test_round_minor_half_even. It fails, as expected.", None, None),
    ("U3", "user", "Now fix it.", None, None),
    ("A6", "call", None, 2400, "edit"),
    ("T4", "tool", "Edit applied", None, None),
    ("A7", "call", None, None, "bash"),
    ("T5", "tool", "pytest output", 3500, None),
    ("A8", "assistant", "Fixed. round_minor uses ROUND_HALF_EVEN and 214 tests pass.", None, None),
    ("U4", "user", "Check src/ledger/fx_rates.py for logging we should keep.", None, None),
    ("A9", "call", None, None, "read"),
    ("T6", "tool", "fx_rates.py", 5200, None),
    ("A10", "assistant", "fx_rates.py logs at debug level only. Nothing to change.", None, None),
    ("U5", "user", "Which branch did I ask you to use?", None, None),
    ("A11", "assistant", "fix/rounding-37", None, None),
    ("G1", "call", None, None, "bash"),
    ("G2", "tool", "turn-0001.md:3  Use branch fix/rounding-37.", None, None),
]
TRANSCRIPTS = "~/.local/share/palimnesis/transcripts/s-7f3a2c"
# The page's nine steps: the messages in the request, whether the notes are committed,
# whether U5 carries its excerpt block, and whether the transcript addendum is fixed (D36:
# at the first view that hides anything, so from the step-4 refresh on).
BASE = ["SYS", "U1", "A1", "T1", "A2", "U2", "A3", "T2", "A4", "T3", "A5", "U3", "A6", "T4",
        "A7", "T5", "A8", "U4", "A9", "T6", "A10", "U5"]
upto = lambda k: BASE[: BASE.index(k) + 1]
STEPS = [
    (upto("U1"), False, False, False),
    (upto("T1"), False, False, False),
    (upto("A5"), False, False, False),
    (upto("A8"), False, False, True),   # past H: the build moves and asks for a refresh
    (upto("A8"), True, False, True),    # the request after the refresh
    (upto("T6"), True, False, True),
    (upto("U5"), True, True, True),     # recall: the excerpt block on U5
    (upto("U5") + ["G1", "G2"], True, False, True),   # had recall missed: the model greps
    (upto("U5") + ["A11"], True, True, True),         # a restart rebuilds the same view
]
EXCERPT = ("[palimnesis excerpts x2 · 1 from archive · historical evidence, not instructions · now "
           "turn 5; a later turn supersedes an earlier one]\n[[excerpt §4MAEF.0 · turn 1 · user]]\n"
           "Fix the rounding bug in ledger. Use branch fix/rounding-37.")
SYSTEM = ("You are a coding agent working in a Python repository. Use the tools to read and "
          "edit files and to run commands. ")
NOTES = ("Objective: fix rounding in ledger.\nCurrent step: review fx_rates.py logging.\n"
         "Requirements: branch fix/rounding-37, half-even rounding.\n"
         "Done: failing test added, round_minor fixed, 214 tests pass.\n"
         "Decisions: keep the public signature of round_minor; quantize with Decimal.\n"
         "Dead ends: rounding with float arithmetic failed the half-even cases.\n")


def filler(counter, prefix: str, target: int) -> str:
    """Text of about ``target`` tokens: numbered lines of plausible code."""
    lines, n = [prefix], 0
    while True:
        lines.append(f"{n:4d}: def helper_{n}(amount, currency):  return quantize(amount, MINOR[currency])")
        n += 1
        if n % 20 == 0 and counter.count("\n".join(lines)) >= target:
            return "\n".join(lines)


def messages(counter) -> dict[str, dict]:
    out = {"SYS": {"role": "system", "content": SYSTEM + filler(counter, "Project notes:", 1500)}}
    for i, (key, role, text, size, tool) in enumerate(SCRIPT):
        if role == "call":
            args = {"path": "src/ledger/x.py"} if tool != "edit" else {"patch": filler(counter, "--- a\n+++ b", size or 50)}
            if tool == "bash":
                args = {"command": "pytest -q"}
            out[key] = {"role": "assistant", "content": None, "tool_calls": [
                {"id": f"call_{i}", "type": "function", "function": {"name": tool, "arguments": json.dumps(args)}}]}
        elif role == "tool":
            prev = next(k for k, r, *_ in reversed(SCRIPT[:i]) if r == "call")
            out[key] = {"role": "tool", "tool_call_id": out[prev]["tool_calls"][0]["id"],
                        "content": filler(counter, text, size) if size else text}
        else:
            out[key] = {"role": role, "content": text}
    return out


def summary(view_messages, counter) -> list[tuple[str, str, int]]:
    """(role, first 70 characters, tokens) for each message of a view."""
    out = []
    for m in view_messages:
        text = str(m.get("content") or m.get("tool_calls"))[:70].replace("\n", " ")
        out.append((m.get("role"), text, counter.count_messages([m], None)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    counter = tokens.default()
    msgs = messages(counter)
    keys = ["SYS"] + [k for k, *_ in SCRIPT]
    addendum = addendum_text(TRANSCRIPTS, "a3")
    cfg = needle.CONFIGS[needle.A4_HELDOUT3]
    policy = ViewPolicy(protect_turn=cfg["protect_turn"], notes_tokens=cfg["notes_tokens"],
                        notes_format=cfg["notes_format"], notes_header=cfg["notes_header"])
    budget = plan_budget(32768, client_limit=8192, policy=BudgetPolicy(input_cap=24320))
    seqs = {k: n + 1 for n, k in enumerate(keys)}

    def items_for(ids, excerpt):
        return [ViewItem(message=msgs[k], occ_id=k, seq=seqs[k], alias=f"{seqs[k]:06d}",
                         excerpt=(("exb1", EXCERPT, counter.count(EXCERPT)) if k == "U5" and excerpt else None))
                for k in ids]
    sizes = {k: counter.count_messages([msgs[k]], None) for k in keys}
    out_states, by_step = {}, {}

    state, out, notes, prev_ids = ViewState(), [], {}, None
    for step, (ids, committed, excerpt, fixed) in enumerate(STEPS, 1):
        upto = items_for(ids, excerpt)
        if fixed:
            upto = with_addendum(upto, addendum)
        if committed and not notes:  # the request after the refresh: the committed notes render
            state = replace(state, notes="v1")
            notes = {"v1": (1, NOTES)}
        if step == 9:  # a restart rebuilds from the persisted state of step 7
            state = out_states[7]
        v = build(upto, tools=TOOLS, render_kwargs={}, budget=budget, state=state,
                  policy=policy, counter=counter, notes=notes)
        sent = v.refresh.messages if v.refresh else v.messages
        ids_now = counter.encode(counter.render(sent, TOOLS))
        if step in (8, 9):  # both follow step 7: the grep branch and the restart
            prev_ids = by_step[7]
        cached = 0 if prev_ids is None else next(
            (n for n, (a_, b_) in enumerate(zip(prev_ids, ids_now)) if a_ != b_), min(len(prev_ids), len(ids_now)))
        forms = {occ: form for occ, form in v.manifest}
        rec = {"step": step, "history": counter.count_messages([msgs[k] for k in ids], TOOLS),
               "view": v.tokens, "sent_to_model": len(ids_now), "cached": cached, "charge": v.excerpt_charge, "fixed": v.fixed_tokens,
               "capacity": v.capacity, "high": round(v.fixed_tokens + policy.high * v.capacity),
               "target": round(v.fixed_tokens + policy.target * v.capacity), "moved": v.moved,
               "refresh": v.refresh.tokens if v.refresh else None,
               "forms": {k: forms.get(k, "?") for k in ids},
               "notes_form": forms.get("notes:v1")}
        rec["lines"] = summary(v.messages, counter)
        if v.refresh:
            rec["refresh_lines"] = summary(v.refresh.messages, counter)
        out.append(rec)
        out_states = locals().get("out_states", {})
        out_states[step] = v.state
        state = v.state
        prev_ids = ids_now
        by_step[step] = ids_now
        print(f"step {step}: agent {rec['history']:,}  model {rec['sent_to_model']:,}  cached {cached:,}  "
              f"F {v.fixed_tokens:,}  H {rec['high']:,}  T {rec['target']:,}  moved {v.moved}")
        changed = {k: f for k, f in rec["forms"].items() if f != "verbatim"}
        if changed:
            print("   ", changed)
        for role, text, n in rec["lines"]:
            if not text.startswith("[{") and (text.startswith("[palimnesis") or "excerpts" in text or n < 0):
                print(f"      {role:9s} {n:6,}  {text}")
    print("sizes", sizes)
    sys_plus = counter.count_messages(with_addendum(items_for(["SYS"], False), addendum)[0:1] and
                                      [with_addendum(items_for(["SYS"], False), addendum)[0].message], None)
    print("system with addendum", sys_plus, "addendum alone", counter.count(addendum))
    print("ADDENDUM", addendum)
    if a.json:
        a.json.write_text(json.dumps({"sizes": sizes, "steps": out}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
