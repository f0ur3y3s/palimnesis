"""Probe 10: two simultaneous requests on the single slot (the one deliberate concurrency probe).

Part 1: A (streaming, ~300 decode tokens) and B (streaming, tiny) sent 0.3 s apart. Records for each:
time to response headers, time to first byte, raw byte arrivals (keep-alives while queued?), status
and the /status queue depth while both are outstanding.
Part 2: while A' runs, C is sent and then disconnected while still queued: does the queue depth drop,
and does C's work run anyway (checked in /metrics request records)?
Saves fixtures/concurrency.json and fixtures/sse_queued_B.sse.
"""

from __future__ import annotations

import json
import socket
import threading
import time

from p09_cancel import raw_post
from strata_common import MODEL, recent_requests, save_bytes, save_json, status

A_BODY = {"model": MODEL, "max_tokens": 400, "reasoning_effort": "none", "stream": True,
          "messages": [{"role": "user", "content": "Count from 1 to 120, numbers separated by single spaces."}]}
B_BODY = {"model": MODEL, "max_tokens": 8, "reasoning_effort": "none", "stream": True,
          "messages": [{"role": "user", "content": "Reply with the single word BEE."}]}
C_BODY = {"model": MODEL, "max_tokens": 8, "reasoning_effort": "none", "stream": False,
          "messages": [{"role": "user", "content": "Reply with the single word SEA. (queued-cancel probe)"}]}


def consume(name: str, body: dict, rec: dict, t_ref: float) -> None:
    s = raw_post("/v1/chat/completions", body)
    t0 = time.monotonic()
    rec[name] = {"sent_at_s": round(t0 - t_ref, 3), "arrivals": []}
    buf = bytearray()
    while True:
        b = s.recv(65536)
        if not b:
            break
        rec[name]["arrivals"].append((round(time.monotonic() - t_ref, 3), len(b), b[:80].decode("utf-8", "replace")))
        buf.extend(b)
    s.close()
    rec[name]["done_at_s"] = round(time.monotonic() - t_ref, 3)
    rec[name]["status_line"] = bytes(buf).split(b"\r\n", 1)[0].decode()
    rec[name]["_raw"] = bytes(buf)


def main() -> None:
    out: dict = {"status_before": status()}
    rec: dict = {}
    t_ref = time.monotonic()
    ta = threading.Thread(target=consume, args=("A", A_BODY, rec, t_ref))
    tb = threading.Thread(target=consume, args=("B", B_BODY, rec, t_ref))
    ta.start()
    time.sleep(0.3)
    tb.start()
    samples = []
    while ta.is_alive() or tb.is_alive():
        st = status()
        samples.append((round(time.monotonic() - t_ref, 2), st.get("busy"), st.get("queued"), st.get("max_tokens"),
                        st.get("generated")))
        time.sleep(0.25)
    ta.join()
    tb.join()
    save_bytes("sse_queued_B.sse", rec["B"].pop("_raw"))
    save_bytes("sse_concurrent_A.sse", rec["A"].pop("_raw"))
    out["part1"] = {"requests": rec, "status_samples": samples}
    print("A first/last:", rec["A"]["arrivals"][0][:2], rec["A"]["done_at_s"], rec["A"]["status_line"])
    print("B first/last:", rec["B"]["arrivals"][0][:2], rec["B"]["done_at_s"], rec["B"]["status_line"])
    print("B arrivals:", [a[:2] for a in rec["B"]["arrivals"]][:10])

    # Part 2: queued request whose client disconnects.
    rec2: dict = {}
    t_ref = time.monotonic()
    ta = threading.Thread(target=consume, args=("A2", A_BODY, rec2, t_ref))
    ta.start()
    time.sleep(0.5)
    c = raw_post("/v1/chat/completions", C_BODY)
    time.sleep(1.0)
    q_before = status().get("queued")
    c.shutdown(socket.SHUT_RDWR)
    c.close()
    time.sleep(0.5)
    q_after = status().get("queued")
    ta.join()
    rec2["A2"].pop("_raw")
    time.sleep(3.0)
    st_end = status()
    reqs = recent_requests(5)
    out["part2"] = {"queued_while_C_waiting": q_before, "queued_after_C_disconnect": q_after,
                    "status_3s_after_A2": {k: st_end.get(k) for k in ("busy", "queued", "prompt_tokens", "max_tokens")},
                    "recent_requests": [{k: r.get(k) for k in ("id", "time", "duration_s", "finish", "prompt_tokens",
                                                                "output_tokens")} for r in reqs]}
    print(json.dumps(out["part2"], indent=1))
    save_json("concurrency.json", out)


if __name__ == "__main__":
    main()
