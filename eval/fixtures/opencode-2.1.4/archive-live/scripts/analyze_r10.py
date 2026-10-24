"""Read-only analysis of the R10 run (multiple sessions, superseded partials). Prints JSON."""

import json
import sqlite3
import sys
from pathlib import Path

from mnemon import ledger
from mnemon.rawarchive import get_raw

ROOT = Path(sys.argv[1])


def taps(name):
    recs = [json.loads(l) for l in (ROOT / "tap" / name / "tap.jsonl").read_text("utf-8").splitlines()]
    return [r for r in recs if "event" not in r]


def stream_summary(body: bytes):
    reasoning = text = ""
    calls = {}
    finish = usage = None
    done = False
    errors = []
    for block in body.replace(b"\r\n", b"\n").split(b"\n\n"):
        for line in block.split(b"\n"):
            if not line.startswith(b"data:"):
                continue
            d = line[5:].strip()
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
            "finish": finish, "usage": usage, "done": done, "errors": errors}


def same_generated(m, rebuilt):
    def calls(x):
        return [(c["id"], c["function"]["name"], json.loads(c["function"]["arguments"]))
                for c in x.get("tool_calls") or []]
    return ((m.get("content") or "") == (rebuilt.get("content") or "")
            and m.get("reasoning_content", rebuilt.get("reasoning_content")) == rebuilt.get("reasoning_content")
            and calls(m) == calls(rebuilt))


arch, back = taps("archive"), taps("back")
db = sqlite3.connect(f"file:{(ROOT / 'archive.db').as_posix()}?mode=ro", uri=True)
reqs = db.execute("SELECT request_id, session_id, raw_id FROM requests ORDER BY arrived_at").fetchall()
accepted = [r for r in arch if r.get("status") == 200]
assert len(accepted) == len(reqs) == len(back), (len(accepted), len(reqs), len(back))
caps = sorted((ROOT / "captures/upstream/upstream").iterdir())
rows = []
for i, (cli, (request_id, sid, raw_id), up) in enumerate(zip(accepted, reqs, back)):
    cbody = (ROOT / "tap/archive" / cli["name"] / "request.body").read_bytes()
    ubody = (ROOT / "tap/back" / up["name"] / "request.body").read_bytes()
    cresp = (ROOT / "tap/archive" / cli["name"] / "response.body").read_bytes()
    uresp = (ROOT / "tap/back" / up["name"] / "response.body").read_bytes()
    events = [(k, json.loads(p)) for k, p in db.execute(
        "SELECT kind, payload FROM events WHERE request_id = ? ORDER BY event_id", (request_id,))]
    st = stream_summary(cresp)
    occ = db.execute("SELECT occ_id FROM occurrences WHERE request_id = ? AND source = 'generated'",
                     (request_id,)).fetchone()
    hist = {a.occ_id: a for a in ledger.load_archived(db, ledger.branch_id_for(sid))}
    a = hist[occ[0]] if occ else None
    msgs = json.loads(cbody)["messages"]
    usage = st["usage"] or {}
    rows.append({
        "n": i + 1, "client": cli["name"], "session": sid[-6:], "status": 200,
        "messages": len(msgs), "roles": "".join(m["role"][0] for m in msgs),
        "req_bytes": len(cbody),
        "raw_archive_equal": get_raw(db, raw_id) == cbody,
        "upstream_body_equal": ubody == cbody,
        "upstream_capture_equal": (caps[i] / "request.body").read_bytes() == cbody,
        "response_equal": cresp == uresp, "response_bytes": len(cresp),
        "generated_equal_streamed": bool(a) and a.reasoning == st["reasoning"] and a.text == st["text"]
            and [(c["id"], c["name"], c["arguments"]) for c in a.tool_calls]
            == [(c["id"], c["name"], c["arguments"]) for c in st["tool_calls"]],
        "generated_chars": a and {"reasoning": len(a.reasoning), "text": len(a.text)},
        "event_order": [k for k, _ in events if k != "delivery_progress"],
        "superseded": [p["occ_id"][-8:] for k, p in events if k == "partial_superseded"],
        "finish": st["finish"], "done": st["done"],
        "usage": {"prompt": usage.get("prompt_tokens"), "completion": usage.get("completion_tokens"),
                  "cached": (usage.get("prompt_tokens_details") or {}).get("cached_tokens")},
        "ttfb_client_ms": round((cli["t_first_data"] - cli["t_arrival"]) * 1000, 1),
        "ttfb_overhead_ms": round(((cli["t_first_data"] - cli["t_arrival"])
                                   - (up["t_first_data"] - up["t_arrival"])) * 1000, 1),
        "duration_s": round(cli["t_end"] - cli["t_arrival"], 2),
        "_st": st, "_msgs": msgs, "_sid": sid,
    })

sessions = {}
for sid, in db.execute("SELECT session_id FROM sessions ORDER BY created_at"):
    history = ledger.load_archived(db, ledger.branch_id_for(sid))
    visible = [a for a in history if a.view != "internal"]
    sup = {json.loads(p)["occ_id"] for p, in db.execute(
        "SELECT e.payload FROM events e JOIN requests r ON e.request_id = r.request_id"
        " WHERE r.session_id = ? AND e.kind = 'partial_superseded'", (sid,))}
    live = [a for a in visible if a.occ_id not in sup]
    last = [r for r in rows if r["_sid"] == sid][-1]
    checks = []
    for i, a in enumerate(live):
        if i < len(last["_msgs"]):
            m, rebuilt = last["_msgs"][i], ledger.message_dict(db, a.occ_id)
            checks.append(same_generated(m, rebuilt) if a.source == "generated" else rebuilt == m)
        else:
            checks.append(a.reasoning == last["_st"]["reasoning"] and a.text == last["_st"]["text"]
                          and a.complete)
    sessions[sid] = {
        "visible_occurrences": len(visible), "superseded_partials": [
            {"occ": a.occ_id[-8:], "position": visible.index(a), "complete": a.complete,
             "cancelled": a.cancelled, "reasoning_chars": len(a.reasoning), "text_chars": len(a.text)}
            for a in visible if a.occ_id in sup],
        "final_request_messages": len(last["_msgs"]),
        "history_minus_superseded_equals_final_request_plus_last_turn":
            len(live) == len(last["_msgs"]) + 1 and all(checks),
    }

for r in rows:
    del r["_st"], r["_msgs"], r["_sid"]
summary = {
    "sessions": sessions,
    "rejected": [r["name"] for r in arch if r.get("status") != 200],
    "event_totals": dict(db.execute("SELECT kind, count(*) FROM events GROUP BY kind").fetchall()),
    "branch_heads": db.execute("SELECT branch_id, active_request_id FROM branch_heads").fetchall(),
    "raw_bodies": dict(zip(["count", "snapshots", "payload_bytes", "logical_bytes"], db.execute(
        "SELECT count(*), sum(format=0), sum(length(payload)), sum(total_len) FROM raw_bodies").fetchone())),
    "requests": rows,
}
print(json.dumps(summary, indent=1))
