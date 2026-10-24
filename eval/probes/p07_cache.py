"""Probe 7: prefix-cache reuse and the metrics that report it.

Sends (1) a ~3K-token prompt, (2) the identical prompt, (3) the same conversation extended by one
assistant + user turn, (4) the identical prompt again on the Anthropic dialect. Records usage,
timings and the server-side /metrics request record for each, plus which requests ran in between
(another client's request in between can replace the single slot's KV state).
Saves fixtures/cache_reuse.json.
"""

from __future__ import annotations

import time

from strata_common import MODEL, client, filler, recent_requests, save_json

DOC = filler(1400, seed=7)
BASE_MSGS = [
    {"role": "system", "content": "You are a terse assistant."},
    {"role": "user", "content": "Here is a document:\n\n" + DOC + "\n\nReply with the single word OK."},
]
EXT_MSGS = BASE_MSGS + [
    {"role": "assistant", "content": "OK"},
    {"role": "user", "content": "Reply with the single word YES."},
]

STEPS = [
    ("first", "/v1/chat/completions", {"model": MODEL, "messages": BASE_MSGS, "max_tokens": 4, "reasoning_effort": "none"}),
    ("repeat", "/v1/chat/completions", {"model": MODEL, "messages": BASE_MSGS, "max_tokens": 4, "reasoning_effort": "none"}),
    ("extended", "/v1/chat/completions", {"model": MODEL, "messages": EXT_MSGS, "max_tokens": 4, "reasoning_effort": "none"}),
    ("anthropic_repeat_ext", "/v1/messages", {"model": MODEL, "system": BASE_MSGS[0]["content"],
                                              "messages": EXT_MSGS[1:], "max_tokens": 4,
                                              "thinking": {"type": "disabled"}}),
]


def main() -> None:
    out = []
    for name, path, body in STEPS:
        t0 = time.monotonic()
        with client() as c:
            r = c.post(path, json=body)
        wall = time.monotonic() - t0
        j = r.json()
        rid = None
        reqs = recent_requests(6)
        rec = {"step": name, "path": path, "status": r.status_code, "wall_s": round(wall, 2),
               "usage": j.get("usage"), "timings": j.get("timings"),
               "content": (j.get("choices") or [{}])[0].get("message", {}).get("content") if "choices" in j
               else j.get("content"),
               "server_recent_requests": [{k: x.get(k) for k in ("id", "time", "prompt_tokens", "reused", "prompt_read",
                                                                  "prompt_ms", "output_tokens", "first_engine_token_s")}
                                          for x in reqs]}
        out.append(rec)
        print(name, r.status_code, f"wall={wall:.1f}s", "usage=", j.get("usage"),
              "timings=", {k: (j.get("timings") or {}).get(k) for k in ("cache_n", "prompt_n", "prompt_ms")})
        print("   recent:", [(x["prompt_tokens"], x["reused"]) for x in reqs[:4]], rid)
    save_json("cache_reuse.json", out)


if __name__ == "__main__" and "--multiturn" not in __import__("sys").argv:
    main()


def multiturn_edit() -> None:
    """Grow a 4-turn conversation turn by turn, then edit turn 2 (as masking would) and turn 4.

    Shows that reuse is limited to engine checkpoints (start of each assistant turn, every 16K tokens,
    system root >= 2048 tokens), not the full longest common token prefix.
    """
    sys_msg = {"role": "system", "content": "You are a terse assistant. " + filler(100, seed=70)}
    turns = [filler(350, seed=71 + i) for i in range(4)]
    out = []

    def send(label, msgs):
        with client() as c:
            r = c.post("/v1/chat/completions", json={"model": MODEL, "messages": msgs, "max_tokens": 4,
                                                      "reasoning_effort": "none"})
        j = r.json()
        u = j["usage"]
        rec = {"step": label, "prompt_tokens": u["prompt_tokens"],
               "cached_tokens": u["prompt_tokens_details"]["cached_tokens"],
               "prompt_n": j["timings"]["prompt_n"], "prompt_ms": j["timings"]["prompt_ms"]}
        out.append(rec)
        print(rec)
        return j["choices"][0]["message"]["content"]

    msgs = [sys_msg]
    for i, t in enumerate(turns):
        msgs = msgs + [{"role": "user", "content": f"Turn {i + 1}:\n{t}\nReply OK."}]
        reply = send(f"grow_turn_{i + 1}", msgs)
        msgs = msgs + [{"role": "assistant", "content": reply}]
    final = msgs + [{"role": "user", "content": "Reply YES."}]
    send("append_turn_5", final)
    send("repeat_turn_5", final)
    edited = [dict(m) for m in final]
    edited[3] = {"role": "user", "content": "Turn 2: [masked: archived as #abc123]\nReply OK."}  # turn 2 user msg
    send("edit_turn_2_masked", edited)
    edited4 = [dict(m) for m in final]
    edited4[7] = {"role": "user", "content": "Turn 4: [masked]\nReply OK."}
    send("edit_turn_4_masked", edited4)
    send("back_to_original_turn_5", final)
    save_json("cache_multiturn_edit.json", out)


if __name__ == "__main__" and "--multiturn" in __import__("sys").argv:
    multiturn_edit()
