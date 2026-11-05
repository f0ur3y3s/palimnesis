"""Pi 1.5.0 as the coding-task client: ``eval/tasks/run.py --harness pi`` (Phase 4B S14).

"Coding against native compaction" (``docs/plan/phases/phase4b.md`` §6, reported, not
gated): the development tasks dev-t1..t5, arm 4 against arm 1, through real Pi run as in
``eval/pi_harness.py`` (throwaway agent directory and home, the shipped adapter, success
judged by ``agent_settled``).

- **Arm 4** (``a4-d77``, ``serve``'s defaults since D78): the adapter as shipped,
  ``contextWindow`` 1,000,000 and ``compaction.enabled: false``, through the proxy.
- **Arm 1** (Pi's own compaction, D44.1 as for OpenCode): ``serve --passthrough``,
  ``compaction.enabled: true`` and every model's ``contextWindow`` at ``--expect-n-ctx``
  (the emulated context under ``--input-budget``). Pi's other compaction settings keep
  their defaults unless ``--pi-keep-recent-tokens`` sets ``keepRecentTokens`` (HP5).

One task is one Pi session: the driver writes an empty session file whose id is the
Palimnesis session id (``pi_harness.new_session_file``), and every task turn is one
``pi --mode json --session <file>`` run, a fresh Pi process. The adapter's extension sends
``X-Palimnesis-Session`` = that id. Before ``RESTART_BEFORE`` the proxy restarts too.

Pi has no session export: its session file stands in for it (``pi_harness.as_export``) in
the client leak scan, as in ``eval/needle_pi.py``. Compactions are counted from Pi's
``compaction_start``/``compaction_end`` events; the summarizer requests the upstream tap
saw are listed beside them.

Held-out tasks are refused: no held-out set runs through Pi in 4B (O-4B-11; D96 keeps
``ho4`` for Phase 7).

**Fake upstream** (``--upstream fake``, Chat; a plumbing check, not a result): the stack
runs against ``tests/fake_upstream.py`` with no slot gate. Turn 1 reads one file of the
task's ``REFERENCE``, the restart turn writes every ``REFERENCE`` file with Pi's ``write``
tool, arm 4's last turn greps the session's transcript directory (one lookup), and every
other request gets "ok" (the proxy's notes refreshes get ``needle_pi.FAKE_NOTES``). The
hidden check should then pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import gate_inputs as gi
import needle
import needle_pi
import oc_stack
import pi_harness as pi

PI_VERSION = "1.5.0"
# The tasks read, search, run the suite and edit files.
TOOLS = "read,grep,bash,ls,find,edit,write"
ARM4_CONFIG = needle.A4_HELDOUT3  # a4-d77: arm 4 as serve's defaults (D78)
ADAPTER_CONTEXT_WINDOW = 1_000_000


def refusals(task_set: str, arm: int, config: str | None, protocol: str, upstream: str) -> list[str]:
    """Why a Pi task run must not start (empty when it may)."""
    out = []
    if task_set != "development":
        out.append(f"Pi runs development tasks only in Phase 4B (O-4B-11, D96), not {task_set}")
    if arm not in (1, 4):
        out.append(f"Pi runs arm 4 ({ARM4_CONFIG}) and arm 1 (native compaction), not arm {arm}")
    if arm == 4 and config not in (None, ARM4_CONFIG):
        out.append(f"Pi runs arm 4 only as {ARM4_CONFIG} (phase4b §6), not {config}")
    if arm == 1 and config is not None:
        out.append("--config applies to arm 4; arm 1 is native compaction")
    if protocol not in pi.PROVIDER:
        out.append(f"unknown protocol {protocol}")
    if upstream == "fake" and protocol != "chat" and arm == 1:
        out.append("the fake upstream answers Chat only; arm 1 passes Messages through unchanged")
    return out


def resolve_arm(arm: int) -> dict:
    """{arm, label, config, cfg}: arm 4 is ``a4-d77`` under its own label (as
    ``run.resolve_arm(4, "a4-d77", ...)``), arm 1 ``a1``."""
    if arm == 4:
        return {"arm": 4, "label": ARM4_CONFIG, "config": ARM4_CONFIG, "cfg": needle.CONFIGS[ARM4_CONFIG]}
    if arm == 1:
        return {"arm": 1, "label": "a1", "config": "a1-native", "cfg": None}
    raise ValueError(f"no Pi arm {arm}")


def pi_config(arm: int, n_ctx: int, keep_recent_tokens: int | None = None) -> dict:
    """The Pi settings an arm changes: ``context_window`` and ``compaction`` for
    ``pi_harness.PiHome``. Arm 4 is the adapter unchanged."""
    if arm == 1:
        comp = {"enabled": True}
        if keep_recent_tokens is not None:
            comp["keepRecentTokens"] = keep_recent_tokens
        return {"context_window": n_ctx, "compaction": comp}
    return {"context_window": ADAPTER_CONTEXT_WINDOW, "compaction": {"enabled": False}}


def arm_fields(info: dict, n_ctx: int, input_budget: int | None = None,
               keep_recent_tokens: int | None = None) -> dict:
    """The arm as ``result.json`` records it (the OpenCode runner's fields, with Pi's
    settings in place of OpenCode's limits)."""
    emulated = gi.emulated_n_ctx(input_budget, n_ctx) if input_budget is not None else None
    cfg = pi_config(info["arm"], emulated or n_ctx, keep_recent_tokens)
    return {"arm": info["arm"], "config": info["config"], "frozen_as": None,
            "config_settings": info["cfg"], "passthrough": info["arm"] == 1,
            "input_budget": input_budget, "emulated_n_ctx": emulated,
            "pi_context_window": cfg["context_window"], "pi_compaction": cfg["compaction"],
            "compaction_auto": info["arm"] == 1}


def session_name(task_id: str, label: str, tag: str, attempt: int) -> str:
    """The Palimnesis session id, which is also Pi's session id (letters, digits, ``-``)."""
    return f"{task_id}-{label}-{tag}-a{attempt}"


def tool_rows(tools: list[dict]) -> list[dict]:
    """``turn_summary`` tools in the OpenCode runner's per-turn shape."""
    return [{"name": t["name"], "status": "error" if t["error"] else "completed",
             "output_chars": t["output_chars"]} for t in tools]


def upstream_compactions(bodies: Path, calls: list[dict]) -> list[int]:
    """Upstream calls whose body is a Pi summarizer request."""
    out = []
    for c in calls:
        f = bodies / f"{c['n']:04d}.json"
        try:
            if pi.is_compaction_request(json.loads(f.read_bytes())):
                out.append(c["n"])
        except (OSError, ValueError):
            continue
    return out


def chat_calls(calls: list[dict]) -> list[dict]:
    """Calls on the Chat endpoint: the only bodies the pinned counter reads (``drift``)."""
    return [c for c in calls if str(c.get("path") or "").endswith("/chat/completions")]


class Stack(oc_stack.Stack):
    """``oc_stack.Stack`` (passthrough for arm 1) with an optional slot gate (none against
    the fake upstream) and the front tap's origin for Pi's ``baseUrl``."""

    def __init__(self, records: Path, upstream: str, settings: dict, *, passthrough: bool = False,
                 gated: bool = True, transcripts: Path | None = None, input_budget: int | None = None):
        self.records = records
        self.gate = needle.SlotGate(upstream if gated else None)
        self.tap = needle.Tap(upstream, records / "bodies", self.gate)
        self.tap_server, self.tap_thread = needle.serve_in_thread(self.tap, tap_port := needle.free_port())
        self.settings = dict(settings, deadline_s=3600.0)
        if transcripts is not None and not passthrough:
            self.settings["transcripts"] = str(transcripts)
        self.transcripts = transcripts if not passthrough else None
        self.proxy = needle.ProxyProcess(records, f"http://127.0.0.1:{tap_port}", self.settings,
                                         input_budget=input_budget, passthrough=passthrough)
        self.proxy.start()
        self.front = needle.Tap(self.proxy.url, records / "front", needle.SlotGate(None))
        self.front_port = needle.free_port()
        self.front_server, self.front_thread = needle.serve_in_thread(self.front, self.front_port)

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.front_port}"


