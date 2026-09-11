import asyncio
from dataclasses import dataclass, field


@dataclass(eq=False)
class Subscriber:
    queue: asyncio.Queue
    overflow: asyncio.Event = field(default_factory=asyncio.Event)


class Broadcaster:
    def __init__(self, queue_size: int):
        self.queue_size = queue_size
        self.subscribers: dict[str, set[Subscriber]] = {}

    def subscribe(self, session_id: str) -> Subscriber:
        subscriber = Subscriber(asyncio.Queue(maxsize=self.queue_size))
        self.subscribers.setdefault(session_id, set()).add(subscriber)
        return subscriber

    def remove(self, session_id: str, subscriber: Subscriber):
        members = self.subscribers.get(session_id, set())
        members.discard(subscriber)
        if not members:
            self.subscribers.pop(session_id, None)

    def publish(self, session_id: str, message: dict):
        for subscriber in tuple(self.subscribers.get(session_id, ())):
            try:
                subscriber.queue.put_nowait(message)
            except asyncio.QueueFull:
                subscriber.overflow.set()
                self.remove(session_id, subscriber)
