"""Einfacher In-Process-Pub/Sub für Live-Updates (WebSocket)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any

log = logging.getLogger(__name__)


class Subscription:
    def __init__(self, bus: Bus, maxsize: int = 2000) -> None:
        self._bus = bus
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)
        self.topics: set[str] = set()
        self.dropped = 0

    def add(self, topic: str) -> None:
        self.topics.add(topic)
        self._bus._index.setdefault(topic, set()).add(self)

    def remove(self, topic: str) -> None:
        self.topics.discard(topic)
        subs = self._bus._index.get(topic)
        if subs is not None:
            subs.discard(self)
            if not subs:
                del self._bus._index[topic]

    def close(self) -> None:
        for t in list(self.topics):
            self.remove(t)

    def _offer(self, event: dict[str, Any]) -> None:
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1


class Bus:
    def __init__(self) -> None:
        self._index: dict[str, set[Subscription]] = {}

    def subscribe(self, topics: Iterable[str] = ()) -> Subscription:
        sub = Subscription(self)
        for t in topics:
            sub.add(t)
        return sub

    def publish(self, topics: Iterable[str], type_: str, data: Any) -> None:
        delivered: set[Subscription] = set()
        for topic in topics:
            for sub in self._index.get(topic, ()):
                if sub in delivered:
                    continue
                delivered.add(sub)
                sub._offer({"type": type_, "topic": topic, "data": data})
