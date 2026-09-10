import asyncio

from anyio import CancelScope

from .broadcast import Broadcaster
from .storage import Storage


class Service:
    """One process: one ordering lock covers commits, snapshots and subscription.

    SQLite runs off-loop. A subscriber is registered under the same lock as its
    snapshot, so no committed update can slip between those two operations.
    """

    def __init__(self, storage: Storage, broadcaster: Broadcaster):
        self.storage, self.broadcaster = storage, broadcaster
        self.lock = asyncio.Lock()

    async def read(self, method, *args):
        with CancelScope(shield=True):
            async with self.lock:
                return await asyncio.to_thread(method, *args)

    async def subscribe(self, session_id):
        with CancelScope(shield=True):
            async with self.lock:
                snapshot = await asyncio.to_thread(self.storage.snapshot, session_id)
                subscriber = self.broadcaster.subscribe(session_id)
                subscriber.queue.put_nowait(snapshot)
                return subscriber

    async def ingest(self, session_id, event):
        with CancelScope(shield=True):
            async with self.lock:
                ack, change = await asyncio.to_thread(self.storage.ingest, session_id, event)
                if change:
                    self.broadcaster.publish(session_id, change)
                return ack

    async def stop(self, session_id):
        with CancelScope(shield=True):
            async with self.lock:
                session, changed = await asyncio.to_thread(self.storage.stop, session_id)
                if changed:
                    self.broadcaster.publish(
                        session_id,
                        {
                            "type": "status",
                            "version": session["version"],
                            "session": session,
                        },
                    )
                return session
