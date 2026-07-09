"""Shared message/stanza cache helpers."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Any

log = logging.getLogger(__name__)

_SHARED_MESSAGE_CACHES: dict[str, dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=10)))
_SHARED_PROCESSED_STANZAS: dict[str, set[str]] = defaultdict(set)
_SHARED_PROCESSED_STANZA_ORDER: dict[str, deque] = defaultdict(lambda: deque(maxlen=10000))


def paginate_items(items: list[Any], page: int, page_size: int):
    """Paginate a list and clamp page into a valid range."""
    total = len(items)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end], page, total_pages, total


def get_stanza_id(msg) -> str | None:
    """Extract a stable message id from a stanza."""
    try:
        stanza_id = msg.get("stanza_id")
        if stanza_id:
            value = stanza_id.get("id")
            if value:
                return str(value)
    except Exception as exc:
        log.debug("[CORE] Could not read stanza_id: %s", exc)
    try:
        msg_id = msg.get("id")
        if msg_id:
            return str(msg_id)
    except Exception as exc:
        log.debug("[CORE] Could not read message id: %s", exc)
    return None


def remember_stanza(namespace: str, stanza_id: str | None) -> bool:
    """Return False if stanza was already processed in this namespace."""
    if not stanza_id:
        return True
    processed = _SHARED_PROCESSED_STANZAS[namespace]
    order = _SHARED_PROCESSED_STANZA_ORDER[namespace]
    if stanza_id in processed:
        return False
    if len(order) == order.maxlen:
        old = order.popleft()
        processed.discard(old)
    processed.add(stanza_id)
    order.append(stanza_id)
    return True


def get_reply_target(msg) -> str | None:
    """Get the ID of the message this is a reply to."""
    try:
        if "reply" in msg:
            reply = msg.get("reply")
            if reply:
                value = reply.get("id")
                if value:
                    return str(value)
    except Exception as exc:
        log.debug("[CORE] Could not read reply target: %s", exc)
    return None


def extract_reply_quote(body: str) -> str | None:
    """Extract the original message from a reply quote."""
    if not body:
        return None
    lines = body.strip().splitlines()
    quoted_lines = []
    for line in lines:
        if line.startswith(">"):
            quoted_lines.append(line[2:] if len(line) > 1 else "")
        else:
            break
    text = "\n".join(quoted_lines).strip()
    return text or None


def cache_message(namespace: str, room: str, nick: str | None, body: str, stanza_id: str | None, *, maxlen: int = 10, extra: dict[str, Any] | None = None):
    """Add a message to the shared cache for a namespace/room."""
    room_cache = _SHARED_MESSAGE_CACHES[namespace]
    if room not in room_cache or room_cache[room].maxlen != maxlen:
        room_cache[room] = deque(room_cache.get(room, []), maxlen=maxlen)
    entry = {"nick": nick, "body": body, "stanza_id": stanza_id}
    if extra:
        entry.update(extra)
    room_cache[room].append(entry)


def get_cached_messages(namespace: str, room: str) -> list[dict[str, Any]]:
    """Return cached messages for a namespace/room."""
    return list(_SHARED_MESSAGE_CACHES[namespace][room])


def get_last_cached_message(namespace: str, room: str) -> dict[str, Any] | None:
    """Return the last cached message entry for a namespace/room."""
    cache = _SHARED_MESSAGE_CACHES[namespace][room]
    if not cache:
        return None
    return cache[-1]


def get_cached_message_by_id(namespace: str, room: str, msg_id: str) -> dict[str, Any] | None:
    """Return a cached message entry by stanza_id for a namespace/room."""
    cache = _SHARED_MESSAGE_CACHES[namespace][room]
    if not cache:
        return None
    for entry in cache:
        if entry.get("stanza_id") == msg_id:
            return entry
    return None
