"""eval/replay.py: re-send captured exchanges to a target and report differences."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx

from .test_capture import _eventually_exchanges
from .test_passthrough import SSE

REPLAY = Path(__file__).resolve().parents[1] / "eval" / "replay.py"


def _capture(s, n_json=1):
    s.upstream.respond_json(b'{"choices":[{"finish_reason":"stop"}]}')
    httpx.post(
        f"{s.proxy_url}/s/sess-1/v1/chat/completions",
        content=b'{"stream":false}',
        headers={"authorization": "Bearer secret"},
    )
    s.upstream.respond_sse(SSE)
    with httpx.stream(
        "POST", f"{s.proxy_url}/s/sess-1/v1/chat/completions", content=b'{"stream":true}'
    ) as r:
        r.read()
    _eventually_exchanges(s.settings.capture_dir, n=2)


def _replay(capture_dir, target, *extra):
    out = subprocess.run(
        [sys.executable, str(REPLAY), str(capture_dir), "--target", target, "--json", *extra],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_replay_against_identical_upstream_reports_byte_identical(capturing_stack, stack):
    _capture(capturing_stack)
    stack.upstream.respond_json(b'{"choices":[{"finish_reason":"stop"}]}')
    stack.upstream.respond_sse(SSE)

    report = _replay(
        capturing_stack.settings.capture_dir,
        stack.upstream_url,
        "--header",
        "authorization=Bearer replayed",
    )

    assert [r["byte_identical"] for r in report["exchanges"]] == [True, True]
    assert report["summary"] == {"exchanges": 2, "status_match": 2, "byte_identical": 2}
    sent = stack.upstream.requests
    assert [r.body for r in sent] == [b'{"stream":false}', b'{"stream":true}']
    assert sent[0].headers["authorization"] == "Bearer replayed"
    assert all(r.path == "/v1/chat/completions" for r in sent)


def test_replay_reports_differences_without_treating_text_drift_as_failure(
    capturing_stack, stack
):
    _capture(capturing_stack)
    stack.upstream.respond_json(b'{"choices":[{"finish_reason":"length"}]}')
    stack.upstream.respond_sse(
        [b'data: {"choices":[{"delta":{"content":"other"}}]}\n\n', b"data: [DONE]\n\n"]
    )

    report = _replay(capturing_stack.settings.capture_dir, stack.upstream_url)

    first, second = report["exchanges"]
    assert first["status_match"] and not first["byte_identical"]
    assert first["finish"] == {"captured": ["stop"], "replayed": ["length"]}
    assert second["sse_events"] == {"captured": 4, "replayed": 2}
    assert second["finish"] == {"captured": ["stop"], "replayed": []}
    assert report["summary"] == {"exchanges": 2, "status_match": 2, "byte_identical": 0}


def test_redacted_credentials_are_not_sent_on_replay(capturing_stack, stack):
    _capture(capturing_stack)
    stack.upstream.respond_json(b"{}")
    stack.upstream.respond_sse(SSE)

    _replay(capturing_stack.settings.capture_dir, stack.upstream_url)

    assert "authorization" not in stack.upstream.requests[0].headers
