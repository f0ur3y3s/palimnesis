"""Phase 8 S4: the needle instrument (plan §1.2).

- ``eval/needle_format.py``: every question ends with exactly one fixed sentence chosen by
  its declared answer kind, and its gold answer has that kind's shape (P).
- ``eval/needle_shape_probe.py``: each question goes direct to upstream with only its
  evidence in view (H), is scored with the frozen ``needle.normalize_loose`` and passes
  on 3 of 3 samples; output is counts only (P)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

from .fake_upstream import FakeUpstream
from .servers import serve

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
import needle  # noqa: E402
import needle_format as nf  # noqa: E402
import needle_shape_probe as probe  # noqa: E402

sys.path.remove(str(ROOT / "eval"))


def _q(text, answer, *, fmt=None, parts=None, evidence=None, category="identifier", qid="h1q1"):
    step = {"kind": "question", "id": qid, "category": category, "text": text,
            "answer": answer, "parts": parts or [answer], "evidence": evidence or parts or [answer]}
    if fmt is not None:
        step["answer_format"] = fmt
    return step


# --- format rule ----------------------------------------------------------------------

def test_each_kind_has_one_fixed_sentence():
    assert nf.sentence({"kind": "identifier"}) == \
        "Reply with the identifier alone, exactly as recorded, and nothing else."
    assert nf.sentence({"kind": "number"}) == "Reply with the number alone, in digits, and nothing else."
    assert nf.sentence({"kind": "path"}) == \
        "Reply with the path alone, exactly as recorded, and nothing else."
    assert nf.sentence({"kind": "value"}) == \
        "Reply with the value alone, exactly as recorded, and nothing else."
    assert nf.sentence({"kind": "list", "n": 3, "sep": "|"}) == \
        "Reply with the 3 values in that order, joined by a vertical bar (|) with no spaces, and nothing else."
    with pytest.raises(ValueError):
        nf.sentence({"kind": "list", "n": 3, "sep": "+"})
    with pytest.raises(ValueError):
        nf.sentence({"kind": "code"})


def test_a_question_built_by_apply_passes_the_lint():
    fmt = {"kind": "identifier"}
    step = _q(nf.apply("Which audit docket was approved for maple?", fmt), "FURROW@498364@SEAL", fmt=fmt)
    assert step["text"].endswith(" Reply with the identifier alone, exactly as recorded, and nothing else.")
    assert nf.lint_step(step) == []
    lst = {"kind": "list", "n": 2, "sep": ";"}
    step = _q(nf.apply("Compose the route from the bulletin.", lst), "A1;B2", fmt=lst, parts=["A1", "B2"])
    assert nf.lint_step(step) == []


@pytest.mark.parametrize("step, problem", [
    (_q("Which docket? Code only.", "X1"), "no answer_format"),
    (_q("Which docket? Code only.", "X1", fmt={"kind": "identifier"}), "does not end with"),
    (_q("Which docket? Reply with the identifier alone, exactly as recorded, and nothing else. "
        "Reply with the identifier alone, exactly as recorded, and nothing else.", "X1",
        fmt={"kind": "identifier"}), "more than one"),
    (_q(nf.apply("How many crates?", {"kind": "number"}), "12a", fmt={"kind": "number"}), "not digits"),
    (_q(nf.apply("Which docket?", {"kind": "identifier"}), "X 1", fmt={"kind": "identifier"}), "whitespace"),
    (_q(nf.apply("Route?", {"kind": "list", "n": 2, "sep": "|"}), "A|B|C",
        fmt={"kind": "list", "n": 2, "sep": "|"}, parts=["A", "B", "C"]), "3 parts"),
    (_q(nf.apply("Route?", {"kind": "list", "n": 2, "sep": "|"}), "B|A",
        fmt={"kind": "list", "n": 2, "sep": "|"}, parts=["A", "B"]), "parts in order"),
    (_q(nf.apply("Which docket?", {"kind": "number"}) + " Code only.", "12",
        fmt={"kind": "number"}), "does not end with"),
])
def test_the_lint_names_each_problem(step, problem):
    assert any(problem in p for p in nf.lint_step(step)), nf.lint_step(step)


def test_lint_history_reports_question_steps_only():
    fmt = {"kind": "identifier"}
    h = {"id": "h1", "steps": [{"kind": "paste", "id": "p1", "text": "File it."},
                               _q(nf.apply("Which?", fmt), "X1", fmt=fmt, qid="q1"),
                               _q("Which? Code only.", "X2", qid="q2")]}
    got = nf.lint_history(h)
    assert set(got) == {"q2"} and got["q2"]


def test_validation_helpers_infer_a_kind_and_strip_a_trailing_instruction():
    assert nf.infer_format(_q("?", "66502818")) == {"kind": "number"}
    assert nf.infer_format(_q("?", "FURROW@498364@SEAL")) == {"kind": "identifier"}
    assert nf.infer_format(_q("?", "A1|B2|C3", parts=["A1", "B2", "C3"])) == \
        {"kind": "list", "n": 3, "sep": "|"}
    assert nf.infer_format(_q("?", "a b", parts=["a b"])) == {"kind": "value"}
    assert nf.stem_of("Which audit docket was approved for maple? Return its code.") == \
        "Which audit docket was approved for maple?"
    assert nf.stem_of("And its backing? Return the token.") == "And its backing?"
    assert nf.stem_of("Give the revised proof latch, bare identifier.") == \
        "Give the revised proof latch, bare identifier."  # one sentence: kept whole
    assert nf.stem_of("Transcribe the triplet in tray, marker, wallet order. "
                      "Separate inscriptions with a single vertical bar.") == \
        "Transcribe the triplet in tray, marker, wallet order."


# --- shape probe ----------------------------------------------------------------------

HISTORY = {
    "id": "hx1", "generator": "eval/needle_gen_x.py",
    "import": [
        {"role": "user", "content": "Start the bench log."},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{\"path\": \"a.txt\"}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "line one\nthe approved docket is FURROW@498364@SEAL\nline three"},
        {"role": "assistant", "content": "Logged."},
    ],
    "steps": [
        {"kind": "paste", "id": "p1", "text": "Unrelated paste about weather: QUIET@1@NOISE."},
        _q("Which docket was approved? Code only.", "FURROW@498364@SEAL", qid="hx1q1"),
        _q("And its spacing? Code only.", "STRIP<70605>TICKS", category="vague", qid="hx1q2"),
    ],
    "workspace": {"tests/t.py": "spacing = 'STRIP<70605>TICKS'\n"},
    "shell": [],
}


def test_passages_hold_the_evidence_and_nothing_unrelated():
    got = probe.passages(HISTORY, HISTORY["steps"][1])
    assert any("FURROW@498364@SEAL" in p for p in got)
    assert not any("QUIET@1@NOISE" in p for p in got)
    # Workspace files count as evidence sources (mid_task answers live there).
    assert any("STRIP<70605>TICKS" in p for p in probe.passages(HISTORY, HISTORY["steps"][2]))


def test_a_long_passage_is_cut_to_a_window_around_the_evidence():
    big = {**HISTORY, "import": [{"role": "tool", "tool_call_id": "c", "content":
                                  "x" * 9000 + " KEY@1@KEY " + "y" * 9000}], "steps": [
        _q("Which key? Code only.", "KEY@1@KEY", qid="b1")]}
    (p,) = probe.passages(big, big["steps"][0], window=500)
    assert "KEY@1@KEY" in p and len(p) <= 500 * 2 + len("KEY@1@KEY") + 40


def test_a_vague_question_carries_the_previous_question_and_its_answer():
    msgs = probe.probe_messages(HISTORY, HISTORY["steps"][2])
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[0]["content"].endswith("Which docket was approved? Code only.")
    assert msgs[1]["content"] == "FURROW@498364@SEAL"
    assert msgs[2]["content"].endswith("And its spacing? Code only.")
    assert "STRIP<70605>TICKS" in msgs[2]["content"]


def test_the_probe_sends_evidence_and_question_direct_to_upstream_and_scores_loose():
    fake = FakeUpstream()
    for text in ("`FURROW@498364@SEAL`.", "FURROW@498364@SEAL", "The code is FURROW@498364@SEAL"):
        fake.respond_turn(text)
    with serve(fake.app()) as url:
        call = probe.make_call(url, model="m")
        passes = probe.probe_step(HISTORY, HISTORY["steps"][1], call, samples=3)
    assert passes == 2  # the third reply wraps the code in a sentence: loose fails
    assert [r.path for r in fake.requests] == ["/v1/chat/completions"] * 3
    body = json.loads(fake.requests[0].body)
    assert "tools" not in body and body["stream"] is True and body["model"] == "m"
    (msg,) = body["messages"]
    assert msg["role"] == "user" and "FURROW@498364@SEAL" in msg["content"]
    assert msg["content"].endswith("Which docket was approved? Code only.")


def test_scoring_is_the_frozen_loose_scorer():
    step = HISTORY["steps"][1]
    for reply in ("FURROW@498364@SEAL", "`FURROW@498364@SEAL`", " furrow@498364@seal. "):
        assert probe.passes(reply, step) is needle.score(reply, step)["exact_loose"] is True
    assert probe.passes("FURROW@498364@SEAL is the code", step) is False


def test_the_format_variant_replaces_the_trailing_instruction():
    step = HISTORY["steps"][1]
    assert probe.question_text(step, "original") == "Which docket was approved? Code only."
    assert probe.question_text(step, "format") == \
        "Which docket was approved? Reply with the identifier alone, exactly as recorded, and nothing else."
    declared = {**step, "answer_format": {"kind": "identifier"},
                "text": nf.apply("Which docket was approved?", {"kind": "identifier"})}
    assert probe.question_text(declared, "format") == declared["text"]


def test_the_cli_prints_counts_only(tmp_path, capsys):
    f = tmp_path / "hx1.json"
    f.write_text(json.dumps(HISTORY), encoding="utf-8")
    fake = FakeUpstream()
    for _ in range(4):
        fake.respond_turn("SECRET-MODEL-TEXT FURROW@498364@SEAL")
    out_json = tmp_path / "probe.json"
    with serve(fake.app()) as url:
        rc = probe.main([str(f), "--upstream", url, "--model", "m", "--samples", "2",
                         "--out", str(out_json)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SECRET-MODEL-TEXT" not in out and "SECRET-MODEL-TEXT" not in out_json.read_text(encoding="utf-8")
    assert "FURROW@498364@SEAL" not in out  # no gold answers either
    assert "hx1: 0/2 questions pass" in out
    rec = json.loads(out_json.read_text(encoding="utf-8"))
    assert rec["questions"]["hx1q1"] == {"passes": 0, "samples": 2, "category": "identifier",
                                         "generator": "x"}


def test_two_runs_require_both_to_pass(tmp_path):
    fake = FakeUpstream()
    for text in ("FURROW@498364@SEAL", "FURROW@498364@SEAL", "FURROW@498364@SEAL", "no"):
        fake.respond_turn(text)
    with serve(fake.app()) as url:
        call = probe.make_call(url, model="m")
        ok = probe.accepted(HISTORY, HISTORY["steps"][1], call, samples=2, runs=2)
    assert ok is False and len(fake.requests) == 4


def test_a_failed_call_is_an_error_not_a_miss():
    fake = FakeUpstream()
    fake.respond_json(b'{"error": "boom"}', status=500)
    with serve(fake.app()) as url:
        call = probe.make_call(url, model="m")
        with pytest.raises(probe.UpstreamError):
            probe.probe_step(HISTORY, HISTORY["steps"][1], call, samples=1)


def test_the_model_name_is_read_from_upstream_when_not_given():
    fake = FakeUpstream()
    fake.respond_json(json.dumps({"object": "list", "data": [{"id": "qwen-x", "object": "model"}]}).encode())
    fake.respond_turn("FURROW@498364@SEAL")
    with serve(fake.app()) as url:
        call = probe.make_call(url)
        assert probe.probe_step(HISTORY, HISTORY["steps"][1], call, samples=1) == 1
    assert fake.requests[0].path == "/v1/models"
    assert json.loads(fake.requests[1].body)["model"] == "qwen-x"
    assert httpx  # imported for the client the probe uses


# --- S4 validation run on retired heldout5 (R70) ----------------------------------------

sys.path.insert(0, str(ROOT / "eval"))
import run_ready  # noqa: E402
import s4_validation as s4v  # noqa: E402

sys.path.remove(str(ROOT / "eval"))


def test_the_validation_spec_runs_each_generator_original_first():
    spec = s4v.make_spec(root="captures/s4", python="py")
    assert [s["name"] for s in spec["steps"]] == [
        f"{v} {g}" for v in ("original", "format") for g in ("a", "b", "c", "d")]
    argv = spec["steps"][0]["argv"]
    assert argv[:2] == ["py", "eval/needle_shape_probe.py"]
    files = [a for a in argv if a.startswith("eval/needles/heldout5/")]
    assert len(files) == 5 and all(not a.startswith(("eval/needles/heldout4", "eval/needles/heldout6"))
                                   for a in argv)
    assert argv[argv.index("--out") + 1] == "captures/s4/original-a.json"
    assert argv[argv.index("--samples") + 1] == "3" and argv[argv.index("--variant") + 1] == "original"
    assert sum(len([a for a in s["argv"] if "/needles/" in a]) for s in spec["steps"]) == 2 * 18
    assert spec["config"] == "s4-probe-s3"
    reh = s4v.make_spec(root="r", python="py", samples=1, per_generator=1)
    assert reh["config"] == "s4-probe-s1-h1" and len(reh["steps"]) == 8
    assert all(len([a for a in s["argv"] if "/needles/" in a]) == 1 for s in reh["steps"])


def _gate_reads(text, tmp_path):
    f = tmp_path / "report.txt"
    f.write_text(text, encoding="utf-8")
    return run_ready._evidence({"report_output": str(f)})[2]


def test_the_report_counts_full_passes_and_names_missing_questions(tmp_path):
    spec = s4v.make_spec(root=str(tmp_path), python="py", per_generator=1, variants=("original",),
                         generators=("a",))
    files = [a for a in spec["steps"][0]["argv"] if "/needles/" in a]
    h = json.loads((ROOT / files[0]).read_text(encoding="utf-8"))
    qs = [s for s in h["steps"] if s.get("kind") == "question"]
    rep = s4v.report(tmp_path, spec)
    assert rep["rows"][("original", "a")] == {"pass": 0, "total": len(qs), "by_category": {}}
    assert len(rep["missing"]) == len(qs)
    assert not _gate_reads("\n".join(s4v.format_report(rep)), tmp_path)["ok"]
    rec = {"questions": {s["id"]: {"passes": 3 if i else 2, "samples": 3, "category": s["category"],
                                   "generator": "a"} for i, s in enumerate(qs)}}
    (tmp_path / "original-a.json").write_text(json.dumps(rec), encoding="utf-8")
    rep = s4v.report(tmp_path, spec)
    assert rep["rows"][("original", "a")]["pass"] == len(qs) - 1 and rep["missing"] == []
    text = "\n".join(s4v.format_report(rep))
    assert "missing attempts: none" in text and _gate_reads(text, tmp_path)["ok"]
