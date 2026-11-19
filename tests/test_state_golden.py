"""Phase 4A S0: the shipped a4-d77 configuration's upstream bytes do not change.

Phase 4A adds provenance, retrievability and measurement to the working notes (D105), not
model-facing behaviour. Two scripted sessions run ``palimnesis serve``'s defaults (a4-d77,
D78) with a small input budget, each call through a fresh proxy process on the same
archive (restarts):

- ``plain``: three notes refreshes and a refresh that cannot fit ``B_in``;
- ``rich`` (D106, after the protocol review found 4A paths the plain one never takes):
  six calls with shorter pasted logs. The first refresh writes its notes only in the
  reasoning (n2, D74), with an emoji split across two deltas, citing turn files; the
  second is cut to fit its slot and cites an archive alias by block; instructions ask
  about collapsed content, so excerpts render.

Every upstream body, refresh calls included, must equal the literal fixture recorded at
``phase-4b`` (``a6f65d2``) byte for byte after normalisation. Transcript files are off: their
root is a temporary folder whose path length would move token counts. Archive aliases,
hashed from random record ids, differ between runs and are named by first appearance with
their length kept (``§A3_6``), so identity, placement and token length are compared.

Re-record only for a decision that changes what the model sees, and record on the code of
the version that decision starts from:
``PALIMNESIS_RECORD_GOLDEN=1 uv run pytest tests/test_state_golden.py``.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import uuid
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pytest

from palimnesis.api import create_app
from palimnesis.archive import ledger
from palimnesis.cli import serve_settings

from .fake_upstream import FakeUpstream
from .servers import serve
from .test_notes_http import _body, _messages
from .test_view_http import post

FIXTURES = Path(__file__).parent / "fixtures" / "phase4a"
BUDGET = 24_320
ALIAS = re.compile(r"§([0-9A-HJKMNP-TV-Z]{6,})")
SPAN_ALIAS = re.compile(r"\[palimnesis s1 span §([0-9A-HJKMNP-TV-Z]{6,})")
NOTES = ("Objective\nFinish every part.\nCurrent step and next move\nPart {n}.\n"
         "Requirements and constraints\n- end == start is an error.\n- The code is ZX-4471.\n"
         "Decisions\n- Keep the parser.\nDone so far\n- Parts 0 to {n}.\nDead ends\n"
         "- Recursion overflowed on deep input.")
SECTIONS = ["Objective", "Current step and next move", "Requirements and constraints",
            "Decisions", "Done so far", "Dead ends"]


def _turns(k: int, *, ask: bool = False, words: int = 1500) -> list[dict]:
    """The client's resend after ``k`` earlier calls: each earlier answer exactly as
    generated, then a long pasted instruction, so the view keeps moving. With ``ask`` the
    instruction also names words from collapsed tool output, so recall has a query."""
    out = []
    for t in range(k):
        out.append({"role": "assistant", "content": f"answer {t}"})
        log = " ".join(f"log{t}_{n}" for n in range(words))
        about = f" What did w0_{t + 1}_7 and w1_{t + 2}_9 say?" if ask else ""
        out.append({"role": "user", "content": f"Instruction {t + 3}: what was the code?{about} "
                                               f"Then fix part {t + 3}. Log: {log}"})
    return out


def _probe(text: str):
    probe = FakeUpstream()
    probe.respond_counted(text)
    return probe._script[0]


def _answer(fake: FakeUpstream, answer: str) -> None:
    """Queue one reply: the notes if the request is a notes refresh, else ``answer``."""
    notes, plain = _probe(NOTES.format(n=answer)), _probe(answer)

    def build(raw: bytes):
        last = json.loads(raw)["messages"][-1]
        refresh = "[palimnesis notes request]" in str(last.get("content"))
        return (notes if refresh else plain).build(raw)

    fake._script.append(replace(plain, build=build))


def _sse(raw: bytes, content: str, reasoning: tuple[str, ...] = ()) -> list[bytes]:
    """A counted reply streaming ``reasoning`` pieces first, then ``content``."""
    built = _probe(content).build(raw)
    pieces = [b"data: " + json.dumps({"choices": [{"index": 0, "delta": {"reasoning_content": r}}]})
              .encode() + b"\n\n" for r in reasoning]
    return pieces + built if content else pieces + built[1:]


def _long_notes(cite: str) -> str:
    out = []
    for s in SECTIONS:
        out.append(s)
        out += [f"- {s.split()[0].lower()} fact {k}: " + " ".join(["word"] * 12)
                for k in range(60)]
    out.insert(2, f"- spec in {cite} and turn-0002.md")
    return "\n".join(out)


def _rich_answer(fake: FakeUpstream, answer: str, refreshes: list) -> None:
    """Queue one reply; the n-th refresh of the session gets the n-th rich case."""
    plain = _probe(answer)

    def build(raw: bytes):
        last = json.loads(raw)["messages"][-1]
        if "[palimnesis notes request]" not in str(last.get("content")):
            return plain.build(raw)
        n = len(refreshes)
        refreshes.append(n)
        if n == 0:  # notes written only in the reasoning (n2, D74), with an emoji split
            # across two deltas, citing turn files
            return _sse(raw, "", ("thinking about \ud83d", "\ude80 launch.\n" + NOTES.format(n=0)
                                  + "\n- see turn-0000.md and turn-0001.md"))
        if n == 1:  # too long for the slot (cut), citing a span alias from the request
            found = SPAN_ALIAS.search(raw.decode("utf-8"))
            return _sse(raw, _long_notes(f"§{found.group(1)}.0" if found else "nothing"))
        return _sse(raw, NOTES.format(n=n))

    fake._script.append(replace(plain, build=build))


def run(tmp_path: Path, *, rich: bool = False, calls: int = 4, words: int = 1500) -> list[str]:
    """Four calls, each through a fresh proxy process on the same archive: the normalised
    text of every upstream body, in order."""
    fake = FakeUpstream()
    db = tmp_path / "archive.db"
    refreshes: list = []
    # Record ids are random, and aliases hash from them: their characters tokenize to
    # different counts, which moves excerpt cuts. Ids come from a counter here instead.
    counter = itertools.count(1)
    with mock.patch.object(ledger.uuid, "uuid4", lambda: uuid.UUID(int=next(counter))),             serve(fake.app()) as upstream:
        # No transcript files: their root, a temporary folder, would put a path of varying
        # length into the system message and so move token counts and excerpt cuts.
        argv = ["--upstream", upstream, "--db", str(db), "--input-budget", str(BUDGET),
                "--no-transcripts"]
        for k in range(calls):
            with serve(create_app(serve_settings(argv)), palimnesis=True) as url:
                for _ in range(2):
                    (_rich_answer(fake, f"answer {k}", refreshes) if rich
                     else _answer(fake, f"answer {k}"))
                messages = _messages(_turns(k, ask=rich, words=words))
                assert post(url, _body(messages)).status_code == 200
                fake._script.clear()
    aliases: dict[str, str] = {}

    def name(m: re.Match) -> str:
        alias = m.group(1)
        return f"§A{aliases.setdefault(alias, str(len(aliases) + 1))}_{len(alias)}"

    return [ALIAS.sub(name, r.body.decode("utf-8")) for r in fake.requests]


def scenario(tmp_path: Path) -> list[dict]:
    """The rich session's upstream bodies, parsed; other Phase 4A tests read its archive
    (two committed states, the second cut, cited aliases and turn files, excerpts)."""
    return [json.loads(text) for text in run(tmp_path, rich=True, calls=6, words=600)]


@pytest.mark.parametrize("name", ["plain", "rich"])
def test_a4_d77_upstream_bodies_unchanged_by_phase_4a(tmp_path, name):
    bodies = run(tmp_path, rich=True, calls=6, words=600) if name == "rich" else run(tmp_path)
    fixture = FIXTURES / f"a4_d77_{name}.json"
    if os.environ.get("PALIMNESIS_RECORD_GOLDEN") == "1":
        fixture.parent.mkdir(parents=True, exist_ok=True)
        fixture.write_text(json.dumps(bodies, indent=1, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    recorded = json.loads(fixture.read_text(encoding="utf-8"))
    assert len(bodies) == len(recorded)
    for k, (got, want) in enumerate(zip(bodies, recorded)):
        assert got == want, f"upstream body {k} changed"
