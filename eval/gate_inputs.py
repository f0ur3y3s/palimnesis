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
- ``internal_scan`` (Phase 3B, O-B6, D62.4), split as D45.9.8 splits excerpt leaks from
  echoes:
  - **hard leaks** (gate): a hidden call (a ``palimnesis_*`` name, or the id of a hidden
    call in the archive) in the proxy's client stream or in the calls OpenCode's export
    says it received; or a hidden result's text in that stream or in the export's received
    text, reasoning and call inputs. Result text is matched by distinctive 40-character
    slices: windows of the result that occur in no earlier non-hidden archived content,
    so a quote of the archived original is not a leak, but the result's own framing is.
  - **mentions** (reported only): other ``palimnesis_`` text the model wrote in its
    visible content, reasoning or call arguments (stream only), and distinct harness tool
    results (by call id) that carried ``palimnesis_`` text back to the client, such as a
    transcript-file read (client requests and export tool outputs).
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
INTERNAL_MARKER = "palimnesis_"  # the reserved tool-name prefix (contracts §3)


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


def sse_tool_names(raw: bytes) -> list[str]:
    """The tool-call names of an SSE response, in order of first appearance."""
    names = []
    for line in raw.decode("utf-8", "replace").splitlines():
        if not line.startswith("data:") or line.strip() == "data: [DONE]":
            continue
        try:
            d = json.loads(line[5:])
        except ValueError:
            continue
        for ch in d.get("choices") or []:
            delta = ch.get("delta") or ch.get("message") or {}
            for tc in delta.get("tool_calls") or []:
                name = (tc.get("function") or {}).get("name")
                if name:
                    names.append(name)
    return names


SLICE = 40          # characters per result window
MIN_SLICE = 16      # shorter results are not matched (too generic)


def sse_parts(raw: bytes) -> dict:
    """One response stream's model-written texts (content, reasoning, each call's
    arguments) and its calls as (id, name)."""
    texts: dict[tuple, str] = {}
    calls: dict[tuple, list] = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        if not line.startswith("data:") or line.strip() == "data: [DONE]":
            continue
        try:
            d = json.loads(line[5:])
        except ValueError:
            continue
        for ch in d.get("choices") or []:
            i = ch.get("index", 0)
            delta = ch.get("delta") or ch.get("message") or {}
            for k in ("content", "reasoning_content"):
                if isinstance(delta.get(k), str):
                    texts[(i, k)] = texts.get((i, k), "") + delta[k]
            for tc in delta.get("tool_calls") or []:
                key = (i, tc.get("index", 0))
                slot = calls.setdefault(key, [None, None])
                fn = tc.get("function") or {}
                slot[0] = slot[0] or tc.get("id")
                slot[1] = slot[1] or fn.get("name")
                texts[(i, "args", key[1])] = texts.get((i, "args", key[1]), "") + (fn.get("arguments") or "")
    return {"texts": list(texts.values()), "calls": [tuple(v) for v in calls.values()]}


def _windows(text: str) -> list[str]:
    if len(text) < MIN_SLICE:
        return []
    if len(text) <= SLICE:
        return [text]
    out = [text[i:i + SLICE] for i in range(0, len(text) - SLICE + 1, SLICE)]
    if len(text) % SLICE:
        out.append(text[-SLICE:])
    return out


