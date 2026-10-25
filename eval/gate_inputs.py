"""Gate inputs and provenance for the held-out runs (D44.6, D45 amendments).

- ``git_provenance``: commit and whether the tree is dirty (held-out runs refuse dirty).
- ``strata_props`` / ``check_n_ctx``: Strata's ``/props`` ``n_ctx`` and build, read
  before and after each history and task; a run refuses to start or go on unless
  ``n_ctx`` is the expected value (32768 for the held-out step, D40).
- ``local_over_budget``: every upstream body counted with the pinned counter
  (``tokens.default().count_messages``), not taken from ``usage``.
- ``explain_gate``: ``replay.py --explain`` must exit 0 and report one pair per upstream
  call after each session's first.
- ``excerpt_leaks``: the exact text of a stored excerpt block, or of one of its items
  (header, payload and closing line together), in client-visible data or transcripts
  is a leak. Text that only quotes an excerpt header is an echo, reported, not a leak.
- ``reachable_records``: run records, answer keys or hidden-check text reachable from a
  workspace tree.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEM = re.compile(r"\[\[excerpt [^\n]*\]\]\n.*?\n\[\[/excerpt\]\]", re.S)
ECHO_MARKERS = ("[palimnesis excerpts", "[[excerpt ")


# ---------------------------------------------------------------- provenance

def git_provenance(root: Path = ROOT) -> dict:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                            text=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True,
                            text=True).stdout.splitlines()
    return {"commit": commit, "dirty": bool(status), "status": status[:50]}


def strata_props(upstream: str) -> dict:
    import httpx

    try:
        p = httpx.get(f"{upstream.rstrip('/')}/props", timeout=10).json()
        return {"n_ctx": (p.get("default_generation_settings") or {}).get("n_ctx"),
                "build": p.get("build_info"), "model_path": p.get("model_path")}
    except Exception as e:  # recorded; check_n_ctx then refuses
        return {"n_ctx": None, "error": f"{type(e).__name__}: {e}"}


def check_n_ctx(props: dict, expect: int) -> str | None:
    """None when ``n_ctx`` is the expected value, else the reason to refuse."""
    if props.get("n_ctx") != expect:
        return f"Strata n_ctx is {props.get('n_ctx')}, expected {expect} ({props.get('error', '')})"
    return None


def input_budget_for(n_ctx: int) -> int:
    from palimnesis.budget import BudgetPolicy, plan_budget

    return plan_budget(n_ctx, client_limit=None, policy=BudgetPolicy()).input_budget


# ---------------------------------------------------------------- budget and --explain

def local_over_budget(bodies: Path, calls: list[dict], budget: int) -> dict:
    """Pinned-counter count of every recorded upstream body against ``budget``."""
    from palimnesis.upstreams.strata import tokens

    counter = tokens.default()
    over, counted, errors = [], 0, []
    for c in calls:
        try:
            body = json.loads((bodies / f"{c['n']:04d}.json").read_bytes())
            n = counter.count_messages(**tokens.render_args_from_openai(body))
        except Exception as e:
            errors.append({"n": c["n"], "error": f"{type(e).__name__}: {e}"[:200]})
            continue
        counted += 1
        if n > budget:
            over.append({"n": c["n"], "tokens": n})
    return {"budget": budget, "counted": counted, "over": over, "errors": errors,
            "ok": not over and not errors and counted == len(calls)}


def explain_gate(exit_code: int | None, report: dict | None, calls_by_session: dict[str, int]) -> dict:
    """``--explain`` passes the gate when it exits 0, reports no unexplained pair, and its
    pair count equals the upstream calls minus each session's first call."""
    expected = sum(max(0, n - 1) for n in calls_by_session.values())
    pairs = len((report or {}).get("pairs", [])) if report else None
    unexplained = ((report or {}).get("summary") or {}).get("unexplained")
    ok = exit_code == 0 and report is not None and pairs == expected and unexplained == 0
    return {"exit": exit_code, "pairs": pairs, "expected_pairs": expected,
            "unexplained": unexplained, "ok": ok}


