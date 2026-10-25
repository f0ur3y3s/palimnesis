"""Regressions for the Phase 3 protocol and paper-fidelity reviews."""

from __future__ import annotations

import json

import pytest

from palimnesis.recall import build_query
from palimnesis.upstreams.strata import tokens

from .test_view_http import DONE, TOOLS, body, history, post, rows, view_stack

COUNTER = tokens.default()


def _turn(messages, user):
    return messages + [{"role": "assistant", "content": "ok"}, {"role": "user", "content": user}]


def _count(messages):
    return COUNTER.count_messages(**tokens.render_args_from_openai({"messages": messages,
                                                                     "tools": TOOLS}))


def _excerpts(settings):
    return rows(settings, "SELECT status, reason, rendered FROM excerpt_blocks ORDER BY created_at")


# Protocol review 1: an archived lone surrogate inside a quoted span.
def test_an_excerpt_of_text_with_a_lone_surrogate_is_quoted_not_a_500(tmp_path):
    messages = history(30)
    messages[3]["content"] = ("line one\nzebra_quux_77 crashed \ud800 here\nline three\n"
                              + messages[3]["content"])
    messages = _turn(messages, "first")
    with view_stack(tmp_path, input_budget=8000) as (fake, url, settings):
        fake.respond_sse([DONE])
        assert post(url, body(messages, max_completion_tokens=8192)).status_code == 200
        messages = _turn(messages, "why did zebra_quux_77 crash?")
        fake.respond_sse([DONE])
        r = post(url, body(messages, max_completion_tokens=8192))

    assert r.status_code == 200
    status, reason, rendered = _excerpts(settings)[-1]
    assert status == "selected" and "zebra_quux_77 crashed � here" in rendered
    assert "zebra_quux_77 crashed � here" in json.loads(fake.requests[-1].body)["messages"][-1]["content"]


# Protocol review 2: proxy-added fixed input and history residue are counted before acceptance.
@pytest.mark.parametrize("variant", ["transcripts_off", "root_changed"])
def test_near_the_budget_a_request_is_rejected_before_acceptance_or_answered(tmp_path, variant):
    first = _turn(history(30), "first")
    long_root = tmp_path / ("q7Zx_k9Lp-" * 14) / "t"
    settings = {"input_budget": 8000}
    if variant == "transcripts_off":
        settings["transcripts_enabled"] = False
    else:
        settings["transcripts"] = long_root
    with view_stack(tmp_path, **settings) as (fake, url, _):
        fake.respond_sse([DONE])
        assert post(url, body(first, max_completion_tokens=8192)).status_code == 200
    if variant == "root_changed":
        settings["transcripts"] = tmp_path / "s"
    words = [f"alpha{i}" for i in range(3000)]
    base = _count([first[0], {"role": "user", "content": ""}])
    sizes = [n for n in range(1, 3000, 7)
             if 7300 <= base + _count([{"role": "user", "content": " ".join(words[:n])}]) <= 8100]
    assert len(sizes) > 5
    messages = first
    with view_stack(tmp_path, **settings) as (fake, url, s):
        for n in sizes:
            fake.respond_sse([DONE])
            before = rows(s, "SELECT count(*) FROM requests")[0][0]
            attempt = _turn(messages, " ".join(words[:n]))
            r = post(url, body(attempt, max_completion_tokens=8192))
            after = rows(s, "SELECT count(*) FROM requests")[0][0]
            assert r.status_code in (200, 400), r.text
            if r.status_code == 400:
                assert r.json()["error"]["code"] == "context_budget_exceeded"
                assert after == before, f"{n} words: rejected after acceptance"
            else:
                messages = attempt
        failed = rows(s, "SELECT payload FROM events WHERE kind = 'attempt_failed'")
    assert not [p for (p,) in failed if "context_budget_exceeded" in p]


# Paper-fidelity review 3: prose punctuation is not code.
def test_hyphenated_and_abbreviated_prose_is_not_code_like():
    q = build_query("a well-known follow-up, e.g. tomorrow")

    assert q.code_terms == 0
    assert q.terms == ("well known", "follow up", "tomorrow")


@pytest.mark.parametrize("text, term", [
    ("see main.py", "main py"), ("call foo::bar", "foo bar"), ("E-1234", "e 1234"),
    ("src/app", "src app"), ("parse_config", "parse config"), ("fetchUser", "fetchuser")])
def test_identifiers_paths_and_codes_stay_code_like(text, term):
    q = build_query(text)

    assert q.terms[0] == term and q.code_terms >= 1


# Paper-fidelity review 5: packing counts the real provenance, not a placeholder.
def test_a_token_dense_tool_name_does_not_lose_the_selection(tmp_path):
    dense = "q1Z9x_W7k3-" * 6  # 64 safe characters, many tokens
    messages = history(30)
    for m in messages:
        if m.get("tool_calls"):
            m["tool_calls"][0]["function"]["name"] = dense[:64]
    tool = next(m for m in messages if m.get("tool_call_id") == "call_7")
    lines = tool["content"].split("\n")
    lines[40] = "ERR_ZX81 raised by flux_capacitor.sync()"
    tool["content"] = "\n".join(lines)
    messages = _turn(messages, "why did flux_capacitor raise ERR_ZX81?")
    with view_stack(tmp_path, input_budget=8000) as (fake, url, settings):
        fake.respond_sse([DONE])
        post(url, body(messages, max_completion_tokens=8192))

    status, reason, rendered = _excerpts(settings)[-1]
    assert (status, reason) == ("selected", None)
    assert "ERR_ZX81 raised" in rendered


