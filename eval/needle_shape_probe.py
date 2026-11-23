"""Phase 8 S4: the needle answer-shape probe (plan §1.2).

    python eval/needle_shape_probe.py FILE... --upstream URL [--model M] [--samples 3]
        [--runs 1] [--variant original|format] [--out JSON]

Each question of each needle history goes direct to upstream (no proxy, no tools, no
system message), with only its evidence in view, and the reply is scored with the frozen
loose scorer (``needle.score``'s ``exact_loose``). A question passes when every one of
``--samples`` samples (3) passes; ``--runs 2`` asks for two consecutive passing probes,
as a revised question needs. The probe tests the question's phrasing, not recall: the
model sees the fact, so a miss is mostly a reply in the wrong shape. It is also counted
when the reply is cut at the output limit with no answer, or when a question that says
"Execute …" draws a refusal: no tools are offered (the command's scripted output is in
view when it holds the evidence). Both affect the original and the format phrasing alike.

**What is in view** (``probe_messages``):

- every passage before the question that holds one of its ``evidence`` strings: history
  messages (text and tool-call arguments), earlier pasted steps, workspace files and
  scripted shell outputs; a passage longer than ``2 * window`` characters is cut to the
  window around each evidence string, so an oversized read shows the lines around the
  fact, not the whole read;
- for a ``vague`` question, the previous question with its gold answer as the reply, so
  "its" has a referent;
- one user message: the passages, then the question.

**Variants.** ``original`` sends the step's text. ``format`` sends the text under the
format rule: a step that declares ``answer_format`` as written; an older step as its stem
(``needle_format.stem_of``) plus the fixed sentence for its inferred kind (R70 only).

**Output is counts only**: per history, per generator and in total, and with ``--out`` a
JSON of per-question pass counts. No model text and no gold answer is printed or stored,
so authors can run it on their own questions (AUTHORING.md §4). A failed upstream call
raises ``UpstreamError``; it is never counted as a miss.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable

import httpx

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.append(str(HERE))

import needle  # noqa: E402
import needle_format as nf  # noqa: E402

WINDOW = 1500
MAX_TOKENS = 8192  # the client output limit arm 4 runs with (needle.output_limit)
Call = Callable[[list[dict]], str]


class UpstreamError(RuntimeError):
    pass


def _text(m: dict) -> str:
    parts = [m.get("content") if isinstance(m.get("content"), str) else ""]
    for c in m.get("tool_calls") or []:
        parts.append((c.get("function") or {}).get("arguments") or "")
    return "\n".join(p for p in parts if p)


def _cut(text: str, evidence: list[str], window: int) -> str:
    if len(text) <= 2 * window:
        return text
    spans = []
    for e in evidence:
        i = text.find(e)
        while i >= 0:
            spans.append((max(0, i - window), min(len(text), i + len(e) + window)))
            i = text.find(e, i + 1)
    spans.sort()
    merged: list[list[int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return "\n…\n".join(text[a:b] for a, b in merged)


def passages(history: dict, step: dict, *, window: int = WINDOW) -> list[str]:
    """The texts before ``step`` holding any of its evidence strings, cut to windows."""
    ev = [e for e in step.get("evidence") or [] if e]
    sources = [_text(m) for m in history.get("import") or []]
    for s in history.get("steps") or []:
        if s is step or s.get("id") == step.get("id"):
            break
        if s.get("kind") != "question":
            sources.append(s.get("text") or "")
    sources += [f"{rel}:\n{body}" for rel, body in (history.get("workspace") or {}).items()]
    sources += [f"$ {s.get('match', '')}\n{s.get('output', '')}" for s in history.get("shell") or []]
    out, seen = [], set()
    for src in sources:
        if src and any(e in src for e in ev) and src not in seen:
            seen.add(src)
            out.append(_cut(src, ev, window))
    return out


def question_text(step: dict, variant: str) -> str:
    if variant == "original" or step.get("answer_format"):
        return step["text"]
    if variant == "format":
        return nf.apply(nf.stem_of(step["text"]), nf.infer_format(step))
    raise ValueError(f"unknown variant {variant!r}")


def _previous_question(history: dict, step: dict) -> dict | None:
    prev = None
    for s in history.get("steps") or []:
        if s.get("id") == step.get("id"):
            return prev
        if s.get("kind") == "question":
            prev = s
    return None


def probe_messages(history: dict, step: dict, *, variant: str = "original",
                   window: int = WINDOW) -> list[dict]:
    head = "Material from earlier in this conversation:\n\n"
    body = "\n\n---\n\n".join(passages(history, step, window=window))
    q = question_text(step, variant)
    msgs = []
    if step.get("category") == "vague" and (prev := _previous_question(history, step)):
        msgs += [{"role": "user", "content": question_text(prev, variant)},
                 {"role": "assistant", "content": prev["answer"]}]
    msgs.append({"role": "user", "content": f"{head}{body}\n\n{q}" if body else q})
    return msgs


def passes(reply: str, step: dict) -> bool:
    """The frozen loose scorer (D115.5): ``needle.score``'s ``exact_loose``."""
    return needle.score(reply, step)["exact_loose"]


