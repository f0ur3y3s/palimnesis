"""The request/transcript ledger: what was accepted, attempted and generated.

Every function takes a SQLite connection and runs inside the caller's
transaction (``Store.write``/``Store.read``), so one logical step is one
atomic commit:

- ``accept`` reconciles a client request with the archived visible history
  and either rejects it (``Rejection``), plans a new attempt of an earlier
  request (a keyless retry), or archives the raw body, request, new
  occurrences and attempt before any inference (contracts §11).
- ``commit_batch`` records a bounded batch of generated content before the
  relay forwards it, creating the generated occurrence on first output.
- ``finish_attempt`` records the terminal outcome and frees the branch.
- ``recover`` marks attempts interrupted by a crash as abandoned (D10.12).

Status codes and error codes follow contracts §5 and D10.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import chat, search
from .addresses import issue_alias
from .chat import ChatRequest, Message
from .rawarchive import put_raw
from .transcript import Archived, Divergence, Extend, Prefix, reconcile

ENDPOINT_CHAT = "/v1/chat/completions"
TERMINAL_EVENTS = ("turn_complete", "attempt_failed", "attempt_abandoned", "cancelled")


def branch_id_for(session_id: str) -> str:
    return f"{session_id}/main"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class Rejection(Exception):
    def __init__(self, status: int, code: str, message: str, retry: bool = False) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.retry = status, code, message, retry


@dataclass
class Plan:
    session_id: str
    branch_id: str
    request_id: str
    attempt_id: str
    upstream_body: bytes
    stream: bool
    replay: dict | None = None  # a committed non-streaming response to deliver as is
    # Upstream messages in order, each with its archived occurrence (palimnesis.view).
    items: list = field(default_factory=list)
    view_state: Any = None  # the branch's persisted ViewState when planned


@dataclass
class Generation:
    """Relay-side state for one attempt's generated occurrence."""

    plan: Plan
    occ_id: str | None = None
    generation_id: str | None = None
    blocks: dict[Any, str] = field(default_factory=dict)  # kind or ("tool", i) → block_id
    next_segment: dict[str, int] = field(default_factory=dict)
    forwarded: int = 0
    finished: bool = False
    delivered: bool = False
    delivery_started: bool = False
    progress_recorded: int = 0


# --- reading -----------------------------------------------------------------


def _text(conn: sqlite3.Connection, block_id: str, encoding: str) -> str:
    data = b"".join(
        row[0]
        for row in conn.execute(
            "SELECT bytes FROM segments WHERE block_id = ? ORDER BY seq", (block_id,)
        )
    )
    return data.decode("utf-8", "surrogatepass" if encoding == "wtf-8" else "strict")


def _blocks(conn: sqlite3.Connection, occ_id: str) -> list[tuple[str, dict, str]]:
    return [
        (kind, json.loads(meta), _text(conn, block_id, encoding))
        for block_id, kind, encoding, meta in conn.execute(
            "SELECT block_id, kind, encoding, meta FROM blocks WHERE occ_id = ? ORDER BY idx",
            (occ_id,),
        )
    ]


def _attempt_events(conn: sqlite3.Connection, generation_id: str) -> set[str]:
    return {
        kind
        for (kind,) in conn.execute(
            "SELECT e.kind FROM events e JOIN generations g ON e.attempt_id = g.attempt_id"
            " WHERE g.generation_id = ?",
            (generation_id,),
        )
    }


# Attempt events after which a generated turn's flags can no longer change.
_SETTLED_EVENTS = frozenset({"cancelled", "attempt_failed", "attempt_abandoned",
                             "delivery_completed", "delivery_failed"})
_OCC_COLUMNS = ("occ_id, role, source, view, content_sha256, generation_id, envelope, seq,"
                " (SELECT alias FROM aliases WHERE target_id = occ_id)")


def _archived(conn: sqlite3.Connection, row) -> tuple[Archived, bool]:
    """(archived occurrence, settled): settled ones never change again."""
    occ_id, role, source, view, sha, generation_id, _envelope = row[:7]
    if source != "generated":
        return Archived(occ_id, role, source, view=view, content_sha256=sha), True
    text = reasoning = ""
    calls = []
    for kind, meta, content in _blocks(conn, occ_id):
        if kind == "text":
            text += content
        elif kind == "reasoning":
            reasoning += content
        elif kind == "tool_call":
            calls.append({"id": meta["id"], "name": meta["name"], "arguments": content})
    kinds = _attempt_events(conn, generation_id)
    archived = Archived.generated(occ_id, text=text, reasoning=reasoning, tool_calls=tuple(calls),
                                  complete="turn_complete" in kinds, view=view,
                                  cancelled="cancelled" in kinds,
                                  delivered="delivery_completed" in kinds)
    return archived, bool(kinds & _SETTLED_EVENTS)


