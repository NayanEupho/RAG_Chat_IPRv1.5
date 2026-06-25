from __future__ import annotations

import json
import queue
import threading
from typing import Any


class AdminEventHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue[dict[str, Any]]] = []

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._lock:
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers = [item for item in self._subscribers if item is not subscriber]

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                pass

    def sse_frame(self, event: dict[str, Any]) -> str:
        event_type = str(event.get("type", "message"))
        return f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


event_hub = AdminEventHub()

