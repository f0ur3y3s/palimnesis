"""Phase 7 run order (plan §1.4, D111.6), deterministic from a seed.

    python eval/phase7_schedule.py --seed N --tasks ho4-t1,...,ho5-t20 [--out plan.json]

From ``random.Random(seed)``, in this order:

1. **Hosts.** Tasks are grouped by set (the id before ``-t``, e.g. ``ho4``), each set's
   tasks shuffled, the sets concatenated in sorted order, and the list dealt to the hosts
   in turn from a seeded starting host. Each host gets the same number of tasks within one,
   and the same number of each set's tasks within one. Both arms of a task run on its host,
   so a McNemar pair never spans hosts.
2. **Task order.** Each host's tasks in a seeded random order.
3. **Arm order.** For each task, its two arms in a seeded random order, run back to back.
4. **Repeats.** ``repeats`` tasks (5) drawn before any run, both arms, again in seeded
   order, on the task's own host after its primaries. They are descriptive only and never
   counted as pairs.

The same seed always gives the same plan; the JSON holds the seed and every input.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

HOSTS = ("pythia", "zeus")
ARMS = ("a4-d77", "a1")
REPEATS = 5


def set_of(task: str) -> str:
    """``ho5-t12`` -> ``ho5``."""
    return task.rsplit("-t", 1)[0]


def make_schedule(tasks: list[str], seed: int, *, hosts: tuple[str, ...] = HOSTS,
                  arms: tuple[str, ...] = ARMS, repeats: int = REPEATS) -> dict:
    if len(set(tasks)) != len(tasks):
        raise ValueError("task ids must be distinct")
    if repeats > len(tasks):
        raise ValueError("more repeats than tasks")
    rnd = random.Random(seed)
    by_set: dict[str, list[str]] = {}
    for t in sorted(tasks):
        by_set.setdefault(set_of(t), []).append(t)
    dealt: list[str] = []
    for s in sorted(by_set):
        group = list(by_set[s])
        rnd.shuffle(group)
        dealt += group
    start = rnd.randrange(len(hosts))
    task_host = {t: hosts[(start + i) % len(hosts)] for i, t in enumerate(dealt)}
    plan: dict[str, list[dict]] = {}
    for h in hosts:
        mine = [t for t in dealt if task_host[t] == h]
        rnd.shuffle(mine)
        plan[h] = []
        for t in mine:
            order = list(arms)
            rnd.shuffle(order)
            plan[h].append({"task": t, "set": set_of(t), "arms": order})
    rep = []
    for t in rnd.sample(sorted(tasks), repeats):
        order = list(arms)
        rnd.shuffle(order)
        rep.append({"task": t, "host": task_host[t], "arms": order})
    return {"seed": seed, "tasks": sorted(tasks), "hosts": plan,
            "task_host": dict(sorted(task_host.items())),
            "task_set": {t: set_of(t) for t in sorted(tasks)}, "repeats": rep,
            "arms": list(arms), "host_names": list(hosts)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--tasks", required=True, help="comma-separated task ids")
    ap.add_argument("--hosts", default=",".join(HOSTS))
    ap.add_argument("--repeats", type=int, default=REPEATS)
    ap.add_argument("--out", type=Path, help="write the JSON here (else stdout)")
    a = ap.parse_args(argv)
    plan = make_schedule(a.tasks.split(","), a.seed, hosts=tuple(a.hosts.split(",")),
                         repeats=a.repeats)
    text = json.dumps(plan, indent=1) + "\n"
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