@dataclass
class _Entry:
    archived: Archived
    supersedes: str | None
    settled: bool
    row: tuple


class BranchCache:
    """Per-process cache of each branch's archived occurrences.

    The archive has one owning process (the store lock), and occurrences are
    append-only, so a branch's cached rows stay valid. Each load fetches only
    rows past the cached max ``seq`` and re-reads generated turns that are not
    yet settled. Accept's database work is O(new rows), not O(history)
    (results R8).
    """

    def __init__(self) -> None:
        self._branches: dict[str, tuple[int, list[_Entry]]] = {}

    def load(self, conn: sqlite3.Connection, branch_id: str) -> list[_Entry]:
        max_seq, entries = self._branches.get(branch_id, (0, []))
        current = conn.execute(
            "SELECT coalesce(max(seq), 0) FROM occurrences WHERE branch_id = ?", (branch_id,)
        ).fetchone()[0]
        if current < max_seq:  # archive replaced underneath us: start over
            max_seq, entries = 0, []
        entries = [
            e if e.settled else _entry(conn, conn.execute(
                f"SELECT {_OCC_COLUMNS} FROM occurrences WHERE occ_id = ?", (e.row[0],)
            ).fetchone())
            for e in entries
        ]
        if current > max_seq:
            entries += [_entry(conn, row) for row in conn.execute(
                f"SELECT {_OCC_COLUMNS} FROM occurrences WHERE branch_id = ? AND seq > ?"
                " ORDER BY seq", (branch_id, max_seq))]
        self._branches[branch_id] = (current, entries)
        return entries

    def addresses(self, branch_id: str) -> dict[str, tuple[int, str | None]]:
        """occ_id → (seq, alias) for the branch as last loaded."""
        return {e.row[0]: (e.row[7], e.row[8]) for e in self._branches.get(branch_id, (0, []))[1]}


def _entry(conn: sqlite3.Connection, row) -> _Entry:
    archived, settled = _archived(conn, row)
    return _Entry(archived, json.loads(row[6]).get("supersedes"), settled, tuple(row))


def load_archived(conn: sqlite3.Connection, branch_id: str,
                  cache: BranchCache | None = None) -> list[Archived]:
    """The branch's occurrences in order, superseded context versions replaced."""
    if cache is not None:
        entries = cache.load(conn, branch_id)
    else:
        entries = [_entry(conn, row) for row in conn.execute(
            f"SELECT {_OCC_COLUMNS} FROM occurrences WHERE branch_id = ? ORDER BY seq",
            (branch_id,))]
    history: list[Archived] = []
    position: dict[str, int] = {}
    for entry in entries:
        archived = entry.archived
        if entry.supersedes in position:
            index = position.pop(entry.supersedes)
            history[index] = archived
            position[archived.occ_id] = index
        else:
            position[archived.occ_id] = len(history)
            history.append(archived)
    return history


def message_dict(conn: sqlite3.Connection, occ_id: str) -> dict:
    """Rebuild an archived occurrence as a Chat Completions message object."""
    role, envelope = conn.execute(
        "SELECT role, envelope FROM occurrences WHERE occ_id = ?", (occ_id,)
    ).fetchone()
    envelope = json.loads(envelope)
    blocks = _blocks(conn, occ_id)
    if role == "tool":
        [(_, meta, content)] = blocks
        return {"role": "tool", "tool_call_id": meta["tool_call_id"], "content": content}
    message: dict[str, Any] = {"role": role}
    texts = [c for k, _, c in blocks if k == "text"]
    message["content"] = "".join(texts) if texts else None
    reasoning = [c for k, _, c in blocks if k == "reasoning"]
    if reasoning:
        message["reasoning_content"] = "".join(reasoning)
    calls = [
        {"id": m["id"], "type": "function", "function": {"name": m["name"], "arguments": c}}
        for k, m, c in blocks
        if k == "tool_call"
    ]
    if calls:
        message["tool_calls"] = calls
    if envelope.get("content_form") == "absent" and message["content"] is None:
        del message["content"]
    return message


