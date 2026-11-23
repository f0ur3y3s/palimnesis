"""Phase 8 S7: random-time external kills of a streaming proxy (plan §1.5, R71).

    python eval/kill_trials.py [--n 50] [--seed 1] [--out JSON]

Each trial starts ``palimnesis serve`` on a fresh archive in front of the test suite's fake
upstream (``tests/fake_upstream.py``: no model), sends one keyed streamed request whose
answer arrives in 40 chunks over about a second, kills the process from outside
(TerminateProcess / SIGKILL) after a random delay, and restarts it on the same archive.
A trial passes when, after the restart:

- ``palimnesis.archive.integrity.check`` is clean (integrity, foreign keys, no active
  branch, one terminal event per attempt, FTS equal to a rebuild);
- the client's keyed resend gets the whole answer (a replay when the turn had completed, a
  new attempt when no output had been archived), or ``409 ambiguous_retry`` when the kill
  left partial output (D130: never regenerated silently);
- the session's transcripts verify.

It prints counts per archive state at the kill and per outcome, and every failure.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.fake_upstream import FakeUpstream  # noqa: E402
from tests.servers import serve  # noqa: E402

from palimnesis.archive import integrity  # noqa: E402

SESSION = "kill-1"
ANSWER = "".join(f"w{i} " for i in range(40))
CHUNKS = 40


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def _proxy(upstream: str, db: Path):
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PALIMNESIS_CRASH", "PALIMNESIS_PAUSE"))}
    log = open(db.parent / f"proxy-{port}.log", "wb")
    proc = subprocess.Popen([sys.executable, "-m", "palimnesis", "serve", "--upstream", upstream,
                             "--db", str(db), "--port", str(port)],
                            env=env, stdout=subprocess.DEVNULL, stderr=log)
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while True:
        try:
            httpx.get(f"{url}/health", timeout=0.5)
            break
        except httpx.TransportError:
            if proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("proxy did not start")
            time.sleep(0.1)
    try:
        yield url, proc
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=15)
        log.close()


def _stream(fake: FakeUpstream) -> None:
    def chunk(delta, finish=None):
        return b"data: " + json.dumps({"id": "c1", "object": "chat.completion.chunk", "created": 1,
                                       "model": "m", "choices": [{"index": 0, "delta": delta,
                                                                  "finish_reason": finish}]}).encode() + b"\n\n"
    parts = [chunk({"role": "assistant", "content": ""})]
    parts += [(0.025, chunk({"content": f"w{i} "})) for i in range(CHUNKS)]
    parts += [chunk({}, "stop"), b"data: [DONE]\n\n"]
    fake.respond_sse(parts)


def _post(url: str) -> httpx.Response:
    body = json.dumps({"model": "m", "stream": True, "messages": [
        {"role": "system", "content": "You are terse."},
        {"role": "user", "content": "Count to forty."}]}).encode()
    with httpx.stream("POST", f"{url}/s/{SESSION}/v1/chat/completions", content=body,
                      headers={"Idempotency-Key": "k1"}, timeout=30) as r:
        r.read()
    return r


def _content(raw: bytes) -> str:
    out = ""
    for line in raw.split(b"\n"):
        if line.startswith(b"data: ") and line != b"data: [DONE]":
            for ch in json.loads(line[6:]).get("choices") or []:
                out += (ch.get("delta") or {}).get("content") or ""
    return out


def _state(db: Path) -> str:
    """What the archive held when the process died."""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        if not c.execute("SELECT 1 FROM requests").fetchone():
            return "nothing accepted"
        if c.execute("SELECT 1 FROM events WHERE kind = 'turn_complete'").fetchone():
            return "turn complete"
        if c.execute("SELECT 1 FROM segments s JOIN blocks b ON b.block_id = s.block_id"
                     " JOIN occurrences o ON o.occ_id = b.occ_id"
                     " WHERE o.source = 'generated'").fetchone():
            return "partial output"
        return "accepted, no output"
    finally:
        c.close()


def _retry(fn, timeout=10.0):
    deadline = time.monotonic() + timeout
    while True:
        try:
            return fn()
        except sqlite3.OperationalError as e:
            if "disk I/O error" not in str(e) or time.monotonic() > deadline:
                raise
        time.sleep(0.2)


def _check(db: Path) -> list[str]:
    def run():
        c = sqlite3.connect(db)
        try:
            return integrity.check(c)
        finally:
            c.close()
    return _retry(run)


def _verify(db: Path, timeout=20.0) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        r = subprocess.run([sys.executable, "-m", "palimnesis", "transcripts", "verify", SESSION,
                            "--db", str(db)], capture_output=True)
        if r.returncode == 0:
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(0.5)


def trial(delay: float, work: Path) -> dict:
    db = work / "archive.db"
    fake = FakeUpstream()
    out: dict = {"delay_s": round(delay, 3)}
    with serve(fake.app()) as up:
        _stream(fake)
        with _proxy(up, db) as (url, proc):
            t = threading.Thread(target=lambda: _swallow(lambda: _post(url)), daemon=True)
            t.start()
            time.sleep(delay)
            proc.kill()
            proc.wait(timeout=15)
            t.join(timeout=30)
        out["state"] = _retry(lambda: _state(db))
        problems: list[str] = []
        with _proxy(up, db) as (url, _):
            _stream(fake)  # used only when the resend is a new attempt
            r = _post(url)
            if r.status_code == 200:
                out["outcome"] = "answered" if _content(r.content) == ANSWER else "wrong answer"
            else:
                try:
                    code = r.json()["error"]["code"]
                except (ValueError, KeyError):
                    code = str(r.status_code)
                out["outcome"] = f"{r.status_code} {code}"
            if not _verify(db):
                problems.append("transcripts do not verify")
        problems += _check(db)
    want = {"turn complete": {"answered"}, "partial output": {"409 ambiguous_retry"},
            "accepted, no output": {"answered"}, "nothing accepted": {"answered"}}[out["state"]]
    if out["outcome"] not in want:
        problems.append(f"outcome {out['outcome']} after {out['state']}")
    out["problems"] = problems
    return out


def _swallow(fn):
    try:
        fn()
    except httpx.TransportError:
        pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n", type=int, default=50)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--max-delay", type=float, default=2.0,
                   help="kill after a uniform delay in [0, this) seconds from the request")
    p.add_argument("--out", type=Path)
    a = p.parse_args(argv)
    rnd = random.Random(a.seed)
    results = []
    for i in range(a.n):
        with tempfile.TemporaryDirectory(prefix="kill-") as d:
            r = trial(rnd.uniform(0, a.max_delay), Path(d))
        results.append(r)
        print(f"trial {i + 1:3}: kill at {r['delay_s']:.3f}s, {r['state']}, {r['outcome']}"
              + (f"  PROBLEMS {r['problems']}" if r["problems"] else ""), flush=True)
    states = Counter(r["state"] for r in results)
    outcomes = Counter((r["state"], r["outcome"]) for r in results)
    failed = [r for r in results if r["problems"]]
    print("states at the kill:", dict(states))
    print("outcomes:", {f"{s} -> {o}": n for (s, o), n in outcomes.items()})
    print(f"passed {len(results) - len(failed)}/{len(results)}")
    if a.out:
        a.out.write_text(json.dumps({"n": a.n, "seed": a.seed, "max_delay": a.max_delay,
                                     "results": results}, indent=1), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
