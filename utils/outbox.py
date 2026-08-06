"""Runtime worker for the persistent XMPP outbound queue."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import time
from typing import Any

from bot.room_state import JOINED_ROOMS

log = logging.getLogger(__name__)


def message_dedupe_key(category: str, destination: str, body: str) -> str:
    """Return a stable, privacy-preserving dedupe key."""
    digest = hashlib.sha256(
        f"{category}\0{destination}\0{body}".encode("utf-8")
    ).hexdigest()
    return f"{category}:{digest}"


async def durable_send(
    bot: Any,
    message: Any,
    *,
    category: str,
    dedupe_key: str | None = None,
    max_attempts: int | None = None,
) -> bool:
    """Send through the bot and request durable fallback when supported.

    Lightweight test doubles and third-party integrations may still expose the
    pre-outbox ``_safe_send_message(message)`` signature. Fall back to it only
    when keyword arguments are unsupported; production EnvsBot keeps the
    durable path.
    """
    safe_send = getattr(bot, "_safe_send_message", None)
    if not callable(safe_send):
        result = message.send()
        if inspect.isawaitable(result):
            result = await result
        return result is not False
    try:
        result = safe_send(
            message,
            persist=True,
            category=category,
            dedupe_key=dedupe_key,
            max_attempts=max_attempts,
        )
        if inspect.isawaitable(result):
            result = await result
    except TypeError as exc:
        text = str(exc)
        if "unexpected keyword" not in text and "keyword argument" not in text:
            raise
        result = safe_send(message)
        if inspect.isawaitable(result):
            result = await result
    return result is not False


class PersistentOutbox:
    """Queue failed or deferred messages and retry them after reconnects."""

    def __init__(self, bot: Any):
        self.bot = bot
        self.store = None
        self.task: asyncio.Task[Any] | None = None
        self.wakeup = asyncio.Event()
        self.stop_event = asyncio.Event()
        self.last_delivery_at = 0
        self.last_error: str | None = None
        self.delivered = 0
        self.failed_attempts = 0
        self.dead_letters = 0

    @property
    def enabled(self) -> bool:
        config = getattr(self.bot, "config", {}) or {}
        return bool(config.get("outbox_enabled", True))

    async def start(self, store: Any) -> None:
        self.store = store
        self.stop_event = asyncio.Event()
        self.wakeup = asyncio.Event()
        # Every inflight row belongs to a previous worker at startup. Recover
        # all of them immediately so a fast process restart cannot strand a row.
        await store.recover_inflight(older_than_seconds=0)
        if not self.enabled or self.task is not None:
            return
        supervisor = getattr(self.bot, "tasks", None)
        if supervisor is not None:
            self.task = supervisor.create(
                "_runtime",
                self._run(),
                name="persistent-outbox",
            )
        else:
            self.task = asyncio.create_task(
                self._run(),
                name="persistent-outbox",
            )

    async def stop(self, *, timeout: float = 10.0) -> None:
        self.stop_event.set()
        self.wakeup.set()
        task = self.task
        self.task = None
        if task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=max(0.1, timeout))
        except asyncio.TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        except asyncio.CancelledError:
            pass

    async def enqueue(
        self,
        *,
        destination: str,
        body: str,
        message_type: str,
        category: str = "message",
        dedupe_key: str | None = None,
        max_attempts: int | None = None,
        available_at: int | None = None,
    ) -> int | None:
        if not self.enabled or self.store is None:
            return None
        config = getattr(self.bot, "config", {}) or {}
        key = dedupe_key or message_dedupe_key(category, destination, body)
        message_id = await self.store.enqueue(
            destination=destination,
            body=body,
            message_type=message_type,
            category=category,
            dedupe_key=key,
            max_attempts=(
                int(max_attempts)
                if max_attempts is not None
                else int(config.get("outbox_max_attempts", 12) or 12)
            ),
            available_at=available_at,
        )
        self.wakeup.set()
        return message_id

    async def enqueue_message(
        self,
        message: Any,
        *,
        category: str = "message",
        dedupe_key: str | None = None,
        max_attempts: int | None = None,
    ) -> int | None:
        try:
            destination = str(message["to"])
            body = str(message["body"])
            message_type = str(message.get("type", "chat") or "chat")
        except Exception:
            log.exception("[OUTBOX] Could not serialize outbound message")
            return None
        return await self.enqueue(
            destination=destination,
            body=body,
            message_type=message_type,
            category=category,
            dedupe_key=dedupe_key,
            max_attempts=max_attempts,
        )

    def _room_ready(self, destination: str, message_type: str) -> bool:
        if message_type != "groupchat":
            return True
        room = str(destination).split("/", 1)[0]
        return room in JOINED_ROOMS

    def _retry_delay(self, attempts: int) -> int:
        config = getattr(self.bot, "config", {}) or {}
        initial = max(1, int(config.get("outbox_retry_initial_seconds", 30) or 30))
        maximum = max(initial, int(config.get("outbox_retry_max_seconds", 1800) or 1800))
        return min(maximum, initial * (2 ** max(0, int(attempts))))

    async def _send_one(self, queued: Any) -> None:
        if not self._room_ready(queued.destination, queued.message_type):
            await self.store.defer(
                queued.id,
                retry_delay_seconds=self._retry_delay(queued.attempts),
                reason="destination room is not joined",
            )
            return

        try:
            message = self.bot.make_message(
                mto=queued.destination,
                mbody=queued.body,
                mtype=queued.message_type,
            )
            sent = await self.bot._safe_send_message(message, persist=False)
            if sent is False:
                raise RuntimeError("Slixmpp did not accept the stanza")
        except Exception as exc:
            self.failed_attempts += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            dead = await self.store.mark_failed(
                queued,
                exc,
                retry_delay_seconds=self._retry_delay(queued.attempts),
            )
            if dead:
                self.dead_letters += 1
                log.error(
                    "[OUTBOX] Message moved to dead letter queue: id=%s category=%s destination=%s",
                    queued.id,
                    queued.category,
                    queued.destination,
                )
            return

        await self.store.mark_sent(queued.id)
        self.delivered += 1
        self.last_delivery_at = int(time.time())
        self.last_error = None

    async def run_once(self) -> int:
        if not self.enabled or self.store is None:
            return 0
        config = getattr(self.bot, "config", {}) or {}
        batch_size = max(1, int(config.get("outbox_batch_size", 20) or 20))
        queued = await self.store.claim_due(limit=batch_size)
        for message in queued:
            if self.stop_event.is_set():
                break
            await self._send_one(message)
        return len(queued)

    async def _run(self) -> None:
        config = getattr(self.bot, "config", {}) or {}
        poll_seconds = max(1.0, float(config.get("outbox_poll_seconds", 5) or 5))
        try:
            while not self.stop_event.is_set():
                processed = 0
                try:
                    processed = await self.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    log.exception("[OUTBOX] Worker iteration failed")
                if processed:
                    await asyncio.sleep(0)
                    continue
                self.wakeup.clear()
                try:
                    await asyncio.wait_for(self.wakeup.wait(), timeout=poll_seconds)
                except asyncio.TimeoutError:
                    pass
        finally:
            self.wakeup.clear()

    async def runtime_state(self) -> dict[str, Any]:
        counts = (
            await self.store.counts()
            if self.store is not None
            else {"pending": 0, "inflight": 0, "dead": 0, "total": 0}
        )
        oldest_age = await self.store.oldest_pending_age() if self.store is not None else 0
        return {
            **counts,
            "oldest_pending_age_seconds": oldest_age,
            "delivered_since_start": self.delivered,
            "failed_attempts_since_start": self.failed_attempts,
            "last_delivery_at": self.last_delivery_at,
            "last_error": self.last_error,
            "worker_running": bool(self.task and not self.task.done()),
        }