def test_history_residue_is_counted_before_acceptance(tmp_path):
    # Fixed input just under the budget: the collapsed history still leaves a span
    # note, so the request must be refused before acceptance, not after.
    messages = _turn(history(30), "first")
    with view_stack(tmp_path, input_budget=8000, transcripts_enabled=False) as (fake, url, _):
        fake.respond_sse([DONE])
        assert post(url, body(messages, max_completion_tokens=8192)).status_code == 200
    words = [f"alpha{i}" for i in range(3000)]
    lo, hi = 1, 3000
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _count([messages[0], {"role": "user", "content": " ".join(words[:mid])}]) <= 7998:
            lo = mid
        else:
            hi = mid - 1
    with view_stack(tmp_path, input_budget=8000, transcripts_enabled=False) as (fake, url, settings):
        fake.respond_sse([DONE])
        before = rows(settings, "SELECT count(*) FROM requests")[0][0]
        r = post(url, body(_turn(messages, " ".join(words[:lo])), max_completion_tokens=8192))
        after = rows(settings, "SELECT count(*) FROM requests")[0][0]

    assert r.status_code == 400 and r.json()["error"]["code"] == "context_budget_exceeded"
    assert after == before


# Cache audit: a move made by the rebuild with the new excerpt block (an R3 omission)
# must be the view the upstream call is attributed to. The auditor's long12b scenario.
def test_a_move_caused_by_a_new_excerpt_block_is_explained(tmp_path):
    import random
    import subprocess
    import sys
    from pathlib import Path

    from .test_transcript_loop_http import _assistant_call, _sse, _tool_call

    root = Path(__file__).resolve().parents[1]
    replay = root / "eval" / "replay.py"
    # OpenCode's real head (system prompt and 11 tools, ~5K tokens) from the live fixture.
    live = sorted((root / "eval/fixtures/opencode-2.1.4/live/exchanges").glob("*/*"))[-1]
    oc = json.loads((live / "request.body").read_text(encoding="utf-8"))

    def body(messages, **extra):
        return json.dumps({"model": "m", "messages": messages, "tools": oc["tools"],
                           "stream": True, **extra}).encode()

    rnd = random.Random(4)
    vocab = ["parser", "router", "ledger", "socket", "codec", "planner", "quota", "widget"]
    messages = [{"role": "system", "content": oc["messages"][0]["content"]},
                {"role": "user", "content": "Refactor the project and keep the tests green."}]
    needles: list[tuple[int, str, str, str]] = []
    with view_stack(tmp_path, input_budget=12000) as (fake, url, settings):
        for k in range(50):
            if k % 3 == 2:
                old = [n for n in needles if n[0] <= k - 10]
                if old:
                    step, mod, fn, err = rnd.choice(old)
                    user = (f"The {mod} module raised {err} earlier. Fix {fn} so that the "
                            f"{mod} retry path no longer exhausts its budget (step {k}).")
                else:
                    user = f"Continue with the next file (step {k})."
                fake.respond_sse([_sse({"index": 0, "delta": {"reasoning_content": "Sum up. " * 10}},
                                       {"index": 0, "delta": {"content": "Done."}},
                                       {"index": 0, "delta": {}, "finish_reason": "stop"})])
                assert post(url, body(messages, max_completion_tokens=8192)).status_code == 200
                messages = messages + [{"role": "assistant", "content": "Done."},
                                       {"role": "user", "content": user}]
                continue
            lines = rnd.randint(5, 60)
            mod = f"{rnd.choice(vocab)}{k}"
            err = f"ERR_{mod.upper()}_{rnd.randint(100, 999)}"
            at = rnd.randrange(lines)
            out = "\n".join(f'raise ConfigError("{err}: budget exhausted in {mod}")' if n == at
                            else f"    def load_{mod}_{n}(self, x): return self.{mod}_{n} * {n}"
                            for n in range(lines))
            needles.append((k, mod, f"load_{mod}_{at}", err))
            args = {"filePath": f"src/{mod}.py"}
            fake.respond_sse([_tool_call(f"call_{k}", "read", args, "Inspect next. " * 12)])
            assert post(url, body(messages, max_completion_tokens=8192)).status_code == 200
            messages = messages + [_assistant_call(f"call_{k}", "read", args),
                                   {"role": "tool", "tool_call_id": f"call_{k}", "content": out}]
        causes = [c for (c,) in rows(settings, "SELECT cause FROM view_versions")]

    assert any(c == "excerpt_omitted" for c in causes), causes  # a rebuild-only move happened
    out = subprocess.run([sys.executable, str(replay), "--explain", str(settings.db_path), "--json"],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout[-1500:] + out.stderr[-1500:]
