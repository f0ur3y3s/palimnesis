"""Probe 26 (Phase 4B, O-4B-7 / D81.7): Strata 0.1.54 with one engine slot against two.

The server is started outside this script (``--parallel 1`` or ``--parallel 2``; the operator
restarts it between runs). One run measures the server as it is and writes
``fixtures/strata_slots/p26_<label>.json``:

  env  /props (no template), /slots, /metrics ``engine`` facts, nvidia-smi, the engine log's
       startup lines since its last ``engine started`` (expert cache, batch slots, warnings)
       and the server log since the last ``=== p26`` marker line.
  W    warm-up: one ~16K-token request, not reported as a measurement.
  a    one request alone: ~16K-token prompt (fresh nonce, so nothing is reused), 256 generated
       tokens, streaming, temperature 0, reasoning off. Client TTFT (send to the first content
       delta), Strata ``timings`` (prompt/predicted per second, drafts) and the /metrics record.
       ``--reps`` repetitions.
  b    after each ``a``: the same conversation extended by the reply exactly as generated plus
       one user turn (64 tokens out). Cached tokens and prefill time.
  c    two requests of the ``a`` shape sent together (B 0.2 s after A, fresh nonces). Per
       request: TTFT, completion time from the common start, timings. /slots and nvidia-smi
       sampled every 0.5 s / 1 s. ``--creps`` repetitions.
  d    two different ~8K-token conversations X and Y alternating, X1 Y1 X2 Y2 X3 Y3, each step
       extending its own conversation by the reply and one user turn (32 tokens out). Cached
       tokens per step, /metrics conversation-cache counters, /slots held tokens.
  e    fit: two ~30K-token prompts sent together (64 tokens out). Both must be accepted and
       finish if each slot holds the full 32K context.
  f    (``--sections f``, written to ``p26_<label>_f.json``) two ~8K-token conversations X and Y
       extended together, three rounds, each round's pair sent 0.2 s apart: does a conversation
       find its prefix again when its next turn overlaps the other's (the batch slots are used
       only when requests overlap; a lone request runs on the engine's solo path).

``--restore-check`` instead records /props, /slots, nvidia-smi and one short request to
``p26_restore.json`` (after the server is back at one slot).

Sequential apart from the deliberate pairs in c and e; synthetic bodies only. Run on pythia:

    uv run python eval/probes/p26_slots.py --label 1slot
    uv run python eval/probes/p26_slots.py --label 2slot
    uv run python eval/probes/p26_slots.py --restore-check
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import threading
import time
import uuid
from pathlib import Path

from strata_common import BASE, FIXTURES, MODEL, client, filler, parse_sse, wait_idle

OUT = FIXTURES / "strata_slots"
OUT.mkdir(parents=True, exist_ok=True)
BUILD = "Strata 0.1.54"
SERVER_LOG = Path.home() / "logs" / "strata-32k.out"
ENGINE_LOG = Path.home() / ".local/state/strata/launch/iq3_xxs-32k.engine.log"
MARKER = "=== p26"

STORY = ("\n\nWrite a long, detailed story that uses as many of the words above as you can, "
         "in order. Do not stop early and do not summarise.")
EXTEND = "Now give the story a title and summarise it in three sentences."


# -- environment -------------------------------------------------------------------------


def nvidia_smi() -> dict:
    q = "memory.used,memory.total,utilization.gpu,temperature.gpu"
    try:
        g = subprocess.run(["nvidia-smi", f"--query-gpu={q}", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10).stdout.strip().split(", ")
        apps = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory",
                               "--format=csv,noheader,nounits"],
                              capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
        return {"memory_used_mib": int(g[0]), "memory_total_mib": int(g[1]), "util_pct": int(g[2]),
                "temp_c": int(g[3]), "apps": [a.split(", ") for a in apps]}
    except Exception as e:  # noqa: BLE001 - recorded, never fatal
        return {"error": repr(e)}


def engine_startup() -> list[str]:
    """The engine log from its last ``engine started`` line up to its first request line."""
    out = []
    for ln in log_since(ENGINE_LOG, "engine started", 400):
        if ln.startswith("strata serve: prompt ") and " reused + " in ln:
            break
        out.append(ln)
    return out


def log_since(path: Path, needle: str, limit: int = 400) -> list[str]:
    """Lines of ``path`` after the last line containing ``needle`` (inclusive)."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        return [f"<unreadable: {e}>"]
    idx = max((i for i, ln in enumerate(lines) if needle in ln), default=0)
    return lines[idx: idx + limit]


