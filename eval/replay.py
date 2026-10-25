"""Replay captured exchanges against a target and report how responses differ.

Usage:
    python eval/replay.py CAPTURE_DIR --target URL [--header name=value]... [--json]
    python eval/replay.py --explain DB_PATH [--session S] [--json]

TARGET is the base the captured API path is appended to: an upstream origin for
a direct baseline (http://192.168.1.173:8080) or a session base for the proxy
(http://127.0.0.1:9000/s/<session>). Exchanges replay sequentially, oldest
first. Generated-text equality is diagnostic only; compare status, event
structure and finish reasons for comparability.

``--explain`` reads an archive instead (contracts §10): for each pair of consecutive
upstream calls on a session's branch it reports the token LCP, the cached tokens the
upstream reported, the reuse estimate, the recorded cause and the reuse class. It exits 1
if any cause is ``unexplained``.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palimnesis.capture import REDACTED, Exchange, load_exchanges  # noqa: E402

_NOT_REPLAYED = frozenset(
    {"host", "content-length", "connection", "transfer-encoding", "keep-alive"}
)


def _replay_headers(ex: Exchange, overrides: dict[str, str]) -> dict[str, str]:
    headers = {
        k: v
        for k, v in ex.request_headers.items()
        if v != REDACTED and k not in _NOT_REPLAYED and not k.startswith("x-palimnesis-")
    }
    headers.update(overrides)
    return headers


def _sse_payloads(body: bytes) -> list[bytes]:
    payloads = []
    for block in body.replace(b"\r\n", b"\n").split(b"\n\n"):
        data = [
            line[5:].removeprefix(b" ")
            for line in block.split(b"\n")
            if line.startswith(b"data:")
        ]
        if data:
            payloads.append(b"\n".join(data))
    return payloads


def _finish_reasons(obj) -> list[str]:
    reasons = []
    if not isinstance(obj, dict):
        return reasons
    for choice in obj.get("choices") or []:
        if isinstance(choice, dict) and choice.get("finish_reason"):
            reasons.append(choice["finish_reason"])
    for holder in (obj, obj.get("delta")):
        if isinstance(holder, dict) and holder.get("stop_reason"):
            reasons.append(holder["stop_reason"])
    return reasons


def _shape(content_type: str, body: bytes) -> tuple[int | None, list[str]]:
    """(SSE data-event count or None, finish/stop reasons)."""
    if content_type.startswith("text/event-stream"):
        payloads = _sse_payloads(body)
        reasons = []
        for p in payloads:
            try:
                reasons += _finish_reasons(json.loads(p))
            except ValueError:
                pass
        return len(payloads), reasons
    try:
        return None, _finish_reasons(json.loads(body))
    except ValueError:
        return None, []


def compare(ex: Exchange, status: int, headers: httpx.Headers, body: bytes) -> dict:
    captured_events, captured_finish = _shape(
        ex.response_headers.get("content-type", ""), ex.response_body
    )
    replayed_events, replayed_finish = _shape(headers.get("content-type", ""), body)
    report = {
        "path": ex.path,
        "captured_complete": ex.complete,
        "status": {"captured": ex.status, "replayed": status},
        "status_match": ex.status == status,
        "byte_identical": ex.response_body == body,
        "finish": {"captured": captured_finish, "replayed": replayed_finish},
    }
    if captured_events is not None or replayed_events is not None:
        report["sse_events"] = {"captured": captured_events, "replayed": replayed_events}
    return report


def replay(capture_dir: Path, target: str, overrides: dict[str, str]) -> dict:
    results = []
    with httpx.Client(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
        for ex in load_exchanges(capture_dir):
            url = target.rstrip("/") + ex.path + (f"?{ex.query}" if ex.query else "")
            with client.stream(
                ex.method,
                url,
                content=ex.request_body,
                headers=_replay_headers(ex, overrides),
            ) as r:
                body = r.read()
                results.append(compare(ex, r.status_code, r.headers, body))
    return {
        "exchanges": results,
        "summary": {
            "exchanges": len(results),
            "status_match": sum(r["status_match"] for r in results),
            "byte_identical": sum(r["byte_identical"] for r in results),
        },
    }


def explain(db_path: Path, session: str | None = None) -> dict:
    """Consecutive upstream-call pairs per branch from an archive's ``upstream_call`` events."""
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        calls = [json.loads(p) for (p,) in c.execute(
            "SELECT payload FROM events WHERE kind = 'upstream_call' ORDER BY event_id")]
    finally:
        c.close()
    if session is not None:
        calls = [x for x in calls if x["branch_id"].startswith(f"{session}/")]
    pairs = [{"session": x["branch_id"].rsplit("/", 1)[0], "prev_call_id": x["prev_call_id"],
              "call_id": x["call_id"], "lcp_tokens": x["lcp_tokens"],
              "cached_tokens": x["cached_tokens"], "expected_reuse_est": x["expected_reuse_est"],
              "cause": x["cause"], "reuse_class": x["reuse_class"]}
             for x in calls if x["prev_call_id"] is not None]
    classes: dict[str, int] = {}
    for pair in pairs:
        if pair["reuse_class"] is not None:
            classes[pair["reuse_class"]] = classes.get(pair["reuse_class"], 0) + 1
    unexplained = sum("unexplained" in pair["cause"].split(",") for pair in pairs)
    return {"pairs": pairs, "summary": {"calls": len(calls), "pairs": len(pairs),
                                        "unexplained": unexplained, "classes": classes}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("capture_dir", type=Path, nargs="?")
    parser.add_argument("--target")
    parser.add_argument("--explain", type=Path, metavar="DB_PATH",
                        help="report cache accounting for an archive instead of replaying")
    parser.add_argument("--session", help="with --explain: only this session")
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="set or replace a request header (e.g. a credential redacted at capture)",
    )
    parser.add_argument("--json", action="store_true", help="print the full JSON report")
    args = parser.parse_args(argv)
    if args.explain is not None:
        report = explain(args.explain, args.session)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            for p in report["pairs"]:
                print(f"{p['session']} {p['prev_call_id']} -> {p['call_id']}: lcp={p['lcp_tokens']}"
                      f" cached={p['cached_tokens']} est={p['expected_reuse_est']} (estimate)"
                      f" cause={p['cause']} class={p['reuse_class']}")
            print(report["summary"])
        return 1 if report["summary"]["unexplained"] else 0
    if args.capture_dir is None or args.target is None:
        parser.error("CAPTURE_DIR and --target are required unless --explain is given")
    overrides = dict(h.split("=", 1) for h in args.header)
    overrides = {k.lower(): v for k, v in overrides.items()}

    report = replay(args.capture_dir, args.target, overrides)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for r in report["exchanges"]:
            print(
                f"{r['path']}: status {r['status']['captured']}->{r['status']['replayed']}"
                f" identical={r['byte_identical']} finish={r['finish']}"
            )
        print(report["summary"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
