"""Probes 1-3: server identity, metadata endpoints, chat template, and route discovery (no inference).

Saves fixtures/props.json, fixtures/strata_chat_template.jinja (verbatim), fixtures/v1_status.json,
fixtures/metrics_sample.json, fixtures/routes.json.
Route discovery only sends GETs and POSTs with an empty JSON object, which every generation route
rejects before inference.
"""

from __future__ import annotations

from strata_common import FIXTURES, client, save_json

GETS = ["/health", "/api/health", "/props", "/v1/models", "/models", "/slots", "/status", "/v1/status",
        "/metrics", "/metrics/prometheus", "/version", "/mcp"]
POSTS = ["/v1/chat/completions", "/v1/completions", "/completion", "/v1/messages", "/v1/messages/count_tokens",
         "/v1/responses", "/v1/responses/input_tokens", "/tokenize", "/detokenize", "/apply-template",
         "/v1/tokenize", "/api/tokenize", "/v1/embeddings", "/infill"]


def main() -> None:
    routes: dict = {"GET": {}, "POST {}": {}}
    with client(15) as c:
        for p in GETS:
            r = c.get(p)
            routes["GET"][p] = {"status": r.status_code, "content_type": r.headers.get("content-type"),
                                "server": r.headers.get("server"), "body_head": r.text[:200]}
        for p in POSTS:
            r = c.post(p, json={})
            routes["POST {}"][p] = {"status": r.status_code, "body": r.text[:300]}
        props = c.get("/props").json()
        save_json("props.json", props)
        (FIXTURES / "strata_chat_template.jinja").write_bytes(props["chat_template"].encode("utf-8"))
        save_json("v1_status.json", c.get("/v1/status").json())
        save_json("metrics_sample.json", c.get("/metrics").json())
        prom = c.get("/metrics", headers={"Accept": "text/plain"})
        (FIXTURES / "metrics_prometheus.txt").write_bytes(prom.content)
    save_json("routes.json", routes)
    for k, v in routes.items():
        for p, x in v.items():
            print(k, p, x["status"], (x.get("body") or x.get("body_head") or "")[:120])
    print("build_info:", props.get("build_info"), "caps:", props.get("chat_template_caps"))


if __name__ == "__main__":
    main()