def hidden_artifacts(db: Path, sessions: list[str] | None = None) -> dict:
    """The archive's hidden call ids, and each hidden result with its windows and the
    non-hidden content archived before it on its branch (for distinctiveness)."""
    conn = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
    try:
        where, args = "", ()
        if sessions is not None:
            where = f" WHERE br.session_id IN ({','.join('?' * len(sessions))})"
            args = tuple(sessions)
        rows = conn.execute(
            "SELECT o.occ_id, o.branch_id, o.seq, o.source FROM occurrences o"
            " JOIN branches br ON br.branch_id = o.branch_id" + where + " ORDER BY o.branch_id, o.seq",
            args).fetchall()
        ids, results, prior, length = set(), [], {}, {}

        def text_of(occ_id):
            out = []
            for block_id, kind, meta in conn.execute(
                    "SELECT block_id, kind, meta FROM blocks WHERE occ_id = ? ORDER BY idx", (occ_id,)):
                m = json.loads(meta)
                if kind == "tool_call" and m.get("internal"):
                    ids.add(m.get("id"))
                data = b"".join(r[0] for r in conn.execute(
                    "SELECT bytes FROM segments WHERE block_id = ? ORDER BY seq", (block_id,)))
                out.append(data.decode("utf-8", "replace"))
            return "\n".join(out)

        for occ_id, branch, seq, source in rows:
            text = text_of(occ_id)
            parts = prior.setdefault(branch, [])
            if source == "internal_tool":
                results.append({"windows": _windows(text), "branch": branch,
                                "upto": length.get(branch, 0)})
            else:
                parts.append(text)
                length[branch] = length.get(branch, 0) + len(text) + 1
    finally:
        conn.close()
    return {"ids": ids, "results": results,
            "prior": {b: "\n".join(v) for b, v in prior.items()}, "_distinct": {}}


def _distinctive(hidden: dict, r: dict, w: str) -> bool:
    key = (r["branch"], r["upto"], w)
    cache = hidden["_distinct"]
    if key not in cache:
        cache[key] = hidden["prior"][r["branch"]].find(w, 0, r["upto"]) == -1
    return cache[key]


def result_hits(hidden: dict, text: str) -> bool:
    """Whether ``text`` holds a distinctive window of any hidden result."""
    return any(w in text and _distinctive(hidden, r, w)
               for r in hidden["results"] for w in r["windows"])


def _export_parts(export: dict) -> tuple[list[str], list[tuple], dict[str, list[str]]]:
    """(received texts, received calls as (id, name), {call id: tool-result strings}) of
    an ``opencode session export``: what the proxy sent, and what OpenCode's tools
    returned."""
    texts, calls, results = [], [], {}
    for m in export.get("messages") or []:
        if m.get("type") != "assistant":
            continue
        for part in m.get("content") or []:
            if part.get("type") in ("text", "reasoning"):
                texts.append(part.get("text") or "")
            elif part.get("type") == "tool":
                calls.append((part.get("id"), part.get("name")))
                state = dict(part.get("state") or {})
                texts += strings_of(state.pop("input", {}))
                results[part.get("id")] = strings_of(state)
    return texts, calls, results


def internal_scan(db: Path, records: Path, front_calls: list[dict], exports: list[dict],
                  sessions: list[str] | None = None) -> dict:
    """Hard leaks and mentions of hidden recall (see the module docstring)."""
    hidden = hidden_artifacts(db, sessions)
    hard = {"stream_calls": 0, "stream_results": 0, "export_calls": 0, "export_results": 0}
    model, harness = 0, set()

    def is_hidden_call(cid, name):
        return bool(name and name.startswith(INTERNAL_MARKER)) or (cid is not None and cid in hidden["ids"])

    for c in front_calls:
        resp = Path(records) / "front" / f"{c['n']:04d}.resp.sse"
        req = Path(records) / "front" / f"{c['n']:04d}.json"
        if resp.exists():
            parts = sse_parts(resp.read_bytes())
            hard["stream_calls"] += sum(is_hidden_call(i, n) for i, n in parts["calls"])
            for t in parts["texts"]:
                if result_hits(hidden, t):
                    hard["stream_results"] += 1
                elif INTERNAL_MARKER in t:
                    model += 1
        if req.exists():
            try:
                body = json.loads(req.read_bytes())
            except ValueError:
                continue
            for m in body.get("messages") or []:
                if m.get("role") == "tool" and any(INTERNAL_MARKER in x for x in strings_of(m.get("content"))):
                    harness.add(m.get("tool_call_id"))
    for export in exports:
        texts, calls, results = _export_parts(export)
        hard["export_calls"] += sum(is_hidden_call(i, n) for i, n in calls)
        hard["export_results"] += sum(1 for t in texts if result_hits(hidden, t))
        harness |= {cid for cid, xs in results.items() if any(INTERNAL_MARKER in x for x in xs)}
    hard["leaks"] = sum(hard.values())
    return {"hard": hard, "mentions": {"model": model, "harness": len(harness)},
            "hidden_ids": len(hidden["ids"]), "hidden_results": len(hidden["results"])}


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