def run_explain(db: Path) -> tuple[int | None, dict | None, str]:
    import sys

    try:
        ex = subprocess.run([sys.executable, str(ROOT / "eval" / "replay.py"), "--explain", str(db),
                             "--json"], capture_output=True, text=True, cwd=str(ROOT), timeout=1800)
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"
    try:
        report = json.loads(ex.stdout) if ex.stdout.strip() else None
    except ValueError:
        report = None
    return ex.returncode, report, ex.stderr[-2000:]


# ---------------------------------------------------------------- excerpt leaks

def excerpt_texts(db: Path, session: str | None = None) -> list[str]:
    """Every stored block's rendered text and each of its items (header to closing line)."""
    conn = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
    try:
        q = "SELECT e.rendered FROM excerpt_blocks e"
        args: tuple = ()
        if session is not None:
            q += " JOIN branches b ON b.branch_id = e.branch_id WHERE b.session_id = ?"
            args = (session,)
        blocks = [r for (r,) in conn.execute(q, args) if r]
    finally:
        conn.close()
    out = []
    for b in blocks:
        out.append(b)
        out += ITEM.findall(b)
    return out


def strings_of(obj) -> list[str]:
    """All string leaves of a JSON value."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in strings_of(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in strings_of(v)]
    return []


def sse_texts(raw: bytes) -> list[str]:
    """Reassembled content, reasoning and tool arguments of an SSE response, plus the
    data of any non-JSON line."""
    parts: dict[tuple, str] = {}
    other = []
    for line in raw.decode("utf-8", "replace").splitlines():
        if not line.startswith("data:") or line.strip() == "data: [DONE]":
            continue
        try:
            d = json.loads(line[5:])
        except ValueError:
            other.append(line[5:])
            continue
        if d.get("error"):
            other += strings_of(d["error"])
        for ch in d.get("choices") or []:
            delta = ch.get("delta") or ch.get("message") or {}
            for k in ("content", "reasoning_content"):
                if isinstance(delta.get(k), str):
                    parts[(ch.get("index", 0), k)] = parts.get((ch.get("index", 0), k), "") + delta[k]
            for tc in delta.get("tool_calls") or []:
                key = (ch.get("index", 0), "tool", tc.get("index", 0))
                parts[key] = parts.get(key, "") + ((tc.get("function") or {}).get("arguments") or "")
    return list(parts.values()) + other


def scan(excerpts: list[str], texts: list[str]) -> dict:
    """Leaks: excerpt block or item text found in ``texts``. Echoes: texts that quote an
    excerpt marker without containing a stored block or item."""
    leaks, echoes = 0, 0
    for t in texts:
        hit = any(e and e in t for e in excerpts)
        leaks += hit
        if not hit and any(m in t for m in ECHO_MARKERS):
            echoes += 1
    return {"texts": len(texts), "leaks": leaks, "echoes": echoes}


def transcript_texts(root: Path | None) -> list[str]:
    if root is None or not Path(root).exists():
        return []
    return [f.read_text(encoding="utf-8", errors="replace") for f in Path(root).rglob("*") if f.is_file()]


# ---------------------------------------------------------------- reachability

RECORD_NAMES = {"questions.jsonl", "calls.jsonl", "front.jsonl", "meta.json", "result.json",
                "explain.json", "attempts.json", "import.json"}


def reachable_records(top: Path, *, answer_keys: list[str] = (), hidden: list[str] = ()) -> list[str]:
    """Files under ``top`` that are run records, hold an answer key (``"gold"`` or a
    needle file's ``"answer"`` field), or contain a hidden check's text."""
    found = []
    for f in Path(top).rglob("*"):
        if not f.is_file():
            continue
        if f.name in RECORD_NAMES or f.suffix == ".sse" or f.parent.name in ("bodies", "front"):
            found.append(str(f))
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if '"gold"' in text or any(f'"answer": {json.dumps(k)}' in text or f'"answer":{json.dumps(k)}' in text
                                   for k in answer_keys):
            found.append(str(f))
        elif any(h and h in text for h in hidden):
            found.append(str(f))
    return found
