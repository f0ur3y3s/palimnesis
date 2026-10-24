"""Run `mnemon serve` (same app + uvicorn config as the CLI) wrapped in an ASGI tap.

The tap records, per HTTP exchange, the exact request body the app received,
the response bytes it sent, status, headers and timings (arrival, headers,
first body, first `data:` chunk, end, client disconnect). A stop file makes
uvicorn shut down cleanly (lifespan shutdown closes the store).
"""

import argparse
import json
import re
import threading
import time
from pathlib import Path

import uvicorn

from mnemon.api import create_app
from mnemon.config import Settings
from mnemon.server import uvicorn_config


class Tap:
    def __init__(self, app, out: Path, label: str):
        self.app, self.out, self.label = app, out, label
        self.n = 0
        self.lock = threading.Lock()
        out.mkdir(parents=True, exist_ok=True)
        self.log = out / "tap.jsonl"

    def emit(self, rec):
        with self.lock, open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        self.n += 1
        name = f"{self.label}-{self.n:03d}"
        hdrs = {}
        for k, v in scope["headers"]:
            k = k.decode("latin-1").lower()
            hdrs[k] = "<redacted>" if k == "authorization" else v.decode("latin-1")
        rec = {"name": name, "label": self.label, "method": scope["method"],
               "path": (scope.get("raw_path") or b"").decode("latin-1"),
               "t_arrival": time.time(), "req_headers": hdrs}
        reqbody, respbody = bytearray(), bytearray()

        async def r():
            msg = await receive()
            if msg["type"] == "http.request":
                reqbody.extend(msg.get("body", b""))
                if not msg.get("more_body"):
                    rec.setdefault("t_body", time.time())
            elif msg["type"] == "http.disconnect":
                rec.setdefault("t_disconnect", time.time())
            return msg

        async def s(msg):
            now = time.time()
            if msg["type"] == "http.response.start":
                rec["status"] = msg["status"]
                rec["t_headers"] = now
                rec["resp_headers"] = {k.decode("latin-1"): v.decode("latin-1")
                                       for k, v in msg["headers"]}
            elif msg["type"] == "http.response.body":
                b = msg.get("body", b"")
                if b:
                    rec.setdefault("t_first_body", now)
                if b"data:" in b and "t_first_data" not in rec:
                    rec["t_first_data"] = now
                    self.emit({"name": name, "event": "first_data", "t": now})
                if "t_first_content" not in rec and re.search(rb'"delta": ?\{"content": ?"[^"]', b):
                    rec["t_first_content"] = now
                    self.emit({"name": name, "event": "first_content", "t": now})
                respbody.extend(b)
            await send(msg)

        try:
            await self.app(scope, r, s)
        finally:
            rec["t_end"] = time.time()
            d = self.out / name
            d.mkdir(exist_ok=True)
            (d / "request.body").write_bytes(bytes(reqbody))
            (d / "response.body").write_bytes(bytes(respbody))
            rec["req_len"], rec["resp_len"] = len(reqbody), len(respbody)
            self.emit(rec)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--upstream", required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--db")
    p.add_argument("--capture-dir")
    p.add_argument("--tap-dir", required=True)
    p.add_argument("--label", required=True)
    a = p.parse_args()
    settings = Settings(upstream_base_url=a.upstream,
                        capture_dir=Path(a.capture_dir) if a.capture_dir else None,
                        db_path=Path(a.db) if a.db else None, synchronous="FULL")
    print(f"label={a.label} db={settings.db_path} capture={settings.capture_dir}", flush=True)
    tap_dir = Path(a.tap_dir)
    app = Tap(create_app(settings), tap_dir, a.label)
    server = uvicorn.Server(uvicorn_config(app, host="127.0.0.1", port=a.port))
    stop = tap_dir / f"STOP-{a.label}"

    def watch():
        while not stop.exists():
            time.sleep(0.2)
        print(f"stop file seen at {time.time():.3f}; shutting down", flush=True)
        server.should_exit = True

    threading.Thread(target=watch, daemon=True).start()
    server.run()
    print(f"exited cleanly at {time.time():.3f}", flush=True)


if __name__ == "__main__":
    main()
