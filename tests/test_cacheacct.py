"""Cache accounting (contracts §10; plan Phase 2 slice 9).

Pure seams: the Strata reuse model against the recorded probe (docs/probes/strata.md §7)
and the reuse classification. HTTP seams: one ``upstream_call`` event per upstream call,
its attributed cause, and ``eval/replay.py --explain``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from palimnesis import profile

ROOT = Path(__file__).resolve().parents[1]


# --- the probe conversation, rebuilt exactly (eval/probes/p07_cache.py --multiturn) ---


def _filler(n_words: int, seed: int) -> str:
    sys.path.insert(0, str(ROOT / "eval" / "probes"))
    try:
        from strata_common import filler
    finally:
        sys.path.pop(0)
    return filler(n_words, seed=seed)


@pytest.fixture(scope="module")
def probe():
    """The renders of cache_multiturn_edit.json's steps (every reply was "OK")."""
    sys_msg = {"role": "system", "content": "You are a terse assistant. " + _filler(100, 70)}
    turns = [_filler(350, 71 + i) for i in range(4)]
    grow, msgs = [], [sys_msg]
    for i, text in enumerate(turns):
        msgs = msgs + [{"role": "user", "content": f"Turn {i + 1}:\n{text}\nReply OK."}]
        grow.append(msgs)
        msgs = msgs + [{"role": "assistant", "content": "OK"}]
    final = msgs + [{"role": "user", "content": "Reply YES."}]
    edit2 = [dict(m) for m in final]
    edit2[3] = {"role": "user", "content": "Turn 2: [masked: archived as #abc123]\nReply OK."}
    edit4 = [dict(m) for m in final]
    edit4[7] = {"role": "user", "content": "Turn 4: [masked]\nReply OK."}
    p = profile.load(profile.DEFAULT_PROFILE, "http://127.0.0.1:1")

    def layout(messages):
        return p.counter.layout(messages, None, effort="none")

    return p.cache_model, {"grow": [layout(m) for m in grow], "final": layout(final),
                           "edit2": layout(edit2), "edit4": layout(edit4)}


def test_strata_cache_model_matches_probe(probe):
    model, r = probe
    # The local renders are the probe's prompts (cache_multiturn_edit.json prompt_tokens).
    assert [len(x.ids) for x in r["grow"]] == [1050, 1880, 2663, 3441]
    assert [len(r[k].ids) for k in ("final", "edit2", "edit4")] == [3459, 2663, 2707]

    # grow_turn_2: resumed at turn 1's assistant-turn checkpoint (cached 1043).
    assert model.expected(r["grow"][0], r["grow"][1]) == 1043
    # repeat_turn_5: everything but the generation prompt (7 tokens) is reused (cached 3452).
    assert model.expected(r["final"], r["final"]) == 3452
    # edit_turn_2_masked: the last checkpoint before the edit is 1043; 1,620 re-read.
    assert model.expected(r["final"], r["edit2"]) == 1043
    assert len(r["edit2"].ids) - 1043 == 1620
    # edit_turn_4_masked: resumed at 2,656; 51 re-read. The probe's immediate predecessor
    # was edit_turn_2, and 2,656 is a checkpoint the unedited history's prefill left
    # (turn 3's assistant start); from edit_turn_2's own render alone the estimate is the
    # 1,043 checkpoint, a lower bound under the measured reuse.
    assert model.expected(r["final"], r["edit4"]) == 2656
    assert len(r["edit4"].ids) - 2656 == 51
    assert model.expected(r["edit2"], r["edit4"]) == 1043
    # No predecessor: nothing to reuse.
    assert model.expected(None, r["final"]) == 0


def test_strata_checkpoints_limit_six_and_keep_a_large_system_root():
    p = profile.load(profile.DEFAULT_PROFILE, "http://127.0.0.1:1")
    system = {"role": "system", "content": _filler(1800, 5)}  # well over 2,048 tokens
    messages = [system]
    for i in range(9):
        messages += [{"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": "a"}]
    messages.append({"role": "user", "content": "last"})
    layout = p.counter.layout(messages, None, effort="none")
    head = layout.segments[0]
    assert head.kind == "head" and head.end - head.start >= 2048
    starts = [s.start for s in layout.segments if s.kind in ("assistant", "generation")]
    assert p.cache_model.checkpoints(layout) == tuple(sorted([head.end] + starts[-6:]))
    # An edit to the oldest user message falls back to the system root.
    edited = [dict(m) for m in messages]
    edited[1] = {"role": "user", "content": "q0 edited"}
    assert p.cache_model.expected(layout, p.counter.layout(edited, None, effort="none")) == head.end


