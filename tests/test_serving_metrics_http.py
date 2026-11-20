"""Serving metrics on the proxy's ``upstream_call`` events (Phase 7 S2, F2; contracts §10).

R61 found the notes refresh calls (``#notes``) recorded ``prompt_ms`` 0 in
``--explain --by-cause``. The refresh is streamed, and the eval tap parses its stream like
any other; the gap was the proxy's event, which kept only the stream's ``usage`` and
dropped Strata's ``timings``. Every ``upstream_call`` event now carries ``prompt_ms`` and
``completion_tokens`` from the upstream's final chunk, numbers only, never text."""

from __future__ import annotations

import json

from .fake_upstream import FakeUpstream
from .test_cacheacct_http import acct_stack, events
from .test_notes_http import BUDGET, NOTES, _body, _messages
from .test_view_http import post

VISIBLE = "visible answer"


def test_notes_refresh_upstream_call_records_prompt_ms(tmp_path):
    fake = FakeUpstream()
    with acct_stack(tmp_path, fake, input_budget=BUDGET, notes_tokens=2048) as (_, url, s):
        fake.respond_counted(NOTES, prompt_ms=333.5, completion_tokens=17)
        fake.respond_counted(VISIBLE, prompt_ms=12.25, completion_tokens=3)
        assert post(url, _body(_messages())).status_code == 200

    calls = events(s)
    [refresh] = [c for c in calls if c["call_id"].endswith("#notes")]
    [main] = [c for c in calls if not c["call_id"].endswith("#notes")]
    assert refresh["prompt_ms"] == 333.5 and refresh["completion_tokens"] == 17
    assert main["prompt_ms"] == 12.25 and main["completion_tokens"] == 3
    # Numbers only: neither reply's text reaches an event (contracts §10, §12).
    for event in calls:
        raw = json.dumps(event)
        assert NOTES.splitlines()[1] not in raw and VISIBLE not in raw
        assert isinstance(event["completion_tokens"], int)
        assert isinstance(event["prompt_ms"], float)
