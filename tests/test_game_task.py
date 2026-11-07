"""game-t1 (the user's TINY TANK WAR prompt): the hidden check passes the reference game and
fails an empty workspace, a page that throws while running, and a page that loads a file."""

from __future__ import annotations

import shutil
import sys

import pytest

from .test_eval_s11 import _runner

# The check runs the game in Node, as the agents' host does; a host without Node skips these.
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _check(overlay):
    task_run = _runner()
    task = task_run.load("game-t1")
    return task, task_run.check_one(task, overlay, sys.executable)


@needs_node
def test_the_reference_game_passes_every_check():
    task, ref = _check(_runner().load("game-t1").REFERENCE)
    assert ref["success"], ref["tail"]
    assert ref["functional_passed"] == ref["functional_total"] == 8
    assert ref["constraints_held"] == ref["constraints_total"] == 1


def test_an_empty_workspace_fails():
    _, stub = _check({})
    assert not stub["success"] and stub["functional_passed"] == 0


@needs_node
def test_a_game_that_throws_while_running_fails_only_the_run_check():
    task = _runner().load("game-t1")
    broken = task.REFERENCE["index.html"].replace("function draw() {", "function draw() {\n  if (state.level) undefinedThing();")
    _, r = _check({"index.html": broken})
    assert not r["success"]
    assert r["results"]["test_f_runs_900_frames"] != "ok"
    assert r["results"]["test_f_scripts_parse"] == "ok"


def test_a_page_that_loads_a_script_file_breaks_the_constraint():
    task = _runner().load("game-t1")
    page = task.REFERENCE["index.html"].replace("</head>", '<script src="https://cdn.example/x.js"></script></head>')
    _, r = _check({"index.html": page})
    assert r["constraints"]["C1"] is False


@needs_node
def test_a_gradient_given_nan_fails_the_run_check_as_in_a_browser():
    # Browsers throw on a non-finite gradient argument (pair 2's a4-d77 game: `b.maxR` read
    # where `max` was stored, so every explosion's radius was NaN).
    task = _runner().load("game-t1")
    page = task.REFERENCE["index.html"].replace(
        "ctx.beginPath(); ctx.arc(b.x, b.y, b.r, 0, Math.PI * 2); ctx.fill();",
        "ctx.fillStyle = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, Math.max(1, b.missing));"
        " ctx.beginPath(); ctx.arc(b.x, b.y, b.r, 0, Math.PI * 2); ctx.fill();")
    assert page != task.REFERENCE["index.html"]
    _, r = _check({"index.html": page})
    assert r["results"]["test_f_runs_900_frames"] != "ok", r["tail"]
