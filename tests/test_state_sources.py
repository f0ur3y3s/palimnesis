"""Phase 4A S3: the archive addresses a state cites are recorded and resolved (D105.4).

``view.state.cited_addresses`` finds ``§ALIAS`` (optionally ``.N``) and ``turn-NNNN``
names in a committed state's text. Each is recorded in ``notes_sources`` as ``valid``,
``unknown`` or ``ambiguous`` against the session's archive; the state's text is never
rewritten, since the archive keeps what the model wrote."""

from __future__ import annotations

import json
import re
from dataclasses import replace

from palimnesis.view.state import cited_addresses

from .fake_upstream import FakeUpstream
from .test_state_golden import BUDGET, _turns
from .test_notes_http import _body, _messages
from .test_view_http import post, rows, view_stack

SPAN_ALIAS = re.compile(r"\[palimnesis s1 span §([0-9A-Z]{6,})")


def test_cited_addresses_finds_aliases_blocks_and_turn_files():
    text = ("Objective\nSee §5DM5KG and §b2fmmc.3 for the spec; turn-0004.md has the "
            "log, and turn-0012 the fix.\nDead ends\n- §ZZZZZZ.x is not a block")
    assert cited_addresses(text) == [
        ("alias", "5DM5KG"), ("alias", "b2fmmc.3"), ("turn", "turn-0004"),
        ("turn", "turn-0012"), ("alias", "ZZZZZZ")]


def test_bare_base32_words_are_not_addresses():
    assert cited_addresses("PARSER RETURNS 5DM5KG and turn 4 and returned-0004") == []


def _citing_notes(fake: FakeUpstream, answer: str) -> None:
    """One reply: notes citing the first span alias the refresh request shows (if any),
    an unknown alias and two turn files; ``answer`` for a client call."""
    probe = FakeUpstream()
    probe.respond_counted("notes")
    probe.respond_counted(answer)
    notes, plain = probe._script

    def build(raw: bytes):
        body = json.loads(raw)
        last = str(body["messages"][-1].get("content"))
        if "[palimnesis notes request]" not in last:
            return plain.build(raw)
        found = SPAN_ALIAS.search(raw.decode("utf-8"))
        cite = (f"§{found.group(1)} and §{found.group(1)}.0 and §{found.group(1)}.9"
                if found else "nothing yet")
        text = (f"Objective\nFinish.\nRequirements and constraints\n- spec in {cite}\n"
                "Done so far\n- see §ZZZZZZ, turn-0001.md and turn-0999.md\n"
                "Dead ends\n- none")
        probe2 = FakeUpstream()
        probe2.respond_counted(text)
        return probe2._script[0].build(raw)

    fake._script.append(replace(plain, build=build))


def test_state_sources_record_valid_unknown_and_never_rewrite(tmp_path):
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048, notes_format="n2") as (
            fake, url, s):
        for k in range(3):
            _citing_notes(fake, f"answer {k}")
            _citing_notes(fake, f"answer {k}")
            assert post(url, _body(_messages(_turns(k)))).status_code == 200
            fake._script.clear()

    versions = rows(s, "SELECT notes_id, n, text FROM notes_versions"
                       " WHERE status = 'committed' ORDER BY n")
    cited = [v for v in versions if ".9" in v[2]]
    assert cited, "a later refresh cites a span alias"
    notes_id, _, text = cited[0]
    sources = rows(s, "SELECT idx, token, kind, status, target_id FROM notes_sources"
                      f" WHERE notes_id = '{notes_id}' ORDER BY idx")
    by_token = {t: (kind, status, target) for _, t, kind, status, target in sources}
    real = re.search(r"§([0-9A-Z]{6,}) and", text).group(1)
    assert by_token[real][:2] == ("alias", "valid") and by_token[real][2]
    assert by_token[f"{real}.0"][:2] == ("alias", "valid")
    assert by_token[f"{real}.9"][:2] == ("alias", "unknown")  # no block 9 (D106)
    assert by_token["ZZZZZZ"][:2] == ("alias", "unknown") and by_token["ZZZZZZ"][2] is None
    assert by_token["turn-0001"][:2] == ("turn", "valid")
    assert by_token["turn-0999"][:2] == ("turn", "unknown")
    assert "§ZZZZZZ" in text  # recorded, never corrected
    events = [json.loads(p) for (p,) in rows(
        s, "SELECT payload FROM events WHERE kind = 'notes_sources'")]
    assert any(e["unknown"] == 3 and e["valid"] == 3 for e in events)


def test_failed_versions_record_no_sources(tmp_path):
    with view_stack(tmp_path, input_budget=BUDGET, notes_tokens=2048, notes_format="n2") as (
            fake, url, s):
        fake.respond_counted(tool_call=("call_x", "read", "{}"))
        fake.respond_counted("answer")
        assert post(url, _body(_messages())).status_code == 200

    assert rows(s, "SELECT count(*) FROM notes_sources") == [(0,)]
