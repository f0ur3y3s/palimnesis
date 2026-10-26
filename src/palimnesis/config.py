from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .profile import DEFAULT_PROFILE


@dataclass(frozen=True)
class Settings:
    # Upstream origin without an API path, e.g. "http://192.168.1.19:8080".
    upstream_base_url: str
    # Opt-in raw exchange capture (contains conversation bodies).
    capture_dir: Path | None = None
    # Archive database. None means pure passthrough (no archiving).
    db_path: Path | None = None
    synchronous: str = "FULL"
    # Bounded views (Phase 2): "on" masks over the watermark, "off" only enforces budgets.
    view: str = "on"
    # Input budget cap in tokens; None means the default (48,000, D14.3).
    input_budget: int | None = None
    # Excerpt source for new user messages (A1). None means the one ``recall`` names.
    excerpt_source: object | None = None
    # Proactive recall (A1 Phase 3): "fts" retrieves from the archive, "off" never does.
    recall: str = "fts"
    # Development-selectable presentation (plan §5): query policy, excerpt renderer and
    # transcript addendum. Frozen after development selection.
    query_policy: str = "q1"
    excerpt_renderer: str = "x2"
    addendum: str = "a3"
    # Request-wide deadline D in seconds from arrival (contracts §5): covers recall,
    # inference and delivery after acceptance.
    deadline_s: float = 600.0
    # Transcript files root (Phase 3); None means "transcripts" beside the archive.
    transcripts: Path | None = None
    # False: no transcript files are published.
    transcripts_enabled: bool = True
    # Upstream profile name (palimnesis.profile.REGISTRY).
    profile: str = DEFAULT_PROFILE
