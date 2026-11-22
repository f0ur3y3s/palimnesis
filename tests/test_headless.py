"""Phase 8 S2h: the headless runner (eval/headless.py).

A run directory holds ``plan.json`` (numbered steps, each an argv), an append-only
``state.jsonl`` and, when a step fails, ``STOPPED``. The runner resolves the next step from
the state alone, so it resumes by itself after a reboot or a crash:

- a step with a ``finished`` event of exit 0 is done;
- a step ``started`` but never ``finished`` was cut off by the host and reruns with
  ``--reason host-restart`` (the D44.7 infrastructure case);
- a step ``finished`` with a nonzero exit stops the run: ``STOPPED`` is written, and the
  runner refuses to continue until a person removes it.

It refuses to start without a readiness PASS (``eval/run_ready.py``) for the same commit,
plan hash and config."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
import headless  # noqa: E402

sys.path.remove(str(ROOT / "eval"))

STEPS = [{"name": f"s{i}", "argv": ["python", "step.py", str(i)]} for i in range(1, 4)]


def _dir(tmp_path, commit="abc1234", config="cfg1"):
    d = tmp_path / "run"
    headless.write_plan(d, STEPS, commit=commit, config=config)
    return d


def _ready(d, **over):
    plan = headless.read_plan(d)
    ready = {"result": "PASS", "commit": plan["commit"], "plan_sha": plan["sha"],
             "config": plan["config"], **over}
    (d / "READY.json").write_text(json.dumps(ready), encoding="utf-8")


class Fake:
    """A step runner that returns scripted exit codes and records what it ran."""

    def __init__(self, codes):
        self.codes, self.ran = list(codes), []

    def __call__(self, argv):
        self.ran.append(argv)
        return self.codes.pop(0)


def test_a_fresh_run_starts_at_step_one():
    plan = {"steps": STEPS}
    assert headless.next_step(plan, []) == (0, None)


def test_finished_steps_are_skipped_and_the_run_ends():
    plan = {"steps": STEPS}
    events = [{"step": i, "event": e, **({"exit": 0} if e == "finished" else {})}
              for i in range(3) for e in ("started", "finished")]
    assert headless.next_step(plan, events) == (None, None)


def test_a_step_cut_off_by_the_host_reruns_with_the_host_restart_reason():
    plan = {"steps": STEPS}
    events = [{"step": 0, "event": "started"}, {"step": 0, "event": "finished", "exit": 0},
              {"step": 1, "event": "started"}]
    assert headless.next_step(plan, events) == (1, "host-restart")


def test_a_failed_step_stops_the_run():
    plan = {"steps": STEPS}
    events = [{"step": 0, "event": "started"}, {"step": 0, "event": "finished", "exit": 2}]
    with pytest.raises(headless.Stopped, match="step 1"):
        headless.next_step(plan, events)


def test_run_executes_every_step_and_logs_it(tmp_path):
    d = _dir(tmp_path)
    _ready(d)
    fake = Fake([0, 0, 0])
    assert headless.run(d, runner=fake) == 0
    assert [a[-1] for a in fake.ran] == ["1", "2", "3"]
    events = headless.read_state(d)
    assert [(e["step"], e["event"]) for e in events] == [
        (i, e) for i in range(3) for e in ("started", "finished")]
    assert headless.status(d)["done"] == 3


def test_run_resumes_after_an_interruption_with_the_reason(tmp_path):
    d = _dir(tmp_path)
    _ready(d)
    headless.append_state(d, {"step": 0, "event": "started"})
    headless.append_state(d, {"step": 0, "event": "finished", "exit": 0})
    headless.append_state(d, {"step": 1, "event": "started"})  # the host died here
    fake = Fake([0, 0])
    assert headless.run(d, runner=fake) == 0
    assert fake.ran[0] == [*STEPS[1]["argv"], "--reason", "host-restart"]
    assert fake.ran[1] == STEPS[2]["argv"]  # the reason goes to the rerun only


def test_a_nonzero_exit_writes_stopped_and_later_runs_refuse(tmp_path):
    d = _dir(tmp_path)
    _ready(d)
    assert headless.run(d, runner=Fake([0, 3])) == 3
    stopped = (d / "STOPPED").read_text(encoding="utf-8")
    assert "step 2" in stopped and "exit 3" in stopped
    fake = Fake([0])
    assert headless.run(d, runner=fake) != 0 and fake.ran == []


@pytest.mark.parametrize("over", [{"result": "FAIL"}, {"commit": "other"},
                                  {"plan_sha": "x"}, {"config": "cfg2"}])
def test_the_run_refuses_without_a_matching_readiness_pass(tmp_path, over):
    d = _dir(tmp_path)
    _ready(d, **over)
    fake = Fake([0, 0, 0])
    assert headless.run(d, runner=fake) != 0 and fake.ran == []


def test_the_run_refuses_without_any_readiness_file(tmp_path):
    d = _dir(tmp_path)
    fake = Fake([0])
    assert headless.run(d, runner=fake) != 0 and fake.ran == []


def test_the_plan_is_immutable_once_written(tmp_path):
    d = _dir(tmp_path)
    with pytest.raises(FileExistsError):
        headless.write_plan(d, STEPS[:1], commit="abc1234", config="cfg1")


def test_status_reports_progress_and_the_stop(tmp_path):
    d = _dir(tmp_path)
    _ready(d)
    headless.run(d, runner=Fake([0, 5]))
    st = headless.status(d)
    assert (st["done"], st["total"], st["stopped"] is not None) == (1, 3, True)
    assert st["current"] is None


def test_a_recorded_rerun_decision_reruns_the_failed_step_with_its_reason(tmp_path):
    d = _dir(tmp_path)
    _ready(d)
    headless.run(d, runner=Fake([0, 3]))
    headless.decide(d, step=2, action="rerun", reason="Strata crashed (D44.7)")
    assert not (d / "STOPPED").exists()
    fake = Fake([0, 0])
    assert headless.run(d, runner=fake) == 0
    assert fake.ran[0] == [*STEPS[1]["argv"], "--reason", "Strata crashed (D44.7)"]
    assert fake.ran[1] == STEPS[2]["argv"]


def test_a_recorded_skip_decision_resumes_at_the_next_step(tmp_path):
    d = _dir(tmp_path)
    _ready(d)
    headless.run(d, runner=Fake([0, 3]))
    headless.decide(d, step=2, action="skip", reason="model failure is an outcome")
    fake = Fake([0])
    assert headless.run(d, runner=fake) == 0
    assert fake.ran == [STEPS[2]["argv"]]
    assert headless.status(d)["done"] == 2  # a skipped step is not done


def test_a_decision_needs_a_reason_and_a_stopped_step(tmp_path):
    d = _dir(tmp_path)
    _ready(d)
    headless.run(d, runner=Fake([0, 3]))
    with pytest.raises(ValueError):
        headless.decide(d, step=2, action="rerun", reason="")
    with pytest.raises(ValueError):
        headless.decide(d, step=1, action="skip", reason="not the stopped step")


PROPS = {"default_generation_settings": {"n_ctx": 32768, "params": {
    "temperature": 1.0, "top_p": 0.95, "top_k": 20}}, "total_slots": 1,
    "build_info": "Strata 0.1.58"}
SERVER = {"props": "http://127.0.0.1:8080/props", "n_ctx": 32768, "slots": 1,
          "build": "Strata 0.1.58", "temperature": 1.0, "top_p": 0.95, "top_k": 20}


def test_server_check_passes_on_the_expected_props_and_names_each_mismatch():
    assert headless.server_problem(PROPS, SERVER) is None
    wrong = {**PROPS, "default_generation_settings": {"n_ctx": 32768, "params": {
        "temperature": 0.6, "top_p": 0.95, "top_k": 20}}}
    assert "temperature" in headless.server_problem(wrong, SERVER)
    assert "n_ctx" in headless.server_problem(
        {**PROPS, "default_generation_settings": {"n_ctx": 65536, "params": PROPS[
            "default_generation_settings"]["params"]}}, SERVER)
    assert "build" in headless.server_problem({**PROPS, "build_info": "Strata 0.1.57"}, SERVER)


def test_before_each_step_the_runner_waits_for_the_server_then_runs(tmp_path):
    d = tmp_path / "run"
    headless.write_plan(d, STEPS[:1], commit="abc1234", config="cfg1", server=SERVER)
    _ready(d)
    answers = [None, None, PROPS]  # loading (unreachable) twice, then up
    fake = Fake([0])
    assert headless.run(d, runner=fake, probe=lambda url: answers.pop(0), poll_s=0) == 0
    assert fake.ran == [STEPS[0]["argv"]] and answers == []


def test_a_wrong_server_stops_the_run_before_the_step(tmp_path):
    d = tmp_path / "run"
    headless.write_plan(d, STEPS[:1], commit="abc1234", config="cfg1", server=SERVER)
    _ready(d)
    wrong = {**PROPS, "total_slots": 2}
    fake = Fake([0])
    assert headless.run(d, runner=fake, probe=lambda url: wrong, poll_s=0) != 0
    assert fake.ran == [] and "slots" in (d / "STOPPED").read_text(encoding="utf-8")


def test_a_server_that_never_comes_up_stops_the_run(tmp_path):
    d = tmp_path / "run"
    headless.write_plan(d, STEPS[:1], commit="abc1234", config="cfg1", server=SERVER)
    _ready(d)
    fake = Fake([0])
    assert headless.run(d, runner=fake, probe=lambda url: None, poll_s=0, wait_s=0) != 0
    assert fake.ran == [] and "not up" in (d / "STOPPED").read_text(encoding="utf-8")


def test_after_a_server_stop_a_recorded_retry_resumes_the_same_step(tmp_path):
    d = tmp_path / "run"
    headless.write_plan(d, STEPS[:1], commit="abc1234", config="cfg1", server=SERVER)
    _ready(d)
    headless.run(d, runner=Fake([0]), probe=lambda url: None, poll_s=0, wait_s=0)
    headless.decide(d, step=1, action="rerun", reason="Strata relaunched with the -t1 config")
    fake = Fake([0])
    assert headless.run(d, runner=fake, probe=lambda url: PROPS, poll_s=0) == 0
    assert fake.ran == [STEPS[0]["argv"]]  # never started, so no reason is passed


def test_the_plan_command_writes_a_plan_from_a_spec_file(tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"config": "cfg1", "server": SERVER, "steps": STEPS}),
                    encoding="utf-8")
    d = tmp_path / "run"
    assert headless.main(["plan", str(d), "--spec", str(spec), "--commit", "abc1234"]) == 0
    plan = headless.read_plan(d)
    assert (plan["commit"], plan["config"], plan["steps"], plan["server"]) == (
        "abc1234", "cfg1", STEPS, SERVER)


def test_plan_env_reaches_the_steps_and_is_part_of_the_plan(tmp_path):
    d = tmp_path / "run"
    step = {"name": "env", "argv": [sys.executable, "-c",
                                    "import os; print('X=' + os.environ['PALIMNESIS_X'])"]}
    plan = headless.write_plan(d, [step], commit="abc1234", config="cfg1",
                               env={"PALIMNESIS_X": "seen"})
    other = headless.write_plan(tmp_path / "other", [step], commit="abc1234", config="cfg1")
    assert plan["sha"] != other["sha"] and headless.read_plan(d)["env"] == {"PALIMNESIS_X": "seen"}
    _ready(d)
    assert headless.run(d) == 0
    assert "X=seen" in (d / "runner.log").read_text(encoding="utf-8")
