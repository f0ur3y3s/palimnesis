"""Probe 4 + 2: exact token counting via /v1/messages/count_tokens (no inference, does not queue).

Also measures how reasoning in history is rendered, by counting variants that differ only in a
thinking block. Saves fixtures/count_tokens.json.
"""

from __future__ import annotations

import time

from p05_nonstream import TOOLS_AN, TOOLS_OA
from strata_common import MODEL, client, filler, save_json

TH = "Let me think about this carefully step by step with many words of reasoning here."
Q1 = [{"role": "user", "content": "Q1"}]
PRIOR_TEXT = Q1 + [{"role": "assistant", "content": "Answer one."}, {"role": "user", "content": "Q2"}]
PRIOR_THINK = Q1 + [{"role": "assistant", "content": [{"type": "thinking", "thinking": TH, "signature": "x"},
                                                       {"type": "text", "text": "Answer one."}]},
                    {"role": "user", "content": "Q2"}]
TOOL_TURN_NO_THINK = [
    {"role": "user", "content": "Weather in Paris?"},
    {"role": "assistant", "content": [{"type": "tool_use", "id": "c1", "name": "get_weather", "input": {"city": "Paris"}}]},
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "Sunny 20C"}]},
]
TOOL_TURN_THINK = [TOOL_TURN_NO_THINK[0],
                   {"role": "assistant", "content": [{"type": "thinking", "thinking": TH, "signature": "x"},
                                                     TOOL_TURN_NO_THINK[1]["content"][0]]},
                   TOOL_TURN_NO_THINK[2]]

CASES = {
    "user_only_default": {"messages": Q1},
    "user_only_thinking_disabled": {"messages": Q1, "thinking": {"type": "disabled"}},
    "user_only_effort_low": {"messages": Q1, "output_config": {"effort": "low"}},
    "user_only_effort_medium": {"messages": Q1, "output_config": {"effort": "medium"}},
    "user_only_effort_high": {"messages": Q1, "output_config": {"effort": "high"}},
    "user_only_reasoning_effort_low_ignored?": {"messages": Q1, "reasoning_effort": "low"},
    "system_plus_user": {"system": "You are terse.", "messages": Q1},
    "prior_turn_text": {"messages": PRIOR_TEXT},
    "prior_turn_thinking": {"messages": PRIOR_THINK},
    "prior_turn_text_thinking_disabled": {"messages": PRIOR_TEXT, "thinking": {"type": "disabled"}},
    "prior_turn_thinking_thinking_disabled": {"messages": PRIOR_THINK, "thinking": {"type": "disabled"}},
    "prior_turn_thinking_preserve_false_kwarg": {"messages": PRIOR_THINK, "chat_template_kwargs": {"preserve_thinking": False}},
    "prior_turn_openai_reasoning_content_field": {"messages": Q1 + [{"role": "assistant", "content": "Answer one.",
                                                                     "reasoning_content": TH},
                                                                    {"role": "user", "content": "Q2"}]},
    "tool_turn_no_think": {"messages": TOOL_TURN_NO_THINK, "tools": TOOLS_AN},
    "tool_turn_think": {"messages": TOOL_TURN_THINK, "tools": TOOLS_AN},
    "tools_only": {"messages": Q1, "tools": TOOLS_AN},
    "openai_style_tools_rejected?": {"messages": Q1, "tools": TOOLS_OA},
    "trailing_assistant_prefill": {"messages": Q1 + [{"role": "assistant", "content": "Partial"}]},
    "filler_1000_words": {"messages": [{"role": "user", "content": filler(1000, seed=1)}], "thinking": {"type": "disabled"}},
    "filler_16000_words_over_ctx": {"messages": [{"role": "user", "content": filler(16000, seed=1)}],
                                    "thinking": {"type": "disabled"}},
}


def main() -> None:
    out = {}
    with client(60) as c:
        for name, body in CASES.items():
            t0 = time.monotonic()
            r = c.post("/v1/messages/count_tokens", json={"model": MODEL, **body})
            out[name] = {"status": r.status_code, "body": r.json(), "ms": round((time.monotonic() - t0) * 1000, 1)}
            print(f"{name:45s} {r.status_code} {r.text[:120]} {out[name]['ms']}ms")
    save_json("count_tokens.json", out)


if __name__ == "__main__":
    main()
