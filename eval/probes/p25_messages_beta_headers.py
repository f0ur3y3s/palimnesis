"""Probe 25 (Phase 4B, S0 M5): ``?beta=true`` and Anthropic headers on Strata 0.1.54.

Does Strata accept, on ``/v1/messages`` and ``/v1/messages/count_tokens``:
  - the query string ``?beta=true`` (Claude Code's form);
  - ``anthropic-version``, ``anthropic-beta`` (known and unknown beta names), ``x-api-key``
    and ``Authorization: Bearer`` headers (this server runs with no API key);
  - the ``/v1/v1/messages`` alias (an Anthropic base URL that already ends in /v1)?

Each variant is compared with the plain request: same status, same prompt count. Response
headers are recorded (any Anthropic-specific or request-id header?).

Sequential, idle-gated (D39), synthetic, tiny. Writes fixtures/strata_messages/p25_messages_beta_headers.json
and the raw stream of the beta+headers streaming variant (p25_beta_headers_stream.sse).

    uv run python eval/probes/p25_messages_beta_headers.py
"""

from __future__ import annotations

import json
import time

import httpx

from strata_common import BASE, FIXTURES, MODEL, check_build, wait_idle

OUT = FIXTURES / "strata_messages"
OUT.mkdir(parents=True, exist_ok=True)
BUILD = "Strata 0.1.54"

BODY = {"model": MODEL, "max_tokens": 8, "thinking": {"type": "disabled"}, "system": "You are terse.",
        "messages": [{"role": "user", "content": "Say hi."}]}
HEADERS = {
    "anthropic-version": "2023-06-01",
    "anthropic-beta": "claude-code-20250219,interleaved-thinking-2025-05-14,fine-grained-tool-streaming-2025-05-14",
    "x-api-key": "sk-probe-dummy",
    "authorization": "Bearer probe-dummy",
}
UNKNOWN_BETA = {"anthropic-version": "2023-06-01", "anthropic-beta": "palimnesis-probe-nonexistent-2099-01-01"}

VARIANTS = [
    ("plain", "/v1/messages", {}, False),
    ("beta_query", "/v1/messages?beta=true", {}, False),
    ("headers", "/v1/messages", HEADERS, False),
    ("beta_query_headers", "/v1/messages?beta=true", HEADERS, False),
    ("unknown_beta", "/v1/messages?beta=true", UNKNOWN_BETA, False),
    ("beta_query_headers_stream", "/v1/messages?beta=true", HEADERS, True),
    ("v1_v1_alias", "/v1/v1/messages?beta=true", HEADERS, False),
    ("count_plain", "/v1/messages/count_tokens", {}, False),
    ("count_beta_query_headers", "/v1/messages/count_tokens?beta=true", HEADERS, False),
    ("count_v1_v1_alias", "/v1/v1/messages/count_tokens?beta=true", HEADERS, False),
]


def main() -> None:
    props = check_build(BUILD)
    results: dict = {"base": BASE, "build": props.get("build_info"), "sent_headers": HEADERS,
                     "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "variants": []}
    with httpx.Client(base_url=BASE, timeout=httpx.Timeout(300, connect=10)) as c:
        for name, path, headers, stream in VARIANTS:
            wait_idle(quiet=1.0)
            body = {**BODY, "stream": True} if stream else BODY
            r = c.post(path, json=body, headers=headers)
            row: dict = {"name": name, "path": path, "headers_sent": sorted(headers), "status": r.status_code,
                         "response_headers": {k: v for k, v in r.headers.items() if k.lower() != "date"}}
            if stream:
                (OUT / "p25_beta_headers_stream.sse").write_bytes(r.content)
                types = [json.loads(ln[5:]).get("type") for ln in r.text.split("\n") if ln.startswith("data:")]
                row["event_types"] = types
            else:
                try:
                    j = r.json()
                except ValueError:
                    j = {"raw": r.text[:500]}
                if "usage" in j:
                    u = j["usage"]
                    row["prompt"] = sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                                                "cache_read_input_tokens"))
                    row["stop_reason"] = j.get("stop_reason")
                elif "input_tokens" in j:
                    row["prompt"] = j["input_tokens"]
                else:
                    row["body"] = j
            results["variants"].append(row)
            print(f"{name:28s} {r.status_code} prompt={row.get('prompt')} {row.get('event_types', '')}"
                  f"{row.get('body', '')}")
    results["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (OUT / "p25_messages_beta_headers.json").write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n",
                                                       encoding="utf-8")


if __name__ == "__main__":
    main()