def get_json(path: str):
    with client(15) as c:
        return c.get(path).json()


def environment() -> dict:
    props = {k: v for k, v in get_json("/props").items() if k != "chat_template"}
    metrics = get_json("/metrics")
    eng_lines = engine_startup()
    keys = ("expert cache", "batch", "slot", "parallel", "warn", "WARN", "fit", "VRAM free", "refus",
            "conversation cache", "prompt chunk", "borrows", "context", "memory guard")
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                             cwd=Path(__file__).resolve().parents[2]).stdout.strip()
        dirty = subprocess.run(["git", "status", "--short"], capture_output=True, text=True,
                               cwd=Path(__file__).resolve().parents[2]).stdout.splitlines()
    except Exception as e:  # noqa: BLE001
        rev, dirty = repr(e), []
    return {
        "host": platform.node(), "base": BASE, "props": props, "slots": get_json("/slots"),
        "engine": metrics.get("engine"), "conversation_cache": metrics.get("conversation_cache"),
        "hardware_static": metrics.get("hardware_static"), "nvidia_smi_idle": nvidia_smi(),
        "engine_log_startup": eng_lines,
        "engine_log_startup_keyed": [ln for ln in eng_lines if any(k in ln for k in keys)],
        "server_log_since_marker": log_since(SERVER_LOG, MARKER, 40),
        "repo_on_host": {"rev": rev, "dirty": dirty},
    }


# -- requests ------------------------------------------------------------------------------


def nonce() -> str:
    return uuid.uuid4().hex[:12]


def calibrate_words(target: int) -> int:
    """Words of filler for about ``target`` prompt tokens (count_tokens on 4,000 words)."""
    def ct(text: str) -> int:
        with client(60) as c:
            return c.post("/v1/messages/count_tokens", json={
                "model": MODEL, "messages": [{"role": "user", "content": text}]}).json()["input_tokens"]
    per_word = (ct(filler(4000, seed=7)) - ct("x")) / 4000
    return int((target - 60) / per_word)


def story_messages(n_words: int, seed: int) -> list[dict]:
    return [{"role": "user", "content": f"[{nonce()}] Notes:\n{filler(n_words, seed=seed)}{STORY}"}]


def body_for(messages: list[dict], max_tokens: int) -> dict:
    return {"model": MODEL, "stream": True, "max_tokens": max_tokens, "temperature": 0, "seed": 1,
            "reasoning_effort": "none", "messages": messages}


def _has_token(raw: bytes) -> bool:
    """True once any streamed delta carries non-empty content or reasoning (the role chunk has content "")."""
    for ev in parse_sse(raw):
        for ch in (ev.get("json") or {}).get("choices") or []:
            d = ch.get("delta") or {}
            if d.get("content") or d.get("reasoning_content") or d.get("tool_calls"):
                return True
    return False


def stream(body: dict, t_ref: float) -> dict:
    """One streaming Chat request. Times are seconds from ``t_ref`` (a shared monotonic origin)."""
    sent = time.monotonic()
    raw = bytearray()
    first_token = None
    status_code = None
    error = None
    try:
        with client(900) as c:
            with c.stream("POST", "/v1/chat/completions", json=body) as r:
                status_code = r.status_code
                for chunk in r.iter_raw():
                    raw.extend(chunk)
                    if first_token is None and _has_token(bytes(raw)):
                        first_token = time.monotonic()
    except Exception as e:  # noqa: BLE001 - recorded
        error = repr(e)
    done = time.monotonic()
    content, usage, timings, finish = [], None, None, None
    for ev in parse_sse(bytes(raw)):
        j = ev.get("json") or {}
        for ch in j.get("choices") or []:
            d = ch.get("delta") or {}
            if d.get("content"):
                content.append(d["content"])
            if ch.get("finish_reason"):
                finish = ch["finish_reason"]
        usage = j.get("usage") or usage
        timings = j.get("timings") or timings
        if "error" in j:
            error = error or json.dumps(j["error"])
    if status_code and status_code != 200:
        error = error or bytes(raw[:500]).decode("utf-8", "replace")
    return {"status": status_code, "error": error, "sent_s": round(sent - t_ref, 3),
            "ttft_s": round(first_token - sent, 3) if first_token else None,
            "done_s": round(done - t_ref, 3), "elapsed_s": round(done - sent, 3), "finish": finish,
            "usage": usage, "timings": timings, "content": "".join(content)}


