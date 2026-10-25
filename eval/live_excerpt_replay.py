"""Live excerpt replay: prefix reuse with excerpt blocks included vs omitted (Phase 2 GL8).

Usage:
    python eval/live_excerpt_replay.py --upstream http://192.168.1.173:8080 --out DIR
        [--turns 6] [--input-budget 16000] [--max-tokens 2048]

In process, against a real Strata (one shared slot: requests run strictly one at a time,
each waits for ``/status`` to report idle, and every request is time-bounded). The proxy
is ``create_app(Settings(..., excerpt_source=SpanExcerpts()))`` on a loopback socket under
its production uvicorn config, archiving into ``DIR/archive.db``.

``SpanExcerpts`` is a ``SeededExcerpts``-like source (tests/test_excerpts_http.py) that
selects a real earlier archived span for every new user instruction: a prefix of the
newest earlier tool result in ``plan.items`` (else the first user message), cut so the
x1 rendering fits the allocation it is given, with exact source boundaries and sha256.

Each turn is OpenCode-shaped (live body 0's model, real tools array, ``stream``,
``stream_options``): a user message asks the model to read ``notes/partK.txt`` with the
``read`` tool; any tool call is answered with a ~1.8K-token synthetic file; the model's
streamed assistant turns are resent exactly as OpenCode does (``content`` null beside tool
calls, ``reasoning_content``). The input budget is forced low so the history crosses the
high watermark within the run (a threshold event, where R3 omits blocks).

Writes ``DIR/report.json``: per upstream call, the request kind, the excerpt blocks
included, whether this request's own new block was included, view moves and causes, and
the accounting event (lcp, cached_tokens, prompt_ms, estimate, reuse class, cause).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from palimnesis.api import create_app  # noqa: E402
from palimnesis.capture import load_exchanges  # noqa: E402
from palimnesis.config import Settings  # noqa: E402
from palimnesis.excerpts import Excerpt, SelectedExcerpt, Selection, render_block  # noqa: E402
from palimnesis.upstreams.strata import tokens  # noqa: E402
from tests.servers import serve  # noqa: E402

LIVE_DIR = ROOT / "eval/fixtures/opencode-2.1.4/live/exchanges"


class SpanExcerpts:
    """Selects a real earlier archived span, sized to the allocation."""

    query_version = "span-v1"
    retrieval_version = "span-v1"

    def __init__(self):
        self.counter = tokens.default()
        self.calls: list[dict] = []

    async def select(self, plan, base_view, allocation):
        items = list(plan.items)
        host = next((i for i, it in enumerate(items) if it.occ_id == plan.host_occ_id), len(items))
        src = next((it for it in reversed(items[:host]) if it.message.get("role") == "tool"
                    and it.occ_id and isinstance(it.message.get("content"), str)), None)
        role, tool = "tool", "read"
        if src is None:
            src = next((it for it in items[:host] if it.message.get("role") == "user"
                        and it.occ_id and isinstance(it.message.get("content"), str)), None)
            role, tool = "user", None
        rec = {"host": plan.host_occ_id, "allocation": allocation, "source": src.occ_id if src else None}
        self.calls.append(rec)
        empty = Selection("", self.query_version, self.retrieval_version, 0, ())
        if src is None or allocation <= 0:
            return empty
        text = src.message["content"]
        added = self.counter.added_token_strings

        def charge(n):
            return self.counter.count(render_block(
                [Excerpt(src.alias or "", 0, src.seq or 0, role, tool, text[:n])], added_tokens=added))

        if charge(1) > allocation:
            return empty
        lo, hi = 1, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if charge(mid) <= allocation:
                lo = mid
            else:
                hi = mid - 1
        rec["chars"], rec["charge"] = lo, charge(lo)
        return Selection(query=f"span of {src.alias}", query_version=self.query_version,
                         retrieval_version=self.retrieval_version,
                         archive_cutoff_seq=src.seq or 0, items=(SelectedExcerpt(
                             rank=1, score=1.0, source_occ_id=src.occ_id,
                             source_alias=src.alias, source_block=0, start=0, end=lo,
                             source_sha256=hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest(),
                             turn_number=src.seq or 0, role=role, tool_name=tool,
                             text=text[:lo]),))


def notes_file(k: int) -> str:
    lines = [f"# notes/part{k}.txt: service configuration review, part {k}"]
    for i in range(1, 49):
        lines.append(f"part{k}.line{i:03d}: key svc{k}_opt{i:03d} = {(k * 7919 + i * 104729) % 100000}"
                     f" (owner team-{(i * k) % 13}, reviewed {2020 + i % 6}-{1 + i % 12:02d})")
    return "\n".join(lines)


def wait_idle(upstream: str, limit_s: float = 600) -> tuple[float, dict]:
    """Wait for the shared slot; returns (seconds waited, /status). The status's
    ``prompt_tokens`` names the last prompt served, so a foreign request in between
    (which can evict this session's checkpoints) is visible in the report."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit_s:
        try:
            st = httpx.get(f"{upstream}/status", timeout=5).json()
            if not st.get("busy"):
                return time.monotonic() - t0, st
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(1.0)
    raise RuntimeError("Strata stayed busy; not sending")


def stream_turn(client, url, body) -> tuple[int, dict | None, dict]:
    """POST one streamed request; returns (status, assistant message, final usage chunk)."""
    reasoning, content, calls, last = [], [], {}, {}
    with client.stream("POST", url, content=json.dumps(body, ensure_ascii=False).encode()) as r:
        if r.status_code != 200:
            return r.status_code, None, {"error": r.read().decode("utf-8", "replace")[:500]}
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            if chunk.get("usage"):
                last = {"usage": chunk["usage"], "timings": chunk.get("timings")}
            for choice in chunk.get("choices") or []:
                d = choice.get("delta") or {}
                if d.get("reasoning_content"):
                    reasoning.append(d["reasoning_content"])
                if d.get("content"):
                    content.append(d["content"])
                for tc in d.get("tool_calls") or []:
                    slot = calls.setdefault(tc["index"], {"id": None, "name": "", "arguments": ""})
                    slot["id"] = tc.get("id") or slot["id"]
                    fn = tc.get("function") or {}
                    slot["name"] += fn.get("name") or ""
                    slot["arguments"] += fn.get("arguments") or ""
                if choice.get("finish_reason"):
                    last["finish_reason"] = choice["finish_reason"]
    text = "".join(content)
    msg: dict = {"role": "assistant", "content": text or None}
    if calls:
        msg["tool_calls"] = [{"id": c["id"], "type": "function",
                              "function": {"name": c["name"], "arguments": c["arguments"]}}
                             for _, c in sorted(calls.items())]
    elif not text:
        msg["content"] = ""
    if reasoning:
        msg["reasoning_content"] = "".join(reasoning)
    return 200, msg, last


def analyze(db: Path, report: dict) -> dict:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        report["upstream_calls"] = [json.loads(p) for (p,) in c.execute(
            "SELECT payload FROM events WHERE kind = 'upstream_call' ORDER BY event_id")]
        cols = [d[0] for d in c.execute("SELECT * FROM view_versions").description]
        report["view_versions"] = [dict(zip(cols, r)) for r in c.execute(
            "SELECT * FROM view_versions ORDER BY n")]
        report["excerpt_blocks"] = [dict(zip(("block_id", "host_occ_id", "status", "token_charge",
                                              "allocation", "base_view_n"), r)) for r in c.execute(
            "SELECT block_id, host_occ_id, status, token_charge, allocation_tokens, base_view_n"
            " FROM excerpt_blocks ORDER BY created_at")]
        report["drift"] = [json.loads(p) for (p,) in c.execute(
            "SELECT payload FROM events WHERE kind = 'count_drift'")]
    finally:
        c.close()
    return report


def run(args) -> dict:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    db = out / "archive.db"
    base = json.loads(load_exchanges(LIVE_DIR)[0].request_body)
    system = base["messages"][0]
    source = SpanExcerpts()
    settings = Settings(upstream_base_url=args.upstream, db_path=db, input_budget=args.input_budget,
                        excerpt_source=source)
    session = f"exc-live-{int(time.time())}"
    messages = [system]
    log = []
    with serve(create_app(settings), palimnesis=True) as proxy:
        url = f"{proxy}/s/{session}/v1/chat/completions"
        with httpx.Client(timeout=httpx.Timeout(args.request_timeout, connect=10)) as client:
            for k in range(1, args.turns + 1):
                messages.append({"role": "user", "content": (
                    f"Use the read tool to read notes/part{k}.txt, then answer in one short "
                    f"sentence: what is the value of svc{k}_opt00{k}?")})
                kind = "user"
                for _ in range(4):  # at most 3 tool rounds per turn
                    body = {"model": base["model"], "messages": messages, "tools": base["tools"],
                            "stream": True, "stream_options": {"include_usage": True},
                            "max_completion_tokens": args.max_tokens}
                    waited, st = wait_idle(args.upstream)
                    prev_prompt = (log[-1]["usage"] or {}).get("prompt_tokens") if log else None
                    t = time.time()
                    status, msg, last = stream_turn(client, url, body)
                    log.append({"turn": k, "kind": kind, "status": status, "wait_s": round(waited, 1),
                                "elapsed_s": round(time.time() - t, 2),
                                "finish": last.get("finish_reason"), "usage": last.get("usage"),
                                "timings": last.get("timings"), "error": last.get("error"),
                                "status_before": {"prompt_tokens": st.get("prompt_tokens"),
                                                  "generated": st.get("generated")},
                                "foreign_between": bool(log) and st.get("prompt_tokens") != prev_prompt})
                    print(json.dumps(log[-1])[:400], flush=True)
                    if status != 200 or msg is None:
                        raise RuntimeError(f"turn {k}: status {status}: {last}")
                    messages.append(msg)
                    if not msg.get("tool_calls"):
                        break
                    for call in msg["tool_calls"]:
                        messages.append({"role": "tool", "tool_call_id": call["id"],
                                         "content": notes_file(k)})
                    kind = "tool"
    report = {"session": session, "settings": {"input_budget": args.input_budget,
                                                "max_completion_tokens": args.max_tokens,
                                                "upstream": args.upstream},
              "requests": log, "source_calls": source.calls}
    (out / "requests.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), "utf-8")
    analyze(db, report)
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), "utf-8")
    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--upstream", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--turns", type=int, default=6)
    p.add_argument("--input-budget", type=int, default=16_000)
    p.add_argument("--max-tokens", type=int, default=2048)
    p.add_argument("--request-timeout", type=float, default=600)
    p.add_argument("--report-only", action="store_true",
                   help="rebuild report.json from DIR/archive.db (and DIR/requests.json) only")
    args = p.parse_args(argv)
    if args.report_only:
        out = Path(args.out)
        saved = out / "requests.json"
        report = json.loads(saved.read_text("utf-8")) if saved.exists() else {}
        analyze(out / "archive.db", report)
        (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), "utf-8")
    else:
        report = run(args)
    for call in report["upstream_calls"]:
        print({k: call.get(k) for k in ("view_n", "input_tokens", "prompt_tokens", "cached_tokens",
                                         "prompt_ms", "lcp_tokens", "expected_reuse_est",
                                         "reuse_class", "cause", "included_excerpts")})
    print("view_versions:", [(v["n"], v["cause"]) for v in report["view_versions"]])
    print("excerpt_blocks:", [(b["status"], b["token_charge"], b["allocation"]) for b in report["excerpt_blocks"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
