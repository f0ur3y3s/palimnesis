"""Seeded civic dispatch histories for heldout5."""

from __future__ import annotations

import argparse
import json
import random
import string
from pathlib import Path

import independence
from needle_gen import Builder, read_result
from needle_strata import LEVELS, check_declared, coverage, strata
from palimnesis.upstreams.strata import tokens


ROOT = Path(__file__).resolve().parent
THEMES = (
    ("natatoriumshift", "pool lane reservations", "deck", "lane", "timetable"),
    ("glazetread", "winter footpath dispatch", "beat", "ramp", "salt cache"),
    ("ordinancefolio", "public hearing book indexing", "folio", "ordinance", "citation slip"),
    ("drawspanwatch", "lift bridge tender handoffs", "span", "beacon", "signal cabinet"),
)
PASTE_LIMIT = 18_000
ENCLOSURE_ROWS = 452


def _caps(rnd: random.Random) -> str:
    return "".join(rnd.choices(string.ascii_uppercase, k=5))


def _stamps(rnd: random.Random, noun: str, count: int) -> list[str]:
    sections = ("upland", "junction", "precinct", "foreshore", "concourse", "terminus")
    notes = ("night custodian signed", "paper duplicate retained", "supervisor initials missing",
             "relief desk reconciled", "noticeboard corrected", "counter copy collected")
    return [
        f"{noun}.{rnd.choice(sections)}/{i:04d} {rnd.randint(300000, 987654)} "
        f"crew={_caps(rnd)} custody={rnd.randint(1, 48):02d} {rnd.choice(notes)}"
        for i in range(count)
    ]


