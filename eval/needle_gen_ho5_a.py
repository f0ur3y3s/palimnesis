"""Generate and verify the five farm-record histories authored for heldout5."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import random

from independence import check, default_exempt, default_sets
from needle_gen import Builder, read_result
from needle_strata import LEVELS, coverage, strata
from palimnesis.upstreams.strata import tokens


OUT = Path(__file__).resolve().parent / "needles" / "heldout5"
THEMES = (
    ("maple", "sugarbush tapping", ("spile", "sapline", "sugaring", "vacuum", "evaporator")),
    ("saffron", "saffron curing", ("crocus", "stigma", "sifting", "curing", "sachet")),
    ("trellis", "cane trellis surveys", ("bramble", "crossarm", "sucker", "wire", "cane")),
    ("hedgerow", "shelterbelt planting", ("whip", "windbreak", "guard", "mulch", "stake")),
    ("millet", "millet threshing", ("panicle", "winnow", "stubble", "screen", "chaff")),
)


def records(rng: random.Random, vocab: tuple[str, ...], target: int) -> list[str]:
    lines = []
    while tokens.count("\n".join(lines)) < target:
        for _ in range(32):
            kind, station = rng.sample(vocab, k=2)
            lines.append(
                f"parcel={rng.randint(110, 999)} {kind}/{station} "
                f"moisture={rng.randrange(3, 98)}.{rng.randrange(10)} "
                f"grade={rng.choice(('clear', 'watch', 'resample', 'stored'))} "
                f"ticks={rng.randrange(10000, 99999)}"
            )
    return lines


def build_history(index: int, seed: int) -> dict:
    rng = random.Random(seed)
    project, subject, vocab = THEMES[index]
    hid = f"ho5-h{index + 1}"
    # Distinct punctuation and widths separate the families of candidate answers.
    docket = f"FURROW@{rng.randrange(100000, 999999)}@SEAL"
    near_docket = f"FURROW@{rng.randrange(100000, 999999)}@TRIAL"
    layout = f"RACK!{rng.randrange(100, 999)}!LIVE"
    old_layout = f"RACK!{rng.randrange(100, 999)}!OLD"
    dispatch = f"BARROW%{rng.randrange(1000, 9999)}%ACTIVE"
    old_dispatch = f"BARROW%{rng.randrange(1000, 9999)}%VOID"
    chamber = f"CRIB~{rng.randrange(10000, 99999)}~RUN"
    check_interval = f"STRIP<{rng.randrange(10000, 99999)}>TICKS"
    threshold = f"KEEL+{rng.randrange(1000000, 9999999)}+SET"
    old_threshold = f"KEEL+{rng.randrange(1000000, 9999999)}+TEST"
    endpoint = f"PLINTH#{rng.randrange(10000, 99999)}#POST"
    channel = f"VANE|{rng.randrange(100000, 999999)}|STEM"
    plot_mode = f"DRILL^{rng.randrange(1000000, 9999999)}^LANE"
    intake = f"RIND{{{rng.randrange(10000, 99999)}}}"
    patrol = f"BINE&{rng.randrange(1000, 9999)}&LOOP"
    row_ids = [f"TINE={n:06}=PASS" for n in rng.sample(range(100000, 999999), 12)]
    test_path = f"tests/test_{project}_trial.py"
    cmd = f"python -m pytest {test_path} -q"

    b = Builder(rng)
    b.user(f"Our {subject} workbench has a private audit queue. Begin with the field notebook.")
    b.say(f"The paving of {project}'s audit route starts at endpoint {endpoint}.")
    b.user(f"Route its work tickets through circuit {channel}. Keep it with this survey.")
    b.tool("read", {"path": "handoff/bed-choice.txt"}, f"Bench operating mode: {plot_mode}.")
    b.say(f"The unconfirmed routing slip bore {old_dispatch}.")
    b.user(f"The binding threshold stamp for the field acceptance test is {threshold}.")
    b.user(f"An abandoned trial notebook carried {old_threshold}; discard that annotation.")
    b.say(f"The previous shelf layout was {old_layout}. Wait for the replacement sheet.")
    b.user(f"Inspect the old {project} sample docket {near_docket}; it belongs to the pilot.")

    large_path = f"logs/{project}-sequence.audit"
    large_rows = records(rng, vocab, target=29_000)
    offset = rng.randrange(100, len(large_rows) - 20)
    large_rows[offset:offset] = [f"Acceptance marker {code}" for code in row_ids]
    b.user(f"Read the full checkpoint ordering under {large_path}; don't correct the ledger.")
    b.tool("read", {"path": large_path}, read_result(large_path, large_rows))
    b.say("The checkpoint order is intact. I left the ledger as filed.")

    def state_fact(role: str, label: str, value: str) -> None:
        line = f"{label} {value}"
        if role == "user_instruction":
            b.user(line)
            b.say(f"I'll keep this {project} note attached to the workbench.")
        elif role == "assistant_statement":
            b.user(f"Resolve the {project} register entry before the next parcel check.")
            b.say(line)
        elif role == "tool_output":
            file = f"queues/{project}-register.txt"
            b.user(f"Check the workbench register at {file}.")
            b.tool("read", {"path": file}, line)
            b.say("The register is current.")
        else:
            raise ValueError(role)

    chamber_fact = f"Binding cabinet for {subject}:"
    if index < 2:
        early_role = ("user_instruction", "assistant_statement")[index]
        state_fact(early_role, chamber_fact, chamber)

    def imported_filler(name: str, target: int) -> None:
        path = f"ledgers/{project}-{name}.audit"
        b.user(f"Compare the {project} tray readings in {path} with our survey rows.")
        b.tool("read", {"path": path}, read_result(path, records(rng, vocab, target)))
        b.say(f"The {name} tray block is aligned with the parcel ledger.")

    for name, budget in (("sill", 15000), ("dawn", 15000), ("purlin", 15000),
                         ("shaded", 15000), ("gate", 12000)):
        imported_filler(name, budget)
    docket_roles = (
        "user_instruction", "assistant_statement", "tool_output", "assistant_statement", "tool_output",
    )
    dispatch_roles = (
        "tool_output", "user_instruction", "assistant_statement", "user_instruction", "tool_output",
    )
    state_fact(docket_roles[index], f"The approved {project} audit docket is", docket)
    imported_filler("fieldside", 3500)
    state_fact(dispatch_roles[index], f"Use the revised {subject} dispatch slip:", dispatch)
    imported_filler("bench", 13000)
    imported_filler("drain", 9500)

    def q(qid: str, category: str, text: str, answer: str, *,
          parts: list[str] | None = None, restart: bool = False) -> dict:
        parts = [answer] if parts is None else parts
        return {"kind": "question", "id": hid + qid.lower(), "qid": qid, "category": category,
                "text": text, "answer": answer, "parts": parts, "evidence": parts,
                "restart_before": restart}

    def paste(pid: str, heading: str, target: int, facts: list[str] | None = None) -> dict:
        rows = records(rng, vocab, target)
        if facts:
            position = rng.randrange(40, len(rows) - 40)
            rows[position:position] = facts
        text = f"{heading} Please acknowledge filing without processing the readings.\n\n"
        return {"kind": "paste", "id": hid + pid.lower(), "text": text + "\n\n```\n"
                + "\n".join(rows) + "\n```"}

    mid = q(
        "Q7", "mid_task",
        f"Execute `{cmd}`. Leave the trial untouched and report the original acceptance "
        f"stamp the {project} trial should expect. Stamp only.",
        threshold,
    )
    mid_out = f"FAILED {test_path}::test_acceptance_stamp - found retired stamp {old_threshold}"
    mid["mid_task"] = {"command": cmd, "output": mid_out}
    cabinet_options = [f"CRIB~{n}~STAGING" for n in rng.sample(range(10000, 99999), 3)]
    steps = [
        q("Q1", "identifier", f"Which audit docket was approved for {project}? Return its code.",
          docket),
        paste("P1", f"File the signed {project} bench handover.", 11500,
              [f"Ratified shelf layout: {layout}", f"First intake tray reference: {intake}"]),
        q("Q2", "superseded",
          f"Which signed shelf layout supersedes the provisional {project} layout? Layout code only.",
          layout),
        q("Q3", "superseded",
          f"Give the replacement dispatch slip for {subject}, without commentary.", dispatch),
        paste("L1", f"Add the {project} west-parcel weighings to the notebook.", 15900),
        paste("L2", f"Bind these {project} sample manifests behind the audit copy.", 15900,
              None if index < 2 else [f"{chamber_fact} {chamber}"]),
        paste("L3", f"File this {project} parcel reconciliation as received.", 15900),
        paste("P2", f"Store the afternoon {project} inspections with the working sheets.", 15900,
              [*cabinet_options, f"Recheck spacing for the binding cabinet: {check_interval}"]),
        q("Q4", "irrelevant_matches",
          f"Which cabinet actually binds for {subject}, excluding staging inventory? Cabinet code.",
          chamber),
        q("Q5", "vague", "Its recheck spacing, please. Give the recorded token.", check_interval),
        paste("P3", f"Keep these {project} closing readings under today's yard tab.", 15900,
              [f"Patrol loop for the closing round: {patrol}"]),
        q("Q6", "oversized_read",
          f"In the full checkpoint ledger, what acceptance marker directly followed {row_ids[4]}? "
          "Give the marker without the label.", row_ids[5]),
        mid,
        q("Q8", "multi_fact",
          f"Print the {project} audit destination as endpoint/circuit/mode, keeping its codes intact.",
          f"{endpoint}/{channel}/{plot_mode}", parts=[endpoint, channel, plot_mode]),
        q("Q9", "restart_multi_eviction",
          f"What first intake tray reference came on the signed {project} bench handover? "
          "Return only that reference.", intake, restart=True),
        q("Q10", "vague", "Before closing up, which loop did we file for patrol? Code only.", patrol),
    ]
    b.user(steps[0]["text"])
    test_source = (
        f"def test_acceptance_stamp():\n    recorded = {old_threshold!r}\n"
        "    accepted = None  # Consult the binding field requirement.\n"
        "    assert accepted == recorded, 'trial is tagged with the retired stamp'\n"
    )
    history = {"id": hid, "seed": seed, "project": project, "set": "heldout5",
               "generator": "eval/needle_gen_ho5_a.py", "import": b.messages, "steps": steps,
               "workspace": {test_path: test_source},
               "shell": [{"match": f"pytest {test_path}", "output": mid_out}]}
    actual = strata(history)
    for step in steps:
        if step["kind"] == "question":
            step["strata"] = {dim: actual[step["id"]][dim] for dim in LEVELS}
            if any(level not in LEVELS[dim] for dim, level in step["strata"].items()):
                raise ValueError(f"{step['id']}: source or depth outside declared levels")
    return history


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--check", action="store_true", help="verify reproduction and independence")
    args = p.parse_args()
    histories = [build_history(i, 7100 + i) for i in range(len(THEMES))]
    cov = coverage(histories)
    if any(n < (12 if dim in ("placement", "planned_depth") else 9)
           for dim, levels in cov.items() for n in levels.values()):
        print("author A coverage: fail")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    paths = [OUT / f"{h['id']}.json" for h in histories]
    independence = check(paths, default_sets(), default_exempt()) if args.check else {}
    ok = True
    for path, history in zip(paths, histories):
        encoded = (json.dumps(history, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        if args.check:
            passed = path.read_bytes() == encoded and independence[str(path)]["pass"]
            print(f"{history['id']}: {'pass' if passed else 'fail'}")
            ok = ok and passed
        else:
            path.write_bytes(encoded)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
