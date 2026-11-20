"""Build the four clinic-operations histories assigned to heldout5 author C."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import independence
import needle_strata
from needle_gen import Builder, read_result

from palimnesis.upstreams.strata import tokens

OUT = Path(__file__).resolve().parent / "needles" / "heldout5"
THEMES = (
    ("arcfit", "orthodontic tray intake", "molar", "tray", "impression", "liner"),
    ("canalbench", "earmold remakes", "vent", "mold", "earpiece", "seal"),
    ("lensbench", "optician lens returns", "prism", "frame", "coating", "hinge"),
    ("rimguide", "mobility chair fitting", "castor", "axle", "cushion", "footrest"),
)


def trace(rnd, theme, label, size):
    """Render a bounded diagnostic export, with varied records from this clinic bench."""
    project, _, *components = theme
    states = ("reconciled", "queued", "verified", "returned", "shelved")
    rows = []
    for row in range(size):
        part = rnd.choice(components)
        state = rnd.choice(states)
        rows.append(
            f"{project}/{label} frame={row:04d} stock={part} unit={rnd.randrange(1000):03d} "
            f"checkpoint={state} duration={rnd.randrange(1000)}ms bin={rnd.choice(components)}"
        )
    return "\n".join(rows)


def replay_padding(builder, rnd, theme, target):
    """Add completed diagnostics until the import approaches the requested token offset."""
    project, work, *_ = theme
    used = sum(tokens.count(message["text"]) for message in needle_strata.defined_transcript(
        {"import": builder.messages, "steps": []}))
    while target - used > 1000:
        stage = len(builder.messages)
        cap = min(target - used, 7700)
        sample = trace(rnd, theme, f"inspection{stage}", 48)
        rows = int(cap * 48 / tokens.count(sample))
        output = trace(rnd, theme, f"inspection{stage}", rows)
        builder.user(f"Audit the {work} checkpoint export {stage} for unresolved batches.")
        command = f"python -m {project}.history inspection{stage}"
        builder.tool("shell", {"command": command}, output)
        builder.say(f"Checkpoint {stage} reconciles against the bench ledger.")
        latest = {"import": builder.messages[-4:], "steps": []}
        used += sum(tokens.count(message["text"]) for message in needle_strata.defined_transcript(latest))


def paste_body(rnd, theme, label, facts, target):
    sample = trace(rnd, theme, label, 64)
    remaining = target - tokens.count("\n".join(facts))
    rows = int(remaining * 64 / tokens.count(sample))
    return "\n".join([*facts, trace(rnd, theme, label, rows)])


def build_history(number, seed):
    rnd = random.Random(seed)
    theme = THEMES[number - 11]
    project, work, first, second, third, fourth = theme
    code = project.upper()
    b = Builder(rnd)

    incident = f"{code}^{rnd.randrange(110000, 900000)}^INTAKE"
    old_branch = f"bench/{project}-prep-{rnd.randrange(1000, 9000)}"
    branch = f"bench/{project}-{first}-{rnd.randrange(1000, 9000)}"
    old_profile = f"{code}+{rnd.randrange(1000, 9000)}+LEGACY"
    profile = f"{code}+{rnd.randrange(10000, 90000)}+CURRENT"
    active = f"{code}!{rnd.randrange(10000, 90000)}cohort"
    queue_mode = f"{code}@{rnd.randrange(100, 800)}~guide"
    other_mode = f"{code}@{rnd.randrange(800, 990)}~backup"
    offline_mode = f"{code}@{rnd.randrange(800, 990)}~offline"
    demo_mode = f"{code}@{rnd.randrange(800, 990)}~sample"
    lead_test = f"test_transfer_{rnd.randrange(1010000, 9900000)}_OPEN"
    next_test = f"test_transfer_{rnd.randrange(1010000, 9900000)}_CLOSED"
    old_manifest = f"{code}:{rnd.randrange(10000, 45000)}~OLD"
    manifest = f"{code}:{rnd.randrange(55000, 99000)}~NEW"
    target = str(rnd.randrange(10300000, 93000000))
    actual = int(target) // 4
    fixture = f"{first}#{project}#{rnd.randrange(100000, 500000)}"
    slot = f"{second}|{rnd.randrange(100000, 500000)}|{third}"
    dispatch = f"{code}/{rnd.randrange(500000, 980000)}/{fourth}"
    retired_helper = f"wrap_{first}_{rnd.randrange(100000, 500000)}_{fourth}"
    helper = f"label_{first}_{rnd.randrange(500000, 990000)}_{fourth}"
    setting = f"{code}_RECHECK_MILLISECONDS"
    command = f"python -m unittest discover -s tests -p test_{project}_recheck.py -v"

    b.user(f"Triage the {work} regression on `{old_branch}`. Keep the bench on profile `{old_profile}`.")
    b.tool("shell", {"command": f"python -m {project}.intake_scan"},
           f"Intake failed for {first}: primary incident {incident}.\n")
    b.say(f"{work.capitalize()} stopped while correlating {first} with the physical ledger.")
    b.user(f"Review reconciliation preferences for the live {second} station.")
    b.say(f"Live {second} station selects cohort {active} during reconciliation.")
    b.user(f"Inspect the station fixtures before touching {third}.")
    path = f"fixtures/{project}_stations.ini"
    fixture_modes = [
        f"[fixture_{part}]\ncohort={code}!{rnd.randrange(10000, 90000)}{word}"
        for part, word in [(first, "staged"), (third, "dummy"), (fourth, "fixture")]
    ]
    b.tool("read", {"path": path}, read_result(path, "\n".join(fixture_modes).splitlines()))
    b.say(f"Fixture cohorts exercise {third} and {fourth} without affecting live picks.")

    b.user(f"Run the exhaustive transfer checks for {work}.")
    before = trace(rnd, theme, "transfer_open", 760)
    after = trace(rnd, theme, "transfer_close", 370)
    b.tool("shell", {"command": f"python -m {project}.transfer_checks --verbose"},
           f"{before}\n{lead_test} ... ok\n{next_test} ... ok\n{after}")
    b.say(f"Transfer checks completed; {fourth} alignment stays within the lane.")

    replay_padding(b, rnd, theme, 51500)
    b.user(f"Move the bench patch to `{branch}`; retire the earlier prep branch.")
    b.say(f"Patch branch switched for {work}.")
    replay_padding(b, rnd, theme, 59000)
    b.user(f"Discontinue the old station profile. Use `{profile}` for {work} instead.")
    b.say("The counter is pointing at its replacement profile.")
    replay_padding(b, rnd, theme, 78500)
    b.user(f"Check the contingency routing modes for this same {second} station.")
    b.say(f"Live fallback is {queue_mode}. Training uses {other_mode}, offline practice uses "
          f"{offline_mode}, and the tour kiosk uses {demo_mode}.")

    history_id = f"ho5-h{number}"

    def question(qid, category, text, answer, *, parts=None, evidence=None, restart=False):
        return {"kind": "question", "id": f"{history_id}{qid.lower()}", "qid": qid,
                "category": category, "text": text, "answer": answer,
                "parts": parts or [answer], "evidence": evidence or parts or [answer],
                "restart_before": restart}

    def paste(pid, wrapper, label, facts, target_tokens):
        body = paste_body(rnd, theme, label, facts, target_tokens)
        return {"kind": "paste", "id": f"{history_id}{pid.lower()}",
                "text": f"{wrapper}\n\n```\n{body}\n```"}

    step1 = question("Q1", "identifier",
                     f"Recover the primary incident code from the failed {first} intake scan. Code alone.",
                     incident)
    first_log = [
        f"Bench release manifest currently promoted: {manifest}",
        f"Superseded manifest from prior inspection: {old_manifest}",
    ]
    bulletin = [
        f"Repair bulletin for {work}: {setting} must equal {target}.",
        f"Dispatch route authority: {dispatch}",
        f"Replacement parts ledger fixture: {fixture}",
        f"Physical scan slot: {slot}",
        f"API rename approved: {retired_helper} -> {helper}",
    ]
    mid_output = (f"test_recheck_interval (test_{project}_recheck.BenchRecheck.test_recheck_interval) ... FAIL\n"
                  f"AssertionError: {actual} != None : {setting} disagrees with the repair bulletin\n"
                  "\nRan 1 test\nFAILED (failures=1)\n")
    steps = [
        step1,
        paste("P1", "Manifest transcript for the bench handoff. Acknowledge receipt.",
              "manifest_trace", first_log, 9300),
        question("Q2", "superseded", f"Name the replacement patch branch for {work}. Branch string only.", branch),
        question("Q3", "superseded",
                 f"Which station profile replaced the retired setting for {work}? Give its identifier.", profile),
        paste("P2", "Set this reconciliation audit aside for the bench binder. Reply 'received'.",
              "reconcile_audit", [], 19700),
        question("Q4", "irrelevant_matches",
                 f"Which cohort does the live {second} station select, excluding fixture cohorts? Value only.", active),
        question("Q5", "vague", "And its live fallback? Return the mode by itself.", queue_mode),
        paste("P3", "Keep the signed repair bulletin and diagnostic attachment together. Confirm receipt only.",
              "bulletin_attachment", bulletin, 19200),
        question("Q6", "oversized_read",
                 f"Identify the check immediately following `{lead_test}` in the exhaustive transfer output. Name only.",
                 next_test),
        dict(question("Q7", "mid_task",
                      f"Run `{command}` with sources intact. Quote the bulletin's required numeric setting "
                      "for the failing check.", target, evidence=[f"{setting} must equal {target}"]),
             mid_task={"command": command, "output": mid_output}),
        question("Q8", "multi_fact",
                 "Compose the transfer coordinates from the repair bulletin as fixture;scan-slot;dispatch-route. "
                 "Provide that composite alone.", f"{fixture};{slot};{dispatch}", parts=[fixture, slot, dispatch]),
        question("Q9", "restart_multi_eviction",
                 "Recover the promoted manifest identifier from the handoff transcript. Give that value alone.",
                 manifest, restart=True),
        question("Q10", "vague",
                 "Which public helper spelling replaced the retired one in the repair bulletin? Supply the new name.",
                 helper),
    ]
    b.messages.append({"role": "user", "content": step1["text"]})
    workspace = {
        f"src/{project}/recheck.py": f"{setting} = {actual}\n",
        f"tests/test_{project}_recheck.py": (
            "import sys\nimport unittest\nfrom pathlib import Path\n\n"
            'sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))\n'
            f"from {project}.recheck import {setting}\n\n\n"
            "class BenchRecheck(unittest.TestCase):\n"
            "    def test_recheck_interval(self):\n"
            f'        self.assertEqual({setting}, None, "{setting} disagrees with the repair bulletin")\n'
        ),
    }
    history = {"id": history_id, "seed": seed, "project": project, "set": "heldout5",
               "generator": "eval/needle_gen_ho5_c.py", "import": b.messages, "steps": steps,
               "workspace": workspace, "shell": [{"match": f"test_{project}_recheck.py", "output": mid_output}]}
    labels = needle_strata.strata(history)
    for step in steps:
        if step["kind"] == "question":
            step["strata"] = {axis: labels[step["id"]][axis] for axis in needle_strata.LEVELS}
    return history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check bytes, independence and strata")
    args = parser.parse_args()
    if not args.check:
        OUT.mkdir(parents=True, exist_ok=True)
    histories = [build_history(number, 7300 + number - 11) for number in range(11, 15)]
    paths = [OUT / f"{history['id']}.json" for history in histories]
    existing = [path for path in paths if path.is_file()]
    standalone = independence.check(existing, independence.default_sets(), independence.default_exempt()
                                    ) if args.check and existing else {}
    failed = False
    for path, history in zip(paths, histories):
        expected = (json.dumps(history, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if not args.check:
            path.write_bytes(expected)
        reproduced = path.is_file() and path.read_bytes() == expected
        independent = not args.check or standalone.get(str(path), {}).get("pass", False)
        declared = not needle_strata.check_declared(history)
        ok = reproduced and independent and declared
        print(f"{history['id']}: {'pass' if ok else 'fail'}")
        failed |= not ok
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
