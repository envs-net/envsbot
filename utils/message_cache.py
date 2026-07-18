"""Shared, persistent recent-message cache and XMPP reply helpers."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from contextlib import suppress
from typing import Any

log = logging.getLogger(__name__)

_BATCH_DELAY_SECONDS = 0.1
_STOP = object()

# Stanza-processing guards remain namespaced because they prevent duplicate
# handlers, not duplicate message storage.
_PROCESSED_STANZAS: dict[str, set[str]] = defaultdict(set)
_PROCESSED_STANZA_ORDER: dict[str, deque[str]] = defaultdict(
    lambda: deque(maxlen=10000)
)


def paginate_items(items: list[Any], page: int, page_size: int):
    """Paginate a list and clamp page into a valid range."""
    total = len(items)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end], page, total_pages, total


def get_stanza_id(msg) -> str | None:
    """Extract a stable message ID from an XMPP stanza."""
    try:
        stanza_id = msg.get("stanza_id")
        if stanza_id:
            value = stanza_id.get("id")
            if value:
                return str(value)
    except Exception as exc:
        log.debug("[MESSAGE_CACHE] Could not read stanza_id: %s", exc)

    try:
        msg_id = msg.get("id")
        if msg_id:
            return str(msg_id)
    except Exception as exc:
        log.debug("[MESSAGE_CACHE] Could not read message id: %s", exc)

    return None


def remember_stanza(namespace: str, stanza_id: str | None) -> bool:
    """Return False when a stanza was already handled in this namespace."""
    if not stanza_id:
        return True

    processed = _PROCESSED_STANZAS[namespace]
    order = _PROCESSED_STANZA_ORDER[namespace]
    if stanza_id in processed:
        return False

    if len(order) == order.maxlen:
        old = order.popleft()
        processed.discard(old)

    processed.add(stanza_id)
    order.append(stanza_id)
    return True


def get_reply_target(msg) -> str | None:
    """Return the XEP-0461 target ID of a reply stanza."""
    try:
        if "reply" in msg:
            reply = msg.get("reply")
            if reply:
                value = reply.get("id")
                if value:
                    return str(value)
    except Exception as exc:
        log.debug("[MESSAGE_CACHE] Could not read reply target: %s", exc)
    return None


def extract_reply_quote(body: str) -> str | None:
    """Extract the leading plain-text XEP-0461 fallback quote."""
    if not body:
        return None

    quoted_lines: list[str] = []
    for line in body.strip().splitlines():
        if not line.startswith(">"):
            break
        quoted_lines.append(line[2:] if len(line) > 1 else "")

    text = "\n".join(quoted_lines).strip()
    return text or None


def conversation_key(
    msg,
    *,
    is_room: bool | None = None,
    joined_rooms: Mapping[str, Any] | set[str] | None = None,
) -> str | None:
    """Return a stable, privacy-safe key for a message conversation.

    Public MUC messages use the bare room JID. Direct chats use the sender's
    bare JID. MUC private messages use the full occupant JID so private
    conversations with different occupants in one room never share history.
    """
    try:
        sender = msg["from"]
        bare = str(sender.bare)
        resource = str(getattr(sender, "resource", "") or "")
        message_type = str(msg.get("type") or "")
    except Exception as exc:
        log.debug("[MESSAGE_CACHE] Could not resolve conversation: %s", exc)
        return None

    if is_room is True or message_type == "groupchat":
        return bare

    known_rooms = joined_rooms or set()
    try:
        is_muc_pm = bare in known_rooms and bool(resource)
    except Exception:
        is_muc_pm = False

    if is_muc_pm:
        return f"mucpm:{bare}/{resource}"
    return bare


def _safe_sender_nick(msg, is_room: bool) -> str | None:
    try:
        if is_room:
            value = msg.get("mucnick") or msg["from"].resource
        else:
            value = msg["from"].resource
        return str(value) if value else None
    except Exception:
        return None


def _safe_sender_jid(msg) -> str | None:
    try:
        return str(msg["from"])
    except Exception:
        return None


class MessageCache:
    """One bounded recent-message cache shared by every plugin.

    Reads are served from RAM. Writes are queued and committed to the existing
    SQLite database in small batches. The queue is drained during normal bot
    shutdown, so cached messages remain available after a restart.
    """

    def __init__(self, max_messages: int = 100):
        self.max_messages = max(1, int(max_messages))
        self._messages: dict[str, deque[dict[str, Any]]] = {}
        self._by_stanza_id: dict[str, dict[str, dict[str, Any]]] = {}
        self._store = None
        self._mutation_lock = asyncio.Lock()
        self._queue: asyncio.Queue[object] = asyncio.Queue()
        self._writer_task: asyncio.Task | None = None
        self._started = False
        self._closing = False

    async def start(self, store) -> None:
        """Load persisted entries and start the asynchronous writer."""
        if self._started:
            return

        self._messages.clear()
        self._by_stanza_id.clear()
        self._store = store
        prune_all = getattr(store, "prune_all", None)
        if callable(prune_all):
            await prune_all(self.max_messages)
        rows = await store.load_recent(self.max_messages)
        for row in rows:
            entry = {
                "cache_key": str(row["cache_key"]),
                "conversation": str(row["conversation"]),
                "stanza_id": row.get("stanza_id"),
                "nick": row.get("sender_nick"),
                "sender_jid": row.get("sender_jid"),
                "body": str(row.get("body") or ""),
                "message_type": str(row.get("message_type") or "unknown"),
                "received_at": int(row.get("received_at") or 0),
                "ts": int(row.get("received_at") or 0),
                "db_id": int(row.get("id") or 0),
            }
            self._append_to_memory(entry)

        self._started = True
        self._closing = False
        self._writer_task = asyncio.create_task(
            self._writer_loop(),
            name="message-cache-writer",
        )
        log.info(
            "[MESSAGE_CACHE] event=start status=ok conversations=%d "
            "messages=%d max_per_conversation=%d",
            len(self._messages),
            self.message_count,
            self.max_messages,
        )

    async def close(self) -> None:
        """Flush queued writes and stop the writer task."""
        if not self._started or self._closing:
            return

        self._closing = True
        await self._queue.put(_STOP)
        task = self._writer_task
        if task is not None:
            await asyncio.gather(task)
        self._writer_task = None
        self._started = False
        log.info(
            "[MESSAGE_CACHE] event=stop status=flushed messages=%d pending=%d",
            self.message_count,
            self._queue.qsize(),
        )

    async def add_message(
        self,
        msg,
        *,
        is_room: bool,
        joined_rooms: Mapping[str, Any] | set[str] | None = None,
    ) -> bool:
        """Add one incoming stanza to the shared cache.

        Returns True when a new entry was accepted and False for empty,
        duplicate, or unresolvable messages.
        """
        try:
            body = str(msg.get("body") or "").strip()
            message_type = str(msg.get("type") or "unknown")
        except Exception:
            return False
        if not body:
            return False

        conversation = conversation_key(
            msg,
            is_room=is_room,
            joined_rooms=joined_rooms,
        )
        if not conversation:
            return False

        entry = {
            "cache_key": uuid.uuid4().hex,
            "conversation": conversation,
            "stanza_id": get_stanza_id(msg),
            "nick": _safe_sender_nick(msg, is_room),
            "sender_jid": _safe_sender_jid(msg),
            "body": body,
            "message_type": message_type,
            "received_at": int(time.time()),
        }
        entry["ts"] = entry["received_at"]
        return await self.add_entry(entry)

    async def add_entry(self, entry: Mapping[str, Any]) -> bool:
        """Add an already-normalized entry and queue persistence."""
        async with self._mutation_lock:
            if self._closing:
                return False

            conversation = str(entry.get("conversation") or "").strip()
            body = str(entry.get("body") or "").strip()
            if not conversation or not body:
                return False

            stanza_id = entry.get("stanza_id")
            if stanza_id:
                stanza_id = str(stanza_id)
                if stanza_id in self._by_stanza_id.get(conversation, {}):
                    return False

            normalized = {
                "cache_key": str(entry.get("cache_key") or uuid.uuid4().hex),
                "conversation": conversation,
                "stanza_id": stanza_id,
                "nick": entry.get("nick"),
                "sender_jid": entry.get("sender_jid"),
                "body": body,
                "message_type": str(entry.get("message_type") or "unknown"),
                "received_at": int(entry.get("received_at") or time.time()),
            }
            normalized["ts"] = normalized["received_at"]
            self._append_to_memory(normalized)

            if self._started:
                self._queue.put_nowait(dict(normalized))
            return True

    def _append_to_memory(self, entry: dict[str, Any]) -> None:
        conversation = str(entry["conversation"])
        messages = self._messages.setdefault(conversation, deque())
        index = self._by_stanza_id.setdefault(conversation, {})

        if len(messages) >= self.max_messages:
            evicted = messages.popleft()
            evicted_id = evicted.get("stanza_id")
            if evicted_id and index.get(str(evicted_id)) is evicted:
                index.pop(str(evicted_id), None)

        messages.append(entry)
        stanza_id = entry.get("stanza_id")
        if stanza_id:
            index[str(stanza_id)] = entry

    async def _writer_loop(self) -> None:
        while True:
            first = await self._queue.get()
            if first is _STOP:
                self._queue.task_done()
                return

            batch = [first]
            stop_after_batch = False
            await asyncio.sleep(_BATCH_DELAY_SECONDS)
            while True:
                try:
                    item = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if item is _STOP:
                    stop_after_batch = True
                    self._queue.task_done()
                    break
                batch.append(item)

            await self._persist_with_retry(batch)
            pending_items = len(batch)
            while pending_items > 0:
                self._queue.task_done()
                pending_items -= 1
            if stop_after_batch:
                return

    async def _persist_with_retry(self, batch: list[object]) -> None:
        entries = [entry for entry in batch if isinstance(entry, Mapping)]
        if not entries or self._store is None:
            return

        for attempt in range(3):
            try:
                await self._store.save_batch(
                    entries,
                    limit_per_conversation=self.max_messages,
                )
                return
            except Exception:
                if attempt == 2:
                    log.exception(
                        "[MESSAGE_CACHE] event=persist status=failed "
                        "entries=%d",
                        len(entries),
                    )
                    return
                await asyncio.sleep(0.25 * (2**attempt))

    def get_messages(
        self,
        conversation: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return retained entries in oldest-to-newest order."""
        messages = list(self._messages.get(str(conversation), ()))
        if limit is not None:
            requested = max(0, int(limit))
            if requested == 0:
                return []
            messages = messages[-requested:]
        return [dict(entry) for entry in messages]

    def get_by_id(self, conversation: str, stanza_id: str) -> dict[str, Any] | None:
        """Return one cached message by conversation and stanza ID."""
        entry = self._by_stanza_id.get(str(conversation), {}).get(str(stanza_id))
        return dict(entry) if entry else None

    def get_last(
        self,
        conversation: str,
        *,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
        exclude_stanza_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the newest entry matching optional filters."""
        for entry in reversed(self._messages.get(str(conversation), ())):
            if exclude_stanza_id and entry.get("stanza_id") == exclude_stanza_id:
                continue
            if predicate is not None and not predicate(entry):
                continue
            return dict(entry)
        return None

    async def clear_conversation(self, conversation: str) -> int:
        """Remove one conversation from RAM and persistent storage."""
        async with self._mutation_lock:
            if self._started:
                await self._queue.join()

            key = str(conversation)
            removed = len(self._messages.pop(key, ()))
            self._by_stanza_id.pop(key, None)
            if self._store is not None:
                with suppress(Exception):
                    await self._store.clear_conversation(key)
            return removed

    @property
    def message_count(self) -> int:
        """Return the total number of retained in-memory messages."""
        return sum(len(messages) for messages in self._messages.values())

    def stats(self, conversation: str | None = None) -> dict[str, int | bool]:
        """Return small runtime counters for diagnostics."""
        if conversation is not None:
            count = len(self._messages.get(str(conversation), ()))
            conversations = 1 if count else 0
        else:
            count = self.message_count
            conversations = len(self._messages)
        return {
            "conversations": conversations,
            "messages": count,
            "max_per_conversation": self.max_messages,
            "pending_writes": self._queue.qsize(),
            "persistent": self._store is not None,
        }
