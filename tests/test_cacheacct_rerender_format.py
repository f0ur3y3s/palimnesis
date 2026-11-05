"""A previous call that cannot be re-rendered under a changed view policy (cache audit of
D70): the recorded format differs, so the pair is ``view_format_change`` (contracts §10),
never ``unexplained``."""

from __future__ import annotations

from palimnesis.view.cacheacct import Call, explain


def _call(call_id, policy, layout=None):
    return Call(call_id=call_id, request_id=f"req_{call_id}", branch_id="b", view_mode="on",
                formats={"policy_version": policy, "stub_format": "s1"}, layout=layout)


def test_a_failed_rerender_under_another_policy_is_a_format_change():
    prev, cur = _call("a", "v2"), _call("b", "v2+turn", layout=object())

    assert explain(prev, cur, model=None)["cause"] == "view_format_change"


def test_a_failed_rerender_under_the_same_policy_stays_unexplained():
    prev, cur = _call("a", "v2+turn"), _call("b", "v2+turn", layout=object())

    assert explain(prev, cur, model=None)["cause"] == "unexplained"