def summary(r: dict) -> dict:
    t = r.get("timings") or {}
    u = r.get("usage") or {}
    return {"status": r["status"], "error": r["error"], "prompt_tokens": u.get("prompt_tokens"),
            "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
            "completion_tokens": u.get("completion_tokens"), "finish": r["finish"],
            "sent_s": r["sent_s"], "ttft_s": r["ttft_s"], "done_s": r["done_s"], "elapsed_s": r["elapsed_s"],
            "prompt_ms": t.get("prompt_ms"), "prefill_tok_s": t.get("prompt_per_second"),
            "decode_ms": t.get("predicted_ms"), "decode_tok_s": t.get("predicted_per_second"),
            "draft_n": t.get("draft_n"), "draft_accepted": t.get("draft_n_accepted")}


def metrics_records(since: float) -> list[dict]:
    keep = ("id", "time", "duration_s", "finish", "prompt_tokens", "reused", "prompt_read", "output_tokens",
            "first_engine_token_s", "prompt_ms", "decode_ms", "decode_tok_s", "hit_rate", "file_mb",
            "drafts_offered", "drafts_accepted")
    recs = get_json("/metrics").get("requests") or []
    return [{k: r.get(k) for k in keep} for r in recs if (r.get("time") or 0) >= since - 1][::-1]


def server_now() -> float:
    return get_json("/metrics").get("time") or time.time()


class Sampler:
    """nvidia-smi every 1 s and /slots + /status every 0.5 s while a section runs."""

    def __init__(self) -> None:
        self.gpu: list = []
        self.slots: list = []
        self.stop = threading.Event()
        self.t0 = time.monotonic()

    def _gpu(self) -> None:
        while not self.stop.is_set():
            s = nvidia_smi()
            self.gpu.append((round(time.monotonic() - self.t0, 1), s.get("memory_used_mib"), s.get("util_pct")))
            self.stop.wait(1.0)

    def _slots(self) -> None:
        while not self.stop.is_set():
            try:
                sl = get_json("/slots")
                st = get_json("/status")
                self.slots.append((round(time.monotonic() - self.t0, 1), st.get("queued"),
                                   [(s.get("id"), s.get("is_processing"), s.get("n_prompt_tokens")) for s in sl]))
            except Exception as e:  # noqa: BLE001
                self.slots.append((round(time.monotonic() - self.t0, 1), "err", repr(e)))
            self.stop.wait(0.5)

    def __enter__(self):
        self.th = [threading.Thread(target=self._gpu, daemon=True), threading.Thread(target=self._slots, daemon=True)]
        for t in self.th:
            t.start()
        return self

    def __exit__(self, *a):
        self.stop.set()
        for t in self.th:
            t.join(timeout=15)

    def result(self) -> dict:
        mem = [m for _, m, _ in self.gpu if isinstance(m, int)]
        max_busy = max((sum(1 for s in row[2] if s[1]) for row in self.slots if isinstance(row[2], list)), default=None)
        max_q = max((row[1] for row in self.slots if isinstance(row[1], int)), default=None)
        return {"gpu_mem_max_mib": max(mem) if mem else None, "gpu_mem_min_mib": min(mem) if mem else None,
                "max_slots_processing": max_busy, "max_queued": max_q, "gpu_series": self.gpu,
                "slots_series": self.slots}


def pair(bodies: list[dict]) -> tuple[list[dict], dict]:
    t_ref = time.monotonic()
    res: list = [None, None]

    def run(i: int) -> None:
        res[i] = stream(bodies[i], t_ref)

    with Sampler() as smp:
        ths = [threading.Thread(target=run, args=(0,))]
        ths[0].start()
        time.sleep(0.2)
        ths.append(threading.Thread(target=run, args=(1,)))
        ths[1].start()
        for t in ths:
            t.join()
    return res, smp.result()