# --- writing helpers ---------------------------------------------------------


def _event(conn, request_id, attempt_id, kind: str, **payload) -> None:
    conn.execute(
        "INSERT INTO events (request_id, attempt_id, kind, payload, at) VALUES (?, ?, ?, ?, ?)",
        (request_id, attempt_id, kind, json.dumps(payload, ensure_ascii=False), time.time()),
    )


def _next_seq(conn, branch_id: str) -> int:
    return conn.execute(
        "SELECT coalesce(max(seq), 0) + 1 FROM occurrences WHERE branch_id = ?", (branch_id,)
    ).fetchone()[0]


def _insert_block(conn, occ_id, idx, kind, encoding, meta, data: bytes | None) -> str:
    block_id = new_id("blk")
    conn.execute(
        "INSERT INTO blocks VALUES (?, ?, ?, ?, ?, ?)",
        (block_id, occ_id, idx, kind, encoding, json.dumps(meta, ensure_ascii=False)),
    )
    if data is not None:
        conn.execute("INSERT INTO segments VALUES (?, 0, ?)", (block_id, data))
    return block_id


def _insert_client_message(conn, session_id, branch_id, request_id, message: Message,
                           source: str, envelope_extra: dict | None = None) -> str:
    occ_id = new_id("occ")
    envelope = {"key_order": list(message.envelope.key_order),
                "content_form": message.envelope.content_form, **(envelope_extra or {})}
    conn.execute(
        "INSERT INTO occurrences VALUES (?, ?, ?, NULL, ?, 'both', ?, ?, NULL, ?, ?)",
        (occ_id, branch_id, _next_seq(conn, branch_id), message.role, source, request_id,
         json.dumps(envelope), chat.content_sha256(message)),
    )
    for idx, block in enumerate(message.blocks):
        meta: dict[str, Any] = {}
        if block.kind == "tool_call":
            meta = {"id": block.tool_call_id, "name": block.name}
        elif block.kind == "tool_result":
            meta = {"tool_call_id": block.tool_call_id}
        _insert_block(conn, occ_id, idx, block.kind, block.encoding, meta, block.to_bytes())
    issue_alias(conn, session_id, occ_id)
    search.index_occurrence(conn, occ_id)
    return occ_id


