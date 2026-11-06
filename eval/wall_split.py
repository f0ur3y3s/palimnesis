"""Where a task run's upstream time goes: prefill and decode, for task calls and for
compaction calls, from Strata's per-call ``timings`` in the recorded responses.

A *compaction call* is any call that rewrites context rather than doing the task:
OpenCode's compaction requests (``tasks/run.is_compaction``), Pi's summarizer
(``pi_harness.is_compaction_request``) and Palimnesis's working-notes refresh (D72). Every
other call is a *task call*.

    uv run python eval/wall_split.py RECORDS_DIR [--json OUT]

``RECORDS_DIR`` is a task run's ``records/`` directory (``attempt-NNN/<task>-<arm>/bodies``).
Strata reports ``prompt_ms`` for the tokens it prefilled (the uncached part of the prompt)
and ``predicted_ms`` for decoding, so the four parts add up to the upstream time of the run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "tasks"))

import pi_harness  # noqa: E402
import run as task_run  # noqa: E402

NOTES_MARKER = "[palimnesis notes request]"
RUN_DIR = re.compile(r"^(?P<task>[a-z0-9]+-t\d+)-(?P<arm>a\d.*)$")
FIELDS = ("calls", "prompt", "cached", "prefilled", "prefill_s", "generated", "decode_s")


def kind(body: dict) -> str:
    """``compaction`` for a call that rewrites context, else ``task``."""
    if task_run.is_compaction(body) or pi_harness.is_compaction_request(body):
        return "compaction"
    last = (body.get("messages") or [{}])[-1]
    if NOTES_MARKER in json.dumps(last.get("content")):
        return "compaction"
    return "task"


def split(bodies: Path) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for req in sorted(bodies.glob("*.json")):
        resp = req.with_suffix(".resp.sse")
        if not resp.exists():
            continue
        final = None
        for line in resp.read_text(encoding="utf-8").splitlines():
            if line.startswith("data: ") and '"timings"' in line:
                final = json.loads(line[6:])
        if final is None:
            continue  # a call that ended without its final chunk (a killed turn)
        body = json.loads(req.read_bytes())
        body = body.get("body", body)
        body = json.loads(body) if isinstance(body, str) else body
        t, u = final["timings"], final.get("usage") or {}
        o = out.setdefault(kind(body), dict.fromkeys(FIELDS, 0))
        o["calls"] += 1
        o["prompt"] += u.get("prompt_tokens", 0)
        o["cached"] += (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        o["prefilled"] += t["prompt_n"]
        o["prefill_s"] += t["prompt_ms"] / 1000
        o["generated"] += t["predicted_n"]
        o["decode_s"] += t["predicted_ms"] / 1000
    return out


def runs(records: Path) -> list[dict]:
    rows = []
    for bodies in sorted(records.glob("attempt-*/*/bodies")):
        m = RUN_DIR.match(bodies.parent.name)
        if not m:
            continue
        result = bodies.parent / "result.json"
        meta = json.loads(result.read_text(encoding="utf-8")) if result.exists() else {}
        rows.append({"attempt": bodies.parent.parent.name, "task": m["task"], "arm": m["arm"],
                     "success": meta.get("success"), "latency_s": meta.get("latency_s"),
                     "split": split(bodies)})
    return rows


def _fmt(row: dict) -> str:
    s = row["split"]
    t, c = s.get("task", {}), s.get("compaction", {})
    total = sum(x.get("prefill_s", 0) + x.get("decode_s", 0) for x in (t, c))
    hit = (t.get("cached", 0) + c.get("cached", 0)) / max(1, t.get("prompt", 0) + c.get("prompt", 0))
    return (f"| {row['task']} | {row['arm']} | {row['attempt'].removeprefix('attempt-')} | {t.get('prefill_s', 0):,.0f} | {t.get('decode_s', 0):,.0f} "
            f"| {c.get('calls', 0)} | {c.get('prefill_s', 0):,.0f} | {c.get('decode_s', 0):,.0f} "
            f"| {c.get('generated', 0):,} | {t.get('prefilled', 0) + c.get('prefilled', 0):,} "
            f"| {hit:.0%} | {total:,.0f} |")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("records", type=Path)
    p.add_argument("--json", type=Path)
    a = p.parse_args()
    rows = runs(a.records)
    print("| Task | Arm | Attempt | Task prefill s | Task decode s | Compaction calls | Compaction prefill s "
          "| Compaction decode s | Compaction tokens written | Tokens prefilled | Cache hit "
          "| Upstream s |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for row in rows:
        print(_fmt(row))
    if a.json:
        a.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
