"""The archive addresses a pinned state cites (Phase 4A, D105.4).

The pinned state is the model's own working notes (D72, contracts §17), introduced after
R33-D found native compaction's summaries were what made it win. Phase 4A records which
archive addresses a state names, so a reader can check whether the state points at real
evidence. Nothing is rewritten: an unknown address is recorded as such. This is
bookkeeping over Palimnesis's own address forms, not a research mechanism.

Addresses are the model-facing forms Palimnesis itself renders: ``§ALIAS`` with an
optional ``.N`` block (``archive.addresses``), and transcript turn files ``turn-NNNN``
(``transcripts.projection``). Bare base32-looking words are never taken: ``PARSER`` is
valid Crockford base32.
"""

from __future__ import annotations

import re

_ADDRESS = re.compile(
    r"§(?P<alias>[0-9A-Za-z]{6,}(?:\.\d+)?)"
    r"|(?<![\w-])(?P<turn>turn-\d{4,})(?:\.md)?(?![\w-])")


def cited_addresses(text: str) -> list[tuple[str, str]]:
    """``(kind, token)`` for each address ``text`` names, in order: ``("alias", "5DM5KG")``,
    ``("alias", "5DM5KG.3")`` or ``("turn", "turn-0004")``. A ``§`` alias followed by a dot
    and no digits keeps only the alias."""
    out = []
    for m in _ADDRESS.finditer(text):
        if m.group("alias"):
            out.append(("alias", m.group("alias")))
        else:
            out.append(("turn", m.group("turn")))
    return out
