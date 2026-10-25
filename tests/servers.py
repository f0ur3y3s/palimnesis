"""Run ASGI apps on real loopback sockets so tests exercise actual HTTP."""

from __future__ import annotations

import asyncio
import threading
import time
from contextlib import contextmanager
from typing import Iterator

import uvicorn

from palimnesis.server import uvicorn_config


@contextmanager
def serve(app, *, palimnesis: bool = False, log_level: str = "warning") -> Iterator[str]:
    """Serve ``app`` on an ephemeral loopback port; yield its base URL.

    ``palimnesis=True`` uses the proxy's production server configuration.
    """
    if palimnesis:
        config = uvicorn_config(app, host="127.0.0.1", port=0, log_level=log_level)
    else:
        config = uvicorn.Config(
            app, host="127.0.0.1", port=0, log_level=log_level, lifespan="on"
        )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("server failed to start")
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
