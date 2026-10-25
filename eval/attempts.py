"""Attempts of held-out evaluation runs and which one counts (D44.7).

A run directory ``RUN`` holds ``RUN/attempts.json`` and one records directory per
attempt, ``RUN/records/attempt-NNN/``. Every invocation of the needle driver or the task
runner is a new attempt with a fresh number; an existing attempt directory is never
reused or removed, so a first attempt's data is always kept. Workspaces, OpenCode homes
and transcript roots live in a separate tree (``ws_root/attempt-NNN/``) that holds no
run records.

The manifest records, per attempt: its number, kind (``needles`` or ``task``), config
or arm, the history or task ids, the reason (``initial`` or why it reruns), timestamps,
status and directories. By default the latest attempt that includes an id is the
designated one for that id; earlier attempts of the same id are listed as superseded,
with the reason the later one gave.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

MANIFEST = "attempts.json"


def default_ws_root(run: Path) -> Path:
    """Beside ``RUN``, never inside it: ``<parent>/<RUN name>-ws``."""
    run = Path(run).resolve()
    return run.parent / f"{run.name}-ws"


def _inside(a: Path, b: Path) -> bool:
    a, b = Path(a).resolve(), Path(b).resolve()
    return a == b or b in a.parents


def load(run: Path) -> list[dict]:
    p = Path(run) / MANIFEST
    return json.loads(p.read_text(encoding="utf-8"))["attempts"] if p.exists() else []


def _save(run: Path, attempts: list[dict]) -> None:
    p = Path(run) / MANIFEST
    tmp = p.with_name(p.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps({"attempts": attempts}, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def new_attempt(run: Path, *, kind: str, config: str, ids: list[str], reason: str | None,
                ws_root: Path | None = None, extra: dict | None = None) -> dict:
    """Register a new attempt and create its records and workspace directories.

    A rerun of any id already attempted under the same kind and config needs a reason
    (D44.7); the first attempt's reason is ``initial``."""
    run = Path(run).resolve()
    run.mkdir(parents=True, exist_ok=True)
    ws_root = Path(ws_root).resolve() if ws_root else default_ws_root(run)
    if _inside(ws_root, run) or _inside(run, ws_root):
        raise ValueError(f"workspace root {ws_root} and run directory {run} must not nest")
    attempts = load(run)
    before = {i for a in attempts if a["kind"] == kind and a["config"] == config for i in a["ids"]}
    again = sorted(before & set(ids))
    if again and not reason:
        raise ValueError(f"rerun of {', '.join(again)} needs --reason (D44.7)")
    n = max((a["attempt"] for a in attempts), default=0) + 1
    name = f"attempt-{n:03d}"
    records, ws = run / "records" / name, ws_root / name
    if records.exists() or ws.exists():
        raise FileExistsError(f"{records} or {ws} already exists; attempts are never reused")
    records.mkdir(parents=True)
    ws.mkdir(parents=True)
    rec = {"attempt": n, "kind": kind, "config": config, "ids": list(ids),
           "reason": reason or "initial", "reruns": again, "started": time.time(),
           "finished": None, "status": "running", "records": str(records), "ws": str(ws),
           **(extra or {})}
    attempts.append(rec)
    _save(run, attempts)
    return rec


def finish_attempt(run: Path, n: int, status: str, **fields) -> None:
    attempts = load(run)
    for a in attempts:
        if a["attempt"] == n:
            a.update(status=status, finished=time.time(), **fields)
    _save(run, attempts)


def designate(attempts: list[dict], kind: str, config: str,
              override: dict[str, int] | None = None) -> tuple[dict[str, dict], list[dict]]:
    """({id: designated attempt}, superseded) for one kind and config. The designated
    attempt is the latest that includes the id, unless ``override`` names one. Each
    superseded entry gives the id, the attempt, its status and the reason the
    designated attempt was run."""
    mine = sorted((a for a in attempts if a["kind"] == kind and a["config"] == config),
                  key=lambda a: a["attempt"])
    by_id: dict[str, list[dict]] = {}
    for a in mine:
        for i in a["ids"]:
            by_id.setdefault(i, []).append(a)
    chosen, superseded = {}, []
    for i, lst in by_id.items():
        want = (override or {}).get(i)
        pick = next((a for a in lst if a["attempt"] == want), None) if want else lst[-1]
        if pick is None:
            raise ValueError(f"attempt {want} does not include {i}")
        chosen[i] = pick
        for a in lst:
            if a is not pick:
                superseded.append({"id": i, "attempt": a["attempt"], "status": a["status"],
                                   "superseded_by": pick["attempt"], "reason": pick["reason"]})
    return chosen, superseded