def _schema_key(req: ChatRequest) -> str:
    system = [m.raw_object for m in req.messages if m.role == "system"][:1]
    material = json.dumps([system, req.settings.get("tools")], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8", "surrogatepass")).hexdigest()


def ensure_session(conn: sqlite3.Connection, session_id: str, association: str) -> str:
    branch_id = branch_id_for(session_id)
    if conn.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone():
        return branch_id
    now = time.time()
    conn.execute("INSERT INTO sessions VALUES (?, ?, ?)", (session_id, now, association))
    conn.execute("INSERT INTO branches VALUES (?, ?, NULL, NULL, ?)", (branch_id, session_id, now))
    conn.execute("INSERT INTO branch_heads VALUES (?, NULL, NULL, 0)", (branch_id,))
    return branch_id


def _set_active(conn, branch_id: str, request_id: str | None) -> None:
    conn.execute(
        "UPDATE branch_heads SET active_request_id = ?, version = version + 1 WHERE branch_id = ?",
        (request_id, branch_id),
    )


def _attempt_has_output(conn, request_id: str) -> bool:
    """Whether any attempt produced output the client did not cancel."""
    return conn.execute(
        "SELECT 1 FROM generations g JOIN attempts a ON g.attempt_id = a.attempt_id"
        " WHERE a.request_id = ? AND NOT EXISTS (SELECT 1 FROM events e"
        " WHERE e.attempt_id = a.attempt_id AND e.kind = 'cancelled')",
        (request_id,),
    ).fetchone() is not None


def _superseded_by_later_turns(conn, branch_id: str, request_id: str) -> bool:
    """Whether occurrences from other requests follow this request's input."""
    last = conn.execute(
        "SELECT max(seq) FROM occurrences WHERE branch_id = ? AND request_id = ?"
        " AND source != 'generated'",
        (branch_id, request_id),
    ).fetchone()[0]
    if last is None:
        return False
    return conn.execute(
        "SELECT 1 FROM occurrences WHERE branch_id = ? AND seq > ? AND request_id IS NOT ?",
        (branch_id, last, request_id),
    ).fetchone() is not None


_STALE = ("This request repeats an earlier one, but the session has moved on since. "
          "Start a new session to continue from earlier history.")


def _request_completed(conn, request_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM events WHERE request_id = ? AND kind = 'turn_complete'", (request_id,)
    ).fetchone() is not None


def _start_attempt(conn, request_id: str) -> str:
    n = conn.execute(
        "SELECT coalesce(max(n), 0) + 1 FROM attempts WHERE request_id = ?", (request_id,)
    ).fetchone()[0]
    attempt_id = new_id("att")
    conn.execute("INSERT INTO attempts VALUES (?, ?, ?, ?)", (attempt_id, request_id, n, time.time()))
    _event(conn, request_id, attempt_id, "attempt_started", n=n)
    return attempt_id


def _addresses(conn, branch_id: str, cache) -> dict[str, tuple[int, str | None]]:
    if cache is not None:
        return cache.addresses(branch_id)
    return {occ: (seq, alias) for occ, seq, alias in conn.execute(
        "SELECT o.occ_id, o.seq, a.alias FROM occurrences o"
        " LEFT JOIN aliases a ON a.target_id = o.occ_id WHERE o.branch_id = ?", (branch_id,))}


def _upstream_body(conn, req: ChatRequest, archived: list[Archived], outcome,
                   client_occs: list[str] | None = None, branch_id: str | None = None,
                   cache=None) -> tuple[bytes, list]:
    """The model view before bounding: client message objects with internal
    occurrences spliced back in and flattened partials split into reasoning
    and text again (D10.3, D10.9), plus one ``ViewItem`` per upstream message.
    Positions come from the reconciliation alignment, so superseded partials
    and context versions cannot shift them."""
    from .view import ViewItem

    position = {occ_id: i for i, occ_id in enumerate(outcome.aligned)}
    by_id = {a.occ_id: a for a in archived}
    insertions: dict[int, list[dict]] = {}
    inserted_occs: dict[int, list[str]] = {}
    aligned_seen = 0
    for item in archived:
        if item.view == "internal":
            insertions.setdefault(aligned_seen, []).append(message_dict(conn, item.occ_id))
            inserted_occs.setdefault(aligned_seen, []).append(item.occ_id)
        elif item.occ_id in position:
            aligned_seen = position[item.occ_id] + 1
    replacements = {}
    for index, extent in outcome.partials:
        past = by_id[outcome.aligned[index]]
        sent = past.reasoning + past.text
        cut = min(extent, len(past.reasoning))
        original = req.messages[index].raw_object
        split = {k: v for k, v in original.items()}
        split["reasoning_content"] = sent[:cut]
        split["content"] = sent[cut:extent] if (sent[cut:extent] or "tool_calls" not in split) else None
        replacements[index] = split
    # Contracts §9: the pinned template renders reasoning for every earlier
    # assistant turn, so archived reasoning the client omitted is restored.
    for index, occ in enumerate(outcome.aligned):
        past = by_id.get(occ)
        original = req.messages[index].raw_object
        if (index not in replacements and past is not None and past.source == "generated"
                and past.reasoning and "reasoning_content" not in original):
            replacements[index] = {**original, "reasoning_content": past.reasoning}
    body = chat.render_upstream(req, insertions, replacements)

    occs = list(outcome.aligned) + list(client_occs or [])
    addresses = _addresses(conn, branch_id, cache) if branch_id else {}
    for occ in occs + [o for group in inserted_occs.values() for o in group]:
        if occ not in addresses:
            row = conn.execute(
                "SELECT o.seq, a.alias FROM occurrences o LEFT JOIN aliases a"
                " ON a.target_id = o.occ_id WHERE o.occ_id = ?", (occ,)).fetchone()
            if row:
                addresses[occ] = (row[0], row[1])
    items = []

    def item(message, occ):
        seq, alias = addresses.get(occ, (None, None))
        return ViewItem(message=message, occ_id=occ, seq=seq, alias=alias)

    for i, message in enumerate(req.messages):
        for occ, extra in zip(inserted_occs.get(i, []), insertions.get(i, [])):
            items.append(item(extra, occ))
        items.append(item(replacements.get(i, message.raw_object), occs[i] if i < len(occs) else None))
    n = len(req.messages)
    for occ, extra in zip(inserted_occs.get(n, []), insertions.get(n, [])):
        items.append(item(extra, occ))
    return body, items


def latest_view(conn: sqlite3.Connection, branch_id: str):
    """(view_id, n, ViewState) of the branch's newest view version, or (None, 0, default)."""
    from .view import ViewState

    row = conn.execute(
        "SELECT view_id, n, watermark_seq, collapse_seq, oversized FROM view_versions"
        " WHERE branch_id = ? ORDER BY n DESC LIMIT 1", (branch_id,)).fetchone()
    if row is None:
        return None, 0, ViewState()
    view_id, n, watermark, collapse, masks = row
    masks = json.loads(masks)
    if isinstance(masks, list):  # oversized only
        masks = {"oversized": masks, "kept": []}
    return view_id, n, ViewState(watermark, collapse, frozenset(masks["oversized"]),
                                 frozenset(masks["kept"]))


def record_view(conn: sqlite3.Connection, plan: Plan, state, *, policy_version: str,
                stub_format: str, budget: dict, cause: str) -> str:
    """Persist a new view version for the plan's branch (immutable, numbered)."""
    _, n, _ = latest_view(conn, plan.branch_id)
    view_id = new_id("view")
    conn.execute(
        "INSERT INTO view_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (view_id, plan.branch_id, n + 1, plan.request_id, policy_version, stub_format,
         state.watermark_seq, state.collapse_seq,
         json.dumps({"oversized": sorted(state.oversized), "kept": sorted(state.kept)}),
         json.dumps(budget), cause, time.time()))
    _event(conn, plan.request_id, plan.attempt_id, "view_version", view_id=view_id, n=n + 1,
           cause=cause, watermark_seq=state.watermark_seq, collapse_seq=state.collapse_seq)
    return view_id


