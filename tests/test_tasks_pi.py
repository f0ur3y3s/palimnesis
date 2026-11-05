"""The coding-task runner's Pi harness (Phase 4B S14, ``eval/tasks/run.py --harness pi``):
refusals, the two arms' Pi settings, the empty session file, compaction counting from Pi's
events and summarizer requests, the fake model's script and the records ``report.py``
reads. Shapes come from ``docs/probes/pi.md`` (HP5, HP7) and its fixtures; nothing here
runs Pi, a proxy or a model."""

from __future__ import annotations

import json
import re
import sys
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval"), str(ROOT / "eval" / "tasks")]

import attempts as att  # noqa: E402
import dev_t1  # noqa: E402,F401  (task modules: run.load finds them once imported)
import dev_t4  # noqa: E402,F401
import ho2_t1  # noqa: E402,F401
import needle  # noqa: E402
import pi_harness as pi  # noqa: E402
import pi_task  # noqa: E402
import report  # noqa: E402
import run as task_run  # noqa: E402

sys.path.remove(str(ROOT / "eval"))
sys.path.remove(str(ROOT / "eval" / "tasks"))


# ---------------------------------------------------------------- refusals and arms

def test_development_tasks_run_both_arms():
    assert pi_task.refusals("development", 4, None, "chat", "http://u") == []
    assert pi_task.refusals("development", 4, "a4-d77", "messages", "http://u") == []
    assert pi_task.refusals("development", 1, None, "messages", "http://u") == []


@pytest.mark.parametrize("task_set", ["heldout", "heldout3", "heldout4"])
def test_every_held_out_set_is_refused(task_set):
    assert pi_task.refusals(task_set, 4, None, "chat", "http://u")


def test_ho2_runs_as_development_data():
    """The plan's coding row is dev-t1..t5 plus the ho2 tasks, development data per D69."""
    assert pi_task.refusals("heldout2", 4, None, "chat", "http://u") == []
    assert pi_task.refusals("heldout2", 1, None, "messages", "http://u") == []


def test_other_arms_and_configurations_are_refused():
    assert pi_task.refusals("development", 5, "a5-A", "chat", "http://u")
    assert pi_task.refusals("development", 4, "a4-d43", "chat", "http://u")
    assert pi_task.refusals("development", 1, "a4-d77", "chat", "http://u")


def test_fake_upstream_is_chat_only_on_the_passthrough_arm():
    assert pi_task.refusals("development", 1, None, "messages", "fake")
    assert pi_task.refusals("development", 4, None, "messages", "fake") == []


def test_run_pi_refuses_before_touching_an_upstream(capsys):
    a = Namespace(task="ho3-t1", arm=4, config=None, protocol="chat", upstream="http://127.0.0.1:1",
                  pi_keep_recent_tokens=None, expect_n_ctx=32768, input_budget=None)
    assert task_run.run_pi(a) == 2
    assert "development tasks only" in capsys.readouterr().err
    b = Namespace(**{**vars(a), "task": "dev-t1", "pi_keep_recent_tokens": 2000})
    assert task_run.run_pi(b) == 2
    assert "arm 1" in capsys.readouterr().err


def test_arm_4_is_a4_d77_under_the_label_the_report_reads():
    info = pi_task.resolve_arm(4)
    oc = task_run.resolve_arm(4, "a4-d77", "development")
    assert info == oc
    assert info["label"] == report.A4_LABEL3 == needle.A4_HELDOUT3
    assert pi_task.resolve_arm(1) == task_run.resolve_arm(1, None, "development")


def test_arm_4_keeps_the_adapter_and_arm_1_compacts_at_the_real_context():
    adapter = json.loads((pi.ADAPTER / "settings.json").read_text(encoding="utf-8"))
    models = pi.adapter_models()["providers"]
    assert pi_task.pi_config(4, 32768) == {
        "context_window": models["palimnesis"]["models"][0]["contextWindow"],
        "compaction": adapter["compaction"]}
    assert pi_task.pi_config(4, 32768)["context_window"] == 1_000_000
    assert pi_task.pi_config(4, 32768)["compaction"] == {"enabled": False}
    assert pi_task.pi_config(1, 65536) == {"context_window": 65536, "compaction": {"enabled": True}}
    assert pi_task.pi_config(1, 32768, 4000)["compaction"] == {"enabled": True, "keepRecentTokens": 4000}


def test_arm_1_keeps_few_enough_recent_tokens_for_compaction_to_run():
    """Pi's defaults (reserve 16,384, keep 20,000) compact nothing below a 36,384 window:
    the threshold fires but ``prepareCompaction`` finds no cut point (D99). Below that,
    arm 1 keeps a quarter of the window."""
    assert pi_task.pi_config(1, 32768) == {
        "context_window": 32768, "compaction": {"enabled": True, "keepRecentTokens": 8192}}
    assert pi_task.pi_config(1, 36384)["compaction"] == {"enabled": True}
    assert pi_task.pi_config(1, 36383)["compaction"]["keepRecentTokens"] == 9095