# --- the live OpenCode exchanges (eval/fixtures/opencode-2.1.4/live) ---

LIVE = ROOT / "eval" / "fixtures" / "opencode-2.1.4" / "live" / "exchanges"


@pytest.fixture(scope="module")
def live():
    """(layout, recorded Usage) per live exchange, in order."""
    import json

    from palimnesis.capture import load_exchanges

    p = profile.load(profile.DEFAULT_PROFILE, "http://127.0.0.1:1")
    out = []
    for ex in load_exchanges(LIVE):
        body = json.loads(ex.request_body)
        tools, kw = p.counter.render_args(body)
        final = [e for e in ex.response_body.split(b"\n\n") if b'"usage"' in e][-1]
        usage = p.cross_check.usage(json.loads(final[len(b"data: "):]))
        out.append((p.counter.layout(body["messages"], tools, **kw), usage))
    return p, out


def test_layout_maps_every_turn_and_counts_exactly_on_live_bodies(live):
    _, exchanges = live
    for layout, usage in exchanges:
        assert len(layout.ids) == usage.prompt_tokens
        assert all(s.kind != "unmapped" for s in layout.segments)
        assert layout.segments[0].kind == "head" and layout.segments[-1].kind == "generation"
        assert [(a.end == b.start) for a, b in zip(layout.segments, layout.segments[1:])] \
            == [True] * (len(layout.segments) - 1)


def test_checkpoint_limited_classification(probe, live):
    from palimnesis.cacheacct import classify

    model, r = probe
    # grow_turn_2 (cache_multiturn_edit.json): the whole of turn 1 is a common prefix, but
    # Strata resumed at turn 1's assistant-turn checkpoint: cached 1,043 of LCP 1,050.
    prev, cur = r["grow"][0], r["grow"][1]
    lcp = profile.common_prefix(prev.ids, cur.ids)
    assert lcp == 1050
    estimate = model.expected(prev, cur)
    assert classify("append", lcp=lcp, cached=1043, estimate=estimate,
                    generation_start=cur.generation_start) == "checkpoint_limited"
    # edit_turn_2_masked: the masking edit leaves 1,043 reused, the checkpoint before it.
    lcp = profile.common_prefix(r["final"].ids, r["edit2"].ids)
    assert 1043 < lcp < 1100
    assert classify("watermark_move", lcp=lcp, cached=1043,
                    estimate=model.expected(r["final"], r["edit2"]),
                    generation_start=r["edit2"].generation_start) == "checkpoint_limited"
    # The live OpenCode appends reuse past the previous prompt (exchange 1: 5,088 > 5,004).
    p, exchanges = live
    (prev, _), (cur, usage) = exchanges[0], exchanges[1]
    lcp = profile.common_prefix(prev.ids, cur.ids)
    assert lcp == 5004 and usage.cached_tokens == 5088
    assert classify("append", lcp=lcp, cached=usage.cached_tokens,
                    estimate=p.cache_model.expected(prev, cur),
                    generation_start=cur.generation_start) == "full"
    # repeat_turn_5: 3,452 of 3,459, the generation prompt re-read, is full reuse.
    assert classify("append", lcp=3459, cached=3452, estimate=model.expected(r["final"], r["final"]),
                    generation_start=r["final"].generation_start) == "full"


def test_restart_eviction_classified(live):
    from palimnesis.cacheacct import classify

    p, exchanges = live
    (prev, _), (cur, usage) = exchanges[0], exchanges[1]
    lcp = profile.common_prefix(prev.ids, cur.ids)
    estimate = p.cache_model.expected(prev, cur)
    # Exchange 1 appended to exchange 0: Strata keeps at least the generation-prompt
    # checkpoint (5,004 − 5 = 4,999); a cold answer (as after the probe's restarts,
    # cache_reuse.json "first": cached 0) means the upstream lost its state.
    assert estimate == 4999
    assert classify("append", lcp=lcp, cached=0, estimate=estimate,
                    generation_start=cur.generation_start) == "restart_or_eviction"
    # An unexplained change is never reclassified as eviction.
    assert classify("unexplained", lcp=lcp, cached=0, estimate=estimate,
                    generation_start=cur.generation_start) == "unexplained"
    # No usage, no class.
    assert classify("append", lcp=lcp, cached=None, estimate=estimate,
                    generation_start=cur.generation_start) is None