# ---------------------------------------------------------------- fake upstream

def fake_replies(task, turn: int, sdir: Path | None) -> list[dict]:
    """The scripted replies of one task turn (module docstring), as
    ``FakeUpstream.respond_counted`` keyword sets."""
    ref = sorted(task.REFERENCE)
    out: list[dict] = []
    if turn == 0 and ref:
        out.append({"tool_call": (f"call_fake_t{turn + 1}_read", "read", pi.js_compact({"path": ref[0]}))})
    if turn == task.RESTART_BEFORE:
        for k, rel in enumerate(ref):
            out.append({"tool_call": (f"call_fake_t{turn + 1}_w{k}", "write",
                                      pi.js_compact({"path": rel, "content": task.REFERENCE[rel]}))})
    if turn == len(task.TURNS) - 1 and sdir is not None:
        cmd = f"grep -rn -F -- {json.dumps(task.ID)} {json.dumps(sdir.as_posix())} | head -3"
        out.append({"tool_call": (f"call_fake_t{turn + 1}_grep", "bash", pi.js_compact({"command": cmd}))})
    out.append({"text": f"Turn {turn + 1} done."})
    return out


class FakeTaskModel(needle_pi.FakeModel):
    """``needle_pi.FakeModel`` scripted per task turn (``fake_replies``)."""

    def script_turn(self, replies: list[dict]) -> None:
        self.queue = list(replies)
        sys.path.insert(0, str(needle.ROOT))
        from tests.fake_upstream import _Scripted

        for _ in range(len(self.queue) + 4):  # spares serve notes refreshes and strays
            self.fake._script.append(_Scripted(status=200, headers={"content-type": "text/event-stream"},
                                               build=self._build, chunks=[]))
