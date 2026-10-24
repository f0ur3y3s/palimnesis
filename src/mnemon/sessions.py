"""Session identity resolution.

Identifiers are opaque routing keys, not secrets. They arrive in the URL path
(``/s/<id>/...``) and/or the ``X-Mnemon-Session`` header; when both are present
they must agree, so the proxy never silently picks one history over another.
"""

from __future__ import annotations

import re

MAX_SESSION_ID_LENGTH = 128

# Starts alphanumeric; '.', '_' and '-' allowed after, but no '..' (path
# traversal look-alike) and no trailing '.' (Windows strips it, so "a." and
# "a" would alias as file names).
_SESSION_ID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_-]|\.(?![.]|$))*")


class SessionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _validate(value: str) -> str:
    if len(value) > MAX_SESSION_ID_LENGTH or not _SESSION_ID.fullmatch(value):
        raise SessionError(
            "invalid_session_id",
            f"Session identifiers are 1-{MAX_SESSION_ID_LENGTH} characters of "
            "[A-Za-z0-9._-], starting alphanumeric, without '..' or a trailing '.'.",
        )
    return value


def resolve_session(path_id: str | None, header_id: str | None) -> str:
    if path_id is None and header_id is None:
        raise SessionError(
            "session_required",
            "No session identifier: use a /s/<session>/ base URL or the "
            "X-Mnemon-Session header.",
        )
    if path_id is not None and header_id is not None:
        if _validate(path_id) != _validate(header_id):
            raise SessionError(
                "session_mismatch",
                "The session in the URL path and the X-Mnemon-Session header differ.",
            )
        return path_id
    return _validate(path_id if path_id is not None else header_id)
