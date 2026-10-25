"""Proxy-originated errors rendered in the shape the client's SDK expects."""

from __future__ import annotations

from fastapi.responses import JSONResponse


def is_anthropic_path(path: str) -> bool:
    return path.strip("/").startswith("v1/messages")


def error_response(
    path: str,
    status: int,
    code: str,
    message: str,
    type_: str = "invalid_request_error",
    retry: bool = False,
) -> JSONResponse:
    """``retry`` sets ``x-should-retry``, which the supported harness SDKs honor."""
    if is_anthropic_path(path):
        # Anthropic's error object has no code field; carry it in the message.
        body = {"type": "error", "error": {"type": type_, "message": f"palimnesis {code}: {message}"}}
    else:
        body = {"error": {"message": message, "type": type_, "code": code, "param": None}}
    return JSONResponse(
        body, status_code=status, headers={"x-should-retry": str(retry).lower()}
    )
