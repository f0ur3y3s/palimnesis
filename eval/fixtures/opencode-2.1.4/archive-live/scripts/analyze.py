"""Read-only analysis of the archive-mode live run. Prints a JSON summary."""

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

from mnemon import ledger
from mnemon.rawarchive import get_raw

ROOT = Path(sys.argv[1])
SID = sys.argv[2]


def taps(name):
    recs = [json.loads(l) for l in (ROOT / "tap" / name / "tap.jsonl").read_text("utf-8").splitlines()]
    return [r for r in recs if "event" not in r]


def sse(body: bytes):
    out = []
    for block in body.replace(b"\r\n", b"\n").split(b"\n\n"):
        for line in block.split(b"\n"):
            if line.startswith(b"data:"):
                out.append(line[5:].strip())
    return out


def stream_summary(body: bytes):
    reasoning = text = ""
    calls = {}
    finish = usage = None
    done = False
    errors = []
    comments = body.count(b": keep-alive")
    for d in sse(body):
        if d == b"[DONE]":
            done = True
            continue
        c = json.loads(d)
        if "error" in c:
            errors.append(c["error"].get("code"))
            continue
        usage = c.get("usage") or usage
        for ch in c.get("choices") or []:
            delta = ch.get("delta") or {}
            reasoning += delta.get("reasoning_content") or ""
            text += delta.get("content") or ""
            for i, tc in enumerate(delta.get("tool_calls") or []):
                e = calls.setdefault(tc.get("index", i), {"id": None, "name": None, "arguments": ""})
                f = tc.get("function") or {}
                e["id"] = tc.get("id") or e["id"]
                e["name"] = f.get("name") or e["name"]
                e["arguments"] += f.get("arguments") or ""
            finish = ch.get("finish_reason") or finish
    return {"reasoning": reasoning, "text": text, "tool_calls": [calls[k] for k in sorted(calls)],
            "finish": finish, "usage": usage, "done": done, "errors": errors,
            "keepalive_comments": comments}


arch = taps("archive")
back = taps("back")
db = sqlite3.connect(f"file:{(ROOT / 'archive.db').as_posix()}?mode=ro", uri=True)
summary = {"session": SID}

summary["sessions"] = db.execute("SELECT count(*) FROM sessions").fetchone()[0]
reqs = db.execute("SELECT request_id, raw_id, fingerprint, arrived_at FROM requests"
                  " ORDER BY arrived_at").fetchall()
summary["archived_requests"] = len(reqs)

# Pair client exchanges (archive tap, status 200) with archived requests and upstream exchanges.
accepted = [r for r in arch if r.get("status") == 200]
rejected = [r for r in arch if r.get("status") != 200]
assert len(accepted) == len(reqs) == len(back), (len(accepted), len(reqs), len(back))
rows = []
for i, (cli, (request_id, raw_id, fp, arrived), up) in enumerate(zip(accepted, reqs, back)):
    cbody = (ROOT / "tap/archive" / cli["name"] / "request.body").read_bytes()
    ubody = (ROOT / "tap/back" / up["name"] / "request.body").read_bytes()
    raw = get_raw(db, raw_id)
    cresp = (ROOT / "tap/archive" / cli["name"] / "response.body").read_bytes()
    uresp = (ROOT / "tap/back" / up["name"] / "response.body").read_bytes()
    # Also the mnemon passthrough capture of the upstream request (independent of the tap).
    caps = sorted((ROOT / "captures/upstream/upstream").iterdir())
    capbody = (caps[i] / "request.body").read_bytes()
    events = [(k, json.loads(p)) for k, p in db.execute(
        "SELECT kind, payload FROM events WHERE request_id = ? ORDER BY event_id", (request_id,))]
    kinds = [k for k, _ in events]
    st = stream_summary(cresp)
    msgs = json.loads(cbody)["messages"]
    rows.append({
        "n": i + 1, "client": cli["name"], "upstream": up["name"], "status": cli["status"],
        "messages": len(msgs), "last_role": msgs[-1]["role"],
        "req_bytes": len(cbody), "req_sha256": hashlib.sha256(cbody).hexdigest()[:16],
        "raw_archive_equal": raw == cbody,
        "upstream_body_equal": ubody == cbody, "upstream_capture_equal": capbody == cbody,
        "response_bytes_client": len(cresp), "response_bytes_upstream": len(uresp),
        "response_equal": cresp == uresp,
        "events": {k: kinds.count(k) for k in dict.fromkeys(kinds)},
        "event_order": [k for k in kinds if k != "delivery_progress"],
        "finish": st["finish"], "done": st["done"], "stream_errors": st["errors"],
        "keepalive_comments": st["keepalive_comments"],
        "usage": st["usage"] and {k: st["usage"].get(k) for k in ("prompt_tokens", "completion_tokens")}
                 | {"cached_tokens": (st["usage"].get("prompt_tokens_details") or {}).get("cached_tokens")},
        "tool_calls": [c["name"] for c in st["tool_calls"]],
        "ttfb_client_ms": round((cli["t_first_data"] - cli["t_arrival"]) * 1000, 1),
        "ttfb_upstream_ms": round((up["t_first_data"] - up["t_arrival"]) * 1000, 1),
        "headers_client_ms": round((cli["t_headers"] - cli["t_arrival"]) * 1000, 1),
        "headers_upstream_ms": round((up["t_headers"] - up["t_arrival"]) * 1000, 1),
        "accept_to_upstream_ms": round((up["t_arrival"] - cli["t_arrival"]) * 1000, 1),
        "duration_s": round(cli["t_end"] - cli["t_arrival"], 2),
        "x_should_retry": cli["resp_headers"].get("x-should-retry"),
        "_stream": st, "_body": cbody,
    })
