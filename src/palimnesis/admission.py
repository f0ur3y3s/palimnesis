"""Proxy admission (O4; Phase 4B S6; contracts §5, §8).

``Admission`` is one FIFO in front of the upstream's slots. A request reserves its
place before acceptance (``reserve``), so a full queue is refused before anything is
archived (429), and takes a slot after acceptance (``Ticket.acquire``), holding it across
every upstream call of its response: the notes refresh, hidden continuations and the
answer. Releasing wakes the next waiter. A waiter cancelled by a client disconnect or
by the deadline leaves the queue and is never dispatched.

The slot count comes from the upstream's facts (Strata's ``/props`` ``total_slots``; one
on pythia, D83), read on every decision, so a restart with more slots needs no new code.

``StreamGate`` wraps a streaming response's ``send``. If no response has started within
``H`` of arrival, it sends the 200 headers itself; from then on, whenever ``K`` passes with
nothing sent, it sends the client protocol's keepalive (``Emitter.keepalive``). A later
response start from the pipeline is absorbed; an error response that arrives after the
gate started the stream becomes the protocol's in-stream error event instead
(``Emitter.error_body``). Keepalives are not progress and never extend the deadline.
"""

from __future__ import annotations

import collections
from collections.abc import Callable
from typing import Any

import anyio

SSE_HEADERS = [(b"content-type", b"text/event-stream"), (b"cache-control", b"no-cache"),
               (b"x-should-retry", b"false")]


class QueueFull(Exception):
    """Every slot is busy and ``capacity`` requests already wait (contracts §5: 429)."""


class Ticket:
    def __init__(self, admission: "Admission") -> None:
        self._admission = admission
        self.granted = False
        self.done = False
        self._event = anyio.Event()

    async def acquire(self) -> None:
        """Wait, first in first out, for a slot. Cancellation leaves the queue."""
        a = self._admission
        try:
            while not a._grant(self):
                self._event = anyio.Event()
                await self._event.wait()
        except BaseException:
            self.release()
            raise

    def release(self) -> None:
        """Give the slot back (or the place in the queue); idempotent."""
        if self.done:
            return
        self.done = True
        a = self._admission
        if self.granted:
            a.active -= 1
        elif self in a.waiting:
            a.waiting.remove(self)
        a._wake()


class Admission:
    def __init__(self, capacity: int, slots: Callable[[], int]) -> None:
        self.capacity = capacity
        self._slots = slots
        self.active = 0
        self.waiting: collections.deque[Ticket] = collections.deque()

    @property
    def slots(self) -> int:
        try:
            return max(1, int(self._slots() or 1))
        except Exception:  # noqa: BLE001 - unknown facts mean one slot
            return 1

    def reserve(self) -> Ticket:
        if self.active + len(self.waiting) >= self.slots + self.capacity:
            raise QueueFull()
        ticket = Ticket(self)
        self.waiting.append(ticket)
        return ticket

    def _grant(self, ticket: Ticket) -> bool:
        if self.waiting and self.waiting[0] is ticket and self.active < self.slots:
            self.waiting.popleft()
            self.active += 1
            ticket.granted = True
            self._wake()
            return True
        return False

    def _wake(self) -> None:
        if self.waiting:
            self.waiting[0]._event.set()


class StreamGate:
    def __init__(self, send, emitter: Any, *, arrival: float, header_wait: float,
                 keepalive: float) -> None:
        self._send = send
        self.emitter = emitter
        self.arrival = arrival
        self.header_wait = header_wait
        self.keepalive_every = keepalive
        self.started = False  # a response start reached the client
        self.early = False  # the gate sent the headers itself
        self.ended = False
        self._last = arrival
        self._lock = anyio.Lock()
        self._converting = False
        self._error = b""

    async def send(self, message: dict) -> None:
        async with self._lock:
            kind = message["type"]
            if kind == "http.response.start":
                if self.early:
                    self._converting = message["status"] != 200
                    return
                self.started = True
            elif kind == "http.response.body" and self._converting:
                self._error += message.get("body", b"")
                if message.get("more_body", False):
                    return
                self._converting = False
                await self._send({"type": "http.response.body", "more_body": True,
                                  "body": self.emitter.error_body(self._error)})
                message = {"type": "http.response.body", "body": b"", "more_body": False}
            await self._send(message)
            self._last = anyio.current_time()
            if kind == "http.response.body" and not message.get("more_body", False):
                self.ended = True

    async def watch(self) -> None:
        """Headers by ``H``, then a keepalive whenever ``K`` passes quietly; until the end."""
        await anyio.sleep_until(self.arrival + self.header_wait)
        while not self.ended:
            async with self._lock:
                if self.ended:
                    return
                now = anyio.current_time()
                if not self.started:
                    await self._send({"type": "http.response.start", "status": 200,
                                      "headers": list(SSE_HEADERS)})
                    self.started = self.early = True
                    self._last = now
                elif now - self._last >= self.keepalive_every:
                    await self._send({"type": "http.response.body", "more_body": True,
                                      "body": self.emitter.keepalive()})
                    self._last = now
                wake = self._last + self.keepalive_every
            await anyio.sleep_until(wake)