# --- accept ------------------------------------------------------------------


def accept(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    association: str,
    req: ChatRequest,
    fingerprint: str,
    retry_hint: int | None,
    idem_key: str | None = None,
    live: set[str] | None = None,
    cache: BranchCache | None = None,
) -> Plan:
    """Accept or reject a request. ``live`` is the set of request IDs this
    process is currently relaying; the archive has one owning process, so an
    active marker outside it is stale (its terminal event could not be
    written) and is abandoned instead of blocking the session. On success the
    planned request is added to ``live`` inside this transaction."""
    branch_id = ensure_session(conn, session_id, association)
    active = conn.execute(
        "SELECT active_request_id FROM branch_heads WHERE branch_id = ?", (branch_id,)
    ).fetchone()[0]
    if active is not None and live is not None and active not in live:
        _abandon(conn, branch_id, active, "stale")
        active = None
    if active is not None:
        same = conn.execute(
            "SELECT fingerprint FROM requests WHERE request_id = ?", (active,)
        ).fetchone()[0] == fingerprint
        if same:
            raise Rejection(409, "request_in_progress",
                            "An identical request is still being answered in this session.")
        raise Rejection(409, "session_busy",
                        "Another request is in progress in this session; Palimnesis serializes "
                        "requests per session.")

    if idem_key is not None:
        plan = _keyed(conn, session_id, branch_id, req, fingerprint, idem_key, cache)
        if plan is not None:
            if live is not None and plan.replay is None:
                live.add(plan.request_id)
            return plan

    archived = load_archived(conn, branch_id, cache)
    outcome = reconcile(req.messages, archived)
    if isinstance(outcome, Divergence):
        raise Rejection(
            409, "history_divergence",
            f"Message {outcome.index} does not match this session's archived history "
            f"({outcome.reason}). Start a new session to continue from edited history.",
        )
    if isinstance(outcome, Prefix):
        plan = _retry(conn, session_id, branch_id, req, fingerprint, archived, outcome, cache)
    else:
        plan = _extend(conn, session_id, branch_id, req, fingerprint, retry_hint, idem_key,
                       archived, outcome, cache)
    if live is not None:
        live.add(plan.request_id)
    return plan


