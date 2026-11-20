"""Unseen held-out sets: which they are, when they unlock, and their sealed hashes (Phase 7 S1).

    python eval/heldout.py status
    python eval/heldout.py seal --out eval/heldout_hashes.json PATH [PATH ...]
    python eval/heldout.py verify [--manifest eval/heldout_hashes.json]

**Unseen sets** (``UNSEEN_SETS``): ``heldout4`` (D96), ``heldout5`` and the ``heldout6``
reserve (D111.4). They stay unseen by the lead until the verdict (plan §1.1, step 5).

**Unlock.** A set is unlocked only when ``eval/heldout_unlock.json`` maps it to the
decision id of the frozen held-out protocol (``PROTOCOL_DECISION``, D115)::

    {"unlocked": {"heldout4": "D115", "heldout5": "D115"}}

and both hold:

- that decision has a heading (a line starting ``## D115:``) in ``docs/decisions/*.md``;
- the unlock file is committed: ``git ls-files`` lists it and ``git status --porcelain``
  shows no change to it.

Analysis tools (``state_eval``, ``report.py``) refuse a locked unseen set
(``require_unlocked``). Run drivers accept an unseen set only when it is unlocked and the
tree is clean (``run_refusal``).

**Sealed hashes.** ``eval/heldout_hashes.json`` maps each sealed file's repository path
(POSIX) to its SHA-256: ``{"files": {"eval/tasks/ho5_t1.py": "<hex>", ...}}``. ``seal``
writes it and ``verify`` checks the files against it. Both print paths and pass/fail only,
never file contents.

Task registries (``TASKS``) name task ids without needing their modules to exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
UNSEEN_SETS = ("heldout4", "heldout5", "heldout6")
PREFIX = {"heldout4": "ho4", "heldout5": "ho5", "heldout6": "ho6"}
PROTOCOL_DECISION = "D115"
UNLOCK_FILE = "eval/heldout_unlock.json"
HASHES_FILE = "eval/heldout_hashes.json"
DECISIONS_DIR = "docs/decisions"
# Task ids per unseen set (D96: ho4-t1..t5; D111.4: ho5-t1..t20 and the ho6 reserve).
TASKS = {"heldout4": [f"ho4-t{i}" for i in range(1, 6)],
         "heldout5": [f"ho5-t{i}" for i in range(1, 21)],
         "heldout6": [f"ho6-t{i}" for i in range(1, 11)]}


class Locked(ValueError):
    """An unseen set used before its unlock."""


def set_of_task(task_id: str) -> str | None:
    """The unseen set a task id belongs to by its prefix (``ho5-t3`` -> ``heldout5``)."""
    head = task_id.split("-", 1)[0]
    return next((s for s, p in PREFIX.items() if p == head), None)


def git_committed(path: str, root: Path = ROOT) -> bool:
    """``path`` (relative to ``root``) is tracked and has no uncommitted change."""
    tracked = subprocess.run(["git", "ls-files", "--", path], cwd=root, capture_output=True,
                             text=True)
    if tracked.returncode != 0 or not tracked.stdout.strip():
        return False
    status = subprocess.run(["git", "status", "--porcelain", "--", path], cwd=root,
                            capture_output=True, text=True)
    return status.returncode == 0 and not status.stdout.strip()


def decision_exists(decision: str, root: Path = ROOT) -> bool:
    """A heading ``## <decision>:`` in any ``docs/decisions/*.md``."""
    head = f"## {decision}:"
    for f in sorted((root / DECISIONS_DIR).glob("*.md")):
        if any(line.startswith(head)
               for line in f.read_text(encoding="utf-8", errors="replace").splitlines()):
            return True
    return False


