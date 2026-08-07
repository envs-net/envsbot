"""Async locking helpers for the shared SQLite connection."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from utils.performance import observe


class AsyncRLock:
    """Small task-reentrant asyncio lock.

    SQLite uses one connection for the runtime stores.  Operations that already
    own the database transaction lock must therefore be able to call helpers
    which acquire the same lock again without deadlocking the current task.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None
        self._depth = 0

    async def acquire(self) -> bool:
        task = asyncio.current_task()
        if task is not None and task is self._owner:
            self._depth += 1
            return True
        started = time.perf_counter()
        await self._lock.acquire()
        observe("db_lock_wait", time.perf_counter() - started)
        self._owner = task
        self._depth = 1
        return True

    def release(self) -> None:
        task = asyncio.current_task()
        if self._owner is not task:
            raise RuntimeError("AsyncRLock released by non-owner task")
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            self._lock.release()

    async def __aenter__(self) -> AsyncRLock:
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.release()
