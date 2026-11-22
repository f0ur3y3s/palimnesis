"""Phase 8 run-readiness gate (eval/run_ready.py; plan "The run-readiness gate").

The checker runs on the host, at the commit that will run, and writes ``READY.json`` with
PASS only when every check passes. Each check is a pure function of what was read, so the
host probes are injected here."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
import headless  # noqa: E402
import run_ready as rr  # noqa: E402

sys.path.remove(str(ROOT / "eval"))

SERVER = {"props": "http://127.0.0.1:8080/props", "n_ctx": 32768, "slots": 1,
          "build": "Strata 0.1.58", "temperature": 1.0, "top_p": 0.95, "top_k": 20}
PROPS = {"default_generation_settings": {"n_ctx": 32768, "params": {
    "temperature": 1.0, "top_p": 0.95, "top_k": 20}}, "total_slots": 1,
    "build_info": "Strata 0.1.58", "chat_template": "TEMPLATE"}
NOW = 1_800_000_000.0


def _facts(**over):
    facts = {
        "suite": "2173 passed, 3 skipped in 555.29s (0:09:15)",
        "head": "abc1234", "origin": "abc1234", "dirty": [],
        "props": PROPS, "template_sha": rr.sha256_text("TEMPLATE"),
        "strata_task": True,
        "update_pause_until": NOW + 30 * 86400, "reboot_pending": False,
        "free_gb": {"C": 200.0, "E": 300.0}, "clock_offset_s": 0.4,
        "now": NOW,
    }
    return {**facts, **over}


def _plan(tmp_path):
    d = tmp_path / "run"
    headless.write_plan(d, [{"name": "s1", "argv": ["python", "x.py"]}], commit="abc1234",
                        config="cfg1", server=SERVER)
    return d


def _checks(tmp_path, short=True, evidence=None, **over):
    d = _plan(tmp_path)
    plan = headless.read_plan(d)
    return rr.evaluate(plan, _facts(**over), est_hours=10, short=short, evidence=evidence,
                       pinned_template=rr.sha256_text("TEMPLATE"), min_free_gb=50)


def _failed(checks):
    return [c["name"] for c in checks if not c["ok"]]


def test_all_checks_pass_on_a_ready_host(tmp_path):
    assert _failed(_checks(tmp_path)) == []


def test_each_problem_fails_its_own_check(tmp_path):
    cases = {
        "suite": {"suite": "1 failed, 2172 passed"},
        "git": {"dirty": [" M src/x.py"]},
        "git_pushed": {"origin": "def5678"},
        "git_commit": {"head": "fff0000", "origin": "fff0000"},
        "server": {"props": {**PROPS, "default_generation_settings": {"n_ctx": 32768, "params": {
            "temperature": 0.6, "top_p": 0.95, "top_k": 20}}}},
        "template": {"template_sha": "0" * 64},
        "strata_task": {"strata_task": False},
        "update_pause": {"update_pause_until": NOW + 3600},
        "reboot": {"reboot_pending": True},
        "disk": {"free_gb": {"C": 20.0, "E": 300.0}},
        "clock": {"clock_offset_s": 9.0},
    }
    for name, over in cases.items():
        assert _failed(_checks(tmp_path / name, **over)) == [name], name


def test_an_unreadable_fact_fails_rather_than_passes(tmp_path):
    assert _failed(_checks(tmp_path / "a", clock_offset_s=None)) == ["clock"]
    assert _failed(_checks(tmp_path / "b", props=None)) == ["server", "template"]
    assert _failed(_checks(tmp_path / "c", suite=None)) == ["suite"]


def _evidence(tmp_path):
    ev = tmp_path / "ev"
    ev.mkdir(parents=True)
    reh = ev / "rehearsal"
    headless.write_plan(reh, [{"name": "a", "argv": ["x"]}], commit="abc1234", config="cfg1")
    headless.append_state(reh, {"step": 0, "event": "started"})
    headless.append_state(reh, {"step": 0, "event": "finished", "exit": 0})
    surv = ev / "survival"
    headless.write_plan(surv, [{"name": "a", "argv": ["x"]}], commit="abc1234", config="cfg1")
    headless.append_state(surv, {"step": 0, "event": "started"})
    headless.append_state(surv, {"step": 0, "event": "started", "reason": "host-restart"})
    headless.append_state(surv, {"step": 0, "event": "finished", "exit": 0})
    report = ev / "report.md"
    report.write_text("## Primary\nsuccesses: 1/1\n", encoding="utf-8")
    for name in ("hand_check.md", "plan_check.md", "review.md"):
        (ev / name).write_text("checked\n", encoding="utf-8")
    return {"rehearsal_run": str(reh), "survival_run": str(surv), "report_output": str(report),
            "hand_check": str(ev / "hand_check.md"), "plan_check": str(ev / "plan_check.md"),
            "review": str(ev / "review.md")}


def test_a_long_run_needs_every_piece_of_evidence(tmp_path):
    ev = _evidence(tmp_path)
    assert _failed(_checks(tmp_path / "ok", short=False, evidence=ev)) == []
    assert "evidence" in _failed(_checks(tmp_path / "none", short=False, evidence=None))
    missing = {k: v for k, v in ev.items() if k != "review"}
    assert "review" in _failed(_checks(tmp_path / "m", short=False, evidence=missing))


def test_evidence_that_shows_a_problem_fails(tmp_path):
    ev = _evidence(tmp_path)
    Path(ev["report_output"]).write_text("trap suite unscored ['ho5-t1']\n", encoding="utf-8")
    assert "report_output" in _failed(_checks(tmp_path / "a", short=False, evidence=ev))
    ev = _evidence(tmp_path / "b")
    (Path(ev["rehearsal_run"]) / "STOPPED").write_text("step 1 exit 2\n", encoding="utf-8")
    assert "rehearsal_run" in _failed(_checks(tmp_path / "b2", short=False, evidence=ev))
    ev = _evidence(tmp_path / "c")
    surv = Path(ev["survival_run"])
    (surv / "state.jsonl").write_text("", encoding="utf-8")
    headless.append_state(surv, {"step": 0, "event": "started"})
    headless.append_state(surv, {"step": 0, "event": "finished", "exit": 0})
    assert "survival_run" in _failed(_checks(tmp_path / "c2", short=False, evidence=ev))


def test_ready_json_says_pass_only_when_every_check_passes(tmp_path):
    d = _plan(tmp_path)
    plan = headless.read_plan(d)
    ok = rr.evaluate(plan, _facts(), est_hours=1, short=True, evidence=None,
                     pinned_template=rr.sha256_text("TEMPLATE"), min_free_gb=50)
    rr.write_ready(d, plan, ok)
    ready = json.loads((d / "READY.json").read_text(encoding="utf-8"))
    assert (ready["result"], ready["commit"], ready["plan_sha"], ready["config"]) == (
        "PASS", "abc1234", plan["sha"], "cfg1")
    bad = rr.evaluate(plan, _facts(reboot_pending=True), est_hours=1, short=True,
                      evidence=None, pinned_template=rr.sha256_text("TEMPLATE"), min_free_gb=50)
    rr.write_ready(d, plan, bad)
    assert json.loads((d / "READY.json").read_text(encoding="utf-8"))["result"] == "FAIL"
