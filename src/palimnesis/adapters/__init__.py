"""Agent adapter files shipped inside the package (D101).

``opencode/`` and ``pi/`` are byte-identical copies of ``integrations/`` (a test keeps
them so), packaged so ``palimnesis setup`` works from a wheel install. The harness-specific
setup and check logic lives in ``palimnesis.adapters.install``.
"""

from __future__ import annotations

from importlib import resources


def read_bytes(relative: str) -> bytes:
    """One shipped adapter file, e.g. ``"pi/models.json"``."""
    return resources.files(__package__).joinpath(relative).read_bytes()
