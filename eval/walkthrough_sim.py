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
from palimnesis.view.builder import ViewItem, ViewPolicy, ViewState, build

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
]
# Steps: (last message in the history, notes committed, excerpt on U5).
STEPS = [("U1", False), ("T1", False), ("A5", False), ("A8", False), ("A8", True),
         ("T6", True), ("U5", True)]
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
            prev = next(k for k, *_ in reversed(SCRIPT[:i]) if k.startswith("A"))
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
    cfg = needle.CONFIGS[needle.A4_HELDOUT3]
    policy = ViewPolicy(protect_turn=cfg["protect_turn"], notes_tokens=cfg["notes_tokens"],
                        notes_format=cfg["notes_format"], notes_header=cfg["notes_header"])
    budget = plan_budget(32768, client_limit=8192, policy=BudgetPolicy(input_cap=24320))
    items = [ViewItem(message=msgs[k], occ_id=k, seq=n + 1, alias=f"{n + 1:06d}",
                      excerpt=(("exb1", EXCERPT, counter.count(EXCERPT)) if k == "U5" else None))
             for n, k in enumerate(keys)]
    sizes = {k: counter.count_messages([msgs[k]], None) for k in keys}

    state, out, notes = ViewState(), [], {}
    for step, (end, committed) in enumerate(STEPS, 1):
        upto = items[: keys.index(end) + 1]
        if committed and not notes:  # the request after the refresh: the committed notes render
            state = replace(state, notes="v1")
            notes = {"v1": (1, NOTES)}
        v = build(upto, tools=TOOLS, render_kwargs={}, budget=budget, state=state,
                  policy=policy, counter=counter, notes=notes)
        forms = {occ: form for occ, form in v.manifest}
        rec = {"step": step, "history": counter.count_messages([i.message for i in upto], TOOLS),
               "view": v.tokens, "charge": v.excerpt_charge, "fixed": v.fixed_tokens,
               "capacity": v.capacity, "high": round(v.fixed_tokens + policy.high * v.capacity),
               "target": round(v.fixed_tokens + policy.target * v.capacity), "moved": v.moved,
               "refresh": v.refresh.tokens if v.refresh else None,
               "forms": {k: forms.get(k, "?") for k in keys[: keys.index(end) + 1]},
               "notes_form": forms.get("notes:v1")}
        rec["lines"] = summary(v.messages, counter)
        if v.refresh:
            rec["refresh_lines"] = summary(v.refresh.messages, counter)
        out.append(rec)
        state = v.state
        print(f"step {step}: history {rec['history']:,}  view {v.tokens:,}  F {v.fixed_tokens:,}  "
              f"H {rec['high']:,}  T {rec['target']:,}  moved {v.moved}  refresh {rec['refresh']}")
        changed = {k: f for k, f in rec["forms"].items() if f != "verbatim"}
        if changed:
            print("   ", changed)
        for role, text, n in rec["lines"]:
            if not text.startswith("[{") and (text.startswith("[palimnesis") or "excerpts" in text or n < 0):
                print(f"      {role:9s} {n:6,}  {text}")
    print("sizes", sizes)
    if a.json:
        a.json.write_text(json.dumps({"sizes": sizes, "steps": out}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
