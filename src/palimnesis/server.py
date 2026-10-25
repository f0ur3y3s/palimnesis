"""The uvicorn configuration the proxy runs under, shared by the CLI and tests."""

from __future__ import annotations

import uvicorn


def uvicorn_config(app, *, host: str, port: int, log_level: str = "info") -> uvicorn.Config:
    # The upstream's own Date and Server headers are relayed; uvicorn adding
    # its own would duplicate them.
    return uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level,
        lifespan="on",
        server_header=False,
        date_header=False,
    )
