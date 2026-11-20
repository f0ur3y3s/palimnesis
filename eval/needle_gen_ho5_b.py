"""Generate the five archival-workflow histories assigned to heldout5 author B."""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path

from independence import check, default_exempt, default_sets
from needle_gen import Builder, read_result
from needle_strata import LEVELS, strata
from palimnesis.upstreams.strata.tokens import count


@dataclass(frozen=True)
class Collection:
    project: str
    material: str
    cue: str
    stations: tuple[str, ...]
    operations: tuple[str, ...]


COLLECTIONS = (
    Collection("vellumgate", "illuminated leaves", "VLG",
               ("pigment bench", "leaf cradle", "raking lamp", "gilt station"),
               ("compare daughter scans", "calibrate folio scale", "capture marginalia")),
    Collection("papertide", "watermarked broadsides", "PTD",
               ("light table", "damp cabinet", "registration rig", "dry shelf"),
               ("align chain marks", "trace watermark", "isolate pulp shadows")),
    Collection("cylinderbraid", "wax field recordings", "CBR",
               ("stylus rack", "horn booth", "sleeve trolley", "pickup arm"),
               ("trace groove wear", "index speech breaks", "capture stylus hiss")),
    Collection("reelcradle", "lantern-slide plates", "RCR",
               ("dark slide", "frost plate", "projection cart", "iris carriage"),
               ("check border bleed", "balance plate tint", "read frame mat")),
    Collection("pressshoal", "movable-type specimen books", "PSH",
               ("proof table", "chase drawer", "composing stick", "gauge bed"),
               ("specify foundry face", "catalogue sorts", "capture ink body")),
)

FIRST = 6
SEED = 7200
OUTPUT = Path(__file__).parent / "needles" / "heldout5"
PASTE_LIMIT = 18000


def value(rng: random.Random, collection: Collection, left: str, right: str) -> str:
    tail = "".join(rng.choices("BCDFGHJKMNPQRSTVWXYZ", k=4))
    return f"{collection.cue}{left}{rng.randrange(100000, 1000000)}{right}{tail}"


def register_rows(
    rng: random.Random, collection: Collection, section: str, budget: int,
) -> list[str]:
    """Compose a synthetic diagnostics register of approximately budget tokens."""
    rows = []
    subtotal = 0
    while subtotal < budget:
        batch = []
        for slot in range(len(rows) + 1, len(rows) + 61):
            station = rng.choice(collection.stations)
            action = rng.choice(collection.operations)
            outcome = rng.choice(("scored", "verified", "repeat requested", "queued"))
            batch.append(
                f"{section}/{slot:04d} | {station} | {action} | "
                f"band {rng.randrange(1, 60):02d} | drift {rng.randrange(200):03d} | {outcome}"
            )
        subtotal += count("\n".join(batch))
        rows.extend(batch)
    return rows


def read_register(
    conversation: Builder, rng: random.Random, collection: Collection, section: str, budget: int,
) -> None:
    path = f"audit/{collection.project}/{section}.tsv"
    bench = rng.choice(collection.stations)
    action = rng.choice(collection.operations)
    conversation.user(f"Registrar review, {bench}: open `{path}` and sample rows marked {action}.")
    conversation.tool("read", {"path": path}, read_result(
        path, register_rows(rng, collection, section, budget),
    ))
    conversation.say(f"`{section}` contains the sampled {bench} annotations.")


def thirds(rows: list[str]) -> tuple[list[str], list[str], list[str]]:
    first = len(rows) // 3
    second = 2 * len(rows) // 3
    return rows[:first], rows[first:second], rows[second:]


