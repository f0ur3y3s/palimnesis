"""Phase 3B evaluation tooling (S9; plan §2.9, D56, O-B2, O-B3, O-B6): the arm-5 matrix
configurations and the held-out alias, OpenCode's output limit per arm, the internal-call
metrics read from an archive, the internal-leak scan, and the fresh held-out set's
registration. Pure functions and a small archive built through ``palimnesis.ledger``;
nothing here runs OpenCode, a proxy or a model."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from palimnesis import ledger
from palimnesis.chat import parse
from palimnesis.fingerprint import fingerprint_v1
from palimnesis.ledger import Generation
from palimnesis.store import Store

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval"), str(ROOT / "eval" / "tasks")]

import gate_inputs  # noqa: E402
import needle  # noqa: E402
import needle_opencode  # noqa: E402
import oc_harness  # noqa: E402
import oc_stack  # noqa: E402
import report  # noqa: E402
import run as task_run  # noqa: E402

sys.path.remove(str(ROOT / "eval"))
sys.path.remove(str(ROOT / "eval" / "tasks"))

A4_BASE = dict(recall="fts", transcripts_enabled=True, query_policy="q1", excerpt_renderer="x2")


# ---------------------------------------------------------------- arm 5 configurations

@pytest.mark.parametrize("name, stub, addendum, tools", [
    ("a5-A", "s2", "a1", "t1"),
    ("a5-B", "s3", "a1", "t1"),
    ("a5-C", "s2", "a0", "t2"),
    ("a5-D", "s0", "a1", "t2"),
])
def test_arm_5_matrix_configs_are_arm_4_plus_stub_addendum_and_tools(name, stub, addendum, tools):
    cfg = needle.CONFIGS[name]
    assert cfg == dict(arm=5, **A4_BASE, stub=stub, addendum=addendum, hidden_tools=tools)
    assert needle.proxy_settings(cfg) == dict(**A4_BASE, stub=stub, addendum=addendum,
                                              hidden_tools=tools)


@pytest.mark.parametrize("name, base", [("a5-Cp", "a5-C"), ("a5-Dp", "a5-D")])
def test_pinned_arm_5_configs_are_their_matrix_arm_plus_4096_pin_tokens(name, base):
    """R29 fixes (D65): the top two matrix arms re-run with pinned instructions."""
    cfg = needle.CONFIGS[name]
    assert cfg == dict(needle.CONFIGS[base], pin_tokens=4096)
    assert needle.proxy_settings(cfg) == dict(needle.proxy_settings(needle.CONFIGS[base]),
                                              pin_tokens=4096)


def test_arm_4_proxy_settings_are_unchanged():
    assert needle.proxy_settings(needle.CONFIGS["a4-d43"]) == dict(**A4_BASE, addendum="a3")


def test_the_held_out_arm_5_name_refuses_until_frozen(monkeypatch):
    assert needle.A5_HELDOUT == "a5-d64"
    assert needle.A5_HELDOUT not in needle.CONFIGS
    assert needle.config("a4-d43") is needle.CONFIGS["a4-d43"]
    monkeypatch.setattr(needle, "A5_FROZEN", None)
    with pytest.raises(ValueError, match="not frozen"):
        needle.config("a5-d64")
    monkeypatch.setattr(needle, "A5_FROZEN", "a5-C")
    assert needle.config("a5-d64") == needle.CONFIGS["a5-C"]
    with pytest.raises(KeyError):
        needle.config("a5-Z")


def _args(**kw):
    import argparse

    return argparse.Namespace(**{"set": "heldout", "config": "a4-d43", "questions": None,
                                 "resume": False, **kw})


@pytest.mark.parametrize("set_name", ["heldout", "heldout2"])
def test_held_out_needles_accept_arm_4_and_the_arm_5_alias_only(set_name):
    def config_refusals(config):
        return [p for p in needle_opencode.refusals(_args(set=set_name, config=config), [Path("h")])
                if "held-out needles run only" in p]

    assert config_refusals("a4-d43") == []
    assert config_refusals("a5-d64") == []
    assert config_refusals("a5-A") and config_refusals("a4-x2")
    # Development needles take any configuration.
    assert not [p for p in needle_opencode.refusals(_args(set="development", config="a5-A"), [Path("h")])
                if "held-out" in p]


def test_task_arms_resolve_to_a_label_and_a_config(monkeypatch):
    four = task_run.resolve_arm(4, None, "heldout")
    assert (four["label"], four["config"], four["cfg"]) == ("a4", "a4-d43", needle.CONFIGS["a4-d43"])
    one = task_run.resolve_arm(1, None, "heldout")
    assert (one["label"], one["config"], one["cfg"]) == ("a1", "a1-native", None)
    five = task_run.resolve_arm(5, "a5-B", "development")
    assert (five["label"], five["config"], five["cfg"]) == ("a5-B", "a5-B", needle.CONFIGS["a5-B"])
    with pytest.raises(ValueError, match="--config"):
        task_run.resolve_arm(5, None, "development")
    with pytest.raises(ValueError, match="a5-d64"):  # held-out tasks run only the frozen arm
        task_run.resolve_arm(5, "a5-B", "heldout")
    with pytest.raises(ValueError, match="arm 4"):
        task_run.resolve_arm(4, "a5-B", "development")
    monkeypatch.setattr(needle, "A5_FROZEN", "a5-D")
    held = task_run.resolve_arm(5, "a5-d64", "heldout")
    assert (held["label"], held["config"], held["cfg"]) == ("a5-d64", "a5-d64", needle.CONFIGS["a5-D"])


def test_result_json_records_the_arms_config(monkeypatch):
    monkeypatch.setattr(needle, "A5_FROZEN", "a5-C")
    f = task_run.arm_fields(task_run.resolve_arm(5, "a5-d64", "heldout"), 32768)
    assert f == {"arm": 5, "config": "a5-d64", "frozen_as": "a5-C",
                 "config_settings": needle.CONFIGS["a5-C"], "passthrough": False,
                 "input_budget": None, "emulated_n_ctx": None,
                 "opencode_limit_context": 1_000_000, "opencode_limit_output": 24_576,
                 "compaction_auto": False}
    f = task_run.arm_fields(task_run.resolve_arm(4, None, "heldout"), 32768)
    assert (f["config"], f["opencode_limit_output"], f["passthrough"]) == ("a4-d43", 8192, False)
    f = task_run.arm_fields(task_run.resolve_arm(1, None, "heldout"), 65536)
    assert (f["config"], f["opencode_limit_context"], f["compaction_auto"]) == ("a1-native", 65536, True)


# ---------------------------------------------------------------- OpenCode limit.output (O-B3)

def test_opencode_output_limit_per_arm():
    assert task_run.opencode_output_limit(5) == needle.output_limit(5) == 24_576
    assert task_run.opencode_output_limit(4) == needle.output_limit(4) == 8192
    assert task_run.opencode_output_limit(1) == 8192
    model = lambda cfg: cfg["providers"][oc_harness.PROVIDER]["models"][oc_harness.MODEL_ID]  # noqa: E731
    assert model(oc_harness.config("http://x/v1"))["limit"] == {"context": 1_000_000, "output": 8192}
    assert model(oc_harness.config("http://x/v1", output_limit=24_576))["limit"]["output"] == 24_576
    # Arm 5 keeps the large context: Palimnesis owns the input budget.
    assert task_run.opencode_context_limit(5, 32768) == 1_000_000


# ---------------------------------------------------------------- internal-call metrics

SID = "ev3b"


def _write(store, fn):
    return asyncio.run(store.write(fn))


def _accept(store, sid, messages):
    req = parse(json.dumps({"model": "m", "stream": True, "messages": messages}).encode())
    fp = fingerprint_v1(ledger.ENDPOINT_CHAT, sid, ledger.branch_id_for(sid), json.loads(req.raw))
    return _write(store, lambda c: ledger.accept(c, session_id=sid, association="path", req=req,
                                                 fingerprint=fp, retry_hint=None, live=set()))


def _call(i, name):
    return ("tool_call", ("tool", i), "{}", {"id": f"call_{name}_{i}", "name": name, "internal": True})


def _result(store, gen, call, meta):
    _, _, _, m = call
    _write(store, lambda c: ledger.commit_internal_result(c, gen, m["id"], m["name"], "result", meta))


def _upstream_call(store, plan, call_id):
    _write(store, lambda c: ledger.record_event(c, plan, "upstream_call", call_id=call_id,
                                                branch_id=plan.branch_id))


@pytest.fixture
def archive(tmp_path):
    """Session ev3b: one response of three upstream calls with four hidden calls (recall x3,
    grep x1): an unknown address, a found block, a grep page and a limit-reached recall.
    Session other: one plain response."""
    db = tmp_path / "archive.db"
    store = Store.open(db)
    try:
        plan = _accept(store, SID, [{"role": "system", "content": "s"},
                                    {"role": "user", "content": "what was E-4123?"}])
        g1 = Generation(plan)
        c1, c2 = _call(0, "palimnesis_recall"), _call(1, "palimnesis_grep")
        _write(store, lambda c: ledger.commit_batch(c, g1, [("text", "text", "Checking. ", {}), c1, c2], 0))
        _result(store, g1, c1, {"ok": False, "error": "unknown_address"})
        _result(store, g1, c2, {"ok": True})
        _upstream_call(store, plan, plan.attempt_id)
        g2 = _write(store, lambda c: ledger.next_generation(c, g1))
        c3 = _call(0, "palimnesis_recall")
        _write(store, lambda c: ledger.commit_batch(c, g2, [c3], 0))
        _result(store, g2, c3, {"ok": True, "address": "§ABCDEF.0"})
        _upstream_call(store, plan, f"{plan.attempt_id}#2")
        g3 = _write(store, lambda c: ledger.next_generation(c, g2))
        c4 = _call(0, "palimnesis_recall")
        _write(store, lambda c: ledger.commit_batch(c, g3, [c4], 0))
        _result(store, g3, c4, {"ok": False, "error": "limit_reached"})
        _upstream_call(store, plan, f"{plan.attempt_id}#3")
        _write(store, lambda c: ledger.finish_attempt(c, g3, "turn_complete"))
        other = _accept(store, "other", [{"role": "user", "content": "hi"}])
        g = Generation(other)
        _write(store, lambda c: ledger.commit_batch(c, g, [("text", "text", "hello", {})], 0))
        _upstream_call(store, other, other.attempt_id)
        _write(store, lambda c: ledger.finish_attempt(c, g, "turn_complete"))
    finally:
        store.close()
    return db


def test_internal_metrics_from_an_archive(archive):
    m = report.internal_metrics(archive)
    assert m["hidden_calls"] == 4
    assert m["calls_by_tool"] == {"palimnesis_recall": 3, "palimnesis_grep": 1}
    assert m["results_by_tool"] == {"palimnesis_recall": 3, "palimnesis_grep": 1}
    assert m["recall_calls"] == 3 and m["invalid_ids"] == 1
    assert m["invalid_id_rate"] == pytest.approx(1 / 3)
    assert m["errors"] == {"unknown_address": 1, "limit_reached": 1}
    assert m["limit_reached"] == 1
    assert m["responses"] == 2 and m["continuations"] == 2
    assert m["continuations_per_response"] == {0: 1, 2: 1}
    assert m["max_continuations"] == 2 and m["mean_continuations"] == pytest.approx(1.0)


def test_internal_metrics_by_session(archive):
    m = report.internal_metrics(archive, sessions=["other"])
    assert (m["hidden_calls"], m["recall_calls"], m["invalid_id_rate"]) == (0, 0, 0.0)
    assert (m["responses"], m["continuations"]) == (1, 0)
    assert report.internal_metrics(archive, sessions=[SID])["hidden_calls"] == 4


def test_invalid_ids_are_the_three_address_errors():
    assert set(report.INVALID_ID_ERRORS) == {"unknown_address", "ambiguous_address", "unknown_block"}


def _sse(*deltas) -> bytes:
    return b"".join(b"data: " + json.dumps({"choices": [{"index": 0, "delta": d}]}).encode() + b"\n\n"
                    for d in deltas) + b"data: [DONE]\n\n"


def test_the_upstream_tap_records_hidden_calls_by_name():
    raw = _sse({"content": "x"},
               {"tool_calls": [{"index": 0, "id": "c0", "function": {"name": "palimnesis_recall", "arguments": ""}}]},
               {"tool_calls": [{"index": 0, "function": {"arguments": "{}"}}]},
               {"tool_calls": [{"index": 1, "id": "c1", "function": {"name": "read", "arguments": "{}"}}]},
               {"tool_calls": [{"index": 2, "id": "c2", "function": {"name": "palimnesis_grep", "arguments": "{}"}}]})
    assert needle.parse_usage(raw)["hidden_calls"] == ["palimnesis_recall", "palimnesis_grep"]
    assert "hidden_calls" not in needle.parse_usage(_sse({"content": "x"}))
    assert needle.hidden_by_tool([{"hidden_calls": ["palimnesis_recall"]}, {},
                                  {"hidden_calls": ["palimnesis_grep", "palimnesis_recall"]}]) == \
        {"palimnesis_recall": 2, "palimnesis_grep": 1}


def test_lookups_count_hidden_calls_plus_harness_transcript_calls():
    rows = [{"history": "h", "session": "s", "step": "q1", "kind": "question", "category": "c",
             "exact": True, "exact_loose": True, "partial": False, "contains": True, "answered": True,
             "answer": "a", "gold": "a", "rounds": 2, "tool_calls": [{"name": "read", "lookup": True}],
             "lookups": 3, "hidden_calls": {"palimnesis_recall": 2}, "prompt_tokens": 0,
             "completion_tokens": 0, "cached_tokens": 0, "calls": [], "errors": [], "total_s": 1.0,
             "fact_absent": False, "unnecessary_lookups": 3}]
    s = report.summarize(rows, {}, {})
    assert (s["lookups"], s["hidden_calls"], s["harness_lookups"]) == (3, 2, 1)
    assert s["hidden_by_tool"] == {"palimnesis_recall": 2}
    assert s["unnecessary_lookups"] == 3


# ---------------------------------------------------------------- internal leaks (O-B6, D62.4)
#
# Hard leaks fail the gate: a hidden call (``palimnesis_*`` name or a hidden call's id) in
# the proxy's client stream, or a hidden result's text (whole, or a distinctive 40-character
# slice: one that occurs in no earlier archived content) in that stream or in what
# OpenCode's export says it received. Mentions are reported only: ``palimnesis_`` text the
# model wrote itself, and such text a harness tool result brought back (a transcript read).

PRIOR = "the kiln log says E-4123 kilnworks ok at line 123 of deploy.log, all fine"
RESULT_TEXT = "[palimnesis_recall §ABCDEF.0 tool_result · 0–72 of 72]\n" + PRIOR
HIDDEN_ID = "call_hidden_1"


def _sse_multi(*deltas) -> bytes:
    return _sse(*deltas)


def _tc(i, cid, name, args="{}"):
    return {"tool_calls": [{"index": i, "id": cid, "function": {"name": name, "arguments": args}}]}


@pytest.fixture
def leak_run(tmp_path):
    db = tmp_path / "archive.db"
    store = Store.open(db)
    try:
        plan = _accept(store, "leak", [{"role": "system", "content": "s"},
                                       {"role": "user", "content": "Look at deploy.log: " + PRIOR}])
        g1 = Generation(plan)
        _write(store, lambda c: ledger.commit_batch(c, g1, [("tool_call", ("tool", 0), '{"id": "§ABCDEF.0"}', {
            "id": HIDDEN_ID, "name": "palimnesis_recall", "internal": True})], 0))
        _write(store, lambda c: ledger.commit_internal_result(c, g1, HIDDEN_ID, "palimnesis_recall",
                                                              RESULT_TEXT, {"ok": True}))
        g2 = _write(store, lambda c: ledger.next_generation(c, g1))
        _write(store, lambda c: ledger.commit_batch(c, g2, [("text", "text", "It was fine.", {})], 0))
        _write(store, lambda c: ledger.finish_attempt(c, g2, "turn_complete"))
    finally:
        store.close()
    front = tmp_path / "front"
    front.mkdir()
    streams = {
        # A mention the model wrote, and a verbatim quote of earlier content: neither is hard.
        1: _sse({"reasoning_content": "maybe palimnesis_grep would help"},
                {"content": "The log: " + PRIOR[:60]}),
        2: _sse(_tc(0, HIDDEN_ID, "read")),                         # a hidden call's id
        3: _sse(_tc(0, "c3", "palimnesis_grep")),                    # a reserved name
        4: _sse({"content": "Recalled: " + RESULT_TEXT[:70]}),        # a fragment: an echo
        5: _sse(_tc(0, "c5", "read", '{"path": "turn-0003.md"}')),
        8: _sse({"content": "Recalled: " + RESULT_TEXT}),             # a result's whole text
    }
    for n, raw in streams.items():
        (front / f"{n:04d}.resp.sse").write_bytes(raw)
        (front / f"{n:04d}.json").write_text(json.dumps({"messages": [{"role": "user", "content": "q"}]}),
                                             encoding="utf-8")
    # The transcript read's result comes back in the next request (twice: history is resent).
    tool_msg = {"role": "tool", "tool_call_id": "c5",
                "content": "turn-0003.md: [internal] palimnesis_recall §ABCDEF.0"}
    for n in (6, 7):
        (front / f"{n:04d}.json").write_text(json.dumps({"messages": [tool_msg]}), encoding="utf-8")
        (front / f"{n:04d}.resp.sse").write_bytes(_sse({"content": "ok"}))
    export = {"info": {}, "messages": [
        {"type": "user", "text": "q", "files": []},
        {"type": "assistant", "content": [
            {"type": "reasoning", "text": "maybe palimnesis_grep would help"},
            {"type": "text", "text": "Recalled: " + RESULT_TEXT[:70]},
            {"type": "tool", "id": "c5", "name": "read", "state": {
                "status": "completed", "input": {"path": "turn-0003.md"},
                "content": [{"type": "text", "text": "turn-0003.md: [internal] palimnesis_recall §ABCDEF.0"}],
                "metadata": {}}},
            {"type": "tool", "id": "c9", "name": "palimnesis_catalog", "state": {
                "status": "completed", "input": {}, "content": [], "metadata": {}}}]}]}
    calls = [{"n": n, "path": "/s/leak/v1/chat/completions"} for n in range(1, 9)]
    return db, tmp_path, calls, {"leak": export}


def test_internal_scan_splits_hard_leaks_from_mentions(leak_run):
    db, records, calls, exports = leak_run
    s = gate_inputs.internal_scan(db, records, calls, exports)
    assert s["hard"] == {"stream_calls": 2, "stream_results": 1, "export_calls": 1,
                         "export_results": 0, "leaks": 4}
    # Model: the stream's reasoning (the export's copy of it is not counted twice).
    # Harness: one tool result (c5), however often the history resends it.
    assert s["mentions"] == {"model": 1, "harness": 1}
    # A fragment of a result's own text the model quotes is an echo (D62.4 amended, R29).
    assert s["echoes"] == {"stream": 1, "export": 1}


def test_a_clean_run_has_no_hard_leaks(leak_run):
    db, records, calls, _ = leak_run
    s = gate_inputs.internal_scan(db, records, [calls[0], calls[4]], {})
    assert s["hard"]["leaks"] == 0 and s["mentions"] == {"model": 1, "harness": 0}
    assert s["echoes"] == {"stream": 0, "export": 0}


def test_result_slices_found_in_earlier_content_are_not_distinctive(leak_run):
    db, *_ = leak_run
    hidden = gate_inputs.hidden_artifacts(db)
    assert hidden["ids"] == {HIDDEN_ID}
    texts = ["The log: " + PRIOR, "x " + RESULT_TEXT[:45] + " y", "x " + RESULT_TEXT + " y"]
    assert [gate_inputs.result_hits(hidden, t) for t in texts] == [None, "echo", "leak"]


def test_arm_5_inputs_need_zero_hard_leaks_and_few_invalid_ids():
    ok = {"explain_gate": {"ok": True}, "verify": {"exit": 0}, "over_budget": {"ok": True},
          "excerpt_scan": {"client": {"leaks": 0}, "transcripts": {"leaks": 0}},
          "internal_scan": {"hard": {"leaks": 0}, "mentions": {"model": 4, "harness": 2}},
          "internal": {"invalid_id_rate": 0.05}}
    assert report.arm_inputs_ok(ok, 5)  # mentions never gate
    assert not report.arm_inputs_ok({**ok, "internal_scan": {"hard": {"leaks": 1}}}, 5)
    assert not report.arm_inputs_ok({**ok, "internal": {"invalid_id_rate": 0.06}}, 5)
    assert not report.arm_inputs_ok({k: v for k, v in ok.items() if k != "internal_scan"}, 5)
    assert report.arm_inputs_ok({k: v for k, v in ok.items() if k not in ("internal_scan", "internal")}, 4)


def test_continuations_count_only_each_requests_designated_attempt(tmp_path):
    """A failed attempt and its retry: only the retry counts. A cancelled attempt with no
    retry counts for nothing."""
    db = tmp_path / "archive.db"
    store = Store.open(db)
    try:
        ask = [{"role": "system", "content": "s"}, {"role": "user", "content": "go"}]
        first = _accept(store, "retried", ask)
        g = Generation(first)
        _write(store, lambda c: ledger.commit_batch(c, g, [_call(0, "palimnesis_recall")], 0))
        for cid in (first.attempt_id, f"{first.attempt_id}#2", f"{first.attempt_id}#3"):
            _upstream_call(store, first, cid)
        _write(store, lambda c: ledger.finish_attempt(c, g, "attempt_failed", reason="upstream_reset"))
        retry = _accept(store, "retried", ask)
        assert retry.request_id == first.request_id and retry.attempt_id != first.attempt_id
        g2 = Generation(retry)
        _write(store, lambda c: ledger.commit_batch(c, g2, [("text", "text", "done", {})], 0))
        for cid in (retry.attempt_id, f"{retry.attempt_id}#2"):
            _upstream_call(store, retry, cid)
        _write(store, lambda c: ledger.finish_attempt(c, g2, "turn_complete"))
        gone = _accept(store, "gone", ask)
        g3 = Generation(gone)
        _write(store, lambda c: ledger.commit_batch(c, g3, [("text", "text", "par", {})], 0))
        for cid in (gone.attempt_id, f"{gone.attempt_id}#2"):
            _upstream_call(store, gone, cid)
        _write(store, lambda c: ledger.finish_attempt(c, g3, "cancelled"))
    finally:
        store.close()
    m = report.internal_metrics(db)
    assert (m["responses"], m["continuations"], m["continuations_per_response"]) == (1, 1, {1: 1})


def test_coding_gate_for_arm_5_against_arm_1():
    tasks = ["ho2-t1", "ho2-t2"]
    res = {("ho2-t1", 5): {"check": {"success": True}, "restart_gate": True},
           ("ho2-t2", 5): {"check": {"success": False}},
           ("ho2-t1", 1): {"check": {"success": True}}, ("ho2-t2", 1): {"check": {"success": False}}}
    g = report.coding_gate(res, tasks, arm=5, restart_task="ho2-t1")
    assert (g["arm_successes"], g["arm1_successes"], g["restart_gate"], g["pass"]) == (1, 1, True, True)
    res[("ho2-t1", 5)]["restart_gate"] = False
    assert not report.coding_gate(res, tasks, arm=5, restart_task="ho2-t1")["pass"]


# ---------------------------------------------------------------- the fresh held-out set (O-B1)

def test_heldout2_needle_set_is_registered(tmp_path, monkeypatch):
    assert needle.SETS["heldout2"] == ("heldout2", "ho2")
    d = tmp_path / "eval" / "needles" / "heldout2"
    d.mkdir(parents=True)
    for i in (10, 2, 1):
        h = {"id": f"ho2-h{i}", "steps": [{"id": f"q{i}", "kind": "question", "category": "c",
                                           "answer": str(i)}]}
        (d / f"ho2-h{i}.json").write_text(json.dumps(h), encoding="utf-8")
    monkeypatch.setattr(needle, "ROOT", tmp_path)
    args = _args(set="heldout2", histories=None)
    assert [p.stem for p in needle.select_histories(args)] == ["ho2-h1", "ho2-h2", "ho2-h10"]
    assert [p.stem for p in needle.select_histories(_args(set="heldout2", histories="h2"))] == ["ho2-h2"]
    exp = report.expected_needles("heldout2", root=tmp_path / "eval" / "needles")
    assert exp == {f"ho2-h{i}": [{"id": f"q{i}", "category": "c", "answer": str(i)}] for i in (1, 10, 2)}
    assert report.expected_needles("heldout2", root=tmp_path / "missing") == {}
    assert report.SET_SHAPE["heldout2"] == report.SET_SHAPE["heldout"] == (12, 10)


def test_heldout2_tasks_are_registered_and_missing_modules_are_skipped(capsys):
    assert [t for t in task_run.TASKS if t.startswith("ho2-")] == [f"ho2-t{i}" for i in range(1, 6)]
    assert {"dev-t4", "dev-t5"} <= set(task_run.TASKS)
    assert task_run.load_optional("ho2-t99") is None
    assert task_run.check_reference(["ho2-t99"]) == 0
    assert "ho2-t99: not present, skipped" in capsys.readouterr().out
    assert set(task_run.available(["dev-t1", "ho2-t99"])) == {"dev-t1"}


def test_dev_t4_states_its_key_constraint_only_before_the_restart():
    t = task_run.load("dev-t4")
    assert t.KEY_CONSTRAINT == "C2" and t.SET == "development"
    assert "half up" in t.TURNS[0] and "2.5" in t.TURNS[0]
    for turn in t.TURNS[1:]:
        assert "half up" not in turn.lower() and "round" not in turn.lower()
    assert "render_report" in t.TURNS[t.RESTART_BEFORE]
    assert "render_report" not in " ".join(t.TURNS[1:t.RESTART_BEFORE])


def test_dev_t5_needs_facts_from_earlier_turns_only_in_its_long_turn():
    t = task_run.load("dev-t5")
    assert t.KEY_CONSTRAINT is None and t.SET == "development"
    note = t.TURNS[2]
    files = t.files(__import__("random").Random(task_run.task_seed(t.ID)))
    for code, label in zip(t.NOTE_CODES, t.NOTE_LABELS):
        assert code in note and label in note
        assert all(code not in turn and label not in turn for i, turn in enumerate(t.TURNS) if i != 2)
        assert all(label not in text for text in files.values()), label
        assert all(code not in text for rel, text in files.items() if not rel.startswith("samples/"))
        assert any(code in text for rel, text in files.items() if rel.startswith("samples/")), code
    long_turn = t.TURNS[t.LONG_TURN]
    assert "samples/" in long_turn and t.LONG_TURN > t.RESTART_BEFORE


# R28-A: two sessions built from one deploy-log template. A grep snippet collapses the
# template's double spaces; the model's copy of its own session's paste does too.
LOG_LINE = "2026-10-21T10:00:01Z INFO  canary rollout step 3 of 5 ok, queue depth 12 nominal"
GREP_RESULT = ("[palimnesis_grep text 'canary' · 1 hit · page 1]\n"
               "§AB12CD.0 seq 3 user lines 1-1: " + " ".join(LOG_LINE.split()))


def test_leak_scan_pairs_sessions_and_normalizes_whitespace(tmp_path):
    db = tmp_path / "archive.db"
    store = Store.open(db)
    try:
        for sid, hidden in (("h2", True), ("h5", False)):
            plan = _accept(store, sid, [{"role": "system", "content": "s"},
                                        {"role": "user", "content": "Here is the deploy log:\n" + LOG_LINE}])
            g = Generation(plan)
            if hidden:
                _write(store, lambda c: ledger.commit_batch(c, g, [("tool_call", ("tool", 0), "{}", {
                    "id": "call_g1", "name": "palimnesis_grep", "internal": True})], 0))
                _write(store, lambda c: ledger.commit_internal_result(c, g, "call_g1", "palimnesis_grep",
                                                                      GREP_RESULT, {"ok": True}))
                g = _write(store, lambda c: ledger.next_generation(c, g))
            _write(store, lambda c: ledger.commit_batch(c, g, [("text", "text", "noted", {})], 0))
            _write(store, lambda c: ledger.finish_attempt(c, g, "turn_complete"))
    finally:
        store.close()
    front = tmp_path / "front"
    front.mkdir()
    copy = " ".join(LOG_LINE.split())  # the model's whitespace-collapsed copy of the paste
    note = _tc(0, "c1", "write", json.dumps({"path": "notes.md", "content": "Deploy log: " + copy}))
    streams = {1: ("h5", _sse(note)), 2: ("h2", _sse(note)),
               3: ("h2", _sse({"content": "Search said: " + GREP_RESULT[:60]}))}
    for n, (sid, raw) in streams.items():
        (front / f"{n:04d}.resp.sse").write_bytes(raw)
        (front / f"{n:04d}.json").write_text(json.dumps({"messages": []}), encoding="utf-8")
    calls = [{"n": n, "path": f"/s/{sid}/v1/chat/completions"} for n, (sid, _) in streams.items()]
    exports = {"h5": {"messages": [{"type": "assistant", "content": [
        {"type": "tool", "id": "c1", "name": "write",
         "state": {"input": {"path": "notes.md", "content": "Deploy log: " + copy}}}]}]}}
    # The copies in h5 (no hidden results) and in h2 (its own paste, normalized) are clean.
    clean = gate_inputs.internal_scan(db, tmp_path, calls[:2], exports)
    assert clean["hard"]["leaks"] == 0, clean
    # A quote of the result's own framing is an echo in its session's stream (R29).
    s = gate_inputs.internal_scan(db, tmp_path, calls, exports)
    assert s["hard"]["leaks"] == 0 and s["echoes"]["stream"] == 1


# R29: a grep hit on the model's own earlier reasoning. The result frames the line as
# "L1: Now I need ...", so a window can start with the space before "Now"; the earlier
# archived block starts with "Now". The model's stream ("... recall that. Now I need ...")
# is its own text, not the result.
REASONING = "Now I need the port. The env file does not specify a port, so the archive must hold it."


def test_leak_scan_matches_windows_across_archived_block_starts(tmp_path):
    db = tmp_path / "archive.db"
    store = Store.open(db)
    try:
        plan = _accept(store, "h6", [{"role": "system", "content": "s"},
                                     {"role": "user", "content": "Find the staging port."}])
        g = Generation(plan)
        _write(store, lambda c: ledger.commit_batch(c, g, [("reasoning", "reasoning", REASONING, {})], 0))
        _write(store, lambda c: ledger.commit_batch(c, g, [("tool_call", ("tool", 0), "{}", {
            "id": "call_g1", "name": "palimnesis_grep", "internal": True})], 0))
        frame = "[palimnesis_grep regex all · hits 1–1 · page 1] §AB12CD.0 seq 3 assistant reasoning L1:"
        frame = frame[:-4] + "x" * (-len(frame) % gate_inputs.SLICE) + frame[-4:]
        result = frame + " " + REASONING
        _write(store, lambda c: ledger.commit_internal_result(c, g, "call_g1", "palimnesis_grep",
                                                              result, {"ok": True}))
        g = _write(store, lambda c: ledger.next_generation(c, g))
        _write(store, lambda c: ledger.commit_batch(c, g, [("text", "text", "noted", {})], 0))
        _write(store, lambda c: ledger.finish_attempt(c, g, "turn_complete"))
    finally:
        store.close()
    assert any(w.startswith(" Now") for w in gate_inputs._windows(gate_inputs.normalize_ws(result)))
    front = tmp_path / "front"
    front.mkdir()
    (front / "0001.resp.sse").write_bytes(_sse({"reasoning_content": "Let me recall that. " + REASONING}))
    (front / "0001.json").write_text(json.dumps({"messages": []}), encoding="utf-8")
    calls = [{"n": 1, "path": "/s/h6/v1/chat/completions"}]
    assert gate_inputs.internal_scan(db, tmp_path, calls, {})["hard"]["leaks"] == 0


# ---------------------------------------------------------------- emulated 32K (O2) through OpenCode

def test_emulated_context_follows_the_input_budget():
    assert gate_inputs.emulated_n_ctx(24_320, 65536) == 32768
    assert gate_inputs.emulated_n_ctx(48_000, 65536) == 56448  # the smallest n_ctx with that budget
    with pytest.raises(ValueError, match="no n_ctx"):
        gate_inputs.emulated_n_ctx(60_000, 65536)
    assert gate_inputs.run_budget(65536, None) == 48_000
    assert gate_inputs.run_budget(65536, 24_320) == 24_320


def test_result_json_records_the_emulated_budget():
    one = task_run.arm_fields(task_run.resolve_arm(1, None, "development"), 65536, input_budget=24_320)
    assert (one["opencode_limit_context"], one["input_budget"], one["emulated_n_ctx"]) == (32768, 24_320, 32768)
    four = task_run.arm_fields(task_run.resolve_arm(4, None, "development"), 65536, input_budget=24_320)
    assert (four["opencode_limit_context"], four["input_budget"]) == (1_000_000, 24_320)
    plain = task_run.arm_fields(task_run.resolve_arm(1, None, "heldout"), 32768)
    assert (plain["opencode_limit_context"], plain["input_budget"], plain["emulated_n_ctx"]) == (32768, None, None)


def test_the_report_judges_against_a_recorded_input_budget():
    assert report.budget_for({"expect_n_ctx": 65536, "input_budget": 24_320}) == 24_320
    assert report.budget_for({"expect_n_ctx": 65536, "input_budget": "default (serve)"}) == 48_000


def test_the_stack_passes_the_input_budget_to_the_proxy(tmp_path, monkeypatch):
    seen = []

    class Proxy:
        def __init__(self, records, upstream, settings, input_budget=None, passthrough=False):
            seen.append(input_budget)
            self.url, self.db, self.starts = "http://127.0.0.1:1", records / "archive.db", 0

        def start(self):
            pass

    class Server:
        should_exit = False

    monkeypatch.setattr(oc_stack.needle, "ProxyProcess", Proxy)
    monkeypatch.setattr(oc_stack.needle, "serve_in_thread", lambda app, port: (Server(), None))
    oc_stack.Stack(tmp_path, "http://x", {}, input_budget=24_320)
    oc_stack.Stack(tmp_path, "http://x", {})
    assert seen == [24_320, None]


def test_the_drivers_accept_input_budget():
    import inspect

    assert "--input-budget" in inspect.getsource(needle.main)
    assert "--input-budget" in inspect.getsource(task_run.main)