def _retry(conn, session_id, branch_id, req, fingerprint, archived, outcome: Prefix,
           cache=None) -> Plan:
    row = conn.execute(
        "SELECT request_id FROM requests WHERE branch_id = ? AND fingerprint = ?"
        " ORDER BY arrived_at DESC LIMIT 1",
        (branch_id, fingerprint),
    ).fetchone()
    if row is None or _superseded_by_later_turns(conn, branch_id, row[0]):
        raise Rejection(409, "history_divergence", _STALE)
    if _attempt_has_output(conn, row[0]):
        raise Rejection(
            409, "ambiguous_retry",
            "This request repeats one this session already answered (fully or partly), but "
            "the answer is missing from the resent history. Palimnesis will not generate it "
            "again silently.",
        )
    request_id = row[0]
    attempt_id = _start_attempt(conn, request_id)
    _set_active(conn, branch_id, request_id)
    return _plan(conn, session_id, branch_id, request_id, attempt_id, req, archived, outcome,
                 cache=cache)


def _keyed(conn, session_id, branch_id, req, fingerprint, idem_key, cache=None) -> Plan | None:
    row = conn.execute(
        "SELECT request_id, fingerprint, stream FROM idempotency_bindings"
        " WHERE session_id = ? AND branch_id = ? AND key = ?",
        (session_id, branch_id, idem_key),
    ).fetchone()
    if row is None:
        return None
    request_id, bound_fingerprint, bound_stream = row
    if bound_fingerprint != fingerprint or bool(bound_stream) != req.stream:
        raise Rejection(409, "idempotency_conflict",
                        "This Idempotency-Key is bound to a different request.")
    if _request_completed(conn, request_id):
        if req.stream:
            raise Rejection(409, "streaming_replay_unsupported",
                            "This streamed request already completed; replaying streams is "
                            "not supported yet.")
        status, headers, body = conn.execute(
            "SELECT status, headers, body FROM prepared_responses WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        return Plan(session_id, branch_id, request_id, "", b"", False,
                    replay={"status": status, "headers": json.loads(headers), "body": body})
    if _superseded_by_later_turns(conn, branch_id, request_id):
        raise Rejection(409, "history_divergence", _STALE)
    if _attempt_has_output(conn, request_id):
        raise Rejection(409, "ambiguous_retry",
                        "This keyed request produced partial output before failing.")
    archived = load_archived(conn, branch_id, cache)
    outcome = reconcile(req.messages, archived)
    if not isinstance(outcome, Prefix):
        raise Rejection(409, "idempotency_conflict",
                        "This Idempotency-Key's request no longer matches the session history.")
    attempt_id = _start_attempt(conn, request_id)
    _set_active(conn, branch_id, request_id)
    return _plan(conn, session_id, branch_id, request_id, attempt_id, req, archived, outcome,
                 cache=cache)


def _plan(conn, session_id, branch_id, request_id, attempt_id, req, archived, outcome, *,
          client_occs=None, cache=None) -> Plan:
    body, items = _upstream_body(conn, req, archived, outcome, client_occs, branch_id, cache)
    _, _, state = latest_view(conn, branch_id)
    return Plan(session_id, branch_id, request_id, attempt_id, body, req.stream,
                items=items, view_state=state)


