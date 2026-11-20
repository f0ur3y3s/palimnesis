"""Phase 7 tooling: serving metrics in the task runner (S2) and the host epoch (S3).

S2: a turn's and a run's totals count every upstream call the turn caused, the proxy's
notes refresh and arm 1's compaction requests included, combined and split by kind; the
time to first visible content is the client stream's, never an upstream call's.
S3: every run reads the upstream's serving epoch before and after over HTTP; a run whose
epoch changed or whose counters went down is flagged, and so is a task pair whose two
runs were not in one epoch. Nothing here runs a harness or a model."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval"), str(ROOT / "eval" / "tasks")]

import gate_inputs as gi  # noqa: E402
import needle  # noqa: E402
import run as task_run  # noqa: E402

sys.path.remove(str(ROOT / "eval"))
sys.path.remove(str(ROOT / "eval" / "tasks"))

from palimnesis.view.builder import NOTES_PROMPT, ViewPolicy, notes_prompt  # noqa: E402

from .fake_upstream import FakeUpstream  # noqa: E402
from .servers import serve  # noqa: E402


def _write(bodies: Path, n: int, last_user: str | list) -> None:
    body = {"model": "m", "messages": [{"role": "system", "content": "s"},
                                       {"role": "user", "content": last_user}]}
    (bodies / f"{n:04d}.json").write_text(json.dumps(body), encoding="utf-8")


def _call(n, prompt, completion, cached, prompt_ms, **extra):
    return {"n": n, "prompt_tokens": prompt, "completion_tokens": completion,
            "cached_tokens": cached, "timings": {"prompt_ms": prompt_ms}, **extra}


# ---------------------------------------------------------------- S2

def test_task_totals_include_refresh_and_compaction_calls(tmp_path):
    bodies = tmp_path / "bodies"
    bodies.mkdir()
    _write(bodies, 1, "implement part 1")
    _write(bodies, 2, NOTES_PROMPT)  # n1's refresh prompt
    _write(bodies, 3, [{"type": "text", "text": notes_prompt(ViewPolicy(notes_tokens=2048, notes_format="n2"))}])
    _write(bodies, 4, "go on")
    _write(bodies, 5, task_run.COMPACTION_PROMPTS[0] + " ...")
    calls = [_call(1, 1000, 50, 800, 120.5), _call(2, 1100, 400, 1000, 30.25),
             _call(3, 900, 300, 0, 600.0), _call(4, 1200, 20, 1100, 10.0),
             _call(5, 1300, 700, 1200, 40.0), {"n": 6, "prompt_tokens": None}]  # 6: no body
    kinds = task_run.call_kinds(bodies, calls)
    assert kinds == {1: "main", 2: "refresh", 3: "refresh", 4: "main", 5: "compaction",
                     6: "main"}

    totals = task_run.call_totals(calls, kinds)
    assert totals["main"] == {"calls": 3, "prompt_tokens": 2200, "completion_tokens": 70,
                              "cached_tokens": 1900, "prompt_ms": 130.5}
    assert totals["refresh"] == {"calls": 2, "prompt_tokens": 2000, "completion_tokens": 700,
                                 "cached_tokens": 1000, "prompt_ms": 630.25}
    assert totals["compaction"] == {"calls": 1, "prompt_tokens": 1300, "completion_tokens": 700,
                                    "cached_tokens": 1200, "prompt_ms": 40.0}
    assert totals["combined"] == {"calls": 6, "prompt_tokens": 5500, "completion_tokens": 1470,
                                  "cached_tokens": 4100, "prompt_ms": 800.75}

    turn = task_run.turn_metrics(calls, [], kinds, t0=0.0)
    assert (turn["prompt_tokens"], turn["completion_tokens"], turn["cached_tokens"],
            turn["prompt_ms"], turn["max_prompt_tokens"]) == (5500, 1470, 4100, 800.75, 1300)
    assert turn["totals"] == totals


def test_ttfvc_per_turn():
    t0 = 1000.0
    # The turn's first upstream call is the notes refresh: its notes stream as content
    # at the upstream tap one second in, but the client sees nothing until the main
    # call's answer reaches the front tap at 5.25 s.
    upstream = [_call(1, 900, 300, 0, 600.0, t_first_content=t0 + 1.0),
                _call(2, 1000, 50, 800, 120.5, t_first_content=t0 + 5.0)]
    kinds = {1: "refresh", 2: "main"}
    front = [{"n": 1, "t_first_content": t0 + 5.25}]
    assert task_run.turn_metrics(upstream, front, kinds, t0)["ttfvc_s"] == 5.25
    # Two client calls in one turn (a tool round): the first visible delta counts.
    front2 = [{"n": 1}, {"n": 2, "t_first_content": t0 + 9.5},
              {"n": 3, "t_first_content": t0 + 12.0}]
    assert task_run.turn_metrics(upstream, front2, kinds, t0)["ttfvc_s"] == 9.5
    # Nothing visible (the client saw only reasoning, or an error): no ttfvc.
    assert task_run.turn_metrics(upstream, [{"n": 1}], kinds, t0)["ttfvc_s"] is None
    # What the taps call visible: text or a tool call, never reasoning.
    assert needle.VISIBLE.search(b'{"delta": {"content": "Hi"}}')
    assert needle.VISIBLE.search(b'{"delta": {"tool_calls": [{"index": 0}]}}')
    assert not needle.VISIBLE.search(b'{"delta": {"reasoning_content": "hm"}}')
    assert not needle.VISIBLE.search(b'{"delta": {"role": "assistant", "content": ""}}')


# ---------------------------------------------------------------- S3

def test_epoch_recorded_before_after_each_run():
    fake = FakeUpstream(props_n_ctx=32768, props_build_info="Strata 0.1.58",
                        status_engine="0.1.58", status_activity=41)
    with serve(fake.app()) as url:
        before = gi.host_epoch(url)
        fake.status_activity, fake.status_uptime_s = 57, 900  # the run's own calls
        after = gi.host_epoch(url)
        # Relaunched with the same command: a new start time, counters from zero.
        fake.status_started, fake.status_activity, fake.status_uptime_s = 1792900000, 3, 40
        relaunched = gi.host_epoch(url)

    assert fake.requests == []  # the readings never reach the scripted routes
    assert {k: before[k] for k in ("upstream", "build", "engine", "model", "n_ctx", "started",
                                   "uptime_s", "activity_requests", "gpu_used_mib",
                                   "gpu_total_mib")} == {
        "upstream": url, "build": "Strata 0.1.58", "engine": "0.1.58",
        "model": "qwen3.8-flash-next-iq3_xxs", "n_ctx": 32768, "started": 1792871477,
        "uptime_s": 18, "activity_requests": 41, "gpu_used_mib": 11868.0,
        "gpu_total_mib": 12288.0}
    assert isinstance(before["epoch"], str) and len(before["epoch"]) == 16
    assert after["epoch"] == before["epoch"]
    assert gi.epoch_summary(before, after) == {"before": before, "after": after, "flags": [],
                                               "flagged": False}
    run = gi.epoch_summary(after, relaunched)
    assert relaunched["epoch"] != before["epoch"]
    assert run["flagged"] and run["flags"] == ["epoch_changed", "activity_dropped",
                                               "uptime_dropped"]
    # Without a start time the epoch id cannot see a relaunch; the counters still do.
    assert gi.epoch_flags({**after, "epoch": "e"}, {**relaunched, "epoch": "e"}) == [
        "activity_dropped", "uptime_dropped"]
    # An upstream that cannot be read is never taken for the same epoch.
    gone = gi.host_epoch("http://127.0.0.1:9")
    assert gone["epoch"] is None and gone["error"]
    assert gi.epoch_flags(before, gone) == ["unread"]


def _reading(epoch, at, activity, uptime):
    return {"epoch": epoch, "at": at, "activity_requests": activity, "uptime_s": uptime}


def _result(before, after):
    return {"host_epoch": gi.epoch_summary(before, after)}


def test_pair_split_across_epochs_flagged():
    a = _result(_reading("e1", 100, 10, 1000), _reading("e1", 200, 30, 1100))
    b = _result(_reading("e1", 210, 31, 1110), _reading("e1", 300, 50, 1200))
    assert gi.pair_split_across_epochs(a, b) is False
    assert gi.pair_split_across_epochs(b, a) is False  # order of the arguments is free
    # The second arm ran after a relaunch: another epoch.
    other = _result(_reading("e2", 210, 2, 15), _reading("e2", 300, 20, 105))
    assert gi.pair_split_across_epochs(a, other) is True
    # A restart between the two runs that the epoch id missed: the counters went down.
    hidden = _result(_reading("e1", 210, 3, 20), _reading("e1", 300, 20, 110))
    assert gi.pair_split_across_epochs(a, hidden) is True
    # One run was itself split by a relaunch.
    split = _result(_reading("e1", 210, 31, 1110), _reading("e2", 300, 5, 30))
    assert split["host_epoch"]["flagged"]
    assert gi.pair_split_across_epochs(a, split) is True
    # A run with no epoch record (or an unread one) cannot show the pair is whole.
    assert gi.pair_split_across_epochs(a, {}) is True
    unread = _result(_reading(None, 210, None, None), _reading("e1", 300, 50, 1200))
    assert gi.pair_split_across_epochs(a, unread) is True