def build_history(number: int, seed: int) -> dict:
    rng = random.Random(seed)
    collection = COLLECTIONS[number - FIRST]
    project = collection.project
    condition = value(rng, collection, "@", "^")
    retired_pass, approved_pass = (value(rng, collection, "+", "+") for _ in range(2))
    retired_cue, approved_cue = (value(rng, collection, ":", ":") for _ in range(2))
    drawer_ids = [value(rng, collection, "^", "~") for _ in range(4)]
    proof_drawer, catalogue_drawer, microfilm_drawer, thrashed_drawer = drawer_ids
    backing, backup_backing = (value(rng, collection, "~", "~") for _ in range(2))
    case = f"review_{project}_witness_{rng.randrange(100000, 1000000)}"
    next_case = f"review_{project}_witness_{rng.randrange(100000, 1000000)}"
    handoff = value(rng, collection, "/", "!")
    bay, idle_bay = (value(rng, collection, "#", "%") for _ in range(2))
    shelf = value(rng, collection, "%", "#")
    packet = value(rng, collection, "@", "=")
    manifest_version = value(rng, collection, "=", ";")
    renamed_reader = f"{project}_readback_{rng.randrange(100000, 1000000)}"

    history = Builder(rng)
    history.user(
        f"Exporter repairs for {collection.material}: set the initial latch to `{retired_pass}` "
        f"and relay cue to `{retired_cue}`. Registrar's required handoff label is `{handoff}`."
    )
    history.say(
        f"Proof latch correction: use `{approved_pass}` from here. "
        f"Use receiving bay `{bay}` for acceptance; `{idle_bay}` stands idle."
    )
    history.user(f"Swap the relay cue to `{approved_cue}`. The acceptance shelf is `{shelf}`.")
    history.tool("read", {"path": f"accessions/{project}/checkout.txt"}, (
        f"export={project}\nacceptance packet: {packet}\n"
        "The packet leaves with the registrar's signed slip."
    ))
    history.say("Routing reconciled against the acquisition slip.")

    for batch in range(11):
        read_register(history, rng, collection, f"intake-{batch:02d}", 8150)
    history.user(f"Find the intake condition raised at {collection.stations[0]}.")
    history.tool("shell", {"command": f"cat audit/{project}/intake-exception.txt"}, (
        f"stage={project} acquisition-entry\ncondition={condition}\n"
        f"asset={collection.material}\nconfirmed-by=registrar"
    ))
    history.say("The registrar flagged this accession for manual review.")
    for batch in range(4):
        read_register(history, rng, collection, f"handover-{batch:02d}", 8550)

    history.user("Inspect catalogue-reader drawers across editions and proof fixtures.")
    history.tool("read", {"path": f"accessions/{project}/readers.ini"}, (
        f"[proof]\ndrawer={proof_drawer}\n[production_catalogue]\n"
        f"drawer={catalogue_drawer}\n[microfilm_copy]\ndrawer={microfilm_drawer}\n"
        f"[damaged_fixture]\ndrawer={thrashed_drawer}"
    ))
    history.say("Readback fixtures specify distinct drawer tokens.")

    p1 = register_rows(rng, collection, "receipt", 8000)
    p1.insert(135, f"Approved export version {manifest_version}; accession status confirmed.")
    p2 = thirds(register_rows(rng, collection, "catalogue-audit", 38500))
    p2[-1][155:155] = [
        f"production_catalogue backing={backing}",
        f"microfilm_copy backing={backup_backing}",
    ]
    p3 = thirds(register_rows(rng, collection, "proof-audit", 38500))
    p3[-1].insert(135, f"Alias migration: retired reader legacy_{project} -> {renamed_reader}")
    oversized_rows = p2[-1] if number < FIRST + 2 else p3[-1]
    center = len(oversized_rows) // 2
    oversized_rows[center:center] = [
        "Ordered full witness run", f"{case} ... ok", f"{next_case} ... ok",
        f"review_{project}_witness_{rng.randrange(100000, 1000000)} ... ok",
        f"review_{project}_witness_{rng.randrange(100000, 1000000)} ... ok",
    ]
    audit_name = "catalogue audit" if oversized_rows is p2[-1] else "proof audit"
    mid_test = f"test_{project}_acceptance.py"
    command = f"python -m unittest {mid_test.removesuffix('.py')}"
    failure = (
        "F\n"
        f"FAIL: test_acceptance_label ({mid_test.removesuffix('.py')}.HandoffTest)\n"
        "AssertionError: unexpectedly None : Acquisition handoff label is unset\n"
        "Ran 1 test\n\nFAILED (failures=1)"
    )

    def question(qid: int, category: str, text: str, answer: str, **extra) -> dict:
        return {
            "kind": "question", "id": f"h{number}q{qid}", "qid": f"Q{qid}",
            "category": category, "text": text, "answer": answer,
            "parts": [answer], "evidence": [answer], "restart_before": False, **extra,
        }

    def paste(pid: str, intro: str, rows: list[str]) -> dict:
        text = intro + "\n\n```text\n" + "\n".join(rows) + "\n```"
        if count(text) > PASTE_LIMIT:
            raise ValueError(f"ho5-h{number} P{pid}: paste exceeds {PASTE_LIMIT} tokens")
        return {"kind": "paste", "id": f"h{number}p{pid}", "text": text}

    def audit_attachment(
        pid: int, title: str, chunks: tuple[list[str], list[str], list[str]],
    ) -> list[dict]:
        return [
            paste(
                f"{pid}{suffix}",
                f"{title} attachment {page}/3. Reply `{title.lower()} {page} filed`.",
                rows,
            )
            for page, (suffix, rows) in enumerate(zip(("a", "b", ""), chunks, strict=True), 1)
        ]

    steps = [
        question(1, "identifier", (
            f"Which intake condition did {collection.material} raise? Code only."
        ), condition),
        paste("1", "Registrar receipt dump follows. Reply `receipt filed`.", p1),
        question(2, "superseded", (
            "Give the revised proof latch, bare identifier."
        ), approved_pass),
        question(3, "superseded", "State the live relay cue, by itself.", approved_cue),
        *audit_attachment(2, "Catalogue audit", p2),
        question(4, "irrelevant_matches", (
            "Which drawer token is live for production catalogue readback? Token only."
        ), catalogue_drawer),
        question(5, "vague", "And its backing? Return the token.", backing),
        *audit_attachment(3, "Proof audit", p3),
        question(6, "oversized_read", (
            f"Consult {audit_name}'s complete witness run. Name the check after `{case}`, "
            "omitting the result."
        ), next_case),
        question(7, "mid_task", (
            f"Execute `{command}` without edits. For the failure, give the registrar's "
            "required label by itself."
        ), handoff, mid_task={"command": command, "output": failure}),
        question(8, "multi_fact", (
            "From intake handover, reconstruct the acceptance route. Format: `bay|shelf|packet`."
        ), f"{bay}|{shelf}|{packet}", parts=[bay, shelf, packet], evidence=[
            f"Use receiving bay `{bay}` for acceptance",
            f"acceptance shelf is `{shelf}`",
            f"acceptance packet: {packet}",
        ]),
        question(9, "restart_multi_eviction", (
            "Find the approved export version in the registrar receipt dump. Version only."
        ), manifest_version, restart_before=True),
        question(10, "vague", (
            "Retrieve that retired reader's replacement alias. Alias only."
        ), renamed_reader),
    ]
    history.user(steps[0]["text"])
    workspace = {
        f"{project}_policy.py": "HANDOFF_LABEL = None\n",
        mid_test: (
            f"import unittest\nfrom {project}_policy import HANDOFF_LABEL\n\n"
            "class HandoffTest(unittest.TestCase):\n"
            "    def test_acceptance_label(self):\n"
            "        self.assertIsNotNone(HANDOFF_LABEL, 'Acquisition handoff label is unset')\n"
        ),
    }
    result = {
        "id": f"ho5-h{number}", "seed": seed, "project": project, "set": "heldout5",
        "generator": "eval/needle_gen_ho5_b.py", "import": history.messages, "steps": steps,
        "workspace": workspace, "shell": [{"match": command, "output": failure}],
    }
    classified = strata(result)
    for step in steps:
        if step["kind"] == "question":
            labels = classified[step["id"]]
            step["strata"] = {key: labels[key] for key in LEVELS}
            for key, levels in LEVELS.items():
                if labels[key] not in levels:
                    raise ValueError(
                        f"{result['id']} {step['qid']}: {key}={labels[key]}, "
                        f"depth={labels.get('depth_tokens')}"
                    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.check:
        OUTPUT.mkdir(parents=True, exist_ok=True)
    paths = []
    exact = {}
    for offset in range(len(COLLECTIONS)):
        history = build_history(FIRST + offset, SEED + offset)
        path = OUTPUT / f"{history['id']}.json"
        content = (json.dumps(history, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        paths.append(path)
        if not args.check:
            path.write_bytes(content)
        exact[path] = path.is_file() and path.read_bytes() == content
    if not args.check:
        return 0
    reports = check(paths, default_sets(), default_exempt()) if all(exact.values()) else {}
    outcomes = {
        path: exact[path] and reports.get(str(path), {}).get("pass", False)
        for path in paths
    }
    for path, passed in outcomes.items():
        print(f"{path.stem}: {'pass' if passed else 'fail'}")
    return 0 if all(outcomes.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