for r in rows:
    r["ttfb_overhead_ms"] = round(r["ttfb_client_ms"] - r["ttfb_upstream_ms"], 1)

summary["rejected"] = []
for r in rejected:
    body = (ROOT / "tap/archive" / r["name"] / "response.body").read_bytes()
    err = json.loads(body)["error"]
    req = json.loads((ROOT / "tap/archive" / r["name"] / "request.body").read_bytes())
    summary["rejected"].append({"client": r["name"], "status": r["status"], "code": err["code"],
                                "message": err["message"],
                                "x_should_retry": r["resp_headers"].get("x-should-retry"),
                                "messages": len(req["messages"]),
                                "roles_tail": [m["role"] for m in req["messages"][-4:]]})

# Visible history vs the final accepted request plus the last generated turn.
history = ledger.load_archived(db, ledger.branch_id_for(SID))
visible = [a for a in history if a.view != "internal"]
final = rows[-1]
final_msgs = json.loads(final["_body"])["messages"]
checks = []
for i, a in enumerate(visible):
    if i < len(final_msgs):
        m = final_msgs[i]
        rebuilt = ledger.message_dict(db, a.occ_id)
        if a.source == "generated":
            same = ((m.get("content") or "") == (rebuilt.get("content") or "")
                    and m.get("reasoning_content", rebuilt.get("reasoning_content")) == rebuilt.get("reasoning_content")
                    and [(c["id"], c["function"]["name"], json.loads(c["function"]["arguments"])) for c in m.get("tool_calls") or []]
                    == [(c["id"], c["function"]["name"], json.loads(c["function"]["arguments"])) for c in rebuilt.get("tool_calls") or []])
        else:
            same = rebuilt == m
        checks.append({"i": i, "role": a.role, "source": a.source, "complete": a.complete, "match": same})
    else:
        st = final["_stream"]
        checks.append({"i": i, "role": a.role, "source": a.source, "complete": a.complete,
                       "match_last_stream": a.reasoning == st["reasoning"] and a.text == st["text"],
                       "reasoning_chars": len(a.reasoning), "text_chars": len(a.text)})
summary["visible_history"] = {"length": len(visible), "final_request_messages": len(final_msgs),
                              "all_match": all(c.get("match", c.get("match_last_stream")) for c in checks),
                              "positions": checks}
# Every generated occurrence equals the stream the client received for its request.
gen_ok = []
for r in rows:
    rid = db.execute("SELECT request_id FROM requests ORDER BY arrived_at").fetchall()[r["n"] - 1][0]
    occ = db.execute("SELECT occ_id FROM occurrences WHERE request_id = ? AND source = 'generated'", (rid,)).fetchone()
    a = next(x for x in history if x.occ_id == occ[0])
    st = r["_stream"]
    gen_ok.append(a.reasoning == st["reasoning"] and a.text == st["text"]
                  and [(c["id"], c["name"], c["arguments"]) for c in a.tool_calls]
                  == [(c["id"], c["name"], c["arguments"]) for c in st["tool_calls"]])
summary["generated_equal_streamed"] = gen_ok
summary["event_totals"] = dict(db.execute("SELECT kind, count(*) FROM events GROUP BY kind").fetchall())
summary["context_versions"] = summary["event_totals"].get("context_version", 0)
summary["branch_heads"] = db.execute("SELECT active_request_id, version FROM branch_heads").fetchall()
summary["raw_bodies"] = db.execute("SELECT count(*), sum(format=0), sum(length(payload)), sum(total_len), max(depth) FROM raw_bodies").fetchone()
summary["raw_formats"] = db.execute("SELECT raw_id, format, depth, length(payload), total_len FROM raw_bodies").fetchall()
summary["db_bytes"] = (ROOT / "archive.db").stat().st_size
summary["archive_capture_dir_exists"] = (ROOT / "captures/archive").exists()
for r in rows:
    r.pop("_stream"), r.pop("_body")
summary["requests"] = rows
print(json.dumps(summary, indent=1))