def _extend(conn, session_id, branch_id, req, fingerprint, retry_hint, idem_key,
            archived, outcome: Extend, cache=None) -> Plan:
    first_request = not archived
    new = req.messages[outcome.matched:]
    if not first_request and any(m.role == "assistant" for m in new):
        index = outcome.matched + next(i for i, m in enumerate(new) if m.role == "assistant")
        raise Rejection(
            409, "history_divergence",
            f"Message {index} is an assistant turn Palimnesis did not generate. Start a new "
            "session to continue from edited history.",
        )
    previous = conn.execute(
        "SELECT envelope FROM requests WHERE branch_id = ? ORDER BY arrived_at DESC LIMIT 1",
        (branch_id,),
    ).fetchone()
    schema_key = _schema_key(req)
    schema_changed = previous is not None and json.loads(previous[0]).get("schema_key") != schema_key
    raw_id = put_raw(conn, session_id, branch_id, req.raw, schema_changed=schema_changed)
    request_id = new_id("req")
    tip = conn.execute(
        "SELECT occ_id FROM occurrences WHERE branch_id = ? ORDER BY seq DESC LIMIT 1", (branch_id,)
    ).fetchone()
    conn.execute(
        "INSERT INTO requests VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)",
        (request_id, session_id, branch_id, ENDPOINT_CHAT, raw_id, fingerprint, int(req.stream),
         idem_key, tip[0] if tip else None, retry_hint,
         json.dumps({"schema_key": schema_key, "top_level_order": list(req.top_level_order)}),
         time.time()),
    )
    for index in outcome.context_changed:
        previous_occ = outcome.aligned[index]
        occ_id = _insert_client_message(conn, session_id, branch_id, request_id,
                                        req.messages[index], "client",
                                        {"supersedes": previous_occ})
        _event(conn, request_id, None, "context_version", position=index, occ_id=occ_id,
               supersedes=previous_occ)
    for index, extent in outcome.partials:
        _event(conn, request_id, None, "partial_acknowledged",
               occ_id=outcome.aligned[index], extent=extent)
    for occ_id in outcome.superseded:
        already = conn.execute(
            "SELECT 1 FROM events WHERE kind = 'partial_superseded'"
            " AND json_extract(payload, '$.occ_id') = ?", (occ_id,)).fetchone()
        if not already:
            _event(conn, request_id, None, "partial_superseded", occ_id=occ_id)
    last_user = max((i for i, m in enumerate(req.messages) if m.role == "user"), default=-1)
    client_occs: list[str] = []
    for offset, message in enumerate(new):
        index = outcome.matched + offset
        source = "client_import" if first_request and message.role in ("assistant", "tool") and index < last_user else "client"
        client_occs.append(
            _insert_client_message(conn, session_id, branch_id, request_id, message, source))
    if idem_key is not None:
        conn.execute("INSERT INTO idempotency_bindings VALUES (?, ?, ?, ?, ?, ?)",
                     (session_id, branch_id, idem_key, request_id, fingerprint, int(req.stream)))
    _event(conn, request_id, None, "accepted_input", messages=len(req.messages),
           new=len(new), raw_id=raw_id)
    attempt_id = _start_attempt(conn, request_id)
    _set_active(conn, branch_id, request_id)
    return _plan(conn, session_id, branch_id, request_id, attempt_id, req, archived, outcome,
                 client_occs=client_occs, cache=cache)


# --- generation --------------------------------------------------------------


def deltas(chunk: dict) -> list[tuple]:
    """(kind, key, text, meta) parts of one Chat Completions stream chunk."""
    out: list[tuple] = []
    for choice in chunk.get("choices") or []:
        delta = choice.get("delta") or choice.get("message") or {}
        if delta.get("reasoning_content"):
            out.append(("reasoning", "reasoning", delta["reasoning_content"], {}))
        if delta.get("content"):
            out.append(("text", "text", delta["content"], {}))
        for i, part in enumerate(delta.get("tool_calls") or []):
            function = part.get("function") or {}
            index = part.get("index", i)
            out.append(("tool_call", ("tool", index), function.get("arguments") or "",
                        {"id": part.get("id"), "name": function.get("name")}))
    return out


def _ensure_occurrence(conn, gen: Generation) -> None:
    if gen.occ_id is not None:
        return
    plan = gen.plan
    gen.occ_id, gen.generation_id = new_id("occ"), new_id("gen")
    conn.execute("INSERT INTO generations VALUES (?, ?, NULL, 1)", (gen.generation_id, plan.attempt_id))
    conn.execute(
        "INSERT INTO occurrences VALUES (?, ?, ?, NULL, 'assistant', 'both', 'generated', ?, ?, ?, '')",
        (gen.occ_id, plan.branch_id, _next_seq(conn, plan.branch_id), plan.request_id,
         gen.generation_id, json.dumps({})),
    )
    issue_alias(conn, plan.session_id, gen.occ_id)


def _merge_runs(parts: list[tuple]) -> list[tuple]:
    """Join consecutive parts of the same block so a batch writes one segment each."""
    merged: list[tuple] = []
    for kind, key, text, meta in parts:
        if merged and merged[-1][1] == key and not (meta.get("id") or meta.get("name")):
            k, _, prev, m = merged[-1]
            merged[-1] = (k, key, prev + text, m)
        else:
            merged.append((kind, key, text, meta))
    return merged


