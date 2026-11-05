"""The Strata 0.1.48 upstream profile (D15 amended).

``pins`` vendors the chat template and tokenizer, ``tokens`` renders and counts with
them, ``facts`` reads ``/props`` and runs the ``count_tokens`` canary, ``errors`` maps
Strata's error shapes and ``cache`` holds the cache-reuse model.
"""

from __future__ import annotations

from palimnesis.upstreams.profile import TemplateRules, UpstreamProfile
from palimnesis.upstreams.strata import pins, tokens
from palimnesis.upstreams.strata.cache import StrataCacheModel
from palimnesis.upstreams.strata.errors import StrataErrors
from palimnesis.upstreams.strata.facts import CountTokensCrossCheck, StatusProbe, UpstreamState

PROFILE_ID = "strata-0.1.48"

# docs/probes/strata.md §2: every earlier turn keeps its reasoning (preserve_thinking is
# ignored); the pinned template raises "System message must be at the beginning."
# §4: completed empty assistant turns are dropped before rendering (#843, D41).
RULES = TemplateRules(reasoning_every_turn=True, leading_system_only=True,
                      drops_empty_assistant=True)


def profile(base_url: str) -> UpstreamProfile:
    counter = tokens.default()
    cross_check = CountTokensCrossCheck(base_url, counter)
    return UpstreamProfile(
        id=PROFILE_ID,
        counter=counter,
        facts=UpstreamState(base_url, pins.load(), counter, cross_check),
        cross_check=cross_check,
        cache_model=StrataCacheModel(),
        errors=StrataErrors(),
        rules=RULES,
        slot_probe=StatusProbe(base_url),
    )
