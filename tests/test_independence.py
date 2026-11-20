"""Phase 7 S9: the independence check (``eval/independence.py``, plan §1.1, D112.6).

A new held-out file shares no four-word run of wording, no defined identifier and no
planted needle value with an earlier set. Pure functions over literal fixtures; no
held-out file is read here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval")]
import independence  # noqa: E402

sys.path.remove(str(ROOT / "eval"))

CODE = '''"""Parse tide tables."""
import json
from pathlib import Path


def tide_height(row):
    # Heights are stored in centimetres above chart datum.
    raise ValueError("the harbour gauge reported nothing at all")


class TideBook:
    pass
'''

MODULE = f'''TURNS = [
    "We're finishing `tidebook`, which prints the harbour's weekly tide card for the boat club.",
    "Run the whole suite verbosely with `python -m unittest discover -s tests -v` and tell me how many tests ran.",
]
REFERENCE = {{"tidebook/tides.py": {CODE!r}}}
'''


def test_prose_of_module_keeps_wording_drops_code():
    texts = " ".join(independence.prose_of_module(MODULE))
    assert "prints the harbour's weekly tide card" in texts
    assert "stored in centimetres above chart datum" in texts  # comment inside embedded code
    assert "the harbour gauge reported nothing at all" in texts  # message inside embedded code
    assert "Parse tide tables." in texts  # docstring inside embedded code
    assert "from pathlib import" not in texts and "def tide_height" not in texts


def test_grams_break_at_identifiers_paths_and_code_spans():
    g = independence.grams(["read docs/tides.md down to `python -m unittest` the end of the card",
                            "call load_tides then stop here now please"])
    assert ("the", "end", "of", "the") in g
    assert not any("docs" in x or "python" in x or "load" in x for x in g)
    assert ("then", "stop", "here", "now") in g


def test_defined_identifiers_from_embedded_code():
    ids = independence.identifiers_of_module(MODULE)
    assert {"tidebook", "tides", "tide_height", "TideBook"} <= ids
    assert "json" not in ids and "Path" not in ids


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_check_flags_shared_wording_identifier_and_value(tmp_path):
    earlier = _write(tmp_path / "old" / "dev_t1.py",
                     'TURNS = ["The harbour gauge reported nothing at all today."]\n'
                     'REFERENCE = {"tidebook/x.py": "def other():\\n    pass\\n"}\n')
    new = _write(tmp_path / "new" / "ho5_t1.py", MODULE)
    r = independence.check([new], {"dev": [earlier]}, exempt=set())
    assert r[str(new)]["pass"] is False
    assert r[str(new)]["wording"] >= 1 and r[str(new)]["identifiers"] == 1  # tidebook
    clean = _write(tmp_path / "old2" / "dev_t2.py", 'TURNS = ["Something else entirely, written apart."]\n')
    r = independence.check([new], {"dev": [clean]}, exempt=set())
    assert r[str(new)] == {"pass": True, "wording": 0, "identifiers": 0, "values": 0}


def test_exempt_fixed_turn_wording(tmp_path):
    earlier = _write(tmp_path / "old" / "dev_t1.py",
                     'TURNS = ["Run the whole suite verbosely with `python -m unittest discover -s '
                     'tests -v` and tell me how many tests ran."]\n')
    new = _write(tmp_path / "new" / "ho5_t1.py", MODULE)
    shared = independence.check([new], {"dev": [earlier]}, exempt=set())[str(new)]
    assert shared["wording"] > 0
    exempt = independence.grams(["Run the whole suite verbosely with `x` and tell me how many tests ran."])
    assert independence.check([new], {"dev": [earlier]}, exempt=exempt)[str(new)]["pass"] is True


def test_only_fixed_trap_warning_wording_is_exempt():
    scaffold = {("also", "we", "already", "tried"), ("and", "it", "failed", "because")}
    warning = "Also, we already tried clipping the chart datum, and it failed because depths shifted."
    exempt = independence.default_exempt()
    assert scaffold <= exempt
    assert not (independence.grams([warning]) - scaffold) & exempt


def _history(user: str, answer: str) -> dict:
    return {"id": "h", "import": [{"role": "user", "content": user},
                                  {"role": "assistant", "content": "Noted, carrying on now."},
                                  {"role": "tool", "tool_call_id": "c", "content": "tool output here is not wording at all"}],
            "steps": [{"kind": "question", "text": "What value did we settle on for the mooring fee?",
                       "answer": answer, "parts": [], "evidence": [answer]}]}


def test_needle_values_and_wording(tmp_path):
    old = _write(tmp_path / "old" / "dev-h1.json",
                 json.dumps(_history("Keep the anchor chain logs for a fortnight.", "bosun-17")))
    new = _write(tmp_path / "new" / "ho5-h1.json",
                 json.dumps(_history("Set the quay lights to dim after ten.", "BOSUN-17")))
    r = independence.check([new], {"dev": [old]}, exempt=set())[str(new)]
    assert r["values"] == 1 and r["wording"] >= 1 and r["pass"] is False  # the shared question


def test_explain_never_shows_sealed_text(tmp_path):
    secret = _write(tmp_path / "s" / "ho4_t1.py",
                    'TURNS = ["The harbour gauge reported nothing at all today."]\n')
    new = _write(tmp_path / "new" / "ho5_t1.py", MODULE)
    lines = independence.explain([new], {"ho4": [secret]}, exempt=set(), sealed={"ho4"})
    text = "\n".join(lines)
    assert "harbour" not in text and "gauge" not in text
    assert "sealed" in text
    lines = independence.explain([new], {"dev": [secret]}, exempt=set(), sealed=set())
    assert "harbour gauge reported nothing" in "\n".join(lines)


def test_cli_prints_pass_or_fail_per_file(tmp_path):
    new = _write(tmp_path / "ho5_t1.py", MODULE)
    out = subprocess.run([sys.executable, str(ROOT / "eval" / "independence.py"), str(new),
                          "--against", "dev"], capture_output=True, text=True, cwd=ROOT)
    assert out.returncode in (0, 1)
    assert out.stdout.strip().splitlines()[-1].startswith(f"{new}: ")
    assert out.stdout.strip().split(": ", 1)[1].split()[0] in ("pass", "fail")


def test_default_sets_cover_earlier_task_modules_and_needles():
    sets = independence.default_sets()
    assert {"dev", "ho", "ho2", "ho3", "ho4"} <= set(sets)
    names = {p.name for paths in sets.values() for p in paths}
    assert "dev_t6.py" in names and "dev-h1.json" in names
    assert not any(n.startswith(("ho5", "ho6")) for n in names)


def test_runs_and_identifiers_in_two_earlier_sets_are_generic(tmp_path):
    """Wording or a name that two earlier sets already share is the skeleton or common
    English, not a copy; one set's wording still fails."""
    line = 'TURNS = ["The harbour gauge reported nothing at all today."]\n'
    ref = 'REFERENCE = {"tidebook/x.py": "def other():\\n    pass\\n"}\n'
    a = _write(tmp_path / "a" / "dev_t1.py", line + ref)
    b = _write(tmp_path / "b" / "ho_t1.py", line + ref)
    new = _write(tmp_path / "new" / "ho5_t1.py", MODULE)
    assert independence.check([new], {"dev": [a]}, exempt=set())[str(new)]["pass"] is False
    assert independence.check([new], {"dev": [a], "ho": [b]}, exempt=set())[str(new)]["pass"] is True


def test_harness_paths_and_short_names_are_not_identifiers():
    src = ('HIDDEN = {"_check/test_hidden.py": "class HiddenTests:\\n    pass\\n",\n'
           '          "pkg/D.py": "class D:\\n    pass\\n"}\n')
    assert independence.identifiers_of_module(src) == {"pkg", "HiddenTests"}
