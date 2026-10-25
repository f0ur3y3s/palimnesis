"""A context version (a changed leading system message, contracts §4) inside a masked
session: the new system occurrence takes the old one's place, so the view's watermark
and collapse positions keep meaning the same messages (found by cache accounting)."""

from __future__ import annotations

from .test_cacheacct_http import acct_stack, body, events, history, post, rows, turn


def test_masked_view_survives_a_system_change(tmp_path):
    messages = history(30)
    with acct_stack(tmp_path, input_budget=8000) as (fake, url, settings):
        fake.respond_counted()
        assert post(url, body(messages)).status_code == 200
        changed = turn(messages)
        changed[0] = {"role": "system", "content": "You are a coding agent. Today is Tuesday."}
        fake.respond_counted()
        assert post(url, body(changed)).status_code == 200
        later = turn(changed, user="again")
        fake.respond_counted()
        r = post(url, body(later))

    assert r.status_code == 200, r.content[:300]
    # The persisted boundaries still apply: no further move, the prefix still masked.
    assert rows(settings, "SELECT count(*) FROM view_versions") == [(1,)]
    assert "[palimnesis s1" in fake.requests[-1].body.decode()
    assert [c["cause"] for c in events(settings)] == ["first_call", "system_change", "append"]
