"""Do not release an ordering lock while its SQLite thread is still committing."""

import asyncio
from functools import wraps

from anyio import CancelScope


def finish_on_cancel(method):
    @wraps(method)
    async def wrapped(*args, **kwargs):
        task = asyncio.create_task(method(*args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            with CancelScope(shield=True):
                await task
            raise

    return wrapped


@finish_on_cancel
async def blocking(method, *args):
    return await asyncio.to_thread(method, *args)
