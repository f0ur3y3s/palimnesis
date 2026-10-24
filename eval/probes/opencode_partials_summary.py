"""Summarize eval/fixtures/opencode-2.1.4/partials/<run>/ fixtures.

For each run: every chat request with its turn and attempt, the messages after the
system prompt (content shown in full; reasoning_content and tool_calls flagged), and a
byte-level check that each request starts with the exact bytes of turn 1's first
request up to the end of its last message (the history before the failed turn).

Usage: uv run python eval/probes/opencode_partials_summary.py [RUN ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "eval"
    / "fixtures"
    / "opencode-2.1.4"
    / "partials"
)


def _messages_span(raw: bytes) -> tuple[int, int]:
    """Byte offsets of the '[' and matching ']' of the top-level "messages" array."""
    start = raw.index(b'"messages":[') + len(b'"messages":')
    depth, in_str, esc = 0, False, False
    for i in range(start, len(raw)):
        c = raw[i]
        if in_str:
            if esc:
                esc = False
            elif c == 0x5C:
                esc = True
            elif c == 0x22:
                in_str = False
        elif c == 0x22:
            in_str = True
        elif c in (0x5B, 0x7B):
            depth += 1
        elif c in (0x5D, 0x7D):
            depth -= 1
            if depth == 0:
                return start, i
    raise ValueError("unterminated messages array")


def summarize(run_dir: Path) -> str:
    out = [f"== {run_dir.name}"]
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    out.append(
        f"   scenario={meta['scenario']} config={meta['config']} "
        f"exits={[t['exit_code'] for t in meta['turns']]}"
    )
    for tag in ("turn1", "turn2"):
        p = run_dir / f"{tag}.stdout.txt"
        e = run_dir / f"{tag}.stderr.txt"
        if p.exists():
            txt = (
                p.read_text("utf-8", "replace") + e.read_text("utf-8", "replace")
            ).strip()
            out.append(f"   {tag} output: {txt!r}")
    reqs = [
        json.loads(line)
        for line in (run_dir / "requests.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    chat = [r for r in reqs if r.get("attempt") is not None]
    base_raw = (run_dir / chat[0]["raw_body_file"]).read_bytes()
    _, e0 = _messages_span(base_raw)
    # Everything up to (not including) the closing ']' of turn 1 attempt 1's messages.
    base_prefix = base_raw[:e0]
    for r in chat:
        raw = (run_dir / r["raw_body_file"]).read_bytes()
        body = json.loads(raw)
        hdr = {k.lower(): v for k, v in r["headers"]}
        out.append(
            f"-- {r['raw_body_file']} turn={r['turn']} attempt={r['attempt']} "
            f"bytes={len(raw)} msgs={len(body['messages'])} "
            f"trace={hdr.get('traceparent', '')[3:35]}"
        )
        for i, m in enumerate(body["messages"]):
            if m["role"] == "system":
                out.append(f"   [{i}] system ({len(m['content'])} chars)")
                continue
            extra = {k: v for k, v in m.items() if k not in ("role", "content")}
            out.append(
                f"   [{i}] {m['role']}: content={json.dumps(m.get('content'), ensure_ascii=False)}"
                + (f" extra={json.dumps(extra, ensure_ascii=False)}" if extra else "")
            )
        if raw.startswith(base_prefix):
            nxt = raw[len(base_prefix) : len(base_prefix) + 1]
            out.append(
                f"   bytes: starts with turn-1 attempt-1 body through its last message "
                f"({len(base_prefix)} B), next byte {nxt!r}"
            )
        else:
            n = next(
                (i for i, (a, b) in enumerate(zip(raw, base_prefix)) if a != b),
                min(len(raw), len(base_prefix)),
            )
            out.append(
                f"   bytes: DIVERGES from turn-1 attempt-1 at byte {n}: "
                f"{base_prefix[max(0, n - 60) : n + 60]!r} vs {raw[max(0, n - 60) : n + 60]!r}"
            )
        _, e = _messages_span(raw)
        same_tail = raw[e:] == base_raw[e0:]
        out.append(f"   bytes after messages array identical to attempt 1: {same_tail}")
    return "\n".join(out)


def main() -> None:
    names = sys.argv[1:] or sorted(
        p.name for p in FIXTURES.iterdir() if (p / "meta.json").exists()
    )
    print("\n\n".join(summarize(FIXTURES / n) for n in names))


if __name__ == "__main__":
    main()
