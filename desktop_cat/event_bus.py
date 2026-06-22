from collections import defaultdict
from typing import Any, Callable


class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        self._queue: list[tuple[str, Any]] = []

    def subscribe(self, event_type: str, callback: Callable) -> None:
        self._subscribers[event_type].append(callback)

    def publish(self, event_type: str, data: Any = None) -> None:
        self._queue.append((event_type, data))

    def tick(self) -> None:
        events, self._queue = self._queue, []
        for event_type, data in events:
            for callback in self._subscribers[event_type]:
                callback(data)