# -- sections ------------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label")
    ap.add_argument("--sections", default="Wabcde")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--creps", type=int, default=2)
    ap.add_argument("--restore-check", action="store_true")
    a = ap.parse_args()

    props = {k: v for k, v in get_json("/props").items() if k != "chat_template"}
    if props.get("build_info") != BUILD:
        raise SystemExit(f"build_info is {props.get('build_info')!r}, expected {BUILD!r}")

    if a.restore_check:
        wait_idle(quiet=1.0)
        r = stream(body_for([{"role": "user", "content": "Reply with the single word READY."}], 8), time.monotonic())
        out = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "props": props,
               "slots": get_json("/slots"), "engine": get_json("/metrics").get("engine"),
               "nvidia_smi": nvidia_smi(), "short_request": summary(r) | {"content": r["content"]},
               "server_log_since_marker": log_since(SERVER_LOG, MARKER, 40),
               "engine_log_startup": engine_startup()}
        (OUT / "p26_restore.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: out[k] for k in ("props", "slots", "short_request")}, indent=1))
        return

    path = OUT / (f"p26_{a.label}.json" if a.sections == "Wabcde" else f"p26_{a.label}_{a.sections}.json")
    out: dict = {"label": a.label, "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "workload": {"temperature": 0, "seed": 1, "reasoning_effort": "none", "a_target_tokens": 16000,
                              "a_max_tokens": 256, "b_max_tokens": 64, "d_target_tokens": 8000, "d_max_tokens": 32,
                              "e_target_tokens": 30000, "e_max_tokens": 64, "reps": a.reps, "creps": a.creps}}

    def save() -> None:
        path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    wait_idle(quiet=1.0)
    out["env"] = environment()
    save()
    print("env:", json.dumps({"total_slots": props.get("total_slots"), "n_ctx": props["default_generation_settings"]["n_ctx"],
                              "gpu": out["env"]["nvidia_smi_idle"].get("memory_used_mib"),
                              "expert_slots": (out["env"]["engine"] or {}).get("expert_slots")}))

    w16 = calibrate_words(16000)
    w8 = calibrate_words(8000)
    w30 = calibrate_words(30000)
    out["workload"]["words"] = {"16k": w16, "8k": w8, "30k": w30}
    save()

    def section(name: str, fn) -> None:
        if name not in a.sections:
            return
        print(f"--- section {name}", flush=True)
        try:
            out[name] = fn()
        except Exception as e:  # noqa: BLE001 - keep what was measured, record the failure
            out[name] = {"error": repr(e)}
        out[name + "_finished"] = time.strftime("%H:%M:%SZ", time.gmtime())
        save()
        print(json.dumps(out[name], default=str)[:1500], flush=True)

    def sec_w():
        wait_idle(quiet=1.0)
        return summary(stream(body_for(story_messages(w16, 100), 256), time.monotonic()))

    def sec_ab():
        reps = []
        for i in range(a.reps):
            wait_idle(quiet=1.0)
            t_srv = server_now()
            msgs = story_messages(w16, 200 + i)
            ra = stream(body_for(msgs, 256), time.monotonic())
            wait_idle(quiet=1.0)
            ext = msgs + [{"role": "assistant", "content": ra["content"]}, {"role": "user", "content": EXTEND}]
            rb = stream(body_for(ext, 64), time.monotonic())
            sa, sb = summary(ra), summary(rb)
            sb["expected_cached"] = (sa["prompt_tokens"] or 0) + (sa["completion_tokens"] or 0)
            reps.append({"a": sa, "b": sb, "metrics": metrics_records(t_srv)})
            print(f"  rep {i}: a {json.dumps(sa)}\n         b {json.dumps(sb)}", flush=True)
        return reps

    def sec_c():
        reps = []
        for i in range(a.creps):
            wait_idle(quiet=1.0)
            t_srv = server_now()
            res, smp = pair([body_for(story_messages(w16, 300 + 2 * i), 256),
                             body_for(story_messages(w16, 301 + 2 * i), 256)])
            reps.append({"A": summary(res[0]), "B": summary(res[1]),
                         "makespan_s": max(res[0]["done_s"], res[1]["done_s"]), "sampler": smp,
                         "metrics": metrics_records(t_srv)})
            print(f"  rep {i}: A {json.dumps(reps[-1]['A'])}\n         B {json.dumps(reps[-1]['B'])}", flush=True)
        return reps

    def sec_d():
        convs = {"X": story_messages(w8, 400), "Y": story_messages(w8, 401)}
        steps = []
        for step in ("X1", "Y1", "X2", "Y2", "X3", "Y3"):
            wait_idle(quiet=1.0)
            cc0 = get_json("/metrics").get("conversation_cache") or {}
            t_srv = server_now()
            m = convs[step[0]]
            r = stream(body_for(m, 32), time.monotonic())
            s = summary(r)
            prior = steps[-2]["summary"] if len(steps) >= 2 else None
            s["expected_cached_if_kept"] = ((prior["prompt_tokens"] or 0) + (prior["completion_tokens"] or 0)
                                            if prior else None)
            cc1 = get_json("/metrics").get("conversation_cache") or {}
            steps.append({"step": step, "summary": s, "slots_after": get_json("/slots"),
                          "conv_cache_delta": {k: (cc1.get(k) or 0) - (cc0.get(k) or 0)
                                               for k in ("parks", "restores", "evictions", "requests_reused")},
                          "conv_cache_after": {k: cc1.get(k) for k in ("parked", "bytes", "last_event", "last_reused")},
                          "metrics": metrics_records(t_srv)})
            convs[step[0]] = m + [{"role": "assistant", "content": r["content"]},
                                  {"role": "user", "content": f"Continue with one more sentence ({step})."}]
            print(f"  {step}: {json.dumps(s)} cc {json.dumps(steps[-1]['conv_cache_delta'])}", flush=True)
        return steps

    def sec_e():
        wait_idle(quiet=1.0)
        t_srv = server_now()
        res, smp = pair([body_for(story_messages(w30, 500), 64), body_for(story_messages(w30, 501), 64)])
        return {"A": summary(res[0]), "B": summary(res[1]), "makespan_s": max(res[0]["done_s"], res[1]["done_s"]),
                "sampler": smp, "metrics": metrics_records(t_srv), "slots_after": get_json("/slots")}

    def sec_f():
        convs = {"X": story_messages(w8, 600), "Y": story_messages(w8, 601)}
        rounds = []
        prev = None
        for rnd in (1, 2, 3):
            wait_idle(quiet=1.0)
            cc0 = get_json("/metrics").get("conversation_cache") or {}
            t_srv = server_now()
            res, smp = pair([body_for(convs["X"], 32), body_for(convs["Y"], 32)])
            sx, sy = summary(res[0]), summary(res[1])
            if prev:
                sx["expected_cached_if_kept"] = (prev[0]["prompt_tokens"] or 0) + (prev[0]["completion_tokens"] or 0)
                sy["expected_cached_if_kept"] = (prev[1]["prompt_tokens"] or 0) + (prev[1]["completion_tokens"] or 0)
            cc1 = get_json("/metrics").get("conversation_cache") or {}
            rounds.append({"round": rnd, "X": sx, "Y": sy, "slots_after": get_json("/slots"),
                           "conv_cache_delta": {k: (cc1.get(k) or 0) - (cc0.get(k) or 0)
                                                for k in ("parks", "restores", "evictions", "requests_reused")},
                           "sampler": {k: smp[k] for k in ("gpu_mem_max_mib", "max_slots_processing", "max_queued")},
                           "metrics": metrics_records(t_srv)})
            for i, k in enumerate("XY"):
                convs[k] = convs[k] + [{"role": "assistant", "content": res[i]["content"]},
                                       {"role": "user", "content": f"Continue with one more sentence ({k}{rnd})."}]
            prev = (sx, sy)
            print(f"  round {rnd}: X {json.dumps(sx)}", flush=True)
            print(f"           Y {json.dumps(sy)}", flush=True)
        return rounds

    section("W", sec_w)
    if "a" in a.sections or "b" in a.sections:
        section("a", sec_ab)
        out["b_note"] = "b results are inside section a (each rep's 'b')"
    section("c", sec_c)
    section("d", sec_d)
    section("e", sec_e)
    section("f", sec_f)
    out["nvidia_smi_end"] = nvidia_smi()
    out["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save()
    print("saved", path)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    main()