def make_call(upstream: str, model: str | None = None, *, timeout: float = 600.0) -> Call:
    """A function that sends one probe and returns the reply's content."""
    base = upstream.rstrip("/")
    client = httpx.Client(timeout=httpx.Timeout(timeout, connect=15))
    if model is None:
        r = client.get(f"{base}/v1/models")
        if r.status_code != 200:
            raise UpstreamError(f"/v1/models: {r.status_code}")
        model = r.json()["data"][0]["id"]

    def call(messages: list[dict]) -> str:
        body = json.dumps({"model": model, "messages": messages, "stream": True,
                           "stream_options": {"include_usage": True},
                           "max_completion_tokens": MAX_TOKENS}).encode()
        res = needle.stream_call(client, f"{base}/v1/chat/completions", body)
        if res.status != 200 or res.error:
            raise UpstreamError(f"status {res.status}: {res.error}")
        return res.content

    return call


def probe_step(history: dict, step: dict, call: Call, *, samples: int = 3,
               variant: str = "original") -> int:
    """How many of ``samples`` replies pass the loose scorer."""
    msgs = probe_messages(history, step, variant=variant)
    return sum(passes(call(msgs), step) for _ in range(samples))


def accepted(history: dict, step: dict, call: Call, *, samples: int = 3, runs: int = 2,
             variant: str = "original") -> bool:
    """``runs`` consecutive probes, each passing every sample (AUTHORING.md §4)."""
    for _ in range(runs):
        if probe_step(history, step, call, samples=samples, variant=variant) < samples:
            return False
    return True


def _generator(h: dict) -> str:
    g = Path(h.get("generator") or "?").stem
    return g.rsplit("_", 1)[-1] if "_" in g else g


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--upstream", required=True)
    p.add_argument("--model")
    p.add_argument("--samples", type=int, default=3)
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--variant", choices=["original", "format"], default="original")
    p.add_argument("--out", type=Path)
    p.add_argument("--reason", default="initial",
                   help="eval/headless.py passes it on a rerun (host-restart); recorded in --out")
    a = p.parse_args(argv)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)  # a headless step's first output
    call = make_call(a.upstream, a.model)
    rec: dict = {"variant": a.variant, "samples": a.samples, "runs": a.runs, "reason": a.reason,
                 "questions": {}}
    by_gen: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    total = [0, 0]
    for f in a.files:
        h = json.loads(f.read_text(encoding="utf-8"))
        qs = [s for s in h.get("steps") or [] if s.get("kind") == "question"]
        ok = 0
        for s in qs:
            got = 0
            for _ in range(a.runs):
                got = probe_step(h, s, call, samples=a.samples, variant=a.variant)
                if got < a.samples:
                    break
            rec["questions"][s["id"]] = {"passes": got, "samples": a.samples,
                                         "category": s.get("category"), "generator": _generator(h)}
            ok += got == a.samples
        g = by_gen[_generator(h)]
        g[0] += ok
        g[1] += len(qs)
        total[0] += ok
        total[1] += len(qs)
        print(f"{h.get('id', f.stem)}: {ok}/{len(qs)} questions pass", flush=True)
        if a.out:
            a.out.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    for g, (ok, n) in sorted(by_gen.items()):
        print(f"generator {g}: {ok}/{n} questions pass")
    print(f"total: {total[0]}/{total[1]} questions pass ({a.variant}, {a.samples} samples, {a.runs} run(s))")
    if a.out:
        a.out.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