def test_arm_fields_record_pi_settings_and_the_emulated_context():
    a1 = pi_task.arm_fields(pi_task.resolve_arm(1), 65536, input_budget=24320)
    assert (a1["arm"], a1["config"], a1["passthrough"], a1["compaction_auto"]) == (1, "a1-native", True, True)
    assert a1["emulated_n_ctx"] == 32768 and a1["pi_context_window"] == 32768
    a4 = pi_task.arm_fields(pi_task.resolve_arm(4), 32768)
    assert (a4["config"], a4["passthrough"], a4["pi_context_window"], a4["pi_compaction"]) == \
        ("a4-d77", False, 1_000_000, {"enabled": False})
    assert a4["config_settings"] == needle.CONFIGS["a4-d77"]


def test_session_name_is_a_valid_pi_session_id():
    s = pi_task.session_name("dev-t4", "a4-d77", "11051530", 3)
    assert s == "dev-t4-a4-d77-11051530-a3"
    assert re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", s)


# ---------------------------------------------------------------- Pi home and session

def test_pi_home_applies_tools_context_window_and_compaction(tmp_path):
    home = pi.PiHome(tmp_path / "pi", tmp_path / "ws", "http://127.0.0.1:4321", "chat",
                     tools=pi_task.TOOLS, context_window=32768,
                     compaction={"enabled": True, "keepRecentTokens": 4000})
    models = json.loads((home.agent / "models.json").read_text(encoding="utf-8"))
    settings = json.loads((home.agent / "settings.json").read_text(encoding="utf-8"))
    for p in models["providers"].values():
        assert p["baseUrl"].startswith("http://127.0.0.1:4321")
        assert [m["contextWindow"] for m in p["models"]] == [32768]
    assert settings["compaction"] == {"enabled": True, "keepRecentTokens": 4000}
    assert home.tools == "read,grep,bash,ls,find,edit,write"
    assert b"\r\n" not in (home.agent / "settings.json").read_bytes()


def test_pi_home_defaults_are_unchanged_for_the_needle_driver(tmp_path):
    home = pi.PiHome(tmp_path / "pi", tmp_path / "ws", "http://127.0.0.1:4321")
    assert home.tools == pi.TOOLS == "read,grep,bash,ls,find"
    assert home.settings["compaction"] == {"enabled": False}
    assert all(m["contextWindow"] == 1_000_000 for p in home.models["providers"].values()
               for m in p["models"])


def test_new_session_file_is_the_header_alone(tmp_path):
    f = pi.new_session_file(tmp_path / "s" / "dev-t1-a1-x-a1.jsonl", "dev-t1-a1-x-a1", "/w",
                            t0_ms=1_793_872_800_000)
    raw = f.read_bytes()
    assert raw.count(b"\n") == 1 and b"\r" not in raw
    assert pi.read_session(f) == [{"type": "session", "version": 3, "id": "dev-t1-a1-x-a1",
                                   "timestamp": "2026-11-05T10:00:00.000Z", "cwd": "/w"}]


# ---------------------------------------------------------------- compaction

HP5_EVENTS = [  # hp5_threshold_on, trimmed
    {"type": "agent_end", "messages": []},
    {"type": "compaction_start", "reason": "threshold"},
    {"type": "compaction_end", "reason": "threshold",
     "result": {"summary": "s", "firstKeptEntryId": "20748cfc", "tokensBefore": 30005,
                "estimatedTokensAfter": 1392}, "aborted": False, "willRetry": False},
    {"type": "agent_settled", "aborted": False},
]


def test_compaction_events_count_each_start():
    assert pi.compaction_events(HP5_EVENTS) == [
        {"reason": "threshold", "ended": True, "aborted": False, "tokens_before": 30005,
         "tokens_after": 1392, "error": None}]
    two = HP5_EVENTS[1:3] + [{"type": "compaction_start", "reason": "overflow"}]
    got = pi.compaction_events(two)
    assert [c["reason"] for c in got] == ["threshold", "overflow"]
    assert got[1]["ended"] is False
    assert pi.compaction_events([{"type": "agent_settled", "aborted": False}]) == []


def test_compaction_end_without_start_still_counts():
    got = pi.compaction_events([{"type": "compaction_end", "reason": "overflow", "aborted": True}])
    assert len(got) == 1 and got[0]["aborted"] is True and got[0]["reason"] == "overflow"


SUMMARIZER = "You are a context summarization assistant. Your task is to read a conversation"


