"""Build archives at the store seam (palimnesis.ledger on a real Store) for projection tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from palimnesis import ledger
from palimnesis.chat import parse
from palimnesis.fingerprint import fingerprint_v1
from palimnesis.store import Store

TOKENS = ("<|im_start|>", "<|im_end|>")


def words(text: str) -> int:
    return len(text.split())


class Archive:
    """One session's history, written through the ledger exactly as the relay writes it."""

    def __init__(self, path: Path, session: str = "s1") -> None:
        self.path = path
        self.session = session
        self.store = Store.open(path)
        self.messages: list[dict] = []

    def close(self) -> None:
        self.store.close()

    def _write(self, fn):
        return asyncio.run(self.store.write(fn))

    def request(self, *new: dict, reply: list[tuple] | None = None,
                end: str | None = "turn_complete") -> ledger.Generation:
        """Send the history plus ``new`` messages; generate ``reply`` parts
        (``ledger.deltas`` tuples); end the attempt with ``end`` (None: leave it running)."""
        self.messages = [*self.messages, *new]
        req = parse(json.dumps({"model": "m", "stream": True, "messages": self.messages}).encode())
        fp = fingerprint_v1(ledger.ENDPOINT_CHAT, self.session, ledger.branch_id_for(self.session),
                            json.loads(req.raw))
        plan = self._write(lambda c: ledger.accept(
            c, session_id=self.session, association="path", req=req, fingerprint=fp,
            retry_hint=None, live=set()))
        gen = ledger.Generation(plan)
        if reply:
            self._write(lambda c: ledger.commit_batch(c, gen, reply, 0))
        if end == "turn_complete":
            self._write(lambda c: ledger.finish_attempt(c, gen, "turn_complete",
                                                        finish_reason="stop"))
        elif end == "cancelled":
            self._write(lambda c: ledger.interrupt(c, gen))
        elif end == "attempt_failed":
            self._write(lambda c: ledger.finish_attempt(c, gen, "attempt_failed", reason="x"))
        if reply and end == "turn_complete":  # what the client saw and will resend
            self.messages.append(assistant_message(reply))
        return gen

    def recover(self) -> int:
        return self._write(ledger.recover)


def text(t: str) -> tuple:
    return ("text", "text", t, {})


def reasoning(t: str) -> tuple:
    return ("reasoning", "reasoning", t, {})


def call(i: int, call_id: str, name: str, arguments: str) -> tuple:
    return ("tool_call", ("tool", i), arguments, {"id": call_id, "name": name})


def assistant_message(parts: list[tuple]) -> dict:
    content = "".join(t for kind, _, t, _ in parts if kind == "text")
    calls = [{"id": m["id"], "type": "function", "function": {"name": m["name"], "arguments": t}}
             for kind, _, t, m in parts if kind == "tool_call"]
    message: dict = {"role": "assistant", "content": content or None}
    if calls:
        message["tool_calls"] = calls
    return message


def user(t: str) -> dict:
    return {"role": "user", "content": t}


def tool(call_id: str, t: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": t}


def tree(directory: Path) -> dict[str, bytes]:
    """Every file under ``directory`` by POSIX relative path."""
    return {p.relative_to(directory).as_posix(): p.read_bytes()
            for p in sorted(directory.rglob("*")) if p.is_file()}
