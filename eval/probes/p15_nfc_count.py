"""Live probe (idle-gated, max_tokens 1): does Strata NFC-normalize text before tokenizing?

The pinned ``tokenizer.json`` has an NFC normalizer; Strata's own tokenizer
(``tools/strata_tokenizer.py``) is built from the pack's vocab and merges. Text whose NFC
form differs (combining accents, the Angstrom sign, ...) tells them apart.

    uv run python eval/probes/p15_nfc_count.py [--upstream URL]
"""

from __future__ import annotations

import argparse
import json
import time
import unicodedata
from pathlib import Path

import httpx

from palimnesis.upstreams.strata import tokens

OUT = Path(__file__).parent / "fixtures" / "strata_nfc.json"
TEXTS = {
    "ascii": "plain text",
    "combining_acute": "café au lait",
    "angstrom_sign": "10 Å apart",
    "fullwidth_a": "grade Ａ",
    "hangul_jamo": "각 word",
    "precomposed": "café au lait",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", default="http://192.168.1.19:8080")
    a = ap.parse_args()
    t = tokens.default()
    out = {"upstream": a.upstream, "cases": {}}
    with httpx.Client(base_url=a.upstream) as client:
        for name, text in TEXTS.items():
            messages = [{"role": "user", "content": text}]
            while (s := client.get("/status", timeout=10).json()).get("busy") or s.get("queued"):
                time.sleep(3)
            r = client.post("/v1/chat/completions", timeout=120, json={
                "model": "m", "max_tokens": 1, "stream": False, "messages": messages})
            n = r.json()["usage"]["prompt_tokens"]
            out["cases"][name] = {"messages": messages, "prompt_tokens": n}
            print(f"{name:16} strata {n}  local {t.count_messages(messages)}  "
                  f"nfc-differs {unicodedata.normalize('NFC', text) != text}")
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