@pytest.mark.parametrize("body", [
    {"messages": [{"role": "developer", "content": SUMMARIZER},
                  {"role": "user", "content": [{"type": "text", "text": "<conversation>"}]}]},
    {"messages": [{"role": "system", "content": SUMMARIZER}, {"role": "user", "content": "x"}]},
    {"system": [{"type": "text", "text": SUMMARIZER, "cache_control": {"type": "ephemeral"}}],
     "messages": [{"role": "user", "content": "x"}]},
])
def test_summarizer_requests_are_compaction_on_either_protocol(body):
    assert pi.is_compaction_request(body)


def test_ordinary_requests_are_not_compaction():
    assert not pi.is_compaction_request({"messages": [
        {"role": "system", "content": "You are a coding assistant running inside pi"},
        {"role": "user", "content": [{"type": "text", "text": SUMMARIZER}]}]})
    assert not pi.is_compaction_request({"messages": [{"role": "user", "content": SUMMARIZER}]})
    assert not pi.is_compaction_request({})


def test_upstream_compactions_and_chat_calls(tmp_path):
    (tmp_path / "0001.json").write_text(json.dumps({"messages": [{"role": "system", "content": "work"}]}))
    (tmp_path / "0002.json").write_text(json.dumps({"messages": [{"role": "system", "content": SUMMARIZER}]}))
    calls = [{"n": 1, "path": "/v1/chat/completions"}, {"n": 2, "path": "/v1/chat/completions"},
             {"n": 3, "path": "/v1/messages"}]
    assert pi_task.upstream_compactions(tmp_path, calls) == [2]
    assert [c["n"] for c in pi_task.chat_calls(calls)] == [1, 2]


def test_tool_rows_take_the_opencode_shape():
    assert pi_task.tool_rows([{"name": "bash", "input": {}, "error": False, "output_chars": 9},
                              {"name": "edit", "input": {}, "error": True, "output_chars": 0}]) == [
        {"name": "bash", "status": "completed", "output_chars": 9},
        {"name": "edit", "status": "error", "output_chars": 0}]


# ---------------------------------------------------------------- fake model script

def test_fake_script_reads_then_writes_the_reference_at_the_restart_turn(tmp_path):
    task = task_run.load("dev-t4")
    ref = sorted(task.REFERENCE)
    first = pi_task.fake_replies(task, 0, None)
    assert first[0]["tool_call"][1:] == ("read", pi.js_compact({"path": ref[0]}))
    assert "text" in first[-1]
    writes = pi_task.fake_replies(task, task.RESTART_BEFORE, None)
    assert [json.loads(r["tool_call"][2]) for r in writes[:-1]] == \
        [{"path": rel, "content": task.REFERENCE[rel]} for rel in ref]
    assert all(r["tool_call"][1] == "write" for r in writes[:-1])
    assert pi_task.fake_replies(task, 1, None) == [{"text": "Turn 2 done."}]


def test_fake_script_greps_the_transcripts_on_the_last_turn_of_arm_4(tmp_path):
    task = task_run.load("dev-t1")
    last = len(task.TURNS) - 1
    sdir = tmp_path / "transcripts" / "s"
    got = pi_task.fake_replies(task, last, sdir)
    name, args = got[0]["tool_call"][1], json.loads(got[0]["tool_call"][2])
    assert name == "bash" and sdir.as_posix() in args["command"]
    assert pi_task.fake_replies(task, last, None) == [{"text": f"Turn {last + 1} done."}]


# ---------------------------------------------------------------- records

def test_report_reads_pi_records_under_both_labels(tmp_path):
    run_dir = tmp_path / "run"
    for arm in (4, 1):
        info = pi_task.resolve_arm(arm)
        a = att.new_attempt(run_dir, kind="task", config=info["label"], ids=["dev-t1"], reason=None,
                            ws_root=tmp_path / "ws", extra={"harness": "pi", "protocol": "chat"})
        out = Path(a["records"]) / f"dev-t1-{info['label']}"
        out.mkdir()
        (out / "result.json").write_text(json.dumps(
            {"harness": "pi", "arm": arm, "aborted": None, "check": {"success": arm == 4},
             "compaction_calls": [{"turn": 2, "reason": "threshold"}] if arm == 1 else []}))
        att.finish_attempt(run_dir, a["attempt"], "done")
    results, sup = report.load_task_results(run_dir, arm4=report.A4_LABEL3)
    assert set(results) == {("dev-t1", 4), ("dev-t1", 1)} and sup == []
    assert report.task_success(results[("dev-t1", 4)]) and not report.task_success(results[("dev-t1", 1)])
    assert len(results[("dev-t1", 1)]["compaction_calls"]) == 1