def commit_batch(conn: sqlite3.Connection, gen: Generation, parts: list[tuple],
                 forwarded_before: int) -> None:
    """Archive one batch of generated parts before it is forwarded."""
    plan = gen.plan
    if parts:
        _ensure_occurrence(conn, gen)
    for kind, key, text, meta in _merge_runs(parts):
        block_id = gen.blocks.get(key)
        if block_id is None:
            if kind == "tool_call" and not (meta.get("id") and meta.get("name")):
                raise ValueError("tool call delta without id and name at its start")
            block_meta = {"id": meta["id"], "name": meta["name"]} if kind == "tool_call" else {}
            # Generated text can carry lone surrogates (JSON \ud83d escapes split by
            # tokenization); WTF-8 is a superset of UTF-8, so tag every generated block.
            block_id = _insert_block(conn, gen.occ_id, len(gen.blocks), kind, "wtf-8", block_meta, None)
            gen.blocks[key] = block_id
            gen.next_segment[block_id] = 0
        elif kind == "tool_call" and meta.get("name"):
            raise ValueError("tool name continued in a later delta; not supported")
        if text:
            seq = gen.next_segment[block_id]
            conn.execute("INSERT INTO segments VALUES (?, ?, ?)",
                         (block_id, seq, text.encode("utf-8", "surrogatepass")))
            gen.next_segment[block_id] = seq + 1
    # Each batch commit also records how far delivery got before it.
    if not gen.delivery_started:
        _event(conn, plan.request_id, plan.attempt_id, "delivery_started", bytes_forwarded=0)
        gen.delivery_started = True
    elif forwarded_before > gen.progress_recorded:
        _event(conn, plan.request_id, plan.attempt_id, "delivery_progress",
               bytes_forwarded=forwarded_before)
        gen.progress_recorded = forwarded_before


def finish_attempt(conn: sqlite3.Connection, gen: Generation, kind: str, **payload) -> None:
    """Record the attempt's terminal event and free the branch."""
    plan = gen.plan
    if kind == "turn_complete":
        _ensure_occurrence(conn, gen)
        payload["occ_id"] = gen.occ_id
    _event(conn, plan.request_id, plan.attempt_id, kind, **payload)
    _set_active(conn, plan.branch_id, None)
    if gen.occ_id is not None:
        search.index_occurrence(conn, gen.occ_id)
    gen.finished = True


def interrupt(conn: sqlite3.Connection, gen: Generation) -> None:
    """Record a client disconnect or unexpected failure. Runs on the single
    writer, after any terminal write already queued, so it never adds a
    second terminal event."""
    terminal = conn.execute(
        "SELECT 1 FROM events WHERE attempt_id = ? AND kind IN (%s)"
        % ",".join("?" * len(TERMINAL_EVENTS)),
        (gen.plan.attempt_id, *TERMINAL_EVENTS),
    ).fetchone()
    if terminal:
        record_delivery(conn, gen.plan, "delivery_failed", bytes_forwarded=gen.forwarded)
    else:
        finish_attempt(conn, gen, "cancelled", forwarded=gen.forwarded)


def prepare_response(conn: sqlite3.Connection, gen: Generation, status: int,
                     headers: list[tuple[str, str]], body: bytes) -> None:
    conn.execute("INSERT INTO prepared_responses VALUES (?, ?, ?, ?)",
                 (gen.plan.request_id, status, json.dumps(headers), body))
    _event(conn, gen.plan.request_id, gen.plan.attempt_id, "response_prepared", status=status)


def record_delivery(conn: sqlite3.Connection, plan: Plan, kind: str, **payload) -> None:
    _event(conn, plan.request_id, plan.attempt_id, kind, **payload)


def recover(conn: sqlite3.Connection) -> int:
    """Mark attempts left active by a crash as abandoned; returns how many."""
    stale = conn.execute(
        "SELECT branch_id, active_request_id FROM branch_heads WHERE active_request_id IS NOT NULL"
    ).fetchall()
    for branch_id, request_id in stale:
        _abandon(conn, branch_id, request_id, "restart")
    return len(stale)


def _abandon(conn, branch_id: str, request_id: str, reason: str) -> None:
    attempt = conn.execute(
        "SELECT attempt_id FROM attempts WHERE request_id = ? ORDER BY n DESC LIMIT 1",
        (request_id,),
    ).fetchone()
    _event(conn, request_id, attempt[0] if attempt else None, "attempt_abandoned", reason=reason)
    _set_active(conn, branch_id, None)
