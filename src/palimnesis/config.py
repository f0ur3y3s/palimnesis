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
    # Stub format: s1, or a Phase 3B matrix variant (s0, s2, s3; docs/affordances.md).
    stub: str = "s1"
    # Hidden recall tools (Phase 3B): the tools affordance (t1 or t2) whose schemas are
    # fixed at a session's first masked view, or None for none.
    hidden_tools: str | None = None
    # Pinned instructions (D65): total tokens of short user instructions a collapse keeps
    # in view; 0 is off.
    pin_tokens: int = 0
    # The current turn's own work stays in view (D70); off keeps the frozen behaviour.
    protect_turn: bool = False
    # Working notes (D72): the notes slot in tokens; 0 is off. A collapse move then
    # refreshes the notes with one internal upstream call.
    notes_tokens: int = 0
    # Working-notes format: n1 (D72), or n2 with the current step second, a slot-sized
    # length, cuts by section and notes taken from reasoning when the reply is empty (D74).
    notes_format: str = "n1"
    # Working-notes header: h1 (D72), or h2, which asks for values quoted in full (D75).
    notes_header: str = "h1"
    # Excerpt retrieval: r1, or r2 without reasoning (D71).
    retrieval: str = "r1"
    # Request-wide deadline D in seconds from arrival (contracts §5): covers recall,
    # inference and delivery after acceptance.
    deadline_s: float = 600.0
    # Transcript files root (Phase 3); None means "transcripts" beside the archive.
    transcripts: Path | None = None
    # False: no transcript files are published.
    transcripts_enabled: bool = True
    # Upstream profile name (palimnesis.profile.REGISTRY).
    profile: str = DEFAULT_PROFILE
