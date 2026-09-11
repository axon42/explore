import asyncio

from anyio import CancelScope

from .broadcast import Broadcaster
from .concurrency import finish_on_cancel
from .storage import Storage


class Service:
    """One process: one ordering lock covers commits, snapshots and subscription.

    SQLite runs off-loop. A subscriber is registered under the same lock as its
    snapshot, so no committed update can slip between those two operations.
    """

    def __init__(self, storage: Storage, broadcaster: Broadcaster):
        self.storage, self.broadcaster = storage, broadcaster
        self.lock = asyncio.Lock()
        self.on_final = lambda session_id: None

    @finish_on_cancel
    async def read(self, method, *args):
        with CancelScope(shield=True):
            async with self.lock:
                return await asyncio.to_thread(method, *args)

    @finish_on_cancel
    async def subscribe(self, session_id):
        with CancelScope(shield=True):
            async with self.lock:
                snapshot = await asyncio.to_thread(self.storage.snapshot, session_id)
                subscriber = self.broadcaster.subscribe(session_id)
                subscriber.queue.put_nowait(snapshot)
                return subscriber

    @finish_on_cancel
    async def ingest(self, session_id, event):
        with CancelScope(shield=True):
            async with self.lock:
                ack, change = await asyncio.to_thread(self.storage.ingest, session_id, event)
                if change:
                    self.broadcaster.publish(session_id, change)
                    if event.is_final:
                        self.on_final(session_id)
                return ack

    @finish_on_cancel
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
