from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    # Upstream origin without an API path, e.g. "http://192.168.1.173:8080".
    upstream_base_url: str
    # Opt-in raw exchange capture (contains conversation bodies).
    capture_dir: Path | None = None
    # Archive database. None means pure passthrough (no archiving).
    db_path: Path | None = None
    synchronous: str = "FULL"