def build_history(number: int, seed: int) -> dict:
    project, remit, desk, asset, fixture = THEMES[number - 15]
    rnd = random.Random(seed)
    brief = Builder(rnd)
    checkpoint = f"{_caps(rnd)}^{seed * 7}"
    nearby = [f"{_caps(rnd)}^{(seed + i) * 7}" for i in (41, 46)]
    branch = f"{project}-council/{seed}-renewal"
    old_branch = f"{project}-council/{seed}-intake"
    protocol = f"{desk}.{seed}-gate"
    old_protocol = f"{desk}.{seed}-crate"
    retry = f"{_caps(rnd)}~~{seed + 191}"
    retry_decoy = f"{_caps(rnd)}~~{seed + 223}"
    test_marker = f"{_caps(rnd)}!{seed * 13}"
    report_stamp = f"{_caps(rnd)}:{seed * 131}~{desk}"
    hold = f"{_caps(rnd)}::{seed * 109}"
    address = f"{_caps(rnd)}?{seed * 17}"
    transit = f"{seed * 19}%{_caps(rnd)}"
    wallet = f"{_caps(rnd)}/@{seed * 23}"
    approval = f"{_caps(rnd)}@={seed * 29}"
    dockets = [f"{_caps(rnd)}@={(seed + i) * 29}" for i in (12, 26, 31)]

    brief.user(f"Council IT opened `{project}` for {remit}. Begin with `{old_branch}` and "
               f"bring the audit trail together with the {desk} circulation sheet.")
    brief.say("First snag: the kiosk archive omits the locker checksum from its header.")
    huge_result = _stamps(rnd, asset, 390)
    huge_result[173] = f"commissioning test blue-slip reconciliation ready for {fixture}"
    huge_result[174] = f"commissioning test {test_marker} reconciled {fixture} custody"
    path = f"artifacts/{project}_commissioning.trace"
    brief.tool("read", {"filePath": path, "offset": 1, "limit": len(huge_result)},
               read_result(path, huge_result))
    brief.user(f"Tender ledger initially specifies `{old_protocol}` for the {desk} handoff.")
    brief.say(f"Signed key-tray recipient: `{address}`. Leave its punctuation intact on the handover card.")
    path = f"artifacts/{project}_inventory.tsv"
    shelf = _stamps(rnd, fixture, 495)
    brief.tool("read", {"filePath": path, "offset": 1, "limit": len(shelf)}, read_result(path, shelf))
    brief.user(f"Public counter handoff requires the permit latch `{hold}`. Treat that docket "
               f"as binding whenever the {asset} queue is handed over.")
    brief.say(f"Transit marker recorded as `{transit}` from the blue custody envelope.")
    path = f"artifacts/{project}_recheck.tsv"
    shelf = _stamps(rnd, desk, 635)
    brief.tool("read", {"filePath": path, "offset": 1, "limit": len(shelf)}, read_result(path, shelf))
    brief.user(f"Retrieve the actual {desk} intake failure from the relay audit. Two neighboring "
               f"warnings arrived during clock synchronization.")
    brief.tool("bash", {"command": f"cat traces/{project}_intake.log", "description": f"Show {desk} intake"},
               f"clock skew detail={nearby[0]}\nintake denied {desk} fingerprint={checkpoint}\n"
               f"wall timer detail={nearby[1]}\n")
    path = f"artifacts/{project}_arrival.tsv"
    shelf = _stamps(rnd, asset, 465)
    brief.tool("read", {"filePath": path, "offset": 1, "limit": len(shelf)}, read_result(path, shelf))
    brief.say(f"Dispatch wallet embossed `{wallet}`. Its deposit book was checked with the clerk.")
    path = f"artifacts/{project}_reassigned.tsv"
    shelf = _stamps(rnd, desk, 515)
    brief.tool("read", {"filePath": path, "offset": 1, "limit": len(shelf)}, read_result(path, shelf))
    brief.say(f"Branch correction filed: retire `{old_branch}` and use `{branch}` for council review.")
    brief.user(f"Cabinet numbering revision confirmed. `{protocol}` replaces `{old_protocol}` on the handoff.")
    brief.say("Clerk approved the revised circulation packet for the morning window.")

    def q(qid: str, category: str, text: str, answer: str, *, parts: list[str] | None = None,
          restart: bool = False) -> dict:
        return {"kind": "question", "id": f"h{number}{qid.lower()}", "qid": qid,
                "category": category, "text": text, "answer": answer,
                "parts": parts or [answer], "evidence": parts or [answer], "restart_before": restart}

    def paste(pid: str, text: str) -> dict:
        return {"kind": "paste", "id": f"h{number}{pid.lower()}", "text": text}

    test = f"tests.test_{project}_desk_handoff"
    command = f"python -m unittest {test} -v"
    stale_hold = f"{desk}-provisional"
    output = (f"test_custody_has_seal ({test}.DeskHandoffTest) ... FAIL\n\n"
              f"AssertionError: {stale_hold!r} is still provisional\n")
    p2 = f"{desk} override card for {fixture}#executive"
    accepted = f"{_caps(rnd)}##{seed * 43}"
    rejected = [f"{_caps(rnd)}##{(seed + i) * 43}" for i in (11, 19, 37)]
    steps = [
        q("Q1", "identifier", f"Which fingerprint blocked {desk} intake in the relay audit? Cite the mark alone.", checkpoint),
        paste("P1", f"Clerk's dispatch carbon for {remit}. Acknowledge receipt without triage.\n"
              f"{asset} circulation revision assessed; binding dispatch imprint={report_stamp}."),
        q("Q2", "superseded", "Name our replacement branch for council review. I need its literal checkout label.", branch),
        q("Q3", "superseded", f"What revised cabinet code belongs on the {desk} handoff now? Bare value, please.", protocol),
        *[paste(f"P2a{i}", f"Attached {asset} inventory tranche {i}; file against council circulation.\n"
                + "\n".join(_stamps(rnd, f"{project}_surplus", ENCLOSURE_ROWS))) for i in range(1, 4)],
        paste("P2", f"Photocopy from the {desk} control leaf for {remit}. Retain for lookup.\n"
              f"training override receipt {rejected[0]} retry={retry_decoy}\n"
              f"depot rehearsal override receipt {rejected[1]}\n"
              f"{p2} override receipt {accepted} retry={retry}\n"
              f"archived green duplicate override receipt {rejected[2]}\n"),
        *[paste(f"P2b{i}", f"Consecutive {desk} tally enclosure {i}; record receipt only.\n"
                + "\n".join(_stamps(rnd, f"{project}_intake", ENCLOSURE_ROWS))) for i in range(1, 3)],
        q("Q4", "irrelevant_matches", f"Which override receipt is on `{p2}`? Ignore the rehearsal duplicates.", accepted),
        q("Q5", "vague", "Read me its retry seal, just the exact inscription.", retry),
        paste("P3", f"Dispatch approval leaf filed for {fixture}. Mark received.\n"
              f"exercise receipts: {dockets[0]}, {dockets[1]}, {dockets[2]}\n"
              f"custodian's operative approval: {approval}"),
        q("Q6", "oversized_read", f"Find blue-slip reconciliation in the long commissioning trace. "
          f"Which test marker stands on the following record? Give that marker.", test_marker),
        dict(q("Q7", "mid_task", f"Execute `{command}`. With files untouched, report the binding "
               f"permit latch the failing handoff should carry, exactly as directed.", hold),
             mid_task={"command": command, "output": output}),
        q("Q8", "multi_fact", "Transcribe the handover triplet in key-tray recipient, transit marker, "
          "wallet order. Separate inscriptions with a single vertical bar.", "|".join([address, transit, wallet]),
          parts=[address, transit, wallet]),
        q("Q9", "restart_multi_eviction", "Retrieve the binding dispatch imprint from the clerk's first carbon. "
          "Give its entire mark.", report_stamp, restart=True),
        q("Q10", "vague", "And the custodian's operative approval for that packet? Just its receipt.", approval),
    ]
    brief.user(steps[0]["text"])
    workspace = {
        "tests/__init__.py": "",
        f"tests/test_{project}_desk_handoff.py": (
            f"import unittest\nfrom {project}.cabinet import permit_latch\n\n"
            "class DeskHandoffTest(unittest.TestCase):\n    def test_custody_has_seal(self):\n"
            f"        self.assertNotEqual(permit_latch(), {stale_hold!r}, 'provisional latch still in use')\n"),
        f"{project}/__init__.py": "",
        f"{project}/cabinet.py": f"def permit_latch():\n    return {stale_hold!r}\n",
    }
    history = {"id": f"ho5-h{number}", "seed": seed, "project": project, "set": "heldout5",
               "generator": "eval/needle_gen_ho5_d.py", "import": brief.messages, "steps": steps,
               "workspace": workspace, "shell": [{"match": test, "output": output}]}
    labels = strata(history)
    for step in steps:
        if step["kind"] == "question":
            step["strata"] = {dimension: labels[step["id"]][dimension] for dimension in LEVELS}
    return history


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    histories = [build_history(number, 7400 + number - 15) for number in range(15, 19)]
    counts = coverage(histories)
    minimum = {"source_role": 7, "placement": 9, "planned_depth": 9, "distractors": 7}
    coverage_ok = all(count >= minimum[dimension] for dimension, levels in counts.items()
                      for count in levels.values())
    directory = ROOT / "needles" / "heldout5"
    paths = [directory / f"{history['id']}.json" for history in histories]
    if not args.check:
        directory.mkdir(parents=True, exist_ok=True)
    present = [path for path in paths if path.is_file()]
    independence_report = (independence.check(present, independence.default_sets(), independence.default_exempt())
                           if args.check else {})
    ok = coverage_ok
    for path, history in zip(paths, histories, strict=True):
        data = (json.dumps(history, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        strata_ok = not check_declared(history)
        sizes_ok = all(tokens.count(step["text"]) < PASTE_LIMIT for step in history["steps"]
                       if step["kind"] == "paste")
        if args.check:
            good = path.is_file() and path.read_bytes() == data and independence_report[str(path)]["pass"]
        else:
            good = strata_ok and sizes_ok and coverage_ok
            if good:
                path.write_bytes(data)
        good = good and strata_ok and sizes_ok
        print(f"{history['id']}: {'pass' if good else 'fail'}")
        ok = ok and good
    print(f"coverage: {'pass' if coverage_ok else 'fail'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