def unlock_problem(set_name: str, *, root: Path = ROOT,
                   committed: bool | Callable[[str], bool] | None = None) -> str | None:
    """Why ``set_name`` is locked, or None when it is unlocked or not an unseen set.
    ``committed`` replaces the git check (a bool, or a function of the file's path)."""
    if set_name not in UNSEEN_SETS:
        return None
    why = (f"{set_name} stays unseen until {UNLOCK_FILE}, committed, names it with "
           f"{PROTOCOL_DECISION} (D96, plan §1.1)")
    f = root / UNLOCK_FILE
    if not f.is_file():
        return f"{why}: no unlock file"
    try:
        unlocked = json.loads(f.read_text(encoding="utf-8")).get("unlocked")
    except (ValueError, AttributeError):
        return f"{why}: the unlock file is not valid JSON"
    if not isinstance(unlocked, dict) or set_name not in unlocked:
        return f"{why}: the unlock file does not list {set_name}"
    if unlocked[set_name] != PROTOCOL_DECISION:
        return f"{why}: the unlock file names {unlocked[set_name]!r}"
    if not decision_exists(PROTOCOL_DECISION, root):
        return f"{why}: no '## {PROTOCOL_DECISION}:' heading in {DECISIONS_DIR}"
    if committed is None:
        ok = git_committed(UNLOCK_FILE, root)
    elif callable(committed):
        ok = committed(UNLOCK_FILE)
    else:
        ok = bool(committed)
    if not ok:
        return f"{why}: the unlock file is not committed"
    return None


def is_unlocked(set_name: str, **kw) -> bool:
    return unlock_problem(set_name, **kw) is None


def require_unlocked(set_name: str | None, **kw) -> None:
    """Analysis tools: raise ``Locked`` for a locked unseen set."""
    if set_name is None:
        return
    why = unlock_problem(set_name, **kw)
    if why:
        raise Locked(why)


def run_refusal(set_name: str | None, provenance: dict | None = None, **kw) -> str | None:
    """Run drivers: why an unseen set may not run (locked, or a dirty tree), else None.
    ``provenance`` is ``gate_inputs.git_provenance()``'s result; read here when None."""
    if set_name not in UNSEEN_SETS:
        return None
    why = unlock_problem(set_name, **kw)
    if why:
        return why
    if provenance is None:
        import gate_inputs

        provenance = gate_inputs.git_provenance()
    if provenance.get("dirty"):
        return ("held-out runs need a clean git tree: "
                + "; ".join((provenance.get("status") or [])[:5]))
    return None


# ---------------------------------------------------------------- sealed hashes

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def seal(paths: list[str], root: Path = ROOT) -> dict:
    """``{"files": {path: sha256}}`` for ``paths`` (relative to ``root``, POSIX)."""
    return {"files": {Path(p).as_posix(): sha256_file(root / p) for p in sorted(paths)}}


def verify(manifest: dict | Path, root: Path = ROOT) -> dict:
    """Check every file of ``manifest`` (a dict, or the path of its JSON) against its hash:
    ``{"ok", "checked", "mismatched": [paths], "missing": [paths]}``. No contents."""
    if isinstance(manifest, Path):
        manifest = json.loads(manifest.read_text(encoding="utf-8"))
    files = manifest.get("files") or {}
    mismatched, missing = [], []
    for rel, want in sorted(files.items()):
        p = root / rel
        if not p.is_file():
            missing.append(rel)
        elif sha256_file(p) != want:
            mismatched.append(rel)
    return {"ok": bool(files) and not mismatched and not missing, "checked": len(files),
            "mismatched": mismatched, "missing": missing}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="each unseen set: locked or unlocked")
    s = sub.add_parser("seal", help="write the SHA-256 manifest of PATHs")
    s.add_argument("--out", default=HASHES_FILE)
    s.add_argument("paths", nargs="+")
    v = sub.add_parser("verify", help="check the sealed files against the manifest")
    v.add_argument("--manifest", default=HASHES_FILE)
    a = ap.parse_args(argv)
    if a.cmd == "status":
        for name in UNSEEN_SETS:
            why = unlock_problem(name)
            print(f"{name}: {'unlocked' if why is None else 'locked'}" + (f" ({why})" if why else ""))
        return 0
    if a.cmd == "seal":
        m = seal(a.paths)
        (ROOT / a.out).write_text(json.dumps(m, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"sealed {len(m['files'])} files -> {a.out}")
        return 0
    r = verify(ROOT / a.manifest)
    for rel in r["missing"]:
        print(f"missing: {rel}")
    for rel in r["mismatched"]:
        print(f"mismatch: {rel}")
    print(f"verify: {'PASS' if r['ok'] else 'FAIL'} ({r['checked']} files)")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
